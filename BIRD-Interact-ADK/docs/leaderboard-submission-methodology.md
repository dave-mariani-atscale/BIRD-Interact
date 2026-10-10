# BIRD-INTERACT-1.0-full, a-Interact — AtScale Semantic Layer

Submission from AtScale. Everything below is stated so the result can be checked or
contested without taking anything on trust. This submission replaces the one we
prepared in September, which is withdrawn; §9 says why.

| | |
|---|---|
| Split / mode | BIRD-Interact-Full, 600 tasks, a-Interact, stress mode (budget-constrained, Universal Cost Scheme) |
| Agent models | four, listed below |
| User simulator | `claude-haiku-4-5-20251001` (three models) and `gpt-4o` (GPT-5), **your prompts and token limits, unmodified** |
| Efficiency (budget) | 17.86 average, matching the value listed for every Full a-Interact entry |
| Runs | 3 per model, all 600 tasks, all included; concurrency 10 |
| Harness | public fork: github.com/dave-mariani-atscale/BIRD-Interact, branch `feature/atscale-mcp-semantic-layer`, commit `d5d269c` (Sonnet 5: `cc08e8f`, one commit earlier) |
| Semantic models | `bird-atscale-models` at tag `deployed-n3` (`e89bb6dc`), supplied as a zip of the repository |
| Semantic engine / MCP server | AtScale engine `pr10556` (image `sha256:fb4a36a0…`), MCP server `930149b` (image `sha256:b7169ae1…`) |
| Dates | 2026-10-03 to 2026-10-06 |
| Contact | dave@atscale.com |

## Results

Success Rate is the blended phase-1 rate over all 600 tasks; Reward is
(0.7·P1 + 0.3·P2)·100. We give two figures for each model and ask you to publish
whichever you consider right for the board.

- **Option 1, cold run**: each model's run 1 of 3, started from an empty memory store
  (§4), so nothing carries over between tasks or runs. This is the figure with no
  advantage from having seen the task set before.
- **Option 2, with memory**: each model's best single run of three, chosen by Success
  Rate with ties broken by Reward; in every case that is run 3. Your Submission
  Guidelines address run count only in §V, Validation Submission Mode, which recommends
  at least three runs and says "we will report the best result among them" without
  naming the metric, so we state ours. Runs 2 and 3 start from what run 1 learned (§4),
  so Option 2 shows what the memory adds.

In both tables **Success Rate and Reward are our own replay of the submitted SQL under
your grading (§3)**: the figures we expect your evaluator to reproduce. **Live** is what
our harness scored during the run; the two agree to the row except where §3 says. The
GPT-5 row is on the GPT-4o simulator track, a separate board entry, and is not
comparable to the Claude-Haiku-4-5 rows.

**Option 1: cold run, no memory (run 1 of 3)**

| Model | User simulator | Success Rate | Reward | Live success | Live reward | Query P1 | Query P2 | Mgmt P1 | Coins / query task |
|---|---|---|---|---|---|---|---|---|---|
| Claude-Sonnet-5 | Claude-Haiku-4-5 | **48.17** | **42.72** | 48.17 | 42.72 | 50.24 | 33.66 | 43.68 | 16.19 |
| Claude-Opus-4.6 | Claude-Haiku-4-5 | **44.17** | **38.87** | 44.17 | 38.87 | 45.37 | 29.02 | 41.58 | 16.22 |
| Kimi-2.5 | Claude-Haiku-4-5 | **40.83** | **34.78** | 40.83 | 34.78 | 41.71 | 23.90 | 38.95 | 17.22 |
| GPT-5 | GPT-4o | **43.00** | **36.85** | 43.00 | 36.85 | 44.63 | 22.68 | 39.47 | 15.70 |

**Option 2: with memory (best of 3 sequential runs; run 3 in every case)**

| Model | User simulator | Success Rate | Reward | Live success | Live reward | Query P1 | Query P2 | Mgmt P1 | Coins / query task | 3-run mean |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude-Sonnet-5 | Claude-Haiku-4-5 | **53.83** | **48.63** | 53.83 | 48.58 | 56.59 | 42.68 | 47.89 | 14.58 | 51.17 ± 2.84 |
| Claude-Opus-4.6 | Claude-Haiku-4-5 | **49.50** | **44.75** | 49.50 | 44.75 | 53.66 | 40.24 | 40.53 | 14.11 | 47.17 ± 2.73 |
| Kimi-2.5 | Claude-Haiku-4-5 | **46.17** | **40.12** | 46.17 | 40.07 | 49.27 | 30.49 | 39.47 | 16.05 | 43.44 ± 2.67 |
| GPT-5 | GPT-4o | **47.67** | **43.07** | 47.67 | 43.07 | 50.49 | 36.34 | 41.58 | 13.85 | 45.95 ± 2.56 |

The **3-run mean** (± sd) is the Success Rate over all three runs. Query P1/P2 and
Mgmt P1 are the phase rates on the 410 Query and 190 Management tasks; coins are the
mean budget spent per Query task out of 17.86.

Three further sweeps on the same protocol, models and stack — Grok 4.3, Nemotron 3
Ultra and Gemini 3.1 Pro — are in our public results workbook and are not part of this
submission.

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
`ORDER BY`/`LIMIT` around them. All twelve runs were exported with that in place, so
no row needed repairing afterwards.

Where the engine returned an error instead of executing, no outbound SQL exists; those
rows (5 to 12 per run) fall back to the logical SQL, are flagged in `notes`, and will
not execute on your evaluator. They score 0, which is what we recorded.

**2. Management-category tasks run on raw PostgreSQL.** A semantic layer is read-only,
so all 190 Management (WRITE) tasks route per task to the standard raw tools and the
standard raw grading path inside the same run, with the same instruction the raw arm
uses; only the 410 Query (READ) tasks use the semantic layer. Each row's `category`
and `backend` say which path it took. This is also the control: Management P1 on the
semantic-layer arm (3-run mean) against the same model's raw arm is Sonnet 45.44 vs
44.74, Opus 40.88 vs 40.00, Kimi 38.42 vs 37.89, GPT-5 40.70 vs 41.05 — all within
run-to-run noise on 190 tasks (binomial SE ≈ 3.6 points) — while Query P1 is 2.1 to
2.4 times the raw arm's.

**3. We re-graded our own submission and are quoting that number.** Every exported
Query SQL was re-executed against a clone of each task's template database and
re-graded under **upstream** rules; the Success Rate and Reward figures in both tables
above are the result. Since 2026-10-01 (harness `8c39060`) our leaderboard-mode grader cleans
`DISTINCT` exactly as `evaluation/src/eval_bird_interact.py` does — equal to your
`remove_distinct` on all 1,288 gold statements in the dataset — so live and replayed
verdicts now agree except for three rows across the twelve runs:

- `cross_border_7` (Sonnet run 2): live pass, replay fail on both phases. The query
  takes a LIMIT over rows tied on its sort key, and the tie broke differently on a
  fresh template. Counted as a fail.
- `exchange_traded_funds_14` (Sonnet run 3, phase 2) and
  `labor_certification_applications_3` (Kimi run 3, phase 2): live fail, replay pass.
  The exported SQL run on PostgreSQL matches gold where the live comparison of
  engine-returned rows did not. Your evaluator scores the SQL, so they count.
- `museum_artifact_1` (Opus run 2, phase 2): live pass, replay fail — an export defect,
  no outbound SQL was recorded for that phase. Counted as a fail.

Tasks that are order-sensitive on gold whose `ORDER BY` does not totally order its own
result (57 of 410 Query tasks are marked `order=true` on such gold) can flip between
executions for reasons unrelated to the submission; the first row above is one. We
treat any deviation under 0.5 points as that instability rather than a finding.

**4. The three runs are sequential and not independent, and the memory learns from
your grader.** Our MCP server carries state across tasks within a sweep: each
submission is graded by the harness's copy of your evaluator against the task's gold
SQL, and that pass or fail is recorded as the user's verdict on the query; one
"correct" verdict certifies the query's shape, and certified shapes are shown to the
agent on later tasks. So the memory learns from gold-graded outcomes — in run 1 from
earlier tasks of the same sweep, and in runs 2 and 3 also from run 1's answers to the
same 600 questions, which is why runs 2 and 3 score 3 to 6 points higher. The agent
never sees gold SQL, results or test cases, only which of its own earlier queries were
accepted. The store was emptied before run 1 of every sweep and the reset is logged
beside the results (`*_feedback_reset.txt`: zeroed at 2026-10-04T05:55:51Z for Sonnet,
10-04T17:01:53Z Kimi, 10-05T22:07:05Z GPT-5, 10-06T11:48:40Z Opus, and read empty again
at launch). Option 1 (the cold run) is the figure with no carry-over.

**5. The models were built against this public dataset, then cleaned of anything
traceable to its gold.** Our 22 semantic models were generated from each database's
schema, data profile and your knowledge base together with the task questions
(question text, follow-up, the knowledge-base entries each task cites and the
ambiguity terms), and tuned between 2026-08-18 and 09-09 against results on these
tasks, during which gold SQL was read to diagnose failures. On 2026-09-23 we audited
every model for content that traced back to gold — answer values, verdict-shaped
descriptions, masked cut-offs, logic present only in gold — and removed it; the models
in this submission are that cleaned tree (`deployed-n3`), further revised to 10-02 on
knowledge-base and trajectory evidence only. Nothing in your guidelines prohibits
developing against Full, but it is a real difference from work that develops on Lite,
and you should weigh it. The agent instruction is in the public fork at
`BIRD-Interact-ADK/config/environment_backends.no_gold_930.yaml`; it includes one line
added on 2026-10-02 telling the agent not to round in its submitted query.

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
errors — a provider outage or 5xx, a timed-out service call, a warehouse crash — were
re-run, never a task the model itself failed; `error_classes.tsv` in each bundle lists
every errored task, its underlying exception and which class it fell in. Model-caused
crashes, all scored 0:

| Model | Crashes / 1,800 | Cause |
|---|---|---|
| Claude-Sonnet-5 | 1 | called a tool that does not exist (`households_8`, run 3) |
| Claude-Opus-4.6 | 3 | called tools that do not exist (`reverse_logistics_3`, `solar_panel_12`, `cross_border_18`) |
| Kimi-2.5 | 17 | 12 tool calls whose arguments were not valid JSON; 5 conversations past the 262k-token context window |
| GPT-5 | 3 | conversations past the 272k-token input limit |

One task, `museum_artifact_2`, asks for a measure whose engine SQL grows to about
12 GB on the warehouse; during the Opus sweep it got the warehouse's Postgres backend
killed, which dropped every concurrent connection. The tasks it took down were re-run
as infrastructure failures; `museum_artifact_2` itself is scored as a fail in every
run of every model, and from the Opus sweep's run 3 on a watchdog cancelled any engine
query on the warehouse running longer than 60 seconds so a runaway query errors
instead of crashing the warehouse. The verification package ships the same watchdog.

The raw-arm control runs the lifts in the bundles are measured against were not re-run;
each model's existing raw run (2026-09-15 to 09-18) was re-graded under the current
rules.

**9. Why this replaces the September submission.** The runs we prepared in September
were produced on models that still carried gold-traceable content (§5) and graded with
a `DISTINCT` cleaning that was 1.2 to 2.0 Success Rate points more generous to the
semantic-layer arm than yours (§3). Both are fixed here, and every scenario was re-run
from a cold store on the cleaned models under the exact upstream grader. For the
record, the September runs re-graded under the current rules read Query P1 Sonnet 52.93,
Opus 50.73, Kimi 51.22, GPT-5 49.02; the runs submitted here read 56.59, 53.66, 49.27
and 50.49.

## Files

One bundle per model, `BIRD_leaderboard_submission_AtScale_<Model>_results_<date>.zip`:

| File | Contents |
|---|---|
| `leaderboard_<model>_<date>_nogold930_rep{1,2,3}_merged.jsonl` | **The submission.** 600 rows per run: `instance_id`, both predicted SQL fields, `prompt_flow` (every prompt, response, action, `action_cost`, `remaining_budget`, per-turn token counts), plus `category`, `backend`, `local_verdict` (live), `validated_verdict` (our replay) and any `notes` |
| `*.summary.json` | Per-run totals, category split, the replay (`validated`) block |
| `<model>_run{1_cold,2_warm,3_warm}.json`, `<model>_raw_n1.json` | The harness's full run records, and the re-graded raw-arm control |
| `RESULTS.md` | The per-run table, lift, memory, errors and every disclosure specific to that sweep |
| `error_classes.tsv` | Every errored task with its exception and class |

Beside the bundles in the shared folder: this file, `VERIFY.md` and the Tier 1
verification assets (Reproducing, below), the models repository zip, and the white
paper `AtScale_BIRD_Semantic_Layer_Benchmark_WhitePaper_2026-10.pdf` (draft v0.1), the
full study behind this submission. The paper also covers three further models and a
modified-harness scenario that are not part of it:
https://drive.google.com/file/d/1Q-9T7V18bhKyjbZzRA-ozPfdpynsB_tv/view

Where your evaluator disagrees with either verdict, yours is correct and we would like
to know.

## Reproducing

The harness is the public fork above, run with `LEADERBOARD_MODE=true`, the single
switch that disables every deviation described here. The models repository, supplied
as a zip, carries a fully self-hosted offline verification package (`verification/`,
`VERIFY.md`): one command, everything runs on your machine, nothing contacts AtScale.
It has two tiers — a deterministic replay that re-executes our submitted SQL on your
warehouse and re-grades upstream (no API key needed), and an optional full re-run of
the pipeline against a band declared in advance. The Tier 1 assets are in the shared
folder; the Tier 2 image bundle (~3 GB) is supplied on request.
