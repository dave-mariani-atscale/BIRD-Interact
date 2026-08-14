#!/usr/bin/env python
"""How many BIRD golds a float64 semantic layer cannot match, MEASURED.

Both tests apply the grader's own rounding first (`resolve_decimal_places`,
which falls back to 2 when a task says `decimal: -1`). That matters: an
18th-significant-digit difference is absorbed by rounding to 2 places and is NOT
a blocker, which is how the first version of this sweep produced a false count.

  E-05  Gold's value cannot survive a float64 round-trip even after rounding.
        Needs a magnitude above 2^53 or a scale rounding cannot reach. Measured
        by round-tripping every gold cell through float and re-rounding.

  E-04  Gold computes in float32 and a float64 engine gets a different number.
        Measured, not guessed: for every `real` column the gold references, the
        query is re-run with that column widened to float8, and the two results
        are compared after rounding. A difference that survives rounding is a
        confirmed blocker; crypto_exchange _5 is the reference case
        (SUM over a real column, 24503744.0 against 24503748.29).

Gold executes on a DISPOSABLE COPY of each template, never the template (B-25).
Free: no LLM calls, no benchmark tokens.
"""
import atexit
import decimal
import json
import re
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


def real_columns(db):
    try:
        rows, _c, _d = U.perform_query(
            "SELECT DISTINCT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND data_type IN ('real','double precision')", db)
    except Exception:
        return set()
    return {r[0] for r in (rows or [])}


def canon(rows, dp):
    pre = U.preprocess_results([list(r) for r in rows], dp)
    return [[U.canonical_cell(c) for c in r] for r in pre]


def widen(sql, cols):
    """Re-express the query with every real column read as float8."""
    out = sql
    for c in cols:
        out = re.sub(r'("%s")(?!\s*::)' % re.escape(c), r"\1::float8", out)
        out = re.sub(r'(?<![\w."])(%s)(?![\w."])(?!\s*::)' % re.escape(c),
                     r"\1::float8", out)
    out = re.sub(r"::\s*REAL\b", "::float8", out, flags=re.I)
    return out


def sweep(db):
    tasks = [json.loads(l) for l in open(settings.data_path)]
    tasks = [t for t in tasks
             if t.get("selected_database") == db and t.get("category") == "Query"]
    if not tasks:
        return None
    scratch = U.create_task_db(db, "precsweep")
    atexit.register(lambda d=scratch: U.drop_task_db(d))
    conn = U.get_connection_for_phase(scratch)
    rcols = real_columns(scratch)

    n_phase = errored = 0
    e05, e04 = set(), set()
    e05_ph = e04_ph = 0
    for t in tasks:
        fu = t.get("follow_up") or {}
        for phase, sol, cond in ((1, t.get("sol_sql"), t.get("conditions")),
                                 (2, fu.get("sol_sql"), fu.get("conditions"))):
            if not sol:
                continue
            sol = clean([sol] if isinstance(sol, str) else sol)
            n_phase += 1
            dp = U.resolve_decimal_places(cond or {})
            try:
                rows, err, to, _ = U.execute_queries(sol, scratch, conn)
            except Exception:
                rows, err = None, "exc"
            if err or to or not rows:
                errored += 1
                continue
            base = canon(rows, dp)

            # E-05: does a float64 round-trip survive the grader's rounding?
            rt = [[float(c) if isinstance(c, decimal.Decimal) else c for c in r]
                  for r in rows]
            if canon(rt, dp) != base:
                e05.add(t["instance_id"])
                e05_ph += 1

            # E-04: would float64 arithmetic give a different number?
            blob = " ".join(sol)
            touched = [c for c in rcols if c in blob]
            if not (touched or re.search(r"::\s*REAL\b", blob, re.I)):
                continue
            wid = [widen(s, touched) for s in sol]
            if wid == sol:
                continue
            try:
                wrows, werr, wto, _ = U.execute_queries(wid, scratch, conn)
            except Exception:
                continue
            if werr or wto or not wrows:
                continue
            if canon(wrows, dp) != base:
                e04.add(t["instance_id"])
                e04_ph += 1
    U.drop_task_db(scratch)
    return dict(db=db, tasks=len(tasks), phases=n_phase, errored=errored,
                e05_phases=e05_ph, e05_tasks=sorted(e05),
                e04_phases=e04_ph, e04_tasks=sorted(e04))


if __name__ == "__main__":
    out = []
    for db in sys.argv[1:]:
        try:
            r = sweep(db)
        except Exception as e:
            print(f"{db:34s} SWEEP FAILED {type(e).__name__}: {str(e)[:110]}", flush=True)
            continue
        if not r:
            print(f"{db:34s} no Query tasks", flush=True)
            continue
        out.append(r)
        print(f"{r['db']:34s} {r['tasks']:3d} tasks {r['phases']:3d} phases | "
              f"E-05 {len(r['e05_tasks']):2d} tasks | "
              f"E-04 {len(r['e04_tasks']):2d} tasks | gold errors {r['errored']}",
              flush=True)
    json.dump(out, open("/tmp/precision_sweep.json", "w"), indent=1)
    print("\nwrote /tmp/precision_sweep.json")
