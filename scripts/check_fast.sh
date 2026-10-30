#!/usr/bin/env bash
set -euo pipefail

# Needs loopback TCP, but no PHP, browser, Drupal fixture or Docker.
cd "$(dirname "$0")/.."
exec npm run check:fast
