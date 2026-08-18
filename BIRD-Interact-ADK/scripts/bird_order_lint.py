#!/usr/bin/env python
"""How many BIRD golds demand a row order they do not themselves determine?

`conditions.order == true` makes the grader compare row-by-row. That is only
answerable if gold's own ORDER BY totally orders its result. Where it does not -
no ORDER BY at all, or an ORDER BY with ties - the "expected" order is whatever
Postgres happened to emit, and no agent can reproduce it except by luck.

Measured, not parsed: each gold runs twice, the second time with the planner
pushed onto different physical operators (seqscan/hashjoin/nestloop off). A
result whose order is fixed by an ORDER BY is unchanged; a result whose order
came from the scan or join order moves. This is a LOWER BOUND - a tie that both
plans happen to emit identically is not caught.

Rounding is the grader's own (`resolve_decimal_places`), so a value difference
below the compared precision does not masquerade as an order difference.

Gold executes on a DISPOSABLE COPY of each template, never the template (B-25).
Free: no LLM calls, no benchmark tokens.
"""
import atexit
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
from shared.config import settings          # noqa: E402
from shared import db_utils as U            # noqa: E402
from shared.db_utils import (remove_comments, remove_distinct,  # noqa: E402
                             remove_round)


def clean(sol):
    """The cleanup gold actually gets at grading time (db_utils:845).
    B-19 strips ROUND() from gold, which removes the ARTIFICIAL ties it
    manufactured - so a sweep that skips this over-counts loose order."""
    return remove_round(remove_distinct(remove_comments(list(sol))))

PERTURB = ["SET enable_seqscan = off", "SET enable_hashjoin = off",
           "SET enable_nestloop = off", "SET enable_hashagg = off"]
RESET = ["SET enable_seqscan = on", "SET enable_hashjoin = on",
         "SET enable_nestloop = on", "SET enable_hashagg = on"]


def canon(rows, dp):
    pre = U.preprocess_results([list(r) for r in rows], dp)
    return [[U.canonical_cell(c) for c in r] for r in pre]


def sweep(db):
    tasks = [json.loads(l) for l in open(settings.data_path)]
    tasks = [t for t in tasks
             if t.get("selected_database") == db and t.get("category") == "Query"]
    if not tasks:
        return None
    scratch = U.create_task_db(db, "ordsweep")
    atexit.register(lambda d=scratch: U.drop_task_db(d))
    conn = U.get_connection_for_phase(scratch)

    ordered_phases = 0
    unstable = []           # (instance_id, phase, rows, moved_rows)
    for t in tasks:
        fu = t.get("follow_up") or {}
        for phase, sol, cond in ((1, t.get("sol_sql"), t.get("conditions")),
                                 (2, fu.get("sol_sql"), fu.get("conditions"))):
            if not sol:
                continue
            cond = cond or {}
            if not cond.get("order"):
                continue
            sol = clean([sol] if isinstance(sol, str) else sol)
            ordered_phases += 1
            dp = U.resolve_decimal_places(cond)
            try:
                a, err, to, _ = U.execute_queries(sol, scratch, conn)
                if err or to or not a:
                    continue
                for s in PERTURB:
                    U.perform_query(s, scratch, conn)
                b, err2, to2, _ = U.execute_queries(sol, scratch, conn)
                for s in RESET:
                    U.perform_query(s, scratch, conn)
            except Exception:
                for s in RESET:
                    try:
                        U.perform_query(s, scratch, conn)
                    except Exception:
                        pass
                continue
            if err2 or to2 or not b:
                continue
            ca, cb = canon(a, dp), canon(b, dp)
            if sorted(map(tuple, ca)) != sorted(map(tuple, cb)):
                continue          # different CONTENT, not an order question
            if ca != cb:
                moved = sum(1 for x, y in zip(ca, cb) if x != y)
                unstable.append((t["instance_id"], phase, len(ca), moved))
    U.drop_task_db(scratch)
    return dict(db=db, tasks=len(tasks), ordered_phases=ordered_phases,
                unstable=unstable)


if __name__ == "__main__":
    # --write regenerates the list the grader consumes when
    # settings.grading_order_lint is on. Pass ALL 22 databases when writing it:
    # the file replaces its predecessor wholesale, so a partial sweep would
    # silently un-flag every phase it did not visit.
    argv = list(sys.argv[1:])
    write_to = None
    if "--write" in argv:
        i = argv.index("--write")
        write_to = argv[i + 1] if len(argv) > i + 1 else "config/order_undetermined.json"
        del argv[i:i + 2]

    out, failed = [], []
    for db in argv:
        try:
            r = sweep(db)
        except Exception as e:
            print(f"{db:34s} FAILED {type(e).__name__}: {str(e)[:100]}", flush=True)
            failed.append(db)
            continue
        if not r:
            # No phases swept is indistinguishable from a database that is not
            # there. Either way its rows are missing from `out`, so treat it as a
            # failure for the wholesale-replacement check below.
            print(f"{db:34s} no phases swept", flush=True)
            failed.append(db)
            continue
        out.append(r)
        ids = sorted({u[0] for u in r["unstable"]})
        print(f"{r['db']:34s} order-sensitive phases {r['ordered_phases']:3d} | "
              f"order NOT determined by gold: {len(r['unstable']):3d} phases / "
              f"{len(ids):2d} tasks {ids if ids else ''}", flush=True)
    json.dump(out, open("/tmp/order_sweep.json", "w"), indent=1)
    print("\nwrote /tmp/order_sweep.json")

    # The output file REPLACES its predecessor, so a partial sweep would silently
    # un-flag every phase of a database that failed — and settings.grading_order_lint
    # reads that file, so the next run grades those phases order-sensitively again
    # with nothing to show why. Refuse rather than write a subset.
    if write_to and failed:
        print(f"\nREFUSING to write {write_to}: {len(failed)} database(s) failed "
              f"({', '.join(failed)}). The file is replaced wholesale, so writing now "
              f"would drop their phases. Re-run those databases first.")
        write_to = None

    if write_to:
        phases = sorted({(u[0], u[1]) for r in out for u in r["unstable"]})
        doc = {
            "_": "Phases whose gold ORDER BY does not determine gold's own row "
                 "order, measured by replanning gold (see this file's generator). "
                 "The grader compares these as multisets when "
                 "settings.grading_order_lint is on. LOWER BOUND: a tie both "
                 "plans happen to emit identically is not caught.",
            "generated_by": "scripts/bird_order_lint.py --write " + write_to,
            "databases_swept": [r["db"] for r in out],
            "order_sensitive_phases": sum(r["ordered_phases"] for r in out),
            "phases": [[t, p] for t, p in phases],
        }
        with open(write_to, "w") as f:
            json.dump(doc, f, indent=1)
        print(f"wrote {write_to}: {len(phases)} phases / "
              f"{len({t for t, _ in phases})} tasks over {len(out)} databases")
