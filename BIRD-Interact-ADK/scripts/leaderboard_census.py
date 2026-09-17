#!/usr/bin/env python3
"""Machine measurements for the LEADERBOARD-MODE unwinnable census.

The task census in `bird-atscale-models/census/census_rev*.json` is tiered under
this harness's CORRECTED grading regime: four comparison corrections
(timestamp_date, order_requires_cue, casefold_text, column_order_free) are
applied unconditionally and two more (ties_as_ties, numeric_rel_tolerance) sit
behind flags. Leaderboard mode turns all six off - rows compare exactly as
`evaluation/src/eval_bird_interact.py` does - so a task the corrected census
calls achievable can be unwinnable on the board.

This script measures, per task and per phase, every property that decides that
difference. It executes GOLD only, read-only, on the `<db>_template` databases;
it runs no agent and calls no model.

    PYTHONPATH=. .venv-adk/bin/python scripts/leaderboard_census.py \
        --out scratch/lb_census/measurements.json

Per Query task and phase it records:

  gold_error_upstream  gold after UPSTREAM cleanup: null, or the error text.
                       Upstream's remove_distinct deletes the word DISTINCT
                       everywhere, which mangles `DISTINCT ON (...)` and
                       `IS [NOT] DISTINCT FROM` into invalid SQL; gold is cleaned
                       on both arms, so a mangled gold errors and NOTHING the
                       agent submits can score. That is unwinnable on the board
                       and invisible in the results.
  gold_error_adk       the same gold after this harness's cleanup (both operators
                       kept), so a gold that only upstream breaks is
                       distinguishable from a gold that is simply broken.
  upstream_preprocess_error
                       upstream's preprocess_results, verbatim, run over gold's
                       rows: it json.dumps a dict/list cell whose numerics have
                       just become Decimal, which raises TypeError and scores the
                       task 0 whatever is submitted. Empty on this dataset.
  order / cue          conditions.order, and whether the phase's question
                       carries an ordering cue (ORDER_CUE_RE). Under the
                       corrected regime order=true without a cue is graded as a
                       set; upstream honours the flag as recorded.
  order_plan_dependent gold run twice, the second time with the planner pushed
                       off its chosen operators (enable_seqscan / hashjoin /
                       nestloop / hashagg = off), compared after the grader's own
                       rounding. True when the row CONTENT is identical as a
                       multiset but the sequence differs: the "expected" order is
                       then an artefact of the plan and no other query reproduces
                       it except by luck. Lower bound - a tie both plans emit
                       identically is not caught.
  normaliser_in_gold   gold uses a case/whitespace normaliser (LOWER, UPPER,
                       INITCAP, TRIM, BTRIM) anywhere, and
  lowercased_text_cells
                       how many of its text cells come back all-lower-case.
                       Supporting evidence for the casefold class only: under the
                       corrected regime text compares case-insensitively and
                       upstream it does not, so an answer carrying the warehouse's
                       own casing fails - but WHICH tasks that hits is taken from
                       the census `why` texts, which measured the stored casing
                       column by column, not from these two flags.

Management tasks are measured for the cleanup-mangling case only (their golds
WRITE, and this script never writes): they are graded by their own test cases
through the same cleaned gold.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import db_utils as U  # noqa: E402
from shared.db_utils import preprocess_results  # noqa: E402


def up_preprocess_results(results):
    """`preprocess_results` VERBATIM from evaluation/src/eval_bird_interact.py,
    decimal_places=2 as upstream always calls it. The one line that matters is
    `json.dumps(processed_item, sort_keys=True)`: a dict or list cell whose
    numerics have just been quantized to Decimal is not JSON-serializable, so it
    raises TypeError, the grader scores 0, and the task is unpassable on the
    board whatever the agent submits. This harness passes default=str there."""
    from datetime import date, datetime
    from decimal import Decimal, ROUND_HALF_UP

    def dec(item, dp):
        q = Decimal(1).scaleb(-dp)
        if isinstance(item, Decimal):
            return item.quantize(q, rounding=ROUND_HALF_UP)
        if isinstance(item, float):
            return round(item, dp)
        if isinstance(item, (list, tuple)):
            return type(item)(dec(x, dp) for x in item)
        if isinstance(item, dict):
            return {k: dec(v, dp) for k, v in item.items()}
        return item

    processed = []
    for result in results:
        row = []
        for item in result:
            if isinstance(item, (date, datetime)):
                row.append(item.strftime("%Y-%m-%d"))
            else:
                pi = dec(item, 2)
                if isinstance(pi, (dict, list)):
                    row.append(json.dumps(pi, sort_keys=True))
                else:
                    row.append(pi)
        processed.append(tuple(row))
    return processed


def up_remove_distinct(sql_list):
    """`remove_distinct` VERBATIM from evaluation/src/eval_bird_interact.py:
    every token equal to "distinct" is deleted, DISTINCT ON and
    IS [NOT] DISTINCT FROM included. This harness's version keeps those two
    operators (shared/db_utils.py); that difference is the whole point of
    running both here."""
    cleaned = []
    for q in sql_list:
        tokens = [t for t in q.split(" ") if t.lower() != "distinct"]
        cleaned.append(" ".join(tokens))
    return cleaned

DATA = "bird-interact-full/bird_interact_data.jsonl"
PG = dict(host="127.0.0.1", port=5433, user="root", password="123123")
REPLAN = ("SET enable_seqscan=off", "SET enable_hashjoin=off",
          "SET enable_nestloop=off", "SET enable_hashagg=off")
NORMALISER = re.compile(r"\b(lower|upper|initcap|btrim|ltrim|rtrim|trim)\s*\(", re.I)


def clean_upstream(sqls):
    # remove_comments and remove_round are byte-identical implementations in the
    # two codebases (read 2026-09-16); only remove_distinct diverges.
    return U.remove_round(up_remove_distinct(U.remove_comments(list(sqls))))


def clean_adk(sqls):
    return U.remove_round(U.remove_distinct(U.remove_comments(list(sqls))))


class DB:
    """One read-only connection per template database."""

    def __init__(self):
        self.conns = {}

    def conn(self, db):
        if db not in self.conns:
            c = psycopg2.connect(dbname=f"{db}_template", **PG)
            c.set_session(readonly=True, autocommit=True)
            self.conns[db] = c
        return self.conns[db]

    def run(self, db, sqls, replan=False):
        """Mirror upstream execute_queries: same connection, last result wins,
        stop at the first error. Returns (rows, error_text)."""
        c = self.conn(db)
        rows = None
        for sql in sqls:
            try:
                with c.cursor() as cur:
                    cur.execute("SET statement_timeout = '60s'")
                    for stmt in (REPLAN if replan else ()):
                        cur.execute(stmt)
                    cur.execute(sql)
                    rows = cur.fetchall() if cur.description else []
                    if replan:
                        cur.execute("RESET ALL")
            except Exception as e:  # noqa: BLE001 - the error text is the datum
                c.rollback()
                if replan:
                    with c.cursor() as cur:
                        cur.execute("RESET ALL")
                return None, f"{type(e).__name__}: {str(e).strip().splitlines()[0][:300]}"
        return rows, None


def measure_phase(dbq: DB, db, sqls, conditions, question, category):
    out = {
        "order": bool((conditions or {}).get("order")),
        "cue": U.question_requests_order(question),
        "sql_mangled_by_upstream_cleanup": clean_upstream(sqls) != clean_adk(sqls),
    }
    out["normaliser_in_gold"] = bool(NORMALISER.search(" ".join(clean_adk(sqls))))
    if category != "Query":
        return out  # gold writes; never executed here

    rows_up, err_up = dbq.run(db, clean_upstream(sqls))
    rows_adk, err_adk = dbq.run(db, clean_adk(sqls))
    out["gold_error_upstream"] = err_up
    out["gold_error_adk"] = err_adk
    if rows_adk is None:
        return out
    graded = preprocess_results(rows_adk)
    out["rows"] = len(graded)
    try:
        up_preprocess_results(rows_adk)
        out["upstream_preprocess_error"] = None
    except Exception as e:  # noqa: BLE001
        out["upstream_preprocess_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    out["rows_upstream"] = None if rows_up is None else len(preprocess_results(rows_up))
    texts = [v for row in graded for v in row if isinstance(v, str)]
    out["text_cells"] = len(texts)
    # A cell that is all lower case and carries letters is what a gold LOWER()
    # in the projection looks like from the outside. Supporting evidence only:
    # the classification of a casefold-dependent task comes from the census
    # `why` text, which measured the stored casing column by column.
    out["lowercased_text_cells"] = sum(
        1 for v in texts if v != v.upper() and v == v.lower())
    if out["order"]:
        rows2, err2 = dbq.run(db, clean_adk(sqls), replan=True)
        if rows2 is None:
            out["order_plan_dependent"] = None
            out["replan_error"] = err2
        else:
            g2 = preprocess_results(rows2)
            same_seq = graded == g2
            try:
                same_set = sorted(map(repr, graded)) == sorted(map(repr, g2))
            except TypeError:
                same_set = False
            out["order_plan_dependent"] = bool(same_set and not same_seq)
            out["replan_content_differs"] = not same_set
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="*", help="limit to these instance_ids")
    a = ap.parse_args()

    tasks = [json.loads(l) for l in open(DATA) if l.strip()]
    if a.only:
        tasks = [t for t in tasks if t["instance_id"] in set(a.only)]
    dbq = DB()
    out = {}
    for i, t in enumerate(tasks, 1):
        tid, db, cat = t["instance_id"], t["selected_database"], t["category"]
        fu = t["follow_up"] or {}
        rec = {"db": db, "category": cat}
        rec["p1"] = measure_phase(dbq, db, t["sol_sql"], t["conditions"],
                                  t["amb_user_query"], cat)
        if fu.get("sol_sql"):
            rec["p2"] = measure_phase(dbq, db, fu["sol_sql"], fu.get("conditions"),
                                      fu.get("query"), cat)
        out[tid] = rec
        if i % 25 == 0:
            print(f"{i}/{len(tasks)}", flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)

    n = defaultdict(int)
    for tid, r in out.items():
        for ph in ("p1", "p2"):
            m = r.get(ph)
            if not m:
                continue
            k = f"{r['category'][:1]}{ph}"
            if m["sql_mangled_by_upstream_cleanup"]:
                n[f"{k} mangled by upstream cleanup"] += 1
            if m.get("gold_error_upstream"):
                n[f"{k} gold errors upstream"] += 1
            if m.get("gold_error_adk"):
                n[f"{k} gold errors here too"] += 1
            if m.get("upstream_preprocess_error"):
                n[f"{k} upstream preprocess TypeError"] += 1
            if m.get("order_plan_dependent"):
                n[f"{k} order plan-dependent"] += 1
                n[f"{k} order plan-dependent, {'cue' if m['cue'] else 'NO cue'}"] += 1
    for k in sorted(n):
        print(f"{n[k]:4d}  {k}")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
