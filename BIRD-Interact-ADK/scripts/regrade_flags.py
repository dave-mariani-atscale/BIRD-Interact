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
import atexit, json, sys, os, pickle
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

# Execution happens on a DISPOSABLE COPY of the template, never the template itself.
# ex_base runs the GOLD sql as well as the prediction, and a Management-category gold is
# DML - pointing this at `*_template` is how B-25 happened: an archive-and-delete ran
# into the template on 2026-08-12, stripped every non-NULL categoryperf out of
# annual_returns, and silently made etf_2 and etf_4 unwinnable for two days. The template
# is the clone source for every per-task DB and the reference gold is graded against, so
# it has to stay pristine. shared.db_utils now refuses non-read-only statements against a
# *_template database outright; this keeps re-grades working rather than merely blocked.
TEMPLATE = f"{DATABASE}_template"
ARM = argv[0]                  # raw | atscale
PATH = argv[1]
CACHE = argv[2] if len(argv) > 2 else f".regrade_cache_{DATABASE}_{ARM}.pkl"

def clean(sqls):
    """The cleanup step 1 of grading applies to both sides."""
    return U.remove_round(U.remove_distinct(U.remove_comments(list(sqls))))


tasks = {}
for line in open(settings.data_path):
    d = json.loads(line)
    if d.get("selected_database") == DATABASE:
        tasks[d["instance_id"]] = d

res = json.load(open(PATH))

DB = U.create_task_db(DATABASE, f"regrade_{ARM}")
atexit.register(lambda: U.drop_task_db(DB))
print(f"grading on scratch copy {DB} (template {TEMPLATE} untouched)")
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
# Full flag sets, never diffs, so a printed number traces to exactly one row.
# The first entry is the baseline every other row is compared against.
COMBOS = {
    # What .env held from 2026-08-11 to 2026-08-14, i.e. what the stored runs
    # were actually scored under.
    "pre-0814 (dec+casefold)":  dict(tie=False, dec=True,  cf=True,  rel=False, lint=False),
    "0814 (tie+rel+lint)":      dict(tie=True,  dec=True,  cf=True,  rel=True,  lint=True),
    "upstream (all off)":       dict(tie=False, dec=False, cf=False, rel=False, lint=False),
}

def gold(tid, phase):
    td = tasks[tid]
    if phase == 1:
        sol, cond = td.get("sol_sql"), td.get("conditions", {})
    else:
        fu = td.get("follow_up") or {}
        sol, cond = fu.get("sol_sql"), fu.get("conditions", {})
    # Same lift the live grader applies (db_environment/server.py); no-op unless
    # settings.grading_order_lint is on. Without this a re-grade silently
    # differs from the run it is re-grading.
    return sol, U.apply_order_lint(cond, tid, phase)

verdicts = {}   # combo -> {(tid,phase,sql): 0/1}
for name, flags in COMBOS.items():
    settings.grading_tie_tolerance = flags["tie"]
    settings.grading_honor_decimal = flags["dec"]
    settings.grading_casefold = flags["cf"]
    settings.grading_rel_tolerance = flags["rel"]
    settings.grading_order_lint = flags["lint"]
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
                # The live grader resets the task DB before every submission
                # (db_environment/server.py). Without this, a DML prediction or gold
                # changes the state the NEXT submission is graded against, which is
                # both wrong and order-dependent.
                U.reset_task_db(DB, TEMPLATE)
                conn = U.get_connection_for_phase(DB)
                # Step 1 of grading, on BOTH sides — remove_comments ->
                # remove_distinct -> remove_round. The live raw path gets it
                # from test_case_default; ex_base itself does none of it, so
                # calling ex_base directly graded ROUND()ed gold against
                # ROUND()ed prediction and disagreed with the run it was
                # replaying (exchange_traded_funds_3 recorded 1.0, replayed
                # 0.0). The reproduction check below is what surfaced it.
                v[(tid, phase, sql)] = U.ex_base(clean([sql]), clean(sol),
                                                 DB, conn, cond)
            else:
                v[(tid, phase, sql)] = U.ex_base_external_pred(pred, sol, DB, conn, cond)
        except Exception:
            v[(tid, phase, sql)] = 0
    verdicts[name] = v

# ---- reward replay -----------------------------------------------------------
# A phase pays 0.7/0.3. The retry discount (0.5/0.2) exists but applies ONLY in
# c-interact — a-interact pays full price on every attempt
# (db_environment/server.py:378). Mode comes from the results JSON rather than
# being assumed, since the same script re-grades both.
FIRST = {1: 0.7, 2: 0.3}
RETRY = {1: 0.5, 2: 0.2}
DISCOUNTS_RETRIES = res.get("mode") == "c-interact"


def reward_for(v):
    per = {}
    for r in res["results"]:
        tid = r["instance_id"]
        if tid not in tasks:
            continue
        phase, total, attempt = 1, 0.0, 0
        for (t, p, sql) in subs:
            if t != tid or p != phase:
                continue
            attempt += 1
            if v.get((t, p, sql)):
                table = RETRY if (DISCOUNTS_RETRIES and attempt > 1) else FIRST
                total += table[phase]
                if phase == 2:
                    break
                phase, attempt = 2, 0
                if not (tasks[tid].get("follow_up") or {}).get("sol_sql"):
                    break
        per[tid] = total
    return per

BASE = next(iter(COMBOS))
base = reward_for(verdicts[BASE])
print(f"\n=== {ARM} ({PATH}) — {len(subs)} submissions, baseline {BASE} ===")

# Does the baseline reproduce what the run recorded? If it does not, the replay
# and the live run disagree about something OTHER than the flags being swept,
# and no delta below is safe to quote until that is explained. Printed per task
# rather than as a total, because a total can net out to zero.
recorded = {r["instance_id"]: r.get("total_reward", 0.0) for r in res["results"]}
off = [(t, recorded.get(t), base[t]) for t in base
       if abs(base[t] - recorded.get(t, 0.0)) > 1e-9]
if off:
    print(f"!! baseline does NOT reproduce the recorded run on {len(off)} task(s) "
          f"(task, recorded, replayed): {off}")
else:
    print(f"baseline reproduces the recorded total ({sum(base.values()):.2f}).")
for name in COMBOS:
    per = reward_for(verdicts[name])
    tot = sum(per.values())
    diffs = [(t, base[t], per[t]) for t in per if abs(per[t] - base[t]) > 1e-9]
    print(f"{name:<26} avg={tot/len(per):.4f} total={tot:.2f}"
          f"  flips={len(diffs)} {diffs if diffs else ''}")

# which submissions changed verdict, per combo
for name in COMBOS:
    if name == BASE:
        continue
    ch = [(t, p, verdicts[BASE][k], verdicts[name][k])
          for k in verdicts[name]
          for t, p, _ in [k]
          if verdicts[name][k] != verdicts[BASE][k]]
    if ch:
        print(f"  submission verdict changes under {name}: {ch}")
