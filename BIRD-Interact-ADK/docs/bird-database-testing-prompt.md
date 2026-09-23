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

## Who does what — three model tiers, one test

Revised 2026-09-22. Two arms have run: 2026-09-18..20 the session was Opus and authored the
specs, and Dianne judged those models measurably worse than the Fable-authored ones; 2026-09-21
the session was Fable end to end, and the weekly Fable quota ran out at request 72 of the
fourth database. Measured from the Claude Code transcripts at list price, a session run on
Fable costs $55–66 per database (robot_fault_prediction: 273 requests, 400k output tokens, 72M
cache-read tokens, $55) against a Fable allowance worth about $125 a week — two databases a
week. Most of that was not design: it was Fable paying ~3k thinking tokens per turn to run
`grep`, read gate output, iterate sweep rounds and rewrite files it had already written.

So the tier of a step is decided by one question: **does this step DESIGN the model — decide
which objects exist, what a description says, what is withheld, what a twin or an ask is?**
Yes — Fable, called in. **Does it apply a decided change, run the process, or classify a
result?** Opus, the session. **Does it produce a number, run a build, deploy, or move text
between files?** Sonnet.

- **Fable (`Agent` with `model: fable`, fresh context) — at most three calls per database.**
  - **F1, the spec.** One call authors `generator/spec.py` and `sql_defs.py` in full — every
    description, name, twin, ask, coverage flag, withholding decision and pinned constant —
    from a packet Opus assembles as paths, not content: `generator/facts.md`, the KB, the
    column meanings, the schema, `<model>/brief/task_brief.json`, the withheld KB ids as
    integers (Opus prints them; `extract_brief.py` drops them), the
    `docs/create_bird_model_prompt.v12.md` sections from `## Modeling rules` through
    `## Engine constraints`, and one existing v12 `spec.py` as the format reference.
  - **F2, the design review.** After the ceiling sweep, one call carrying every finding that
    needs a NEW object, twin, dataset grain, withholding change or ask wording — a numbered
    list with each task's FINDING line and the live counts — which Fable answers with `Edit`s
    to the spec. Findings Opus can apply without a design decision never reach this list.
  - **F3, iteration levers.** At most one call, after the baseline diagnosis, for the levers
    that need the same kind of decision, batched across tasks. Skipped when the batch is empty.
  - In every call: read only the packet paths and the spec sections being edited (`grep -n`,
    `sed -n` — never a whole `spec.py`); `Write` a file at most once, `Edit` it thereafter;
    at most 15 tool calls; no build, no `gold_diff`, no deploy; report in 20 lines or fewer.
    A gate that needs a shorter name, ASCII, a dropped digit or an allowlisted KB name is not a
    Fable call. If a Fable call fails on quota, stop at that boundary, write the handoff and
    report; the spec is never authored on Opus.
- **Opus — the session itself, hands-off — runs the pass and applies decided changes.** It
  assembles the F1 packet; fixes wording gates mechanically (shorten, ASCII, drop the digit,
  allowlist — never change what a description means; anything more goes on the F2 list); runs
  the ceiling sweep — writes each task's SQL, iterates rounds two to five, reads each FINDING
  and classifies it (caller projection / threshold / population / wrong twin / missing object)
  — and applies the edits that need no design: a wrong count in prose, a missing twin-name
  clause under the existing rule, a coverage flag that already exists. It owns the per-task
  diagnosis after `loop_step.py` (lever, counterfactual test, cap decision), the worklist,
  caps, report, findings and their propagation. It reads only summaries: `facts.md`, the KB,
  `loop_step.py` screens (~1k tokens against ~20k for the raw files), one-line gate results;
  never a raw run file, never a whole emitted YAML. Opus context is billed too — batch shell
  commands, never re-read after editing, and see `docs/fable-token-efficiency-plan.md` for
  the context-cap measures.
- **Sonnet (`Agent` with `model: sonnet`) does everything whose output is a number or a
  mechanical step.** The measurement pass that writes `generator/facts.md` — column types and
  where Postgres truncates, degenerate columns, `character(n)` columns, unit-suffixed text,
  JSON keys at every nesting level, join cardinalities and orphan counts, `corr(stored,
  recomputed)` for every KB formula the warehouse already stores, candidate column bindings
  per KB term with live counts — numbers only, authoring nothing. The build loop: `build.sh`
  until green, fixing only mechanical gates itself (pipe characters, a missing column, ASCII,
  schema qualification, MDX brackets, join roles, orphans) and returning any gate that needs
  a description or a name changed as one line for Opus. Deploy, `scripts/gate_run.sh`, run
  scripts and launches, `llm_usage` summaries, sheet and change-log and kickoff writes, the
  propagation grep audits. Reports are 20 lines or fewer and it never decides anything.
- **Every subagent brief names the forbidden files by path, not the forbidden concept.**
  "You may not read gold SQL" is not an instruction a fresh context can follow — it does not
  know which file that is. Name `bird_interact_data.jsonl` and the denied keys (`sol_sql`,
  `follow_up.sol_sql`, `sql_snippet`, `test_cases`, `conditions`, `preprocess_sql`,
  `clean_up_sqls`) in **every** Fable or Sonnet delegation that touches the model or a
  diagnosis, and say that the brief at `<model>/brief/task_brief.json` is the only task data
  it may open. Measured 2026-09-19: the build brief carried the prohibition by path and was
  honoured; the *diagnosis* brief said only "you may NOT read gold SQL" and pointed at
  `gold_diff.py`, and the subagent opened the raw JSONL, where `follow_up` carries phase-2
  gold SQL. It disclosed this unprompted and marked which of its conclusions were tainted —
  which is the behaviour to want — but the whole diagnosis then had to be discarded under the
  rule below (A-69).
- **A contaminated diagnosis is discarded, not laundered.** When a session or subagent has seen
  gold for a task, nothing from that context may become a model object, however well-reasoned —
  `docs/create_bird_model_prompt.v12.md` puts it as "never folded back into the build", and the
  reason is that the *hypothesis space* is contaminated even where each measured step is sound.
  Re-derive from a clean context if the change is genuinely rule-mandated, or cap the task. What
  you may keep is anything you re-verify yourself from the warehouse alone: a join cardinality,
  a row count, a key's uniqueness.
- **This tiering is a measured test.** At the end of every pass run
  `python3 scripts/session_cost.py --session` — it reads this session's transcript and its
  subagents' and prints tokens and list-price dollars per model, which is the figure the
  kickoffs used to ask for from `/cost` (a CLI command no session can invoke; the field was
  blank in every report). Put that table in the report beside `v12 reward / tuned reward`.
  Budget: Fable at most ~150k output and ~15M cache-read tokens per database (≈$20 at list),
  against $55–66 when the whole session ran on Fable. Exceeding it is a finding to report, not
  a target to meet by skipping F2. History: 2026-09-19 the Fable spec draft of solar_panel cost
  563k subagent tokens over six gate iterations because it ran the build loop itself — that is
  why F1 runs no build and Sonnet's loop follows it.

**Correction, measured 2026-09-23 on exchange_traded_funds.** The tiering was adopted because an
all-Fable session cost $55–66 per database. The first full pass under it cost **$59.88** — Opus
$44.97 over 222 requests and 73.2M cache-read tokens, Fable $11.54 over three calls, Sonnet $3.37 —
inside that same range. The money moved to Opus, which now runs the sweep, the diagnosis and the
process; it did not go away. What the tiering demonstrably buys is Fable **quota**, 28 requests
against a weekly allowance the all-Fable sessions exhausted at the fourth database. That justifies
the split on its own, but it is not a cost saving and a kickoff implying one is wrong. To make
sessions cheaper, attack Opus's own context, not which model authors the spec.

Measurement is **n=1 per task with feedback memory off**, plus the mechanism check in
step 1.4. n=1 is enough to see a mechanism fire or not; it is not enough to quote a rate,
so the report says "fired 1/1" and the sheet number waits for the close run. Buy a second
run only where the stop table says so (a canary drop, a flaky first result).

## Spend rules — read before running anything

Measured: **~$0.25 per task-run** on atscale, ~$0.20 on raw, Sonnet with caching on. A
19-task arm is ~$4.50; a 2-arm comparison with useful repeats is ~$25. Input tokens are 97%
of spend because the whole conversation is re-sent every turn, so cost scales with turns,
not with answers.

0. **Cost scales with RUNS, not with tasks, and the ceiling sweep is what makes runs small.**
   Measured 2026-09-21 on polar_equipment: a **20**-task database closed for **$12.67** in four
   runs (one 20-task baseline, then 9, 7 and 4 targeted tasks), against $16 and $11.29 for two
   **10**-task databases done without a full sweep. Ten sweep rounds, every sufficiency proof
   and every warehouse probe cost $0 and found four model gaps and one cap before a cent was
   spent. Budget by runs when you plan a pass, and never quote a per-task figure as a total.
   Measured 2026-09-22 on exchange_traded_funds: a **19**-task database closed for **$13.82**
   across six runs — a 19-task baseline, a 7-task repair of the tasks the interference above
   destroyed, two targeted runs of 6 and 5 tasks, a 19-task close run and a 2-task repeat —
   against a $25 cap, and the sweep is what kept the targeted runs to 5 and 6 tasks.
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

Two things about `--sweep` that cost a cycle each on 2026-09-22, both still true:

- **It leaks one Postgres connection per task**, so a sweep of more than `pg_maxconn` tasks (the
  default is **5**) dies partway with `PoolError: connection pool exhausted` — a 19-task sweep
  cannot run out of the box. `PG_MAXCONN=40 PYTHONPATH=. .venv-adk/bin/python scripts/gold_diff.py
  --sweep …` works around it.
- **The model must be schema-qualified in the query** — `FROM "<schema>"."<Model Name>"`. A bare
  model name is refused with an R10 error, and every task in the sweep file fails identically,
  which reads like a broken model rather than a broken query.
**"Free" means free of LLM cost, not free of interference — and the run interferes with itself.**
Every tool below that reaches gold opens `<db>_template`, and `gold_diff --sweep` leaks one
connection per task. The harness clones that same template with `createdb` per task, and `createdb`
fails outright if *any* session is connected. Measured on exchange_traded_funds: **7 of 19 tasks**
lost when a sweep ran beside a baseline, and **1 of 7** lost with no sweep running, at
`--concurrency 3`, the log naming the two sibling tasks that held it. Two rules follow. Do the free
work before the run, never beside it. And read a task returning with **no `instance_id`** as a
harness loss to re-run, not as a zero — it is invisible in the results JSON and the cause appears
only in `logs/db_environment.out`. All 15 recorded occurrences are on exchange_traded_funds, whose
gold queries hold the template longest (tracker E-03); on a database with that profile, run at
`--concurrency 1`.

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

## Ask fired and answer correct are two different outcomes — count them apart

Revised 2026-09-21. The build prompt's twin-plus-ask rule works and it has a ceiling that shows
up as wasted iterations if you do not measure the two halves separately. On polar_equipment the
ask was moved into the first sentence of five competing readings and then **fired on 4 of 4**
remaining tasks over three runs, while converting **2 of 7** phases. Both conversions were
tasks where the question itself settled the choice. On the other four the user simulator chose
the reading the reference does not use, named two join paths in one sentence, asked for a
combination no twin carried, or answered "this question is out of scope" — and on one of them
the agent had spelled out in its own question that the option offered returns zero rows.

So, in the worklist and in the report:

- Record `ask fired` and `answer correct` as separate columns. A task where the ask fires and
  the answer is wrong is a **simulator cap**, not a model gap, and it is a different row from a
  reference cap: a reference cap means *do not spend*, a simulator cap means *the model is
  already right and the next run may pass it*. Say which you mean.
- Once the ask has fired and the answer decided it wrongly, stop writing description text. The
  move that still works is structural — put the plain name on the reading the questions mean.
  On polar_equipment that converted a task whose counts and averages already matched gold and
  which lost on a label column alone.
- A simulator that answers differently run to run makes these tasks flip. Three runs of
  polar_equipment `_16` gave 0, 1.0, 0 with the model improving throughout. Do not read a
  single flip as a regression, and check the $0 ceiling before you believe one.

## Net the firewall out before comparing against a tuned model

Added 2026-09-23. The tuned models in `AtScaleInc/bird-atscale-models` do **not** observe the
answer-key firewall, so a v12 arm compared against one is not compared on modelling craft alone. On
exchange_traded_funds the tuned model publishes **five of the seven withheld cutoffs** as
precomputed flags, and one description states the resulting screen's population. The gross per-task
gap was 4.6 reward points and **2.3 of them sat on tasks decided by a published withheld cutoff**;
the rest was craft, and the craft half is the half worth working on. So quote the craft gap beside
the headline and say which tasks turn on a withheld cutoff — otherwise the arm looks worse than it
is and the next pass chases tasks no honest model reaches.

## When two estimates of a pass disagree, re-run the tasks the difference rests on

Added 2026-09-21. A pass that iterates produces several runs against several model versions, so
"latest per task" and "best observed per task" can differ, and neither has a repeat behind it.
Do **not** average the two: they are two estimators computed over overlapping runs of different
model versions, not two samples, and their mean has no interpretation.

Instead, find the tasks the gap rests on and buy a repeat of just those, against the shipped
model, with no model change. On polar_equipment the two estimates were 0.425 and 0.490 and the
whole 0.065 sat on two tasks; re-running that pair cost **$0.73** and five minutes, both scored
higher than their last figure, and the recorded estimate became the mean of the two runs on the
shipped model for those two tasks and latest-per-task elsewhere. A full 20-task re-run would
have cost $6.30 and an n=3 $19.

Record which estimator you used and on which tasks — a reward figure whose construction is not
stated cannot be compared with the next database's.

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
un-overridable; a top-level `UNION ALL` over the model **works** — it dispatches and grades, and a listing
`UNION ALL` a one-row summary is a working shape (corrected 2026-09-23; the old entry here said it
returned zero rows). What does not work: a `UNION` inside a subquery, CTE or `WHERE`; a bare `NULL`
literal in a branch, which needs `CAST(NULL AS VARCHAR)`; and the branch **order**, which the engine
re-sorts and no `ORDER BY` can restore (E-17). Also: a
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

### 5b. A ceiling sweep is a lower bound on the model, not an upper bound on the agent

Measured 2026-09-22 on virtual_idol: nine sweep rounds established that 8 of 19 tasks were
reachable, and the baseline then passed a task that was **not** in that set — the agent found a
query for `_16` that reached all four of its rows where my hand-written one reached three. Use the
sweep to prove a fix sufficient and to find model gaps; do not quote it as the model's ceiling, and
do not treat a task the sweep could not reach as capped.

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

- **Gate a few minutes AFTER deploying, not instantly.** `sml-cli atscale-deploy` can kill the
  engine JVM (E-14), and it does so *after* returning `Deploy SUCCESSFUL`, so a gate run seconds
  later passes and the run then dies under you. Measured 2026-09-19: a gate passed clean, the run
  launched, and all three tasks burned their full 18-coin budget with **10-12 `list_models` calls
  each** (one is normal) and two recorded a passing submission yet scored 0. Void it; do not read
  it as a result. The fingerprint of this class is **budget exhaustion plus repeated metadata
  calls**, and afterwards `gate_run.sh` reports `list_models errored`. Recovery is the engine's own
  restart plus a redeploy; MCP sessions do not survive it (`ATSCALE_ENGINE_AUTH_PERSIST_SESSION=false`),
  so a stale 401 on your own MCP client afterwards is expected and is not the harness's token.
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
- **Cost scales with the number of whole-arm RUNS, not with the task count.** Measured
  2026-09-20: insider_trading's 21 tasks cost $0.24 per task-run, the same as the 10-task
  databases, and its $18.70 total is explained by three whole-arm runs rather than by having
  twice the tasks. A database needing one baseline and one close should land near $10-12
  whatever its size; each extra arm is about $5.
- **Whole-arm repeats belong on the raw baseline, once.** Measured: across repeats the
  semantic arm moved on 1 task of 19, raw on 7 of 19; 13 raw tasks were perfectly stable
  and six carried the whole spread. Budget n≥3 raw when establishing a baseline. Inside the
  loop, the target's n=2 *is* the semantic repeat. A single run per arm read anywhere from
  +7 to +32 pp of lift on identical code.
- Report the mean of the repeats with its range, in percentage points, relative alongside.
  Never quote a single pair. One outlier run paired with one good run produced a headline
  double the settled value — and it was the number everything else got compared against.

### Operational gotchas, each of which has wasted a cycle

- **A whole arm that finishes in seconds with every task at `error reward=0.0` is the Anthropic
  workspace usage cap, not your model - and it is a DIFFERENT quota from the claude.ai
  subscription this session runs on.** The benchmark bills `ANTHROPIC_API_KEY` from the ADK
  `.env` to a console API workspace, so a healthy subscription usage page is not evidence
  against the failure; on 2026-09-20 that looked like a contradiction and was not. Separate
  the two in seconds by probing each key in `.env` with a 1-token `/v1/messages` call - the
  configured key returned HTTP 400 with the cap message and a key commented out one line
  above returned HTTP 200. Swapping keys moves the billing, so it is Dianne's call, and the
  services must be restarted afterwards because they read the key at start.** Four occurrences so far (2026-08-10, 08-20, 09-07,
  09-20; A-70). `logs/system_agent.out` carries the `AnthropicException ... "You have reached
  your specified workspace API usage limits"`, `results/llm_usage.jsonl` gains **zero** rows in
  the run window, and the runner warns "No LLM usage rows for this run". The pre-run gate passes
  immediately before, because the engine and the catalog are healthy - which is exactly what
  makes it easy to misread as a catalog fault. Void the run; it is not a measurement and it costs
  nothing. Everything that makes no LLM call still works, so a capped session's deliverable is
  the ceiling table, the model and the cap list.
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
   `loop_step.py` labels a submission `PASS` when the trajectory entry carries no `passed`
   key — which is what an **execution error** looks like. Measured 2026-09-22: two of one task's
   four submissions were reported as passes and both had failed the engine's own validator. Read
   the `result` text before believing a `PASS` line. **A pass counts only if the trajectory shows the fix's mechanism firing** — the ask you
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

### 3. Once per database — close ($1–3, or a full arm at n≥2 on a twin-heavy model)

**Budget the close run's second repeat from the start.** Measured 2026-09-20 on
insider_trading: the close run scored 0.3190 where the baseline had scored 0.3857 on a model
differing only in description text, and the second repeat came back 0.3381 - 5 of 21 tasks
flipped between the two identical-model runs. One close run would have reported a regression
that does not exist. Where the model publishes many competing readings, the agent's choice
among them is resolved by the simulator and moves more score than the pass's edits do, so a
single close run cannot state a number. The third arm cost $4.82 of an $18.70 pass and was
the difference between a number and a guess.


One run of every task whose model object you touched — targets and canaries — at n=1 on the
final deployed model, so the pass ends on one artifact under one grader against one model.
Stop when the worklist has no task left in the loop or the database cap is reached,
whichever is first.

**Then propagate, as the last step and not before.** A pass produces findings all the way to its
final iteration, so propagating in the middle guarantees the last ones are lost. Measured
2026-09-19: the process changes from that session's first half reached all 21 kickoff files, and
the three findings from its second half — ceiling-test-first, prescriptive descriptions, E-14 gate
timing — reached **none** of them, because the propagation had already happened and nothing
brought it back. The pass was declared closed with a third of its lessons stranded in one report.

Make it mechanical rather than a resolution:

1. **List every finding this pass produced**, from the baseline classification to the last
   iteration, including the ones that cost nothing and the ones that turned out wrong.
2. **For each, name where it landed** — `docs/create_bird_model_prompt.v12.md` for a modelling
   rule, this document for a process or spend rule, `results/kickoff_*_v12.md` for something the
   next database must do differently, the tracker for a defect or a cap — **or state that it
   landed nowhere and why.** "It is in the pass report" is not landed: nobody reads a previous
   database's report before starting the next one.
3. **Audit with grep, not memory**: one distinctive phrase per finding, counted across all 21
   kickoff files, printed as `n/21`. A finding that should be in every kickoff and is in three is
   the normal failure and it is invisible without the count.
4. **Corrections propagate too.** Where the pass proved an earlier rule wrong — a stale cap, a
   mis-applied rule, a retired workaround — edit that rule where it lives. A wrong rule left
   standing costs more than a missing one.

Only then write the report's closing section, and say in it which findings propagated where.

Then report from the worklist: each task's stop condition and price, predicted versus what
happened, spend against the caps, and the lift on the intersection against the re-graded
raw baseline, in percentage points with relative alongside.
