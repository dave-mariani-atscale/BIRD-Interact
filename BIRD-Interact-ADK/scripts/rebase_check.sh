#!/usr/bin/env bash
# Paired n=1 regression check of an MCP image against the one the stack runs.
#
#   bash scripts/rebase_check.sh                         # rebased arm, then current arm
#   DBS=solar_panel bash scripts/rebase_check.sh         # other databases (comma list)
#   MODEL=anthropic/claude-opus-4-6 bash scripts/rebase_check.sh
#   MODEL=openai/gpt-5 TRACK=gpt4o bash scripts/rebase_check.sh   # the GPT-4o simulator track
#
# Both arms run the leaderboard protocol (run_leaderboard.sh, n=1) on the QUERY tasks
# of the chosen databases, each from a COLD feedback store (reset_feedback_store.sh
# backs the store up first). The candidate image is swapped in with the compose
# override CANDIDATE_OVERRIDE and the stack's own image is restored afterwards -
# on success, on failure and on Ctrl-C alike. Results land in results/<TAG>_*.json;
# compare them with scripts/compare_arms.py.
#
# Refuses to start while an orchestrator.runner is running: the store reset and the
# service restarts would break that run.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

DBS="${DBS:-cybermarket_pattern,reverse_logistics}"
MODEL="${MODEL:-anthropic/claude-sonnet-5}"
# Leaderboard simulator track: haiku (Claude-Haiku-4-5) or gpt4o (the board's GPT-5 track).
TRACK="${TRACK:-haiku}"
CONCURRENCY="${CONCURRENCY:-5}"
STAMP="${STAMP:-$(date +%Y%m%d_%H%M)}"
COMPOSE_DIR="${COMPOSE_DIR:-/Users/davidmariani/workspace/atscale/container-local-tooling/devel/docker/compose}"
CANDIDATE_OVERRIDE="${CANDIDATE_OVERRIDE:-additional/docker-compose.mcp-bird-develop.yml}"
CANDIDATE_LABEL="${CANDIDATE_LABEL:-rebased}"
ADMIN_URL="${SEMANTIC_LAYER_MCP_ADMIN_URL:-http://localhost:3003}"
BASE=(-f docker-compose.yml -f additional/docker-compose.dm.branches.yml)

if ps -eo command | grep -E "^[^ ]*python[^ ]* -m orchestrator\.runner" >/dev/null; then
    echo "refusing: an orchestrator.runner is running" >&2; exit 1
fi

# Query tasks only: LEADERBOARD_MODE refuses --query-only, so name the tasks instead
# (Management tasks never touch the MCP server and would only add cost).
TASKS=$(python3 - "$DBS" <<'PY'
import glob, json, os, sys
dbs = set(sys.argv[1].split(","))
f = sorted(glob.glob("results/leaderboard_*_atscale*run01*.json"), key=os.path.getmtime)[-1]
rows = json.load(open(f))["results"]
def tid(r):
    return r.get("instance_id") or r["task_id"]
def db(r):  # older result files carry the database; newer ones only the task id
    return r.get("database") or tid(r).rsplit("_", 1)[0]
ids = [tid(r) for r in rows if db(r) in dbs and "_M_" not in tid(r)]
print(",".join(ids))
PY
)
[ -n "$TASKS" ] || { echo "no Query tasks found for $DBS" >&2; exit 1; }
echo "== $(echo "$TASKS" | tr ',' '\n' | wc -l | tr -d ' ') Query tasks in $DBS; model $MODEL; track $TRACK; concurrency $CONCURRENCY"

swap() {  # $@ = extra compose files (none = the stack's own image)
    local extra=()
    for f in "$@"; do extra+=(-f "$f"); done
    (cd "$COMPOSE_DIR" && docker compose -p development-compose "${BASE[@]}" ${extra[@]+"${extra[@]}"} \
        up -d --force-recreate --pull never --no-deps mcp >/dev/null)
    for _ in $(seq 1 60); do
        curl --noproxy '*' -s -m 3 "$ADMIN_URL/configz" >/dev/null 2>&1 && break; sleep 1
    done
    echo "== mcp image now: $(docker inspect development-compose-mcp-1 --format '{{.Config.Image}}')"
}
restore() { echo "== restoring the stack's own MCP image"; swap; }
trap restore EXIT

arm() {  # $1 = label
    local tag="rebasecheck_${STAMP}_$1"
    bash scripts/reset_feedback_store.sh
    LEADERBOARD_AGENT_MODEL="$MODEL" LEADERBOARD_TRACK="$TRACK" REPEAT=1 CONCURRENCY="$CONCURRENCY" \
        TAG="$tag" bash scripts/run_leaderboard.sh --tasks "$TASKS"
    echo "== arm $1 done: results/${tag}_atscale*.json"
}

swap "$CANDIDATE_OVERRIDE"
arm "$CANDIDATE_LABEL"
swap
arm current
echo "== both arms done (STAMP=$STAMP). Compare: python scripts/compare_arms.py results/rebasecheck_${STAMP}_${CANDIDATE_LABEL}_atscale*.json results/rebasecheck_${STAMP}_current_atscale*.json"
