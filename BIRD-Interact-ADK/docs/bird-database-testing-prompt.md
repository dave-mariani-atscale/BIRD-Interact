# Prompt: testing and fixing a BIRD database on the semantic layer

Paste this at the start of a session working on a new BIRD-Interact database.
Distilled from the ETF work of 2026-08-13/14; the examples are ETF, the method is not.

---

We are measuring **semantic-layer lift**: how much better the `atscale` arm scores than the
`raw` arm on the same tasks. Your job is to find why tasks fail, fix them in the right
layer, and report numbers that survive a repeat.

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
2. **One run per session, and only when a $0 route cannot answer the question.** Batch every
   pending change into it.
3. **Predict what each change will move before you spend.** Write the prediction down. If
   the honest prediction is "nothing measurable", say so and don't run.
4. Never start a run I didn't ask for. Never run two evaluations at once — usage is
   attributed by timestamp window.

### What is free (no LLM calls, no benchmark tokens)

| tool | answers |
|---|---|
| `scripts/outbound_sql.py "SELECT ..."` | what the engine actually dispatched |
| `scripts/outbound_sql.py --query-id <uuid>` | resolve an earlier `run_query` |
| `scripts/clause_fidelity.py` | battery: inbound vs dispatched, dropped clauses |
| `scripts/regrade_flags.py` | re-score a finished run under new grading logic |
| MCP `run_query` + Postgres on `<db>_template` | model vs gold, value by value |
| stored trajectories in `results/*.json` | every query the agent wrote, and its verdict |
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

### 2. Diff against gold at value level

For any failing task, in one batch: pull the graded submission (the **last** trajectory
entry carrying an `sql` key, not the first), run it live, run gold against
`<db>_template`, and compare row count, column count and order, values, row order, rounding.
This diagnosed four ETF tasks in one sitting for $0 and named a cause for each.

Gold may be read to **diagnose**, never to build.

### 3. Derive the decision rule, don't read the score

A task score is a noisy aggregate over independent requirements. Work out the exact set of
conditions a submission must satisfy, then score every stored submission against that rule
until it agrees on all of them. One task's phase 1 needed three things at once; only then
was it obvious that one was failing and two were already fine — the opposite of what the
score suggested.

### 4. Re-grade before comparing anything

Every stored baseline was graded under whatever code existed then, and comparing across that
boundary invents regressions.

    python scripts/regrade_flags.py atscale|raw <results.json> --database <db>

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

## Running an arm

Write a script per run, with a header stating what changed, which tasks it should move, and
which tasks are canaries — so a null result is readable and a regression is caught before you
read any improvement. Then:

- `bash scripts/gate_run.sh` first, every time: services newer than the newest harness
  commit, catalog healthy (a working `run_query` is *not* evidence — metadata calls can be
  dead while queries work), template databases unmodified.
- Keep `SYSTEM_AGENT_MODEL` fixed for anything scored. Haiku is fine for plumbing only.
- `--query-only` on the raw arm, or the arms cover different task sets. **Compute lift on the
  intersection, never on arm totals.**
- `--tasks <id,...> --repeat N` for targeted validation; ~$0.25 per task-run.
- **Repeats belong on the raw arm.** Measured: across repeats the semantic arm moved on 1
  task of 19, raw on 7 of 19; 13 raw tasks were perfectly stable and six carried the whole
  spread. Budget ~4 raw repeats to 1–2 semantic. A single run per arm read anywhere from +7
  to +32 pp of lift on identical code.
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

## Non-negotiable

- **Gold SQL diagnoses, never builds.** Nothing shipped to the model, guidance, or code may
  come from an answer key. Masked thresholds never ship; gate it mechanically.
- Record findings in the tracker as you go, including corrections to your own entries.
- **File engine defects.** Guidance mitigation is a workaround; a defect with a
  mechanism-grade repro and no ticket never gets fixed, and the same dialect gaps will hit
  every other database.
- Never write to a `*_template` database. Gold executes against it, so a stray DML there
  corrupts the grading reference for every future run — this cost two tasks in every arm for
  a day before it was found.

## Start here on a new database

Batch 1 — **$0, do all of it before spending anything:**

1. Re-grade any existing baseline; only run both arms if none exists.
2. Read every failing task's submitted SQL from the stored trajectories.
3. Value-diff each failure against gold; read the dispatched SQL for anything
   plausible-but-wrong.
4. Group failures by shared cause, and sort into: engine-blocked, model-fixable,
   simulator/ambiguity, gold non-unique, agent-side.
5. For each model-fixable one, prove sufficiency for free (§ Predict the payoff).

Batch 2 — **one run:** every change that survived batch 1, with predictions written down
first. Gate, run, then judge by the mechanism you targeted, not by the total.

Then report: what failed, why, which layer, what it cost, what's next — and what you
predicted versus what happened.
