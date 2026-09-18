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
  they run, report when there is something to report. Stop only for decisions that are
  genuinely mine: spending beyond what I approved, shipping a change whose evidence you
  doubt, or a real tradeoff with no better option.
- **Concise.** Real numbers, no preamble, no recap of what you just did. What you found,
  what it means, what it cost.
- **Always end with next steps and their price.**
- Correct your own earlier conclusions in one line and move on. A wrong finding left
  standing costs the next session more than it cost you.

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
4. **Read the new trajectory, not the score**: `failing_sql.py` for the asks and the
   submitted SQL, `gold_diff.py` for the finding. The question is whether the finding is the
   same class as last iteration or a new one — a new one means the fix landed and the next
   constraint up the stack is now binding; the same one means the lever does not reach.

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

### 3. Once per database — close ($1–3)

One run of every task whose model object you touched — targets and canaries — at n=1 on the
final deployed model, so the pass ends on one artifact under one grader against one model.
Stop when the worklist has no task left in the loop or the database cap is reached,
whichever is first.

Then report from the worklist: each task's stop condition and price, predicted versus what
happened, spend against the caps, and the lift on the intersection against the re-graded
raw baseline, in percentage points with relative alongside.
