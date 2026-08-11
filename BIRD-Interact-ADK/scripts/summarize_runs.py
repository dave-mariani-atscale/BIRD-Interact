#!/usr/bin/env python3
"""Summarise evaluation runs: per-arm scores, lift, and per-task stability.

    python scripts/summarize_runs.py                          # every database, every run
    python scripts/summarize_runs.py --database cybermarket_pattern
    python scripts/summarize_runs.py --lastn 3                # 3 most recent runs PER ARM

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


def load_runs(results_dir: str, database: str | None, lastn: int | None):
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
        runs.append({"path": base, "arm": arm, "db": db, "doc": doc,
                     "mtime": os.path.getmtime(path),
                     "by_id": {r["task_id"]: r for r in results}})

    if lastn:
        # Per (database, arm), not globally: the arms are usually run in an
        # uneven interleaving, so a global "last N files" would silently compare
        # e.g. 5 atscale runs against 1 raw run. Per-arm keeps it N vs N.
        kept = []
        groups = defaultdict(list)
        for r in runs:
            groups[(r["db"], r["arm"])].append(r)
        for g in groups.values():
            kept.extend(sorted(g, key=lambda r: r["mtime"])[-lastn:])
        runs = sorted(kept, key=lambda r: r["mtime"])
    return runs


# A run whose every task scored zero, or whose tool calls mostly errored, is
# almost always broken infrastructure rather than a bad model: a dead MCP
# endpoint, an undeployed model, a corrupted catalog. Averaging it in produces a
# confident and completely wrong lift, so such runs are flagged and excluded.
# Observed: an entire 3-run arm scored 0.000 because a redeploy of a SIBLING
# model corrupted the shared catalog, and every call returned
# 'ERROR: relation "..." already exists'.
_INFRA_MARKERS = ("Error calling ", "already exists", "No semantic model configured")


def run_health(run) -> tuple[bool, str]:
    """(is_suspect, reason) for one run."""
    results = list(run["by_id"].values())
    if not results:
        return True, "no task results"
    calls = errs = 0
    for r in results:
        for t in r.get("tool_trajectory") or []:
            if not t.get("tool"):
                continue
            calls += 1
            if any(m in str(t.get("result") or "") for m in _INFRA_MARKERS):
                errs += 1
    if calls and errs / calls > 0.30:
        return True, f"{errs}/{calls} tool calls ({errs/calls:.0%}) returned an infrastructure error"
    if all(r.get("total_reward", 0) == 0 for r in results):
        return True, f"every one of {len(results)} tasks scored zero"
    return False, ""


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
    suspect = {}
    for arm in sorted(by_arm):
        for r in by_arm[arm]:
            m = r["doc"]["metrics"]
            bad, why = run_health(r)
            if bad:
                suspect[r["path"]] = why
            print(f"   {r['path']:<62} {arm:<8} n={m['total_tasks']:<3} "
                  f"avg={m['average_reward']:.3f}{'   <<< SUSPECT' if bad else ''}")

    if suspect:
        print("\n!! SUSPECT RUNS EXCLUDED -- these look like broken infrastructure,")
        print("!! not a model result. Fix the cause and re-run before drawing any")
        print("!! conclusion; scores below omit them.")
        for path, why in suspect.items():
            print(f"     {path}\n       {why}")
        for arm in list(by_arm):
            by_arm[arm] = [r for r in by_arm[arm] if r["path"] not in suspect]
            if not by_arm[arm]:
                print(f"\n     ARM '{arm}' HAS NO USABLE RUNS LEFT -- no comparison is possible "
                      f"for it.")
                del by_arm[arm]
        if not by_arm:
            return

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
    ap.add_argument("--lastn", type=int, default=None, metavar="N",
                    help="Only summarise the N most recent runs OF EACH ARM (per "
                         "database), by file mtime. Use this to compare the runs "
                         "since a change without hand-picking files. Default: all runs.")
    args = ap.parse_args()

    if args.lastn is not None and args.lastn < 1:
        ap.error("--lastn must be at least 1")

    runs = load_runs(args.results_dir, args.database, args.lastn)
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
