"""Harvest the raw-Postgres arm's agent SQL into an AO query-log CSV.

Usage: python scripts/ao/harvest_sql.py <run_raw.json> <out.csv>
Keeps execute_sql statements against the warehouse (schema public, unqualified).
Firewall: submit_sql results carry grader verdicts, so submitted statements are
dropped, and so is any execute_sql statement identical to a submitted one.
Also drops errored statements and anything naming the semantic layer; dedups.
"""

import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone

BLOCKED = re.compile(r"bird_models|exchange traded funds", re.I)


def norm(step: dict) -> str:
    return " ".join((step["args"].get("sql") or step["args"].get("query") or "").split())


def main(src: str, out: str) -> None:
    run = json.load(open(src))
    end = datetime.fromtimestamp(run["run_finished"], timezone.utc).isoformat()
    steps = [s for r in run["results"] for s in r["tool_trajectory"]]
    submitted = {norm(s) for s in steps if s.get("tool") == "submit_sql"}
    counts: Counter[str] = Counter()
    dropped = Counter()
    for s in steps:
        if s.get("tool") != "execute_sql":
            continue
        sql = norm(s)
        if not sql:
            continue
        if sql in submitted:
            dropped["submitted"] += 1
            continue
        if BLOCKED.search(sql):
            dropped["semantic_layer"] += 1
            continue
        if re.match(r"\s*(error|sql error|query failed)", str(s.get("result", "")), re.I):
            dropped["errored"] += 1
            continue
        counts[sql] += 1
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["query_text", "end_time", "count", "source"])
        for q, n in counts.items():
            w.writerow([q, end, n, "run_raw_ref_20261006_144917"])
    print(f"written {len(counts)} distinct statements; dropped {dict(dropped)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
