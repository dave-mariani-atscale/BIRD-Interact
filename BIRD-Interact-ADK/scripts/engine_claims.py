#!/usr/bin/env python3
"""Re-probe every engine claim we ship, live, against whichever engine is running.

The claims live in four places that all assert what the SQL interface can and cannot
do: ENGINE_NOTES in the models repo (which reaches every v12 model description, and
from there every agent), the build prompt, the agent guidance in
config/environment_backends.yaml, and the E-*/Q-* rows in the tracker. A claim that
something is BROKEN costs as much as a missing feature once it is stale: the agent
pays for a workaround it does not need, or never tries the construct at all. So a
claim only stays in those files if it still reproduces on the engine we are running.

Each probe states what we currently ship and the script computes what actually
happens, so a fixed claim shows up as CHANGED rather than being carried forward.
`where` records whether a refusal came from the MCP guardrail (its messages carry
Next Steps) or from the engine itself, because only the second is an engine claim.

Baseline: engine ghcr.io/atscaleinc/engine:pr9967 (40.0.0-pr9967, rev d44a17b),
mcp release-feedback-memory-combined, catalog bird_models_v12, 2026-09-28.

Usage:
  scripts/engine_claims.py                  # whole battery
  scripts/engine_claims.py --only union     # substring match on probe name
  scripts/engine_claims.py --show           # print each probe's raw result

No LLM calls and no benchmark tokens - MCP queries only.
"""
import argparse
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from shared.mcp_client import MCPToolError            # noqa: E402
from outbound_sql import client, outbound, QUERY_ID   # noqa: E402

M = '"bird_models_v12"."Exchange Traded Funds V12"'

# (name, tracker/notes id, sql, expected, claim as we currently ship it)
# expected is what our own documents assert: "refused" or "accepted".
PROBES = [
    # ---- refusals asserted by ENGINE_NOTES / the build prompt --------------------
    ("count-star", "Q-09", f'SELECT COUNT(*) FROM {M}', "refused",
     "COUNT(*) is refused - a semantic model has no row count of its own"),

    ("avg-over-attribute", "Q-21", f'SELECT AVG("Alpha 3Y") FROM {M}', "refused",
     "AVG over a dimension attribute is refused outright by the planner"),

    ("sum-over-attribute", "E-01",
     f'SELECT "Fund Family", SUM("Alpha 3Y") AS s FROM {M} GROUP BY "Fund Family"', "refused",
     "SUM over an attribute returns one row per member, silently ungrouped"),

    ("count-over-attribute", "E-01",
     f'SELECT "Fund Family" AS f, COUNT("Fund Ticker") AS n, COUNT(DISTINCT "Fund Ticker") AS nd, '
     f'"Fund Count" AS fc FROM {M} GROUP BY "Fund Family" ORDER BY f ASC LIMIT 5', "refused",
     "COUNT over an attribute returns the member value, not a count"),

    ("percentile-cont", "Q-06/Q-31",
     f'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "Alpha 3Y") FROM {M}', "refused",
     "PERCENTILE_CONT is not accepted in submitted SQL"),

    ("median-fn", "Q-06", f'SELECT MEDIAN("Alpha 3Y") FROM {M}', "refused",
     "MEDIAN is not accepted"),

    ("percent-rank", "Q-19",
     f'SELECT "Fund Ticker", PERCENT_RANK() OVER (ORDER BY "Alpha 3Y") AS pr FROM {M}', "refused",
     "PERCENT_RANK is not accepted"),

    ("ntile", "Q-19 corrected 09-27",
     f'SELECT "Fund Ticker", NTILE(4) OVER (ORDER BY "Alpha 3Y") AS q FROM {M}', "accepted",
     "NTILE IS accepted (claim corrected 2026-09-27)"),

    ("corr", "notes", f'SELECT CORR("Alpha 3Y", "Beta 3Y") FROM {M}', "refused",
     "CORR is not accepted"),

    ("regr-slope", "notes", f'SELECT REGR_SLOPE("Alpha 3Y", "Beta 3Y") FROM {M}', "refused",
     "REGR_SLOPE is not accepted"),

    ("greatest", "E-07",
     f'SELECT "Fund Ticker", GREATEST("Alpha 3Y", "Beta 3Y") AS g FROM {M} LIMIT 5', "refused",
     "GREATEST/LEAST (MinMaxExpr) is rejected"),

    ("in-subquery", "Q-13",
     f'SELECT "Fund Ticker" FROM {M} WHERE "Fund Family" IN '
     f'(SELECT "Fund Family" FROM {M} WHERE "Fund Category" = \'Large Blend\') LIMIT 5', "refused",
     "IN (subquery) is not accepted"),

    ("exists", "notes",
     f'SELECT "Fund Ticker" FROM {M} t1 WHERE EXISTS '
     f'(SELECT 1 FROM {M} t2 WHERE t2."Fund Ticker" = t1."Fund Ticker") LIMIT 5', "refused",
     "EXISTS is not accepted"),

    ("cte", "Q-38",
     f'WITH t AS (SELECT "Fund Ticker" FROM {M}) SELECT "Fund Ticker" FROM t LIMIT 5', "refused",
     "CTEs are not accepted"),

    ("nullif", "Q-28",
     f'SELECT "Fund Ticker", NULLIF("Alpha 3Y", 0) AS a FROM {M} LIMIT 5', "refused",
     "NULLIF is rejected by the dialect while COALESCE is accepted"),

    ("coalesce-control", "Q-28",
     f'SELECT "Fund Ticker", COALESCE("Alpha 3Y", 0) AS a FROM {M} LIMIT 5', "accepted",
     "COALESCE is accepted (control for NULLIF)"),

    ("trim", "Q-07", f"SELECT TRIM('  SPY  ') AS t FROM {M} LIMIT 2", "refused",
     "TRIM is unsupported"),

    ("cube", "E-13",
     f'SELECT "Fund Family", "Fund Count" FROM {M} GROUP BY CUBE("Fund Family")', "refused",
     "CUBE/ROLLUP/GROUPING SETS are refused"),

    ("comma-join", "notes",
     f'SELECT a.f, b.n FROM (SELECT "Fund Family" AS f FROM {M} WHERE "Fund Family"=\'AAM\') a, '
     f'(SELECT "Fund Count" AS n FROM {M} WHERE "Fund Family"=\'AAM\') b', "refused",
     "two FROM-subqueries joined with a comma are refused"),

    ("conditional-aggregates", "notes",
     f'SELECT MAX(CASE WHEN f=\'AAM\' THEN n END) AS aam, MAX(CASE WHEN f=\'AAMA\' THEN n END) AS aama '
     f'FROM (SELECT "Fund Family" AS f, "Fund Count" AS n FROM {M} GROUP BY "Fund Family") t',
     "accepted",
     "one subquery with conditional aggregates outside gives two figures in one row"),

    ("bare-numeric-cast", "notes",
     f'SELECT "Fund Ticker", CAST("Alpha 3Y" AS numeric) AS a FROM {M} LIMIT 5', "refused",
     "a bare CAST(x AS numeric) is refused - precision and scale required"),

    ("numeric-cast-with-scale", "notes",
     f'SELECT "Fund Ticker", CAST("Alpha 3Y" AS numeric(18,4)) AS a FROM {M} LIMIT 5', "accepted",
     "CAST(x AS numeric(18,4)) works and returns a string, not a number"),

    ("string-agg", "notes",
     f'SELECT f, STRING_AGG(tk, \', \') AS s FROM (SELECT "Fund Family" AS f, "Fund Ticker" AS tk '
     f'FROM {M} WHERE "Fund Family" = \'AAM\') t GROUP BY f', "accepted",
     "STRING_AGG over a FROM-subquery is accepted"),

    ("string-agg-order-by", "notes",
     f'SELECT f, STRING_AGG(tk, \', \' ORDER BY tk) AS s FROM (SELECT "Fund Family" AS f, '
     f'"Fund Ticker" AS tk FROM {M} WHERE "Fund Family" = \'AAM\') t GROUP BY f', "refused",
     "STRING_AGG(x, ', ' ORDER BY x) is refused"),

    # ---- ORDER BY family ---------------------------------------------------------
    ("orderby-unprojected-attribute", "Q-29",
     f'SELECT "Fund Ticker" FROM {M} ORDER BY "Alpha 3Y" DESC LIMIT 5', "refused",
     "sorting by a column the query neither projects nor groups by is refused"),

    ("orderby-unprojected-measure", "Q-03/Q-36",
     f'SELECT "Fund Family" AS f FROM {M} GROUP BY "Fund Family" ORDER BY "Fund Count" DESC LIMIT 3',
     "refused",
     "ORDER BY an unprojected measure fails"),

    ("orderby-unprojected-aggregate", "E-21",
     f'SELECT "Fund Family" FROM {M} GROUP BY "Fund Family" '
     f'ORDER BY COUNT(DISTINCT "Fund Ticker") DESC LIMIT 1', "refused",
     "ORDER BY an aggregate the SELECT does not project is refused"),

    ("orderby-round-alias", "notes",
     f'SELECT "Fund Ticker", CAST("Alpha 3Y" AS numeric(18,4)) AS a FROM {M} '
     f'WHERE "Alpha 3Y" IS NOT NULL ORDER BY a DESC LIMIT 5', "accepted",
     "give the rounded expression an alias and ORDER BY the alias"),

    # ---- UNION family ------------------------------------------------------------
    ("union-all-top-level", "E-17/Q-25",
     f'SELECT "Fund Ticker" AS c FROM {M} WHERE "Fund Ticker" = \'SPY\' '
     f'UNION ALL SELECT \'TOTAL\' AS c', "accepted",
     "a top-level UNION ALL over the model works (listing plus a summary row)"),

    ("union-untyped-null", "notes",
     f'SELECT "Fund Ticker" AS c, "Alpha 3Y" AS v FROM {M} WHERE "Fund Ticker" = \'SPY\' '
     f'UNION ALL SELECT \'TOTAL\' AS c, NULL AS v', "refused",
     "a bare NULL literal in a UNION branch must be typed"),

    ("union-in-subquery", "Q-25/Q-37",
     f'SELECT c FROM (SELECT "Fund Ticker" AS c FROM {M} WHERE "Fund Ticker" = \'SPY\' '
     f'UNION ALL SELECT "Fund Ticker" AS c FROM {M} WHERE "Fund Ticker" = \'QQQ\') t', "refused",
     "a UNION inside a subquery, CTE or WHERE is refused"),

    # ---- window functions --------------------------------------------------------
    ("window-filtered-in-subquery-where", "notes",
     f'SELECT tk FROM (SELECT "Fund Ticker" AS tk, RANK() OVER (ORDER BY "Alpha 3Y" DESC) AS r '
     f'FROM {M} WHERE "Alpha 3Y" IS NOT NULL) t WHERE r <= 5', "refused",
     "a window column cannot be filtered in WHERE at any depth"),

    ("window-filtered-in-having", "notes corrected 09-27",
     f'SELECT tk FROM (SELECT "Fund Ticker" AS tk, RANK() OVER (ORDER BY "Alpha 3Y" DESC) AS r '
     f'FROM {M} WHERE "Alpha 3Y" IS NOT NULL) t GROUP BY tk HAVING MIN(r) <= 5', "accepted",
     "select the window column in a subquery, GROUP BY the key, filter it in HAVING"),

    ("window-agg-over-subquery", "E-16",
     f'SELECT f, SUM(n) OVER () AS tot FROM (SELECT "Fund Family" AS f, "Fund Count" AS n '
     f'FROM {M} GROUP BY "Fund Family") t LIMIT 3', "refused",
     "a window aggregate over an aliased FROM-subquery falls through the guardrail"),

    # ---- published metric naming and conformance ---------------------------------
    ("percentile-metric-instance", "Q-31",
     f'SELECT "Fund Category" AS c, "Median 1-Year Return_instance_0.5" AS m FROM {M} '
     f'GROUP BY "Fund Category" LIMIT 3', "refused",
     "every percentile metric in the catalog is unexecutable"),

    ("percentile-metric-plain-name", "notes",
     f'SELECT "Median 1-Year Return" FROM {M}', "refused",
     "the plain name of a median metric is not found"),

    ("nonconforming-pairing", "Q-32",
     f'SELECT "Calendar Year" AS y, "Total Holding Weight" AS w FROM {M} '
     f'GROUP BY "Calendar Year" LIMIT 5', "refused",
     "pairing a measure with a dimension on a non-conforming fact group is refused"),

    ("count-distinct-with-measure-predicate", "Q-15",
     f'SELECT "Fund Family" AS f, COUNT(DISTINCT "Fund Ticker") AS n FROM {M} '
     f'GROUP BY "Fund Family" HAVING "Average Alpha 3Y" > 0 LIMIT 5', "refused",
     "COUNT(DISTINCT dim) returns null when combined with a measure predicate"),

    ("dim-filter-in-subquery", "Q-05",
     f'SELECT tk FROM (SELECT "Fund Ticker" AS tk FROM {M} '
     f'WHERE "Fund Category" = \'Large Blend\') t LIMIT 3', "refused",
     "a dimension filter inside a subquery is rejected"),

    ("flag-equals-integer", "Q-10",
     f'SELECT "Fund Ticker" AS tk FROM {M} WHERE "Has Risk Metrics Record" = 1 LIMIT 3', "refused",
     "a text flag compared to 1 raises a varchar/int error"),
]


# Silent-wrongness probes: nothing errors, so the verdict comes from the dispatched SQL
# or from two results that should agree and do not.
def p_offset(cli):
    """Q-22: OFFSET is dropped from the dispatch entirely."""
    base = (f'SELECT tk FROM (SELECT "Fund Ticker" AS tk, "Alpha 3Y" AS a FROM {M} '
            f'WHERE "Alpha 3Y" IS NOT NULL) t ORDER BY a DESC LIMIT 3')
    r0, _ = run(cli, base)
    r5, q5 = run(cli, base + " OFFSET 5")
    if q5 is None:
        return "ERROR", r5[:160]
    disp = dispatch(cli, q5)
    kept = bool(re.search(r"\bOFFSET\b", disp, re.I))
    same = body(r0) == body(r5)
    return ("CHANGED" if kept and not same else "HOLDS",
            f"OFFSET {'survives' if kept else 'dropped'} in dispatch; "
            f"rows {'identical to OFFSET 0' if same else 'differ from OFFSET 0'}")


def p_nulls_order(cli):
    """Q-23: DESC puts NULLs first, the reverse of Postgres, and cannot be overridden."""
    sel = f'SELECT "Fund Ticker" AS tk, "Alpha 3Y" AS a FROM {M}'
    bare, qb = run(cli, sel + " ORDER BY a DESC LIMIT 3")
    over, qo = run(cli, sel + " ORDER BY a DESC NULLS LAST LIMIT 3")
    if qb is None or qo is None:
        return "ERROR", (bare + over)[:160]
    bare_nulls = "null" in body(bare)
    over_nulls = "null" in body(over)
    # Postgres's own default IS NULLS FIRST for DESC, so bare-DESC nulls first is
    # Postgres-conforming; the claim is only alive if the override is also ignored.
    return ("HOLDS" if over_nulls else "CHANGED",
            f"bare DESC returns nulls first: {bare_nulls}; "
            f"NULLS LAST override honoured: {not over_nulls}")


def p_inner_orderby(cli):
    """Q-12: an inner ORDER BY is dropped when the derived table has no LIMIT."""
    sql = (f'SELECT fam, n FROM (SELECT "Fund Family" AS fam, "Fund Count" AS n FROM {M} '
           f'GROUP BY "Fund Family" ORDER BY n DESC) t LIMIT 5')
    res, qid = run(cli, sql)
    if qid is None:
        return "ERROR", res[:160]
    vals = [int(v) for v in re.findall(r'"n":\s*(\d+)', body(res))]
    ordered = vals == sorted(vals, reverse=True)
    kept = bool(re.search(r"ORDER\s+BY", dispatch(cli, qid), re.I))
    return ("CHANGED" if (kept and ordered) else "HOLDS",
            f"ORDER BY {'survives' if kept else 'dropped'} in dispatch; "
            f"rows {'in order' if ordered else 'NOT in order'} {vals[:5]}")


def p_keyless_collapse(cli):
    """Q-24/Q-42: a measure-less SELECT returns DISTINCT attribute tuples."""
    n_key = nrows(cli, f'SELECT "Fund Ticker", "Fund Short Name", "Has Risk Metrics Record" FROM {M}')
    n_no = nrows(cli, f'SELECT "Fund Short Name", "Has Risk Metrics Record" FROM {M}')
    return ("HOLDS" if (n_key or 0) > (n_no or 0) else "CHANGED",
            f"with key {n_key} rows, without key {n_no} rows")


def p_keyless_avg(cli):
    """Q-42: an outer AVG over a measure-less subquery averages distinct values."""
    a, _ = run(cli, f'SELECT AVG(a) AS x FROM (SELECT "Fund Ticker", "Alpha 3Y" AS a FROM {M} '
                    f'WHERE "Alpha 3Y" IS NOT NULL) t')
    b, _ = run(cli, f'SELECT AVG(a) AS x FROM (SELECT "Alpha 3Y" AS a FROM {M} '
                    f'WHERE "Alpha 3Y" IS NOT NULL) t')
    va, vb = firstnum(a), firstnum(b)
    return ("HOLDS" if va != vb else "CHANGED", f"with key {va}, without key {vb}")


def p_cross_dataset_filter(cli):
    """Q-41: a WHERE on one grain's column while projecting another's is dropped."""
    sql = (f'SELECT "Security Name", "Holding Weight" FROM {M} '
           f'WHERE "Fund Ticker" = \'SPY\' LIMIT 20')
    res, qid = run(cli, sql)
    if qid is None:
        return "ERROR", res[:160]
    dropped = bool(re.search(r"WHERE\s+true", dispatch(cli, qid), re.I))
    return ("HOLDS" if dropped else "CHANGED",
            "dispatch carries WHERE true - the filter was dropped" if dropped
            else "the filter reached the dispatch")


def p_scalar_subquery(cli):
    """Q-26/Q-20: a whole-population scalar subquery is inlined as a per-row value."""
    sql = (f'SELECT "Fund Ticker" AS tk, "Alpha 3Y" AS a, (SELECT "Average Alpha 3Y" FROM {M}) '
           f'AS pop FROM {M} WHERE "Fund Ticker" IN (\'SPY\',\'QQQ\')')
    res, _ = run(cli, sql)
    try:
        rows = json.loads(re.search(r"\[.*\]", body(res), re.S).group(0))
    except Exception:                                        # noqa: BLE001
        return "ERROR", body(res)[:160]
    per_row = all(abs(r["pop"] - r["a"]) < 1e-3 for r in rows if r.get("a") is not None)
    return ("HOLDS" if per_row else "CHANGED",
            "the population value equals each row's own value" if per_row
            else f"population value is independent of the row: {rows}")


def p_measure_float8(cli):
    """E-10: every measure is dispatched as SUM(CAST(col AS FLOAT8))."""
    sql = (f'SELECT "Geographic Zone" AS z, "Total Net Worth" AS w FROM {M} '
           f'WHERE "Base Currency" = \'USD\' GROUP BY "Geographic Zone"')
    res, qid = run(cli, sql)
    if qid is None:
        return "ERROR", res[:160]
    disp = dispatch(cli, qid)
    hit = bool(re.search(r"(SUM|AVG)\s*\(\s*CAST\([^)]*AS\s+(FLOAT8|DOUBLE)", disp, re.I))
    agg = re.findall(r"(?:SUM|AVG)\s*\([^)]{0,60}\)", disp)[:2]
    return ("HOLDS" if hit else "CHANGED", f"dispatched aggregate: {agg}")


def p_union_order(cli):
    """E-17: the engine re-sorts UNION ALL branches, so a summary row cannot be last."""
    sql = (f'SELECT "Fund Ticker" AS c, "Alpha 3Y" AS v FROM {M} '
           f'WHERE "Fund Ticker" IN (\'SPY\',\'QQQ\') '
           f'UNION ALL SELECT \'TOTAL\' AS c, CAST(0 AS numeric(18,4)) AS v')
    res, _ = run(cli, sql)
    cs = re.findall(r'"c":\s*"([^"]+)"', body(res))
    return ("CHANGED" if cs and cs[-1] == "TOTAL" else "HOLDS", f"branch order returned: {cs}")


def p_window_grain(cli):
    """Q-39: a window function over a measure in a flat SELECT ranks at the wrong grain."""
    flat, _ = run(cli, f'SELECT "Fund Family" AS f, "Fund Count" AS n, '
                       f'RANK() OVER (ORDER BY "Fund Count" DESC) AS r FROM {M} '
                       f'GROUP BY "Fund Family" LIMIT 5')
    sub, _ = run(cli, f'SELECT f, n, RANK() OVER (ORDER BY n DESC) AS r FROM '
                      f'(SELECT "Fund Family" AS f, "Fund Count" AS n FROM {M} '
                      f'GROUP BY "Fund Family") t LIMIT 5')
    return ("HOLDS" if body(flat) != body(sub) else "CHANGED",
            "flat ranking agrees with the subquery form" if body(flat) == body(sub)
            else f"flat {body(flat)[:80]} vs subquery {body(sub)[:80]}")


SILENT = [
    ("offset-dropped", "Q-22", "OFFSET is silently ignored by the query engine", p_offset),
    ("nulls-order", "Q-23", "DESC places NULLs FIRST and NULLS LAST cannot override it", p_nulls_order),
    ("inner-orderby-no-limit", "Q-12", "an inner ORDER BY is dropped without a LIMIT", p_inner_orderby),
    ("keyless-collapse", "Q-24", "a measure-less SELECT returns DISTINCT attribute tuples", p_keyless_collapse),
    ("keyless-avg", "Q-42", "an outer AVG over a keyless subquery averages distinct values", p_keyless_avg),
    ("cross-dataset-filter", "Q-41", "a filter on an unjoined dataset is silently dropped", p_cross_dataset_filter),
    ("scalar-subquery-per-row", "Q-26/Q-20", "a population scalar subquery is inlined per row", p_scalar_subquery),
    ("measure-float8", "E-10", "every measure is dispatched as SUM(CAST(col AS FLOAT8))", p_measure_float8),
    ("union-branch-order", "E-17", "the engine re-sorts UNION ALL branches", p_union_order),
    ("window-grain-flat", "Q-39", "a window over a measure in a flat SELECT is at the wrong grain", p_window_grain),
]

# Not probed here, and why: E-02 (search_path) and E-14/E-19/E-23 are deploy-time;
# E-18 (result cache) and E-22 (stale aggregates) only show across a redeploy;
# E-06 is a harness timezone setting; E-20 is a connection loss; E-04/E-05 are gold
# float width. None of them is reachable from a single run_query.


def run(cli, sql):
    """Return (text, queryId or None). A refusal comes back as text with no id."""
    try:
        res = str(cli.call_tool("run_query", {"query": sql}))
    except Exception as e:                                   # noqa: BLE001
        return f"REFUSED: {e}", None
    m = QUERY_ID.search(res)
    return res, (m.group(1) if m else None)


def body(res):
    return res.split("queryId:")[0].strip()


def dispatch(cli, qid):
    return re.sub(r"\s+", " ", " ".join(q.get("sql", "") for q in outbound(cli, qid)))


def nrows(cli, sql):
    res, _ = run(cli, sql)
    try:
        return len(json.loads(re.search(r"\[.*\]", body(res), re.S).group(0)))
    except Exception:                                        # noqa: BLE001
        return None


def firstnum(res):
    m = re.search(r"-?\d+\.\d+", body(res))
    return m.group(0) if m else None


def where_from(msg):
    """MCP guardrail messages carry the tool's own Next Steps; engine ones do not."""
    return "mcp" if "## Next Steps" in msg else "engine"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring match on probe name")
    ap.add_argument("--show", action="store_true", help="print each probe's raw result")
    args = ap.parse_args()

    cli = client()
    changed = []

    print(f"{'probe':38} {'id':22} {'shipped':9} {'observed':9} verdict")
    print("-" * 104)
    for name, ident, sql, expected, claim in PROBES:
        if args.only and args.only not in name:
            continue
        res, _ = run(cli, sql)
        refused = res.startswith("REFUSED")
        observed = "refused" if refused else "accepted"
        verdict = "HOLDS" if observed == expected else "CHANGED"
        src = where_from(res) if refused else "-"
        print(f"{name:38} {ident:22} {expected:9} {observed:9} {verdict}  [{src}]")
        if verdict == "CHANGED":
            changed.append((name, ident, claim, body(res)[:200]))
        if args.show:
            print(f"    {body(res)[:300]}\n")

    print()
    for name, ident, claim, fn in SILENT:
        if args.only and args.only not in name:
            continue
        try:
            verdict, detail = fn(cli)
        except Exception as e:                               # noqa: BLE001
            verdict, detail = "ERROR", str(e)[:160]
        print(f"{name:38} {ident:22} {'silent':9} {'':9} {verdict}  {detail}")
        if verdict != "HOLDS":
            changed.append((name, ident, claim, detail))

    print("\n" + "=" * 104)
    if not changed:
        print("every claim reproduces on this engine build")
    else:
        print(f"{len(changed)} claim(s) no longer reproduce - each is a line to fix in ENGINE_NOTES, "
              f"the build prompt, config/environment_backends.yaml and the tracker:")
        for name, ident, claim, detail in changed:
            print(f"\n  {name} ({ident})\n    shipped: {claim}\n    observed: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
