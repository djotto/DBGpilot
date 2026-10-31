# Final Python-to-JavaScript test audit

Reference: [`f3ce1ec`](https://github.com/djotto/DBGpilot/tree/f3ce1ecb654137cc356b3a49f3f966d67db6ed8e).
Audited on 2026-10-31: **34 files, 309 named test-function families**.
Parametrized instances and generated examples are not counted as separate families.

The [case-by-case ledger](migration-audit.json) records every archived function,
its disposition, JS evidence paths and the reason for adapting/retiring/deferring it.
Paths identify the relevant test families; they do not assert identical test counts,
wire/API naming, framework behaviour or every old workload parameter.

| Disposition | Families | Meaning |
| --- | ---: | --- |
| covered | 87 | Retained PHP/DBGp invariant has JS regression evidence. |
| adapted | 89 | Behaviour retained with explicit JS lifetime/value/API differences or retired subparts. |
| retired | 116 | Removed Python/HTTP/framework/non-Xdebug contract; reason recorded per function. |
| deferred | 17 | Feasible optional capability awaiting demonstrated need or a scope decision. |

## Remaining gates

- The target environment is unavailable on this machine. Its install/network/path-map
  acceptance check remains outstanding; isolated local consumer validation does not
  substitute for it.
- Proxy support, automatic TOML discovery and the shared browser diagnostics helper
  remain deferred as recorded in [migration exceptions](migration-exceptions.md).
- No new JavaScript GitHub release or registry publication is implied by this audit.

The previously partial protocol, values, binary evaluation, session, conformance and
review rows are reconciled. New regressions include seeded binary fragmentation,
large integer/JSON fidelity, standard/extended/typemap empty values, binary eval and
assignment, metadata validation, stop EOF boundaries, late breakpoint mutations,
init/vendor metadata, postmortem capability guards, listener admission/startup/waits
and snapshot validation before any engine command.
