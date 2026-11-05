#!/usr/bin/env bash
# One launcher for the three Databricks scenarios of the AtScale comparison, each run n=1 and compared like
# for like with the 2026-09-10 AtScale n=3 sweep (results/full0910_atscale_run0[1-3]_*.json; workbook tab
# "Modified Harness 09-10 Sonnet"), whose BEST run (r3) is the headline baseline:
#
#   1 | metric-views-agent : Metric Views + 3rd-party agent   (backend dbx_metric_views)
#   2 | genie-space        : Metric Views + Genie Agent        (backend dbx_genie_space, one Genie space per database)
#   3 | genie-ontology     : Metric Views + Genie Ontology     (backend dbx_genie_ontology, Genie One as the owner;
#                                                              the ontology picks metric views, base tables or anything else)
#
# Matched to the sweep: Sonnet 5 agent and simulator, a-interact, all 410 Query tasks, non-leaderboard
# corrected grading (the same six corrections), default LLM routing, and the 09-10 atscale instruction with
# only the tool-specific lines rewritten (config/environment_backends.dbx_vs_0910.yaml). Concurrency
# defaults to 3 (the Genie API rate-limits). Runs on this checkout's .env service ports, which must not be
# the shared harness's 6000-6002.
#
#   bash scripts/run_databricks_scenario.sh 3                     # foreground, one repetition
#   REPEAT=3 bash scripts/run_databricks_scenario.sh 3            # three repetitions (n=3), run back to back
#   mkdir -p logs && nohup bash scripts/run_databricks_scenario.sh genie-ontology > logs/scenario3_launcher.log 2>&1 &
#
# Writes results/<backend>_vs_0910/<backend>[_runNN]_<stamp>.json (one per repetition), live_compare.txt (every
# 10 min, for the repetition in progress), final_compare[_runNN].txt,
# and for every scenario the per-database four-way table (scripts/four_way_by_db.py) to four_way.md.
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
unset LEADERBOARD_MODE LEADERBOARD_AGENT_MODEL LEADERBOARD_TRACK LLM_ROUTING_FILE BIRD_LLM_DUMP_DIR SYSTEM_AGENT_MAX_TOKENS DISABLE_AGGREGATES
export ENVIRONMENT_BACKENDS_FILE=config/environment_backends.dbx_vs_0910.yaml
PY=.venv-adk/bin/python
SCEN="${1:?usage: run_databricks_scenario.sh <1|2|3|metric-views-agent|genie-space|genie-ontology>}"
BACKEND=$($PY -c "from shared.environment_backends import resolve_databricks_scenario as r; print(r('$SCEN'))") || exit 2
LABEL=$($PY -c "from shared.environment_backends import DATABRICKS_SCENARIO_LABELS as L; print(L['$BACKEND'])")
OUT=results/${BACKEND}_vs_0910; LOGD=logs/${BACKEND}_vs_0910; mkdir -p "$OUT" "$LOGD"
LOG="$LOGD/$BACKEND.log"
BASE='results/full0910_atscale_run0[123]_*.json'
step(){ echo; echo "=== $(date +%H:%M:%S) $* ==="; }
port(){ grep -E "^$1=" .env | tail -1 | cut -d= -f2; }

step "$LABEL (backend $BACKEND)"
step "preflight"
SA=$(port SYSTEM_AGENT_PORT); echo "  service ports: $SA $(port USER_SIMULATOR_PORT) $(port DB_ENVIRONMENT_PORT)"
[ -n "$SA" ] && [ "$SA" != "6000" ] || { echo "REFUSING: set this checkout's .env ports off the shared 6000-6002"; exit 1; }
ls $BASE >/dev/null 2>&1 || { echo "REFUSING: baseline files missing: $BASE"; exit 1; }
dscacheutil -q host -a name api.anthropic.com | grep -q ip_address || { echo "REFUSING: api.anthropic.com does not resolve"; exit 1; }
s=$(docker inspect -f '{{.State.Status}}' bird_interact_postgresql_full 2>/dev/null); echo "  BIRD postgres: $s"; [ "$s" = running ] || exit 1
BACKEND=$BACKEND $PY - <<'PYEOF' || exit 1
import asyncio, os
from shared.config import settings
from shared.databricks_auth import resolve_token
from shared.databricks_sql import DatabricksSQL
from shared.environment_backends import get_configured_domains, get_domain_config
b = os.environ["BACKEND"]
r = DatabricksSQL().execute("SELECT COUNT(DISTINCT table_schema), COUNT(*) FROM bird.information_schema.tables WHERE table_type='METRIC_VIEW'")
assert not r.error, r.error
doms = get_configured_domains(b)
print("  metric views:", r.rows[0][1], "in", r.rows[0][0], "schemas; domains:", len(doms))
assert tuple(r.rows[0]) == (22, 119) and len(doms) == 22
if b == "dbx_genie_space":
    spaces = [get_domain_config(b, d).get("space_id") for d in doms]
    assert all(spaces), "every domain needs a space_id (scripts/provision_genie_spaces.py)"
    print("  Genie spaces:", len(spaces))
if b == "dbx_genie_ontology":
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from system_agent.tools_genie_one import GENIE_ONE_MCP_PATH
    assert all(get_domain_config(b, d)["objects"] == "any" for d in doms), "scenario 3 domains must be objects: any"
    async def tools():
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {resolve_token(None)}"}, timeout=60, trust_env=False) as h:
            async with streamable_http_client(settings.databricks_host.rstrip("/") + GENIE_ONE_MCP_PATH, http_client=h) as st:
                async with ClientSession(st[0], st[1]) as s:
                    await s.initialize()
                    return [t.name for t in (await s.list_tools()).tools]
    names = asyncio.run(tools())
    print("  Genie One MCP tools:", names)
    assert "genie_ask" in names and "genie_poll_response" in names
PYEOF

step "services"
bash scripts/start_services_isolated.sh || exit 1
H=$(curl -s "http://127.0.0.1:$SA/health"); echo "$H"
echo "$H" | grep -q '"model":"anthropic/claude-sonnet-5"' || { echo "REFUSING: agent is not Sonnet 5"; exit 1; }
echo "$H" | grep -q '"leaderboard_mode":false' || { echo "REFUSING: leaderboard mode on"; exit 1; }
[ -f "$LOG" ] && mv "$LOG" "$LOG.prev-$(date +%Y%m%d_%H%M%S)"

step "live comparison every 10 minutes"
( while sleep 600; do
    # Only the repetition in progress: the log section after its "=== repetition k of n ===" marker.
    awk '/=== repetition [0-9]+ of [0-9]+ ===/{buf=""; rep=$0} {buf=buf $0 "\n"} END{printf "%s", buf}' "$LOG" > "$OUT/live_rep.log"
    $PY scripts/compare_vs_baseline_runs.py --log "$OUT/live_rep.log" --baseline "$BASE" --audit results/grading_audit.jsonl --backend "$BACKEND" > "$OUT/live_compare.tmp" 2>/dev/null \
      && { echo "updated $(date '+%Y-%m-%d %H:%M') $(grep -o 'repetition [0-9]* of [0-9]*' "$OUT/live_rep.log" | tail -1)"; cat "$OUT/live_compare.tmp"; } > "$OUT/live_compare.txt"
    $PY scripts/four_way_by_db.py > "$OUT/four_way.tmp" 2>/dev/null && mv "$OUT/four_way.tmp" "$OUT/four_way.md"
  done ) &
WATCH=$!

step "$BACKEND: 410 Query tasks, concurrency ${CONCURRENCY:-3}, ${REPEAT:-1} repetition(s)"
$PY -m orchestrator.runner --mode a-interact --databricks-scenario "$SCEN" --query-only --concurrency "${CONCURRENCY:-3}" --repeat "${REPEAT:-1}" \
    --output "$OUT/$BACKEND.json" > "$LOG" 2>&1
rc=$?
kill $WATCH 2>/dev/null
echo "  runner exit $rc; files: $(ls -1 $OUT/${BACKEND}_*.json 2>/dev/null | tr '\n' ' ')"

step "final comparison (each repetition)"
FILES=$(ls -1tr $OUT/${BACKEND}_*.json 2>/dev/null | tail -${REPEAT:-1})
if [ -n "$FILES" ]; then
  for R in $FILES; do
    tag=$(basename "$R" .json | grep -o '_run[0-9][0-9]' || true)
    echo "--- $R"
    $PY scripts/compare_vs_baseline_runs.py --results "$R" --baseline "$BASE" --audit results/grading_audit.jsonl | tee "$OUT/final_compare${tag}.txt"
  done
else
  $PY scripts/compare_vs_baseline_runs.py --log "$LOG" --baseline "$BASE" --audit results/grading_audit.jsonl --backend "$BACKEND" | tee "$OUT/final_compare.txt"
fi
$PY scripts/four_way_by_db.py | tee "$OUT/four_way.md"
bash scripts/start_services_isolated.sh --stop
