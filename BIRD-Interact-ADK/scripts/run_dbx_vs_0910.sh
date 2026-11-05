#!/usr/bin/env bash
# The Databricks metric-view arm (dbx_metric_views), n=1, compared like for like with the 2026-09-10 AtScale
# n=3 sweep (results/full0910_atscale_run0[1-3]_*.json; workbook tab "Modified Harness 09-10 Sonnet").
# Matched to that sweep: Sonnet 5 agent and simulator, a-interact, all 410 Query tasks, concurrency 5,
# non-leaderboard corrected grading (the same six corrections), default LLM routing, and the 09-10 atscale
# instruction with only the tool-specific lines rewritten (config/environment_backends.dbx_vs_0910.yaml).
# Runs from a git worktree on its own service ports (.env: 6100/6101/6102) so it cannot collide with another
# session's harness on 6000-6002. A live comparison is written to results/dbx_vs_0910/live_compare.txt every
# 10 minutes, and the final one to results/dbx_vs_0910/final_compare.txt.
#
#   mkdir -p logs/dbx_vs_0910 && nohup bash scripts/run_dbx_vs_0910.sh > logs/dbx_vs_0910/launcher.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
unset LEADERBOARD_MODE LEADERBOARD_AGENT_MODEL LEADERBOARD_TRACK LLM_ROUTING_FILE BIRD_LLM_DUMP_DIR SYSTEM_AGENT_MAX_TOKENS DISABLE_AGGREGATES
export ENVIRONMENT_BACKENDS_FILE=config/environment_backends.dbx_vs_0910.yaml
PY=.venv-adk/bin/python
OUT=results/dbx_vs_0910; LOGD=logs/dbx_vs_0910; mkdir -p "$OUT" "$LOGD"
BASE='results/full0910_atscale_run0[123]_*.json'
step(){ echo; echo "=== $(date +%H:%M:%S) $* ==="; }
port(){ grep -E "^$1=" .env | tail -1 | cut -d= -f2; }

step "preflight"
[ "$(port SYSTEM_AGENT_PORT)" = "6100" ] || { echo "REFUSING: this checkout's .env must use ports 6100-6102"; exit 1; }
ls $BASE >/dev/null 2>&1 || { echo "REFUSING: baseline files missing: $BASE"; exit 1; }
dscacheutil -q host -a name api.anthropic.com | grep -q ip_address || { echo "REFUSING: api.anthropic.com does not resolve"; exit 1; }
s=$(docker inspect -f '{{.State.Status}}' bird_interact_postgresql_full 2>/dev/null); echo "  BIRD postgres: $s"; [ "$s" = running ] || exit 1
$PY - <<'PYEOF' || exit 1
from shared.databricks_sql import DatabricksSQL
from shared.environment_backends import get_configured_domains
r = DatabricksSQL().execute("SELECT COUNT(DISTINCT table_schema), COUNT(*) FROM bird.information_schema.tables WHERE table_type='METRIC_VIEW'")
assert not r.error, r.error
print("  metric views:", r.rows[0][1], "in", r.rows[0][0], "schemas; domains:", len(get_configured_domains("dbx_metric_views")))
assert tuple(r.rows[0]) == (22, 119) and len(get_configured_domains("dbx_metric_views")) == 22
PYEOF

step "services on 6100-6102"
bash scripts/start_services_isolated.sh || exit 1
curl -s http://127.0.0.1:6100/health; echo
curl -s http://127.0.0.1:6100/health | grep -q '"model":"anthropic/claude-sonnet-5"' || { echo "REFUSING: agent is not Sonnet 5"; exit 1; }
curl -s http://127.0.0.1:6100/health | grep -q '"leaderboard_mode":false' || { echo "REFUSING: leaderboard mode on"; exit 1; }

step "live comparison every 10 minutes"
( while sleep 600; do
    $PY scripts/compare_vs_baseline_runs.py --log "$LOGD/dbx_metric_views.log" --baseline "$BASE" > "$OUT/live_compare.tmp" 2>/dev/null \
      && { echo "updated $(date '+%Y-%m-%d %H:%M')"; cat "$OUT/live_compare.tmp"; } > "$OUT/live_compare.txt"
  done ) &
WATCH=$!

step "dbx_metric_views: 410 Query tasks, concurrency 5"
$PY -m orchestrator.runner --mode a-interact --backend dbx_metric_views --query-only --concurrency 5 --repeat 1 \
    --output "$OUT/dbx_metric_views.json" > "$LOGD/dbx_metric_views.log" 2>&1
rc=$?
kill $WATCH 2>/dev/null
echo "  runner exit $rc; files: $(ls -1 $OUT/dbx_metric_views_*.json 2>/dev/null | tr '\n' ' ')"

step "final comparison"
R=$(ls -1t $OUT/dbx_metric_views_*.json 2>/dev/null | head -1)
if [ -n "$R" ]; then
  $PY scripts/compare_vs_baseline_runs.py --results "$R" --baseline "$BASE" | tee "$OUT/final_compare.txt"
else
  $PY scripts/compare_vs_baseline_runs.py --log "$LOGD/dbx_metric_views.log" --baseline "$BASE" | tee "$OUT/final_compare.txt"
fi
bash scripts/start_services_isolated.sh --stop
