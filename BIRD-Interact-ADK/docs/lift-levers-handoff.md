# Lift levers: context for investigating five open items

Written 2026-08-17 as a handoff. Everything here is framed by one question —
**what can we change that makes the semantic-layer arm score better relative to
raw** — and nothing here is organised by whose defect it is. Where a lever is
only reachable by changing something we don't own, that is stated as a cost, not
as a reason to stop.

Companion reading, in this order: `docs/bird-grading-comparison.md` (the grader
and its defects, §11 for what we changed on 2026-08-14), then the tracker
(`python scripts/sheet.py get <ID>`) for any row named below.

---

## 0. Orientation you need before touching any of it

**What lift is.** Mean reward, semantic arm minus raw arm, on the same
databases under the same grader. Report it in **percentage points**, with the
relative figure alongside — never the fraction form.

**Current baselines** (re-graded 2026-08-14 under today's flags; all four
reproduce their recorded totals):

| database | atscale | raw | lift |
|---|---|---|---|
| crypto_exchange (n=20) | 8.90 → 0.445 | 6.80 → 0.340 | **+10.5 pts** |
| exchange_traded_funds (n=19) | 8.70 → 0.458 | 7.40 → 0.390 | **+6.8 pts** |

**Scores from different dates are not comparable.** Tracker **B-16** documents
three grading epochs; a fourth landed 2026-08-14. Every baseline comment in
`scripts/run_*.sh` predates at least one of them. Re-grade the baseline
trajectory before comparing anything — it is free and takes minutes.

**The measurement rule that governs all five items:**

* Changing **how a submission is graded** → `scripts/regrade_flags.py` or
  `scripts/score_dual.py`. Free, no LLM calls, trajectory held fixed.
* Changing **what the agent can do or see** (tools, prompts, budget, the
  semantic model) → requires a re-run, because the trajectory changes. ~$0.35
  per task with caching on. Only the affected arm needs re-running when the
  change touches one arm.

**Run-to-run variance is large** (tracker **A-03**, P0). A single run cannot
distinguish a small lift change from noise. Budget n≥2, preferably 3, for
anything whose conclusion is "this helped".

**Flags currently on** (`.env`, recorded per run in `results/*.json` under
`deviations`): `GRADING_HONOR_DECIMAL`, `GRADING_CASEFOLD`,
`GRADING_TIE_TOLERANCE`, `GRADING_ORDER_LINT`, `GRADING_REL_TOLERANCE` @1e-6.
Off: `SEMANTIC_LAYER_KNOWLEDGE_TOOLS`, `FREE_WASTED_ACTIONS`.

### Where the exposure actually is, per item

Tasks affected in the **seven databases we have models deployed for**. Details
and the full 22-database picture are in each section.

| item | ETF (19) | crypto (20) | archeology (10) | households (21) | labor-cert (19) | solar (20) | cyber (20) | verify by |
|---|---|---|---|---|---|---|---|---|
| §1 under-determined golds | 0 | 2 | 0 | 3 | 1 | 1 | 0 | re-grade (free) |
| §2 float32 golds | 0 | 2 | **4** | 0 | 0 | 1 | 0 | re-grade (free) |
| §3 set vs multiset | 0 | 0 | 1 | 0 | 0 | 0 | 0 | re-grade (free) |
| §4 knowledge tools | **19** | **20** | **10** | **21** | **19** | **20** | **20** | re-run, atscale only |
| §5 model defects | **6** | 0 | 3 | 0 | 0 | 0 | 0 | re-run, atscale only |

Read that table as the priority order it implies: the three grading items are
individually small and mostly land outside the databases we run, while §4
touches every task and §5 touches a third of ETF. The two cheap-to-verify
columns are also the two smallest.

Caveat on the §5 row: zeros there mean **nobody has audited that model**, not
that it is clean. ETF has had by far the most attention.

---

## 1. The 25 under-determined golds

**Tracker: B-34** (the sweep), **B-27** (the first two found), **B-36** (a
separate 2-phase truncation issue). Write-up: `bird-grading-comparison.md` §6b.
Lint: `python scripts/bird_content_lint.py <db ...>`.

### What it is

25 graded phases where gold returns **different values depending on the query
plan** — a different row wins a tie, so the reference answer is not determined
by the reference query. `households_8` returns a different pair of cities;
`mental_health_2` phase 2 returns diagnosis `f440` or `f429`.

Two things to know before you spend time here:

* **No grading change can reach these.** Measured: 19 of 25 differ
  non-numerically or in row count, so no tolerance can absorb them; of the 6
  purely numeric, five are 5.6%–190% apart. Exactly one sits in tolerance range.
* **They are disjoint from the 68 order-undetermined phases** we already
  mitigated (zero overlap). The fix that worked there — decline to grade the row
  order — does not transfer, because here the ambiguity is in *which rows and
  values*, not their sequence.

### Why it matters for lift

**Both arms score 0 on these**, so they don't move lift directly. They act on
the denominator. Removing k tasks that both arms fail from a run of n leaves the
*relative* lift unchanged but scales **percentage-point lift by n/(n−k)**.

**Per database.** 20 tasks across 12 databases; 7 tasks sit in databases we
have models deployed for. A phase-1 hit costs the whole task (0.7 + 0.3); a
phase-2 hit costs only the 0.3.

| database | tasks hit | of which phase 1 | Query tasks in db | model deployed |
|---|---|---|---|---|
| households | 3 | 3 | 21 | **yes** |
| mental_health | 3 | 1 | 20 | no |
| polar_equipment | 3 | 2 | 20 | no |
| crypto_exchange | 2 | 1 | 20 | **yes** |
| museum_artifact | 2 | 0 | 20 | no |
| cold_chain_pharma_compliance | 1 | 1 | 18 | no |
| fake_account | 1 | 1 | 24 | no |
| labor_certification_applications | 1 | 1 | 19 | **yes** |
| disaster_relief | 1 | 0 | 12 | no |
| insider_trading | 1 | 0 | 21 | no |
| solar_panel | 1 | 0 | 20 | **yes** |
| virtual_idol | 1 | 0 | 19 | no |

`exchange_traded_funds`, `archeology_scan` and `cybermarket_pattern` are clean.
Named tasks are in `/tmp/content_sweep.json` after running the lint, or in the
B-34 tracker row.

### What can actually be changed

1. **Exclude them from scoring.** Cheapest, needs no data edits, and it is the
   only one of the three that is purely a reporting decision. It raises both
   arms' means and raises percentage-point lift. It must be disclosed alongside
   any number, and it makes totals non-comparable to published results.
2. **Edit gold locally** so the answer is determined (add a tiebreak). §6b has
   the per-construct fix table — one line each. This changes what the benchmark
   answers, so it is a fork of the dataset and a much bigger comparability cost
   than a flag. It also does *not* make the tasks winnable: pinning `f440` over
   `f429` makes them stable and still unguessable.
3. **Nothing.** Defensible: 7 tasks across the databases we run, all currently
   lost by both arms.

**Open question for the next session:** does the exposure skew by arm? It should
not — both arms fail them — but nobody has checked whether the semantic arm
fails them *for this reason* while raw fails them for another, which would
change how you read a per-task diff. `results/grading_audit*.jsonl` has the rows
to check without spending anything.

---

## 2. The float32 golds

**Tracker: E-04.** Write-up: `bird-grading-comparison.md` §3. Lint:
`python scripts/bird_precision_lint.py <db ...>`.

### What it is

11 of 410 Query tasks have gold parsing text to `::real` — 32-bit float, ~7
significant digits — and computing in that type. Any other engine reads the same
text as `numeric` or `float8`, and where the true value sits near a rounding
boundary the two land on opposite sides.

**Per database** — 11 tasks across 6 databases, 7 of them in databases we have
models for:

| database | tasks hit | Query tasks in db | which | model deployed |
|---|---|---|---|---|
| archeology_scan | 4 | 10 | `_1 _6 _7 _8` | **yes** |
| crypto_exchange | 2 | 20 | `_5 _10` | **yes** |
| polar_equipment | 2 | 20 | `_4 _9` | no |
| disaster_relief | 1 | 12 | `_4` | no |
| planets_data | 1 | 19 | `_5` | no |
| solar_panel | 1 | 20 | `_2` | **yes** |

`archeology_scan` at 4 of 10 is the concentration, and it is also the database
§8 of the grading doc shows is structurally ungradable for other reasons —
7 of its 10 tasks are at risk once defect A is counted too.

**Not fixable model-side.** The AtScale engine dispatches
`SUM(CAST(x AS FLOAT8))` regardless of the declared column type — read from the
outbound SQL, not inferred.

### Why it matters for lift

This is structurally a semantic-layer tax: raw runs prediction and gold on the
same engine, so it only diverges when the agent's own casts differ from gold's.

`GRADING_REL_TOLERANCE` @1e-6 is **already on** as of 2026-08-14 and rescued
`crypto_exchange_5` p1 for the atscale arm. Measured over 930 stored
submissions: atscale +2 phases, raw +1, no regressions.

### What can actually be changed

1. **`GRADING_REL_TOLERANCE_VALUE`.** The one remaining dial. At 2e-5 it adds
   `crypto_exchange_4` p2 — on the **raw** arm — and historically rescued
   `archeology_scan_7` for atscale. Rejected on 2026-08-14 on the principle that
   *the tolerance must stay below the precision the task is graded to*; at 2e-5
   the forgiven gap on a 7-digit value exceeds one unit at the graded decimal.
   Re-open only with evidence that atscale submissions are failing where a
   sub-1e-4 gap is the ONLY blocker, and count that from the audit rather than
   guessing (this is exactly what tracker **B-20** already litigated once).
2. **Edit gold to drop `::real`.** Same fork cost as item 1's option 2.
3. **Per-database awareness.** The direction is not uniform. ETF and crypto
   rescues land on atscale; archeology rescues land on raw. `archeology_scan` is
   the database where 7 of 10 tasks are structurally at risk (§8) — its lift
   number was never a model verdict, so do not let it drive this decision.

---

## 3. Set vs multiset

**Tracker: B-32.** Write-up: `bird-grading-comparison.md` §5.

### What it is

Unordered results are compared with `set()`, so **row multiplicity is ignored**
on every `order: false` phase — 382 of 820. Demonstrated through the real
grader: gold's 15 rows score 1, the same rows duplicated score 1, ×5 score 1,
one row alone scores 0. Dropping rows is caught; only multiplicity is not.

Compounding it, step 1 of grading strips the `DISTINCT` keyword from both
queries, which manufactures duplicates, and then `set()` erases them.
`conditions["distinct"]` is never read.

### Why it matters for lift — and why the obvious fix is backwards

The obvious change is `Counter()` instead of `set()`. **That cuts against us.**
A semantic layer answering at a grain cannot emit duplicate identical rows;
raw SQL mirroring gold's join fan-out can. Measured across all 22 databases:
gold's own result contains duplicate rows on **25 of 810 phases, 12 of them
unordered** — those 12 are exactly where the change bites, and it bites the arm
that de-duplicates by construction.

**Per database, the 12 unordered phases** (the ones where `set()` and
`Counter()` actually disagree). Note how little of it touches what we run:

| database | phases | tasks | Query tasks in db | model deployed |
|---|---|---|---|---|
| disaster_relief | 5 | `_5 _6 _7 _9 _10` | 12 | no |
| mental_health | 2 | `_15` | 20 | no |
| sports_events | 2 | `_4 _13` | 20 | no |
| archeology_scan | 1 | `_2` | 10 | **yes** |
| polar_equipment | 1 | `_2` | 20 | no |
| robot_fault_prediction | 1 | `_6` | 10 | no |

Counting ordered phases too, dup-gold appears in 11 databases (`sports_events`
6, `disaster_relief` 5, `robot_fault_prediction` 3, `crypto_exchange` 2,
`mental_health` 2, `polar_equipment` 2, and 5 databases with 1) — but ordered
phases already fail an exact compare, so they are not where this change lands.

The two phases whose gold answer the DISTINCT strip actually changes are
`fake_account_15` p1 and `museum_artifact_6` p1 — **neither in a database we
have a model for**.

Measured on the DISTINCT strip itself: 89 golds contain `DISTINCT`; stripping it
changes gold's own answer on 2 (`fake_account_15` 46 rows → 2476;
`museum_artifact_6` 545 → 566, and that one *declares* `conditions.distinct:
true`). Over the 23 audited raw submissions containing `DISTINCT`, removing the
strip flips one 0→1 and nothing the other way.

### What can actually be changed

1. **Stop stripping `DISTINCT` from gold, keep `set()`.** The only piece of this
   that plausibly helps the semantic arm: it un-blocks 2 phases where gold's
   graded answer contains fan-out duplicates no semantic layer can produce.
   Neither is in a database we run today.
2. **`Counter()` alone — don't.** Strictly worse for lift, for the reason above.
3. **Both together** (honour `DISTINCT`, compare multisets) is the coherent
   position and the one worth arguing for externally, but it needs measuring on
   new databases before adoption; there is no evidence in the current audit
   either way, because zero submissions in it differ *only* by multiplicity.

**Verdict from this session: lowest-value of the three grading items.** Revisit
only if a new database shows submissions failing on multiplicity.

---

## 4. The knowledge-tools asymmetry

**Tracker: B-12** (P1, open). Flag: `SEMANTIC_LAYER_KNOWLEDGE_TOOLS`, currently
**false**. Code: `system_agent/tools_atscale.py:239-248`,
`system_agent/agent.py:139`, `shared/config.py:225`.

### What it is

The raw backend gets three tools over the task's `external_knowledge` — the
benchmark's glossary of domain terms. The semantic-layer backend gets **none**:
`get_all_knowledge_definitions` is mapped to `get_sml_skills`, which returns
query-construction guidance, not domain definitions.

Measured on the 19-task 0806/0810 pair:

* raw made **148 knowledge/meaning calls costing 80.5 coins — 4.24 per task out
  of an 18-coin budget, 24% of it**
* atscale called `get_sml_skills` **0 times** and had no other route to the
  content

The definitions are not decorative. KB 47 states *Contrarian Value Play* exactly
(price position in 52-week range below 25, turnover under 30%, relative expense
ratio negative) — the same definition M-01 records the model encoding
differently (turnover 0.3 vs 30).

**Per database: this one is near-total everywhere.** Query tasks carrying
`external_knowledge` — i.e. tasks where the raw arm has a channel the semantic
arm does not:

    archeology_scan          10 of 10      crypto_exchange     20 of 20
    exchange_traded_funds    19 of 19      cybermarket_pattern 20 of 20
    households               21 of 21      labor_cert_apps     19 of 19
    solar_panel              20 of 20

Every other database is also 100% except `insider_trading` (18 of 21) and
`museum_artifact` (16 of 20). So unlike items 1–3, the exposure here is not a
handful of tasks — it is **essentially every task in every database**, which is
why the 4.24 coins/task figure matters more than any single task flip.

### Why this is not a straight defect

It is a **scope decision about what is being measured**:

* If the thesis is *"the semantic model replaces external knowledge"*, the
  current split is correct and should be stated as the claim.
* If the thesis is *"semantic layer vs raw schema, knowledge held constant"*,
  the atscale arm is handicapped by 4.24 coins per task and every lift number so
  far understates the model.

Decide that before running anything.

### State of play

Implemented 2026-08-11 behind the flag: tools exported in
`tools_atscale.get_ainteract_tools_atscale`, instruction text appended in
`agent.build_agent` under the same flag (so the agent is never told about a tool
it lacks), costs already present in `callbacks.TOOL_COSTS`. Masking still
applies — `db_environment/server.py:_filter_knowledge` drops every id in
`knowledge_ambiguity.deleted_knowledge`, so turning this on does **not** bypass
the masked-entry test that M-08 protects.

**Temper the expected gain.** B-12's original estimate was two task flips; its
own correction says otherwise. Masking is per task and holes exactly the link
that matters — `etf_9` sees the three components but not the composite (id 47
withheld); `etf_18` sees the composite but not Low-Turnover Strategy (id 12
withheld, where the turnover<30 threshold lives). Each task sees 88 of 89
entries. So the realistic gain is **discovery efficiency and better-targeted
`ask_user` calls**, not two wins.

### How to investigate

This is a **capability change: not re-gradable**. Re-run the atscale arm only —
raw is unaffected, so its stored runs remain valid comparators, provided you
re-grade them onto today's grader first (see §0).

A 7-task A/B was set up on 2026-08-11 against `iter7_postmerge_atscale` — same
commit, same flags, KB tools the only difference. **Baseline to beat: 1.00
total / 0.1429 mean.** Check whether that run completed before repeating it.

Watch for the interaction with **M-25**: ask-trigger language in the model has a
measured opportunity cost, redirecting a fixed ask budget onto conditions the
agent already had right. Knowledge tools change the same budget, so the two
compound and should not be varied in the same run.

---

## 5. Issues in the semantic model itself

Model work lives in **`AtScaleInc/bird-atscale-models`** (single-model repos,
commit to `main`, no branching). Deploy with `scripts/deploy_models.sh` — it
resolves the project by git *remote*, so an unpushed change deploys the OLD
model and still reports success. **Never source the ADK `.env`** for model work.
Every deployed-model change must be recorded in `docs/model-change-log.md` in
the same commit, including by sessions that did not build the model.

`docs/model-change-log.md` also carries a **Workarounds table** — engine defects
the models deliberately work around (E-01, E-02, Q-15, Q-17b, Q-20, Q-21, D-01,
catalog naming). Read it before changing any model; several are load-bearing.

### The open model rows, and what each is worth

| ID | What | Database → tasks | State |
|---|---|---|---|
| **M-27** | `Composite Score (Within Category)` ranks each metric over its own population; gold uses one common population (funds having all three metrics — 997 overall, 42 in Large Value) | ETF → `etf_7` | **Proven exactly at value level, no runs needed.** Most actionable row here. Scores 0.0 in every arm today |
| **M-02** | `Fund Count` ignores metric availability | ETF → `etf_10`, plus an audit of every count measure | Systematic. First audit result landed as M-18 (49 categories on all funds vs 34 on funds carrying a Composite Score); `Fund Category Scored Fund Count` now ships alongside |
| **M-06** | `Secure Income Efficiency Rank` ranks over all funds, not the filtered set | ETF → `etf_1` | **Still reproduces under a new name** (`Fund SIES Rank`) after a redeploy — re-check before assuming fixed |
| **M-01** | Contrarian fund count off by one (turnover 0.3 vs 30 — same definition as B-12's KB 47) | ETF → `etf_18` | Agent behaviour was already optimal; this is purely a model fix |
| **M-07** | `Usable Annual Return Years` name matches the question but drops a condition | ETF → `etf_4` | open, P2 |
| **M-03** | No median measure at the needed grain | ETF → `etf_10` | Model side **done** (percentile metrics, 5e3fbc6) but **blocked by the engine** — see Q-06, percentiles rejected by the dialect. No action available |
| **M-09** | KB-formula measures average over the support set; gold averages over the population | archeology_scan → `_5`, `_9`, partly `_6` | open, P2 |
| **M-11** | `Degradation Risk Zone` uses a substring test where gold uses exact equality that never fires | archeology_scan → `_2` | open, P2 |
| **M-25** | Ask-trigger language redirects a fixed ask budget onto conditions already correct | ETF → `etf_8` measured, `etf_3` same shape; latent on any task touching several trigger-bearing columns | validated, P1 — interacts with §4 |

**Per database rollup:** `exchange_traded_funds` carries 6 of the 9 rows,
covering **6 distinct tasks of its 19** (`etf_1 _4 _7 _8 _10 _18` = 32% of the
database, one of them engine-blocked). `archeology_scan` carries 3 rows over
**3 tasks of its 10** — but see the caution below. No open model rows exist for
`crypto_exchange`, `households`, `labor_certification_applications`,
`cybermarket_pattern` or `solar_panel`; that is a gap in auditing, not evidence
those models are clean — ETF has simply had the most eyes on it.

**Caution on archeology_scan:** M-09 and M-11 name `_2`, `_5`, `_6`, `_9`, and
four of that database's ten tasks are also float32-exposed (§2) with more caught
by defect A. Before investing in those model rows, check whether the task is
winnable at all — §8 of the grading doc puts archeology's structural ceiling
near 30%.

### Engine blockers that cap what the model can do

These are not model bugs but they bound model work, and several are P0:
**Q-24** (any projection omitting the entity key is de-duplicated on the value
tuple — silently), **Q-27** (attribute-only projection has no join path when a
dimension is joined on two different columns), **E-01** (`COUNT(attribute)`
returns members), **Q-15** (`COUNT(DISTINCT)` unreliable three ways), **Q-06**
(percentiles unsupported — blocks M-03), **Q-25** (UNION returns zero rows
silently), **Q-12/Q-20/Q-22/Q-23** (clauses dropped or inverted silently).

**Before concluding "the model is right and gold is wrong", read the dispatched
SQL.** That family of silent rewrites is the most common failure shape in the
tracker and none of it is visible from the result:

    scripts/outbound_sql.py "SELECT ..."        # run, then show what was dispatched
    scripts/outbound_sql.py --query-id <uuid>   # resolve an earlier run_query
    scripts/clause_fidelity.py                  # sweep for dropped clauses

Both are MCP-only — no LLM calls. Clause fidelity is necessary, not sufficient:
the engine can preserve every clause and still resolve it at the wrong grain
(Q-24 is invisible to it and shows up only as two different numbers).

### Why this section is where the lift is

Items 1–3 are worth at most a phase or two each and several are already spent.
Every row in the table above is a **task the semantic arm loses outright**, and
the six ETF rows cover 6 of 19 tasks — **32% of that database**. Model fixes
also compound with §4: better definitions reduce the ask budget the knowledge
tools would otherwise have to buy.

The constraint is verification cost: a model change needs a re-run of the
atscale arm to show up in a score, at ~$0.35/task with caching, and n≥2 for
variance. Fix in batches, not one row at a time.
