#!/usr/bin/env bash
# Warehouse query timeout for the ENGINE's connections only (Dave, 2026-10-06). The engine's SQL for museum_artifact_2's
# "Environmental Risk Factor (All Ten Factors, Unrated As Zero)" query grows to ~12.7 GB and the Docker VM OOM-kills
# Postgres, which restarts and drops every connection - failing every concurrent task. Postgres cannot scope
# statement_timeout to one client (the engine and the harness both connect as root), so this cancels, every 5 s, any
# ACTIVE query from application_name 'PostgreSQL JDBC Driver' (the engine; the harness's psycopg2/psql connections carry
# none or 'psql') running longer than LIMIT_S. pg_cancel_backend cancels the statement, not the connection: the engine
# gets "canceling statement due to user request" and returns an error to the agent.
# LIMIT_S=60 from the engine's own history (2026-10-05/06, 28,070 warehouse subqueries): p99.9 1.4 s, longest SUCCESSFUL
# 49.2 s, fastest OOM kill at 72 s - so 60 s touches no query that has ever succeeded and stops the runaway before it kills.
#   nohup bash scripts/warehouse_query_watchdog.sh > logs/warehouse_query_watchdog.log 2>&1 &
LIMIT_S=${LIMIT_S:-60}
# The warehouse container: the development stack's by default; the verification
# package's compose project names it bird-verify-bird-warehouse-1 and sets this.
WAREHOUSE_CONTAINER="${WAREHOUSE_CONTAINER:-bird_interact_postgresql_full}"
echo "$(date '+%m-%d %H:%M:%S') watchdog up: cancel engine (PostgreSQL JDBC Driver) queries active > ${LIMIT_S}s on $WAREHOUSE_CONTAINER"
while true; do
  docker exec -i "$WAREHOUSE_CONTAINER" psql -U root -d postgres -AtF' | ' -c "
    select pg_cancel_backend(pid), pid, datname, round(extract(epoch from now()-query_start)) as secs,
           left(regexp_replace(query, '\s+', ' ', 'g'), 160)
    from pg_stat_activity
    where application_name = 'PostgreSQL JDBC Driver' and state = 'active' and pid <> pg_backend_pid()
      and now() - query_start > interval '${LIMIT_S} seconds'" 2>&1 | grep -v '^$' | while read -r l; do echo "$(date '+%m-%d %H:%M:%S') CANCELLED $l"; done
  sleep 5
done
