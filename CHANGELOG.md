# Changelog

## JavaScript 0.1.0 — unreleased

- Port real-Xdebug stepping, hit-count/temporary breakpoint, stdout routing and
  evaluation-error recovery tests across all six PHP/Xdebug combinations. Add
  `test:integration` to the full check command and share live runtime profiles.

- Port feature negotiation safeguards: discover command support, expose cached
  capability helpers, preserve encoding/base64 requirements, tolerate unsupported
  optional settings and retain late feature replies.

- Replace the Python controller with the Playwright fixture and same-process Node core.
- Include CJS/ESM exports, TypeScript declarations, request capture, PHP value and
  source mapping APIs, bounded event queues and automatic session cleanup.
- Migrate PHP/browser, Drupal, runtime compatibility and stress coverage; preserve
  pending scenario audits and deferred capabilities in MIGRATION.md and docs/.
- Make the repository root directly installable from GitHub. Replace Poetry and
  pytest setup/check tools with Node and Playwright commands.
- Preserve Python 0.1.1 on [archive/python](https://github.com/djotto/DBGpilot/tree/archive/python).
  Unpublish both Python testing releases as drafts, retaining assets and tags.

Historical Python changes are in the [archive changelog](https://github.com/djotto/DBGpilot/blob/archive/python/CHANGELOG.md).
