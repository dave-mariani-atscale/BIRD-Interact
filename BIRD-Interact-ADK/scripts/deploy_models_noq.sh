#!/usr/bin/env bash
# Deploy the no-questions arm (AtScaleInc/bird-atscale-models, branch no-questions, worktree
# ../bird-atscale-models-noq) to the bird_models_noq catalog, then gate it.
#
# A copy of scripts/deploy_models_v12.sh with three differences:
#   - MODELS_DIR is the no-questions worktree, overridable with BIRD_MODELS_NOQ_DIR
#   - the catalog is bird_models_noq (config/environment_backends.yaml, atscale_noq)
#   - A8 and A10 are replaced by utilities/noq_gate.py: this arm reads nothing from the task
#     file, not even the deleted KB ids (decided 2026-09-29), so there is no brief to gate on
# The pre-flight refuses anything but branch no-questions: sml-cli deploys what the REMOTE
# branch holds, and deploying main from here would publish the 22 tuned models into this catalog.
#
# NODE_OPTIONS preloads scripts/sml_fetch_retry.cjs (E-23: the deploy POST reuses a
# keep-alive socket the API has already closed; one retry on a fresh socket fixes it).
#
# Usage: scripts/deploy_models_noq.sh [expected_model_count]   (default 1)
set -euo pipefail

ADK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${BIRD_MODELS_NOQ_DIR:-$HOME/go/src/github.com/AtScaleInc/bird-atscale-models-noq}"
EXPECTED="${1:-1}"
CATALOG=bird_models_noq

[ -d "$MODELS_DIR" ] || { echo "FAIL: no-questions worktree not found at $MODELS_DIR"; exit 1; }

# Read only the one variable we need. Never `source` the .env - it holds other
# services' keys, and a value containing shell metacharacters gets executed.
TOKEN="$(grep -m1 '^SEMANTIC_LAYER_MCP_TOKEN=' "$ADK_DIR/.env" | cut -d= -f2-)"
[ ${#TOKEN} -eq 64 ] || { echo "FAIL: expected a 64-char user-scoped API token, got ${#TOKEN} chars"; exit 1; }

# A stale exported token overrides the .env one and 401s every MCP call, which
# looks exactly like E-14 (A-71, labor_certification 2026-09-27).
unset SEMANTIC_LAYER_MCP_TOKEN || true

cd "$MODELS_DIR"

echo "=== pre-flight: everything committed? ==="
if [ -n "$(git status --porcelain)" ]; then
  echo "FAIL: uncommitted changes in $MODELS_DIR."
  echo "      deploy only committed state, so the deployed model always has a commit id."
  git status --short
  exit 1
fi
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "no-questions" ] || { echo "FAIL: $MODELS_DIR is on $BRANCH, not no-questions"; exit 1; }
# sml-cli COMPILES THE LOCAL TREE (verified in its source 2026-09-29: compile(localPath)); the git
# remote only names the repository, via `git remote get-url origin`, and the repository id seeds
# every object UUID. A worktree shares main's config, so without the worktree-scoped insteadOf
# below this branch would deploy under main's repository id and its objects could collide with
# the tuned labor model's (the insider_trading A/B "SML names are repo-wide" finding).
ORIGIN="$(git remote get-url origin)"
case "$ORIGIN" in
  *bird-atscale-models-noquestions*) echo "  OK - repository id from $ORIGIN (distinct from main)";;
  *) echo "FAIL: origin resolves to $ORIGIN - set the worktree insteadOf (see docs/model-change-log.md)"; exit 1;;
esac
# The real remote is `atscaleinc`. Pushing needs Dianne's OK, so an unpushed branch warns only.
git fetch -q atscaleinc "$BRANCH" 2>/dev/null || true
if [ "$(git rev-parse HEAD)" != "$(git rev-parse -q --verify "atscaleinc/$BRANCH" || echo none)" ]; then
  echo "  WARN - $BRANCH at $(git rev-parse --short HEAD) is not on atscaleinc; deploying the local commit"
else
  echo "  OK - $BRANCH matches atscaleinc at $(git rev-parse --short HEAD)"
fi

echo
echo "=== validate (run from the repo ROOT: catalog.yml lives here) ==="
sml-cli validate . 2>&1 | tail -3

echo
echo "=== no-questions gate (replaces A8 and A10), per model ==="
G_FAILED=0
for m in */; do
  [ -f "${m}generator/spec.py" ] || continue
  kb="$ADK_DIR/bird-interact-full/${m%/}/${m%/}_kb.jsonl"
  [ -f "$kb" ] || { echo "FAIL: no KB at $kb"; exit 1; }
  python3 utilities/noq_gate.py --model-dir "${m%/}" --kb "$kb" | tail -1 || G_FAILED=1
done
[ "$G_FAILED" -eq 0 ] || { echo "FAIL: a no-questions gate failed - fix before deploying."; exit 1; }

echo "=== deploy to $CATALOG ==="
NODE_OPTIONS="--require $ADK_DIR/scripts/sml_fetch_retry.cjs" \
ATSCALE_API_URL=http://local.atscaleinternal.com:3001 \
ATSCALE_API_TOKEN="$TOKEN" \
  sml-cli atscale-deploy . --catalog-name="$CATALOG" 2>&1 | tail -8

echo
echo "=== post-deploy gate (wait first: atscale-deploy can kill the engine AFTER reporting success, E-14) ==="
python3 -c "import time; time.sleep(120)"
bash "$ADK_DIR/scripts/gate_run.sh" "$EXPECTED" atscale_noq
