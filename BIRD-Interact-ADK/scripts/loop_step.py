#!/usr/bin/env python3
"""One screen per task: everything the per-task loop needs to read after a run, $0.

    python scripts/loop_step.py <results.json> [task_id ...] [--no-gold]

For each task (default: every task in the file) it prints about 15 lines:
verdicts and coins, the asks and answers, each submitted WHERE clause with its
verdict, the first focus_columns call, the gold_diff FINDING line per failed
phase, and a MECHANISM line - whether the trajectory shows an ask, a filter or
a projection you can name with --expect.

Why this exists (docs/bird-database-testing-prompt.md, step 1.4): the loop's
reader must see the trajectory, not the score, and must confirm that a fix's
mechanism fired. Reading failing_sql.py, gold_diff.py and the coin trail by hand
costs the expensive model ~20k tokens per iteration; this is ~1k. It makes no
LLM calls and never prints gold SQL (gold_diff.py's guarantee, reused as-is).

    --expect "ask:Fault Prediction Score Tier"   ask text must contain this
    --expect "filter:Has Performance Record"     a submitted WHERE must contain this
    --expect "project:Precision Degradation On"  a submitted SELECT list must contain this
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _tools(task):
    return [s for s in task.get("tool_trajectory") or [] if s.get("type") == "tool"]


def _where(sql: str) -> str:
    i = sql.upper().find("WHERE")
    return re.sub(r"\s+", " ", sql[i:] if i >= 0 else "(no WHERE)")[:150]


def _select_list(sql: str) -> str:
    m = re.search(r"SELECT\s+(.*?)\s+FROM\s", sql, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1))[:150] if m else ""


def gold_finding(results_path: str, task_id: str, phase: int) -> str:
    """The FINDING line from gold_diff for one phase, or a one-line error."""
    cmd = [sys.executable, os.path.join(HERE, "gold_diff.py"), "--results", results_path,
           task_id, "--phase", str(phase)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                             cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT}).stdout
    except subprocess.TimeoutExpired:
        return "gold_diff timed out"
    lines = [l.strip() for l in out.splitlines() if l.startswith(("FINDING", "shape:", "  "))]
    return " | ".join(lines[:3])[:300] if lines else "(no finding)"


def report(results_path: str, task, want_gold: bool, expects):
    tid = task["task_id"]
    tools = _tools(task)
    p1, p2 = int(bool(task.get("phase1_passed"))), int(bool(task.get("phase2_passed")))
    start = tools[0]["budget_before"] if tools else "?"
    coins = collections.Counter()
    for s in tools:
        coins[s["tool"]] += s.get("cost", 0)
    out = [f"== {tid}  P1={p1} P2={p2} reward={task.get('total_reward')}  coins {start}->{task.get('budget_remaining')}  "
           + " ".join(f"{k}={v:g}" for k, v in coins.items())]
    first = next((s for s in tools if s["tool"] == "focus_columns"), None)
    if first:
        out.append(f"   first focus: {first.get('args', {}).get('columns')}")
    asks = [m for m in task.get("dialogue_history") or []]
    for m in asks:
        role = m.get("role") or m.get("speaker")
        out.append(f"   [{role}] {str(m.get('content') or m.get('text'))[:170]}")
    phase = 1
    for s in tools:
        if s["tool"] == "submit_sql":
            sql = (s.get("args") or {}).get("sql") or ""
            res = str(s.get("result") or "")
            verdict = "PASS" if "correct!" in res.lower() and "failed" not in res.lower() else "fail"
            out.append(f"   submit p{phase} {verdict}: {_where(sql)}")
            if "Phase 1 correct" in res:
                phase = 2
    if want_gold:
        if not p1:
            out.append(f"   gold p1: {gold_finding(results_path, tid, 1)}")
        elif task.get("has_follow_up") and not p2:
            out.append(f"   gold p2: {gold_finding(results_path, tid, 2)}")
    if expects:
        hits = []
        asks_text = " ".join(str(m.get("content") or m.get("text")) for m in asks
                             if (m.get("role") or m.get("speaker")) == "agent")
        wheres = " ".join(_where((s.get("args") or {}).get("sql") or "") for s in tools if s["tool"] == "submit_sql")
        selects = " ".join(_select_list((s.get("args") or {}).get("sql") or "") for s in tools if s["tool"] == "submit_sql")
        for e in expects:
            kind, _, needle = e.partition(":")
            hay = {"ask": asks_text, "filter": wheres, "project": selects}.get(kind, "")
            hits.append(f"{e} -> {'FIRED' if needle.lower() in hay.lower() else 'did not fire'}")
        out.append("   MECHANISM: " + "; ".join(hits))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("task_ids", nargs="*")
    ap.add_argument("--no-gold", action="store_true", help="skip gold_diff (faster, no Postgres)")
    ap.add_argument("--expect", action="append", default=[],
                    help="ask:<text> | filter:<text> | project:<text>; repeatable")
    a = ap.parse_args()
    run = json.load(open(a.results))
    tasks = run["results"] if isinstance(run, dict) else run
    if a.task_ids:
        tasks = [t for t in tasks if t["task_id"] in a.task_ids or t["task_id"].split("_")[-1] in a.task_ids]
    hdr = run if isinstance(run, dict) else {}
    print(f"# {a.results}  backend={hdr.get('backend')} regime={hdr.get('deviations_as_graded', {}).get('regime')} "
          f"memory={(hdr.get('deviations') if isinstance(hdr.get('deviations'), dict) else {}).get('feedback_memory')} agent={str(hdr.get('agent_model'))[:40]}")
    for t in sorted(tasks, key=lambda x: int(x["task_id"].split("_")[-1])):
        print(report(a.results, t, not a.no_gold, a.expect))


if __name__ == "__main__":
    main()
