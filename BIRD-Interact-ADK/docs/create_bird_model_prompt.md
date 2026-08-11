# Prompt: build an AtScale semantic model for a BIRD-Interact database

**How this prompt was made.** Distilled from two full build-and-refine cycles: the
`exchange_traded_funds` prompt-only build (`create_etf_prompt.txt` plus every post-build
fix recorded in `docs/model-change-log.md`) and the `solar_panel` build log (initial
prompt plus the defects found by live evaluation). Each rule traces to a concrete,
observed failure; database-specific details and anything derived from gold SQL were
stripped. This file supersedes `create_etf_prompt.txt`; the modeling rules are also
mirrored in the MCP `sml-create-metric` skill — propagate new lessons to both.

Replace `<db>` throughout (e.g. `exchange_traded_funds`, `solar_panel`).

---

Build an AtScale semantic model over the BIRD-Interact data in
`bird_interact_agent/data/bird-interact-full` at the BIRD-Interact fork root. Target the
`<db>` database through the `bird_<db>` connection, in a new dedicated repo (single-model
repo, commit to main). Build via a deterministic generator script parameterized by
database name (see Build process). Run unattended.

## Preconditions

1. An AtScale connection exists for the target database
   (`utilities/create_bird_connections.sh` in the BIRD-Interact fork provisions a
   connection per BIRD database).
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
which approach you took. Gold SQL is fair game only later, if asked to diagnose specific
failing tasks — never folded back into the build.

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
  on the one component it found, gets a partial yes, and never learns the rest.

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
  `name_column`.

**Ranks and top-N**
- Expose the ranks and orderings that superlative and top-N questions need, at each grain
  they could ask about, stating sort direction, null placement, and tie convention. "The
  top N" means the first N rank positions under `RANK` and the N highest distinct values
  under `DENSE_RANK` — different row sets whenever values tie. Check the live data at the
  N the questions use; wherever the two disagree, ship both as separately named twins
  whose descriptions say which question each answers and name the other. The caller
  cannot recover the missing reading: a window alias used in `WHERE` must also be
  projected on this engine, which changes the column count.
- A pre-built rank's **population** is part of its definition. A rank computed over every
  entity returns a gapped sequence the moment the caller filters (1, 2, 3, 5, 8...), which
  is not the dense within-filter rank a "top N of the entities that ..." question means.
  Put the population in the *name*, not only the description — an object whose name
  matches the question's vocabulary gets picked on surface word match, and by then the
  caller has already filtered. Where questions ask both ways, ship both readings.

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

**Support sets and hidden objects**
- Any measure computed over a subset of rows must expose its support set, and both pieces
  must be visible to the discovery API — never hidden. Ship the count of entities that
  actually entered the computation (the regression n, the non-null count) and, where a
  caller would select that population, an availability classifier saying which entities
  carry the required inputs. The generic entity count is not a substitute — it
  over-selects. Where a formula has several components, the support set is the
  **intersection** of entities where every component is present — one count per formula,
  never per-component counts, never the widest one.
- Hidden is only for terms with no standalone meaning (a sum of squares, a rebased
  denominator). Before declaring the model done, list every hidden object and state what
  question could be asked about it; if you can phrase one, unhide it. Report the list
  with evidence. Also confirm every defined object is referenced by the model file — no
  orphans that exist but cannot be queried.

**Definitions and labels**
- Model every KB-defined metric, even composite ones. A missing KB metric doesn't fail
  loudly — queries silently fall back to a simpler, wrong aggregate.
- Where the KB defines named multi-condition concepts ("X failure" = A OR B; "major Y" =
  three ANDed conditions), don't just describe the logic — precompute it once, correctly,
  as a Yes/No attribute the agent can filter on directly. Description text alone is not
  reliably turned into correct SQL, even when read. Two second-order effects to plan
  for: the raw component columns compete with the flag on surface word match (a question
  phrased in a component's words gets filtered on that component alone, losing the OR
  branch) — say in each component's description that it is an *input* to the concept and
  direct filtering to the flag; and a Yes/No flag hides the quantity it was derived from
  — note on the flag which underlying measure the answer likely still needs to display.
- Label text belongs to the caller. Where a definition sorts entities into named buckets,
  expose the pieces the bucketing is built from — deltas, threshold comparisons, a
  boolean per condition. If you also ship a ready-made classification, say in its
  description that its label strings are this model's convention and the caller should
  re-label to the question's wording.
- Verify formula inputs mean what the formula requires — gross vs net, pre- vs post-
  adjustment, units and scale (kW vs MW is a silent 1000x error; check internal
  consistency across metrics that share a column). Where a raw recorded column and a
  computed near-equivalent both exist, use whichever the KB formula names — they are not
  interchangeable. Check a specific live value end-to-end against the source; a
  plausible result computed from the wrong basis is silently wrong (double-counting a
  loss ratio, for example).

**Keys, identity, and naming**
- If the human-readable label is not actually unique in the live data, expose the true
  unique key as a queryable (not hidden) secondary attribute. `COUNT(DISTINCT label)` on
  a non-unique label silently under-counts. Separate identity from display in both
  descriptions: the key is identity (count and group on it, but it's an internal code),
  the label is what to show — prescribe `GROUP BY key` + `SELECT label`. When you warn
  against a column for one purpose, say what it *is* for; a caution with no counterpart
  guidance is read as "never use this column".
- A name that mirrors a question's phrasing must satisfy **every** condition in that
  phrasing. A measure named in the question's own words that quietly drops one of its
  qualifiers is worse than a neutrally-named one: it is the obvious pick, it returns a
  plausible number over a larger population, and nothing signals the mismatch. Either
  carry every qualifier in the name, or name it for what it actually computes and let the
  description carry the paraphrases.
- Keep `unique_name` and label identical for anything an agent will query. The tools
  surface `unique_name`, so a friendly label attached to a snake_case technical name is
  invisible where it matters — and a snake_case identifier gets written unquoted, as a
  bare SQL column rather than a semantic-layer attribute. Descriptions that
  cross-reference other objects must use their queryable names, or the model's own
  metadata points at names that don't resolve.

**Descriptions**
- Every measure and attribute description carries: formula and provenance, units and
  scale, live null and coverage counts, disambiguation from near-twins, and the
  paraphrases someone would actually ask with. `explore_columns` is a contiguous,
  case-insensitive substring match, not fuzzy search — "count of years" does not match
  "count of calendar years" — so include several wordings verbatim. Descriptions on objects the discovery API doesn't
  expose don't count. The model's own description should be an orientation guide, not a
  one-liner.

## Engine constraints (learned the hard way)

These work around tracked engine/tool defects — parenthesized IDs reference the team's
defect tracker and are provenance, not something to resolve. Check the Workarounds table
in BIRD-Interact-ADK's `docs/model-change-log.md` for whether each still applies.

- **Precompute whatever the query dialect cannot express.** A caller cannot work around a
  missing language feature; they discover it by spending submits on queries that never
  execute. Any concept the questions need that the dialect cannot say is a model object,
  not a caller problem — move the computation into a measure or attribute so that SQL is
  never written. Currently inexpressible on this engine: percentile/median (see below),
  string aggregation (`string_agg`/`listagg`/`group_concat` rejected, `ARRAY_AGG` accepted
  but silently does not aggregate), `GREATEST`/`LEAST`, `IN (subquery)`/`EXISTS`, CTEs,
  and `COUNT(*)`. Re-probe the list against the live engine before each build; a
  workaround that stops being needed is dead weight, and a new gap is a silent failure.
- **Schema-qualify derived-dataset SQL** with the connection's declared schema —
  `public.<table>` for all current BIRD connections. The engine executes derived SQL
  without that schema on the `search_path`; bare references deploy clean and then fail
  every query with `relation does not exist` (E-02).
- **Median** must be a `calculation_method: percentile` aggregation with
  `named_quantiles`, never a `metric_calc` — MDX `Median()` is rejected at deploy. On the
  Postgres dialect the percentile sketch is then rejected at query time; ship it anyway
  (correct SML, costs nothing, works when the dialect does) and record the limitation.
  The engine exposes percentile metrics as `<name>_instance_<q>` — the plain label
  returns `Column not found`, and metadata is cached until `list_models force_refresh`.
- **Catalog naming**: pick a catalog name not already deployed. Deploying from Design
  Center (the web UI) appends the git branch to the catalog name (`_main`);
  `sml-cli atscale-deploy` uses it verbatim — the two paths publish to different schemas.
  After any redeploy, read the schema back from `list_models`; if the ADK eval harness is
  in play, make its `config/environment_backends.yaml` match — a stale entry fails every
  task with no hint that config is the cause.
- Two deployed models sharing a name render corrupted metadata (Q-17); keep deployed
  model names unique across the engine.

## Build process

- A deterministic, re-runnable generator script (spec → emitter). Changes are made by
  editing the spec and re-running, never by hand-editing emitted YAML — any identity that
  must survive (model name, catalog) belongs in the generator as a parameter, or
  regeneration silently reverts it.
- Have the generator self-audit its output: duplicate labels, unreferenced datasets,
  metrics naming columns no dataset defines — `sml-cli validate` misses some of these.
- Before validate/deploy, dry-run every derived dataset's SQL directly against the
  warehouse (row count plus a hand-recomputed spot value). This catches same-level alias
  references and formula transpositions that no SML layer can.
- Follow the SML authoring skills from `get_sml_skills`; `sml-cli validate` clean; commit
  and push before deploying (deploy resolves the model from the git remote); deploy.
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
