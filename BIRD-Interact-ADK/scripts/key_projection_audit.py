#!/usr/bin/env python3
"""Does any graded submission omit the entity key? (Q-24 exposure, per stored run.)

Q-24: a projection that omits a per-entity-unique key is deduplicated on the value
tuple, so rows silently vanish - `SELECT "Fund 3-Year Beta" FROM model` returns 342
rows where there are 2310 funds. It is invisible from the result and it lands on the
submitted answer directly, which is why Q-24 is P0.

This audits a completed run for exposure to it. For each task it takes the GRADED
submission - the LAST trajectory item whose args carry an `sql` key, not the first -
parses it with sqlglot, and reports every SELECT scope that reads the model directly:
which model dimensions and measures it projects, its GROUP BY, and whether the key is
projected.

A scope is flagged when it reads the model, projects at least one dimension, and does
not project the key. Flagged is NOT the same as defective: a grouped scope whose GROUP
BY key is itself projected is answering at that grain legitimately. Confirming a flag
means comparing the row count against a key-added variant, which has to be written by
hand per task - a generated rewriter changes the question (adding "Fund" to a GROUP BY
explodes the grain rather than restoring lost rows). Use --rows to get the baseline
counts this comparison starts from.

No LLM calls and no benchmark tokens: MCP queries only, and none at all without --rows.

Usage:
  scripts/key_projection_audit.py results/<run>.json
  scripts/key_projection_audit.py results/<run>.json --rows      # + live row counts
  scripts/key_projection_audit.py results/<run>.json --key Fund
"""
import argparse
import csv
import io
import json
import sys

import sqlglot
from sqlglot import expressions as exp

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
sys.path.insert(0, __file__.rsplit("/", 1)[0])

CATALOG = "bird_atscale_models_catalog_main"
TABLE = "Exchange Traded Funds"


def roles(cli):
    """{name: 'measure'|'dimension'} from explore_columns.

    Parsed with csv, not a regex: the remark field is quoted only when it contains a
    comma, so a pattern anchored on `name,"` silently drops every column whose remark
    happens to be comma-free - which cost this script a wrong answer on "Family".
    """
    out = {}
    for role in ("measure", "dimension"):
        raw = str(cli.call_tool("explore_columns", {
            "catalog": CATALOG, "schema": CATALOG, "table": TABLE, "role": role}))
        for row in csv.reader(io.StringIO(raw)):
            if len(row) < 2:
                continue
            name = row[0].strip()
            if name and not name.startswith(("#", "column_name", "Columns grouped")):
                out.setdefault(name, role)
    return out


def graded_submissions(path):
    """{task_id: (reward, sql)} using the LAST sql-bearing trajectory item."""
    data = json.load(open(path))
    out = {}
    for task in data["results"]:
        subs = [i for i in task["tool_trajectory"]
                if isinstance(i.get("args"), dict) and "sql" in i["args"]]
        if subs:
            out[task["task_id"]] = (task["total_reward"], subs[-1]["args"]["sql"])
    return out


def on_model(select):
    """True if this Select's FROM is the model table, not a derived table.

    sqlglot 30 names the arg `from_`; reading `from` returns None for every scope and
    drives the flagged count to a false zero.
    """
    frm = select.args.get("from_") or select.args.get("from")
    src = frm.this if frm else None
    return isinstance(src, exp.Table) and TABLE in (src.name or "")


def columns(nodes):
    return [c.name for n in nodes for c in n.find_all(exp.Column)]


def audit(sql, role_of, key):
    scopes = []
    for i, sel in enumerate(sqlglot.parse_one(sql).find_all(exp.Select)):
        proj = columns(sel.expressions)
        gb = columns(sel.args["group"].expressions) if sel.args.get("group") else []
        dims = [c for c in proj if role_of.get(c) == "dimension"]
        meas = [c for c in proj if role_of.get(c) == "measure"]
        model = on_model(sel)
        scopes.append({
            "scope": i, "on_model": model, "key_projected": key in proj,
            "dims": dims, "measures": meas, "group_by": gb,
            "flagged": bool(model and dims and key not in proj),
        })
    return scopes


def row_count(cli, sql):
    from outbound_sql import QUERY_ID
    try:
        res = str(cli.call_tool("run_query", {"query": sql}))
    except Exception as e:                                       # noqa: BLE001
        return None, f"ERROR: {str(e).splitlines()[0][:90]}"
    if not QUERY_ID.search(res):
        return None, "NO QUERYID"
    try:
        rows = json.loads(res.split("queryId:")[0].strip())
    except json.JSONDecodeError:
        return None, "UNPARSEABLE RESULT"
    return len(rows if isinstance(rows, list) else [rows]), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", help="path to a stored run's results JSON")
    ap.add_argument("--key", default="Fund", help="entity key column (default Fund)")
    ap.add_argument("--rows", action="store_true", help="also run each submission live")
    args = ap.parse_args()

    from outbound_sql import client
    cli = client()
    role_of = roles(cli)
    subs = graded_submissions(args.results)
    print(f"{len(subs)} graded submissions; key = {args.key!r}; "
          f"{sum(1 for r in role_of.values() if r == 'dimension')} dimensions, "
          f"{sum(1 for r in role_of.values() if r == 'measure')} measures\n")

    flagged = []
    for task, (reward, sql) in subs.items():
        short = task.rsplit("_", 1)[-1]
        try:
            scopes = audit(sql, role_of, args.key)
        except Exception as e:                                   # noqa: BLE001
            print(f"_{short:<4} reward={reward:<4} PARSE ERROR {e}")
            continue
        hits = [s["scope"] for s in scopes if s["flagged"]]
        extra = ""
        if args.rows:
            n, err = row_count(cli, sql)
            extra = f" | {n} rows" if n is not None else f" | {err}"
        if hits:
            flagged.append(task)
        print(f"_{short:<4} reward={reward:<4} "
              f"{'FLAGGED scopes ' + str(hits) if hits else 'key present in every model scope'}"
              f"{extra}")
        for s in scopes:
            tag = "<<< FLAGGED" if s["flagged"] else ("on-model" if s["on_model"] else "derived")
            print(f"       s{s['scope']} {tag:<12} key={str(s['key_projected']):<5} "
                  f"dims={s['dims']} meas={s['measures']} gb={s['group_by']}")

    print(f"\n{len(flagged)}/{len(subs)} tasks have a flagged scope"
          + (f": {', '.join(t.rsplit('_', 1)[-1] for t in flagged)}" if flagged else ""))
    print("A flag is exposure, not a defect - confirm with a hand-written key-added variant.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
