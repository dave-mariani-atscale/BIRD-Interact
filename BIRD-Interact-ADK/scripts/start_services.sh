#!/usr/bin/env bash
# Starts the three microservices once; they stay up across multiple eval runs.
# The environment backend ("raw", "atscale", ...) is NOT set here — it's a
# --backend flag on `orchestrator.runner`, pushed to these already-running
# services via their /set_backend endpoint at the start of each run. No
# restart needed to switch backends between runs.
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export no_proxy="${no_proxy:-127.0.0.1,localhost}"

# Project-local environments win over an ambient conda env: CONDA_PREFIX stays set
# even after `source .venv-adk/bin/activate`, so checking it first silently runs the
# services on the base conda interpreter, which lacks this project's dependencies.
PYTHON_BIN="python"
if [ -x "$PROJECT_DIR/.conda-py310/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.conda-py310/bin/python"
elif [ -x "$PROJECT_DIR/.venv-adk/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv-adk/bin/python"
elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "${CONDA_PREFIX}/bin/python" ]; then
    PYTHON_BIN="${CONDA_PREFIX}/bin/python"
fi

HOST="${SERVICE_HOST:-127.0.0.1}"

pkill -f uvicorn 2>/dev/null || true
sleep 2
# TERM is delivered through the event loop, and a service whose loop is frozen
# never processes it — the survivor keeps its LISTEN socket, later starts race
# it for accepts, and new runs land on stale code. Seen live 2026-08-27: three
# system_agent processes on port 6000. Force-kill whatever TERM didn't stop.
if pgrep -f uvicorn >/dev/null 2>&1; then
    pkill -9 -f uvicorn 2>/dev/null || true
    sleep 1
fi

# Start all three microservices.
# BIRD_LLM_ROLE tags this process's rows in the LLM usage log
# (settings.llm_usage_path) so a run's spend can be split between the agent
# under test and the user simulator. Without it both read "unknown" and are only
# separable by model name — which fails as soon as they share a model. Each
# service makes calls in exactly one role, so the tag is per process.
# nohup + a persisted log per service: a bare `&` ties each service to the
# launching terminal (closing it SIGHUPs all three, and every later run fails
# with "All connection attempts failed"), and without the redirect a crash
# leaves no trace on disk. Both failure modes have voided scored runs.
mkdir -p "$PROJECT_DIR/logs"
BIRD_LLM_ROLE=system_agent nohup "$PYTHON_BIN" -m uvicorn system_agent.server:app --host "$HOST" --port 6000 --log-level warning >> "$PROJECT_DIR/logs/system_agent.out" 2>&1 &
BIRD_LLM_ROLE=user_sim nohup "$PYTHON_BIN" -m uvicorn user_simulator.server:app --host "$HOST" --port 6001 --log-level warning >> "$PROJECT_DIR/logs/user_simulator.out" 2>&1 &
BIRD_LLM_ROLE=db_environment nohup "$PYTHON_BIN" -m uvicorn db_environment.server:app --host "$HOST" --port 6002 --log-level warning >> "$PROJECT_DIR/logs/db_environment.out" 2>&1 &

# Wait for all three to be healthy
for i in $(seq 1 30); do
    if curl --noproxy '*' -s "http://127.0.0.1:6000/health" > /dev/null 2>&1 && \
       curl --noproxy '*' -s "http://127.0.0.1:6001/health" > /dev/null 2>&1 && \
       curl --noproxy '*' -s "http://127.0.0.1:6002/health" > /dev/null 2>&1; then
        echo "ALL_SERVICES_READY (ports 6000, 6001, 6002)"
        exit 0
    fi
    sleep 1
done
echo "SERVICES_FAILED"
exit 1
