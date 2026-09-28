#!/usr/bin/env python3
"""Correct stale engine claims in the v12 model descriptions IN PLACE, without a rebuild.

The engine notes reach an agent as sentences inside each model's `description:` scalar,
put there at build time from utilities/birdsml/engine_notes.py. When a claim turns out
to be false - measured by scripts/engine_claims.py - the sentence has to change in the
deployed YAML, but regenerating 22 models to change a sentence is the expensive way to
do it, and a regenerate also reverts any hand edit the generator does not carry.

So this edits the sentence where it already sits. It rewrites only the matched text,
leaves the rest of the description untouched, and reports which models it changed. The
same wording must also be applied to engine_notes.py (and to any generator that inlines
its own copy) or the next real rebuild puts the false claim back.

  scripts/patch_engine_notes.py --dry-run     # what would change, per model
  scripts/patch_engine_notes.py               # apply
  scripts/patch_engine_notes.py --repo PATH   # default ~/go/src/github.com/diannewood/bird-models-v12

Baseline for every replacement below: engine ghcr.io/atscaleinc/engine:pr9967, probed
live 2026-09-28 by scripts/engine_claims.py. Do not add one without a probe.
"""
import argparse
import glob
import os
import re
import sys
import textwrap

DEFAULT_REPO = os.path.expanduser("~/go/src/github.com/diannewood/bird-models-v12")

# (label, old sentence as it reads in the description, new sentence, probe that settled it)
# Apostrophes are doubled here because the description is a single-quoted YAML scalar.
REPLACEMENTS = [
    ("sum-count-over-attribute",
     "SUM or COUNT over a dimension ATTRIBUTE returns one row per member carrying that member''s "
     "own value, with no aggregation and no error, and AVG over one is refused outright by the planner",
     "SUM or AVG over a dimension ATTRIBUTE is refused before the query is dispatched, with a message "
     "naming the workaround, while COUNT over an attribute aggregates correctly and agrees with "
     "COUNT(DISTINCT <key column>)",
     "count-over-attribute: COUNT(Fund Ticker) = COUNT(DISTINCT) = Fund Count per family"),

    ("nulls-order",
     "ORDER BY <col> DESC places NULLs FIRST, the reverse of Postgres and not overridable, so a "
     "top-N over a nullable column returns the unmeasured rows first unless the query also says "
     "that column IS NOT NULL.",
     "ORDER BY <col> DESC places NULLs FIRST and ASC places them LAST, which is what Postgres does, "
     "and an explicit NULLS FIRST or NULLS LAST is honoured, so a top-N over a nullable column "
     "writes DESC NULLS LAST or filters that column IS NOT NULL.",
     "nulls-order: bare DESC nulls first, NULLS LAST override honoured"),

    ("orderby-measure",
     "and sorting by a column the query neither projects nor groups by is refused outright with a "
     "message saying to add it to the select list",
     "and sorting by an ATTRIBUTE the query neither projects nor groups by is refused outright with "
     "a message saying to add it to the select list, while a published MEASURE can be sorted on "
     "without being projected",
     "orderby-unprojected-measure: accepted and correctly ordered"),

    ("window-filter",
     "A window column cannot be filtered in WHERE at any depth; select it in a FROM-subquery, "
     "GROUP BY the row key outside and filter it in HAVING.",
     "A window column is filtered by selecting it in a FROM-subquery and filtering its alias in the "
     "outer WHERE; filtering it in HAVING after a GROUP BY is refused as an incorrectly constructed "
     "constraint.",
     "window-filtered-in-subquery-where accepted; window-filtered-in-having refused"),

    ("union-branch-order",
     "a bare NULL literal in a branch must be typed, e.g. CAST(NULL AS VARCHAR), and the engine "
     "re-sorts the branches so their order cannot be restored.",
     "a NULL literal in a branch may be written as CAST(NULL AS VARCHAR) though a bare NULL is also "
     "accepted, and the branch order is preserved, so a listing followed by a one-row summary comes "
     "back in that order.",
     "union-untyped-null accepted; union-branch-order returns TOTAL last"),

    # exchange_traded_funds carries its own wording for two of the same facts.
    ("etf-ntile",
     "REGR_SLOPE, CORR, PERCENT_RANK and NTILE are not accepted.",
     "REGR_SLOPE, CORR and PERCENT_RANK are not accepted, though NTILE is.",
     "ntile: accepted (already corrected in engine_notes.py on 2026-09-27)"),

    ("etf-string-agg-order",
     "because STRING_AGG(x, '', '' ORDER BY x) is refused.",
     "and STRING_AGG(x, '', '' ORDER BY x) is accepted too.",
     "string-agg-order-by: accepted and ordered"),

    # archeology_scan was built before the shared block and carries its own wording.
    ("arch-ntile",
     "NTILE, PERCENTILE_CONT, COUNT(*) FILTER, CTEs, IN (subquery) and EXISTS are not accepted",
     "PERCENTILE_CONT, COUNT(*) FILTER, CTEs, IN (subquery) and EXISTS are not accepted, though "
     "NTILE is accepted",
     "ntile: accepted"),

    ("arch-sum-count",
     "SUM or COUNT over a dimension attribute returns one row per member carrying that member''s "
     "own value, with no aggregation and no error, and AVG over a dimension attribute is refused "
     "outright",
     "SUM or AVG over a dimension attribute is refused before the query is dispatched, while COUNT "
     "over an attribute aggregates correctly and agrees with COUNT(DISTINCT <key column>)",
     "count-over-attribute: aggregates correctly"),

    ("arch-nulls",
     "ORDER BY a column DESC places NULLS FIRST, the reverse of Postgres and not overridable, so a "
     "top-N over a nullable column returns the unmeasured rows first unless the query also says "
     "that column IS NOT NULL.",
     "ORDER BY a column DESC places NULLS FIRST and ASC places them LAST, which is what Postgres "
     "does, and an explicit NULLS FIRST or NULLS LAST is honoured, so a top-N over a nullable "
     "column writes DESC NULLS LAST or filters that column IS NOT NULL.",
     "nulls-order: override honoured"),
    ("etf-null-literal",
     "a bare NULL literal in a UNION branch is refused by the planner, so type it, e.g. "
     "CAST(NULL AS VARCHAR).",
     "a NULL literal in a UNION branch may be typed as CAST(NULL AS VARCHAR) though a bare NULL is "
     "also accepted, and the branch order is preserved.",
     "union-untyped-null accepted; union-branch-order returns TOTAL last"),

    ("etf-sum-count",
     "SUM or COUNT over a dimension ATTRIBUTE returns one row per member carrying that member''s "
     "own value, with no aggregation and no error, so a total names the published metric",
     "SUM or AVG over a dimension ATTRIBUTE is refused before the query is dispatched, while COUNT "
     "over an attribute aggregates correctly, so a total names the published metric",
     "count-over-attribute: aggregates correctly"),

    ("etf-nulls",
     "ORDER BY <col> DESC places NULLs FIRST on this engine, the reverse of Postgres and not "
     "overridable, so a top-N over a column that has nulls returns the unmeasured rows first unless "
     "the query also says that column IS NOT NULL.",
     "ORDER BY <col> DESC places NULLs FIRST and ASC places them LAST, which is what Postgres does, "
     "and an explicit NULLS FIRST or NULLS LAST is honoured, so a top-N over a column that has "
     "nulls writes DESC NULLS LAST or filters that column IS NOT NULL.",
     "nulls-order: override honoured"),
]

# Phrases that must not survive anywhere once the replacements above have run. A model
# that words a claim its own way is invisible to the replacements but shows up here.
STALE_PHRASES = [
    "reverse of Postgres",
    "not overridable",
    "cannot be filtered in WHERE",
    "re-sorts the branches",
    "must be typed",
    "refused by the planner, so type it",
    "and NTILE are not accepted",
    "ORDER BY x) is refused",
]


def flexible(text):
    """A regex matching `text` however the scalar wrapped and escaped it.

    Descriptions are emitted as single-quoted scalars in most models and double-quoted
    in others, so a line break arrives as indentation, as a backslash continuation, or
    both, and an apostrophe is written ' or ''. Matching on the words alone survives all
    of that; matching on the literal sentence only works for one of the two styles.
    """
    words = [re.escape(w.replace("''", "'")).replace("'", "(?:''|')") for w in text.split()]
    return re.compile(r"[\s\\]+".join(words))


def rewrap(new, indent="  ", width=100):
    return ("\n" + indent).join(textwrap.wrap(new, width=width - len(indent)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.repo, "*/models/*_v12.yml")))
    if not files:
        print(f"no model YAML under {args.repo}", file=sys.stderr)
        return 1

    totals = {label: 0 for label, *_ in REPLACEMENTS}
    for path in files:
        text = open(path).read()
        original, fired = text, []
        for label, old, new, _probe in REPLACEMENTS:
            text, n = flexible(old).subn(rewrap(new), text)
            if n:
                fired.append(f"{label}x{n}")
                totals[label] += n
        model = path.split("/")[-3]
        print(f"{model:36} {', '.join(fired) if fired else '-'}")
        if text != original and not args.dry_run:
            open(path, "w").write(text)

    print()
    for label, old, _new, probe in REPLACEMENTS:
        print(f"{totals[label]:3} models  {label:24} settled by {probe}")
    print()
    for phrase in STALE_PHRASES:
        left = [p.split("/")[-3] for p in files if phrase in open(p).read()]
        if left:
            print(f"STILL PRESENT: {phrase!r} in {', '.join(left)} - wording variant, add a replacement")

    missed = [l for l, n in totals.items() if n == 0]
    if missed:
        print(f"\nno match for: {', '.join(missed)} - already applied, or the wording "
              f"drifted; the audit above is the check that matters")
    if args.dry_run:
        print("\ndry run - nothing written")
    else:
        print("\nwritten. Next: the same wording in utilities/birdsml/engine_notes.py, "
              "then scripts/deploy_models_v12.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
