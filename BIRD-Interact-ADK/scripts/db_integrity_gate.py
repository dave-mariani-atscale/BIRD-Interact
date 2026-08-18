#!/usr/bin/env python3
"""Fail a run before it starts if a benchmark TEMPLATE database has drifted.

Why this exists (B-25). On 2026-08-12 a Management-category task ran an
archive-and-delete against `exchange_traded_funds_template` itself instead of a
per-task copy: 21574 rows moved from `annual_returns` into a new
`annual_returns_archive`, taking every non-NULL `categoryperf` value with them. The
grader executes gold against that template, so gold for etf_2 and etf_4 silently
started returning ZERO rows, and both tasks became unwinnable by any submission in
either arm. They had scored 1.00 on 2026-08-11 and scored 0.00 in every run for the
next two days. Nothing errored, and nothing in a results file said why.

Two checks, because the first alone would not have caught it:

  ROW COUNTS  each source table against its known-good count.
  NON-NULL    the count of non-NULL values in specific columns. B-25 is invisible to
              a row-count check on its own: `annual_returns` kept 7174 perfectly
              valid rows, and it was the *values* in one column that were gone.

Only the 15 source tables are checked. Management-task DML legitimately leaves extra
tables behind (`annual_returns_archive`, `style_drift_log`, ...), so their presence is
not itself a failure — the source tables being wrong is.

Usage:
  scripts/db_integrity_gate.py                 # check every DB in the baseline
  scripts/db_integrity_gate.py --update        # re-record the baseline from live DBs

No LLM calls. Exits non-zero on drift so it can gate a run.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import db_utils as U  # noqa: E402

BASELINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "db_baseline.json")


def measure(db, row_tables, non_null_cols):
    conn = U.get_connection_for_phase(db)
    rows = {}
    for t in row_tables:
        r, err, _, _ = U.execute_queries([f'SELECT COUNT(*) FROM "{t}"'], db, conn)
        rows[t] = r[0][0] if r else f"ERROR: {err}"  # non-int marks a failure
    nn = {}
    for col in non_null_cols:
        tbl, c = col.split(".", 1)
        r, err, _, _ = U.execute_queries(
            [f'SELECT COUNT(*) FILTER (WHERE "{c}" IS NOT NULL) FROM "{tbl}"'], db, conn)
        nn[col] = r[0][0] if r else f"ERROR: {err}"
    return rows, nn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="re-record the baseline from the live DBs (use only when "
                         "you have verified the live state is correct)")
    args = ap.parse_args()

    baseline = json.load(open(BASELINE))
    failures = []
    failed_update = False
    for db, spec in sorted(baseline.items()):
        if db.startswith("_"):
            continue
        want_rows = spec["row_counts"]
        want_nn = spec.get("non_null", {})
        got_rows, got_nn = measure(db, want_rows, want_nn)

        if args.update:
            # A failed measurement renders as "ERROR: ...". Writing that into the
            # baseline poisons it permanently: every later gate then compares an
            # int against a string and reports drift on a healthy template.
            broken = [k for k, v in list(got_rows.items()) + list(got_nn.items())
                      if not isinstance(v, int)]
            if broken:
                print(f"  SKIPPED {db}: {len(broken)} measurement(s) failed "
                      f"({', '.join(broken[:4])}) — baseline left unchanged")
                failed_update = True
                continue
            spec["row_counts"], spec["non_null"] = got_rows, got_nn
            continue

        bad = [(t, want_rows[t], got_rows[t]) for t in want_rows if got_rows[t] != want_rows[t]]
        bad_nn = [(c, want_nn[c], got_nn[c]) for c in want_nn if got_nn[c] != want_nn[c]]
        if not bad and not bad_nn:
            print(f"  OK - {db}: {len(want_rows)} tables, "
                  f"{len(want_nn)} non-null checks all match")
            continue
        for t, w, g in bad:
            failures.append(f"{db}.{t}: expected {w} rows, found {g}")
        for c, w, g in bad_nn:
            failures.append(f"{db}.{c}: expected {w} non-NULL, found {g}")

    if args.update:
        json.dump(baseline, open(BASELINE, "w"), indent=1, sort_keys=True)
        print(f"baseline updated: {BASELINE}")
        if failed_update:
            print("NOTE: one or more databases were skipped above; their baseline "
                  "entries are unchanged, not refreshed.")
            return 1
        return 0

    if failures:
        print("\nFAIL: a template database has drifted from its known-good shape.")
        for f in failures:
            print(f"  {f}")
        print("\nThe grader runs gold against these templates, so a drifted table "
              "silently changes what 'correct' means and can make a task unwinnable "
              "with no error anywhere (B-25). Restore before running; do NOT rebuild "
              "a template from the base DB, which is itself recreated from the "
              "template and will already carry the damage.")
        return 1
    print("  OK - all template databases match baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
