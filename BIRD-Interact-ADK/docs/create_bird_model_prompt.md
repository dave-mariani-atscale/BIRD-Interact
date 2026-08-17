# Prompt: build an AtScale semantic model for a BIRD-Interact database

**How this prompt was made.** Distilled from three full build-and-refine cycles — the
`exchange_traded_funds` prompt-only build (`create_etf_prompt.txt` plus every post-build
fix recorded in `docs/model-change-log.md`), the `solar_panel` build log (initial prompt
plus the defects found by live evaluation), and the `cybermarket_pattern` build, the first
to use this prompt rather than an ad-hoc one and therefore the first real test of it — plus
the ETF evaluation work of 2026-08-13/14, which measured what model fixes are actually
worth. Each rule traces to a concrete, observed failure; database-specific details and
anything derived from gold SQL were stripped. This file supersedes `create_etf_prompt.txt`;
the modeling rules are also mirrored in the MCP `sml-create-metric` skill — propagate new
lessons to both.

Replace `<db>` throughout (e.g. `exchange_traded_funds`, `solar_panel`).

**What changed in this revision (ETF evaluation, 2026-08-13/14).** Listed so each change
can be reviewed or reverted independently.

1. **Restored four rules that a previous merge dropped**, each of which had already been
   paid for: the dialect-inexpressible inventory and its "do not drop this" warning
   (Engine constraints); a pre-built rank's population belongs in its *name* (Ranks); a
   name that mirrors a question's phrasing must satisfy *every* condition in it (Keys);
   and the `is_mask` operational test based on the KB entry's `type` (Answer-key firewall).
2. **New**: a composite of percentile ranks must share one population, and rank on the
   undivided sum (Group vs entity level). One model defect, two distinct failures.
3. **New**: predict a model fix's task-level payoff at **zero** by default, and verify
   sufficiency for free before spending a run on it (After acceptance). Measured 3 for 3.
4. **New**: "confirm with the user" in a description only works when the agent asks the
   question *open*; a leading question gets ratified (After acceptance).
5. **Sharper n≥3 rule**: run-to-run variance is arm-asymmetric, with measured numbers and
   a per-arm repeat budget (After acceptance).

**What changed in the previous revision (from the `cybermarket_pattern` build).** That
build passed every acceptance gate below, deployed clean, validated clean — and scored
level with the raw text-to-SQL baseline. Everything in that revision came from closing
that gap.

1. **Reversed the advice on description-based steering** (Definitions and labels, first
   bullet). The previous revision said to redirect a caller via description text. That was
   tried in four places and failed in all four; only structural fixes worked. The old
   guidance is now explicitly marked as insufficient.
2. **Added a name-ownership rule** for every place this prompt tells you to ship more
   than one reading of a concept (Sources; referenced from Ranks, Group vs entity, Grain).
3. **Strengthened the rule on invented classifications** to a default prohibition.
4. Continuous values questions group *by* need a queryable attribute, not only a measure.
5. **Surface size**, making object count a budgeted quantity. Eight rules in this prompt
   multiply object count and nothing previously bounded it.
6. Missing-input policy is a separate reading with its own object.
7. Pre-ship shares and rates as calculations, because a caller's numeric cast returns a
   string.
8. **After acceptance.** The four gates prove correctness, not usability.
9. Repo target corrected to the shared `bird-atscale-models` repo, with the consequence
   that deploying publishes the whole catalog.
10. Precondition 1 corrected — `create_bird_connections.sh` has moved repos.
11. Two new engine constraints: no `|` in derived SQL (D-01); numeric casts need
    precision/scale and return strings.
12. New engine constraint Q-17b (non-idempotent publish, asymmetric failure) and the
    pre-run health gate that follows from it; plus the config-cache restart requirement.
13. Discoverability promoted from an acceptance check to a build-time assertion, with the
    YAML-folding trap that makes a naive version report false failures.
14. Sharper `explore_columns` examples: a plural and a voice change are each enough to
    miss.
15. Non-unique-label warnings must lead the description, not follow it.
16. Median-split concepts: precompute the median in dataset SQL, since the engine's
    percentile aggregation is dialect-blocked.
17. The answer-key firewall now recommends enforcing itself mechanically (an allowlisting
    extractor that asserts on its own output) rather than by intention, and the `is_mask`
    rule now says plainly to expect it to cost tasks and to report those separately.
18. Smaller propagations of the same evidence, each one line to a few: join exactly-1:1
    source tables into one wide fact to pre-empt the conformance class; prefer a compound
    SML leaf key where an entity has no single identifier; ship one rank twin where the
    live data shows no ties, and record a `LIMIT`-across-a-tie task as capped rather than
    failing; check an entity-grain variant is distinguishable before shipping it; verify a
    recorded column and its computed near-equivalent actually differ, and record the
    evidence; consider not exposing a concept component that has no independent use; have
    the generator fail on a dangling cross-reference between descriptions; note that an
    unpushed fix deploys the old model and looks like the fix did nothing.

---

Build an AtScale semantic model over the BIRD-Interact data in
`bird_interact_agent/data/bird-interact-full` at the BIRD-Interact fork root. Target the
`<db>` database through the `bird_<db>` connection, in the shared model repo
`AtScaleInc/bird-atscale-models`, in a new top-level folder named for the database,
committing to main. Note the consequence of the shared repo: deploying publishes the
**whole** catalog, so every model in it goes out together, and a redeploy for an unrelated
sibling model can break yours (see Q-17b under Engine constraints). Build via a
deterministic generator script parameterized by database name (see Build process). Run
unattended.

## Preconditions

1. An AtScale connection exists for the target database
   (`utilities/create_bird_connections.sh` in **`AtScaleInc/bird-atscale-models`** — not
   in the BIRD-Interact fork, where it used to live — provisions a connection per BIRD
   database). It reads `utilities/.env`, which is gitignored and must stay that way; copy
   `utilities/.env.example` and fill in `ATSCALE_CLIENT_SECRET` and `PG_PASSWORD`.
2. The AtScale MCP server is running and connected.
3. Deploy credentials: `ATSCALE_API_URL` is the SML API base URL without `/v1/public`
   (locally `http://local.atscaleinternal.com:3001`); `ATSCALE_API_TOKEN` — locally, use
   `ATSCALE_MCP_TEST_API_TOKEN` from `AtScaleInc/mcp/.env`.

## Answer-key firewall — read before opening any JSONL

Anything answer-bearing in `bird_interact_data.jsonl` is out of bounds while modeling:
`sol_sql` and `follow_up.sol_sql`, `sql_snippet` on any ambiguity entry, `test_cases` and
`conditions` (top level and inside `follow_up`), `preprocess_sql`, `clean_up_sqls`. The
cleanest guarantee is to extract the permitted fields (listed under Sources) into a brief
up front and model only from the brief, so the gold answers never reach your context. Say
which approach you took. Prefer to enforce this mechanically rather than by intention: a
short extractor that allowlists the permitted keys and then asserts that no denied key and
no SQL-shaped text appears in its own output is cheap, auditable, and removes the question
entirely. Gold SQL is fair game only later, if asked to diagnose specific failing tasks —
never folded back into the build.

Two working rules that keep the build honest:

- Every model change must be justifiable from the KB, the schema, or the engine's own
  observed behaviour — never from "this matches the expected answer".
- Hard-code a KB constant or threshold into the model only when its ambiguity entry is
  `is_mask: false` (an openly stated convention). When `is_mask` is true the benchmark
  intends the agent to resolve it by asking the user; baking it into the model answers
  the question for the agent. Still ship the masked concept's components — but each
  component's description must say it is one input to a larger named concept and that the
  agent should ask the user for the complete definition, every condition and threshold,
  before filtering. Observed failure otherwise: the agent anchors its clarifying question
  on the one component it found, gets a partial yes, and never learns the rest. Expect
  this rule to cost you tasks and do not try to buy them back: on `cybermarket_pattern`
  every one of the four tasks that failed on every run of both backends turned on a
  masked term, and no honest model change would have moved any of them. Report those
  separately from real defects so the score is read correctly.

  **The operational test is the KB entry's `type`, not your reading of the word
  "threshold."** Verified 2026-08-12 across `solar_panel`, `households` and
  `archeology_scan`: masked `calculation_knowledge` entries — KB-NAMED FORMULAS — ship
  under their own names in every model, 7 of 7 (Effective Power Output, Annual Degradation
  Rate, Temperature-Corrected Performance, System Unavailability, Infrastructure Quality
  Score, Household Density, Bathroom Ratio), because there the ambiguity is "which index
  did you mean", which competing named metrics answer honestly. Masked `domain_knowledge`
  entries that state a numeric cutoff do NOT ship, 0 of 17. The single apparent exception,
  `Accelerated Aging Asset`, is `domain_knowledge` whose definition states no number at all
  ("a high Annual Degradation Rate and signs of Major Module Degradation"), so there is
  nothing precise to hand over. Apply the same split rather than re-deciding per model, and
  enforce it mechanically: derive the masked set from `is_mask` in the brief, close it over
  the KB's own `children_knowledge` edges (a concept that depends on a masked one leaks the
  same cutoff), and fail the build if any member is implemented. `archeology_scan`'s
  generator gate A10 does this and reproduces its hand-written omission list exactly.

## Sources — and only these

Verify everything against the live database; the metadata files drift, so live wins.

- `<db>_schema.txt` and `<db>_column_meaning_base.json`. Profile the live tables yourself
  and fold what you find into the descriptions.
- `<db>_kb.jsonl` — every business definition, no exceptions, including any that
  individual tasks hide. Where the engine can't express one inline, say so rather than
  approximating silently. Some databases' KB files lost LaTeX backslashes to JSON
  unescaping: raw control characters stand where escape sequences belong (0x09 for `\t`
  as in `\text{}`, 0x0C for `\f` as in `\frac{}`, likewise `\n` `\r` `\b`). Check for
  raw control characters after parsing and restore them before reading formulas; most
  KBs are clean — don't transform ones that are.
- The natural-language questions in `bird_interact_data.jsonl` (filter on
  `selected_database`), for naming, synonyms, and coverage only: `amb_user_query`,
  `follow_up.query`, `category`, `output_type`, `high_level`, `follow_up.type`,
  `external_knowledge`, and the term/type/is_mask of each entry in `knowledge_ambiguity`
  and `user_query_ambiguity`. Don't hard-code any single task's thresholds or column
  picks. Where a term is genuinely ambiguous, ship a candidate object per reading, each
  description naming the alternative.

**Name readings asymmetrically.** This applies everywhere below that tells you to ship
more than one reading of a concept — ambiguous terms, competing join paths, the three
group/entity objects, RANK/DENSE_RANK twins, `(Current)` variants. Exactly one reading
carries the bare concept name; every other carries a qualifier stating its narrowing
(`(Recorded Only)`, `(Missing X As Zero)`, `(Computed)`, `(Current)`, `(All Entities)`).
Choose which one is bare from the questions' own vocabulary, not from which reading is more
technically correct. Two objects with equally plausible names is the failure mode, not a
service to the caller — see the first bullet under Definitions and labels for why the
descriptions will not save you.

**A threshold whose unit is ambiguous against the stored column gets both readings, and
the KB's own words verbatim.** A KB definition states a cutoff in prose ("annual portfolio
turnover is less than 30%", "largest holding greater than 8%", "allocations exceed 60%").
The stored column may be on a different scale, and then the definition admits two readings:
the literal number, or the number converted to the column's scale. Resolve it like this:

1. **Count both readings** against the live population before choosing. A reading is
   *viable* if it selects a proper, non-degenerate subset — not ~0% and not ~100% of the
   non-null rows, judged on the screen the questions actually ask for rather than on the
   bare column.
2. **Exactly one viable reading → ship it alone**, and say in the description why the other
   was rejected, with the number that rejects it. `High-Conviction Portfolio` is this case:
   `holdingpct` is a 0-1 fraction (max 1.0105), so `> 8` selects 0 of 2297 top holdings and
   only `> 0.08` (743) is viable. So is `Appraisal Ratio`, where R-squared is 0-100 and the
   KB's `sqrt(1 - R²)` is undefined unless the model divides by 100 first.
3. **Two viable readings → ship both**, asymmetrically named per the rule above, with the
   bare name on the reading the questions' vocabulary favours and a `(Percent Scale)`-style
   qualifier on the other. Each description must name its twin. Do not silently pick one:
   a threshold is the one thing a caller cannot recover from a result they can't see.
4. **Quote the KB verbatim before stating the resolution.** Descriptions already open with
   `KB '<Term>': …`; the original wording, including its unit, must survive into that text
   so the caller can see a decision was made and check it against the question. A
   description that reinterprets a cutoff without carrying the KB's own phrasing is a
   build defect — it is mechanically checkable, so don't leave it to review.

Gold is not a tiebreak here, and can disagree with itself: on `etf_18` gold phase 1 filters
`Turnover_Ratio < 0.3` and phase 2 filters `< 30`, the same KB term (id 12, "less than
30%") read both ways in one task. Contrarian Value Play counts 53 under the first reading
and 145 under the second, so no single reading wins both phases — which is precisely why
both must exist as named objects rather than one being chosen for the caller.

Do not read any other semantic model on this machine, nor its git history. If you open
one by accident, say so in your report.

## Modeling rules

**Placement and conformance**
- An attribute that describes an entity goes on that entity's dimension, so it conforms
  wherever the entity does — not on the fact or derived table that computed it.
  Degenerate dimensions are for genuinely fact-grain attributes only.
- A filter or grain flows to a measure only along a relationship path the engine
  accepts, and some structures that look like paths in the SML are not accepted at
  query time: a many-to-many bridge between the measure's dataset and the dimension, a
  degenerate dimension sourced from a different fact, a measure declared on a coarser
  dimension's dataset. When no accepted path exists the query falls back to
  `unrelated_dimensions_handling` — silently empty results with an easy-to-miss
  warning. Where a pairing must work and the path is one of these shapes, denormalize
  the value onto a dataset with a direct relationship at the grain you need (a
  degenerate dimension repointed via `dataset:` alone still fails — convert to
  secondary attributes on the real dimension). The conformance acceptance check is what
  proves each pairing; trust it, not the diagram.
- Where several source tables are exactly 1:1 on the same key (verify live: equal row
  counts, no orphans either way), joining them into one wide fact is usually worth it —
  it gives every attribute on them a direct relationship to each entity dimension and
  removes the whole conformance failure class above before it can occur.
- Set unrelated-dimensions handling explicitly on every measure — prefer error, so a bad
  pairing fails loudly instead of silently returning empty.
- Where an entity can reach another by more than one join path (a direct FK vs a
  many-to-many bridge), ship attributes for both readings with descriptions saying which
  path each uses and when to prefer which. Don't assume the structurally "more correct"
  path is the one questions mean. If the bridge's pairs exactly mirror pairs derivable
  from the fact (verify live), model it as a plain link-count fact instead of an M2M
  bridge.
- Key each dimension leaf on the column the fact's FK actually references (watch
  numeric-id FKs against text labels — type mismatch); keep the descriptive string as
  `name_column`. Where the source has no single identifier for an entity, use a compound
  SML leaf key over its natural columns rather than concatenating a surrogate in dataset
  SQL — see D-01 under Engine constraints for why concatenation is actively dangerous.
- **A continuous numeric that questions might group *by*, rather than aggregate, needs a
  queryable attribute as well as a measure.** Scan the question set for "per X" / "by X"
  / "for each X" phrasing over stored scores, rates and ratios. A measure-only numeric
  silently makes an entire question shape *inexpressible* — not merely awkward — and the
  caller has no workaround. Observed: a 1000-distinct-value score shipped as a measure
  only, where the questions group by it directly.

**Ranks and top-N**
- Expose the ranks and orderings that superlative and top-N questions need, at each grain
  they could ask about, stating sort direction, null placement, and tie convention. "The
  top N" means the first N rank positions under `RANK` and the N highest distinct values
  under `DENSE_RANK` — different row sets whenever values tie. Check the live data at the
  N the questions use; wherever the two disagree, ship both as separately named twins
  whose descriptions say which question each answers and name the other. The caller
  cannot recover the missing reading: a window alias used in `WHERE` must also be
  projected on this engine, which changes the column count.
- Where the two agree in the live data — no ties at the N the questions use — ship only
  one. Twins that never disagree are pure surface cost (see Surface size).
- **A pre-built rank's *population* is part of its definition, and belongs in its name.**
  A rank computed over every entity returns a gapped sequence the moment the caller filters
  (1, 2, 3, 5, 8...), which is not the dense within-filter rank a "top N of the entities
  that ..." question means. A within-filter rank is not expressible at build time — the
  rank cannot know a runtime `WHERE` — so the honest fix is to put the population in the
  *name* (`... Rank (All Entities)`), not only in the description, because an object whose
  name matches the question's vocabulary is picked on surface word match and by then the
  caller has already filtered. Where questions ask both ways, ship both readings.
- Note the limit of what this can buy you: when the question's own `LIMIT N` cuts across
  a tie, the expected answer is *not unique*, and no model can make it so. Record such
  tasks as capped rather than failing.

**Group vs entity level**
- Group-level and entity-level versions of a statistic are separate, separately named
  objects. Where the definition is a formula over other quantities (ratio, difference,
  weighted score, share), the group-level version must recompute the formula from aggregated
  components, as a calculated metric referencing component measures. Do not compute it
  per row in dataset SQL and average that column — that answers "the typical entity",
  not "this group", and once components are collapsed per row the group reading is
  unrecoverable. That makes **three** separately named objects: the formula over
  aggregated components, the mean of per-entity values, and the entity's own value —
  each description saying which question it answers and naming the others. Every
  component must exist as its own measure.
- Before shipping all three, check whether the entity-level variant is actually
  distinguishable from its base at entity grain. Where it is provably identical, ship one.
- **A composite of percentile ranks must rank every ingredient over ONE population**, and
  that population is the entities carrying *all* the ingredients. Ranking each ingredient
  over its own non-null set gives each a different denominator, so their mean averages
  incomparable scales and no entity's score is right. Observed: within one category the
  three ingredient populations were 42, 60 and 78, the composite was wrong for every fund,
  and 7 of 48 group winners changed. The defect is visible without any reference answer —
  a value ranked against 78 peers has no common scale with one ranked against 42 — so this
  is a correctness fix, not tuning.
- **Rank on the undivided sum, not on the mean.** Ordering by a sum and by that sum
  divided by a constant is the same ordering in exact arithmetic, but the division is lossy
  in floating point and *invents ties*: two distinct sums (`2.0` and `1.9999999999999998`)
  collapsed to one double and produced two rank-1 entities where there is one. Publish the
  mean as the score if that is the natural scale, and rank on the sum.

**Grain and time**
- Where the fact grain is finer than the entity (one row per reading/snapshot per
  entity), state on every flag and measure whether it answers "has this entity *ever*
  had X" or "does it have X *as of its latest reading*" — a model silent on that
  distinction produces plausible wrong answers. Ship latest-state "(Current)" variants
  of state/cost/output measures as objects distinct from history-wide aggregates. Where
  questions ask "as of right now", a NOW()-based dataset column works: it is pushed down
  and re-evaluated per query, not frozen at deploy.
- Don't trust `semi_additive (position: last)` for "latest snapshot per entity": it
  needs the trigger level to sit inside a hierarchy that also contains the entity, and a
  snapshot-keyed hierarchy plus a separate entity hierarchy cannot express it — the
  failure is silent, falling back to base aggregation with plausible numbers. Use
  `FIRST_VALUE(...) OVER (PARTITION BY entity ORDER BY snapshot DESC)` window-carry
  columns instead, and confirm via `get_outbound_queries` that the warehouse SQL
  contains the window function, not a plain `MAX()`.
- Document each measure's natural row grain. Averaging over entities silently differs
  depending on whether the inner grain is the snapshot or the entity; a coarser-grain
  figure requires an explicit reduction first, and the description should say so.

**Surface size**

Because it was the single largest cost measured on `cybermarket_pattern` and nothing else
in this prompt bounds it. Eight of the rules here multiply object count.

- Object count is a direct tax on the agent's budget: `explore_columns` is a substring
  match with no relevance ranking, so every near-duplicate description is sifted on every
  search. Measured on a 188-metric model: **62.5% of the per-task coin budget spent on
  discovery, 151 `explore_columns` calls over 20 tasks, and 19 of 20 tasks exhausting
  budget immediately after phase 1** — leaving nothing for the follow-up. Cutting to 162
  metrics brought discovery to parity with the raw baseline. Nothing about the tools
  changed; the model got smaller.
- Watch for the symptom, since it looks like a scoring mystery rather than a defect: a
  model with no visible flaw, correct on every gate, scoring at the baseline, with tasks
  running out of budget right after their first answer.
- The multiplicative rules above are permissions, not obligations. Ship a variant only
  where it is **provably** distinguishable in the live data — check ties before shipping a
  rank twin, check identity before shipping an entity-grain variant.
- Withholding peripheral columns that no question touches is legitimate and preferred over
  shipping them for completeness. Record which ones and why, in the spec, next to the
  exclusion — a silent omission is indistinguishable from an oversight later.

**Support sets and hidden objects**
- Any measure computed over a subset of rows must expose its support set, and both pieces
  must be visible to the discovery API — never hidden. Ship the count of entities that
  actually entered the computation (the regression n, the non-null count) and, where a
  caller would select that population, an availability classifier saying which entities
  carry the required inputs. The generic entity count is not a substitute — it
  over-selects. Where a formula has several components, the support set is the
  **intersection** of entities where every component is present — one count per formula,
  never per-component counts, never the widest one.
- **A support-set count is itself a reading, and a "group with enough entities" gate can
  mean either it or the generic count.** Where you ship both, say in each description that
  the choice changes which groups clear any given minimum, give the live counts for both,
  and direct the caller to confirm which population the question means. Expect the ask to
  be framed badly anyway (see After acceptance) — the two counts must at least be
  separately named and separately documented, because a caller who picks the wrong one gets
  a plausible, wrong row set with no error.
- **The missing-input policy is itself a reading, and needs its own object.** Where a
  formula's inputs are absent for some entities, ship both the strict version that
  excludes them and the zero/coalesce version that keeps them, named asymmetrically, each
  carrying its coverage count. A caller cannot recover one policy from the other.
  Observed: only the strict reading shipped, dropping 387 of 954 entities, where the
  questions wanted all of them.
- Hidden is only for terms with no standalone meaning (a sum of squares, a rebased
  denominator). Before declaring the model done, list every hidden object and state what
  question could be asked about it; if you can phrase one, unhide it. Report the list
  with evidence. Also confirm every defined object is referenced by the model file — no
  orphans that exist but cannot be queried.

**Definitions and labels**
- **Where two objects can answer one question, the name decides — not the description.**
  Verified repeatedly and expensively: the agent picks the object whose name best matches
  the question's words, and does not act on description text pointing it elsewhere, *even
  when that text is the description's first sentence*. In one case a description reading
  "prefer X" was ignored on two consecutive runs. In another, a task used the correct
  value, the correct population and the correct sort across three runs and never all three
  in one submission, because two objects shared one concept. Descriptions still carry
  disambiguation for a human reader and to trigger the ask-the-user path, but never rely on
  one to steer a choice. Resolve competition structurally, in this order: (1) if a reading
  has no basis in the KB, **delete it**; (2) otherwise move the plain, unqualified name
  onto the reading the questions actually mean and push every other behind a qualifier.
- Model every KB-defined metric, even composite ones. A missing KB metric doesn't fail
  loudly — queries silently fall back to a simpler, wrong aggregate.
- Where the KB defines named multi-condition concepts ("X failure" = A OR B; "major Y" =
  three ANDed conditions), don't just describe the logic — precompute it once, correctly,
  as a Yes/No attribute the agent can filter on directly. Description text alone is not
  reliably turned into correct SQL, even when read. Two second-order effects to plan
  for: the raw component columns compete with the flag on surface word match (a question
  phrased in a component's words gets filtered on that component alone, losing the OR
  branch); and a Yes/No flag hides the quantity it was derived from — note on the flag
  which underlying measure the answer likely still needs to display. Say in each
  component's description that it is an *input* to the concept and direct filtering to the
  flag — but treat that as documentation, not as a fix. It is not sufficient on its own,
  per the first bullet above: a component whose name contains the question's own word will
  still be chosen sometimes. Where the component has no independent use, consider not
  exposing it at all.
- **Do not invent a bucketing the KB does not define.** Expose the raw value and the
  pieces a bucketing would be built from — deltas, threshold comparisons, a boolean per
  condition. An invented bucket is worse than a missing one: it is usually named in
  exactly the words a question would use, so it out-competes the correct object on match
  while encoding a threshold nobody authorised. Both objects deleted from
  `cybermarket_pattern` were of this kind, and each had been chosen by the agent in
  preference to the correct object. Where the KB *does* name buckets, ship them, and say
  in the description that the label strings are this model's convention and the caller
  should re-label to the question's wording.
- **Pre-ship the divisions.** Any share, rate or percentage a question is likely to ask
  for should exist as a calculation rather than being left to the caller to divide two
  measures. On this SQL interface a caller's explicit numeric cast returns a **string**
  (see Engine constraints), so a hand-computed ratio cannot be rounded downstream and
  fails on presentation with the right value underneath. Scan the follow-up questions for
  "what percentage / what share / what proportion" and ship one calculation per answer
  shape; on `cybermarket_pattern` that was 13 of them, and most phase-2 follow-ups were of
  this form. Say in the description whether the value is a **fraction (0-1) or a percentage
  (0-100)**, and give a live example value: a share shipped as a fraction where the
  question asks "what percentage" is a silent 100× error the caller will not notice.
- Verify formula inputs mean what the formula requires — gross vs net, pre- vs post-
  adjustment, units and scale (kW vs MW is a silent 1000x error; check internal
  consistency across metrics that share a column). Where a raw recorded column and a
  computed near-equivalent both exist, use whichever the KB formula names — they are not
  interchangeable. Check a specific live value end-to-end against the source; a
  plausible result computed from the wrong basis is silently wrong (double-counting a
  loss ratio, for example). Verify the two are actually different before shipping both,
  and say so in the descriptions with the evidence (observed: 0 of 994 entities had the
  recorded column equal to the computed formula).

**Keys, identity, and naming**
- If the human-readable label is not actually unique in the live data, expose the true
  unique key as a queryable (not hidden) secondary attribute. `COUNT(DISTINCT label)` on
  a non-unique label silently under-counts. Separate identity from display in both
  descriptions: the key is identity (count and group on it, but it's an internal code),
  the label is what to show — prescribe `GROUP BY key` + `SELECT label`. When you warn
  against a column for one purpose, say what it *is* for; a caution with no counterpart
  guidance is read as "never use this column". **Lead with the warning** — descriptions
  are read top-down, and a caveat that is not first is a caveat that is not read.
  Observed: a non-uniqueness warning in the second sentence, and both tasks that listed
  those entities grouped by the label anyway, silently collapsing ~9 entities per row.
- **A name that mirrors a question's phrasing must satisfy *every* condition in that
  phrasing.** A measure named in the question's own words that quietly drops one of its
  qualifiers is worse than a neutrally-named one: it is the obvious pick, it returns a
  plausible number over a larger population, and nothing signals the mismatch. Either
  carry every qualifier in the name, or name it for what it actually computes and let the
  description carry the paraphrases.
- Keep `unique_name` and label identical for anything an agent will query. The tools
  surface `unique_name`, so a friendly label attached to a snake_case technical name is
  invisible where it matters — and a snake_case identifier gets written unquoted, as a
  bare SQL column rather than a semantic-layer attribute. Descriptions that
  cross-reference other objects must use their queryable names, or the model's own
  metadata points at names that don't resolve. Have the generator fail the build on a
  dangling cross-reference, so a description can never name an object that is not
  published.

**Descriptions**
- Every measure and attribute description carries: formula and provenance, units and
  scale, live null and coverage counts, disambiguation from near-twins, and the
  paraphrases someone would actually ask with. `explore_columns` is a contiguous,
  case-insensitive substring match, not fuzzy search, and the near misses are much cheaper
  than they look: an inserted word ("count of years" does not match "count of calendar
  years"), **a plural** ("dodgy buyers" does not match "dodgy buyer"), and **a change of
  voice** ("how quickly we handled threats" does not match "how quickly threats were
  handled") each make the object invisible. Include several wordings verbatim, in both
  singular and plural, and in both active and passive phrasing. Descriptions on objects the
  discovery API doesn't expose don't count. The model's own description should be an
  orientation guide, not a one-liner.

## Engine constraints (learned the hard way)

These work around tracked engine/tool defects — parenthesized IDs reference the team's
defect tracker and are provenance, not something to resolve. Check the Workarounds table
in BIRD-Interact-ADK's `docs/model-change-log.md` for whether each still applies.

- **Precompute whatever the query dialect cannot express.** A caller cannot work around a
  missing language feature; they discover it by spending submits on queries that never
  execute. Any concept the questions need that the dialect cannot say is a model object,
  not a caller problem — move the computation into a measure or attribute so that SQL is
  never written. Currently inexpressible on this engine: percentile/median (see below),
  quantile bucketing (`NTILE` rejected — so quartile/decile/percentile-band questions are
  unanswerable unless the band ships as an attribute; `ROW_NUMBER` and `RANK` are both
  accepted, so it is `NTILE` specifically), string aggregation (`string_agg`/`listagg`/
  `group_concat` rejected, `ARRAY_AGG` accepted but silently does not aggregate),
  `GREATEST`/`LEAST`, `IN (subquery)`/`EXISTS`, CTEs, and `COUNT(*)`. Re-probe the list
  against the live engine before each build; a workaround that stops being needed is dead
  weight, and a new gap is a silent failure.

  > **Do not drop this bullet.** A previous revision removed it along with the inventory
  > above, and the cost showed up immediately: `archeology_scan_7` had `NTILE` rejected,
  > then spent five of its twelve `run_query` calls hand-rolling a quartile from
  > `ROW_NUMBER` and hardcoding the row count as the denominator. A caller cannot discover
  > a missing language feature except by paying for it (Q-19).
- **Schema-qualify derived-dataset SQL** with the connection's declared schema —
  `public.<table>` for all current BIRD connections. The engine executes derived SQL
  without that schema on the `search_path`; bare references deploy clean and then fail
  every query with `relation does not exist` (E-02).
- **Never use `|` in derived SQL** (D-01). The engine re-parses and re-emits
  derived-dataset SQL, and a `'|'` string literal does not survive the round trip: every
  query touching the dataset dies with a raw warehouse `syntax error at or near "'|'"`.
  Other literals in the same SQL (`'$'`, `','`, `' km'`, `'Yes'`, `'2FA'`) round-trip
  fine, so this is specific to the pipe character. Validate and deploy both pass; it only
  surfaces on a live query, and it killed every query on two datasets. Where a composite
  key needs representing, use a compound SML leaf key rather than a concatenated
  surrogate. Assert in the generator that no emitted SQL contains a `|`.
- **A numeric cast needs explicit precision and scale, and returns a string.** Bare
  `CAST(x AS numeric)` and `x::numeric` are both rejected, so a caller must write
  `CAST(x AS numeric(p,s))` — which comes back through the SQL interface as a string
  (`'0.27800000000000000000'`), silently defeating any downstream rounding. Ship the
  ratios yourself as calculations rather than leaving the division to the caller (see
  Definitions and labels).
- **Median** must be a `calculation_method: percentile` aggregation with
  `named_quantiles`, never a `metric_calc` — MDX `Median()` is rejected at deploy. On the
  Postgres dialect the percentile sketch is then rejected at query time; ship it anyway
  (correct SML, costs nothing, works when the dialect does) and record the limitation.
  The engine exposes percentile metrics as `<name>_instance_<q>` — the plain label
  returns `Column not found`, and metadata is cached until `list_models force_refresh`.
  Consequence for concepts *defined by* a median rather than reporting one (a median
  split, an above-median flag): the engine's own percentile cannot be used, so precompute
  the median in the dataset SQL — `percentile_cont(0.5) WITHIN GROUP (ORDER BY x)` in a
  cross join — and ship the resulting flag. Otherwise the concept is simply unreachable.
- **Catalog naming**: pick a catalog name not already deployed. Deploying from Design
  Center (the web UI) appends the git branch to the catalog name (`_main`);
  `sml-cli atscale-deploy` uses it verbatim — the two paths publish to different schemas.
  After any redeploy, read the schema back from `list_models`; if the ADK eval harness is
  in play, make its `config/environment_backends.yaml` match — a stale entry fails every
  task with no hint that config is the cause. `shared/environment_backends.py` caches that
  file in a module-level dict at first load, so **the services must be restarted** for an
  edit to take effect; a `--backend` flag will not pick it up. Two full runs were lost to
  a config that was already correct on disk.
- Two deployed models sharing a name render corrupted metadata (Q-17); keep deployed
  model names unique across the engine.
- **Q-17b — publishing is not idempotent, and it fails asymmetrically.** A published model
  is materialised as a real relation, and the code path that creates it does so with no
  `IF NOT EXISTS` and no preceding drop, so once the relation exists from an earlier
  publish, metadata calls die with `relation "<Model>" already exists`. The asymmetry is
  the dangerous part: `list_models`, `explore_columns` and `focus_columns` hard-fail while
  `run_query` catches the error, skips path validation and returns **correct results** —
  so the deploy looks healthy while the agent is blind. Neither redeploying nor restarting
  the MCP server clears it; drop the stale relation in the catalog schema. Because a
  shared repo publishes the whole catalog, a redeploy of an unrelated sibling model can
  trigger it. **Before any evaluation run, gate on `list_models` succeeding AND returning
  the expected model count. A working `run_query` is not evidence the catalog is healthy**
  — that is precisely the trap. Three runs scored 0.000 on every task before this was
  understood.

## Build process

- A deterministic, re-runnable generator script (spec → emitter). Changes are made by
  editing the spec and re-running, never by hand-editing emitted YAML — any identity that
  must survive (model name, catalog) belongs in the generator as a parameter, or
  regeneration silently reverts it.
- Have the generator self-audit its output: duplicate labels, unreferenced datasets,
  metrics naming columns no dataset defines, dangling cross-references between
  descriptions — `sml-cli validate` misses all of these.
- **Assert discoverability at build time, not only at acceptance.** Keep a list of the
  question wordings the task set actually uses and fail the build if any of them matches
  no published description. Finding these one at a time as they surface is slow and
  repeats: the same class recurred on three consecutive acceptance runs before it became a
  build check, and 34 phrases are currently gated. The check must **parse the emitted YAML
  and normalise whitespace** — `safe_dump` line-wraps long descriptions at column 100 and
  the consumer sees the folded value, so grepping raw file text reports false failures on
  phrases that are in fact present.
- Before validate/deploy, dry-run every derived dataset's SQL directly against the
  warehouse (row count plus a hand-recomputed spot value). This catches same-level alias
  references and formula transpositions that no SML layer can.
- Follow the SML authoring skills from `get_sml_skills`; `sml-cli validate` clean; commit
  and push before deploying (deploy resolves the model from the git remote — an unpushed
  fix deploys the old model and looks like the fix did nothing); deploy.
- Record every post-build change — the kind of change and why, naming the tracker row if
  it works around a defect — in BIRD-Interact-ADK's `docs/model-change-log.md`.

## Acceptance — not done until all four pass, with evidence

`validate` is layer 1 only; every defect class above deployed clean and only surfaced via
live `run_query`, `get_outbound_queries`, or reading the agent's actual failed queries.
Budget time to test live, and never take a plausible number as evidence a feature fired —
read the outbound warehouse SQL for any semi-additive or window-based construct.

1. **Exactness.** Smoke queries through the model exact-equal to the same query on the
   source database. The data is synthetic — never judge a result by plausibility.
2. **Conformance.** Per dimension, one measure-by-attribute query per fact that dimension
   should reach, returning non-empty. Empty or erroring is a model bug, not a limitation
   to document — the sole exception is metrics already documented as dialect-blocked
   (e.g. percentile medians on Postgres).
3. **Discoverability.** Search the deployed model with question-style paraphrases only,
   never an object's own name — take the probe phrases from the task briefs' own
   `amb_user_query` wordings; the intended object must surface. If not, fix the
   description.
4. **Coverage.** One passing query per question shape: group aggregate,
   filter-by-classification then measure, superlative/top-N, cross-fact, entity-level
   detail, group-relative comparison. Close any gap or state explicitly what was left
   out.

## After acceptance — the gates prove correctness, not usability

The most important thing the `cybermarket_pattern` build had to say. That model passed all
four gates, validated clean, deployed clean, satisfied every rule above — and its first
evaluation run scored 0.295 average reward, level with the raw text-to-SQL baseline. Every
point of lift after that came from work this prompt previously did not ask for. Expect the
same, and treat a first run at baseline as the start of the work rather than a failure.

- **Read the agent's actual submitted SQL** in the results JSON for every failing task.
  Almost every defect in the classes added in this revision — object competition, an
  invisible phrasing, an inexpressible shape, a string-typed cast — is invisible to
  `validate`, invisible to the four gates, and invisible to live `run_query`, and obvious
  in one look at what the agent wrote. Note the graded submission is the **last** trajectory
  entry carrying an `sql` key, not the first.
- **Predict a model fix's task-level payoff at zero, and price it that way.** Measured 3
  for 3 on ETF: a defect was found, fixed, verified against the reference, and the task did
  not move, because the agent's next choice up the stack became the binding constraint —
  it stopped projecting a misleading rank but never computed the right one; it stopped
  computing a wrong composite but then gated the population on the wrong count. A model fix
  reliably *removes a known-wrong answer*; it does not reliably produce a right one. Score
  it on that basis, and don't fund a model change on a predicted score gain.
- **Verify sufficiency for free before spending a run.** Take the agent's own stored
  submission, run it through `run_query` against the fixed model, and diff it against the
  reference result — value by value, row count and all. That costs nothing and answers
  "is the model now capable of the right answer" definitively. Only then decide whether a
  scored run is worth it. Doing this caught a fix that was correct-but-insufficient before
  any benchmark spend, and isolated the one remaining condition exactly.
- **"Confirm with the user" in a description only works if the agent asks the question
  *open*.** Observed on the same task twice: asked as a genuine two-option question ("the
  total count, or only those with a computable score?") the agent chose correctly; asked as
  a leading one ("what minimum number of *scoreable* entities...") the simulator simply
  ratified the premise and the task failed. You cannot fix the framing from the model, so
  where a wrong choice is silent, make the two objects separately named and separately
  documented with live counts, and expect to lose the task some fraction of the time.
- **n≥3 per arm before believing any delta, and spend the repeats on the noisier arm.**
  A single run moves by roughly ±0.10 average reward from agent variance alone; the measured
  noise floor on a final `cybermarket_pattern` configuration was sd 0.012–0.018. A
  before/after comparison built from one run per arm says nothing, and it is easy to spend a
  day chasing a change that was noise.
  Run-to-run variance is also *asymmetric*: measured on a 19-task ETF set, the semantic arm
  moved on 1 task of 19 across repeats (sd 0.71 points) while the raw arm moved on 7 of 19
  (sd 0.91 points, single-run totals ranging 5.40-7.40). 13 of 19 raw tasks were perfectly
  stable and the whole spread came from six. The semantic layer appears to constrain the
  agent to a narrow path while raw SQL lets it re-pick a formulation every run. Budget
  roughly **4 repeats on raw, 1-2 on the semantic arm**; a single run per arm can read
  anywhere from +7 to +32 percentage points of lift on identical code.
- **Compute lift on the task intersection, never on arm totals**, and never quote a single
  pair of runs. The raw arm runs the Management-category tasks that a read-only semantic
  layer structurally cannot serve; drop them from both sides. Quote the mean of the repeats
  with its range, in percentage points, with relative alongside. One outlier run paired
  against one good run produced a headline that was double the settled value.
- **Sort failures into model-fixable and not, and say which is which** before changing
  anything. A task whose question turns on an ambiguity marked `is_mask: true` cannot
  honestly be fixed in the model — that failure is the firewall rule working, not a gap.
  Likewise a task whose expected answer is non-unique (a `LIMIT` across a tie) is capped
  regardless of the model. Reporting these together with real defects makes the model look
  worse than it is and invites a dishonest fix.
- **Before each run, verify the environment with the harness's own credentials**, not
  through your own MCP connection: run a full initialize → session → `tools/call`
  handshake using the token the harness will use. Three runs were lost to an HTTP 401 that
  a check through a different connection had pronounced healthy. Combined with the Q-17b
  gate above, these two habits account for six voided runs — more elapsed time than every
  model fix in that build put together.
