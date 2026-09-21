#!/usr/bin/env python3
"""Assemble the LEADERBOARD-MODE unwinnable census (revision LB1).

Inputs, all measured, none hand-entered:

  --measurements  scripts/leaderboard_census.py output: gold executed under both
                  cleanups, the replan order test, per phase.
  --evidence      per-task phase-1/phase-2 pass counts over every leaderboard-mode
                  run (grading regime `upstream`, all six comparison corrections
                  off), both arms, every agent model.
  --rev3/--rev5   the corrected-regime task census. Revision 3 was judged under
                  the strict regime (all deviations off but timestamp-to-date),
                  i.e. the board's rules; revision 4 then WAIVED a set of tasks
                  by adopting casefold_text and column_order_free as census
                  rules, and revision 5 falsified others with live passes scored
                  under the corrected regime. Both waivers are void on the board.

A task-phase is UNWINNABLE in leaderboard mode when it has

  (a) a cited census reason - a verified gold defect, a plan-dependent answer, or
      a reason revision 4/5 waived only because a grading correction covered it;
      AND
  (b) zero passes in every leaderboard-mode run recorded to date.

(b) is what keeps the census honest: a single live pass under the board's own
comparison falsifies any claim of unwinnability, the same rule revision 5 used.
It also means the count is a LOWER bound - a task that no agent has yet won and
that carries no cited defect is left OUT (reported as `residual`).

`board_cleanup_mangles_gold` is counted separately, not in the headline. Upstream's
remove_distinct deletes the word DISTINCT from `DISTINCT ON (...)` and
`IS [NOT] DISTINCT FROM`, so the BOARD's grader executes a mangled gold and scores
0 whatever is submitted; this harness keeps both operators, so the same task is
winnable here. Those tasks are unwinnable on the board and winnable in our tabs,
which is the one place the two regimes disagree in our favour.

    PYTHONPATH=. .venv-adk/bin/python scripts/leaderboard_census_assemble.py \
        --measurements scratch/lb_census/measurements.json \
        --evidence scratch/lb_census/lb_evidence.json \
        --out-json census_lb1.json --out-md CENSUS_LB1.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

CENSUS = "/Users/davidmariani/workspace/atscale/bird-atscale-models/census/"
DB_ORDER = [
    "archeology_scan", "exchange_traded_funds", "solar_panel", "households",
    "cybermarket_pattern", "organ_transplant", "labor_certification_applications",
    "crypto_exchange", "fake_account", "reverse_logistics", "polar_equipment",
    "disaster_relief", "cold_chain_pharma_compliance", "museum_artifact",
    "robot_fault_prediction", "mental_health", "planets_data", "insider_trading",
    "cross_border", "sports_events", "virtual_idol", "hulushows",
]


def short(why, n=240):
    return " ".join((why or "").split())[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measurements", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--rev3", default=CENSUS + "census_rev3_final.json")
    ap.add_argument("--rev4", default=CENSUS + "census_rev4_final.json")
    ap.add_argument("--rev5", default=CENSUS + "census_rev5_final.json")
    ap.add_argument("--revision", default="LB1",
                    help="revision label stamped into the census file; bump it "
                         "when re-assembling over a wider set of runs")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md")
    a = ap.parse_args()

    M = json.load(open(a.measurements))
    ev = json.load(open(a.evidence))
    E, RUNS = ev["tasks"], ev["runs"]
    r3 = json.load(open(a.rev3))
    r4 = json.load(open(a.rev4))
    r5 = json.load(open(a.rev5))

    tasks = {}
    for tid, m in M.items():
        db, cat = m["db"], m["category"]
        e = E.get(tid, {})
        rec = {"db": db, "category": cat,
               "tier_rev3": r3.get(tid, {}).get("tier"),
               "tier_rev4": r4.get(tid, {}).get("tier"),
               "tier_rev5": r5.get(tid, {}).get("tier"),
               "lb_runs": e.get("n", 0), "lb_p1_passes": e.get("p1", 0),
               "lb_p2_passes": e.get("p2", 0)}
        for ph in ("p1", "p2"):
            mp = m.get(ph) or {}
            reasons, board = [], []
            if mp.get("sql_mangled_by_upstream_cleanup"):
                # Management golds are not executed here; the mangling is textual
                # and decides the board's execution either way.
                if cat != "Query" or mp.get("gold_error_upstream"):
                    board.append("board_cleanup_mangles_gold")
            if mp.get("upstream_preprocess_error"):
                board.append("board_preprocess_typeerror")
            if cat == "Query":
                t3, t5 = rec["tier_rev3"], rec["tier_rev5"]
                if t5 == "T1":
                    reasons.append("gold_defect")
                if t5 == "T2":
                    reasons.append("plan_dependent")
                if mp.get("order_plan_dependent"):
                    reasons.append("order_plan_dependent_measured")
                t4 = rec["tier_rev4"]
                if t3 in ("T1", "T2") and t4 == "T4":
                    # Revision 4 waived these by adopting casefold_text and
                    # column_order_free as CENSUS rules: the tier moved, the
                    # `why` text still records the measured defect. Void here.
                    reasons.append("waived_rev4_correction")
                if t4 in ("T1", "T2") and t5 == "T4":
                    # Revision 5 falsified these with a live pass in the
                    # 2026-09-06/07 sweep, which was scored under the CORRECTED
                    # regime; the pass does not carry to the board's comparison.
                    reasons.append("falsified_rev5_under_corrections")
                if ph == "p2":
                    for f in ("gold_p2", "content_p2", "order_p2"):
                        if r5.get(tid, {}).get(f):
                            reasons.append(f)
            rec[ph] = {
                "reasons": reasons,
                "board_only": board,
                "passes": e.get("p1" if ph == "p1" else "p2", 0),
                "order": mp.get("order"), "cue": mp.get("cue"),
                "rows": mp.get("rows"),
            }
        for ph in ("p1", "p2"):
            r = rec[ph]
            r["unwinnable"] = bool(r["reasons"]) and r["passes"] == 0
            r["falsified"] = bool(r["reasons"]) and r["passes"] > 0
        # Phase 2 is only graded after phase 1 passes, so a phase-1 unwinnable
        # task is unwinnable at phase 2 whatever its own follow-up gold does.
        if rec["p1"]["unwinnable"]:
            rec["p2"]["reasons"] = rec["p2"]["reasons"] + ["p1_unwinnable"]
            rec["p2"]["unwinnable"] = True
            rec["p2"]["falsified"] = False
        rec["residual_p1"] = (not rec["p1"]["reasons"]) and rec["lb_p1_passes"] == 0
        rec["residual_p2"] = (not rec["p2"]["reasons"]) and rec["lb_p2_passes"] == 0
        rec["why_rev5"] = short(r5.get(tid, {}).get("why"))
        rec["why_rev3"] = short(r3.get(tid, {}).get("why"))
        tasks[tid] = rec

    per_db = defaultdict(lambda: Counter())
    for tid, r in tasks.items():
        k = per_db[r["db"]]
        cat = "q" if r["category"] == "Query" else "m"
        k[f"{cat}_n"] += 1
        for ph in ("p1", "p2"):
            if r[ph]["unwinnable"]:
                k[f"{cat}_unw_{ph}"] += 1
            if r[ph]["board_only"]:
                k[f"{cat}_board_{ph}"] += 1
        if r["residual_p1"]:
            k[f"{cat}_residual_p1"] += 1

    out = {
        "revision": a.revision,
        "regime": "leaderboard / upstream: none of the six comparison corrections",
        "runs_used": RUNS,
        "task_runs": sum(r["n"] for r in RUNS) if RUNS and "n" in RUNS[0] else None,
        "per_db": {db: dict(per_db[db]) for db in DB_ORDER},
        "tasks": tasks,
    }
    json.dump(out, open(a.out_json, "w"), indent=1)

    tot = Counter()
    for db in DB_ORDER:
        for k, v in per_db[db].items():
            tot[k] += v
    print(f"{'database':36s} {'Qs':>3s} {'U-P1':>5s} {'U-P2':>5s} {'board':>5s} {'resid':>5s}")
    for db in DB_ORDER:
        k = per_db[db]
        print(f"{db:36s} {k['q_n']:3d} {k['q_unw_p1']:5d} {k['q_unw_p2']:5d} "
              f"{k['q_board_p1']:5d} {k['q_residual_p1']:5d}")
    print(f"{'ALL 22':36s} {tot['q_n']:3d} {tot['q_unw_p1']:5d} {tot['q_unw_p2']:5d} "
          f"{tot['q_board_p1']:5d} {tot['q_residual_p1']:5d}")
    print()
    print("Management: n=%d, board-cleanup-mangled P1=%d P2=%d"
          % (tot["m_n"], tot["m_board_p1"], tot["m_board_p2"]))
    rc = Counter()
    for r in tasks.values():
        for ph in ("p1", "p2"):
            if r[ph]["unwinnable"]:
                for x in r[ph]["reasons"]:
                    rc[f"{ph} {x}"] += 1
    for k in sorted(rc):
        print(f"{rc[k]:4d}  {k}")
    print("falsified (reason but a live pass):",
          sum(1 for r in tasks.values() if r["p1"]["falsified"]))
    print("wrote", a.out_json)


if __name__ == "__main__":
    main()
