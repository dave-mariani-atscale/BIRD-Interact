# The three-arm SML authoring comparison: method

How the labor (2026-10-05) and ETF (2026-10-06) three-arm comparisons were run so the arms are
apples-to-apples, and what the input sweep added for ETF does. Written 2026-10-15 from
`results/arms_lca/kickoff.md`, `results/arms_etf/kickoff.md`, `results/arms_etf/ARMS.md` and
`results/arms_lca/briefs/sweep/`.

**Short version.** The three arms differ in exactly one thing: the authoring instructions Fable
sees. Inputs, warehouse facts, MCP server, gates, smoke, sweep, benchmark run, task set and agent
model are held identical. The thing added between labor and ETF is the **input sweep**: a
reachability test-and-fix loop run against the deployed model with no grading involved,
bracketed by a pre-sweep and a post-sweep benchmark run so its lift is measured.

## 1. What is held constant

| Control | How |
|---|---|
| Design inputs | Each arm repo gets an identical `brief/`: `task_brief.json` (from `extract_brief.py`, answer-key firewall PASS), `kb.jsonl`, `deleted_ids.txt`, `column_meaning_base.json`, `schema.txt`. Plus one shared `facts.md`. |
| Warehouse metadata | One Sonnet "facts" pass, run once and copied into all three repos: live column types and where Postgres truncates, degenerate columns, `character(n)` columns, unit-suffixed text, JSON keys at every nesting level, join cardinalities and orphans, `corr(stored, recomputed)` for every KB formula the warehouse already stores, candidate column bindings per KB term with live counts. Numbers only, no descriptions, no judgement. On ETF it found 6 live tables absent from `schema.txt`. For the DG arm it also emits `dg_inputs/ddl.sql` (`pg_dump -s -n public`) and `dg_inputs/data_profile.yaml` in the DG skill's own format, with numbers matching `facts.md`. |
| BIRD modeling rules | `packet_<db>.md` (the v12 modeling rules without the build-process sections), checked mechanically by `scripts/b2_packet_check.sh`, bound identically on every arm's Fable call. |
| MCP server | One dedicated server on `:3004` (worktree `mcp-b2-arm` at `be3d547`), separate from the benchmark's `:3003`. Every call goes through `mcp/plans/sml-reference-model-arms/tools/mcp_call.py` with `MCP_CALL_LOG` set, so every call and the bytes of every skill fetch are recorded per arm. |
| LLM tiering | Opus orchestrates, applies mechanical fixes, commits and reports; it never designs objects or writes descriptions. Fable: at most 4 calls per arm on ETF (2 on labor), fresh context each call, with read and write limits. Sonnet: every mechanical step (facts, generate, validate/deploy, smoke, sweep tester, runs, compare). |
| Fence | Every prior model of the database, the other arms' folders, run results, gold keys (`sol_sql`, `test_cases`, `conditions`, ...), grading audits, memory files and `gold_diff.py` are off-limits by path. Every agent ends with an INVENTORY of files opened; a fenced path in an inventory is a reported breach. |
| Gates | `sml-cli validate`, A8 question-leakage gate, A10 masked-threshold gate, run by `scripts/deploy_models_arm.sh` before every publish. |
| Smoke | Identical Sonnet brief per arm: 8+ `run_query` checks for exactness (vs the raw source column on the warehouse), conformance per dimension, and coverage of six question shapes; `validate_mdx_expression` on every calculation; `get_outbound_queries` on window and semi-additive constructs; a fixed discoverability method (one `explore_columns` per question carrying all content words as multi-word terms); folder count via `list_models`; a leak grep over the YAML. |
| Benchmark | Same 15 Query tasks (census-winnable, from `scripts/sweep_questions.py`), backend `atscale_arm_<arm>`, `SYSTEM_AGENT_MODEL` and `USER_SIM_MODEL` both Sonnet 5, `--repeat 1 --concurrency 2`, `GRADING_AUDIT_PATH` per arm, `scripts/gate_run.sh` before each run, one run at a time. |
| Budget | $40 per arm all-in on ETF (build, sweep, orchestration, both runs), with a reserve held back for the post-sweep run. $35 per build on labor. |

## 2. What differs per arm

| | SRV | DG | B2 |
|---|---|---|---|
| Repo / catalog | `diannewood/bird-models-srv` / `bird_models_srv` | `diannewood/bird-models-dg` / `bird_models_dg` | `diannewood/bird-models-b2` / `bird_models_b2` |
| MCP functionality used to generate | `get_sml_skills` to fetch `create-model-workflow`; `explore_datasource` over the `public` tables; `create_sml_model` (`confirmed:false` then `confirmed:true`, FD probe on). Output committed unedited. | **No MCP generate call.** Fable writes `use_case.md` and `build.yaml`, then runs the local `atscale-sml-model-generator` v1.8.0 Claude skill, which emits YAML from DDL, data profile and use case and loops its own `validate_sml.py`. | Same as SRV: `create_sml_model`. |
| Skills Fable refines with | The 12 default served skills (`sml-create-dataset`, `sml-create-dimension`, `sml-create-metric`, `sml-descriptions`, `sml-modeling-guide`, the workflow sub-skills, ...). ETF: 71 KB fetched over 10 calls. | None served. The DG skill's own `SKILL.md` (42 KB) and `references/`. | 6 skills: `create-model-workflow`, `sml-reference-model:core` (a worked example to copy shapes from) and `sml-essentials`, fetched whole in one call. ETF: 37 KB over 5 calls. `:3004` is restarted with a different `ATSCALE_MCP_SKILLS_DIR` before the B2 arm. |
| F1 input packaging | Brief lists paths; 15 tool-call limit, one Write per file. | At most 40 tool calls; writes YAML directly. | `scripts/f1_inputs.py` bundles generator notes, withheld ids, question wordings, KB, column meanings and schema into two files each under 22k tokens. Limits: 3 input Reads, 1 skills call, reads at most 6, Writes at most 25 then `Edit`, no generator scripts. |
| Post-processing | none | Sonnet copies only `datasets/ dimensions/ metrics/ calculations/ models/` into the repo, repoints every `connection_id` to `bird_<db>`, and drops the skill's `catalog.yml`, `connections/`, `context/` and `README.md`. | none |

So apples-to-apples means: same facts, same brief, same rules, same gates, same tester, same
benchmark; only the authoring recipe and the skill text Fable reads change. The MCP server's
`create_sml_model` output is the starting point for SRV and B2 (on ETF: 13 datasets, 30
dimensions, 71 metrics, byte-identical in both repos), and Fable's single F1 refinement is what
turns it into an 11 dataset / 11 dimension / 110+ metric model.

Arm order is SRV, DG, B2, each arm finished (both runs) before the next starts. Engine deploys
restart the engine, so nothing deploys while a run is in progress.

**A fourth arm, CM, is planned** (2026-10-15, runbook `results/arms_etf_cm/kickoff.md`): the
comodel CLI from `AtScaleInc/mcp` `feat/ATSCALE-53937` @ `57aa9e5`, driven by the text of its
plugin command (`comodel init`, `db tables/columns/sample/profile`, the agent writes every YAML,
`comodel --json validate`), post step as DG, same gates, smoke, sweep and 15 tasks. Two deliberate
differences from the table above: the packet is still bound, but **`facts.md`, `dg_inputs/` and
every authoring skill are withheld**, because the CLI's own input pipeline is the thing being
measured and the plugin ships with no skill. Repo `diannewood/bird-models-cm`, catalog
`bird_models_cm`, model `Exchange Traded Funds CM`, backend `atscale_arm_cm`.

## 3. Size of the instruction set per arm

**Net.** B2 is about half of SRV and a third of DG by bytes available, and almost all of B2 is
the worked example. SRV spends its bytes on prose rules split across eight skills; DG is the only
arm that ships the SML spec and an MDX function reference, and it loads a 42 KB `SKILL.md` whole
where SRV and B2 open with 7 KB and 5 KB and fetch the rest on demand.

Measured 2026-10-15 on the three sources the arms read: SRV = `mcp` `.agents/skills` at `be3d547`
(the `:3004` server's default set); DG = `~/.claude/skills/atscale-sml-model-generator` v1.8.0; B2 =
`mcp/plans/sml-reference-model-arms/arms/B2-example-guided/skills` (the `ATSCALE_MCP_SKILLS_DIR` the
`:3004` server is restarted with). Bytes on disk, not tokens.

| | SRV | DG | B2 |
|---|---|---|---|
| files | 62 | 103 | 25 |
| all bytes | 277,820 | 486,722 | 147,244 |
| authoring guidance only (no query skill, validate, deploy, meta) | 215,702 | ~339,000 | 94,786 |

By kind:

| kind | SRV | DG | B2 |
|---|---|---|---|
| entry page loaded first | `create-model-workflow` 7,106 (+ 3 refs = 23,751) | `SKILL.md` 41,727 | `create-model-workflow` 4,985 |
| prose rules | ~100,000: `sml-create-dataset`, `-dimension`, `-metric`, `sml-descriptions`, `sml-geography-dimension`, `sml-modeling-guide`, `sml-model-memory` | 96,627: `rules.md` 68,280, `grounding.md`, `build-config.md`, `data-profile.md`, `reference-models.md` | 8,155: `sml-essentials` (9 rules) |
| worked example | 69,790: `sml-reference-model` (TPC-DS, YAML inlined in 10 md refs) | 83,398: `references/internet-sales/` (60 raw YAML files + README) | 81,646: same `sml-reference-model` plus `core.md` 15,121 |
| spec and language docs | 0 | 164,532: `sml-spec/` 115,442 + `mdx-reference/` 49,090 | 0 |
| validate and deploy | 10,153 (`sml-validate`, `deploy-sml-model`) | `scripts/validate_sml.py` 58,945 (code, run not read) | 10,153 (same files) |
| query skill (smoke only) | 42,305 (`query-semantic-layer`) | 0 | 42,305 (same files) |
| meta | 9,660 (README, ENFORCEMENT, SKILL-TEMPLATE, PROMPT-SCHEMAS) | 41,493 (README, CHANGELOG, NOTICE, LICENSE) | 0 |

Within the shared files, `deploy-sml-model`, `query-semantic-layer` and `sml-validate` are
byte-identical between SRV and B2. Only `create-model-workflow` differs: SRV's routes every write
to a `sml-create-*` sub-skill and three reference pages; B2's routes every write to
`sml-reference-model:core` plus `sml-essentials` and has no references.

Available is not read. On ETF (section 2, and the "Skill bytes fetched" table in
`results/arms_etf/ARMS.md`) SRV's F1 fetched 71 KB over 10 calls, B2's 37 KB over 5. DG's per-file
reads were not recorded, and its 68 KB `rules.md` was not read at all (Read size cap), so DG
ran on `SKILL.md` plus whichever references fit.

Outside the skills, SRV and B2 also lean on the MCP server's `explore_datasource` and the
deterministic `create_sml_model` generator (17 Python files, 408 KB at `be3d547`), which produce
the skeleton the agent refines. DG has no server dependency: it writes every YAML from DDL and the
data profile and validates with its own script.

## 4. The phase added for ETF: the input sweep

Labor was one-pass: generate, F1, validate and deploy, smoke, optional defect-only F2, freeze, one
run. ETF inserts a measured optimization loop between the one-pass model and the final run. It is
explicitly **not reward-driven**: the sweep never sees gold, grading audits, verdicts or run
results. The benchmark runs only bracket it.

1. **Pre-sweep freeze and run.** Commit, tag `etf-<arm>-presweep`, push, then run the 15 tasks
   once. This is the one-pass score, comparable to the labor arms. Opus reads only the reward line
   and `llm_usage` until the compare phase.
2. **Sweep round N (Sonnet tester, fresh context).** The tester sees only the 15 `amb_user_query`
   wordings and the query tools: `list_models`, `explore_columns`, `focus_columns`, `run_query`,
   `get_outbound_queries`. Per question: one `explore_columns` with every content word as
   multi-word terms, `focus_columns` on the chosen objects, one `run_query` with bare object
   names, one retry on an SQL error, a dispatched-SQL fidelity check, and a one-line result shape
   with no numeric values. It logs one row per question with a class guess:
   - OK: first search surfaced the intended objects, one reading, query ran.
   - MISS: the question's words surfaced nothing or the wrong object (vocabulary gap).
   - FORK: two or more published objects fit; picked without evidence (unsettled reading).
   - ASSEMBLY: rebuilt a KB-named concept from parts (missing named object).
   - LABEL: right object, member values differ from the KB's words.
   - ENGINE: dispatched SQL dropped, inverted or re-grained a written clause.
   - GAP: needs a value or definition the inputs withhold.
3. **Fixer F<N+1> (Fable, one call).** Re-classifies every row from the trajectory, applies the
   fix table cross-cutting first: MISS gets the KB's wording in the description; FORK gets a closed
   single-axis ask leading the description of the object the tester opens first, or readings
   published side by side; ASSEMBLY gets a named metric; LABEL gets KB words in CASE literals; GAP
   gets the inputs published plus an "ask for the full definition" sentence; ENGINE gets a note
   only. Every `changes:` line names class, question ids, file, and a motive that must be a KB
   entry or a trajectory fact, never a result value. Example from the SRV F2: threshold-shaped
   counts sitting beside withheld verdict names were removed because the tester had read a cutoff
   off the description.
4. **Validate, A8 and A10 gates, deploy, re-smoke what the fixer touched.**
5. **Continuation test before F3 and before F4** (Opus, written into `sweep_<arm>.md` each time
   with its numbers). Continue only if all hold: (a) the last round raised the OK count; (b) the
   last round still has MISS, FORK, ASSEMBLY or LABEL rows the fix table can address (GAP and
   ENGINE do not count); (c) remaining arm budget minus the post-run reserve covers one more round
   plus one fixer at the last measured cost. Stop at the first failure, at Fable call 4, or at the
   stall rule (no row changed class).
6. **Freeze and post-sweep run.** Commit `<ARM> freeze`, push, record the SHA, run the same 15
   tasks on the same instrument.

## 5. What the ETF sweep showed

| arm | pre reward (P1/P2 of 15) | post reward (P1/P2) | sweep lift | rounds, fixers | OK count by round |
|---|---|---|---|---|---|
| SRV | 0.513 (8/7) | 0.653 (11/7) | +14.0 pp | 2, F2 | 5, 5 |
| DG | 0.493 (8/6) | 0.673 (11/8) | +18.0 pp | 3, F2+F3 | 2, 3, 2 |
| B2 | 0.673 (11/8) | 0.693 (11/9) | +2.0 pp | 2, F2 | 3, 3 |
| raw | 0.560 (9/7) | | | | |

All three sweeps stopped on test (a), the OK count flat or down, after one or two fixers. The
benchmark still moved, P1-driven, on the two arms that started low. The sweep's own OK count did
not predict the lift. Post-sweep the arms tied (same P1 11/15; P2 gaps of 1 to 2 tasks, which is
noise at n=1), all above raw by 9 to 13 pp. No authoring approach separated at n=1 on 15 tasks.
## 6. Cost per arm, and how much of it was the benchmark

From the Cost and time table in `results/arms_etf/ARMS.md`. Run $ is `llm_usage.cost_usd` from each
run's results JSON; build, sweep and orchestration $ is the session delta (Opus plus subagents at
list price) between the arm's start and freeze timestamps.

| arm | all-in | benchmark runs (pre + post) | share | build + sweep + orchestration |
|---|---|---|---|---|
| SRV | $24.45 | $3.35 + $3.94 = $7.29 | 30% | $17.16 |
| DG | $31.05 | $3.80 + $3.48 = $7.28 | 23% | $23.77 |
| B2 | $34.11 | $3.69 + $3.84 = $7.54 | 22% | $26.57 |

Each 15-task run cost $3.23 to $3.94, about $0.24 per task, with prompt caching on. The raw
reference run ($3.23) and the two extra B2 pre-sweep repeats ($3.84, $3.59) sit outside the arm
caps. Session totals: $25.34 of benchmark API spend over 7 runs, $71.45 of Opus plus subagents.
The single B2 F1 Fable call was $15.45, which is why B2 is the most expensive arm despite the
smallest sweep.

## 7. Wall time per phase

From `results/arms_etf/timestamps.md` (one session, 2026-10-06 09:46 to 15:04, 5h18m end to end).
Arms ran strictly in sequence. Within an arm the pre-sweep run and sweep round 1 overlapped: the
run was launched at the pre-sweep freeze and the tester started at the same moment, so the sweep
column does not add to the run column.

| phase | SRV | DG | B2 |
|---|---|---|---|
| generate (`create_sml_model`; DG: Fable runs the generator skill) | 2m | 19m | 2m |
| design F1 (Fable) | 32m | (in generate) | 32m |
| validate + first deploy | 3m | 3m | 3m |
| smoke | 19m | 15m | 9m |
| **build, start to pre-sweep freeze** | **56m** | **37m** | **46m** |
| pre-sweep run (15 tasks, concurrency 2) | 20m | 23m | 14m |
| sweep round 1 | 8m | 10m | 6m |
| fixer F2 (Fable) | 10m | 11m | 13m |
| F2 deploy + re-smoke | 8m | 4m | 2m |
| sweep round 2 | 3m | 8m | 8m |
| fixer F3 + deploy + round 3 | | 13m | |
| **sweep, pre-sweep freeze to freeze** | **30m** | **47m** | **29m** |
| post-sweep run | 23m | 12m | 14m |
| **arm total** | **1h49m** | **1h36m** | **1h29m** |

Shared steps outside the arms: facts pass 10m, raw reference run 11m, compare 4m, close 1m.

Caveats: the F1 and generate figures are the Fable call's wall time including its skill fetches
and YAML writes; smoke and sweep figures are Sonnet subagent wall time. Run wall times are not
comparable across arms: three other catalogs were undeployed from the shared engine at about
13:00, after which per-task time roughly halved (DG pre 173 s/task, DG post 89 s/task).
