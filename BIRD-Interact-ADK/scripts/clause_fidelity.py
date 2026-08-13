#!/usr/bin/env python3
"""Diff what the agent WRITES against what the engine DISPATCHES, clause by clause.

Q-22 (OFFSET dropped) and Q-23 (NULL ordering inverted and un-overridable) were both
found by accident, in a single throwaway query. Both are silent: the result is
plausible, nothing errors, and the defect is invisible unless you read the outbound
SQL. That is the most expensive failure shape in the tracker, so it should not depend
on luck.

This runs a fixed battery of constructs through the semantic layer, fetches the
dispatched warehouse SQL for each, and reports every clause that was DROPPED or
REWRITTEN on the way. Known defects are included as controls: if OFFSET ever stops
being reported here, the probe broke, not the engine.

A clause surviving is not proof of correctness - the engine can preserve a clause and
still resolve it at the wrong grain (Q-24). This catches disappearance and rewriting,
which is a subset of silent wrongness, not all of it.

Usage:
  scripts/clause_fidelity.py                 # run the whole battery
  scripts/clause_fidelity.py --only offset   # substring match on probe name
  scripts/clause_fidelity.py --show-sql      # print dispatched SQL for each probe

No LLM calls and no benchmark tokens - MCP queries only.
"""
import argparse
import re
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from outbound_sql import client, outbound, QUERY_ID  # noqa: E402

M = '"bird_atscale_models_catalog_main"."Exchange Traded Funds"'

# Features worth tracking. Each is (label, regex). Presence is compared inbound vs
# outbound; a feature present in the inbound and absent from the dispatch is a DROP.
FEATURES = [
    ("DISTINCT",     re.compile(r"\bDISTINCT\b", re.I)),
    ("GROUP BY",     re.compile(r"\bGROUP\s+BY\b", re.I)),
    ("HAVING",       re.compile(r"\bHAVING\b", re.I)),
    ("ORDER BY",     re.compile(r"\bORDER\s+BY\b", re.I)),
    ("LIMIT",        re.compile(r"\bLIMIT\b", re.I)),
    ("OFFSET",       re.compile(r"\bOFFSET\b", re.I)),
    ("NULLS FIRST",  re.compile(r"\bNULLS\s+FIRST\b", re.I)),
    ("NULLS LAST",   re.compile(r"\bNULLS\s+LAST\b", re.I)),
    ("UNION",        re.compile(r"\bUNION\b", re.I)),
    ("ASC",          re.compile(r"\bASC\b", re.I)),
    ("DESC",         re.compile(r"\bDESC\b", re.I)),
]

# Each probe: name, inbound SQL, and what we already believe. `expect` is prose for the
# reader; the verdict is computed, not asserted, so a probe whose belief is wrong shows
# up as a surprise rather than being silently accepted.
PROBES = [
    ("offset-control",
     f'SELECT "Fund 1-Year Return" FROM (SELECT "Fund", "Fund 1-Year Return" FROM {M} '
     f'WHERE "Fund 1-Year Return" IS NOT NULL) t ORDER BY "Fund 1-Year Return" ASC LIMIT 1 OFFSET 50',
     "Q-22: OFFSET dropped entirely"),

    ("nulls-last-override-control",
     f'SELECT "Fund", "Fund Bond Duration (Years)" FROM {M} '
     f'ORDER BY "Fund Bond Duration (Years)" ASC NULLS LAST LIMIT 5',
     "Q-23: NULLS LAST ignored, rewritten to NULLS FIRST"),

    ("nulls-first-override-control",
     f'SELECT "Fund", "Fund Bond Duration (Years)" FROM {M} '
     f'ORDER BY "Fund Bond Duration (Years)" DESC NULLS FIRST LIMIT 5',
     "Q-23: NULLS FIRST ignored, rewritten to NULLS LAST"),

    ("inner-orderby-no-limit",
     f'SELECT "Exchange" FROM (SELECT "Exchange", "Total Daily Value Traded 3M" AS v FROM {M} '
     f'GROUP BY "Exchange" ORDER BY v DESC) t',
     "Q-12: inner ORDER BY stripped when the derived table has no LIMIT"),

    ("inner-orderby-with-limit",
     f'SELECT "Exchange" FROM (SELECT "Exchange", "Total Daily Value Traded 3M" AS v FROM {M} '
     f'GROUP BY "Exchange" ORDER BY v DESC LIMIT 1000) t',
     "Q-12 workaround: ORDER BY should SURVIVE when LIMIT is present"),

    ("select-distinct",
     f'SELECT DISTINCT "Exchange" FROM {M}',
     "unknown - does DISTINCT survive or get folded into a GROUP BY?"),

    ("grain-key-omitted",
     f'SELECT AVG("Fund Consistency-Adjusted Information Ratio") FROM '
     f'(SELECT "Fund Consistency-Adjusted Information Ratio" FROM {M}) t',
     "Q-24: key dropped, outer GROUP BY dedupes on the value tuple"),

    ("grain-key-projected",
     f'SELECT AVG("Fund Consistency-Adjusted Information Ratio") FROM '
     f'(SELECT "Fund", "Fund Consistency-Adjusted Information Ratio" FROM {M}) t',
     "Q-24 control: key projected, grain should hold"),

    ("having-on-measure",
     f'SELECT "Exchange" FROM {M} GROUP BY "Exchange" HAVING "Average Net Expense Ratio" < 5',
     "guidance 225(c) prescribes this shape - does HAVING reach the dispatch intact?"),

    ("orderby-ordinal",
     f'SELECT "Exchange", "Fund Count" FROM {M} GROUP BY "Exchange" ORDER BY 2 DESC',
     "unknown - is an ordinal ORDER BY honoured?"),

    ("limit-in-derived-only",
     f'SELECT "Fund" FROM (SELECT "Fund" FROM {M} ORDER BY "Fund" ASC LIMIT 3) t',
     "unknown - does an inner LIMIT survive without an outer one?"),

    ("union-all-over-model",
     f'SELECT "Exchange" FROM {M} WHERE "Exchange" = \'BATS\' '
     f'UNION ALL SELECT "Exchange" FROM {M} WHERE "Exchange" = \'NasdaqGM\'',
     "Q-25: UNION touching the model is dropped and returns ZERO rows, no error"),

    ("union-all-literals-only",
     "SELECT 'AAA' AS ticker, '1.23' AS score UNION ALL SELECT 'TOTAL', '456'",
     "Q-25 control: the guidance-prescribed literal form WORKS - it never reaches "
     "the warehouse, so there is no rewrite to survive"),

    ("scalar-subquery-in-where",
     f'SELECT "Fund Count" FROM {M} WHERE "Fund Turnover Ratio" < '
     f'(SELECT "Fund 52-Week Range Move Pct" FROM {M} LIMIT 1)',
     "Q-26 control: the subquery is spliced into the outer row, dispatching as "
     "turnover_ratio < range_move_pct - a plausible count, no error. Clause-level "
     "this shows only as a dropped LIMIT; the wrongness needs --show-sql"),

    ("scalar-subquery-in-select",
     f'SELECT "Fund", (SELECT "Average Net Assets (AUM)" FROM {M}) AS pop_avg FROM {M} LIMIT 3',
     "Q-26 / Q-20 control: pop_avg should be one repeated population value and is "
     "instead each row's own AUM"),

    ("case-in-where",
     f'SELECT "Fund Count" FROM {M} WHERE CASE WHEN "Fund Turnover Ratio" > 1 '
     f"THEN 'high' ELSE 'low' END = 'high'",
     "unknown - does a CASE survive in the WHERE clause?"),

    ("case-in-orderby",
     f'SELECT "Exchange", "Fund Count" FROM {M} GROUP BY "Exchange" '
     f"ORDER BY CASE WHEN \"Exchange\" = 'BATS' THEN 0 ELSE 1 END, \"Exchange\"",
     "an agent hit an engine assertion on CASE-in-ORDER-BY in etf_6 - does it "
     "error, survive, or get dropped?"),

    ("string-function",
     f'SELECT "Exchange" FROM {M} WHERE UPPER("Exchange") = \'BATS\'',
     "unknown - are string functions pushed down or evaluated somewhere else?"),

    ("nested-aggregate",
     f'SELECT AVG(t.v) AS v FROM (SELECT "Exchange", SUM("Fund Net Assets (AUM)") AS v '
     f'FROM {M} GROUP BY "Exchange") t',
     "unknown - an aggregate over a grouped derived table. Q-24 says the inner "
     "grouping key may not survive into the outer level"),

    ("two-dataset-groupby",
     f'SELECT "Exchange", "Category", "Fund Count" FROM {M} '
     f'GROUP BY "Exchange", "Category" ORDER BY "Exchange", "Category" LIMIT 5',
     "unknown - grouping on two dimensions that reach the fact through different "
     "joins is where a fan-out would show up"),
]


def features(sql):
    return {label for label, rx in FEATURES if rx.search(sql or "")}


def strip_datasets(sql):
    """Drop inlined dataset bodies so their SQL is not mistaken for the wrapper's.

    The model's own derived SQL contains GROUP BY, DISTINCT and ORDER BY of its own.
    Counting those would mask a dropped clause in the wrapper - the only part that
    reflects what the agent asked for.
    """
    out, depth = [], 0
    for line in sql.splitlines():
        if re.match(r"\s*WITH\s+\w+\s+AS\s*\(", line) and depth == 0:
            depth = 1
            continue
        if depth:
            if re.match(r'\s*\)\s*AS\s+"t_\d+"', line):
                depth = 0
            continue
        out.append(line)
    return "\n".join(out)


def run_probe(cli, name, sql, expect, show_sql):
    try:
        res = str(cli.call_tool("run_query", {"query": sql}))
    except Exception as e:                                   # noqa: BLE001
        print(f"\n[{name}] TOOL ERROR: {str(e)[:160]}")
        return None
    m = QUERY_ID.search(res)
    if not m:
        first = res.strip().splitlines()[0] if res.strip() else "(empty)"
        print(f"\n[{name}] no queryId - query errored or returned nothing")
        print(f"    expect: {expect}")
        print(f"    engine: {first[:200]}")
        return None

    obq = outbound(cli, m.group(1))
    rows = res.split("queryId:")[0].strip()
    if not obq or not any(q.get("sql") for q in obq):
        # No warehouse query at all. Not a defect - it means the engine answered
        # without dispatching (literal-only SELECTs), so there was no rewrite to
        # survive. Worth distinguishing from "dispatched and mangled".
        print(f"\n[{name}] NOT DISPATCHED (answered without a warehouse query)")
        print(f"    expect : {expect}")
        print(f"    rows   : {rows[:120]}")
        return "NOT DISPATCHED"

    dispatched = "\n".join(strip_datasets(q.get("sql", "")) for q in obq)
    fin, fout = features(sql), features(dispatched)
    dropped, added = sorted(fin - fout), sorted(fout - fin)
    # The engine aggregates by design, so a GROUP BY it introduces is how it works,
    # not evidence of anything. Reporting it as a rewrite buries the real findings.
    benign = {"GROUP BY"}
    notable_added = [a for a in added if a not in benign]

    verdict = "CLEAN" if not dropped and not notable_added else "REWRITTEN"
    print(f"\n[{name}] {verdict}")
    print(f"    expect : {expect}")
    if dropped:
        print(f"    DROPPED: {', '.join(dropped)}")
    if notable_added:
        print(f"    ADDED  : {', '.join(notable_added)}")
    print(f"    rows   : {rows[:120]}")
    if show_sql:
        print("    --- dispatched ---")
        for line in dispatched.splitlines():
            if line.strip():
                print(f"    {line}")
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring match on probe name")
    ap.add_argument("--show-sql", action="store_true")
    args = ap.parse_args()

    probes = [p for p in PROBES if not args.only or args.only in p[0]]
    cli = client()
    print(f"clause fidelity: {len(probes)} probes against {M}")

    results = {}
    for name, sql, expect in probes:
        results[name] = run_probe(cli, name, sql, expect, args.show_sql)

    rewritten = [n for n, v in results.items() if v == "REWRITTEN"]
    errored = [n for n, v in results.items() if v is None]
    print(f"\n{'='*60}\n{len(rewritten)} rewritten, {len(errored)} errored, "
          f"{len(results) - len(rewritten) - len(errored)} clean")
    if rewritten:
        print("rewritten: " + ", ".join(rewritten))
    if errored:
        print("errored  : " + ", ".join(errored))
    return 0


if __name__ == "__main__":
    sys.exit(main())
