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
# Validate and deploy run on a STAGED copy holding only the SML project: catalog.yml
# plus every top-level folder with a non-empty models/ directory (the BIRD databases),
# with the git metadata sml-cli resolves the repository from. sml-cli reads every YAML
# file under the project root and rejects any ${VAR} it cannot classify as a template
# variable, so the repo's Docker compose files (verification/compose, scripts/) made
# every branch containing them undeployable. Selecting the models by what they contain
# rather than excluding named tooling folders means a new tooling folder cannot break
# deploys again - the same rule verification/build/fetch-models.sh applies. The gates
# still read the repo itself. DEPLOY_DRY_RUN=1 stops before the publish.
#
# Usage: scripts/deploy_models.sh [expected_model_count]   (default 22)
set -euo pipefail

ADK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${BIRD_MODELS_DIR:-$HOME/go/src/github.com/AtScaleInc/bird-atscale-models}"
EXPECTED="${1:-22}"
# The catalog to publish into, and so the schema list_models reports. Default is the one
# every recorded run names. A branch with a different catalog.yml (e.g. blind-build's
# bird_models_noq) MUST set this, or it publishes over the 22-model main catalog.
CATALOG_NAME="${CATALOG_NAME:-bird_atscale_models_catalog_main}"
echo "  catalog: $CATALOG_NAME"

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
echo "=== stage the SML project (catalog.yml + folders with a models/ directory) ==="
[ -f catalog.yml ] || { echo "FAIL: no catalog.yml at $MODELS_DIR"; exit 1; }
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/sml-deploy.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
cp -p catalog.yml "$STAGE"/
cp -Rp .git "$STAGE"/          # a directory in a clone, a gitdir pointer file in a worktree
STAGED=()
for d in */; do
  d="${d%/}"
  if [ -d "$d/models" ] && [ -n "$(ls -A "$d/models" 2>/dev/null)" ]; then
    cp -Rp "$d" "$STAGE"/ && STAGED+=("$d")
  fi
done
echo "  staged ${#STAGED[@]} model folders; left out: $(for d in */; do d="${d%/}"; [[ " ${STAGED[*]} " == *" $d "* ]] || printf '%s ' "$d"; done)"
[ "${#STAGED[@]}" -ge "$EXPECTED" ] || { echo "FAIL: staged ${#STAGED[@]} model folders, expected at least $EXPECTED"; exit 1; }

echo
echo "=== validate (the staged SML project) ==="
( cd "$STAGE" && sml-cli validate . 2>&1 | tail -3 )

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
if [ -n "${DEPLOY_DRY_RUN:-}" ]; then
  echo "  DEPLOY_DRY_RUN set - stopping before the publish (staged, validated, gated)."
  exit 0
fi
# Over IPv4: local.atscaleinternal.com is a localhost alias that resolves to ::1 first, and
# Docker Desktop's IPv6 port forward drops a large publish body, which sml-cli reports only as
# an opaque "FetchError: The request failed". The same body over 127.0.0.1 is accepted. Not a
# guarantee: on 2026-10-01 one IPv4 publish also failed with FetchError before reaching the api
# container (engine busy restarting) and the next attempt succeeded, so re-run once before digging.
# DEPLOY_LOG_LINES widens the sml-cli output kept below when a failure needs reading.
# A FetchError can also be a CLIENT give-up on a publish the server completed: on 2026-10-01 22:32
# the api logged `POST /v1/public/catalogs 201 ... Deployed catalog` while sml-cli printed FetchError,
# and two retries never reached the api. Before retrying, check `docker logs api | grep 'Deployed
# catalog'` and whether the live descriptions already carry the change; if so run gate_run.sh alone.
SML_API_URL="${SML_API_URL:-http://127.0.0.1:3001}"
# The catalog publish has two routes. The host route is sml-cli on this Mac posting through Docker
# Desktop's port forward. On 2026-10-02 four consecutive host publishes of a 11.7 MB body died with
# FetchError and NOT ONE reached the api container (no POST in its log), while the same staged
# project published first time from INSIDE the `api` container, where sml-cli talks to :3001 over
# loopback and no port forward is involved. The container route copies the staged project and the
# host's sml-cli install into the api container (node 22 is there; git is not, and sml-cli shells
# `git remote get-url origin` to find the repository, so a tiny shim answers it with this clone's
# values). DEPLOY_VIA_CONTAINER=1 takes the container route directly; otherwise it is the fallback
# after a host FetchError that the api log shows never arrived.
DEPLOY_T0="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
api_deployed() { docker logs --since "$DEPLOY_T0" api 2>&1 | grep -q "Deployed catalog"; }
deploy_in_container() {
  local cli="${SML_CLI_DIR:-$(dirname "$(dirname "$(readlink -f "$(command -v sml-cli)")")")}"
  [ -f "$cli/bin/run.js" ] || { echo "FAIL: sml-cli package not found at $cli (set SML_CLI_DIR)"; return 1; }
  local origin branch sha
  origin="$(git -C "$MODELS_DIR" remote get-url origin)"; branch="$(git -C "$MODELS_DIR" rev-parse --abbrev-ref HEAD)"; sha="$(git -C "$MODELS_DIR" rev-parse HEAD)"
  cat > "$STAGE/.git-shim" <<EOF
#!/bin/sh
# git stand-in for sml-cli inside the api container (no git there); answers for $branch@${sha:0:8}
case "\$*" in
  "remote get-url origin"*|"config --get remote.origin.url"*) echo "$origin" ;;
  "rev-parse --abbrev-ref HEAD"*) echo "$branch" ;;
  "rev-parse HEAD"*) echo "$sha" ;;
  *) echo "git shim: unhandled: \$*" >&2; exit 0 ;;
esac
EOF
  docker exec -u 0 api sh -c 'rm -rf /tmp/smlproj /tmp/sml-cli /tmp/bin && mkdir -p /tmp/bin' || return 1
  docker cp "$STAGE" api:/tmp/smlproj && docker cp "$cli" api:/tmp/sml-cli || return 1
  docker exec -u 0 api sh -c 'mv /tmp/smlproj/.git-shim /tmp/bin/git && chmod 755 /tmp/bin/git' || return 1
  docker exec -u 0 -e PATH=/tmp/bin:/usr/local/bin:/usr/bin:/bin -e HOME=/tmp \
    -e ATSCALE_API_URL=http://127.0.0.1:3001 -e ATSCALE_API_TOKEN="$TOKEN" api \
    sh -c "cd /tmp/smlproj && node /tmp/sml-cli/bin/run.js atscale-deploy . --catalog-name='$CATALOG_NAME' 2>&1 | tail -${DEPLOY_LOG_LINES:-8}"
  docker exec -u 0 api sh -c 'rm -rf /tmp/smlproj /tmp/sml-cli /tmp/bin' || true
}
if [ -n "${DEPLOY_VIA_CONTAINER:-}" ]; then
  echo "  DEPLOY_VIA_CONTAINER set - publishing from inside the api container"
  deploy_in_container
else
  ( cd "$STAGE" && ATSCALE_API_URL="$SML_API_URL" \
    ATSCALE_API_TOKEN="$TOKEN" \
    sml-cli atscale-deploy . --catalog-name="$CATALOG_NAME" 2>&1 | tail -${DEPLOY_LOG_LINES:-8} )
  if ! api_deployed; then
    echo "  host publish did not reach the api (no 'Deployed catalog' in its log since $DEPLOY_T0) - retrying from inside the api container"
    deploy_in_container
  fi
fi
if api_deployed; then
  echo "  api log confirms: $(docker logs --since "$DEPLOY_T0" api 2>&1 | grep -o 'Deployed catalog: [0-9a-f-]*' | tail -1)"
else
  echo "FAIL: no 'Deployed catalog' in the api log since $DEPLOY_T0 - the catalog was NOT published"; exit 1
fi

echo
echo "=== post-deploy gate (Q-17b: a working run_query is NOT evidence of health) ==="
CATALOG_NAME="$CATALOG_NAME" bash "$ADK_DIR/scripts/gate_run.sh" "$EXPECTED"
