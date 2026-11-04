#!/usr/bin/env bash
# Scenario 1 head-to-head, n=1 (prepared 2026-11-04): the AtScale arm (no-gold-930 SML models) against the
# Databricks metric-view arm (backend dbx_metric_views, bird_interact catalog), same 410 Query tasks on the 22
# databases, same agent and simulator (Sonnet 5 / Sonnet 5), a-interact, NON-leaderboard (corrected grading),
# concurrency 5, one repeat per arm. The setup mirrors scripts/run_nogold930_n3.sh run 1: feedback store zeroed
# (cold), aggregates zeroed on the no-gold-930 project, the 180 s LLM request timeout. Roughly 4-5 h per arm.
#
#   mkdir -p logs/dbx_vs_atscale_n1 && nohup bash scripts/run_dbx_vs_atscale_n1.sh > logs/dbx_vs_atscale_n1/launcher.log 2>&1 &
#
# ARMS=atscale or ARMS=dbx_metric_views runs one arm only; ORDER is atscale first by default (its MCP dependency
# fails fast). Results land in results/dbx_vs_atscale_n1/<arm>_run01_<stamp>.json; the script ends with
# scripts/compare_arms.py over the two files.
set -uo pipefail
cd /Users/davidmariani/workspace/atscale/BIRD-Interact/BIRD-Interact-ADK
unset LEADERBOARD_MODE LEADERBOARD_AGENT_MODEL LEADERBOARD_TRACK BIRD_LLM_DUMP_DIR SYSTEM_AGENT_MAX_TOKENS DISABLE_AGGREGATES
export ENVIRONMENT_BACKENDS_FILE=config/environment_backends.no_gold_930.yaml
export LLM_ROUTING_FILE=config/llm_routing.anthropic_timeout180.yaml
ARMS="${ARMS:-atscale dbx_metric_views}"
CONCURRENCY="${CONCURRENCY:-5}"
OUT=results/dbx_vs_atscale_n1
step(){ echo; echo "=== $(date +%H:%M:%S) $* ==="; }
busy(){ ps -eo args= 2>/dev/null | grep -E "(/Python|python[0-9.]*) -m orchestrator\.runner" | grep -vF grep >/dev/null; }
busy && { echo "REFUSING: a runner is active"; exit 1; }
PY=.venv-adk/bin/python

step "host: DNS, disk, containers"
dscacheutil -q host -a name api.anthropic.com | grep -q ip_address || { echo "REFUSING: api.anthropic.com does not resolve"; exit 1; }
free=$(df -g . | awk 'NR==2{print $4}'); echo "  free disk: ${free} GB"; [ "$free" -ge 12 ] || { echo "REFUSING: under 12 GB free"; exit 1; }
for c in development-compose-engine-1 development-compose-mcp-1 api postgres bird_interact_postgresql_full; do
  s=$(docker inspect -f '{{.State.Status}}' $c 2>/dev/null); echo "  $c: $s"; [ "$s" = running ] || { echo "REFUSING: $c not running"; exit 1; }
done

step "databricks: warehouse reachable, 22 schemas and 119 metric views in bird_interact"
PYTHONPATH=. $PY - <<'PYEOF' || exit 1
from shared.databricks_sql import DatabricksSQL
r = DatabricksSQL().execute("SELECT COUNT(DISTINCT table_schema), COUNT(*) FROM bird_interact.information_schema.tables WHERE table_type='METRIC_VIEW'")
assert not r.error, r.error
schemas, views = r.rows[0]
print(f"  metric views: {views} in {schemas} schemas")
assert (schemas, views) == (22, 119), "REFUSING: expected 22 schemas / 119 metric views"
PYEOF

step "both backends present in $ENVIRONMENT_BACKENDS_FILE, 22 domains each"
PYTHONPATH=. $PY - <<'PYEOF' || exit 1
from shared.environment_backends import get_configured_domains
for b in ("atscale", "dbx_metric_views"):
    n = len(get_configured_domains(b)); print(f"  {b}: {n} domains"); assert n == 22, b
PYEOF

step "zero the feedback store (cold run; also stops the services)"
bash scripts/reset_feedback_store.sh 2>&1 | tail -3
post=$(docker exec postgres psql -U atscale -d atscale -Atc "select (select count(*) from mcp_feedback.exchange)+(select count(*) from mcp_feedback.feedback)+(select count(*) from mcp_feedback.certified_query);")
echo "  rows after reset: $post"; [ "$post" = "0" ] || { echo "REFUSING: store not empty"; exit 1; }

step "wait for MCP presample traffic and queued aggregate builds to stop"
for i in $(seq 1 120); do
  n=$(docker exec postgres psql -U atscale -d atscale -Atc "select count(*) from engine.queries where service in ('user-query','aggregate-creation-service') and received > now() - interval '2 minutes';")
  [ "${n:-1}" -lt 5 ] && { echo "  quiet: $n queries in the last 2 min"; break; }
  [ $i -eq 120 ] && { echo "REFUSING: engine still busy after 60 min"; exit 1; }
  sleep 30
done
step "aggregates on bird_models_no_gold_930: reset and confirm zero"
AGG_PROJECT=bird_models_no_gold_930 bash scripts/reset_aggregates.sh 2>&1 | tail -1
n=$(AGG_PROJECT=bird_models_no_gold_930 bash scripts/reset_aggregates.sh --status 2>&1 | grep -oE "total: [0-9]+" | grep -oE "[0-9]+" | head -1)
echo "  active: ${n:-?}"; [ "${n:-1}" = "0" ] || { echo "REFUSING: aggregates not zero"; exit 1; }

step "start services (backends file: $ENVIRONMENT_BACKENDS_FILE)"
pkill -f "uvicorn" 2>/dev/null; sleep 2
bash scripts/start_services.sh 2>&1 | tail -2
for i in $(seq 1 40); do curl -s http://127.0.0.1:6000/health | grep -q healthy && curl -s http://127.0.0.1:6002/health | grep -q healthy && break; sleep 3; done
curl -s http://127.0.0.1:6000/health; echo
curl -s http://127.0.0.1:6000/health | grep -q '"model":"anthropic/claude-sonnet-5"' || { echo "REFUSING: agent is not Sonnet 5"; exit 1; }
curl -s http://127.0.0.1:6000/health | grep -q '"leaderboard_mode":false' || { echo "REFUSING: leaderboard mode is on"; exit 1; }

mkdir -p "$OUT" logs/dbx_vs_atscale_n1
for arm in $ARMS; do
  step "arm $arm: 410 Query tasks, concurrency $CONCURRENCY"
  bash scripts/run_eval.sh --mode a-interact --backend "$arm" --concurrency "$CONCURRENCY" --repeat 1 \
       --output "$OUT/${arm}.json" > "logs/dbx_vs_atscale_n1/${arm}.log" 2>&1
  echo "  exit $? ; files: $(ls -1 $OUT/${arm}_run*.json 2>/dev/null | tr '\n' ' ')"
done

step "compare"
A=$(ls -1t $OUT/atscale_run*.json 2>/dev/null | head -1); B=$(ls -1t $OUT/dbx_metric_views_run*.json 2>/dev/null | head -1)
if [ -n "$A" ] && [ -n "$B" ]; then
  PYTHONPATH=. $PY scripts/compare_arms.py "$A" "$B" --label-a atscale --label-b dbx_metric_views | tee "$OUT/compare.txt"
else
  echo "one arm has no results file (atscale: ${A:-none}, dbx: ${B:-none}); run compare_arms.py by hand"
fi
