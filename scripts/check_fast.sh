#!/usr/bin/env bash
set -euo pipefail

# Run in the supported Python environment selected by Poetry. Needs loopback
# TCP but no PHP, browser, Drupal fixture or Docker. No CI-provider assumptions.
fast_report=${1:-test-results/fast-junit.xml}
poetry check --lock --strict
poetry run pytest -m 'not integration' --junitxml="$fast_report"
