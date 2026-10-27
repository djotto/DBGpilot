"""Run outside the checkout using a freshly installed distribution and stdlib."""

import asyncio
import importlib.metadata
import importlib.resources
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

import dbgpilot
from dbgpilot import Client, DebuggerSetup

NAMESPACE = "urn:debugger_protocol_v1"


def installation():
    distribution = importlib.metadata.distribution("dbgpilot")
    assert Path(dbgpilot.__file__).is_relative_to(Path(sys.prefix))
    assert dbgpilot.__version__ == distribution.version
    assert not distribution.requires
    assert importlib.util.find_spec("pytest") is None
    assert importlib.util.find_spec("playwright") is None
    assert importlib.resources.files("dbgpilot").joinpath("py.typed").is_file()
    assert all(hasattr(dbgpilot, name) for name in dbgpilot.__all__)
    files = distribution.files or []
    for name in ("LICENSE", "NOTICE.md"):
        matches = [item for item in files if item.name == name and ".dist-info" in str(item)]
        assert len(matches) == 1, f"Missing packaged {name}"
        assert distribution.locate_file(matches[0]).read_text()
    entry = Path(sys.executable).with_name("dbgpilot.exe" if os.name == "nt" else "dbgpilot")
    for command in ([sys.executable, "-m", "dbgpilot", "--version"], [str(entry), "--version"]):
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=5)
        assert result.stdout.strip() == f"dbgpilot {distribution.version}"
    return distribution.version, entry


def node(tag, **attributes):
    return ET.Element(f"{{{NAMESPACE}}}{tag}", {key: str(value) for key, value in attributes.items()})


async def send(writer, element):
    data = ET.tostring(element, encoding="utf-8")
    writer.write(str(len(data)).encode() + b"\0" + data + b"\0")
    await writer.drain()


async def peer(reader, writer):
    """A small scripted engine verifies the installed TCP/HTTP path, not PHP."""
    try:
        while True:
            parts = shlex.split((await reader.readuntil(b"\0"))[:-1].decode())
            command = parts[0]
            options = dict(zip(parts[1::2], parts[2::2]))
            reply = node("response", command=command, transaction_id=options["-i"])
            if command == "feature_get":
                reply.set("supported", "1")
                reply.text = {"encoding": "UTF-8", "supports_async": "0", "supports_postmortem": "0",
                              "breakpoint_types": "line conditional call return exception"}.get(options["-n"], "1")
            elif command == "feature_set":
                reply.set("success", "1")
            elif command == "breakpoint_set":
                reply.attrib.update(id="probe-breakpoint", state="enabled")
            elif command == "run":
                reply.attrib.update(status="break", reason="ok")
            elif command == "stack_get":
                reply.append(node("stack", level=0, filename="file:///release/probe.php", lineno=1, where="probe"))
            elif command == "property_get":
                prop = node("property", name=options["-n"], fullname=options["-n"], type="int")
                prop.text = "42"
                reply.append(prop)
            elif command == "detach":
                reply.attrib.update(status="stopped", reason="ok")
                await send(writer, reply)
                return
            else:
                raise AssertionError(f"Unexpected probe command {command}")
            await send(writer, reply)
    finally:
        writer.close()
        await writer.wait_closed()


async def roundtrip(version, entry):
    token = uuid.uuid4().hex
    setup = DebuggerSetup(launch=True, port=0, xdebug_port=0, token=token)
    engine = None
    try:
        async with setup, asyncio.timeout(20):
            health = await setup.health()
            assert health["protocol"] == "dbgpilot/1" and health["version"] == version
            env = dict(os.environ, DBGPILOT_TOKEN=token)
            cli = await asyncio.create_subprocess_exec(
                str(entry), "call", "health", "--url", setup.url, "--no-config", env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await cli.communicate()
            assert cli.returncode == 0, stderr.decode()
            assert json.loads(stdout)["version"] == version
            reader, writer = await asyncio.open_connection(health["xdebug_host"], health["xdebug_port"])
            engine = asyncio.create_task(peer(reader, writer))
            await send(writer, node("init", appid="release-probe", language="PHP", protocol_version="1.0",
                                    idekey="release-probe", fileuri="file:///release/probe.php"))
            remote = await setup.client.wait_for_session(idekey="release-probe", timeout=5)
            await remote.set_breakpoint("file:///release/probe.php", 1)
            snapshot = await remote.break_and_return(["$number"], timeout=5)
            assert snapshot["variables"]["$number"]["value"] == 42
            await setup.client.aclose()
            async with Client(setup.url, token=token) as later:
                assert (await later.session(remote.id).info())["state"] == "break"
                assert (await later.session(remote.id).property_get("$number"))["value"] == 42
                await later.session(remote.id).detach()
            await engine
    finally:
        if engine is not None and not engine.done():
            engine.cancel()
            await asyncio.gather(engine, return_exceptions=True)
        if setup.owns_server:
            await setup.shutdown(release_sessions=True)


if __name__ == "__main__":
    version, entry = installation()
    asyncio.run(roundtrip(version, entry))
    print(json.dumps({"version": version, "python": sys.version, "protocol": "dbgpilot/1",
                      "runtime_dependencies": [], "pytest_playwright_absent": True,
                      "http_tcp_roundtrip": True, "snapshot": 42, "reconnect": True}))
