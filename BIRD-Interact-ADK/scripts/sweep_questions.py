#!/usr/bin/env python3
"""Write the sweep question list for one BIRD database: Query tasks only, phase-1 winnable only.
    python scripts/sweep_questions.py <task_brief.json> <out.txt> [--census <census_lb*_final.json>]
Reads amb_user_query per task, drops ids of the form <db>_M_<n> (Management), drops tasks whose
census p1.unwinnable is true, writes `id<TAB>question` lines, prints the counts. No LLM calls.
The census is the orchestrator's input; never hand it to the sweep tester (sml-model-sweep:inputs-bird).
"""
import argparse, json, re, sys

ap = argparse.ArgumentParser()
ap.add_argument("task_brief"); ap.add_argument("out")
ap.add_argument("--census", default=None)
a = ap.parse_args()

d = json.load(open(a.task_brief))
rows = d if isinstance(d, list) else (d.get("tasks") or d.get("items") or list(d.values()))
rows = [r for r in rows if isinstance(r, dict) and r.get("amb_user_query")]
unwinnable = set()
if a.census:
    c = json.load(open(a.census))
    unwinnable = {k for k, v in c["tasks"].items() if (v.get("p1") or {}).get("unwinnable")}

out, n_mgmt, n_unw = [], 0, 0
for r in rows:
    tid = str(r.get("task_id") or r.get("instance_id") or r.get("id") or "")
    if re.search(r"_M_\d+$", tid) or r.get("category") == "Management":
        n_mgmt += 1; continue
    if tid in unwinnable:
        n_unw += 1; continue
    out.append(f"{tid.split('_')[-1]}\t{' '.join(str(r['amb_user_query']).split())}")
open(a.out, "w").write("\n".join(out) + "\n")
print(f"tasks {len(rows)}  dropped management {n_mgmt}  dropped unwinnable {n_unw}  written {len(out)} -> {a.out}")
