#!/usr/bin/env python3
"""Diagnose WHY a submission failed, by diffing RESULT SETS rather than SQL text.

The text-diff pass of 2026-08-21 produced mostly artefacts: comparing
semantic-layer SQL against raw Postgres gold makes join counts, subquery depth
and aggregate spellings diverge by construction, not by defect. Only the result
sets are comparable across the two arms, and this is the method the build prompt
prescribes:

    Re-execute each submission against the engine and the reference against the
    warehouse, then score them with the harness's own comparison function under
    four settings - as graded, order-insensitive, case-folded, both. That splits
    the failures into tie-order, casing, wrong-shape and genuinely-wrong in one
    pass, and it is the only cheap way to know which of them a model change
    could possibly address.

Why no per-task database is rebuilt: Query-category gold is read-only. Across
all 410 Query tasks there is no `preprocess_sql`, no `clean_up_sqls`, and
exactly one task whose gold mutates state. Gold therefore runs against
`<db>_template` directly, and the phase-2 gold sees the same state phase 1 left
(unchanged), which is what the live run saw. That one mutating task is reported
as SKIPPED rather than silently mis-graded.

Reads gold SQL. That is permitted for diagnosing specific failing tasks and is
never folded back into a model - but it contaminates the databases it touches,
so anything it teaches must be recorded as gold-derived (see
docs/model-change-log.md, 2026-08-21).

Usage:
    python3 scripts/result_diff.py results/<run>.json [--databases a,b] [--limit N]
    python3 scripts/result_diff.py results/<run>.json --out /tmp/diff.json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.config import settings                      # noqa: E402
from shared.db_utils import (_compare_rows, canonical_cell,  # noqa: E402
                             preprocess_results)

PG = dict(host=os.environ.get("BIRD_PG_HOST", "localhost"),
          port=os.environ.get("BIRD_PG_PORT", "5433"),
          user=os.environ.get("BIRD_PG_USER", "root"),
          password=os.environ.get("BIRD_PG_PASSWORD", "123123"))
DATA = ROOT / "bird-interact-full" / "bird_interact_data.jsonl"
MCP_URL = os.environ.get("SEMANTIC_LAYER_MCP_URL", "http://localhost/mcp")

MUTATES = re.compile(r'\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE)\s', re.I)


# --------------------------------------------------------------------- gold --
def run_gold(db: str, sql: str, timeout: int = 60):
    """Execute gold against <db>_template. Returns (rows, error)."""
    env = dict(os.environ, PGPASSWORD=PG["password"])
    cmd = ["psql", "-h", PG["host"], "-p", PG["port"], "-U", PG["user"],
           "-d", f"{db}_template", "-qAt", "-F", "\x1f", "--no-align",
           "-v", "ON_ERROR_STOP=1", "-c", sql]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "gold timeout"
    if r.returncode:
        return None, "gold error: " + r.stderr.strip().split("\n")[0][:160]
    rows = [tuple(line.split("\x1f")) for line in r.stdout.split("\n") if line != ""]
    return rows, None


# ---------------------------------------------------------------- semantic --
class Mcp:
    """Minimal streamable-HTTP MCP client, so this does not depend on a bridge."""

    def __init__(self):
        tok = os.environ.get("SEMANTIC_LAYER_MCP_TOKEN") or self._token_from_env_file()
        self.hdr = {"Authorization": tok if tok.startswith("Bearer ") else f"Bearer {tok}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"}
        self.sid = None

    @staticmethod
    def _token_from_env_file():
        f = ROOT / ".env"
        for line in f.read_text().split("\n") if f.exists() else []:
            if line.startswith("SEMANTIC_LAYER_MCP_TOKEN="):
                return line.split("=", 1)[1].strip()
        raise SystemExit("no SEMANTIC_LAYER_MCP_TOKEN in env or .env")

    def _post(self, payload, timeout=120):
        import urllib.request
        hdr = dict(self.hdr)
        if self.sid:
            hdr["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(),
                                     headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not self.sid:
                self.sid = resp.headers.get("Mcp-Session-Id")
            body = resp.read().decode()
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                line = line[6:]
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return {}

    def start(self):
        self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "result_diff", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def run_query(self, sql: str):
        """Returns (rows, error). Rows are tuples in the projected column order."""
        try:
            d = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "run_query", "arguments": {"query": sql}}})
        except Exception as exc:                                  # transport
            return None, f"transport: {type(exc).__name__}"
        content = ((d.get("result") or {}).get("content") or [])
        text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        if not text:
            return None, "empty response"
        payload = text.split("queryId:")[0].strip()
        if not payload.startswith("["):
            return None, "engine error: " + re.sub(r"\s+", " ", payload)[:160]
        try:
            recs = json.loads(payload)
        except json.JSONDecodeError:
            return None, "unparseable result"
        if not recs:
            return [], None
        keys = list(recs[0].keys())
        return [tuple(r.get(k) for k in keys) for r in recs], None


# ------------------------------------------------------------------ verdict --
def four_way(agent_rows, gold_rows, conditions):
    """Score the pair under the harness's own comparator, four settings."""
    dp = 2
    a = preprocess_results(agent_rows, dp)
    g = preprocess_results(gold_rows, dp)
    ordered = dict(conditions or {})
    unordered = dict(ordered, order=False)
    out = {}
    saved = settings.grading_casefold
    for label, cond, fold in (("as graded", ordered, saved),
                              ("order-insensitive", unordered, saved),
                              ("case-folded", ordered, True),
                              ("both", unordered, True)):
        settings.grading_casefold = fold
        out[label] = bool(_compare_rows(a, g, cond, cell=canonical_cell))
    settings.grading_casefold = saved
    return out, a, g


def classify(v, a, g, agent_err, gold_err):
    if gold_err:
        return f"UNDIAGNOSABLE: {gold_err.split(':')[0]}"
    if agent_err:
        return f"agent SQL no longer executes: {agent_err.split(':')[0]}"
    if v["as graded"]:
        return "MATCHES on replay (graded-run failure was environmental)"
    if v["order-insensitive"]:
        return "row ORDER only"
    if v["case-folded"]:
        return "string CASE only"
    if v["both"]:
        return "order + case only"
    if not a and g:
        return "agent returned NO rows"
    if a and not g:
        return "gold returned no rows"
    if len(a[0]) != len(g[0]):
        return f"column COUNT differs ({len(a[0])} vs {len(g[0])})"
    if len(a) != len(g):
        return f"row COUNT differs ({len(a)} vs {len(g)})"
    return "same shape, VALUES differ"


# --------------------------------------------------------------------- main --
def load_gold():
    gold = {}
    for line in DATA.read_text().split("\n"):
        if not line.strip():
            continue
        r = json.loads(line)
        fu = r.get("follow_up") or {}
        if isinstance(fu, list):
            fu = fu[0] if fu else {}
        gold[r["instance_id"]] = {
            1: (" ".join(r.get("sol_sql") or []), r.get("conditions") or {}),
            2: (" ".join(fu.get("sol_sql") or []), fu.get("conditions") or {}),
        }
    return gold


def failing_tasks(results_path, dbs=None):
    d = json.loads(pathlib.Path(results_path).read_text())
    rows = next(v for v in d.values()
                if isinstance(v, list) and v and isinstance(v[0], dict) and "total_reward" in v[0])
    out = []
    for r in rows:
        db = r.get("database") or re.sub(r"_(M_)?\d+$", "", r.get("instance_id") or "")
        if dbs and db not in dbs:
            continue
        tt = r.get("tool_trajectory") or []
        subs = [(i, t) for i, t in enumerate(tt) if t.get("tool") == "submit_sql"]
        if not subs:
            continue
        boundary = None
        for i, t in subs:
            s = t.get("result") if isinstance(t.get("result"), str) else json.dumps(t.get("result"))
            if "Phase 1 correct" in s:
                boundary = i
                break
        p1_ok = bool(r.get("phase1_passed"))
        p2_ok = bool(r.get("phase2_passed"))
        if p1_ok and p2_ok:
            continue
        phase = 2 if p1_ok else 1
        mine = ([t for i, t in subs if boundary is not None and i > boundary] if phase == 2
                else [t for i, t in subs if boundary is None or i <= boundary])
        if not mine:
            continue
        out.append(dict(db=db, iid=r["instance_id"], phase=phase,
                        sql=(mine[-1].get("args") or {}).get("sql", "")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--databases")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default="/tmp/result_diff.json")
    a = ap.parse_args()
    dbs = set(a.databases.split(",")) if a.databases else None

    gold = load_gold()
    tasks = failing_tasks(a.results, dbs)
    if a.limit:
        tasks = tasks[: a.limit]
    mcp = Mcp()
    mcp.start()

    report, verdicts = [], Counter()
    for n, t in enumerate(tasks, 1):
        gsql, cond = gold.get(t["iid"], {}).get(t["phase"], ("", {}))
        if not gsql:
            verdicts["UNDIAGNOSABLE: no gold for this phase"] += 1
            continue
        if MUTATES.search(gsql):
            verdicts["SKIPPED: gold mutates state"] += 1
            continue
        grows, gerr = run_gold(t["db"], gsql)
        arows, aerr = mcp.run_query(t["sql"]) if t["sql"] else (None, "no submitted sql")
        if grows is None or arows is None:
            v = {k: False for k in ("as graded", "order-insensitive", "case-folded", "both")}
            cls = classify(v, [], [], aerr, gerr)
        else:
            v, pa, pg = four_way(arows, grows, cond)
            cls = classify(v, pa, pg, aerr, gerr)
        verdicts[cls] += 1
        report.append(dict(db=t["db"], iid=t["iid"], phase=t["phase"], verdict=cls,
                           four_way=v, agent_rows=(len(arows) if arows is not None else None),
                           gold_rows=(len(grows) if grows is not None else None),
                           agent_err=aerr, gold_err=gerr))
        print(f"  [{n}/{len(tasks)}] {t['iid']:36} p{t['phase']}  {cls}", flush=True)

    pathlib.Path(a.out).write_text(json.dumps(report, indent=1))
    tot = sum(verdicts.values())
    print(f"\n=== {tot} failing submissions replayed ===")
    for k, c in verdicts.most_common():
        print(f"  {c:4} ({c/tot:4.0%})  {k}")
    by = defaultdict(Counter)
    for r in report:
        by[r["db"]][r["verdict"]] += 1
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
