"""Harvest raw-Postgres agent SQL into an AO query-log CSV.

Usage: python scripts/ao/harvest_sql.py <out.csv> <run_raw.json>... [--db exchange_traded_funds]
                                         [--exclude-tasks id,id,...] [--block REGEX]
Keeps execute_sql statements against the warehouse (schema public, unqualified) from tasks of --db.
Firewall: submit_sql results carry grader verdicts, so submitted statements are dropped, and so is
any execute_sql statement identical to a submitted one (across all given runs). Also drops errored
statements, anything naming the semantic layer, and every statement from --exclude-tasks (the
scored tasks, for a held-out log). Dedups; `count` is occurrences across runs.
"""

import argparse
import csv
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

BLOCKED = re.compile(r"bird_models|exchange traded funds", re.I)


def norm(step: dict) -> str:
    return " ".join((step["args"].get("sql") or step["args"].get("query") or "").split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--db", default="exchange_traded_funds")
    ap.add_argument("--exclude-tasks", default="")
    ap.add_argument("--block", default="", help="extra regex; matching statements are dropped "
                    "(e.g. relations created by task solutions, absent from a clean warehouse)")
    a = ap.parse_args()
    extra = re.compile(a.block, re.I) if a.block else None
    excluded = {t for t in a.exclude_tasks.split(",") if t}

    tasks = []  # (run file, finished iso, task result)
    for src in a.runs:
        run = json.load(open(src))
        end = datetime.fromtimestamp(run.get("run_finished") or os.path.getmtime(src), timezone.utc).isoformat()
        for r in run["results"]:
            if (r.get("instance_id") or "").startswith(a.db + "_"):
                tasks.append((src, end, r))
    steps = [s for _, _, r in tasks for s in r["tool_trajectory"]]
    submitted = {norm(s) for s in steps if s.get("tool") == "submit_sql"}

    counts: Counter[str] = Counter()
    first: dict[str, tuple[str, str]] = {}
    dropped: Counter[str] = Counter()
    for src, end, r in tasks:
        held_out = r["instance_id"] not in excluded
        for s in r["tool_trajectory"]:
            if s.get("tool") != "execute_sql":
                continue
            sql = norm(s)
            if not sql:
                continue
            if not held_out:
                dropped["scored_task"] += 1
            elif sql in submitted:
                dropped["submitted"] += 1
            elif BLOCKED.search(sql):
                dropped["semantic_layer"] += 1
            elif extra and extra.search(sql):
                dropped["blocked"] += 1
            elif re.match(r"\s*(error|sql error|query failed)", str(s.get("result", "")), re.I):
                dropped["errored"] += 1
            else:
                counts[sql] += 1
                first.setdefault(sql, (end, src.rsplit("/", 1)[-1].removesuffix(".json")))
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["query_text", "end_time", "count", "source"])
        for q, n in counts.items():
            w.writerow([q, first[q][0], n, first[q][1]])
    print(f"runs {len(a.runs)}, tasks {len({r['instance_id'] for _, _, r in tasks})}; "
          f"written {len(counts)} distinct statements; dropped {dict(dropped)}")


if __name__ == "__main__":
    main()
