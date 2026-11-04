#!/usr/bin/env bash
# Scenario 2, n=1 (prepared 2026-11-04): the Genie Ontology arm (backend dbx_genie_ontology) - the agent never
# writes SQL; it passes the user's question and clarifications verbatim to Genie One (grounded in the Genie
# Ontology) over the BASE TABLES of bird_interact and submits the SQL Genie produced - on the same 410 Query
# tasks of the 22 databases, same agent and simulator (Sonnet 5 / Sonnet 5), a-interact, NON-leaderboard
# (corrected grading), concurrency 5, one repeat. Modelled on scripts/run_dbx_vs_atscale_n1.sh; the AtScale
# engine, MCP, feedback store and aggregates play no part in this arm, so none of them is touched.
#
# The whole arm runs as the benchmark principal DATABRICKS_TOKEN_ONTOLOGY names (service principal
# bird-benchmark-ontology): SELECT on every base table, no privilege on the 119 metric views, so Genie cannot
# draw on them and the grader re-executes each submission with the same grants. Run this BEFORE the metric-view
# arms pour queries into the ontology's learning history (docs/databricks-metric-views-backend.md, scenario 2).
#
#   mkdir -p logs/dbx_ontology_n1 && nohup bash scripts/run_dbx_ontology_n1.sh > logs/dbx_ontology_n1/launcher.log 2>&1 &
#
# A Genie turn takes 20-260 s and runs on Databricks' side, so an arm is slower per task than scenario 1
# (budget ~5-8 h). Results land in results/dbx_ontology_n1/dbx_genie_ontology_run01_<stamp>.json. Set
# COMPARE_WITH=<results file of another arm> to end with scripts/compare_arms.py against it.
set -uo pipefail
cd /Users/davidmariani/workspace/atscale/BIRD-Interact/BIRD-Interact-ADK
unset LEADERBOARD_MODE LEADERBOARD_AGENT_MODEL LEADERBOARD_TRACK BIRD_LLM_DUMP_DIR SYSTEM_AGENT_MAX_TOKENS DISABLE_AGGREGATES
export ENVIRONMENT_BACKENDS_FILE=config/environment_backends.no_gold_930.yaml
export LLM_ROUTING_FILE=config/llm_routing.anthropic_timeout180.yaml
ARM=dbx_genie_ontology
CONCURRENCY="${CONCURRENCY:-5}"
OUT=results/dbx_ontology_n1
step(){ echo; echo "=== $(date +%H:%M:%S) $* ==="; }
busy(){ ps -eo args= 2>/dev/null | grep -E "(/Python|python[0-9.]*) -m orchestrator\.runner" | grep -vF grep >/dev/null; }
busy && { echo "REFUSING: a runner is active"; exit 1; }
PY=.venv-adk/bin/python

step "host: DNS, disk, containers"
dscacheutil -q host -a name api.anthropic.com | grep -q ip_address || { echo "REFUSING: api.anthropic.com does not resolve"; exit 1; }
free=$(df -g . | awk 'NR==2{print $4}'); echo "  free disk: ${free} GB"; [ "$free" -ge 12 ] || { echo "REFUSING: under 12 GB free"; exit 1; }
for c in bird_interact_postgresql_full; do
  s=$(docker inspect -f '{{.State.Status}}' $c 2>/dev/null); echo "  $c: $s"; [ "$s" = running ] || { echo "REFUSING: $c not running (gold SQL is graded on it)"; exit 1; }
done

step "databricks: the benchmark principal sees 22 schemas of base tables and NO metric view; Genie One answers"
PYTHONPATH=. $PY - <<'PYEOF' || exit 1
import asyncio, httpx
from dotenv import load_dotenv; load_dotenv(".env")
from shared.config import settings
from shared.databricks_auth import resolve_token
from shared.databricks_sql import DatabricksSQL
tok = resolve_token("DATABRICKS_TOKEN_ONTOLOGY")
sql = DatabricksSQL(token=tok)
who = sql.execute("SELECT current_user()"); assert not who.error, who.error
print(f"  principal: {who.rows[0][0]}")
r = sql.execute("SELECT table_type, COUNT(DISTINCT table_schema), COUNT(*) FROM bird_interact.information_schema.tables "
                "WHERE table_schema <> 'information_schema' GROUP BY 1 ORDER BY 1")
assert not r.error, r.error
seen = {t: (s, n) for t, s, n in r.rows}; print(f"  visible: {seen}")
assert seen.get("MANAGED", (0, 0))[0] == 22 and seen["MANAGED"][1] == 244, "REFUSING: expected 244 base tables in 22 schemas"
assert "METRIC_VIEW" not in seen, "REFUSING: the principal can see metric views - the arm would not be base-tables-only"
mv = sql.execute("SELECT COUNT(*) FROM bird_interact.solar_panel.solar_panel_plants")
assert mv.error and "INSUFFICIENT_PERMISSIONS" in mv.error, f"REFUSING: a metric view is readable by the principal: {mv.error}"
print("  metric view read refused: ok")
from system_agent.tools_genie_one import GENIE_ONE_MCP_PATH
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
async def probe():
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {tok}"}, timeout=60, trust_env=False) as hc:
        async with streamable_http_client(settings.databricks_host.rstrip("/") + GENIE_ONE_MCP_PATH, http_client=hc) as st:
            async with ClientSession(st[0], st[1]) as s:
                await s.initialize(); return sorted(t.name for t in (await s.list_tools()).tools)
tools = asyncio.run(probe()); print(f"  Genie One MCP tools: {tools}")
assert {"genie_ask", "genie_poll_response", "genie_get_query_result"} <= set(tools), "REFUSING: Genie One MCP tools missing"
PYEOF

step "backend present in $ENVIRONMENT_BACKENDS_FILE, 22 domains of base tables, token_env set"
PYTHONPATH=. $PY - <<'PYEOF' || exit 1
from shared.environment_backends import get_backend_config, get_configured_domains
b = get_backend_config("dbx_genie_ontology")
n = len(get_configured_domains("dbx_genie_ontology")); print(f"  dbx_genie_ontology: {n} domains, token_env={b.get('token_env')}")
assert n == 22 and b.get("token_env") == "DATABRICKS_TOKEN_ONTOLOGY" and b.get("executor") == "databricks"
assert all(d.get("objects") == "tables" for d in b["domains"].values())
PYEOF

step "start services (backends file: $ENVIRONMENT_BACKENDS_FILE)"
pkill -f "uvicorn" 2>/dev/null; sleep 2
bash scripts/start_services.sh 2>&1 | tail -2
for i in $(seq 1 40); do curl -s http://127.0.0.1:6000/health | grep -q healthy && curl -s http://127.0.0.1:6002/health | grep -q healthy && break; sleep 3; done
curl -s http://127.0.0.1:6000/health; echo
curl -s http://127.0.0.1:6000/health | grep -q '"model":"anthropic/claude-sonnet-5"' || { echo "REFUSING: agent is not Sonnet 5"; exit 1; }
curl -s http://127.0.0.1:6000/health | grep -q '"leaderboard_mode":false' || { echo "REFUSING: leaderboard mode is on"; exit 1; }

mkdir -p "$OUT" logs/dbx_ontology_n1
step "arm $ARM: 410 Query tasks, concurrency $CONCURRENCY"
bash scripts/run_eval.sh --mode a-interact --backend "$ARM" --concurrency "$CONCURRENCY" --repeat 1 \
     --output "$OUT/${ARM}.json" > "logs/dbx_ontology_n1/${ARM}.log" 2>&1
echo "  exit $? ; files: $(ls -1 $OUT/${ARM}_run*.json 2>/dev/null | tr '\n' ' ')"

step "summary"
B=$(ls -1t $OUT/${ARM}_run*.json 2>/dev/null | head -1)
if [ -n "${COMPARE_WITH:-}" ] && [ -f "${COMPARE_WITH:-}" ] && [ -n "$B" ]; then
  PYTHONPATH=. $PY scripts/compare_arms.py "$COMPARE_WITH" "$B" --label-a "$(basename "$COMPARE_WITH" .json)" --label-b "$ARM" | tee "$OUT/compare.txt"
elif [ -n "$B" ]; then
  echo "results: $B (set COMPARE_WITH=<other arm's results file> for scripts/compare_arms.py)"
else
  echo "no results file written; see logs/dbx_ontology_n1/${ARM}.log"
fi
