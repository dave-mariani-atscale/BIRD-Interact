#!/usr/bin/env bash
# n=1 two-arm re-baseline, all 19 ETF Query tasks, under the 2026-08-11 flag set:
#   SUBMIT_FEEDBACK_LEVEL=none  GRADING_TIE_TOLERANCE=false
#   GRADING_HONOR_DECIMAL=true  FREE_WASTED_ACTIONS=false
#   SEMANTIC_LAYER_KNOWLEDGE_TOOLS=false
#
# WHY BOTH ARMS. feedback=none and free_wasted=false change what the agent DOES,
# so unlike the two grading flags they cannot be recovered by re-grading a
# finished run offline. Every prior number (raw 0.321 / atscale 0.426 / +0.105)
# was taken under shape feedback and free_wasted=true and is stale on both
# sides. Comparing a new atscale run to the old raw baseline would report a lift
# that is real in neither direction, so the denominator has to be re-measured
# too.
#
# KB tools stay OFF here deliberately: this run's job is to isolate the flag
# flip, and every atscale number in the history was taken with them off. The
# SEMANTIC_LAYER_KNOWLEDGE_TOOLS A/B is a separate, atscale-only run measured
# against the baseline this one establishes (tracker B-12).
#
# Sequential, never parallel: the two arms share one set of services and one
# MCP server, and the runner pushes the backend to the running services with
# /set_backend at startup — a second run would retarget the first one's tools
# mid-flight.
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
source .venv-adk/bin/activate

# atscale first: it is the arm with an external dependency (local MCP on :3003),
# so if anything is misconfigured it fails before the raw arm spends anything.
echo "=== atscale start $(date) ==="
python -m orchestrator.runner --mode a-interact --backend atscale \
  --databases exchange_traded_funds \
  --output results/rebase0811_atscale_r1.json \
  > results/rebase0811_atscale_r1.log 2>&1
echo "=== atscale done $(date) ==="

if [ ! -s results/rebase0811_atscale_r1.json ]; then
  echo "ABORT: atscale output missing/empty; not starting raw"
  exit 1
fi

# --query-only for parity: the atscale arm drops Management-category tasks
# structurally (semantic layers are read-only), so the raw arm must drop the
# same ones or the two totals are over different task sets.
echo "=== raw start $(date) ==="
python -m orchestrator.runner --mode a-interact --backend raw --query-only \
  --databases exchange_traded_funds \
  --output results/rebase0811_raw_r1.json \
  > results/rebase0811_raw_r1.log 2>&1
echo "=== raw done $(date) ==="
echo ALL DONE
