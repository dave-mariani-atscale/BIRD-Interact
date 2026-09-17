#!/usr/bin/env python3
"""Add a "Leaderboard <label>" tab to the BIRD Results workbook from
leaderboard-mode run files.

Follows the Summary-tab conventions: title row 1, provenance paragraph row 2,
merged colour-coded section headers row 4, column headers row 5, the 22
databases rows 6-27, the task-mean ALL row 28, the best-single-run row 29 and
the notes row 30, with two-wide separator columns so the outline groups
collapse independently.

Carries the three figures the BIRD-Interact leaderboard reports for a-Interact,
and names them as the board does:

  Success Rate  blended phase-1 pass rate x100, over all 600 tasks
  Reward        blended reward x100 (0.7 x phase1 + 0.3 x phase2)
  Efficiency    bird-coins. In Stress Mode - which the Full a-Interact board is -
                this is the BUDGET, and every listed entry shows 17.86, so it is
                a conformance check rather than a ranking. Coins actually used
                and coins per correct answer sit beside it as the informative
                numbers; the board's own note is that a higher value "means more
                interactive but also cost more", not better or worse.

    PYTHONPATH=. .venv-adk/bin/python scripts/build_leaderboard_tab.py \\
        --runs 'results/leaderboard_20260911_atscale_run0*.json' \\
        --label '09-11 Opus 4.6' --out /tmp/preview.xlsx     # or --in-place
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import glob
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as GL

GREY = "FFD9D9D9"
BLUE = "FFBDD7EE"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchestrator.ainteract import calculate_initial_budget  # noqa: E402

DRIVE_XLSX = ("/Users/davidmariani/Library/CloudStorage/GoogleDrive-dave@atscale.com/"
              "Shared drives/Product/Benchmark/BIRD Benchmark/Results/"
              "BIRD Results 22db — 2026-09-01 (atscale n=3, Semantic Memory shapes, engine pr9967).xlsx")
DATA = "bird-interact-full/bird_interact_data.jsonl"
DB_ROW_ORDER = [
    "archeology_scan", "exchange_traded_funds", "solar_panel", "households",
    "cybermarket_pattern", "organ_transplant", "labor_certification_applications",
    "crypto_exchange", "fake_account", "reverse_logistics", "polar_equipment",
    "disaster_relief", "cold_chain_pharma_compliance", "museum_artifact",
    "robot_fault_prediction", "mental_health", "planets_data", "insider_trading",
    "cross_border", "sports_events", "virtual_idol", "hulushows",
]
FIRST, LAST, ALL, BEST, NOTE = 6, 27, 28, 29, 30
NAVY, PALE, GREEN, GREEN2, YELLOW, PEACH = "FF1F3864", "FFBDD7EE", "FFC6E0B4", "FFA9D08E", "FFFFE699", "FFF8CBAD"


def load(paths):
    docs = [json.load(open(p)) for p in paths]
    budgets = {t["instance_id"]: calculate_initial_budget(t)
               for t in (json.loads(l) for l in open(DATA) if l.strip())}
    per = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    id2db = {r["task_id"]: r["database"] for d in docs for r in d["results"] if r.get("database")}
    for i, d in enumerate(docs, 1):
        for r in d["results"]:
            db = r.get("database") or id2db.get(r["task_id"]) or r["task_id"].rsplit("_", 1)[0]
            cat = r.get("category") or ("Management" if "_M_" in r["task_id"] else "Query")
            p1, p2 = int(bool(r.get("phase1_passed"))), int(bool(r.get("phase2_passed")))
            per[db][i][cat].append({
                "p1": p1, "p2": p2, "rw": 0.7 * p1 + 0.3 * p2,
                "coins": float(r.get("budget_used") or 0.0),
                "budget": budgets.get(r["task_id"], 0.0),
                "oob": 1 if (r.get("budget_remaining") or 0) <= 0 else 0,
            })
    meta = {"files": [Path(p).name for p in paths], "runs": len(docs),
            "agent": docs[0].get("agent_model"), "sim": docs[0].get("user_sim_model"),
            "lb": docs[0].get("leaderboard_mode"), "backend": docs[0].get("backend"),
            "regime": (docs[0].get("deviations") or {}).get("grading_regime"),
            "cost_scheme": docs[0].get("cost_scheme"),
            "usd": sum(d["llm_usage"]["total"]["cost_usd"] for d in docs),
            "started": [d.get("run_started") for d in docs],
            "finished": [d.get("run_finished") for d in docs]}
    return per, meta, docs


def agg(rows, key):
    return sum(r[key] for r in rows) / len(rows) if rows else None


def db_cols(per, db, nruns):
    runs = per.get(db, {})
    q = [x for i in runs for x in runs[i].get("Query", [])]
    m = [x for i in runs for x in runs[i].get("Management", [])]
    a = q + m
    per_run = {}
    for i in range(1, nruns + 1):
        rows = [x for c in runs.get(i, {}) for x in runs[i][c]]
        per_run[i] = ((agg(rows, "p1"), agg(rows, "p2"), agg(rows, "rw"))
                      if rows else (None, None, None))
    first = runs.get(min(runs), {}) if runs else {}
    passes = sum(x["p1"] for x in a)
    coins = sum(x["coins"] for x in a)
    return {
        "nq": len(first.get("Query", [])), "nm": len(first.get("Management", [])),
        "n": len(first.get("Query", [])) + len(first.get("Management", [])),
        "q": (agg(q, "p1"), agg(q, "p2")), "m": (agg(m, "p1"), agg(m, "p2")),
        "b": (agg(a, "p1"), agg(a, "p2"), agg(a, "rw")),
        "runs": per_run,
        "budget": agg(a, "budget"), "coins": agg(a, "coins"),
        "per_correct": (coins / passes) if passes else None,
        "oob": agg(a, "oob"),
    }


def query_reward_lift(cols, r):
    """Reward lift over the QUERY tasks only: BIRD's own 0.7*P1 + 0.3*P2, built
    from the two Query columns rather than read off the blended Reward column,
    which carries the 190 Management tasks both arms answer with the same raw
    Postgres tools."""
    a = f"(0.7*{cols['q_p1']}{r}+0.3*{cols['q_p2']}{r})"
    b = f"(0.7*{cols['raw_q_p1']}{r}+0.3*{cols['raw_q_p2']}{r})"
    return f'=IF(OR({cols["raw_q_p1"]}{r}="",{b}=0),"n/a",{a}/{b}-1)'


def style(c, *, fill=None, bold=False, color=None, fmt=None, center=False, wrap=False, size=10):
    if fill:
        c.fill = PatternFill("solid", fgColor=fill)
    c.font = Font(bold=bold, color=color or "FF000000", size=size)
    if fmt:
        c.number_format = fmt
    if center or wrap:
        c.alignment = Alignment(horizontal="center" if center else None, vertical="center", wrap_text=wrap)


def build(src, out, paths, label, in_place=False, raw_paths=None):
    per, meta, docs = load(paths)
    nr = meta["runs"]
    per_raw = raw_meta = None
    if raw_paths:
        per_raw, raw_meta, _ = load(raw_paths)
    wb = openpyxl.load_workbook(src)
    title = f"Leaderboard {label}"
    if title in wb.sheetnames:
        del wb[title]
    anchor = max((i for i, n in enumerate(wb.sheetnames) if n.startswith(("Summary", "Leaderboard"))), default=0)
    ws = wb.create_sheet(title, anchor + 1)

    cols, c = {}, 1
    def add(name, width=10):
        nonlocal c
        cols[name] = GL(c); ws.column_dimensions[GL(c)].width = width; c += 1
    sections = []
    def section(start, heading, fill):
        sections.append((start, c - 1, heading, fill))

    s = c; add("db", 32); add("nq", 8); add("nm", 8); add("n", 8); section(s, "MODEL", PALE); add("s0", 2)
    s = c; add("q_p1", 11); add("q_p2", 11); section(s, "QUERY TASKS (semantic layer)", GREEN); add("s1", 2)
    s = c; add("m_p1", 11); add("m_p2", 11); section(s, "MANAGEMENT TASKS (raw Postgres)", GREEN2); add("s2", 2)
    s = c; add("sr", 13); [add(f"sr_r{i}", 9) for i in range(1, nr + 1)]
    add("b_p2", 12); [add(f"p2_r{i}", 9) for i in range(1, nr + 1)]
    add("rw", 12); [add(f"rw_r{i}", 9) for i in range(1, nr + 1)]
    section(s, "BLENDED - THE LEADERBOARD'S OWN FIGURES (all 600 tasks)", YELLOW); add("s3", 2)
    s = c; add("eff", 12); add("coins", 12); add("percorr", 14); add("oob", 12)
    section(s, "EFFICIENCY - bird-coins", PEACH)
    if per_raw is not None:
        add("s4", 2)
        s = c; add("raw_q_p1", 12); add("raw_q_p2", 12); add("raw_sr", 12); add("raw_b_p2", 12); add("raw_rw", 12)
        section(s, "RAW ARM - NO SEMANTIC LAYER (control, n=%d)" % raw_meta["runs"], GREY)
        add("s5", 2)
        s = c; add("lift_q_p1", 13); add("lift_q_p2", 13); add("lift_q_rw", 13)
        # QUERY TASKS ONLY, deliberately. In leaderboard mode the 190 Management
        # tasks are routed to the raw Postgres tools on BOTH arms, so they are the
        # same system twice and a blended lift just dilutes the measurement toward
        # 1.0 with a third of the benchmark. The semantic layer only touches Query
        # tasks, so that is where a lift means anything.
        section(s, "LIFT - ATSCALE vs RAW (QUERY TASKS ONLY)", BLUE)

    ws["A1"] = f"BIRD-Interact-Full, leaderboard protocol - {label}"
    style(ws["A1"], bold=True, size=14)
    ws["A2"] = provenance(meta, label)
    style(ws["A2"], wrap=True, size=9)
    ws.row_dimensions[2].height = 120
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=min(c - 1, 30))
    for s0, e0, heading, fill in sections:
        cell = ws.cell(4, s0); cell.value = heading
        style(cell, fill=fill, bold=True, color=NAVY, center=True, wrap=True)
        if e0 > s0:
            ws.merge_cells(start_row=4, start_column=s0, end_row=4, end_column=e0)
    heads = {"db": "Database", "nq": "Query Qs", "nm": "Mgmt Qs", "n": "All Qs",
             "q_p1": "Query P1 %", "q_p2": "Query P2 %", "m_p1": "Mgmt P1 %", "m_p2": "Mgmt P2 %",
             "sr": "Success Rate (P1)", "rw": "Reward", "b_p2": "Blended P2 %",
             "eff": "Efficiency (budget)", "coins": "Coins used", "percorr": "Coins per correct",
             "oob": "% out of budget",
             "raw_q_p1": "Raw Query P1 %", "raw_q_p2": "Raw Query P2 %", "raw_sr": "Raw Success Rate (P1)",
             "raw_b_p2": "Raw Blended P2 %", "raw_rw": "Raw Reward",
             "lift_q_p1": "Query P1 lift", "lift_q_p2": "Query P2 lift",
             "lift_q_rw": "Query reward lift"}
    for i in range(1, nr + 1):
        heads[f"sr_r{i}"] = f"P1 r{i}"; heads[f"p2_r{i}"] = f"P2 r{i}"
        heads[f"rw_r{i}"] = f"Reward r{i}"
    for name, letter in cols.items():
        if name.startswith("s") and name[1:].isdigit():
            continue
        cell = ws[f"{letter}5"]; cell.value = heads.get(name, name)
        style(cell, fill=NAVY, bold=True, color="FFFFFFFF", center=True, wrap=True)
    ws.row_dimensions[5].height = 56
    ws.freeze_panes = "E6"

    PCT, R2, R1 = "0.0%", "0.00", "0.0"
    for i, db in enumerate(DB_ROW_ORDER):
        r = FIRST + i
        d = db_cols(per, db, nr)
        ws[f"{cols['db']}{r}"] = db
        for k in ("nq", "nm", "n"):
            ws[f"{cols[k]}{r}"] = d[k]
        for key, val, fmt in (("q_p1", d["q"][0], PCT), ("q_p2", d["q"][1], PCT),
                              ("m_p1", d["m"][0], PCT), ("m_p2", d["m"][1], PCT),
                              ("sr", d["b"][0], PCT), ("b_p2", d["b"][1], PCT), ("rw", d["b"][2], "0.000"),
                              ("eff", d["budget"], R2), ("coins", d["coins"], R2),
                              ("percorr", d["per_correct"], R2), ("oob", d["oob"], PCT)):
            cell = ws[f"{cols[key]}{r}"]; cell.value = val; cell.number_format = fmt
        for i2 in range(1, nr + 1):
            p1, p2, rw = d["runs"].get(i2, (None, None, None))
            for key, val, fmt in ((f"sr_r{i2}", p1, PCT), (f"p2_r{i2}", p2, PCT),
                                  (f"rw_r{i2}", rw, "0.000")):
                cell = ws[f"{cols[key]}{r}"]; cell.value = val; cell.number_format = fmt
        if per_raw is not None:
            dr = db_cols(per_raw, db, raw_meta["runs"])
            for key, val, fmt in (("raw_q_p1", dr["q"][0], PCT), ("raw_q_p2", dr["q"][1], PCT),
                                  ("raw_sr", dr["b"][0], PCT), ("raw_b_p2", dr["b"][1], PCT),
                                  ("raw_rw", dr["b"][2], "0.000")):
                cell = ws[f"{cols[key]}{r}"]; cell.value = val; cell.number_format = fmt
            for key, a_key, r_key in (("lift_q_p1", "q_p1", "raw_q_p1"),
                                      ("lift_q_p2", "q_p2", "raw_q_p2")):
                cell = ws[f"{cols[key]}{r}"]
                cell.value = (f'=IF(OR({cols[r_key]}{r}="",{cols[r_key]}{r}=0),"n/a",'
                              f'{cols[a_key]}{r}/{cols[r_key]}{r}-1)')
                cell.number_format = "+0%;-0%"
            cell = ws[f"{cols['lift_q_rw']}{r}"]
            cell.value = query_reward_lift(cols, r)
            cell.number_format = "+0%;-0%"

    ws[f"A{ALL}"] = "ALL 22 DATABASES (task-mean over runs)"
    for k in ("nq", "nm", "n"):
        ws[f"{cols[k]}{ALL}"] = f"=SUM({cols[k]}{FIRST}:{cols[k]}{LAST})"
    W = {"q_p1": "nq", "q_p2": "nq", "m_p1": "nm", "m_p2": "nm",
         "raw_q_p1": "nq", "raw_q_p2": "nq"}
    raw_keys = ["raw_q_p1", "raw_q_p2", "raw_sr", "raw_b_p2", "raw_rw"] if per_raw is not None else []
    for key in ("q_p1", "q_p2", "m_p1", "m_p2", "sr", "b_p2", "rw", "eff", "coins", "oob", *raw_keys,
                *[f"sr_r{i}" for i in range(1, nr + 1)], *[f"p2_r{i}" for i in range(1, nr + 1)],
                *[f"rw_r{i}" for i in range(1, nr + 1)]):
        L, w = cols[key], cols[W.get(key, "n")]
        cell = ws[f"{L}{ALL}"]
        cell.value = (f'=IF(SUM(${w}${FIRST}:${w}${LAST})=0,"n/a",'
                      f"SUMPRODUCT({L}{FIRST}:{L}{LAST},${w}${FIRST}:${w}${LAST})/SUM(${w}${FIRST}:${w}${LAST}))")
        cell.number_format = ws[f"{L}{FIRST}"].number_format
    # coins per correct pools: total coins / total correct, never a mean of ratios
    ws[f"{cols['percorr']}{ALL}"] = (f"=SUMPRODUCT({cols['coins']}{FIRST}:{cols['coins']}{LAST},"
                                     f"{cols['n']}{FIRST}:{cols['n']}{LAST})/"
                                     f"SUMPRODUCT({cols['sr']}{FIRST}:{cols['sr']}{LAST},"
                                     f"{cols['n']}{FIRST}:{cols['n']}{LAST})")
    ws[f"{cols['percorr']}{ALL}"].number_format = R2

    if per_raw is not None:
        for key, a_key, r_key in (("lift_q_p1", "q_p1", "raw_q_p1"),
                                  ("lift_q_p2", "q_p2", "raw_q_p2")):
            cell = ws[f"{cols[key]}{ALL}"]
            cell.value = f"={cols[a_key]}{ALL}/{cols[r_key]}{ALL}-1"
            cell.number_format = "+0%;-0%"
        cell = ws[f"{cols['lift_q_rw']}{ALL}"]
        cell.value = query_reward_lift(cols, ALL)
        cell.number_format = "+0%;-0%"

    ws[f"A{BEST}"] = "BEST SINGLE RUN (leaderboard reporting convention)"
    rr = [cols[f"rw_r{i}"] for i in range(1, nr + 1)]
    rng = f"{rr[0]}{ALL}:{rr[-1]}{ALL}"
    idx = f"MATCH(MAX({rng}),{rng},0)"
    sr_r = [cols[f"sr_r{i}"] for i in range(1, nr + 1)]
    ws[f"{cols['sr']}{BEST}"] = f"=INDEX({sr_r[0]}{ALL}:{sr_r[-1]}{ALL},{idx})"
    ws[f"{cols['rw']}{BEST}"] = f"=MAX({rng})"
    p2_r = [cols[f"p2_r{i}"] for i in range(1, nr + 1)]
    ws[f"{cols['b_p2']}{BEST}"] = f"=INDEX({p2_r[0]}{ALL}:{p2_r[-1]}{ALL},{idx})"
    ws[f"{cols['b_p2']}{BEST}"].number_format = PCT
    ws[f"{cols['eff']}{BEST}"] = f"={cols['eff']}{ALL}"
    ws[f"{cols['sr']}{BEST}"].number_format = PCT
    ws[f"{cols['rw']}{BEST}"].number_format = "0.000"
    ws[f"{cols['eff']}{BEST}"].number_format = R2
    ws[f"{cols['coins']}{BEST}"] = f'="best run by reward: r"&{idx}'
    for r in (ALL, BEST):
        for col in range(1, c):
            cell = ws.cell(r, col)
            cell.fill = PatternFill("solid", fgColor="FFFFF2CC"); cell.font = Font(bold=True, size=10)

    ws[f"A{NOTE}"] = (
        "HOW TO READ. The three columns the BIRD-Interact leaderboard reports for a-Interact are SUCCESS RATE "
        "(blended phase-1 pass rate, all 600 tasks), REWARD (blended 0.7*P1 + 0.3*P2) and EFFICIENCY (bird-coins). "
        "Multiply Success Rate and Reward by 100 to read them in the board's units. EFFICIENCY in Stress Mode - which "
        "the Full a-Interact board is - is the BUDGET, and every listed entry shows 17.86; ours matching it exactly is "
        "a protocol conformance check, not a ranking. The board's own note is that a higher value 'means more "
        "interactive but also cost more', so it is neither good nor bad on its own: COINS PER CORRECT is the "
        "informative efficiency number, and it falls as memory warms. Blended is Query + Management together, which is "
        "the leaderboard's denominator; Query tasks ran on the semantic layer and Management tasks on raw Postgres, "
        "routed per task inside the same run. Row 28 is the task-mean over runs (per-database cells are means; the ALL "
        "row weights them by question count, so it equals pooling all tasks). Row 29 is the best single run by reward, "
        "the convention the submission guidelines use.")
    style(ws[f"A{NOTE}"], wrap=True, size=9)
    ws.merge_cells(start_row=NOTE, start_column=1, end_row=NOTE, end_column=min(c - 1, 30))
    ws.row_dimensions[NOTE].height = 95

    if in_place:
        b = Path(out).with_name(Path(out).stem + f".bak_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx")
        shutil.copy2(src, b); print(f"backup: {b}")
    wb.save(out)
    print(f"wrote {out}: tab {title!r}, {c-1} columns, {nr} run(s)")


def provenance(meta, label):
    f = lambda ts: dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"
    return (f"LEADERBOARD PROTOCOL RUN ({label}). {meta['runs']} run(s) of all 600 BIRD-Interact-Full tasks: "
            f"{', '.join(meta['files'])}. Agent {meta['agent']}, user simulator {meta['sim']} on the UPSTREAM prompts "
            f"and token limits, grading regime {meta['regime']} (none of this harness's six comparison corrections are "
            f"applied), cost scheme {meta['cost_scheme']}, backend {meta['backend']}, leaderboard_mode={meta['lb']}. "
            f"Ran {f(min(x for x in meta['started'] if x))} to {f(max(x for x in meta['finished'] if x))}, "
            f"${meta['usd']:,.0f} of API spend. Management tasks are routed per task to the raw Postgres tools and the "
            f"raw grading path inside the same run, so all 600 score; Query tasks run on the semantic layer with every "
            f"run_query carrying disable_aggregates, so the engine neither reads nor learns an aggregate table and the "
            f"outbound SQL recorded for the submission touches only base tables. The feedback store was truncated and "
            f"every aggregate invalidated before run 1, so run 1 is COLD and any later run is warm on memory built "
            f"during this sweep. Built by scripts/build_leaderboard_tab.py.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--label", default=dt.date.today().strftime("%m-%d"))
    ap.add_argument("--src", default=DRIVE_XLSX)
    ap.add_argument("--out", default=None)
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--raw-runs", nargs="*", default=None)
    a = ap.parse_args()
    paths = sorted(p for g in a.runs for p in glob.glob(g))
    if not paths:
        raise SystemExit("no results files matched")
    if not a.out and not a.in_place:
        raise SystemExit("give --out <file.xlsx> or --in-place")
    raw_paths = sorted(p for g in (a.raw_runs or []) for p in glob.glob(g)) or None
    build(a.src, a.out or a.src, paths, a.label, in_place=a.in_place, raw_paths=raw_paths)


if __name__ == "__main__":
    main()
