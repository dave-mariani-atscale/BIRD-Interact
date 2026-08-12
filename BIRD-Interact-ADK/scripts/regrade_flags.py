"""Re-grade a completed run under different grading-flag settings, offline.

Usage:  python scripts/regrade_flags.py raw|atscale <results.json> [cache.pkl]
                                       [--database NAME]

--database defaults to exchange_traded_funds. The template DB and the task
filter both follow it.


Free (no LLM calls). Raw arm: pred SQL re-executes against the pristine
template DB. AtScale arm: pred SQL is replayed through the local MCP run_query
once per submission and the rows cached, so flag toggling is in-memory.

Trajectory is held FIXED — this answers "what would the grader have said about
the SQL the agent actually wrote", not "what would the agent have done".
"""
import json, sys, os, pickle
# Repo root, derived from this file's own location rather than hardcoded: the
# grader resolves dataset paths relative to the working directory, so this has
# to chdir, but it must work on any checkout and not just the machine it was
# written on.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
from shared.config import settings
from shared import db_utils as U

argv = sys.argv[1:]
DATABASE = "exchange_traded_funds"
if "--database" in argv:
    i = argv.index("--database")
    DATABASE = argv[i + 1]
    del argv[i:i + 2]

DB = f"{DATABASE}_template"
ARM = argv[0]                  # raw | atscale
PATH = argv[1]
CACHE = argv[2] if len(argv) > 2 else f".regrade_cache_{DATABASE}_{ARM}.pkl"

tasks = {}
for line in open(settings.data_path):
    d = json.loads(line)
    if d.get("selected_database") == DATABASE:
        tasks[d["instance_id"]] = d

res = json.load(open(PATH))
conn = U.get_connection_for_phase(DB)

# ---- collect (task, phase, attempt, pred_sql) in trajectory order -----------
subs = []
for r in res["results"]:
    td = tasks.get(r["instance_id"])
    if not td:
        continue
    phase = 1
    for t in r["tool_trajectory"]:
        if t.get("tool") != "submit_sql":
            continue
        sql = (t.get("args") or {}).get("sql")
        if not sql:
            continue
        subs.append((r["instance_id"], phase, sql))
        if "Phase 1 correct" in str(t.get("result", "")):
            phase = 2

# ---- pred rows, computed once ----------------------------------------------
cache = pickle.load(open(CACHE, "rb")) if os.path.exists(CACHE) else {}
if ARM == "atscale":
    from shared.mcp_client import MCPClient, MCPEndpoint
    cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                                bearer_token=settings.semantic_layer_mcp_token))

for i, (tid, phase, sql) in enumerate(subs):
    key = (tid, phase, sql)
    if key in cache:
        continue
    if ARM == "raw":
        rows, err, to, _ = U.execute_queries([sql], DB, conn)
        cache[key] = None if (err or to) else rows
    else:
        q = sql
        if DATABASE == "exchange_traded_funds":
            # The r1 run targeted the since-retired bird_etf_prompt_only
            # deployment. Retarget at the current one; the 0810 model changes
            # were additive (two new attributes, description text), so existing
            # queries are unaffected — validated by the as-run total
            # reproducing 9.10. Other databases were never on that deployment.
            import re as _re
            q = q.replace("bird_etf_prompt_only_main", "bird_atscale_models_catalog_main")
            q = _re.sub(r'"?exchange_traded_funds_test"?', '"Exchange Traded Funds"', q)
        try:
            txt = cli.call_tool("run_query", {"query": q})
            cache[key] = U.parse_semantic_layer_rows(str(txt)) or None
        except Exception as e:
            print("  MCP fail", tid, phase, type(e).__name__, str(e)[:80])
            cache[key] = None
    if i % 10 == 0:
        pickle.dump(cache, open(CACHE, "wb"))
        print(f"  ...{i}/{len(subs)}", flush=True)
pickle.dump(cache, open(CACHE, "wb"))

# ---- grade under each flag combo -------------------------------------------
COMBOS = {
    "as-run (tie=T dec=T)":  (True,  True),
    "tie=F dec=T":           (False, True),
    "tie=T dec=F":           (True,  False),
    "tie=F dec=F (upstream)": (False, False),
}

def gold(tid, phase):
    td = tasks[tid]
    if phase == 1:
        return td.get("sol_sql"), td.get("conditions", {})
    fu = td.get("follow_up") or {}
    return fu.get("sol_sql"), fu.get("conditions", {})

verdicts = {}   # combo -> {(tid,phase,sql): 0/1}
for name, (tie, dec) in COMBOS.items():
    settings.grading_tie_tolerance = tie
    settings.grading_honor_decimal = dec
    v = {}
    for (tid, phase, sql) in subs:
        pred = cache.get((tid, phase, sql))
        sol, cond = gold(tid, phase)
        if pred is None or not sol:
            v[(tid, phase, sql)] = 0
            continue
        if isinstance(sol, str):
            sol = [sol]
        try:
            if ARM == "raw":
                v[(tid, phase, sql)] = U.ex_base([sql], sol, DB, conn, cond)
            else:
                v[(tid, phase, sql)] = U.ex_base_external_pred(pred, sol, DB, conn, cond)
        except Exception:
            v[(tid, phase, sql)] = 0
    verdicts[name] = v

# ---- reward replay (a-interact: 0.7 phase1 + 0.3 phase2, attempt-agnostic) --
def reward_for(v):
    per = {}
    for r in res["results"]:
        tid = r["instance_id"]
        if tid not in tasks:
            continue
        phase, total = 1, 0.0
        for (t, p, sql) in subs:
            if t != tid:
                continue
            if p != phase:
                continue
            if v.get((t, p, sql)):
                total += 0.7 if phase == 1 else 0.3
                if phase == 2:
                    break
                phase = 2
                if not (tasks[tid].get("follow_up") or {}).get("sol_sql"):
                    break
        per[tid] = total
    return per

base = reward_for(verdicts["as-run (tie=T dec=T)"])
print(f"\n=== {ARM} ({PATH}) — {len(subs)} submissions ===")
for name in COMBOS:
    per = reward_for(verdicts[name])
    tot = sum(per.values())
    diffs = [(t, base[t], per[t]) for t in per if abs(per[t] - base[t]) > 1e-9]
    print(f"{name:<24} avg={tot/len(per):.4f} total={tot:.2f}"
          f"  flips={len(diffs)} {diffs if diffs else ''}")

# which submissions changed verdict, per flag
for name in COMBOS:
    if name.startswith("as-run"):
        continue
    ch = [(t, p, verdicts['as-run (tie=T dec=T)'][k], verdicts[name][k])
          for k in verdicts[name]
          for t, p, _ in [k]
          if verdicts[name][k] != verdicts['as-run (tie=T dec=T)'][k]]
    if ch:
        print(f"  submission verdict changes under {name}: {ch}")
