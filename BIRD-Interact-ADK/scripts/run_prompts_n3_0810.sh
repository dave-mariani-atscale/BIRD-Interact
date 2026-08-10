#!/usr/bin/env bash
# n=3 re-baseline of the prompt-only ETF model of record (backend atscale),
# after the masked-KB flag removal (fdf78fc/28169a0). Prior baseline
# ab19_0806ab19_atscale_r{1,2,3} is stale.
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
source .venv-adk/bin/activate
for i in 1 2 3; do
  echo "=== replicate $i start $(date) ==="
  python -m orchestrator.runner --mode a-interact --backend atscale \
    --databases exchange_traded_funds \
    --output "results/rebase0810_atscale_r${i}.json" \
    > "results/rebase0810_atscale_r${i}.log" 2>&1
  echo "=== replicate $i done $(date) ==="
done
echo ALL DONE
