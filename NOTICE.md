# DBGpilot provenance

DBGpilot is an original implementation by DBGpilot contributors, distributed
under the MIT license in LICENSE. Its runtime uses the Python standard library.
No third-party debugger implementation, engine binary, PHP/Drupal fixture,
downloaded vendor tree or reference project is part of its distributions.

The DBGp specification and public implementations were consulted as design
and interoperability references, without copying or importing their code:

- DBGp 1.0 draft 22: https://xdebug.org/docs/dbgp
- Xdebug implementation: https://github.com/xdebug/xdebug
- Vdebug: https://github.com/vim-vdebug/vdebug
- Komodo Python DBGp: https://github.com/agroszer/komodo-python3-dbgp
- Pugdebug: https://github.com/Mte90/pugdebug

Poetry/poetry-core are build tools. pytest, Hypothesis and Playwright are
optional development/validation tools. PHP, Xdebug, dbgpProxy, Drupal, Composer
and their downloaded dependencies retain their own licensing and are external
test tooling. The optional-engine investigation downloads its pinned candidate
outside the package and adds no runtime dependency.

This candidate is not published. The source distribution contains the package's
Python sources, maintained documentation, examples and validation scripts.
Source-hosting and publication URLs will be supplied by the release operator
once those destinations are established.
