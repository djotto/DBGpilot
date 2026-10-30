"""The plain health endpoint must translate RPC failures into HTTP failures."""

import json

import pytest

from dbgpilot import ConnectionClosed, RemoteError, Server
from .test_server import request


FAILURES = [
    pytest.param(
        ConnectionClosed("Server unavailable"), 503,
        {"code": -32006, "message": "Server unavailable",
         "data": {"type": "ConnectionClosed", "message": "Server unavailable"}},
        id="unavailable",
    ),
    pytest.param(
        RuntimeError("Private implementation detail"), 500,
        {"code": -32603, "message": "Internal server error", "data": {"type": "InternalError"}},
        id="unexpected-error",
    ),
    pytest.param(
        RemoteError(-32099, "Health could not be collected", {"type": "HealthFailure", "detail": "test"}),
        500,
        {"code": -32099, "message": "Health could not be collected",
         "data": {"type": "HealthFailure", "detail": "test"}},
        id="structured-error",
    ),
]


@pytest.mark.parametrize("token", [None, "health-test-token"], ids=["loopback", "authenticated"])
async def test_health_success_returns_plain_data_and_http_200(token):
    async with Server(port=0, xdebug_port=0, token=token) as server:
        headers = {"Authorization": "Bearer " + token} if token else None
        status, body = await request(server.url, path="/health", method="GET", headers=headers)
        assert status == 200
        assert body["status"] == "ok" and body["protocol"] == "dbgpilot/1"
        assert body["instance_id"] == server.instance_id
        assert body["xdebug_port"] == server.controller.port
        assert body["live_sessions"] == 0
        assert not {"result", "error", "jsonrpc"}.intersection(body)
        if token:
            assert token not in json.dumps(body)


@pytest.mark.parametrize("failure,http_status,expected_error", FAILURES)
async def test_health_failure_uses_failure_status_and_preserves_error_details(
    monkeypatch, failure, http_status, expected_error,
):
    async with Server(port=0, xdebug_port=0) as server:
        def fail_health():
            raise failure

        monkeypatch.setattr(server, "health", fail_health)
        status, body = await request(server.url, path="/health", method="GET")
        assert status == http_status
        assert body["error"] == expected_error
        assert "result" not in body and "status" not in body


@pytest.mark.parametrize("failure,_health_status,expected_error", FAILURES)
async def test_rpc_health_errors_keep_http_200_and_structured_errors(
    monkeypatch, failure, _health_status, expected_error,
):
    async with Server(port=0, xdebug_port=0) as server:
        def fail_health():
            raise failure

        monkeypatch.setattr(server, "health", fail_health)
        payload = {"jsonrpc": "2.0", "id": "health-rpc-test", "method": "health"}
        status, body = await request(server.url, body=json.dumps(payload).encode())
        assert status == 200
        assert body == {"jsonrpc": "2.0", "id": "health-rpc-test", "error": expected_error}


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token"], ids=["missing", "incorrect"])
async def test_health_still_requires_authorization(authorization):
    async with Server(port=0, xdebug_port=0, token="health-test-token") as server:
        headers = {"Authorization": authorization} if authorization else None
        status, body = await request(server.url, path="/health", method="GET", headers=headers)
        assert status == 401
        assert body["error"]["code"] == -32009
