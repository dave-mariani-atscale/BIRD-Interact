#!/usr/bin/env bash
# Pre-run gate. Two independent failure modes, both of which have silently
# voided runs before, and neither of which the other detects:
#
#   1. Q-17b - a published model is materialised as a real relation by a
#      non-idempotent CREATE TABLE. list_models/explore_columns/focus_columns
#      hard-fail while run_query keeps returning CORRECT results, so the deploy
#      looks healthy while the agent is blind. Gate on list_models SUCCEEDING
#      and returning every model the run will actually address.
#
#      "Every model the run will actually address" means the domains of the
#      backend being gated, read from config/environment_backends.yaml - not a
#      hardcoded catalog. Gate 2 named `bird_atscale_models_catalog_main`
#      literally until 2026-09-19, so it reported "catalog healthy / GATE
#      PASSED" while `bird_models_v12` - the whole atscale_v12 arm - was absent
#      from the server. A run started then would have died at its first
#      metadata call with nothing in the gate to explain it. The catalog an arm
#      lives in is config, so the gate reads the same config the runner does.
#
#   2. Stale services - shared/environment_backends.py caches config in a
#      module-level dict at first load, and the uvicorn workers hold whatever
#      grading code was on disk when they started. A grading commit landing
#      after the services start is simply not in effect, and the run grades
#      under the old rules with no warning. Cost so far: the 2026-08-12
#      archeology run (0.000 live vs 0.140 on replay of its own submissions,
#      services 5h older than B-19).
#
# Usage: scripts/gate_run.sh [expected_model_count] [backend]
#
#   expected_model_count - a FLOOR on the models found across the gated
#       backends' schemas. The per-domain check below is the real gate; this
#       only catches a catalog that came back mostly empty.
#   backend - which backend's domains to check (e.g. atscale, atscale_v12).
#       DEFAULT: every backend in config/environment_backends.yaml that
#       declares domains. Checking everything is the safe default - a gate that
#       only looks where you tell it to look is how the 2026-09-19 blindness
#       happened. Name a backend explicitly when another arm is deliberately
#       undeployed and you do not want its absence to block this run.
set -e
cd "$(dirname "$0")/.."
EXPECTED="${1:-5}"
BACKEND="${2:-}"

echo "=== gate 1: services newer than the newest grading/harness commit ==="
LAST_CODE_COMMIT=$(git log -1 --format=%ct -- shared/ db_environment/ system_agent/ orchestrator/ config/)
LAST_CODE_HUMAN=$(git log -1 --format='%h %ad %s' --date=format:'%Y-%m-%d %H:%M' -- shared/ db_environment/ system_agent/ orchestrator/ config/)
PID=$(pgrep -f "uvicorn db_environment.server:app" | head -1 || true)
if [ -z "$PID" ]; then
  echo "FAIL: services are not running. Start them with scripts/start_services.sh"
  exit 1
fi
START=$(ps -p "$PID" -o lstart= | xargs)
START_EPOCH=$(date -j -f "%a %b %d %T %Y" "$START" +%s 2>/dev/null || echo 0)
echo "  newest code commit : $LAST_CODE_HUMAN"
echo "  services started   : $START (pid $PID)"
if [ "$START_EPOCH" -lt "$LAST_CODE_COMMIT" ]; then
  echo "FAIL: services predate the newest harness commit; they are running stale code."
  echo "      Restart with scripts/start_services.sh, then re-run this gate."
  exit 1
fi
echo "  OK - services are newer than the code"

echo
echo "=== gate 2: Q-17b catalog health via list_models, per backend domain ==="
source .venv-adk/bin/activate
PYTHONPATH=. python - "$EXPECTED" "$BACKEND" <<'PY'
import sys, re
from shared.config import settings
from shared.mcp_client import MCPClient, MCPEndpoint
from shared.environment_backends import load_backends

expected = int(sys.argv[1])
only = (sys.argv[2] or "").strip()

# What the RUNNER would address, read from the same config it reads. A backend
# with no domains routes nothing through a semantic layer (raw), so skip it.
backends = {n: c for n, c in load_backends().items() if c.get("domains")}
if only:
    if only not in backends:
        sys.exit(f"FAIL: backend {only!r} has no domains in config/environment_backends.yaml. "
                 f"Known: {sorted(backends)}")
    backends = {only: backends[only]}
if not backends:
    sys.exit("FAIL: no backend in config/environment_backends.yaml declares domains.")

cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                            bearer_token=settings.semantic_layer_mcp_token))
try:
    out = str(cli.call_tool("list_models", {}))
except Exception as e:
    sys.exit(f"FAIL: list_models errored ({type(e).__name__}: {str(e)[:120]}).\n"
             "      A working run_query is NOT evidence the catalog is healthy - "
             "that is exactly the Q-17b trap.")

# schema -> {model names present}, straight from the listing rows.
present = {}
for schema, table in re.findall(r'"table_schema":"([^"]+)","table_name":"([^"]+)"', out):
    present.setdefault(schema, set()).add(table)

failures, total = [], 0
for name, cfg in sorted(backends.items()):
    want = {}   # schema -> {model name: [domains asking for it]}
    for domain, d in sorted(cfg["domains"].items()):
        want.setdefault(d["schema"], {}).setdefault(d["table"], []).append(domain)
    for schema, tables in sorted(want.items()):
        have = present.get(schema, set())
        total += len(have)
        missing = sorted(t for t in tables if t not in have)
        print(f"  {name}: {schema} - {len(tables) - len(missing)}/{len(tables)} wanted model(s) "
              f"present ({len(have)} in the schema)"
              + (f", MISSING {missing}" if missing else ""))
        if not have:
            failures.append(f"{name}: schema {schema} is absent from the server entirely - "
                            f"the whole arm is undeployed ({len(tables)} domain(s) point at it)")
        elif missing:
            for t in missing:
                failures.append(f"{name}: {schema}.{t!r} is missing, wanted by domain(s) "
                                f"{want[schema][t]}")
        # Q-17/Catalog-suffix: Design Center appends the branch, sml-cli does not.
        # A run addresses ONE of them, so the other is a silent second copy.
        if schema.endswith("_main"):
            twin = schema[:-len("_main")]
            if twin in present:
                failures.append(f"{name}: an UNSUFFIXED catalog copy {twin!r} exists alongside "
                                f"{schema!r} (Q-17/Catalog-suffix)")

if failures:
    sys.exit("FAIL: " + "\n      ".join(failures) +
             "\n      Deploy the missing catalog, or name a single healthy backend as the "
             "2nd argument if this arm is down on purpose.")
if total < expected:
    sys.exit(f"FAIL: expected >= {expected} models across the gated schemas, found {total}.")
print(f"  OK - every domain of {', '.join(sorted(backends))} resolves to a published model")
PY
echo
echo "=== gate 3: template DB integrity (B-25) ==="
python3 "$(dirname "$0")/db_integrity_gate.py" || {
  echo "FAIL: a template database has drifted - gold would be graded against the wrong data."
  exit 1
}

echo
echo "GATE PASSED - safe to run"
