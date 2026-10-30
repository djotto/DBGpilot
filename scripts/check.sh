#!/usr/bin/env bash
set -euo pipefail

ddev drupal-setup
ddev test-setup
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run check:all
