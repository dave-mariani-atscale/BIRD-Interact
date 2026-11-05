#!/usr/bin/env python3
"""Like-for-like comparison of one arm against a finished n-run baseline, live or final.

    # while the arm runs: verdicts parsed from the runner log
    python scripts/compare_vs_baseline_runs.py --log logs/dbx_vs_0910/dbx_metric_views.log \
        --baseline results/full0910_atscale_run0[123]_*.json
    # after it finishes: the arm's results file (adds coins, turns, wall-clock)
    python scripts/compare_vs_baseline_runs.py --results results/dbx_vs_0910/dbx_metric_views_run01_*.json \
        --baseline results/full0910_atscale_run0[123]_*.json

Like-for-like means: only Query tasks, and only tasks the arm has FINISHED, compared
with the baseline's verdicts on those same tasks. Three baseline readings are shown:
run 1 (the cold run, the fair counterpart of an arm with no memory), the n-run mean,
and best-of-n (the leaderboard convention). Paired counts are against run 1, with an
exact McNemar p-value. Baseline tasks are also classed always / flaky / never passing
P1 across its runs, which tells whether the arm loses the baseline's stable wins or
only its coin-flips. A task the arm errored on counts as a failure.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import re
from typing import Dict, List, Tuple

VERDICT = re.compile(r"<== (\S+): (PASS both phases|PASS phase 1|fail|error)\s+reward=([0-9.]+)\s+\((\d+)/(\d+) done")


def _query_ids() -> set:
    """Query-category instance ids from the task file. Filtering on the category,
    not on "_M_" in the id: three Query tasks carry "_M_" in their ids
    (households_M_10, insider_trading_M_9, insider_trading_M_10)."""
    from shared.config import settings
    return {json.loads(l)["instance_id"] for l in open(settings.data_path)
            if json.loads(l).get("category") == "Query"}


QUERY = None


def is_query(tid: str) -> bool:
    global QUERY
    if QUERY is None:
        QUERY = _query_ids()
    return tid in QUERY


def load_runs(paths: List[str]) -> List[Dict[str, dict]]:
    runs = []
    for p in sorted(paths):
        d = json.load(open(p))
        rows = d.get("results") or d.get("tasks") or []
        runs.append({(r.get("instance_id") or r.get("task_id")): r for r in rows
                     if is_query(r.get("instance_id") or r.get("task_id"))})
    return runs


def arm_from_log(path: str) -> Tuple[Dict[str, dict], int]:
    out, total = {}, 0
    for line in open(path, errors="replace"):
        m = VERDICT.search(line)
        if m:
            tid, v, rw, _, total = m.group(1), m.group(2), float(m.group(3)), m.group(4), int(m.group(5))
            if not is_query(tid):
                continue
            out[tid] = {"phase1_passed": v.startswith("PASS"), "phase2_passed": v == "PASS both phases",
                        "total_reward": rw, "error": v == "error"}
    return out, total


def mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def pct(k: float, n: int) -> str:
    return f"{100 * k / n:5.1f}%" if n else "    -"


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--log")
    g.add_argument("--results")
    ap.add_argument("--baseline", nargs="+", required=True)
    ap.add_argument("--arm-label", default="Databricks")
    ap.add_argument("--audit", help="grading_audit.jsonl: adds the views-only split (submissions that "
                    "read only metric views vs ones that fell back to base tables)")
    ap.add_argument("--backend", default=None, help="the arm's backend name in the audit (default: from the results file)")
    ap.add_argument("--base-label", default="AtScale 09-10")
    a = ap.parse_args()

    base = load_runs([p for b in a.baseline for p in glob.glob(b)])
    nb = len(base)
    since = 0.0
    backend = a.backend
    if a.log:
        arm, total = arm_from_log(a.log)
        final = False
        first = next((l for l in open(a.log, errors="replace") if re.match(r"\d{4}-\d{2}-\d{2} ", l)), None)
        if first:
            import datetime as _dt
            since = _dt.datetime.strptime(first[:19], "%Y-%m-%d %H:%M:%S").timestamp() - 60
    else:
        rp = sorted(glob.glob(a.results))[-1]
        meta = json.load(open(rp))
        since = float(meta.get("run_started") or 0) - 60
        backend = backend or meta.get("backend")
        arm = load_runs([rp])[-1]
        total = len(arm)
        final = True
    tasks = sorted(t for t in arm if all(t in b for b in base))
    n = len(tasks)
    print(f"{a.arm_label}: {len(arm)} Query tasks finished" + (f" of {total}" if total else "")
          + f"; compared on the {n} that all {nb} baseline runs also have.\n")
    if not n:
        return

    def p1(r): return bool(r.get("phase1_passed"))
    def p2(r): return bool(r.get("phase2_passed"))
    def rw(r): return float(r.get("total_reward") or 0)

    arm_p1 = sum(p1(arm[t]) for t in tasks); arm_p2 = sum(p2(arm[t]) for t in tasks); arm_rw = sum(rw(arm[t]) for t in tasks)
    r1 = base[0]
    b1_p1 = sum(p1(r1[t]) for t in tasks); b1_p2 = sum(p2(r1[t]) for t in tasks); b1_rw = sum(rw(r1[t]) for t in tasks)
    mean_p1 = sum(p1(b[t]) for b in base for t in tasks) / nb
    mean_p2 = sum(p2(b[t]) for b in base for t in tasks) / nb
    mean_rw = sum(rw(b[t]) for b in base for t in tasks) / nb
    best = max(range(nb), key=lambda i: sum(rw(base[i][t]) for t in tasks))
    bb = base[best]
    best_p1 = sum(p1(bb[t]) for t in tasks); best_p2 = sum(p2(bb[t]) for t in tasks); best_rw = sum(rw(bb[t]) for t in tasks)

    hdr = f"{'':22s}{a.arm_label:>14s}{a.base_label + ' r1 (cold)':>24s}{'mean of ' + str(nb):>12s}{'best run (r' + str(best + 1) + ')':>18s}"
    print(hdr)
    print(f"{'P1':22s}{pct(arm_p1, n):>14s}{pct(b1_p1, n):>24s}{pct(mean_p1, n):>12s}{pct(best_p1, n):>18s}")
    print(f"{'P2':22s}{pct(arm_p2, n):>14s}{pct(b1_p2, n):>24s}{pct(mean_p2, n):>12s}{pct(best_p2, n):>18s}")
    print(f"{'reward / task':22s}{arm_rw / n:>14.4f}{b1_rw / n:>24.4f}{mean_rw / n:>12.4f}{best_rw / n:>18.4f}")
    print(f"{'arm / baseline':22s}{'':14s}{(arm_rw / b1_rw if b1_rw else float('nan')):>23.2f}x{(arm_rw / mean_rw if mean_rw else float('nan')):>11.2f}x{(arm_rw / best_rw if best_rw else float('nan')):>17.2f}x")
    errs = sum(1 for t in tasks if arm[t].get("error"))
    if errs:
        print(f"{a.arm_label} errors (scored as failures): {errs}")

    won = [t for t in tasks if p1(arm[t]) and not p1(r1[t])]
    lost = [t for t in tasks if p1(r1[t]) and not p1(arm[t])]
    print(f"\nPaired P1 vs AtScale run 1: {a.arm_label} won {len(won)}, AtScale won {len(lost)}, "
          f"net {len(won) - len(lost):+d}, McNemar p = {mcnemar(len(won), len(lost)):.3g}")

    if a.audit:
        rows = [json.loads(l) for l in open(a.audit)]
        rows = [r for r in rows if r.get("ts", 0) >= since and (not backend or r.get("backend") == backend)
                and r.get("task_id") in arm]
        sub = collections.defaultdict(list)
        for r in rows:
            sub[(r["task_id"], r.get("phase"))].append(r)
        def passing(t, ph):
            ok = [r for r in sub.get((t, ph), []) if r.get("passed")]
            return ok[-1] if ok else None
        flagged = [r for r in rows if r.get("reads_base_tables") is not None]
        fb_subs = sum(1 for r in flagged if r["reads_base_tables"])
        fb_tasks = {r["task_id"] for r in flagged if r["reads_base_tables"]}
        p1_views = sum(1 for t in tasks if p1(arm[t]) and passing(t, 1) and passing(t, 1).get("reads_base_tables") is False)
        p1_fb = sum(1 for t in tasks if p1(arm[t]) and passing(t, 1) and passing(t, 1).get("reads_base_tables"))
        p2_views = sum(1 for t in tasks if p2(arm[t]) and passing(t, 2) and passing(t, 2).get("reads_base_tables") is False)
        print(f"\nFallback to base tables ({a.arm_label}): {fb_subs} of {len(flagged)} graded submissions, "
              f"on {len(fb_tasks)} of {n} tasks")
        print(f"{'P1 views only':22s}{pct(p1_views, n):>14s}{pct(b1_p1, n):>24s}   (passes whose passing SQL read only metric views)")
        print(f"{'P1 via fallback':22s}{pct(p1_fb, n):>14s}")
        print(f"{'P2 views only':22s}{pct(p2_views, n):>14s}{pct(b1_p2, n):>24s}")
        vo_won = sum(1 for t in tasks if (p1(arm[t]) and passing(t, 1) and passing(t, 1).get("reads_base_tables") is False) and not p1(r1[t]))
        vo_lost = sum(1 for t in tasks if p1(r1[t]) and not (p1(arm[t]) and passing(t, 1) and passing(t, 1).get("reads_base_tables") is False))
        print(f"Paired P1 views only vs AtScale run 1: {a.arm_label} won {vo_won}, AtScale won {vo_lost}, "
              f"net {vo_won - vo_lost:+d}, McNemar p = {mcnemar(vo_won, vo_lost):.3g}")

    cls = {}
    for t in tasks:
        k = sum(p1(b[t]) for b in base)
        cls[t] = "always" if k == nb else ("never" if k == 0 else "flaky")
    print(f"\nBy AtScale's P1 stability across its {nb} runs:")
    print(f"{'class':10s}{'tasks':>7s}{a.arm_label + ' P1':>18s}")
    for c in ("always", "flaky", "never"):
        ts = [t for t in tasks if cls[t] == c]
        print(f"{c:10s}{len(ts):>7d}{pct(sum(p1(arm[t]) for t in ts), len(ts)):>18s}")

    from shared.config import settings
    db_of = {json.loads(l)["instance_id"]: json.loads(l)["selected_database"] for l in open(settings.data_path)}
    by = collections.defaultdict(list)
    for t in tasks:
        by[db_of.get(t, t.rsplit("_", 1)[0])].append(t)   # households_M_10 belongs to households
    print(f"\n{'database':34s}{'n':>4s}{'arm P1':>9s}{'AtS r1':>9s}{'AtS mean':>10s}{'arm P2':>9s}{'AtS r1':>9s}{'net P1':>8s}")
    for db in sorted(by, key=lambda d: -len(by[d])):
        ts = by[db]; k = len(ts)
        net = sum(1 for t in ts if p1(arm[t]) and not p1(r1[t])) - sum(1 for t in ts if p1(r1[t]) and not p1(arm[t]))
        print(f"{db:34s}{k:>4d}{pct(sum(p1(arm[t]) for t in ts), k):>9s}{pct(sum(p1(r1[t]) for t in ts), k):>9s}"
              f"{pct(sum(p1(b[t]) for b in base for t in ts) / nb, k):>10s}{pct(sum(p2(arm[t]) for t in ts), k):>9s}"
              f"{pct(sum(p2(r1[t]) for t in ts), k):>9s}{net:>+8d}")

    if final:
        def coins(r): return float(r.get("budget_used") or 0)
        def turns(r): return len(r.get("tool_trajectory") or [])
        def secs(r): return float(r.get("elapsed_seconds") or 0)
        print(f"\n{'efficiency (same tasks)':34s}{a.arm_label:>14s}{'AtScale r1':>14s}{'AtScale mean':>14s}")
        for label, f in (("coins / task", coins), ("tool calls / task", turns), ("wall-clock s / task", secs)):
            av = sum(f(arm[t]) for t in tasks) / n
            bv = sum(f(r1[t]) for t in tasks) / n
            mv = sum(f(b[t]) for b in base for t in tasks) / (n * nb)
            print(f"{label:34s}{av:>14.2f}{bv:>14.2f}{mv:>14.2f}")
        a_sec = sum(secs(arm[t]) for t in tasks); b_sec = sum(secs(r1[t]) for t in tasks)
        print(f"{'seconds per reward point':34s}{(a_sec / arm_rw if arm_rw else float('nan')):>14.1f}{(b_sec / b1_rw if b1_rw else float('nan')):>14.1f}")
        a_c = sum(coins(arm[t]) for t in tasks); b_c = sum(coins(r1[t]) for t in tasks)
        print(f"{'coins per P1 pass':34s}{(a_c / arm_p1 if arm_p1 else float('nan')):>14.2f}{(b_c / b1_p1 if b1_p1 else float('nan')):>14.2f}")


if __name__ == "__main__":
    main()
