#!/usr/bin/env python3
"""Does the model already carry gold's whole DERIVED quantity as one named object?

The 0825 failure analysis put the remaining losses in assembly, not lookup: the
agent finds the right objects and builds most of a multi-part definition, then
drops a conjunct or a term. planets_data_10's gold ANDs two quality flags and
the agent applied one; insider_trading_10's aggression formula includes
cancel_pct and the agent's composite omits it. Neither is a naming problem — the
names were all present — so neither is reachable by rewording a description.

What IS reachable: publishing the finished composite as a single named measure,
so there is nothing left to assemble. This measures how often that is already
true, and names the tasks where it is not.

Method, and its limits, because this is a proxy and should be read as one:

  * gold's COMPOSITE COLUMNS are the warehouse columns it touches inside a
    derived expression — a CASE, arithmetic, an aggregate argument, or a
    comparison against a literal. Join keys (column = column) and bare
    identifier projections are excluded: they are how gold reaches the data, not
    what it computes.
  * a model object's REACH is the warehouse columns it resolves to, following
    expression references to a fixed point (shared with collision_causal.py).
  * the composite is CARRIED when one object's reach covers every composite
    column. Two objects that jointly cover it do not count — that is the
    assembly this is trying to remove.

Under-claims where gold reaches a column through a view or names it differently
from the model's `column:` entry, and over-claims where an object happens to
span the columns without computing gold's function of them. Treat a low
coverage score as a place to LOOK, not as a proven defect.

    python scripts/composite_coverage.py <grading_audit.jsonl>
        [--databases a,b] [--quartile 4] [--results-dir results/825_all]
        [--arm atscale] [--models-repo PATH] [--out results/composite_coverage.json]

No MCP, no LLM, no re-run.
"""
import argparse
import collections
import glob
import json
import os
import sys
import re

import sqlglot
import yaml
from sqlglot import expressions as exp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collision_causal import object_columns          # noqa: E402  (same resolver)

DEFAULT_MODELS = os.environ.get(
    "BIRD_MODELS_REPO",
    "/Users/dianne/go/src/github.com/AtScaleInc/bird-atscale-models")

ARITH = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Pow, exp.Mod)
CMP = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.In)


def dataset_physical_columns(model_dir):
    """(dataset, output column) -> the PHYSICAL columns its expression reads.

    Model objects name a dataset column, not a warehouse column: the dataset's
    `sql:` block is where `h.socioeconomic->>'Tenure_Type'` becomes
    `tenure_type`. Without this hop every object resolves to names gold never
    writes, and the coverage test measures nothing - which is what the
    passed-task control caught the first time this script was run.
    """
    out = collections.defaultdict(set)
    for path in glob.glob(os.path.join(model_dir, "datasets", "*.yml")):
        try:
            doc = yaml.safe_load(open(path, errors="ignore"))
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(doc, dict):
            continue
        name, sql = doc.get("unique_name"), doc.get("sql")
        if not name:
            continue
        if not sql:                      # a physical-table dataset: columns are already physical
            for col in doc.get("columns") or []:
                if isinstance(col, dict) and col.get("name"):
                    out[(name, col["name"].lower())].add(col["name"].lower())
            continue
        try:
            tree = sqlglot.parse_one(sql, read="postgres")
        except sqlglot.ParseError:
            continue
        for projection in (tree.selects if hasattr(tree, "selects") else []):
            alias = projection.alias_or_name
            if not alias:
                continue
            phys = {c.name.lower() for c in projection.find_all(exp.Column) if c.name}
            out[(name, alias.lower())] |= phys
    return out


def object_reach(model_dir):
    """unique_name -> physical warehouse columns, resolved through the datasets."""
    logical = object_columns(model_dir)          # object -> dataset column names
    ds = dataset_physical_columns(model_dir)
    if not ds:
        raise SystemExit(f"no dataset SQL resolved under {model_dir}/datasets — "
                         "object reach would silently fall back to logical names "
                         "and the coverage number would be meaningless")
    by_col = collections.defaultdict(set)
    for (_dataset, col), phys in ds.items():
        by_col[col] |= phys
    reach = {}
    for name, cols in logical.items():
        phys = set()
        for col in cols:
            low = col.lower()
            phys |= by_col.get(low, {low})       # fall back to the name itself
        reach[name] = phys
    return reach


def gold_complexity(sql):
    """The 0825 difficulty proxy: comparisons + 3*CASE branch + 2*CTE."""
    s = sql.lower()
    return (len(re.findall(r"[<>]=?|!=|<>|\s=\s", s))
            + 3 * len(re.findall(r"\bwhen\b", s))
            + 2 * len(re.findall(r"\bwith\b", s)))


def composite_columns(sql):
    """Warehouse columns gold touches inside a derived expression.

    Gold's OWN aliases are subtracted. A gold that computes `cpi_score` in a CTE
    and then buckets it in the outer select references `cpi_score` from a CASE,
    but that is gold's intermediate, not a column any model could carry - leaving
    it in makes every composite look unreachable.
    """
    try:
        trees = sqlglot.parse(sql, read="postgres")
    except Exception:
        return None
    found = set()
    own = set()
    for tree in trees:
        if tree is None:
            continue
        for node in tree.find_all(exp.Alias):
            if node.alias:
                own.add(node.alias.lower())
        for node in tree.find_all(exp.CTE):
            if node.alias:
                own.add(node.alias.lower())
        for node in tree.find_all(exp.TableAlias):
            if node.name:
                own.add(node.name.lower())

    def columns_under(node):
        return {c.name for c in node.find_all(exp.Column) if c.name}

    for tree in trees:
        if tree is None:
            continue
        for node in tree.find_all(exp.Case, *ARITH):
            found |= columns_under(node)
        for node in tree.find_all(exp.AggFunc):
            found |= columns_under(node)
        for node in tree.find_all(*CMP):
            left, right = node.this, node.args.get("expression")
            # column = column is a join key: how gold reaches the data, not what it computes
            if isinstance(left, exp.Column) and isinstance(right, exp.Column):
                continue
            found |= columns_under(node)
        # JSON extraction (txprogmet->>'Tx_Adh') is a derived read in these golds
        for node in tree.find_all(exp.JSONExtract, exp.JSONExtractScalar):
            found |= columns_under(node)
    return {c.lower() for c in found if len(c) > 2} - own


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audit_file")
    ap.add_argument("--databases", help="comma-separated; default every db in --results-dir")
    ap.add_argument("--quartile", type=int, default=4,
                    help="gold-complexity quartile to report, computed over the whole run (default 4)")
    ap.add_argument("--results-dir", default="results/825_all")
    ap.add_argument("--arm", default="atscale")
    ap.add_argument("--models-repo", default=DEFAULT_MODELS)
    ap.add_argument("--out", default="results/composite_coverage.json")
    args = ap.parse_args()

    db_of, passed = {}, {}
    for path in glob.glob(os.path.join(args.results_dir, f"*_{args.arm}.json")):
        db = os.path.basename(path)[:-len(f"_{args.arm}.json")]
        for row in json.load(open(path))["results"]:
            db_of[row["task_id"]] = db
            passed[row["task_id"]] = row["phase1_passed"]

    # Last phase-1 attempt per task, so the verdict is the one the run ended on.
    golds = {}
    for line in open(args.audit_file):
        if not line.strip():
            continue
        row = json.loads(line)
        if row["phase"] != 1:
            continue
        gold = " ".join(row["sol_sql"]) if isinstance(row["sol_sql"], list) else (row["sol_sql"] or "")
        golds[row["task_id"]] = gold

    ranked = sorted(golds, key=lambda t: gold_complexity(golds[t]))
    size = max(len(ranked) // 4, 1)
    lo = (args.quartile - 1) * size
    hi = len(ranked) if args.quartile == 4 else args.quartile * size
    in_quartile = set(ranked[lo:hi])
    print(f"gold-complexity quartile {args.quartile}: {len(in_quartile)} tasks of {len(ranked)}\n")

    wanted = set(args.databases.split(",")) if args.databases else None
    cache, out = {}, []
    for tid in sorted(in_quartile):
        db = db_of.get(tid)
        if not db or (wanted and db not in wanted):
            continue
        if db not in cache:
            cache[db] = object_reach(os.path.join(args.models_repo, db))
        reach = cache[db]
        need = composite_columns(golds[tid])
        if not need:
            continue
        best, best_cov = None, 0.0
        carried = []
        for name, cols in reach.items():
            low = {c.lower() for c in cols}
            cov = len(need & low) / len(need)
            if need <= low:
                carried.append(name)
            if cov > best_cov:
                best, best_cov = name, cov
        # Greedy set cover: the number of objects the agent must combine, and
        # what the model cannot reach at all.
        remaining, pieces = set(need), 0
        while remaining:
            gain, pick = 0, None
            for name, cols in reach.items():
                g = len(remaining & {c.lower() for c in cols})
                if g > gain:
                    gain, pick = g, name
            if not pick:
                break
            remaining -= {c.lower() for c in reach[pick]}
            pieces += 1
        out.append(dict(task=tid, db=db, need=sorted(need), carried=carried,
                        best=best, best_coverage=round(best_cov, 2),
                        pieces=pieces if not remaining else None,
                        unreachable=sorted(remaining), passed=bool(passed.get(tid))))

    fails = [r for r in out if not r["passed"]]
    wins = [r for r in out if r["passed"]]
    print("CONTROL — same quartile, same databases, graded outcome:")
    for label, group in (("phase-1 FAILED", fails), ("phase-1 PASSED", wins)):
        if not group:
            continue
        spanned = sum(1 for r in group if r["carried"])
        mean_cov = sum(r["best_coverage"] for r in group) / len(group)
        pieces = [r["pieces"] for r in group if r["pieces"]]
        mp = sum(pieces) / len(pieces) if pieces else float("nan")
        unreach = sum(1 for r in group if r["unreachable"])
        print(f"  {label:16s} n={len(group):3d}  spanned by ONE object {spanned:2d}  "
              f"best single {mean_cov:.2f}  objects to combine {mp:.1f}  "
              f"with a column no object reaches {unreach}")
    print()
    by_db = collections.defaultdict(list)
    for rec in fails:
        by_db[rec["db"]].append(rec)
    print(f"{'database':22s} {'failing q4':>11s} {'carried':>8s} {'best cov (mean)':>16s}")
    for db in sorted(by_db):
        rs = by_db[db]
        n_carried = sum(1 for r in rs if r["carried"])
        mean = sum(r["best_coverage"] for r in rs) / len(rs)
        print(f"{db:22s} {len(rs):11d} {n_carried:8d} {mean:16.2f}")

    print("\nTasks whose composite NO single object spans — the assembly the agent is left to do:")
    for rec in sorted(fails, key=lambda r: (r["db"], -len(r["need"]))):
        if rec["carried"]:
            continue
        print(f"  {rec['db']:22s} {rec['task']:26s} needs {len(rec['need']):2d} cols, "
              f"best single object covers {rec['best_coverage']:.0%} ({rec['best']})")
        print(f"      {', '.join(rec['need'])}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
