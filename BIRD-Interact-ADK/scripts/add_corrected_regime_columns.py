#!/usr/bin/env python3
"""Add a CORRECTED-REGIME comparison section to every "Leaderboard *" tab.

The leaderboard tabs are scored the way the board scores: upstream comparison,
none of this harness's six corrections, and the census that goes with it
(revision LB1). The *Modified Harness* tab is scored the other way: corrections
on, census revision 5. Read side by side the two adjusted rates look like a
contradiction, so this section puts the leaderboard runs' OWN submissions on the
Modified Harness tab's rules - same grading, same census, same
`passes / (Qs - unsolvable)` formula - and nothing else changes.

It answers exactly one question: how much of the difference between the two tabs
is the rules, and how much is the run? (Measured: the rules are worth about
1.5 points of adjusted phase 1; the rest is the protocol, chiefly the upstream
user simulator - docs/LEADERBOARD_TASK_CENSUS.md.)

Inputs. One `scripts/regrade_leaderboard_as_corrected.py` output per tab: the
run's recorded rows re-graded under both regimes, per task and phase, with the
upstream pass gated against the run's own recorded verdict. Tabs are matched to
regrade files by the run filenames in the tab's provenance paragraph (row 2).

Two properties of the corrected numbers, both stated on the tab:

  * Phase 1 is a true re-grade of every graded submission.
  * Phase 2 is a LOWER BOUND. A run only reaches phase 2 where phase 1 passed
    under the grading it ran with, so the ~28 tasks per run whose phase 1 flips
    to a pass under the corrections never submitted a phase-2 answer at all and
    cannot be credited one here.
  * Where a task has no audit row (gold could not be executed offline, 1-3 per
    run), the run's recorded verdict stands in. Those counts are printed.

    PYTHONPATH=. .venv-adk/bin/python scripts/add_corrected_regime_columns.py \
        --regrade scratch/regrade_09*.json --in-place
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as GL

DRIVE_XLSX = ("/Users/davidmariani/Library/CloudStorage/GoogleDrive-dave@atscale.com/"
              "Shared drives/Product/Benchmark/BIRD Benchmark/Results/"
              "BIRD Results 22db — 2026-09-01 (atscale n=3, Semantic Memory shapes, engine pr9967).xlsx")
REV5 = ("/Users/davidmariani/workspace/atscale/bird-atscale-models/census/"
        "census_rev5_final.json")
RESULTS = "results"
FIRST, LAST, ALL, BEST, NOTE = 6, 27, 28, 29, 30
NAVY, SAGE, BAND = "FF1F3864", "FFE2EFDA", "FFFFF2CC"
PCT, NUM = "0.0%", "0.0"
MARKER = " CORRECTED-REGIME COMPARISON (added 2026-09-16"

NOTE_ADD = (
    " CORRECTED-REGIME COMPARISON (added 2026-09-16). These columns are NOT leaderboard figures and "
    "must never be quoted as one. They take this tab's own runs and score them under the OTHER "
    "regime - the four unconditional comparison corrections plus the two tolerances, and census "
    "revision 5 (93 unsolvable at P1, 127 at P2) - which is what the Modified Harness tab uses, so "
    "the two tabs can be read against each other. Every submission is the same; only the grader and "
    "the census change. What it shows: the rules are worth about 1.5 points of adjusted phase 1, and "
    "the rest of the distance to the Modified Harness tab is the protocol, chiefly leaderboard mode "
    "serving upstream's user simulator without this harness's routing and fidelity rules "
    "(docs/LEADERBOARD_TASK_CENSUS.md). PHASE 2 CORRECTED IS A LOWER BOUND: a run only reaches phase "
    "2 where phase 1 passed under the grading it actually ran with, so the tasks whose phase 1 flips "
    "to a pass here never submitted a phase-2 answer and cannot be credited one.")


def tab_runs(ws):
    return set(re.findall(r"[\w.\-]+\.json", ws["A2"].value or ""))


def db_of_tasks():
    r5 = json.load(open(REV5))
    return {t: v["db"] for t, v in r5.items()}, r5


def census_counts(r5):
    per = defaultdict(lambda: {"n": 0, "u1": 0, "u2": 0, "unw1": set(), "unw2": set()})
    for t, v in r5.items():
        p = per[v["db"]]
        p["n"] += 1
        p1 = v["tier"] in ("T1", "T2")
        p2 = p1 or v.get("gold_p2") or v.get("content_p2") or v.get("order_p2")
        if p1:
            p["u1"] += 1
            p["unw1"].add(t)
        if p2:
            p["u2"] += 1
            p["unw2"].add(t)
    return per


def aggregate(regrade, files, db_of, per_census):
    """Per database: mean corrected passes over the tab's runs, all tasks and
    achievable-only, with the run's recorded verdict standing in where a task has
    no audit row."""
    runs = [f for f in regrade["per_task"] if f in files]
    if not runs:
        return None, 0, 0
    recorded = {}
    for f in runs:
        p = Path(RESULTS) / f
        d = json.load(open(p))
        recorded[f] = {r.get("instance_id") or r["task_id"]:
                       (1 if r.get("phase1_passed") else 0, 1 if r.get("phase2_passed") else 0)
                       for r in d["results"]}
        del d
    acc = defaultdict(lambda: defaultdict(float))
    fallbacks = 0
    for f in runs:
        pt = regrade["per_task"][f]
        for tid, db in db_of.items():
            for ph, idx in (("p1", 0), ("p2", 1)):
                cell = pt.get(f"{tid}|{ph}")
                if cell is not None:
                    v = cell["corrected"]
                else:
                    v = recorded[f].get(tid, (0, 0))[idx]
                    if ph == "p1" and tid in recorded[f]:
                        fallbacks += 1
                acc[db][f"{ph}_all"] += v
                if tid not in per_census[db][f"unw{ph[-1]}"]:
                    acc[db][f"{ph}_ach"] += v
    n = len(runs)
    for db in acc:
        for k in list(acc[db]):
            acc[db][k] /= n
    return acc, n, fallbacks


def style(c, *, fill=None, bold=False, color=None, fmt=None, center=False, wrap=False, size=10):
    if fill:
        c.fill = PatternFill("solid", fgColor=fill)
    c.font = Font(bold=bold, color=color or "FF000000", size=size)
    if fmt:
        c.number_format = fmt
    if center or wrap:
        c.alignment = Alignment(horizontal="center" if center else None,
                                vertical="center", wrap_text=wrap)


def upsert_note(ws, marker, text, next_markers=()):
    cur = ws[f"A{NOTE}"].value or ""
    i = cur.find(marker)
    if i < 0:
        ws[f"A{NOTE}"].value = cur + text
        return
    j = len(cur)
    for nm in next_markers:
        k = cur.find(nm, i + 1)
        if k >= 0:
            j = min(j, k)
    ws[f"A{NOTE}"].value = cur[:i] + text + cur[j:]


def headers(ws):
    return {ws.cell(5, c).value: GL(c) for c in range(1, ws.max_column + 2)
            if ws.cell(5, c).value}


def add_section(ws, acc, per_census, nruns):
    H = headers(ws)
    if "Query Qs" not in H or "Database" not in H:
        raise SystemExit(f"{ws.title}: layout not recognised")

    start = None
    for c in range(1, ws.max_column + 1):
        if str(ws.cell(4, c).value or "").startswith("CORRECTED-REGIME"):
            start = c
            break
    if start is None:
        start = ws.max_column + 2
        ws.column_dimensions[GL(start - 1)].width = 2
    for rng in [r for r in ws.merged_cells.ranges if r.min_row == 4 and r.min_col >= start]:
        ws.unmerge_cells(str(rng))
    for c in range(start, ws.max_column + 2):
        for r in range(4, NOTE):
            ws.cell(r, c).value = None

    cols, c = {}, start

    def add(name, head, width, fmt):
        nonlocal c
        cols[name] = GL(c)
        ws.column_dimensions[GL(c)].width = width
        cell = ws[f"{GL(c)}5"]
        cell.value = head
        style(cell, fill=NAVY, bold=True, color="FFFFFFFF", center=True, wrap=True)
        c += 1
        return cols[name]

    add("u1", "P1 unsolvable Qs (rev 5)", 12, "0")
    add("u2", "P2 unsolvable Qs (rev 5)", 12, "0")
    add("p1", "Query P1 % (corrected)", 12, PCT)
    add("p2", "Query P2 % (corrected, floor)", 13, PCT)
    add("a1", "P1 Qs passed, achievable only", 13, NUM)
    add("a2", "P2 Qs passed, achievable only", 13, NUM)
    add("adj1", "Query P1 Adjusted % (corrected)", 14, PCT)
    add("adj2", "Query P2 Adjusted % (corrected, floor)", 14, PCT)
    end = c - 1

    cell = ws.cell(4, start)
    cell.value = (f"CORRECTED-REGIME COMPARISON - SAME RUNS ON THE MODIFIED HARNESS TAB'S RULES "
                  f"(n={nruns}, not a leaderboard figure)")
    style(cell, fill=SAGE, bold=True, color=NAVY, center=True, wrap=True)
    ws.merge_cells(start_row=4, start_column=start, end_row=4, end_column=end)

    q = H["Query Qs"]
    for r in range(FIRST, LAST + 1):
        db = ws[f"{H['Database']}{r}"].value
        cen, a = per_census.get(db), acc.get(db)
        if not cen or a is None:
            raise SystemExit(f"{ws.title} row {r}: no data for {db!r}")
        ws[f"{cols['u1']}{r}"] = cen["u1"]
        ws[f"{cols['u2']}{r}"] = cen["u2"]
        ws[f"{cols['p1']}{r}"] = a["p1_all"] / cen["n"]
        ws[f"{cols['p2']}{r}"] = a["p2_all"] / cen["n"]
        ws[f"{cols['a1']}{r}"] = a["p1_ach"]
        ws[f"{cols['a2']}{r}"] = a["p2_ach"]
        for adj, ach, unw in (("adj1", "a1", "u1"), ("adj2", "a2", "u2")):
            ws[f"{cols[adj]}{r}"] = (f'=IF({q}{r}>{cols[unw]}{r},'
                                     f'{cols[ach]}{r}/({q}{r}-{cols[unw]}{r}),"n/a")')

    for key in ("u1", "u2", "a1", "a2"):
        ws[f"{cols[key]}{ALL}"] = f"=SUM({cols[key]}{FIRST}:{cols[key]}{LAST})"
    for key in ("p1", "p2"):
        ws[f"{cols[key]}{ALL}"] = (
            f"=SUMPRODUCT({cols[key]}{FIRST}:{cols[key]}{LAST},${q}${FIRST}:${q}${LAST})"
            f"/SUM(${q}${FIRST}:${q}${LAST})")
    for adj, ach, unw in (("adj1", "a1", "u1"), ("adj2", "a2", "u2")):
        ws[f"{cols[adj]}{ALL}"] = (f'=IF(SUM({q}{FIRST}:{q}{LAST})>{cols[unw]}{ALL},'
                                   f'{cols[ach]}{ALL}/(SUM({q}{FIRST}:{q}{LAST})-{cols[unw]}{ALL}),"n/a")')

    fmts = {"u1": "0", "u2": "0", "p1": PCT, "p2": PCT, "a1": NUM, "a2": NUM,
            "adj1": PCT, "adj2": PCT}
    for r in list(range(FIRST, LAST + 1)) + [ALL]:
        for key, fmt in fmts.items():
            ws[f"{cols[key]}{r}"].number_format = fmt
    for c2 in range(start, end + 1):
        cell = ws.cell(ALL, c2)
        cell.fill = PatternFill("solid", fgColor=BAND)
        cell.font = Font(bold=True, size=10)
        cell = ws.cell(BEST, c2)
        cell.fill = PatternFill("solid", fgColor=BAND)

    upsert_note(ws, MARKER, NOTE_ADD)
    return end - start + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regrade", nargs="+", required=True)
    ap.add_argument("--src", default=DRIVE_XLSX)
    ap.add_argument("--out")
    ap.add_argument("--in-place", action="store_true")
    a = ap.parse_args()
    if not a.out and not a.in_place:
        raise SystemExit("give --out <file.xlsx> or --in-place")

    regrades = [json.load(open(p)) for g in a.regrade for p in sorted(glob.glob(g))]
    db_of, r5 = db_of_tasks()
    per_census = census_counts(r5)

    wb = openpyxl.load_workbook(a.src)
    for n in [s for s in wb.sheetnames if s.startswith("Leaderboard")]:
        ws = wb[n]
        files = tab_runs(ws)
        match = [rg for rg in regrades if set(rg["per_task"]) & files]
        if not match:
            print(f"{n}: no regrade file covers {sorted(files)[:1]}... - skipped")
            continue
        acc, nruns, fb = aggregate(match[0], files, db_of, per_census)
        cnt = add_section(ws, acc, per_census, nruns)
        print(f"{n}: {cnt} corrected-regime columns from {nruns} run(s), "
              f"{fb} task-phase fallbacks to the recorded verdict")
    out = a.out or a.src
    if a.in_place:
        b = Path(out).with_name(Path(out).stem + f".bak_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx")
        shutil.copy2(a.src, b)
        print(f"backup: {b}")
    wb.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
