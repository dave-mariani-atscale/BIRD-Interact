# A/B: shorter agent output — measured, and declined

**Verdict: rejected.** Telling the agent not to narrate cost **5 of 252 phase-1 passes and gained none**, for a
**3% wall-clock saving**. The flag and the instruction were removed; this document keeps the wording and the
numbers so the idea can be retried deliberately rather than rediscovered.

## Why it was worth testing

Output tokens are where an a-interact task's wall-clock goes. Measured 2026-09-09 on the 09-06/07 semantic-layer
run against the 09-08 raw run, both at concurrency 5: per agent call the semantic-layer arm emits 770 completion
tokens against raw's 535, and generation costs ~14.1 ms per token (probed live). That gap is 25.5 s of the 42.7 s
per-task difference between the arms — 60% of it. Tool round-trips are 15.7 s (37%); the 25k-token larger prompt
is 1.5 s (3%), because a 22k-token system prompt costs only ~0.2 s per call whether cached or not. So the lever
was what the agent writes, not what it is told.

## Design

Paired, same day, same tasks, same concurrency, control first. Population: the **253 tasks that passed phase 1 in
all three repeats** of the 09-06/07 run. Deliberate: a regression from suppressing narration shows up as losing
passes we already had, and stable passers have almost no run-to-run variance — the control arm lost exactly 1 of
253, so the noise floor on this population is ~0.4%, against ~6% for repeat-to-repeat churn on the full 410. One
run of each arm therefore resolves a 5-task change, which 410 tasks at n=1 could not.

## Result

| | control | terse |
| --- | ---: | ---: |
| phase 1 | 252/253 (99.6%) | 247/253 (97.6%) |
| phase 2 | 202/253 (79.8%) | 202/253 (79.8%) |
| average reward | 0.9368 | 0.9229 |
| seconds per task | 102.1 | 99.0 |
| output tokens per agent call | 645 | 552 |
| agent calls | 2180 | 2073 |
| API cost | $58.32 | $55.13 |

Discordant pairs: **5 control-only passes, 0 terse-only.** Exact McNemar p = 0.062; the difference in phase-1 pass
rate is **−2.0 points, 95% CI [−3.7, −0.3]**. Not significant at 0.05, but one-sided 5–0 with a CI excluding zero:
this fails to show the pass rate holds, which was the thing to prove, and the upside it was bought for is 3%.

Lost: `labor_certification_applications_15`, `organ_transplant_3`, `planets_data_20`, `solar_panel_15`,
`virtual_idol_17`.

## Mechanism — the wording did more than it said

It was written to forbid narration and explicitly not deliberation. It suppressed asking anyway. Population-wide,
mean `ask_user` calls fell 0.32 → 0.27 and discovery calls 2.74 → 2.44. On 4 of the 5 lost tasks the terse arm
asked fewer questions than the control (2→1, 1→0, 1→0, 2→1) and then spent the saved budget flailing:
`solar_panel_15` went from 4 run_query calls to 10, `planets_data_20` from 11 coins to its full 18 with twice the
submits. Out-of-budget tasks fell 40 → 34, so it saved budget and spent it worse.

Plausible reading: one clause capped the *ask* itself ("keep an ask_user message to the question itself and its
options"), and a general instruction to write less generalises to asking less. Any retry should say nothing about
ask_user, and should probably raise the value of asking at the same time.

## The wording tested (removed from `system_agent/agent.py` after this run)

> OUTPUT LENGTH. Every token you write costs wall-clock time, and the graded artefact is the query, not your
> commentary. Before a tool call, write at most one short sentence saying what you are doing and why. Do not
> restate your plan, do not summarise what a tool just returned (it is already in the transcript), and do not
> explain a query you are about to run. Do not list columns in prose that you are also writing into the query.
> Keep an ask_user message to the question itself and its options. Reasoning that changes your next action is
> worth writing; narration of what you have already done is not.

Artefacts: `results/ab0909_control.json`, `results/ab0909_terse.json` (both carry `deviations.agent_terse_output`
and the new `concurrency` / `effective_parallelism` fields).

## What remains of the wall-clock question

The 37% tool-round-trip term is untouched and is the next honest lever: ~2.4 s per MCP+engine call against ~0.5 s
for a local Postgres query. Prompt trimming is not a lever (3%). And per-task wall-clock must only ever be
compared at equal concurrency — see `docs/grader-review-20260909.md`'s companion note and the runner's new
`effective_parallelism`.
