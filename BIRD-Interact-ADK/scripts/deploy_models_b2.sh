#!/usr/bin/env bash
# Deploy diannewood/bird-models-b2 to the bird_models_b2 catalog, then check it.
# Copy of deploy_models_v12.sh: same pre-flight, validate, A8/A10 gates (run from the v12
# repo's utilities/, which accept any model folder) and deploy; the post-deploy check is a
# list_models on :3004 because the B2 catalog is in no benchmark backend yet.
#
# Same three non-guessable facts as scripts/deploy_models.sh (read its header).
#
# NODE_OPTIONS preloads scripts/sml_fetch_retry.cjs (E-23: the deploy POST reuses a
# keep-alive socket the API has already closed; one retry on a fresh socket fixes it).
#
# Usage: scripts/deploy_models_b2.sh   (Deploying publishes the whole bird_models_b2 catalog; the dev engine restarts for about a minute.)
set -euo pipefail

ADK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${BIRD_MODELS_B2_DIR:-$HOME/go/src/github.com/diannewood/bird-models-b2}"
V12_UTIL="$HOME/go/src/github.com/diannewood/bird-models-v12/utilities"
CATALOG=bird_models_b2

[ -d "$MODELS_DIR" ] || { echo "FAIL: B2 models repo not found at $MODELS_DIR"; exit 1; }

# Read only the one variable we need. Never `source` the .env - it holds other
# services' keys, and a value containing shell metacharacters gets executed.
TOKEN="$(grep -m1 '^SEMANTIC_LAYER_MCP_TOKEN=' "$ADK_DIR/.env" | cut -d= -f2-)"
[ ${#TOKEN} -eq 64 ] || { echo "FAIL: expected a 64-char user-scoped API token, got ${#TOKEN} chars"; exit 1; }

# A stale exported token overrides the .env one and 401s every MCP call, which
# looks exactly like E-14 (A-71, labor_certification 2026-09-27).
unset SEMANTIC_LAYER_MCP_TOKEN || true

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
A8_FAILED=0
for m in */; do
  brief="${m}brief/task_brief.json"
  [ -f "$brief" ] || continue
  allow="${m}generator/leakage_allow.json"
  if [ -f "$allow" ]; then
    out="$(python3 "$V12_UTIL/question_leakage_gate.py" --model-dir "${m%/}" \
            --brief "$brief" --allow "$allow" 2>&1)" && rc=0 || rc=$?
  else
    out="$(python3 "$V12_UTIL/question_leakage_gate.py" --model-dir "${m%/}" \
            --brief "$brief" 2>&1)" && rc=0 || rc=$?
  fi
  printf '  %-34s %s\n' "${m%/}" "$(printf '%s\n' "$out" | tail -1)"
  [ "$rc" -eq 0 ] || A8_FAILED=1
done
[ "$A8_FAILED" -eq 0 ] || { echo "FAIL: a published description quotes a task question - fix before deploying."; exit 1; }

echo
echo "=== A10 masked-threshold gate, per model ==="
A10_FAILED=0
for m in */; do
  brief="${m}brief/task_brief.json"
  kb="$ADK_DIR/bird-interact-full/${m%/}/${m%/}_kb.jsonl"
  [ -f "$brief" ] || continue
  census="${TASK_CENSUS:-$ADK_DIR/results/bird_full_run_2026-09-06_atscale_n3/docs/census_rev4_final.json}"
  CENSUS_ARG=()
  [ -f "$census" ] && CENSUS_ARG=(--census "$census")
  if [ ! -f "$kb" ]; then
    echo "  ${m%/}: no KB at $kb - running with the NUMBER detector OFF"
    out="$(python3 "$V12_UTIL/masked_threshold_gate.py" --model-dir "${m%/}" \
            --brief "$brief" ${CENSUS_ARG+"${CENSUS_ARG[@]}"} 2>&1)" && rc=0 || rc=$?
  else
    out="$(python3 "$V12_UTIL/masked_threshold_gate.py" --model-dir "${m%/}" \
            --brief "$brief" --kb "$kb" ${CENSUS_ARG+"${CENSUS_ARG[@]}"} 2>&1)" && rc=0 || rc=$?
  fi
  printf '%s\n' "$out" | grep -vE "^\s*\[ok\]" | grep -vE "^\s*$" || true
  [ "$rc" -eq 0 ] || A10_FAILED=1
done
[ "$A10_FAILED" -eq 0 ] || { echo "FAIL: a masked threshold is published - fix before deploying."; exit 1; }

echo
echo "=== deploy to $CATALOG ==="
NODE_OPTIONS="--require $ADK_DIR/scripts/sml_fetch_retry.cjs" \
ATSCALE_API_URL=http://local.atscaleinternal.com:3001 \
ATSCALE_API_TOKEN="$TOKEN" \
  sml-cli atscale-deploy . --catalog-name="$CATALOG" 2>&1 | tail -8

echo
echo "=== post-deploy gate (wait first: atscale-deploy can kill the engine AFTER reporting success, E-14) ==="
python3 -c "import time; time.sleep(120)"
unset ARM_MCP_URL
MCP_PY="$HOME/go/src/github.com/AtScaleInc/mcp-b2-arm/.venv/bin/python"
MCP_CALL="$HOME/go/src/github.com/AtScaleInc/mcp/plans/sml-reference-model-arms/tools/mcp_call.py"
out="$("$MCP_PY" "$MCP_CALL" list_models "{\"catalog\": \"$CATALOG\", \"force_refresh\": true}" 2>&1)"
printf '%s\n' "$out" | head -20
n="$(printf '%s\n' "$out" | grep -c "Cold Chain Pharma Compliance B2" || true)"
[ "$n" -ge 1 ] || { echo "FAIL: list_models on $CATALOG does not return the B2 model"; exit 1; }
echo "POST-DEPLOY CHECK PASSED ($CATALOG answers list_models)"
