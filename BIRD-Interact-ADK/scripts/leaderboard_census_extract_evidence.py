#!/usr/bin/env python3
"""Per-task phase-1/phase-2 pass evidence from every leaderboard-mode run.

The falsification half of the leaderboard census (see
scripts/leaderboard_census_assemble.py): a task-phase that has ever passed under
the board's own comparison cannot be called unwinnable, whichever defect it
carries. This walks every `results/leaderboard*.json` whose `leaderboard_mode` is
true - so grading regime `upstream`, none of the six comparison corrections -
and records, per task, how many of those runs passed each phase and which ones.

Both arms and every agent model count: the claim is about the TASK, not about the
semantic layer.

    PYTHONPATH=. .venv-adk/bin/python scripts/leaderboard_census_extract_evidence.py \
        ../../bird-atscale-models/census/lb1_pass_evidence.json
"""
import glob
import json
import os
import sys

RESULTS = "results/leaderboard*.json"


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    out, runs = {}, []
    for p in sorted(glob.glob(RESULTS)):
        d = json.load(open(p))
        if not d.get("leaderboard_mode"):
            print("skip (not leaderboard mode):", p)
            continue
        dev = d.get("deviations") or {}
        meta = dict(file=os.path.basename(p), backend=d.get("backend"),
                    agent=d.get("agent_model"), sim=d.get("user_sim_model"),
                    regime=dev.get("grading_regime"),
                    corrections=dev.get("grading_corrections"),
                    n=len(d["results"]), started=d.get("run_started"))
        runs.append(meta)
        for r in d["results"]:
            t = r.get("instance_id") or r["task_id"]
            e = out.setdefault(t, {"db": r.get("database"), "cat": r.get("category"),
                                   "p1": 0, "p2": 0, "n": 0, "p1_by": [], "p2_by": []})
            e["n"] += 1
            if r.get("phase1_passed"):
                e["p1"] += 1
                e["p1_by"].append(meta["file"])
            if r.get("phase2_passed"):
                e["p2"] += 1
                e["p2_by"].append(meta["file"])
        del d  # these files are ~100MB each; one at a time
        print("ok", meta["file"], meta["backend"], meta["agent"], meta["regime"],
              meta["n"], flush=True)

    json.dump({"runs": runs, "tasks": out}, open(sys.argv[1], "w"), indent=1)
    print("runs", len(runs), "task-runs", sum(r["n"] for r in runs), "tasks", len(out))


if __name__ == "__main__":
    main()
