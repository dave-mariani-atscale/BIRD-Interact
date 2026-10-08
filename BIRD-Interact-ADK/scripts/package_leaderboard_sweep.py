#!/usr/bin/env python3
"""Package a finished no-gold-930 leaderboard sweep the way the Sonnet / Kimi re-runs were packaged by hand (2026-10-04):

  1. board-graded copies of the three merged runs (submission validator verdicts; errored entries completed from the dataset
     and classed from error_classes.tsv)                      -> results/<BASE>_rep{1,2,3}_board.json
  2. the corrected-regime regrade the workbook tab needs      -> <sweep_dir>/regrade_corrected.json   (reads the template DBs:
     NEVER while a sweep runs - refused if a runner or validator is active)
  3. results table + behaviour metrics                        -> <sweep_dir>/table.json, behaviour.json
  4. RESULTS.md, the colleagues/ bundle, the results zip and the submission zip -> Drive (Results-Submission, Submission/)
  5. a new "Leaderboard <tab-label>" workbook tab built with the same chain as the earlier tabs (build_leaderboard_tab +
     census + corrected-regime + cost columns, seeded section headers so the columns align), row 29, the A2 sweep-specific
     paragraph and the BEHAVIOUR PROFILE rows A32-A40 styled from an existing Leaderboard tab; inserted after the last
     Leaderboard tab; every other tab verified cell-for-cell unchanged; the Drive file overwritten in place after a hash check.

Every sentence written to the tab or RESULTS.md is computed from the run files - no model-specific prose. Pass --dry-run to
write the workbook and zips to a scratch directory instead of Drive (used to prove the script reproduces the Kimi tab).

    package_leaderboard_sweep.py --sweep-dir logs/lb_gpt5_nogold930 --base leaderboard_gpt5_20261005_nogold930 \
        --model "GPT-5" --tag gpt5 --zip-model GPT5 --raw-board results/leaderboard_gpt5_20260918_raw_raw_board_20261005.json \
        --raw-note "the 2026-09-18 GPT-5 raw run, re-graded 2026-10-03 under the current upstream DISTINCT rule (0 verdicts change)" \
        --tab-label "10-05 GPT5 NG930" --prev-note "..." [--track-note "..."] [--date 20261005] [--dry-run DIR]
"""
import argparse, ast, collections, copy, hashlib, json, math, os, re, shutil, statistics as st, subprocess, sys, zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
PY = sys.executable
DRIVE = Path("/Users/davidmariani/Library/CloudStorage/GoogleDrive-dave@atscale.com/Shared drives/Product/Benchmark/BIRD Benchmark/Results-Submission")
WORKBOOK = DRIVE / "BIRD Results (atscale n=3, memory=shapes, mcp=bird-develop-rebase, engine=dm-bird-develop-interim).xlsx"
CENSUS = Path.home() / "workspace/atscale/bird-atscale-models-no-gold-930/census/census_lb7_final.json"
MODELS = Path.home() / "workspace/atscale/bird-atscale-models-no-gold-930"
TEST = {"run_query", "execute_sql"}; SUB = "submit_sql"; ASK = "ask_user"
RND = re.compile(r"\bROUND\s*\(", re.I)
META = {json.loads(l)["instance_id"]: json.loads(l) for l in open("bird-interact-full/bird_interact_data.jsonl")}


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ----------------------------------------------------------------------------------------------------------- 1. board
def board_copies(sweep, base):
    cls = {}
    ec = sweep / "error_classes.tsv"
    if ec.exists():
        for l in open(ec):
            p = l.rstrip("\n").split("\t", 3)
            if len(p) == 4: cls[p[0]] = f"{p[2]}: {p[3]}"
    outs = []
    for r in (1, 2, 3):
        src, sub, out = f"results/{base}_rep{r}_merged.json", f"submissions/{base}_rep{r}_merged.jsonl", f"results/{base}_rep{r}_board.json"
        res = sh([PY, "logs/lb_grok43_nogold930/apply_validated.py", src, sub, out])
        if res.returncode: raise SystemExit(f"apply_validated failed for rep {r}: {res.stderr[-400:]}")
        log("  " + res.stdout.strip()[:200])
        d = json.load(open(out)); filled = []
        for x in d["results"]:
            if "category" not in x:
                m = META[x["task_id"]]
                x.update(category=m.get("category") or "Query", database=m["selected_database"], instance_id=x["task_id"],
                         total_reward=0.0, phase1_passed=False, phase2_passed=False, has_follow_up=bool(m.get("follow_up")),
                         error_class=cls.get(x["task_id"], "unclassified"))
                filled.append(x["task_id"])
        json.dump(d, open(out, "w")); outs.append(out)
        if filled: log(f"  rep{r}: completed {len(filled)} errored entries {filled[:6]}")
    return outs, cls


# ----------------------------------------------------------------------------------------------------- 2. corrected regrade
def corrected_regrade(sweep, base):
    out = sweep / "regrade_corrected.json"
    if out.exists() and out.stat().st_size > 1000:
        log(f"  corrected-regime regrade exists: {out}"); return out
    if sh(["pgrep", "-f", "orchestrator.runner|export_submission.py"]).stdout.strip():
        raise SystemExit("REFUSING the corrected-regime regrade: a runner or validator is active (it reads the template DBs)")
    res = sh([PY, "scripts/regrade_leaderboard_as_corrected.py", "--runs", f"results/{base}_rep*_board.json", "--out", str(out)],
             env={**os.environ, "PYTHONPATH": str(ROOT)})
    if res.returncode or not out.exists(): raise SystemExit(f"regrade failed: {res.stderr[-600:]}")
    log("  " + " | ".join(l.strip() for l in res.stdout.split("\n") if "p1_corrected" in l or "wrote" in l)[:300])
    return out


# ------------------------------------------------------------------------------------------------- 3. table + behaviour
def row_stats(label, p):
    d = json.load(open(p)); R = d["results"]
    q = [x for x in R if x["category"] == "Query"]; m = [x for x in R if x["category"] == "Management"]
    pct = lambda xs, k: 100 * sum(1 for x in xs if x.get(k)) / len(xs)
    src = d.get("merged_from") or [p]; usd = hrs = 0.0
    for s in src:
        e = json.load(open(s)); usd += e["llm_usage"]["total"]["cost_usd"]; hrs += (e["run_finished"] - e["run_started"]) / 3600
    return dict(label=label, n=len(R), nq=len(q), qp1=pct(q, "phase1_passed"), qp2=pct(q, "phase2_passed"), mp1=pct(m, "phase1_passed"),
                mp2=pct(m, "phase2_passed"), sr=pct(R, "phase1_passed"), rw=100 * sum(x["total_reward"] for x in R) / len(R),
                err=sum(1 for x in R if "error" in x), hrs=hrs, usd=usd, agent=d.get("agent_model"), sim=d.get("user_sim_model"),
                started=d["run_started"], finished=d["run_finished"])


def arm(p):
    d = json.load(open(p)); R = d["results"]; Q = [r for r in R if r["category"] == "Query"]; M = [r for r in R if r["category"] == "Management"]
    calls, subs, asks, tests, expl, used, left, maxc = [], [], [], [], [], [], [], 0
    nosub = sub_pass = sub_n = 0; nosub_tasks = []
    for t in Q:
        names = [e.get("tool") for e in (t.get("tool_trajectory") or []) if e.get("type") == "tool"]
        calls.append(len(names)); s = names.count(SUB); subs.append(s); asks.append(names.count(ASK))
        tests.append(sum(1 for n in names if n in TEST)); expl.append(sum(1 for n in names if n not in TEST | {SUB, ASK}))
        if "budget_used" in t: used.append(t["budget_used"]); left.append(t.get("budget_remaining", 0))
        if s == 0: nosub += 1; nosub_tasks.append(t["task_id"])
        else: sub_n += 1; sub_pass += bool(t.get("phase1_passed"))
        for e in t.get("adk_events") or []:
            u = e.get("usage") or {}
            maxc = max(maxc, next((u[k] for k in ("completion_tokens", "output_tokens", "candidates_token_count") if k in u), 0) or 0)
    pct = lambda xs, k: 100 * sum(1 for x in xs if x.get(k)) / len(xs)
    return dict(nq=len(Q), qp1=pct(Q, "phase1_passed"), qp2=pct(Q, "phase2_passed"), mp1=pct(M, "phase1_passed"), mp2=pct(M, "phase2_passed"),
                sr=pct(R, "phase1_passed"), rw=100 * sum(x["total_reward"] for x in R) / len(R),
                calls=st.mean(calls), subs=st.mean(subs), asks=st.mean(asks), tests=st.mean(tests), expl=st.mean(expl),
                used=st.mean(used) if used else 0, left=st.mean(left) if left else 0, nosub=nosub, nosub_tasks=nosub_tasks,
                max_completion=maxc, sub_pass_rate=100 * sub_pass / max(sub_n, 1), errors=sum(1 for r in R if "error" in r))


def behaviour(raw, reps):
    Rw = arm(raw); A = [arm(p) for p in reps]
    bi = max(range(len(A)), key=lambda i: (A[i]["sr"], A[i]["rw"])); B = A[bi]
    se = 100 * math.sqrt((Rw["qp1"] / 100) * (1 - Rw["qp1"] / 100) / Rw["nq"])
    return dict(best_run=bi + 1, best=B, raw=Rw, runs=A, lift1=100 * (B["qp1"] / Rw["qp1"] - 1), lift2=100 * (B["qp2"] / Rw["qp2"] - 1),
                abs1=B["qp1"] - Rw["qp1"], se=se, lift_lo=100 * (B["qp1"] / (Rw["qp1"] + 2 * se) - 1), lift_hi=100 * (B["qp1"] / (Rw["qp1"] - 2 * se) - 1),
                mp1_mean=st.mean(a["mp1"] for a in A), qp1_mean=st.mean(a["qp1"] for a in A), qp2_mean=st.mean(a["qp2"] for a in A))


# ------------------------------------------------------------------------------------------------------ disclosures
def error_summary(cls, reps):
    """(count, by-class counts, task list by class, per-run counts) over the three board files."""
    per_run = []; by = collections.Counter(); tasks = collections.defaultdict(list)
    for r, p in enumerate(reps, 1):
        d = json.load(open(p)); n = 0
        for x in d["results"]:
            if "error" in x:
                n += 1; c = (x.get("error_class") or cls.get(x["task_id"]) or "unclassified").split(":")[0]
                by[c] += 1; tasks[c].append(f"{x['task_id']} (r{r})")
        per_run.append(n)
    return sum(per_run), by, tasks, per_run


def disagreements(base):
    out = []
    for r in (1, 2, 3):
        s = json.load(open(f"submissions/{base}_rep{r}_merged.summary.json"))
        for dg in s["validated"].get("disagreements", []):
            out.append((r, dg["instance_id"], dg["local"], dg["validated"]))
    return out


def reset_attestation(base):
    p = Path(f"results/{base}_rep1_atscale_feedback_reset.txt")
    if not p.exists(): return "not found"
    txt = open(p).read(); z = re.search(r"reset at (\S+)", txt); s = re.search(r"at run start (\S+): (exchange=\d+ feedback=\d+ certified_query=\d+)", txt)
    return f"zeroed at {z.group(1) if z else '?'} and read {s.group(2) if s else '?'} at {s.group(1) if s else '?'} when run 1 started ({p})"


def model_crash_text(by, tasks):
    if not by: return "No task errored in any run."
    label = {"model": "model-caused crash", "infra": "unrecovered infrastructure error", "infra?": "unclassified error (treated as infrastructure)", "unclassified": "unclassified error"}
    parts = []
    for c, n in by.most_common():
        name = label.get(c, c) + ("es" if n != 1 and label.get(c, c).endswith("crash") else "s" if n != 1 else "")
        parts.append(f"{n} {name} ({', '.join(tasks[c][:8])}{', ...' if len(tasks[c]) > 8 else ''})")
    return "; ".join(parts)


# ----------------------------------------------------------------------------------------------------------- RESULTS.md
def results_md(a, T, B, errs, dis, prev_note, raw_note, track_note, harness):
    r1, r2, r3, raw = T; b = B["best"]; rw = B["raw"]; total_err, by, tasks, per_run = errs
    row = lambda r, l: f"| {l} | {r['qp1']:.2f} | {r['qp2']:.2f} | {r['mp1']:.2f} | {r['mp2']:.2f} | {r['sr']:.2f} | {r['rw']:.2f} | {r['err']} | {r['hrs']:.2f} | {r['usd']:.0f} |"
    best = T[B["best_run"] - 1]
    mg = B["mp1_mean"] - rw["mp1"]; mp = [x["mp1"] for x in B["runs"]]; q = [x["qp1"] for x in B["runs"]]
    swing = max(mp) - min(mp)
    mem = ("Management stays flat while Query climbs on both phases, which is the pattern a memory effect must show; read the Query rise as memory."
           if swing < 2.5 and (q[2] - q[0]) > 1.5 * swing else
           f"Management moved {swing:.1f} points between runs (binomial SE on 190 tasks ~3.6), so part of any run-to-run rise is noise; read the Query climb with that in mind.")
    live = ("They match the live verdicts exactly." if not dis else
            f"They differ from the live verdicts in {len(dis)} place(s): " + "; ".join(f"`{t}` (r{r}) live {l} -> board {v}" for r, t, l, v in dis) +
            ". A live pass -> board fail is counted as a fail; a live fail -> board pass counts because the board scores the exported SQL.")
    infra_n = by.get("infra", 0) + by.get("infra?", 0)
    model_n = by.get("model", 0)
    err_txt = (f"Only true infrastructure errors are re-run (an outage, provider 5xx, credit/budget refusal); a crash the model causes is scored as "
               f"a fail, as upstream's harness scores it. {'No infrastructure error went unrecovered.' if infra_n == 0 else f'{infra_n} infrastructure error(s) remain scored 0 (see error_classes.tsv).'} "
               f"{'No model-caused crash occurred.' if model_n == 0 else f'{model_n} model-caused crash(es) across the three runs ({per_run[0]} / {per_run[1]} / {per_run[2]}), all scored 0: ' + ', '.join(tasks['model'])}.")
    return f"""# BIRD-Interact-Full - {a.model}, n=3 atscale (COLD) + raw baseline, leaderboard protocol ({a.date[:4]}-{a.date[4:6]}-{a.date[6:]})

Agent `{r1['agent']}`, user simulator `{r1['sim']}` on the upstream prompts{track_note}, upstream grading (none of this
harness's corrections), Universal Cost Scheme, all 600 tasks (410 Query on the semantic layer, 190 Management on raw Postgres,
routed per task), every `run_query` with the aggregate bypass, **concurrency 10**. {('This is the first ' + a.model + ' leaderboard sweep; it runs on the clean models like every no-gold-930 re-run.') if a.first_sweep else ('This sweep is the no-gold-930 re-run of the ' + a.model + ' leaderboard scenario: every leaderboard scenario is being re-run on the clean models.')}

**Semantic models: the clean `no-gold-930` catalog** (`bird-atscale-models` branch `no-gold-930-logic` @ `e89bb6dc`,
catalog `bird_models_no_gold_930`): every finding of the 2026-09-23 cheat list removed.{'' if a.first_sweep else ' The earlier sweep ran on `main`.'}
Engine `ghcr.io/atscaleinc/engine:pr10556`, MCP `ghcr.io/atscaleinc/mcp:bird-develop-rebase`. Harness `{harness}`, which
includes the "do not round in the submitted query" instruction (`f12ac55`), as the Sonnet, Kimi and GPT-5 re-runs.

## Query tasks only - the semantic layer answers these and nothing else

Figures are the BIRD evaluator's: every run's submission was exported and re-graded on fresh template databases under the
upstream rules, which is what the board computes. {live}

| Run | Query P1 | Query P2 | Mgmt P1 | Mgmt P2 | Success Rate | Reward | Errors | Hours | USD |
|---|---|---|---|---|---|---|---|---|---|
{row(r1, "01 (cold)")}
{row(r2, "02 (warm)")}
{row(r3, "03 (warm)")}
{row(raw, "raw n=1 (" + a.raw_short + ")")}

Best run r{B['best_run']} (by Success Rate, ties by Reward): **Query P1 {best['qp1']:.2f}, Query P2 {best['qp2']:.2f}** (Success Rate {best['sr']:.2f}, Reward {best['rw']:.2f}).
3-run mean: Query P1 {B['qp1_mean']:.2f}, Query P2 {B['qp2_mean']:.2f}.

Lift over the raw arm (best run): Query P1 {best['qp1']:.2f} vs {raw['qp1']:.2f} = **{B['lift1']:+.0f}%**; Query P2 {B['lift2']:+.0f}%.
The raw arm is n=1; its sampling error alone puts the Query P1 lift between {B['lift_lo']:+.0f}% and {B['lift_hi']:+.0f}% (95%).

{prev_note}

## Memory lift

Query P1 r1 -> r2 -> r3: {q[0]:.2f} -> {q[1]:.2f} -> {q[2]:.2f} ({q[2]-q[0]:+.2f}); Query P2 {r1['qp2']:.2f} -> {r2['qp2']:.2f} -> {r3['qp2']:.2f}.
Management - raw Postgres on both arms, never the semantic layer - {mp[0]:.2f} / {mp[1]:.2f} / {mp[2]:.2f}. {mem}

## Errors and infrastructure

{err_txt}

## Raw arm

{raw_note}. {'The raw arm was run in this sweep, after the three AtScale runs, under the same protocol.' if a.raw_fresh else 'The raw arm is reused, not re-run.'}

## Behaviour (best run r{B['best_run']} vs raw, per Query task)

AtScale: {b['calls']:.1f} tool calls, {b['tests']:.2f} test executions, {b['asks']:.2f} asks, {b['subs']:.2f} submits; {b['used']:.2f} bird-coins used; {b['nosub']} Query task(s) ended without a submit.
Raw: {rw['calls']:.1f} tool calls, {rw['tests']:.2f} test executions, {rw['asks']:.2f} asks, {rw['subs']:.2f} submits; {rw['used']:.2f} bird-coins used; {rw['nosub']} without a submit.
Management control: AtScale 3-run mean {B['mp1_mean']:.2f}% vs raw {rw['mp1']:.2f}% = AtScale {mg:+.2f} points ({'within run-to-run noise' if abs(mg) < 3.6 else 'outside one binomial SE of 190 tasks'}).

## Store state at run 1

Attested cold: the three-table feedback store was {reset_attestation(a.base)}.

## Files

- `{a.tag}_run{{1_cold,2_warm,3_warm}}.json` - the three runs (board-graded; `live_phase*_passed` keeps the live verdicts), `{a.tag}_raw_n1.json` the re-graded raw run
- `{a.base}_rep{{1,2,3}}_merged.jsonl` + `.summary.json` - the submission files and their validation reports
- `error_classes.tsv` - every errored task, the agent's underlying exception and its model/infra class
"""


# ------------------------------------------------------------------------------------------------------ 4. bundle + zips
def bundle_and_zip(a, sweep, md, dest):
    B = sweep / "bundle"; C = B / "colleagues"
    shutil.rmtree(B, ignore_errors=True); C.mkdir(parents=True)
    (C / "RESULTS.md").write_text(md)
    for src, dst in ((sweep / "error_classes.tsv", "error_classes.tsv"), (sweep / "run.sh", "launcher_run.sh")):
        if src.exists(): shutil.copy(src, C / dst)
    names = {1: "1_cold", 2: "2_warm", 3: "3_warm"}
    for r in (1, 2, 3):
        shutil.copy(f"results/{a.base}_rep{r}_board.json", C / f"{a.tag}_run{names[r]}.json")
        shutil.copy(f"submissions/{a.base}_rep{r}_merged.jsonl", C); shutil.copy(f"submissions/{a.base}_rep{r}_merged.summary.json", C)
    shutil.copy(a.raw_board, C / f"{a.tag}_raw_n1.json")
    for f in C.glob(f"{a.tag}_*.json"):
        d = json.load(open(f))
        if a.agent not in (d.get("agent_model") or ""): raise SystemExit(f"{f.name} agent_model {d.get('agent_model')!r} is not {a.agent!r} - refusing to bundle")
    date = f"{a.date[:4]}-{a.date[4:6]}-{a.date[6:]}"
    R = B / f"BIRD Results - {date} - atscale COLD + raw (leaderboard) - n=3+1 - concurrency = 10 - no-gold-930 - {a.zip_model}.zip"
    Z = B / f"BIRD_leaderboard_submission_AtScale_{a.zip_model}_results_{a.date}.zip"
    with zipfile.ZipFile(R, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(C.iterdir()): z.write(f, f"colleagues/{f.name}")
    with zipfile.ZipFile(Z, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(C.iterdir()):
            if f.name == "RESULTS.md" or f.name == "error_classes.tsv" or f.name.startswith(a.base) or f.name.startswith(a.tag + "_"): z.write(f, f"colleagues/{f.name}")
    for src, folder in ((R, dest), (Z, dest / "Submission")):
        folder.mkdir(parents=True, exist_ok=True); shutil.copy(src, folder / src.name)
        if sha(src) != sha(folder / src.name): raise SystemExit(f"copy mismatch for {src.name}")
        log(f"  {src.name} -> {folder}")
    return R, Z


# ---------------------------------------------------------------------------------------------------------- 5. workbook
def workbook_tab(a, T, B, errs, dis, prev_note, track_note, regrade, scratch, dest_xlsx):
    import openpyxl
    from openpyxl.utils import get_column_letter as L
    src = scratch / "src.xlsx"; shutil.copy(WORKBOOK, src); src_sha = sha(src)
    wb = openpyxl.load_workbook(src)
    tab = f"Leaderboard {a.tab_label}"
    if len(tab) > 31: raise SystemExit(f"tab name {tab!r} is {len(tab)} chars (max 31)")
    if tab in wb.sheetnames: raise SystemExit(f"tab {tab!r} already exists")
    held = {}
    for n in wb.sheetnames:
        if n.startswith("Leaderboard "): held[f"HOLD{len(held)}"] = n; wb[n].title = f"HOLD{len(held)-1}"
    if not held: raise SystemExit("no existing Leaderboard tab to use as the style donor")
    donor_hold = list(held)[-1]  # the most recent Leaderboard tab (e.g. Kimi's) styles row 29 and A32-A40
    w0 = scratch / "w0.xlsx"; wb.save(w0)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    def step(cmd, out):
        res = sh(cmd, env=env)
        if res.returncode or not out.exists(): raise SystemExit(f"{cmd[1]} failed: {res.stderr[-600:]}{res.stdout[-300:]}")
    w1 = scratch / "w1.xlsx"
    step([PY, "scripts/build_leaderboard_tab.py", "--src", str(w0), "--out", str(w1), "--runs", f"results/{a.base}_rep*_board.json",
          "--raw-runs", a.raw_board, "--label", a.tab_label], w1)
    wb = openpyxl.load_workbook(w1); g = wb[tab]
    for col, txt in (("BA", "CENSUS"), ("BO", "CORRECTED-REGIME"), ("BY", "COST")): g[f"{col}4"].value = txt
    for col in ("AY", "AZ", "BM", "BN", "BW", "BX"): g.column_dimensions[col].width = 2
    v1 = scratch / "v1.xlsx"; wb.save(v1)
    v2, v3, v4 = scratch / "v2.xlsx", scratch / "v3.xlsx", scratch / "v4.xlsx"
    step([PY, "scripts/add_leaderboard_census_columns.py", "--census", str(CENSUS), "--src", str(v1), "--out", str(v2)], v2)
    step([PY, "scripts/add_corrected_regime_columns.py", "--regrade", str(regrade), "--src", str(v2), "--out", str(v3)], v3)
    step([PY, "scripts/add_cost_columns.py", "--src", str(v3), "--out", str(v4)], v4)
    wb = openpyxl.load_workbook(v4); n = wb[tab]; d = wb[donor_hold]
    diffs = [(L(c), d.cell(5, c).value, n.cell(5, c).value) for c in range(1, 85)
             if d.cell(5, c).value != n.cell(5, c).value or (d.cell(4, c).value or "")[:12] != (n.cell(4, c).value or "")[:12]]
    if diffs: raise SystemExit(f"column layout differs from the donor tab: {diffs[:6]}")
    def cp(s, t):
        t.font = copy.copy(s.font); t.fill = copy.copy(s.fill); t.number_format = s.number_format; t.alignment = copy.copy(s.alignment); t.border = copy.copy(s.border)
    b = B["best"]; r = B["raw"]; A = B["runs"]; br = B["best_run"]
    lit = {"F": round(b["qp1"] * 410 / 100) / 410, "J": round(b["qp2"] * 410 / 100) / 410, "O": round(b["mp1"] * 190 / 100) / 190, "S": round(b["mp2"] * 190 / 100) / 190}
    for col in ["A", "F", "J", "O", "S", "AP", "AQ", "AR", "AS", "AT", "AV", "AW", "AX", "BD", "BE", "BF", "BG", "X", "AB", "AF", "AK", "AL"]:
        s, t = d[f"{col}29"], n[f"{col}29"]; cp(s, t)
        if col in lit: t.value = lit[col]
        elif col in ("X", "AB", "AF", "AK"): pass
        else: t.value = s.value
    n.row_dimensions[29].height = d.row_dimensions[29].height
    total_err, by, tasks, per_run = errs
    live = ("" if not dis else " (" + str(len(dis)) + " verdict(s) differ from live: " + "; ".join(f"{t} r{rr} live {l} -> board {v}" for rr, t, l, v in dis) + ")")
    n["A2"].value += (f" SWEEP-SPECIFIC ({a.date[:4]}-{a.date[4:6]}-{a.date[6:]}): semantic models are the CLEAN no-gold-930 catalog (bird-atscale-models no-gold-930-logic @ e89bb6dc, "
                      f"catalog bird_models_no_gold_930), with every 2026-09-23 cheat-list finding removed{'' if a.first_sweep else ' - the earlier ' + a.model + ' leaderboard tab ran on main'}.{track_note} "
                      f"Engine ghcr.io/atscaleinc/engine:pr10556, MCP bird-develop-rebase. Concurrency 10{'' if a.first_sweep else ' (the earlier sweep ran at 5; concurrency changes no task' + chr(39) + 's behaviour)'}. "
                      f"Every figure is the BIRD evaluator's: each run's submission was re-graded on fresh template databases under the upstream rules and those verdicts are the ones on this tab{live}. "
                      f"Raw arm: {a.raw_note}. Agent instruction at harness {a.harness}, WITH the 'do not round in the submitted query' rule (f12ac55), as the Sonnet and Kimi re-runs. "
                      f"Only true infrastructure errors are re-run; errors remaining in the figures, all scored 0: {model_crash_text(by, tasks)}.")
    mp = [x["mp1"] for x in A]; q = [x["qp1"] for x in A]; q2 = [x["qp2"] for x in A]; swing = max(mp) - min(mp)
    nosub_txt = (f"{b['nosub']} of 410 Query tasks ({100*b['nosub']/410:.1f}%) ended without a submit on the AtScale arm in r{br}, {r['nosub']} on raw; every such task scores 0."
                 + ((lambda errd: f" Of those, {len(errd)} errored (model-caused, scored 0): {', '.join(errd)}." if errd else "")
                    ([t for t in b['nosub_tasks'] if any(x.startswith(t + " (r" + str(br) + ")") for x in tasks.get('model', []))]))
                 + (f" No call came near the 16,384-token completion ceiling (largest {b['max_completion']:,} tokens on AtScale, {r['max_completion']:,} raw)." if max(b["max_completion"], r["max_completion"]) < 16000
                    else f" The largest completion counts are {b['max_completion']:,} tokens on AtScale and {r['max_completion']:,} raw; a count above 16,384 means this model's usage includes its thinking tokens, so these figures cannot show whether the 16,384-token output cap (applied identically to both arms) was reached." if max(b["max_completion"], r["max_completion"]) > 16384
                    else f" Calls reached the 16,384-token completion ceiling (largest {b['max_completion']:,} tokens on AtScale, {r['max_completion']:,} raw) - a harness limit applied identically to both arms."))
    mg = B["mp1_mean"] - r["mp1"]
    rows = [
        (f"BEHAVIOUR PROFILE - best AtScale run (r{br}) vs raw arm (n=1, {a.raw_short}), Query tasks only. Computed {a.date[:4]}-{a.date[4:6]}-{a.date[6:]} from the run files named in A2; tool counts from each task's tool_trajectory, truncation from the per-call usage ledger.", None),
        ("What is distinctive", f"Tests-per-submit ratio {b['tests']/max(b['subs'],0.01):.2f} on AtScale ({b['tests']:.2f} test executions per {b['subs']:.2f} submits) vs {r['tests']/max(r['subs'],0.01):.2f} raw; {b['asks']:.2f} asks per task. The layer changes its tool calls by {100*(b['calls']/r['calls']-1):+.0f}% and its spend by {b['used']-r['used']:+.2f} coins per task while moving Query P1 from {r['qp1']:.2f}% to {b['qp1']:.2f}%. Management control {'within noise' if abs(mg) < 3.6 else 'outside one SE'} ({mg:+.2f} points). {model_crash_text(by, tasks).rstrip('.')}."),
        ("Lift", f"Query P1 {b['qp1']:.2f}% on AtScale (best run r{br}) vs {r['qp1']:.2f}% raw = {B['lift1']:+.0f}% ({B['abs1']:+.1f} points); Query P2 {b['qp2']:.2f}% vs {r['qp2']:.2f}% = {B['lift2']:+.0f}%. The raw arm is n=1, so its binomial sampling error (~{B['se']:.1f} pts) feeds straight into the ratio: the 95% interval on this lift from raw-arm noise alone is {B['lift_lo']:+.0f}% to {B['lift_hi']:+.0f}%. {prev_note}"),
        ("Tool profile (per Query task)", f"AtScale: {b['calls']:.1f} tool calls, {b['expl']:.1f} exploration, {b['tests']:.2f} test executions (run_query), {b['asks']:.2f} ask_user, {b['subs']:.2f} submit_sql; pass rate on tasks that reached a submit {b['sub_pass_rate']:.1f}%. Raw: {r['calls']:.1f} calls, {r['expl']:.1f} exploration, {r['tests']:.2f} tests (execute_sql), {r['asks']:.2f} asks, {r['subs']:.2f} submits; pass rate when it submits {r['sub_pass_rate']:.1f}%. Tests-per-submit ratio {b['tests']/max(b['subs'],0.01):.2f} on AtScale vs {r['tests']/max(r['subs'],0.01):.2f} raw."),
        ("Budget", f"Bird-coins used {b['used']:.2f} of ~17.86 on AtScale ({b['left']:.2f} left unspent) vs {r['used']:.2f} raw ({r['left']:.2f} left). The semantic layer changed this model's spend by {b['used']-r['used']:+.2f} coins per task."),
        ("Unsubmitted tasks / truncation", nosub_txt),
        ("Management control", f"Management routes to raw PostgreSQL on both arms and never touches the semantic layer. AtScale 3-run mean {B['mp1_mean']:.2f}% vs raw {r['mp1']:.2f}% (n=1) = AtScale {mg:+.2f} points; {'within run-to-run noise (binomial SE on 190 tasks ~3.6 points)' if abs(mg) < 3.6 else 'outside one binomial SE of 190 tasks (~3.6 points)'}."),
        ("Memory across the 3 AtScale runs", f"Query P1 r1 -> r2 -> r3: {q[0]:.2f} -> {q[1]:.2f} -> {q[2]:.2f} ({q[2]-q[0]:+.2f}); Query P2 {q2[0]:.2f} -> {q2[1]:.2f} -> {q2[2]:.2f} ({q2[2]-q2[0]:+.2f}); Management P1 {mp[0]:.2f} -> {mp[1]:.2f} -> {mp[2]:.2f} (swing {swing:.2f}). "
         + ("Management stays flat while Query climbs, which is the pattern a memory effect must show; read the Query rise as memory." if swing < 2.5 and (q[2]-q[0]) > 1.5*swing else "Management moved as well, so part of any run-to-run rise is noise; the Query climb is read with that caveat.")),
        ("Store state at run 1", f"Attested cold: the three-table feedback store was {reset_attestation(a.base)}."),
    ]
    for i, (h, body) in enumerate(rows):
        R = 32 + i
        for col in ("A", "B"): cp(d[f"{col}{R}"], n[f"{col}{R}"])
        n[f"A{R}"].value = h
        if body is not None: n[f"B{R}"].value = body
        n.row_dimensions[R].height = d.row_dimensions[R].height
    have = {str(m) for m in n.merged_cells.ranges}
    for m in d.merged_cells.ranges:
        if 29 <= m.min_row <= 40 and str(m) not in have: n.merge_cells(str(m))
    for h, orig in held.items(): wb[h].title = orig
    order = [s for s in wb.sheetnames if s != tab]
    last_lb = max(i for i, s in enumerate(order) if s.startswith("Leaderboard "))
    order.insert(last_lb + 1, tab); wb._sheets = [wb[s] for s in order]; wb.active = last_lb + 1
    final = scratch / "final.xlsx"; wb.save(final)
    # every other tab byte-for-byte (populated cells + merges) unchanged
    a_ = openpyxl.load_workbook(src); b_ = openpyxl.load_workbook(final)
    val = lambda x: (x.text, x.ref) if hasattr(x, "text") else (round(x, 12) if isinstance(x, float) else x)
    for nm in a_.sheetnames:
        A = {(c.row, c.column): val(c.value) for row in a_[nm].iter_rows() for c in row if c.value is not None}
        Bc = {(c.row, c.column): val(c.value) for row in b_[nm].iter_rows() for c in row if c.value is not None}
        bad = [k for k in set(A) | set(Bc) if A.get(k) != Bc.get(k)]
        if bad or sorted(map(str, a_[nm].merged_cells.ranges)) != sorted(map(str, b_[nm].merged_cells.ranges)):
            raise SystemExit(f"tab {nm!r} would change ({len(bad)} cells) - refusing to write")
    log(f"  tab {tab!r} built; other tabs unchanged; sheet order {b_.sheetnames}")
    if dest_xlsx == WORKBOOK and sha(WORKBOOK) != src_sha:
        raise SystemExit("the Drive workbook changed while the tab was being built - not written; rerun")
    dest_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with open(final, "rb") as fi, open(dest_xlsx, "wb") as fo: fo.write(fi.read())   # overwrite in place keeps the Drive id
    if sha(dest_xlsx) != sha(final): raise SystemExit("workbook write verification failed")
    log(f"  workbook written: {dest_xlsx}")
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep-dir", required=True); ap.add_argument("--base", required=True); ap.add_argument("--model", required=True)
    ap.add_argument("--tag", required=True); ap.add_argument("--zip-model", required=True); ap.add_argument("--raw-board", required=True)
    ap.add_argument("--raw-note", required=True); ap.add_argument("--raw-short", required=True); ap.add_argument("--tab-label", required=True)
    ap.add_argument("--prev-note", default=""); ap.add_argument("--first-sweep", action="store_true", help="no earlier leaderboard sweep of this model exists"); ap.add_argument("--raw-fresh", action="store_true", help="the raw arm was run in this sweep, not reused"); ap.add_argument("--track-note", default=""); ap.add_argument("--agent", required=True)
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d")); ap.add_argument("--harness", default=None)
    ap.add_argument("--dry-run", default=None, help="write the workbook and zips under this directory instead of Drive")
    a = ap.parse_args()
    a.harness = a.harness or sh(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    sweep = Path(a.sweep_dir); scratch = Path(a.dry_run) if a.dry_run else sweep / "pkg_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    for r in (1, 2, 3):
        for p in (f"results/{a.base}_rep{r}_merged.json", f"submissions/{a.base}_rep{r}_merged.jsonl", f"submissions/{a.base}_rep{r}_merged.summary.json"):
            if not Path(p).exists(): raise SystemExit(f"missing {p}")
    log("1. board-graded copies"); reps, cls = board_copies(sweep, a.base)
    log("2. corrected-regime regrade"); regrade = corrected_regrade(sweep, a.base)
    log("3. table + behaviour")
    T = [row_stats(l, p) for l, p in (("01 (cold)", reps[0]), ("02 (warm)", reps[1]), ("03 (warm)", reps[2]), ("raw", a.raw_board))]
    json.dump(T, open(sweep / "table.json", "w"), indent=1)
    B = behaviour(a.raw_board, reps); json.dump(B, open(sweep / "behaviour.json", "w"), indent=1)
    errs = error_summary(cls, reps); dis = disagreements(a.base)
    log(f"  best r{B['best_run']}: Query P1 {B['best']['qp1']:.2f} P2 {B['best']['qp2']:.2f} | lift {B['lift1']:+.0f}% | errors {errs[0]} {dict(errs[1])} | live/board disagreements {len(dis)}")
    md = results_md(a, T, B, errs, dis, a.prev_note, a.raw_note, a.track_note, a.harness)
    (sweep / "RESULTS.md").write_text(md)
    dest = Path(a.dry_run) / "drive" if a.dry_run else DRIVE
    log("4. bundle + zips"); bundle_and_zip(a, sweep, md, dest)
    log("5. workbook tab"); workbook_tab(a, T, B, errs, dis, a.prev_note, a.track_note, regrade, scratch, (Path(a.dry_run) / "drive" / WORKBOOK.name) if a.dry_run else WORKBOOK)
    log("DONE")


if __name__ == "__main__":
    main()
