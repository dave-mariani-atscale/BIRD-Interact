# Prompt: testing and fixing a BIRD database on the semantic layer

Paste this at the start of a session working on a new BIRD-Interact database.
Distilled from the ETF work of 2026-08-13/14; the examples are ETF, the method is not.

---

We are measuring **semantic-layer lift**: how much better the `atscale` arm scores than the
`raw` arm on the same tasks. Your job is to take each failing task to a stop condition — fixed,
capped, or out of budget — in one pass over the model, and report numbers that survive a
repeat. The unit of work is a task, not an arm (§ The pass).

## How to behave

- **Hands-off.** Batch the work and keep going. Background long jobs, do free analysis while
  they run. Stop only for decisions that are genuinely mine: spending beyond what I approved,
  shipping a change whose evidence you doubt, or a real tradeoff with no better option.
- **A diagnosis is not a deliverable.** Finishing the classification, writing the worklist and
  proving a fix sufficient at $0 are the *first steps of iteration 1*, not a place to hand
  back. If the worklist has a task in it, the caps have room and no stop condition has fired,
  do the next thing rather than describing it. "Next: ..." at the end of a message, followed
  by nothing, is the failure this line exists to prevent — it has cost whole sessions.
- **Concise.** Real numbers, no preamble, no recap of what you just did. What you found,
  what it means, what it cost.
- **Report at a boundary, not between iterations.** The boundaries are: the pass is finished,
  a cap or stop condition fired, a run is in flight and there is genuinely nothing free left
  to do, or you need a decision that is mine. At those points, and only those, end with the
  next step and its price.
- Correct your own earlier conclusions in one line and move on. A wrong finding left
  standing costs the next session more than it cost you.

## Who does what — two model tiers, one session

The session that runs this document is **Opus**. It owns the worklist, the caps, the
tracker and every decision in the stop table. Everything mechanical is delegated downward; nothing is delegated upward:

- **Down to Sonnet or a script, everything mechanical.** Reading a finished run is
  `python scripts/loop_step.py <results.json> [task ...] --expect ask:<text> --expect
  filter:<text>` — one screen per task (verdicts, coins, asks, every submitted WHERE with its
  verdict, the gold_diff FINDING, and whether the named mechanism fired). Never read
  `failing_sql.py` output, `gold_diff.py` output and the trajectory by hand when that
  screen answers the question; it is ~1k tokens against ~20k. Sonnet subagents
  (`Agent` with `model: sonnet`) run builds, gates, deploys, tracker and change-log writes,
  and report the exit status and the one line that matters. They never decide anything.
- **Every subagent brief names the forbidden files by path, not the forbidden concept.**
  "You may not read gold SQL" is not an instruction a fresh context can follow — it does not
  know which file that is. Name `bird_interact_data.jsonl` and the denied keys (`sol_sql`,
  `follow_up.sol_sql`, `sql_snippet`, `test_cases`, `conditions`, `preprocess_sql`,
  `clean_up_sqls`) in **every** delegation that touches diagnosis, and say that the brief at
  `<model>/brief/task_brief.json` is the only task data it may open. Measured 2026-09-19: the
  build brief carried the prohibition by path and was honoured; the *diagnosis* brief said only
  "you may NOT read gold SQL" and pointed at `gold_diff.py`, and the subagent opened the raw
  JSONL, where `follow_up` carries phase-2 gold SQL. It disclosed this unprompted and marked
  which of its conclusions were tainted — which is the behaviour to want — but the whole
  diagnosis then had to be discarded under the rule below. The extractor was not at fault: the
  brief was verified clean, no denied key and no SQL-shaped value.
- **A contaminated diagnosis is discarded, not laundered.** When a session or subagent has seen
  gold for a task, nothing from that context may become a model object, however well-reasoned —
  `docs/create_bird_model_prompt.v12.md` puts it as "never folded back into the build", and the
  reason is that the *hypothesis space* is contaminated even where each measured step is sound.
  Re-derive from a clean context if the change is genuinely rule-mandated, or cap the task. What
  you may keep is anything you re-verify yourself from the warehouse alone: a join cardinality,
  a row count, a key's uniqueness.
- **Nothing is delegated upward. Fable is reserved** (2026-09-19). The week's Fable quota is
  nearly spent and resets Thursday, so `model: fable` is not called by a session running this
  document; if a database genuinely stalls, ask Dianne one closed question naming what is stuck
  and what Opus and Sonnet have already tried, and let her decide. The two moments that used to
  go up now resolve as follows. **The first draft of a model's `spec.py`** becomes a two-step
  Opus job: a Sonnet subagent runs a measurement-only pass over the warehouse, the KB and the
  column meanings and writes `generator/facts.md` (column types and where Postgres truncates,
  degenerate columns, `character(n)` columns, unit-suffixed text columns, JSON profile keys at
  every nesting level, join cardinalities and orphan counts, every KB formula the warehouse
  already stores with `corr(stored, recomputed)`, candidate column bindings per KB term with live
  counts) and authors nothing; Opus then writes the spec from those facts, because description
  quality is what the build is for and it is the one thing that cannot be delegated downward.
  **A task still failing after the cheap classification** — `loop_step.py` read, gold finding
  classified, first lever tried — is Opus's to solve, with `gold_diff.py --sql` proving each
  candidate lever sufficient at $0 before any spend. Measured 2026-09-19 on solar_panel: the
  Fable spec draft cost 563k subagent tokens and 45 minutes to reach a green build over six
  gate iterations, so the measurement half is the expensive half and it is the half Sonnet can
  do.

Measurement is **n=1 per task with feedback memory off**, plus the mechanism check in
step 1.4. n=1 is enough to see a mechanism fire or not; it is not enough to quote a rate,
so the report says "fired 1/1" and the sheet number waits for the close run. Buy a second
run only where the stop table says so (a canary drop, a flaky first result).

## Spend rules — read before running anything

Measured: **~$0.25 per task-run** on atscale, ~$0.20 on raw, Sonnet with caching on. A
19-task arm is ~$4.50; a 2-arm comparison with useful repeats is ~$25. Input tokens are 97%
of spend because the whole conversation is re-sent every turn, so cost scales with turns,
not with answers.

1. **Do all $0 work first, in one batch.** Most questions never need a run.
2. **Runs are per task, never per arm.** `--tasks <id>,<canaries> --repeat 2`, bought only
   after the fix is proven sufficient at $0 and only inside that task's cap (§ The pass).
   The one whole-arm run in a pass is the baseline, and only when none exists.
3. **Predict what each change will move before you spend.** Write the prediction down. If
   the honest prediction is "nothing measurable", say so and don't run.
4. Never start a run I didn't ask for. Never run two evaluations at once — usage is
   attributed by timestamp window.
5. **Feedback memory off for every loop run.** With it on, the MCP server appends certified
   exemplars, query patterns, a column track record and clarification counts built from your
   own earlier runs to `list_models`, so the agent's inputs change every run even when the
   model does not. On 2026-09-18 robot_fault_prediction_1 went 4/4 then 0/3 on identical
   model content; a whole iteration was reverted before the cause was found. Both sides must
   be off — `FEEDBACK_MEMORY=false` in the ADK `.env` (restart services) and
   `ATSCALE_MCP_FEEDBACK_MEMORY=false` in the MCP server's `.env` (recreate the container).
   Check: a scoped `list_models` ends at the Column Index, with no "Certified query
   exemplars" or "Column track record" section. Memory is its own experiment (A-61..A-65),
   never a passenger on a model-tuning run.

### What is free (no LLM calls, no benchmark tokens)

| tool | answers |
|---|---|
| `scripts/outbound_sql.py "SELECT ..."` | what the engine actually dispatched |
| `scripts/outbound_sql.py --query-id <uuid>` | resolve an earlier `run_query` |
| `scripts/clause_fidelity.py` | battery: inbound vs dispatched, dropped clauses |
| `scripts/regrade_sweep.py` | re-score recorded submissions under the current grader (`regrade_flags.py` no longer exists) |
| `scripts/gold_diff.py` | model vs gold: row count, columns, values, order, rounding — without showing you gold |
| MCP `run_query` + Postgres on `<db>_template` | anything gold_diff does not answer |
| `scripts/failing_sql.py <results.json>` | every query the agent wrote, its verdict, and the asks it made |
| `--mode oracle`, `orchestrator.test_harness` | plumbing checks with zero LLM calls |

Set `GRADING_AUDIT_PATH` on every run so it stays re-gradable offline later.

### Predict the payoff before you spend

Priors measured on ETF, and they were right every time:

- **A model fix: predict zero.** 3 for 3, a defect was found, fixed, verified against gold —
  and the task didn't move, because the agent's next choice up the stack became the binding
  constraint. A model fix reliably removes a *known-wrong* answer; it does not reliably
  produce a right one.
- **A guidance change that prescribes a construction: predict zero.** Tested twice on the
  same prescription — 5 repeats of the target task, then 15 task-runs after making it
  imperative — both null, with the target construction appearing 0/5 times either way.
  Prohibitions land (violation rates ≤1.8% across 961 submissions); "do Y instead" does not.
  What does land is a change that turns a silent wrong answer into a loud error.
- **A fix to something structurally broken (bad data, a dead reference, an unwinnable
  task): predict the full points.** Restoring one damaged table moved two tasks by +1.0
  each, exactly as predicted.

So: before spending, prove the fix is *sufficient* for free. Take the agent's own stored
submission, run it against the fixed model through `run_query`, and diff it against gold —
row count, values, order. That answers "can the model now produce the right answer" with
certainty, for nothing. Then decide if the run is worth it. This caught a
correct-but-insufficient fix before any spend and isolated the one remaining condition.

## The three layers you can fix in

1. **Guidance** (`config/environment_backends.yaml`) — cheapest, no deploy, but **restart
   services** (config is cached at import). Shared across domains, so it must stay
   domain-neutral. Weakest lever; see the prior above.
2. **The semantic model** (the model repo) — commit, push, `scripts/deploy_models.sh`, and
   record it in `docs/model-change-log.md` in the same change.
3. **The engine / MCP server** — you cannot fix it. File it, mitigate elsewhere.

Diagnose which layer *before* changing anything. Most "model problems" are one of the other
two, and today's most common real cause was neither: it was the user simulator.

## Method

### 1. Read the dispatched SQL before theorising

The SQL an agent writes is **not** what runs. The engine rewrites it, and several rewrites
are silent — a clause dropped or inverted, a plausible result, no error. Known so far
(re-probe on your build): `OFFSET` ignored entirely; NULL ordering inverted vs Postgres and
un-overridable; a `UNION` touching the model returning zero rows without dispatching; a
grain-forcing derived table that drops the entity key and re-groups on the value tuple.

**A negative result is valuable** — "the engine dispatched exactly what the agent wrote"
eliminates a whole layer. **Clause fidelity is necessary, not sufficient:** every clause can
survive and still resolve at the wrong grain, which shows up only as two different numbers.

### 2. Diff against gold at value level — with `gold_diff.py`, not by hand

    PYTHONPATH=. .venv-adk/bin/python scripts/gold_diff.py \
        --results results/<run>.json <instance_id> [<instance_id> ...]

It pulls the graded submission (the **last** trajectory entry carrying an `sql` key, not
the first), re-executes it **live** against the model as it stands now, executes gold
against `<db>_template`, and returns the finding: row count, column count and order,
values, row order, rounding — plus the real grader's verdict, from the grading code
itself rather than a reimplementation. $0, no LLM calls. This is how four ETF tasks were
diagnosed in one sitting.

It reads gold so that you do not. **Gold SQL never appears in its output** — not the
text, not a fragment, not a paraphrase of the construction; the Postgres `LINE n:` echo
is stripped for the same reason. Column labels and a capped sample of differing cell
values do appear, because otherwise it is not a value diff. Those are diagnosis only.

Read the finding, not the rows: `ROW ORDER` is an `ORDER BY` defect, `VALUES ROUNDING`
is a ROUND/CAST defect, a row-count difference with the non-numeric columns matching is
a measure or filter defect and not a join one. `--phase 2` for the follow-up. `--sql
"..."` diffs a candidate query with no run to pull it from — which is how you prove a
model fix **sufficient** before spending anything (§ Predict the payoff).

If you find yourself opening gold SQL directly, the tool is missing a comparison. Add it
there rather than reading around it.

### 3. Derive the decision rule, don't read the score

A task score is a noisy aggregate over independent requirements. Work out the exact set of
conditions a submission must satisfy, then score every stored submission against that rule
until it agrees on all of them. One task's phase 1 needed three things at once; only then
was it obvious that one was failing and two were already fine — the opposite of what the
score suggested.

### 4. Re-grade before comparing anything

Every stored baseline was graded under whatever code existed then, and comparing across that
boundary invents regressions.

    PYTHONPATH=. .venv-adk/bin/python scripts/regrade_sweep.py \
        --atscale-audit <grading_audit.jsonl> --raw-audit <grading_audit.jsonl> --out <dir>

It needs the `GRADING_AUDIT_PATH` rows, which is why every run sets it.

Re-grade for grading logic, flags, tolerance, rounding, comparison fixes. Re-run only when
the change affects what the agent *does* — prompts, tools, budget, model, backend.

### 5. Suspect your parser before the data

Every wrong conclusion in the ETF work came from a parsing bug, not from the benchmark.
Actual cases, each of which produced a confident false claim first:

- **Keying on a trailing integer**: `exchange_traded_funds_M_10` collided with
  `exchange_traded_funds_10`, silently merging Management tasks into Query tasks and
  reversing a per-task comparison. Match the **full** `instance_id`.
- **Regex over a whole trajectory blob**: searching for `RANK()` matched the *column
  description* in a tool result, not the agent's SQL — reading 3/5 where the truth was 0/5.
  Search **tool call args only**, never the result text.
- Matching `HAVING` missed a threshold in `WHERE`; matching a quoted column missed the
  aliased form; `[^\s]+` truncated a quoted multi-word name; a regex flagged the *good*
  shape as the bad one.

**When a pattern-match disagrees with the data, suspect the pattern.** Parse structure with
`sqlglot` rather than matching text, and hand-verify ~10 classifications before trusting any
rate.

### 6. Ask-triggers compete for a fixed budget

Writing "confirm which the question means" into a description works — the agent asks. But
the budget is roughly **three questions per task**, and a trigger that fires on something
the agent already gets right subtracts directly from the one that decides the task.

- Prefer **amending a trigger that already fires** to adding one. Redirecting is free;
  adding costs an ask.
- Before adding one, name the question it will displace.
- **Closing** a question ("settled, do not ask") trades a certain wasted ask for an
  occasional wrong guess found by a failed submit.

### 7. How a question is asked decides the answer

The user simulator is not a neutral oracle, and this was the single largest source of
unfixable ETF failures:

- **A leading question gets ratified.** Asked "what minimum number of *scoreable* entities",
  it accepted the premise; asked the same thing as a genuine two-option question, the agent
  chose correctly. The premise is never challenged.
- **One proposed answer invites agreement**, including when wrong, with confident reasoning
  attached.
- **Mutually-exclusive alternatives get a real choice** — and it will sometimes still be the
  wrong one. Observed: a clean two-option question naming both formulas got the answer that
  contradicts gold, with a rationale describing the *other* option. Model right, agent right,
  task lost.
- **A bundled question** can make it invent a requirement the task never had, which the
  agent then implements faithfully. Worse than not asking.
- Some questions come back "out of scope" — 2 coins for nothing.

When diagnosing, read the actual question *text*, not just whether an ask happened.

### 8. Phase 2 has its own failure modes

Check separately from phase 1: entering with too little budget to look up a column name and
guessing identifiers (measures usually guessed right, identity columns not); and answering a
follow-up from a **stale earlier exploratory query** rather than the submission that passed
— these differ exactly when the discriminating filter was added last, which is the normal
case.

## Running a targeted run

Write a script per run, with a header stating what changed, which task it should move, and
which tasks are canaries — so a null result is readable and a regression is caught before you
read any improvement. Then:

- `bash scripts/gate_run.sh` first, every time: services newer than the newest harness
  commit, catalog healthy (a working `run_query` is *not* evidence — metadata calls can be
  dead while queries work), template databases unmodified.
- Keep `SYSTEM_AGENT_MODEL` fixed for anything scored. Haiku is fine for plumbing only.
- `--tasks <id>,<canaries> --repeat 2` is the loop's instrument; ~$0.25 per task-run at the
  run mean, **~$0.48 for a never-pass task** (measured 2026-09-08 — they burn attempts).
  Budget from the higher figure.
- The raw arm is the control. It does not move with model edits (measured 2026-09-08:
  0.3029 before and after a 22-db model pass), so it is never re-run inside the loop.
  `--query-only` when you do run it, or the arms cover different task sets. **Compute lift
  on the intersection, never on arm totals.**
- **Whole-arm repeats belong on the raw baseline, once.** Measured: across repeats the
  semantic arm moved on 1 task of 19, raw on 7 of 19; 13 raw tasks were perfectly stable
  and six carried the whole spread. Budget n≥3 raw when establishing a baseline. Inside the
  loop, the target's n=2 *is* the semantic repeat. A single run per arm read anywhere from
  +7 to +32 pp of lift on identical code.
- Report the mean of the repeats with its range, in percentage points, relative alongside.
  Never quote a single pair. One outlier run paired with one good run produced a headline
  double the settled value — and it was the number everything else got compared against.

### Operational gotchas, each of which has wasted a cycle

- `setsid` does not exist on macOS, and a run launched from inside a backgrounded shell dies
  with its parent. Plain `nohup … &` from a foreground shell survives.
- The runner **always** timestamps `--output` (`<stem>_YYYYmmdd_HHMMSS.json`). Glob for the
  file; testing the bare path "fails" after the expensive arm has already been paid for.
- A `pgrep -f "orchestrator.runner"` waiter matches **its own** command line and waits
  forever. Grep the log for a completion marker, or break the literal.
- `shared/environment_backends.py` caches config at import: restart services after editing
  guidance or grading code, or the run silently uses the old rules.
- `scripts/sheet.py` has no append primitive — read the cell, concatenate, write back, then
  verify with `get` (a `set` can time out silently).
- A canary that fails after a model change is not proof the change did it. Before
  reverting, run the canary once more on the changed model, then once on the reverted
  model; if it fails on both, look at what else moved — on 2026-09-18 it was memory blocks.
- `git revert -q` is not a flag; a failed command at the head of an `&&` chain lets the `;`
  tail run anyway. Never put the run launch on the same line as the deploy.

## Non-negotiable

- **Gold SQL is read by `scripts/gold_diff.py`, not by you.** It returns a description of
  the difference and never the answer key's SQL, which is what keeps "diagnose, never
  build" true by construction instead of by discipline. Open gold directly only when a
  diff the tool cannot express is the only way forward, say so in the tracker when you
  do, and do not carry that session's work into a model change.
- **Nothing shipped to the model, guidance, or code may come from an answer key.**
  Masked thresholds never ship; gate it mechanically.
- Record findings in the tracker as you go, including corrections to your own entries.
- **File engine defects.** Guidance mitigation is a workaround; a defect with a
  mechanism-grade repro and no ticket never gets fixed, and the same dialect gaps will hit
  every other database.
- Never write to a `*_template` database. Gold executes against it, so a stray DML there
  corrupts the grading reference for every future run — this cost two tasks in every arm for
  a day before it was found.
- **A model built in this session goes into an existing multi-database model repo as a new
  folder — one root `catalog.yml`, one shared `utilities/`, a folder per database.** One repo
  per database is the mistake to avoid: it buys a second catalog, a second deployed schema, a
  second vendored copy of the build machinery to keep in sync by hand, and a second deploy, for
  models that are one comparison arm. Before building, work out which repo the arm already uses
  — a brief that names a *build process* or an *arm* ("a from-scratch v12 model") is not naming
  a repo. If you genuinely cannot tell, ask one closed question naming the candidates before you
  build, never after. Measured 2026-09-19: robot_fault_prediction and archeology_scan were built
  into `diannewood/bird-robot-fault-prediction` and `diannewood/bird-archeology-scan` and had to
  be merged into `diannewood/bird-models-v12` afterwards, which is strictly harder than starting
  there because the models were already measured and could not be allowed to change.
- **The grader does not change during a pass, or between passes, without Dianne saying so
  explicitly.** A grader gap found while tuning (2026-09-18: `column_order_free` and
  `ties_as_ties` never tried together, robot_fault_prediction_8 phase 2) is a cap row with the
  offline evidence attached, not a lever. A pass that moves the model and the grader at once
  cannot say which moved the score.

## The pass: one task at a time, to convergence

A whole-arm re-run after a batch of fixes tells you what moved but not why, costs a full arm
to learn it, and the next pass diagnoses the same tasks again from fresh trajectories.
Instead, take each fixable task to a stop condition before touching the next, with the price
of each task and of the database capped before you start.

### 0. Once per database — baseline and worklist ($0 when a baseline exists)

1. Baseline: any existing run for this db, re-graded with `scripts/regrade_sweep.py` so it
   sits under the current grader. Only if none exists, run both arms once (raw at n≥3) —
   the only whole-arm run in the pass.
2. `scripts/failing_sql.py <results.json>`, then `scripts/gold_diff.py --results
   <results.json> <every failing id>` in one invocation; read the dispatched SQL for
   anything plausible-but-wrong.
3. Sort every failure into one class: **engine-blocked, gold-bound** (non-unique, tie,
   column order), **simulator-bound, model-fixable, agent-variance.** Only model-fixable
   enters the loop. Everything else gets a tracker row and $0. Verify a shared-cause claim
   on the SQL before grouping tasks under one fix — three "same cause" tasks on 09-07 were
   three causes.

   **Falsify every cap before you write it — two $0 checks, both mandatory.** A cap row tells
   the next session not to spend on that task, so a wrong one is more expensive than a missed
   finding, and it is the easiest row in the tracker to write by accident. Measured 2026-09-19
   on solar_panel: five phase-1 tasks were capped and **four were not caps at all** — the tuned
   model of the same database scored 3/3 on every one of them, so no reasoning about gold could
   have been right.

   a. **Diff against another arm's per-task verdicts.** `results/bird_full_run_*/scoring/
      per_task_verdicts_by_run.json` carries every database's per-task phase-1 and phase-2
      results under the tuned models. Any task another model passes is reachable, full stop.
      Read the **verdicts only**: opening the other model's objects contaminates a from-scratch
      build, and that trade is Dianne's to make, not yours to drift into.
   b. **Name the rule that makes it unreachable and re-read that rule.** Both 09-19 mis-cappings
      were a rule applied to the wrong shape — the dimensional-inconsistency rule stretched over
      a percent-versus-fraction twin, and "the caller supplies the constant" read as "publish
      nothing". Re-reading the rule was enough to see it in both cases.

   Also re-check **inherited** caps, in the same pass and for the opposite reason: tie-order and
   casing caps filed before the grading corrections no longer bind. `B-77`'s `_10`, `_13` and
   `_16` all ceiling-pass under the current grader and two of them passed a live baseline with no
   model work, and archeology_scan's `_6` did the same the day before. A cap has a date on it, and
   the grader has moved since most of them were written.

   The honest cap list is the deliverable here, in both directions: a real cap with a mechanism is
   worth as much as a fix, and a fictitious one costs every session that reads it.
4. Write the worklist before spending — one line per model-fixable task: id, `gold_diff`
   finding, the model object you will change, the predicted outcome, the canaries (passing
   tasks that read the same object). Order by predicted payoff, sufficiency-proven first.
5. State the caps at the top of the session. Defaults: **3 paid iterations or $3 per task,
   $25 per database.** Change them out loud before the pass, never mid-task.
6. Fix the instrument before the first paid run and do not touch it during the pass:
   `SYSTEM_AGENT_MODEL` Sonnet, `PATIENCE=3` (the upstream budget; a bigger purse is a
   diagnostic you run once and never score), feedback memory off on both sides (spend rule
   5), grading regime unchanged. Write these four in the run script header with the
   prediction. A regression on a canary is only a regression if all four held.

### 1. Per task — the loop

**The model is frozen for the duration of a run.** The agent queries a deployed catalog, tasks
run concurrently, and a redeploy mid-run changes `model_version` under them. So "fix it during
the run" is not a thing that exists: per-task iteration means per-task *targeted runs* against
successive deploys. The cycle below is the smallest unit that can attribute a change.

**Run the cycle to its stop condition without checking in.** Diagnose, fix, prove at $0,
deploy, gate, buy the targeted run, read it, decide against the stop table, and go straight
into the next task's fix. Each iteration's evidence goes into the report file as you make it,
so the write-up is accumulating while you work and nothing is re-derived at the end.

**Batch fixes that touch disjoint model objects into one deploy and one run.** One task at a
time is about *attribution*, not about deploy count: two fixes to objects no shared task
reads are still attributable, because the targeted run names each task and the canaries catch
the crossover. Deploy and gate are the wall-clock cost of the loop — paying them once for
three independent fixes is strictly cheaper and no less readable. Fixes that touch the same
object, or a task that reads both, go in separate iterations.

One iteration is:

1. **Fix** in the model. Steer the model object — description, gap-naming sentence, twin
   measure — not the shared instruction: appended instruction bullets measured 0/3 and 1/3
   firing (B-87). Asserting the answer in a description does nothing; naming the choice as
   *unsettled* fires the ask.
2. **Prove sufficiency at $0**: `gold_diff.py --task <id> --sql "<the query the agent should
   now write>"` shows no finding for phase 1, then `--phase 2`. If no query against the
   fixed model is sufficient, the fix is not ready — stay here, still $0. Then deploy, record
   in `docs/model-change-log.md`, `bash scripts/gate_run.sh`.
3. **Buy one targeted run**: `--tasks <id>,<canaries> --repeat 2`. About $1 for the target
   plus ~$0.30 per canary-run.
4. **Read the new trajectory, not the score**: `scripts/loop_step.py <results.json> <id>
   --expect <mechanism>` first; `failing_sql.py` and `gold_diff.py` only for what it does
   not show. The question is whether the finding is the
   same class as last iteration or a new one — a new one means the fix landed and the next
   constraint up the stack is now binding; the same one means the lever does not reach.
   **A pass counts only if the trajectory shows the fix's mechanism firing** — the ask you
   wrote was asked (with the alternatives you named), the filter you described was written,
   the twin you added was projected. A pass with zero asks, or one that copies a prior
   answer (`adk_events` text like "matches the certified exemplar"), is not evidence for the
   fix. On 2026-09-18 two "converged" fixes were memory copies and failed 0/2 when run clean.

### 2. Stop conditions — the first to fire ends the task

| stop | signal | record |
|---|---|---|
| **converged** | 2/2 at P1, canaries unchanged | model commit, iterations, spend |
| **flaky** | 1/2 | log it and move on; do not buy a third — flaky is a separate pool, not a model defect |
| **stalled** | same `gold_diff` finding class two iterations running | cap row: the lever does not reach |
| **reclassified** | the new failure is engine-, gold-, or simulator-bound | cap row with the mechanism |
| **capped** | 3 paid iterations or $3 on this task | cap row, "budget", with the last finding |
| **regression** | a canary drops | revert the object first; never carry a regression forward |

Passing tasks do regress under later fixes (insider_trading_15 did), which is what the
canaries are for. A task that stops for any reason other than *converged* is not revisited
in this pass.

**"Agent-variance" is not a stop.** It may be written only after two checks on the failing
trajectories: (1) the agent never read the column whose description carries the deciding
sentence, or (2) it read it and that sentence was not the first thing said about the column.
If neither holds, the failure is the same for the same reason and there is a lever: move the
deciding sentence to the front of the description (robot_fault_prediction_5, 2026-09-18: one
reorder, the ask fired), and if the sentence is read and still ignored, ship the choice or the
population as a value the agent can filter or project (robot_fault_prediction_3: three
sentences failed, one twin verdict landed first try). Four identical failing trajectories on
robot_fault_prediction_1 were filed as variance the same day, with the lever untried.

### 3. Once per database — close ($1–3)

One run of every task whose model object you touched — targets and canaries — at n=1 on the
final deployed model, so the pass ends on one artifact under one grader against one model.
Stop when the worklist has no task left in the loop or the database cap is reached,
whichever is first.

Then report from the worklist: each task's stop condition and price, predicted versus what
happened, spend against the caps, and the lift on the intersection against the re-graded
raw baseline, in percentage points with relative alongside.
