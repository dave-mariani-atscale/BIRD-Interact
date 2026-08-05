#!/usr/bin/env bash
# Creates one AtScale data-warehouse connection-group per BIRD-Interact
# database, named "bird_<database>". Verified end-to-end against a live
# instance before being handed over (one probe connection was created and
# confirmed successful, then the script was finalized for all 22).
#
# Usage: cp .env.example .env, fill in ATSCALE_CLIENT_SECRET and PG_PASSWORD,
# then: bash create_bird_connections.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

if [ -z "${ATSCALE_CLIENT_SECRET:-}" ] || [ -z "${PG_PASSWORD:-}" ]; then
  echo "ATSCALE_CLIENT_SECRET and/or PG_PASSWORD are not set." >&2
  echo "Copy .env.example to .env in this directory and fill in real values." >&2
  exit 1
fi

# ── AtScale auth (Keycloak password grant) ──
# Keycloak is a container, so nginx on :80 proxies to it fine.
ATSCALE_BASE_URL="${ATSCALE_BASE_URL:-http://localhost}"

# ── Engine API ──
# NOT ${ATSCALE_BASE_URL}/engine. nginx resolves that prefix to a container
# named "engine"; when the engine runs natively on the host instead, the name
# doesn't resolve and every call returns 502 ("engine could not be resolved").
# Talking to the engine's own port skips nginx entirely. For a containerized
# engine: ENGINE_URL=http://localhost/engine bash create_bird_connections.sh
ENGINE_URL="${ENGINE_URL:-http://localhost:10502}"
CLIENT_ID="atscale-modeler"
CLIENT_SECRET="${ATSCALE_CLIENT_SECRET}"
ATSCALE_USERNAME="atscale-kc-admin" # "dave@atscale.com"
ATSCALE_PASSWORD="@scaleAdmin123" # "123"

# ── Postgres data warehouse details (same server for every BIRD database) ──
# This host/port is resolved by the ENGINE, not by this script. With the engine
# running natively, "localhost" is correct; a containerized engine needs
# host.docker.internal instead, since its own "localhost" is the container.
# 5433 is bird_interact_postgresql_full, which holds the 22 BIRD databases —
# not 10514 (testdata-db), a different server with different credentials.
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5433}"
PG_USER="root"
AGGREGATE_SCHEMA="aggregates"

# ── The 22 BIRD-Interact databases ──
BIRD_DATABASES=(
  archeology_scan
  cold_chain_pharma_compliance
  cross_border
  crypto_exchange
  cybermarket_pattern
  disaster_relief
  exchange_traded_funds
  fake_account
  households
  hulushows
  insider_trading
  labor_certification_applications
  mental_health
  museum_artifact
  organ_transplant
  planets_data
  polar_equipment
  reverse_logistics
  robot_fault_prediction
  solar_panel
  sports_events
  virtual_idol
)

echo "Fetching AtScale access token..."
TOKEN=$(curl -s --location "${ATSCALE_BASE_URL}/auth/realms/atscale/protocol/openid-connect/token" \
  --header 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "client_id=${CLIENT_ID}" \
  --data-urlencode "client_secret=${CLIENT_SECRET}" \
  --data-urlencode "username=${ATSCALE_USERNAME}" \
  --data-urlencode "password=${ATSCALE_PASSWORD}" \
  --data-urlencode 'grant_type=password' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

if [ -z "$TOKEN" ]; then
  echo "Failed to obtain access token." >&2
  exit 1
fi
echo "Token acquired."
echo

FAILURES=()

for db in "${BIRD_DATABASES[@]}"; do
  name="bird_${db}"
  echo "Creating connection: ${name} ..."

  response=$(curl -s -w '\n%{http_code}' --location "${ENGINE_URL}/connection-groups" \
    --header "Authorization: Bearer ${TOKEN}" \
    --header 'Content-Type: application/json' \
    --data "{
      \"name\": \"${name}\",
      \"platformType\": \"postgresql\",
      \"connectionId\": \"${name}\",
      \"aggregateSchema\": \"${AGGREGATE_SCHEMA}\",
      \"database\": \"${db}\",
      \"isImpersonationEnabled\": false,
      \"isCanaryAlwaysEnabled\": false,
      \"isPartialAggHitEnabled\": false,
      \"readOnly\": false,
      \"extraProperties\": {
          \"udafSchema\": \"\",
          \"udafMode\": \"udaf_disabled\"
      },
      \"secretProperties\": {},
      \"secretRefs\": {},
      \"subgroups\": [
          {
              \"name\": \"${name}\",
              \"hosts\": \"${PG_HOST}\",
              \"port\": ${PG_PORT},
              \"connectorType\": \"postgresql\",
              \"username\": \"${PG_USER}\",
              \"isKerberosClientEnabled\": false,
              \"extraJdbcFlags\": \"\",
              \"database\": \"${db}\",
              \"queryRoles\": [
                  \"agg_creation_role\",
                  \"large_user_query_role\",
                  \"small_user_query_role\",
                  \"system_query_role\"
              ],
              \"extraProperties\": {
                  \"udafSchema\": \"\",
                  \"udafMode\": \"udaf_disabled\"
              },
              \"secretProperties\": {
                  \"password\": \"${PG_PASSWORD}\"
              },
              \"secretRefs\": {}
          }
      ],
      \"visibleQueryRoles\": {
          \"small_user_query_role\": true,
          \"canary_query_role\": false,
          \"system_query_role\": true,
          \"agg_creation_role\": true,
          \"large_user_query_role\": true
      }
  }")

  http_code=$(echo "$response" | tail -n1)
  body=$(echo "$response" | sed '$d')

  if [ "$http_code" = "201" ] || [ "$http_code" = "200" ]; then
    echo "  OK (${http_code})"
  else
    echo "  FAILED (${http_code}): ${body}"
    FAILURES+=("$name")
  fi
done

echo
if [ ${#FAILURES[@]} -eq 0 ]; then
  echo "All 22 connections created successfully."
else
  echo "${#FAILURES[@]} connection(s) failed: ${FAILURES[*]}"
  exit 1
fi
