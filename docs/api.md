# DBGpilot 0.1 API

## Lifetime

Use `async with Controller(...) as controller` or await `start()` and `aclose()`.
Xdebug connects to the listener and waits for a continuation command while the
controller negotiates features and the caller sets breakpoints.

`await controller.wait_for_session(timeout=...)` returns the next ready session.
`controller.sessions` lists live sessions. `await controller.next_error()` reports
rejected handshakes without disabling the listener. `session.info` records its
local UUID, engine app ID, IDE key, language, protocol version, and initial file.
It also retains the session cookie, thread/parent IDs, proxy address, engine
name/version, init attributes, and init XML for vendor metadata.

Each session owns a reader task and transaction table. Paused PHP does not block
other sessions. Objects belong to their owning event loop and are not
thread-safe or cross-process handles. Keep the owning Python process alive for
interactive follow-up commands.

For cross-process callers, the [persistent server](server.md) owns this event
loop and exposes session IDs through an HTTP API. `Client`/`RemoteSession` are
JSON-based remote handles; closing a client leaves its server-owned sessions
alive. Direct `Session` objects still belong to the controller's process.
For script cancellation, use `Client.request()` / `RemoteRequest.cancel()` or
`cancel_request` on the server. Cancelling an RPC abandons its response without
advancing PHP; late engine replies remain available through state/events. The
Python client also cancels its outstanding RPCs when closed. The
[Playwright helper](playwright.md) adds browser action routing and cleanup above
these remote session handles.

Context exit attempts a bounded detach for paused sessions and closes their
connections. `detach()` lets PHP finish; `stop()` terminates its execution.
Closing while PHP runs closes the transport rather than sending an unsupported
synchronous command. [Configured local/remote path mappings](path-mapping.md)
translate file arguments and add local locations to results while preserving
engine URIs. [Proxy registration and optional stdin/shell APIs](proxies-and-shells.md)
are available through both the controller and persistent server.
The [optional-command guide](optional-commands.md) covers `expr`, `exec`, and the
five spawnpoint operations, including engine support and late acknowledgements.

## Execution and results

- `run()` / `resume()` return an `ExecutionResult` at the next execution stop.
- `run_until_break()` raises `ExecutionFinished` if execution ends first.
- `step_into()`, `step_over()`, and `step_out()` return the next execution result.
- `snapshot(variables=(), expressions=(), depth=0, context=0)` returns copied
  properties and stack frames. `Snapshot.to_dict()` is JSON-safe.

A result or snapshot leaves PHP paused and the session available for the next
decision. Snapshot properties explicitly report truncated values and children;
they do not recursively fetch the entire application graph. Expressions are
evaluations and can have side effects.

Commands default to a configurable five-second timeout. Execution commands,
including evaluation, expr/exec, and interaction, have no default deadline;
pass `timeout=`, configure `execution_timeout`, or use
`asyncio.timeout()`. Timeout/cancellation abandons the response, not PHP execution.
The reader still processes later stops and updates session state. The caller
must continue investigating or close the connection. Unknown transaction IDs
and mismatched response command names close the connection with `ProtocolError`.
An outstanding evaluation blocks overlapping inspection, continuations, detach,
and stop even after its caller times out or cancels. Its actual response restores
the prior inspection state, including on engine errors. Evaluation completion
emits a `StoppedEvent` when returning to a paused frame, including responses
without a status attribute. Evaluation can produce streams and notifications.

`status()` returns an `ExecutionResult`; `stack_depth()` returns an integer.
`stop()` and `detach()` also return execution results. A clean EOF after a written
stop command counts as a successful stop; a truncated packet, malformed response,
or socket error does not. Detach checks the advertised command capability; if
unsupported, it raises without closing the session. Context cleanup then closes
the transport directly. Postmortem property/stack inspection is allowed in
`stopping` only when the engine advertises `supports_postmortem`.

That gate also applies to context names, type maps, source, and evaluation in
stopping state. Malformed continuation completion states raise `ProtocolError`.
Breakpoint and capability inventories update from acknowledged replies even
after caller cancellation. Malformed breakpoint lists never commit a partial
inventory. See the [protocol/lifecycle review](protocol-review.md) for findings,
regressions, and the scope of verification.

`ExecutionResult.response_received` distinguishes actual engine responses from
termination inferred from clean EOF. Known proxy sessions also accept clean EOF
after detach because official dbgpProxy 0.6.2 drops the terminal reply; see the
[proxy guide](proxies-and-shells.md#proxy-errors-and-terminal-replies).

## Inspection and assignment

- `stack(depth=None)` returns stack `Frame` objects.
- Frames retain `cmdbegin`, `cmdend`, and nested input/source frames in `inputs`.
- `contexts(depth=0)` lists context IDs/names.
- `context(context=0, depth=0)` reads a frame's context properties.
- `property_get(name, context=0, depth=0, page=0, max_data=None, key=None, address=None)`
  returns a property with page/truncation metadata.
- `property_children(name, context=0, depth=0, max_pages=1024, key=None, address=None)` pages through all
  direct children. Deeper expansion remains explicit.
- `property_value(name, context=0, depth=0, page=None, key=None, address=None, max_data=0)`
  returns bytes, with an unlimited data request by default.
- `property_value_info(...)` accepts the same arguments and returns a
  `PropertyValue` containing bytes, reported size, encoding, page, key, address,
  and a `truncated` indicator. Its `to_dict()` represents binary data safely.
- `evaluate(expression, depth=0, page=0, timeout=...)` evaluates in the selected
  frame where supported, with execution-state management.
- `property_set(name, expression, type=None, context=0, depth=0, address=None)`
  sends an engine-native string or byte payload. Xdebug evaluates it as PHP code,
  even with a type argument. Other engines define their assignment semantics.
- `set_value(name, value, context=0, depth=0, address=None)` safely represents a Python string,
  bytes, integer, finite float, boolean, or `None` as an assignment expression.
  This helper is PHP-specific and rejects other languages; use `property_set`
  with a payload suitable for those engines.

`Property.type` and `classname` are separate. Valid UTF-8 strings become text;
other strings become bytes. `raw_value` preserves scalar bytes. Extended
properties, NUL-containing names, child order, and engine fullnames are preserved.
Use `fullname` for follow-up retrieval. Binary snapshot values become objects
with `encoding: "base64"` and a `data` string. Properties are not flattened into
Python dictionaries that would lose key/order information.
Models and JSON also retain facets, constant flags, and key/address identity.

`typemap_get()` returns `TypeMapping` records (language type, common type,
optional schema type, and XML), cached in the read-only `session.type_map`.
Subsequent context, property, and evaluation decoding uses those mappings while
retaining the original language type in `Property.type` and the mapped type in
`Property.common_type`. Call this explicitly to load engine-specific mappings.

The tested Xdebug 3.5.3 ignores `eval` depth. Nonzero evaluation depths are
therefore rejected by default for PHP; use frame-aware property/context reads.
Other languages default to allowing the spec's evaluation-depth argument.
`Controller(eval_depth_supported=True/False)` explicitly overrides this policy
for an engine whose behaviour is known. Snapshot expressions follow that policy.
The tested engine reports `supports_async=0`, so `interrupt()`
raises `SessionStateError`. This is separate from Python async orchestration.

## Breakpoints, source, and features

`set_breakpoint(file=None, line=None, kind="line", condition=None,
function=None, exception=None, temporary=False, hit_value=None,
hit_condition=None, state="enabled")` returns a `Breakpoint`. Disabled creation
is supported. A condition selects a conditional breakpoint; its line may be
omitted for a filename-wide condition where the engine supports that form.
Function/exception breakpoints use their named argument.
Engine support determines available types; Xdebug does not implement watch
breakpoints. IDs remain opaque strings.
Unsupported types are rejected against the advertised `breakpoint_types`.
Models retain function, exception, temporary, expression, hit settings, initial
state, and resolution information when supplied by the engine or known at
creation. Continuation results include structured breakpoint details when sent.
Initialization requests `breakpoint_details` by default.

Use `get_breakpoint(id)`, `breakpoints()`, `update_breakpoint(id, ...)`, and
`remove_breakpoint(id)`. The tested engine disables temporary breakpoints instead
of deleting them, and disables them before checking hit thresholds. To combine
those behaviours, use a normal hit-count breakpoint and remove it after the stop.
`known_breakpoints` is a read-only map of last observed records, updated by
creation/get/list/update/remove and breakpoint resolution notifications. Records
may lack fields the engine omitted; notification records are exposed directly.

File arguments accept paths or explicit `file:`/`dbgp:` URIs. Paths become
engine file URIs using configured mappings, or absolute file URIs on the
controller's machine when mapping is disabled. Explicit URIs bypass outbound
mapping. Result `file` fields retain engine URIs; `local_file` and
`path_mapping_error` describe reverse mapping. Use a remote URI for remote
files outside the configured local roots. `source(file=None, begin=None, end=None)` returns source bytes, including
virtual sources where supported.

`feature_get(name)` returns `Feature(supported, value)`: recognition differs from
the enabled value. `feature_set(name, value)` reports success. Initialization
tries extended properties, depth 1, 32 children, 1024 data bytes, multiple
sessions, notifications, breakpoint details, and breakpoint resolution notifications. Unsupported
optional features are tolerated. Pass `features={...}` to replace these defaults.
`capabilities` exposes a read-only inventory of queried core/optional commands
and spec features. `supports_command(name)` checks the latest advertised value;
`refresh_capabilities()` queries the inventory again. Queries and successful
settings update it. Optional eval/expr/exec, detach/break, stdin/interact, and
spawnpoint operations check support before
sending their command. Unknown/unadvertised support is treated as unavailable;
raw `command()` remains available for unusual engines.

Generic engines must use UTF-8 communication: initialization requests UTF-8 if
another encoding is advertised and rejects engines that refuse it. Explicit
non-UTF-8 settings are rejected before sending. Xdebug is a specific exception:
it advertises fixed ISO-8859-1 XML framing over PHP application bytes. DBGpilot
preserves those bytes, decodes valid UTF-8 names, and uses surrogateescape for
other names. UTF-8 XML packets are not reinterpreted. Base64 payloads preserve
binary values in both profiles; the API rejects switching command data encoding
away from base64.

`command(name, arguments=None, data=None, timeout=...)` is the raw command escape
hatch returning XML. Use execution methods for continuation commands so their
state and outstanding operations are managed correctly.

## Events and errors

`await session.next_event(timeout=...)` returns a `StreamEvent(stream, data)`,
`NotificationEvent(name, xml, data)`, `StoppedEvent(result)`, `InteractiveEvent(result)`,
`ProxyErrorEvent(error)`, or `ClosedEvent(error)`.
Streams preserve bytes; `set_output(stream="stdout", mode=1)` enables copying.
Notification XML is retained. Notification body data includes text after XML
children, excluding the children's metadata text. `NotificationEvent.breakpoint`
contains a decoded breakpoint when present; `.message` contains notification
text, filename, line, type, and attributes when present. Original XML preserves
vendor additions. Events are dispatched independently of responses.

Consume events in long-running applications. The default queue holds 1024;
overflow explicitly closes the session. The packet limit defaults to 16 MiB.
Both are configurable. Snapshot capture does not require stdout redirection.

The controller also bounds pending plus abandoned transactions per session
(`max_pending_commands=1024`), live plus initializing connections
(`max_sessions=256`), and recent rejected-connection errors (`error_queue_size=50`).
At the command limit, new commands fail before transmission; late replies free
capacity. At the connection limit, only new admissions are rejected. Existing
live sessions are never evicted or resumed. Closed sessions are removed from the
controller automatically; the server independently owns its bounded closed
history. Cancelled event/session waits preserve queued items and FIFO ordering.

`CommandError` contains the command, numeric engine code, message, error
attributes, and error XML (including vendor elements).
`ProxyError` retains opaque string codes and proxy error XML; it is reported
directly for registration and through events for established sessions.
`PathMappingError` retains the input path, direction, and reason. Unmapped local
file arguments fail before a command is sent; unmatched incoming engine files
retain their URI and a diagnostic rather than closing the session.
`ConnectionClosed`, `ProtocolError`, `SessionStateError`, and `ExecutionFinished`
also derive from `DBGpilotError`. Deadlines raise Python's `TimeoutError` and
cancellation remains `asyncio.CancelledError`.

## Python setup

`DebuggerSetup(*, config=None, discover=False, **overrides)` is an async context
manager that connects to an existing daemon or explicitly launches the existing
CLI when `launch=True` is configured. `start()` returns the setup; `client` is
its normal `Client`, `url` its reachable endpoint, `pid` its owned process ID or
None, and `owns_server` records ownership. `health()` checks compatibility and
child identity; `debugger(page, idekey=None)` returns `PlaywrightDebugger`.
`aclose()`/context exit closes only the client. `shutdown(release_sessions=True)`
stops only an owned child and releases all its sessions. Reused servers cannot
be shut down through setup. Startup failures raise `SetupError`; invalid settings
raise `ValueError` (file access errors remain `OSError`). See
[Python setup](python-setup.md) for `SetupConfig`, shared TOML settings, timeout
precedence, pytest scopes/teardown, networking, and runnable examples.

