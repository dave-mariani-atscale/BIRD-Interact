#!/usr/bin/env bash
# Zero the engine's aggregates for the BIRD catalog so the next run is genuinely COLD.
#
#   bash scripts/reset_aggregates.sh            # deactivate through the engine, drop orphaned tables, verify
#   bash scripts/reset_aggregates.sh --status   # just report the counts
#
# Through the engine, not around it. The old protocol ran `drop schema aggregates
# cascade` in each BIRD database. That removes the tables and tells the engine
# nothing: its catalog (engine.aggregate_definitions.active_instance_id, and the
# instance's row in engine.aggregate_instance_statuses) still says "active", and
# the planner keeps routing to a table that is gone. It finds out only when a
# user query FAILS against the missing table (QueryFailedHealthCheck -> health
# checker -> Unreliable -> Invalid on the next miss), and until then the count the
# verification package asserts on is not zero. Measured 2026-09-16: 205 instances
# carried the reason aggregate_table_missing from exactly this. Harmless in
# leaderboard mode, where every graded query is hinted use_aggs(false), but a
# planted failure for any A/B run.
#
# Nor does a redeploy reset anything. Cube ids are name-derived (UUIDv5) and every
# BIRD cube has kept one id across a month of publishes; a publish only re-checks
# plans, and an aggregate whose plan still compiles stays active.
#
# What does work is the engine's own deactivate-all, the call behind the Design
# Center button:  DELETE /aggregates/projectId/{p}/cubeId/{c}
# It moves every Active/New/InProgress/Done instance of the cube to invalid
# (reason removed_by_admin), clears active_instance_id, and updates the engine's
# in-memory catalog in the same call. Measured: 48 -> 0 active on one cube,
# synchronously. The engine drops the physical tables itself only after
# aggregates.invalid.removalAge (2 days), so step 2 drops them now - but only the
# ones no active instance still points at, checked against the engine.
#
# nginx serves the engine under /engine and STRIPS the prefix (rewrite
# ^/engine/(.*) /$1), so the engine's /aggregates is http://localhost/engine/aggregates.
# The engine wants a Keycloak bearer token; the 64-char MCP API token is refused
# (401). Credentials come from the stack's compose .env unless overridden.
set -euo pipefail
cd "$(dirname "$0")/.."

ENGINE_URL="${ENGINE_URL:-http://localhost/engine}"
KC_URL="${KC_URL:-http://localhost:8083/auth}"
COMPOSE_ENV="${COMPOSE_ENV:-/Users/davidmariani/workspace/atscale/container-local-tooling/devel/docker/compose/.env}"
# The catalog the harness deploys (scripts/deploy_models.sh --catalog-name).
PROJECT_NAME="${AGG_PROJECT:-bird_atscale_models_catalog_main}"

# Read single variables; never `source` an env file (other services' keys, shell metacharacters).
envvar() { grep -m1 "^$2=" "$1" | cut -d= -f2- | tr -d '"'; }
PG_HOST="$(envvar .env PG_HOST)"; PG_PORT="$(envvar .env PG_PORT)"; PG_USER="$(envvar .env PG_USER)"
export PGPASSWORD; PGPASSWORD="$(envvar .env PG_PASSWORD)"
[ -n "$PG_HOST" ] && [ -n "$PGPASSWORD" ] || { echo "FAIL: PG_HOST/PG_PASSWORD missing from .env" >&2; exit 1; }

PG() { docker exec postgres psql -U atscale -d atscale -v ON_ERROR_STOP=1 -Atc "$1"; }      # engine metadata
WH() { psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$1" -v ON_ERROR_STOP=1 -Atc "$2"; } # BIRD warehouse
# The 22 BIRD databases. A run clones per-task scratch copies named <db>__<task>[__p1snap]
# and drops them minutes later, so they are skipped, and a database that vanished between
# the listing and the connect reads as having no tables.
WH_DBS() { WH postgres "select datname from pg_database where not datistemplate and datname<>'postgres' and datname not like '%\_\_%' order by 1"; }
AGG_TABLES() { WH "$1" "select table_name from information_schema.tables where table_schema='aggregates' order by 1" 2>/dev/null || true; }

token() {
    curl -s -m 15 "$KC_URL/realms/atscale/protocol/openid-connect/token" \
        -H 'Content-Type: application/x-www-form-urlencoded' \
        --data-urlencode "client_id=${KC_CLIENT_ID:-$(envvar "$COMPOSE_ENV" KC_ATSCALE_CLIENT_ID)}" \
        --data-urlencode "client_secret=${KC_CLIENT_SECRET:-$(envvar "$COMPOSE_ENV" KC_ATSCALE_CLIENT_SECRET)}" \
        --data-urlencode "username=${KC_USERNAME:-$(envvar "$COMPOSE_ENV" KC_ATSCALE_ADMIN_USERNAME)}" \
        --data-urlencode "password=${KC_PASSWORD:-$(envvar "$COMPOSE_ENV" KC_ATSCALE_ADMIN_PASSWORD)}" \
        --data-urlencode grant_type=password \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
}

# GET /cubes lists the published projects with their cube ids.
# Prints: project_id<TAB>cube_id<TAB>cube_name, one line per cube of PROJECT_NAME.
cubes() {
    curl -sf -m 30 -H "Authorization: Bearer $TOKEN" "$ENGINE_URL/cubes" | python3 -c '
import json,sys
want=sys.argv[1]
for p in json.load(sys.stdin)["response"]["projects"]:
    if p["name"]==want:
        for c in p["cubes"]: print(p["id"], c["id"], c["name"], sep="\t")' "$PROJECT_NAME"
}

# The predicate verification/verify/phases/60_attest.sh asserts on, scoped to one project.
ACTIVE_SQL="select count(*) from engine.aggregate_instances i
              join engine.aggregate_instance_statuses s on s.id=i.status_id
              join engine.aggregate_definitions d on d.id=i.definition_id
             where s.status='active' and d.project_id='%s'"
active_count() { PG "$(printf "$ACTIVE_SQL" "$1")"; }

report() {  # $1 = project_id
    echo "-- engine: active instances on $PROJECT_NAME, by cube"
    PG "select coalesce(m.table_database,'?')||'.'||d.cube_id||'  '||count(*)
          from engine.aggregate_definitions d
          join engine.aggregate_instances i on i.id=d.active_instance_id
          join engine.aggregate_instance_statuses s on s.id=i.status_id
          left join engine.aggregate_materializations m on m.id=i.materialization_id
         where s.status='active' and d.project_id='$1'
         group by m.table_database, d.cube_id order by 1" | sed 's/^/   /'
    echo "   total: $(active_count "$1")   (all projects on this engine: $(PG "select count(*) from engine.aggregate_instances i join engine.aggregate_instance_statuses s on s.id=i.status_id where s.status='active'"))"
    # Not served, but not gone either: the fixed-plans job re-activates an invalidplan
    # instance whose plan compiles again, and unreliable ones return on a successful probe.
    pend=$(PG "select string_agg(status||'='||n, ' ') from (select s.status, count(*) n from engine.aggregate_instances i join engine.aggregate_instance_statuses s on s.id=i.status_id join engine.aggregate_definitions d on d.id=i.definition_id where d.project_id='$1' and s.status in ('new','inprogress','done','pending','unreliable','invalidplan') group by 1) x")
    [ -n "$pend" ] && echo "   WARN non-terminal instances the API cannot deactivate: $pend"
    echo "-- warehouse: tables in each database's aggregates schema"
    for db in $(WH_DBS); do
        n=$(AGG_TABLES "$db" | grep -c . || true)
        [ "$n" -gt 0 ] && echo "   $db: $n"
    done
    return 0
}

TOKEN="$(token)" || { echo "FAIL: no Keycloak token (KC_URL=$KC_URL, creds from $COMPOSE_ENV)" >&2; exit 1; }
CUBES="$(cubes)"
[ -n "$CUBES" ] || { echo "FAIL: project '$PROJECT_NAME' is not published on $ENGINE_URL (set AGG_PROJECT)" >&2; exit 1; }
PROJECT_ID="${CUBES%%$'\n'*}"; PROJECT_ID="${PROJECT_ID%%$'\t'*}"   # first line, first field
NCUBES="$(printf '%s\n' "$CUBES" | wc -l | tr -d ' ')"

if [ "${1:-}" = "--status" ]; then report "$PROJECT_ID"; exit 0; fi

# An unhinted query from a live run would re-create what this removes, and its
# aggregates are the run's, not ours to drop mid-flight.
pgrep -f orchestrator.runner >/dev/null && { echo "refusing: an orchestrator.runner is still running" >&2; exit 1; }

echo "== before: $(active_count "$PROJECT_ID") active on $PROJECT_NAME ($PROJECT_ID, $NCUBES cubes)"
mkdir -p results/backups
f="results/backups/aggregates_before_reset_$(date +%Y%m%d_%H%M%S).tsv"
PG "select d.id, d.cube_id, d.connection_id, coalesce(m.table_database,''), coalesce(m.table_name,''), s.created_at
      from engine.aggregate_definitions d
      join engine.aggregate_instances i on i.id=d.active_instance_id
      join engine.aggregate_instance_statuses s on s.id=i.status_id
      left join engine.aggregate_materializations m on m.id=i.materialization_id
     where s.status='active' and d.project_id='$PROJECT_ID' order by d.connection_id, m.table_name" | tr '|' '\t' > "$f"
echo "== recorded $(wc -l < "$f" | tr -d ' ') active definitions to $f"

echo "== step 1: deactivating through the engine, cube by cube"
total=0
while IFS=$'\t' read -r pid cid cname; do
    out=$(curl -s -m 300 -w '\n%{http_code}' -X DELETE -H "Authorization: Bearer $TOKEN" \
              "$ENGINE_URL/aggregates/projectId/$pid/cubeId/$cid")
    code=${out##*$'\n'}; body=${out%$'\n'*}
    [ "$code" = 200 ] || { echo "FAIL: DELETE cube $cid ($cname) -> HTTP $code: $(printf '%s' "$body" | head -c 300)" >&2; exit 1; }
    n=$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin)["response"]["invalidated_count"])')
    [ "$n" -gt 0 ] && printf '   %-40s %s\n' "$cname" "$n"
    total=$((total + n))
done <<< "$CUBES"
echo "   invalidated $total instances"

active=$(active_count "$PROJECT_ID")
[ "$active" -eq 0 ] || { echo "FAIL: engine still reports $active active instance(s) on $PROJECT_NAME after deactivation" >&2; report "$PROJECT_ID"; exit 1; }
echo "== engine: 0 active on $PROJECT_NAME"

echo "== step 2: dropping tables no active instance points at (the engine would wait 2 days)"
backed_by_active() {  # $1 = database, $2 = table: does an ACTIVE instance still materialize here?
    PG "select count(*) from engine.aggregate_materializations m
          join engine.aggregate_instances i on i.materialization_id=m.id
          join engine.aggregate_instance_statuses s on s.id=i.status_id
         where s.status='active' and m.table_database='$1' and m.table_schema='aggregates' and m.table_name='$2'"
}
dropped=0; kept=0
for db in $(WH_DBS); do
    k=0
    for t in $(AGG_TABLES "$db"); do
        if [ "$(backed_by_active "$db" "$t")" -eq 0 ]; then
            WH "$db" "drop table if exists aggregates.\"$t\" cascade" >/dev/null; dropped=$((dropped + 1))
        else  # another project's live aggregate on this warehouse - not ours to drop
            k=$((k + 1))
        fi
    done
    [ "$k" -gt 0 ] && { echo "   keeping $k table(s) in $db.aggregates: backed by active instances outside $PROJECT_NAME"; kept=$((kept + k)); }
done
echo "   dropped $dropped orphaned table(s), kept $kept"

echo "== verify"
active=$(active_count "$PROJECT_ID")
orphans=0
for db in $(WH_DBS); do
    for t in $(AGG_TABLES "$db"); do
        [ "$(backed_by_active "$db" "$t")" -eq 0 ] && orphans=$((orphans + 1))
    done
done
report "$PROJECT_ID"
[ "$active" -eq 0 ] && [ "$orphans" -eq 0 ] || { echo "FAIL: active=$active orphaned tables=$orphans - NOT cold" >&2; exit 1; }
echo "== aggregates on $PROJECT_NAME are COLD. The feedback store is a separate step (scripts/reset_feedback_store.sh)."
