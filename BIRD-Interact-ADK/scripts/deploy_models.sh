#!/usr/bin/env bash
# Deploy AtScaleInc/bird-atscale-models via sml-cli, then gate the result.
#
# Replaces the manual Design Center publish. Three things about this command are
# not guessable and each one cost a failed attempt to find:
#
#   1. ATSCALE_API_URL is the SML public API on the `api` container
#      (local.atscaleinternal.com:3001), NOT the engine API on :10502. The engine
#      URL authenticates fine and then 404s looking for the repository.
#   2. --catalog-name MUST be passed. catalog.yml says
#      `bird_atscale_models_catalog`, and sml-cli uses that verbatim, which would
#      publish to a DIFFERENT schema from the one every recorded run and every
#      config/environment_backends.yaml domain entry names (the Catalog-suffix
#      row in docs/model-change-log.md). Design Center got `_main` by appending
#      the git branch; the CLI has to be told.
#   3. sml-cli resolves the project by its git REMOTE URL against repositories
#      registered in AtScale, not by the local path — so a change must be
#      COMMITTED AND PUSHED before it will deploy. An unpushed fix deploys the
#      old model and is indistinguishable from success.
#
# Deploying publishes the WHOLE catalog: every BIRD model goes out together.
#
# Usage: scripts/deploy_models.sh [expected_model_count]   (default 22)
set -euo pipefail

ADK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${BIRD_MODELS_DIR:-$HOME/go/src/github.com/AtScaleInc/bird-atscale-models}"
EXPECTED="${1:-22}"

[ -d "$MODELS_DIR" ] || { echo "FAIL: models repo not found at $MODELS_DIR"; exit 1; }

# Read only the one variable we need. Never `source` the .env — it holds other
# services' keys, and a value containing shell metacharacters gets executed.
TOKEN="$(grep -m1 '^SEMANTIC_LAYER_MCP_TOKEN=' "$ADK_DIR/.env" | cut -d= -f2-)"
[ ${#TOKEN} -eq 64 ] || { echo "FAIL: expected a 64-char user-scoped API token, got ${#TOKEN} chars"; exit 1; }

cd "$MODELS_DIR"

echo "=== pre-flight: everything committed and pushed? ==="
if [ -n "$(git status --porcelain)" ]; then
  echo "FAIL: uncommitted changes in $MODELS_DIR."
  echo "      sml-cli deploys what the REMOTE has, so these would be silently left out."
  git status --short
  exit 1
fi
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git fetch -q origin "$BRANCH"
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ]; then
  echo "FAIL: local $BRANCH differs from origin/$BRANCH. Push first, or you will deploy the old model."
  exit 1
fi
echo "  OK - $BRANCH matches origin at $(git rev-parse --short HEAD)"

echo
echo "=== validate (run from the repo ROOT: catalog.yml lives here) ==="
sml-cli validate . 2>&1 | tail -3

echo
echo "=== A8 question-leakage gate, per model ==="
# Pass each model's own leakage_allow.json when it has one, exactly as that
# model's generator/build.sh does. Two models carry a triaged entry - each is a
# knowledge-base concept name the model is REQUIRED to state correctly, which the
# six-word detector cannot tell from copied question phrasing - and without the
# allowlist this loop failed the whole deploy on them (set -o pipefail makes the
# gate's non-zero exit fatal here).
A8_FAILED=0
for m in */; do
  brief="${m}brief/task_brief.json"
  [ -f "$brief" ] || continue
  # bash 3.2 (the macOS system shell) treats "${arr[@]}" on an EMPTY array as an
  # unbound variable under set -u, so branch on the file instead of expanding an
  # empty array - the same trap the A10 loop's kbarg=() below would hit.
  allow="${m}generator/leakage_allow.json"
  if [ -f "$allow" ]; then
    out="$(python3 utilities/question_leakage_gate.py --model-dir "${m%/}" \
            --brief "$brief" --allow "$allow" 2>&1)" && rc=0 || rc=$?
  else
    out="$(python3 utilities/question_leakage_gate.py --model-dir "${m%/}" \
            --brief "$brief" 2>&1)" && rc=0 || rc=$?
  fi
  printf '  %-34s %s\n' "${m%/}" "$(printf '%s\n' "$out" | tail -1)"
  [ "$rc" -eq 0 ] || A8_FAILED=1
done
[ "$A8_FAILED" -eq 0 ] || { echo "FAIL: a published description quotes a task question - fix before deploying."; exit 1; }

# A10: a masked KB threshold in the model hands the semantic-layer arm a number the
# raw arm has to ask the user for, so the lift it buys is a protocol artifact. The
# generator-built models gate this at build time; prompt-only models had nothing until
# a hand audit found three (one of them introduced by the previous hand audit).
# Only fatal when the concept is masked on a task this backend actually RUNS -
# Management-category tasks never reach a read-only semantic layer.
echo
echo "=== A10 masked-threshold gate, per model ==="
# TASK_CENSUS lets a masked term be reported census-exempt rather than fatal when
# every task masking it is tiered unsolvable, matching what <db>/generator/build.sh
# passes. Without this passthrough the exemption is unusable end to end: a term that
# builds green is rejected here, so the model can never be deployed. The gate still
# fails CLOSED on a masking task that is absent from the census or tiered achievable.
CENSUS_ARG=()
if [ -n "${TASK_CENSUS:-}" ]; then
  if [ ! -f "$TASK_CENSUS" ]; then
    echo "FAIL: TASK_CENSUS=$TASK_CENSUS not found." >&2
    exit 1
  fi
  CENSUS_ARG=(--census "$TASK_CENSUS")
  echo "  census: $TASK_CENSUS"
fi

A10_FAILED=0
for m in */; do
  brief="${m}brief/task_brief.json"
  kb="$ADK_DIR/bird-interact-full/${m%/}/${m%/}_kb.jsonl"
  [ -f "$brief" ] || continue
  # Capture first, then filter: in a pipeline the exit status is the LAST command's,
  # so `gate | grep` would report grep's verdict and silently pass a real leak.
  # Branch rather than expand a possibly-empty array - see the A8 loop above.
  if [ ! -f "$kb" ]; then
    echo "  ${m%/}: no KB at $kb - running with the NUMBER detector OFF"
    out="$(python3 utilities/masked_threshold_gate.py --model-dir "${m%/}" \
            --brief "$brief" ${CENSUS_ARG+"${CENSUS_ARG[@]}"} 2>&1)" && rc=0 || rc=$?
  else
    out="$(python3 utilities/masked_threshold_gate.py --model-dir "${m%/}" \
            --brief "$brief" --kb "$kb" ${CENSUS_ARG+"${CENSUS_ARG[@]}"} 2>&1)" && rc=0 || rc=$?
  fi
  printf '%s\n' "$out" | grep -vE "^\s*\[ok\]" | grep -vE "^\s*$" || true
  [ "$rc" -eq 0 ] || A10_FAILED=1
done
[ "$A10_FAILED" -eq 0 ] || { echo "FAIL: a masked threshold is published - fix before deploying."; exit 1; }

echo
echo "=== deploy ==="
ATSCALE_API_URL=http://local.atscaleinternal.com:3001 \
ATSCALE_API_TOKEN="$TOKEN" \
  sml-cli atscale-deploy . --catalog-name=bird_atscale_models_catalog_main 2>&1 | tail -8

echo
echo "=== post-deploy gate (Q-17b: a working run_query is NOT evidence of health) ==="
bash "$ADK_DIR/scripts/gate_run.sh" "$EXPECTED"
