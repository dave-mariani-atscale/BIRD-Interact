#!/usr/bin/env bash
# Pre-run gate. Two independent failure modes, both of which have silently
# voided runs before, and neither of which the other detects:
#
#   1. Q-17b - a published model is materialised as a real relation by a
#      non-idempotent CREATE TABLE. list_models/explore_columns/focus_columns
#      hard-fail while run_query keeps returning CORRECT results, so the deploy
#      looks healthy while the agent is blind. Gate on list_models SUCCEEDING
#      and returning the expected model count.
#
#   2. Stale services - shared/environment_backends.py caches config in a
#      module-level dict at first load, and the uvicorn workers hold whatever
#      grading code was on disk when they started. A grading commit landing
#      after the services start is simply not in effect, and the run grades
#      under the old rules with no warning. Cost so far: the 2026-08-12
#      archeology run (0.000 live vs 0.140 on replay of its own submissions,
#      services 5h older than B-19).
#
# Usage: scripts/gate_run.sh [expected_model_count]
set -e
cd "$(dirname "$0")/.."
EXPECTED="${1:-5}"

echo "=== gate 1: services newer than the newest grading/harness commit ==="
LAST_CODE_COMMIT=$(git log -1 --format=%ct -- shared/ db_environment/ system_agent/ orchestrator/ config/)
LAST_CODE_HUMAN=$(git log -1 --format='%h %ad %s' --date=format:'%Y-%m-%d %H:%M' -- shared/ db_environment/ system_agent/ orchestrator/ config/)
PID=$(pgrep -f "uvicorn db_environment.server:app" | head -1 || true)
if [ -z "$PID" ]; then
  echo "FAIL: services are not running. Start them with scripts/start_services.sh"
  exit 1
fi
START=$(ps -p "$PID" -o lstart= | xargs)
START_EPOCH=$(date -j -f "%a %b %d %T %Y" "$START" +%s 2>/dev/null || echo 0)
echo "  newest code commit : $LAST_CODE_HUMAN"
echo "  services started   : $START (pid $PID)"
if [ "$START_EPOCH" -lt "$LAST_CODE_COMMIT" ]; then
  echo "FAIL: services predate the newest harness commit; they are running stale code."
  echo "      Restart with scripts/start_services.sh, then re-run this gate."
  exit 1
fi
echo "  OK - services are newer than the code"

echo
echo "=== gate 2: Q-17b catalog health via list_models ==="
source .venv-adk/bin/activate
PYTHONPATH=. python - "$EXPECTED" <<'PY'
import sys, re
from shared.config import settings
from shared.mcp_client import MCPClient, MCPEndpoint
expected = int(sys.argv[1])
cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                            bearer_token=settings.semantic_layer_mcp_token))
try:
    out = str(cli.call_tool("list_models", {}))
except Exception as e:
    sys.exit(f"FAIL: list_models errored ({type(e).__name__}: {str(e)[:120]}).\n"
             "      A working run_query is NOT evidence the catalog is healthy - "
             "that is exactly the Q-17b trap.")
schemas = set(re.findall(r'bird_atscale_models_catalog\w*', out))
models = sorted(set(re.findall(r'"table_schema":"bird_atscale_models_catalog_main","table_name":"([^"]+)"', out)))
print(f"  catalog schemas seen : {sorted(schemas)}")
print(f"  models in _main      : {models}")
if "bird_atscale_models_catalog" in schemas:
    sys.exit("FAIL: an UNSUFFIXED catalog copy exists alongside _main (Q-17/Catalog-suffix).")
if len(models) < expected:
    sys.exit(f"FAIL: expected >= {expected} models in _main, found {len(models)}.")
print("  OK - catalog healthy")
PY
echo
echo "GATE PASSED - safe to run"
