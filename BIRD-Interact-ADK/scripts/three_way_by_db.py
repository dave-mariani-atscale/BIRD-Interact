#!/usr/bin/env python3
"""Per-database, side by side: the AtScale 09-10 sweep, the Databricks metric-view arm
(Sonnet writes the SQL) and the Databricks Genie-space arm (Genie writes the SQL), on the
databases BOTH Databricks runs have finished.

    python scripts/three_way_by_db.py            # table of every database finished in both runs
    python scripts/three_way_by_db.py --newly-complete-since STATEFILE   # print only databases
                                                  # that completed since the last call (for a watcher)

AtScale is shown as its BEST run, the leaderboard convention: the run of the 09-10 sweep
with the highest reward over all 410 tasks (run 3), fixed once rather than re-picked per
database. Genie's P1 is also shown views-only: a pass counts only if
the SQL that passed read nothing but metric views (from the Genie run's grading audit).
Query tasks are selected by category from the task file.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
MV_LOG = Path.home() / "workspace/atscale/BIRD-Interact-dbx-run/BIRD-Interact-ADK/logs/dbx_vs_0910/dbx_metric_views.log"
GS_LOG = HERE / "logs/dbx_genie_space_vs_0910/dbx_genie_space.log"
GS_AUDIT = HERE / "results/grading_audit.jsonl"
BASE = sorted(glob.glob(str(HERE / "results/full0910_atscale_run0[123]_*.json")))
DATA = HERE / "bird-interact-full/bird_interact_data.jsonl"
VERDICT = re.compile(r"<== (\S+): (PASS both phases|PASS phase 1|fail|error)\s+reward=([0-9.]+)")


def query_tasks() -> dict:
    out = collections.defaultdict(list)
    for l in open(DATA):
        t = json.loads(l)
        if t.get("category") == "Query":
            out[t["selected_database"]].append(t["instance_id"])
    return out


def from_log(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in open(path, errors="replace"):
        m = VERDICT.search(line)
        if m:
            out[m.group(1)] = (m.group(2).startswith("PASS"), m.group(2) == "PASS both phases", float(m.group(3)))
    return out


def run_start(path: Path) -> float:
    import datetime as dt
    for l in open(path, errors="replace"):
        if re.match(r"\d{4}-\d{2}-\d{2} ", l):
            return dt.datetime.strptime(l[:19], "%Y-%m-%d %H:%M:%S").timestamp() - 60
    return 0.0


def genie_views_only(tasks: set) -> dict:
    """task -> True if its phase-1 PASSING submission read only metric views."""
    out = {}
    if not GS_AUDIT.exists():
        return out
    since = run_start(GS_LOG) if GS_LOG.exists() else 0
    for l in open(GS_AUDIT):
        r = json.loads(l)
        if r.get("backend") != "dbx_genie_space" or r.get("ts", 0) < since or r.get("task_id") not in tasks:
            continue
        if r.get("phase") == 1 and r.get("passed"):
            out[r["task_id"]] = r.get("reads_base_tables") is False
    return out


def baseline() -> list:
    runs = []
    for p in BASE:
        d = json.load(open(p))
        runs.append({r["instance_id"]: (bool(r.get("phase1_passed")), bool(r.get("phase2_passed")),
                                        float(r.get("total_reward") or 0)) for r in d["results"]})
    return runs


def best_run(base: list) -> int:
    """Index of the baseline run with the highest mean reward over ALL its Query tasks."""
    qt = {t for ts in query_tasks().values() for t in ts}
    def mean_reward(run):
        rs = [v[2] for t, v in run.items() if t in qt]
        return sum(rs) / max(len(rs), 1)
    return max(range(len(base)), key=lambda i: mean_reward(base[i]))


def complete_dbs(qt, mv, gs) -> list:
    return [db for db, ts in qt.items() if all(t in mv for t in ts) and all(t in gs for t in ts)]


def pct(k, n):
    return f"{100 * k / n:.0f}%" if n else "-"


def table(dbs, qt, mv, gs, base) -> str:
    vo = genie_views_only({t for db in dbs for t in qt[db]})
    bi = best_run(base)
    r1 = base[bi]
    head = (f"| Database | Tasks | AtScale P1 (best, r{bi + 1}) | Metric views P1 | Genie P1 | Genie P1, views only "
            "| AtScale P2 | Metric views P2 | Genie P2 | AtScale reward | Metric views reward | Genie reward |")
    lines = [head, "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    tot = collections.Counter()
    for db in dbs:
        ts = qt[db]; n = len(ts)
        a1 = sum(r1[t][0] for t in ts); m1 = sum(mv[t][0] for t in ts); g1 = sum(gs[t][0] for t in ts)
        gv = sum(1 for t in ts if gs[t][0] and vo.get(t))
        a2 = sum(r1[t][1] for t in ts); m2 = sum(mv[t][1] for t in ts); g2 = sum(gs[t][1] for t in ts)
        ar = sum(r1[t][2] for t in ts); mr = sum(mv[t][2] for t in ts); gr = sum(gs[t][2] for t in ts)
        for k, v in (("n", n), ("a1", a1), ("m1", m1), ("g1", g1), ("gv", gv), ("a2", a2), ("m2", m2), ("g2", g2)):
            tot[k] += v
        tot["ar"] += ar; tot["mr"] += mr; tot["gr"] += gr
        lines.append(f"| {db} | {n} | {pct(a1,n)} | {pct(m1,n)} | {pct(g1,n)} | {pct(gv,n)} | {pct(a2,n)} | "
                     f"{pct(m2,n)} | {pct(g2,n)} | {ar/n:.2f} | {mr/n:.2f} | {gr/n:.2f} |")
    n = tot["n"]
    if n:
        lines.append(f"| **All {len(dbs)} finished** | **{n}** | **{pct(tot['a1'],n)}** | "
                     f"**{pct(tot['m1'],n)}** | **{pct(tot['g1'],n)}** | **{pct(tot['gv'],n)}** | **{pct(tot['a2'],n)}** | "
                     f"**{pct(tot['m2'],n)}** | **{pct(tot['g2'],n)}** | **{tot['ar']/n:.2f}** | **{tot['mr']/n:.2f}** | "
                     f"**{tot['gr']/n:.2f}** |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--newly-complete-since", metavar="STATEFILE")
    a = ap.parse_args()
    qt, mv, gs, base = query_tasks(), from_log(MV_LOG), from_log(GS_LOG), baseline()
    done = complete_dbs(qt, mv, gs)
    order = [db for db in qt if db in done]      # task-file order = run order
    if a.newly_complete_since:
        st = Path(a.newly_complete_since)
        seen = set(json.loads(st.read_text())) if st.exists() else set()
        new = [db for db in order if db not in seen]
        st.write_text(json.dumps(sorted(set(order))))
        for db in new:
            print(f"database complete in all three: {db} ({len(order)} of {len(qt)} databases)")
        return
    print(f"Databases finished in both Databricks runs: {len(order)} of {len(qt)}  "
          f"(metric-view run {len(mv)} tasks, Genie-space run {len(gs)} tasks)\n")
    print(table(order, qt, mv, gs, base) if order else "none yet")


if __name__ == "__main__":
    main()
