#!/usr/bin/env python3
"""Measure the blast radius of Q-24: does omitting the grain key change the answer?

Guidance PRESCRIBES the grain-forcing pattern - "put the grain column AND the measure
in an inner derived table, then aggregate outside". Q-24 says that when the key is NOT
projected, the next wrapper level re-groups on the value tuple, so the outer aggregate
runs over distinct VALUES, not entities. That is silent: no error, plausible number.

If it bites everywhere, the guidance bullet must state the key as an absolute. If it
bites only in some shapes, they need naming. This runs each prescribed shape three ways
and compares them against the model's own pre-built measure, which is the arbiter:

  projected  SELECT AGG(m) FROM (SELECT "Fund", m FROM model ...) t   <- prescribed
  omitted    SELECT AGG(m) FROM (SELECT m FROM model ...) t           <- Q-24 suspect
  where-only SELECT AGG(m) FROM (SELECT m FROM model WHERE "Fund" IS NOT NULL ...) t

The third arm exists because guidance claims the key "only in the inner WHERE" also
fails to force the grain; that claim has never been measured.

No LLM calls and no benchmark tokens - MCP queries only.

Usage:
  scripts/grain_pairs.py                  # whole matrix
  scripts/grain_pairs.py --only sum       # substring match on shape name
  scripts/grain_pairs.py --show-groupby   # print each arm's dispatched GROUP BY list
"""
import argparse
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from outbound_sql import client, outbound, QUERY_ID  # noqa: E402
from clause_fidelity import strip_datasets, M        # noqa: E402

KEY = '"Fund"'
CAIR = '"Fund Consistency-Adjusted Information Ratio"'
BETA = '"Fund 3-Year Beta"'
AUM = '"Fund Net Assets (AUM)"'
CAT = "'Large Blend'"

# Each shape: name, outer template, inner projection list, inner WHERE, reference
# measure. `{inner}` is substituted per arm. The reference is the model's own measure
# under the same filter - the arm that matches it is the one answering the question the
# user asked, so a disagreement names a winner instead of just a discrepancy.
SHAPES = [
    # (name, agg, measure, extra inner cols, inner where, outer group by, reference SQL)
    ("avg-plain", "AVG", CAIR, [], "", "",
     f'SELECT "Average Consistency-Adjusted Information Ratio" FROM {M}'),
    ("max-plain", "MAX", CAIR, [], "", "",
     f'SELECT "Max Consistency-Adjusted Information Ratio" FROM {M}'),
    ("min-plain", "MIN", BETA, [], "", "",
     f'SELECT "Min 3-Year Beta" FROM {M}'),
    ("sum-plain", "SUM", AUM, [], "", "",
     f'SELECT "Total Net Assets (AUM)" FROM {M}'),

    ("avg-filtered", "AVG", CAIR, [], f'WHERE "Category" = {CAT}', "",
     f'SELECT "Average Consistency-Adjusted Information Ratio" FROM {M} '
     f'WHERE "Category" = {CAT}'),
    ("max-filtered", "MAX", CAIR, [], f'WHERE "Category" = {CAT}', "",
     f'SELECT "Max Consistency-Adjusted Information Ratio" FROM {M} '
     f'WHERE "Category" = {CAT}'),
    ("min-filtered", "MIN", BETA, [], f'WHERE "Category" = {CAT}', "",
     f'SELECT "Min 3-Year Beta" FROM {M} WHERE "Category" = {CAT}'),
    ("sum-filtered", "SUM", AUM, [], f'WHERE "Category" = {CAT}', "",
     f'SELECT "Total Net Assets (AUM)" FROM {M} WHERE "Category" = {CAT}'),

    # A second dimension in the SELECT/GROUP BY. The dimension is present in the inner
    # select in every arm; only the grain key varies, so this isolates whether an extra
    # grouping column substitutes for the key.
    ("avg-grouped", "AVG", CAIR, ['"Exchange"'], "", '"Exchange"',
     f'SELECT "Exchange", "Average Consistency-Adjusted Information Ratio" FROM {M} '
     f'GROUP BY "Exchange" ORDER BY "Exchange"'),
    ("sum-grouped", "SUM", AUM, ['"Exchange"'], "", '"Exchange"',
     f'SELECT "Exchange", "Total Net Assets (AUM)" FROM {M} GROUP BY "Exchange" '
     f'ORDER BY "Exchange"'),

    # Two measures in the inner select. The 2026-08-13 repro used one measure plus one
    # filter column; if a second measure is enough to make the value tuple distinct per
    # fund, the defect would hide here - which would be the worst case for guidance.
    ("avg-two-measures", "AVG", CAIR, [AUM], "", "",
     f'SELECT "Average Consistency-Adjusted Information Ratio" FROM {M}'),
]

GROUPBY = re.compile(r"^\s*GROUP BY\s*(.*)$", re.I | re.M)


def build(shape, arm):
    _, agg, measure, extra, where, outer_gb, _ = shape
    cols = list(extra)
    inner_where = where
    if arm == "projected":
        cols = [KEY] + cols
    elif arm == "where-only":
        clause = f"{KEY} IS NOT NULL"
        inner_where = f"{where} AND {clause}" if where else f"WHERE {clause}"
    cols.append(measure)
    inner = f'SELECT {", ".join(cols)} FROM {M} {inner_where}'.strip()
    outer_cols = ([f't.{c}' for c in extra] if outer_gb else []) + [f"{agg}(t.{measure}) AS v"]
    sql = f'SELECT {", ".join(outer_cols)} FROM ({inner}) t'
    if outer_gb:
        sql += f" GROUP BY t.{outer_gb} ORDER BY t.{outer_gb}"
    return sql


def run(cli, sql):
    """Return (rows-json-string, dispatched GROUP BY lists) or (None, error)."""
    try:
        res = str(cli.call_tool("run_query", {"query": sql}))
    except Exception as e:                                   # noqa: BLE001
        return None, f"TOOL ERROR: {str(e)[:120]}"
    m = QUERY_ID.search(res)
    if not m:
        return None, (res.strip().splitlines() or ["(empty)"])[0][:120]
    rows = res.split("queryId:")[0].strip()
    dispatched = "\n".join(strip_datasets(q.get("sql", "")) for q in outbound(cli, m.group(1)))
    return rows, GROUPBY.findall(dispatched)


# Below this relative gap a difference is float repr, not a grain error. Set from
# measurement, not taste: the two routes agree to ~2e-15 when they agree at all, and the
# smallest REAL dedup gap seen here is 3e-11 (SUM over AUM, where the 36 dropped rows
# happen to total $160 against a $5.65e12 sum). An earlier 1e-8 floor swallowed exactly
# that case and reported three SUM shapes as clean - the defect is sized by the data, so
# any floor loose enough to be "safe" hides real instances on data that happens to be
# kind. Relative, not absolute: AVG lands near 0.045 and SUM near 1e12.
NOISE = 1e-12


def norm(rows):
    """Numeric cell values in row order, parsed from JSON.

    Parsed rather than regexed out of the text: column NAMES carry digits here
    ("Min 3-Year Beta"), and a regex over the raw string pulls the 3 out of the label
    and reports a disagreement that does not exist.
    """
    try:
        parsed = json.loads(rows or "")
    except (json.JSONDecodeError, TypeError):
        return []
    out = []
    for row in parsed if isinstance(parsed, list) else [parsed]:
        for v in (row.values() if isinstance(row, dict) else [row]):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            out.append(float(v))
    return out


def max_rel_delta(a, b):
    """Largest relative gap between two aligned value lists; None if incomparable."""
    if not a or not b or len(a) != len(b):
        return None
    worst = 0.0
    for x, y in zip(a, b):
        scale = max(abs(x), abs(y))
        worst = max(worst, abs(x - y) / scale if scale else 0.0)
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring match on shape name")
    ap.add_argument("--show-groupby", action="store_true")
    ap.add_argument("--show-sql", action="store_true")
    args = ap.parse_args()

    shapes = [s for s in SHAPES if not args.only or args.only in s[0]]
    cli = client()
    print(f"Q-24 blast radius: {len(shapes)} shapes x 3 arms against {M}\n")

    verdicts = {}
    for shape in shapes:
        name, ref_sql = shape[0], shape[-1]
        print(f"[{name}]")
        ref_rows, _ = run(cli, ref_sql)
        print(f"    model measure : {(ref_rows or 'ERROR')[:110]}")
        ref = norm(ref_rows)

        deltas = {}
        for arm in ("projected", "omitted", "where-only"):
            sql = build(shape, arm)
            if args.show_sql:
                print(f"    {arm} sql   : {sql}")
            rows, gb = run(cli, sql)
            d = max_rel_delta(norm(rows), ref)
            deltas[arm] = d
            tag = "  n/a" if d is None else (f"  DIFFERS {d:.2e}" if d > NOISE else f"  ok ({d:.0e})")
            print(f"    {arm:<11}: {(rows or gb)[:96] if rows else gb}{tag}")
            if args.show_groupby and rows:
                print(f"                 GROUP BY {gb}")

        # The verdict that matters is not "the arms differ" but "which arm is wrong".
        wrong = [a for a, d in deltas.items() if d is not None and d > NOISE]
        if not ref or all(d is None for d in deltas.values()):
            verdicts[name] = "NO REFERENCE"
        elif not wrong:
            verdicts[name] = "all arms match the model measure"
        else:
            verdicts[name] = "wrong: " + ", ".join(wrong)
        print(f"    => {verdicts[name]}\n")

    print("=" * 66)
    for name, v in verdicts.items():
        print(f"  {name:<18} {v}")
    hit = [n for n, v in verdicts.items() if v.startswith("wrong")]
    print(f"\n{len(hit)}/{len(verdicts)} shapes have at least one silently wrong arm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
