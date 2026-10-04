#!/usr/bin/env bash
# From a fresh clone to the published tables. Needs bun and python3; no API keys.
set -euo pipefail
cd "$(dirname "$0")/.."

(cd scorer && bun install --frozen-lockfile && bun test)
bun test ./scripts

echo
python3 scripts/verify.py
echo
echo "Scorer audit:"
bun scripts/scorer_audit.ts
echo
echo "Paired bootstrap:"
python3 scripts/bootstrap.py
echo
echo "Calibration of the last-pass routes:"
python3 scripts/calibrate.py
echo
echo "Error analysis:"
bun scripts/error_analysis.ts --check
echo
python3 scripts/error_reading.py
