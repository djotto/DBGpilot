# Values and source paths

[Documentation index](../README.md#documentation) · [API](api.md) · [Troubleshooting](troubleshooting.md)

## PHP values

Choose between convenient values and structured properties:

```js
const value = await session.getVariable('$cart', {depth: 2});
const property = await session.getProperty('$cart', {depth: 2});
```

`getVariable()`, `evaluate()` and `locals()` convert complete values for ordinary
JS assertions. `getProperty()` keeps engine metadata and explicit child records.

| PHP value | Convenient JS representation |
| --- | --- |
| null | `null` |
| Uninitialized | `undefined` |
| Boolean | `boolean` |
| Integer in JS's safe range | `number` |
| Larger integer | `bigint` |
| Float | `number`, including Infinity, -Infinity and NaN |
| Valid UTF-8 bytes | `string`, preserving whitespace |
| Invalid UTF-8 bytes | Lossless `Buffer` |
| Array with consecutive keys `0..n-1` | JS array |
| Other complete array with text keys | JS object |
| Complete object | JS object with a convenient `__class` field |
| Truncated value/container, or container with binary keys | `PartialValue` |

The `__class` field is a convenience, not an unambiguous schema for arbitrary
objects with the same property name. Use structured properties when exact
class/property metadata matters.

### Partial values and paging

`PartialValue` has `type`, optional `classname`, `totalChildren`, `children`
(name/value entries), `truncated` and optional `rawValue`. A binary-key container
can be a PartialValue even when every child was fetched; the entry representation
preserves keys that cannot safely become ordinary JS object keys.

```js
const {PartialValue} = require('dbgpilot/core');
const value = await session.getVariable('$cart');
if (value instanceof PartialValue) {
  console.log(value.totalChildren, value.truncated, value.children);
}
```

High-level property reads collect direct-child pages. The default depth is one;
request a greater depth to descend into nested containers. Each property's
pagination is bounded, and wrong pages, changing child counts or no progress
raise ProtocolError. Deep reads run sequentially to bound request fan-out.

Use `getPropertyPage()` for one specific page and `propertyValueInfo()` for raw
bytes with a reported size and truncation status. `maxData` controls explicit
page/value reads; it does not configure every read in the session.

### Structured properties

Property records include `name`, `fullname`, engine `type`, `commonType`, optional
`classname`, scalar `value`, `rawValue`, recursive `children`, `totalChildren`,
`size`, `page`, `pageSize`, `hasChildren`, `childrenTruncated`, `valueTruncated`,
facets, constant status, key and address. Names, fullnames and class names can
be Buffers when their bytes are not valid UTF-8.

For containers, structured `value` is `null`; the contents are in `children`.
It is not the convenient object returned by `getVariable()`. Uninitialized
properties and missing variables also differ: a missing variable can produce
an engine error, while an existing uninitialized property has explicit metadata.

### Assignments

`setVariable()` accepts JS null, booleans, finite safe numbers, signed 64-bit
BigInts, strings, Buffers, arrays and plain objects. It converts them to PHP
expressions without JSON rounding. Objects become PHP associative arrays, not
instances of their JS class. Undefined, cyclic values, Date/class instances,
nonfinite numbers and unsafe numeric integers are rejected.

```js
await session.setVariable('$discount', 15);
await session.setVariable('$payload', {
  bytes: Buffer.from([255, 0, 120]),
  identifier: 9223372036854775807n,
});
```

The target must be an existing variable/property in the chosen frame. Assignment
is verified by reading it afterwards; a verification failure can occur after
PHP was already changed. Use `setProperty()` for an explicit PHP expression,
such as constructing a PHP object. Evaluation and mutation may invoke application
code; neither is a passive inspection guarantee.

## Snapshots and JSON

`snapshot({variables, expressions, frame, context, depth})` returns execution,
frames and requested structured properties. It is copied and JSON-safe; later
stepping or mutation does not change it. Capture helpers obtain an initial
snapshot automatically.

`toJSONSafe(value)` is also available for values you assemble yourself:

```js
const {toJSONSafe} = require('dbgpilot/core');
console.log(JSON.stringify(toJSONSafe({
  bytes: Buffer.from([255, 0]),
  integer: 9223372036854775807n,
  uninitialized: undefined,
}), null, 2));
```

| Original | JSON-safe value |
| --- | --- |
| Buffer `ff 00` | `{encoding: 'base64', data: '/wA='}` |
| BigInt | `{type: 'bigint', value: '9223372036854775807'}` |
| Undefined | `{type: 'uninitialized'}` |
| Nonfinite number | `{type: 'float', value: 'Infinity'}` (or `-Infinity` / `NaN`) |

Arrays and objects are traversed recursively. This is an export representation;
there is no automatic inverse conversion or session reconnect encoded in JSON.
Use it on debugger data or other acyclic data, not cyclic application objects.

## Source paths

A browser URL identifies a request. A breakpoint identifies a source file in
**PHP's filesystem**. They are separate namespaces.

With no mappings, a supplied path is converted to an absolute file URI using
Node's path base. If PHP sees another root, configure a mapping rather than
assuming that the same string names the same file:

```js
test.use({
  xdebugPathMappings: [
    {local: '/Users/alice/site', remote: 'file:///var/www/html'},
  ],
});
// Inside the test:
await session.setBreakpoint('/Users/alice/site/src/Checkout.php', 42);
```

The remote root must be an absolute `file://` URI. Mappings use the longest
matching directory root, not a plain string-prefix replacement. They are
lexical: DBGpilot does not copy files, resolve symlinks on PHP's machine, or
verify that local and remote file contents match. A stale deployed copy can
therefore stop at a different line.

Relative local paths use `xdebugBaseDir`, or the process working directory.
Explicit `file:` and `dbgp:` URIs bypass outbound local mapping. Use a `dbgp:`
URI returned by the engine when retrieving virtual/evaluated source.

### Windows and case handling

Windows drives and UNC paths work even when Node runs on Linux:

```js
test.use({
  xdebugPathMappings: [{local: 'C:\\Site', remote: 'file:///var/www/html'}],
});
// Inside the test:
await session.setBreakpoint('C:\\Site\\src\\Checkout.php', 42);
```

Local Windows roots match without case sensitivity. Remote Windows roots default
to case-insensitive matching; POSIX remote roots default to case-sensitive.
A mapping's `remoteCaseSensitive` boolean overrides that remote policy.
Duplicate roots, conflicting overlap policies and mappings that do not round-trip
are rejected. An outgoing path outside configured local roots fails explicitly.

Results retain `fileUri` from the engine and optionally expose `localFile`.
An incoming URI without a matching local mapping keeps its engine location and
gets `pathMappingError`; it does not silently invent a local path. With no
mappings, `localFile` is unset. Execution/frame records can also have `file`, a
convenient server path; prefer `fileUri`/`localFile` when crossing operating systems.

### `PathMapper`

Standalone callers can use the mapper directly:

```js
const {PathMapper} = require('dbgpilot/core');
const paths = new PathMapper([
  {local: '/work/site', remote: 'file:///var/www/html'},
]);
console.log(paths.toRemote('/work/site/index.php'));
console.log(paths.toLocal('file:///var/www/html/index.php'));
```

`new PathMapper(mappings = [], {baseDir = process.cwd()} = {})` provides
`toRemote(path)`, `toLocal(uri)`, `location(uri)` and copied `mappings`.
`location()` returns `{localFile, pathMappingError}` without throwing an incoming
mapping failure. `withOverrides(mappings, {baseDir} = {})` creates a mapper whose
new rules replace existing rules with the same local root; other rules remain.
The override paths use the supplied base directory, defaulting to the current
working directory. Pass a mapper as core `Xdebug` option `pathMappings` to reuse it.
