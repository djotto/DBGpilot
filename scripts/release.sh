#!/usr/bin/env bash
set -euo pipefail

# Build and validate a local JS candidate. Uploads remain a separate step.
release_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$release_root"
exec npm run check:package -- "$@"
