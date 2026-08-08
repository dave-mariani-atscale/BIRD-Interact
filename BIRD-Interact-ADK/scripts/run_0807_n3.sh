#!/usr/bin/env bash
# n=3 benchmark of the one-shot ETF_0807 model (backend atscale_0807).
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
source .venv-adk/bin/activate
for i in 1 2 3; do
  echo "=== replicate $i start $(date) ==="
  python -m orchestrator.runner --mode a-interact --backend atscale_0807 \
    --databases exchange_traded_funds \
    --output "results/ab0807_etf0807_r${i}.json" \
    > "results/ab0807_etf0807_r${i}.log" 2>&1
  echo "=== replicate $i done $(date) ==="
done
echo ALL DONE
