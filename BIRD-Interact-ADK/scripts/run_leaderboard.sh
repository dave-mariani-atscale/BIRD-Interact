#!/usr/bin/env bash
# One command for a leaderboard-comparable run of BIRD-Interact-Full.
#
#   bash scripts/run_leaderboard.sh                       # atscale hybrid, 3 runs, concurrency 5
#   BACKEND=raw bash scripts/run_leaderboard.sh           # the raw control under the same protocol
#   REPEAT=1 CONCURRENCY=3 bash scripts/run_leaderboard.sh --databases solar_panel --limit 4
#
# Everything the leaderboard protocol needs hangs off ONE switch, LEADERBOARD_MODE
# (shared/config.py): upstream grading (no corrections), the upstream user
# simulator on Claude-Haiku-4-5, the agent model from LEADERBOARD_AGENT_MODEL
# (Claude-Opus-4.6 by default), the Universal Cost Scheme, all 600 tasks with
# Management tasks routed to raw Postgres, and the engine's outbound SQL
# recorded on every semantic-layer submission. This script exports the switch,
# RESTARTS the three services so they all read it, runs the evaluation, and
# exports one submission file per run. The runner itself refuses to start if
# any service reports a different setting, so a stale service cannot score a
# run under a mixed protocol.
#
# To go back to the A/B stack afterwards: bash scripts/start_services.sh (the
# switch is not persisted; only .env LEADERBOARD_MODE=true would make it stick).
set -euo pipefail
# results/ and logs/ are gitignored, so a fresh clone has neither; the reset
# attestation below is written through tee and a missing directory would abort the
# whole launch under pipefail (seen 2026-10-10 in the verification package).
mkdir -p results logs

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
export LEADERBOARD_MODE=true

BACKEND="${BACKEND:-atscale}"
REPEAT="${REPEAT:-3}"
CONCURRENCY="${CONCURRENCY:-5}"
TAG="${TAG:-leaderboard_$(date +%Y%m%d)}"
OUTPUT="results/${TAG}_${BACKEND}.json"

PYTHON_BIN="python"
if [ -x "$PROJECT_DIR/.conda-py310/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.conda-py310/bin/python"
elif [ -x "$PROJECT_DIR/.venv-adk/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv-adk/bin/python"
fi

# Aggregates: in leaderboard mode the harness sends disable_aggregates=true on
# every run_query (agent and grading), so the outbound SQL in the submission
# reads only base tables. Nothing to flip on the MCP server; the runner's
# pre-flight checks the server understands the parameter (/configz).

# Cold start (review tracker items 2 and 4). Run 1 is the "cold" figure, so it
# must begin with an EMPTY feedback-memory store, and the sweep must be able to
# prove it: until 2026-10-01 nothing here reset the store, and the 09-11/09-12
# sweeps' cold start could only be inferred afterwards from list_models sizes.
# reset_feedback_store.sh stops the services, backs up and truncates all three
# mcp_feedback tables, verifies zero and restarts the MCP server; its report is
# kept beside the results. The raw backend writes no feedback, so it is skipped.
# KEEP_FEEDBACK_STORE=1 skips the reset on purpose (a deliberately warm run) and
# says so in the same file.
RESET_LOG="results/${TAG}_${BACKEND}_feedback_reset.txt"
if [ "${KEEP_FEEDBACK_STORE:-0}" != "1" ] && [ "$BACKEND" != "raw" ]; then
    echo "== resetting the feedback-memory store for a cold run 1 -> $RESET_LOG"
    { date -u +"reset at %Y-%m-%dT%H:%M:%SZ"; bash "$PROJECT_DIR/scripts/reset_feedback_store.sh"; } 2>&1 | tee "$RESET_LOG"
else
    echo "== feedback store NOT reset (KEEP_FEEDBACK_STORE=${KEEP_FEEDBACK_STORE:-0}, backend=$BACKEND): $(bash "$PROJECT_DIR/scripts/reset_feedback_store.sh" --status)" | tee "$RESET_LOG"
fi

echo "== leaderboard mode: restarting services with LEADERBOARD_MODE=true"
bash "$PROJECT_DIR/scripts/start_services.sh"

echo "== services report:"
for p in 6000 6001 6002; do curl --noproxy '*' -s "http://127.0.0.1:$p/health"; echo; done

# The store must still be empty at the moment run 1 starts (a service restart or a
# stray probe in between would otherwise warm it unnoticed).
if [ "${KEEP_FEEDBACK_STORE:-0}" != "1" ] && [ "$BACKEND" != "raw" ]; then
    store="$(bash "$PROJECT_DIR/scripts/reset_feedback_store.sh" --status)"
    date -u +"at run start %Y-%m-%dT%H:%M:%SZ: $store" | tee -a "$RESET_LOG"
    [ "$store" = "exchange=0 feedback=0 certified_query=0" ] || { echo "feedback store is not empty at run start - refusing" >&2; exit 1; }
fi

echo "== running: backend=$BACKEND repeat=$REPEAT concurrency=$CONCURRENCY -> $OUTPUT"
"$PYTHON_BIN" -m orchestrator.runner --mode a-interact --backend "$BACKEND" \
    --repeat "$REPEAT" --concurrency "$CONCURRENCY" --output "$OUTPUT" "$@"

echo "== exporting submission files (validated against gold with the upstream grader)"
shopt -s nullglob
for f in results/${TAG}_${BACKEND}_run*.json results/${TAG}_${BACKEND}_2*.json; do
    "$PYTHON_BIN" scripts/export_submission.py "$f" --validate || echo "export failed for $f"
done
echo "== done. Submission files are under submissions/."
