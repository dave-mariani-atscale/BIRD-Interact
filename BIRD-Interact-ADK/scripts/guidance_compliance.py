#!/usr/bin/env python3
"""Item 3: is the atscale guidance landing? Per-bullet compliance over stored runs.

Every classification is made on the PARSED submission (sqlglot), never on a regex over
the SQL text. Eight detector bugs on 2026-08-13 each produced a confident wrong answer
from pattern-matching, so the rule here is: walk the AST, and when a check cannot be
made structurally, report it as not-mechanically-checkable rather than approximating it.

Two scoping rules make the rates mean something:

  * A run is only scored against bullets that EXISTED when it ran. Bullet introduction
    dates come from `git log -S` on config/environment_backends.yaml; run dates from the
    results file's mtime (validated against the timestamps in the filenames). Scoring a
    2026-08-03 run against a bullet added 2026-08-13 measures nothing.
  * Only ETF atscale submissions count. The role map (measure vs dimension) is
    ETF-specific, and raw-arm submissions never saw this guidance at all. Arm is decided
    from the SQL's own FROM target, not from the filename.

No LLM calls, no MCP calls, no benchmark tokens: pure offline parsing.
"""
import glob
import json
import os
import re
import subprocess
import sys

import sqlglot
from sqlglot import expressions as exp

S = os.path.dirname(os.path.abspath(__file__))
# roles.json = {"measure": [...], "dimension": [...]} from explore_columns; regenerate with
# scripts/key_projection_audit.py's roles() helper, or point ETF_ROLES_JSON at a copy.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROLES = json.load(open(os.environ.get("ETF_ROLES_JSON", f"{S}/roles.json")))
MEASURE, DIM = set(ROLES["measure"]), set(ROLES["dimension"])
MODEL_TABLES = ("Exchange Traded Funds", "exchange_traded_funds_test")
MODEL_SCHEMAS = ("bird_atscale_models_catalog_main", "bird_etf_prompt_only_main",
                 "atscale_catalogs")
# The fund-grain key was RENAMED across deployments: "Fund Ticker" up to 2026-08-07,
# "Fund" from 2026-08-06 on. Hardcoding "Fund" alone reported a 66.2% violation rate on
# the grain bullet that hand-checking showed was almost entirely this rename - the inner
# projections did carry a key, under the older name.
KEY_SET = {"Fund", "Fund Ticker"}

# Detectors that ask "is this column a measure or a dimension?" can only be trusted where
# the submission's column names actually resolve against the CURRENT model's role map.
# Measured coverage of quoted column refs: 22-53% for runs up to 2026-08-06, then 96.2%,
# 99.0%, 96.8%, 99.7% from 2026-08-10 on. Below that threshold a role lookup silently
# returns "neither", so the detector under-counts instead of erroring.
ROLE_MAP_VALID_FROM = "2026-08-10"
ROLE_DEPENDENT = {"count-dim-plain", "count-distinct-alone", "sum-count-dim-groupby",
                  "prefer-count-measure", "grain-in-inner-select", "explicit-order-by"}

# phrase -> (bullet id, human label). Phrase is what git is searched for, so it must be
# the wording actually committed. Cited by phrase, not line number: lines shift.
# (bullet id, phrase cited, date the RULE first appeared).
#
# The date is the rule's introduction, NOT the current wording's. Several bullets were
# rewritten later, and dating them by today's phrasing shrinks the eligible population
# to the last day or two and silently turns a real rate into "insufficient data" — E-01's
# COUNT rule reads 2026-08-12 by wording but landed 2026-08-03 (858372b), which is the
# difference between 107 eligible submissions and 850. Each date was read off
# `git log --reverse -S<phrase> -- config/environment_backends.yaml`; where the rule and
# its later refinement have different dates they are split into separate bullets.
BULLETS = [
    ("count-star", "COUNT(*) is rejected by this engine", "2026-07-29"),
    ("count-dim-plain", "Plain COUNT(\"<dim>\") is silently wrong", "2026-08-03"),
    ("count-distinct-alone", "must be ALONE in its SELECT", "2026-08-12"),
    ("union-model", "NEVER COMBINE TWO QUERIES OF THE MODEL WITH UNION", "2026-08-07"),
    ("bare-numeric-cast", "A CAST to a numeric type MUST carry an explicit precision", "2026-08-07"),
    ("no-cte", "does NOT support CTEs", "2026-07-29"),
    ("rhs-subquery", "NEVER put a subquery over the model on the right-hand side", "2026-08-10"),
    ("grain-in-inner-select", "force the natural row grain", "2026-08-04"),
    ("no-offset", "OFFSET IS SILENTLY IGNORED", "2026-08-13"),
    ("inner-limit-required", "That inner LIMIT is required", "2026-08-03"),
    ("no-in-subquery", "does NOT support `IN (subquery)`", "2026-08-04"),
    ("sum-count-dim-groupby", "A raw SQL SUM() or COUNT() applied to a dimension column", "2026-08-13"),
    ("no-case-in-aggregate", "Do NOT wrap a CASE expression", "2026-08-04"),
    ("no-crossjoin-derived", "Do NOT cross-join two aggregated derived tables", "2026-08-04"),
    ("nulls-first-last", "NULLS FIRST and NULLS LAST are accepted without error and then IGNORED", "2026-08-13"),
    ("explicit-order-by", "include an explicit ORDER BY on every multi-row", "2026-08-05"),
    ("prefer-count-measure", "If the model publishes a count measure", "2026-08-12"),
    ("round-precision", "Do NOT round in SQL unless the question states a precision", "2026-08-07"),
]

AGGS = (exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Count)


def counted_columns(count_node):
    """Column names inside a COUNT(...), and whether it was DISTINCT.

    sqlglot puts the argument of COUNT(DISTINCT x) in Distinct.EXPRESSIONS, and leaves
    Distinct.this as None. Reading .this returned nothing for every DISTINCT count, so
    the E-01 detector saw 0 applicable cases and reported "insufficient data" on the one
    bullet this item most needed to measure.
    """
    arg = count_node.this
    distinct = isinstance(arg, exp.Distinct)
    holders = arg.expressions if distinct else ([arg] if arg is not None else [])
    names = [c.name for h in holders if hasattr(h, "find_all") for c in h.find_all(exp.Column)]
    return names, distinct


def wrote_nulls_ordering(sql):
    """Was NULLS FIRST/LAST actually written? Lexical, because sqlglot fills it in.

    exp.Ordered always carries a nulls_first value - False for DESC, True for bare ASC -
    whether or not the text said so, so `nulls_first is not None` flagged 88.9% of all
    submissions as violations. This tokenizes instead of regexing so the token cannot be
    matched inside a string literal.
    """
    from sqlglot.tokens import Tokenizer
    try:
        return any(tk.text.upper() == "NULLS" for tk in Tokenizer().tokenize(sql))
    except Exception:                                            # noqa: BLE001
        return False


def run_date(path):
    m = re.search(r"_(\d{8})_\d{6}\.json$", path)
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    import datetime
    return datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()


def is_model_sql(sql):
    """Semantic-layer submission? Decided from the FROM target, not the filename."""
    return any(t in sql for t in MODEL_TABLES) or any(s in sql for s in MODEL_SCHEMAS)


def on_model(select):
    frm = select.args.get("from_") or select.args.get("from")
    src = frm.this if frm else None
    return isinstance(src, exp.Table) and any(t in (src.name or "") for t in MODEL_TABLES)


def col_names(node):
    return [c.name for c in node.find_all(exp.Column)]


# ---------------------------------------------------------------- detectors
# Each returns (applicable: bool, violated: bool, note: str).

def d_count_star(t, ctx):
    stars = [c for c in t.find_all(exp.Count)
             if any(isinstance(a, exp.Star) for a in c.find_all(exp.Star))]
    return True, bool(stars), "COUNT(*)" if stars else ""


def d_count_dim_plain(t, ctx):
    """E-01: plain COUNT(dim) returns the member values, not a count."""
    applicable = violated = False
    notes = []
    for sel in t.find_all(exp.Select):
        for c in sel.find_all(exp.Count):
            names, distinct = counted_columns(c)
            dims = [n for n in names if n in DIM]
            if not dims:
                continue
            applicable = True
            if not distinct:
                violated = True
                notes.append(f"plain COUNT({dims[0]!r})")
    return applicable, violated, "; ".join(notes)


def d_count_distinct_alone(t, ctx):
    """COUNT(DISTINCT dim) must be ALONE in its SELECT or the two forms poison each other."""
    applicable = violated = False
    notes = []
    for sel in t.find_all(exp.Select):
        for c in sel.find_all(exp.Count):
            names, distinct = counted_columns(c)
            if not distinct or not [n for n in names if n in DIM]:
                continue
            applicable = True
            if len(sel.expressions) > 1:
                violated = True
                notes.append(f"COUNT(DISTINCT {names[0]!r}) beside "
                             f"{len(sel.expressions)-1} other projection(s)")
    return applicable, violated, "; ".join(notes)


def d_union_model(t, ctx):
    unions = list(t.find_all(exp.Union))
    if not unions:
        return True, False, ""
    for u in unions:
        for side in (u.this, u.expression):
            for sel in [side] + list(side.find_all(exp.Select)):
                if isinstance(sel, exp.Select) and on_model(sel):
                    return True, True, "UNION with a model-reading branch"
    return True, False, "literal-only UNION (permitted form)"


def d_bare_numeric_cast(t, ctx):
    applicable = violated = False
    notes = []
    for c in t.find_all(exp.Cast):
        to = c.to
        if to and to.this in (exp.DataType.Type.DECIMAL,):
            applicable = True
            if not to.expressions:
                violated = True
                notes.append("CAST to numeric with no precision/scale")
    return applicable, violated, "; ".join(notes)


def d_no_cte(t, ctx):
    has = bool(list(t.find_all(exp.With)))
    return True, has, "WITH ... AS (...)" if has else ""


def d_rhs_subquery(t, ctx):
    """Q-26: a model subquery on the RHS of a comparison, or as a SELECT-list scalar."""
    notes = []
    cmps = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
    for node in t.find_all(*cmps):
        rhs = node.expression
        if isinstance(rhs, exp.Subquery) or (hasattr(rhs, "find") and rhs.find(exp.Select)):
            sub = rhs if isinstance(rhs, exp.Select) else (rhs.find(exp.Select) if hasattr(rhs, "find") else None)
            if sub is not None and on_model(sub):
                notes.append("model subquery on RHS of a comparison")
    return True, bool(notes), "; ".join(sorted(set(notes)))


def d_grain_in_inner_select(t, ctx):
    """Q-24: an outer aggregate over a derived table whose projection omits the key."""
    applicable = violated = False
    notes = []
    for sel in t.find_all(exp.Select):
        frm = sel.args.get("from_") or sel.args.get("from")
        src = frm.this if frm else None
        if not isinstance(src, exp.Subquery):
            continue
        if not any(isinstance(e, AGGS) or (hasattr(e, "find") and e.find(*AGGS))
                   for e in sel.expressions):
            continue
        inner = src.find(exp.Select)
        if inner is None or not on_model(inner):
            continue
        applicable = True
        proj = col_names(exp.select(*inner.expressions)) if inner.expressions else []
        proj = [c.name for e in inner.expressions for c in e.find_all(exp.Column)]
        if not (set(proj) & KEY_SET):
            violated = True
            notes.append(f"inner projection lacks a fund key: {proj}")
    return applicable, violated, "; ".join(notes)


def d_no_offset(t, ctx):
    has = bool(list(t.find_all(exp.Offset)))
    return True, has, "OFFSET present" if has else ""


def d_inner_limit_required(t, ctx):
    """A derived table carrying ORDER BY must carry LIMIT, or the sort is dropped."""
    applicable = violated = False
    notes = []
    for sub in t.find_all(exp.Subquery):
        inner = sub.this if isinstance(sub.this, exp.Select) else None
        if inner is None or not inner.args.get("order"):
            continue
        applicable = True
        if not inner.args.get("limit"):
            violated = True
            notes.append("derived table has ORDER BY with no LIMIT")
    return applicable, violated, "; ".join(notes)


def d_no_in_subquery(t, ctx):
    notes = []
    for node in t.find_all(exp.In):
        if node.args.get("query") or any(node.find_all(exp.Select)):
            notes.append("IN (subquery)")
    if list(t.find_all(exp.Exists)):
        notes.append("EXISTS")
    return True, bool(notes), "; ".join(sorted(set(notes)))


def d_sum_count_dim_groupby(t, ctx):
    """Raw SUM/COUNT over a dimension column alongside GROUP BY neither sums nor groups."""
    applicable = violated = False
    notes = []
    for sel in t.find_all(exp.Select):
        if not sel.args.get("group"):
            continue
        for agg in sel.find_all(exp.Sum, exp.Count):
            arg = agg.this
            inner = arg.this if isinstance(arg, exp.Distinct) else arg
            if isinstance(arg, exp.Distinct):
                continue
            names = [x.name for x in inner.find_all(exp.Column)] if hasattr(inner, "find_all") else []
            dims = [n for n in names if n in DIM]
            if dims:
                applicable = True
                violated = True
                notes.append(f"{agg.key.upper()}({dims[0]!r}) with GROUP BY")
    return applicable, violated, "; ".join(notes)


def d_no_case_in_aggregate(t, ctx):
    notes = []
    for agg in t.find_all(*AGGS):
        if agg.this is not None and hasattr(agg.this, "find") and agg.this.find(exp.Case):
            notes.append(f"{agg.key.upper()}(CASE ...)")
    return True, bool(notes), "; ".join(sorted(set(notes)))


def d_no_crossjoin_derived(t, ctx):
    """FROM (SELECT ...) a, (SELECT ...) b - comma cross-join of two derived tables."""
    notes = []
    for sel in t.find_all(exp.Select):
        frm = sel.args.get("from_") or sel.args.get("from")
        if not frm:
            continue
        srcs = [frm.this] + [j.this for j in sel.args.get("joins") or []
                             if not j.args.get("on") and not j.args.get("using")]
        subs = [s for s in srcs if isinstance(s, exp.Subquery)]
        if len(subs) > 1:
            notes.append("comma-joined derived tables")
    return True, bool(notes), "; ".join(sorted(set(notes)))


def d_nulls_first_last(t, ctx):
    """NULLS FIRST/LAST is accepted then ignored, so writing it is a violation."""
    wrote = wrote_nulls_ordering(ctx.get("sql", ""))
    return True, wrote, "NULLS FIRST/LAST written" if wrote else ""


def d_explicit_order_by(t, ctx):
    """Applicable when the submission plausibly returns multiple rows.

    Structural proxy: no LIMIT 1, and the projection is not purely aggregate (a
    scalar). Recorded as a proxy, and hand-checked in the sample.
    """
    root = t
    sel = root if isinstance(root, exp.Select) else (root.find(exp.Select) if hasattr(root, "find") else None)
    if sel is None or isinstance(root, exp.Union):
        return False, False, "union/non-select: skipped"
    lim = sel.args.get("limit")
    if lim is not None and str(getattr(lim.expression, "this", "")) == "1":
        return False, False, "LIMIT 1: scalar"
    # Scalar if every projection is a SQL aggregate OR a pre-aggregated model MEASURE.
    # Counting only SQL aggregates flagged all 8 measure-only submissions in the newest
    # run as "multi-row with no ORDER BY" - "SELECT \"Fund Count\" FROM model" returns one
    # row and needs no sort. That single omission produced the only substantial violation
    # rate in the whole sweep, which is why it is checked against the role map.
    def scalarish(e):
        if isinstance(e, AGGS) or (hasattr(e, "find") and e.find(*AGGS)):
            return True
        names = [c.name for c in e.find_all(exp.Column)]
        return bool(names) and all(n in MEASURE for n in names)
    if sel.expressions and all(scalarish(e) for e in sel.expressions) and not sel.args.get("group"):
        return False, False, "aggregate/measure-only: scalar"
    has = bool(sel.args.get("order")) or any(
        s.args.get("order") for s in root.find_all(exp.Select))
    return True, not has, "" if has else "multi-row submission with no ORDER BY"


def d_prefer_count_measure(t, ctx):
    """Hand-written COUNT where the model publishes a Count measure for that entity.

    Applicable only when the counted column has a published "<Col> Count" measure -
    flagging every COUNT reported 100% violation on 4 cases, which measured the detector
    rather than the agent.
    """
    applicable = violated = False
    notes = []
    for c in t.find_all(exp.Count):
        names, _ = counted_columns(c)
        for n in names:
            if f"{n} Count" in MEASURE:
                applicable = True
                violated = True
                notes.append(f"COUNT({n!r}) but model publishes \"{n} Count\"")
    return applicable, violated, "; ".join(sorted(set(notes)))


def d_round_precision(t, ctx):
    """ROUND must match the task's own stated precision, or be absent when none."""
    rounds = list(t.find_all(exp.Round))
    dec = ctx.get("decimal")
    if not rounds:
        return (dec is not None and dec >= 0), False, ""
    notes = []
    violated = False
    for r in rounds:
        args = r.args.get("decimals")
        n = None
        if args is not None:
            try:
                n = int(args.name)
            except (ValueError, TypeError):
                n = None
        if dec is None or dec < 0:
            violated = True
            notes.append(f"ROUND(...,{n}) but task states no precision")
        elif n is not None and n != dec:
            violated = True
            notes.append(f"ROUND(...,{n}) but task decimal={dec}")
    return True, violated, "; ".join(notes)


DETECTORS = {
    "count-star": d_count_star,
    "count-dim-plain": d_count_dim_plain,
    "count-distinct-alone": d_count_distinct_alone,
    "union-model": d_union_model,
    "bare-numeric-cast": d_bare_numeric_cast,
    "no-cte": d_no_cte,
    "rhs-subquery": d_rhs_subquery,
    "grain-in-inner-select": d_grain_in_inner_select,
    "no-offset": d_no_offset,
    "inner-limit-required": d_inner_limit_required,
    "no-in-subquery": d_no_in_subquery,
    "sum-count-dim-groupby": d_sum_count_dim_groupby,
    "no-case-in-aggregate": d_no_case_in_aggregate,
    "no-crossjoin-derived": d_no_crossjoin_derived,
    "nulls-first-last": d_nulls_first_last,
    "explicit-order-by": d_explicit_order_by,
    "prefer-count-measure": d_prefer_count_measure,
    "round-precision": d_round_precision,
}


def task_conditions():
    from shared.config import settings
    out = {}
    for line in open(settings.data_path):
        d = json.loads(line)
        if d.get("selected_database") == "exchange_traded_funds":
            out[d["instance_id"]] = {
                "decimal": (d.get("conditions") or {}).get("decimal")}
    return out


def collect():
    """[(run, date, task, reward, is_graded, sql)] for ETF atscale submissions."""
    rows = []
    for path in sorted(glob.glob(f"{ROOT}/results/*.json")):
        try:
            d = json.load(open(path))
        except Exception:
            continue
        if not isinstance(d, dict) or "results" not in d:
            continue
        date = run_date(path)
        for t in d["results"] or []:
            if t.get("database") != "exchange_traded_funds":
                continue
            subs = [i for i in t.get("tool_trajectory") or []
                    if isinstance(i.get("args"), dict) and i["args"].get("sql")]
            subs = [s for s in subs if is_model_sql(s["args"]["sql"])]
            for i, s in enumerate(subs):
                rows.append({
                    "run": os.path.basename(path), "date": date,
                    "task": t.get("instance_id") or t.get("task_id"),
                    "reward": t.get("total_reward"),
                    "graded": i == len(subs) - 1,
                    "sql": s["args"]["sql"],
                })
    return rows


def main():
    conds = task_conditions()
    rows = collect()
    runs = sorted({(r["run"], r["date"]) for r in rows}, key=lambda x: x[1])
    print(f"{len(rows)} ETF atscale submissions across {len(runs)} runs "
          f"({runs[0][1]} .. {runs[-1][1]})\n")

    parse_fail = 0
    for r in rows:
        try:
            r["tree"] = sqlglot.parse_one(r["sql"])
        except Exception:
            r["tree"] = None
            parse_fail += 1
    print(f"parsed {len(rows)-parse_fail}/{len(rows)} submissions "
          f"({parse_fail} unparseable, excluded)\n")

    results = {}
    for bid, phrase, intro in BULLETS:
        det = DETECTORS[bid]
        floor = max(intro, ROLE_MAP_VALID_FROM) if bid in ROLE_DEPENDENT else intro
        elig = [r for r in rows if r["tree"] is not None and intro and r["date"] >= floor]
        app = viol = 0
        viol_rows = []
        for r in elig:
            ctx = dict(conds.get(r["task"], {}), sql=r["sql"])
            try:
                a, v, note = det(r["tree"], ctx)
            except Exception as e:                                # noqa: BLE001
                a, v, note = False, False, f"detector error: {e}"
            r.setdefault("verdicts", {})[bid] = (a, v, note)
            if a:
                app += 1
                if v:
                    viol += 1
                    viol_rows.append((r, note))
        results[bid] = {"intro": intro, "floor": floor, "eligible": len(elig), "applicable": app,
                        "violated": viol, "rows": viol_rows, "phrase": phrase}

    print(f"{'bullet':<24}{'added':<12}{'elig':>5}{'appl':>6}{'viol':>6}  rate     0-score correlation")
    print("-" * 96)
    for bid, phrase, _intro in BULLETS:
        d = results[bid]
        if not d["intro"]:
            print(f"{bid:<24}{'NOT FOUND':<12}{'':>5}{'':>6}{'':>6}  phrase not in git history")
            continue
        rd = " [roles]" if bid in ROLE_DEPENDENT else ""
        if d["applicable"] < 3:
            print(f"{bid:<24}{d['intro']:<12}{d['eligible']:>5}{d['applicable']:>6}"
                  f"{d['violated']:>6}  insufficient data (<3 applicable){rd}")
            continue
        rate = d["violated"] / d["applicable"]
        graded = [r for r, _ in d["rows"] if r["graded"]]
        zero = [r for r in graded if (r["reward"] or 0) == 0]
        corr = (f"{len(zero)}/{len(graded)} graded violations scored 0"
                if graded else "no graded violations")
        print(f"{bid:<24}{d['intro']:<12}{d['eligible']:>5}{d['applicable']:>6}"
              f"{d['violated']:>6}  {rate:6.1%}  {corr}{rd}")

    base_graded = [r for r in rows if r["graded"] and r["tree"] is not None]
    base_zero = sum(1 for r in base_graded if (r["reward"] or 0) == 0)
    print(f"\nbase rate: {base_zero}/{len(base_graded)} graded submissions scored 0 "
          f"({base_zero/len(base_graded):.1%})")

    # Outputs go to the CWD, not next to the script: writing them into scripts/ drops two
    # untracked artifacts into the repo every run.
    outdir = os.environ.get("COMPLIANCE_OUT", ".")
    json.dump({b: {k: v for k, v in d.items() if k != "rows"} for b, d in results.items()},
              open(f"{outdir}/compliance.json", "w"), indent=1)
    with open(f"{outdir}/violations.txt", "w") as fh:
        for bid, d in results.items():
            for r, note in d["rows"]:
                fh.write(f"[{bid}] {r['run']} {r['task']} graded={r['graded']} "
                         f"reward={r['reward']} :: {note}\n{r['sql']}\n\n")
    print(f"violation detail -> {outdir}/violations.txt")


if __name__ == "__main__":
    main()
