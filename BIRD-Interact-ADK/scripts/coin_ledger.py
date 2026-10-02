#!/usr/bin/env python3
"""Coin ledger for P1-pass / P2-fail tasks, $0 (no LLM, no gold reads beyond gold_diff verdict files).

    python scripts/coin_ledger.py <by_database_dir> <per_task.csv> <gold_diff_sweep_dir> [--suffix _r5] > ledger.tsv

One TSV row per task that passed phase 1 and failed phase 2: P1 coins by tool, coins entering P2,
P2 actions, whether P2 submitted, main's P2 record, and the P2 FINDING bucket from the stored sweep.
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import os
import re

TOOLS = ["list_models", "explore_columns", "focus_columns", "run_query", "ask_user", "submit_sql"]


def bucket(block: str) -> str:
    if "REFUSED: no phase-2 submission" in block:
        return "no-submit"
    m = re.search(r"^FINDING: ([A-Z][A-Z ]+?)(?: —|$)", block, re.M)
    f = m.group(1).strip() if m else "?"
    if f.startswith("COLUMN") or "COLUMNS" in f:
        return "column-set" if f != "COLUMN ORDER" else "column-order"
    if f.startswith("ROW COUNT") or f.startswith("SHAPE"):
        return "grain-or-rowcount"
    if f.startswith("ROW ORDER"):
        return "order"
    if f.startswith("VALUES ROUNDING"):
        return "rounding"
    if f.startswith("VALUES"):
        return "values"
    if f.startswith("EXECUTION"):
        return "exec-error"
    return f.lower().replace(" ", "-")


def sweep_blocks(path: str) -> dict:
    out, cur, buf = {}, None, []
    for line in open(path):
        m = re.match(r"=== (\S+)", line)
        if m:
            if cur:
                out[cur] = "".join(buf)
            cur, buf = m.group(1), []
        buf.append(line)
    if cur:
        out[cur] = "".join(buf)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("by_database")
    ap.add_argument("per_task")
    ap.add_argument("sweep")
    ap.add_argument("--suffix", default="_r5")
    a = ap.parse_args()
    main_p2 = {r["task_id"]: [r[f"main_r{i}_P2"] for i in (1, 2, 3)] for r in csv.DictReader(open(a.per_task))}
    cols = (["task_id", "database", "start", "p1_spent"] + [f"p1_{t}" for t in TOOLS]
            + ["p1_failed_submits", "p1_asks", "entering_p2", "p2_actions", "p2_asks", "p2_submits",
               "p2_submitted", "end_coins", "main_p2", "main_fails_p2", "p2_bucket", "p2_finding"])
    print("\t".join(cols))
    for f in sorted(glob.glob(os.path.join(a.by_database, f"*{a.suffix}.json"))):
        db = os.path.basename(f)[: -len(a.suffix) - 5]
        blocks = sweep_blocks(os.path.join(a.sweep, f"{db}_p2.txt"))
        for t in json.load(open(f))["results"]:
            if not (t.get("phase1_passed") and t.get("has_follow_up") and not t.get("phase2_passed")):
                continue
            tools = [s for s in t.get("tool_trajectory") or [] if s.get("type") == "tool"]
            start = float(tools[0]["budget_before"]) if tools else 0.0
            p1 = collections.Counter()
            p1_fail = p1_asks = 0
            p2 = []
            entering = None
            for s in tools:
                if entering is None:
                    p1[s["tool"]] += float(s.get("cost", 0))
                    if s["tool"] == "ask_user":
                        p1_asks += 1
                    if s["tool"] == "submit_sql":
                        if "Phase 1 correct" in str(s.get("result")):
                            entering = float(s["budget_after"])
                        else:
                            p1_fail += 1
                else:
                    p2.append(s["tool"])
            blk = blocks.get(t["task_id"], "")
            fm = re.search(r"^FINDING: (.*)$", blk, re.M)
            mp = main_p2.get(t["task_id"], ["", "", ""])
            row = [t["task_id"], db, f"{start:g}", f"{sum(p1.values()):g}"] + [f"{p1[x]:g}" for x in TOOLS]
            row += [str(p1_fail), str(p1_asks), f"{entering:g}" if entering is not None else "?",
                    " ".join(p2) or "-", str(p2.count("ask_user")), str(p2.count("submit_sql")),
                    "1" if "submit_sql" in p2 else "0", f"{float(t.get('budget_remaining') or 0):g}",
                    "".join(mp), "1" if mp.count("1") < 2 else "0", bucket(blk),
                    (fm.group(1)[:120] if fm else "").replace("\t", " ")]
            print("\t".join(row))


if __name__ == "__main__":
    main()
