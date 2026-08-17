"""Grade a candidate semantic-layer query against a task's gold, offline.

Usage:  python scripts/probe_pred.py <database> <instance_id> <phase> "<SQL>"
        python scripts/probe_pred.py --file probes.json

Answers "would this SQL have scored" without running the agent. The SQL is
dispatched through the same local MCP run_query the atscale arm uses and graded
with the same ex_base_external_pred the live grader calls, under the flags
currently in .env.

Free: no LLM calls. Use it to prove a fix before spending a run on it — a
hypothesis that the agent projected one column too many is cheap to test here
and costs ~$0.25 to test on a real task.

--file takes a JSON list of {database, instance_id, phase, sql, label}.
"""
import json, sys, os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
from shared.config import settings
from shared import db_utils as U
from shared.mcp_client import MCPClient, MCPEndpoint

argv = sys.argv[1:]
if not argv:
    sys.exit(__doc__)

if argv[0] == "--file":
    probes = json.load(open(argv[1]))
else:
    probes = [dict(database=argv[0], instance_id=argv[1], phase=int(argv[2]), sql=argv[3])]

tasks = {}
for line in open(settings.data_path):
    d = json.loads(line)
    tasks[d["instance_id"]] = d

cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                            bearer_token=settings.semantic_layer_mcp_token))

# One scratch DB per database touched. Gold executes here; the template stays
# pristine (shared.db_utils refuses writes against *_template — B-25).
dbs, conns = {}, {}
for p in probes:
    d = p["database"]
    if d not in dbs:
        dbs[d] = U.create_task_db(d, "probe")
        conns[d] = U.get_connection_for_phase(dbs[d])

print(f"flags: tie={settings.grading_tie_tolerance} dec={settings.grading_honor_decimal} "
      f"casefold={settings.grading_casefold} rel={settings.grading_rel_tolerance} "
      f"lint={settings.grading_order_lint}\n")

try:
    for p in probes:
        tid, phase = p["instance_id"], int(p["phase"])
        td = tasks[tid]
        if phase == 1:
            sol, cond = td.get("sol_sql"), td.get("conditions", {})
        else:
            fu = td.get("follow_up") or {}
            sol, cond = fu.get("sol_sql"), fu.get("conditions", {})
        cond = U.apply_order_lint(cond, tid, phase)
        if isinstance(sol, str):
            sol = [sol]

        label = p.get("label", "")
        print("=" * 70)
        print(f"{tid} phase {phase}  {label}")
        print(p["sql"].strip()[:600])
        try:
            txt = cli.call_tool("run_query", {"query": p["sql"]})
            pred = U.parse_semantic_layer_rows(str(txt)) or None
        except Exception as e:
            print(f"  MCP ERROR {type(e).__name__}: {str(e)[:300]}")
            continue
        if pred is None:
            print(f"  no rows parsed; raw head: {str(txt)[:300]}")
            continue
        verdict = U.ex_base_external_pred(pred, sol, dbs[p["database"]],
                                          conns[p["database"]], cond)
        print(f"  rows={len(pred)} cols={len(pred[0]) if pred else 0}  "
              f"first={pred[0] if pred else None}")
        print(f"  VERDICT: {verdict}")
finally:
    for d, db in dbs.items():
        U.drop_task_db(db)
