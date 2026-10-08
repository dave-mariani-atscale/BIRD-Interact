#!/usr/bin/env python3
"""Paired A/B report for an instruction change: two runs, same tasks, same grader.

Reports the OUTCOME and the MECHANISM, because at subset sizes the outcome alone
cannot carry a conclusion:

  * outcome   - phase-1 pass counts and McNemar's exact test on the discordant
                pairs. Run-to-run agent churn is ~9% of tasks even at
                temperature 0, so on 79 tasks an arm only a large effect shows.
  * mechanism - the signed column-count delta (prediction minus gold) over every
                graded phase-1 submission. Far less noisy than pass/fail, and it
                is what an output-shape edit has to move first if it works at
                all. An edit that shifts nothing here did not land, whatever the
                pass counts say.

Harm is measured, not assumed: run whole databases rather than the selected
failures, so tasks that already pass are in scope and an edit that wins in one
direction while losing in the other shows up as such.

POWER, LEARNED THE EXPENSIVE WAY (2026-08-25). The first use of this script tested
a RESULT_SHAPE_TIP variant on 4 databases, $46 and 95 minutes, and returned 0
gained / 1 lost with the mechanism moving 4 toward gold and 5 away. That reads as
"the edit does nothing", but the test could not have shown otherwise: the edit
targeted UNDER-projection, which across all 22 databases splits 33 too-few against
17 too-many -- while in the 4 databases chosen it splits 10 to 9. The subset was
picked by density of presentation failures overall, not by density of the specific
failure the edit addresses, and those two are not the same thing.

Worse, no better subset exists. The 33 under-projection tasks are spread over 16
databases with at most 4 in any one, so no 4-database slice holds more than ~14 of
them. Before running this, check that the failure mode you are targeting actually
concentrates somewhere; if it does not, a subset A/B cannot answer the question and
only a full 22-database paired run (2x the full cost) will.

Usage:
  scripts/ab_shape_report.py results/<control>.json results/<treatment>.json
"""
import argparse
import collections
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2                              # noqa: E402

from shared.config import settings          # noqa: E402
from shared.db_utils import (                # noqa: E402
    remove_comments, remove_round,
)

# Gold runs on a direct, reused connection per database rather than through
# execute_queries: that helper leases from a pool of settings.pg_maxconn (5) and
# does not release, so a per-task loop exhausts it after ~20 tasks and every
# later gold comes back as "connection pool exhausted" -- indistinguishable, in
# the report, from a gold that legitimately returns nothing. Against the
# `_template` databases, which are the pristine source every task DB is cloned
# from, so nothing here depends on run-order state (and the session is read-only
# so nothing here can write to one).
_CONNS = {}


def _conn(db):
    if db not in _CONNS:
        c = psycopg2.connect(host=settings.pg_host, port=settings.pg_port,
                             user=settings.pg_user, password=settings.pg_password,
                             dbname=f"{db}_template")
        c.set_session(readonly=True, autocommit=True)
        _CONNS[db] = c
    return _CONNS[db]

AUDIT = Path(__file__).parent.parent / "results" / "grading_audit.jsonl"


def load_arm(path):
    run = json.load(open(path))
    t0, t1 = run["run_started"], run["run_finished"]
    passed = {r["task_id"]: bool(r.get("phase1_passed")) for r in run["results"]}
    dbs = {r["task_id"]: r["database"] for r in run["results"]}
    last = {}
    for line in open(AUDIT):
        try:
            a = json.loads(line)
        except ValueError:
            continue
        if not (t0 - 5 <= a.get("ts", 0) <= t1 + 5) or a.get("phase") != 1:
            continue
        prev = last.get(a["task_id"])
        if prev is None or a.get("attempt", 0) >= prev.get("attempt", 0):
            last[a["task_id"]] = a
    return run, passed, dbs, last


def gold_width(a, db, cache):
    """Column count of gold for this task, or None if gold will not run."""
    key = a["task_id"]
    if key in cache:
        return cache[key]
    sols = a.get("sol_sql") or []
    if isinstance(sols, str):
        sols = [sols]
    try:
        cur = _conn(db).cursor()
        cur.execute("SET statement_timeout = 30000")
        rows = []
        for query in remove_round(remove_comments(list(sols))):
            cur.execute(query)
            rows = cur.fetchall()
        cache[key] = len(rows[0]) if rows else None
    except Exception:                                                   # noqa: BLE001
        _CONNS.pop(db, None)
        cache[key] = None
    return cache[key]


def mechanism(last, dbs, cache):
    """Signed prediction-minus-gold column delta, per task."""
    out = {}
    for tid, a in last.items():
        pred = a.get("pred_rows")
        if not pred:
            continue
        g = gold_width(a, dbs.get(tid, ""), cache)
        if g is None:
            continue
        out[tid] = len(pred[0]) - g
    return out


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1))
    return min(1.0, 2 * tail / 2 ** n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("control")
    ap.add_argument("treatment")
    args = ap.parse_args()

    c_run, c_pass, c_dbs, c_last = load_arm(args.control)
    t_run, t_pass, t_dbs, t_last = load_arm(args.treatment)
    shared = sorted(set(c_pass) & set(t_pass))
    print(f"paired task set: {len(shared)} tasks across "
          f"{len(set(c_dbs[t] for t in shared))} databases")
    if len(shared) != len(c_pass) or len(shared) != len(t_pass):
        print(f"  NOTE: control ran {len(c_pass)}, treatment ran {len(t_pass)}; "
              f"comparing only the overlap")

    print("\n--- OUTCOME (phase 1) ---")
    cp = sum(c_pass[t] for t in shared)
    tp = sum(t_pass[t] for t in shared)
    gained = [t for t in shared if t_pass[t] and not c_pass[t]]
    lost = [t for t in shared if c_pass[t] and not t_pass[t]]
    p = mcnemar_exact(len(gained), len(lost))
    print(f"  control   {cp:>3} / {len(shared)}   ({100*cp/len(shared):.1f}%)")
    print(f"  treatment {tp:>3} / {len(shared)}   ({100*tp/len(shared):.1f}%)")
    print(f"  {len(gained)} gained, {len(lost)} lost -> McNemar exact p = {p:.3f}")
    if len(gained) + len(lost):
        se = math.sqrt(len(gained) + len(lost))
        print(f"  difference {tp-cp:+d} tasks against a discordant-pair SE of "
              f"{se:.1f} -> {abs(tp-cp)/se:.2f} sigma")
    print(f"    gained: {gained}")
    print(f"    lost:   {lost}")

    print("\n--- MECHANISM (prediction columns minus gold columns) ---")
    cache = {}
    c_delta = mechanism(c_last, c_dbs, cache)
    t_delta = mechanism(t_last, t_dbs, cache)
    both = sorted(set(c_delta) & set(t_delta))
    print(f"  {len(both)} tasks with a gradeable submission in both arms")
    for name, d in (("control", c_delta), ("treatment", t_delta)):
        few = sum(1 for t in both if d[t] < 0)
        ok = sum(1 for t in both if d[t] == 0)
        many = sum(1 for t in both if d[t] > 0)
        print(f"  {name:10} too few {few:>3} | exact {ok:>3} | too many {many:>3}")
    moved = [(t, c_delta[t], t_delta[t]) for t in both if c_delta[t] != t_delta[t]]
    toward = sum(1 for _, c_, t_ in moved if abs(t_) < abs(c_))
    away = sum(1 for _, c_, t_ in moved if abs(t_) > abs(c_))
    print(f"  {len(moved)} tasks changed column count between arms: "
          f"{toward} moved TOWARD gold, {away} moved AWAY")
    p_mech = mcnemar_exact(toward, away)
    print(f"  McNemar exact on that = {p_mech:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
