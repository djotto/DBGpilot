# Other Python / Xdebug options

Research date: 2026-10-26. Searched GitHub repository metadata and PyPI, then
cloned the relevant sources into temporary directories for inspection. That
survey did not install dependencies. Komodo, Pugdebug, and Vdebug were subsequently
packaged as development references, then removed after DBGpilot's independent
suite passed.
Commit dates below describe the checked
source, rather than GitHub's repository `pushed_at` timestamp, which can change
without a new commit on the default branch.

## Strongest additional leads

### ActiveState / Komodo's IDE-side DBGp controller

Source: [agroszer/komodo-python3-dbgp](https://github.com/agroszer/komodo-python3-dbgp),
commit `aa277c0055dffb597777bba49d4eb65d30af02a0`, 2019-01-25.

Correction to the earlier search: this package contains more than a Python
debugging engine. Its `dbgp/server.py` and `dbgp/serverBase.py` implement the
IDE-side controller that could talk to Xdebug. The Python components are MIT
licensed.

It has broader protocol coverage than Vdebug: separate handling of stream,
response, and notification packets; transaction-ID response queues; per-session
reader threads; multiple applications/sessions; property paging; full-value
retrieval; property mutation; frame-aware inspection; source retrieval; and
breakpoint management. These findings come from source inspection, not a
complete conformance test.

The package imported and its manager instantiated under the harness's Python
3.13.5. However, direct socket-pair checks of the controller reproduced:

```text
send: TypeError: a bytes-like object is required, not 'str'
receive: TypeError: can only concatenate str (not "bytes") to str
```

The code also calls old APIs such as `base64.encodestring` and
`base64.decodestring`. It is an interesting controller architecture or porting
candidate, rather than a tested current-Python dependency.

Primary files:
[server.py](https://github.com/agroszer/komodo-python3-dbgp/blob/aa277c0055dffb597777bba49d4eb65d30af02a0/dbgp/server.py),
[serverBase.py](https://github.com/agroszer/komodo-python3-dbgp/blob/aa277c0055dffb597777bba49d4eb65d30af02a0/dbgp/serverBase.py).

### Pugdebug, Mte90 fork

Source: [Mte90/pugdebug](https://github.com/Mte90/pugdebug),
commit `d07044536f0bd5ab3cef3d178cc35a2e51e0e7a2`, 2021-03-11.
[PyPI](https://pypi.org/project/pugdebug/) lists version 1.1.1, released on
2021-03-11. The original
[robertbasic/pugdebug](https://github.com/robertbasic/pugdebug) is archived and
directs readers to this fork.

This is a standalone Python GUI debugger, not a plugin for another editor. The
fork explicitly targets Xdebug 3 and defaults to port 9003. It supports basic
debugging and queues additional incoming PHP connections for later debugging.

Its server and connection classes depend on PyQt5 threads, signals, and settings.
Its command helper still performs a send followed by one receive. It does not
provide a separate stream/notification dispatcher there. Its property parser
reads attribute-based properties and does not decode extended-property name,
fullname, and value elements. This is a source-level assessment; the GUI and
live debugging were not run in this survey. GPL-3.0 licensing.

Primary file:
[server.py](https://github.com/Mte90/pugdebug/blob/d07044536f0bd5ab3cef3d178cc35a2e51e0e7a2/pugdebug/server.py).

## Other clients inspected

| Project | Checked source | Assessment |
| --- | --- | --- |
| [SublimeTextXdebug](https://github.com/martomo/SublimeTextXdebug) | `7b62975`, 2019-12-01 | MIT-licensed Python client with a separate protocol module, but the module imports Sublime configuration/logging helpers and session handling is editor-oriented. Source still uses one send/read cycle and text-oriented framing. Extraction and transport work would be required. |
| [Gedit DBGp plugin](https://github.com/addiks/gedit-dbgp-plugin) | `17db3f1`, 2017-07-18 | Python 3; supports proxies, conditional breakpoints, path mappings, property mutation, and stepping. DebugSession directly imports Gtk/GLib and integrates UI updates into debugger operations. GPL-3.0. |
| [cleandebug](https://github.com/fabsor/cleandebug) | `a53e2af`, 2012-03-11 | Small protocol implementation with ncurses UI. Legacy `SocketServer` import and string-based socket operations need Python 3 changes. Much narrower coverage than Komodo. |
| [PyXdebugClient](https://github.com/artbek/PyXdebugClient) | `54f9c53`, 2012-10-05 | Small threaded GUI client. Its main engine fails Python 3 syntax parsing due to Python 2 print statements. |
| [dbgp-client](https://github.com/ytrstu/dbgp-client) | `d61c3bc`, 2012-11-08 | Older Vim client. The Python file fails current syntax parsing with inconsistent indentation. |
| [DBGPavim](https://github.com/brookhong/DBGPavim) | Public README / prior survey | Another legacy Vim/Python client. Documented tested environments use Python 2 and Xdebug 2. |

## Related results that are not substitutes

- [CaptKrisp/DBGpProxy](https://github.com/CaptKrisp/DBGpProxy), commit `8ab7c31`
  dated 2026-06-25, is a recent Python 3 port of an old ActiveState proxy. Its
  author reports testing the proxy with Python 3.11. This routes debugger
  connections; that is not the same as a working debugger controller. It also
  ships old controller files, whose receive path still mixes strings and bytes.
- [xdebugtoolkit](https://github.com/AlexeyKupershtokh/xdebugtoolkit) analyzes
  cachegrind profiling files. It does not provide interactive step debugging.
- [dbgp on PyPI](https://pypi.org/project/dbgp/) has a 2010 release and points to
  the old pydbgp project; it is not evidence of a current client library.
- Searching newer Xdebug MCP projects found Go, PHP, TypeScript, and JavaScript
  implementations, but no clear modern Python DBGp client suited to this
  harness. This is a search result, not a claim that none exists anywhere.

## Direction for the harness

For Python-only protocol handling, Komodo is the strongest additional reference
for architectural completeness, and Pugdebug is the clearest extra example
explicitly updated for Xdebug 3. Both require adaptation before use in our
headless harness.

An alternative is to write a Python DAP client around the
[PHP Debug Adapter](https://github.com/xdebug/vscode-php-debug). That keeps
Playwright and orchestration in Python while delegating DBGp to a Node-based
adapter. It adds a process and protocol layer. This path was not implemented or
tested in this survey. See the
[DAP overview](https://microsoft.github.io/debug-adapter-protocol/overview).
