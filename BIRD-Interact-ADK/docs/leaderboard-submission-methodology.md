# BIRD-INTERACT-1.0-full, a-Interact — AtScale Semantic Layer

Submission from AtScale. Everything below is stated so the result can be checked or
contested without taking anything on trust.

| | |
|---|---|
| Split / mode | BIRD-Interact-Full, 600 tasks, a-Interact |
| Agent models | eight, listed below |
| User simulator | `claude-haiku-4-5-20251001` (seven models) and `gpt-4o` (GPT-5), **your prompts and token limits, unmodified** |
| Efficiency (budget) | 17.86 average, matching the value listed for every Full a-Interact entry |
| Runs | 3 per model, all 600 tasks, all included |
| Harness | public fork: github.com/dave-mariani-atscale/BIRD-Interact, branch `feature/atscale-mcp-semantic-layer` |
| Dates | 2026-09-11 to 09-23 |
| Contact | dave@atscale.com |

## Results

Success Rate is the blended phase-1 rate over all 600 tasks; Reward is
(0.7·P1 + 0.3·P2)·100. Both are the best single run by reward, which is the
convention your guidelines describe. **Validated** is our own gold replay (§3) and is
the figure we expect your evaluator to reproduce. **First run** is each model's
opening run from an empty state (§4).

**Claude-Haiku-4-5 simulator track**

| Model | Success | Validated | Reward | Query P1 | Query P2 | Mgmt P1 | Coins | First run | 3-run mean |
|---|---|---|---|---|---|---|---|---|---|
| Claude-Sonnet-5 | 53.17 | **53.00** | 47.02 | 57.1 | 37.3 | 44.7 | 15.57 | 49.17 | 51.44 ± 1.68 |
| Claude-Opus-4.6 | 50.33 | **50.17** | 45.08 | 54.4 | 38.3 | 41.6 | 15.12 | 44.33 | 47.89 ± 2.57 |
| Kimi-2.5 | 49.00 | **48.83** | 42.90 | 53.7 | 34.1 | 38.9 | 16.49 | 43.33 | 46.06 ± 2.32 |
| Grok-4.3 | 46.00 | **45.67** | 39.75 | 46.3 | 25.9 | 45.3 | 16.01 | 40.50 | 43.33 ± 2.25 |
| Nemotron-Ultra | 44.83 | **44.50** | 39.28 | 47.8 | 30.2 | 38.4 | 16.32 | 41.33 | 43.39 ± 1.49 |
| Qwen3.8-27B | 37.83 | **37.67** | 33.48 | 40.5 | 28.3 | 32.1 | 12.80 | 33.83 | 36.39 ± 2.22 |
| GLM-4.7 | 33.50 | **33.33** | 28.90 | 33.9 | 21.7 | 32.6 | 16.18 | 30.17 | 32.28 ± 1.84 |

**GPT-4o simulator track** — not comparable to the rows above, different simulator.

| Model | Success | Validated | Reward | Query P1 | Query P2 | Mgmt P1 | Coins | First run | 3-run mean |
|---|---|---|---|---|---|---|---|---|---|
| GPT-5 | 48.17 | **47.83** | 43.02 | 51.5 | 34.9 | 41.1 | 14.80 | 44.33 | 46.83 ± 1.77 |

## What the system is

An agent that answers through a governed **semantic layer** (AtScale) rather than
writing physical SQL against the raw schema. It sees a semantic model over each BIRD
database through an MCP server and writes logical SQL against metrics and dimensions;
the engine compiles that to PostgreSQL. That is the only substantive difference from
a raw text-to-SQL agent. The scaffold is your own Google-ADK `BIRD-Interact-ADK`
implementation with a semantic-layer backend added, and the fork is public so every
change to your harness can be diffed against yours.

## Things you should know before scoring this

**1. The predicted SQL is the engine's outbound SQL, not the text the agent wrote.**
Logical SQL cannot execute on your PostgreSQL, so for every graded submission we
captured the physical PostgreSQL the engine dispatched, and that is what
`subtask_*_predicted_sql` contains. The agent's own logical SQL is preserved in
`prompt_flow` under the `submit_sql` action so the two can be compared. Every query
carried the engine hints `use_aggs(false)` and `generate_aggs(false)`, so no
aggregate table was read and the SQL references only base tables present in your
database.

A **set operation** is not dispatched as one engine query: the engine runs it branch
by branch and applies the statement's `ORDER BY` to the concatenated result. Our first
export captured only the last branch, so those rows returned a fraction of the answer;
a second attempt joined the branches but lost the ordering. Both are fixed — branches
are combined with `UNION ALL` and the statement's own `ORDER BY`/`LIMIT` reapplied
around them. For the Sonnet and Opus sweeps, which ran before the fix, affected rows
were repaired afterwards and are flagged in `notes`; the four later sweeps captured
correctly at run time. About 5 of 410 Query tasks per run are affected.

Where the engine returned an error instead of executing, no outbound SQL exists; those
rows fall back to the logical SQL, are flagged in `notes`, and will not execute on
your evaluator. They should score 0, which is what we recorded.

**2. Management-category tasks run on raw PostgreSQL.** A semantic layer is read-only,
so all 190 Management (WRITE) tasks route per task to the standard raw tools and the
standard raw grading path inside the same run; only the 410 Query (READ) tasks use the
semantic layer. Each row's `category` and `backend` say which path it took. This is
also a useful control: Management sits at 32–45% across all eight models while Query
moves with the semantic layer.

**3. We re-graded our own submission and are quoting the lower number.** Every
exported Query SQL was re-executed against a clone of each task's template database
and re-graded under **upstream** rules. All eighteen runs land within 0.34 of what we
reported; the Validated column above is the result.

`museum_artifact_6` disagrees in all eighteen: it returns gold's 545 rows exactly and
fails only because upstream grading strips `DISTINCT` from both sides, inflating that
gold to 566 rows. We are not asking you to count it as a pass.

Five further tasks disagreed in exactly one replay each and never twice. Every one is
order-sensitive or has no ordering guarantee, and the cause is worth stating because
it will affect your own verification: BIRD marks 57 of 410 Query tasks `order=true` on
gold whose `ORDER BY` does not totally order its own result, so which rows gold emits
first can change with the query plan. A submission that matched gold's order in one
execution can fail the next. Replaying the same fixed SQL three times in one session
gave identical results every time, but a replay months or machines apart will not
necessarily agree to the task. We therefore treat any deviation under 0.5 points
(three tasks of 600) as gold's instability rather than a finding about the submission.

**4. The three runs are sequential and not independent.** Our system carries state
across tasks within a sweep, so the second and third runs of a model start from what
the first learned and score 3 to 6 points higher. The **First run** column is each
model's opening run from an empty state, and it is the figure to use if you would
rather list a number with no carry-over at all. We have no preference and will list
whichever you consider correct; we simply did not want to hand you the higher number
without saying where it comes from. The mechanism is described in a draft whitepaper
we are finishing and can share with you.

**5. The scaffold was developed against this public dataset.** Our agent instruction
and the 22 semantic models were built and tuned while measuring against
BIRD-Interact-Full, whose tasks and gold SQL are public. Nothing in the guidelines
prohibits it and any entrant could do the same, but it is a real difference from work
that trains on Lite and evaluates on Full, and you should weigh it. The instruction is
in the public fork, at `BIRD-Interact-ADK/config/environment_backends.yaml`.

**6. Grading is yours, unmodified.** Our harness carries six optional comparison
corrections we use for internal A/B work (case-insensitive text, column-order
independence, and others). **All six are off for these runs.** Row comparison is exact,
as in `evaluation/src/eval_bird_interact.py`. The services report
`{"regime":"upstream","corrections":[]}` on their health endpoint and each results
file records it.

**7. Costs follow the Universal Cost Scheme.** ask_user 2, submit_sql 3, run_query 1,
and every other action 0.5 or 1.0 by the token rule; each tool's placement was measured
from its real input and output sizes rather than assumed. Budget is
6 + 2·ambiguities + 2·patience with patience 3, averaging 17.86 over the 600 tasks —
the same value your board lists.

**8. Failures we are not hiding.** A task that errored is scored as a **failure**, not
excluded, so the rates above already carry them. Counts across each model's three runs:

| Model | Task errors / 1,800 | Cause |
|---|---|---|
| Claude-Sonnet-5 | 0 | — |
| Claude-Opus-4.6 | 1 | agent emitted a malformed tool call (`cross_border_18`) |
| Kimi-2.5 | 43 | provider 5xx / rate-limit from the hosting endpoint |
| Nemotron-Ultra | 27 | provider 5xx / rate-limit from the hosting endpoint |
| GPT-5 | 20 | provider 5xx / rate-limit from the hosting endpoint |
| Grok-4.3 | 0 | — |
| Qwen3.8-27B | 11 | client-side read timeout to the agent service |
| GLM-4.7 | 6 | client-side read timeout to the agent service |

The open-weight and hosted-API models were served through a third-party
inference provider, and those errors are infrastructure rather than model behaviour.
Scored as failures they depress those models' numbers by roughly 1 to 2 points
against a clean run (well under 1 point for Qwen3.8-27B and GLM-4.7, whose counts are
single-digit to low-double-digit). We have not re-run to remove them.

## Files

| File | Contents |
|---|---|
| `*.jsonl` | The submission. 600 rows per run: `instance_id`, both predicted SQL fields, `prompt_flow` (every prompt, response, action, `action_cost`, `remaining_budget`, per-turn token counts), plus `category`, `backend`, our own verdict, our validated verdict and any `notes` |
| `*.summary.json` | Per-run totals, category split, warning counts |
| `METHODOLOGY.md` | This file |

`local_verdict` is what our harness scored; `validated_verdict` is our own gold replay
under your rules. Where your evaluator disagrees with either, yours is correct and we
would like to know.

## Reproducing

The harness is the public fork above, run with `LEADERBOARD_MODE=true`, the single
switch that disables every deviation described here. We have also built a fully
self-hosted offline verification package: one command, everything runs on your
machine, nothing contacts AtScale. It has two tiers — a deterministic replay that
re-executes our submitted SQL on your warehouse and re-grades upstream (no API key
needed), and an optional full re-run of the pipeline against a band declared in
advance. We are glad to ship it.
