#!/usr/bin/env python3
"""Per-database, side by side: the AtScale 09-10 sweep (its BEST run) and the three Databricks
scenarios, on the databases the scenario-3 run (Genie Ontology) has finished:

    1 Metric Views + 3rd-party agent   (dbx_metric_views; Sonnet writes the SQL)
    2 Metric Views + Genie Agent       (dbx_genie_space;  Genie in a per-database space)
    3 Metric Views + Genie Ontology    (dbx_genie_ontology; Genie One over the whole workspace)

plus scenario 3's ROUTING: which sources the ontology chose for each task's phase-1 answer
(metric views only, base tables only, both, or something outside the task database) and the
pass rate by choice, from the grading audit; and the same split over every Genie turn, from
the system agent's log.

    python scripts/four_way_by_db.py                                   # markdown tables
    python scripts/four_way_by_db.py --newly-complete-since STATEFILE  # for a watcher

AtScale's best run is fixed once over all 410 tasks (see three_way_by_db.best_run).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from three_way_by_db import (GS_LOG, HERE, MV_LOG, baseline, best_run, from_log, pct,  # noqa: E402
                             query_tasks, run_start)

GO_LOG = HERE / "logs/dbx_genie_ontology_vs_0910/dbx_genie_ontology.log"
AUDIT = HERE / "results/grading_audit.jsonl"
AGENT_LOG = HERE / "logs/system_agent.out"
ROUTES = ("metric_views", "base_tables", "mixed", "elsewhere", "none", "error", "ignored_catalog", "ignored_catalog_hidden")
ROUTE_LABEL = {"metric_views": "views only", "base_tables": "base tables only", "mixed": "views + tables",
               "elsewhere": "outside the database", "none": "no SQL / unparsed", "error": "Genie error", "ignored_catalog": "redone (read bird)", "ignored_catalog_hidden": "bird query hidden"}
TURN_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*ask_genie route: db=(\S+) route=(\S+)")


def route_class(read, rejected=None) -> str:
    if rejected == "other_database":
        return "elsewhere"
    if not read:
        return "none"
    if read.get("elsewhere"):
        return "elsewhere"
    v, b = bool(read.get("metric_views")), bool(read.get("base_tables"))
    return "mixed" if v and b else "metric_views" if v else "base_tables" if b else "none"


def ontology_routes(tasks: set) -> dict:
    """task -> route of its phase-1 answer: the passing submission if any, else the last one."""
    out, passed = {}, set()
    if not (AUDIT.exists() and GO_LOG.exists()):
        return out
    since = run_start(GO_LOG)
    for l in open(AUDIT):
        r = json.loads(l)
        t = r.get("task_id")
        if r.get("backend") != "dbx_genie_ontology" or r.get("ts", 0) < since or t not in tasks or r.get("phase") != 1:
            continue
        if t in passed:
            continue
        out[t] = route_class(r.get("objects_read"), r.get("rejected"))
        if r.get("passed"):
            passed.add(t)
    return out


def turn_routes() -> collections.Counter:
    c = collections.Counter()
    if not (AGENT_LOG.exists() and GO_LOG.exists()):
        return c
    since = run_start(GO_LOG)
    for l in open(AGENT_LOG, errors="replace"):
        m = TURN_RE.match(l)
        if m and dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp() >= since:
            c[m.group(3)] += 1
    return c


def tables(dbs, qt, mv, gs, go, base) -> str:
    bi = best_run(base); at = base[bi]
    arms = (("AtScale", at), ("MV agent", mv), ("Genie space", gs), ("Genie Ontology", go))
    out = [f"### Results (AtScale = best run, r{bi + 1})", "",
           "| Database | Tasks | " + " | ".join(f"{a} P1" for a, _ in arms) + " | "
           + " | ".join(f"{a} P2" for a, _ in arms) + " | " + " | ".join(f"{a} reward" for a, _ in arms) + " |",
           "| --- | ---: |" + " ---: |" * 12]
    tot = collections.Counter()
    for db in dbs + ["__all__"]:
        ts = [t for d in dbs for t in qt[d]] if db == "__all__" else qt[db]
        n = len(ts)
        if not n:
            continue
        p1 = [sum(r[t][0] for t in ts) for _, r in arms]
        p2 = [sum(r[t][1] for t in ts) for _, r in arms]
        rw = [sum(r[t][2] for t in ts) / n for _, r in arms]
        name = f"**All {len(dbs)} finished**" if db == "__all__" else db
        cells = [pct(k, n) for k in p1] + [pct(k, n) for k in p2] + [f"{x:.2f}" for x in rw]
        if db == "__all__":
            cells = [f"**{c}**" for c in cells]
        out.append(f"| {name} | {n} | " + " | ".join(cells) + " |")

    routes = ontology_routes({t for d in dbs for t in qt[d]})
    out += ["", "### Genie Ontology routing: sources of each task's phase-1 answer", "",
            "| Database | Tasks | " + " | ".join(ROUTE_LABEL[r] for r in ROUTES) + " |",
            "| --- | ---: |" + " ---: |" * len(ROUTES)]
    by_route = collections.defaultdict(lambda: [0, 0])
    for db in dbs:
        c = collections.Counter(routes.get(t, "none") for t in qt[db])
        out.append(f"| {db} | {len(qt[db])} | " + " | ".join(str(c[r]) for r in ROUTES) + " |")
    for t in (t for d in dbs for t in qt[d]):
        r = routes.get(t, "none"); by_route[r][0] += 1; by_route[r][1] += go[t][0]
    out += ["", "| Route of the phase-1 answer | Tasks | Genie Ontology P1 |", "| --- | ---: | ---: |"]
    for r in ROUTES:
        n, k = by_route[r]
        if n:
            out.append(f"| {ROUTE_LABEL[r]} | {n} | {pct(k, n)} |")
    tc = turn_routes()
    if tc:
        n = sum(tc.values())
        out += ["", f"Every Genie turn so far ({n}): " + ", ".join(
            f"{ROUTE_LABEL.get(r, r)} {tc[r]} ({pct(tc[r], n)})" for r in ROUTES if tc[r])]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--newly-complete-since", metavar="STATEFILE")
    a = ap.parse_args()
    qt, mv, gs, go, base = query_tasks(), from_log(MV_LOG), from_log(GS_LOG), from_log(GO_LOG), baseline()
    done = [db for db, ts in qt.items() if all(t in mv and t in gs and t in go for t in ts)]
    if a.newly_complete_since:
        st = Path(a.newly_complete_since)
        seen = set(json.loads(st.read_text())) if st.exists() else set()
        st.write_text(json.dumps(sorted(done)))
        for db in (d for d in done if d not in seen):
            print(f"database complete in all four: {db} ({len(done)} of {len(qt)} databases)")
        return
    print(f"Databases finished by the Genie Ontology run: {len(done)} of {len(qt)}  "
          f"(tasks: MV agent {len(mv)}, Genie space {len(gs)}, Genie Ontology {len(go)})\n")
    print(tables(done, qt, mv, gs, go, base) if done else "none yet")


if __name__ == "__main__":
    main()
