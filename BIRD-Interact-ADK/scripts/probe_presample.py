#!/usr/bin/env python3
"""Probe the LIVE server's first-query advisories after model pre-sampling.

One task session (what the agent uses — sampled_values live in the session's
model document): list_models, then run_query with a literal that only differs
from the stored value by case, and one that is not stored at all. No LLM calls.

    python scripts/probe_presample.py --database households \
        --column Region --stored Taguatinga --missing Nowhere
"""
import argparse, asyncio, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import settings                          # noqa: E402
from shared.environment_backends import get_domain_config   # noqa: E402
from shared.mcp_client import MCPEndpoint, TaskSessionMCPClient  # noqa: E402

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", required=True); ap.add_argument("--column", required=True)
    ap.add_argument("--stored", required=True, help="a stored value, typed with the wrong case")
    ap.add_argument("--missing", default="zz_not_a_value")
    a = ap.parse_args()
    dom = get_domain_config("atscale", a.database)
    cli = TaskSessionMCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                                           bearer_token=settings.semantic_layer_mcp_token))
    tid = f"probe_presample_{int(time.time())}"
    t0 = time.time(); lm = await cli.acall_tool(tid, "list_models", dom); t1 = time.time()
    print(f"list_models: {len(str(lm))} chars in {t1-t0:.1f}s")
    tbl = f'"{dom["schema"]}"."{dom["table"]}"'
    for lit in (a.stored.swapcase(), a.missing):
        sql = f'SELECT "{a.column}" FROM {tbl} WHERE "{a.column}" = \'{lit}\' GROUP BY "{a.column}"'
        out = str(await cli.acall_tool(tid, "run_query", {"query": sql, "question": f"probe {lit}"}))
        adv = re.search(r"## Query risk advisories.*", out, re.S)
        print(f"\n--- literal {lit!r}\n" + (adv.group(0)[:600] if adv else "(no advisory block)\n" + out[:300]))

asyncio.run(main())
