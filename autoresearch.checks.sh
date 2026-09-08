#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# Correctness backpressure: full suite (includes the contract-drift gate that
# single-sources exit codes / cache envelope / trust rule from fetch_pricing.py)
# plus smoke of every offline read action. Suppress success noise.
python3 -m unittest discover -s tests 2>&1 | tail -15

# Offline smoke. Exit-code contract (FR-008): 0 fresh, 1 stale/degraded,
# 2 = no data / not found = failure. JSON must always parse.
# The review queue is empty: every model either inherits a catalog price or
# carries an attestation, so `list`/`fresh` exit 0. If one of these starts
# exiting 1, a price went unattested or a pin stopped resolving — investigate
# rather than relaxing the expectation back to 1.
smoke() {  # smoke <expected-0-or-1> <args...>
  local expect="$1"; shift
  local out code
  out=$(python3 fetch_pricing.py "$@" 2>/dev/null) && code=0 || code=$?
  [ "$code" -ne 2 ] || { echo "checks: exit 2 (no data) from: $*"; exit 1; }
  [ "$code" -eq "$expect" ] || { echo "checks: exit $code (want $expect) from: $*"; exit 1; }
  python3 -c 'import json,sys; json.load(sys.stdin)' <<< "$out"
}
smoke 0 query price gpt-4o --offline
smoke 0 query list --offline
smoke 0 query fresh --offline
smoke 0 query cheapest gpt-4o --offline
echo "checks: suite + offline smoke OK"