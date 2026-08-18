#!/usr/bin/env python3
"""Show the warehouse SQL AtScale actually dispatched for a semantic-layer query.

The inbound SQL an agent writes is not what runs. The engine rewrites it — it
inlines each dataset's derived SQL, re-aggregates at an inferred grain, and
silently edits clauses it does not honour. Two defects were found exactly this
way and are invisible from the result alone:

  Q-22  OFFSET is dropped entirely. `LIMIT 1 OFFSET 335` dispatches as `LIMIT 1`,
        so every offset returns the first row with no error.
  Q-23  NULL ordering is forced to the engine's own convention. `DESC NULLS FIRST`
        dispatches as `DESC NULLS LAST` — the opposite of Postgres's default, which
        is what the expected answers are generated from.

So when a query returns plausible-but-wrong rows, read the outbound SQL before
theorising about the model.

Usage:
  scripts/outbound_sql.py "SELECT ... FROM ..."        # run and show dispatched SQL
  scripts/outbound_sql.py --query-id <uuid>            # resolve an earlier run_query
  scripts/outbound_sql.py --tail 40 "SELECT ..."       # only the last N lines
  scripts/outbound_sql.py --full "SELECT ..."          # include inlined dataset SQL

By default the inlined dataset SQL is elided: it is hundreds of lines of the
model's own derived SQL and almost never the thing you are looking at. The
wrapper — the GROUP BYs, the ORDER BY, the LIMIT — is where the rewrites show up.
"""
import argparse
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from shared.config import settings                      # noqa: E402
from shared.mcp_client import MCPClient, MCPEndpoint    # noqa: E402

QUERY_ID = re.compile(r"queryId:\s*([0-9a-f-]{36})")


def client():
    return MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                                 bearer_token=settings.semantic_layer_mcp_token))


def outbound(cli, query_id):
    raw = str(cli.call_tool("get_outbound_queries", {"queryId": query_id}))
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        # Tool responses may arrive wrapped in prose; recover the JSON array.
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            return [{"outboundQueryId": "?", "sql": raw}]
        rows = json.loads(m.group(0))
    return rows if isinstance(rows, list) else [rows]


def elide_datasets(sql):
    """Drop the inlined `WITH ... ) AS "t_N"` dataset bodies, keep the wrapper."""
    out, depth, skipped = [], 0, 0
    for line in sql.splitlines():
        if re.match(r"\s*WITH\s+\w+\s+AS\s*\(", line) and depth == 0:
            depth = 1
            continue
        if depth:
            if re.match(r'\s*\)\s*AS\s+"t_\d+"', line):
                depth = 0
                out.append(f"      -- [{skipped} lines of inlined dataset SQL elided; --full to see]")
                skipped = 0
                out.append(line)
            else:
                skipped += 1
            continue
        out.append(line)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sql", nargs="?", help="inbound SQL to run")
    ap.add_argument("--query-id", help="resolve a queryId from an earlier run_query")
    ap.add_argument("--full", action="store_true", help="keep inlined dataset SQL")
    ap.add_argument("--tail", type=int, help="print only the last N lines")
    args = ap.parse_args()

    if not args.sql and not args.query_id:
        ap.error("give a SQL string or --query-id")

    cli = client()
    qid = args.query_id
    if not qid:
        res = str(cli.call_tool("run_query", {"query": args.sql}))
        m = QUERY_ID.search(res)
        if not m:
            print("no queryId in run_query response (did it error?):\n" + res[:600])
            return 1
        qid = m.group(1)
        print(f"-- queryId: {qid}")
        print(f"-- rows returned: {res.split('queryId:')[0].strip()[:300]}\n")

    queries = outbound(cli, qid)
    for i, q in enumerate(queries, 1):
        sql = q.get("sql", "")
        if not args.full:
            sql = elide_datasets(sql)
        if args.tail:
            sql = "\n".join(sql.splitlines()[-args.tail:])
        print(f"===== outbound query {i}/{len(queries)} "
              f"(id {q.get('outboundQueryId','?')}) =====")
        print(sql)
    return 0


if __name__ == "__main__":
    sys.exit(main())
