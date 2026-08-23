#!/usr/bin/env python3
"""Measure the blast radius of ATSCALE-52084.

For every failing submission whose SQL projects only dimension attributes, add one
measure to the SELECT list, drop the added column from the result, and re-score
against gold with the harness's own comparator. A verdict that flips to matching is
a failure caused by the attribute-only truncation rather than by the agent.
"""
import glob
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import result_diff as rd                                          # noqa: E402

MODEL_RE = re.compile(r'FROM\s+"([^"]+)"\."([^"]+)"', re.I)


def model_of(sql):
    m = MODEL_RE.search(sql or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def measures_of(mcp, schema, table, cache):
    """Measure names for a model, read from the list_models Column Index."""
    if (schema, table) in cache:
        return cache[(schema, table)]
    d = mcp._post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": "list_models",
                              "arguments": {"schema": schema, "table": table}}})
    text = "".join(c.get("text", "") for c in ((d.get("result") or {}).get("content") or [])
                   if isinstance(c, dict))
    names, keep = set(), False
    for line in text.split("\n"):
        if line.startswith("## column_group:"):
            keep = "(measures" in line
            continue
        s = line.strip()
        if keep and s and s != "column_name" and not s.startswith(("#", "|", "-")):
            names.add(s)
    cache[(schema, table)] = names
    return names


def projected(sql):
    m = re.search(r"SELECT(.*?)\bFROM\b", re.sub(r"\s+", " ", sql), re.I | re.S)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def inject(sql, measure):
    """Add the measure as a trailing SELECT item, leaving GROUP BY untouched."""
    m = re.search(r"\bFROM\b", sql, re.I)
    return sql[:m.start()].rstrip().rstrip(",") + f', "{measure}" AS __probe__ ' + sql[m.start():]


def main():
    cases = []
    for f in glob.glob("/tmp/rv_*.json"):
        cases += [c for c in json.load(open(f)) if c.get("agent_sql") and c.get("gold_sql")]
    mcp = rd.Mcp(); mcp.start()
    cache, out = {}, []
    for c in cases:
        schema, table = model_of(c["agent_sql"])
        if not table:
            continue
        meas = measures_of(mcp, schema, table, cache)
        if not meas:
            continue
        cols = projected(c["agent_sql"])
        if any(col in meas for col in cols):
            continue                                   # already has a measure
        probe = sorted(m for m in meas if "Count" in m) or sorted(meas)
        arows, aerr = mcp.run_query(inject(c["agent_sql"], probe[0]))
        if arows is None:
            out.append(dict(c, probe_verdict=f"probe failed: {aerr}")); continue
        arows = [r[:-1] for r in arows]                 # drop the injected column
        grows, gerr = rd.run_gold(c["db"], c["gold_sql"])
        if gerr or grows is None:
            out.append(dict(c, probe_verdict=f"gold failed: {gerr}")); continue
        cond = {"order": True}
        v, pa, pg = rd.four_way(arows, grows, cond)
        out.append(dict(c, probe_verdict=rd.classify(v, pa, pg, None, None),
                        probe_rows=len(arows), probe_measure=probe[0]))
        print(f"  {c['iid']:34} p{c['phase']}  {c['verdict'][:34]:36} -> {out[-1]['probe_verdict'][:44]}",
              flush=True)
    pathlib.Path("/tmp/injection.json").write_text(json.dumps(out, indent=1, default=str))
    flips = [o for o in out if o.get("probe_verdict", "").startswith(("MATCHES", "row ORDER only"))]
    print(f"\n=== {len(out)} attribute-only cases probed")
    print(f"=== {len(flips)} now match (or match ignoring row order)")
    for o in flips:
        print(f"      {o['iid']} p{o['phase']}: {o['verdict']} -> {o['probe_verdict']}")


if __name__ == "__main__":
    main()
