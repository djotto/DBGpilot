# Persistent server and script clients

The server owns one `Controller` and all of its PHP sessions. Scripts own HTTP
clients and session IDs; disconnecting a client does not resume, detach, or stop
PHP. Closing a Python client now cancels its outstanding RPCs without advancing
PHP. The runtime still has no third-party dependencies. Playwright is installed
as a development dependency and is not required to run the packaged server.

## Start and connect

```sh
# First terminal, inside the included DDEV environment:
ddev poetry install
ddev poetry run dbgpilot serve
# Equivalent module entry point:
ddev poetry run python -m dbgpilot serve

# Another terminal:
ddev poetry run dbgpilot call health
ddev poetry run python scripts/check_server_harness.py
```

The first stdout line is a JSON `ready` event with the process ID, API URL,
protocol version (`dbgpilot/1`), and Xdebug listening address. Startup errors go
to stderr and exit nonzero. SIGINT/SIGTERM stop accepting API calls, release
waiters, and close owned sessions. Paused sessions attempt a bounded detach;
running sessions close their debugging transport.

API defaults: `127.0.0.1:9004`. Xdebug defaults: `127.0.0.1:9003`.
`--host`, `--port`, `--xdebug-host`, and `--xdebug-port` configure them separately;
port zero chooses an available port. The test harness points Xdebug at localhost
inside the container, so run the server there. These ports are not automatically
published to the host. API clients in another container/host need deliberate
network routing and a reachable API address; PHP also needs the right Xdebug
client address. Breakpoint files can use the PHP server's explicit URIs or local
paths translated through configured directory roots. `--config`, `--no-config`,
and repeatable `--path-map LOCAL REMOTE` configure mappings. The CLI discovers
the nearest project `dbgpilot.toml`; see [path mapping](path-mapping.md), including
the local namespace when the server runs inside a container.

`--proxy-host HOST --proxy-port 9001 --idekey KEY` registers the listener through
a DBGp proxy before readiness. `--proxy-listen-port` overrides its advertised
port. The server unregisters owned keys on shutdown; PHP must be configured to
connect to the proxy's separate engine port. See the
[proxy, stdin, and shell guide](proxies-and-shells.md) for setup and limitations.

An optional bearer token can be configured with `DBGPILOT_TOKEN` or `--token`.
Pass the same token to `Client(..., token=...)` or the CLI. Listening beyond
loopback requires a token. HTTP is intended for local/trusted transports; use
tunneling for remote connections. The API accepts JSON from script clients,
does not enable CORS, and rejects browser-origin requests. Playwright's Python
client or server-side `fetch` can call it; page JavaScript is not the API client.

## Python workflow

```python
import asyncio
import json
from dbgpilot import Client

async def debug_checkout(page):
    navigation = None
    session_id = None
    try:
        async with Client() as first:
            await first.health()
            navigation = asyncio.create_task(page.goto(
                "http://127.0.0.1/?code=SAVE10&XDEBUG_TRIGGER=1",
                timeout=60_000,
            ))
            session = await first.wait_for_session(timeout=10)
            session_id = session.id
            await session.set_breakpoint("/var/www/html/src/checkout.php", 11)
            snapshot = await session.break_and_return(
                ["$subtotal", "$discount"], timeout=10,
            )
            assert snapshot["variables"]["$discount"]["value"] == 10
            assert not navigation.done()
            print(json.dumps(snapshot), flush=True)

        # This can instead happen in a later script/tool call using session_id.
        async with Client() as later:
            session = later.session(session_id)
            assert (await session.info())["state"] == "break"
            assert await session.set_value("$discount", 15)
            await session.step_over()
            assert (await session.property_get("$total"))["value"] == 85
            await session.detach()

        await navigation
        assert await page.get_by_test_id("total").inner_text() == "£85"
        return snapshot
    finally:
        if session_id is not None:
            async with Client() as cleanup:
                await cleanup.session(session_id).close()
        if navigation is not None:
            await asyncio.gather(navigation, return_exceptions=True)
```

For coordinated routing, unique session matching, action failure handling, and
cleanup, use the reusable [PlaywrightDebugger helper](playwright.md). The manual
example above demonstrates the underlying API and uses a finite browser timeout;
the helper's `goto()` disables the navigation deadline by default so PHP can
remain paused for longer interactive investigations.

Run this with a Python Playwright page in the same network environment as the
example. The caller owns the browser and its lifetime. DBGpilot keeps PHP
debugging alive across script calls; it does not keep a browser or an asyncio
task alive after its owning process exits. A browser action waiting on PHP must
run concurrently with debugger control. Only explicit control commands advance
PHP; returning snapshots or closing a `Client` does not.

`Client` is async and opens one HTTP connection per call over asyncio streams.
Long polls do not occupy Python worker threads. `RemoteSession` provides the common methods shown above,
plus stepping, stop, events, and cleanup. Use
`await session.call("stack", depth=1)` for other exposed controller methods.
Client results are JSON dictionaries/lists/scalars, rather than the controller's
dataclasses. Binary results use `{"encoding":"base64","data":"..."}`.
Python `bytes` arguments to assignment methods are encoded automatically.

## Selecting and reconnecting to sessions

`wait_for_session(idekey=None, cookie=None, appid=None, file=None, timeout=30)`
returns and claims the next matching, unclaimed, open session. Filters are exact
matches against init metadata; local file filters are first translated to engine
URIs. A waiter for one IDE key does not consume requests
for another key. Concurrent waiters claim distinct sessions. Arrange distinct
IDE keys/cookies in PHP/Xdebug when multiple scripts debug the same site; an
unfiltered waiter intentionally accepts any matching request.

Use `session.id` to reconnect with `client.session(id)`. This makes a local
handle; `await session.info()` verifies that it still exists. `sessions()` lists
known sessions, including claimed and recently closed sessions. `errors()`
returns the latest 50 rejected-handshake errors for diagnosing failed attachment.

IDs are UUIDs scoped to the running server, not durable database IDs. Restarting
the server loses them. There is no automatic idle timeout that unexpectedly
resumes a paused request. Explicit cleanup methods are:

- `detach()`: let PHP finish its request.
- `stop()`: terminate PHP execution.
- `close()`: attempt detach where supported/paused, then close the transport.
- `forget()`: remove a closed session's metadata/events; rejects live sessions.

Closed-session history retains the latest 128 closures by default; live sessions
are not evicted by that limit. Old/forgotten IDs return `UnknownSession`.
Programmatic `Server(max_closed_sessions=..., event_history=...)` configures
history. `Server(controller=...)` takes ownership of that controller and its
session/event consumption; do not consume its ready queue from another owner.

## Operations, timeouts, and disconnections

Ordinary session operations are serialized with a per-session guard. An
overlapping operation receives `SessionStateError` rather than waiting behind a
running PHP request. Read-only server metadata and event polling remain available;
`interrupt()` and `status` bypass that guard when the engine supports asynchronous
commands; the controller still checks engine support and state.
`stdin`, `set_stdin`, and `send_stdin` use a separate input guard so input can
reach a waiting execution RPC. The engine must advertise stdin and either async
support or an active stdin-read notification. Configuration still requires async
support while running. `interact`, `expr`, and `exec` use the ordinary execution
guard/deadline. Spawnpoint operations use the ordinary command deadline and
remain guarded against overlapping execution.
Explicit `close()` can release an outstanding operation. Separate sessions remain
independent.

`break_and_return(variables=[], expressions=[], depth=0, context=0, timeout=30)`
runs to the next breakpoint and snapshots it under one guard. Reaching completion
first returns `ExecutionFinished`. Snapshot expressions can execute PHP and have
side effects. Use `run_until_break()` followed by `snapshot()` for separate calls.

Server-side wait/execution timeouts default to 30 seconds, accept zero, and are
bounded by `Server(max_wait=300)`. The overall RPC deadline is `max_wait + 5`.
Other controller commands retain their own five-second default deadlines.
Unlike direct controller execution methods, the remote API requires finite
timeouts. `session.events` returns an empty batch when its wait deadline expires;
`wait_for_session` and execution deadlines return a structured timeout error.

A timeout does not interrupt PHP. Late stops still update session state and
appear in the event feed. Inspect `session.info()` and events before deciding
what to do next. Cancelling an RPC does not undo engine commands already sent:
evaluation or execution can continue until its actual response. Repeating an
evaluation, mutation, or continuation after a lost response can repeat side
effects; requests are not automatically retried or deduplicated.

### Explicit remote cancellation

```python
from dbgpilot import RemoteError

pending = client.request("wait_for_session", idekey="my-request", timeout=60)
print(pending.id)                 # also available to another client/process
ack = await pending.cancel()      # or await client.cancel_request(pending.id)
try:
    await pending                 # awaitable handle, or await pending.result()
except RemoteError as error:
    assert error.code == -32010
```

`session.request("run", timeout=60)` creates the same handle for a session
operation. `cancel_request` acknowledges `cancelled` (an active RPC was
cancelled) and `submission_blocked` (a delayed request with this ID is blocked).
A cancelled pending session waiter cannot claim future connections. Cancellation
also releases event polls without consuming events. A cancelled run/evaluation
does not send resume, detach, or stop; its later engine response still updates
the session and event feed.

Cancelling a Python `Client.call()` coroutine sends a best-effort remote
cancellation with a two-second cleanup deadline. Transport/protocol failures
attempt the same cleanup. `Client.aclose()` cancels outstanding calls but leaves
PHP sessions owned by the server. For explicit confirmation, use the handle or
`cancel_request`. The HTTP server also cancels a pending RPC when it observes
socket EOF/reset, so a lost waiter cannot claim a future session after that
cancellation. Keep the connection's writing side open until the response: a TCP
write half-close is treated as abandonment. An already committed session claim
or command cannot be rolled back; recover through `sessions()` and metadata.
Cancellation of an execution RPC leaves its engine operation pending until its
actual reply, without sending stop, detach, or resume.

Cancellation can arrive before submission. The server retains up to 1024
cancelled-ID tombstones for `max_wait + 5` seconds. Use unique IDs and do not reuse
cancelled IDs during that window. If multiple active requests use the same ID,
cancellation is rejected as ambiguous. A request cannot cancel itself. Completed
claims cannot be rolled back: if completion beats cancellation, recover the
session ID through `sessions()`. The cancellation mechanism does not roll back
side effects or automatically retry work.

The client defaults to a 35-second HTTP timeout and raises it to accommodate an
explicit longer remote wait. `Client(timeout=..., max_response_bytes=...)`
configures transport limits. Server request bodies default to 1 MiB; malformed
requests do not affect PHP sessions. Session event history defaults to 1024
events per session. These limits are counts/packet limits, not a guarantee about
the total memory required for large application values.

`Server(max_http_connections=128)` bounds admitted HTTP connections/workers,
including partial requests. Excess connections close before a worker is created;
shutdown closes accepted sockets. Pass a configured `Controller(max_sessions=256,
max_pending_commands=1024, error_queue_size=50)` to `Server(controller=...)` to
change engine admission, unanswered-command, and diagnostic retention limits.
Live sessions are preserved at capacity. Concurrent start calls create one
listener per owner. See the [review record](protocol-review.md) for verified
failure paths and remaining boundaries.

## Event feed

```python
batch = await session.events(after=0, timeout=30, limit=100)
for event in batch["events"]:
    print(event["sequence"], event["type"], event["data"])
cursor = batch["cursor"]
# Save cursor for the next call, possibly from another process.
batch = await session.events(after=cursor, timeout=30)
```

Events have monotonically increasing, session-local sequence numbers. Polling
does not consume another client's history. Responses include `cursor`, `closed`,
and `oldest_cursor`; the closing event is retained before `closed` becomes true
in the feed. A cursor older than retained history returns `EventHistoryLost`
with recovery cursors, rather than silently skipping events. Limits are 1–1000
events per response. A cursor ahead of the session is rejected.

The server continuously drains the controller's event queue, even when clients
are disconnected. Long-polling provides server-to-script event delivery over
HTTP; WebSockets or browser extensions are not required. Keep the cursor with
your session ID if reconnecting clients need prior stream/notification data.

Interactive responses emit `InteractiveEvent` with status, `more`, and prompt;
proxy error packets emit `ProxyErrorEvent` with the structured error. Session
metadata includes `interaction`, `stdin_redirected`, and `stdin_waiting`, so
reconnecting clients can recover the latest observed shell/input state.

## JSON-RPC and CLI

`POST /rpc`, `Content-Type: application/json`:

```json
{"jsonrpc":"2.0","id":"request-uuid","method":"session.snapshot","params":{"session_id":"session-uuid","variables":["$subtotal","$discount"]}}
```

Success: `{"jsonrpc":"2.0","id":"request-uuid","result":...}`.
Failure: `{"jsonrpc":"2.0","id":"request-uuid","error":{"code":...,"message":"...","data":...}}`.
Request IDs must be strings or integers; JSON-RPC batches and no-ID
notifications are not implemented. Use unique request IDs for correlation.
HTTP application responses use status 200, including structured debugging
errors; malformed JSON, authorization, and request framing use HTTP errors.
`GET /health` returns a plain health object.

Global methods: `health`, `sessions`, `errors`, `wait_for_session`,
`cancel_request(request_id=...)`, `proxy.register`, `proxy.unregister`, and
`proxy.registrations`. Registration takes `idekey`, optional `host`, `port`,
`listen_port`, `multiple_sessions`, and `timeout`; unregister takes `idekey`,
optional `host`, `port`, and `timeout`. Health includes owned registrations as
`proxies`. Python `Client` provides matching convenience methods.
`paths.mappings` lists configured directory roots; `paths.to_remote(path=...)`
and `paths.to_local(path=...)` translate explicitly. Health/readiness include
`path_mappings`. File-bearing results/events retain engine `file` URIs and add
`local_file` and `path_mapping_error` for local navigation and diagnostics.
Session methods require `session_id`:

```text
info events close forget break_and_return
status stack_depth typemap_get stack contexts context
property_get property_children property_value property_value_info
property_set set_value evaluate expr exec source set_output
set_breakpoint get_breakpoint breakpoints update_breakpoint remove_breakpoint
set_spawnpoint get_spawnpoint spawnpoints update_spawnpoint remove_spawnpoint
feature_get feature_set refresh_capabilities
run resume run_until_break step_into step_over step_out interrupt detach stop snapshot
stdin set_stdin send_stdin interact
```

Names are prefixed with `session.`, and parameters otherwise follow the
[controller API](api.md). Only this explicit allowlist is exposed. `interrupt`
returns `{"success":true/false}`; byte-returning methods use base64 envelopes.
`RemoteError` exposes `code`, `message`, and `data`, including engine error code,
command, XML, and attributes where present.
Termination results include `response_received`; a false value indicates a clean
EOF rather than an engine acknowledgement, including proxy detach compatibility.
`expr` returns a property dictionary or null on `success=0`; `exec` returns a
boolean. Spawnpoint methods return dictionaries/arrays, or null for update/remove.
`session.info` includes the observed `spawnpoints` inventory. See
[optional commands](optional-commands.md) for arguments and capability limits.

| Code | Meaning |
| --- | --- |
| -32700 | Invalid JSON |
| -32600 | Invalid RPC request |
| -32601 | Unknown method |
| -32602 | Invalid parameters |
| -32603 | Internal server error |
| -32001 | Unknown/expired session |
| -32002 | Session state or concurrent-operation conflict |
| -32003 | Server-side timeout |
| -32004 | Engine command error |
| -32005 | DBGp protocol error |
| -32006 | Closed connection/server |
| -32007 | Execution finished before reaching a breakpoint |
| -32008 | Event history expired |
| -32009 | Authorization/Host/origin rejection |
| -32010 | Request cancelled / delayed submission blocked |
| -32011 | Proxy error (opaque proxy code in error data) |
| -32012 | Unmapped or ambiguous path (path/direction/reason in error data) |

CLI results are JSON on stdout; errors are JSON on stderr with nonzero exit.
Parameters may be a JSON object, `@filename`, or `-` to read stdin. `--session`
adds `session_id`, avoiding repeated JSON editing:

```sh
dbgpilot call sessions
dbgpilot call session.info --session SESSION_ID
dbgpilot call session.snapshot --session SESSION_ID --params @snapshot.json
dbgpilot call session.detach --session SESSION_ID
```

For JavaScript/TypeScript Playwright scripts, the same protocol works with fetch:

```javascript
async function rpc(method, params = {}) {
  const response = await fetch("http://127.0.0.1:9004/rpc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: crypto.randomUUID(), method, params }),
  });
  const message = await response.json();
  if (message.error) throw new Error(JSON.stringify(message.error));
  return message.result;
}
```

This fetch runs in the script process, not through `page.evaluate()`.
