# BIRD-INTERACT-1.0-full, a-Interact — AtScale Semantic Layer

Submission from AtScale, re-run with **feedback memory off** as the BIRD team asked on
2026-11-08. Everything below is stated so the result can be checked or contested
without taking anything on trust. This submission replaces the one we sent on
2026-10-12, which offered two memory-on figures (§9).

| | |
|---|---|
| Split / mode | BIRD-Interact-Full, 600 tasks, a-Interact, stress mode (budget-constrained, Universal Cost Scheme) |
| Agent models | four, listed below |
| User simulator | `claude-haiku-4-5-20251001` (three models) and `gpt-4o` (GPT-5), **your prompts and token limits, unmodified** |
| Efficiency (budget) | 17.86 average, matching the value listed for every Full a-Interact entry |
| Feedback memory | **off**: `FEEDBACK_MEMORY=false` in the harness, `ATSCALE_MCP_FEEDBACK_MEMORY=false` on the MCP server, for every run (§4) |
| Runs | 3 per model, all 600 tasks, all included, independent of each other; concurrency 10 |
| Harness | public fork: github.com/dave-mariani-atscale/BIRD-Interact, branch `feature/bird-memoff-reruns`, commit `669dcf1` (Opus 4.6: `74b3358`, one commit earlier; `669dcf1` adds only an offline packaging script) |
| Semantic models | `bird-atscale-models` at tag `deployed-memoff` (`3967b1a9`), supplied as a zip of the repository |
| Semantic engine / MCP server | AtScale engine develop `42.0.0-2665` (image `sha256:4391ea45…`), MCP server `22c9afa0` (image `sha256:e2185a40…`) |
| Dates | 2026-11-09 to 2026-11-11 |
| Contact | dave@atscale.com |

## Results

Success Rate is the blended phase-1 rate over all 600 tasks; Reward is
(0.7·P1 + 0.3·P2)·100. With memory off the three runs of each model are independent
samples, so all three are reported. By the board's convention the figure to publish is
the **best of the three**, chosen by Success Rate with ties broken by Reward; it is
marked **best**. Your Submission Guidelines address run count in §V, Validation
Submission Mode, which recommends at least three runs and says "we will report the
best result among them" without naming the metric, so we state ours.

**Success Rate and Reward are our own replay of the submitted SQL under your grading
(§3)**: the figures we expect your evaluator to reproduce. **Live** is what our harness
scored during the run; the two agree to the row except where §3 says. The GPT-5 rows
are on the GPT-4o simulator track, a separate board entry, and are not comparable to
the Claude-Haiku-4-5 rows.

| Model | User simulator | Run | Success Rate | Reward | Live success | Live reward | Query P1 | Query P2 | Mgmt P1 | Coins / query task |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude-Opus-4.6 | Claude-Haiku-4-5 | 1 | 46.33 | 40.93 | 46.00 | 40.65 | 48.54 | 30.98 | 41.58 | 16.20 |
| | | **2 (best)** | **47.50** | **42.10** | 47.17 | 41.87 | 50.24 | 32.93 | 41.58 | 16.03 |
| | | 3 | 45.83 | 40.48 | 45.83 | 40.43 | 48.78 | 31.71 | 39.47 | 16.10 |
| Gemini-3.1-Pro | Claude-Haiku-4-5 | **1 (best)** | **54.00** | **46.45** | 54.17 | 46.62 | 55.85 | 32.93 | 50.00 | 17.18 |
| | | 2 | 53.33 | 45.83 | 53.50 | 46.00 | 55.85 | 32.68 | 47.89 | 17.26 |
| | | 3 | 52.83 | 45.23 | 52.67 | 45.07 | 54.88 | 30.73 | 48.42 | 17.23 |
| Kimi-2.5 | Claude-Haiku-4-5 | **1 (best)** | **42.33** | **36.08** | 42.33 | 36.08 | 43.41 | 23.66 | 40.00 | 17.11 |
| | | 2 | 40.33 | 34.23 | 40.33 | 34.23 | 40.49 | 22.44 | 40.00 | 17.08 |
| | | 3 | 41.83 | 35.68 | 41.50 | 35.45 | 42.44 | 24.63 | 40.53 | 17.01 |
| GPT-5 | GPT-4o | 1 | 43.33 | 37.93 | 43.33 | 37.93 | 44.63 | 26.34 | 40.53 | 15.75 |
| | | 2 | 44.17 | 38.87 | 44.17 | 38.87 | 46.59 | 27.56 | 38.95 | 15.89 |
| | | **3 (best)** | **44.33** | **38.78** | 44.17 | 38.67 | 45.37 | 27.07 | 42.11 | 15.83 |

3-run mean Success Rate (± sd): Opus 4.6 46.56 ± 0.86, Gemini 3.1 Pro 53.39 ± 0.59,
Kimi 2.5 41.50 ± 1.04, GPT-5 43.94 ± 0.54. The spread is within the binomial standard
error of a 600-task rate (about 2 points), as independent samples should be.

Query P1/P2 and Mgmt P1 are the phase rates on the 410 Query and 190 Management tasks;
coins are the mean budget spent per Query task out of 17.86. For GPT-5, run 3 has the
highest Success Rate but run 2 the highest Query P1 (46.59 against 45.37); we mark run
3 by the rule above, and all three runs are in the bundle if you apply another.

Gemini 3.1 Pro has no board entry of its own; the other three do. Per-database rates for
every run, and the same runs set against our earlier memory-on sweeps of the same
models, are in the results workbook, `AtScale_BIRD_Results_Workbook_2026-11_memory_off.xlsx`
in the shared folder: one tab per model plus a `README` tab.

## What the system is

An agent that answers through a governed **semantic layer** (AtScale) rather than
writing physical SQL against the raw schema. It sees a semantic model over each BIRD
database through an MCP server and writes logical SQL against metrics and dimensions;
the engine compiles that to PostgreSQL. For query tasks, that backend — its tools and
its instruction — is the only substantive difference from a raw text-to-SQL agent.
The scaffold is your own Google-ADK `BIRD-Interact-ADK` implementation with a
semantic-layer backend added, and the fork is public so every change to your harness
can be diffed against yours.

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
by branch and applies the statement's `ORDER BY` to the concatenated result. The
export combines the branches with `UNION ALL` and reapplies the statement's own
`ORDER BY`/`LIMIT` around them.

Where the engine returned an error instead of executing, no outbound SQL exists; those
rows fall back to the logical SQL, are flagged in `notes`, and will not execute on your
evaluator. They score 0, which is what we recorded.

**2. Management-category tasks run on raw PostgreSQL.** A semantic layer is read-only,
so all 190 Management (WRITE) tasks route per task to the standard raw tools and the
standard raw grading path inside the same run, with the same instruction the raw arm
uses; only the 410 Query (READ) tasks use the semantic layer. Each row's `category`
and `backend` say which path it took. This is also the control: Management P1 on the
semantic-layer arm (3-run mean) against the same model's raw arm is Opus 40.88 vs
40.00, Gemini 48.77 vs 49.47, Kimi 40.18 vs 37.89, GPT-5 40.53 vs 41.05 — all within
run-to-run noise on 190 tasks (binomial SE ≈ 3.6 points) — while Query P1 is 1.5 to
2.2 times the raw arm's.

**3. We re-graded our own submission and are quoting that number.** Every exported
Query SQL was re-executed against a clone of each task's template database and
re-graded under **upstream** rules; the Success Rate and Reward figures above are the
result. Our leaderboard-mode grader cleans `DISTINCT` exactly as
`evaluation/src/eval_bird_interact.py` does — equal to your `remove_distinct` on all
1,288 gold statements in the dataset — so live and replayed verdicts agree except for
15 of 7,200 rows across the twelve runs, each counted the way the replay scores it:

- `crypto_exchange_9` (6 runs) and `sports_events_19` (3 runs): live fail, replay pass
  on phase 1. `labor_certification_applications_3` (2 runs) and `virtual_idol_20`
  (1 run): live fail, replay pass on phase 2. The exported SQL run on PostgreSQL
  matches gold where the live comparison of engine-returned rows did not. Your
  evaluator scores the SQL, so they count.
- `cross_border_7` (2 runs): live pass, replay fail on both phases, and
  `exchange_traded_funds_11` (1 run): live pass, replay fail on phase 1. The query
  takes a LIMIT over rows tied on its sort key, and the tie broke differently on a
  fresh template. Counted as fails.

Each run's `*.summary.json` lists its own. Tasks that are order-sensitive on gold
whose `ORDER BY` does not totally order its own result (57 of 410 Query tasks are
marked `order=true` on such gold) can flip between executions for reasons unrelated to
the submission. We treat any deviation under 0.5 points as that instability rather
than a finding.

**4. Feedback memory was off, on both sides, in every run.** Our MCP server has a
feedback memory: when it is on, the harness records each graded submission's pass or
fail as the user's verdict and the server shows certified query shapes to the agent on
later tasks. That is what you asked us to remove, and every run here has it off:

- **The harness** ran with `FEEDBACK_MEMORY=false`, so it sends no verdicts. Each
  results file records `feedback_memory: false` in its `deviations` block, and the
  launcher checked every results file for it before accepting the run.
- **The MCP server** ran with `ATSCALE_MCP_FEEDBACK_MEMORY=false`, which its
  `/configz` endpoint reports and the launcher checked before every run. With it off
  the server does not open the feedback store at all: it records nothing and serves no
  certified shape or column track record.
- **The store did not change.** We did not empty it first: it held rows from our
  earlier work, and leaving them in place made the test stricter, since any write
  would have changed the counts. The launcher read the row counts of all three store
  tables (`exchange`, `feedback`, `certified_query`) before the first run and after
  every invocation, and they never changed; during the Opus sweep the database's own
  statistics also showed no reads of those tables. Each bundle's
  `memoff_attestation.txt` carries the counts with timestamps.

With nothing carried between tasks or runs, the three runs of each model are
independent samples, and their spread is ordinary run-to-run noise. The agent never
sees gold SQL, results or test cases. The MCP server's version string reads
`3.0-bird-model-memory-22c9afa0`; "model memory" there is a different feature, which
serves business context a semantic model declares in `ai_context` blocks. None of the
22 models declares any, so it has nothing to serve.

**5. The models were built against this public dataset, then cleaned of anything
traceable to its gold.** Our 22 semantic models were generated from each database's
schema, data profile and your knowledge base together with the task questions
(question text, follow-up, the knowledge-base entries each task cites and the
ambiguity terms), and tuned between 2026-08-18 and 09-09 against results on these
tasks, during which gold SQL was read to diagnose failures. On 2026-09-23 we audited
every model for content that traced back to gold — answer values, verdict-shaped
descriptions, masked cut-offs, logic present only in gold — and removed it; the models
in this submission are that cleaned tree (tag `deployed-n3`, which the October runs
used) plus one corrected description of a calculation (`deployed-memoff`, nothing that
changes a query). Nothing in your guidelines prohibits developing against Full, but it
is a real difference from work that develops on Lite, and you should weigh it. The
agent instruction is in the public fork at
`BIRD-Interact-ADK/config/environment_backends.no_gold_930.yaml`, the backend file every
run selected; it includes one line telling the agent not to round in its submitted
query. The branch also carries two unrelated backends (Databricks) added for other
work; neither is selected in these runs.

**6. Grading is yours, unmodified.** Our harness carries six optional comparison
corrections we use for internal A/B work (case-insensitive text, column-order
independence, and others). **All six are off for these runs.** Row comparison is
exact, as in `evaluation/src/eval_bird_interact.py`. The services report
`{"regime":"upstream","corrections":[]}` on their health endpoint and each results
file records it, together with the harness commit it ran.

**7. Costs follow the Universal Cost Scheme.** ask_user 2, submit_sql 3, run_query 1,
and every other action 0.5 or 1.0 by the token rule; each tool's placement was measured
from its real input and output sizes (explore_columns averages about 600 output tokens,
so 0.5). Budget is 6 + 2·ambiguities + 2·patience with patience 3, averaging 17.86 over
the 600 tasks — the same value your board lists.

**8. Failures we are not hiding.** A task the model crashed is scored as a **failure**,
not excluded, so the rates above already carry them. Only genuine infrastructure
errors — a provider outage or 5xx, a timed-out service call — were re-run, never a
task the model itself failed; `error_classes.tsv` in each bundle lists every errored
task, its underlying exception and which class it fell in. Model-caused crashes, all
scored 0:

| Model | Crashes / 1,800 | Cause |
|---|---|---|
| Claude-Opus-4.6 | 0 | — |
| Gemini-3.1-Pro | 0 | — |
| Kimi-2.5 | 19 | 16 tool calls whose arguments were not valid JSON; 3 conversations past the 262k-token context window |
| GPT-5 | 5 | conversations past the 272k-token input limit |

Infrastructure re-runs: Opus 1 task and Gemini 6 tasks whose call to the agent service
timed out, and one Kimi task with no model failure in the agent log.

One task, `museum_artifact_2`, asks for a measure whose engine SQL grows to about
12 GB on the warehouse, enough to get the warehouse's Postgres backend killed. Every
run ran with a watchdog that cancels any engine query on the warehouse running longer
than 60 seconds, so that task errors instead of crashing the warehouse; it is scored
as a fail in every run. The verification package ships the same watchdog.

The raw-arm control runs the lifts in the bundles are measured against were not re-run;
each model's existing raw run (2026-09-15 to 09-18; Gemini 3.1 Pro 10-07) was re-graded
under the current rules.

**9. Why this replaces the October submission.** On 2026-11-08 you told us neither
October option could be listed: the memory reused gold-graded verdicts across tasks
(Option 1, even within run 1) and across runs (Option 2). Every scenario here was re-run
from scratch with the memory off on both sides (§4). We also dropped Claude Sonnet 5
from the submission and added Gemini 3.1 Pro, and moved to the current engine and MCP
builds; the models changed by one description. For the record, the October runs read
Success Rate 44.17 / 47.83 / 49.50 for Opus 4.6, 40.83 / 43.33 / 46.17 for Kimi 2.5 and
43.00 / 47.17 / 47.67 for GPT-5, rising run over run as the memory learned; the memory-off
runs above are flat.

## Files

One bundle per model, `BIRD_leaderboard_submission_AtScale_<Model>_memoff_results_<date>.zip`:

| File | Contents |
|---|---|
| `leaderboard_<model>_<date>_memoff_rep{1,2,3}_merged.jsonl` | **The submission.** 600 rows per run: `instance_id`, both predicted SQL fields, `prompt_flow` (every prompt, response, action, `action_cost`, `remaining_budget`, per-turn token counts), plus `category`, `backend`, `local_verdict` (live), `validated_verdict` (our replay) and any `notes` |
| `*.summary.json` | Per-run totals, category split, the replay (`validated`) block |
| `<model>_run{1,2,3}.json`, `<model>_raw_n1.json` | The harness's full run records, and the re-graded raw-arm control |
| `memoff_attestation.txt` | The memory-off checks: images, `/configz`, harness setting, store row counts after every invocation |
| `RESULTS.md` | The per-run table, lift, the memory-on comparison, errors and every disclosure specific to that sweep |
| `error_classes.tsv` | Every errored task with its exception and class |

`merged` means a run's task set was assembled from one base pass plus re-runs of tasks
that hit infrastructure errors, never of tasks the model itself failed.

Beside the bundles in the shared folder: this file, `VERIFY.md`, the Tier 1
verification assets (Reproducing, below), the models repository zip, and the results
workbook. The white paper we shared in October describes the earlier memory-on runs and
is not part of this submission.

Where your evaluator disagrees with either verdict, yours is correct and we would like
to know.

## Reproducing

The harness is the public fork above, run with `LEADERBOARD_MODE=true`, the single
switch that disables every grading deviation described here, and `FEEDBACK_MEMORY=false`.
The models repository, supplied as a zip, carries a fully self-hosted offline
verification package (`verification/`, `VERIFY.md`, tag `verify-2026-11-memoff`): one
command, everything runs on your machine, nothing contacts AtScale. It has two tiers —
a deterministic replay that re-executes our submitted SQL on your warehouse and
re-grades upstream (no API key needed), and an optional full re-run of the pipeline,
with memory off on both sides and asserted so before and after, against a band
declared in advance. The Tier 1 assets are in the shared folder; the Tier 2 image
bundle (~3 GB) is supplied on request.
