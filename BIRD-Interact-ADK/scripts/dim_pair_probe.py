#!/usr/bin/env python
"""Attribute-only conformance probe: can every pair of dimensions be projected
together WITHOUT a measure?

    python scripts/dim_pair_probe.py "Crypto Exchange" [schema]

Free - no LLM calls, no benchmark tokens. One `run_query` per pair.

Why this exists. A model's conformance gate normally asks "does measure M
resolve by dimension D", and a measure names the fact the planner routes
through. Take the measure away and the planner has to choose a path on its own,
and it can fail where the measured form succeeds:

    SELECT "Exchange Spot Market", "Snapshot Time" FROM model      -> assertion
        failed: No candidate paths found for an attribute
    SELECT "Exchange Spot Market", "Snapshot Time", "Market Snapshot Count"
        FROM model GROUP BY 1,2                                    -> fine

crypto_exchange shipped with exactly that hole: Market Snapshot was joined from
three datasets on two different columns, so no attribute-only query could pair
it with anything. It passed every build gate and then ate 32 of 98 run_query
calls in the first benchmark arm, because BIRD questions ask for identifiers
and labels far more often than they ask for aggregates. See tracker Q-27.

Reports one line per pair; a FAIL is a pair no attribute-only question can use.
"""
import itertools
import json
import re
import sys

sys.path.insert(0, "/Users/dianne/go/src/github.com/BIRD-Interact/BIRD-Interact-ADK")
from shared.config import settings                      # noqa: E402
from shared.mcp_client import MCPClient, MCPEndpoint    # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "Crypto Exchange"
SCHEMA = sys.argv[2] if len(sys.argv) > 2 else "bird_atscale_models_catalog_main"
T = f'"{SCHEMA}"."{MODEL}"'

cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                            bearer_token=settings.semantic_layer_mcp_token))


def call(tool, args):
    try:
        return str(cli.call_tool(tool, args))
    except Exception as e:
        return f"__ERROR__ {type(e).__name__}: {e}"


# The key attribute of each dimension is the one to probe with: it is what a
# question naming an entity actually selects.
meta = call("list_models", {})
keys = {}
for line in meta.splitlines():
    m = re.match(r"\s{2}(.+?) -> (\S+)\s*$", line)
    if m:
        keys[m.group(1).strip()] = m.group(2).strip()
if not keys:
    sys.exit("could not read column_groups from list_models; run it by hand and "
             "pass the dimension key attributes another way")

names = sorted(keys)
print(f"# {MODEL}: {len(names)} dimensions, {len(names)*(len(names)-1)//2} pairs\n")
fails = []
for a, b in itertools.combinations(names, 2):
    q = f'SELECT "{a}", "{b}" FROM {T} LIMIT 1'
    out = call("run_query", {"query": q})
    if out.startswith("__ERROR__"):
        reason = out.split(":", 1)[-1].strip()[:90]
        print(f"FAIL {a} x {b}\n     {reason}")
        fails.append((a, b, reason))
    else:
        print(f"ok   {a} x {b}")

print(f"\n{len(names)*(len(names)-1)//2 - len(fails)}"
      f"/{len(names)*(len(names)-1)//2} pairs resolve attribute-only")
if fails:
    print("\nUnusable pairs (no attribute-only question can combine these):")
    for a, b, r in fails:
        print(f"  {a} x {b}: {r}")
sys.exit(1 if fails else 0)
