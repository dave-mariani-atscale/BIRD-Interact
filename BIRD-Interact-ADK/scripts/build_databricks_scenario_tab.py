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

SCENARIOS = {   # consolidated 2026-11-08: the three Genie One scenarios (retired ones kept for old tabs)
    "1": ("Genie One on raw data (no Metric Views)", "dbx_genie_ontology_no_mv",
          "The BIRD agent (Sonnet 5) hands every question to Genie One, grounded in the workspace's Genie "
          "Ontology, running as the benchmark principal bird-benchmark-ontology, whose grants cover the 244 "
          "base tables of catalog bird and no metric view (verified before every run). ask_genie 1 coin, 0.5 "
          "when Genie runs no query."),
    "2": ("Genie One + Genie-generated Metric Views", "dbx_genie_ontology_genie_mv",
          "As scenario 1, but running as bird-benchmark-genie-mv, which also reads the 121 metric views Genie "
          "One authored itself in bird_genie_mv.<db> from the base tables, the knowledge base and the gold-free "
          "task questions (bird-databricks-models/genie_metric_views); the AtScale-generated views are invisible "
          "to it. ask_genie 1 coin, 0.5 when Genie runs no query."),
    "3": ("Genie One + AtScale-generated Metric Views", "dbx_genie_ontology",
          "The BIRD agent (Sonnet 5) hands every question to Genie One, grounded in the workspace's Genie "
          "Ontology, which chooses its sources (the 119 metric views generated from the AtScale SML models, "
          "base tables, anything the owner can read). ask_genie 1 coin, 0.5 when Genie runs no query."),
    "retired-1": ("Metric Views + 3rd-party agent", "dbx_metric_views",
          "The BIRD agent (Sonnet 5) discovers and queries the task database's Unity Catalog metric views "
          "itself (list_metric_views 1 coin, describe_metric_view 1, run_query 1), and submits its own SQL."),
    "retired-2": ("Metric Views + Genie Agent (Genie space)", "dbx_genie_space",
          "The BIRD agent (Sonnet 5) hands every question to Genie in a Genie space holding only that "
          "database's metric views (ask_genie 1 coin, 0.5 when Genie runs no query), and submits the SQL "
          "Genie wrote. Genie runs as the workspace owner, so it may fall back to base tables; that is "
          "allowed and recorded."),
}
SNOWFLAKE_SCENARIOS = {
    "sf1": ("Cortex Sense on raw data (no semantic views)", "sf_cortex_sense_raw", "BIRD_S1",
            "BIRD_SENSE.CONTEXTS.BIRD_BENCH_<DB> (the tables, comments, keys and query history of BIRD_BENCH.<DB>)",
            "whose grants cover the 244 base tables of BIRD_BENCH and no semantic view in the BIRD databases"),
    "sf2": ("Cortex Sense + CoCo-authored semantic views", "sf_cortex_sense_coco_views", "BIRD_S2",
            "BIRD_SENSE.CONTEXTS.BIRD_BENCH_<DB>_COCO (the tables of BIRD_BENCH.<DB>, the semantic views of "
            "BIRD_SENSE.COCO_<DB>, and query history on both)",
            "whose grants cover the 244 base tables of BIRD_BENCH and the 114 semantic views Cortex Code authored in "
            "BIRD_SENSE.COCO_<DB> from the base tables, the knowledge base and the gold-free task questions"),
    "sf3": ("Cortex Sense + AtScale-generated semantic views", "sf_cortex_sense_atscale_views", "BIRD_S3",
            "BIRD_SENSE.CONTEXTS.BIRD_BENCH_<DB>_ATSCALE", "whose grants cover the base tables and the AtScale-derived semantic views"),
}
for _k, (_label, _backend, _role, _ctx, _grants) in SNOWFLAKE_SCENARIOS.items():
    SCENARIOS[_k] = (_label, _backend,
        f"The BIRD agent (Sonnet 5) hands every question to a Cortex Agent (ask_cortex; orchestration model auto) whose "
        f"one tool is Cortex Sense bound to the database's context {_ctx}, running as role {_role}, {_grants} "
        "(verified before every run). ask_cortex 1 coin, 0.5 when Cortex runs no successful query.")
SNOWFLAKE = tuple(v[1] for v in SNOWFLAKE_SCENARIOS.values())
CORTEX_SECS_RE = re.compile(r"# Cortex's answer \(([0-9.]+)s\)")
GENIE_ONE = ("dbx_genie_ontology", "dbx_genie_ontology_no_mv", "dbx_genie_ontology_genie_mv")
#: The backend whose domains route_of classifies against (set per tab: scenario 2's views live in
#: bird_genie_mv.<db>, which only its domains know about).
ROUTE_BACKEND = "dbx_genie_ontology"
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
            elif backend in SNOWFLAKE and t.get("tool") == "ask_cortex":
                a["queries"] += len(SQL_BLOCK_RE.findall(res))
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


# ── Genie Ontology routing ──

ROUTES = ("metric_views", "base_tables", "mixed", "elsewhere", "unparsed")
ROUTE_LABEL = {"metric_views": "views only", "base_tables": "base tables only", "mixed": "views + tables",
               "elsewhere": "outside the database", "unparsed": "unparsed SQL", "none": "no SQL"}
SQL_BLOCK_RE = re.compile(r"```sql\n(.*?)\n```", re.S)
GENIE_SECS_RE = re.compile(r"status: \w+, ([0-9.]+)s\)")
VERDICT_RE = re.compile(r"\s*(?:SQL failed Phase (\d)|Phase (\d) correct)")


def route_of(sql, db, rejected=False):
    """metric_views | base_tables | mixed | elsewhere | none, for a statement on task database `db`."""
    from shared.environment_backends import get_domain_config, objects_read
    if rejected:
        return "elsewhere"
    if not sql:
        return "none"
    read = objects_read(sql, get_domain_config(ROUTE_BACKEND, db))
    if not read:
        return "unparsed"                          # sqlglot could not parse it
    if read.get("elsewhere"):
        return "elsewhere"
    v, b = bool(read.get("metric_views")), bool(read.get("base_tables"))
    return "mixed" if v and b else "metric_views" if v else "base_tables" if b else "unparsed"


def task_routes(r):
    """(route of the phase-1 answer, passed?), (route of the phase-2 answer, passed?), [route of each Genie turn].
    An answer is the submission that passed, else the last one of that phase; (None, False) when there was none."""
    db = r["database"]
    subs = {1: [], 2: []}
    turns = []
    for t in r.get("tool_trajectory") or []:
        res = str(t.get("result") or "")
        if t.get("tool") == "submit_sql":
            m = VERDICT_RE.match(res)                 # "SQL failed Phase N. ..." or "Phase N correct! ..."
            if m:
                phase, ok = int(m.group(1) or m.group(2)), bool(m.group(2))
                sql = (t.get("args") or {}).get("sql", "")
                subs[phase].append((sql, ok, "Query rejected" in res and "references" in res))
        elif t.get("tool") in ("ask_genie", "ask_cortex"):
            blocks = SQL_BLOCK_RE.findall(res)
            turns.append(route_of(blocks[-1], db) if blocks else "none")
    out = []
    for ph in (1, 2):
        if not subs[ph]:
            out.append((None, False)); continue
        sql, ok, rej = next((x for x in subs[ph] if x[1]), subs[ph][-1])
        out.append((route_of(sql, db, rej), ok))
    return out[0], out[1], turns


def add_routing_section(ws, src, runs, at_runs, max_runs=3):
    """Append the Genie Ontology routing columns after the census/time sections. Returns the note text."""
    from copy import copy
    from openpyxl.utils import column_index_from_string as CI, get_column_letter as GL

    per = collections.defaultdict(collections.Counter)          # db -> counters, pooled over runs
    base_by_run = [collections.Counter() for _ in runs]
    for k, run in enumerate(runs):
        for r in run:
            (r1, ok1), (r2, ok2), turns = task_routes(r)
            c = per[r["database"]]
            if r1:
                c[f"p1_{r1}"] += 1; c[f"p1ok_{r1}"] += ok1
                if r1 in ("base_tables", "mixed"):
                    base_by_run[k][r["database"]] += 1
            else:
                c["p1_none"] += 1
            if r2:
                c[f"p2_{r2}"] += 1; c[f"p2ok_{r2}"] += ok2
            for t in turns:
                c[f"turn_{t}"] += 1

    hdr4, hdr5 = src["CP4"], src["CP5"]
    STYLE = {"cnt": (src["R6"], src["R28"]), "pct": (src["H6"], src["H28"]),
             "sec": (src["BN6"], src["BN28"]), "x": (src["Q6"], src["Q28"])}
    col = CI("CT") + 1
    sections = []

    def put(c, row, value, style):
        cell = ws.cell(row=row, column=c, value=value)
        cell._style = copy(style._style)
        return cell

    def section(title, columns):
        nonlocal col
        ws.column_dimensions[GL(col)].width = 2                 # separator, as between the source's sections
        col += 1
        first = col
        for header, kind, values, total in columns:
            L = GL(col)
            put(col, 5, header, hdr5)
            for i, row in enumerate(range(FIRST, LAST + 1)):
                v = values(row) if callable(values) else values[i]
                put(col, row, v, STYLE[kind][0])
            put(col, ALL, total(L) if total else f"=SUM({L}{FIRST}:{L}{LAST})", STYLE[kind][1])
            ws.column_dimensions[L].width = 12
            col += 1
        put(first, 4, title, hdr4)
        for c in range(first + 1, col):
            put(c, 4, None, hdr4)
        ws.merge_cells(start_row=4, start_column=first, end_row=4, end_column=col - 1)
        sections.append((title, GL(first), GL(col - 1)))

    dbs = [ws[f"A{r}"].value for r in range(FIRST, LAST + 1)]
    for ph in (1, 2):
        cols = []
        for rt in ROUTES:
            n_col = GL(col + 1 + len(cols))                     # letters of this route's count / passed columns
            p_col = GL(col + 2 + len(cols))
            cols.append((f"P{ph} answers: {ROUTE_LABEL[rt]}", "cnt", [per[d][f"p{ph}_{rt}"] for d in dbs], None))
            cols.append((f"P{ph} passed: {ROUTE_LABEL[rt]}", "cnt", [per[d][f"p{ph}ok_{rt}"] for d in dbs], None))
            cols.append((f"P{ph} pass %: {ROUTE_LABEL[rt]}", "pct",
                         (lambda n_col, p_col: lambda row: f'=IF({n_col}{row}=0,"",{p_col}{row}/{n_col}{row})')(n_col, p_col),
                         (lambda n_col, p_col: lambda L: f'=IF({n_col}{ALL}=0,"n/a",{p_col}{ALL}/{n_col}{ALL})')(n_col, p_col)))
        if ph == 1:
            cols.append(("P1 tasks with no answer", "cnt", [per[d]["p1_none"] for d in dbs], None))
        section(f"GENIE ONTOLOGY ROUTING: PHASE-{ph} ANSWERS (all runs pooled)", cols)

    cols = [(f"P1 answers using base tables r{k + 1}", "cnt",
             [base_by_run[k][d] for d in dbs] if k < len(runs) else [None] * len(dbs),
             None if k < len(runs) else (lambda L: None)) for k in range(max_runs)]
    section("BASE-TABLE USE BY RUN (P1 answers: base tables only or views + tables)", cols)

    first_turn = col + 1
    cols = [(f"Genie turns: {ROUTE_LABEL[rt]}", "cnt", [per[d][f"turn_{rt}"] for d in dbs], None)
            for rt in ROUTES + ("none",)]
    tl = [GL(first_turn + i) for i in range(len(ROUTES) + 1)]
    share = lambda row: f'=IF(SUM({tl[0]}{row}:{tl[-1]}{row})=0,"",({tl[1]}{row}+{tl[2]}{row})/SUM({tl[0]}{row}:{tl[-1]}{row}))'
    cols.append(("Base-table share of Genie turns", "pct", share, lambda L: share(ALL)))
    section("GENIE TURNS BY SOURCE (every ask_genie turn, all runs pooled)", cols)

    # ── time: AtScale vs Genie Ontology, per question, by run ──
    def per_run_times(run):
        t = collections.defaultdict(lambda: collections.defaultdict(float))
        for r in run:
            a = t[r["database"]]
            a["n"] += 1
            a["secs"] += float(r.get("elapsed_seconds") or 0)
            a["p1"] += float(r.get("phase1_elapsed_seconds") or 0)
            a["p2"] += float(r.get("phase2_elapsed_seconds") or 0)
            for x in r.get("tool_trajectory") or []:
                if x.get("tool") in ("ask_genie", "ask_cortex"):
                    a["calls"] += 1
                    m = (CORTEX_SECS_RE if x.get("tool") == "ask_cortex" else GENIE_SECS_RE).search(str(x.get("result") or ""))
                    a["gsecs"] += float(m.group(1)) if m else 0.0
        return t
    go_t = [per_run_times(r) for r in runs]
    at_t = [per_run_times(r) for r in at_runs]
    at_mean = lambda d, key: sum(t[d][key] for t in at_t) / sum(t[d]["n"] for t in at_t)
    wtd = lambda L: f"=SUMPRODUCT({L}{FIRST}:{L}{LAST},$C${FIRST}:$C${LAST})/SUM($C${FIRST}:$C${LAST})"
    blank = lambda L: None
    first_time = col + 1
    cols = [("AtScale wall-clock/Q (s), 3-run mean", "sec", lambda row: f"=BN{row}", lambda L: f"=BN{ALL}"),
            ("AtScale phase-1 s/Q, 3-run mean", "sec", [at_mean(d, "p1") for d in dbs], wtd),
            ("AtScale phase-2 s/Q, 3-run mean", "sec", [at_mean(d, "p2") for d in dbs], wtd)]
    for k in range(max_runs):
        have = k < len(runs)
        for key, lab in (("secs", "wall-clock/Q (s)"), ("p1", "phase-1 s/Q"), ("p2", "phase-2 s/Q")):
            vals = [go_t[k][d][key] / go_t[k][d]["n"] for d in dbs] if have else [None] * len(dbs)
            cols.append((f"Genie Ontology {lab} r{k + 1}", "sec", vals, wtd if have else blank))
    gw = [GL(first_time + 3 + 3 * k) for k in range(max_runs)]            # Genie Ontology wall-clock columns
    gp = [GL(first_time + 4 + 3 * k) for k in range(max_runs)]            # Genie Ontology phase-1 columns
    at_w, at_p1 = GL(first_time), GL(first_time + 1)
    cols.append(("Slowdown, wall-clock (x): Genie Ontology / AtScale", "x",
                 lambda row: f'=IF({at_w}{row}=0,"",AVERAGE({gw[0]}{row},{gw[1]}{row},{gw[2]}{row})/{at_w}{row})',
                 lambda L: f'=AVERAGE({gw[0]}{ALL},{gw[1]}{ALL},{gw[2]}{ALL})/{at_w}{ALL}'))
    cols.append(("Slowdown, phase 1 (x): Genie Ontology / AtScale", "x",
                 lambda row: f'=IF({at_p1}{row}=0,"",AVERAGE({gp[0]}{row},{gp[1]}{row},{gp[2]}{row})/{at_p1}{row})',
                 lambda L: f'=AVERAGE({gp[0]}{ALL},{gp[1]}{ALL},{gp[2]}{ALL})/{at_p1}{ALL}'))
    section("TIME PER QUESTION: ATSCALE VS GENIE ONTOLOGY (seconds)", cols)

    first_calls = col + 1
    cols = []
    for k in range(max_runs):
        have = k < len(runs)
        c_col, s_col = GL(first_calls + 3 * k), GL(first_calls + 3 * k + 1)
        cols.append((f"Genie calls/Q r{k + 1}", "sec",
                     [go_t[k][d]["calls"] / go_t[k][d]["n"] for d in dbs] if have else [None] * len(dbs),
                     wtd if have else blank))
        cols.append((f"Genie s/call r{k + 1}", "sec",
                     [go_t[k][d]["gsecs"] / max(go_t[k][d]["calls"], 1) for d in dbs] if have else [None] * len(dbs),
                     (lambda c_col: lambda L: f"=SUMPRODUCT({L}{FIRST}:{L}{LAST},{c_col}{FIRST}:{c_col}{LAST},"
                      f"$C${FIRST}:$C${LAST})/SUMPRODUCT({c_col}{FIRST}:{c_col}{LAST},$C${FIRST}:$C${LAST})")(c_col)
                     if have else blank))
        cols.append((f"Waiting on Genie s/Q r{k + 1}", "sec",
                     (lambda c_col, s_col, have: lambda row: f"={c_col}{row}*{s_col}{row}" if have else None)(c_col, s_col, have),
                     wtd if have else blank))
    section("GENIE ONE CALLS (per question, by run)", cols)

    return ("GENIE ONTOLOGY ROUTING (" + ", ".join(f"{a}:{b}" for _, a, b in sections) + ") classifies the SQL by what it "
            "reads in the task database: its metric views only, its base tables only, both, or anything outside the "
            "database (another schema or catalog; refused at grading), or 'unparsed SQL' when the statement could not be "
            "parsed. A task's phase-1 or phase-2 answer is the "
            "submission that passed, else the last one of that phase; pass % is passed / answers for that source. "
            "Genie turns classify the SQL of each ask_genie answer; a turn with no SQL (a clarifying question, a "
            "refusal, an error) is 'no SQL'. Counts are summed over the runs. TIME: wall-clock and phase-1 / phase-2 "
            "seconds per question over all questions (phase 2 counts 0 for a question that never reached it); AtScale "
            "is the mean of its three 09-10 runs. Slowdown is the mean of Genie Ontology's runs divided by AtScale. "
            "Genie s/call is Genie One's own answer time per ask_genie call, from the tool result. Empty r2 / r3 "
            "columns are runs not yet finished.")


def build_tab(wb, src, name, scen, results_glob, at_runs, unsolv):
    label, backend, describe = SCENARIOS[scen]
    paths = sorted(glob.glob(results_glob))
    if not 1 <= len(paths) <= 3:
        raise SystemExit(f"{name}: {results_glob} matches {len(paths)} files; expected 1 to 3 runs")
    loaded = [load(p) for p in paths]
    metas, runs = [m for m, _ in loaded], [r for _, r in loaded]
    n_runs = len(runs)
    stats = [per_db(r, backend)[0] for r in runs]
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
    dbx_ok = [passes_on(r, ok_p1) for r in runs]
    # task id -> database from the AtScale files (handles *_M_* ids)
    t2db = {x["task_id"]: x["database"] for x in at_runs[0]}
    unsolv_db = collections.Counter(t2db.get(t) for t, u in unsolv.items() if u and t in t2db)

    def mean_of(db, key, per_task=True):
        tot = sum(st[db][key] for st in stats)
        return tot / sum(st[db]["n"] for st in stats) if per_task else tot / n_runs

    for row in range(FIRST, LAST + 1):
        db = ws[f"A{row}"].value
        if any(db not in st for st in stats):
            raise SystemExit(f"{name}: a {backend} run has no results for database {db}")
        n = stats[0][db]["n"]
        assert int(n) == int(ws[f"C{row}"].value), (db, n, ws[f"C{row}"].value)
        r = row
        for cols, key in ((("M", "N", "O"), "p1"), (("AC", "AD", "AE"), "p2"), (("AU", "AV", "AW"), "reward")):
            for k, col in enumerate(cols):
                ws[f"{col}{r}"] = stats[k][db][key] / stats[k][db]["n"] if k < n_runs else None
        ws[f"L{r}"] = f"=AVERAGE(M{r}:O{r})"
        ws[f"AB{r}"] = f"=AVERAGE(AC{r}:AE{r})"
        ws[f"AT{r}"] = f"=AVERAGE(AU{r}:AW{r})"
        ws[f"S{r}"] = mean_of(db, "p1", per_task=False)
        ws[f"AI{r}"] = mean_of(db, "p2", per_task=False)
        if n_runs > 1:
            ws[f"AZ{r}"] = f"=2*MAX(STDEVP(AP{r}:AR{r}),STDEVP(AU{r}:AW{r}))"
            ws[f"BA{r}"] = "both arms"
        else:
            ws[f"AZ{r}"] = f"=2*STDEVP(AP{r}:AR{r})"
            ws[f"BA{r}"] = "AtScale runs (Databricks n=1)"
        ws[f"BE{r}"] = mean_of(db, "coins")
        ws[f"BG{r}"] = f'=IF(S{r}>0,BE{r}*C{r}/S{r},"n/a")'
        ws[f"BK{r}"] = mean_of(db, "turns")
        ws[f"BM{r}"] = mean_of(db, "oob", per_task=False)
        ws[f"BO{r}"] = mean_of(db, "secs")
        ws[f"BT{r}"] = sum(st[db]["queries"] for st in stats)
        ws[f"BU{r}"] = sum(st[db]["errors"] for st in stats)
        ws[f"CJ{r}"] = unsolv_db.get(db, 0)
        ws[f"CL{r}"] = sum(c[db] for c in at_ok) / len(at_ok)
        ws[f"CS{r}"] = at_ok[best][db]
        ws[f"CM{r}"] = sum(c[db] for c in dbx_ok) / n_runs
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
    global ROUTE_BACKEND
    ROUTE_BACKEND = backend if backend in GENIE_ONE + SNOWFLAKE else "dbx_genie_ontology"
    routing_note = add_routing_section(ws, src, runs, at_runs) if backend in GENIE_ONE + SNOWFLAKE else None

    # Title, provenance, notes.
    ws["A1"] = f"BIRD-Interact head-to-head, all 22 databases: AtScale vs Databricks scenario {scen} ({label})"
    tot = lambda key: sum(st[db][key] for st in stats for db in st) / (410 * n_runs)
    p1, p2, rw, secs = tot("p1"), tot("p2"), tot("reward"), tot("secs")
    meta = metas[0]
    ws["A2"] = (
        f"DATABRICKS ARM n={n_runs}, scenario {scen}: {label}. {fmt_ts(metas[0]['run_started'])} -> "
        f"{fmt_ts(metas[-1]['run_finished'])}: all 22 databases, 410 query tasks x {n_runs} "
        f"{'run' if n_runs == 1 else 'sequential runs'}, concurrency {meta.get('concurrency')}. {describe} "
        "Same agent and user simulator (Sonnet 5), a-interact mode, the 2026-09-10 AtScale instruction with only the "
        "tool lines rewritten, and the same six grading corrections applied live. Databricks workspace "
        "adb-6969958581353382, SQL warehouse b1a1ad089fa01319, 119 metric views over the 22 BIRD databases "
        "(AtScaleInc/bird-databricks-models), built from the SML models, knowledge base and business questions, never "
        "the gold SQL. Submitted SQL is graded by re-executing it on the warehouse. "
        f"Files: {', '.join(Path(p).name for p in paths)}. Task-mean P1 {p1:.1%} / P2 {p2:.1%} / reward {rw:.4f}, wall-clock "
        f"{secs:.0f}s per question. ATSCALE ARM IS THE 2026-09-10 RUN, UNCHANGED from the 'Modified Harness 09-10  "
        "Sonnet' tab (n=3, files full0910_atscale_run01-03), except the census-based columns described in the notes. "
        "The Databricks arm fills the columns that tab gives to the raw arm"
        + ("; its r2 and r3 columns are empty." if n_runs == 1 else f", r1 to r{n_runs} in run order."))
    for row in range(NOTES, ws.max_row + 1):
        for c in ws[row]:
            c.value = None
    notes = [
        f"ROW 29 IS THE LEADERBOARD-CONVENTION FIGURE: each arm's best single run by reward over all 410 tasks. "
        f"For AtScale that is r{best + 1}; for Databricks it is "
        + ("r1, its only run." if n_runs == 1 else "the run named in BA29.")
        + " Row 28 is the task-mean over each arm's runs and remains the basis for every other metric.",
        "LIFT IS ATSCALE OVER DATABRICKS: 1.20x means AtScale returns 1.2x Databricks; below 1.00x means Databricks "
        "is ahead. Delta is AtScale minus Databricks. Cost and time lift run the other way (Databricks divided by "
        "AtScale), so above 1.00x means AtScale is cheaper or faster per question passed or per reward point.",
        ("NOISE GATE is 2 x the population sd of AtScale's three runs on that database. The Databricks arm ran once, so "
         "it has no spread of its own; a database where the reward difference exceeds the gate is marked in Verdict."
         if n_runs == 1 else
         "NOISE GATE is 2 x the population sd of the LARGER arm's runs on that database, as on the 09-10 tab; a "
         "database where the reward difference exceeds the gate is marked in Verdict."),
        f"UNSOLVABLE COUNTS (CJ) ARE FROM THE CURRENT TASK CENSUS TAB OF THE BIRD RESULTS WORKBOOK ({sum(unsolv.values())} phase-1 unsolvable "
        "tasks), not the revision-5 counts on the 09-10 tab, so AtScale's adjusted figures (CL, CS, U) are recomputed "
        "from its result files against the same list as Databricks'. The phase-2 adjusted columns are n/a: the census "
        "records phase-2 blockers as free text, so a phase-2 achievable list cannot be rebuilt reliably.",
        ("QUERIES ARE THE AGENT'S run_query CALLS and errors are the ones that returned an error, as for AtScale's "
         "run_query. Turns per question are ADK events per task, as on the 09-10 tab." if backend == "dbx_metric_views" else
         "QUERIES ARE THE SQL STATEMENTS GENIE RAN on the agent's behalf (every statement of every ask_genie turn) and "
         "errors are ask_genie turns that failed. Turns per question are ADK events per task, as on the 09-10 tab."),
        ("ATSCALE QUERY AND ERROR COUNTS ARE SUMS OVER ITS THREE RUNS (as on the 09-10 tab) and Databricks' are one "
         "run, so compare the error rates, not the counts." if n_runs == 1 else
         f"QUERY AND ERROR COUNTS ARE SUMS OVER EACH ARM'S RUNS (AtScale 3, Databricks {n_runs}), as on the 09-10 tab."),
        "WALL-CLOCK IS ONLY ROUGHLY COMPARABLE: the AtScale run used concurrency 5 against its own engine; this run "
        f"used concurrency {meta.get('concurrency')} against one Databricks SQL warehouse"
        + (" and the Genie API, which is rate limited" if backend != "dbx_metric_views" else "") + ".",
        "AGGREGATE AND CACHE (BX:CG) are AtScale engine measures and are blank, as on the 09-10 tab.",
    ]
    if backend == "dbx_genie_space":
        notes.append("BASE-TABLE FALLBACK: Genie could read the base tables but every graded submission of this run "
                     "read metric views only (checked in the grading audit).")
    if routing_note:
        notes.append(routing_note)
    for i, text in enumerate(notes):
        ws[f"A{NOTES + i}"] = text
    # The source tab is formatted down to row 1000; drop the empty rows so the file stays small.
    last = NOTES + len(notes)
    if ws.max_row > last:
        ws.delete_rows(last + 1, ws.max_row - last)
    for r in list(ws.row_dimensions):
        if r > last:
            del ws.row_dimensions[r]
    if backend in SNOWFLAKE:
        snowflake_labels(ws, scen, label, describe, paths, metas, n_runs, p1, p2, rw, secs)
    return ws


SF_WORDS = [("Genie Ontology", "Cortex Sense"), ("GENIE ONTOLOGY", "CORTEX SENSE"), ("Genie One", "Cortex"),
            ("GENIE ONE", "CORTEX"), ("ask_genie", "ask_cortex"), ("Genie", "Cortex"), ("GENIE", "CORTEX"),
            ("Databricks SQL warehouse", "Snowflake warehouse"), ("Databricks", "Snowflake"), ("DATABRICKS", "SNOWFLAKE"),
            ('" / dbx "', '" / sf "'), ("metric views", "semantic views"), ("METRIC VIEWS", "SEMANTIC VIEWS"),
            ("metric view", "semantic view"), ("schema or catalog", "schema or database")]


def snowflake_labels(ws, scen, label, describe, paths, metas, n_runs, p1, p2, rw, secs):
    """Relabel a tab built for a Snowflake scenario: the baseline arm is Snowflake Cortex Sense."""
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str):
                v = c.value
                for a, b in SF_WORDS:
                    v = v.replace(a, b)
                c.value = v
    n = scen[2:]
    ws["A1"] = f"BIRD-Interact head-to-head, all 22 databases: AtScale vs Snowflake scenario {n} ({label})"
    ws["A2"] = (
        f"SNOWFLAKE ARM n={n_runs}, scenario {n}: {label}. {fmt_ts(metas[0]['run_started'])} -> "
        f"{fmt_ts(metas[-1]['run_finished'])}: all 22 databases, 410 query tasks x {n_runs} sequential runs, "
        f"concurrency {metas[0].get('concurrency')}. {describe} Same agent and user simulator (Sonnet 5), a-interact mode, "
        "the 2026-09-10 AtScale instruction with only the tool lines rewritten, and the same six grading corrections "
        "applied live. Snowflake account UGBNILI-NG29656, warehouse BIRD_SENSE_WH, database BIRD_BENCH (the 22 BIRD "
        "databases with their column comments and keys; AtScaleInc/bird-snowflake-models). Submitted SQL is graded by "
        "re-executing it read-only on the warehouse. "
        f"Files: {', '.join(Path(p).name for p in paths)}. Task-mean P1 {p1:.1%} / P2 {p2:.1%} / reward {rw:.4f}, "
        f"wall-clock {secs:.0f}s per question. ATSCALE ARM IS THE 2026-09-10 RUN, UNCHANGED from the 'Modified Harness "
        "09-10  Sonnet' tab (n=3, files full0910_atscale_run01-03), except the census-based columns described in the "
        f"notes. The Snowflake arm fills the columns that tab gives to the raw arm, r1 to r{n_runs} in run order.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tab", nargs=3, action="append", metavar=("NAME", "SCENARIO", "RESULTS_GLOB"), required=True,
                    help="tab name, scenario 1/2/3, sf1/sf2/sf3 (Snowflake) (or retired-1/retired-2), and a quoted glob of the scenario's 1 to 3 run files")
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
    # A lift/ratio cell guards only against blanks (=IF(OR(X="",Y=""),"n/a",Y/X)); when one side is
    # itself "n/a" (an arm with no correct answer on a database, so no cost per correct answer) the
    # division gives #VALUE!. Guard on ISNUMBER instead: identical for numbers, "n/a" otherwise.
    guard = re.compile(r'=IF\(OR\((\$?[A-Z]+\$?\d+)="",(\$?[A-Z]+\$?\d+)=""\),"n/a",')
    for name in built:
        for row in wb[name].iter_rows():
            for c in row:
                if isinstance(c.value, str) and guard.match(c.value):
                    c.value = guard.sub(lambda m: f'=IF(OR(NOT(ISNUMBER({m[1]})),NOT(ISNUMBER({m[2]}))),"n/a",', c.value, 1)
    wb.active = 0
    wb.save(a.out)
    print("wrote", a.out, "tabs:", wb.sheetnames)


if __name__ == "__main__":
    main()
