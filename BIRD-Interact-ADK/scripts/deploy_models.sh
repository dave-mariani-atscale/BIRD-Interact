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
# Deploying publishes the WHOLE catalog: all five BIRD models go out together.
#
# Usage: scripts/deploy_models.sh [expected_model_count]   (default 5)
set -euo pipefail

ADK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${BIRD_MODELS_DIR:-$HOME/go/src/github.com/AtScaleInc/bird-atscale-models}"
EXPECTED="${1:-5}"

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
for m in */; do
  brief="${m}brief/task_brief.json"
  [ -f "$brief" ] || continue
  python3 utilities/question_leakage_gate.py --model-dir "${m%/}" --brief "$brief" 2>&1 | tail -1
done

echo
echo "=== deploy ==="
ATSCALE_API_URL=http://local.atscaleinternal.com:3001 \
ATSCALE_API_TOKEN="$TOKEN" \
  sml-cli atscale-deploy . --catalog-name=bird_atscale_models_catalog_main 2>&1 | tail -8

echo
echo "=== post-deploy gate (Q-17b: a working run_query is NOT evidence of health) ==="
bash "$ADK_DIR/scripts/gate_run.sh" "$EXPECTED"
