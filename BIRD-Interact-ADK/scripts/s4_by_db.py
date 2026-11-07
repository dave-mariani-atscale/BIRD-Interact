#!/usr/bin/env python3
"""Scenario 4 (Genie Ontology without Metric Views, dbx_genie_ontology_no_mv) per database, against
the two Sonnet 5 / Sonnet 5 baselines:

    Raw     the 2026-09-08 raw n=3 (the agent writes Postgres SQL over the base tables; no semantic layer)
    AtScale the 2026-09-10 AtScale n=3 (the workbook's "Modified Harness 09-10 Sonnet" sweep)

Each baseline is shown as its BEST run (highest mean reward over all 410 Query tasks, the
convention of three_way_by_db.best_run). Scenario 4 is shown per repetition, as its log marks them
("=== repetition k of n ==="); a database is reported once all its Query tasks have a verdict in
that repetition. Scenario 3 (Genie Ontology WITH the metric views, best of its three runs) is a
reference row.

    python scripts/s4_by_db.py                                   # every finished database, all repetitions
    python scripts/s4_by_db.py --newly-complete-since STATEFILE  # only what finished since the last call
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from three_way_by_db import HERE, VERDICT, query_tasks  # noqa: E402

RAW = [str(Path.home() / "workspace/atscale/BIRD-Interact/BIRD-Interact-ADK/results" / f) for f in (
    "full0908_raw_run01_repaired.json", "full0908_raw_run02_20260908_230318.json",
    "full0908_raw_run03_20260909_013929.json")]
ATSCALE = sorted(glob.glob(str(HERE / "results/full0910_atscale_run0[123]_*.json")))
S3 = sorted(glob.glob(str(HERE / "results/dbx_genie_ontology_vs_0910/dbx_genie_ontology_run0[123]_*.json")))
S4_LOG = HERE / "logs/dbx_genie_ontology_no_mv_vs_0910/dbx_genie_ontology_no_mv.log"
LABELS = {"dbx_genie_ontology_no_mv": "Scenario 4: Genie Ontology, no Metric Views",
          "dbx_genie_ontology_genie_mv": "Scenario 5: Genie Ontology, Genie-authored Metric Views"}
LABEL = LABELS["dbx_genie_ontology_no_mv"]


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


def s4_reps():
    """[{task: (p1, p2, reward)}] per repetition, in log order."""
    reps = []
    if not S4_LOG.exists():
        return reps
    for line in open(S4_LOG, errors="replace"):
        if "=== repetition " in line:
            reps.append({})
            continue
        m = VERDICT.search(line)
        if m:
            if not reps:
                reps.append({})
            reps[-1][m.group(1)] = (m.group(2).startswith("PASS"), m.group(2) == "PASS both phases",
                                    float(m.group(3)))
    return reps


def row(name, run, tasks):
    n = len(tasks)
    got = [run.get(t, (False, False, 0.0)) for t in tasks]
    p1 = sum(g[0] for g in got); p2 = sum(g[1] for g in got); rw = sum(g[2] for g in got)
    return f"| {name} | {n} | {p1} ({100*p1/n:.1f}%) | {p2} ({100*p2/n:.1f}%) | {rw/n:.3f} |"


def table(title, tasks, rows):
    out = [f"**{title}**", "", "| Setup | Tasks | P1 | P2 | Reward / task |", "| --- | ---: | ---: | ---: | ---: |"]
    out += [row(n, r, tasks) for n, r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--newly-complete-since")
    ap.add_argument("--backend", default="dbx_genie_ontology_no_mv", choices=sorted(LABELS),
                    help="the Genie One run to report (scenario 4 or 5)")
    a = ap.parse_args()
    global S4_LOG, LABEL
    S4_LOG = HERE / f"logs/{a.backend}_vs_0910/{a.backend}.log"
    LABEL = LABELS[a.backend]
    qt = query_tasks()
    qt_all = {t for ts in qt.values() for t in ts}
    ri, raw = best(load_runs(RAW), qt_all)
    ai, ats = best(load_runs(ATSCALE), qt_all)
    s3 = best(load_runs(S3), qt_all) if len(S3) == 3 else None
    reps = s4_reps()
    seen = set()
    state = Path(a.newly_complete_since) if a.newly_complete_since else None
    if state and state.exists():
        seen = set(json.loads(state.read_text()))
    blocks = []
    for k, rep in enumerate(reps, 1):
        done = [db for db, ts in qt.items() if all(t in rep for t in ts)]
        new = [db for db in done if f"{k}:{db}" not in seen]
        if state and not new:
            continue
        def rows(tasks_label):
            if a.backend == "dbx_genie_ontology_genie_mv":
                # Scenario 5 is reported against AtScale and Genie over the SML-based metric views (asked 2026-11-07).
                r = [(f"AtScale, Sonnet 5 / Sonnet 5 (09-10 best run, r{ai+1})", ats)]
                if s3:
                    r.append((f"Scenario 3: Genie One with SML-based Metric Views (best run, r{s3[0]+1})", s3[1]))
                r.append((f"**{LABEL} (rep {k})**", rep))
                return r
            r = [(f"Raw, Sonnet 5 / Sonnet 5 (09-08 best run, r{ri+1})", raw),
                 (f"AtScale, Sonnet 5 / Sonnet 5 (09-10 best run, r{ai+1})", ats),
                 (f"**{LABEL} (rep {k})**", rep)]
            if s3:
                r.append((f"Scenario 3: Genie Ontology with Metric Views (best run, r{s3[0]+1})", s3[1]))
            return r
        for db in (new if state else done):
            blocks.append(table(f"{db} (repetition {k} of {LABEL.split(':')[0].lower()})", qt[db], rows(db)))
        tasks = [t for db in done for t in qt[db]]
        if tasks:
            blocks.append(table(f"All {len(done)} finished databases, repetition {k} ({len(tasks)} tasks)", tasks, rows(None)))
        seen.update(f"{k}:{db}" for db in done)
    if state:
        state.write_text(json.dumps(sorted(seen)))
    print("\n\n".join(blocks))


if __name__ == "__main__":
    main()
