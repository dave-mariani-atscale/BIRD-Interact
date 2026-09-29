# v12 from-scratch build programme — run order, caps, and why

Twenty databases remain. Two are done: `robot_fault_prediction` (2026-09-18, clean reward 0.55 vs
raw 0.163) and `archeology_scan` (2026-09-19, 0.30 vs raw 0.113). Each remaining database has its
own kickoff file, numbered with the order to run it in:

    results/kickoff_01_solar_panel_v12.md   ...   results/kickoff_20_cold_chain_pharma_compliance_v12.md

Start one with: **`Do results/kickoff_NN_<db>_v12.md`**. One database per session. Never two runs at
once — usage is attributed by timestamp window.

## The order, and the reasoning

Both databases built so far were the two SMALLEST in the estate (10 Query tasks each). Everything
below is 12 to 24 tasks, so every one of them is roughly twice the work and twice the spend. That
makes the ordering matter more than it did: the early slots should buy the most information per
dollar.

**1–5, clean and high-headroom.** The five databases whose shared-repo passes measured the largest
lift with the fewest structural caps. If v12 is going to beat the tuned models anywhere, it is
here, and a failure here is a real signal about the build process rather than about the benchmark.

**6–12, solid lift or unexplored.** `exchange_traded_funds` is the most-studied database in the
project and therefore the best control on whether a from-scratch build matches a heavily tuned one.
`disaster_relief` is the cheapest thing left at 12 tasks. `crypto_exchange` and `sports_events` are
the two least-studied databases in the estate — their worklists will be longer and their baselines
more surprising, which is worth paying for once the process is proven but not before.

**13–20, benchmark-bound.** Every one of these has a recorded wall that no model object can move:
ceiling probes that reached only 8–10 tasks, tie-order golds, gold casing. Expect small lift and a
long cap list. They are still worth running — a cap list with mechanisms is a deliverable — but
they are the wrong place to discover that the v12 process has a flaw.

`cold_chain_pharma_compliance` is deliberately last. Its wall is gold casing (B-71), and the only
lever the 2026-08-27 pass could find was `GRADING_CASEFOLD`. The grader does not change without
Dianne saying so, so that kickoff opens by asking her.

## Caps

**$25 per database, uniform.** Raised from $20 on 2026-09-19 so that no database has a different
budget from any other — a per-database cap that varies by task count makes the spends
incomparable, which is the opposite of what this programme is measuring.

**$25 is headroom, not a target.** For calibration, `archeology_scan` spent $11.29 on 10 tasks
including a $3.17 voided run, and `robot_fault_prediction` about $16 across 4 iterations. A 20-task
database should land near $16-18 *if* cost scales with task count, and the 12-task
`disaster_relief` should come in well under half the cap. Most of these should finish with money
left; a database that reaches $25 should stop and report rather than quietly overrun, and its
report should say what it would have bought next.

**Programme ceiling: $500.** Expect the actual total to be meaningfully lower. Each kickoff asks
whether cost actually scaled with task count, because that answer is what turns this ceiling into
a forecast.

Per-task caps are unchanged at 3 paid iterations or $3.

## What every kickoff now says that the archeology one did not

- **A model is a folder, not a repo.** `diannewood/bird-models-v12`, one shared `catalog.yml` and
  `utilities/`, one folder per database, one deploy that publishes all of them. No new repo and no
  new catalog, ever.
- **The gate is `scripts/gate_run.sh 1 atscale_v12`.** Gate 2 now reads the backend's domains, so
  it fails when this arm's catalog is missing instead of reporting "catalog healthy".
- **Every diagnosis delegation names the forbidden files by PATH**, not by concept — A-69 was a
  firewall breach caused by naming the concept.
- **Pull the raw row and the census count from the sheet yourself.** The archeology kickoff
  hardcoded them; hardcoding a number that has a source is how stale numbers get republished.
- **A "what is already known" paragraph** carrying that database's conventions and caps from its
  shared-repo pass, explicitly marked as a prior and not a specification: a convention that is not
  re-derivable from the KB and the warehouse does not ship.

## Preconditions, already done

- The `aggregates` schema now exists on all 22 BIRD databases (E-15). It was missing on 21 of them
  and is what starved the engine and voided the first archeology baseline. Verified 2026-09-19.
- `utilities/create_bird_connections.sh` now authenticates. The blocker was simply a **wrong
  `ATSCALE_CLIENT_SECRET`** in `bird-atscale-models/utilities/.env`; the working value is the one
  the Keycloak container was provisioned with, `KC_ATSCALE_MODELER_CLIENT_SECRET` in
  `docker inspect keycloak`. Fixed 2026-09-19 and verified: both the password grant and
  `client_credentials` return tokens for `atscale-modeler`. Direct Access Grants was enabled on
  that client the whole time.
  - If this breaks again, read the secret from the container rather than guessing, and do NOT
    trust a `source <(grep ...)` test harness: process substitution silently set nothing in some
    shells here, which makes EVERY variant return the same
    `unauthorized_client | Invalid client or Invalid client credentials` and looks exactly like a
    disabled grant. `set -a; source utilities/.env; set +a` is the form that actually loads.
    Keycloak's `client.secret` DB column is also not a reliable check — it matched the wrong value.
- **The script is nonetheless not needed.** Its schema half is done on all 22, and its connection
  half is a no-op — now measured rather than inferred: `GET /engine/connection-groups` returns 22
  `bird_*` connection groups, no duplicates, every one with `aggregateSchema: aggregates`.

## Model tiers, revised 2026-09-22 — Fable for the design turns only

Measured 2026-09-18..21 from the Claude Code transcripts at list price: a session run end to
end on Fable cost **$55** for robot_fault_prediction (273 requests, 400k output tokens, 72M
cache-read tokens) and **$25** for the half of polar_equipment it finished before the weekly
Fable quota ran out — a full pass would have been $55–66. The Fable allowance is worth about
$125 a week, so that rate is two databases a week. Almost none of that was design: it was
Fable paying ~3k thinking tokens a turn to run `grep`, read gate output and rewrite files.

From here every kickoff runs the session on **Opus** and calls **Fable** as a fresh-context
subagent at most three times — F1 the spec, F2 the post-sweep design review, F3 batched
iteration levers — each ≤15 tool calls, `Write` once and `Edit` after, no build and no
`gold_diff` inside the call. Sonnet's work is unchanged. Target per database: **Fable ≤ ~150k
output and ≤ ~15M cache-read tokens (≈$20 at list, about a third of before)**; Opus takes the
process turns Fable used to pay for. Record the split with `python3 scripts/session_cost.py
--session` and put it in the report. Rules: `docs/bird-database-testing-prompt.md`, "Who does
what"; every `results/kickoff_*_v12.md` carries the same MODEL TIERS block (21/21).

SEVEN THINGS MEASURED ON virtual_idol, 2026-09-22.

1. APPLY THE "OTHERWISE" BRANCH BY GENERATION AND COUNT THE NULLS ON EVERY VERDICT FLAG. A build
that had already applied the rule twice shipped 17 of its 21 knowledge-base verdict flags null on
the MAJORITY of the population - Loyal Achiever was Yes on 4, No on 60 and null on 914 of 972 fans.
Cost, in one trajectory: the agent asked which reading of a segment to use, was told, wrote exactly
the right query with = 'No' for "the other fans", and got ZERO rows off a flag null on 741 of 821
rows. Drive the bare flag and its (<Record> Record Only) twin from one table of (flag, condition,
record) and gate on "no published Yes/No attribute is null on more rows than it is non-null".

2. INTEGER DIVISION IS A FAMILY. Run pg_typeof over EVERY knowledge-base ratio with each operand
cast to its declared type, not just the ones that look like counts. Four of this database's ratios
were integer quotients and the measurement pass caught two: the other two disagreed with the
numeric reading on 787 of 821 and 182 of 185 rows, and moved a segment from 32 to 70 members. A
ratio with a `real` operand needs no twin - the real promotes the integer.

3. gold_diff.py --sweep LEAKS ONE POSTGRES CONNECTION PER TASK, so a sweep longer than pg_maxconn
(default 5) dies with PoolError partway and a 19-task sweep cannot run out of the box. Use
PG_MAXCONN=40. The sweep also needs the model schema-qualified - FROM "<schema>"."<Model Name>" -
or every task fails identically with an R10 error that reads like a broken model.

4. loop_step.py REPORTS AN ERRORED SUBMISSION AS "PASS", because it treats a trajectory entry with
no `passed` key as a pass. Two of one task's four submissions were shown as passes and both had
been refused by the engine's validator. Read the result text before believing a PASS line.

5. A CEILING SWEEP IS A LOWER BOUND ON THE MODEL, NOT AN UPPER BOUND ON THE AGENT. Nine rounds
established 8 of 19 tasks reachable; the baseline then passed a task that was not in that set,
because the agent wrote a better query than the hand-written one. Never cap a task because the
sweep could not reach it.

6. CHECK WHETHER THE MASKED IDS ARE ALL ON MANAGEMENT TASKS BEFORE PLANNING AROUND THE FIREWALL.
Every deleted_knowledge id here was deleted on a Management task only, and the semantic backends
run Query tasks only, so masked_threshold_gate.py reports them inert and NOTHING is withheld from
this arm - the KB's own cutoffs ship. That changes which tasks are winnable before you spend
anything, so read the ids per task rather than assuming a firewall cost.

7. AN ASK THAT FIRES WHERE THE AGENT WAS ALREADY RIGHT LOSES THE TASK. A task passed the baseline
because the agent wrote the strict reading unprompted. A twin was then published for the other
reading with the recommended closed question naming both counts, and on the next run the agent
asked exactly that question, the simulator answered "neither of those definitions is quite right",
invented a third reading, and the task went 0.7 to 0. Publish the twin; attach the ask only where
the baseline shows the agent getting it wrong.

---

## HANDS-OFF DRIVER — builds 8-20 run themselves

    scripts/start_services.sh            # once, and leave them up
    DRY_RUN=1 scripts/run_v12_programme.sh   # print the plan, spend nothing
    scripts/run_v12_programme.sh 08 08       # canary: one build, then read it
    scripts/run_v12_programme.sh 09 20       # the rest

One `claude -p` process per database. The process boundary is the context clear, so there is
nothing to clear and nothing to leak — everything a build tells the next travels through the two
ledgers below. Serial by construction: usage is attributed by timestamp window, so the driver never
starts a second build while one is running, and neither should you.

**The driver's only gate is the ledger row.** After each build it checks that `| NN |` appears in
the PROGRAMME LEDGER table. Missing row means the close did not complete, so it stops the whole
programme rather than let the next build start from a false picture of the spend. It also refuses
to start a build that could carry the committed total past $500, and skips any build whose row is
already there — so a rerun after an abort resumes instead of repeating.

It cannot check whether the model is any GOOD. Nothing can, short of reading the pass report. Run
build 8 alone first and read it before turning the other twelve loose.

**E-19, 2026-09-24 - FIXED the same night.** The engine used to refuse a catalog POST over 8388608 bytes,
and `bird_models_v12` with an 11th model came to 9001981. Dianne raised it to 64m
(`-Dpekko.http.server.parsing.max-content-length=64m` in the engine's `JDK_JAVA_OPTIONS`, compose override
`docker-compose.dm.branches.yml`). If a deploy returns 413 again, the override has been lost: that is the
cause, and not your model's size.

THREE THINGS MEASURED ON mental_health, 2026-09-25 (build 10: reward 0.250 vs raw 0.1783, 7.2 pp).

1. AN ASK THE SIMULATOR CALLS "OUT OF SCOPE" IS A STRUCTURAL DECISION YOU OWE. The facility-binding
closed question (assigned patient's facility vs the encounter's own facility) fired 5 times and was
answered "out of scope" 4 times, and the agent then took the bare reading and lost. Moving the bare name
to the binding a plain SQL reader uses (the table the FK lives on, here `encounters.fac_id`), removing the
ask, and cutting asks 5 to 1 converted the task, and no canary dropped. If your model ships a binding or
population fork, count its out-of-scope answers in the baseline before writing more text.

2. A STORED LEVEL THE KB'S LADDER DOES NOT NAME MAY BE THE ZERO, NOT THE GAP. KB 4 scores engagement High
3 / Medium 2 / Low 1, and the warehouse also stores 'Non-compliant'. The reference scored it 0: the
Non-compliant-as-zero twin passed a phase the bare (excluded) reading failed, and making it bare converted
that phase live. So when a ladder's surplus level is the bottom of the same scale, ship the zero reading
bare and the excluded one as the twin. Run a $0 regression sweep first: here the KB flags built on it moved
22 → 16, 27 → 36 and 33 → 25.

3. ASK F1 FOR CROSS-GRAIN FOLDS BY NAME. F1 built five unjoined datasets. The $0 ceiling then found tasks
that filter a treatment by its assessment's diagnosis, or an assessment by its encounter's facility, which
an island cannot express. F2 spent most of its call adding those columns. In the F1 brief, list which
satellite attributes each grain must carry from the grains it joins to.

SIX THINGS MEASURED ON crypto_exchange, 2026-09-25 (build 11: reward 0.5675 vs raw 0.5717, n=2 on the shipped model).

1. NEVER END A TURN TO WAIT - UNATTENDED, A BACKGROUND SHELL DIES WITH THE TURN. A `run_in_background` wait was
killed when the `claude -p` turn ended. Launch runs with `nohup ... &`, then wait in the FOREGROUND:
`until grep -q "ALL DONE" out; do sleep 15; done` under a 590 s timeout, re-issued until it returns.

2. A WHERE ON AN UNJOINED DATASET'S COLUMN IS SILENTLY DROPPED (Q-41). Filtering one dataset while projecting
another's dispatches `WHERE true`, and every row comes back with no error. It is now in birdsml.ENGINE_NOTES. Carry the
owner columns a question projects into each grain, and read the dispatch when a cross-grain listing looks too long.
ENGINE_NOTES also CORRECTED: STRING_AGG over a FROM-subquery is accepted (it passed a graded phase); median metrics
are called as `<name>_instance_0.5`.

3. GREP THE FLAG HELPER, NOT THE PROSE. F1 copied "read back as 1 for Yes and 0 for No" while its SQL emitted
'Yes'/'No'. A phase with a boolean reference lost on 'No' against 0, with every row right.

4. A STATUS THE KB DOES NOT NAME IS A LABEL THE USER SUPPLIES. "Check the market's health" was graded against
one text column ("Liquidity Crisis"/"Normal Market Conditions"). A closed question on the verdict flag (1/0 or a
label, and which wording) got the right labels from the simulator and converted the task.

5. WHEN THE QUESTION'S FRAMING CONTRADICTS A WAREHOUSE FACT, STATE THE FACT WHERE THE AGENT READS FIRST. "The
latest market-depth snapshot, i.e. the one with maximum market stats id" narrowed the agent to one market (1 row vs
454). Saying "one book row per market, so every order's book is its latest snapshot" on the book columns converted
it, without naming a filter.

6. GREP THE RESULTS JSON FOR `Connection refused` BEFORE READING A ZERO (E-20). The engine lost its warehouse
connection in two runs. One task scored 0 while its last submission matched gold at $0.


FIVE THINGS MEASURED ON sports_events, 2026-09-25 (build 12: reward 0.565 vs raw 0.3633, n=2 on the shipped model).

1. A MEASURE-LESS FROM-SUBQUERY RETURNS DISTINCT TUPLES (Q-42). An AVG over pit-stop durations selected without the stop
ID came back 87.23 against 83.4, and a passing task was lost on it. It is now in birdsml.ENGINE_NOTES: the row-grain
subquery carries the row's ID. The same collapse merges entities that share a name or have none.

2. SAY A NULL NAME AS MEMBERSHIP, NEVER AS A DEFECT. 10 of 44 constructors have no name. "10 have NULL names, group by ID"
was read and the agent filtered the 10 OUT. "One row per Constructor ID; the unnamed are still constructors in every
listing" converted the task on 2 of 4 runs.

3. A CLOSED QUESTION MUST OFFER EVERY PUBLISHED READING, BY GRAIN WORD. An ask offering two driver denominators while a
row-grain twin existed got "qualifying records ... the 154", and the agent took the driver grain.

4. EVERY "N CARRY A VALUE" COMES FROM A LIVE COUNT. F2 wrote 154 where 153 carry a deficit. The agent asked about exactly
that population and lost a passing task by one row. Put the count in LIVE and pin it.

5. SEARCH READINGS ON THE RAW BACKEND BEFORE F2 ($0). `gold_diff.py --backend raw --task <id> --sql "<postgres>"`,
briefed to KB-derivable readings only, found the reproducing reading for 5 of 7 unreached tasks; F2 shipped four as
named twins and the ceiling went P1 11 -> 15. Brief it READ-ONLY on the warehouse: the subagent created a function.

FIVE THINGS MEASURED ON museum_artifact, 2026-09-25 (build 13: reward 0.315 vs raw 0.1367, n=2).

1. A JSONB NUMBER IS NATIVELY NUMERIC, SO A KB RATIO OVER JSON NUMBERS IS A DECIMAL QUOTIENT AT THE WAREHOUSE'S OWN
TYPES. F1 cast the JSON scores to integer, made the whole-number CPI bare, and the agent took it: 7 of 9 values wrong on
four submissions of one task, while every ceiling CPI pass used the decimal twin. Put this in the F1 brief by name: cast a
JSON leaf with ::numeric, keep integer bare only where the operands are genuinely integer COLUMNS.

2. BUDGET NAMES AGAINST SML'S 63-CHARACTER unique_name CAP IN F1. A grain prefix, a KB name and a qualifier overflowed on
54 names and cost two build rounds of mechanical shortening. Keep qualifiers to about 15 characters ("(Rated Only)",
"(Integer Division)"), and never emit "(... Only)" twice in one name.

3. LEFT-JOIN EVERY SATELLITE INTO A GRAIN AND PIN THE PARENT COUNT. facts.md reported every showcase as having a reading;
one had none, the placement grain inner-joined readings, and that showcase's only artifact vanished from the grain (a
flag summed 994 of 995). Have the facts pass count parents with zero children by anti-join, and pin each grain's entity
count so a dropped parent fails the dry-run.

4. calculation_method "max" / "min" ARE NOT RECOGNISED BY THE KEY-METRIC AUDIT and read as FATAL; write "maximum" /
"minimum", as every sibling model does.

5. A CEILING PASS THAT NEEDED AN INVENTED LABEL OR CONSTANT IS NOT A REACHABILITY PROOF. One sweep "pass" mapped budget
words to labels no source names and filled a missing status with 5; no agent writes that. Do not count it in the
ceiling, and give the task an R2 row with a predicted zero. And skip F4 when the reachable failures are simulator,
reference-convention or agent-narrowing rather than coins: here that was every one of them.

## PROGRAMME LEDGER — where the spend and the score actually stand

**Every build appends its row here as the LAST step of its close, after propagation.** This file
is what a fresh session reads first, so this table is the only place the programme's position
survives a context clear. A pass report does not count: the propagation rule says plainly that
nobody reads the previous database's report before starting the next one, and three of the first
nine reports had no parseable benchmark-spend line at all.

Reward is 0.7·P1 + 0.3·P2. "raw" is the re-graded raw arm for the same database. Spend is
BENCHMARK dollars from `llm_usage` — not session cost, which is recorded separately in each report.

| # | database | tasks | P1 | P2 | reward | raw | lift (pp) | benchmark $ | date |
|---|---|---|---|---|---|---|---|---|---|
| — | robot_fault_prediction | 10 | — | — | 0.550 | 0.163 | +38.7 | ~16.00 | 2026-09-18 |
| — | archeology_scan | 10 | — | — | 0.300 | 0.113 | +18.7 | 11.29 | 2026-09-19 |
| 01 | solar_panel | 20 | 0.850 | 0.600 | 0.775 | 0.525 | +25.0 | 11.85 | 2026-09-19 |
| 02 | organ_transplant | 19 | 0.158 | 0.053 | 0.1263 | 0.0702 | +5.6 | 16.96 | 2026-09-20 |
| 03 | insider_trading | 21 | 0.357 | 0.262 | 0.3286 | 0.2270 | +10.2 | 18.70 | 2026-09-20 |
| 04 | polar_equipment | 20 | 0.525 | 0.275 | 0.450 | 0.070 | +38.0 | 13.40 | 2026-09-21 |
| 05 | virtual_idol | 19 | 0.421 | 0.105 | 0.3263 | 0.2526 | +7.4 | 12.30 | 2026-09-22 |
| 06 | exchange_traded_funds | 19 | 0.605 | 0.368 | 0.5342 | 0.2947 | +23.9 | 13.82 | 2026-09-22 |
| 07 | disaster_relief | 12 | 0.417 | 0.333 | 0.3917 | 0.1528 | +23.9 | 18.55 | 2026-09-23 |
| 08 | fake_account | 24 | 0.750 | 0.625 | 0.7125 | 0.2681 | +44.4 | 21.77 | 2026-09-24 |
| 09 | planets_data | 19 | 0.526 | 0.342 | 0.4711 | 0.4070 | +6.4 | 19.97 | 2026-09-24 |
| 10 | mental_health | 20 | 0.250 | 0.250 | 0.250 | 0.1783 | +7.2 | 22.94 | 2026-09-25 |
| 11 | crypto_exchange | 20 | 0.650 | 0.375 | 0.5675 | 0.5717 | -0.4 | 17.70 | 2026-09-25 |
| 12 | sports_events | 20 | 0.625 | 0.425 | 0.565 | 0.3633 | +20.2 | 19.88 | 2026-09-25 |
| 13 | museum_artifact | 20 | 0.375 | 0.175 | 0.315 | 0.1367 | +17.8 | 15.43 | 2026-09-25 |
| 14 | reverse_logistics | 20 | 0.850 | 0.775 | 0.8275 | 0.5883 | +23.9 | 9.09 | 2026-09-26 |
| 15 | cross_border | 19 | 0.526 | 0.368 | 0.479 | 0.1140 | +36.5 | 21.89 | 2026-09-26 |
| 16 | hulushows | 20 | 0.675 | 0.575 | 0.645 | 0.4717 | +17.3 | 13.83 | 2026-09-26 |
| 17 | households | 21 | 0.119 | 0.095 | 0.112 | 0.0698 | +4.2 | 14.51 | 2026-09-26 |
| 18 | labor_certification_applications | 19 | 0.842 | 0.474 | 0.7316 | 0.3544 | +37.7 | 10.50 | 2026-09-27 |
| 19 | cybermarket_pattern | 20 | 0.700 | 0.550 | 0.6550 | 0.6017 | +5.3 | 3.91 | 2026-09-28 |
| 20 | cold_chain_pharma_compliance | 18 | 0.611 | 0.500 | 0.5778 | 0.3667 | +21.1 | 3.93 | 2026-09-28 |

**EVERY SCORE IN THIS TABLE PREDATES THE DEPLOYED MODEL — A RE-RUN IS OWED ON ALL OF THEM
(written 2026-09-28).** The models repo has moved under the whole table. Three changes, in
order of how much they can move a number:

1. **`f564e11` 2026-09-27 21:07 — the round-2 retrofit, applied to all 19 models built before
   builds 18–20.** This is a behaviour change, not a wording change: it is the newer process
   (rename-to-plain, cut asks with no paid evidence, the restored rounding rule) retrofitted
   onto models whose recorded score was measured under the older one. No row above was
   measured after it.
2. **`24341a4` / `051179b` / `584c1db` / `2e7e58b` 2026-09-28 — engine notes corrected in place
   across all 22 models,** from the pr9967 re-probe: 16 of 50 shipped claims no longer
   reproduce. A description that told the agent the engine refuses something it accepts was
   steering it away from a working query, so some of these are live, not cosmetic.
3. **`faf4f8b` / `e9a95cc` / `7881d16` 2026-09-28 — organ_transplant only, three KB composites
   published** (KB 34 allocation priority rank, KB 51 AMR risk, KB 31 optimal match) after
   `is_mask: true` was found to withhold nothing. `_2` was measured converting to a bare pass
   at $0. Row 02's 0.1263 is the furthest from its model of any row here.

Rows 19 and 20 were bought on 2026-09-28 and are no longer dashes. Both ran on the **nocheat**
arm (branch `nocheat` @`0c6a4f0` = main `7881d16` + the description-only strip), n=1.

**2026-09-29 ROUND 3 WITHDRAWN.** Every round-3 model change was reverted the same day (all were
gold_diff-triggered, finding 2/3 of the cheating review). Current state, per
`results/optimize_r3_20260929/RESULT.md` top table: cross_border 0.600, fake_account 0.671,
sports_events 0.555, museum_artifact 0.270, disaster_relief 0.333 (measured, still valid);
cybermarket 0.655 and cold_chain 0.5778 (the 09-28 rows stand); insider_trading 0.367, hulushows
0.555, households 0.143 (estimates: 09-29 close minus the withdrawn task). The table below records
what was measured on the since-reverted models.

**2026-09-29 ROUND 3 — supersedes the rows below for these ten databases.** One task at a time on
branch `nocheat` (end `f007a0c`), n=1, $50.15 benchmark. Full record `results/optimize_r3_20260929/RESULT.md`.

| # | database | tasks | P1 | P2 | reward | raw | lift (pp) | benchmark $ | date | was |
|---|---|---|---|---|---|---|---|---|---|---|
| 15 | cross_border | 19 | 0.632 | 0.526 | 0.600 | 0.1140 | +48.6 | 5.01 | 2026-09-29 | 0.479 |
| 19 | cybermarket_pattern | 20 | 0.800 | 0.650 | 0.755 | 0.6017 | +15.3 | 1.07 | 2026-09-29 | 0.655 (spliced) |
| 03 | insider_trading | 21 | 0.429 | 0.381 | 0.414 | 0.2270 | +18.7 | 4.86 | 2026-09-29 | 0.3286 |
| 17 | households | 21 | 0.190 | 0.190 | 0.191 | 0.0698 | +12.1 | 6.11 | 2026-09-29 | 0.112 |
| 12 | sports_events | 20 | 0.600 | 0.450 | 0.555 | 0.3633 | +19.2 | 4.46 | 2026-09-29 | 0.565 |
| 16 | hulushows | 20 | 0.650 | 0.500 | 0.605 | 0.4717 | +13.3 | 6.25 | 2026-09-29 | 0.645 (composite) |
| 08 | fake_account | 24 | 0.708 | 0.583 | 0.671 | 0.2681 | +40.3 | 4.69 | 2026-09-29 | 0.7125 |
| 13 | museum_artifact | 20 | 0.300 | 0.200 | 0.270 | 0.1367 | +13.3 | 7.32 | 2026-09-29 | 0.315 |
| 20 | cold_chain_pharma_compliance | 18 | 0.556 | 0.444 | 0.522 | 0.3667 | +15.6 | 4.23 | 2026-09-29 | 0.5778 |
| 07 | disaster_relief | 12 | 0.333 | 0.333 | 0.333 | 0.1528 | +18.1 | 4.88 | 2026-09-29 | 0.3917 |

8 of 13 levers converted; the four positive rows are the four databases whose levers converted
without a variance loss elsewhere. The negative rows are n=1 moves on tasks no edit touched, and
three of them (fake_account, sports_events, museum_artifact) had no lever at all — the retrofit's
bare-ceiling gains did not appear live there.

**2026-09-28 re-measurements — see `results/nocheat_record_20260928_204444/RESULT.md`.** Four
rows above are now stale in the other direction; the re-runs that were owed have been bought
for three of them:

| row | recorded | re-measured 2026-09-28 | arm |
|---|---|---|---|
| 02 organ_transplant | 0.1263 (+5.6 pp) | **0.2895 (+21.9 pp)** | nocheat, n=1 |
| 09 planets_data | 0.4711 (+6.4 pp) | **0.6158 (+20.9 pp)** | nocheat, n=1 |
| 11 crypto_exchange | 0.5675 (−0.4 pp) | **0.5250**, main n=2 | main `7881d16` |

- **organ_transplant was never the estate's worst build.** It was handicapped by `is_mask`, which
  withholds nothing. Three KB composites shipped 2026-09-28; `_2` converted exactly as the $0
  sweep predicted, and live P1 7/19 is a 100% conversion of the bare-name ceiling.
- **planets_data confirms B-69 as a live cost.** The rounding rule restored 2026-09-26 is worth
  real tasks, hardest at P2 (6.5 → 11).
- **crypto_exchange is noise, not regression.** Two identical main runs the same day returned
  0.4250 and 0.6250 — **±20 pp at n=1**. Its mean (0.5250) is within noise of the recorded
  0.5675, so the round-2 retrofit did not hurt it. Do not quote any crypto_exchange figure at
  n<3; the original "−0.4 pp" was also a single pair of draws.
- **The nocheat strip costs nothing at P1** on the one database where both arms ran (10/20 vs
  10/20). It removes only ask machinery — 4 of 383 descriptions, 830 chars, on crypto_exchange.

Do not quote any figure above as current without saying it predates these commits. The
estimator in `results/gap_investigation_20260926.md` (P1 ≈ 0.906 × bare-name ceiling) is the
$0 stand-in until the re-runs are bought.

**Numbered builds 1–7: $105.58 spent, mean $15.08, range $11.85–$18.55.** No build has reached the
$25 cap. At that mean the remaining 13 come to about $196, putting the programme near **$302 of the
$500 ceiling** and leaving roughly **$198 for a round 2** — so builds 8–20 spend normally and do NOT
hold money back. If the mean climbs above $22, say so in the report: that is the point at which
round 2 starts competing with the builds, and it is a decision for Dianne, not for a build session.

Note the spread in lift is 5.6 to 38.7 pp with no relation to task count. Do not treat a low lift
as a failed build until the cap list has been read.

## ROUND-2 LEDGER — what to write down when you run out of budget, not ideas

Dianne's decision, 2026-09-23: after all 20 databases are built, the residual may fund **one more
round**. Round 2 is scoped to exactly two things — **untried model levers** and **re-testing capped
tasks**. It is NOT for n≥2 re-measurement of noisy estimates, and NOT for cross-database process
experiments. Both were considered and declined.

So every build closes by writing its deferred levers down in a form that is rankable a month later
against nineteen other databases, by a session that has never read its pass report.

**The sheet is canonical.** One row per deferred lever, id `R2-NN` (flat sequence, next free number
— `B- M- Q- A- E- C-` are taken), `Status: open`, via `scripts/sheet.py` like any other row. Then
regenerate the local mirror with `python3 scripts/r2_ledger.py`, which rewrites
`results/v12_round2_ledger.tsv` FROM the sheet. The mirror is generated, never hand-edited, so it
cannot drift; if the two disagree, the sheet is right.

**A lever qualifies for a row only if it carries all four of these.** Three out of four is not a
row — it is a sentence in the pass report. This rule is the whole mechanism: without it round 2
opens on a wish list and spends its first two hours deciding what anything meant.

1. **A named mechanism.** Which model object changes and how — "a bare-name move on the X family",
   "publish the intersection population as a twin". Not "improve the description".
2. **A falsifiable prediction.** Which task ids, and what they would score. "`_5` and `_7` go 0 →
   0.7." A prediction of zero is a legitimate row and is worth more than a vague positive one.
3. **The result of a $0 `gold_diff` sweep already attempted.** Every lever is free to test before
   it is free to defer. Write what the sweep returned — reached, or the FINDING head if it did not.
   A lever nobody swept is not deferred, it is unexamined, and it does not get a row.
4. **A cost estimate in RUNS**, not dollars. Cost scales with runs; one targeted run is ~$1–2.

Put the mechanism in `Issue`, the database and build number first in `Brief`, the task ids in
`Tasks affected`, the prediction in `Impact`, the sweep result in `Repro / evidence`, and the run
cost plus why it was not done in `Notes`. `Fix needed in` is `model` or `cap re-test`.

**A capped task gets an R2 row too, unless its cap was DEMONSTRATED rather than merely asserted.**
A cap whose mechanism was proven — `_1`'s caller column count, a gold the layer cannot emit — has
no round-2 value and gets no row. A cap that merely survived its falsification checks without being
reached ("neither check falsifies it; it stands unresolved") is an open question wearing a cap's
clothes, and it gets a row with a predicted zero. Measured precedent: four of five solar_panel
phase-1 caps were wrong, and the B-77 tie-order caps dissolved under the corrected grader.

**When round 2 opens:** `python3 scripts/r2_ledger.py --rank`, re-sweep every open row at $0 first
— the model has changed underneath some of them and the grader may have too — and spend only on
rows that still prove sufficient, ranked by predicted tasks per run across all 20 databases rather
than within any one of them. The cross-database ranking is the point: a build session can only see
its own levers, and the cheapest conversion in the estate is unlikely to be in the database that
happened to be built last.

## GAP INVESTIGATION

- 2026-09-26 `results/gap_investigation_20260926.md` — why v12 loses to tuned (mean −15.7 pp over 16 builds): 36% model object, 45% steering on twin forks, 14% shape/rounding (5 phases are the rounding rule deleted in `90c21a8`, an arm confound), 6% engine. Tuned YAML carries grader verdicts and gold-selected bare readings in 8 of 16 dbs; v12 by rule does not. The lever is a firewall decision (bare-name move on a ceiling-selected reading), then ask-targeting; $0 test = "bare-name ceiling" vs tuned P1 on builds 18–20. Read before changing the build process.
- **Decision 2026-09-26 (Dianne): rename-to-plain allowed for builds 18–20.** A reading the $0 ceiling sweep selects takes the bare name; asks target shape/population/label/order only. Rule block `RENAME TO PLAIN` in kickoffs 18–20; prompt §Support sets and the testing-prompt decision table carry a pointer. Rounding rule (B-69, `90c21a8`) still undecided.
- **Decision 2026-09-26 (Dianne), second part: `gold_diff.py` may diagnose any failing task and motivate a model change, for builds 18–20; gold SQL never enters the model.** Every change is tagged `[PLAIN]` / `[DIAG]` / `[KB]` (commit subject + change log) and each pass report carries a `## LEVER ATTRIBUTION` section: per-task conversions by lever plus a $0 ablation (final vs noDIAG vs noPLAIN: full ceiling, bare-name ceiling, replay). Sum the three builds' tables to measure the two decisions separately. Rule block `GOLD_DIFF DIAGNOSIS ALLOWED` in kickoffs 18–20; `gold_diff.py` docstring, the v12 prompt, the testing prompt and the change-log header carry pointers.
- **Decision 2026-09-26 (Dianne), third part: the rounding rule is restored.** The "Do NOT round … TO_CHAR(x, '9.99EEEE')" bullet dropped by `90c21a8` is back in the `atscale` instruction in `config/environment_backends.yaml` (inherited by `atscale_v12`); builds 18–20 run with it, as every tuned reference run did. Builds 1–17 ran without it (B-69); their planets_data/solar_panel rounding losses are the measured cost.
- **A/B re-author brief 2026-09-26: `results/kickoff_ab_insider_trading_reauthor_20260926.md`.** Tests whether Fable owning the whole $0 phase beats the tiered process, on insider_trading (ceiling 11/21 vs tuned 18/21, an Opus build), two fresh arms under the new rules, no benchmark run; B − shipped also measures the rule changes. Decision rule inside; run before build 18 if Dianne wants the answer to shape it.

FIVE THINGS MEASURED ON labor_certification_applications, 2026-09-27 (build 18: reward 0.7316 vs raw 0.3544, 37.7 pp; tuned 0.5088).

1. UNSET SEMANTIC_LAYER_MCP_TOKEN BEFORE EVERYTHING. The session shell exported a stale token that beats the ADK .env;
services started from it and every MCP initialize returned 401, which gate_run.sh reports as "list_models errored" and reads
like E-14 (A-71). Put `unset SEMANTIC_LAYER_MCP_TOKEN` in every run script and before start_services.sh and gate_run.sh.

2. A DESIGN CALL WILL PUBLISH A WITHHELD CUTOFF TO "CUT AN ASK". F2 wrote KB 44's 50% and KB 52's 95/85 into descriptions to
retire their asks, both withheld on running tasks. Name every withheld cutoff BY NUMBER in each F2/F3 brief as never-write,
and diff the design call's edits for those numbers before building; A10 caught only a third, later phrase.

3. SHAPE ASKS CONVERT; A COMPANION SENTENCE ALONE DID NOT. One run converted `_13` P1 (states listed vs a count), `_14` P1+P2
(a fourth top-occupations column) and `_4` P2 (job title vs SOC title), each ask fired and answered right, while the SOC
code+title companion sentence on `_8` P2 lost on the same COLUMN COUNT again. A follow-up column word that maps to different
columns on different tasks (`_4` SOC title, `_17` recorded job title) is a fork the sweep cannot settle: ship the closed
question; `_17` did not flip.

4. THE CREDIT CAN RUN OUT MID-RUN, WITH A DIFFERENT MESSAGE (A-72). "Your credit balance is too low", not the workspace-limit
text: tasks finished before its timestamp are clean, the rest are void (HTTP 500 on /run_session, no instance_id).
`gold_diff.py --results` crashes with KeyError 'instance_id' on such a file; filter those rows out first.

5. THE $0 ABLATION CANNOT SEE [PLAIN]. PLAIN commits change descriptions and asks, not dataset SQL or names, so noPLAIN equals
FINAL on every $0 measure by construction; say so and attribute PLAIN per task from the paid runs. After the noDIAG deploy the
first FINAL redeploy did not take: probe a changed value after every ablation deploy. And the grader passes case-only
differences ('CA' vs 'ca'), so LOWER-rendering caps do not bind (B-79's five were stale).
