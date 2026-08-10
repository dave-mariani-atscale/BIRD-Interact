#!/usr/bin/env python3
"""Summarise evaluation runs: per-arm scores, lift, and per-task stability.

    python scripts/summarize_runs.py                          # every database
    python scripts/summarize_runs.py --database cybermarket_pattern
    python scripts/summarize_runs.py --since 20260810_1400    # only newer runs

Why this exists: a single run's score moves by as much as +/-0.10 from agent
variance alone, so a before/after delta from one run per arm says nothing. This
reports the mean and spread across every run it finds, and separates tasks that
always pass from the ones that flip -- which is what actually tells you whether
a change did anything.

Two comparisons are deliberately kept apart:

  * The HEADLINE per-arm numbers, as each run reported them. Not comparable
    across arms: the raw arm runs the Management tasks too (DDL/DML, which a
    read-only semantic layer cannot attempt), and it scores differently on them.
  * The LIKE-FOR-LIKE table, restricted to the query tasks both arms attempted.
    This is the honest comparison and the one lift is computed from.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
from collections import defaultdict


def load_runs(results_dir: str, database: str | None, since: str | None):
    runs = []
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json")),
                       key=os.path.getmtime):
        try:
            with open(path) as f:
                doc = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        results = doc.get("results")
        if not results:
            continue
        base = os.path.basename(path)
        # Prefer the recorded backend; fall back to the filename for runs
        # written before --repeat started stamping provenance into the file.
        arm = doc.get("backend")
        if not arm:
            arm = "raw" if "_raw" in base else ("atscale" if "_atscale" in base else "?")
        dbs = {r.get("database") for r in results if r.get("database")}
        db = sorted(dbs)[0] if len(dbs) == 1 else (",".join(sorted(dbs)) or "?")
        if database and db != database:
            continue
        if since and base.rsplit(".", 1)[0][-15:] < since:
            continue
        runs.append({"path": base, "arm": arm, "db": db, "doc": doc,
                     "by_id": {r["task_id"]: r for r in results}})
    return runs


def _fmt(vals):
    if not vals:
        return "n/a"
    if len(vals) == 1:
        return f"{vals[0]:.3f}"
    return (f"{statistics.mean(vals):.3f}  (min {min(vals):.3f} max {max(vals):.3f}"
            f" sd {statistics.stdev(vals):.3f})")


def summarize(db: str, runs: list):
    print("=" * 84)
    print(f"DATABASE: {db}")
    print("=" * 84)

    by_arm = defaultdict(list)
    for r in runs:
        by_arm[r["arm"]].append(r)

    print("\n1. RUNS FOUND")
    for arm in sorted(by_arm):
        for r in by_arm[arm]:
            m = r["doc"]["metrics"]
            print(f"   {r['path']:<62} {arm:<8} n={m['total_tasks']:<3} "
                  f"avg={m['average_reward']:.3f}")

    print("\n2. HEADLINE, as each run reported it (NOT comparable across arms --")
    print("   the raw arm also runs the Management tasks the atscale arm filters out)")
    for arm in sorted(by_arm):
        rs = by_arm[arm]
        print(f"   {arm:<9} n_runs={len(rs)}  p1={_fmt([x['doc']['metrics']['phase1_rate'] for x in rs])}")
        print(f"   {'':<9}            p2={_fmt([x['doc']['metrics']['phase2_rate'] for x in rs])}")
        print(f"   {'':<9}           avg={_fmt([x['doc']['metrics']['average_reward'] for x in rs])}")

    # like-for-like: the task ids every arm actually attempted
    common = None
    for arm in by_arm:
        ids = set.intersection(*[set(r["by_id"]) for r in by_arm[arm]])
        common = ids if common is None else (common & ids)
    common = sorted(common or [], key=lambda k: (("_M_" in k), k))
    query_ids = [k for k in common if "_M_" not in k]
    mgmt_ids = [k for k in common if "_M_" in k]
    if mgmt_ids:
        print(f"\n   (excluding {len(mgmt_ids)} Management tasks from the comparison below)")

    if not query_ids:
        print("\n   No query tasks shared by all arms -- nothing to compare.")
        return

    print(f"\n3. LIKE-FOR-LIKE on the {len(query_ids)} query tasks both arms ran")
    print(f"   {'arm':<10} {'runs':<6} {'phase1':<34} {'phase2':<34} avg_reward")
    means = {}
    for arm in sorted(by_arm):
        rs = by_arm[arm]
        p1 = [sum(r["by_id"][k]["phase1_passed"] for k in query_ids) / len(query_ids) for r in rs]
        p2 = [sum(r["by_id"][k]["phase2_passed"] for k in query_ids) / len(query_ids) for r in rs]
        rw = [sum(r["by_id"][k]["total_reward"] for k in query_ids) / len(query_ids) for r in rs]
        means[arm] = statistics.mean(rw)
        print(f"   {arm:<10} {len(rs):<6} {_fmt(p1):<34} {_fmt(p2):<34} {_fmt(rw)}")

    if "raw" in means:
        for arm in sorted(a for a in means if a != "raw"):
            print(f"\n   LIFT of {arm} over raw (mean avg_reward): {means[arm] - means['raw']:+.3f}")
        spreads = [statistics.stdev([sum(r["by_id"][k]["total_reward"] for k in query_ids) / len(query_ids)
                                     for r in by_arm[a]]) for a in by_arm if len(by_arm[a]) > 1]
        if spreads:
            print(f"   Largest single-arm spread (sd): {max(spreads):.3f} -- a lift smaller "
                  f"than roughly 2x this is not distinguishable from variance.")

    print(f"\n4. PER-TASK STABILITY (query tasks, phase 1)")
    for arm in sorted(by_arm):
        rs = by_arm[arm]
        buckets = {"always": [], "never": [], "flaky": []}
        for k in query_ids:
            hits = [r["by_id"][k]["phase1_passed"] for r in rs]
            buckets["always" if all(hits) else "never" if not any(hits) else "flaky"].append(
                k.rsplit("_", 1)[1])
        print(f"   {arm}:")
        for name in ("always", "never", "flaky"):
            print(f"     {name:<7} ({len(buckets[name])}): {buckets[name]}")

    if len(by_arm) > 1 and "raw" in by_arm:
        print(f"\n5. WHERE THE ARMS DIFFER (query tasks, mean reward per task)")
        others = [a for a in sorted(by_arm) if a != "raw"]
        print(f"   {'task':<26} {'raw':<8} " + " ".join(f"{a:<8}" for a in others) + " delta")
        for k in query_ids:
            rawm = statistics.mean([r["by_id"][k]["total_reward"] for r in by_arm["raw"]])
            oms = [statistics.mean([r["by_id"][k]["total_reward"] for r in by_arm[a]]) for a in others]
            if max(abs(o - rawm) for o in oms) < 0.05:
                continue
            best = max(oms)
            tag = "atscale wins" if best > rawm else "raw wins"
            print(f"   {k:<26} {rawm:<8.2f} " + " ".join(f"{o:<8.2f}" for o in oms)
                  + f" {best - rawm:+.2f}  {tag}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--database", default=None,
                    help="Only summarise this selected_database (e.g. cybermarket_pattern)")
    ap.add_argument("--since", default=None,
                    help="Only include runs whose filename timestamp is >= this "
                         "(e.g. 20260810_140000), for before/after comparisons")
    args = ap.parse_args()

    runs = load_runs(args.results_dir, args.database, args.since)
    if not runs:
        print(f"No runs with results found in {args.results_dir!r}"
              + (f" for database {args.database!r}" if args.database else ""))
        return
    by_db = defaultdict(list)
    for r in runs:
        by_db[r["db"]].append(r)
    for db in sorted(by_db):
        summarize(db, by_db[db])
        print()


if __name__ == "__main__":
    main()
