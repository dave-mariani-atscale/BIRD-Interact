#!/usr/bin/env bash
# OPTIONAL, server-wide: turn the MCP server's aggregate bypass on or off for the
# local stack. Leaderboard runs do NOT need this - the harness sends
# disable_aggregates=true per run_query when LEADERBOARD_MODE is on, so one MCP
# server serves both modes. Use this only for another client that cannot pass
# the parameter, or to check what the server reports (status).
#
#   bash scripts/mcp_aggregates.sh status   # what the running server reports
#   bash scripts/mcp_aggregates.sh on       # leaderboard: use_aggs(false) + generate_aggs(false) on every SELECT
#   bash scripts/mcp_aggregates.sh off      # A/B: aggregates as normal
#
# The flag is ATSCALE_MCP_DISABLE_AGGREGATES on the MCP container, read at
# start-up, so on/off recreate the container (a few seconds; sessions are in
# Postgres and survive). "on" layers additional/docker-compose.mcp-leaderboard.yml
# over the stack's compose files; "off" recreates without it. Both wait until
# /configz on the server reports the requested state, so a caller can trust the
# exit code. orchestrator.runner refuses a leaderboard run on a semantic-layer
# backend unless the server reports per_query_disable_aggregates (or the
# global flag) on /configz.
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/Users/davidmariani/workspace/atscale/container-local-tooling/devel/docker/compose}"
PROJECT="${COMPOSE_PROJECT:-development-compose}"
BASE=(-f docker-compose.yml -f additional/docker-compose.dm.branches.yml)
OVERRIDE=additional/docker-compose.mcp-leaderboard.yml
ADMIN_URL="${SEMANTIC_LAYER_MCP_ADMIN_URL:-http://localhost:3003}"

status() { curl --noproxy '*' -s -m 5 "$ADMIN_URL/configz" || echo '{"error":"configz unreachable"}'; echo; }

wait_for() {  # $1 = true|false
    for _ in $(seq 1 60); do
        got=$(curl --noproxy '*' -s -m 3 "$ADMIN_URL/configz" | python3 -c 'import json,sys
try: print(str(json.load(sys.stdin).get("disable_aggregates")).lower())
except Exception: print("?")' 2>/dev/null || echo "?")
        [ "$got" = "$1" ] && return 0
        sleep 1
    done
    echo "MCP server did not report disable_aggregates=$1 within 60s (last: $got)" >&2
    return 1
}

case "${1:-status}" in
    status) status ;;
    on)
        (cd "$COMPOSE_DIR" && docker compose -p "$PROJECT" "${BASE[@]}" -f "$OVERRIDE" \
            up -d --force-recreate --pull never --no-deps mcp)
        wait_for true && echo "MCP aggregates: DISABLED (leaderboard mode)"; status ;;
    off)
        (cd "$COMPOSE_DIR" && docker compose -p "$PROJECT" "${BASE[@]}" \
            up -d --force-recreate --pull never --no-deps mcp)
        wait_for false && echo "MCP aggregates: enabled (A/B mode)"; status ;;
    *) echo "usage: $0 status|on|off" >&2; exit 2 ;;
esac
