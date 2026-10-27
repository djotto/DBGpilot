"""The persistent server and a JSON command-line client."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys

from .client import Client
from .server import Server
from .errors import DBGpilotError
from .wire import RemoteError, json_value
from .config import load_config
from ._version import __version__


def _settings(args):
    names = ("host", "port", "xdebug_host", "xdebug_port", "token") if args.command == "serve" else ("url", "token", "request_timeout")
    overrides = {name: getattr(args, name) for name in names if getattr(args, name) is not None}
    if "token" not in overrides and "DBGPILOT_TOKEN" in os.environ:
        overrides["token"] = os.environ["DBGPILOT_TOKEN"]
    return load_config(False if args.no_config else args.config, discover=not args.no_config, **overrides)


async def _serve(args):
    settings = _settings(args)
    mapper = settings.path_mapper
    mapper = mapper.with_overrides([
        {"local": local, "remote": remote} for local, remote in args.path_map
    ])
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stopped.set)
            installed.append(signum)
        except NotImplementedError:
            pass
    try:
        async with Server(settings.host, settings.port, xdebug_host=settings.xdebug_host,
                          xdebug_port=settings.xdebug_port, token=settings.token,
                          proxy_host=args.proxy_host, proxy_port=args.proxy_port,
                          idekey=args.idekey, proxy_listen_port=args.proxy_listen_port,
                          path_mappings=mapper) as server:
            print(json.dumps({"event": "ready", "pid": os.getpid(), **server.health()}), flush=True)
            await stopped.wait()
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)


async def _call(args):
    settings = _settings(args)
    raw = args.params
    if raw == "-":
        raw = sys.stdin.read()
    elif raw.startswith("@"):
        raw = Path(raw[1:]).read_text()
    params = json.loads(raw)
    if not isinstance(params, dict):
        raise ValueError("--params must contain a JSON object")
    if args.session is not None:
        params["session_id"] = args.session
    async with Client(settings.url, token=settings.token, timeout=settings.request_timeout) as client:
        result = await client.call(args.method, **params)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dbgpilot")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Keep a controller and PHP sessions alive")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--xdebug-host")
    serve.add_argument("--xdebug-port", type=int)
    serve.add_argument("--token")
    serve.add_argument("--proxy-host")
    serve.add_argument("--proxy-port", type=int, default=9001)
    serve.add_argument("--proxy-listen-port", type=int)
    serve.add_argument("--idekey")
    config = serve.add_mutually_exclusive_group()
    config.add_argument("--config", type=Path, help="Read project settings from this TOML file")
    config.add_argument("--no-config", action="store_true", help="Disable project configuration discovery")
    serve.add_argument("--path-map", nargs=2, action="append", default=[], metavar=("LOCAL", "REMOTE"),
                       help="Map a local directory to an engine file URI; repeat for multiple roots")
    call = commands.add_parser("call", help="Send a JSON-RPC command and print its result")
    call.add_argument("method")
    call.add_argument("--url")
    call.add_argument("--token")
    call.add_argument("--timeout", dest="request_timeout", type=float, help="HTTP transport timeout in seconds")
    call_config = call.add_mutually_exclusive_group()
    call_config.add_argument("--config", type=Path)
    call_config.add_argument("--no-config", action="store_true")
    call.add_argument("--params", default="{}", help="JSON, @filename, or - for stdin")
    call.add_argument("--session", help="Add session_id to the parameters")
    args = parser.parse_args(argv)
    try:
        asyncio.run(_serve(args) if args.command == "serve" else _call(args))
    except RemoteError as error:
        print(json.dumps({"error": error.to_dict()}), file=sys.stderr)
        return 1
    except DBGpilotError as error:
        print(json.dumps({"error": json_value(error)}), file=sys.stderr)
        return 1
    except (OSError, ValueError, TimeoutError) as error:
        print(json.dumps({"error": {"type": type(error).__name__, "message": str(error)}}), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
