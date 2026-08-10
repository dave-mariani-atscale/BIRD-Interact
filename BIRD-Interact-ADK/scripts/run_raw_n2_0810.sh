#!/usr/bin/env bash
# Two more raw-backend replicates, to be pooled with the existing n=1
# (results/etf_raw_full_0806.json) for a raw n=3. Harness config verified
# identical to that run: mode a-interact, submit_feedback_level shape,
# grading_tie_tolerance/honor_decimal true, casefold false,
# free_wasted_actions true, system agent claude-sonnet-5.
#
# Waits for the atscale re-baseline driver to exit before starting, so the
# two arms never contend for the services.
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
source .venv-adk/bin/activate

echo "=== waiting for run_prompts_n3_0810.sh to finish ==="
while pgrep -f "run_prompts_n3_0810.sh" > /dev/null; do sleep 20; done
echo "=== atscale driver gone $(date); starting raw ==="

if [ ! -s results/rebase0810_atscale_r3.json ]; then
  echo "ABORT: rebase0810_atscale_r3.json missing/empty - atscale run did not complete"
  exit 1
fi

for i in 2 3; do
  echo "=== raw replicate $i start $(date) ==="
  python -m orchestrator.runner --mode a-interact --backend raw --query-only \
    --databases exchange_traded_funds \
    --output "results/raw0810_r${i}.json" \
    > "results/raw0810_r${i}.log" 2>&1
  echo "=== raw replicate $i done $(date) ==="
done
echo ALL DONE RAW
