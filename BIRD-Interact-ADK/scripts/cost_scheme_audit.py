#!/usr/bin/env python3
"""Measure each tool's input and output size, in tokens, against the BIRD
submission guidelines' Universal Cost Scheme for custom agents:

    ask user = 2, submit SQL = 3, execute SQL = 1 (fixed);
    any other action: 0.5 if input < 250 tokens AND average output < 1000 tokens,
                      else 1.0.

Two sources, in this order of preference:

  --run results.json   the run's own tool_trajectory. Steps recorded since
                       2026-09-11 carry `result_chars` (the FULL response length);
                       older steps only have the 2000-character preview, which is
                       reported as a lower bound and flagged.
  --live N             re-issue N sampled calls per token-aware tool against the
                       MCP server named in settings and measure the real response.
                       Costs MCP calls, no LLM tokens.

Tokens are counted with litellm's Claude tokenizer (chars/4 if unavailable).
Prints the table and the cost the scheme implies next to the cost the harness
charges (system_agent.callbacks.effective_tool_costs), for both cost schemes.

Usage:
    PYTHONPATH=. .venv-adk/bin/python scripts/cost_scheme_audit.py --run results/full0910_atscale_run03_*.json
    PYTHONPATH=. .venv-adk/bin/python scripts/cost_scheme_audit.py --run <file> --live 40
"""
import argparse
import collections
import glob
import json
import random
import statistics
import sys

sys.path.insert(0, ".")
from shared.config import settings  # noqa: E402

FIXED = {"ask_user": 2.0, "submit_sql": 3.0, "execute_sql": 1.0, "run_query": 1.0}
INPUT_LIMIT, OUTPUT_LIMIT = 250, 1000


def tok(text: str) -> int:
    try:
        import litellm
        return litellm.token_counter(model="claude-3-5-sonnet-20241022", text=text)
    except Exception:  # noqa: BLE001
        return max(1, len(text) // 4)


def from_run(paths):
    ins, outs, lower_bound = collections.defaultdict(list), collections.defaultdict(list), collections.Counter()
    for p in paths:
        d = json.load(open(p))
        for r in d.get("results", []):
            for s in r.get("tool_trajectory") or []:
                t = s.get("tool")
                if not t:
                    continue
                ins[t].append(tok(json.dumps(s.get("args") or {})))
                if s.get("result_chars") is not None:
                    outs[t].append(tok("x" * int(s["result_chars"])))
                else:
                    txt = str(s.get("result") or "")
                    if txt.endswith("...<truncated>"):
                        lower_bound[t] += 1
                    outs[t].append(tok(txt))
    return ins, outs, lower_bound


def live_sample(paths, n, backend):
    import yaml
    from shared.mcp_client import MCPClient, MCPEndpoint
    from shared.environment_backends import get_backend_config
    cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                                bearer_token=settings.semantic_layer_mcp_token, timeout_s=120))
    domains = get_backend_config(backend).get("domains", {})
    calls = collections.defaultdict(list)
    for p in paths:
        d = json.load(open(p))
        for r in d.get("results", []):
            for s in r.get("tool_trajectory") or []:
                if s.get("tool") in ("explore_columns", "focus_columns", "list_models", "get_sml_skills"):
                    calls[s["tool"]].append((r.get("database"), s.get("args") or {}))
    random.seed(11)
    ins, outs = collections.defaultdict(list), collections.defaultdict(list)
    for tool, items in calls.items():
        for db, args in random.sample(items, min(n, len(items))):
            a = {k: v for k, v in args.items() if v}
            if tool == "explore_columns" and isinstance(a.get("search_terms"), str):
                a["search_terms"] = [a["search_terms"]]
            if tool == "get_sml_skills":
                a = {"skill_name": "query-semantic-layer"}
            elif db in domains:
                a = {**domains[db], **a}
            try:
                res = cli.call_tool(tool, a)
            except Exception as e:  # noqa: BLE001
                res = str(e)
            ins[tool].append(tok(json.dumps(args)))
            outs[tool].append(tok(res))
    return ins, outs


def report(ins, outs, lower_bound, backend):
    from system_agent.callbacks import effective_tool_costs
    charged_ab = effective_tool_costs(backend)
    saved = settings.leaderboard_mode
    settings.leaderboard_mode = True
    charged_lb = effective_tool_costs(backend)
    settings.leaderboard_mode = saved
    print(f"{'tool':26s} {'n':>5s} {'avg_in':>7s} {'avg_out':>8s} {'p90_out':>8s} {'scheme':>7s} {'A/B':>5s} {'lb':>5s}  note")
    for tool in sorted(outs):
        o, i = outs[tool], ins[tool]
        avg_in, avg_out = statistics.mean(i), statistics.mean(o)
        p90 = sorted(o)[max(0, int(0.9 * len(o)) - 1)]
        if tool in FIXED:
            implied = FIXED[tool]
        else:
            implied = 0.5 if (avg_in < INPUT_LIMIT and avg_out < OUTPUT_LIMIT) else 1.0
        note = ""
        if lower_bound.get(tool):
            note = (f"{lower_bound[tool]} of {len(o)} outputs truncated in the record: avg_out is a LOWER BOUND, "
                    f"scheme column inconclusive - use --live")
            flag = ""
        else:
            flag = "" if charged_lb.get(tool) in (None, implied) else "  <-- leaderboard table differs from the scheme"
        print(f"{tool:26s} {len(o):5d} {avg_in:7.0f} {avg_out:8.0f} {p90:8.0f} {implied:7.1f} "
              f"{charged_ab.get(tool, float('nan')):5.1f} {charged_lb.get(tool, float('nan')):5.1f}  {note}{flag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs="+", required=True, help="results JSON file(s), globs allowed")
    ap.add_argument("--live", type=int, default=0, help="also re-issue N sampled calls per tool against the MCP server")
    ap.add_argument("--backend", default="atscale")
    a = ap.parse_args()
    paths = [p for g in a.run for p in glob.glob(g)]
    if not paths:
        raise SystemExit("no results files matched")
    ins, outs, lb = from_run(paths)
    print(f"== recorded in {len(paths)} run file(s)")
    report(ins, outs, lb, a.backend)
    if a.live:
        print(f"\n== live: {a.live} sampled calls per token-aware tool against {settings.semantic_layer_mcp_url}")
        li, lo = live_sample(paths, a.live, a.backend)
        report(li, lo, {}, a.backend)


if __name__ == "__main__":
    main()
