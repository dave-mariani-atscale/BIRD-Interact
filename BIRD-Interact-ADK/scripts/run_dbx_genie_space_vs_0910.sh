#!/usr/bin/env bash
# The Genie-space arm (dbx_genie_space: Sonnet in the BIRD loop, Genie writing the SQL over each database's metric views), n=1, compared like for like with the 2026-09-10 AtScale
# n=3 sweep (results/full0910_atscale_run0[1-3]_*.json; workbook tab "Modified Harness 09-10 Sonnet").
# Concurrency defaults to 3, below the sweep's 5, because the Genie API rate-limits (HTTP 429 seen while
# provisioning); ask_genie backs off and retries, so a 429 costs time, not a task. Matched to that sweep: Sonnet 5 agent and simulator, a-interact, all 410 Query tasks, concurrency ${CONCURRENCY:-3},
# non-leaderboard corrected grading (the same six corrections), default LLM routing, and the 09-10 atscale
# instruction with only the tool-specific lines rewritten (config/environment_backends.dbx_vs_0910.yaml).
# Runs from a git worktree on its own service ports (.env: 6200/6201/6202) so it cannot collide with another
# session's harness on 6000-6002 or the metric-view run on 6100-6102. A live comparison is written to results/dbx_vs_0910/live_compare.txt every
# 10 minutes, and the final one to results/dbx_vs_0910/final_compare.txt.
#
#   mkdir -p logs/dbx_genie_space_vs_0910 && nohup bash scripts/run_dbx_genie_space_vs_0910.sh > logs/dbx_genie_space_vs_0910/launcher.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
unset LEADERBOARD_MODE LEADERBOARD_AGENT_MODEL LEADERBOARD_TRACK LLM_ROUTING_FILE BIRD_LLM_DUMP_DIR SYSTEM_AGENT_MAX_TOKENS DISABLE_AGGREGATES
export ENVIRONMENT_BACKENDS_FILE=config/environment_backends.dbx_vs_0910.yaml
PY=.venv-adk/bin/python
OUT=results/dbx_genie_space_vs_0910; LOGD=logs/dbx_genie_space_vs_0910; mkdir -p "$OUT" "$LOGD"
BASE='results/full0910_atscale_run0[123]_*.json'
step(){ echo; echo "=== $(date +%H:%M:%S) $* ==="; }
port(){ grep -E "^$1=" .env | tail -1 | cut -d= -f2; }

step "preflight"
[ "$(port SYSTEM_AGENT_PORT)" = "6200" ] || { echo "REFUSING: this checkout's .env must use ports 6200-6202"; exit 1; }
ls $BASE >/dev/null 2>&1 || { echo "REFUSING: baseline files missing: $BASE"; exit 1; }
dscacheutil -q host -a name api.anthropic.com | grep -q ip_address || { echo "REFUSING: api.anthropic.com does not resolve"; exit 1; }
s=$(docker inspect -f '{{.State.Status}}' bird_interact_postgresql_full 2>/dev/null); echo "  BIRD postgres: $s"; [ "$s" = running ] || exit 1
$PY - <<'PYEOF' || exit 1
from shared.databricks_sql import DatabricksSQL
from shared.environment_backends import get_configured_domains
r = DatabricksSQL().execute("SELECT COUNT(DISTINCT table_schema), COUNT(*) FROM bird_interact.information_schema.tables WHERE table_type='METRIC_VIEW'")
assert not r.error, r.error
from shared.environment_backends import get_domain_config
spaces = [get_domain_config("dbx_genie_space", d).get("space_id") for d in get_configured_domains("dbx_genie_space")]
print("  metric views:", r.rows[0][1], "in", r.rows[0][0], "schemas; domains:", len(spaces), "with a Genie space:", sum(1 for s in spaces if s))
assert all(spaces), "every domain needs a space_id (scripts/provision_genie_spaces.py)"
assert tuple(r.rows[0]) == (22, 119) and len(get_configured_domains("dbx_genie_space")) == 22
PYEOF

step "services on 6100-6102"
bash scripts/start_services_isolated.sh || exit 1
curl -s http://127.0.0.1:6200/health; echo
curl -s http://127.0.0.1:6200/health | grep -q '"model":"anthropic/claude-sonnet-5"' || { echo "REFUSING: agent is not Sonnet 5"; exit 1; }
curl -s http://127.0.0.1:6200/health | grep -q '"leaderboard_mode":false' || { echo "REFUSING: leaderboard mode on"; exit 1; }

step "live comparison every 10 minutes"
( while sleep 600; do
    $PY scripts/compare_vs_baseline_runs.py --log "$LOGD/dbx_genie_space.log" --baseline "$BASE" > "$OUT/live_compare.tmp" 2>/dev/null \
      && { echo "updated $(date '+%Y-%m-%d %H:%M')"; cat "$OUT/live_compare.tmp"; } > "$OUT/live_compare.txt"
  done ) &
WATCH=$!

step "dbx_genie_space: 410 Query tasks, concurrency ${CONCURRENCY:-3}"
$PY -m orchestrator.runner --mode a-interact --backend dbx_genie_space --query-only --concurrency "${CONCURRENCY:-3}" --repeat 1 \
    --output "$OUT/dbx_genie_space.json" > "$LOGD/dbx_genie_space.log" 2>&1
rc=$?
kill $WATCH 2>/dev/null
echo "  runner exit $rc; files: $(ls -1 $OUT/dbx_genie_space_*.json 2>/dev/null | tr '\n' ' ')"

step "final comparison"
R=$(ls -1t $OUT/dbx_genie_space_*.json 2>/dev/null | head -1)
if [ -n "$R" ]; then
  $PY scripts/compare_vs_baseline_runs.py --results "$R" --baseline "$BASE" | tee "$OUT/final_compare.txt"
else
  $PY scripts/compare_vs_baseline_runs.py --log "$LOGD/dbx_genie_space.log" --baseline "$BASE" | tee "$OUT/final_compare.txt"
fi
bash scripts/start_services_isolated.sh --stop
