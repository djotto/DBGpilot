# Provenance

This JavaScript implementation derives from DBGpilot's original MIT-licensed
Python debugger and the supplied reduced JavaScript port. Copyright notices and
license terms are in LICENSE. The source repository preserves the Python
implementation on its archive/python branch as a migration reference.

The DBGp specification (https://xdebug.org/docs/dbgp), Xdebug's implementation,
and public debugger projects were consulted when developing DBGpilot. No
third-party debugger implementation or PHP/Drupal engine/application fixture
is bundled in this JavaScript package.

The runtime XML parser is fast-xml-parser (MIT). The Playwright Test fixture
uses @playwright/test as a peer dependency (Apache-2.0). Those projects retain
their own licenses. The core entry point does not import Playwright Test.
