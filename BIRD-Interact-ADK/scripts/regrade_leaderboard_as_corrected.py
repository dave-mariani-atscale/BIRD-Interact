#!/usr/bin/env python3
"""Re-grade a leaderboard-mode run's OWN submissions under the corrected regime.

Why: the leaderboard tabs and the Modified Harness tab report very different
accuracy for the same stack, and two things differ at once - the grading regime
(upstream vs this harness's six corrections) and the protocol (upstream user
simulator prompts and token limits, the Universal Cost Scheme, all 600 tasks).
This isolates the first: the same recorded rows, graded both ways.

Method. Every graded semantic-layer submission is recorded in the grading audit
(`record_graded_submission`) with the rows the engine returned, the task's
conditions and the verdict. For each audit row inside a run's window this
script executes that phase's gold once (cached), then grades the recorded rows
twice through the harness's own comparison - once with
`settings.grading_regime = "upstream"`, once `"corrected"` - and counts the
verdicts.

Reproduction gate, as in scripts/regrade_sweep.py: the upstream pass must
reproduce the run's RECORDED verdict. Rows where it does not are reported and
excluded, so a mirroring bug cannot masquerade as a grading delta.

    PYTHONPATH=. .venv-adk/bin/python scripts/regrade_leaderboard_as_corrected.py \
        --runs results/leaderboard_sonnet_20260912_atscale*.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402

from shared.config import settings  # noqa: E402
from shared import db_utils as U  # noqa: E402


def load_tasks():
    out = {}
    for line in open(settings.data_path):
        t = json.loads(line)
        out[t["instance_id"]] = t
    return out


class GoldCache:
    """Gold rows + cursor description per (task, phase), executed exactly as the
    semantic path does: remove_comments -> remove_round, no remove_distinct.

    One READ-ONLY connection per template database, held open - a connection per
    call exhausts Postgres' max_connections a third of the way through a run and
    the failures look like broken golds.
    """

    def __init__(self):
        self.conns, self.cache = {}, {}

    def conn(self, db):
        if db not in self.conns:
            c = psycopg2.connect(dbname=f"{db}_template", host=settings.pg_host,
                                 port=settings.pg_port, user=settings.pg_user,
                                 password=settings.pg_password)
            c.set_session(readonly=True, autocommit=True)
            self.conns[db] = c
        return self.conns[db]

    def get(self, task, phase, sol_sqls, db):
        key = (task, phase)
        if key in self.cache:
            return self.cache[key]
        sqls = U.remove_round(U.remove_comments(list(sol_sqls)))
        c, res, desc, err = self.conn(db), None, None, None
        for sql in sqls:
            if not sql or not sql.strip():
                continue
            try:
                with c.cursor() as cur:
                    cur.execute("SET statement_timeout = '60s'")
                    cur.execute(sql)
                    res = cur.fetchall() if cur.description else []
                    desc = cur.description
            except Exception as e:  # noqa: BLE001
                c.rollback()
                err = str(e).splitlines()[0][:200]
                break
        self.cache[key] = (None, None, None) if err else (res, desc, sqls)
        return self.cache[key]


def grade(pred_rows, gt_res, gt_desc, sqls, conditions, regime, question):
    """The tail of ex_base_external_pred, with the regime chosen by the caller."""
    # grading_regime is derived from leaderboard_mode on purpose (there is no way
    # to run the leaderboard stack with corrected grading), so the switch here is
    # the flag itself.
    settings.leaderboard_mode = (regime == "upstream")
    cond = U.effective_conditions(conditions, question)
    pred_rounded = U.preprocess_results(pred_rows)
    gt_rounded = U.preprocess_results(gt_res)
    if not pred_rounded or not gt_rounded:
        return 0
    return 1 if U._compare_rows(
        pred_rounded, gt_rounded, cond, cell=U.canonical_cell,
        raw=(pred_rows, gt_res, U._gold_key(sqls, gt_desc, cond))) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--audit", default="results/grading_audit.jsonl")
    ap.add_argument("--out")
    a = ap.parse_args()

    paths = sorted(p for g in a.runs for p in glob.glob(g))
    windows = {}
    for p in paths:
        d = json.load(open(p))
        windows[Path(p).name] = (d["run_started"], d["run_finished"],
                                 d.get("leaderboard_mode"),
                                 (d.get("deviations") or {}).get("grading_regime"))
        del d
    for f, (s, e, lb, rg) in windows.items():
        print(f"window {f}: leaderboard={lb} regime={rg} {s:.0f}..{e:.0f}")

    tasks = load_tasks()
    gold = GoldCache()
    rows_by_run = defaultdict(list)
    with open(a.audit) as fh:
        for line in fh:
            if '"backend": "atscale"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = float(d.get("ts", 0))
            for f, (s, e, _lb, _rg) in windows.items():
                if s <= ts <= e:
                    rows_by_run[f].append(d)
                    break

    summary, mismatches, per_task = {}, [], defaultdict(dict)
    for f in windows:
        rows = rows_by_run[f]
        # one verdict per (task, phase): the last attempt recorded, which is the
        # submission the run scored
        last = {}
        for d in rows:
            last[(d["task_id"], d["phase"])] = d
        n = defaultdict(int)
        for (tid, phase), d in sorted(last.items()):
            t = tasks.get(tid)
            if not t or t["category"] != "Query":
                continue
            db = t["selected_database"]
            sol = d.get("sol_sql") or (t["sol_sql"] if phase == 1 else t["follow_up"]["sol_sql"])
            question = (t["amb_user_query"] if phase == 1 else t["follow_up"]["query"])
            cond = d.get("conditions") or (t["conditions"] if phase == 1
                                           else t["follow_up"]["conditions"])
            gt_res, gt_desc, sqls = gold.get(tid, phase, sol, db)
            n[f"p{phase}_rows"] += 1
            n[f"p{phase}_recorded_all"] += 1 if d.get("passed") else 0
            if gt_res is None:
                n[f"p{phase}_gold_error"] += 1
                continue
            up = grade(d["pred_rows"], gt_res, gt_desc, sqls, cond, "upstream", question)
            co = grade(d["pred_rows"], gt_res, gt_desc, sqls, cond, "corrected", question)
            rec = 1 if d.get("passed") else 0
            n[f"p{phase}_recorded"] += rec
            n[f"p{phase}_upstream"] += up
            n[f"p{phase}_corrected"] += co
            if up != rec:
                n[f"p{phase}_mirror_mismatch"] += 1
                mismatches.append((f, tid, phase, rec, up, co))
            if co and not up:
                n[f"p{phase}_flips_up"] += 1
            per_task[f][f"{tid}|p{phase}"] = {"recorded": rec, "upstream": up,
                                              "corrected": co}
        summary[f] = dict(n)
        print(f"\n{f}")
        for k in sorted(n):
            print(f"   {k:24s} {n[k]}")

    print("\nmirror mismatches (excluded from the delta):", len(mismatches))
    for m in mismatches[:20]:
        print("  ", m)
    if a.out:
        json.dump({"summary": summary, "mismatches": mismatches,
                   "per_task": per_task}, open(a.out, "w"), indent=1)
        print("wrote", a.out)


if __name__ == "__main__":
    main()
