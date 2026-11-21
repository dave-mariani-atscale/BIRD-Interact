"""Live comparison of a Snowflake Cortex Sense run against the Databricks Genie One scenarios and the
2026-09-10 AtScale Sonnet 5 sweep, on the tasks the Snowflake repetition in progress has finished.

Rows: the Snowflake repetition in progress (from its log), then each baseline's best run and its 3-run
mean, restricted to the same tasks. Columns: tasks, P1, P2 (passes of both phases), reward.
A per-database table follows.

    .venv-adk/bin/python scripts/sf_vs_genie_atscale.py [--backend sf_cortex_sense_raw] [--by-db]
"""
import argparse
import glob
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENIE = Path.home() / "workspace/atscale/BIRD-Interact-genie-space/BIRD-Interact-ADK/results"
BASELINES = [
    ("AtScale (Sonnet 5, 09-10)", str(ROOT / "results/full0910_atscale_run0[123]_*.json")),
    ("Genie S1 raw data", str(GENIE / "dbx_genie_ontology_no_mv_vs_0910/dbx_genie_ontology_no_mv_run0[123]_*.json")),
    ("Genie S2 + Genie views", str(GENIE / "dbx_genie_ontology_genie_mv_vs_0910/dbx_genie_ontology_genie_mv_run0[123]_*.json")),
    ("Genie S3 + AtScale views", str(GENIE / "dbx_genie_ontology_vs_0910/dbx_genie_ontology_run0[123]_*.json")),
]
VERDICT = re.compile(r"<== (\S+): (PASS both phases|PASS phase 1|fail|error)\s+reward=([0-9.]+)")
REP = re.compile(r"=== repetition (\d+) of (\d+) ===")


def truthy(v):
    return str(v).lower() == "true"


def load_run(path):
    d = json.load(open(path))
    out = {}
    for t in d.get("results") or d.get("tasks") or []:
        out[t["task_id"]] = (truthy(t.get("phase1_passed")), truthy(t.get("phase2_passed")),
                             float(t.get("total_reward") or 0), t.get("database") or t["task_id"].rsplit("_", 1)[0])
    return out


def live(log):
    """Per task (p1, p2, reward, db) for the repetition in progress, and its label."""
    text = Path(log).read_text(errors="replace")
    reps = list(REP.finditer(text))
    label = f"repetition {reps[-1].group(1)} of {reps[-1].group(2)}" if reps else "repetition 1"
    if reps:
        text = text[reps[-1].end():]
    out = {}
    for m in VERDICT.finditer(text):
        tid, verdict, reward = m.group(1), m.group(2), float(m.group(3))
        out[tid] = (verdict.startswith("PASS"), verdict == "PASS both phases", reward, tid.rsplit("_", 1)[0])
    return out, label


def score(run, tasks):
    n = len(tasks)
    if not n:
        return None
    p1 = sum(run[t][0] for t in tasks) / n
    p2 = sum(run[t][1] for t in tasks) / n
    rw = sum(run[t][2] for t in tasks) / n
    return n, p1, p2, rw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="sf_cortex_sense_raw")
    ap.add_argument("--by-db", action="store_true")
    ap.add_argument("--wait-new-db", metavar="STATEFILE",
                    help="block until a database not listed in STATEFILE has all its tasks finished, update "
                         "STATEFILE, print the comparison and exit (for a background watcher)")
    a = ap.parse_args()
    log = ROOT / f"logs/{a.backend}_vs_0910/{a.backend}.log"
    if a.wait_new_db:
        import time
        per_db = defaultdict(int)
        for t in load_run(sorted(glob.glob(BASELINES[0][1]))[0]).values():
            per_db[t[3]] += 1
        state = Path(a.wait_new_db)
        seen = set(json.loads(state.read_text())) if state.exists() else set()
        while True:
            cur, label = live(log)
            done = defaultdict(int)
            for t in cur.values():
                done[t[3]] += 1
            complete = {db for db, n in per_db.items() if done[db] >= n}
            key = {f"{label}:{db}" for db in complete}
            new = key - seen
            if new:
                state.write_text(json.dumps(sorted(seen | key)))
                print("Newly complete:", ", ".join(sorted(k.split(":", 1)[1] for k in new)), f"({label})\n")
                break
            parts = label.split()               # "repetition k of n"
            text = log.read_text(errors="replace")
            last_rep = list(REP.finditer(text))
            tail = text[last_rep[-1].end():] if last_rep else text
            if parts[1] == parts[-1] and "Done! Tasks" in tail:
                print("Run finished.\n"); break
            time.sleep(60)
        a.by_db = True
    cur, label = live(log)
    tasks = sorted(cur)
    if not tasks:
        print(f"No task has finished yet in the Snowflake {label}.")
        return
    rows = [(f"Snowflake Cortex Sense ({label})", score(cur, tasks))]
    base_runs = {}
    for name, pattern in BASELINES:
        runs = [load_run(p) for p in sorted(glob.glob(pattern))]
        common = [t for t in tasks if all(t in r for r in runs)]
        scored = [score(r, common) for r in runs]
        if not scored or not common:
            continue
        # The best run is fixed over all of the baseline's tasks (as in the reports so far), not
        # re-picked on the subset finished here, which would favour the baseline.
        full = [score(r, sorted(r)) for r in runs]
        best = max(range(len(full)), key=lambda i: (full[i][1], full[i][3]))
        mean = tuple(sum(s[k] for s in scored) / len(scored) for k in (1, 2, 3))
        rows.append((f"{name} best run (r{best + 1})", scored[best]))
        rows.append((f"{name} mean of {len(scored)}", (len(common),) + mean))
        base_runs[name] = (runs, best)
    print(f"{len(tasks)} tasks finished in the Snowflake {label}; baselines restricted to the same tasks.\n")
    print(f"{'':44} {'tasks':>5} {'P1':>7} {'P2':>7} {'reward':>7}")
    for name, s in rows:
        print(f"{name:44} {s[0]:>5} {s[1]:>6.1%} {s[2]:>6.1%} {s[3]:>7.3f}")
    if a.by_db:
        by = defaultdict(list)
        for t in tasks:
            by[cur[t][3]].append(t)
        names = ["Snowflake"] + [n.split(" (")[0] for n in base_runs]
        print(f"\nP1 / P2 by database (baselines: best run)\n{'database':34} {'n':>3} " + " ".join(f"{n[:17]:>17}" for n in names))
        for db in sorted(by):
            ts = by[db]
            cells = []
            s = score(cur, ts)
            cells.append(f"{s[1]:>7.0%} /{s[2]:>6.0%}  ")
            for name, (runs, best) in base_runs.items():
                common = [t for t in ts if t in runs[best]]
                s = score(runs[best], common)
                cells.append(f"{s[1]:>7.0%} /{s[2]:>6.0%}  " if s else f"{'-':>17}")
            print(f"{db:34} {len(ts):>3} " + " ".join(cells))


if __name__ == "__main__":
    main()
