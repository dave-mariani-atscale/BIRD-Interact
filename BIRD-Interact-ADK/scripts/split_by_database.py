#!/usr/bin/env python3
"""Split a monolithic eval results file into one JSON per database.

Mirrors the layout of results/820_all: each output file carries a per-database
header (run provenance, deviations, recomputed aggregates) plus that database's
slice of `results`, and a MANIFEST.json indexes everything written.

    python scripts/split_by_database.py <results.json> [--outdir DIR] [--arm NAME]

Defaults: --outdir is the input file's directory, --arm is the run's backend.
Makes no LLM calls.
"""
import argparse
import json
import os
from datetime import datetime, timezone


def iso_utc(epoch):
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_file")
    ap.add_argument("--outdir", help="default: directory of results_file")
    ap.add_argument("--arm", help="default: the run's backend")
    ap.add_argument("--force", action="store_true", help="overwrite existing per-database files")
    args = ap.parse_args()

    with open(args.results_file) as f:
        run = json.load(f)

    outdir = args.outdir or os.path.dirname(os.path.abspath(args.results_file))
    arm = args.arm or run.get("backend")
    source = os.path.basename(args.results_file)
    finished = iso_utc(run.get("run_finished"))

    # Infra stubs are bare records with no "database"; attribute them to the
    # database named by their task id so they still count as that db's failure.
    known = {r["database"] for r in run["results"] if r.get("database")}

    def db_of(r):
        if r.get("database"):
            return r["database"]
        tid = r.get("task_id", "")
        cands = [d for d in known if tid.startswith(d + "_")]
        if not cands:
            raise SystemExit(f"cannot infer database for record {tid!r}")
        return max(cands, key=len)

    by_db = {}
    for r in run["results"]:
        by_db.setdefault(db_of(r), []).append(r)

    targets = {db: os.path.join(outdir, f"{db}_{arm}.json") for db in by_db}
    clashes = [p for p in targets.values() if os.path.exists(p)]
    if clashes and not args.force:
        raise SystemExit(
            f"{len(clashes)} output file(s) already exist, e.g. {clashes[0]}\n"
            "Re-run with --force to overwrite."
        )

    manifest = []
    for db in sorted(by_db):
        rows = by_db[db]
        header = {
            "database": db,
            "arm": arm,
            "source_results_file": source,
            "run_backend": run.get("backend"),
            "run_mode": run.get("mode"),
            "run_query_only": run.get("query_only"),
            "run_finished_utc": finished,
            "run_finished_source": "run_finished",
            "deviations": run.get("deviations"),
            "task_count": len(rows),
            "expected_query_tasks": len(rows),
            "avg_reward": round(sum(r["total_reward"] or 0 for r in rows) / len(rows), 4),
            "phase1_passed": sum(1 for r in rows if r.get("phase1_passed")),
            "phase2_passed": sum(1 for r in rows if r.get("phase2_passed")),
        }
        with open(targets[db], "w") as f:
            json.dump({**header, "results": rows}, f)
        manifest.append({k: header[k] for k in (
            "database", "arm", "source_results_file", "run_finished_utc",
            "run_query_only", "task_count", "expected_query_tasks",
            "avg_reward", "phase1_passed", "phase2_passed")})
        print(f"{os.path.basename(targets[db]):58s} {len(rows):3d} tasks  avg {header['avg_reward']}")

    # Merge into any existing manifest so a second arm written here is additive.
    mpath = os.path.join(outdir, "MANIFEST.json")
    if os.path.exists(mpath):
        with open(mpath) as f:
            kept = [e for e in json.load(f) if (e.get("database"), e.get("arm")) not in
                    {(e2["database"], e2["arm"]) for e2 in manifest}]
        manifest = kept + manifest
    manifest.sort(key=lambda e: (e["database"], e["arm"]))
    with open(mpath, "w") as f:
        json.dump(manifest, f, indent=1)

    print(f"\n{len(by_db)} files + MANIFEST.json ({len(manifest)} entries) in {outdir}")


if __name__ == "__main__":
    main()
