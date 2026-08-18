"""Dump, for every task in a run, what the agent actually submitted.

Usage:  python scripts/failing_sql.py <results.json> [instance_id ...]
        python scripts/failing_sql.py <results.json> --all      # passes too

The iteration loop this serves is "read the submitted SQL for every failing
task, then fix the model / MCP / guidance" — so the default is failures only,
and each task prints in the order the evidence is needed: the question, the tool
calls that errored, then each phase's submission beside its gold.

No LLM calls, no queries. Reads the results file only.
"""
import json, sys, os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
from shared.config import settings

argv = sys.argv[1:]
if not argv:
    sys.exit(__doc__)
PATH = argv[0]
SHOW_ALL = "--all" in argv
WANT = [a for a in argv[1:] if not a.startswith("-")]

res = json.load(open(PATH))
tasks = {}
for line in open(settings.data_path):
    d = json.loads(line)
    tasks[d["instance_id"]] = d


def gold_of(td, phase):
    """Gold SQL for a phase. Phase 2 lives under the follow_up object."""
    if phase == 1:
        return td.get("sol_sql") or td.get("gold_sql") or ""
    fu = td.get("follow_up") or {}
    return fu.get("sol_sql") or fu.get("gold_sql") or ""


def text(v, n=1200):
    s = v if isinstance(v, str) else json.dumps(v)
    return s if len(s) <= n else s[:n] + f"\n    ... [{len(s)-n} more chars]"


print(f"# {PATH}")
m = res.get("metrics", {})
print(f"# backend={res.get('backend')} tasks={m.get('total_tasks')} "
      f"avg={m.get('average_reward')} phase1={m.get('phase1_count')} phase2={m.get('phase2_count')}\n")

for r in sorted(res["results"], key=lambda r: r["instance_id"]):
    iid = r["instance_id"]
    if WANT and iid not in WANT:
        continue
    if not WANT and not SHOW_ALL and r["total_reward"] >= 1.0:
        continue
    td = tasks.get(iid, {})
    print("=" * 78)
    print(f"{iid}  reward={r['total_reward']}  p1={r['phase1_passed']} p2={r['phase2_passed']} "
          f"follow_up={r['has_follow_up']}  budget_used={r['budget_used']}/"
          f"{r['budget_used'] + r['budget_remaining']}")
    print("-" * 78)
    # The dataset's phase-1 question is `amb_user_query` (the deliberately
    # ambiguous one the agent is shown); follow-up uses the plain `query`.
    print("Q1:", text(td.get("amb_user_query", ""), 700))
    print("conditions:", td.get("conditions"), " output_type:", td.get("output_type"))
    amb = (td.get("user_query_ambiguity") or {}).get("critical_ambiguity") or []
    for a in amb:
        print(f"  ambiguity[{'MASKED' if a.get('is_mask') else 'open'}] {a.get('term')!r}"
              f" -> {str(a.get('sql_snippet'))[:160]}")
    fu = td.get("follow_up") or {}
    if fu:
        print("Q2:", text(fu.get("query", ""), 700))

    # Errors first: a task that never got a clean query is a plumbing story, not
    # a semantics one, and the submitted SQL alone does not show that.
    errs = []
    for t in r["tool_trajectory"]:
        got = str(t.get("result", ""))
        if t.get("tool") in ("run_query", "explore_columns", "focus_columns") and \
                ("rror" in got[:400] or "ailed" in got[:400]):
            errs.append((t["tool"], json.dumps(t.get("args", {}))[:300], got[:300]))
    if errs:
        print(f"\n-- {len(errs)} failed tool call(s) of {len(r['tool_trajectory'])} --")
        for tool, args, got in errs[:8]:
            print(f"  [{tool}] {args}\n     -> {got}")

    phase = 1
    for t in r["tool_trajectory"]:
        if t.get("tool") != "submit_sql":
            continue
        sql = (t.get("args") or {}).get("sql", "")
        print(f"\n-- SUBMITTED phase {phase} --\n{text(sql, 2500)}")
        print(f"-- verdict: {text(t.get('result', ''), 400)}")
        print(f"\n-- GOLD phase {phase} --\n{text(gold_of(td, phase), 2500)}")
        phase += 1

    if r["has_follow_up"] and phase == 1:
        print("\n(no submission at all)")
    print()
