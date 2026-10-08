#!/usr/bin/env bash
# One full leaderboard pass (all 600 tasks, n=1) on a CANDIDATE MCP image, from a cold
# feedback store, with the stack's own image restored afterwards no matter how it ends.
#
#   MODEL=openai/gpt-5 TRACK=gpt4o bash scripts/candidate_fullpass.sh
#   CANDIDATE_OVERRIDE=additional/docker-compose.mcp-<x>.yml bash scripts/candidate_fullpass.sh
#
# Comparable baseline for the GPT-5 / gpt4o pair: results/leaderboard_gpt5_20260916_cold_atscale_atscale_run01_*.json
# (same protocol, cold store, concurrency 5). Refuses to start while an orchestrator.runner runs.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"; cd "$PROJECT_DIR"
MODEL="${MODEL:-openai/gpt-5}"; TRACK="${TRACK:-gpt4o}"; CONCURRENCY="${CONCURRENCY:-5}"
STAMP="${STAMP:-$(date +%Y%m%d_%H%M)}"; LABEL="${LABEL:-rebased}"
TAG="${TAG:-fullpass_${STAMP}_${LABEL}}"
COMPOSE_DIR="${COMPOSE_DIR:-/Users/davidmariani/workspace/atscale/container-local-tooling/devel/docker/compose}"
CANDIDATE_OVERRIDE="${CANDIDATE_OVERRIDE:-additional/docker-compose.mcp-bird-develop.yml}"
ADMIN_URL="${SEMANTIC_LAYER_MCP_ADMIN_URL:-http://localhost:3003}"
RELEASE_IMAGE="${RELEASE_IMAGE:-ghcr.io/atscaleinc/mcp:release-feedback-memory-combined}"
BASE=(-f docker-compose.yml -f additional/docker-compose.dm.branches.yml)

if ps -eo command | grep -E "^[^ ]*python[^ ]* -m orchestrator\.runner" >/dev/null; then
    echo "refusing: an orchestrator.runner is running" >&2; exit 1
fi
docker image inspect "$RELEASE_IMAGE" >/dev/null 2>&1 || { echo "refusing: $RELEASE_IMAGE is not present locally (nothing to restore to)" >&2; exit 1; }

swap() {
    local extra=(); for f in "$@"; do extra+=(-f "$f"); done
    (cd "$COMPOSE_DIR" && docker compose -p development-compose "${BASE[@]}" ${extra[@]+"${extra[@]}"} \
        up -d --force-recreate --pull never --no-deps mcp >/dev/null)
    for _ in $(seq 1 60); do curl --noproxy '*' -s -m 3 "$ADMIN_URL/configz" >/dev/null 2>&1 && break; sleep 1; done
    echo "== mcp image now: $(docker inspect development-compose-mcp-1 --format '{{.Config.Image}}')"
}
trap 'echo "== restoring the stack image"; swap' EXIT

swap "$CANDIDATE_OVERRIDE"
bash scripts/reset_feedback_store.sh
echo "== full pass: model $MODEL track $TRACK concurrency $CONCURRENCY tag $TAG"
LEADERBOARD_AGENT_MODEL="$MODEL" LEADERBOARD_TRACK="$TRACK" REPEAT=1 CONCURRENCY="$CONCURRENCY" TAG="$TAG" \
    bash scripts/run_leaderboard.sh
echo "== done: results/${TAG}_atscale*.json"
