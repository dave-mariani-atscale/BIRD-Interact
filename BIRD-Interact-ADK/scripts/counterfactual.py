#!/usr/bin/env python3
"""Instrument 1: would obeying a guidance rule have moved each arm, and by how much?

Takes stored submissions from runs that PREDATE a rule, applies the rule as a
mechanical AST transform, and re-grades the transformed SQL offline. The
trajectory is held fixed, so the measurement is immune to every confound that
wrecks a before/after arm comparison - model redeploys, grading flags, max_tokens,
run-to-run variance.

WHY PER ARM: a tip appended to both arms' instructions can only move LIFT to the
extent the failure it fixes is asymmetric between them. If raw and atscale have
the same headroom under a rule, the rule is lift-neutral by construction and no
new run is needed to know that.

No LLM calls. Raw submissions execute against Postgres (ex_base); atscale
submissions dispatch through the same MCP run_query the arm uses and grade with
ex_base_external_pred. Free either way.

Transforms are AST-based via sqlglot, never regex over the SQL text: the
2026-08-13 detector round produced eight confident wrong answers from
pattern-matching (see scripts/guidance_compliance.py). Where a transform cannot
be made structurally it reports not-applicable rather than approximating.

Usage:
  python scripts/counterfactual.py [--rules B37,B38,B42,B41] [--runs f1,f2,...]
                                   [--limit N] [--verbose]

Default corpus: the pre-rule arm-paired runs on the three databases that have
both arms recorded (crypto_exchange, exchange_traded_funds, archeology_scan).
"""
import argparse, collections, functools, json, os, re, sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import sqlglot
from sqlglot import expressions as exp

from shared.config import settings
from shared import db_utils as U
from outbound_sql import client as mcp_client

# Arm-paired runs that predate f3ba423 (2026-08-17 14:54), so the agent was
# never told any of the four rules. Both arms, three databases.
DEFAULT_RUNS = [
    # crypto_exchange
    "results/crypto_n1_atscale_20260814_084450.json",
    "results/crypto_n1_raw_20260814_085602.json",
    # exchange_traded_funds
    "results/postb25_atscale_r1_20260813_165413.json",
    "results/postb25_raw_r1_20260813_174743.json",
    "results/postb25_atscale_r2_20260813_212403.json",
    "results/postb25_raw_r2_20260813_213412.json",
    "results/guidance0813_atscale_r1_20260813_095443.json",
    "results/guidance0813_raw_r1_20260813_100632.json",
    "results/rebase0811_atscale_r1.json",
    "results/rebase0811_raw_r1.json",
    "results/iter7_postmerge_atscale_20260811_084411.json",
    "results/iter7_postmerge_raw_20260811_085034.json",
    # archeology_scan
    "results/archeology_n1_atscale_20260812_094731.json",
    "results/archeology_n1_raw_20260812_095452.json",
    "results/archeology_n1_atscale_20260811_112847.json",
    "results/archeology_n1_raw_20260811_113830.json",
]

# Older ETF pair (2026-08-06), a different agent era. Off by default because its
# atscale SQL was written against an earlier deployed model, so dispatch errors
# there measure model drift rather than the rule. --runs-old adds it.
OLD_RUNS = [
    "results/etf_prompt_only_full_0806.json",
    "results/etf_raw_full_0806.json",
]


MODEL_SCHEMAS = ("bird_atscale_models_catalog_main", "bird_etf_prompt_only_main",
                 "bird_atscale_models_catalog")


@functools.lru_cache(maxsize=None)
def parse(sql):
    """Cached: the same gold is re-parsed for every submission of its task, and
    every transform copies the tree before mutating it."""
    try:
        return sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return None


def arm_of(sql):
    """Decide the arm from the SQL's own FROM target, not the filename."""
    return "atscale" if any(s in sql for s in MODEL_SCHEMAS) else "raw"


def outer_select(tree):
    """The top-level SELECT (the one whose rows are graded)."""
    if isinstance(tree, exp.Select):
        return tree
    if isinstance(tree, (exp.Subquery, exp.Paren)):
        return outer_select(tree.this)
    if isinstance(tree, (exp.Union, exp.Except, exp.Intersect)):
        return None              # set ops: leave alone
    if isinstance(tree, exp.With):
        return outer_select(tree.this)
    return tree.find(exp.Select)


def gold_of(td, phase):
    if phase == 1:
        sol, cond = td.get("sol_sql"), td.get("conditions") or {}
    else:
        fu = td.get("follow_up") or {}
        sol, cond = fu.get("sol_sql"), fu.get("conditions") or {}
    if isinstance(sol, str):
        sol = [sol]
    return sol, cond


# Each transform returns (new_sql, note), or (None, why-not) when its rule
# does not fire on this phase.
def t_b37(tree, gold_tree, gold_sql, td, phase):
    """B-37: the question named the entity, so return the value alone.

    Fires only where the rule itself fires: the question hands over a quoted
    entity AND gold returns a single column. Reduces the projection to one
    column, preferring a computed expression over a bare column reference (the
    identifier is what the rule says to drop). Using gold's ARITY is what makes
    this a ceiling measurement - the agent must infer the count from the
    question, which is exactly the claim B-37 makes.
    """
    sel = outer_select(tree)
    gsel = outer_select(gold_tree) if gold_tree is not None else None
    if sel is None or gsel is None:
        return None, "unparseable"
    if len(gsel.expressions) != 1:
        return None, f"gold returns {len(gsel.expressions)} columns, not 1"
    if len(sel.expressions) < 2:
        return None, "pred already returns one column"
    q = (td.get("amb_user_query") or "") if phase == 1 else ((td.get("follow_up") or {}).get("query") or "")
    if not re.search(r"'[A-Za-z0-9_\-]{3,}'", q):
        return None, "question names no quoted entity"

    def is_bare(e):
        inner = e.this if isinstance(e, exp.Alias) else e
        return isinstance(inner, (exp.Column, exp.Identifier))

    computed = [e for e in sel.expressions if not is_bare(e)]
    keep = computed[-1] if computed else sel.expressions[-1]
    new = tree.copy()
    outer_select(new).set("expressions", [keep.copy()])
    return new.sql(dialect="postgres"), \
        f"{len(sel.expressions)} cols -> 1 ({'computed' if computed else 'last'})"


def t_b38(tree, gold_tree, gold_sql, td, phase):
    """B-38: gold has no top-level ORDER BY, so strip the invented one."""
    gsel = outer_select(gold_tree) if gold_tree is not None else None
    if gsel is None:
        return None, "gold unparseable"
    if gold_tree.args.get("order") or gsel.args.get("order"):
        return None, "gold sorts too - rule does not fire"
    sel = outer_select(tree)
    if sel is None:
        return None, "pred unparseable"
    if not (tree.args.get("order") or sel.args.get("order")):
        return None, "pred has no top-level ORDER BY"
    new = tree.copy()
    new.set("order", None)
    ns = outer_select(new)
    if ns is not None:
        ns.set("order", None)
    return new.sql(dialect="postgres"), "stripped invented ORDER BY"


def t_b42(tree, gold_tree, gold_sql, td, phase):
    """B-42: gold groups AND sorts; add ORDER BY on the grouping keys."""
    gsel = outer_select(gold_tree) if gold_tree is not None else None
    if gsel is None:
        return None, "gold unparseable"
    if not gsel.args.get("group"):
        return None, "gold does not group"
    if not (gold_tree.args.get("order") or gsel.args.get("order")):
        return None, "gold groups but does not sort (B42 RISK case)"
    sel = outer_select(tree)
    if sel is None:
        return None, "pred unparseable"
    if tree.args.get("order") or sel.args.get("order"):
        return None, "pred already sorts"
    grp = sel.args.get("group")
    keys = list(grp.expressions) if grp else []
    if not keys:
        if not sel.expressions:
            return None, "pred has no projection to sort by"
        first = sel.expressions[0]
        keys = [exp.column(first.alias) if isinstance(first, exp.Alias) else first]
    new = tree.copy()
    outer_select(new).set(
        "order", exp.Order(expressions=[exp.Ordered(this=k.copy(), desc=False) for k in keys]))
    return new.sql(dialect="postgres"), f"added ORDER BY on {len(keys)} group key(s)"


LABELS = re.compile(r"THEN\s+'([^']*)'|ELSE\s+'([^']*)'", re.I)


def t_b41(tree, gold_tree, gold_sql, td, phase):
    """B-41: substitute gold's status labels into the predicted CASE.

    This is the ceiling of the ask, not the ask itself: it answers "if the agent
    had learned the wording, would the rest of the query have graded".
    """
    if gold_tree is None:
        return None, "gold unparseable"
    gsel = outer_select(gold_tree)
    gold_labels = [a or b for a, b in LABELS.findall(gold_sql)]
    if not gold_labels:
        return None, "gold projects no CASE labels"
    sel = outer_select(tree)
    if sel is None:
        return None, "pred unparseable"
    cases = [c for e in sel.expressions for c in e.find_all(exp.Case)]
    if not cases:
        return None, "pred projects no CASE"
    new = tree.copy()
    pred_lits = [l for e in outer_select(new).expressions
                 for c in e.find_all(exp.Case)
                 for l in c.find_all(exp.Literal) if l.is_string]
    if len(pred_lits) != len(gold_labels):
        return None, f"label count differs (pred {len(pred_lits)}, gold {len(gold_labels)})"
    for lit, want in zip(pred_lits, gold_labels):
        lit.set("this", want)
    return new.sql(dialect="postgres"), f"relabelled {len(gold_labels)} cell value(s)"


RULES = {"B37": t_b37, "B38": t_b38, "B42": t_b42, "B41": t_b41}


PHASE_RE = re.compile(r"[Pp]hase (\d)")


def submissions(path, tasks):
    """Yield every FAILED submission with the phase it was aimed at."""
    try:
        res = json.load(open(path))
    except Exception:
        return
    for r in res.get("results", []):
        iid = r.get("instance_id")
        td = tasks.get(iid)
        if not td:
            continue
        for t in r.get("tool_trajectory", []):
            if t.get("tool") != "submit_sql":
                continue
            args = t.get("args") or {}
            sql = args.get("sql") or args.get("query") or ""
            verdict = str(t.get("result") or "")
            if not sql.strip() or "failed" not in verdict.lower():
                continue          # only failures have headroom to recover
            m = PHASE_RE.search(verdict)
            phase = int(m.group(1)) if m else 1
            yield dict(run=os.path.basename(path), iid=iid, td=td, sql=sql, phase=phase)


def diagnose(arm, new_sql, pred, sol, db, conn, cond):
    """Shape-level description of a still-failing probe, via the grader's own
    diagnose_rows. Answers the question a bare zero cannot: was the rule
    irrelevant, or was it one of several things wrong at once?"""
    try:
        clean = lambda qs: U.remove_round(U.remove_distinct(U.remove_comments(list(qs))))
        gt, err, to, _ = U.execute_queries(clean(sol), db, conn)
        if err or to or not gt:
            return "gold did not execute"
        if arm == "raw":
            # both sides cleaned, matching grade_raw_submission
            pred, perr, pto, _ = U.execute_queries(clean([new_sql]), db, conn)
            if perr or pto:
                return f"pred errored: {str(perr)[:70]}"
        if not pred:
            return "pred returned no rows"
        dp = U.resolve_decimal_places(cond)
        return U.diagnose_rows(U.preprocess_results(pred, dp),
                               U.preprocess_results(gt, dp), cond, cell=U.canonical_cell)
    except Exception as e:
        return f"diagnose failed: {type(e).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default="B37,B38,B42,B41")
    ap.add_argument("--runs", default="")
    ap.add_argument("--limit", type=int, default=0, help="cap graded probes per rule/arm (0 = no cap)")
    ap.add_argument("--runs-old", action="store_true",
                    help="also include the 2026-08-06 ETF pair (different agent era)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--diagnose", action="store_true",
                    help="on a probe that still fails, say HOW its rows differ from gold — "
                         "separates 'rule useless' from 'rule necessary but not sufficient'")
    a = ap.parse_args()

    rules = [r.strip() for r in a.rules.split(",") if r.strip() in RULES]
    wanted = a.runs.split(",") if a.runs else (DEFAULT_RUNS + (OLD_RUNS if a.runs_old else []))
    runs = [r for r in wanted if os.path.exists(r)]

    tasks = {}
    for line in open(settings.data_path):
        d = json.loads(line)
        tasks[d["instance_id"]] = d

    cli = mcp_client()
    dbs, conns = {}, {}

    def scratch(dbname):
        if dbname not in dbs:
            dbs[dbname] = U.create_task_db(dbname, "cfact")
            conns[dbname] = U.get_connection_for_phase(dbs[dbname])
        return dbs[dbname], conns[dbname]

    print(f"corpus: {len(runs)} runs | rules: {','.join(rules)}")
    print(f"flags: tie={settings.grading_tie_tolerance} dec={settings.grading_honor_decimal} "
          f"casefold={settings.grading_casefold} rel={settings.grading_rel_tolerance} "
          f"lint={settings.grading_order_lint}\n")

    # (db, rule, arm) -> counters. The pooled table is this summed, so it is
    # derived at print time rather than incremented alongside.
    per_db = collections.defaultdict(collections.Counter)
    census = collections.Counter()

    def pooled(rule, arm):
        total = collections.Counter()
        for (_, r, m), c in per_db.items():
            if (r, m) == (rule, arm):
                total.update(c)
        return total

    seen = set()
    try:
        for path in runs:
            for s in submissions(path, tasks):
                sql, td, phase = s["sql"], s["td"], s["phase"]
                arm = arm_of(sql)
                dbname = td["selected_database"]
                census[(dbname, arm)] += 1
                tree = parse(sql)
                if tree is None:
                    continue
                sol, cond = gold_of(td, phase)
                if not sol:
                    continue
                gold_tree = parse(sol[-1])
                cond = U.apply_order_lint(cond, s["iid"], phase)

                for rule in rules:
                    new_sql, note = RULES[rule](tree, gold_tree, sol[-1], td, phase)
                    if new_sql is None:
                        continue
                    D = per_db[(dbname, rule, arm)]
                    D["elig"] += 1
                    key = (rule, arm, s["iid"], phase, new_sql)
                    if key in seen:
                        D["dedup"] += 1
                        continue      # same transform reached twice = same evidence
                    seen.add(key)
                    if a.limit and pooled(rule, arm)["graded"] >= a.limit:
                        D["capped"] += 1
                        continue

                    db, conn = scratch(dbname)
                    try:
                        if arm == "raw":
                            # grade_raw_submission, never ex_base: ex_base does
                            # none of step 1's cleanup, so gold keeps its ROUND()
                            # while the prediction loses its own and the two are
                            # compared at different precisions. Its docstring
                            # names two offline tools that already walked into
                            # this; a counterfactual that grades differently from
                            # the run it replays measures the grader.
                            verdict = U.grade_raw_submission([new_sql], sol, db, conn, cond)
                            pred = None
                        else:
                            txt = cli.call_tool("run_query", {"query": new_sql})
                            pred = U.parse_semantic_layer_rows(str(txt)) or None
                            verdict = 0 if pred is None else \
                                U.ex_base_external_pred(pred, sol, db, conn, cond)
                    except Exception as e:
                        if a.verbose:
                            print(f"  [{rule}/{arm}] {s['iid']} p{phase} ERR "
                                  f"{type(e).__name__}: {str(e)[:90]}")
                        D["graded"] += 1
                        D["err"] += 1
                        continue
                    D["graded"] += 1
                    if verdict:
                        D["recovered"] += 1
                        D["gain"] += 0.7 if phase == 1 else 0.3
                        print(f"  RECOVERED [{rule}/{arm}] {s['iid']} p{phase} ({note}) — {s['run']}")
                    elif a.diagnose:
                        print(f"  no  [{rule}/{arm}] {s['iid']} p{phase} ({note}) "
                              f"— {diagnose(arm, new_sql, pred, sol, db, conn, cond)}")
                    elif a.verbose:
                        print(f"  no  [{rule}/{arm}] {s['iid']} p{phase} ({note})")
    finally:
        for db in dbs.values():
            U.drop_task_db(db)

    print("\ncorpus census (failed submissions by database and arm):")
    for (d, arm), n in sorted(census.items()):
        print(f"  {d:<26}{arm:<9}{n:>4}")

    def table(title, getter):
        print(f"\n{title}")
        print(f"{'rule':<6}{'arm':<9}{'eligible':>9}{'dupes':>7}{'graded':>7}{'err':>5}"
              f"{'recovered':>10}{'reward':>8}{'capped':>8}")
        for rule in rules:
            for arm in ("raw", "atscale"):
                c = getter(rule, arm)
                if not c:
                    continue
                print(f"{rule:<6}{arm:<9}{c['elig']:>9}{c['dedup']:>7}{c['graded']:>7}{c['err']:>5}"
                      f"{c['recovered']:>10}{c['gain']:>8.2f}{c['capped']:>8}")

    def direction(r, s_):
        """A rule only moves lift to the extent its recovered reward is
        ASYMMETRIC between the arms. Equal columns = lift-neutral."""
        if abs(r - s_) < 0.35:
            return "lift-neutral"
        return "SHRINKS lift (helps raw more)" if r > s_ else "GROWS lift (helps atscale more)"

    def verdicts(indent, getter):
        for rule in rules:
            raw, ats = getter(rule, "raw"), getter(rule, "atscale")
            r, s_ = raw["gain"], ats["gain"]
            if not (r or s_):
                print(f"{indent}{rule}: no recovery either arm "
                      f"(eligible raw {raw['elig']}, atscale {ats['elig']})")
            else:
                print(f"{indent}{rule}: raw {r:+.2f} vs atscale {s_:+.2f}  ->  {direction(r, s_)}")

    table("POOLED, all databases", pooled)
    for d in sorted({k[0] for k in per_db}):
        # .get, not per_db[...]: a defaultdict lookup would create the missing
        # cell and it would then show up in the pooled sum.
        def by_db(rule, arm, d=d):
            return per_db.get((d, rule, arm)) or collections.Counter()

        table(f"PER DATABASE: {d}", by_db)
        print("  lift direction here:")
        verdicts("    ", by_db)
    print("\nPOOLED lift reading: a rule only moves atscale-vs-raw lift to the extent its")
    print("recovered reward is ASYMMETRIC between the two arms. Equal columns = lift-neutral.")
    verdicts("  ", pooled)


if __name__ == "__main__":
    main()
