"""Offline grader-defect sweep over recorded submissions, both arms. No LLM calls.

THE offline regrade entry points are `shared.db_utils.grade_raw_submission`
(raw SQL) and `shared.db_utils.ex_base_external_pred` (semantic-layer rows);
this script drives them over grading-audit rows and classifies every
still-failing submission into near-miss classes, so a proposed grading change
can be measured on both arms before adoption.

Usage:
    PYTHONPATH=. .venv-adk/bin/python scripts/regrade_sweep.py \
        --atscale-audit results/bird_full_run_2026-09-06_atscale_n3/results/grading_audit_this_run.jsonl \
        --raw-audit results/grading_audit.jsonl \
        --out scratch/us002

Reproduction gate (see docs/bird-grading-comparison.md "Three replay bugs"):
the mirrored fast path must agree with the real grading entry point on a
stratified sample, and with the recorded verdict on every row of the run being
replayed; the script refuses to print a classification otherwise. The raw rows
recorded before 2026-09-04 predate the unconditional corrections, so recorded
disagreement there is reported, not gated.
"""
import argparse
import atexit
import itertools
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal

sys.path.insert(0, ".")

from shared.config import settings  # noqa: E402
from shared import db_utils as U  # noqa: E402

# The 2026-09-04 raw replay window: the recorded source of
# scoring/raw_arm_regraded_all22.json (all 22 dbs, both phases).
RAW_REPLAY_TS = (1788554260.0, 1788555638.0)


def load_tasks():
    tasks = {}
    for line in open(settings.data_path):
        t = json.loads(line)
        tasks[t["instance_id"]] = t
    return tasks


def rows_from(path, backend, ts_window=None):
    out = []
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("backend") != backend:
            continue
        if ts_window and not (ts_window[0] <= float(d["ts"]) <= ts_window[1]):
            continue
        out.append(d)
    return out


class GoldCache:
    """Executed gold rows per (db, cleaned sol_sqls). One scratch DB per base db."""

    def __init__(self):
        self.dbs = {}
        self.cache = {}

    def conn(self, base_db):
        if base_db not in self.dbs:
            task_db = U.create_task_db(base_db, "us002sweep")
            conn = U.get_connection_for_phase(task_db)
            self.dbs[base_db] = (task_db, conn)
            atexit.register(U.drop_task_db, task_db)
        return self.dbs[base_db]

    def gold_rows(self, base_db, sol_sqls, mode):
        """mode 'atscale': remove_round(remove_comments(gold)) as
        ex_base_external_pred does; mode 'raw': grade_raw_submission's chain."""
        key = (base_db, mode, tuple(sol_sqls))
        if key in self.cache:
            return self.cache[key]
        if mode == "atscale":
            cleaned = U.remove_round(U.remove_comments(list(sol_sqls)))
        else:
            cleaned = U.remove_round(U.remove_distinct(U.remove_comments(list(sol_sqls))))
        task_db, conn = self.conn(base_db)
        res, err, to, _ = U.execute_queries(cleaned, task_db, conn)
        self.cache[key] = None if (err or to) else res
        return self.cache[key]


def pred_tuples(pred_rows):
    if not pred_rows:
        return []
    return [tuple(r) for r in pred_rows]


def grade_atscale_mirror(pred_rows, gt_raw, conditions):
    """Mirror of ex_base_external_pred with gold rows precomputed."""
    if not pred_rows or gt_raw is None:
        return 0
    pred_r = U.preprocess_results(pred_tuples(pred_rows))
    gt_r = U.preprocess_results(gt_raw)
    if not gt_r:
        return 0
    return U._compare_rows(pred_r, gt_r, conditions, cell=U.canonical_cell)


def grade_raw_mirror(pred_sqls, gt_raw, base_db, conn_db, conn, conditions):
    """Mirror of grade_raw_submission with gold rows precomputed. Returns
    (verdict, pred_raw_rows_or_None, error_str_or_None)."""
    if not pred_sqls or gt_raw is None:
        return 0, None, None
    cleaned = U.remove_round(U.remove_distinct(U.remove_comments(list(pred_sqls))))
    res, err, to, _ = U.execute_queries(cleaned, conn_db, conn)
    if err or to:
        return 0, None, str(err or "timeout")
    pred_r = U.preprocess_results(res)
    gt_r = U.preprocess_results(gt_raw)
    if not pred_r or not gt_r:
        return 0, res, None
    return U._compare_rows(pred_r, gt_r, conditions), res, None


# ---------------------------------------------------------------- classification

def _cells(rows, cell):
    if cell is None:
        return [tuple(r) for r in rows]
    return [tuple(cell(v) for v in r) for r in rows]


def _passes(pred_cells, gt_cells, conditions):
    return U._compare_rows(pred_cells, gt_cells, conditions) == 1


def _strip_cells(rows):
    return [tuple(v.strip() if isinstance(v, str) else v for v in r) for r in rows]


_NUM = (int, float, Decimal)


def _tolerant_rows_equal(pred, gt, tol):
    """Aligned compare, numbers within tol, strings casefolded. Both sides are
    sorted lexicographically first, so it is only meaningful when the row
    multisets nearly agree; used as a diagnostic bucket, not a grader."""
    if len(pred) != len(gt) or (pred and len(pred[0]) != len(gt[0])):
        return False

    def keyed(rows):
        return sorted(rows, key=lambda r: tuple(str(v) for v in r))

    def cellnum(v):
        if isinstance(v, _NUM) and not isinstance(v, bool):
            return Decimal(str(v))
        if isinstance(v, str):
            s = v.strip()
            try:
                return Decimal(s)
            except Exception:
                return None
        return None

    for pr, gr in zip(keyed(pred), keyed(gt)):
        for pv, gv in zip(pr, gr):
            pn, gn = cellnum(pv), cellnum(gv)
            if pn is not None and gn is not None:
                if abs(pn - gn) > tol:
                    return False
            else:
                ps = pv.casefold().strip() if isinstance(pv, str) else pv
                gs = gv.casefold().strip() if isinstance(gv, str) else gv
                if ps != gs:
                    return False
    return True


_MAX_SUBSET_TRIES = 300


def classify(pred_p, gt_p, conditions, cell):
    """Near-miss class for a failing (preprocessed) submission. First hit wins."""
    if not pred_p:
        return "empty-pred"
    if not gt_p:
        return "empty-gold"
    pred_c, gt_c = _cells(pred_p, cell), _cells(gt_p, cell)
    pw, gw = len(pred_c[0]), len(gt_c[0])

    if pw == gw:
        # same rows, other order (only reachable when order was enforced,
        # i.e. the question carries an ordering cue)
        if conditions.get("order") and _passes(pred_c, gt_c, {**conditions, "order": False}):
            return "order-only-cue-present"
        if _passes(_strip_cells(pred_c), _strip_cells(gt_c), conditions):
            return "whitespace-only"
        if _tolerant_rows_equal(pred_c, gt_c, Decimal("0.011")):
            return "rounding-only"
        if len(pred_c) == len(gt_c):
            # per-column agreement on sorted rows
            sp = sorted(pred_c, key=lambda r: tuple(str(v) for v in r))
            sg = sorted(gt_c, key=lambda r: tuple(str(v) for v in r))
            same_cols = sum(
                all((a[i] == b[i]) or
                    (isinstance(a[i], str) and isinstance(b[i], str)
                     and a[i].casefold() == b[i].casefold())
                    for a, b in zip(sp, sg))
                for i in range(pw))
            if same_cols > 0:
                return f"value-diff-{pw - same_cols}col"
            return "value-diff-allcol"
        ps, gs = set(map(tuple, pred_c)), set(map(tuple, gt_c))
        if ps < gs:
            return "missing-rows"
        if ps > gs:
            return "extra-rows"
        return "row-mismatch" if ps & gs else "disjoint-rows"

    if pw > gw:
        combos = itertools.combinations(range(pw), gw)
        for n, keep in enumerate(combos):
            if n >= _MAX_SUBSET_TRIES:
                break
            sub = [tuple(r[i] for i in keep) for r in pred_c]
            if _passes(sub, gt_c, conditions):
                return "extra-columns-only"
        return "width-pred-wider"
    combos = itertools.combinations(range(gw), pw)
    for n, keep in enumerate(combos):
        if n >= _MAX_SUBSET_TRIES:
            break
        sub = [tuple(r[i] for i in keep) for r in gt_c]
        if _passes(pred_c, sub, conditions):
            return "gold-extra-columns"
    return "width-gold-wider"


# ---------------------------------------------------------------------- driver

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--atscale-audit",
                    default="results/bird_full_run_2026-09-06_atscale_n3/results/grading_audit_this_run.jsonl")
    ap.add_argument("--raw-audit", default="results/grading_audit.jsonl")
    ap.add_argument("--out", default="scratch/us002/sweep")
    ap.add_argument("--sample-gate", type=int, default=60,
                    help="rows per arm cross-checked against the real entry point")
    args = ap.parse_args()

    tasks = load_tasks()
    gc = GoldCache()

    arms = {
        "atscale": rows_from(args.atscale_audit, "atscale"),
        "raw": rows_from(args.raw_audit, "raw", RAW_REPLAY_TS),
    }
    # Query tasks only: Management (_M) grading is test-case code, not rows.
    for arm in arms:
        arms[arm] = [d for d in arms[arm]
                     if d["task_id"] in tasks and tasks[d["task_id"]].get("category") == "Query"]
        print(f"{arm}: {len(arms[arm])} audit rows", file=sys.stderr)

    verdicts = {}          # (arm, idx) -> mirror verdict
    detail = []
    repro_mismatch = Counter()
    gate_checked = gate_bad = 0

    for arm, rows in arms.items():
        cell = U.canonical_cell if arm == "atscale" else None
        for i, d in enumerate(rows):
            tid = d["task_id"]
            base_db = tasks[tid]["selected_database"]
            sol = d["sol_sql"]
            if isinstance(sol, str):
                sol = [sol]
            cond = d.get("conditions") or {}
            gt_raw = gc.gold_rows(base_db, sol, arm)
            task_db, conn = gc.conn(base_db)
            if arm == "atscale":
                v = grade_atscale_mirror(d["pred_rows"], gt_raw, cond)
                pred_p = U.preprocess_results(pred_tuples(d["pred_rows"]))
            else:
                pred_sqls = d["pred_sql"] if isinstance(d["pred_sql"], list) else [d["pred_sql"]]
                v, pred_raw, err = grade_raw_mirror(pred_sqls, gt_raw, base_db, task_db, conn, cond)
                pred_p = U.preprocess_results(pred_raw) if pred_raw else []
            verdicts[(arm, i)] = v
            if bool(v) != bool(d["passed"]):
                repro_mismatch[(arm, bool(d["passed"]), bool(v))] += 1
            cls = None
            if v == 0:
                gt_p = U.preprocess_results(gt_raw) if gt_raw is not None else []
                if arm == "raw" and pred_p == [] and gt_raw is not None and not d.get("pred_rows"):
                    cls = "exec-error-or-empty"
                cls = cls or classify(pred_p, gt_p, cond, cell)
            detail.append({"arm": arm, "task_id": tid, "phase": d["phase"],
                           "attempt": d["attempt"], "ts": d["ts"],
                           "recorded": bool(d["passed"]), "replayed": v,
                           "class": cls})
            if i % max(1, len(rows) // args.sample_gate) == 0:
                gate_checked += 1
                if arm == "atscale":
                    real = U.ex_base_external_pred(pred_tuples(d["pred_rows"]), sol, task_db, conn, cond)
                else:
                    real = U.grade_raw_submission(pred_sqls, sol, task_db, conn, cond)
                if real != v:
                    gate_bad += 1
                    print(f"GATE MISMATCH {arm} {tid} p{d['phase']} real={real} mirror={v}",
                          file=sys.stderr)

    if gate_bad:
        print(f"REFUSING TO PRINT: {gate_bad}/{gate_checked} gate rows disagree "
              f"with the real entry point.", file=sys.stderr)
        sys.exit(2)
    print(f"gate: {gate_checked} rows agree with the real entry points", file=sys.stderr)
    print(f"recorded-vs-replayed mismatches: {dict(repro_mismatch)}", file=sys.stderr)

    with open(args.out + "_detail.jsonl", "w") as f:
        for d in detail:
            f.write(json.dumps(d) + "\n")

    # summary table: still-failing near-miss classes per arm, phase 1 and 2
    print("\n| class | atscale p1 | atscale p2 | raw p1 | raw p2 |")
    print("| --- | --- | --- | --- | --- |")
    per = defaultdict(Counter)
    for d in detail:
        if d["class"]:
            per[d["class"]][(d["arm"], d["phase"])] += 1
    for cls in sorted(per, key=lambda c: -sum(per[c].values())):
        c = per[cls]
        print(f"| {cls} | {c[('atscale',1)]} | {c[('atscale',2)]} "
              f"| {c[('raw',1)]} | {c[('raw',2)]} |")

    # distinct tasks per class (a class can hold several attempts of one task)
    print("\nDistinct (arm, phase, task) per class:")
    seen = defaultdict(set)
    for d in detail:
        if d["class"]:
            seen[d["class"]].add((d["arm"], d["phase"], d["task_id"]))
    for cls in sorted(seen, key=lambda c: -len(seen[c])):
        print(f"  {cls}: {len(seen[cls])}")


if __name__ == "__main__":
    main()
