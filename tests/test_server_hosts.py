"""Listener authorization and real HTTP connectivity with controlled DNS replies."""

import errno
import socket

import pytest

from dbgpilot import Client, RemoteError, Server


def forbid_resolution(*args, **kwargs):
    raise AssertionError("Listener authorization must not perform DNS resolution")


@pytest.fixture
def host_resolution(monkeypatch):
    original = socket.getaddrinfo
    addresses = {}

    def resolve(host, port, family=0, type=0, proto=0, flags=0):
        if host in addresses:
            host = addresses[host]
            if host is None:
                raise socket.gaierror(socket.EAI_NONAME, "Test hostname does not resolve")
        return original(host, port, family, type, proto, flags)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    return addresses


def require_ipv6(family):
    if family != socket.AF_INET6:
        return
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
    except OSError as error:
        if error.errno in {errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL, errno.EPROTONOSUPPORT}:
            pytest.skip("IPv6 loopback is unavailable on this host")
        raise


def test_hostname_with_token_is_accepted_without_resolving_in_constructor(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", forbid_resolution)
    server = Server(host="devbox.dbgpilot.test", token="test-token", port=0, xdebug_port=0)
    assert server.host == "devbox.dbgpilot.test"
    assert server.url == "http://devbox.dbgpilot.test:0"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.2", "::1"])
def test_explicit_loopback_hosts_do_not_require_token_or_dns(host, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", forbid_resolution)
    server = Server(host=host, port=0, xdebug_port=0)
    assert server.host == host and server.token is None


@pytest.mark.parametrize("host", [
    "0.0.0.0", "::", "192.0.2.1", "devbox.dbgpilot.test", "loopback-alias.dbgpilot.test",
])
@pytest.mark.parametrize("token", [None, ""], ids=["missing-token", "empty-token"])
def test_other_listener_hosts_require_token_without_dns(host, token, monkeypatch):
    # A hostname is subject to this rule even if DNS might resolve it to loopback.
    monkeypatch.setattr(socket, "getaddrinfo", forbid_resolution)
    with pytest.raises(ValueError, match="requires a token"):
        Server(host=host, token=token, port=0, xdebug_port=0)


@pytest.mark.parametrize("family,address", [
    (socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1"),
], ids=["ipv4", "ipv6"])
async def test_authorized_hostname_binds_resolved_family_and_serves_http(family, address, host_resolution):
    require_ipv6(family)
    hostname = "listener.dbgpilot.test"
    host_resolution[hostname] = address
    async with Server(host=hostname, token="test-token", port=0, xdebug_port=0) as server:
        assert server._http.socket.family == family
        assert server._http.socket.getsockname()[0] == address
        assert server.url == f"http://{hostname}:{server.port}"
        async with Client(server.url, token="test-token", timeout=2) as client:
            health = await client.health()
            assert health["status"] == "ok" and health["instance_id"] == server.instance_id
        async with Client(server.url, timeout=2) as unauthorized:
            with pytest.raises(RemoteError) as caught:
                await unauthorized.health()
            assert caught.value.code == -32009


@pytest.mark.parametrize("family,address", [
    (socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1"),
], ids=["ipv4-only", "ipv6-only"])
async def test_localhost_uses_resolved_family_and_remains_connectable(family, address, host_resolution):
    # localhost already passes constructor validation, isolating family selection.
    require_ipv6(family)
    host_resolution["localhost"] = address
    async with Server(host="localhost", port=0, xdebug_port=0) as server:
        assert server._http.socket.family == family
        assert server._http.socket.getsockname()[0] == address
        async with Client(server.url, timeout=2) as client:
            assert (await client.health())["status"] == "ok"


async def test_unresolvable_authorized_hostname_fails_at_startup_and_cleans_up(host_resolution):
    hostname = "missing.dbgpilot.test"
    host_resolution[hostname] = None
    server = Server(host=hostname, token="test-token", port=0, xdebug_port=0)
    try:
        with pytest.raises(socket.gaierror, match="Test hostname does not resolve"):
            await server.start()
        assert server.controller._closed.is_set()
    finally:
        await server.aclose()
