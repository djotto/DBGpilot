# Vdebug versus DBGp

Audit date: 2026-10-26.

Compared the [DBGp 1.0 draft 22 specification](https://xdebug.org/docs/dbgp)
with Vdebug's `master` at commit
[`66517871178779ac54e19ed0f34d66805b820664`](https://github.com/vim-vdebug/vdebug/commit/66517871178779ac54e19ed0f34d66805b820664),
dated 2024-05-02. The source was cloned and inspected, rather than relying on
Vdebug's advertised feature list. Runtime checks used the project's DDEV
environment: PHP 8.4.22, Xdebug 3.5.3, and Python 3.13.5. The clone and diagnostic
scripts were kept in temporary directories. Vdebug was subsequently packaged as
a development reference, then removed after DBGpilot's independent suite passed.

## Assessment

Vdebug implements a useful subset of DBGp, but it is not a complete protocol
implementation or an asynchronous debugger library. Basic debugging works.
Missing wrappers are relatively easy to add; message routing, property decoding,
and concurrent request management require more substantial work for this
project's intended use.

## Existing coverage

The API has methods for status, feature queries/settings, run, all three step
operations, stop, detach, stack retrieval, context names/retrieval, property
retrieval, breakpoint creation/listing/removal, and breakpoint enable/disable.

The breakpoint helpers include ordinary, temporary, conditional, exception,
function-call, and function-return breakpoints. A watch helper also exists,
though the Xdebug instance tested advertises only `line conditional call return
exception` as supported breakpoint types.

Proxy registration is present. Feature negotiation is present. Extended-property
decoding is partially implemented and enabled by the normal session setup;
these should not be described as wholly missing.

Sources: [API](https://github.com/vim-vdebug/vdebug/blob/66517871178779ac54e19ed0f34d66805b820664/python3/vdebug/dbgp.py),
[breakpoint helpers](https://github.com/vim-vdebug/vdebug/blob/66517871178779ac54e19ed0f34d66805b820664/python3/vdebug/breakpoint.py),
[connection layer](https://github.com/vim-vdebug/vdebug/blob/66517871178779ac54e19ed0f34d66805b820664/python3/vdebug/connection.py).

## Missing or incomplete coverage

| Area | Vdebug finding | Consequence for this project |
| --- | --- | --- |
| Message dispatch, sections 6.2 and 6.4 | `Api.send_cmd()` sends once and receives exactly one packet, without checking its root tag, command, or transaction ID. | A stream or notification can be consumed as the command response and leave the real response pending. |
| Concurrent debugger commands | API calls block in `recv_msg()`; the background listener only accepts a connection and then hands over a blocking socket. | Browser orchestration needs threads or a redesigned async transport. There is no built-in concurrent command dispatcher. |
| Multiple sessions, section 5.4 | Normal session setup explicitly sets `multiple_sessions` to `0`; the listener accepts one connection and finishes. Continuous mode starts listening again after the current session ends. | Sequential requests are supported, but simultaneous AJAX/PHP requests need a new session manager. |
| Property paging and full values, sections 7.11–7.13 | `property_get(name)` exposes no page, maximum-data-size, context, key, or address options. There is no `property_value()` wrapper. The parsed property object does not retain page/pagesize metadata. | Large arrays and truncated strings cannot be fully retrieved through the existing high-level API. Feature settings can raise limits but do not implement paging. |
| Selected stack frames, sections 7.8–7.13 and 8.3 | `context_get()` accepts a stack depth, but `property_get()` hardcodes `-d 0`, and `eval()` exposes no depth. | Listing another frame's variables is possible; evaluating there or expanding its properties needs API changes. |
| Breakpoint management, section 7.6 | No `breakpoint_get()` wrapper. `breakpoint_update` is used only for enable/disable. High-level breakpoint helpers omit hit-count conditions. | Changing a breakpoint's line or hit condition requires raw commands or new wrappers. `breakpoint_set(cmd_args)` already accepts arbitrary arguments. |
| Other core commands | No dedicated wrappers for `stack_depth`, `typemap_get`, `property_set`, `property_value`, `source`, `stdout`, or `stderr`. | These require new methods/decoders or raw commands. Missing `source` support matters for virtual `dbgp:` source files. |
| Optional commands | No dedicated wrappers for `stdin`, `break`, `expr`, `exec`, spawnpoint commands, or `interact`. The UI explicitly rejects interactive mode. | These are gaps against the generic specification, not necessarily capabilities available in Xdebug. |
| Breakpoint notifications/details | No dedicated handling for `breakpoint_resolved` notifications or structured `breakpoint_details`. | Raw XML may contain useful details, but the existing API does not turn them into reliable events. |

The distinction between a missing wrapper and an impossible operation matters:
`send_cmd(command, args, response_class)` can send arbitrary commands and return
their XML. This is an escape hatch for simple requests; it does not fix the
one-packet response assumption or add property decoding and session management.

Sources: API `send_cmd()` at lines 232–255; API wrappers at lines 257–391;
[session feature setup](https://github.com/vim-vdebug/vdebug/blob/66517871178779ac54e19ed0f34d66805b820664/python3/vdebug/session.py#L282-L305);
[background listener](https://github.com/vim-vdebug/vdebug/blob/66517871178779ac54e19ed0f34d66805b820664/python3/vdebug/connection.py#L225-L269).

## Reproduced failures

1. **Stdout routing — live Xdebug.** Enabled output copying through the raw
   `stdout -c 1` command. The following `api.run()` returned a `<stream>` packet,
   with no status. Reading another packet revealed the actual `run` response,
   still pending. This confirms a failure when the stream facility is enabled;
   it is not a claim that default PHP output always uses DBGp streams.

2. **Extended PHP array keys — live Xdebug.** Enabled `extended_properties`,
   created `$data = ["a\0b" => 1]`, and evaluated `$data` at a breakpoint.
   `get_context()` raised `AttributeError: 'NoneType' object has no attribute
   'isdigit'`. `EvalProperty` assumes that PHP child properties always have a
   `name` attribute, while extended properties carry a base64 `<name>` element.

3. **Binary PHP strings — live Xdebug.** Retrieved `$binary = "\xff"` with
   extended properties enabled. Xdebug correctly returned base64 `/w==` in a
   `<value>` element. Vdebug raised `UnicodeDecodeError` while decoding it as
   UTF-8. The ordinary property-value path has a fallback for invalid UTF-8;
   the extended-property path does not.

4. **Protocol-version parsing — live Xdebug and a synthetic packet.** A valid
   `protocol_version="1.0"` initialization packet leaves `api.version` as `None`.
   The parser looks for `api_version`. The session separately queries the
   protocol-version feature, so this did not prevent the basic debug loop.

5. **Mismatched transaction ID — synthetic packet.** A response with ID `999`
   was accepted for the first request. There is no correlation check.

6. **UTF-8 split across reads — simulated socket.** Splitting the two-byte UTF-8
   encoding of `é` between valid socket reads raises `UnicodeDecodeError`.
   `ConnectionHandler` decodes each received chunk before reassembling the body.

7. **Partial UTF-8 writes — simulated socket.** With a socket returning partial
   writes, sending `éé` produced only one character plus the terminator. The send
   loop counts characters but advances using the number of bytes sent.

Sources: [property parsing](https://github.com/vim-vdebug/vdebug/blob/66517871178779ac54e19ed0f34d66805b820664/python3/vdebug/dbgp.py#L394-L557),
[initialization and response handling](https://github.com/vim-vdebug/vdebug/blob/66517871178779ac54e19ed0f34d66805b820664/python3/vdebug/dbgp.py#L219-L255),
[socket reads/writes](https://github.com/vim-vdebug/vdebug/blob/66517871178779ac54e19ed0f34d66805b820664/python3/vdebug/connection.py#L59-L93).

## Scope and recommendation

The harness's Xdebug returned `supports_async = 0`. Missing support for sending
`break` while PHP is running therefore is not an additional Vdebug limitation
for this runtime. This protocol feature is separate from using Python async
code to coordinate Playwright with a debugger that is stopped at a breakpoint.

Use Vdebug as reference code or a carefully scoped source of reusable parts.
For the proposed Playwright integration, budget explicitly for packet dispatch,
safe byte-oriented transport, frame-aware property/evaluation APIs, faithful
property decoding, paging, and ownership of multiple PHP connections. A thin
wrapper around its current API would inherit the failures above.
