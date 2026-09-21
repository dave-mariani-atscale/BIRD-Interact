#!/usr/bin/env python3
"""Write the per-task unwinnable register: every task the leaderboard-mode census
counts, with its question and the cited reason it cannot be won.

The census file itself (`census_lb*_final.json`) carries the verdicts and the
machine measurements; `LEADERBOARD_TASK_CENSUS.md` carries the method and the
category totals. Neither shows, task by task, what the user actually asked and
why no correct answer can score - which is the thing anyone contesting the
census needs to read. This generates that register.

Every reason is quoted, not written here: the prose comes from the census
`why` fields (revision 5, falling back to revision 3 where revision 4 moved a
tier but kept the text, and to the phase-2 status file for phase-2 defects), and
where a task has no prose the reason is stated from the machine measurement -
ordering flag, ordering cue, replan result, row count.

    PYTHONPATH=. .venv-adk/bin/python scripts/gen_unwinnable_tasks_doc.py \
        --census ../../bird-atscale-models/census/census_lb7_final.json \
        --out ../../bird-atscale-models/docs/UNWINNABLE_TASKS.md
"""
from __future__ import annotations

import argparse
import json
import textwrap
from collections import defaultdict
from datetime import date
from pathlib import Path

CENSUS_DIR = Path("/Users/davidmariani/workspace/atscale/bird-atscale-models/census")
DATA = Path("bird-interact-full/bird_interact_data.jsonl")

#: Phase-1 categories, in the order a task is assigned to exactly one of them.
P1_CATEGORIES = [
    ("gold_defect", "Gold is defective or unreachable",
     "Gold's own answer does not follow from the question, the knowledge base and the "
     "ambiguities the simulated user will resolve - a contradicted filter, a grain the "
     "question never asks for, a constant or label that appears nowhere the agent can read. "
     "Census tier 1, verified task by task."),
    ("plan_dependent", "The answer depends on the query plan",
     "`order: true` over a gold whose ORDER BY leaves ties, a LIMIT or window function over "
     "tied rows, or row content that changes with the plan. Two correct queries disagree, so "
     "no query reproduces gold except by luck. Census tier 2."),
    ("order_plan_dependent_measured", "Row order undetermined, and the question never asks for one",
     "`order: true` with no ordering cue anywhere in the question, over a gold whose row order "
     "changes when the planner is pushed off its chosen operators. Our own regime compares these "
     "as a set; upstream honours the dataset flag, so the agent has to guess both that an order "
     "is wanted and which one."),
    ("waived_rev4_correction", "Gold's text casing or column order, which nothing discloses",
     "Gold wraps labels in `LOWER()`/`TRIM()` the question never mentions, or projects columns in "
     "an order the question contradicts. Census revision 4 waived these by adopting the casefold "
     "and column-order corrections as census rules; upstream compares text case-sensitively and "
     "tuples positionally, so the defect stands."),
    ("falsified_rev5_under_corrections", "Retired by a pass that only the corrections allowed",
     "Census revision 5 retired the tier on a live pass in the 2026-09-06/07 sweep, which was "
     "scored with the corrections on. Under the board's comparison the task has still never "
     "passed."),
]
P2_CATEGORIES = [
    ("gold_p2", "Phase-2 gold defect"),
    ("content_p2", "Phase-2 row content depends on the plan"),
    ("order_p2", "Phase-2 row order undetermined"),
    ("order_plan_dependent_measured", "Phase-2 row order plan-dependent (measured)"),
    ("plan_dependent", "Plan-dependent at phase 2"),
    ("gold_defect", "Phase-2 gold unreachable"),
    ("waived_rev4_correction", "Phase-2 casing or column order nothing discloses"),
    ("falsified_rev5_under_corrections", "Phase-2 tier retired under the corrections"),
]


def clean(text, limit=None):
    t = " ".join((text or "").split())
    if limit and len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return t


def load_json(p):
    return json.load(open(p))


def why_for(tid, rec, r5, r3, status, meas, phase):
    """The cited reason, and where it came from."""
    if phase == "p2":
        w = (status.get(tid) or {}).get("why")
        if w and "phase-2" in w.lower():
            return clean(w), "phase-2 status file, 2026-09-06"
    for src, label in ((r5, "census revision 5"), (r3, "census revision 3")):
        w = (src.get(tid) or {}).get("why")
        if w:
            return clean(w), label
    m = (meas.get(tid) or {}).get(phase) or {}
    if m.get("order_plan_dependent"):
        return (f"Measured: `conditions.order` is true and the question carries no ordering cue, "
                f"so upstream compares gold's {m.get('rows', '?')} rows row by row; re-running gold "
                f"with the planner pushed off its chosen operators returns the same rows in a "
                f"different order, so the expected sequence is an artefact of the plan."), "measured here"
    # No prose on file: state the flag that set the verdict and what was measured
    # beside it, rather than leaving the entry empty.
    flags = [f for f in ("gold_p2", "content_p2", "order_p2")
             if (r5.get(tid) or {}).get(f)]
    if flags:
        names = {"gold_p2": "a phase-2 gold defect",
                 "content_p2": "phase-2 row content that changes with the query plan",
                 "order_p2": "a phase-2 row order the follow-up gold does not determine"}
        said = " and ".join(names[f] for f in flags)
        extra = ""
        if m.get("rows") is not None:
            extra = (f" Measured here: gold returns {m['rows']} row"
                     f"{'' if m['rows'] == 1 else 's'}"
                     + (", graded row by row (`order: true`"
                        + (", and the question carries no ordering cue)" if not m.get("cue")
                           else ")") if m.get("order") else ", compared as a set")
                     + ".")
        return (f"Census revision 5 records {said} for this task ("
                f"{', '.join('`' + f + '`' for f in flags)}); the flag comes from the phase-2 "
                f"sweep and no per-task prose was written for it." + extra), "census revision 5 flags"
    return "(no prose on file - see the census record)", "census record"


def question_for(task, phase):
    if phase == "p1":
        return clean(task["amb_user_query"])
    return clean((task.get("follow_up") or {}).get("query"))


def pick(reasons, categories):
    for key, *_ in categories:
        if key in reasons:
            return key
    return reasons[0] if reasons else "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rev3", default=str(CENSUS_DIR / "census_rev3_final.json"))
    ap.add_argument("--rev5", default=str(CENSUS_DIR / "census_rev5_final.json"))
    ap.add_argument("--status", default=str(CENSUS_DIR / "per_task_status_20260906.json"))
    ap.add_argument("--measurements", default=str(CENSUS_DIR / "lb1_measurements.json"))
    a = ap.parse_args()

    cen = load_json(a.census)
    r3, r5 = load_json(a.rev3), load_json(a.rev5)
    status, meas = load_json(a.status), load_json(a.measurements)
    tasks = {}
    for line in open(DATA):
        t = json.loads(line)
        tasks[t["instance_id"]] = t

    T = cen["tasks"]
    runs = cen.get("runs_used") or []
    task_runs = sum(r.get("n", 0) for r in runs)
    q = {k: v for k, v in T.items() if v["category"] == "Query"}
    p1 = {k: v for k, v in q.items() if v["p1"]["unwinnable"]}
    p2_only = {k: v for k, v in q.items()
               if v["p2"]["unwinnable"] and not v["p1"]["unwinnable"]}
    r5_unw = {k for k, v in r5.items() if v["tier"] in ("T1", "T2")}

    by_cat = defaultdict(list)
    for tid, rec in sorted(p1.items()):
        by_cat[pick(rec["p1"]["reasons"], P1_CATEGORIES)].append(tid)
    by_cat2 = defaultdict(list)
    for tid, rec in sorted(p2_only.items()):
        by_cat2[pick(rec["p2"]["reasons"], P2_CATEGORIES)].append(tid)

    out = []
    w = out.append
    w("# Unwinnable tasks, one by one: the question, and why no correct answer scores")
    w("")
    w(f"> **Census {cen.get('revision')}, generated {date.today()}** from "
      f"`census/{Path(a.census).name}` by `BIRD-Interact-ADK/scripts/gen_unwinnable_tasks_doc.py`. "
      f"Method, categories and totals: `docs/LEADERBOARD_TASK_CENSUS.md`. Regime: the leaderboard "
      f"protocol - rows compare exactly as `evaluation/src/eval_bird_interact.py` does, with none "
      f"of this harness's six comparison corrections.")
    w("")
    w(f"> Every task below carries a **cited reason** AND has **zero passes** across "
      f"**{len(runs)} leaderboard-mode runs / {task_runs:,} task-runs**, both arms and every agent "
      f"model run to date. One live pass under the board's own comparison retires a task from the "
      f"census, so this list is a floor, not a claim: tasks nobody has won but that carry no cited "
      f"defect are left out.")
    w("")
    w(f"**{len(p1)} of the 410 Query tasks cannot be won at phase 1** "
      f"({len(p1) / 410:.1%}), and **{len(p1) + len(p2_only)} at phase 2** "
      f"({len(p1) + len(p2_only)} = {len(p1)} of them plus {len(p2_only)} that are winnable at "
      f"phase 1 and lost at phase 2). Of the phase-1 set, {len(set(p1) & r5_unw)} are also "
      f"unsolvable under this harness's corrected grading (census revision 5) and "
      f"{len(set(p1) - r5_unw)} are unwinnable only because the board applies none of the "
      f"corrections.")
    w("")

    w("## Index")
    w("")
    w("| task | database | phase | category | passes |")
    w("|---|---|:--:|---|:--:|")
    for key, title, _desc in P1_CATEGORIES:
        for tid in by_cat.get(key, []):
            rec = T[tid]
            w(f"| [`{tid}`](#{tid.replace('_', '-')}) | {rec['db']} | 1 | {title} | "
              f"0/{rec['lb_runs']} |")
    for key, title in P2_CATEGORIES:
        for tid in by_cat2.get(key, []):
            rec = T[tid]
            w(f"| [`{tid}`](#{tid.replace('_', '-')}) | {rec['db']} | 2 | {title} | "
              f"0/{rec['lb_runs']} |")
    w("")

    def entries(cat_list, bucket, phase):
        for key, title, *rest in cat_list:
            ids = bucket.get(key, [])
            if not ids:
                continue
            desc = rest[0] if rest else None
            w(f"### {title} ({len(ids)})")
            w("")
            if desc:
                w(textwrap.fill(desc, 96))
                w("")
            for tid in ids:
                rec = T[tid]
                task = tasks[tid]
                why, src = why_for(tid, rec, r5, r3, status, meas, phase)
                m = (meas.get(tid) or {}).get(phase) or {}
                w(f"<a id=\"{tid.replace('_', '-')}\"></a>**`{tid}`** &nbsp; "
                  f"*{rec['db']}* &nbsp; · &nbsp; census tier {rec.get('tier_rev5')} "
                  f"· 0 passes in {rec['lb_runs']} runs"
                  + (f" · gold returns {m['rows']} row{'' if m['rows'] == 1 else 's'}"
                     if m.get("rows") is not None else "")
                  + (" · `order: true`, no ordering cue in the question"
                     if m.get("order") and not m.get("cue") else "")
                  + "  ")
                w(f"**Q.** {question_for(task, phase)}  ")
                w(f"**Why.** {why} *({src})*")
                w("")

    w("## Phase 1 - the tasks no correct answer can win")
    w("")
    entries(P1_CATEGORIES, by_cat, "p1")
    w("## Phase 2 only - winnable at phase 1, unwinnable at phase 2")
    w("")
    w("Phase 2 is graded only after phase 1 passes, so every task above is also lost at phase 2. "
      "These are the tasks that are reachable at phase 1 and then hit a defect in the follow-up.")
    w("")
    entries([(k, t, None) for k, t in P2_CATEGORIES], by_cat2, "p2")

    w("## Per database")
    w("")
    w("| database | Query tasks | unwinnable P1 | unwinnable P2 | winnable P1 | winnable P2 |")
    w("|---|---:|---:|---:|---:|---:|")
    per = cen["per_db"]
    tot = defaultdict(int)
    for db, k in per.items():
        n, u1, u2 = k.get("q_n", 0), k.get("q_unw_p1", 0), k.get("q_unw_p2", 0)
        tot["n"] += n
        tot["u1"] += u1
        tot["u2"] += u2
        w(f"| {db} | {n} | {u1} | {u2} | {n - u1} | {n - u2} |")
    w(f"| **all 22** | **{tot['n']}** | **{tot['u1']}** | **{tot['u2']}** | "
      f"**{tot['n'] - tot['u1']}** | **{tot['n'] - tot['u2']}** |")
    w("")
    w("## Runs this census is falsified against")
    w("")
    w("| run | arm | agent | tasks |")
    w("|---|---|---|---:|")
    for r in runs:
        w(f"| `{r['file'].replace('.json', '')}` | {r.get('backend')} | `{r.get('agent')}` | "
          f"{r.get('n')} |")
    w(f"| **{len(runs)} runs** | | | **{task_runs:,}** |")
    w("")

    Path(a.out).write_text("\n".join(out) + "\n")
    print(f"wrote {a.out}: {len(p1)} phase-1 entries, {len(p2_only)} phase-2-only, "
          f"{len(runs)} runs / {task_runs:,} task-runs")


if __name__ == "__main__":
    main()
