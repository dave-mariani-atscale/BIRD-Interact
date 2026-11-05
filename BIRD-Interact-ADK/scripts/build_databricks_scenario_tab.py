#!/usr/bin/env python3
"""Build "AtScale vs Databricks scenario" tabs in the layout of the results workbook's
"Modified Harness 09-10  Sonnet " tab, one tab per Databricks scenario run.

The 09-10 tab compares the AtScale arm (n=3) with a baseline arm (raw, n=3). Each tab built
here keeps every column, section, formula, format and outline group of that tab: the AtScale
columns are the 09-10 AtScale run, unchanged, and the baseline columns (the ones headed
"Raw") hold the Databricks scenario run instead, so Delta and Lift read AtScale minus / over
Databricks exactly as they read AtScale over raw there.

Columns that are rebuilt rather than carried over:
  - the Databricks half of every section, from the scenario's results file;
  - P1 unsolvable counts (CJ) from the workbook's current Task Census tab, with AtScale's
    achievable-only passes (CL mean of 3 runs, CS best run) recomputed from its result files,
    so both arms are adjusted against the same task list;
  - the phase-2 adjusted columns (AJ, AK, AL, CK, CN, CO, CT) are "n/a": the census records
    phase-2 blockers as free text, so a phase-2 achievable list cannot be rebuilt reliably.

    PYTHONPATH=. .venv-adk/bin/python scripts/build_databricks_scenario_tab.py \\
        --source /path/to/BIRD\\ Results.xlsx --out /tmp/databricks_tabs.xlsx \\
        --tab "DBX S1 Metric Views + Sonnet" 1 results/.../dbx_metric_views_*.json \\
        --tab "DBX S2 Metric Views + Genie" 2 results/.../dbx_genie_space_*.json

The output workbook holds only the new tabs, or with --keep-source-tabs every tab of the source
workbook with the new ones after the 09-10 tab.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import re
import statistics
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SRC_TAB = "Modified Harness 09-10  Sonnet "
CENSUS_TAB = "Task Census"
ATSCALE_GLOB = "results/full0910_atscale_run0[123]_*.json"
FIRST, LAST, ALL, BEST, NOTES = 6, 27, 28, 29, 30

SCENARIOS = {
    "1": ("Metric Views + 3rd-party agent", "dbx_metric_views",
          "The BIRD agent (Sonnet 5) discovers and queries the task database's Unity Catalog metric views "
          "itself (list_metric_views 1 coin, describe_metric_view 1, run_query 1), and submits its own SQL."),
    "2": ("Metric Views + Genie Agent (Genie space)", "dbx_genie_space",
          "The BIRD agent (Sonnet 5) hands every question to Genie in a Genie space holding only that "
          "database's metric views (ask_genie 1 coin, 0.5 when Genie runs no query), and submits the SQL "
          "Genie wrote. Genie runs as the workspace owner, so it may fall back to base tables; that is "
          "allowed and recorded."),
    "3": ("Metric Views + Genie Ontology (Genie One)", "dbx_genie_ontology",
          "The BIRD agent (Sonnet 5) hands every question to Genie One, grounded in the workspace's Genie "
          "Ontology, which chooses its sources (metric views, base tables, anything the owner can read). "
          "ask_genie 1 coin, 0.5 when Genie runs no query."),
}
QUERIES_RE = re.compile(r"# Queries Genie ran \((\d+);")


def load(path):
    d = json.load(open(path))
    return d, [r for r in d["results"] if r.get("category", "Query") == "Query"]


def census(wb):
    """task -> True when the current Task Census tiers it unsolvable at phase 1."""
    out = {}
    for r in wb[CENSUS_TAB].iter_rows(min_row=2, values_only=True):
        if r[0]:
            out[r[0]] = str(r[3] or "").startswith("unsolvable")
    return out


def as_bool(v):
    return v is True or str(v).lower() == "true"


def per_db(results, backend):
    """{db: stats} for one run."""
    acc = collections.defaultdict(lambda: collections.defaultdict(float))
    tasks = collections.defaultdict(list)
    for r in results:
        db = r["database"]
        a = acc[db]
        tasks[db].append(r["task_id"])
        p1, p2 = as_bool(r.get("phase1_passed")), as_bool(r.get("phase2_passed"))
        a["n"] += 1; a["p1"] += p1; a["p2"] += p2
        a["reward"] += float(r.get("total_reward") or 0)
        a["coins"] += float(r.get("budget_used") or 0)
        a["oob"] += 1 if float(r.get("budget_remaining") or 0) <= 0 else 0
        a["secs"] += float(r.get("elapsed_seconds") or 0)
        traj = r.get("tool_trajectory") or []
        a["turns"] += len(r.get("adk_events") or [])          # the 09-10 tab's turns/Q: ADK events per task
        for t in traj:
            res = str(t.get("result") or "")
            if backend == "dbx_metric_views" and t.get("tool") == "run_query":
                a["queries"] += 1
                a["errors"] += res.lstrip().startswith("Error")
            elif backend != "dbx_metric_views" and t.get("tool") == "ask_genie":
                m = QUERIES_RE.search(res)
                a["queries"] += int(m.group(1)) if m else (1 if "# SQL Genie ran" in res else 0)
                a["errors"] += res.lstrip().startswith("Error")
    return acc, tasks


def passes_on(results, ok_tasks, phase="phase1_passed"):
    c = collections.Counter()
    for r in results:
        if r["task_id"] in ok_tasks and as_bool(r.get(phase)):
            c[r["database"]] += 1
    return c


def fmt_ts(x):
    return dt.datetime.fromtimestamp(float(x)).strftime("%Y-%m-%d %H:%M")


def build_tab(wb, src, name, scen, results_path, at_runs, unsolv):
    label, backend, describe = SCENARIOS[scen]
    meta, res = load(results_path)
    stats, _ = per_db(res, backend)
    ws = wb.copy_worksheet(src)
    ws.title = name
    for cf in src.conditional_formatting:                      # copy_worksheet does not carry these
        for rule in cf.rules:
            ws.conditional_formatting.add(str(cf.sqref), rule)
    ws.freeze_panes = src.freeze_panes

    # Labels: the baseline arm is Databricks.
    for c in ws[5]:
        if isinstance(c.value, str):
            c.value = c.value.replace("Raw", "Databricks")
    for row in range(FIRST, BEST + 1):
        for col in ("BA", "BB"):
            v = ws[f"{col}{row}"].value
            if isinstance(v, str):
                ws[f"{col}{row}"].value = (v.replace('"Raw clears gate"', '"Databricks clears gate"')
                                           .replace('" / raw "', '" / dbx "').replace('", raw r"', '", Databricks r"'))

    ok_p1 = {t for t, u in unsolv.items() if not u}
    at_ok = [passes_on(r, ok_p1) for r in at_runs]
    at_reward = [sum(float(x.get("total_reward") or 0) for x in r) for r in at_runs]
    best = max(range(len(at_runs)), key=lambda i: at_reward[i])
    dbx_ok = passes_on(res, ok_p1)
    # task id -> database from the AtScale files (handles *_M_* ids)
    t2db = {x["task_id"]: x["database"] for x in at_runs[0]}
    unsolv_db = collections.Counter(t2db.get(t) for t, u in unsolv.items() if u and t in t2db)

    for row in range(FIRST, LAST + 1):
        db = ws[f"A{row}"].value
        a = stats.get(db)
        if not a:
            raise SystemExit(f"{name}: no {backend} results for database {db}")
        n = a["n"]
        assert int(n) == int(ws[f"C{row}"].value), (db, n, ws[f"C{row}"].value)
        r = row
        ws[f"M{r}"], ws[f"N{r}"], ws[f"O{r}"] = a["p1"] / n, None, None
        ws[f"L{r}"] = f"=AVERAGE(M{r}:O{r})"
        ws[f"S{r}"] = a["p1"]
        ws[f"AC{r}"], ws[f"AD{r}"], ws[f"AE{r}"] = a["p2"] / n, None, None
        ws[f"AB{r}"] = f"=AVERAGE(AC{r}:AE{r})"
        ws[f"AI{r}"] = a["p2"]
        ws[f"AU{r}"], ws[f"AV{r}"], ws[f"AW{r}"] = a["reward"] / n, None, None
        ws[f"AT{r}"] = f"=AVERAGE(AU{r}:AW{r})"
        ws[f"AZ{r}"] = f"=2*STDEVP(AP{r}:AR{r})"
        ws[f"BA{r}"] = "AtScale runs (Databricks n=1)"
        ws[f"BE{r}"] = a["coins"] / n
        ws[f"BG{r}"] = f'=IF(S{r}>0,BE{r}*C{r}/S{r},"n/a")'
        ws[f"BK{r}"] = a["turns"] / n
        ws[f"BM{r}"] = a["oob"]
        ws[f"BO{r}"] = a["secs"] / n
        ws[f"BT{r}"] = a["queries"]
        ws[f"BU{r}"] = a["errors"]
        ws[f"CJ{r}"] = unsolv_db.get(db, 0)
        ws[f"CL{r}"] = sum(c[db] for c in at_ok) / len(at_ok)
        ws[f"CS{r}"] = at_ok[best][db]
        ws[f"CM{r}"] = dbx_ok[db]
        for col in ("AJ", "AK", "AL", "CK", "CN", "CO", "CT"):
            ws[f"{col}{r}"] = "n/a"
    for col in ("AJ", "AK", "AL", "CK", "CN", "CO", "CT"):
        ws[f"{col}{ALL}"] = "n/a"
        if ws[f"{col}{BEST}"].value is not None:
            ws[f"{col}{BEST}"] = "n/a"
    # Run columns the Databricks arm did not fill stay blank in the total row (not 0.0%).
    for col in ("M", "N", "O", "AC", "AD", "AE", "AU", "AV", "AW"):
        f = ws[f"{col}{ALL}"].value
        if isinstance(f, str) and f.startswith("="):
            ws[f"{col}{ALL}"] = f'=IF(COUNT({col}{FIRST}:{col}{LAST})=0,"",{f[1:]})'
    ws[f"BG{ALL}"] = f"=SUMPRODUCT(BE{FIRST}:BE{LAST},C{FIRST}:C{LAST})/SUM(S{FIRST}:S{LAST})"
    ws[f"AZ{ALL}"] = f"=SUMPRODUCT(AZ{FIRST}:AZ{LAST},$C${FIRST}:$C${LAST})/SUM($C${FIRST}:$C${LAST})"

    # Title, provenance, notes.
    ws["A1"] = f"BIRD-Interact head-to-head, all 22 databases: AtScale vs Databricks scenario {scen} ({label})"
    p1 = sum(a["p1"] for a in stats.values()) / 410
    p2 = sum(a["p2"] for a in stats.values()) / 410
    rw = sum(a["reward"] for a in stats.values()) / 410
    secs = sum(a["secs"] for a in stats.values()) / 410
    ws["A2"] = (
        f"DATABRICKS ARM n=1, scenario {scen}: {label}. {fmt_ts(meta['run_started'])} -> {fmt_ts(meta['run_finished'])}: "
        f"all 22 databases, 410 query tasks x 1 run, concurrency {meta.get('concurrency')}. {describe} "
        "Same agent and user simulator (Sonnet 5), a-interact mode, the 2026-09-10 AtScale instruction with only the "
        "tool lines rewritten, and the same six grading corrections applied live. Databricks workspace "
        "adb-6969958581353382, SQL warehouse b1a1ad089fa01319, 119 metric views over the 22 BIRD databases "
        "(AtScaleInc/bird-databricks-models), built from the SML models, knowledge base and business questions, never "
        "the gold SQL. Submitted SQL is graded by re-executing it on the warehouse. "
        f"File: {Path(results_path).name}. Task-mean P1 {p1:.1%} / P2 {p2:.1%} / reward {rw:.4f}, wall-clock "
        f"{secs:.0f}s per question. ATSCALE ARM IS THE 2026-09-10 RUN, UNCHANGED from the 'Modified Harness 09-10  "
        "Sonnet' tab (n=3, files full0910_atscale_run01-03), except the census-based columns described in the notes. "
        "The Databricks arm fills the columns that tab gives to the raw arm; its r2 and r3 columns are empty.")
    for row in range(NOTES, ws.max_row + 1):
        for c in ws[row]:
            c.value = None
    notes = [
        f"ROW 29 IS THE LEADERBOARD-CONVENTION FIGURE: each arm's best single run by reward over all 410 tasks. "
        f"For AtScale that is r{best + 1}; for Databricks it is r1, its only run. Row 28 is the task-mean (AtScale's "
        "3-run mean) and remains the basis for every other metric.",
        "LIFT IS ATSCALE OVER DATABRICKS: 1.20x means AtScale returns 1.2x Databricks; below 1.00x means Databricks "
        "is ahead. Delta is AtScale minus Databricks. Cost and time lift run the other way (Databricks divided by "
        "AtScale), so above 1.00x means AtScale is cheaper or faster per question passed or per reward point.",
        "NOISE GATE is 2 x the population sd of AtScale's three runs on that database. The Databricks arm ran once, so "
        "it has no spread of its own; a database where the reward difference exceeds the gate is marked in Verdict.",
        f"UNSOLVABLE COUNTS (CJ) ARE FROM THE CURRENT TASK CENSUS TAB OF THE BIRD RESULTS WORKBOOK ({sum(unsolv.values())} phase-1 unsolvable "
        "tasks), not the revision-5 counts on the 09-10 tab, so AtScale's adjusted figures (CL, CS, U) are recomputed "
        "from its result files against the same list as Databricks'. The phase-2 adjusted columns are n/a: the census "
        "records phase-2 blockers as free text, so a phase-2 achievable list cannot be rebuilt reliably.",
        ("QUERIES ARE THE AGENT'S run_query CALLS and errors are the ones that returned an error, as for AtScale's "
         "run_query. Turns per question are ADK events per task, as on the 09-10 tab." if backend == "dbx_metric_views" else
         "QUERIES ARE THE SQL STATEMENTS GENIE RAN on the agent's behalf (every statement of every ask_genie turn) and "
         "errors are ask_genie turns that failed. Turns per question are ADK events per task, as on the 09-10 tab."),
        "ATSCALE QUERY AND ERROR COUNTS ARE SUMS OVER ITS THREE RUNS (as on the 09-10 tab) and Databricks' are one "
        "run, so compare the error rates, not the counts.",
        "WALL-CLOCK IS ONLY ROUGHLY COMPARABLE: the AtScale run used concurrency 5 against its own engine; this run "
        f"used concurrency {meta.get('concurrency')} against one Databricks SQL warehouse"
        + (" and the Genie API, which is rate limited" if backend != "dbx_metric_views" else "") + ".",
        "AGGREGATE AND CACHE (BX:CG) are AtScale engine measures and are blank, as on the 09-10 tab.",
    ]
    if backend == "dbx_genie_space":
        notes.append("BASE-TABLE FALLBACK: Genie could read the base tables but every graded submission of this run "
                     "read metric views only (checked in the grading audit).")
    for i, text in enumerate(notes):
        ws[f"A{NOTES + i}"] = text
    # The source tab is formatted down to row 1000; drop the empty rows so the file stays small.
    last = NOTES + len(notes)
    if ws.max_row > last:
        ws.delete_rows(last + 1, ws.max_row - last)
    for r in list(ws.row_dimensions):
        if r > last:
            del ws.row_dimensions[r]
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tab", nargs=3, action="append", metavar=("NAME", "SCENARIO", "RESULTS"), required=True)
    ap.add_argument("--atscale", default=ATSCALE_GLOB)
    ap.add_argument("--keep-source-tabs", action="store_true",
                    help="keep every tab of the source workbook; the new tabs go right after the 09-10 tab")
    a = ap.parse_args()
    wb = openpyxl.load_workbook(a.source)
    src = wb[SRC_TAB]
    unsolv = census(wb)
    at_runs = [load(p)[1] for p in sorted(glob.glob(a.atscale))]
    assert len(at_runs) == 3, a.atscale
    # The AtScale columns are carried over: check they agree with the AtScale files.
    for row in range(FIRST, LAST + 1):
        db = src[f"A{row}"].value
        for k, col in enumerate("IJK"):
            rs = [x for x in at_runs[k] if x["database"] == db]
            mine = sum(as_bool(x.get("phase1_passed")) for x in rs) / len(rs)
            if abs(mine - float(src[f"{col}{row}"].value)) > 1e-6:
                print(f"warning: AtScale r{k + 1} P1 {db}: tab {src[f'{col}{row}'].value} vs files {mine}")
    built = [build_tab(wb, src, n, s, p, at_runs, unsolv).title for n, s, p in a.tab]
    if a.keep_source_tabs:
        order = [s for s in wb._sheets if s.title not in built]
        at = order.index(src) + 1
        order[at:at] = [wb[n] for n in built]
        wb._sheets = order
    else:
        for name in list(wb.sheetnames):
            if name not in built:
                del wb[name]
    wb.active = 0
    wb.save(a.out)
    print("wrote", a.out, "tabs:", wb.sheetnames)


if __name__ == "__main__":
    main()
