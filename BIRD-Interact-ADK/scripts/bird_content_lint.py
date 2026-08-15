#!/usr/bin/env python
"""How many BIRD golds return different VALUES on different executions?

bird_order_lint asks whether gold determines its own row ORDER. It explicitly
discards any pair of runs whose row CONTENT differs, on the grounds that a value
difference is not an order question. It is a question about something worse: a
gold that returns different values depending on the plan cannot be reproduced by
anyone, including a rerun of itself, and every task built on one is a coin flip.

The usual mechanism is a pick-one-per-group with a non-unique tiebreak --
ROW_NUMBER() OVER (PARTITION BY x ORDER BY y) where y ties inside a partition,
DISTINCT ON, or a bare LIMIT after a non-total ORDER BY. Which row wins is
whatever the plan emitted.

Measured, not parsed, exactly as the order lint measures: each gold runs twice,
the second time with the planner pushed onto different physical operators, and
the results are compared as MULTISETS after the grader's own rounding. Anything
that survives that is a value difference the grader would see.

Reported in two buckets, because they belong to different owners:

  float noise    the two runs agree within a 1e-6 relative tolerance -- float64
                 accumulation order, which GRADING_REL_TOLERANCE absorbs.
  NON-DETERMINISTIC  they do not. Nobody can pass this task reliably. Upstream
                 data defect (tracker B-27).

Gold executes on a DISPOSABLE COPY of each template, never the template (B-25).
Free: no LLM calls, no benchmark tokens.
"""
import atexit
import collections
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
from shared.config import settings          # noqa: E402
from shared import db_utils as U            # noqa: E402

PERTURB = ["SET enable_seqscan = off", "SET enable_hashjoin = off",
           "SET enable_nestloop = off", "SET enable_hashagg = off"]
RESET = [s.replace("off", "on") for s in PERTURB]
PICKER = re.compile(r"row_number\s*\(\s*\)|distinct\s+on|rank\s*\(\s*\)", re.I)


def clean(sol):
    return U.remove_round(U.remove_distinct(U.remove_comments(list(sol))))


def sweep(db, tasks):
    scratch = U.create_task_db(db, "contentlint")
    atexit.register(lambda d=scratch: U.drop_task_db(d))
    conn = U.get_connection_for_phase(scratch)
    phases, bad = 0, []
    for t in tasks:
        fu = t.get("follow_up") or {}
        for pn, sol, cond in ((1, t.get("sol_sql"), t.get("conditions")),
                              (2, fu.get("sol_sql"), fu.get("conditions"))):
            if not sol:
                continue
            cond = cond or {}
            sols = clean([sol] if isinstance(sol, str) else sol)
            a, e, to, _ = U.execute_queries(sols, scratch, conn)
            if e or to or not a:
                continue
            try:
                for s in PERTURB:
                    U.perform_query(s, scratch, conn)
                b, e2, to2, _ = U.execute_queries(sols, scratch, conn)
            finally:
                for s in RESET:
                    try:
                        U.perform_query(s, scratch, conn)
                    except Exception:
                        pass
            if e2 or to2 or not b:
                continue
            phases += 1
            dp = U.resolve_decimal_places(cond)
            ca = sorted(tuple(U.canonical_cell(c) for c in r)
                        for r in U.preprocess_results(a, dp))
            cb = sorted(tuple(U.canonical_cell(c) for c in r)
                        for r in U.preprocess_results(b, dp))
            if ca == cb:
                continue
            moved = sum(1 for x, y in zip(ca, cb) if x != y)
            # Same tolerance the grader would apply, on the PRE-rounding rows.
            settings.grading_rel_tolerance_value = 1e-6
            noise = U._compare_rows_numeric_tolerant(a, b, {"order": False})
            bad.append(dict(task=t["instance_id"], phase=pn, rows=len(ca),
                            differing=moved, kind="float" if noise else "NONDET",
                            gold_uses_row_picker=bool(PICKER.search(" ".join(sols)))))
    U.drop_task_db(scratch)
    return phases, bad


if __name__ == "__main__":
    settings.grading_honor_decimal = True
    settings.grading_casefold = True
    by_db = collections.defaultdict(list)
    for line in open(settings.data_path):
        d = json.loads(line)
        if d.get("category") == "Query":
            by_db[d.get("selected_database")].append(d)

    total_phases, all_bad = 0, []
    for db in sys.argv[1:]:
        if db not in by_db:
            print(f"{db:34s} no Query tasks", flush=True)
            continue
        phases, bad = sweep(db, by_db[db])
        total_phases += phases
        all_bad += bad
        nd = [x for x in bad if x["kind"] == "NONDET"]
        print(f"{db:34s} phases {phases:3d} | not reproducible: {len(bad):2d} "
              f"({len(nd)} non-deterministic) "
              f"{sorted({x['task'] for x in nd}) if nd else ''}", flush=True)

    nd = [x for x in all_bad if x["kind"] == "NONDET"]
    print(f"\n{total_phases} phases | {len(all_bad)} not reproducible | "
          f"{len(nd)} non-deterministic / {len(all_bad) - len(nd)} float noise")
    json.dump(all_bad, open("/tmp/content_sweep.json", "w"), indent=1)
    print("wrote /tmp/content_sweep.json")
