#!/usr/bin/env python3
"""The three Genie One scenarios per database, against AtScale (consolidated 2026-11-08).

    1 Genie One on raw data (no Metric Views)        dbx_genie_ontology_no_mv
    2 Genie One + Genie-generated Metric Views       dbx_genie_ontology_genie_mv
    3 Genie One + AtScale-generated Metric Views     dbx_genie_ontology

For the scenario named by --backend, each repetition (the log marks them "=== repetition k of n ===")
is reported per database once all its Query tasks have a verdict, next to the AtScale 09-10 sweep and
the other two scenarios. AtScale and the other scenarios are shown as their BEST run (highest mean
reward over all 410 Query tasks, the convention of three_way_by_db.best_run); a scenario without a
complete run file is left out. --with-raw adds the 2026-09-08 raw Sonnet 5 / Sonnet 5 run.

    python scripts/genie_one_by_db.py --backend dbx_genie_ontology_genie_mv
    python scripts/genie_one_by_db.py --backend dbx_genie_ontology_no_mv --newly-complete-since STATEFILE
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from three_way_by_db import HERE, VERDICT, query_tasks  # noqa: E402

SCENARIOS = {   # backend -> (number, label)
    "dbx_genie_ontology_no_mv": (1, "Genie One on raw data (no Metric Views)"),
    "dbx_genie_ontology_genie_mv": (2, "Genie One + Genie-generated Metric Views"),
    "dbx_genie_ontology": (3, "Genie One + AtScale-generated Metric Views"),
}
RAW = [str(Path.home() / "workspace/atscale/BIRD-Interact/BIRD-Interact-ADK/results" / f) for f in (
    "full0908_raw_run01_repaired.json", "full0908_raw_run02_20260908_230318.json",
    "full0908_raw_run03_20260909_013929.json")]
ATSCALE = sorted(glob.glob(str(HERE / "results/full0910_atscale_run0[123]_*.json")))


def run_files(backend):
    return sorted(glob.glob(str(HERE / f"results/{backend}_vs_0910/{backend}_run0[123]_*.json")))


def load_runs(paths):
    runs = []
    for p in paths:
        d = json.load(open(p))
        runs.append({(r.get("instance_id") or r["task_id"]): (bool(r.get("phase1_passed")), bool(r.get("phase2_passed")),
                                                             float(r.get("total_reward") or 0)) for r in d["results"]})
    return runs


def best(runs, qt_all):
    def mean(run):
        rs = [v[2] for t, v in run.items() if t in qt_all]
        return sum(rs) / max(len(rs), 1)
    i = max(range(len(runs)), key=lambda k: mean(runs[k]))
    return i, runs[i]


def reps_from_log(log: Path):
    """[{task: (p1, p2, reward)}] per repetition, in log order."""
    reps = []
    if not log.exists():
        return reps
    for line in open(log, errors="replace"):
        if "=== repetition " in line:
            reps.append({})
            continue
        m = VERDICT.search(line)
        if m:
            if not reps:
                reps.append({})
            reps[-1][m.group(1)] = (m.group(2).startswith("PASS"), m.group(2) == "PASS both phases", float(m.group(3)))
    return reps


def row(name, run, tasks):
    n = len(tasks)
    got = [run.get(t, (False, False, 0.0)) for t in tasks]
    p1 = sum(g[0] for g in got); p2 = sum(g[1] for g in got); rw = sum(g[2] for g in got)
    return f"| {name} | {n} | {p1} ({100*p1/n:.1f}%) | {p2} ({100*p2/n:.1f}%) | {rw/n:.3f} |"


def table(title, tasks, rows):
    out = [f"**{title}**", "", "| Setup | Tasks | P1 | P2 | Reward / task |", "| --- | ---: | ---: | ---: | ---: |"]
    return "\n".join(out + [row(n, r, tasks) for n, r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=sorted(SCENARIOS))
    ap.add_argument("--newly-complete-since")
    ap.add_argument("--with-raw", action="store_true")
    a = ap.parse_args()
    qt = query_tasks()
    qt_all = {t for ts in qt.values() for t in ts}
    num, label = SCENARIOS[a.backend]
    fixed = []
    if a.with_raw:
        ri, raw = best(load_runs(RAW), qt_all)
        fixed.append((f"Raw, Sonnet 5 / Sonnet 5 (09-08 best run, r{ri+1})", raw))
    ai, ats = best(load_runs(ATSCALE), qt_all)
    fixed.append((f"AtScale, Sonnet 5 / Sonnet 5 (09-10 best run, r{ai+1})", ats))
    for b, (n, lab) in sorted(SCENARIOS.items(), key=lambda kv: kv[1][0]):
        if b == a.backend:
            continue
        runs = [r for r in load_runs(run_files(b)) if len(r) >= len(qt_all)]
        if runs:
            k, r = best(runs, qt_all)
            fixed.append((f"Scenario {n}: {lab} (best of {len(runs)}, r{k+1})", r))
    reps = reps_from_log(HERE / f"logs/{a.backend}_vs_0910/{a.backend}.log")
    state = Path(a.newly_complete_since) if a.newly_complete_since else None
    seen = set(json.loads(state.read_text())) if state and state.exists() else set()
    blocks = []
    for k, rep in enumerate(reps, 1):
        done = [db for db, ts in qt.items() if all(t in rep for t in ts)]
        new = [db for db in done if f"{k}:{db}" not in seen]
        if state and not new:
            continue
        rows = fixed + [(f"**Scenario {num}: {label} (rep {k})**", rep)]
        for db in (new if state else done):
            blocks.append(table(f"{db} (repetition {k} of scenario {num})", qt[db], rows))
        tasks = [t for db in done for t in qt[db]]
        if tasks:
            blocks.append(table(f"All {len(done)} finished databases, repetition {k} ({len(tasks)} tasks)", tasks, rows))
        seen.update(f"{k}:{db}" for db in done)
    if state:
        state.write_text(json.dumps(sorted(seen)))
    print("\n\n".join(blocks))


if __name__ == "__main__":
    main()
