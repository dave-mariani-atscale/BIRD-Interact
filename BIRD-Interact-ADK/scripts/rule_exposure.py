#!/usr/bin/env python3
"""Instrument 2: how much of each database's gold does a guidance rule touch?

scripts/counterfactual.py measures what a rule RECOVERS, but only on the three
databases that have arm-paired runs. This measures a rule's EXPOSURE — how many
graded phases its precondition fires on — from gold alone, so it covers all 22
databases with no run and no LLM call.

Exposure is an upper bound on effect, not an effect. A rule can be exposed on 20
phases and recover none. What exposure IS good for is the opposite direction: a
rule exposed on 0 phases in a database cannot move that database's lift, and a
rule whose RISK count is non-zero can lose points there.

Per rule, per database:
  fires  phases where obeying the rule is what gold wants
  risk   phases where obeying it makes a correct answer wrong

Both arms see identical gold, so exposure is arm-blind by construction. What the
recovery numbers mean per arm is counterfactual.py's docstring.
"""
import json, os, re, sys, collections

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import counterfactual as C          # parse/outer_select/gold_of/LABELS, and chdir to root

from shared.config import settings
from shared import db_utils as U
from sqlglot import expressions as exp

QUOTED = re.compile(r"'[A-Za-z0-9_\-]{3,}'")


def _name(e):
    e = e.this if isinstance(e, exp.Alias) else e
    return e.name.lower() if isinstance(e, exp.Column) else None


def filtered_and_projected(sel) -> bool:
    """True when gold equality-filters a column against a string literal and
    then projects that same column."""
    where = sel.args.get("where")
    if where is None:
        return False
    keys = set()
    for eq in where.find_all(exp.EQ):
        for a, b in ((eq.this, eq.expression), (eq.expression, eq.this)):
            if isinstance(a, exp.Column) and isinstance(b, exp.Literal) and b.is_string:
                keys.add(a.name.lower())
    if not keys:
        return False
    return any(_name(e) in keys for e in sel.expressions)

rows = collections.defaultdict(collections.Counter)

for line in open(settings.data_path):
    td = json.loads(line)
    db = td["selected_database"]
    for phase in (1, 2):
        sol, cond = C.gold_of(td, phase)
        if not sol:
            continue
        cond = U.apply_order_lint(cond, td["instance_id"], phase)
        R = rows[db]
        t = C.parse(sol[-1])
        sel = C.outer_select(t) if t is not None else None
        if sel is None:
            R["unparseable"] += 1
            continue
        R["phases"] += 1
        ordered = bool(cond.get("order"))
        sorts = bool(t.args.get("order") or sel.args.get("order"))
        groups = bool(sel.args.get("group"))
        if ordered:
            R["ordered"] += 1

        # B-37: question hands over the entity, gold returns the value alone
        q = (td.get("amb_user_query") or "") if phase == 1 \
            else ((td.get("follow_up") or {}).get("query") or "")
        named = bool(QUOTED.search(q))
        if named and len(sel.expressions) == 1:
            R["B37_fires"] += 1
        # The sharp counter-case, and the reason to measure it separately: the
        # question names an entity AND gold projects the very column it filtered
        # that entity on. There B-37's "the identifier is NOT part of the answer"
        # is false and obeying it drops a required column. A gold that merely
        # returns 2+ columns is NOT a counter-case - it may project two values
        # and no identifier - so counting arity alone overstates the risk.
        if named and len(sel.expressions) > 1 and filtered_and_projected(sel):
            R["B37_risk"] += 1

        # B-38: order graded, gold does not sort -> an invented sort is fatal
        if ordered and not sorts:
            R["B38_fires"] += 1

        # B-42: order graded and gold groups -> sorted = must sort, unsorted = risk
        if ordered and groups:
            R["B42_fires" if sorts else "B42_risk"] += 1

        # B-41: gold prints chosen label text, so the wording is the user's
        if [a or b for a, b in C.LABELS.findall(sel.sql(dialect="postgres"))]:
            R["B41_fires"] += 1

COLS = ["phases", "ordered", "B37_fires", "B37_risk", "B38_fires",
        "B42_fires", "B42_risk", "B41_fires"]
print(f"{'database':<38}" + "".join(f"{c:>11}" for c in COLS))
tot = collections.Counter()
for db in sorted(rows, key=lambda d: -rows[d]["phases"]):
    R = rows[db]
    tot.update(R)
    print(f"{db:<38}" + "".join(f"{R[c]:>11}" for c in COLS))
print(f"{'TOTAL':<38}" + "".join(f"{tot[c]:>11}" for c in COLS))
if tot["unparseable"]:
    print(f"\n{tot['unparseable']} gold phases unparseable by sqlglot, excluded.")
