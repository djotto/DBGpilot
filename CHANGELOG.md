# Changelog

## [JavaScript 0.1.0 — testing 1](https://github.com/djotto/DBGpilot/releases/tag/js-v0.1.0-testing.1) — 2026-10-31

- Use `dbgpilot` as the package name, with `dbgpilot` and `dbgpilot/core` imports.
- Provide a Playwright Test fixture and standalone Node core for PHP/Xdebug.
- Include CommonJS/ESM exports and TypeScript declarations. Keep DBGp transport,
  packet parsing and command encoding internal to the package.
- Capture paused navigation, form submissions and AJAX requests, with snapshots,
  inspection, mutation, stepping and source mappings.
- Preserve binary strings, large integers, partial values and engine metadata.
- Check transport encodings and apply settings at startup; attempt commands
  directly and expose an uncached capability inventory through `getCapabilities()`.
- Validate inputs before sending commands, retain late replies, and release owned
  requests through bounded cleanup.
- Cover PHP/Xdebug compatibility, real browser/Drupal workflows, concurrency,
  failure recovery and clean package installation.
- Keep the retired Python implementation on
  [archive/python](https://github.com/djotto/DBGpilot/tree/archive/python).

Historical Python changes are in the [archive changelog](https://github.com/djotto/DBGpilot/blob/archive/python/CHANGELOG.md).
