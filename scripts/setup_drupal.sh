#!/usr/bin/env bash
set -euo pipefail

dbgpilot_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$dbgpilot_root"
ddev start

cd "$dbgpilot_root/fixtures/drupal11"
ddev start
ddev exec composer install --no-interaction --prefer-dist
ddev fixture-setup
