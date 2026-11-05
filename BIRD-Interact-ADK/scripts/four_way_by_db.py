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
Scenario 3 may run several repetitions (runner --repeat; the log marks each with
"=== repetition k of n ==="): each repetition is its own column, a database is reported
per repetition as it completes, and once every repetition is done its best run (highest
mean reward over all its tasks, AtScale's convention) is shown too.
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
ROUTES = ("metric_views", "base_tables", "mixed", "elsewhere", "none", "error")
ROUTE_LABEL = {"metric_views": "views only", "base_tables": "base tables only", "mixed": "views + tables",
               "elsewhere": "outside the database", "none": "no SQL / unparsed", "error": "Genie error"}
TURN_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*ask_genie route: db=(\S+) route=(\S+)")


REP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*=== repetition (\d+) of (\d+) ===")
VERDICT_RE = re.compile(r"<== (\S+): (PASS both phases|PASS phase 1|fail|error)\s+reward=([0-9.]+)")


def ontology_reps(path: Path = GO_LOG):
    """([per-repetition {task: (p1, p2, reward)}], [repetition start ts], total repetitions)."""
    reps, starts, total = [{}], [run_start(path) if path.exists() else 0.0], 1
    if not path.exists():
        return reps, starts, total
    first = True
    for line in open(path, errors="replace"):
        m = REP_RE.match(line)
        if m:
            total = int(m.group(3))
            ts = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
            if first:
                starts[0] = ts
                first = False
            else:
                reps.append({}); starts.append(ts)
            continue
        v = VERDICT_RE.search(line)
        if v:
            reps[-1][v.group(1)] = (v.group(2).startswith("PASS"), v.group(2) == "PASS both phases", float(v.group(3)))
    return reps, starts, total


def route_class(read, rejected=None) -> str:
    if rejected == "other_database":
        return "elsewhere"
    if not read:
        return "none"
    if read.get("elsewhere"):
        return "elsewhere"
    v, b = bool(read.get("metric_views")), bool(read.get("base_tables"))
    return "mixed" if v and b else "metric_views" if v else "base_tables" if b else "none"


def ontology_routes(tasks: set, since: float = None, until: float = float("inf")) -> dict:
    """task -> route of its phase-1 answer (the passing submission if any, else the last
    one), over the audit rows written between `since` and `until`."""
    out, passed = {}, set()
    if not (AUDIT.exists() and GO_LOG.exists()):
        return out
    since = run_start(GO_LOG) if since is None else since
    for l in open(AUDIT):
        r = json.loads(l)
        t = r.get("task_id")
        if (r.get("backend") != "dbx_genie_ontology" or not since <= r.get("ts", 0) < until
                or t not in tasks or r.get("phase") != 1):
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


def best_rep(reps: list, qt: dict) -> int:
    alltasks = [t for ts in qt.values() for t in ts]
    return max(range(len(reps)), key=lambda i: sum(reps[i][t][2] for t in alltasks) / len(alltasks))


def tables(qt, mv, gs, reps, starts, total, base) -> str:
    bi = best_run(base); at = base[bi]
    done = [[db for db, ts in qt.items() if all(t in mv and t in gs and t in r for t in ts)] for r in reps]
    full = len(reps) == total and all(len(d) == len(qt) for d in done)
    arms = [(f"AtScale r{bi + 1} (best)", at, None), ("MV agent", mv, None), ("Genie space", gs, None)]
    arms += [(f"Genie Ontology r{k + 1}", r, set(done[k])) for k, r in enumerate(reps) if done[k]]
    if full and total > 1:
        b = best_rep(reps, qt)
        arms.append((f"Genie Ontology best (r{b + 1})", reps[b], set(qt)))
    dbs = [db for db in qt if any(a[2] and db in a[2] for a in arms)]
    out = []
    for title, idx in (("P1", 0), ("P2", 1), ("Reward / task", 2)):
        out += ["", f"### {title}", "", "| Database | Tasks | " + " | ".join(a[0] for a in arms) + " |",
                "| --- | ---: |" + " ---: |" * len(arms)]
        for db in dbs + ["__all__"]:
            cells = []
            for name, r, scope in arms:
                in_scope = [d for d in dbs if scope is None or d in scope] if db == "__all__" else (
                    [db] if scope is None or db in scope else [])
                ts = [t for d in in_scope for t in qt[d]]
                if not ts:
                    cells.append("-"); continue
                v = sum(r[t][idx] for t in ts)
                cells.append(f"{v / len(ts):.2f}" if idx == 2 else pct(v, len(ts)))
            if db == "__all__":
                n_db = len([d for d in dbs])
                out.append(f"| **All finished (per column)** | | " + " | ".join(f"**{c}**" for c in cells) + " |")
            else:
                out.append(f"| {db} | {len(qt[db])} | " + " | ".join(cells) + " |")

    out += ["", "### Genie Ontology routing: sources of each task's phase-1 answer (all repetitions)", "",
            "| Database | Task-runs | " + " | ".join(ROUTE_LABEL[r] for r in ROUTES) + " |",
            "| --- | ---: |" + " ---: |" * len(ROUTES)]
    per_db = collections.defaultdict(collections.Counter)
    by_route = collections.defaultdict(lambda: [0, 0])
    for k, r in enumerate(reps):
        if not done[k]:
            continue
        until = starts[k + 1] if k + 1 < len(starts) else float("inf")
        routes = ontology_routes({t for d in done[k] for t in qt[d]}, starts[k], until)
        for d in done[k]:
            for t in qt[d]:
                rc = routes.get(t, "none")
                per_db[d][rc] += 1; by_route[rc][0] += 1; by_route[rc][1] += r[t][0]
    for d in dbs:
        if per_db[d]:
            out.append(f"| {d} | {sum(per_db[d].values())} | " + " | ".join(str(per_db[d][r]) for r in ROUTES) + " |")
    out += ["", "| Route of the phase-1 answer | Task-runs | Genie Ontology P1 |", "| --- | ---: | ---: |"]
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
    qt, mv, gs, base = query_tasks(), from_log(MV_LOG), from_log(GS_LOG), baseline()
    reps, starts, total = ontology_reps()
    done = {f"{db}@{k + 1}" for k, r in enumerate(reps) for db, ts in qt.items()
            if all(t in mv and t in gs and t in r for t in ts)}
    if a.newly_complete_since:
        st = Path(a.newly_complete_since)
        seen = set(json.loads(st.read_text())) if st.exists() else set()
        st.write_text(json.dumps(sorted(done)))
        for key in sorted(done - seen, key=lambda x: (int(x.split("@")[1]), list(qt).index(x.split("@")[0]))):
            db, k = key.split("@")
            n_k = sum(1 for x in done if x.endswith(f"@{k}"))
            print(f"database complete: {db} in repetition {k} of {total} ({n_k} of {len(qt)} databases in that repetition)")
        return
    print(f"Genie Ontology repetitions: {len(reps)} of {total} started; tasks per repetition: "
          + ", ".join(str(len(r)) for r in reps) + f"  (MV agent {len(mv)}, Genie space {len(gs)})")
    print(tables(qt, mv, gs, reps, starts, total, base) if done else "\nnone finished yet")


if __name__ == "__main__":
    main()
