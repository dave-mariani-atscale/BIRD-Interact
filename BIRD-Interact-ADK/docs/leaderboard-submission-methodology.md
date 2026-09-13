# BIRD-INTERACT-1.0-full, a-Interact — AtScale Semantic Layer

Submission from AtScale. Everything below is stated so the result can be
checked or contested without taking anything on trust.

| | |
|---|---|
| Split / mode | BIRD-Interact-Full, 600 tasks, a-Interact |
| Agent models | `claude-sonnet-5` (primary) and `claude-opus-4-6` |
| User simulator | `claude-haiku-4-5-20251001`, **your prompts and token limits, unmodified** |
| Efficiency (budget) | 17.86 average, matching the value listed for every Full a-Interact entry |
| Runs | 3 per model, all 600 tasks, all included |
| Dates | 2026-09-11 / 13 |
| Contact | dave@atscale.com |

## Results

Success Rate is the blended phase-1 pass rate over all 600 tasks; Reward is
blended (0.7·P1 + 0.3·P2)·100. "Validated" is our own gold replay — see
"We re-graded our own submission" below — and is the figure we expect you to
reproduce.

| Run | | Success | Validated | Reward | Query | Mgmt | Coins |
|---|---|---|---|---|---|---|---|
| **Sonnet 5 r3** | warm | **53.17** | **53.00** | 47.02 | 57.1 | 44.7 | 15.57 |
| Sonnet 5 r2 | warm | 52.00 | 51.83 | 46.05 | 55.6 | 44.2 | 15.76 |
| Sonnet 5 r1 | **cold** | 49.17 | 49.00 | 42.32 | 51.2 | 44.7 | 16.63 |
| Opus 4.6 r3 | warm | 50.33 | 50.17 | 45.08 | 54.4 | 41.6 | 15.12 |
| Opus 4.6 r2 | warm | 49.00 | 48.83 | 43.50 | 52.0 | 42.6 | 15.41 |
| Opus 4.6 r1 | **cold** | 44.33 | 44.00 | 39.13 | 45.9 | 41.1 | 16.28 |

Sonnet 5 mean 51.45 (sd 1.68); Opus 4.6 mean 47.89 (sd 2.57). One task error in
3,600 task-runs.

## What the system is

An agent that answers through a governed **semantic layer** (AtScale) rather
than writing physical SQL against the raw schema. It sees a semantic model over
the BIRD database through an MCP server and writes logical SQL against metrics
and dimensions; the engine compiles that to PostgreSQL. That is the only
substantive difference from a raw text-to-SQL agent. The scaffold is the
Google-ADK `BIRD-Interact-ADK` implementation you publish, with a semantic-layer
backend added.

## Things you should know before scoring this

**1. The predicted SQL is the engine's outbound SQL, not the text the agent
wrote.** The agent writes logical SQL against the semantic model, which cannot
execute on your PostgreSQL. For every graded submission we captured the physical
PostgreSQL the engine dispatched for that execution, and that is what
`subtask_*_predicted_sql` contains. The agent's own logical SQL is preserved in
`prompt_flow` under the `submit_sql` action so the two can be compared. Every
query ran with the engine hints `use_aggs(false)` and `generate_aggs(false)`, so
no aggregate table was read or created and the outbound SQL references only base
tables present in your database.

A **set operation** is not dispatched as one engine query: the engine runs it
branch by branch and applies the statement's `ORDER BY` to the concatenated
result. Our first export captured only the last branch, so those rows returned a
fraction of the answer; a later one joined the branches but lost the ordering.
Both are fixed — the branches are combined with `UNION ALL` and the statement's
own `ORDER BY`/`LIMIT` is reapplied around them — and rows repaired this way are
flagged in `notes`. 5 of 410 Query tasks per run are affected.

Where the engine returned an error instead of executing, no outbound SQL exists;
those rows fall back to the logical SQL, are flagged in `notes`, and will not
execute on your evaluator. They should score 0, which is what we recorded.

**2. Management-category tasks run on raw PostgreSQL.** A semantic layer is
read-only, so all 190 Management (WRITE) tasks are routed per task to the
standard raw tools and the standard raw grading path, inside the same run. Their
SQL is ordinary PostgreSQL. Only the 410 Query (READ) tasks use the semantic
layer. `category` and `backend` on each row say which path a task took. This is
also a useful control: Management sits at 41–45% across every run, while Query
moves with the semantic layer.

**3. We re-graded our own submission, and we are reporting the lower number.**
Every exported Query SQL was re-executed against a clone of each task's template
database and re-graded under **upstream** rules, which is the verdict we think
your evaluator will reach. On the run we are putting forward it returns **53.00**
against our own 53.17. Exactly one task of 600 disagrees on every repaired run: `museum_artifact_6`
returns gold's 545 rows exactly, and fails only because upstream grading strips
`DISTINCT` from BOTH sides, which inflates that gold to 566 rows. We are not
asking you to treat that as a pass — we mention it only so the 0.17 is
accounted for. Quote 53.00.

**4. Memory, and why the cold run is also reported.** The MCP server has a
feedback-memory feature: it records each question, the query it produced and
whether the answer was accepted, and replays confirmed patterns as context. The
store was truncated to empty before r1 of each model, so **r1 is cold**. Runs 2
and 3 warm on memory accumulated during that sweep, i.e. from the evaluation set
itself. That is worth 3–6 points and we do not think it should be reported
without saying so. Both figures are in the table. Note it also makes the agent
cheaper: coins fall from 16.28 to 15.12 across the Opus sweep.

**5. The scaffold was developed against this public dataset.** Our agent
instruction and the 22 semantic models were built and tuned while measuring
against BIRD-Interact-Full, whose tasks and gold SQL are public. Nothing in the
guidelines prohibits this and any entrant could do it, but it is a real
difference from work that trains on Lite and evaluates on Full, and you should
weigh it.

**6. Grading is yours, unmodified.** Our harness carries six optional comparison
corrections used in our internal A/B work (case-insensitive text, column-order
independence, and others). **All six are off for these runs.** Row comparison is
exact, as in `evaluation/src/eval_bird_interact.py`. The services report
`{"regime":"upstream","corrections":[]}` on their health endpoint and each
results file records it.

**7. Costs follow the Universal Cost Scheme.** ask_user 2, submit_sql 3,
run_query 1, and every other action 0.5 or 1.0 by the token rule; we measured
each tool's real input and output sizes to place it. Budget is
6 + 2·ambiguities + 2·patience with patience 3, averaging 17.86 over the 600
tasks — the same value your board lists.

**8. One agent failure, disclosed.** In Opus r2, one task (`cross_border_18`)
failed because the agent emitted a malformed tool call. It is scored 0. No other
run had one.

## Files

| File | Contents |
|---|---|
| `*.repaired.jsonl` | The submission. 600 rows per run: `instance_id`, both predicted SQL fields, `prompt_flow` (every prompt, response, action, `action_cost`, `remaining_budget`, per-turn token counts), plus `category`, `backend`, our own verdict, our validated verdict and any `notes` |
| `*.summary.json` | Per-run totals, category split, warning counts |
| `METHODOLOGY.md` | This file |

`local_verdict` is what our harness scored; `validated_verdict` is our own gold
replay under your rules. Where your evaluator disagrees with either, yours is
correct and we would like to know.

## Reproducing

The harness is a fork of `bird-bench/BIRD-Interact` (the `BIRD-Interact-ADK`
implementation) with a semantic-layer backend added, run with
`LEADERBOARD_MODE=true`, the single switch that disables every deviation
described above. We are glad to supply the code and a hosted semantic-layer
endpoint for validation-mode verification.
