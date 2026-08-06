# BIRD-Interact exchange_traded_funds AtScale Semantic Model — Build & Refinement Log

*Evaluation session notes by Dianne Wood (with Claude Code). What broke, why, and what it cost,
running the BIRD-Interact benchmark against an AtScale semantic layer over the
exchange_traded_funds database. Updated 6 August 2026.*

---

## Part 1 — Model creation

### 1.1 — The model these findings describe

**Its build prompt was not recorded.** Nothing in this repo documents how the ETF semantic
model under test was created. That is a real gap: the model cannot be reproduced or audited
from source, and we cannot say whether it was built without reference to the benchmark's gold
SQL — which matters, because a model built with sight of the answer key would inflate every
number in Part 3.

Every model-side defect in §2.4 and §2.5 was found *after* the build, by comparing model output
against gold in Postgres. That is a legitimate debugging step and it works. What we cannot
currently prove is that the build itself stayed clean.

### 1.2 — Rebuild in progress (2026-08-06)

A second ETF model is being built from a single recorded prompt, using the MCP server's tools
and SML authoring skills, into `diannewood/bird-etf-prompt-only`. It will be run against the
same benchmark to see whether it behaves like the model described here. Verbatim:

```
Build an AtScale semantic model over the BIRD-Interact data in
/Users/dianne/go/src/github.com/BIRD-Interact/bird_interact_agent/data/bird-interact-full.
Target the exchange_traded_funds database through the bird_exchange_traded_funds connection,
in a new repo at /Users/dianne/go/src/github.com/diannewood/bird-etf-prompt-only
(label "Exchange Traded Funds").

Build from these, verifying everything against the live database — the metadata files drift,
so live wins:
- exchange_traded_funds_schema.txt and _column_meaning_base.json. Profile the live tables
  yourself and fold what you find into the descriptions.
- exchange_traded_funds_kb.jsonl — every business definition in the file, no exceptions,
  including any that individual tasks hide. Where the engine can't express one inline, say so
  rather than approximating silently. The definition strings are LaTeX that lost its
  backslashes to JSON unescaping: raw control characters stand where escape sequences belong
  (0x09 for \t as in \text{}, 0x0C for \f as in \frac{}, likewise \n \r \b). Convert them back
  before parsing or many formulas read as garbage.
- The natural-language questions in bird_interact_data.jsonl (filter on selected_database),
  for naming, synonyms, and coverage: amb_user_query, follow_up.query, category, output_type,
  high_level, follow_up.type, external_knowledge, and the term/type/is_mask of each entry in
  knowledge_ambiguity and user_query_ambiguity. Don't hard-code any single task's thresholds
  or column picks. Where a term is genuinely ambiguous, ship a candidate object per reading,
  each description naming the alternative.

Build only from the sources named above. Do not read any other semantic model on this
machine — in particular nothing under /Users/dianne/go/src/github.com/AtScaleInc/ or
/Users/dianne/go/src/github.com/diannewood/ other than the repo you are creating, and not
their git history either. If you open one by accident, say so in your report.

Anything answer-bearing in that JSONL is out of bounds while modeling: sol_sql and
follow_up.sol_sql, sql_snippet on any ambiguity entry in either ambiguity block, test_cases
and conditions (top level and inside follow_up), preprocess_sql, clean_up_sqls. The cleanest
guarantee is to extract the permitted fields into a brief up front and model only from the
brief, so the gold answers never reach your context at all. Tell me which approach you took.
Gold SQL is fair game only later, if I ask you to diagnose specific failing tasks — never
folded back into the build.

Modeling rules:
- An attribute that describes an entity goes on that entity's dimension, so it conforms
  wherever the entity does — not on the fact or derived table that computed it. Degenerate
  dimensions are for genuinely fact-grain attributes only.
- Set unrelated-dimensions handling explicitly on every measure; never inherit the default.
  A pairing that silently returns empty is worse than one that errors.
- Expose the ranks and orderings that superlative and top-N questions need, at each grain they
  could ask about, stating sort direction, null placement, and tie convention.
- Ship group-level and entity-level versions of the same statistic as separate, separately
  named objects.
- Label text belongs to the caller, not the model. Where a definition sorts entities into
  named buckets, expose the pieces the bucketing is built from — the deltas, the threshold
  comparisons, a boolean per condition — so any wording can be assembled on top. If you also
  ship a ready-made classification for convenience, say in its description that its label
  strings are this model's own convention and the caller should re-label to whatever the
  question asks for. Never let the model be the only place a bucket's output text is decided.
- Every measure and attribute description carries: formula and provenance, units and scale,
  live null and coverage counts, disambiguation from near-twins, and the paraphrases someone
  would actually ask with. Descriptions on objects the discovery API doesn't expose don't
  count. The model's own description should be an orientation guide, not a one-liner.

Environment: the engine connection-group bird_exchange_traded_funds already exists. Pick a
catalog name that isn't already deployed on the engine — bird_exchange_traded_funds_catalog is
taken. The source database is Postgres in docker container bird_interact_postgresql_full on
localhost:5433, user root, password 123123 — that's what the exactness cross-checks run
against, and psql -tAc returns only the last result, so send one statement per call. Deploy
with ATSCALE_API_URL=http://local.atscaleinternal.com:3001 and the bearer from
.mcpServers["atscale-local"].headers.Authorization in
/Users/dianne/go/src/github.com/AtScaleInc/mcp/.mcp.json.

Then: a deterministic, re-runnable generator script; follow the SML authoring skills from
get_sml_skills; sml-cli validate clean; commit and push before deploying (deploy resolves the
model from the git remote); deploy.

Not done until all four pass, and I want the evidence:
1. Exactness. Smoke queries through the model exact-equal to the same query run on the source
   database. This data is synthetic — never judge a result by whether it looks plausible.
2. Conformance. Per dimension, one measure-by-attribute query per fact that dimension should
   reach, returning non-empty. Empty or erroring is a model bug, not a limitation to document.
3. Discoverability. Search the deployed model with question-style paraphrases only, never an
   object's own name; the intended object must surface. If it doesn't, fix the description.
4. Coverage. One passing query per question shape: group aggregate, filter-by-classification
   then measure, superlative/top-N, cross-fact, entity-level detail, group-relative
   comparison. Close any gap or tell me explicitly what you left out.

Keep everything parameterized by database name. Run unattended.
```

**What this prompt is actually testing.** Read against Part 2, it is close to a distillation of
the model-side findings into build-time constraints. Each of these targets a defect we found by
running the benchmark:

| Prompt rule | Defect it pre-empts |
|---|---|
| "Expose the ranks and orderings superlative and top-N questions need, **at each grain**" | M-06 — rank measure computed over all 2310 funds, useless once filtered |
| "Ship group-level and entity-level versions of the same statistic as separate objects" | M-03 — median exposed only at family grain, not re-aggregable to group grain |
| "Label text belongs to the caller, not the model" — added 2026-08-06 | M-04 — model owns a classification vocabulary that can't match gold's |
| "Descriptions carry … **disambiguation from near-twins**, and the paraphrases someone would actually ask with" | M-07 — measure name matches the question but drops a qualifier |
| "Set unrelated-dimensions handling explicitly on every measure; a pairing that silently returns empty is worse than one that errors" | the silent-empty half of §2.1 |
| Verification gate 1: "never judge a result by whether it looks plausible" | §2.1 as a class — the defects that return plausible wrong answers |
| Verification gate 3: search with question-style paraphrases, fix the description if the object doesn't surface | Q-16 — discovery starvation, from the model side |
| Gold-SQL quarantine | the §1.1 provenance gap itself |

**What it cannot reach, and why the comparison will still be partial.** The four remaining P0s
(Q-02, Q-03, Q-14, Q-15) are engine and dialect defects. No model, however built, changes them.
Likewise B-03 and B-04 are properties of the benchmark's own gold SQL. If the new model scores
similarly, that is the expected result and not a null finding — it would confirm that the
ceiling is engine-side rather than model-side, which is currently our central claim and is
so far only inferred from the defect distribution.

> **A design constraint the rebuild must respect: the model cannot own output vocabulary.**
>
> etf_6 needs a classification column emitting exactly `'Drifted'` / `'No Significant Drift'`.
> The KB carries the logic — *"A fund is considered to have drifted if its absolute Beta change
> exceeds 0.15 or its absolute R-Squared change exceeds 10"* — so a clean build recovers the
> thresholds, and the follow-up question names the column, `drift_analysis`, from a permitted
> field. **But the two literal strings appear only in gold SQL and in
> `user_query_ambiguity[].sql_snippet`, all of which this prompt puts out of bounds.** No
> gold-clean build can know them.
>
> **That is correct, and the model should not try.** Probed live 2026-08-06, the user simulator
> discloses both labels verbatim on a single pointed ask (§2.4). The labels are *dialogue*
> knowledge, not model knowledge. A model that hard-codes any fixed vocabulary here — including
> the right one — is answering a question the user is supposed to be asked.
>
> So the check on the rebuild is not "does etf_6 pass" but **"does the model ship a fixed
> classification vocabulary at all?"** It should expose the drift components and let the caller
> label them. If the new model passes etf_6 by emitting gold's exact strings, ask where they
> came from — no permitted source contains them.

---

## Part 2 — Defects found after the initial build

37 issues tracked. The distribution is itself the headline finding:

| Category | Count | P0 | What it is |
|---|---|---|---|
| **Q — query engine / MCP** | **16** | **4** | SQL dialect gaps, silent wrong answers, discovery tools |
| B — benchmark / harness | 10 | 1 | Grading semantics, budget accounting, user simulator |
| M — semantic model | 7 | 0 | Measures that disagree with gold |
| A — agent behaviour | 3 | 0 | Question form, nondeterminism |
| C — model generator | 1 | 0 | Cosmetic |

Only 7 of 37 issues are model defects. Sixteen are engine or MCP defects, and **all four
remaining P0s are engine defects.** The ETF task set leans heavily on compositional SQL —
ranked lists, delimited aggregates, filtered counts — which is exactly the surface where this
dialect is thinnest. A colleague whose task set is more aggregate-and-group-by shaped should
expect a different balance.

### 2.1 — Silent non-aggregation (the dominant and most dangerous class)

Four separate constructs accept a query, return a plausible result, and are wrong. No error, no
warning. Because grading is an exact row compare, each scores 0 and reads in the trajectory
like an agent reasoning mistake.

- **`COUNT(<dimension>)` returns the member, not a count — and silently drops the `GROUP BY`**
  (Q-02, P0). `SELECT "Fund Ticker", COUNT("Fund Ticker") … GROUP BY "Fund Ticker"` returns
  `{"Fund Ticker":"DMRI","cnt":"DMRI"}`. Grouping by `"Exchange"` returns ~2300 rows, one per
  fund, instead of 4. The second half is what actually misled the agent in etf_5 and etf_6: it
  read cardinality off a result set that had been un-grouped behind its back.
  `COUNT(DISTINCT <dim>)` is correct in every form tested.
- **`COUNT(DISTINCT <dim>)` returns null under some measure predicates** (Q-15, P0). With
  `WHERE "Secure Income Efficiency Score" > 20` the count is null, and adding a `GROUP BY`
  returns zero rows — while listing the same rows under the same filter returns 26. It is
  predicate-dependent (`> 0` gives a correct 389), so the agent cannot learn a rule. Q-02
  established `COUNT(DISTINCT <dim>)` as the *only* trustworthy counting form; this removes it
  under measure filters.
- **`ARRAY_AGG` is accepted but does not aggregate** (Q-14, P0). Returns one row per input row
  instead of one row containing all values — 27 rows of `{"s":"<ticker>"}` where one was asked
  for.
- **An inner `ORDER BY` is stripped when the derived table has no `LIMIT`** (Q-12, P1).
  `RemoveInnerOrderBy.scala:19` drops the ordering whenever `order.nonEmpty && limit.isEmpty`,
  silently. This is the failure mode of the Q-03 workaround below if the agent omits the inner
  `LIMIT`: a correct query becomes a wrong answer with nothing surfaced.

> **Takeaway for colleagues**
>
> This class costs far more than the loud errors. A loud error is one wasted coin and a retry;
> a silent wrong answer is a failed task that looks like the agent's fault. Budget explicit
> live probes: for every aggregate the model exposes, run it grouped, ungrouped, and under a
> measure filter, and check the row *count* changed the way you expect. Do not trust that a
> query which returned rows returned the right rows.

### 2.2 — Compositional SQL is close to unavailable

No CTEs. `IN (SELECT …)` rejected (Q-13). That leaves derived tables as the only compositional
construct — and derived tables carry three defects of their own (Q-03, Q-04, Q-12), which is
why those rate higher than their individual severity suggests.

- **`ORDER BY` an unprojected measure fails** (Q-03, P0): *"Could not find correct column to
  sort by."* A workaround exists, confirmed across 17 probed shapes — project the sort key in a
  derived table, keep `ORDER BY` **and** `LIMIT` inside it, project the wanted columns from
  outside. Root cause located: `PGSqlLanguage.scala:928-950` resolves the sort term only
  against the projected select list. It cannot simply be relaxed —
  `VirtualCubeBuilder.scala:390-402` throws `Missing order by expression` unless the sort column
  is projected. The real fix is in `processSelectStmt` (~:1070): synthesize the sort expression
  as a hidden select column and wrap in an outer projection, i.e. generate the workaround shape
  automatically.
- **Outer reference to an unprojected column** (Q-04, P2): *"Unmatched physical type
  AttributeValue(FlatAttribute(…))"*. Scoped to the outer-reference form only, so it does not
  close the Q-03 workaround. A 2026-08-04 variant is worse: joining against a derived table
  that groups a measure raises the same error naming an engine-generated `__COUNTATTRNAME__`
  attribute — which the agent *cannot* project, making the rule the error enforces
  unsatisfiable. Cost etf_5 its phase-2 credit.
- **Dimension filter in a subquery rejected** (Q-05, P1): a `HAVING`/`WHERE` on a dimension
  projected by an inner derived table returns *"One or more constraints have been incorrectly
  constructed."* Three occurrences in etf_14; cost that task its phase-2 credit.
- **`IN (SELECT …)` rejected** (Q-13, P3): the agent must run the inner query, read the members,
  and paste them back as literals. It works — etf_5 pasted 10 tickers and scored 0.3 — but
  scales badly: a top-100 follow-up would need 100 literals. Low severity only because the
  error message names the workaround explicitly.

> **Takeaway for colleagues**
>
> The compound failure is the one to watch, and it is invisible from any single defect. etf_1
> phase 2, 2026-08-04: the Q-03 workaround requires projecting the sort key, which made the
> result one column wider than gold, which failed the exact-column-set grading rule — two
> charged submits and the budget driven to −1. The documented workaround and the grading rule
> are individually reasonable and jointly fatal. Write the derived-table form (sort key inside,
> outer SELECT projecting only gold's columns) into the system prompt explicitly, for the
> phase-2 shape as well as phase 1.

### 2.3 — Hard expressiveness ceilings

Two functions gold depends on have no expressible equivalent, making the tasks unwinnable
rather than merely awkward:

- **No string aggregation** (Q-14, P0). `string_agg`, `listagg`, `group_concat` all rejected
  with *"Don't understand function"*; `ARRAY_AGG` accepted but broken (§2.1). etf_3's phase-2
  gold **is** `STRING_AGG(f.tickersym, ', ' ORDER BY f.tickersym)`, and the follow-up asks in
  words for the tickers "in a single text field". No query shape on this backend produces that.
  etf_3 caps at 0.7 until the engine supports it.
- **`percentile_cont` / median unsupported** (Q-06, P2). Gold uses
  `percentile_cont(0.5) WITHIN GROUP` and the simulator explicitly asks for a median in etf_10.
  Combined with M-03 there is no path to the right answer. AtScale's `Percentile` is the likely
  substitute but is not reachable through the SQL dialect today.

### 2.4 — Model measures that disagree with gold

- **Off-by-one from definition drift** (M-01): `"Contrarian Value Play Fund Count"` returns 52,
  gold returns 53. Root cause is B-03 — the measure implements a blend of two incompatible gold
  definitions.
- **Counts that ignore metric availability** (M-02): the model reports 814 Opaque / 1496
  Transparent; gold counts only funds with a numeric `Return_1Y`, giving 671 / 1246. Any task
  pairing a count with a metric disagrees with gold. **Every `*_Fund Count` measure needs the
  same audit** — this is systematic, not a one-off.
- **A metric never modeled at the needed grain** (M-03): etf_10 needs a median 1Y return per
  transparency group. The model exposes `Median Return 1Y By Family And Transparency` — family
  grain, which cannot be re-aggregated into a group median (averaging it gives 0.152/0.442
  against gold's 0.057/0.410).
- **Vocabulary mismatch on a classification column** (M-04): the model emits `Beta Drift Only` /
  `Correlation Drift Only` / `Both Beta and Correlation Drift` / `Insufficient Data`; gold emits
  only `Drifted` / `No Significant Drift`. An agent that uses the model's pre-built attribute
  can never match. **Previously filed as making etf_6 structurally unwinnable — that was wrong,
  and refuted 2026-08-06** (see the takeaway below). It is a real model defect at the wrong
  layer, now repointed model → agent and downgraded P1 → P2.

> **Takeaway for colleagues — output vocabulary belongs in the dialogue, not the model**
>
> `"summary"` is a **labeled critical ambiguity**, which in BIRD's design means it is meant to
> be resolved by asking. `user_simulator/server.py:43` dumps the entire `user_query_ambiguity`
> JSON — `sql_snippet` and its literals included — into the phase-1 prompt, and `[[GT_SQL]]`
> (`prompts.py:57`, `:188`) carries the same strings in both phases. `is_mask` appears **nowhere
> in the Python** and gates nothing.
>
> Probed live 2026-08-06, three independent single-question asks, each returning the labels
> verbatim:
>
> - *"what exact text … for a fund whose risk profile has NOT changed significantly?"* →
>   *"the summary should display **"No Significant Drift"**"*
> - *"what exact label text should the summary column contain?"* → *"one of two labels:
>   **"Drifted"** … or **"No Significant Drift"**"*
>
> This is structurally **the same problem as M-06**, and it has the same fix. There, the model
> shipped a pre-built rank whose semantics didn't match the task, and the answer was not to
> correct the rank — it was `7ac7b29`, prompting the agent to compute `RANK()` itself. Here the
> model should expose the drift *components* and let the agent build the `CASE`, asking the user
> for the label text. A model that hard-codes any fixed vocabulary is answering a question the
> protocol reserves for the user.
>
> **Scope check.** Scanning all 28 ETF golds for output-bearing string literals (`CASE
> THEN/ELSE`, `UNION ALL SELECT '<label>'`) found only three tasks emit any: etf_6; etf_10
> (`'Transparent'`/`'Opaque'`, both recoverable from the KB); and etf_4, a false positive whose
> `'up_year'`/`'down_year'` live in a CTE referenced only by `FILTER (WHERE …)` and never reach
> a result cell — consistent with etf_4 passing at 1.0. **etf_6 is the only real case**, so this
> is a one-task fix, not a class-wide prompt rule.

### 2.5 — Naming traps: the measure whose name matches the question but not the meaning

A distinct failure mode from a wrong measure, because nothing signals the mismatch — the agent
behaves optimally and still loses:

- **`Secure Income Efficiency Rank` ranks over all 2310 funds** (M-06), so filtering to premium
  funds yields a gapped sequence (1..12, 14, 15, …) where gold expects a dense within-filter
  rank. The name matches the question's vocabulary exactly, and the Score column's remark
  actively points at it: *"for the ordering use Secure Income Efficiency Rank."* Cost etf_1 its
  last two submits. Mitigated by prompting the agent to compute `RANK()` over the filtered rows
  itself (`7ac7b29`).
- **`Usable Annual Return Years` omits gold's qualifier** (M-07). The name mirrors the
  simulator's phrasing for etf_4's "enough history", but counts usable years overall and drops
  gold's "in both market conditions". Yields 452 funds against gold's 142, with no error.
- **`*_Flag` columns typed as strings** (M-05 / Q-10): `flag = 1` raises *"operator does not
  exist: character varying > integer"*, so agents alternate between `1` and `'1'` across submits
  with no signal about which is right.

> **Takeaway for colleagues**
>
> A measure whose name matches the question's vocabulary will be picked, and a remark that
> qualifies it will not save you — M-06's remark *does* say "across ALL funds" and the agent
> picked it anyway. Either rename to state the qualifier, or ship the variant the task actually
> needs. Model the benchmark's assumption, not reality's, and make the *name* carry the
> distinction.

### 2.6 — Discovery tool defects

`explore_columns` failed in both directions within two days, which is worth recording as a pair:

- **Before `0cb6ae9`** (Q-01): a bare-string `search_terms` was tokenised on whitespace and
  OR'd, so `'premium fund'` matched almost everything — 86,794 characters, burying the answer.
  Worked around harness-side by wrapping the string as a single phrase.
- **After `0cb6ae9`** (Q-16, P1): terms longer than about three words now match *nothing*.
  `['up market down market outperformance']` returns "No columns matched";
  `['up market','down market']` returns exactly the 3 needed columns in 1,490 characters.
  **13 of 18 `explore_columns` calls in etf_4 returned nothing — 13 coins — leaving budget for a
  single submit and taking the task 0.7 → 0.0.**
- **`focus_columns` has no fuzzy match** (Q-11): an inexact name is rejected and charged.

The server should rank partial matches rather than choosing between everything and nothing. See
Part 4 — this is not just a defect, it is the budget story.

### 2.7 — Harness / evaluation-side fixes

Separately from the model, the harness needed corrections. Most are *grading and budget
semantics*, and three turned out to be deviations from upstream BIRD-Interact that needed gating
rather than fixing.

**Prompt and behaviour fixes:**

1. `0cb6ae9` — coerce `explore_columns` `search_terms` string → list (Q-01).
2. `858372b` — document the `COUNT`-over-dimension trap and the `ORDER BY` dialect trap.
3. `a143154` — read a column's description before submitting it (mitigates M-06, M-07).
4. `7ac7b29` — compute `RANK()` over the filtered rows, not a pre-built rank column (M-06).
5. `3150af6` — `ask_user` after a rejected submit instead of guessing again.
6. `945567a` — refuse bundled `ask_user` questions free of charge (B-02).
7. `24c7a28` — one ambiguity per `ask_user`; demand unstated cutoffs (B-02).
8. `d948c37` — `diagnose_rows` distinguishes wrong column *order* from wrong values (B-07).
9. `4065fbf` — config-driven error hints; correct the sort-column error for atscale (Q-03).

**The B-02 result is the one to copy.** It was originally filed as a BIRD data defect on the
premise that gold's magic constants (`LIMIT 100`, `HAVING COUNT(*) > 25`, …) are absent from
both the prompt and the dialogue. **That premise was false and we had written it.** Probed live
against the running simulator, all six constants were disclosed exactly on a single pointed ask
— including etf_19's `LIMIT 1`, which is not even annotated. They are reachable three ways
over: as labeled critical ambiguities, via the full ambiguity JSON that
`user_simulator/server.py:43` dumps into both prompt stages, as `SQL_Glot` clause segments, and
via `[[GT_SQL]]` in the response-generator prompt.

The real defect was **agent-side question form**: the simulator's stage-1 action parser emits
one `labeled(term)` per turn, so a bundled multi-part question gets its first part answered and
the rest comes back as hedging. etf_5 had asked "how many funds?" and "what info?" together and
received gold's exact column list plus *"a reasonable sample size"* in place of the `LIMIT 100`
it needed. After `945567a` + `24c7a28`, etf_5 asked one pointed question, received *"I want to
see the top 100 funds"*, and passed phase 1 for the first time.

> **Takeaway for colleagues**
>
> Before writing a task off as a benchmark limitation, ask the running simulator the pointed
> single question directly. It is a two-minute check, and here it moved a task from "unwinnable"
> to passing — against our own written-down belief.
>
> A known hole remains: a two-part question written with one "?" passes the guard. etf_3 asked
> *"a specific minimum value, or should I use top N?"*, got "out of scope", and paid 2 coins.

**Upstream deviations — gated, not fixed** (`30282ea`). Three behaviours differed from reference
BIRD-Interact. All are now config flags defaulting to upstream behaviour, and every results JSON
records which were on:

| Flag | Upstream | Ours when enabled | Blast radius |
|---|---|---|---|
| `grading_tie_tolerance` | bare `predicted == ground` | forgives a tie-only permutation when gold's `ORDER BY` key has ties | all tasks |
| `grading_honor_decimal` | always rounds to 2 | honours each task's declared `conditions.decimal` | 125 of 600 tasks (21%); 11 of 28 ETF |
| `free_wasted_actions` | charges by action type, never inspects outcome | duplicate submits and bundled questions refused free | a-interact only |

Two adjacent findings resolved during the same audit:

- **B-09 was a real local bug, and fixing it restored parity.** `conditions.decimal = -1` means
  "unspecified" (377 of 600 tasks) but was passed straight to `round()`, meaning *round to the
  nearest 10*. On the raw path both sides rounded symmetrically so wrong answers **passed** (gold
  1004.0 vs predicted 999.0 scored 1); cross-source the two sides rounded to different spellings
  so correct answers **failed** — feeding gold rows back as a prediction scored 0 on all 5 ETF
  tasks. Upstream never reads the field at all, so our `-1 → 2` fallback now agrees with it.
- **B-06 is by design, not our bug.** Exact-tuple column-set comparison is what the reference
  does (`test_utils.py:245-250`). Closed as won't-fix. Column *position* (B-07) is separate,
  still open, and currently the sole remaining blocker on etf_1 phase 1.

> **Takeaway for colleagues**
>
> If you change grading, gate it and record it per run. We found three ungated deviations only
> by checking out the reference implementation and reading it — two were ours, and one
> (`167a940`) changed verdicts globally. A totals number should never travel without the regime
> that produced it.

---

## Part 3 — Results

**No raw text-to-SQL control arm has been run.** Every number below is an AtScale-arm absolute
score with nothing to be a lift over, so none of it answers "does the semantic layer help?".
Building that arm is the single highest-value missing piece of this study.

### Full ETF task set, 2026-07-31 (19 Query-category tasks)

| Metric | AtScale | Raw baseline |
|---|---|---|
| Phase 1 pass rate | 31.6% (6/19) | **not run** |
| Phase 2 pass rate | 26.3% (5/19) | **not run** |
| Average reward | 0.300 | **not run** |

This predates roughly ten fix commits and should be re-run before it is quoted anywhere.

### Five-task development subset, run history

Same 5 tasks (`exchange_traded_funds_1`–`5`), code differing only where noted:

| Run | Date | Total /5 | Notes |
|---|---|---|---|
| followup_full | 07-31 | 1.0 | |
| 08-03 a–f | 08-03 | 2.0, 2.0, 1.0, 2.4, 1.4, 2.4 | prompt fixes landing through the day |
| 08031728 | 08-03 | 2.7 | |
| **08041128** | **08-04** | **4.1** | first 5/5 phase 1; includes the B-02 mitigation |

Latest run detail — phase 1 **5/5**, phase 2 **2/5**, average reward 0.82:

| Task | Phase 1 | Phase 2 | Reward | Phase-2 blocker |
|---|---|---|---|---|
| etf_1 | pass | fail | 0.7 | Q-03 workaround widened the result → B-06; budget to −1 |
| etf_2 | pass | pass | 1.0 | — |
| etf_3 | pass | fail | 0.7 | Q-14 — gold *is* `STRING_AGG`; unwinnable |
| etf_4 | pass | pass | 1.0 | — |
| etf_5 | pass | fail | 0.7 | Q-04 `__COUNTATTR__` variant |

### Three caveats that must travel with these numbers

1. **`submit_feedback_level` was `shape`, not `none`.** The run told the agent row/column counts
   and whether rows matched but order didn't. Upstream's protocol is `none` — the 3-coin charge
   *is* the penalty for guessing. **These scores are not comparable to published BIRD-Interact
   numbers**, independent of anything else.
2. **The `deviations` block is absent from this run** (recording landed in `30282ea`, after it).
   `grading_honor_decimal` was effectively on, affecting 11 of the 28 ETF tasks.
3. **n = 1, against a measured ±1.0 swing.** See below.

### Run-to-run nondeterminism is large enough to swamp single-run deltas

Tracked as A-03, raised to P1 because it blocks measuring every other fix. With **no code change
at all**, etf_4 went 1.0 → 0.0 → 1.0 across consecutive runs, the agent building a different
(self-join over aggregated measures) formulation each time. Five-task totals swing a full point
on user-simulator wording and column-choice luck alone.

Most instructive case: **etf_1 phase 1 flipped 0 → 0.7 with nothing in the codebase touching
column ordering.** In `08031728` it emitted ticker/name/score/rank against gold's
ticker/name/rank/score and scored 0; in `08041128` it happened to emit gold's order and passed.
Neither `945567a` nor `24c7a28` touches ordering. **That is not a fix, it is a coin flip**, and
the 3/5 → 5/5 phase-1 improvement is therefore only partly attributable to the B-02 work.

Run n = 3 before crediting any delta — including the forthcoming comparison against the
rebuilt model, where a one-run difference of ±1.0 would be indistinguishable from noise.

### Unwinnable-by-construction tasks

Distinct from "hard": no model change, prompt change, or agent improvement reaches these. Any
headline pass rate should state them, because they set the ceiling.

| Task | Blocker | Why unreachable |
|---|---|---|
| etf_3 (phase 2) | Q-14 | gold is `STRING_AGG`; no engine equivalent |
| etf_10 | M-03 + Q-06 | no median at the needed grain, and `percentile_cont` unsupported |
| etf_11, etf_12 | B-04 | gold is `(SELECT … LIMIT 10) UNION ALL (SELECT '<label>', <agg>::text)` — a ranked table with a summary row appended, every value coerced to text |
| etf_9 *or* etf_18 | B-03 | "contrarian value play" is defined two incompatible ways across the two golds (53 funds vs 145); one is guaranteed to fail whatever the model encodes |

On the 5-task subset this caps the achievable total at **4.7 / 5.0**, not 5.0.

**etf_6 was removed from this list on 2026-08-06.** It was listed on the strength of M-04's
vocabulary mismatch; probing the live simulator showed the labels are disclosed on a pointed ask
(§2.4), making it winnable for the price of one 2-coin question. That is twice now — B-02 was the
first — that a task written off as structurally unwinnable turned out to be recoverable in
dialogue. **Probe before you write one off.**

---

## Part 4 — Product improvement opportunities

### Finding 1: discovery costs more round-trips than raw SQL exploration, out of the same budget

Both backends charge similar per-call prices (raw `get_schema`/`execute_sql` = 1.0 each; AtScale
`list_models`/`explore_columns`/`run_query` = 1.0, `focus_columns` = 0.5). The difference is not
price but shape: **AtScale's discovery tools are metadata-only and never touch real data**, so
confirming a hypothesis needs a separate `run_query` afterwards. Raw's `execute_sql` does both at
once — an ad-hoc `SELECT DISTINCT` probe explores *and* validates in one call. AtScale
structurally needs more sequential round-trips to reach the same confidence, and each comes out
of the budget that would otherwise fund retrying a wrong first attempt.

Our sharpest data point is stronger than a round-trip count, because the calls returned
*nothing*:

| Task | Discovery spend | Outcome |
|---|---|---|
| **etf_4** | **13 of 18 `explore_columns` calls returned "No columns matched" — 13 coins** | budget left for one submit; task went 0.7 → 0.0 |
| etf_1 | one `explore_columns` returned ~109k characters of noise (pre-`0cb6ae9`) | guessed column names instead of reading them |

> **Suggested product direction**
>
> Since `list_models`/`explore_columns`/`focus_columns` never touch the warehouse, price them
> separately from data-touching calls, or bundle sample data into the discovery response so
> agents need not spend a separate `run_query` to sanity-check a hypothesis.
>
> Independently: **`explore_columns` should rank partial matches rather than choosing between
> everything and nothing.** Q-01 and Q-16 are the same tool failing in opposite directions two
> days apart. A tool returning 86k characters of noise and a tool returning "No columns matched"
> are both unusable, and partial-match ranking is one change addressing both.

### Finding 2: silent wrong answers are a product problem, not just a defect list

Four constructs (§2.1) accept a query and return a wrong result with no error. From the harness's
side these are indistinguishable from agent reasoning failures, which means **they depress
measured semantic-layer quality while being invisible in the failure logs.** We only found them
by feeding gold rows back through the engine and noticing the mismatch.

`RemoveInnerOrderBy` is the clearest instance of a fixable principle: dropping an ordering the
caller explicitly asked for should, at minimum, be surfaced as a warning. Silence converts a
recoverable error into a wrong answer.

### Finding 3: error messages that name their workaround pay for themselves

A natural experiment inside our own tracker. Q-13 (`IN (SELECT …)`) is rated **P3** despite
blocking a common pattern, purely because its message says *"Rewrite it with an explicit value
list, e.g. col IN (v1, v2, …)"* — the agent self-corrected on the next turn, cost 1 coin. Q-03 is
rated **P0** for a comparable dialect limitation whose message is *"Could not find correct column
to sort by"* — naming neither cause nor fix, and costing 12 coins across the 07-31 run in submits
that never executed.

> **Suggested product direction**
>
> Same class of limitation, two severities, and the only difference is the error text. Auditing
> dialect rejection messages so each names its supported alternative is cheap and measurably
> reduces wasted budget. We have implemented this harness-side as a stopgap — `4065fbf` adds
> config-driven `error_hints` that append the derived-table repair when the sort-column error
> matches — but that is a workaround for a message the engine should produce itself.

---

## Part 5 — Comparison with the solar_panel log

David Mariani's solar_panel log covers the same harness and protocol on a different BIRD
database. Read together, three things stand out.

**1. The two logs answer different questions, and his is the one with a lift number.** His is a
model-building log ending in a raw-vs-AtScale comparison: 20 tasks, average reward 0.255 → 0.510,
a clean 2.00x across every headline metric. Ours is a defect log with no control arm. His result
is the publishable one; ours explains what is capping it. Our Part 3 gap is the direct
consequence.

**2. The centre of gravity is inverted, and that is informative.** His six model-defect sections
carry the weight, with dialect issues as a ten-item list at the end. Ours is 16 engine/MCP issues
to 7 model issues, with all remaining P0s engine-side. Either the ETF model is better built, or —
more likely — the ETF task set reaches compositional SQL that solar_panel's does not. **A
colleague starting a third database should budget for both shapes**, because which log their
experience resembles depends on their task set.

**Independently confirmed in both databases** — treat these as generalizing:

| Finding | solar_panel | ETF |
|---|---|---|
| Silent non-aggregation of measures | §2.1, §2.7.8 | Q-02, Q-12, Q-14, Q-15 |
| Model formula disagrees with gold | §2.2 (629.11 vs 639.47) | M-01 (52 vs 53) |
| KB metric never modeled | §2.3 | M-03 |
| Counts over a non-unique or partial key | §2.4 | M-02 |
| No CTEs; `COUNT(*)` rejected; 3-part name; `IN (subquery)` | §2.7.1/2/3/7 | Q-09, Q-08, Q-13 |
| Discovery round-trips consume the task budget | Part 4 | Q-16, B-01, Part 4 |

That last row is the strongest convergence: two teams, two databases, two different routes to
the same conclusion. His route was tool-call accounting (task 5: 14 discovery calls against 1
`run_query` and 1 `submit_sql`, no budget left to fix a typo'd column name); ours was a discovery
tool that stopped returning matches (etf_4, 13 empty calls). Same outcome, opposite proximate
cause.

**3. Four things in his log we have not applied here:**

- **Pre-computed flag attributes for named KB concepts** (his §2.5) — the technique credited in
  §2.4 above. He confirmed live that the agent reads the description and still builds
  multi-condition OR/AND logic wrong. This would fix M-04 and B-03 and is the highest-value
  unapplied item in either log.
- **Primary-vs-bridge join attribution** (§2.6) — gold assumes one panel model per plant; the
  many-to-many bridge is "more correct" but wrong for the benchmark. No ETF analogue, but the
  same genus as our M-06/M-07 naming traps.
- **Two-layer validation** — `sml-cli validate` catches none of this; only live `run_query` does.
  Now encoded as the four verification gates in the §1.2 rebuild prompt.
- **Four dialect rules we have not recorded**: cross-joining two aggregated derived tables → use
  scalar subqueries; `CASE` inside an aggregate → move the condition to an inner `WHERE`;
  `HAVING` must repeat the full expression, not the alias; and forcing natural row grain before
  averaging a calculated metric, which otherwise silently returns the aggregate of pre-aggregated
  inputs.

**Two cautions worth sending back:**

- **His n = 1 per arm.** A-03 quantifies our swing at ±1.0 on a 5-task total with no code change.
  A 2x gap at 20 tasks per arm is probably real, but its *roundness* is coincidence, and his
  task-5 flip is exactly the phenomenon A-03 tracks — correctly identified there as sampling
  variance, worth quantifying because it bounds what any single run can claim.
- **His "both fail" bucket may be partly recoverable.** He attributes solar_panel tasks 2 and 15
  to masked KB constants garbled by the user-simulator paraphrase. That was our B-02 hypothesis
  too, and probing the live simulator disproved it — the constants are disclosed exactly on a
  single pointed ask, and the real defect was our agent bundling questions. Worth the two-minute
  probe before writing those tasks off.

**One direct conflict to resolve.** His §2.7.2 instructs *"COUNT(\*) is rejected — use
COUNT(<column>)"*. Our Q-02 found that `COUNT` over a **dimension** column returns the member
string and silently drops the `GROUP BY`. If solar_panel's counted columns are measures the
advice is safe — `COUNT(<measure>)` returns an integer, though it counts only non-null rows,
itself the M-02 problem. If any are dimensions, that prompt is steering the agent into a
silent-wrong-answer trap. Worth a direct check, and the highest-value thing this log can hand
back to that one.
