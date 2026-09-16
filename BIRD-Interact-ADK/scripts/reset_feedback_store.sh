#!/usr/bin/env bash
# Zero the MCP feedback-memory store so the next run is genuinely COLD.
#
#   bash scripts/reset_feedback_store.sh            # stop services, back up, truncate, verify
#   bash scripts/reset_feedback_store.sh --status   # just report the counts
#
# Three tables, not two. exchange and feedback are the raw telemetry;
# certified_query is the PROMOTED (question, query) pairings the server actually
# serves back to agents as "Certified query exemplars" (top EXEMPLARS_K per model).
# It has no foreign key to the other two, so TRUNCATE ... CASCADE on exchange and
# feedback leaves it intact - measured 2026-09-16: two sweeps believed cold began
# with 934 and 1,630 certified pairings inherited from earlier models' accepted
# answers to the same questions, and their list_models payload on task 1 was
# 37.9k chars against 17.0k for a true cold start.
#
# Services first: the telemetry that fills these tables runs on daemon threads
# inside the system_agent process and keeps writing for a few seconds after the
# runner dies. Truncating with them up produced a non-empty store twice.
set -euo pipefail
cd "$(dirname "$0")/.."
PG() { docker exec postgres psql -U atscale -d atscale -Atc "$1"; }
counts() { PG "select 'exchange='||(select count(*) from mcp_feedback.exchange)
                   ||' feedback='||(select count(*) from mcp_feedback.feedback)
                   ||' certified_query='||(select count(*) from mcp_feedback.certified_query);"; }

if [ "${1:-}" = "--status" ]; then counts; exit 0; fi

echo "== stopping services (telemetry threads live inside them)"
pkill -f uvicorn 2>/dev/null || true; sleep 3
pgrep -f uvicorn >/dev/null && { pkill -9 -f uvicorn; sleep 1; }
pgrep -f orchestrator.runner >/dev/null && { echo "refusing: an orchestrator.runner is still running" >&2; exit 1; }

echo "== waiting for in-flight writes to drain"
a=$(PG "select count(*) from mcp_feedback.exchange"); sleep 15
b=$(PG "select count(*) from mcp_feedback.exchange")
[ "$a" = "$b" ] || { echo "store still changing ($a -> $b); wait and re-run" >&2; exit 1; }

mkdir -p results/backups
f="results/backups/mcp_feedback_before_reset_$(date +%Y%m%d_%H%M%S).sql"
docker exec postgres pg_dump -U atscale -d atscale -n mcp_feedback > "$f"
echo "== backed up to $f ($(du -h "$f" | cut -f1)); before: $(counts)"

PG "truncate table mcp_feedback.feedback, mcp_feedback.exchange, mcp_feedback.certified_query restart identity cascade;" >/dev/null
after=$(counts); echo "== after:  $after"
[ "$after" = "exchange=0 feedback=0 certified_query=0" ] || { echo "reset incomplete" >&2; exit 1; }

echo "== restarting MCP server so nothing cached survives"
docker restart development-compose-mcp-1 >/dev/null
for _ in $(seq 1 30); do curl -s -m 3 http://localhost:3003/configz >/dev/null 2>&1 && break; sleep 2; done
echo "== store is COLD. Aggregates are a separate step (drop schema aggregates per BIRD database)."
