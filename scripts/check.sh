#!/usr/bin/env bash
set -euo pipefail

ddev drupal-setup
ddev test-setup
ddev exec env DBGPILOT_REQUIRE_DRUPAL=1 /mnt/ddev_config/commands/web/poetry run pytest --junitxml=test-results/junit.xml
ddev poetry run python scripts/check_distribution.py --live-php --live-browser --suite-junit test-results/junit.xml
