#!/usr/bin/env python3
"""Diff a graded submission against gold and report WHAT DIFFERS. Gold SQL never leaves here.

This is Method step 2 ("diff against gold at value level") as a tool, so that the
session doing the diagnosis never reads the answer key's SQL. It pulls the submission
the grader actually scored, re-executes it LIVE (so it reflects the model as it is
now, not as it was during the run), executes gold against `<db>_template`, and
returns a description of the difference: row count, column count and order, values,
row order, rounding.

Why live re-execution is the point: a model fix is proved *sufficient* for $0 by
taking the agent's own stored submission, running it against the fixed model, and
diffing it against gold. If the rows now match, the fix is sufficient; if they do
not, the run would have been wasted. No LLM calls, no benchmark tokens.

    PYTHONPATH=. .venv-adk/bin/python scripts/gold_diff.py \
        --results results/<run>.json exchange_traded_funds_7 exchange_traded_funds_9

    # a candidate query, with no run to pull it from
    PYTHONPATH=. .venv-adk/bin/python scripts/gold_diff.py \
        --task exchange_traded_funds_7 --sql "SELECT ..."

    # a whole ceiling-sweep round in one call: {instance_id: sql} or
    # {instance_id: {"sql": ..., "phase": 2}}; prints ONE line per task and writes the
    # full reports to <queries>.report.txt, so a 20-task round costs one screen
    PYTHONPATH=. .venv-adk/bin/python scripts/gold_diff.py --sweep round1.json

WHAT IT WILL NOT PRINT: gold SQL, in any form — not the text, not a fragment, not a
paraphrase of its construction. Column labels and a capped sample of differing cell
VALUES are printed, because a value diff is not a value diff without them, and the
protocol already allows gold to be read to diagnose. Those are diagnosis only:
nothing seen here may be built into the model, the guidance, or the code.

The verdict line is the real grader's (`ex_base_external_pred` / `grade_raw_submission`
on `<db>_template`), not a reimplementation, so it cannot drift from what a run would
score. The finding below it is this script's own analysis of the same two row sets.

Management-category tasks are refused: their phase 2 needs the phase-1 write state,
which does not exist offline.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from shared.config import settings                                          # noqa: E402
from shared.db_utils import (                                               # noqa: E402
    canonical_cell, effective_conditions, execute_queries,
    ex_base_external_pred, get_connection_for_phase, grade_raw_submission,
    parse_semantic_layer_rows, preprocess_results,
    remove_comments, remove_distinct, remove_round, _as_number, _values_close,
)
from db_environment.server import _run_query_via_semantic_layer            # noqa: E402

MAX_SAMPLES = 3


# ---------------------------------------------------------------- inputs

def load_tasks():
    tasks = {}
    with open(settings.data_path) as f:
        for line in f:
            d = json.loads(line)
            tasks[d["instance_id"]] = d
    return tasks


def graded_submission(trajectory, phase):
    """(index, sql) of the submission the grader scored for `phase`, or None.

    The LAST entry carrying an `sql` key for that phase, not the first: a phase can
    be submitted several times, and the first attempt is usually the one that failed.
    Phase advances on the environment's own "Phase 1 correct" verdict rather than on
    a count of submissions, or a second phase-1 attempt is read as phase 2.
    """
    current, found = 1, None
    for i, entry in enumerate(trajectory or []):
        sql = (entry.get("args") or {}).get("sql")
        if sql:
            if current == phase:
                found = (i, sql)
        if "Phase 1 correct" in str(entry.get("result", "")):
            current = 2
    return found


def task_phase(task, phase):
    """(gold_sqls, conditions, category, question_text) for a phase — mirrors
    db_environment/server.py's own selection so the grading inputs are identical."""
    if phase == 2:
        fu = task.get("follow_up") or {}
        sol, cond = fu.get("sol_sql", []), fu.get("conditions", {})
        cat, q = fu.get("category", "Query"), fu.get("query", "")
    else:
        sol, cond = task.get("sol_sql", []), task.get("conditions", {})
        cat, q = task.get("category", "Query"), task.get("amb_user_query") or task.get("query", "")
    if isinstance(sol, str):
        sol = [sol]
    return list(sol or []), effective_conditions(cond, q), cat, q


# ---------------------------------------------------------------- execution

def semantic_layer_columns(result_text):
    """Column labels from a run_query response, in projection order."""
    for line in (result_text or "").splitlines():
        line = line.strip()
        if line.startswith("["):
            try:
                rows = json.loads(line)
            except Exception:                                               # noqa: BLE001
                continue
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                return list(rows[0].keys())
    return []


def run_prediction(sql, backend, db_template, conn):
    """(rows, columns, error) for the submission, executed live."""
    if backend == "raw":
        cleaned = remove_round(remove_distinct(remove_comments([sql])))
        rows, err, timed_out, desc = execute_queries(cleaned, db_template, conn)
        if timed_out:
            return None, [], "timed out after 60s"
        if err:
            return None, [], err
        return rows or [], [d[0] for d in (desc or [])], None
    text = _run_query_via_semantic_layer(sql)
    if text.startswith("Error"):
        return None, [], text
    return parse_semantic_layer_rows(text), semantic_layer_columns(text), None


def run_gold(sol_sqls, backend, db_template, conn):
    """(rows, columns, error) for gold, executed against the template database.

    Cleaned exactly as the grading path for this backend cleans it, so the rows
    described here are the rows the verdict was reached on.
    """
    cleaned = (remove_round(remove_distinct(remove_comments(list(sol_sqls))))
               if backend == "raw" else remove_round(remove_comments(list(sol_sqls))))
    rows, err, timed_out, desc = execute_queries(cleaned, db_template, conn)
    if timed_out:
        return None, [], "gold timed out after 60s"
    if err:
        # Postgres quotes the offending statement back in a `LINE n:` block, which for
        # this query is gold itself. Keep the reason, drop the echo - the one place
        # gold SQL could escape this tool.
        return None, [], f"gold failed to execute: {err.splitlines()[0].split('LINE ')[0].strip()}"
    return rows or [], [d[0] for d in (desc or [])], None


# ---------------------------------------------------------------- comparison

def canon(rows, decimals=2):
    """Rows as comparable strings, rounded the way grading rounds them."""
    return [tuple(canonical_cell(c) for c in r)
            for r in preprocess_results(list(rows or []), decimals)]


def width(rows):
    return max((len(r) for r in rows), default=0)


def column_permutation(pred, gold, pw):
    """A non-identity mapping pred column -> gold column that matches every column
    as a multiset, or None. Catches the projection written in the wrong order,
    which otherwise reads as "every value is wrong"."""
    if pw < 2 or pw > 8 or not pred or len(pred) != len(gold):
        return None
    pcols = [Counter(r[i] for r in pred) for i in range(pw)]
    gcols = [Counter(r[i] for r in gold) for i in range(pw)]
    for perm in itertools.permutations(range(pw)):
        if perm != tuple(range(pw)) and all(pcols[i] == gcols[perm[i]] for i in range(pw)):
            return perm
    return None


def classify_cell(p, g, p_raw, g_raw):
    """Why one cell differs, in the vocabulary the fix depends on."""
    if p.strip().lower() == g.strip().lower():
        return "case only"
    try:
        pf, gf = float(p), float(g)
    except (TypeError, ValueError):
        return "different value" if not _values_close(p_raw, g_raw) else "rounding/precision"
    # The grader's own 1e-6 tolerance is far tighter than the 2dp both sides were
    # rounded to, so it never names the commonest precision defect: two values that
    # agree to within the last graded digit and land either side of a boundary.
    if _values_close(p_raw, g_raw) or abs(pf - gf) <= 0.01 + 1e-9:
        return "rounding/precision"
    if gf and pf:
        ratio = pf / gf
        for factor, name in ((100.0, "100x"), (0.01, "1/100"), (1000.0, "1000x"),
                             (0.001, "1/1000"), (2.0, "2x"), (0.5, "1/2")):
            if abs(ratio - factor) < 0.005 * max(1.0, abs(factor)):
                return f"predicted is {name} expected"
    return "different number"


def key_indices(gold, pw):
    """The leading run of columns that gold never returns as a number.

    Only a LEADING run counts: those are the grouping keys, the thing that says
    which entity a row is about. A measure formatted as text ('7.96%') is
    non-numeric too, and treating one as a key turned a two-row measure mismatch
    into a confident "different entities" claim.
    """
    idx = []
    for i in range(pw):
        if all(_as_number(r[i]) is None for r in gold[:200]):
            idx.append(i)
        else:
            break
    return idx


def key_column_note(pred, gold, pcols, pw):
    """Whether the non-numeric (grouping) columns agree when the rows do not.

    A row-count difference reads the same whether the submission grouped the right
    entities and computed the wrong measures or listed different entities entirely,
    and the fix is in a different layer in each case. Comparing the non-numeric
    columns alone separates them in one line.
    """
    idx = key_indices(gold, pw)
    if not idx or len(idx) == pw:
        return []
    kp = Counter(tuple(r[i] for i in idx) for r in pred)
    kg = Counter(tuple(r[i] for i in idx) for r in gold)
    shared = sum((kp & kg).values())
    labels = [pcols[i] if i < len(pcols) else f"col {i + 1}" for i in idx]
    if shared >= 0.9 * len(gold):
        return [f"  but the non-numeric columns {labels} match on {shared} of {len(gold)} "
                "rows: the entities are right and the measure or the row filter is not."]
    return [f"  the non-numeric columns {labels} match on only {shared} of {len(gold)} "
            "rows: these are different entities, so look at the join and the grain."]


def describe(pred, gold, pred_raw, gold_raw, pcols, gcols, conditions):
    """The finding: a list of lines, most load-bearing first."""
    out = []
    ordered = bool(conditions.get("order"))
    pw, gw = width(pred), width(gold)
    out.append(f"shape: predicted {len(pred)} rows x {pw} cols, "
               f"expected {len(gold)} rows x {gw} cols")
    if pcols:
        out.append(f"predicted columns: {pcols}")
    if gcols:
        out.append(f"expected columns:  {gcols}")

    if not pred:
        out.append("FINDING: EMPTY RESULT — the submission returned no rows at all, "
                   f"where {len(gold)} are expected. Read the dispatched SQL before "
                   "theorising about the filter.")
        return out

    if pw != gw:
        out.append(f"FINDING: COLUMN COUNT — predicted {pw} columns, expected {gw}. "
                   "Nothing else can be compared until the projection matches.")
        return out

    perm = column_permutation(pred, gold, pw)
    if perm:
        out.append(f"FINDING: COLUMN ORDER — the values are right but projected in the "
                   f"wrong order. Predicted column i belongs at position {list(perm)}.")
        return out

    if Counter(pred) == Counter(gold):
        if pred == gold:
            out.append("FINDING: MATCH — every cell is identical, in the same order.")
        elif ordered:
            first = next(i for i, (a, b) in enumerate(zip(pred, gold)) if a != b)
            out.append(f"FINDING: ROW ORDER — identical rows, different order, first "
                       f"differing at row {first + 1}. This task is graded ordered "
                       "(the question asks for one), so the ORDER BY is the whole defect.")
        else:
            out.append("FINDING: MATCH — same rows in a different order, and order is "
                       "not graded for this question, so the submission is correct.")
        return out

    if len(pred) != len(gold):
        extra = Counter(pred) - Counter(gold)
        missing = Counter(gold) - Counter(pred)
        shared = sum((Counter(pred) & Counter(gold)).values())
        out.append(f"FINDING: ROW COUNT — predicted {len(pred)}, expected {len(gold)}; "
                   f"{shared} rows are common, {sum(missing.values())} expected rows are "
                   f"missing and {sum(extra.values())} predicted rows do not belong.")
        if not extra:
            out.append("  every predicted row is a correct row: the submission is too "
                       "narrow (a filter, a join, or a LIMIT drops rows).")
        elif not missing:
            out.append("  every expected row is present: the submission is too broad "
                       "(a missing filter, or a grain finer than the question's).")
        else:
            out.append("  rows are wrong in both directions: suspect the grain or the "
                       "join before the filter.")
        out += key_column_note(pred, gold, pcols, pw)
        return out

    # Same shape, same count, different content: locate it per column.
    p_sorted, g_sorted = (pred, gold) if ordered else (sorted(pred), sorted(gold))
    pr_sorted, gr_sorted = ((pred_raw, gold_raw) if ordered
                            else (sorted(pred_raw), sorted(gold_raw)))
    per_col = Counter()
    kinds = {}
    samples = []
    for r, (prow, grow) in enumerate(zip(p_sorted, g_sorted)):
        praw = pr_sorted[r] if r < len(pr_sorted) else prow
        graw = gr_sorted[r] if r < len(gr_sorted) else grow
        for c, (p, g) in enumerate(zip(prow, grow)):
            if p == g:
                continue
            per_col[c] += 1
            kind = classify_cell(p, g, praw[c] if c < len(praw) else p,
                                 graw[c] if c < len(graw) else g)
            kinds.setdefault(c, Counter())[kind] += 1
            if len(samples) < MAX_SAMPLES:
                label = pcols[c] if c < len(pcols) else f"col {c + 1}"
                samples.append(f"  row {r + 1} [{label}]: predicted {p!r}, "
                               f"expected {g!r}  ({kind})")

    if not per_col:
        out.append("FINDING: ROW ORDER — the same rows in a different order, and the "
                   "task is graded unordered, so this should have passed. Re-check the "
                   "verdict line above before acting on it.")
        return out

    everything = sum(per_col.values())
    only_rounding = all(k.most_common(1)[0][0] == "rounding/precision" for k in kinds.values())
    head = "VALUES ROUNDING" if only_rounding else "VALUES"
    out.append(f"FINDING: {head} — same row count ({len(pred)}) and {pw} columns, "
               f"{everything} cells differ" + ("" if ordered else " (rows aligned by sorting, "
                                               "since order is not graded)") + ".")
    for c, n in per_col.most_common():
        label = pcols[c] if c < len(pcols) else f"col {c + 1}"
        why = ", ".join(f"{kind} x{cnt}" for kind, cnt in kinds[c].most_common(3))
        out.append(f"  column {c + 1} [{label}]: {n}/{len(pred)} rows differ — {why}")
    # A key-shaped column differing in nearly every row means these are different
    # entities, which is a filter or grain defect — not the arithmetic defect the
    # differing measure columns beside it otherwise look like.
    keys = key_indices(gold, pw)
    if len(pred) >= 5 and len(keys) < pw and any(
            per_col[c] >= 0.9 * len(pred) for c in keys):
        out.append("  a non-numeric column differs in nearly every row: these are "
                   "DIFFERENT ENTITIES, not the same entities with wrong measures. "
                   "Look at the filter and the grain before the arithmetic.")
    if only_rounding:
        out.append("  every difference is precision: this is a ROUND/CAST defect, not a "
                   "wrong answer.")
    out.extend(samples)
    return out


# ---------------------------------------------------------------- driver

def report(instance_id, task, phase, sql, submission_note, backend):
    db = task.get("selected_database") or task.get("database")
    db_template = f"{db}_template"
    sol_sqls, conditions, category, _q = task_phase(task, phase)

    lines = [f"=== {instance_id}  phase {phase}  backend={backend}  db={db} ==="]
    if submission_note:
        lines.append(submission_note)
    if category != "Query":
        lines.append(f"REFUSED: category {category}. Phase 2 of a Management task needs the "
                     "phase-1 write state, which does not exist offline.")
        return "\n".join(lines)
    if not sol_sqls:
        lines.append("REFUSED: this task file carries no gold for that phase. Merge the "
                     "ground truth first (scripts/combine_public_with_gt.py).")
        return "\n".join(lines)

    conn = get_connection_for_phase(db_template)
    pred_rows, pcols, pred_err = run_prediction(sql, backend, db_template, conn)
    if pred_err:
        lines.append(f"FINDING: EXECUTION ERROR — the submission does not run against the "
                     f"model as it stands now:\n  {pred_err[:600]}")
        return "\n".join(lines)
    gold_rows, gcols, gold_err = run_gold(sol_sqls, backend, db_template, conn)
    if gold_err:
        lines.append(f"HARNESS PROBLEM: {gold_err[:400]}")
        return "\n".join(lines)

    if backend == "raw":
        verdict = grade_raw_submission([sql], sol_sqls, db_template, conn, conditions)
    else:
        verdict = ex_base_external_pred(pred_rows, sol_sqls, db_template, conn, conditions)
    lines.append(f"grader verdict: {'PASS' if verdict else 'FAIL'}"
                 f"   (order graded: {bool(conditions.get('order'))}"
                 + (", relaxed: the question carries no ordering cue"
                    if conditions.get("order_relaxed_no_cue") else "") + ")")
    lines += describe(canon(pred_rows), canon(gold_rows),
                      canon(pred_rows, 12), canon(gold_rows, 12),
                      pcols, gcols, conditions)
    return "\n".join(lines)


def sweep(path, default_phase, backend, tasks):
    """One line per task; full reports go to <path>.report.txt, not to the screen."""
    spec = json.load(open(path))
    if isinstance(spec, list):                       # [[label, task, sql], ...] also accepted
        spec = {row[-2]: {"sql": row[-1], "label": row[0]} for row in spec}
    out_path = path + ".report.txt"
    full, table = [], []
    for iid, q in spec.items():
        sql = q["sql"] if isinstance(q, dict) else q
        phase = q.get("phase", default_phase) if isinstance(q, dict) else default_phase
        task = tasks.get(iid)
        if not task:
            rep = f"=== {iid} ===\nREFUSED: not in {settings.data_path}"
        else:
            rep = report(iid, task, phase, sql, "submission: from --sweep file", backend)
        full.append(rep + "\n")
        verdict = next((l.split(":", 1)[1].split()[0] for l in rep.splitlines()
                        if l.startswith("grader verdict:")), "—")
        shape = next((l.replace("shape: ", "").replace("predicted ", "").replace(", expected ", " vs ")
                      for l in rep.splitlines() if l.startswith("shape:")), "")
        finding = next((l for l in rep.splitlines() if l.startswith("FINDING:")
                        or l.startswith("REFUSED:") or l.startswith("HARNESS")), "")
        table.append(f"{iid} | P{phase} | {verdict} | {shape} | {finding[:110]}")
    open(out_path, "w").write("\n".join(full))
    print(f"task | phase | verdict | shape (pred vs gold) | finding      full reports: {out_path}")
    print("\n".join(table))
    n_pass = sum(1 for r in table if "| PASS |" in r)
    print(f"{n_pass}/{len(table)} PASS")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("instance_ids", nargs="*", help="tasks to diff")
    ap.add_argument("--results", help="run results JSON to pull the graded submission from")
    ap.add_argument("--task", help="single instance_id, for use with --sql")
    ap.add_argument("--sql", help="query to diff instead of a stored submission")
    ap.add_argument("--phase", type=int, default=1, choices=(1, 2))
    ap.add_argument("--backend", choices=("atscale", "raw"),
                    help="default: the results file's backend, else atscale")
    ap.add_argument("--sweep", metavar="QUERIES_JSON",
                    help="grade every {instance_id: sql} in the file; one line per task")
    a = ap.parse_args()

    if a.sweep:
        print("Gold SQL is not printed by this tool, ever; sampled values are DIAGNOSIS ONLY.\n")
        sweep(a.sweep, a.phase, a.backend or "atscale", load_tasks())
        return 0
    ids = list(a.instance_ids) + ([a.task] if a.task else [])
    if not ids:
        ap.error("name at least one instance_id")
    if a.sql and len(ids) != 1:
        ap.error("--sql applies to exactly one task")
    if not a.sql and not a.results:
        ap.error("give --results (to pull the graded submission) or --sql")

    tasks = load_tasks()
    run = json.load(open(a.results)) if a.results else {}
    backend = a.backend or run.get("backend") or "atscale"
    by_id = {r["instance_id"]: r for r in run.get("results", [])}

    print("Gold SQL is not printed by this tool, ever. Column labels and the sampled "
          "values below are for DIAGNOSIS ONLY — nothing here may be built into the "
          "model, the guidance, or the code.\n")

    for iid in ids:
        task = tasks.get(iid)
        if not task:
            print(f"=== {iid} ===\nREFUSED: not in {settings.data_path}\n")
            continue
        if a.sql:
            sql, note = a.sql, "submission: supplied on the command line"
        else:
            row = by_id.get(iid)
            if not row:
                print(f"=== {iid} ===\nREFUSED: not in {a.results}\n")
                continue
            found = graded_submission(row.get("tool_trajectory"), a.phase)
            if not found:
                print(f"=== {iid} ===\nREFUSED: no phase-{a.phase} submission in the "
                      "trajectory — the agent never submitted.\n")
                continue
            i, sql = found
            note = (f"submission: trajectory entry {i + 1} of "
                    f"{len(row['tool_trajectory'])}, the last one for phase {a.phase}")
        print(report(iid, task, a.phase, sql, note, backend))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
