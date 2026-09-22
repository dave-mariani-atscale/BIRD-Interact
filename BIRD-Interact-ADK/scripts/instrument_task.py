#!/usr/bin/env python3
"""Full instrumentation log for ONE a-interact task: context, tool calls, tool returns.

Written 2026-09-22 to investigate how the agent uses list_models and explore_columns.

    # 1. dump the context the agent starts with (no run, no LLM calls)
    python scripts/instrument_task.py context --backend atscale_v12 --out <file>

    # 2. after the run, render the timeline from its results JSON
    python scripts/instrument_task.py timeline --results <run.json> --task <id> --out <file>

The run itself must be made with TRAJECTORY_FULL_RESULTS=true in the SYSTEM AGENT's
environment, or every tool response over 2000 characters arrives here truncated.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

RULE = "=" * 100
SUB = "-" * 100


def _w(fh, *lines):
    for l in lines:
        fh.write(str(l) + "\n")


def dump_context(backend: str, out: str) -> None:
    """Everything that is in the agent's context BEFORE its first turn."""
    from shared.config import settings
    from system_agent.agent import build_agent

    agent = build_agent(mode="a-interact", backend=backend)
    instruction = agent.instruction

    with open(out, "w") as fh:
        _w(fh, RULE, "CONTEXT LOADED AT AGENT CONSTRUCTION", RULE, "")
        _w(fh, f"backend                 {backend}")
        _w(fh, f"agent model             {settings.system_agent_model}")
        _w(fh, f"user simulator model    {getattr(settings, 'user_sim_model', '?')}")
        _w(fh, f"patience                {getattr(settings, 'patience', '?')}")
        _w(fh, f"feedback memory (ADK)   {getattr(settings, 'feedback_memory', '?')}")
        _w(fh, f"leaderboard mode        {getattr(settings, 'leaderboard_mode', '?')}")
        _w(fh, f"temperature             0.0")
        _w(fh, "")
        _w(fh, SUB, f"SYSTEM INSTRUCTION — {len(instruction):,} characters, "
                    f"~{len(instruction)//4:,} tokens, sent on EVERY model turn", SUB)
        _w(fh, instruction, "")
        _w(fh, SUB, f"TOOL SCHEMAS — {len(agent.tools)} tools, "
                    "sent with the instruction on every model turn", SUB)
        total = 0
        for t in agent.tools:
            name = getattr(t, "name", None) or getattr(t, "__name__", str(t))
            doc = (getattr(t, "description", None)
                   or (getattr(t, "func", None) and t.func.__doc__)
                   or getattr(t, "__doc__", "") or "")
            decl = None
            for attr in ("_get_declaration", "get_declaration"):
                fn = getattr(t, attr, None)
                if callable(fn):
                    try:
                        d = fn()
                        decl = d.model_dump() if hasattr(d, "model_dump") else d
                    except Exception:
                        pass
                    break
            blob = json.dumps(decl, indent=2, default=str) if decl else "(no declaration exposed)"
            total += len(str(doc)) + len(blob)
            _w(fh, "", f"### tool: {name}", "", "description:", str(doc).strip(),
               "", "declaration:", blob)
        _w(fh, "", f"(tool descriptions + declarations: ~{total:,} characters)")
    print(f"context -> {out}  ({len(instruction):,} chars of instruction, {len(agent.tools)} tools)")


def dump_timeline(results: str, task: str, out: str) -> None:
    d = json.load(open(results))
    rows = [r for r in d.get("results", []) if r.get("instance_id") == task]
    if not rows:
        sys.exit(f"task {task} not in {results}")
    r = rows[0]

    # model-role text, keyed by position among function calls, from the ADK events
    thoughts: list[tuple[int, str]] = []
    ncalls = 0
    for e in r.get("adk_events") or []:
        c = e.get("content") or {}
        if c.get("role") != "model":
            continue
        for p in c.get("parts") or []:
            if p.get("type") == "text" and (p.get("text") or "").strip():
                thoughts.append((ncalls, p["text"].strip()))
            elif p.get("type") == "function_call":
                ncalls += 1

    traj = r.get("tool_trajectory") or []
    with open(out, "a") as fh:
        _w(fh, "", RULE, f"TASK {task}", RULE, "")
        _w(fh, f"category            {r.get('category')}")
        _w(fh, f"backend             {r.get('backend')}")
        _w(fh, f"phase 1 passed      {r.get('phase1_passed')}")
        _w(fh, f"phase 2 passed      {r.get('phase2_passed')}")
        _w(fh, f"reward              {r.get('total_reward')}")
        _w(fh, f"budget              {r.get('budget_used')} used, "
                f"{r.get('budget_remaining')} left")
        _w(fh, f"tool calls          {len(traj)}")
        counts: dict[str, int] = {}
        for s in traj:
            counts[s.get("tool", "?")] = counts.get(s.get("tool", "?"), 0) + 1
        _w(fh, f"by tool             {counts}")
        _w(fh, "")

        _w(fh, SUB, "DIALOGUE — the task text and every simulator turn, in order", SUB)
        for turn in r.get("dialogue_history") or []:
            who = turn.get("role") or turn.get("speaker") or "?"
            txt = turn.get("content") or turn.get("message") or turn.get("text") or ""
            _w(fh, f"[{who}]", txt, "")

        _w(fh, SUB, "CONTEXT ACCUMULATION — what each tool put into the conversation, and when",
           SUB)
        _w(fh, "Every response below stays in the conversation and is re-sent on every later")
        _w(fh, "model turn, so the cost of a call is its size times the turns that follow it.")
        _w(fh, "")
        _w(fh, "  #  tool              chars returned   running total   turns it is re-sent in")
        run = 0
        per_tool: dict[str, list[int]] = {}
        for i, s2 in enumerate(traj):
            n = s2.get("result_chars") or 0
            run += n
            per_tool.setdefault(s2.get("tool", "?"), []).append(n)
            _w(fh, "  %-2d %-16s %14s %15s %12d" %
               (i + 1, s2.get("tool"), f"{n:,}", f"{run:,}", len(traj) - i - 1))
        _w(fh, "")
        _w(fh, "  by tool:")
        for name, sizes in sorted(per_tool.items(), key=lambda kv: -sum(kv[1])):
            _w(fh, "    %-16s %d call(s), %s chars total, %s largest, %s mean" %
               (name, len(sizes), f"{sum(sizes):,}", f"{max(sizes):,}",
                f"{sum(sizes)//len(sizes):,}"))
        _w(fh, "")
        _w(fh, f"  instruction + tool schemas are sent on EVERY turn on top of all of this.")
        _w(fh, "")
        _w(fh, SUB, "TIMELINE — every tool call with FULL arguments and FULL response", SUB)
        for i, s in enumerate(traj):
            for at, txt in thoughts:
                if at == i:
                    _w(fh, "", f"--- agent reasoning before call {i+1} ---", txt)
            res = s.get("result", "")
            res_s = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
            declared = s.get("result_chars")
            trunc = "<truncated>" in res_s
            _w(fh, "", f"{'='*80}",
               f"CALL {i+1}/{len(traj)}  {s.get('tool')}"
               f"   cost {s.get('cost')}   budget {s.get('budget_before')} -> {s.get('budget_after')}",
               f"{'='*80}")
            _w(fh, "ARGUMENTS:")
            _w(fh, json.dumps(s.get("args"), indent=2, ensure_ascii=False))
            _w(fh, "",
               f"RESPONSE  ({len(res_s):,} chars recorded"
               + (f", {declared:,} chars sent to the agent" if declared is not None else "")
               + (" — TRUNCATED, re-run with TRAJECTORY_FULL_RESULTS=true" if trunc else "")
               + "):")
            _w(fh, res_s)
            if s.get("query_ids"):
                _w(fh, "", f"engine query ids: {s['query_ids']}")
            if s.get("query_id"):
                _w(fh, f"graded query id: {s['query_id']}")
        for at, txt in thoughts:
            if at >= len(traj):
                _w(fh, "", "--- agent reasoning after the last call ---", txt)
        _w(fh, "", SUB, "FINAL RESPONSE", SUB, r.get("final_response") or "(none)")
    print(f"timeline -> {out}  ({len(traj)} calls, by tool {counts})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("context"); c.add_argument("--backend", required=True); c.add_argument("--out", required=True)
    t = sub.add_parser("timeline"); t.add_argument("--results", required=True)
    t.add_argument("--task", required=True); t.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "context":
        dump_context(a.backend, a.out)
    else:
        dump_timeline(a.results, a.task, a.out)
