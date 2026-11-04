#!/usr/bin/env bash
# Start the three services on the ports named in this checkout's .env (SYSTEM_AGENT_PORT,
# USER_SIM_PORT, DB_ENV_PORT), stopping only processes on THOSE ports. start_services.sh
# runs `pkill -f uvicorn`, which kills every harness on the machine; use this one when a
# second checkout (a git worktree) runs beside another session's services.
#   bash scripts/start_services_isolated.sh          # start (restart) this checkout's services
#   bash scripts/start_services_isolated.sh --stop   # stop them
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}" no_proxy="${no_proxy:-127.0.0.1,localhost}"
port(){ grep -E "^$1=" .env | tail -1 | cut -d= -f2; }
SA=$(port SYSTEM_AGENT_PORT); US=$(port USER_SIM_PORT); DB=$(port DB_ENV_PORT)
[ -n "$SA" ] && [ -n "$US" ] && [ -n "$DB" ] || { echo "set SYSTEM_AGENT_PORT, USER_SIM_PORT, DB_ENV_PORT in .env"; exit 1; }
for p in $SA $US $DB; do pkill -f "uvicorn .*--port $p( |$)" 2>/dev/null || true; done
sleep 2
[ "${1:-}" = "--stop" ] && { echo "stopped services on $SA $US $DB"; exit 0; }
PY="$PROJECT_DIR/.venv-adk/bin/python"
HOST="${SERVICE_HOST:-127.0.0.1}"
mkdir -p logs
BIRD_LLM_ROLE=system_agent nohup "$PY" -m uvicorn system_agent.server:app --host "$HOST" --port "$SA" --log-level warning >> logs/system_agent.out 2>&1 &
BIRD_LLM_ROLE=user_sim nohup "$PY" -m uvicorn user_simulator.server:app --host "$HOST" --port "$US" --log-level warning >> logs/user_simulator.out 2>&1 &
BIRD_LLM_ROLE=db_environment nohup "$PY" -m uvicorn db_environment.server:app --host "$HOST" --port "$DB" --log-level warning >> logs/db_environment.out 2>&1 &
for i in $(seq 1 60); do
  ok=0; for p in $SA $US $DB; do curl --noproxy '*' -s "http://127.0.0.1:$p/health" >/dev/null 2>&1 && ok=$((ok+1)); done
  [ $ok -eq 3 ] && { echo "SERVICES_READY (ports $SA, $US, $DB)"; exit 0; }
  sleep 2
done
echo "services did not come up; see logs/*.out"; exit 1
