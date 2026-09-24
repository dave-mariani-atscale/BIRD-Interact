#!/usr/bin/env python3
"""Compare two arms of a paired run on their shared Query tasks.

    python scripts/compare_arms.py results/A.json results/B.json [--label-a X --label-b Y]

Reports Query P1/P2 per arm (overall and per database), the paired McNemar test on
P1, per-task tool-call counts by tool, error-result counts, budget and wall clock.
A task that errored counts as a failure, never an exclusion.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from typing import Any


def load(path: str) -> dict[str, dict[str, Any]]:
    d = json.load(open(path))
    rows = d.get("results") or d.get("tasks") or []
    out = {}
    for r in rows:
        tid = r.get("instance_id") or r.get("task_id")
        if "_M_" in tid:
            continue
        out[tid] = r
    return out


def db_of(tid: str, r: dict[str, Any]) -> str:
    return r.get("database") or tid.rsplit("_", 1)[0]


def tool_counts(r: dict[str, Any]) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    for e in r.get("tool_trajectory") or []:
        if not isinstance(e, dict):
            continue
        name = e.get("tool") or e.get("name") or e.get("tool_name") or "?"
        c[name] += 1
        txt = json.dumps(e.get("result", e.get("response", e.get("output", ""))))[:400].lower()
        if e.get("is_error") or e.get("error") or '"iserror": true' in txt or "query not executed" in txt:
            c["__errors__"] += 1
    return c


def mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2**n
    return min(1.0, 2 * p)


def rate(rows: list[dict[str, Any]], key: str) -> str:
    n = len(rows)
    k = sum(1 for r in rows if r.get(key))
    return f"{k}/{n} ({100*k/n:.1f}%)" if n else "-"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    args = ap.parse_args()
    A, B = load(args.a), load(args.b)
    shared = sorted(set(A) & set(B))
    if not shared:
        sys.exit("no shared Query tasks")
    only_a, only_b = sorted(set(A) - set(B)), sorted(set(B) - set(A))
    print(f"shared Query tasks: {len(shared)}  (only in {args.label_a}: {len(only_a)}, only in {args.label_b}: {len(only_b)})")
    ra, rb = [A[t] for t in shared], [B[t] for t in shared]
    print(f"\n{'':24s}{args.label_a:>22s}{args.label_b:>22s}")
    for key, label in (("phase1_passed", "Query P1"), ("phase2_passed", "Query P2")):
        print(f"{label:24s}{rate(ra, key):>22s}{rate(rb, key):>22s}")
    for key, label, fmt in (("total_reward", "mean reward", "{:.3f}"), ("elapsed_seconds", "mean s/task", "{:.0f}"), ("budget_used", "mean budget used", "{:.2f}")):
        va = [r.get(key) or 0 for r in ra]
        vb = [r.get(key) or 0 for r in rb]
        print(f"{label:24s}{fmt.format(sum(va)/len(va)):>22s}{fmt.format(sum(vb)/len(vb)):>22s}")
    # paired P1
    won_a = sum(1 for t in shared if A[t].get("phase1_passed") and not B[t].get("phase1_passed"))
    won_b = sum(1 for t in shared if B[t].get("phase1_passed") and not A[t].get("phase1_passed"))
    print(f"\npaired P1: {args.label_a} won {won_a}, {args.label_b} won {won_b}, net {won_a-won_b:+d}; exact McNemar p = {mcnemar(won_a, won_b):.3f}")
    # per database
    by_db: dict[str, list[str]] = collections.defaultdict(list)
    for t in shared:
        by_db[db_of(t, A[t])].append(t)
    print(f"\n{'database':32s}{'n':>4s}{args.label_a+' P1':>14s}{args.label_b+' P1':>14s}{args.label_a+' P2':>14s}{args.label_b+' P2':>14s}")
    for db, ts in sorted(by_db.items()):
        pa1 = sum(1 for t in ts if A[t].get("phase1_passed")); pb1 = sum(1 for t in ts if B[t].get("phase1_passed"))
        pa2 = sum(1 for t in ts if A[t].get("phase2_passed")); pb2 = sum(1 for t in ts if B[t].get("phase2_passed"))
        print(f"{db:32s}{len(ts):>4d}{pa1:>14d}{pb1:>14d}{pa2:>14d}{pb2:>14d}")
    # tool usage
    ca, cb = collections.Counter(), collections.Counter()
    for t in shared:
        ca.update(tool_counts(A[t])); cb.update(tool_counts(B[t]))
    tools = sorted(set(ca) | set(cb), key=lambda k: -(ca[k] + cb[k]))
    print(f"\n{'tool calls per task':32s}{args.label_a:>14s}{args.label_b:>14s}")
    for k in tools:
        print(f"{k:32s}{ca[k]/len(shared):>14.2f}{cb[k]/len(shared):>14.2f}")
    flips = [(t, A[t].get("phase1_passed"), B[t].get("phase1_passed")) for t in shared if bool(A[t].get("phase1_passed")) != bool(B[t].get("phase1_passed"))]
    if flips:
        print("\nP1 flips (task, %s, %s):" % (args.label_a, args.label_b))
        for t, a, b in flips:
            print(f"  {t}: {bool(a)} -> {bool(b)}")


if __name__ == "__main__":
    main()
