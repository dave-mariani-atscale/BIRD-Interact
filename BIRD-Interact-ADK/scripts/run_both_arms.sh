#!/usr/bin/env bash
# Runs BOTH ARMS (atscale and raw) over one or more databases, unattended -
# the batch driver behind every head-to-head measurement. Long enough for a
# full sweep to be an overnight job:
#
#   ./scripts/run_both_arms.sh                    # all 8 databases, n=3 per arm
#   ./scripts/run_both_arms.sh organ_transplant   # one database (regression test)
#   RUNS=1 ./scripts/run_both_arms.sh organ_transplant   # quick single-pass check
#
# Each individual run is executed by orchestrator.runner at CONCURRENCY tasks
# in parallel (default 5, same as running the runner by hand); the batch's
# own loops - database by database, then arm by arm - are deliberately
# SEQUENTIAL, so a full sweep is slow by construction, not by inefficiency.
#
# Positional args: databases to run (default: all 8 with deployed models).
# Env: RUNS (repetitions per arm per database, default 3),
#      CONCURRENCY (within-run task concurrency, default 5).
#
# Per database: atscale first (it has the external MCP dependency, so a
# misconfiguration fails before the raw arm spends anything), then raw with
# --query-only so both arms grade the same task set. A database whose atscale
# arm produced no output files skips its raw arm (the pair would not be
# comparable) and the script moves on to the next database rather than dying —
# one broken domain must not cost the whole night. Every failure is listed in
# the end-of-run summary.
#
# The runner ALWAYS timestamps --output (shared.output_paths), so files land as
# <stem>_runNN_YYYYmmdd_HHMMSS.json; existence checks must glob, never test the
# bare name. Services are shared and the backend is pushed per-run via
# /set_backend, so no restarts happen between arms; do NOT run two of these
# concurrently (per-task scratch DBs would collide).
set -u
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
source .venv-adk/bin/activate

RUNS="${RUNS:-3}"
CONCURRENCY="${CONCURRENCY:-5}"
ALL_DBS=(organ_transplant archeology_scan crypto_exchange cybermarket_pattern
         exchange_traded_funds households labor_certification_applications solar_panel)
DBS=("$@"); [ ${#DBS[@]} -eq 0 ] && DBS=("${ALL_DBS[@]}")

STAMP="$(date +%Y%m%d_%H%M)"
PREFIX="batch${STAMP}"   # results/batch<stamp>_<db>_<arm>*.json ; runs before
                         # 2026-08-18 used the "overnight<stamp>_" prefix

# Keep every run re-gradable offline later (CLAUDE.md: re-grade, don't re-run).
export GRADING_AUDIT_PATH="results/${PREFIX}_audit.jsonl"

# A sleeping laptop silently kills the night: re-exec under caffeinate when
# available (idle+system sleep held while this shell lives).
if command -v caffeinate >/dev/null && [ -z "${_CAFFEINATED:-}" ]; then
  export _CAFFEINATED=1
  exec caffeinate -is "$0" "${DBS[@]}"
fi

# Pre-flight: all three services up and the MCP reachable, or nothing runs.
for p in 6000 6001 6002; do
  if ! curl -s -m 5 "http://127.0.0.1:$p/health" | grep -q healthy; then
    echo "ABORT: service on port $p is not healthy — run scripts/start_services.sh first"
    exit 1
  fi
done
if ! curl -s -m 5 "http://localhost:3003/healthz" | grep -q ok; then
  echo "ABORT: MCP server on :3003 is not healthy — the atscale arm cannot run"
  exit 1
fi

# Circuit breaker: a run whose tasks mostly died without a single tool call is
# infrastructure failure (service down, API auth, usage cap), not task failure.
# Continuing would burn every remaining database writing void files - the
# 2026-08-17 overnight lost 7 of 8 databases to exactly this when the Anthropic
# workspace hit its monthly usage cap mid-sweep. Abort the whole night instead.
run_is_void() {  # $1 = results-file glob; returns 0 (void) when any run has >=50% dead tasks
  python - "$@" <<'PYEOF'
import json, glob, sys
for pat in sys.argv[1:]:
    for f in glob.glob(pat):
        rows = json.load(open(f)).get("results", [])
        if not rows: continue
        dead = sum(1 for r in rows if not r.get("tool_trajectory"))
        if dead * 2 >= len(rows):
            print(f"VOID: {f}: {dead}/{len(rows)} tasks died without a tool call")
            sys.exit(0)
sys.exit(1)
PYEOF
}

# Only the log written SINCE this script started counts - the services append
# across restarts, so an old cap message must not trip future nights.
AGENT_LOG="logs/system_agent.out"
AGENT_LOG_BASE=$(wc -c < "$AGENT_LOG" 2>/dev/null || echo 0)
usage_cap_hit() {
  tail -c "+$((AGENT_LOG_BASE + 1))" "$AGENT_LOG" 2>/dev/null | grep -q "workspace API usage limits"
}

abort_night() {
  echo "================ NIGHT ABORTED: $1 ================"
  echo "Completed so far:"; ls -1 "results/${PREFIX}"*_*.json 2>/dev/null || echo "(none)"
  [ ${#FAILURES[@]} -gt 0 ] && echo "FAILED ARMS: ${FAILURES[*]}"
  exit 2
}

FAILURES=()
for db in "${DBS[@]}"; do
  echo "===== $db : atscale x$RUNS start $(date) ====="
  python -m orchestrator.runner --mode a-interact --backend atscale \
    --databases "$db" --repeat "$RUNS" --concurrency "$CONCURRENCY" \
    --output "results/${PREFIX}_${db}_atscale.json" \
    > "results/${PREFIX}_${db}_atscale.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ] || ! compgen -G "results/${PREFIX}_${db}_atscale*_*.json" > /dev/null; then
    echo "FAIL: $db atscale arm (rc=$rc, or no output files) — skipping its raw arm"
    FAILURES+=("$db (atscale rc=$rc)")
    continue
  fi
  if usage_cap_hit; then abort_night "Anthropic workspace usage cap reached"; fi
  if run_is_void "results/${PREFIX}_${db}_atscale*_*.json"; then
    abort_night "$db atscale arm produced a void run (infrastructure failure)"
  fi
  echo "===== $db : raw x$RUNS start $(date) ====="
  python -m orchestrator.runner --mode a-interact --backend raw --query-only \
    --databases "$db" --repeat "$RUNS" --concurrency "$CONCURRENCY" \
    --output "results/${PREFIX}_${db}_raw.json" \
    > "results/${PREFIX}_${db}_raw.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ] || ! compgen -G "results/${PREFIX}_${db}_raw*_*.json" > /dev/null; then
    echo "FAIL: $db raw arm (rc=$rc, or no output files)"
    FAILURES+=("$db (raw rc=$rc)")
  elif run_is_void "results/${PREFIX}_${db}_raw*_*.json"; then
    abort_night "$db raw arm produced a void run (infrastructure failure)"
  fi
  if usage_cap_hit; then abort_night "Anthropic workspace usage cap reached"; fi
  echo "===== $db : done $(date) ====="
done

echo
echo "================ OVERNIGHT SUMMARY $(date) ================"
ls -1 "results/${PREFIX}"*_*.json 2>/dev/null || echo "(no result files)"
if [ ${#FAILURES[@]} -gt 0 ]; then
  echo "FAILED ARMS: ${FAILURES[*]}"
  exit 1
fi
echo "ALL ARMS COMPLETE — summarize with: python scripts/summarize_runs.py --lastn $RUNS"
