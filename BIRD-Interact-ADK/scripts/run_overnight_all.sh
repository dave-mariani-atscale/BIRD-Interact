#!/usr/bin/env bash
# Both arms, every modeled database, unattended. Designed to run overnight:
#
#   ./scripts/run_overnight_all.sh                    # all 8 databases, n=3 per arm
#   ./scripts/run_overnight_all.sh organ_transplant   # one database (regression test)
#   RUNS=1 ./scripts/run_overnight_all.sh organ_transplant   # quick single-pass check
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
PREFIX="overnight${STAMP}"

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
  echo "===== $db : raw x$RUNS start $(date) ====="
  python -m orchestrator.runner --mode a-interact --backend raw --query-only \
    --databases "$db" --repeat "$RUNS" --concurrency "$CONCURRENCY" \
    --output "results/${PREFIX}_${db}_raw.json" \
    > "results/${PREFIX}_${db}_raw.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ] || ! compgen -G "results/${PREFIX}_${db}_raw*_*.json" > /dev/null; then
    echo "FAIL: $db raw arm (rc=$rc, or no output files)"
    FAILURES+=("$db (raw rc=$rc)")
  fi
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
