#!/usr/bin/env python
"""AO disambiguation probe (baseline, no AO): does a Sonnet agent querying an AtScale
semantic model through the local MCP server pick the object the organization means?

    .venv-adk/bin/python scripts/ao/disambig_probe.py --label smoke --ids q01
    .venv-adk/bin/python scripts/ao/disambig_probe.py --label base            # all 20
    .venv-adk/bin/python scripts/ao/disambig_probe.py --label base --grade-only
    .venv-adk/bin/python scripts/ao/disambig_probe.py --resolve-only

Steps: (1) resolve question object names (SML unique_name) to deployed column names via
list_models column index (cached results/aodisambig/column_index_<schema>.txt) ->
questions_resolved.jsonl; (2) agent loop per question (litellm, Sonnet, all MCP tools +
local ask_user, MCP `instructions` in system prompt, prompt caching, one MCP session per
question); (3) offline grade -> probe_<label>_grade.md.

Auth: MCP URL/token are read as single values from .env (never sourced, never printed).
.env wins over the process env on purpose: a stale exported SEMANTIC_LAYER_MCP_TOKEN
in the shell is a known gotcha (unset it).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BIRD_LLM_ROLE", "aodis_probe")  # attribution in results/llm_usage.jsonl

D = ROOT / "results" / "aodisambig"
QUESTIONS = D / "questions.jsonl"
RESOLVED = D / "questions_resolved.jsonl"
MODEL = "anthropic/claude-sonnet-5"  # Sonnet is the instrument; do not change
MAX_TURNS = 20
MAX_COST_USD = 10.0
TOOL_RESULT_SEND_CAP = 40000   # chars sent back to the model per tool result (spend guard)
TOOL_RESULT_REC_CAP = 2000     # chars recorded per tool result

AO_CARDS: dict = {}  # schema -> card text, filled by --ao-card

SCHEMAS = {  # question "model" -> (schema, model table, display)
    "TPC-DS Benchmark Model": ("aodis_tpcds", "tpcds_benchmark_model"),
    "World Wide Importers": ("aodis_wwi", "world_wide_importers"),
}
# TPC-DS calcs equivalent to the sum of per-channel metrics (expressions checked in
# sml-models-tutorials-tpcds/calculations/): intended per-channel trio -> total calc.
TPCDS_TOTALS = {
    "Total Ext Sales Price": ["Store Ext Sales Price", "Web Ext Sales Price", "Catalog Ext Sales Price"],
    "Total Net Profit": ["Store Net Profit", "Web Net Profit", "Catalog Net Profit Amount"],
    "Total Quantity Sold": ["Store Quantity Sold", "Web Quantity Sold", "Catalog Quantity Sold"],
    "Total Net Paid Amount": ["Store Net Paid Amount", "Web Net Paid Amount", "Catalog Net Paid Amount"],
}


# ── env / MCP plumbing ────────────────────────────────────────────────────────
def env_value(key: str) -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        m = re.match(rf"^\s*(?:export\s+)?{key}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip("'\"")
    return os.environ.get(key, "")


def mcp_conn():
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    url, tok = env_value("SEMANTIC_LAYER_MCP_URL"), env_value("SEMANTIC_LAYER_MCP_TOKEN")
    if not url:
        sys.exit("SEMANTIC_LAYER_MCP_URL missing in .env")
    hdr = {"Authorization": f"Bearer {tok}"} if tok else {}
    http = httpx.AsyncClient(headers=hdr, timeout=300)
    return http, streamable_http_client(url, http_client=http), ClientSession


def text_of(res) -> str:
    return "\n".join(getattr(c, "text", "") or "" for c in res.content)


# ── step 1: resolve names ────────────────────────────────────────────────────
async def _fetch_index(schema: str) -> str:
    p = D / f"column_index_{schema}.txt"
    if p.exists():
        return p.read_text()
    http, tr, CS = mcp_conn()
    async with http, tr as (r, w), CS(r, w) as s:
        await s.initialize()
        txt = text_of(await s.call_tool("list_models", {"schema": schema}))
    p.write_text(txt)
    return txt


def parse_columns(txt: str) -> list[str]:
    """Names listed under '## column_group:' headings of the Column Index section."""
    cols, ingrp = [], False
    for line in txt.splitlines():
        if line.startswith("## column_group:"):
            ingrp = True
        elif line.startswith("## ") or line.startswith("# "):
            ingrp = False
        elif ingrp and line.strip() and line.strip() != "column_name":
            cols.append(line.strip())
    return cols


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def resolve_name(name: str, cols: list[str]) -> str | None:
    if name in cols:
        return name
    low = {c.lower(): c for c in cols}
    if name.lower() in low:
        return low[name.lower()]
    nn = _norm(name)
    cand = [c for c in cols if _norm(c) == nn]
    if len(cand) == 1:
        return cand[0]
    # role-prefixed: deployed "<Role> <name>" or name with a role infix; require unique suffix match
    cand = [c for c in cols if _norm(c).endswith(" " + nn)]
    if len(cand) == 1:
        return cand[0]
    return None


def do_resolve() -> list[dict]:
    qs = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]
    idx = {}
    for sch in {v[0] for v in SCHEMAS.values()}:
        idx[sch] = parse_columns(asyncio.run(_fetch_index(sch)))
    out, unresolved = [], []
    for q in qs:
        cols = idx[SCHEMAS[q["model"]][0]]
        r = dict(q)
        for key in ("intended_objects", "wrong_objects"):
            res = []
            for n in q[key]:
                c = resolve_name(n, cols)
                if c is None:
                    unresolved.append((q["id"], key, n))
                res.append(c or n)
            r[key + "_resolved"] = res
        out.append(r)
    RESOLVED.write_text("".join(json.dumps(r) + "\n" for r in out))
    for sch, cols in idx.items():
        print(f"index {sch}: {len(cols)} columns")
    print(f"wrote {RESOLVED.relative_to(ROOT)}; unresolved: {unresolved or 'none'}")
    renamed = {(n, c) for q in out for k in ("intended_objects", "wrong_objects")
               for n, c in zip(q[k], q[k + "_resolved"]) if n != c}
    if renamed:
        print("renamed:", sorted(renamed))
    return out


# ── step 2: agent loop ───────────────────────────────────────────────────────
ASK_TOOL = {"type": "function", "function": {
    "name": "ask_user",
    "description": "Ask the user a clarifying question about what their business question means. Returns their answer.",
    "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}}


SYSTEM_HEAD = (
    "Answer the user's business question using the semantic model they name. "
    "You may ask the user a clarifying question with the ask_user tool if you need to. "
    "Finish with a final answer.\n\n")


def user_prompt(q: dict) -> str:
    # The model name rides in the user turn, not the system prompt, so the (very large)
    # system block is byte-identical across questions and the prompt cache hits.
    schema, table = SCHEMAS[q["model"]]
    return f'Semantic model: "atscale_catalogs"."{schema}"."{table}" ({q["model"]})\n\n{q["question"]}'


def is_success(name: str, text: str, is_error: bool) -> bool:
    return not is_error and not re.match(r"\s*(error|failed)\b", text, re.I) and "Error calling" not in text[:200]


async def run_question(q: dict, state: dict) -> dict:
    import litellm
    from shared import usage as U
    from shared.config import settings
    from shared.llm import cache_breakpoints
    from shared.llm_routing import route_kwargs

    rec = {"id": q["id"], "model": q["model"], "kind": q["kind"], "question": q["question"],
           "tool_calls": [], "run_queries": [], "ask_count": 0, "asked": False, "calls": [],
           "final_answer": "", "stop": "", "turns": 0}
    http, tr, CS = mcp_conn()
    async with http, tr as (r, w), CS(r, w) as s:
        init = await s.initialize()
        mtools = (await s.list_tools()).tools
        tools = [{"type": "function", "function": {
            "name": t.name, "description": t.description or "", "parameters": t.input_schema}}
            for t in mtools] + [ASK_TOOL]
        messages = [{"role": "system", "content": SYSTEM_HEAD + (init.instructions or "")},
                    {"role": "user", "content": user_prompt(q)}]
        kw = dict(model=MODEL, tools=tools, max_tokens=settings.system_agent_max_tokens, num_retries=5)
        if settings.litellm_api_base:
            kw["api_base"] = settings.litellm_api_base
        if settings.litellm_api_key:
            kw["api_key"] = settings.litellm_api_key
        pts = cache_breakpoints(MODEL)
        if pts:
            kw["cache_control_injection_points"] = pts
        kw.update(route_kwargs(MODEL))
        litellm.drop_params = True

        with U.task_context(f"aodis:{q['id']}"):
            for turn in range(1, MAX_TURNS + 1):
                if state["cost"] > MAX_COST_USD:
                    rec["stop"] = "budget"; break
                resp = await litellm.acompletion(messages=messages, **kw)
                rec["turns"] = turn
                u = resp.usage
                cr, cw = U._cache_tokens(u)
                try:
                    cost = float(litellm.completion_cost(completion_response=resp))
                except Exception:
                    cost = 0.0
                state["cost"] += cost
                rec["calls"].append({"turn": turn, "prompt_tokens": u.prompt_tokens,
                                     "completion_tokens": u.completion_tokens,
                                     "cache_read_tokens": cr, "cache_write_tokens": cw, "cost_usd": cost})
                msg = resp.choices[0].message
                m = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    m["tool_calls"] = [{"id": tc.id, "type": "function",
                                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                       for tc in msg.tool_calls]
                messages.append(m)
                if not msg.tool_calls:
                    rec["final_answer"] = msg.content or ""
                    rec["stop"] = "final"; break
                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    is_err = False
                    if name == "ask_user":
                        rec["ask_count"] += 1; rec["asked"] = True
                        out = q["clarification_answer"]
                    else:
                        try:
                            res = await s.call_tool(name, args, read_timeout_seconds=None)
                            out, is_err = text_of(res), bool(res.is_error)
                        except Exception as e:  # tool/transport failure goes back to the agent
                            out, is_err = f"Error calling {name}: {e}", True
                    rec["tool_calls"].append({"turn": turn, "name": name, "args": args,
                                              "is_error": is_err, "result": out[:TOOL_RESULT_REC_CAP]})
                    if name == "run_query":
                        rec["run_queries"].append({"sql": args.get("query", ""), "ok": is_success(name, out, is_err)})
                    sent = out if len(out) <= TOOL_RESULT_SEND_CAP else out[:TOOL_RESULT_SEND_CAP] + "\n...[truncated by probe]"
                    card = AO_CARDS.get(SCHEMAS[q["model"]][0])
                    if card and name in ("focus_columns", "explore_columns"):  # like error_hints
                        sent += "\n\nVocabulary (AO): \n" + card
                        rec["tool_calls"][-1]["ao_card_tail"] = sent[-200:]
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": sent})
            else:
                rec["stop"] = "max_turns"
    t = lambda k: sum(c[k] for c in rec["calls"])
    rec.update(prompt_tokens=t("prompt_tokens"), completion_tokens=t("completion_tokens"),
               cache_read_tokens=t("cache_read_tokens"), cache_write_tokens=t("cache_write_tokens"),
               cost_usd=round(t("cost_usd"), 6))
    return rec


# ── step 3: grading (offline) ────────────────────────────────────────────────
def quoted(sql: str) -> set[str]:
    return {m.lower() for m in re.findall(r'"([^"]+)"', sql)}


_GROUPS: dict = {}


def col_groups(schema: str) -> dict:
    """lower(column) -> (group, kind) from the cached list_models column index."""
    if schema not in _GROUPS:
        m, grp, kind = {}, None, None
        for line in (D / f"column_index_{schema}.txt").read_text().splitlines():
            h = re.match(r"## column_group: (.*) \((.*)\)\s*$", line)
            if h:
                grp, kind = h.group(1), h.group(2)
            elif line.startswith("#"):
                grp = None
            elif grp and line.strip() and line.strip() != "column_name":
                m[line.strip().lower()] = (grp, kind)
        _GROUPS[schema] = m
    return _GROUPS[schema]


def cal_type(name: str):
    n = name.lower()
    return "fiscal" if "fiscal" in n else "calendar" if "calendar" in n else None


def grade_row(row: dict, q: dict) -> dict:
    """Measure choice and role/calendar choice, not the exact level.
    measure: intended measure (or accepted total calc) used; wrong_pick if a wrong measure used.
    dimension: any column from the intended column_group, same calendar type (Fiscal vs Calendar)
    for date objects; wrong_pick if a wrong object's group (not also an intended group) or the
    opposite calendar type is used. Overall correct only if both correct."""
    ok = [r["sql"] for r in row.get("run_queries", []) if r["ok"]]
    if not ok:
        return {"verdict": "other", "measure": "other", "dim": "other", "why": "no successful run_query"}
    qs = quoted(ok[-1])
    cg = col_groups(SCHEMAS[q["model"]][0])
    isdim = lambda o: cg.get(o.lower(), ("", "dimension attributes"))[1] == "dimension attributes"
    I, W = q["intended_objects_resolved"], q["wrong_objects_resolved"]
    im, idim = [o for o in I if not isdim(o)], [o for o in I if isdim(o)]
    wm, wdim = [o for o in W if not isdim(o)], [o for o in W if isdim(o)]
    # measures
    missing_m = [o for o in im if o.lower() not in qs]
    if q["model"].startswith("TPC-DS"):
        for tot, parts in TPCDS_TOTALS.items():
            if tot.lower() in qs and all(p in im for p in parts):
                missing_m = [o for o in missing_m if o not in parts]
    wrong_m = [o for o in wm if o.lower() in qs]
    mv = "wrong_pick" if wrong_m else "correct" if not missing_m else "other"
    # dimensions
    used = {c: cg[c] for c in qs if c in cg and cg[c][1] == "dimension attributes"}
    igroups = {cg[o.lower()][0] for o in idim if o.lower() in cg}
    wgroups = {cg[o.lower()][0] for o in wdim if o.lower() in cg} - igroups
    bad = [c for c, (g, _) in used.items() if g in wgroups]
    missing_d = []
    for g in sorted(igroups):
        cols = [c for c, (gg, _) in used.items() if gg == g]
        if not cols:
            missing_d.append(g); continue
        for o in idim:
            t = cal_type(o)
            if o.lower() in cg and cg[o.lower()][0] == g and t:
                if any(cal_type(c) and cal_type(c) != t for c in cols):
                    bad += [c for c in cols if cal_type(c) and cal_type(c) != t]
    dv = "wrong_pick" if bad else "correct" if not missing_d else "other"
    v = "wrong_pick" if "wrong_pick" in (mv, dv) else "correct" if mv == dv == "correct" else "other"
    return {"verdict": v, "measure": mv, "dim": dv, "missing_measure": missing_m, "wrong_measure": wrong_m,
            "missing_dim_groups": missing_d, "wrong_dim_cols": sorted(set(bad)),
            "dim_cols_used": sorted(c for c in used)}


def do_grade(label: str) -> None:
    qmap = {json.loads(l)["id"]: json.loads(l) for l in RESOLVED.read_text().splitlines() if l.strip()}
    rows = [json.loads(l) for l in (D / f"probe_{label}.jsonl").read_text().splitlines() if l.strip()]
    lines = [f"# probe_{label} grade (measure + role/calendar, not exact level)", "",
             "| id | kind | measure | dimension | overall | asks | detail | cost |", "|---|---|---|---|---|---|---|---|"]
    agg: dict = {}
    for r in rows:
        g = grade_row(r, qmap[r["id"]])
        a = agg.setdefault(r["kind"], {"n": 0, "correct": 0, "wrong_pick": 0, "other": 0, "asked": 0, "asks": 0})
        a["n"] += 1; a[g["verdict"]] += 1; a["asked"] += int(r["asked"]); a["asks"] += r["ask_count"]
        det = g.get("why") or "; ".join(x for x in (
            "missing measure: " + ", ".join(g["missing_measure"]) if g["missing_measure"] else "",
            "wrong measure: " + ", ".join(g["wrong_measure"]) if g["wrong_measure"] else "",
            "missing dim group: " + ", ".join(g["missing_dim_groups"]) if g["missing_dim_groups"] else "",
            "wrong dim cols: " + ", ".join(g["wrong_dim_cols"]) if g["wrong_dim_cols"] else "",
            "dim used: " + ", ".join(g["dim_cols_used"])) if x)
        lines.append(f"| {r['id']} | {r['kind']} | {g['measure']} | {g['dim']} | {g['verdict']} | "
                     f"{r['ask_count']} | {det} | ${r['cost_usd']:.3f} |")
    keys = ["n", "correct", "wrong_pick", "other", "asked", "asks"]
    lines += ["", "## Summary by kind (overall verdict)", "", "| kind | n | correct | wrong_pick | other | questions that asked | total asks |", "|---|---|---|---|---|---|---|"]
    tot = dict.fromkeys(keys, 0)
    for k, a in sorted(agg.items()):
        lines.append(f"| {k} | " + " | ".join(str(a[x]) for x in keys) + " |")
        for x in keys: tot[x] += a[x]
    lines.append("| all | " + " | ".join(str(tot[x]) for x in keys) + " |")
    lines += ["", f"Total cost: ${sum(r['cost_usd'] for r in rows):.3f}"]
    out = D / f"probe_{label}_grade.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines)); print(f"-> {out.relative_to(ROOT)}")


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--ids", default="")
    ap.add_argument("--grade-only", action="store_true")
    ap.add_argument("--resolve-only", action="store_true")
    ap.add_argument("--ao-card", action="append", default=[],
                    help="AO vocabulary card (repeatable); matched to a question's model by schema suffix in the filename")
    a = ap.parse_args()
    for cp in a.ao_card:
        for schema, _ in SCHEMAS.values():
            if schema.split("_", 1)[1] in Path(cp).name:
                AO_CARDS[schema] = Path(cp).read_text().strip()
    if a.resolve_only or not RESOLVED.exists():
        do_resolve()
        if a.resolve_only:
            return
    if not a.label:
        sys.exit("--label required")
    if a.grade_only:
        return do_grade(a.label)
    qs = [json.loads(l) for l in RESOLVED.read_text().splitlines() if l.strip()]
    if a.ids:
        want = set(a.ids.split(","))
        qs = [q for q in qs if q["id"] in want]
    out = D / f"probe_{a.label}.jsonl"
    done = {json.loads(l)["id"] for l in out.read_text().splitlines() if l.strip()} if out.exists() else set()
    from shared import usage as U
    import shared.llm  # noqa: F401  (installs the usage callback)
    t0 = time.time()
    state = {"cost": 0.0}
    async def loop():
        for q in qs:
            if q["id"] in done:
                print(f"skip {q['id']} (already in {out.name})"); continue
            if state["cost"] > MAX_COST_USD:
                print(f"HARD STOP: cumulative ${state['cost']:.2f} > ${MAX_COST_USD}"); break
            rec = await run_question(q, state)
            with open(out, "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"{q['id']}: stop={rec['stop']} turns={rec['turns']} asked={rec['ask_count']} "
                  f"queries={len(rec['run_queries'])} cache_read={rec['cache_read_tokens']} "
                  f"cost=${rec['cost_usd']:.3f} cum=${state['cost']:.3f}", flush=True)
        await asyncio.sleep(1)  # let async usage callbacks flush
    asyncio.run(loop())
    print(U.format_summary(U.aggregate(since=t0)))
    do_grade(a.label)


if __name__ == "__main__":
    main()
