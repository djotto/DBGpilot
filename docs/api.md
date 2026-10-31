# API reference

[Documentation index](../README.md#documentation) · [Workflows](workflows.md) · [Values and paths](values-and-paths.md)

`dbgpilot` exports the extended Playwright `test`, Playwright's `expect`, and all
public core exports. `dbgpilot/core` exports `Listener`, `Xdebug`, `Session`,
`PausedBrowser`, `PathMapper`, `PartialValue`, `toJSONSafe`, and the error classes.
The core entry point does not import Playwright Test at runtime.

`Session` and `PausedBrowser` instances come from the debugger; their constructors
are private in the public declarations. Raw connections, packet encoders,
parsers, protocol constants and internal module paths are not public exports.
The exact TypeScript definitions are in [core.d.ts](../core.d.ts) and
[index.d.ts](../index.d.ts).

All time values below are milliseconds. Operations return promises unless
identified as synchronous properties or constructors.

## Playwright fixture options

Use the exported `test.use({...})`, or `use` in a Playwright config. The option
types are `XdebugTestOptions` and `XdebugWorkerOptions`.

| Option | Default | Scope and purpose |
| --- | --- | --- |
| `xdebugHost` | `127.0.0.1` | Worker; listener bind interface. |
| `xdebugPort` | `9003` | Worker; listener TCP port. |
| `xdebugUnclaimedTimeout` | `2000` | Test; delay before detaching an unclaimed prepared session. Zero schedules immediate release, not an unlimited wait. |
| `xdebugIdeKey` | Generated `pw…` key | Test; parent owner key and trigger cookie value. |
| `xdebugPathMappings` | `[]` | Test; local source roots mapped to PHP file URI roots. |
| `xdebugBaseDir` | Process working directory | Test; base for relative local paths. |

The fixture creates a worker-owned listener, test-owned debugger, and trigger
cookie for `baseURL` when configured. Use `enableFor()` for another hostname.
Debugger operations are Playwright steps. Test teardown disposes the owner even
when assertions fail. The fixture does not extend the test runner timeout.

## `Xdebug`

### Construction and ownership

```js
const listener = new Listener();
await listener.listen(9003, '127.0.0.1');
const xdebug = listener.register(new Xdebug(context, 'my-debug-key', 2000, {
  pathMappings: [{local: '/work/site', remote: 'file:///var/www/html'}],
}));
```

`new Xdebug(context, ideKey, unclaimedTimeout = 2000, options = {})` creates an
owner. `context` is a Playwright BrowserContext, or `undefined` for manual CLI
attachment. `options` accepts the [session options](#session-options) and an
optional listener; registering with a listener sets that association.

Properties: `ideKey`, `disposed`, `listener`, and `captures` (the current returned
capture handles). Use registration methods rather than modifying ownership maps.

| Method | Result and behavior |
| --- | --- |
| `enableFor(url)` | Sets an `XDEBUG_TRIGGER` cookie at the URL's origin root in the supplied context. |
| `waitForSession({url, method, timeout = 30000, signal} = {})` | Claims a prepared Session. String URL matches path without query; RegExp matches recorded URI including query. Method matching is uppercased. Zero timeout disables the timer. |
| `capture(page, action, options)` | Captures the first routed request and returns a `PausedBrowser` at a breakpoint. `action` is a function returning a promise. |
| `goto(page, absoluteURL, options = {})` | Navigation capture; its action is `page.goto()`. URL must be absolute HTTP(S). |
| `dispose()` | Cancels preparation/waiters, releases owned sessions, and closes captures. Repeated calls share the same result. |

Setup errors reach current session waiters, or are queued for a subsequent wait.
An owner retains at most 50 queued errors. Waiting on a disposed owner fails.
Unregistering an owner alone does not dispose it.

### Capture options

| Field | Default / purpose |
| --- | --- |
| `urlPattern` | Required by `capture()`; Playwright route glob, RegExp, or `(url: URL) => boolean`. `goto()` supplies an exact URL predicate excluding its fragment. |
| `method` | Optional HTTP method filter. |
| `breakpoints` | `[]`; array of `{file?, line?, ...BreakpointOptions}`. PHP must hit a breakpoint for capture to succeed. |
| `variables` | `[]`; PHP variable fullnames for the initial snapshot. |
| `expressions` | `[]`; PHP expressions for the initial snapshot. |
| `timeout` | `30000`; total setup-to-breakpoint-and-snapshot deadline, greater than zero and at most `300000`. |
| `signal` | Optional AbortSignal for capture setup. Its listener is removed once the handle returns. |
| `ideKey` | Generated `capture-…` key; use a unique accepted key if PHP restricts triggers. Independent of the fixture's `xdebugIdeKey`. |
| `navigationTimeout` | `goto()` only; `0` by default, passed to `page.goto()`. |

The selected URL receives `XDEBUG_SESSION` and `XDEBUG_TRIGGER` query parameters.
Method and request body are preserved. This requires browser routing to observe
the request. Setup selects only one request; subsequent matches fall through.
Capture does not offer per-call path mapping, frame, context or snapshot-depth
options: configure paths on the owner and request additional session reads after
capture returns.

### `PausedBrowser<T>`

| Member | Meaning |
| --- | --- |
| `session` | Live paused Session. |
| `snapshot` | Copied, JSON-safe initial Snapshot. |
| `action` | Promise for the supplied action, with result type `T`. |
| `finished({timeout = 30000, signal} = {})` | Waits for that action without resuming PHP. A timed-out wait does not cancel the action or close the capture. |
| `close()` | Releases its child owner/session, allows the action to settle briefly, and removes its exact route handler. Does not close the caller's page. Repeated calls share cleanup. |

For `goto()`, `T` is Playwright `Response | null`. For a click returning `void`,
`T` is `void`; action completion need not mean AJAX completion. Route removal is
deferred until cleanup because removing interception during a paused navigation
can itself wait for PHP. A closed/expired handler does not select new requests.

## `Session`

A session owns one PHP request. `id` is a process-local label, not a reconnect
handle. `init` contains engine initialization metadata. `info` adds original init
XML and mapped source information. `label` identifies the request for reporting.
`state`, `lastResult`, `paths` and `knownBreakpoints` describe current execution,
last continuation result, path mapper and copied known breakpoint inventory.

Call operations sequentially within a session. Inspection, mutation and raw
commands reject while another operation owns it. Execution ownership persists
after timeout/abort until the actual response. In `stopping`, inspection is
attempted and the engine decides availability; another run/step is rejected.

### Execution and release

| Method | Result / behavior |
| --- | --- |
| `run({timeout = 30000, signal} = {})` | Continues to the next pause or completion; returns ExecutionResult. |
| `runUntilBreak(options)` | Like run, but rejects and releases the session if execution ends without a breakpoint. |
| `stepInto(options)`, `stepOver(options)`, `stepOut(options)` | Continue according to the requested stepping mode; same timeout/signal defaults as run. |
| `waitForPause({timeout = 30000, signal} = {})` | Recovers a current or eventual pause after an earlier wait ended. Rejects if PHP finishes first. Does not run PHP. |
| `detach()` | Calls bounded release and lets PHP finish; returns ExecutionResult. |
| `release()` | Same underlying idempotent cleanup used by owner teardown. Attempts detach when safe; otherwise closes the connection to release execution. |
| `stop()` | Requests PHP termination, then closes the connection. Returns an acknowledgement result or a result identifying permitted clean EOF; other errors propagate. |

ExecutionResult fields are optional unless stated:

| Field | Meaning |
| --- | --- |
| `status` | Required engine state such as `break`, `stopping` or `stopped`. |
| `reason` | Engine reason. |
| `fileUri`, `file`, `localFile`, `pathMappingError`, `line` | Engine URI, convenient server path, mapped local path, mapping diagnostic and source line. |
| `exception`, `message`, `breakpoint` | Exception/message or breakpoint metadata supplied by the engine. |
| `responseReceived` | Whether the result came from a command acknowledgement. Clean EOF is distinct from acknowledgement. |
| `releaseError` | Detach failure message recorded during release; connection closure still occurs. |

Release uses a 2 s detach wait when no execution is pending. Closing while PHP
runs abandons debugging; it is not a promise of application rollback. Read a
returned `releaseError` if detach success matters to the script.

### Breakpoints

| Method | Result |
| --- | --- |
| `setBreakpoint(file?, line?, options = {})` | Opaque breakpoint ID string. |
| `setExceptionBreakpoint(className = '*')` | Convenience exception breakpoint ID. |
| `getBreakpoint(id)` | Breakpoint record from the engine. |
| `breakpoints()` | Current engine breakpoint records; refreshes known inventory. |
| `updateBreakpoint(id, {state?, line?, hitValue?, hitCondition?})` | Updates selected breakpoint settings. |
| `removeBreakpoint(id)` | Removes the breakpoint and its known inventory entry. |

Breakpoint options:

| Option | Meaning |
| --- | --- |
| `kind` | `line` by default; also `conditional`, `call`, `return`, `exception`, `watch`. Xdebug may reject unsupported kinds. |
| `condition` | PHP expression string or Buffer. A condition on a line breakpoint selects `conditional`. Required for conditional/watch. |
| `temporary` | `false` by default; request removal after its hit. |
| `state` | `enabled` by default, or `disabled`. |
| `hitValue`, `hitCondition` | Nonnegative hit count and one of `>=`, `==`, `%`. |
| `function` | Required function/method name for call/return breakpoints. |
| `exception` | Required exception name for exception breakpoints. |

Line breakpoints require a file and positive line. Conditional breakpoints
require a file and expression, with optional positive line. Engine responses
control whether a breakpoint is accepted, resolved or adjusted; capability
advertisements do not reject a request locally. Breakpoint records can include
`id`, `type`, `state`, location, `resolved`, hit fields, expression, function,
exception, temporary flag and original attributes. Notifications and late
breakpoint responses also update `knownBreakpoints`.

### Stack, contexts and values

Frame and context indexes default to zero where present. Frame zero is the
current frame. See [value representations](values-and-paths.md#php-values) before
using container values or serializing debugger data.

| Method | Result / options |
| --- | --- |
| `stack({frame} = {})` | Frame array, optionally requesting one frame. Records contain level, function (`where`), location, type, command range, nested `inputs` and original attributes. |
| `stackDepth()` | Nonnegative stack depth number. |
| `contexts({frame = 0} = {})` | Object mapping context ID to name; discover IDs instead of assuming a globals context number. |
| `locals({frame = 0, context = 0} = {})` | Name-to-convenient-value object. May contain partial values. Does not recursively fetch every container. |
| `getVariable(name, {frame = 0, context = 0, depth = 1} = {})` | Convenient PHPValue; pages direct children and descends when depth requests it. |
| `getProperty(name, options)` | Structured Property with metadata, raw bytes, children and truncation flags; same traversal options as getVariable. |
| `getPropertyPage(name, target = {})` | One structured page; no automatic child-page traversal. |
| `propertyValue(name, target = {})` | Raw value Buffer, default `maxData: 0`. |
| `propertyValueInfo(name, target = {})` | `{data, size, truncated, page?, key?, address?}`. Compare advertised size with returned bytes. |
| `evaluate(expression, {timeout = 10000, signal, frame = 0, page = 0} = {})` | Convenient result of PHP evaluation. Only frame 0 is supported; nonzero frame rejects before sending. |
| `setVariable(name, value, {frame = 0, context = 0} = {})` | Assigns a supported JS value to an existing variable/property and verifies it remains readable. |
| `setProperty(name, expression, {frame = 0, context = 0, type?, address?} = {})` | Assigns an explicit PHP expression string/Buffer; returns the engine success boolean. |
| `snapshot({variables = [], expressions = [], frame = 0, context = 0, depth = 1} = {})` | Copied JSON-safe Snapshot of execution, stack and requested structured properties. Expressions require frame 0. |

Names/fullnames and expressions can be strings or Buffers on methods whose
declarations permit them. Property targets accept `frame`, `context`, `page`,
`maxData`, `key` and `address`. Page/frame/context default to zero for page reads;
property-value page is omitted unless supplied. Address and key are engine
metadata useful for explicit property access.

Evaluation and assignment can execute application code and have side effects.
They are tracked as execution while pending. `setVariable()` accepts null,
booleans, finite safe numbers, signed 64-bit BigInts, strings, Buffers, arrays and
plain objects. It rejects Date/class instances, undefined, cycles and unsafe
numbers. If the verification read fails after assignment, the failure is the
thrown error's `cause`; the assignment may already have happened.

### Engine metadata, capabilities and source

| Method | Result / behavior |
| --- | --- |
| `status()` | Validates and records the engine state; returns ExecutionResult. |
| `getCapabilities()` | Fresh Record of 40 known feature/command names to Feature records. Every call queries the whole inventory; no cache or subset argument. |
| `featureGet(name)` | Fresh individual Feature; also accepts vendor-specific names. |
| `featureSet(name, value)` | Engine success boolean; false is a refusal, not a successful change. |
| `typeMap()` | Engine type-name mappings with common type, schema type and original attributes; subsequent value decoding uses the map. |
| `source(file?, {begin?, end?} = {})` | Source bytes as Buffer, optionally limited by positive source lines. Supports mapped file paths and explicit virtual `dbgp:` source URIs. |
| `setOutput(stream = 'stdout', mode = 1)` | Requests stdout/stderr off (0), copy (1), or redirect (2); returns success boolean. Engine support varies. |
| `command(name, args?, data?, timeout?)` | Raw parsed DBGp response. The transport supplies transaction IDs and base64 command-data encoding. Known execution commands retain execution ownership and state handling. |

Feature records are `{supported: boolean, value: string, enabled: boolean}`.
`enabled` is true only when the name is supported and its value is `1`. A
supported numeric limit or list can have `enabled: false`. Unsupported inventory
queries returning DBGp error 3 or 4 become unavailable entries; unexpected
errors reject. Explicit `featureGet()` errors propagate.

Startup normally sends 10 commands: read `encoding` and `data_encoding`; set
`max_children=100`, `max_data=0`, `max_depth=1`, `extended_properties=1`,
`notify_ok=1`, `resolved_breakpoints=1`, `breakpoint_details=1`; evaluate request
method and URI/CLI filename. Optional setting refusals retain engine defaults.
Other engine/protocol failures fail setup. Incompatible encodings require
additional successful correction settings before metadata evaluation.

The session preserves UTF-8 transport assumptions with lossless handling of
Xdebug's Latin-1-labelled application bytes. Command data remains base64. Both
typed and raw feature setters reject changes that would break those assumptions.
Raw commands otherwise remain subject to validation, pending-operation guards
and engine errors. The [DBGp manual](https://xdebug.org/docs/dbgp) defines their
arguments and response shapes; raw access does not add unsupported extensions.

### Events

`session.on('stream', handler)`, `on('notification', handler)` and
`on('stopped', handler)` receive their data directly. The EventEmitter `close`
event receives the closing Error; `finished` receives the last execution result
when a continuation reports completion. Attach handlers before resuming PHP.

`nextEvent({timeout = 30000, signal} = {})` consumes retained events in arrival
order. EventEmitter handlers do not consume that queue.

| Event record | Payload |
| --- | --- |
| `{type: 'stream', data}` | `{stream, data: Buffer}` with stdout/stderr bytes. |
| `{type: 'notification', data}` | Engine notification fields, decoded data, original XML, and mapped breakpoint/message information where present. |
| `{type: 'stopped', data}` | ExecutionResult at a continuation stop, or recovered abandoned evaluation pause. Ordinary completed evaluations do not create duplicate stop events. |
| `{type: 'closed', error}` | Terminal `{name, message}`; queued events drain first. Further reads return a copy of the terminal event. |

A timeout or aborted event wait does not consume a future event. Queue overflow
closes the connection with ProtocolError; consumers of long-running streams must
drain the queue or choose a suitable core `maxEvents` bound.

## `Listener` and session options

`new Listener(options = {})` accepts:

| Option | Default | Meaning |
| --- | --- | --- |
| `handshakeTimeout` | `5000` | Deadline for the initial DBGp init packet, not a total session-preparation deadline. Must be positive. |
| `maxSessions` | `256` | Maximum accepted connections, including uninitialized/preparing connections. |
| `connectionOptions.maxPacketSize` | `16777216` | Maximum incoming XML packet bytes (16 MiB). |
| `connectionOptions.maxPendingCommands` | `1024` | Maximum outstanding commands, including abandoned waits awaiting replies. |

`listen(port = 9003, host = '127.0.0.1')` resolves to the Listener. Core callers
can request port zero and read the assigned `port`. `register(owner)` returns
the owner; duplicate IDE keys reject. `unregister(owner)` removes only that
owner's registration. `close()` disposes registered owners and closes all
connections, including sockets still initializing. Repeated close calls share
one cleanup promise. A closed listener cannot restart.

`owners` exposes registered owners; `diagnostics` returns the latest 50 diagnostic
summaries. Listen for `diagnostic` to receive live errors, including invalid
initialization and listener failures. Owner setup failures also reach its waiters.

### Session options

Pass these through the core `Xdebug` constructor. The Playwright fixture exposes
path configuration but does not expose every transport/resource limit as a
fixture option.

| Option | Default | Meaning |
| --- | --- | --- |
| `pathMappings` | `[]` | Array of mappings or a PathMapper instance. |
| `baseDir` | Working directory | Resolve relative local paths. |
| `maxPages` | `1024` | Per-property child-page traversal bound. |
| `maxDepth` | `16` | Maximum requested property traversal depth; default reads still use depth 1. |
| `maxEvents` | `1024` | Retained session-event capacity. |
| `step(title, body)` | Calls body directly | Optional reporting wrapper; the fixture injects Playwright steps. |

These limits bound traversal and retained metadata. Startup requests unlimited
string data (`max_data=0`), so huge individual values can still exceed packet
limits. Use targeted page/value reads and explicit `maxData` when appropriate.

## Errors

| Export | Meaning and useful fields |
| --- | --- |
| `XdebugError` | Engine rejected a command; `command`, numeric `code`, original `attributes`, XML and parsed response when supplied. |
| `CommandTimeout` | Command wait expired; `command`. PHP may still be executing. |
| `ConnectionClosed` | Connection ended; `cleanEOF` distinguishes a clean socket end from other failures. |
| `ProtocolError` | Malformed/unexpected response, invalid property data or exceeded protocol resource bounds. |
| `PathMappingError` | Mapping failure with `path`, `direction` and `reason`. |

Caller validation may throw TypeError/RangeError. AbortSignal rejection preserves
its reason. Cleanup across several resources can throw AggregateError. When
cleanup also fails during a failed capture setup, the original error is
preserved; `cleanupError` is attached when that value can carry properties.
Primitive or frozen rejections cannot always carry secondary diagnostics.
