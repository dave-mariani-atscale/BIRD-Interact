#!/usr/bin/env bash
# Run BIRD-Interact evaluation.
# Usage:
#   bash scripts/run_eval.sh --mode a-interact --concurrency 3
#   bash scripts/run_eval.sh --mode c-interact --concurrency 5
#   bash scripts/run_eval.sh --mode oracle --concurrency 5
#   bash scripts/run_eval.sh --mode a-interact --limit 10
#   bash scripts/run_eval.sh --mode a-interact --backend atscale --databases solar_panel --limit 5
#
# --backend (default "raw") is handled entirely by orchestrator.runner, which
# pushes it to the already-running services via /set_backend — no service
# restart needed to switch backends between runs.

set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

# Start services if not running
if ! curl --noproxy '*' -s "http://127.0.0.1:6000/health" > /dev/null 2>&1; then
    echo "Starting services..."
    bash "$PROJECT_DIR/scripts/start_services.sh"
fi

# Run evaluation
python -m orchestrator.runner "$@"
