# Expressions, code fragments, and spawnpoints

DBGpilot implements the optional commands from
[DBGp sections 8.3.1–8.4](https://xdebug.org/docs/dbgp). Each method checks
its own advertised command capability before sending it. They are available on
both `Session` and `RemoteSession`; remote results use JSON instead of dataclasses.
The tested Xdebug does not advertise these commands. Use `evaluate()` for PHP
code; positive coverage of these optional APIs uses scripted engines.

## Expressions and code fragments

```python
# On an engine advertising expr and exec:
property = await session.expr("answer + 1", depth=0, page=0, timeout=30)
if property is not None:
    print(property.value)  # RemoteSession instead returns a property dictionary.

success = await session.exec("answer = 42", timeout=30)
assert success
```

`expr(expression, depth=0, page=0, timeout=...)` evaluates an expression. It returns
a `Property` when `success=1`, or `None` when the engine explicitly reports
`success=0`. A successful response must contain exactly one property. Normal
property decoding preserves binary values, type mappings, children, paging, and
truncation indicators. A null-valued property is still a `Property`, distinct from
an unsuccessful expression.

`exec(code, timeout=...)` executes a code fragment and returns the boolean
`success` flag. It does not expose an expression result or accept `depth`/`page`;
the spec lists those options for eval/expr. Output remains available through
stream events. A vendor-supplied property in an exec response is ignored.

Both methods accept text or bytes, including empty payloads, and encode the data
as base64. Invalid success flags and malformed successful expr properties are
protocol errors; engine error elements raise `CommandError` with their original
code/message/vendor metadata. An explicit `success=0` leaves the session usable.

These are execution operations, with the same ownership rules as evaluation.
They require a paused `break`/`interactive` state; `stopping` is permitted only
with advertised postmortem support. While a reply is outstanding, overlapping
inspection, execution, detach, and stop are rejected. Stream/notification events
and supported async controls remain available. Responses without a status restore
the previous state; an explicit status updates it. Returning to a breakpoint
publishes a `StoppedEvent`, including late replies after cancellation.

`expr` requires nonnegative integer depth/page values. Nonzero depth follows the
controller's `eval_depth_supported` policy, as `evaluate()` does. PHP defaults to
current-frame evaluation; an explicitly configured engine can override it.

Direct calls have no default execution deadline unless `execution_timeout` is
configured. Remote calls default to 30 seconds and require finite timeouts.
Timeout/cancellation abandons the result, not execution. The guard stays held
until the actual reply, even when the original HTTP call has ended. Do not
automatically retry lost execution responses: the code may already have run.

## Spawnpoints

Spawnpoints configure locations where an engine may start another debug session.
The engine implements spawning and application-wide ID/thread semantics;
DBGpilot manages the protocol requests and records, not process creation.

```python
point = await session.set_spawnpoint(
    "/app/child.tcl", 12, state="disabled",
)
point = await session.get_spawnpoint(point.id)
await session.update_spawnpoint(point.id, state="enabled", line=15)
points = await session.spawnpoints()
await session.remove_spawnpoint(point.id)
```

Direct methods return `Spawnpoint` objects or tuples; update/remove return
`None`. For remote calls, read IDs as `point["id"]` and results as dictionaries
or arrays. Methods map to the five separate capability names:

| Python method | DBGp command |
| --- | --- |
| `set_spawnpoint(file=None, line=None, state="enabled")` | `spawnpoint_set` |
| `get_spawnpoint(spawnpoint_id)` | `spawnpoint_get` |
| `update_spawnpoint(spawnpoint_id, state=None, line=None)` | `spawnpoint_update` |
| `remove_spawnpoint(spawnpoint_id)` | `spawnpoint_remove` |
| `spawnpoints()` | `spawnpoint_list` |

The legacy Python keyword `id` remains accepted for `spawnpoint_id` in both
direct and remote methods. JSON-RPC continues to accept the `id` field.

File and line are optional when creating a spawnpoint. Paths become absolute
file URIs; explicit `file://` URIs are preserved. Virtual `dbgp:` URIs are not
valid spawnpoint locations. Supplied line numbers must be positive integers;
update requires at least one changed field. State is `enabled` or `disabled`,
and IDs remain nonempty opaque strings. No breakpoint hit conditions or
expression payloads are attached to spawnpoint requests.

`Spawnpoint` retains ID, fixed type `spawn`, file, line, state, attributes, and
XML. Creation uses the engine's returned state and the requested location.
Get/list preserve returned locations, including engine-specific unset-line
sentinels. Vendor attributes and child elements survive in attributes/XML.
Missing IDs, invalid states/types/line encodings, mismatched get IDs, or duplicate
list IDs raise `ProtocolError` without committing a partial inventory.

`session.known_spawnpoints` is a read-only inventory separate from
`known_breakpoints`. Successful set/get/list/update/remove replies update it,
including replies arriving after timeout or cancellation. A list replaces its
contents; update changes only known records. Engine errors do not change it.
The inventory reflects observed acknowledgements, not a subscription to all
application-wide changes made by other sessions. Query get/list to refresh it.
Raw attributes/XML retain the last actual engine data rather than fabricated
fields after an update acknowledgement.

Spawnpoint methods use the ordinary command deadline, not the execution deadline.
They may be used during initial setup, but are rejected while execution is
outstanding. Cancelling a mutation cannot undo a request already sent. Its late
acknowledgement remains observable through the inventory.

## Server and client

The RPC allowlist exposes `session.expr`, `session.exec`, `session.set_spawnpoint`,
`session.get_spawnpoint`, `session.update_spawnpoint`, `session.remove_spawnpoint`,
and `session.spawnpoints`. Python `RemoteSession` provides matching methods.
Session info includes a `spawnpoints` map keyed by opaque ID, retained across
client reconnections while the server lives. Python bytes use the standard
base64 argument envelope; property bytes use the same envelope in JSON results.
The [server guide](server.md) describes cancellation IDs, errors, and deadlines.

Unsupported commands raise `SessionStateError` (`-32002` remotely), malformed
arguments return `-32602`, engine command errors return `-32004`, and malformed
protocol responses return `-32005`. Capability rejection leaves the debugging
session available for supported operations.
