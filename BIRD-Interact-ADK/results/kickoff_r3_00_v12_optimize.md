# ROUND 3 — one task at a time, iterate while optimistic, across the v12 estate

Decided by Dianne 2026-09-29. Invoke as `Do results/kickoff_r3_00_v12_optimize.md` on an **Opus**
session (`/model opus` first). Unattended. Budget **$100 hard, $65 target, stop at $90 spent**.

Read first, fully: `CLAUDE.md`, `docs/bird-database-testing-prompt.md` (the "Who does what", spend
rules, and the stop table at "### 2. Stop conditions"), and `results/kickoff_r2_00_v12_round2.md`
(the checklist, the lever tags, and every ruling under "RULINGS MADE DURING THIS PASS" — all still
in force). Then follow them. Everything below is the instance of that process for this round.

## WHAT THIS IS

An optimization pass over models that already exist and are deployed. **It is an UPDATE, not a
rebuild** — do not regenerate a model, restate a spec, or re-derive datasets. The unit of work is
ONE TASK with a recorded lever. Iterate on that task while the evidence says the next iteration is
likely to convert; stop when the stop table fires. Then the next task. Then close the database with
a measured P1/P2/reward against its previous reward. By the end the models should feel close to
optimized, and the report should say where the remaining headroom is and why it was not bought.

Two facts frame the round:
1. The sheet holds 61 `R2-` rows (all still `open`) plus five polar levers in
   `results/handoff_polar_equipment_0921.md`. Each has a mechanism, a prediction and a $0 sweep
   result. That is the worklist. Do not invent levers the sweep has not seen.
2. The 2026-09-27 retrofit (`f564e11`) moved summed bare-name P1 193→226 across 19 models and only
   five rows have been re-measured since. **Every ledger row dated before 2026-09-28 describes a
   model that no longer exists.** A close run on a stale row measures the retrofit as well as this
   round's levers; the report says so and does not attribute the whole delta to the lever.

## INSTRUMENT, fixed for the whole round and written into every run-script header

`SYSTEM_AGENT_MODEL` and `USER_SIM_MODEL` both `anthropic/claude-sonnet-5`; `PATIENCE=3`;
`FEEDBACK_MEMORY=false` **exported explicitly in the run script** (the shell exports true); feedback
memory off on the MCP side too; `LEADERBOARD_MODE` unset; corrected grading; **the grader is not
changed for any reason**; n=1; concurrency 3; backend `atscale_v12`; models repo branch **`nocheat`**
(main + the description strip — every commit this round goes on `nocheat`). `GRADING_AUDIT_PATH`
set on every run. `scripts/gate_run.sh 22 atscale_v12` in its own call before every launch.
**Never two runs at once. Never any `gold_diff` call — sweep or `--task` — while a paid run is live.**

Cost basis: **$0.250 per task**, measured from `llm_usage.total.cost_usd` on
`results/virtual_idol_v12_paired_20260928_194216` (3.999 / 16). Read every run's
`llm_usage.total.cost_usd` and keep a running total in the report file from the first run.

## MODEL TIERS — three tiers, one test

*Does this step design the model — decide which objects exist, what a description says, what is
withheld, what a twin or an ask is?* **Fable.** *Does it apply a decided change, run the process, or
classify a result?* **Opus, the session.** *Does it produce numbers, run a build, deploy, or move
text between files?* **Sonnet.**

- **OPUS (you):** orders the queue, assembles every packet AS PATHS, classifies FINDINGs, writes the
  prediction before each spend, decides stops, owns the report, ledger, change-log and propagation.
  You are the expensive reader: read summaries, never raw run output, never a whole `spec.py`.
- **FABLE** (`Agent` with `model: "fable"`, fresh context): **at most TWO calls per database.**
  Call 1 is BATCHED — every unsettled lever of that database, each with its FINDING and the
  `grep -n` spec sections, in one packet. Call 2 is reserved for a stall. A third needs a written
  reason in the report. Most R2 rows are DECIDED changes (a rename, a twin, an ask cut, a
  population sentence) — Sonnet applies those; Fable is called only where the change needs
  designing. Per call: reads only the packet paths, `Write`s at most once and `Edit`s thereafter,
  ≤15 tool calls, runs **no build and no `gold_diff`**, reports in ≤20 lines. On quota failure:
  stop at that boundary, record, go on to the next database — never design on Opus.
- **SONNET** (`Agent` with `model: "sonnet"`): sweeps, diagnoses, spec edits for decided changes,
  builds, deploy + gate, run scripts, `llm_usage` reads, sheet / change-log / ledger writes,
  propagation grep audits. Reports ≤20 lines. Any investigation of more than three commands is a
  Sonnet call, not an Opus turn.

Record the split at close: `python3 scripts/session_cost.py --session`.

## FENCE — every Fable or Sonnet brief carries this paragraph verbatim

**SUPERSEDED 2026-09-29 (Dianne): no model change may be motivated by `gold_diff` output.** Not a `[DIAG]` change, not a RENAME TO PLAIN settled by a sweep, not an ask or companion sentence whose options or columns were found by diffing against gold, not an object published because gold passes on it. Those are findings 2 and 3 of `results/v12_cheating_review_20260928.md`, and every round-3 change of that kind was reverted the same day. `gold_diff` MEASURES (sweeps, verdicts, ceilings); a model change must be derivable from the KB, the warehouse and the agent's trajectory alone, and its commit must say which of those motivated it. Round 3 was run before this rule and all of its model changes were withdrawn; a re-run of this kickoff must carry the rule into every brief.

Forbidden BY PATH: `bird-interact-full/bird_interact_data.jsonl`; the keys `sol_sql`,
`follow_up.sol_sql`, `sql_snippet`, `test_cases`, `conditions`, `preprocess_sql`, `clean_up_sqls`;
`results/bird_full_run_*/results/grading_audit_this_run.jsonl`. The only task data you may open is
`<db>/brief/task_brief.json`. Gold is read ONLY through `scripts/gold_diff.py`, and gold SQL never
enters the model in any form. **R2-34, R2-42 and R2-58 are gold-fitted readings Dianne has ruled
stay unshipped — do not revisit them.** The grader is not changed. Never write to `<db>_template`.
Never `source` the ADK `.env`. Edits go in `generator/spec*.py`, never the emitted YAML.

## THE QUEUE — in this order, gain per dollar

Caps: **≤ $3 targeted spend per database** (four task-plus-two-canary runs at ~$0.75), **≤ 3 paid
rounds per task**, close run ≤ $6. Stop the round at $90 total regardless of position.

| # | database | levers | kind | predicted | previous reward | close |
|---|---|---|---|---|---|---|
| 1 | cybermarket_pattern | R2-56 `_9` (ask fired and cost the task 09-28; ceiling passes both phases grouping on the raw score — scope the ask to questions naming bands); R2-57 `_6` only (`_4` already realised) | iterate | +2 tasks | 0.6550 (09-28, current) | splice if the splice test passes, else full |
| 2 | cold_chain_pharma_compliance | R2-61 residual: `_1` delivery-variance ask, `_9` LRP-delay ask never converted live — read the 09-28 trajectories for whether the ask fired and what the simulator answered before changing anything | iterate | +2 | 0.5778 (09-28, current) | splice / full |
| 3 | disaster_relief | R2-01 `_10` routing; R2-02 `_4` bare-name move (verify it is not already shipped — the retrofit moved MCI and Cost Per Beneficiary); R2-03 `_9` missing-as-zero, one-row gap | iterate | +2.1 | 0.3917 (stale) | full, 12 tasks |
| 4 | labor_certification_applications | R2-49, R2-50, R2-52, R2-53 — four P2 rows `_3 _6 _13 _8`, all tuned-P2 FFF, no cap risk | iterate | +1.2 | 0.7316 | full |
| 5 | households | R2-46 `_17` literal-label Affluent flag (ceiling P1+P2, tuned 3/3) | iterate | +0.7 | 0.112 (stale) | full |
| 6 | hulushows | R2-44 `_19` one clip reading (drop the general-clips twins) | iterate | +0.7 | 0.645 (stale) | full |
| 7 | insider_trading | no rows; bare ceiling 8→12 in the retrofit, never measured. Re-sweep `results/it_r2/` first; a lever only if the sweep produces one that meets the four-part bar | sweep → maybe | ? | 0.3286 (stale) | full |
| 8 | polar_equipment | handoff levers `_4 _11 _18` (P1), `_14 _15` (P2). The handoff predates the retrofit (bare 9→12): **re-sweep `results/pe_r2/` before any Fable call** — some may already be done | sweep → iterate | +1–2 | 0.540 (09-28 nocheat copy) | full |
| 9 | cross_border | R2-37 `_1` `(Control As Fraction)` already live — Dianne 2026-09-29: **keep and measure**. No design turn | measure | +1.0 | 0.479 (stale) | full |
| 10 | mental_health | R2-15 `_16` grain — one targeted run, simulator-decided coin flip | iterate ≤1 | +0.7 or 0 | 0.250 | none |

**If ≥ $25 remains after #10** (Dianne, 2026-09-29): measurement-only closes of stale rows, largest
bare-ceiling jump first — fake_account (16→20; R2-07/09 shipped), sports_events (13→16; R2-22
shipped), museum_artifact (9→11; R2-27), reverse_logistics (3-task run of R2-35, ~$1). No design
turns on these; they are re-measurements and the report labels them so.

**Not in this round:** crypto_exchange (±20 pp at n=1 — nothing measurable below n=3, $15+ for one
lever; record R2-17 as still open); solar_panel `Plant`→`Plant Code` (a gate-G10 decision at $0 —
record the question, do not spend); every row with a predicted 0 and a demonstrated cap (R2-05, 06,
08, 12–14, 19–21, 24, 28–33, 38–41, 43, 45, 51, 54, 55, 59, 60) — re-swept at $0 only if the
database's sweep is being run anyway, never bought.

**Splice test** (#1 and #2 only): a targeted re-run may be spliced onto the 09-28 full run ONLY when
every object the change touches is one the 09-28 PASSING submissions never projected — check at $0
from that run's `grading_audit.jsonl` under `results/nocheat_record_20260928_204444/<db>/`. A
rename or description change on a shared object fails the test and buys a full close. Spliced rows
are labelled "spliced" in the report.

## THE LOOP

**0. Once, before any database.**
- Sonnet: flip the R2 rows that are recorded `open` but are not, so the ranking is honest —
  R2-04 (converted at $0), R2-07, R2-09, R2-10, R2-11, R2-18, R2-22, R2-27, R2-35, R2-37 (shipped
  in the retrofit), R2-23 and R2-26 (reclassified to caps), R2-43 (dissolved: gold defect), R2-54,
  R2-55, R2-58, R2-59, R2-60 (falsified 09-28 as predicted), R2-61 (bought 09-28, P1 11/18).
  `python scripts/sheet.py cols` first; `set` with the existing Status vocabulary; **append** to
  Notes, never replace; a cell never starts with `+`; `add` only when `set` reports no matching
  row. Then `python3 scripts/r2_ledger.py`.
- `scripts/start_services.sh`; `scripts/gate_run.sh 22 atscale_v12`. In the models repo: on
  `nocheat`, `git fetch origin nocheat` and `git log nocheat..origin/nocheat` — read it before any
  `build.sh`, per `CLAUDE.md`.
- Open `results/optimize_r3_<date>/RESULT.md` now with the queue, the predictions, and a running
  spend line. Write it incrementally; nothing is re-derived at the end.

**1. Per database — $0 re-sweep.** Sonnet re-runs the database's existing round files (bare and
full, P1 and P2) against the deployed model — `results/<ab>_r2/` for the retrofitted 19
(`cb cx dr etf fa hh hs it ma mh ot pd pe rf rl se sp vi as`), `results/cybermarket_v12_sweep/` and
`results/cold_chain_v12_sweep/` for builds 19–20:
`PG_MAXCONN=40 PYTHONPATH=. .venv-adk/bin/python scripts/gold_diff.py --sweep <file>.json --phase 1|2 --backend atscale`.
BEFORE counts. A lever whose task now passes the bare sweep AND passed the last paid run is done —
flip its row, no spend.

**2. Per lever, one at a time, in row order. Write the prediction first** — task, predicted score,
the mechanism that would have to fire. Sonnet diagnoses: `gold_diff.py --results <last run> <task>`
for the stored submission, `--task <id> --sql "..."` for a candidate, `scripts/outbound_sql.py` the
moment a result is plausible-but-wrong. Classify the FINDING. A decided change → Sonnet edits
`generator/spec*.py`. A change that needs design → into the database's batched Fable packet.
E-22: a change to an attribute's SQL renames its degenerate dimension in the same commit. E-18:
identical SQL is cached across redeploys — a fix that emits byte-identical SQL has not deployed.

**3. Prove at $0 before deploying.** `gold_diff.py --task <id> --sql "..."` against the rebuilt
model's objects must PASS for the lever's task and not regress the sweep. Build:
`PYTHON=<ADK>/.venv-adk/bin/python bash <db>/generator/build.sh`, all six gates. Batch one
database's proven fixes into one commit per lever tag (`[PLAIN]` / `[DIAG]` / `[KB]`, one tag per
commit), with the `docs/model-change-log.md` entry in the same commit. **Commit AND push `nocheat`**
— `scripts/deploy_models_v12.sh 22` refuses a dirty tree or local ≠ `origin/nocheat`. The deploy
sleeps 120 s and gates itself; gate again in a separate call before launching. Restart services if
any ADK commit lands under `shared/ db_environment/ system_agent/ orchestrator/ config/`.

**4. Paid confirm — task plus two canaries.** Canaries are two tasks that passed the last paid run
and project the objects the change touched. Run script per `scripts/run_nocheat_record_20260928.sh`
(copy its header), with:
```
python -m orchestrator.runner --mode a-interact --backend atscale_v12 --query-only \
  --concurrency 3 --databases <db> --tasks <task>,<canary1>,<canary2> --output "$OUT/<task>_r<n>.json"
```
Launch with `nohup … &` and wait in the FOREGROUND (`until grep -q … ; do sleep 15; done` under a
590 s timeout, re-issued) — a background wait dies with the turn. After every run, before reading
any 0 as a fail, check `logs/system_agent.out` for credit exhaustion (A-72) and for the E-14
fingerprint (every task burning its full budget on `list_models`) — void such a run. **Count a
pass only if the mechanism fired** — the ask asked, the twin projected, the sentence read — from
the trajectory summary (`scripts/loop_step.py`, one screen), not from the score alone.
Then the stop table: converged / flaky / stalled / reclassified / capped / regression. A canary drop
reverts the object first. "Agent-variance" only after the two trajectory checks. A task that stops
for any reason but *converged* is not revisited this round.

**5. Close the database.** Stale ledger row → full n=1 `--query-only` run over all Query tasks.
Current row (#1, #2) → splice only if the splice test passes. Record P1 and P2 separately, reward
= 0.7·P1 + 0.3·P2, lift in pp vs raw, `llm_usage.total.cost_usd`. Append the ledger row in
`results/kickoff_00_v12_order.md` (the old row stays, marked "superseded 2026-09-29 by …").
Flip every R2 row touched: converted / falsified / capped, with the measured score in Notes.

**6. Propagate before moving on** — a finding that generalizes goes where it lives
(`docs/bird-database-testing-prompt.md` for process, `docs/create_bird_model_prompt.v12.md` for a
modelling rule, the tracker for a defect) and is audited with grep (`n/22`), never from memory.
Then step 1 on the next database.

## CAPS ARE FALSIFIED, NOT ASSERTED

Before writing a cap: (a) diff against the tuned arm's per-task verdicts in
`results/bird_full_run_*/scoring/per_task_verdicts_by_run.json` — verdicts only, never that
model's objects; a task the tuned model passes is reachable; (b) name the rule that makes it
unreachable and re-read it. Inherited tie-order and casing caps predate the grading corrections —
several no longer bind (B-77, B-79).

## YOU ARE RUNNING UNATTENDED

Nobody is watching. A question asked into the terminal is the end of the round with the money
spent. Take the CONSERVATIVE branch, record the question in the report and as an R2 row if it meets
the four-part bar, and go on. **A question recorded is a deliverable; a question waited on is a
dead round.** That includes not stopping to report progress: "run launched, next: close" ends the
round. Launch, WAIT in the foreground, read, continue. **The only sentence that ends this round is
the one written after the last ledger row and the report are in place.**

Questions already known to need Dianne and to be RECORDED, not waited on: whether `main` should
fast-forward to `nocheat` at close; solar_panel `Plant`→`Plant Code` vs gate G10; crypto_exchange
R2-17 at n≥3; disaster `_7` and the `CORR` refusal tracker row.

## DELIVERABLE — `results/optimize_r3_<date>/RESULT.md`

1. Title, date, **total benchmark spend vs $100** on line 2, from `llm_usage`, summed per run.
2. `## Arm` — branch and commit before / after, catalog, instrument, n.
3. `## Results` — one row per database that changed, in queue order:
   `| database | P1 | P2 | reward | previous reward | Δ pp | raw | lift pp | $ | basis |`
   cells like `12/20 0.600`; reward and Δ bold; basis = `full` / `spliced` / `re-measure only`.
   A stale-baseline row says in a footnote that Δ includes the retrofit.
4. `## Levers` — `| row | task | predicted | measured | mechanism fired? | stop | $ |`, every lever
   worked, including the ones that failed and the ones flipped at $0.
5. `## Where the headroom is` — per database, bare-name ceiling vs live P1 after this round, and
   why the residual was not bought (cap, budget, simulator, needs Dianne).
6. `## Needing Dianne` — numbered.
7. `## Cost` — per run, per database, session split from `session_cost.py --session`.

## CLOSE — two things that survive a context clear, then commit

(1) Every touched database has its ledger row in `results/kickoff_00_v12_order.md`. (2) Every R2
row touched is flipped in the sheet and `python3 scripts/r2_ledger.py` regenerated. Then: models
repo clean and pushed on `nocheat`; ADK commit with the report, the ledger, the change-log,
`Co-Authored-By` line per the session's attribution rule; memory files for anything not derivable
from the repo (a lever class that converted or did not, an estimator refit).

Stop only for: spend beyond the caps, a change whose evidence you doubt, or a decision the stop
table does not cover — and in every one of those cases, record it and continue with the next
database rather than ending the round.
