#!/usr/bin/env python
"""Does the gold-cleanup step still produce runnable SQL?

`remove_distinct` deletes the set-quantifier DISTINCT from both the prediction and
gold before either is executed. It used to delete the word unconditionally, which
turns Postgres' `SELECT DISTINCT ON (col) ...` -- one operator, not a quantifier --
into `SELECT ON (col) ...`, a syntax error. Gold then fails to execute, both graders
score 0, and the task is unpassable whatever the agent submits.

Three parts:
  * unit     - the keyword cases, no database needed.
  * live     - every bird-interact-full gold that uses DISTINCT ON is cleaned and
               EXECUTED, so a regression shows up as a syntax error rather than as a
               quietly unwinnable task. Needs Postgres; skipped with --unit-only.
  * semantic - the same failure one layer up. ex_base_external_pred grades ROWS
               against gold, so it must NOT strip the plain set quantifier: doing so
               inflates any gold whose DISTINCT collapses a fan-out join, past
               anything a correct prediction could return. Asserts the semantic
               arm's cleanup leaves every such gold's row count alone. Needs
               Postgres; skipped with --unit-only.

Gold runs on a session-READ-ONLY connection to each `<db>_template`. Templates are
the source every task database is cloned from, so nothing here may write to one
(B-25) -- read-only is enforced by the server, not by this script's good intentions.

Usage:
    python scripts/test_remove_distinct.py [--unit-only]
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import settings  # noqa: E402
from shared.db_utils import remove_comments, remove_distinct, remove_round  # noqa: E402

DATA = Path(__file__).parent.parent / "bird-interact-full" / "bird_interact_data.jsonl"

# The two Postgres operators that merely spell themselves with the word DISTINCT.
USES_OPERATOR = re.compile(r"(?i)\bdistinct\s+on\b|\bis\s+(?:not\s+)?distinct\s+from\b")
# The plain set quantifier -- the thing remove_distinct is actually FOR. Matched by
# excluding the two operator spellings above.
USES_QUANTIFIER = re.compile(r"(?i)\bdistinct\b(?!\s+on\b)")
# What each looks like once the keyword has been wrongly deleted.
CORRUPTED = re.compile(r"(?i)\bselect\s+on\b|\bis\s+(?:not\s+)?from\b")

UNIT_CASES = [
    # (input, expected, why)
    ("SELECT DISTINCT a FROM t",
     "SELECT a FROM t",
     "plain set quantifier is still removed"),
    ("SELECT DISTINCT ON (a) a, b FROM t ORDER BY a",
     "SELECT DISTINCT ON (a) a, b FROM t ORDER BY a",
     "DISTINCT ON is one operator and survives intact"),
    ("SELECT DISTINCT ON(a) a FROM t",
     "SELECT DISTINCT ON(a) a FROM t",
     "no space before the paren"),
    ("select distinct on (a) a from t",
     "select distinct on (a) a from t",
     "lower case"),
    ("SELECT COUNT(DISTINCT a) FROM t",
     "SELECT COUNT(DISTINCT a) FROM t" if False else "SELECT COUNT(DISTINCT a) FROM t",
     "PLACEHOLDER"),  # replaced below - see note
    ("SELECT DISTINCT online FROM t",
     "SELECT online FROM t",
     "a column starting with 'on' is not DISTINCT ON"),
    ("SELECT DISTINCT  ON (a) a FROM t",
     "SELECT DISTINCT  ON (a) a FROM t",
     "extra space between the two words"),
    ("SELECT a FROM t WHERE x IS DISTINCT FROM y",
     "SELECT a FROM t WHERE x IS DISTINCT FROM y",
     "IS DISTINCT FROM is a null-safe comparison operator, not a quantifier"),
    ("SELECT a FROM t WHERE x IS NOT DISTINCT FROM y",
     "SELECT a FROM t WHERE x IS NOT DISTINCT FROM y",
     "IS NOT DISTINCT FROM likewise"),
    ("SELECT DISTINCT a FROM t WHERE x IS DISTINCT FROM y",
     "SELECT a FROM t WHERE x IS DISTINCT FROM y",
     "both in one query: the quantifier goes, the operator stays"),
    ("SELECT DISTINCT\n a FROM t",
     "SELECT DISTINCT\n a FROM t",
     "a token carrying whitespace never matched upstream either - unchanged"),
]

# COUNT(DISTINCT a) is written as one token "COUNT(DISTINCT" by the space split, so
# upstream never removed that DISTINCT either. Asserting the pre-existing behaviour
# rather than a new opinion: this function's contract is unchanged except for
# DISTINCT ON.
UNIT_CASES[4] = ("SELECT COUNT(DISTINCT a) FROM t",
                 "SELECT COUNT(DISTINCT a) FROM t",
                 "COUNT(DISTINCT x) is untouched, as before")


def run_unit() -> int:
    failures = 0
    for src, want, why in UNIT_CASES:
        got = remove_distinct([src])[0]
        ok = got == want
        failures += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {why}")
        if not ok:
            print(f"          in:   {src}\n          want: {want}\n          got:  {got}")
    return failures


def run_live() -> int:
    """Every affected gold, cleaned exactly as the graders clean it.

    Two checks, because not every gold can be executed here:

      * text  - the cleaned SQL must not contain a corrupted operator. Applies to
                all of them, including the Management-category golds that write.
      * exec  - Query-category golds additionally have to RUN. That is the check
                that would have caught this bug; the text check alone only catches
                the corruptions we already know how to spell.

    Management-category golds are DDL/DML and depend on prior-phase state, so they
    cannot execute against a pristine template on a read-only connection. They are
    reported as text-only rather than quietly counted as passes.
    """
    import psycopg2

    golds = []
    for line in open(DATA):
        task = json.loads(line)
        for phase, sqls in ((1, task.get("sol_sql") or []),
                            (2, (task.get("follow_up") or {}).get("sol_sql") or [])):
            if sqls and USES_OPERATOR.search(" ".join(sqls)):
                golds.append((task["instance_id"], phase, task["selected_database"],
                              task.get("category", "Query"), sqls))
    print(f"  {len(golds)} gold queries use a DISTINCT operator")

    conns, failures, executed, text_only = {}, 0, 0, 0
    for instance_id, phase, db, category, sqls in golds:
        cleaned = remove_round(remove_distinct(remove_comments(list(sqls))))
        corrupt = [c for c in cleaned if CORRUPTED.search(c)]
        if corrupt:
            failures += 1
            hit = CORRUPTED.search(corrupt[0]).group(0)
            print(f"  [FAIL] {instance_id} phase {phase}: cleanup produced {hit!r}")
            continue
        if category != "Query":
            text_only += 1
            continue
        if db not in conns:
            conn = psycopg2.connect(host=settings.pg_host, port=settings.pg_port,
                                    user=settings.pg_user, password=settings.pg_password,
                                    dbname=f"{db}_template")
            conn.set_session(readonly=True, autocommit=True)
            conns[db] = conn
        cur = conns[db].cursor()
        try:
            for query in cleaned:
                cur.execute(query)
                cur.fetchall()
            executed += 1
        except Exception as exc:                                        # noqa: BLE001
            failures += 1
            print(f"  [FAIL] {instance_id} phase {phase}: {str(exc).splitlines()[0]}")
            conns.pop(db).close()
    for conn in conns.values():
        conn.close()
    print(f"  [ok]   {executed} Query-category golds executed after cleanup")
    print(f"  [ok]   {text_only} Management-category golds checked for corruption only "
          f"(they write, so they cannot run against a read-only template)")
    return failures


def run_semantic_arm() -> int:
    """The semantic arm must grade against gold with its DISTINCT still on.

    ex_base_external_pred receives the prediction as ROWS, already de-duplicated by
    the engine as the agent's own DISTINCT asked. remove_distinct is one half of a
    two-sided normalisation of two SQL STRINGS (grade_raw_submission still applies
    both halves); running only the gold half here cannot make a wrong answer right,
    it can only inflate gold past anything a correct prediction could return.

    Checked directly: for every phase-1 Query gold carrying a set quantifier, the
    rows the semantic arm now grades against must equal the rows gold itself
    returns. A regression -- someone putting remove_distinct back in that chain --
    shows up as a row-count difference on the fan-out golds rather than as a
    handful of quietly unpassable tasks.
    """
    import psycopg2

    golds = []
    for line in open(DATA):
        task = json.loads(line)
        sqls = task.get("sol_sql") or []
        joined = " ".join(sqls)
        if not sqls or task.get("category", "Query") != "Query":
            continue
        # Strip the operator spellings before looking for the quantifier, so
        # `DISTINCT ON` / `IS DISTINCT FROM` alone never qualify a gold.
        if USES_QUANTIFIER.search(USES_OPERATOR.sub(" ", joined)):
            golds.append((task["instance_id"], task["selected_database"], sqls))
    print(f"  {len(golds)} phase-1 Query golds use a set-quantifier DISTINCT")

    conns, failures, loadbearing, checked = {}, 0, 0, 0
    for instance_id, db, sqls in golds:
        if db not in conns:
            conn = psycopg2.connect(host=settings.pg_host, port=settings.pg_port,
                                    user=settings.pg_user, password=settings.pg_password,
                                    dbname=f"{db}_template")
            conn.set_session(readonly=True, autocommit=True)
            conns[db] = conn
        cur = conns[db].cursor()

        def rows_of(queries):
            out = []
            cur.execute("SET statement_timeout = 30000")
            for query in queries:
                cur.execute(query)
                out = cur.fetchall()
            return out

        try:
            graded = rows_of(remove_round(remove_comments(list(sqls))))
            verbatim = rows_of(list(sqls))
            stripped = rows_of(remove_round(remove_distinct(remove_comments(list(sqls)))))
        except Exception as exc:                                        # noqa: BLE001
            failures += 1
            print(f"  [FAIL] {instance_id}: {str(exc).splitlines()[0]}")
            conns.pop(db).close()
            continue
        checked += 1
        # The property: the cleanup the semantic arm applies must not change what
        # gold means. remove_comments/remove_round do not; remove_distinct does,
        # on any gold whose quantifier collapses a fan-out join.
        if len(graded) != len(verbatim):
            failures += 1
            print(f"  [FAIL] {instance_id}: semantic-arm cleanup changed gold from "
                  f"{len(verbatim)} rows to {len(graded)} — the set quantifier is being "
                  f"stripped again")
        if len(stripped) != len(verbatim):
            loadbearing += 1
    for conn in conns.values():
        conn.close()
    print(f"  [ok]   {checked - failures} golds survive the semantic-arm cleanup unchanged")
    print(f"  [ok]   {loadbearing} of them are load-bearing: stripping the quantifier would "
          f"inflate gold and make the task unpassable")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit-only", action="store_true", help="skip the cases needing Postgres")
    args = ap.parse_args()

    print("unit:")
    failures = run_unit()
    if not args.unit_only:
        print("live (gold must execute after cleanup):")
        failures += run_live()
        print("semantic arm (gold keeps its set quantifier):")
        failures += run_semantic_arm()
    print(f"\n{'PASS' if not failures else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
