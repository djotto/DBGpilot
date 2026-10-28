#!/usr/bin/env bash
set -euo pipefail

# Build a local candidate with packaging/install probes. Full tests and uploads
# are separate manual steps. Pass validator options through, including --help.
release_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$release_root"
exec poetry run python scripts/check_distribution.py "$@"
