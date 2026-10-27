# DBGp proxies, stdin, and interactive shells

These APIs implement the optional workflows in the
[DBGp specification](https://xdebug.org/docs/dbgp). Command availability still
depends on the engine. The tested Xdebug supports proxy routing but advertises
neither `stdin` nor `interact`; those calls raise `SessionStateError` before
sending a command. Positive stdin/shell coverage uses scripted TCP engines.

## Proxy registration

A proxy routes engine connections by IDE key. Its control port (usually 9001)
accepts `proxyinit` and `proxystop` on separate short-lived connections. PHP
connects to the proxy's engine port (usually 9003), and the proxy connects back
to DBGpilot's listener. Keep those ports distinct when running locally.

Start the proxy separately, configure PHP's Xdebug client host/port to reach its
engine endpoint, then register DBGpilot:

```sh
dbgpilot serve --xdebug-port 9007 \
  --proxy-host 127.0.0.1 --proxy-port 9001 --idekey alice
```

The server registers its actual listener port before emitting `ready`. Both
`--proxy-host` and `--idekey` are required together. `--proxy-listen-port`
overrides the advertised port for explicit port forwarding. The proxy must be
able to connect back to that port at the address from which registration arrives;
registration does not establish a reverse tunnel or configure PHP.

The direct controller and remote client expose the same workflow:

```python
from dbgpilot import Controller, Client, ProxyClient

async with Controller(port=9007) as controller:
    registration = await controller.register_proxy(
        host="127.0.0.1", port=9001, idekey="alice",
        multiple_sessions=True,
    )
    session = await controller.wait_for_session(timeout=30)
    # Set breakpoints and debug normally.
    await session.detach()
    # Controller shutdown unregisters registrations it successfully owns.

async with Client() as client:
    registration = await client.register_proxy(idekey="bob")
    registrations = await client.proxy_registrations()
    await client.unregister_proxy(idekey="bob")

# Low-level use does not own a listener or automatically unregister:
proxy = ProxyClient(host="127.0.0.1", port=9001, timeout=5)
registration = await proxy.register(9007, "alice", multiple_sessions=True)
await proxy.unregister("alice")
```

`Controller.proxy_registrations` is a tuple of owned `ProxyRegistration` records;
the remote equivalent returns JSON. Records preserve the requested settings,
response address/port, attributes, and XML. Controller operations serialize
registration changes and reject duplicate owned keys. Successful unregister
removes ownership. Shutdown attempts bounded unregister operations; cleanup
failures are reported through `Controller.next_error()`.

A rejected registration is not owned and is never automatically unregistered.
If cancellation or timeout loses a registration acknowledgement, the proxy's
state is uncertain. Reconcile that key explicitly; an automatic `proxystop`
could remove an existing registration belonging to another client.

Control responses may be length-framed XML or bare XML, with or without a NUL
terminator. Reads are bounded by size and timeout. This is plain TCP DBGp proxy
support; TLS and Xdebug Cloud protocols are separate transports.

The official dbgpProxy 0.6.2 echoes the registered IDE endpoint in its response
address/port fields. Keep the separately configured proxy engine endpoint for
PHP rather than assuming these fields identify it. When using the Playwright
helper through a proxy, construct `PlaywrightDebugger(page, client, idekey="alice")`
with the registered key; a fresh
unregistered generated key cannot be routed.

## Proxy errors and terminal replies

`ProxyError` preserves `command`, opaque string `code`, `message`, `attributes`,
and XML. It is separate from numeric engine `CommandError`. Registration failures
raise it directly; an initial `proxyerror` reaches `Controller.next_error()`
without disabling the listener. During an established session, the same packet
emits `ProxyErrorEvent(error)` without consuming an unrelated engine response.

Official dbgpProxy 0.6.2 closes the routed connection without forwarding a final
response whose status is `stopped`. DBGpilot accepts clean EOF after a written
detach for sessions with proxied init metadata or an IDE key owned by its proxy
registration. For separately managed routing, opt in with
`Controller(allow_detach_eof=True)`. Direct sessions otherwise require a detach
reply. Truncated packets and socket errors still fail.

`ExecutionResult.response_received` is `False` when termination was inferred
from clean EOF, including the existing stop-without-reply case. It is `True`
when a response was received. An inferred close alone does not prove that PHP
completed successfully; observe the application response for that guarantee.

## Standard input

Configure redirection before sending data:

```python
assert await session.set_stdin(True)
assert await session.send_stdin("first line\n")
assert await session.send_stdin(b"\x00binary\n")
assert await session.set_stdin(False)
```

The lower-level `stdin(mode=1)` enables redirection, `stdin(mode=0)` disables it,
and `stdin(data=...)` sends input. Mode and data are mutually exclusive. Data
accepts text or bytes, including an empty payload, and is base64 encoded on the
wire. All three methods return the engine's boolean success flag. Redirection
state changes only after a successful acknowledgement, including late replies
after caller cancellation.

While execution is pending, input is allowed when the engine advertises async
support. A synchronous engine may instead emit `notify name="stdin"`; redirected
input can be delivered while it waits for that notification. Configuration is
still subject to the engine's async restrictions. Unsolicited input to a running
synchronous engine is rejected. Calls serialize through an input-specific lock,
so remote input can proceed while another RPC waits for `run` to finish.

`stdin_redirected` and `stdin_waiting` describe the last observed state and appear
in remote session metadata. Notifications remain available in the event journal.
Cancelling an input call abandons its result; it cannot retract data already
sent to the engine.

## Interactive shells

For an engine advertising `interact`, submit fragments and inspect its prompt:

```python
result = await session.interact("if condition:")
print(result.prompt)
if result.more:
    result = await session.interact("    answer = 42")

# Discard the engine's pending input buffer:
result = await session.interact(mode=0)
assert not result.more and result.prompt == ""
```

`interact(code="", mode=1, timeout=...)` accepts text or bytes and returns
`InteractiveResult(status, more, prompt, reason)`. The engine owns the code
buffer; DBGpilot sends fragments as supplied rather than concatenating them.
Mode 0 clears it. Malformed results, including invalid `more` flags or a nonempty
reset prompt, are protocol errors.

Calls require `break` or `interactive` state and share execution ownership with
run/step/eval. The `interactive` state permits property/stack inspection and
evaluation. For an interactive-only engine, call `status()` to observe that
state before submitting code. Output and notifications remain separate events.
Each valid interaction response updates `last_interaction` and emits
`InteractiveEvent(result)`; server metadata exposes the same value as
`interaction`, and event cursors can replay prompts after client reconnection.

Direct interaction calls follow the execution-timeout policy: no default
deadline unless configured. Remote calls use the server's execution deadline.
Timeout/cancellation does not stop code execution or clear its buffer; late
responses still update state and publish events. A second execution operation
remains blocked until the actual reply arrives.

`RemoteSession` exposes `stdin`, `set_stdin`, `send_stdin`, and `interact`.
Remote results are JSON rather than dataclasses; Python byte arguments use the
standard binary envelope. The corresponding RPCs are `session.stdin`,
`session.set_stdin`, `session.send_stdin`, and `session.interact`.
