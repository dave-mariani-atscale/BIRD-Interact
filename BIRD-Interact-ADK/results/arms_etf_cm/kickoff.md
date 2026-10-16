Run the **comodel arm** on BIRD database **exchange_traded_funds** as a fourth arm of the 2026-10-06 three-arm comparison (`results/arms_etf/`), end to end, unattended, in a fresh **Opus** session. Build one SML model with the `comodel` CLI the way its plugin ships it, score the one-pass model (n=1, the same 15 Query tasks), tune it with the input sweep while the budget and the evidence justify it, score it again, and compare against the three ETF arms and raw as recorded in `results/arms_etf/ARMS.md`. Nobody is watching: never ask a question; on a blocker, write `results/arms_etf_cm/HANDOFF.md` (what is done, what is blocked, the exact next command) and stop.

This follows `results/arms_etf/kickoff.md` (the ETF kickoff) for one arm. Read that kickoff fully; everything stated here overrides it. Written 2026-10-15.

## WHAT IS BEING TESTED

One variable: the authoring approach. The approach under test is **CoModel as shipped on `AtScaleInc/mcp` branch `feat/ATSCALE-53937` at commit `57aa9e5`**: the `comodel` CLI plus the text of its Claude Code plugin (`plugins/atscale-comodel/commands/comodel.md` and `claude-md-snippet.md`). Nothing else from that branch. Three decisions, recorded here so the result is interpretable:

1. **The packet is bound, as for every arm.** `results/arms_etf/packet_etf.md` is the benchmark's rules of engagement (answer-key firewall, allowed sources, A8/A10 gates, BIRD naming), not part of any authoring approach. Every arm had it. Without it a gate failure says nothing about comodel.
2. **`facts.md` and `dg_inputs/` are withheld.** They are the warehouse knowledge that `comodel db columns`, `db sample` and `db profile` are supposed to supply. The ETF arms all read `facts.md`; this arm reads only what the CLI gives it. This is the one deliberate difference, and it is what the arm measures: comodel's own input pipeline.
3. **No authoring skill.** The plugin's `skills/` folder is empty and its command never invokes one, so the agent gets no `atscale-sml-model-generator`, no served `sml-*` skills, no `sml-essentials`. The branch's `build.yaml` and `db profile` are written for "the build-model skill" (the DG skill), but nothing wires it in, so as shipped there is none. The DG arm already measures that skill's authoring with rich inputs.

What the arm therefore answers: given the same database, rules and benchmark, does Claude with the comodel CLI alone build a model that scores like the three arms (ETF one-pass: SRV 0.513, DG 0.493, B2 0.673; post-sweep 0.653 / 0.673 / 0.693; raw 0.560)?

Pre-registered follow-ups, run only after this arm is frozen and scored, each as its own arm folder, and only if this arm's one-pass reward is below DG's 0.493 by more than 2 tasks:
- **CM+DG**: the same, plus the `atscale-sml-model-generator` v1.8.0 skill readable by the build agent (the branch's intended "build-model skill"). Separates "no skill" from "thin inputs".
- **CM+facts**: the same as this arm, plus `facts.md`. Separates "thin inputs" from everything else. Run second, only if CM+DG is also low.

Not a follow-up: Canary. The branch's optimization loop is Canary, which needs golden SQL; this arm uses the input sweep so its optimization is comparable to the three arms. Say so in `ARMS.md`.

| Arm | Approach | Repo / catalog | Model name (unique_name AND label) | Backend |
|---|---|---|---|---|
| **CM** | Fable runs the comodel plugin command with the `comodel` CLI; no skills; no `facts.md` | `diannewood/bird-models-cm` / `bird_models_cm` | `Exchange Traded Funds CM` | `atscale_arm_cm` |

## READ FIRST, FULLY

`CLAUDE.md`, `results/arms_etf/kickoff.md`, then this file. Read `results/arms_etf/packet_etf.md` by section only (subagents read it whole). Read `results/arms_etf/ARMS.md` only in Phase C. Do NOT read `docs/create_bird_model_prompt.v12.md`, `docs/bird-database-testing-prompt.md`, `results/kickoff_b2_arm.md`, `docs/three-arm-comparison-method.md` beyond §2, or anything in `~/.claude/plans/`.

## FENCE (Phases 0-2)

The ETF kickoff's FENCE applies in full, with these changes. Paste the full list into every brief:
- Add to the fenced model folders: `~/go/src/github.com/diannewood/bird-models-{srv,dg,b2}/` entirely.
- Add: `results/arms_etf/facts.md`, `results/arms_etf/dg_inputs/`, `results/arms_etf/dg_output/`, `results/arms_etf/f1_inputs_b2/`, `results/arms_etf/generate_output_*.md`, `results/arms_etf/ARMS.md`, `results/arms_etf/smoke_*.md`, `results/arms_etf/sweep_*.md`, `results/arms_etf/validate_*.md`, `results/arms_etf/run_*.json`, `results/arms_etf/grading_audit_*`. The ETF arms' models and their build evidence are not design input for this arm.
- Add: `~/.claude/skills/atscale-sml-model-generator/`, `.agents/skills/` in any checkout, `~/go/src/github.com/AtScaleInc/mcp/plans/`, and the `:3004` `get_sml_skills` tool. The build agent gets no authoring skill (decision 3). The smoke and sweep testers may still fetch `query-semantic-layer:calculations` as the ETF briefs say.
- Readable by the build agent, and only by it: the comodel checkout's `plugins/atscale-comodel/commands/comodel.md` and `claude-md-snippet.md`, `docs/comodel/cli-spec.md` and `docs/comodel/output-rules.md` (the CLI's own documentation, which a user would have). Not its `src/`, not its tests.
- `results/arms_etf/briefs/`, `results/arms_etf/packet_etf.md`, `results/arms_etf/packet_check.txt` and `results/arms_lca/briefs/sweep/` are readable as the ETF kickoff says.

Every agent, and this session, ends with an INVENTORY: every file it opened, one path per line. A fence path in an inventory is a breach. Report it in `ARMS.md`; do not hide it.

## INPUTS

In the arm repo at `exchange_traded_funds/brief/`: `task_brief.json`, `kb.jsonl`, `deleted_ids.txt`, `column_meaning_base.json`, `schema.txt`, copied from the B2 arm repo's `exchange_traded_funds/brief/` (identical bytes; verify with `cmp`). NO `facts.md`. The live warehouse is reached only through `comodel db …` (the engine connection `bird_exchange_traded_funds`, database `exchange_traded_funds`, schema `public`, 21 tables). The build agent gets no Postgres password and no `psql`.

## ENVIRONMENT

As the ETF kickoff (`:3004` worktree `mcp-b2-arm` at `be3d547` for smoke, sweep and the deploy check; helper `mcp_call.py`; `MCP_CALL_LOG`), with every `results/arms_etf/` output path becoming `results/arms_etf_cm/`, plus the comodel tool:

- **comodel checkout**: `git -C ~/go/src/github.com/AtScaleInc/mcp worktree add ../mcp-comodel 57aa9e5` (detached, pinned). Install: `uv tool install ~/go/src/github.com/AtScaleInc/mcp-comodel`, then `comodel --version` must print a version. Record the commit and version in `ARMS.md`. If `uv tool install` fails, HANDOFF.
- **comodel config** `~/.comodel/config.toml`, written by Opus with the secret copied by `grep '^ATSCALE_MCP_ENGINE_KEYCLOAK_CLIENT_SECRET=' ~/go/src/github.com/AtScaleInc/mcp-b2-arm/.env | cut -d= -f2-` (never `source`, never print it, never paste it into a brief or a log):
  ```toml
  [engine]
  url = "http://localhost/engine"
  [auth]
  url = "http://localhost/auth/realms/atscale"
  client_id = "atscale-mcp-engine"
  client_secret = "<from the .env>"
  ```
  Then `comodel --json doctor` from any folder. It must exit 0 with `5 of 5 checks passed` (git, sml-cli, engine, login, warehouse). On exit 2: try `client_id = "atscale-mcp"` with `ATSCALE_MCP_KEYCLOAK_CLIENT_SECRET` once; if still 2, HANDOFF with the doctor output. Save the passing doctor JSON to `results/arms_etf_cm/doctor.json`.
- **Build project** (scratch, outside the arm repo, like the DG arm's `dg_output/`): `results/arms_etf_cm/cm_project/`, created by the build agent with `comodel init` (step 1). It is where `comodel validate` runs. The arm repo receives only the SML object folders (step 2), exactly as the DG post step did, so `deploy_models_arm.sh`, the A8/A10 gates, smoke and the runs are identical to the other arms.
- **Deploy**: `scripts/deploy_models_arm.sh cm "Exchange Traded Funds CM"`. The script takes any arm string (its usage text says `srv|dg|b2`; it does not check), looks for `~/go/src/github.com/diannewood/bird-models-cm` and catalog `bird_models_cm`.

## Phase 0. setup (Opus, $0, before `cm start`)

1. `mkdir -p results/arms_etf_cm/briefs`. Copy `results/arms_etf/briefs/smoke_brief.md` and `sweep_brief.md` to `results/arms_etf_cm/briefs/` with `results/arms_etf/` → `results/arms_etf_cm/` for log paths only (the question file stays `results/arms_etf/briefs/questions.txt`), and the fence block replaced by this file's FENCE. Fill ARM=cm, ARMU=CM, MODEL="Exchange Traded Funds CM", ROUND at launch.
2. Arm repo: `gh repo create diannewood/bird-models-cm --private --clone` into `~/go/src/github.com/diannewood/bird-models-cm`. Root `catalog.yml`: the B2 repo's root `catalog.yml` with `unique_name: bird_models_cm`, `label: BIRD Models (CM builds)`, and a description saying "built with the comodel CLI (AtScaleInc/mcp feat/ATSCALE-53937 @ 57aa9e5) and its plugin command, no authoring skills, no facts.md, to compare that approach against the SRV, DG and B2 arms on the same BIRD inputs and rules". `README.md` one paragraph. `exchange_traded_funds/{brief,connections}`: the five brief files `cmp`-identical to B2's; `connections/bird_exchange_traded_funds.yml` byte-identical to B2's. Commit `CM setup: brief + connection`, push. `cmp` every brief file against B2's and paste the five OK lines into `ARMS.md`.
3. Packet check: `scripts/b2_packet_check.sh results/arms_etf/packet_etf.md`; paste its OK lines into `ARMS.md`. Any DIFF = stop. The packet is reused unchanged.
4. Backend: add `atscale_arm_cm` to `config/environment_backends.yaml` as a copy of `atscale_arm_b2` with only the ETF domain, `schema: bird_models_cm`, `table: Exchange Traded Funds CM`. Then `scripts/start_services.sh`.
5. comodel install, config and doctor, as ENVIRONMENT. `uv tool list` and `comodel --version` lines into `ARMS.md`.
6. `results/llm_usage.jsonl` line count into `ARMS.md`. `results/arms_etf_cm/timestamps.md` with the ETF labels, arm `cm`.

## MODEL TIERS

**Opus** this session (briefs, mechanical fixes, commits, reports; never designs objects or writes descriptions). **Fable** at most **4 calls**: the build (call 1, with one continuation allowed as call 2 if it stops on its tool-call cap with the project not yet validating), F2 (smoke defects AND sweep round-1 classes), and one sweep fixer F3 only when the continuation test passes; if the build used two calls, F3 is the last. **Sonnet** every mechanical step, including the post step, smoke and sweep testers. Briefs list PATHS, never pasted content. Reports ≤ 20 lines plus INVENTORY.

## BUDGET

**$40 all-in** for the arm: build, post, smoke, sweep rounds and fixers, Opus orchestration, and both runs. Phase 0 and Phase C are outside the cap. Session hard stop **$60**. Reserve, continuation test and the cap rule as the ETF kickoff. Expect the build call to be the expensive step: it makes 40 to 80 `comodel` calls and writes 50 or more files, so plan $15 to $20 for it (the B2 F1 was $15.45 with 15 calls).

## STEPS

**1. build (Fable, call 1 of 4, ≤ 120 tool calls).** The brief gives paths only:
- the plugin command text `~/go/src/github.com/AtScaleInc/mcp-comodel/plugins/atscale-comodel/commands/comodel.md` and `claude-md-snippet.md`: "follow these as if you were invoked by `/atscale-comodel:comodel` with the request below"; `docs/comodel/cli-spec.md` and `output-rules.md` as the CLI's manual;
- the request: "Build the semantic model `Exchange Traded Funds CM` for the `exchange_traded_funds` database (schema `public`, connection `bird_exchange_traded_funds`) under the packet's rules";
- the packet `results/arms_etf/packet_etf.md` (whole), the five `brief/` files in the arm repo, and the question wordings rule from the ETF F1 brief ("read `amb_user_query` for vocabulary and coverage; never copy one into a description");
- the project folder: `comodel init results/arms_etf_cm/cm_project --schema public --connection bird_exchange_traded_funds --database exchange_traded_funds --name bird_models_cm`, then work inside it; the model file's `unique_name` and `label` are `Exchange Traded Funds CM`;
- tools: Bash restricted to `comodel …`, `ls`, `cat`, `wc`; Read/Write/Edit inside `results/arms_etf_cm/cm_project/` and the brief; nothing else. No `psql`, no helper, no `get_sml_skills`, no Skill tool, no WebFetch;
- the stop rule from the plugin: when `comodel --json validate` exits 0, stop and report; never commit, push or deploy;
- limits: ≤ 120 tool calls; if it stops on the cap with validate not yet 0, Opus launches ONE continuation (call 2 of 4) with the same brief plus "continue from the project as it stands; run `comodel --json validate` first". If that also fails to reach 0, Opus records the findings and goes to step 2 anyway (the deploy script's `sml-cli validate` is the gate of record).
- Opus saves the report to `results/arms_etf_cm/build_cm.md` with: tool-call count, `comodel` call count by command, validate runs and their error counts per run, the final `comodel --json validate` output to `validate_cm_comodel.json`, and the project's file counts per folder.

**2. post (Sonnet, mechanical).** As the DG post step: copy only `datasets/ dimensions/ metrics/ calculations/ models/` from `results/arms_etf_cm/cm_project/` into `bird-models-cm/exchange_traded_funds/`. Do NOT copy `catalog.yml`, `connections/`, `context/`, `build.yaml`, `README.md` or `.claude/`. Repoint every dataset's `connection_id` to `bird_exchange_traded_funds` if it differs. Keep the SML object files byte-identical otherwise; list every file changed in `results/arms_etf_cm/post_cm.md`. Commit `CM build: comodel output`, push.

**3. validate / deploy (Sonnet):** as the ETF kickoff step 3, arm `cm`; log `results/arms_etf_cm/validate_cm.md`. An A8/A10 failure: Opus applies the minimal wording change the gate names. If `sml-cli validate` fails on something `comodel validate` passed, record both outputs side by side in `validate_cm.md`: that gap is a finding about the CLI.

**4. smoke (Sonnet):** the ETF SMOKE BRIEF, arm `cm`. Log `results/arms_etf_cm/smoke_cm.md`.

**5. pre-sweep freeze + run.** Opus commits `CM pre-sweep freeze`, tags `etf-cm-presweep`, pushes, records the SHA. Run as the ETF Phase R with backend `atscale_arm_cm`, `GRADING_AUDIT_PATH=results/arms_etf_cm/grading_audit_cm.jsonl`, output `results/arms_etf_cm/run_cm_pre_*.json`. Opus reads only the reward line and `llm_usage` until Phase C.

**6. sweep round 1 (Sonnet tester):** `results/arms_etf_cm/briefs/sweep_brief.md`, ROUND=1, log `results/arms_etf_cm/sweep_cm.md`.

**7. F2 (Fable):** as the ETF step 7, with the brief's input list minus `facts.md` and plus `results/arms_etf_cm/cm_project/context/profile/` (the CLI's own profiles, which this arm's agent is allowed to read in place of facts). F2 may run `comodel db …` and `comodel --json validate` but edits the arm repo's `exchange_traded_funds/` folder directly, as the other arms' F2 did. Then validate, deploy, re-smoke what F2 touched.

**8. sweep round 2, then the continuation test** as the ETF step 8, with the Fable cap from MODEL TIERS.

**9. freeze + post-sweep run.** Commit `CM freeze`, push, record the SHA, run `run_cm_post_*`.

**C. compare (Sonnet, $0, fence lifted).** Read `results/arms_etf/ARMS.md` and the ETF run JSONs now. Produce `results/arms_etf_cm/ARMS.md` with: CM pre and post reward, P1, P2 on the 15 tasks; the ETF table of SRV/DG/B2 pre/post and raw copied with its date; CM lift over raw and over each arm's post, in pp with relative %; `compare_arms.py` pairs CM pre vs post, CM post vs each ETF post; sweep tables per round; fixer change counts by class; continuation tests; all-in $ against $40; wall time per phase in the ETF §6 shape. Then the arm's own findings: doctor output, comodel call counts, `comodel validate` vs `sml-cli validate` gaps, CLI errors or `NOT_IMPLEMENTED` hits, anything the build agent did by hand because the CLI could not. Caveats, verbatim: "n=1 × 15 tasks; a gap of 2 tasks or fewer is noise" and "CM ran on a different day from the ETF arms, with a different set of catalogs on the shared engine; run wall times are not comparable, scores are".

**Z. close (Opus).** `docs/model-change-log.md` entry "exchange_traded_funds CM arm, initial build"; sheet row `ARM-ETF-CM`; ADK commit `arms_etf_cm: comodel arm on ETF, build + sweep + n=1 compare` (include `results/arms_etf_cm/`, the backend row); no push unless the branch tracks a remote of its own; memory file `arms-etf-cm-<date>.md` plus its MEMORY.md line. Leave `:3004` on the B2 skills; leave every catalog deployed; leave `comodel` installed.

## DO NOT

Everything in the ETF kickoff's DO NOT, plus: give the build agent `facts.md`, `dg_inputs/`, any skill text, `psql` or the helper; edit `cm_project/` by hand except through the post step; edit the comodel checkout; let a `comodel` bug stop the arm when the plugin's own rule ("tell the person, do that step by hand only if they agree") applies: in this unattended run the build agent does the step by hand and reports it as a CLI gap, which is a result.

## DELIVERABLES

A frozen, deployed `Exchange Traded Funds CM` plus its `etf-cm-presweep` tag; `results/arms_etf_cm/{doctor.json,build_cm.md,validate_cm_comodel.json,post_cm.md,validate_cm.md,smoke_cm.md,sweep_cm.md,run_cm_pre_*.json,run_cm_post_*.json,ARMS.md,timestamps.md}`; the change-log entry; the sheet row; the memory file. Final message: verdict first, then one table of CM pre and post reward, P1 and P2 beside the three ETF arms and raw, sweep lift, lift over raw, Fable calls used, all-in $, then the CLI-gap findings in at most five bullets, then the one next action (which pre-registered follow-up to run, or none).
