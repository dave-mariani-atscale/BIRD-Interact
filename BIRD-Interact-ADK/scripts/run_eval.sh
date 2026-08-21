#!/usr/bin/env bash
# Run BIRD-Interact evaluation.
# Usage:
#   bash scripts/run_eval.sh --mode a-interact --concurrency 3
#   bash scripts/run_eval.sh --mode c-interact --concurrency 5
#   bash scripts/run_eval.sh --mode oracle --concurrency 5
#   bash scripts/run_eval.sh --mode a-interact --limit 10
#   bash scripts/run_eval.sh --mode a-interact --backend atscale --databases solar_panel --limit 5
#
# For a HEAD-TO-HEAD comparison, pass --query-only to BOTH arms. A non-raw
# backend always excludes the Management (DDL/DML) tasks because a semantic
# layer is read-only; without --query-only the raw arm also runs them, so the
# two arms score over different task sets and their headline numbers are not
# comparable:
#   bash scripts/run_eval.sh --mode a-interact --backend raw     --query-only --databases households --repeat 3
#   bash scripts/run_eval.sh --mode a-interact --backend atscale --query-only --databases households --repeat 3
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

# Resolve the interpreter exactly as start_services.sh does.  Bare `python` is
# whatever the shell resolves - a pyenv shim, say - which does not have this
# project's dependencies, so the runner dies on `ModuleNotFoundError: httpx`
# while the services keep running fine on .venv-adk.  Project-local
# environments win over an ambient conda env for the reason given in
# start_services.sh.
PYTHON_BIN="python"
if [ -x "$PROJECT_DIR/.conda-py310/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.conda-py310/bin/python"
elif [ -x "$PROJECT_DIR/.venv-adk/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv-adk/bin/python"
elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "${CONDA_PREFIX}/bin/python" ]; then
    PYTHON_BIN="${CONDA_PREFIX}/bin/python"
fi

if ! "$PYTHON_BIN" -c 'import httpx' 2>/dev/null; then
    echo "FAIL: $PYTHON_BIN cannot import httpx - it is not this project's" >&2
    echo "      environment.  Create .venv-adk and pip install -r requirements.txt," >&2
    echo "      or activate the environment the services are running on." >&2
    exit 1
fi

# Run evaluation
"$PYTHON_BIN" -m orchestrator.runner "$@"
