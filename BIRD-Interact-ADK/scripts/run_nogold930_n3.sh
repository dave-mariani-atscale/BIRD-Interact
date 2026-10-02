#!/usr/bin/env bash
# FULL n=3 on the modified harness (prepared 2026-10-02): no-gold-930 models at Dianne's next head, Sonnet 5 agent /
# Sonnet 5 guarded simulator, 410 Query tasks x 3 repeats, a-interact, atscale, concurrency 5, corrected grading,
# memory ON and warming across repeats (run 1 cold), aggregates ON (Dave tracks aggregate usage). ~14 h.
# LLM requests time out at 180 s (default 600 s) and retry.
# Engine ghcr.io/atscaleinc/engine:pr10556, MCP bird-develop-rebase, catalog bird_models_no_gold_930.
#
# Run AFTER the models are deployed:
#   mkdir -p logs/nogold930_n3 && MODELS_SHA=<sha> nohup bash scripts/run_nogold930_n3.sh > logs/nogold930_n3/launcher.log 2>&1 &
# MODELS_SHA must equal the models worktree HEAD, origin, and the `deployed-n3` tag set at deploy time, so the run
# cannot measure a catalog other than the commit it names. Every reset is redone here because a publish's presample
# builds aggregates and any list_models (the gate's included) triggers it.
set -uo pipefail
cd /Users/davidmariani/workspace/atscale/BIRD-Interact/BIRD-Interact-ADK
M=$HOME/workspace/atscale/bird-atscale-models-no-gold-930
unset LEADERBOARD_MODE LEADERBOARD_AGENT_MODEL LEADERBOARD_TRACK LLM_ROUTING_FILE BIRD_LLM_DUMP_DIR SYSTEM_AGENT_MAX_TOKENS DISABLE_AGGREGATES
export ENVIRONMENT_BACKENDS_FILE=config/environment_backends.no_gold_930.yaml
# 180 s per-request timeout on the Sonnet 5 calls (config/llm_routing.anthropic_timeout180.yaml explains why).
export LLM_ROUTING_FILE=config/llm_routing.anthropic_timeout180.yaml
step(){ echo; echo "=== $(date +%H:%M:%S) $* ==="; }
busy(){ ps -eo args= 2>/dev/null | grep -E "(/Python|python[0-9.]*) -m orchestrator\.runner" | grep -vF grep >/dev/null; }
busy && { echo "REFUSING: a runner is active"; exit 1; }

step "models: the commit this run measures"
[ -n "${MODELS_SHA:-}" ] || { echo "REFUSING: set MODELS_SHA to the deployed models commit"; exit 1; }
head=$(git -C "$M" rev-parse HEAD); br=$(git -C "$M" rev-parse --abbrev-ref HEAD)
git -C "$M" fetch -q origin "$br"; org=$(git -C "$M" rev-parse "origin/$br"); dep=$(git -C "$M" rev-parse -q --verify deployed-n3 || echo none)
echo "  worktree $br @ ${head:0:8} | origin ${org:0:8} | deployed-n3 ${dep:0:8} | MODELS_SHA ${MODELS_SHA:0:8}"
[ -z "$(git -C "$M" status --porcelain)" ] || { echo "REFUSING: models worktree has uncommitted changes"; exit 1; }
for x in "$head" "$org" "$dep"; do [ "$(git -C "$M" rev-parse "$MODELS_SHA" 2>/dev/null)" = "$x" ] || { echo "REFUSING: MODELS_SHA, worktree, origin and deployed-n3 disagree"; exit 1; }; done

step "host: DNS, disk, containers"
dscacheutil -q host -a name api.anthropic.com | grep -q ip_address || { echo "REFUSING: api.anthropic.com does not resolve"; exit 1; }
free=$(df -g . | awk 'NR==2{print $4}'); echo "  free disk: ${free} GB"; [ "$free" -ge 12 ] || { echo "REFUSING: under 12 GB free"; exit 1; }
[ "$free" -ge 25 ] || echo "  WARNING: under 25 GB free for a ~14 h run (aggregate tables grow the Docker disk image; docker builder prune frees ~6 GB)"
for c in development-compose-engine-1 development-compose-mcp-1 api postgres bird_interact_postgresql_full; do
  s=$(docker inspect -f '{{.State.Status}}' $c 2>/dev/null); echo "  $c: $s"; [ "$s" = running ] || { echo "REFUSING: $c not running"; exit 1; }
done

step "zero the feedback store (3 tables; also stops the services)"
bash scripts/reset_feedback_store.sh 2>&1 | tail -3
post=$(docker exec postgres psql -U atscale -d atscale -Atc "select (select count(*) from mcp_feedback.exchange)+(select count(*) from mcp_feedback.feedback)+(select count(*) from mcp_feedback.certified_query);")
echo "  rows after reset: $post"; [ "$post" = "0" ] || { echo "REFUSING: store not empty"; exit 1; }

step "wait for MCP presample traffic AND the aggregate builds it queued to stop (both create aggregates)"
for i in $(seq 1 120); do
  n=$(docker exec postgres psql -U atscale -d atscale -Atc "select count(*) from engine.queries where service in ('user-query','aggregate-creation-service') and received > now() - interval '2 minutes';")
  [ "${n:-1}" -lt 5 ] && { echo "  quiet: $n user-query + aggregate-creation queries in the last 2 min"; break; }
  [ $i -eq 120 ] && { echo "REFUSING: engine still busy after 60 min ($n queries in 2 min)"; exit 1; }
  sleep 30
done
for P in bird_atscale_models_catalog_main bird_models_no_gold_930; do
  step "aggregates on $P: reset and confirm zero"
  AGG_PROJECT=$P bash scripts/reset_aggregates.sh 2>&1 | tail -1
  n=$(AGG_PROJECT=$P bash scripts/reset_aggregates.sh --status 2>&1 | grep -oE "total: [0-9]+" | grep -oE "[0-9]+" | head -1)
  echo "  active on $P: ${n:-?}"; [ "${n:-1}" = "0" ] || { echo "REFUSING: aggregates not zero on $P"; exit 1; }
done

step "start services on the modified-harness defaults (backends file: $ENVIRONMENT_BACKENDS_FILE)"
pkill -f "uvicorn" 2>/dev/null; sleep 2
bash scripts/start_services.sh >/dev/null 2>&1
for i in $(seq 1 30); do sleep 2; ok=0; for p in 6000 6001 6002; do curl --noproxy '*' -s -m 2 "http://127.0.0.1:$p/health" | grep -q healthy && ok=$((ok+1)); done; [ $ok -eq 3 ] && break; done
.venv-adk/bin/python - <<'PY' || exit 1
import sys, httpx, shared.environment_backends as e
exp=["timestamp_date","order_requires_cue","casefold_text","column_order_free","ties_as_ties","numeric_rel_tolerance"]
h={p:httpx.get(f"http://127.0.0.1:{p}/health",timeout=5).json() for p in (6000,6001,6002)}; a,u,d=h[6000],h[6001],h[6002]
bad=[]
if a.get("model")!="anthropic/claude-sonnet-5": bad.append(f"agent {a.get('model')}")
if u.get("model")!="anthropic/claude-sonnet-5": bad.append(f"sim {u.get('model')}")
if any(x.get("leaderboard_mode") for x in (a,u,d)): bad.append("leaderboard_mode on")
if any(x.get("aggregates_bypassed") for x in (a,d)): bad.append("aggregates bypassed - modified-harness runs keep them ON")
from shared import llm_routing as r
if r.route_kwargs("anthropic/claude-sonnet-5") != {"timeout": 180}: bad.append(f"routing {r.route_kwargs('anthropic/claude-sonnet-5')} from {r.routing_file()}")
g=d.get("grading") or {}
if g.get("regime")!="corrected" or sorted(g.get("corrections",[]))!=sorted(exp): bad.append(f"grading {g}")
doms=e.get_backend_config("atscale")["domains"]
if any(e.get_domain_config("atscale",db)["schema"]!="bird_models_no_gold_930" for db in doms): bad.append("a domain is not on no-gold-930")
print(f"  agent {a['model']} | sim {u['model']} ({u.get('simulator_variant')}) | leaderboard off | aggregates on | LLM timeout 180 s | grading {g['regime']} {len(g['corrections'])} corrections | {len(doms)} domains -> bird_models_no_gold_930")
if bad: print("  FAIL:", bad); sys.exit(1)
PY
[ $? -eq 0 ] || { echo "REFUSING: not on the 09-10 protocol"; exit 1; }

step "stack images and models"
docker inspect -f '  engine {{.Config.Image}} rev={{index .Config.Labels "org.opencontainers.image.revision"}}' development-compose-engine-1
docker inspect -f '  mcp    {{.Config.Image}} {{.Image}}' development-compose-mcp-1
git -C "$M" log -1 --format="  models $br @ %h %s" | cut -c1-130

mkdir -p logs/nogold930_n3
step "RUN: a-interact atscale --query-only, all 22 databases, repeat 3, concurrency 5"
bash scripts/run_eval.sh --mode a-interact --backend atscale --query-only --repeat 3 --concurrency 5 \
  --output results/nogold930_n3.json > logs/nogold930_n3/run.log 2>&1
echo "  finished rc=$? $(date +%H:%M:%S)"
