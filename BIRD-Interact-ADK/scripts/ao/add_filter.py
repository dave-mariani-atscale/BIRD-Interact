"""Add a standard row filter to every statement in a query log that reads a given table.

Usage (sqlglot needed, e.g. from the AO repo): uv run python add_filter.py <in.csv> <out.csv> <table> <column> <value>
Each SELECT that reads <table> gets `<alias>.<column> = <value>`: in the JOIN's ON when the table is
the outer side of a LEFT/RIGHT/FULL join (keeps the join's meaning), else ANDed into the SELECT's WHERE.
Statements sqlglot cannot parse are dropped and counted.
"""

import csv
import sys

import sqlglot
from sqlglot import exp


def rewrite(sql: str, table: str, col: str, val: str) -> str:
    tree = sqlglot.parse_one(sql, read="postgres")
    for t in list(tree.find_all(exp.Table)):
        if t.name != table:
            continue
        cond = exp.condition(f"{t.alias_or_name}.{col} = {val}")
        join = t.parent if isinstance(t.parent, exp.Join) else None
        if join and join.side:
            join.set("on", exp.and_(join.args["on"], cond) if join.args.get("on") else cond)
            continue
        sel = t.find_ancestor(exp.Select)
        if sel is not None:
            sel.where(cond, copy=False)
    return tree.sql(dialect="postgres")


def main(src: str, dst: str, table: str, col: str, val: str) -> None:
    changed = dropped = 0
    with open(src) as f, open(dst, "w", newline="") as g:
        r = csv.DictReader(f)
        w = csv.DictWriter(g, fieldnames=r.fieldnames)
        w.writeheader()
        for row in r:
            q = row["query_text"]
            try:
                new = rewrite(q, table, col, val) if table in q else q
            except Exception:
                dropped += 1
                continue
            changed += new != q
            row["query_text"] = new
            w.writerow(row)
    print(f"rewritten {changed}, dropped (unparseable) {dropped}")


if __name__ == "__main__":
    main(*sys.argv[1:6])
