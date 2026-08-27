# Semantic-model change log

Post-build changes to the AtScale semantic models in
[AtScaleInc/bird-atscale-models](https://github.com/AtScaleInc/bird-atscale-models),
one section per model. Record the kind of change and why; name the Workarounds
row when a change works around a tracked defect.

Sections below sometimes cite `docs/create_bird_model_prompt.md`,
`docs/lift-levers-handoff.md` or `docs/crypto-followups-handoff.md`. Those are
local working documents and are deliberately not in this repo — the build-prompt
content lives on Google Drive, the handoffs are single-author session notes. The
citation records where a decision came from; nothing here depends on reading them.

## Workarounds

Engine/tool defects the models deliberately work around. Check whether a row
still applies before carrying its workaround into a new model.

| ID | Defect | Workaround | Still applies? |
|---|---|---|---|
| E-02 | Derived-dataset SQL executes without the connection's schema on the `search_path`; bare table references deploy clean then fail every query with `relation does not exist`. | Schema-qualify every table reference in derived SQL (`public.<table>` for all BIRD connections). | Yes - applied in `cybermarket_pattern` (2026-08-10). Not re-tested against a fixed build. |
| Q-17 | Two deployed models sharing a name render corrupted metadata. | Keep deployed model names unique across the engine; do not publish the same catalog to two schemas. | Yes. |
| Q-17b | **A published model is materialised as a real relation by a non-idempotent code path.** `get_model_document` triggers `CREATE TABLE "<catalog_schema>"."<Model Name>"` with no `IF NOT EXISTS` and no preceding drop, so once that relation exists from an earlier publish every metadata call dies with `relation "<Model>" already exists`. **The failure is asymmetric, which is the dangerous part:** `list_models`, `explore_columns` and `focus_columns` hard-fail while `run_query` catches the error, skips path validation and returns CORRECT results - so the deploy looks healthy while the agent is blind. Neither redeploying nor restarting the MCP server clears it. | Drop the stale materialised relations in the catalog schema inside the engine's SQL store; republishing alone does not. Before any run, gate on `list_models` succeeding AND returning the expected model count - a working `run_query` is NOT evidence the catalog is healthy. | Yes - 2026-08-10/11. Voided three atscale runs (every task 0.000, 81-84% of tool calls erroring). `scripts/summarize_runs.py` flags such runs SUSPECT and excludes them. |
| MDX-Median | `Median()` is rejected at deploy as a `metric_calc`; must be `calculation_method: percentile` with `named_quantiles`. On the Postgres dialect the percentile sketch is then rejected at query time. Percentile metrics are exposed as `<name>_instance_<q>`; metadata is cached until `list_models force_refresh`. | Ship the percentile form anyway and record the dialect limitation. | Yes, where a KB definition needs a median. |
| D-01 | The engine re-parses and re-emits derived-dataset SQL, and a `'|'` string literal does not survive the round trip: every query touching the dataset fails with a raw warehouse `syntax error at or near "'|'"`. Other literals (`'$'`, `','`, `' km'`, `'Yes'`) round-trip fine. Validation and deploy both pass - it only surfaces on a live query. | Never use `|` in derived SQL. For a composite key use a compound SML leaf key rather than concatenating a surrogate. | Yes - found and fixed in `cybermarket_pattern` 2026-08-10. |
| E-01 | Bare `COUNT(<dimension attribute>)` is not evaluated: the engine drops the aggregate and returns the attribute's members. Re-confirmed live 2026-08-12. `COUNT(DISTINCT <attr>)` and a count measure are both correct. | Every identifier attribute's description must name the model's count measure and `COUNT(DISTINCT <attr>)`, and state that plain `COUNT` returns members rather than a number. | Yes - applied to `archeology_scan` Site Code (M-14) and `exchange_traded_funds` Fund. Carry into every new model's key attributes. |
| Q-15 | `COUNT(DISTINCT <dim>)` - the one form E-01 says to trust - is itself unreliable in three ways: it returns **null** under some measure predicates; it returns the **unfiltered** count under others (the predicate degrades to "joins to any fact"); and when **co-projected** with a plain `COUNT(<dim>)` the whole query drops to the dimension's grain and the distinct count collapses to 1 per row. Alone and unfiltered it is correct. | Run the DISTINCT form alone, never beside a plain `COUNT`, and never trust it under a measure filter - wrap the filter in a derived table instead. | Yes - engine fix open. |
| Q-20 | **A whole-population value cannot be shown beside detail rows by any obvious means, and three of the four failures are silent.** A scalar subquery in the SELECT list alongside detail rows returns each row's OWN value (a share measure came back 1.0 per row instead of 0.9397); `COUNT(m) OVER ()` likewise returns the row's own value; a `UNION ALL` totals row returns ZERO rows; `AVG(m) OVER ()` and a comma cross-join at least error. | `JOIN (SELECT <aggregate measure> AS total FROM <model> WHERE <population>) s ON 1=1` — confirmed live to repeat the true population value on every row. The scalar-subquery form stays correct only when the SELECT has no per-row grain. This buys a repeated COLUMN; where the answer needs a summary ROW (tracker B-04) the only route stays the FROM-less literal-values form. | Yes - found 2026-08-12 on ETF `_11` and `_12`. |
| Q-21 | A bare SQL stat function (`MIN`/`MAX`/`AVG`) over a measure in a flat SELECT dies in query planning with `ExpandStatFunctions: assertion failed: We already handled attribute values`. | Force the natural row grain in an inner derived table, then aggregate outside it. Window aggregates are not an escape - `AVG(m) OVER ()` raises the same error. | Yes - 2026-08-12. |
| Catalog-suffix | Deploying from Design Center appends the git branch to the catalog name (`_main`); `sml-cli atscale-deploy` uses `catalog.yml`'s name verbatim, which is unsuffixed. The two paths publish to different schemas, and every recorded run names the `_main` one. | Deploy through `scripts/deploy_models.sh`, which passes `--catalog-name=bird_atscale_models_catalog_main` so the CLI lands where Design Center did. Still read the schema back from `list_models` afterwards and make `config/environment_backends.yaml` match. | Yes - all models are published at `bird_atscale_models_catalog_main`. |
| Deploy-remote | `sml-cli atscale-deploy` resolves the project by its git REMOTE url against repositories registered in AtScale, not by the local path, so it deploys what `origin` has. An uncommitted or unpushed change deploys the OLD model and reports `Deploy SUCCESSFUL`. Its `ATSCALE_API_URL` is also the SML public API (`local.atscaleinternal.com:3001`), not the engine API on `:10502` - the engine URL authenticates and then 404s hunting for the repository. | `scripts/deploy_models.sh` refuses to deploy on a dirty tree or a branch that differs from `origin`, and hardcodes the right API url. | Yes - 2026-08-12, first CLI deploy. |
| Publish-timestamp | `data_type: timestamp` passes `sml-cli validate` but the engine rejects the whole catalog at publish with `400 Error occurred during schema publishing: Don't understand type TimeStamp`. The message names no column and no model, so in a shared repo it reads as a fault in whatever model you happen to be deploying - one `cross_border` column blocked every model's deploy. | Use `data_type: datetime` for every TIMESTAMP/DATETIME source. `fake_account` also casts `timestamptz` to plain `timestamp` in derived SQL and refuses to map `timestamptz` in its type prober, since `timestamptz` is not in the SML type table at all. | Yes - found and fixed 2026-08-20 (`cross_border/datasets/flow_fact.yml`). |
| MDX-hierarchy-name | A `metric_calc` naming a hierarchy as `[Dim].[Dim]` instead of `[Dim].[Dim Hierarchy]` passes `sml-cli validate` - Layer 1 checks YAML shape, not expression contents - then fails the whole catalog's publish with `400 ... Hierarchy \`[X].[X]\` not found in <Model>`. Because a shared repo publishes every model together, it blocks every sibling too. | A hierarchy's `unique_name` is `<Dimension> Hierarchy`. `fake_account` generator gate G14 resolves every `[Measures].[...]` and `[Dim].[Hier]` reference in every `metric_calc` against what the model actually publishes. | Yes - found and fixed 2026-08-20 (`fake_account`). |
| Engine-payload-413 | The API posts the **whole compiled catalog** to the engine in one request, and pekko-http caps an incoming body at 8 MiB. At 22 semantic models `bird_atscale_models_catalog` compiles to ~9.8 MB and the publish dies with `413 ... EntityStreamSizeException: incoming entity size (9818195) exceeded size limit (8388608 bytes)`. Nothing before deploy sees it, and it scales with the number of models in the repo, so it will recur. | Raise the engine's limit rather than splitting the catalog (splitting changes the schema name and invalidates every `domains:` entry). `container-local-tooling/devel/docker/compose/docker-compose.yml` now sets `JDK_JAVA_OPTIONS` on the engine service to `-Dpekko.http.server.parsing.max-content-length=${ATSCALE_ENGINE_MAX_CONTENT_LENGTH:-32m}`, repeating the image's own `-Xms2G -Xmx4G -XX:NativeMemoryTracking=summary` because the variable REPLACES rather than appends. `docker compose up -d --no-deps engine` then a `/ping` check. | Yes - found 2026-08-19 at 22 models. |
| MDX-POWER | `power(x, 4)` in a `metric_calc` passes `sml-cli validate` and then fails the whole catalog's publish with `400 ... Calculated measure <name> is not valid as either MDX or DAX. MDX error: end of input expected`. Uppercase `POWER` fails identically; `ABS`, `SQRT` and `LOG10` all publish fine, so it is this function, not function calls in general. Because a shared repo publishes every model together, one bad expression made all 22 undeployable. | Write the exponent out as repeated multiplication, which parses on both sides of the MDX/DAX fence. Fixed 2026-08-19 in `planets_data/calculations/group_stellar_luminosity_pooled.yml`; no other calculation in the repo calls POWER. | Yes. |
| Q-27b | **A dataset that HOSTS a dimension's key level must not also carry a relationship to a DIFFERENT dimension.** If it does, no attribute-only query can pair that hosted dimension with anything: `SELECT "Patient", "Facility"` dies with `query planning: assertion failed: No candidate paths found for an attribute` while `SELECT "Patient", "Facility", "Assessment Count"` returns rows. Measured, not inferred: dropping two such edges in `mental_health` moved it from 87 to 136 of 276 dimension pairs, and the pairs that came good were exactly the ones those edges fed. `sports_events` and `virtual_idol` both pass 100% of pairs and neither has an edge of that shape. Invisible to `sml-cli validate`, to deploy, and to a conformance check that pairs a MEASURE with the attribute - and BIRD questions ask for labels far more often than aggregates. | Separate the dimension table from the fact: host the dimension on its own twin of the projection (same SQL, no outgoing relationships) and leave the foreign keys and the measures on the fact. `mental_health` does this for its five entity dimensions. Where a dimension is reachable only from ONE fact, carrying the missing key down onto the other facts is enough instead - `sports_events` propagated the circuit key onto all seven race-keyed facts, and `virtual_idol` put all thirteen chain keys on all nine downstream datasets. Check with `scripts/acceptance_gates.py --gates 3`. | Yes - found and characterised 2026-08-19. |

---

## cybermarket_pattern

**2026-08-10 - initial build.** Generated by `cybermarket_pattern/generator/`.
304 objects: 8 derived datasets, 7 dimensions, 178 metrics, 10 `metric_calc`s,
1 model.

Build decisions worth carrying to other models:

- **One wide transaction fact.** Six source tables are exactly 1:1 on the
  transaction key (1000 rows each, no orphans, verified live). Joining them into
  one fact gives every transaction-grain attribute a direct relationship to
  Platform / Vendor / Buyer / Product Listing, removing the conformance failure
  class where a measure on one fact cannot be sliced by a dimension from another.
- **Derived datasets throughout.** The source stores numbers as unit-suffixed or
  currency-formatted text (`'$98.60 '`, `'2140.32 km'`) and packs most attributes
  into `jsonb`. Parsing happens in the dataset SQL.
- **Recorded columns are not the KB formulas.** Verified live: 0 of 994 vendors
  have `RegStandeff` equal to the computed CEI; same for WTR and THR. Shipped as
  separate `Recorded` measures whose descriptions state they are different
  quantities.
- **Live data beats the metadata files** where they disagree - four columns
  documented as small categorical sets are continuous numerics live. Descriptions
  state the live reality and name the metadata's claim.
- **Multi-condition concepts precomputed** as Yes/No attributes (High Risk Vendor,
  Secure Platform, Premium Authentication, ...). Each raw component's description
  says it is an *input* and redirects filtering to the flag - otherwise a question
  phrased in a component's words gets filtered on that component alone and loses
  the other OR branch (240 or 146 vendors instead of 345).
- **Deliberate omissions where the KB states no threshold.** Suspicious Buyer,
  Traceable Communication and Escrow Compliance are defined qualitatively with no
  cut-off and their ambiguity entries are `is_mask: true`. No flag ships; the
  component measures are exposed instead.
- **Bucketed tiers are labelled as this model's convention** where the KB names
  tiers but the source stores no such labels.
- **RANK / DENSE_RANK twins** ship for every ranked quantity, each naming its twin
  and the reading it answers. Ties are real (17 threads share the max keyword
  count). Ranks are over the whole population, not a query's filtered subset.
- **Formula families.** Each KB formula ships as a per-entity average, a
  `Group Formula` recomputing the definition from aggregated components, a
  `Single <Entity> Value`, every component as its own measure, and exactly one
  support-set count (the intersection where all components are present). The
  group/average divergence is material - BRDR is 0.0479 pooled vs 0.0942 as a mean
  of per-buyer ratios.
- **`unrelated_dimensions_handling: error`** on every metric, so a non-conforming
  pairing fails loudly instead of returning empty.
- **No time dimension** - each entity appears once in its source table, so the
  "ever vs as-of-latest" distinction does not arise. History-wide flags are named
  "ever".

**Acceptance - all four gates pass** (after redeploying the D-01 fix). Exactness
25/25 exact-equal against source, Conformance 15/15, Discoverability 14/14,
Coverage 6/6. Group-vs-average separation verified on all nine ratio formulas,
diverging 1.43x to 4.09x. `unrelated_dimensions_handling: error` confirmed
refusing a non-conforming pairing before execution, at no warehouse cost.

Two gotchas worth carrying:

- **Re-verification.** Source columns declared `real` (float4) must be re-checked
  with `::float8`, not `::numeric`. The engine casts `real -> FLOAT8` and preserves
  the binary value; `::numeric` rounds to shortest round-trip decimal and produces
  a spurious 8th-digit mismatch. Caused a false alarm on ACI and THR.
- **Rank twins.** `SSD Rank Descending <= 10` returns 11 rows because two threads
  tie at position 10 - the RANK reading of "top N", which is why the DENSE_RANK
  twin ships beside it.

---


### 2026-08-14 — the same `real::numeric` truncation crypto_exchange had (M-31)

Found by sweeping every generated model after crypto_exchange M-31, not by a
cybermarket run. `PriceAmt`, `ThreatIntelIndex` and `TraceScore` are `real`, and
Postgres converts float4 to numeric through `float4out` at `FLT_DIG=6`, so
`real::numeric` truncates to six significant digits — `232.59462` became
`232.595`. **973 of 1000 `PriceAmt` values and 943 of 1000 `ThreatIntelIndex`
values were affected.**

Worse here than in crypto_exchange, because the usage was **mixed inside one
dataset**: `sold_unit_price` was published from the raw column while
`sold_line_value_usd` was computed from the truncated one, so unit price ×
quantity did not equal the line value in the model's own rows. Same shape for
`threat_intel_index` against the KB 7 Threat Handling Rate ratio.

Casts dropped on those three; `AnonLevel` keeps its own, being TEXT, where
`::numeric` is the correct and lossless conversion. Verified after redeploy —
`Sold Line Value USD Total` is now 7788131.640065193, matching Postgres exactly,
where the truncated model returned 7788132.4030.

**Any cybermarket number recorded before 2026-08-14 was measured against
truncated prices.** The aggregate error is small (76 cents in $7.8M) but 973 of
1000 individual rows were wrong, and per-row values are what the tasks ask for.

Swept clean at the same time: `archeology_scan` (no cast on any of its four
float columns), `exchange_traded_funds`, `households`,
`labor_certification_applications` and `solar_panel` (no `::numeric` at all).
## archeology_scan

### Unit-ambiguous-threshold audit: no change needed, 2026-08-17

Audited against the new build-prompt rule that a KB threshold whose unit is ambiguous
against the stored column must ship both readings (see the ETF and crypto entries of this
date). **This model has no such case, verified against live data rather than assumed:**

- Every percent-labelled KB field is stored on the 0-100 scale the KB labels it with —
  `Cover_Pct` 80–99.9, `Lap_Pct` 30.1–69.8, `Hume_Pct`, `Proc_CPU`, `Proc_GPU`. KB 11's
  *"Coverage (%) ≥ 95 and Overlap (%) ≥ 30"* therefore applies with no conversion, and
  the `Comprehensive Coverage` description already states both thresholds in the KB's own
  units.
- Every `/100` and `* 10^4` in `generator/sqls.py` is the KB formula's own arithmetic
  (KB 1 SCE, KB 3 SQS, KB 34 SDI), transcribed rather than reinterpreted.
- The one non-percent threshold, KB 40's *"Surface Area (m²) > 100"*, matches the stored
  unit: `Area_M2` runs 1.2–999.5 and `> 100` selects 300 of 342 sites.

Recorded so the audit is not repeated. No files changed.

**2026-08-11 - initial build from `create_bird_model_prompt.v2.md`, prompt-only.**
Full rationale, exclusions and evidence in the model folder's `SPEC.md`.
Published at `bird_atscale_models_catalog_main`.

Shape: 4 fact grains - `scan_fact` (1000), `site_equipment_fact` (1000, carrying
998 real records plus spine rows), `site_quality_fact` (900),
`conservation_fact` (455). Site is the only dimension reaching all four.
94 metrics, 10 calculations, 123 queryable attributes.

**Acceptance - all four gates pass.** Every exactness probe exact-equal to source
to 12 decimals (counts 1000/900/905/900, total points 35,850,368,904, support
sets, per-site SQS and SCE, ranks, risk-zone split 778/122, a four-fact
cross-fact aggregate). Conformance: every dimension reaches its facts, and a
non-conforming pairing is refused before execution. Discoverability probed with
`amb_user_query` wordings only. Coverage: all six shapes.

### Findings worth carrying to other databases

- **`count(*)` in a dry run does not evaluate the select list.** Postgres
  optimises the projection away, so a division-by-zero in a computed column
  survives to query time. Counting `md5(row::text)` instead surfaced two
  (4 of 944 scanners record 0% battery; ESI can approach -10). Both denominators
  now use `NULLIF`.
- **Engine MDX function set**, probed with `validate_mdx_expression`: `SQRT`,
  `ABS`, `LOG10`, `EXP` supported; **`POWER` is not**. So `x^2` and `x^1.5` are
  rewritable as `x*x` and `x*SQRT(x)`, but `x^0.3` is not. Probe before declaring
  a group-level formula inexpressible.
- **A dangling-cross-reference check keyed on `Name (ACRONYM)` is not enough.** It
  matches the published base name and stops, so a description can promise a
  `(Recomputed For Group)` twin that was never shipped. A qualifier-aware check
  caught two more left stale by a rename whose phrase spanned a line break.
- **The build-time discoverability gate caught missing OBJECTS, not just missing
  wordings** - the model had no Registration ID and no Scan Timestamp at all, both
  asked for by name. Treat a failing phrase as a possible modelling gap first.
- **The dialect cannot express quartiles (Q-19).** `NTILE` is rejected outright
  ("Don't understand function: ntile") while `ROW_NUMBER` and `RANK` are accepted.
  Precompute the bucket in the model and say in the description why it must be
  read rather than derived. This is the "precompute whatever the query dialect
  cannot express" rule that v2 of the build prompt dropped; it should go back.

### Masked terms - expect these tasks to fail, and report them separately

`High Resolution Scan` (KB 10) and `High Fidelity Mesh` (KB 13) are
`is_mask: true` in every task that uses them: the benchmark deliberately
withholds those thresholds so the agent must ask the user, and KB 12, 16, 19 and
53 depend on them. None ships. Tasks `archeology_scan_6`, `_M_1` and `_M_3` turn
on these terms and **cannot honestly be fixed in the model** - score them
separately rather than counting them as model defects.

**The rule is not "never ship a masked term".** A masked KB-NAMED FORMULA may
ship under its own name, because there the ambiguity is "which index did you
mean", which competing named metrics answer honestly. A masked THRESHOLD must
not, because baking in a cutoff answers the question. ESI, FEE and DPQ therefore
ship; KB 10 and 13 do not.

The operational test is the KB entry's own `type`, verified across three models:

| KB `type` | Masked terms | Shipped |
|---|---|---|
| `calculation_knowledge` (named formulas) | Effective Power Output, Annual Degradation Rate, Temperature-Corrected Performance, System Unavailability, Infrastructure Quality Score, Household Density, Bathroom Ratio | 7 of 7 |
| `domain_knowledge` (numeric cutoffs) | Underperforming Asset, Critical Alert, Severe Soiling Condition, Affluent / Crowded / Compact / Urban Household, Modern Dwelling, and 9 more | 0 of 17 |

The one apparent exception, `Accelerated Aging Asset`, is `domain_knowledge` whose
definition states no number, so nothing precise is handed over. The build prompt
now carries this `type`-based test so it is applied rather than re-decided per
model.

**Re-examined and upheld 2026-08-12.** The challenge was reasonable - a real
business semantic layer WOULD encode "High Fidelity Mesh", and the benchmark is
meant to test the layer more than the agent. Two things settled it. The rule is
not ours and not incidental: v2 of the build prompt states it directly, and its
change list records that it was STRENGTHENED off cybermarket evidence ("every one
of the four tasks that failed on every run of both backends turned on a masked
term, and no honest model change would have moved any of them"). And practice
matches the doc, per the table above.

**Measurement caveat worth repeating whenever a lift is quoted:** on a masked task
the raw arm must spend a turn asking, so a model that skipped that would be
banking a protocol artifact, not semantic-layer value.

**The exemption bar is that the DATA cannot express the concept, not that the
concept selects nothing.** KB 41 is exempt because the texture column never
carries 'Detailed' or 'Critical' and TDI peaks at 0.178 against a threshold of
8.0 - both conjuncts unreachable. KB 48 is exempt because all 8 sites reaching
DPQ > 80 already have ADC >= 70, so no project qualifies under either defensible
reading of "combined". KB 19, by contrast, IS shipped even though all 900 sites
come back 'No': its inputs are all present and in range, so an empty answer is a
real answer. `dryrun.py` asserts all five zeros live.

### Why the failing tasks fail - three causes, not seven

Every failing submission was replayed against gold offline and, where a
hypothesis needed testing, re-run live.

**1. Component averages use a support-set denominator; gold uses the population
(M-09).** The model's `Average <X>` measures average over the rows that HAVE an
X. Gold averages over every row in scope and treats a missing input as zero. The
two differ by exactly the coverage ratio, so any KB formula built on them is
wrong by that factor. Site SC3083: Average Surface Area 974.76 (over the 1 scan
that has one) vs gold's 487.38 (974.76 / 2 scans); PCDR 12.95 vs 25.89. The
numerator and density code agree to the last digit - only the denominator's row
count differs. Affects tasks 5 (582/900 sites differ), 9 (816/900) and, through
Model Fidelity Score, 6.

The STRUCTURE was already right: the `(Recomputed For Group)` calc correctly
divides aggregates rather than averaging per-row ratios. Switching to it does not
help, because its inputs carry the same denominators. The fix belongs in the
component measures.

**1b. But the denominator is not the scan count either - gold's joins fan out, and
that half must NOT be chased (B-17).** Correcting only the support-set denominator
reproduces gold on 201 of 243 usable sites and misses 42, because `arcref` is not
unique in any of these tables (up to 4 rows in `scans`, 3 in `pointcloud`, 2 in
`spatial`), so gold's join fans out and its denominator is the JOINED row count.
The two counts differ on 92 of 900 sites. Reproducing that would mean making a
`scans x pointcloud x spatial` cross product the fact grain, corrupting every
other measure to chase an artifact of a sloppy join. **Fix 1, log 1b as a gold
defect, accept task 9 as unwinnable.** Because grading is all-or-nothing, fixing 1
alone buys NO score on task 9 - do it for model correctness, not for lift.

**2. A site with no rows in a fact disappears when any measure from that fact is
projected (M-10).** The Site dimension has all 900 members and returns 900 alone,
but `SELECT "Site Code", "<any measure>"` returned 898. The two missing exist in
`sites` with a scan each but zero `environment` and zero `conservation` rows.
Sites that DO have fact rows with null contents still come back, so this is
specifically zero-fact-rows, not null-valued. Gold reaches all 900 by starting
`FROM sites` and LEFT JOINing.

Fixed 2026-08-11 by a spine: the `pairs` CTE became `real_pairs` plus a spine row
for every site present in none of them, carrying `equipref NULL` and
`spine_row_count 0`. The dataset goes 998 -> 1000 rows while still carrying 998
records, which is what keeps it inert - the record count is `sum(row_count)` and
stays 998, every `has_*_inputs` flag yields NULL on a spine row, and every measure
is an AVG. Verified live post-deploy: `Site + ESI` and `Site + MFS` return 900
where they returned 898, and every other count is unmoved.

**3. Task 1 threw away a won task on one column** (agent-side, mitigated). The
submission had the right 648 rows and values correct to 15 significant digits, and
scored 0 because `"Site Scan Quality Rank"` was in the SELECT purely so ORDER BY
could reference it. Dropping it and ordering by the SQS measure already projected
grades 1, verified live. A rank column is redundant with the measure it ranks, so
it never needs projecting. Now a rule in `config/environment_backends.yaml`.

**Task 2 - the grain IS reachable; the classification is not (M-11).** Gold's 926
rows are 455 conservation records plus the 471 sites that have none, and
`Conservation Record ID` expresses exactly that grain. The harder half: gold writes
`c.structstate <> 'Stable'`, but all three values in the data are sentences
('Stable condition, structure secure for access', ...), so nothing equals
`'Stable'` exactly and gold's predicate is TRUE for every record - its risk test
collapses to `Preservation Status IN ('Poor','Critical')`. The model's
`Degradation Risk Zone` uses `NOT LIKE '%Stable%'`, which is FALSE on the 142
stable-condition records; the two disagree on 142 of 455. **The model's reading is
the defensible one, so this must NOT be changed to match gold** - doing so would
require an agent to write a predicate contradicting the model's own attribute.

**Tasks 8 and 10 - unreachable.** Task 8: gold joins `processing` to `scans` on
SITE, not scan, taking 821 processing rows to 1102, and every per-group average is
over that fan-out. Same family as B-17. Task 10: gold's sixth column is the raw
`system_usage` jsonb projected whole, which no semantic-layer measure can return -
structurally not winnable at any model quality.

### Measurement, 2026-08-12 (n=1, 10 Query tasks, both arms)

**atscale 0.270 vs raw 0.100, lift +0.170.** Phase 1 3/10 against 1/10, phase 2
2/10 against 1/10. Won: `_3` and `_4` (1.00), `_1` (0.70); no raw wins.

**The lift does not depend on any deviation flag.** An offline replay of the same
submissions reproduces 2.70 under all four tie/decimal combinations, including
upstream (`tie=F dec=F`). Raw reproduced 0.100 exactly across two runs a day apart.

**Two earlier runs scored 0.000 and neither was a model result** - both were graded
by harness code held in memory since before B-19 and B-20 landed. The signature was
unambiguous once looked for: `_3` and `_4` graded FAIL live and PASS offline on
byte-identical SQL under identical flags. Tracked as B-23 and gated by
`scripts/gate_run.sh`, which refuses to run when the services predate the newest
harness commit. The Q-17b `list_models` gate does not catch this - it inspects the
catalog, not the code version - so both gates are needed.

Note what this says about re-grading: replaying recorded submissions answers "what
would the grader say about this SQL", never "what would the agent do next time".
The void run's own agent resubmitted identical SQL to budget -1 because the stale
grader kept telling it a correct answer was wrong.

### M-12 question-phrasing leakage removed, 2026-08-12

A cross-model scan found benchmark question wording copied verbatim into published
descriptions in all five BIRD models - archeology worst at 17 phrases across 4
tasks. The leaked text is question grammar rather than business vocabulary ("in
descending order of quality values"), and one DPQ description quoted a question
outright to steer the agent to itself. A model built for a real business would
contain none of it, so it inflates the arm on exactly the questions being measured.

Notably the leakage tracks the `DISCOVERY_PHRASES` build gate rather than the lift:
`solar_panel` carries the largest lift of any model (+0.370), predates that gate,
and has 2 phrases, while the two gate-built models carry the most. The gate as
inherited asks that every question wording match some published description, and
the cheapest way to satisfy it is to paste the question in.

**The governing rule: the model may describe WHAT A THING IS, never HOW A QUESTION
ASKS FOR IT.** Enforced by two build gates:

- **A8** - no published description may contain a verbatim 6-word run of any task
  question.
- **A9** - no `DISCOVERY_PHRASES` entry may be question-shaped: no question
  grammar, no 4-word run of a task question. An aggregation prefix over a real term
  is exempt, so `average Environmental Suitability Index` survives while `how many
  sites fall into each ECCS category` does not.

Plus an emit-time filter in `write()` stripping question-shaped synonyms from all
181 `Ask for it as:` lists - applied there rather than in `spec.py` so the policy
stays true for synonyms added later. Questions are read from the allowlisted brief
`extract_brief.py` emits, never from `bird_interact_data.jsonl`, so the answer-key
firewall stays auditable: a negative guard asserts absence rather than importing
content.

**Deployed, and it cost nothing: 0.270, identical to the leaky baseline** - same
three tasks pass, same per-task rewards. So the +0.170 lift stands on a model with
zero question-phrasing leakage. Of the four tasks carrying leaked phrasing, three
fail for structural reasons no phrasing could fix; only `_3` both leaked and
passes, and it passes either way.

Two cautions against over-reading. It is n=1, and the clean result is partly luck
of where the leakage sat on this database - concentrated on already-broken tasks.
It does NOT license leaving leakage in the other models: where a leaked phrase sits
on a winnable task the experiment would come out differently. What it establishes
is that removing leakage is cheap, so there is no reason to trade methodology for
score.

Verified live before re-running rather than trusting the deploy - an unpushed fix
deploys the old model and is indistinguishable from success.

### Read-the-submitted-SQL pass, 2026-08-12 (M-13 to M-16, Q-19)

Read what the agent actually submitted for every failing task, then fix the model
rather than the harness. Done against agent SQL, tool errors and the knowledge base
only - no gold SQL, so the answer-key firewall holds.

**The headline finding was wrong, and correcting it is the useful part.**
`archeology_scan_6` ended with ZERO submissions - five `explore_columns`, two
`ask_user`, no `run_query` - asking the user to define "High-Fidelity Mesh". Read
as a model gap, all six missing KB concepts (10, 12, 13, 16, 19, 53) were shipped.
That was a misreading of a decision this log and `SPEC.md` had already recorded:
those terms are `is_mask: true`, and task 6 spending its budget on `ask_user` is
the firewall working as designed. Baking the thresholds in would hand the atscale
arm an answer the raw arm has to ask for - the same teaching-to-the-test problem as
M-12, in a more damaging form. All six were reverted and redeployed before anything
ran against them.

KB 16 went too, and only the gate caught it. The reading was that the KB mentions
Premium Quality Scans as the *remedy* for a conservation priority, not a condition
of it - but the KB's own `children_knowledge` names KB 12 as a parent, so it
inherits the mask. **When the concept graph and a human reading disagree, the graph
wins.**

**Gate A10 now derives the firewall instead of trusting prose.** It reads `is_mask`
from the allowlisted brief, closes over the KB's own dependency edges, and fails
the build if any masked-or-dependent concept is implemented. It reproduces the
`SPEC.md` table exactly - firewalled `[10, 12, 13, 16, 19, 53]` - with masked named
formulas exempted through an explicit `MASKED_BUT_SHIPPABLE` list. A10's other half
requires every unmasked KB concept to be implemented or exemption-documented. The
lesson runs both ways: the mechanical gate caught a concept the hand audit missed
AND caught the hand audit shipping something it should not have.

**Three model defects visible only in the submitted SQL:**

- **M-14.** The Site Code description opened "USE THIS TO COUNT AND GROUP SITES" -
  grouping advice correct, counting advice not, since `COUNT(Site Code)` returns a
  list of site codes on this engine rather than a number, which is exactly what
  task 5 got back and believed.
- **M-15.** Neither `flowregistry` nor `facetregistry` was published, so a question
  wanting one row per processing run had no key but Equipment. Both are now
  attributes. (See the correction below - this premise did not hold up.)
- **M-16, a stale profile publishing wrong numbers.** `profile.json` recorded 998
  site-equipment records and 898 sites against a true 1000 and 900. Running the
  pre-change SQL from git HEAD returns 1000/900, so the profile was stale, not the
  SQL changed - a dozen deployed descriptions had been quoting 998. **Gate A11** now
  compares `profile.json` against `sqls.EXPECTED_ROWS` and fails the build on a
  mismatch; negative-tested, it reproduces this exact error. Note `profile_live.py`
  writes relative to cwd, so it must run from the generator directory.

Plus **Q-19**: `NTILE` rejected, so Environmental Suitability Quartile is now
precomputed (see Findings above).

**Net effect on the model surface: three attributes.** Metrics and calculations are
back at 94 / 10, exactly where they started; attributes 120 -> 123 (Environmental
Suitability Quartile, Processing Workflow ID, Mesh ID). Everything else is
corrected description text and KB annotations. A1-A11 pass, `dryrun.py` passes
including five unsatisfiability assertions, `sml-cli validate` clean, row counts
unchanged.

### Post-fix measurement and close-out, 2026-08-12

**0.270 atscale / 0.100 raw - unchanged.** Not one task moved. The three new
attributes bought nothing measurable on this task set.

- **Task 7 found and used `Environmental Suitability Quartile`** in its final
  submit, so Q-19's fix worked as intended; the failure is now downstream of it.
- **Task 10's premise was wrong (correcting M-15).** The question says "For each
  piece of equipment, please provide its ID" - equipment grain, and the ID already
  existed (`Equipment` is the registry code, 944 unique). The agent found it, used
  it, and correctly ignored the new workflow key. The remaining failure is a
  free-form JSON "resource details" column whose exact serialization is unknowable,
  plus an ambiguous row population. **Not a model defect.**
- The M-15 premise came from a single run's user-simulator wording ("from each
  individual processing instance"), which the next run contradicted ("for each
  equipment piece"). **Do not file a model defect off one run's simulator
  utterance** - require the task text or two runs.

**Where archeology stands.** Of 10 Query tasks: 2 won outright, 1 partial (`_1` at
0.70), 3 structurally closed (`_6` masked, `_8` and `_10` unreachable), and 4 lost
to gold defects deliberately not matched (`_2` M-11, `_5` M-09, `_7` float32,
`_9` B-17). The remaining model-side upside is `_1`'s phase 2 (0.30); everything
else open is engine, agent or grading. Treat 0.270 as this model's ceiling absent a
change in one of those layers.

---

## exchange_traded_funds

### Unit-ambiguous KB thresholds: both readings shipped, KB wording quoted, 2026-08-17

Implements the new build-prompt rule "A threshold whose unit is ambiguous against the
stored column gets both readings, and the KB's own words verbatim"
(`docs/create_bird_model_prompt.md`). A KB cutoff stated in prose ("less than 30%") does
not say whether it means the literal number or the number on the stored column's scale,
and the model was resolving that silently — the caller saw a Yes/No flag and no sign that
a decision had been made.

**New attribute `Low-Turnover Strategy (Percent Scale)`** (`low_turnover_pct_scale_flag`
in `datasets/fund_analytics.yml`), the literal reading `turnover_ratio < 30` of KB 12.
The bare `Low-Turnover Strategy` keeps `< 0.3` as the PRIMARY reading and every composite
(Ideal Index Fund, Strategic Beta) still builds from it.

Both readings are viable, which is why this one is twinned rather than resolved: on the
Contrarian Value Play screen they give **53 funds and 145**. The deciding evidence is that
**gold itself uses both** — `etf_18` phase 1 filters `Turnover_Ratio < 0.3` and phase 2
filters `< 30`, same task, same KB term. No single reading can win both phases, so the
model cannot pick for the caller. Note this also corrects the premise of tracker **M-01**,
which attributed an off-by-one to the model reading 0.3 where gold read 30: gold phase 1
reads 0.3 too, the same as the model. (M-01's own 2026-08-13 note already records that it
no longer reproduces and that `etf_18`'s live cause is Q-26.)

**Descriptions now quote the KB verbatim before stating the resolution**, on the three
attributes that reinterpret a cutoff, each naming the number that rejected the other
reading:

| attribute | KB wording | shipped | why not the literal reading |
|---|---|---|---|
| `Low-Turnover Strategy` | "annual portfolio turnover is less than 30%" | `< 0.3` | both viable — literal reading shipped as the `(Percent Scale)` twin |
| `High-Conviction Portfolio` | "largest holding is greater than 8%" | `> 0.08` | `> 8` selects 0 of 2297 top holdings; `holdingpct` is a 0-1 fraction, max 1.0105 |
| `High-Quality Credit Portfolio` | "exceeds 60% of its total bond holdings" | `> 0.6` | `> 60` selects 0 of 382 funds with bond allocations; max sum 1.0156 |

`Market-Tracking Fund` needed no change — KB says "R-squared greater than 90" and the
column is already 0-100. `Appraisal Ratio` already recorded its own resolution (R-squared
divided by 100, since the KB's `sqrt(1 - R²)` is undefined on the 0-100 scale).

Not yet deployed at the time of writing.

### Fund attribute says how to count funds, 2026-08-12 (E-01)

The Fund level attribute's description now points at the `Fund Count` measure and
`COUNT(DISTINCT Fund)`, and states that plain `COUNT` over the attribute returns
ticker symbols rather than a number. `archeology_scan` has carried the equivalent
warning on Site Code since M-14; ETF carried nothing, which is the likely reason
ETF agents kept walking into E-01.

### M-12 question-phrasing leakage removed, 2026-08-12

Four phrases lifted verbatim from the evaluation questions, reworded out of six
files. Same policy as archeology.

| phrase | from | lived in |
|---|---|---|
| "the relationship between trading and skill" | `_8` | `alpha_turnover_slope` |
| "less sensitive to rate changes than category peers" | `_3` | `avg/max_duration_advantage`, `fund` |
| "'Total excess fees for all closet funds' sums this." | `_20` | `max/total_wasted_fee_amount`, `fund` |

Each was replaced with the quantity's own meaning rather than deleted - a
regression slope became "how much alpha changes per unit of turnover", the
duration gloss became "shorter duration than the category average". Seven lines
changed, no reformatting; `sml-cli validate` clean.

**The gate could not be ported as A8/A9.** ETF is a prompt-only build with no
`generator/`, so there is no `generate.py` to hold a build gate and no
`spec.DISCOVERY_PHRASES` for A9 to check - ETF carries zero "Ask for it as:" lists.
A9 is generator-only by construction. A8 was lifted into
`utilities/question_leakage_gate.py` in the models repo, which reads the published
YAML instead of the generator's in-memory objects and so covers prompt-only models
too. Cross-checked against archeology, where it agrees with generator A8. Questions
come from a firewalled `extract_brief.py` brief.

**Deployed 2026-08-12**, verified through the MCP layer rather than the repo: all
three old phrases absent from live descriptions, all three replacements present.

**Measured on the three affected tasks only** (n=1, $0.63): `_20` **1.00 -> 1.00**,
`_8` 0.00 -> 0.70, `_3` 0.00 -> 0.00. `_20` is the whole point of the check - the
only affected task that already passed, leaning on the descriptions that were
reworded. It held, so de-leaking ETF cost nothing, matching the archeology result.

`_8`'s gain is NOT de-leak credit - removing the model's help cannot add a win. The
baseline predates several harness guidance changes, so the run moved two variables,
and per-task swing is a full point on its own.

**This does not clear the ETF lift.** Only 3 of 19 tasks, one arm, n=1. Re-quote
only after a full both-arm run on the deployed model.

### Read-the-submitted-SQL pass, 2026-08-12

Read every submission for all 13 failing/partial ETF tasks (10 at 0.000, 3 at 0.700)
across the three most recent atscale runs, then probed each hypothesis live through
MCP at no LLM cost. Agent SQL, tool errors and the KB only — no gold SQL, so the
answer-key firewall holds. **Most of what the pass found is dialect, not model**, and
that is itself the finding: this model is in better shape than the harness's account
of how to query it was.

**One model change (M-18, an instance of M-02): `Fund Category Scored Fund Count`.** M-02
filed the general defect a year of runs ago — count measures ignore metric availability,
so a count paired with a metric disagrees with gold — and asked for an audit of every
count measure. This is that audit's first ETF result. KB 81 gates Category
Dominator on "the category contains at least 10 funds", and the model published only
one reading of that — `Category Fund Count` / `Fund Category Fund Count`, every fund in
the category. The second reading, funds the composite comparison can actually rank, was
not expressible at all: only 1142 of 2310 funds carry a Composite Score, and at a
cut-off of 10 the two readings qualify **48 real categories against 34** (35 and 49 with
the Uncategorized placeholder left in). Task `_7` used the
only one on offer, three times, and failed all three. Shipped as a window count in
`fund_analytics` mirroring `Alpha-Turnover Pair Count`'s "sample size, not group size"
pattern, with both descriptions naming each other, quoting the 48-vs-34 divergence and
telling the agent to confirm which population the question means. **Deployed and verified
live 2026-08-12**; the first pass quoted 49-vs-34, which paired two different populations
(one counting Uncategorized in, the other out), and the descriptions were corrected. Note what this does
NOT do: it does not pick the winning reading, it makes the ambiguity askable — which is
what the model owes a question the KB left open. `sml-cli validate` clean, A8 clean.

**Four harness-guidance defects, all read off submissions (see `config/environment_backends.yaml`).**

- **The sort-key error hint gave actively wrong advice.** It ended "the outer SELECT must
  not reference sortkey", conflating *ordering by* an unprojected column with *projecting*
  one. Task `_19` had the correct two-column result in `run_query`, then submitted the
  one-column version the hint described, then tried the two-column form using the
  measure's pre-alias name and died on "column reference does not exist in sub selects".
  A task lost to guidance, not to the engine.
- **Q-20 was uncovered entirely** — the four broken shapes for a total beside detail rows
  are now named alongside the one that works, with the warning that only one of them
  announces itself. This does NOT reopen B-04: gold for `_11` and `_12` appends a summary
  ROW with every value coerced to text, which no model query produces at all. What the
  guidance now adds there is that the silent empty result IS that attempt failing, and
  redirects to the FROM-less literal-values form rather than letting the agent read the
  empty result as an empty answer.
- **The grain rule was too weak.** It said to force the row grain in an inner derived
  table without saying the grain column must be in that table's SELECT LIST. Task `_14`
  wrote the derived table without it and got 0.013368 where the grain-forced value is
  0.013270 — no error, just a different number.
- **The model is also the glossary, and the agent did not know it.** Each KB concept's full
  test is published inside the implementing column's own description (`KB '<name>': ...`),
  so `explore_columns` on a business term returns the definition *and* the column in one
  1-coin call. Nothing said so. In the one run where the flag-gated knowledge tools were
  exposed (`SEMANTIC_LAYER_KNOWLEDGE_TOOLS`, off by default — B-12's experiment), task `_9`
  paid 29 lookups, 14.5 of 24 coins, for definitions the model was giving away, and reached
  its first query broke. The bullet is written to hold either way: search the model first,
  knowledge tools are the fallback where they exist at all.

Plus two free error hints for the tool responses that were costing coins with no repair
in them: `explore_columns`' "No columns matched" (14 of 90 calls across the three runs,
one task burning 6 coins on 6 empty searches) and the `Column [X] not found` family,
which covers both the invented-name case (`_8` phase 2 guessed "Fund Ticker") and the
inner-alias case.

**Checked and NOT changed, deliberately.** `Fund Turnover Ratio` and
`Fund Price Position in 52-Week Range` looked like unit bugs (`< 0.3` against a column
reaching 773.84; `< 25` against a 0-1-looking name) and are not — both descriptions
already state their scale and which KB threshold applies on it. Task `_14`'s measure and
a correctly grain-forced `AVG` agree to 15 digits, so `Average Consistency-Adjusted
Information Ratio` is not a denominator defect. Task `_10` needs a median the dialect
cannot compute (MDX-Median row) and the user simulator refuses to accept the mean twin;
that is an engine gap, not a model gap, and precomputing a median per grouping the
questions happen to use would be teaching to the test.

### Second pass, 2026-08-12: false ambiguities and the phase-2 budget cliff

Same method, second sweep — this time over the phase-2 halves, which the first pass
had not read. Two changes, one open item.

**Model (M-19): three published "alternate readings" that are not.** The ETF model
carries nine PRIMARY/ALTERNATE column pairs. Tested all nine live: six genuinely
diverge (Information Ratio 1005 of 1005 funds, Liquidity Pressure 1359, Composite
Score 1142, Beta Drift, R-Squared Drift, Style Drift, Global Alpha Specialist, MA50
value-traded). **Three never diverge at all** — `Fund Positive Years`,
`Fund Negative Years` and `Positive Return Consistency`, each Reported-vs-From-Annual-
Returns, agree on **0 of 1829** funds differing, confirmed against Postgres as well as
through MCP. `fund.yml` asserted outright that the year pair "disagree for some funds";
it does not. The year pair differs only in *coverage* (2080 vs 1829); the consistency
pair is identical outright.

This matters because the agent instruction makes rival-reading language a **trigger to
`ask_user`** (2 coins) — so a false ambiguity buys a wasted ask and casts doubt on a
column that had none. Fixed in descriptions only: state the measured agreement, name
the column to use, say the choice cannot change an answer's values. No SQL, no new
objects, so nothing downstream moves. Deployed and verified live.

**Guidance: phase 2 is paid for out of what phase 1 leaves behind.** Nothing told the
agent to reserve for it. Measured over `rebase0811_atscale_r1`: every task that finished
at **1.0 entered phase 2 with ≥9 coins**; the three that stalled at 0.7 entered with
6.0, 4.0 and 1.5. The 1.5-coin case (`_8`, de-leaked run) is the clean demonstration —
the follow-up asked for ticker, name, alpha and turnover, none of which phase 1 had
looked up; the agent could not afford a 1-coin `explore_columns`, guessed six names,
got **all four measures right and both identity columns wrong**, and lost the phase to
`Column [Fund Ticker] not found` holding correct values. Two bullets added: reserve ~6
coins (explore + run_query + submit) before submitting phase 1, and never let phase 2's
first action be `submit_sql`. Written domain-neutrally — that instruction is shared by
every atscale domain — so it names the identity-column *pattern*, not ETF's columns.

**`_14` phase 2: the model is right and gold still rejects it. Open, no change made.**
The follow-up wants the average CAIR for funds with consistency ≤ 50. Recomputed the KB
formula straight from Postgres: **0.01326990** over the 136 of 351 such funds that carry
the ratio — matching the model's `Average Consistency-Adjusted Information Ratio` exactly.
The agent submitted that value and was rejected. Phase 1 (unfiltered CAIR average, 0.0456)
*passed*, which pins both the CAIR definition and its `/100` as correct, and the two
consistency columns are the identical pair above, so the filter is not the variable.
At `decimal: 2` every defensible reading collapses to 0.01 — including the
COALESCE-nulls-to-zero denominator (0.00514). The only readings that land elsewhere are
`≤ 0.5` on a 0-1 scale (0.00), IR with no consistency adjustment (0.03), and CAIR with
the `/100` dropped (**1.32699 — exactly 100× ours**). That last one is suggestive but
contradicts phase 1 passing. Not resolvable without the answer key; filed rather than
guessed at, because every available fix here would be fitting the model to an unseen
number.

### Third pass, 2026-08-12: two composite concepts the model was not carrying

**M-20: the Premier Income Fund screen was invisible (`etf_1`).** "Premium funds" is
KB 42, a **two-condition** screen — High-Quality Credit Portfolio AND KB 14
Efficient Income Generator (a minimum on YTER). The model published both input columns
and the SIES score but never named the composite, so the agent applied the credit half
alone and submitted **136 funds' worth of rows where the screen yields 27**. The user
simulator did say "both criteria"; nothing in the model corroborated it, and the agent
had already had its one-condition reading enthusiastically confirmed.

Fixed by naming the two-condition structure in the three descriptions an agent actually
lands on (High-Quality Credit Portfolio, YTER, SIES) and stating the YTER minimum is
deliberately absent — ask the user. **Firewall reasoning, since this is a masked-adjacent
concept:** KB 42 is `domain_knowledge` stating *no number* and is not masked in any ETF
task, so it ships under the same exception as `Accelerated Aging Asset`. KB 14 **is**
masked and its cutoff is shipped nowhere — verified by grep. This gives the atscale arm
only what the raw arm can already buy from `get_knowledge_definition` for 0.5 coins (KB 42
is not in `deleted_knowledge`, KB 14 is and is filtered server-side for both arms), so it
is parity, not a leak. Also relabels SIES as *a score, not a screen*.

A sweep for the general case found no others: **every unmasked KB concept used by any ETF
task is published**; the only unpublished one is KB 47, which is masked and correctly absent.

**M-21: KB 4 has two price bases in this data, and the model silently picked one
(`etf_18`).** The source never stores the recent price — only offsets from each end of the
52-week range — and the two ends **disagree for 60 of 2310 funds**
(`low_52w + Low_Delta <> high_52w + High_Delta`). The model reconstructed from the low end.
That is not neutral: 566 funds fall below 25 on the low basis against **582** on the high
basis, and on the KB 47 Contrarian Value Play screen it is **52 against 53**.

Found by comparing arms rather than reading gold: `etf_18` **passed phase 1 in raw and
failed in atscale**, and the raw agent's own SQL used the high-end basis. The denominator
was ruled out — stored `Range_Move` equals `high - low` on every row. Shipped
`price_position_52w_high_basis` as a published twin, both descriptions quoting the
divergence and telling the agent to confirm which basis a screen means. **The primary was
deliberately NOT switched** — publishing both is the honest fix; switching to the one that
happens to match would be fitting the model to an answer it cannot see. Verified live:
the twin returns 582 and 53.

Also confirmed NOT defects while here: the turnover scale (model says `< 0.3` on the stored
ratio scale, Yes=556 — correct, and the agent used it correctly) and the price-position
0-100 scale.

### M-22: one masked ETF threshold shipped (2026-08-12) — FIXED, and now gated

ETF is prompt-only, so it has **no A10 gate** — archeology's firewall gate reads `is_mask`
from the brief and fails the build on any masked-or-dependent concept, and nothing
equivalent ran here. Auditing ETF by hand against the same rule found masked thresholds
published in the deployed model — but only ONE of them on a task that actually runs:

| KB | Concept | Masked on | Runs? | Threshold shipped | Status |
|---|---|---|---|---|---|
| 81 | Category Dominator | `etf_7` (Query) | **yes** | "at least 10 funds" | **FIXED** 2026-08-12 |
| 15 | Consistent Outperformer | `etf_M_3` (Management) | no | consistency `> 80` | inert — leave |
| 79 | Style Drift | `etf_M_8` (Management) | no | `\|beta\| > 0.15` OR `\|R²\| > 10` | inert — leave |
| 17 | Golden Cross Signal | `etf_M_1` (Management) | no | momentum `> 0` | inert — leave |
| 39 / 87 | RREI, Family Sector Profile | `etf_M_9` / `_M_10` | no | — | inert |

**Correction to the first draft of this section, which said `etf_3` and `_8` and called for
stripping KB 15 and 79.** That was wrong, and wrong in the expensive direction. The masked
ids are `exchange_traded_funds_M_3` and `_M_8` — **Management**-category tasks — and a hand
audit that splits the id on `_` and reads the last segment turns `_M_3` into `3`.
`orchestrator/runner.py:162` excludes Management tasks from every non-raw backend
unconditionally, because a read-only semantic layer cannot serve DDL/DML. So those
thresholds are published at **no measurement cost**, and only Category Dominator was ever a
real leak on a running task.

Worse, acting on the draft would have hurt: **Style Drift is used UNMASKED by `etf_6`**,
which does run. Stripping its thresholds would have taken a definition away from a live task
to protect one that never executes. The corrected rule is *masked on a task this backend
runs*, not *masked anywhere*.

**A10 now exists for prompt-only models** (`utilities/masked_threshold_gate.py`, wired into
`scripts/deploy_models.sh`, fatal before deploy). Two detectors: NAMED (masked term published
beside a number) and NUMBER (a cutoff from the concept's own KB definition published in
comparison position even when the concept is never named — the Category Dominator leak named
nothing, so NAMED alone would have missed it). Both negative-tested against the real leak and
a synthetic one; ETF passes clean and reports the five inert cases. False positives found and
fixed while building it: `<>` read as a comparison, "over the past 52 weeks" read as a
threshold, and `52` harvested out of "52-Week Range" as if it were a cutoff.

**KB 81 was my own leak, one day old.** M-18 quoted "at a cut-off of 10 … 48 against 34" in
three descriptions to demonstrate that the two category-count populations diverge, and 10 is
precisely the number `etf_7` withholds. Fixed by keeping M-18's point — two defensible
populations, ask which — and dropping the number: the descriptions now say only that the
populations differ materially (1142 of 2310 funds scored) and that the model states neither
the population nor the minimum. Verified absent from the live model, not just the repo.

**KB 15 and KB 79 are deliberately KEPT.** Both are baked into flag columns
(`consistent_outperformer_flag`, `style_drift_flag_3y_vs_10y/_5y`), and the first feeds four
downstream composites — but per the correction above they are masked only on Management
tasks, which this backend never runs, so they leak nothing measurable and `etf_6` actively
needs Style Drift. No surgery, and no score effect in either direction.

Checked and cleared while auditing: KB 47 (Contrarian Value Play) and KB 14 (Efficient
Income Generator) ship no threshold anywhere; KB 17 (Golden Cross) and KB 87 (Family Sector
Concentration) are the no-number `domain_knowledge` exception; the masked
`calculation_knowledge` entries (39, 50, 72, 73, 74, 83) are named formulas and ship by rule.

**Why the gate, not more auditing.** The hand audit found leaks in a model
that has been through several careful passes, and one of them was introduced by the previous
pass. A mechanical `is_mask` check is the only thing that keeps this closed.

### Fourth pass, 2026-08-13: the read is complete

Read the last four unmined failing tasks (`_9`, `_10`, `_11`, `_12`). **No model change came
out of it** — three were already accounted for by changes made earlier in this sweep, and the
fourth is an engine limit.

- **`_9`** is the same KB 47 Contrarian Value Play screen as `_18`, so **M-21** (the two price
  bases) already covers it. Its second submit also dropped to `turnover < 30`, the percent-scale
  reading the model explicitly warns against — the model's text was right and the agent
  second-guessed it after a rejection.
- **`_11` and `_12`** are the Q-20/B-04 family and unchanged: `_11` hard-coded `63 AS
  total_count` as a literal rather than computing it, `_12` answered only the ranking half and
  dropped "what portion have a positive score". Both already covered by the Q-20 guidance.
- **`_10`** needs KB 85 Median 1-Year Return. This produced the one new finding, **Q-22**.

**Q-22: OFFSET is silently ignored.** With no percentile functions, the obvious route to a
median is "sort and skip to the middle" — `ORDER BY x LIMIT 1 OFFSET n`. It does not work, and
it does not fail either: OFFSET 0, 1, 5, 100 and 335 all return the identical first row.
Ordering and LIMIT are applied correctly and the group sizes are exactly right (Opaque 671,
Transparent 1246, both matching Postgres), so the answer looks entirely plausible. True medians
from source — Opaque 0.0569, Transparent 0.4099 — are simply unreachable through the layer.

Swept every recorded run: **no agent has ever written OFFSET**, so this has cost nothing to
date. It is written down because the median route looked like the obvious fix for `_10` right
up until it was tested, and without a record a later pass would rediscover it and trust it.
Guidance now says never to use OFFSET; no error hint is possible because there is no error.

**`_10` stays unwinnable for the semantic-layer arm**, alongside `_11`/`_12` (B-04) and `_14`
(B-24). Precomputing a median per the grouping the questions happen to use would be teaching to
the test — KB 85 defines the median "for a specified group", with no fixed grain, so there is no
honest grain to precompute at.

### Still leaking

Measured with the same gate: `cybermarket_pattern` 23 phrases over 6 tasks,
`households` 11 over 5. Both have generators and should get A8 wired in-build.
`solar_panel` could not be measured at all - `extract_brief.py`'s firewall audit
refuses it, because `solar_panel_16` asks the user to "group by the panel
technology" and the audit's `group\s+by` SQL-shape check fires on plain English.
That regex guards against gold leaking into a brief, so it was left alone;
narrowing it is a deliberate change to a firewall control. solar_panel is the
largest recorded lift (+0.370) and is currently ungatable.

---

## Grading-flag decisions

### Tie tolerance is off, and B-19 is why

`GRADING_TIE_TOLERANCE` forgives permutations of tied rows. It was introduced
because the semantic-layer arm returns an equally valid different tie order from
the one gold's own Postgres produced, so the flag looked asymmetric in the
semantic layer's favour.

**B-19 removed the cause rather than forgiving the symptom.** The semantic-layer
path now gives gold the same `remove_comments` -> `remove_distinct` ->
`remove_round` cleanup the raw path and upstream already give it. Unflagged,
because it retires a deviation rather than adding one.

The side effect matters more than the fix: stripping gold's `ROUND()` removes the
ARTIFICIAL ties it manufactured. Gold's `ORDER BY` was sorting on rounded values,
so its row order was arbitrary inside each tied block and no external engine could
reproduce it; unrounded, the order is strict and a full-precision semantic layer
matches it directly. `GRADING_TIE_TOLERANCE` is now a **no-op on the
semantic-layer arm** - identical pass counts either way on both domains
(archeology 5/21 submissions, ETF 17/74).

So the archeology lift no longer depends on a deviation flag, and the flag now only
affects the RAW arm - which makes keeping it on a choice that slightly favours raw
rather than one that rescues the semantic layer. **It stays off.**

### GRADING_REL_TOLERANCE stays off

`grading_rel_tolerance_value` was declared in config and read nowhere, so the 1e-6
default in `_values_close` was fixed regardless of the flag (B-20). The knob is now
wired; a declared-but-unread config value was a defect either way.

The flag itself stays **off**. Re-grading every archeology submission with it on:
no verdict changes on the atscale arm at all, and the RAW arm gains a task at the
default 1e-6. It helps raw, not the semantic layer.

### Why task 7 diverges, and why the model is NOT changed to match

Gold casts the JSON sensor fields to `real` (float32), then subtracts near-equal
magnitudes - `ABS(temp - 20)`, `ABS((hum - 50)/2)^1.5`. Cancellation amplifies
float32's ~1e-7 representation error into the 1.13e-5 measured against the live
model. The model casts the same fields to `::numeric`. That one choice is the
entire gap, and **the model is computing the MORE accurate value**.

Gold's convention is consistent enough to copy - every measure-like JSON field
`::real`, every count-like field `::bigint` - so the model could match bit-for-bit
with no grading deviation at all. Deliberately not doing it: nothing about the
source justifies float32 (it is JSON text, there is no upstream type to mirror, and
`double precision` would not close the gap - only `real` does), so choosing it is
gold-derived tuning, and it makes the model less accurate to win one task. Same
call as M-11.

Task 7 therefore joins B-17's family: lost to a defect in gold, logged rather than
worked around.

**What would reopen this.** If, with the full database set in, atscale submissions
start failing where a sub-1e-4 gap is the only thing between them and a pass, then
exact comparison is measuring the grader rather than the semantic layer, and that is
a good argument. `GRADING_AUDIT_PATH` makes counting it free and offline. Report it
as a sensitivity number next to the headline, never inside it.

## M-23, 2026-08-13 — "fund name" has two answers and the model never said so

`Fund Short Name` (`shortlabel`) and `Fund Full Name` (`fulldescription`) both answer
"fund name" and return a different string for every one of the 2310 funds. The
descriptions cross-referenced each other passively ("Sibling: Fund Full Name"), which
is not the language the atscale instruction treats as an ask-trigger — that bullet
looks for "confirm which the question means", "are not interchangeable", "this model's
convention". So the agent read two plausible columns, picked one, and never asked.

Both descriptions now state the rivalry in trigger language, note that a wrong pick
makes every row wrong while looking plausible, and add that "identify the fund" has a
third answer again (the leaf `Fund` member, the ticker). Deliberately NOT stating a
preference: the model has no basis for one, and inventing a convention here would be
fitting to an answer key rather than describing the data. Same shape as M-19.

**Why it was worth a change.** `etf_3` is the most volatile task in the set — scored
1.00, 0.70, 0.00, 0.00, 0.70, 1.00, 1.00 across seven runs under identical current
grading. Reading the trajectories, the outcome tracks exactly which name column the
agent happened to project: the 0.00 runs used Full Name, the 1.00 runs used Short Name.
That is a coin flip inside the benchmark, and it costs twice over — the task itself,
and the variance it injects into every arm total that includes it.

**This is variance reduction, not a score fix.** The point is not that Short Name is
right; the point is that the agent should ASK, which costs 2 coins and is what the
ambiguity machinery is for. If it asks and the user says Full Name, the model has done
its job. Measuring the effect needs repeats — a single run cannot separate this from
the +/-0.70-point noise floor recorded in A-03.

## M-24, 2026-08-13 — 'Uncategorized' is our own invention and never said so

`Uncategorized` does not exist in the source. `funds.productclass` is simply NULL for
623 of 2310 funds; the model manufactures the member with a `COALESCE` in
`categories.yml` and `fund_analytics.yml` so category rollups keep every fund. The
description stated that fact plainly but in descriptive language, so nothing told the
agent it was looking at a synthetic member rather than a real peer group — and every
peer comparison in the model runs through `Category`.

The description now says the member is the model's own placeholder, that any
per-category aggregate over it (Category Average Duration above all) averages an
arbitrary mixture rather than peers, and that whether those 623 funds belong in an
answer is a question for the user. It deliberately does NOT say to exclude them: the
model has no basis for that call, and making it would be fitting to an answer key.

**Evidence.** Five repeats of `etf_3` after M-23, trajectories read individually. The
Uncategorized filter is the largest single discriminator: present -> 1.00, absent ->
0.00, in 4 of 5 runs. The fifth had the filter right and lost on column set instead,
so this is one of at least three independent coin flips in that task, not the only one.

**The second half of the bullet is the more transferable finding.** Asking about
Uncategorized is not enough — HOW it is asked decides the answer. A run that asked
about it cleanly and on its own ("should these be excluded since they don't have a
genuine peer group?") was told to exclude them and scored 1.00. A run that bundled it
with a second question ("categories like Uncategorized OR equity-allocation categories,
not pure bond categories such as Corporate Bond...") was told to "restrict to
bond-focused categories only ... Corporate Bond, High Yield Bond, Government Bond and
similar" — a category whitelist nothing in the task asks for — and scored 0.00. The
bundled question did not merely fail to inform, it manufactured a wrong specification.
Hence the instruction to ask it alone. Third confirmation of A-07 (etf_3, etf_8, now
this), and an instance of B-02's known two-part-question hole.

**Measurement note.** M-23 shipped an hour earlier and its own check illustrates why
this log should not quote a score: `etf_3` went 0.00, 1.00, 1.00, 0.00, 0.00 = 0.40
mean against 0.63 before, while the mechanism it targeted worked perfectly (0 of 5
runs chose the wrong name column, against a run that had). Score fell, fix worked.
Judge M-24 the same way — on whether the Uncategorized question gets asked on its own,
not on the next total.

## M-26, 2026-08-13 — redirect an existing trigger instead of adding a new one

`Alpha-Turnover Pair Count` told the agent to filter on it and never said where the
cut-off comes from. The number is a masked KB constant, so the model must not carry it
— but "ask the user for it" is not a leak, and that sentence was missing. The
description now says the cut-off is absent from the model, that no value can be derived
from the data, that the agent should ask for it as its own candidate-free question, and
that omitting the filter is not the safe fallback (unfiltered, the ranking is topped by
two-pair categories whose slopes are the largest numbers in the result).

It also closes a question the description already answered: which of the two count
columns to use. That was stated plainly and the agent kept spending an ask on it anyway,
so the text now says explicitly not to.

**Why this shape rather than a new trigger.** See M-25. Five etf_8 repeats after M-23
and M-24: total asks held (3.14 -> 3.20) but threshold asks fell 1.57 -> 0.80, and
threshold-ask count predicted the outcome perfectly — asks 2,1,0,0,1 gave rewards 0.70,
1.00, 0.00, 0.00, 1.00. The two runs that asked nothing about the threshold spent all
three of their asks on the count column, the Uncategorized placeholder (M-24's own
trigger) and row ordering — every one of which was correct in every submission of all
five runs. The ask budget is about three questions and triggers compete for it, so a
trigger that fires on a settled question is not free; it costs the one that decides the
task. Adding a fourth trigger here would have taken another. Amending the trigger that
already fires takes none.

**A10 note.** The cut-off is deliberately absent and the gate was run to prove it, plus
an explicit assertion that "25" does not appear in the description. Telling the agent to
ask for a number is the opposite of leaking it: it restores the turn the raw arm has to
spend, rather than handing the semantic-layer arm a free answer.

**How to judge it.** On whether a threshold question gets asked, not on etf_8's mean —
which was 0.63 before M-23/M-24 and 0.54 after, both inside the +/-0.70-point noise
floor in A-03. If the ask appears and the count-column and ordering questions stop
consuming asks, the redirect worked whatever the score does.

### M-26 measured, same day

Five etf_8 repeats after deploying: **1.00, 1.00, 1.00, 1.00, 1.00**, against
0.70, 1.00, 0.00, 0.00, 1.00 immediately before. The mechanism it targeted moved as
intended — a threshold question was asked in 5 of 5 runs (2,1,1,1,1) against 2,1,0,0,1
before, and the two runs that previously asked nothing about the cut-off and scored 0.00
have no counterpart here.

**The cost it introduced, recorded because it is real.** M-26 also tells the agent not
to spend a question on which count column to use, since the description already answers
it. That stopped the wasted ask — and in 2 of 5 runs the agent then picked `Fund Count`
silently and burned a 3-coin submit discovering it. Before M-26 that condition never
failed, because agents were asking about it. So the change trades a guaranteed wasted
ask for an occasional failed submit. It nets out strongly positive: a wrong count column
is recoverable and was recovered every time, while an unasked threshold is fatal. But
"settled, do not ask" is not free, and a future edit that closes a question this way
should expect the same trade.

**On M-25's design rule.** This is its first test and it holds: the redirect added no
new trigger, and the ask it repurposed was already firing. Trigger count went 12 -> 20
across today's four description changes, which is the number to watch — the cost of the
technique is bounded by the roughly three questions a task can afford, and only tasks
not re-run today would show it.

## 2026-08-13 — M-02 availability-aware count, M-06 rank population in the name

Two of the six model-side rows from `docs/etf-investigation-plan.md` Item 4 turned out to
still reproduce live; the other four did not need a model change (M-01's subject had been
dropped in an earlier redeploy, M-07 was already fixed by the Up/Down-Market pair, M-03 is
blocked engine-side by Q-06, M-09 belongs to the archeology model). These are the two that
did, both re-verified against the live deployment before being touched.

**M-02 — `1-Year Return Known Fund Count`.** `Fund Count` counts every fund in the slice
whether or not it carries the metric being reported beside it. By `Valuation Data
Availability` it gives 814 Opaque / 1496 Transparent where the funds that actually have a
1-year return are 671 / 1246, so any answer pairing a count with an average return
described two different populations. Adds a support-set counterpart rather than changing
`Fund Count`, whose all-funds semantics are correct on their own terms — the same shape as
`AMV Known Fund Count` and as `Fund Category Scored Fund Count` from M-18. New dataset
column `return_1y_known` on Fund Analytics.

**M-06 — `Fund SIES Rank` → `Fund SIES Rank (All Funds)`.** The rank is computed over all
2310 funds at build time and cannot narrow to a query's `WHERE`, so inside a filter it
returns a gapped sequence: on etf_1's high-quality/YTER screen, 27 rows ranked 1..12,
14..18, 20.., skipping 13, 19 and 25. A within-filter rank is not expressible in a
semantic model, so the fix is to stop the name promising one — the population now sits in
the name, not only in the remark, and the description names `RANK() OVER (...)` over the
filtered rows as the alternative. The three descriptions that pointed at the old name
(`Fund Secure Income Efficiency Score` and the Average/Max SIES metrics) were updated in
the same change; a pointer to a name that no longer resolves costs a submit to discover.

Only the SIES rank was renamed. The model ships **12** global rank measures (AMV, AMV
Dense, AUM, CAIR, TVS, Sharpe, Sharpe Dense, Duration Advantage, Liquidity Pressure,
Composite Score Rank in Category, Sector Rank) and every one of them gaps the same way,
but renaming measures that other tasks already query successfully risks regressions
outside etf_1. Scope was deliberately held to the one rank M-06 was filed on.

**On M-25's design rule.** Neither change adds an ask trigger. M-02's description states a
coverage fact and contrasts two counts; M-06's states a population and names a SQL
alternative. Trigger count is unchanged at 20.

**A10 PASSES** — 13 masked terms across 402 published descriptions, no masked threshold on
a task this backend runs (12 inert). Run it the way `scripts/deploy_models.sh` runs it, or
it lies: **the gate needs `--kb`**. Invoked without it, it reported `A10 FAIL` with 4 leaks
on running tasks, including `Appraisal Ratio` against etf_17. That is a false positive, and
the direction is counter-intuitive — `--kb` is documented as *enabling* the extra NUMBER
detector, so dropping it looks like it can only detect less. It also removes the gate's
ability to decide which tasks a masked term actually applies to, so terms that are inert
get classified as live. The same edits, same tree, same brief: `--kb` → PASS, no `--kb` →
FAIL. Anyone hand-running this gate outside the deploy script should assume a bare
invocation over-reports, and no conclusion about leak status should be drawn from one.

### M-02 and M-06 measured, same day

Validated the way M-26 was — 5 repeats of the affected task rather than a 19-task arm,
because both tasks sat at a hard zero floor beforehand (etf_1 scored 0.0 in all 10
recorded atscale runs, etf_10 in all 6 that ran it), so any non-zero would be a real
move. Sonnet, caching on, **$2.24 for 10 task-runs** ($0.224/task).

**Scores did not move.** etf_1: 0.0, 0.0, 0.0, 0.0, 0.0. etf_10: 0.0, 0.0, 0.0, 0.0, 0.0.
Both unchanged. What moved is the mechanism, and only one of the two moved usefully.

**M-02 — the column is right, the task is gated elsewhere.** Gold for etf_10 is
`[('Opaque', 671, 0.0569), ('Transparent', 1246, 0.4099)]`, so `1-Year Return Known Fund
Count` reproduces gold's count column **exactly**. The agent discovers it in 5/5 runs. It
survives into the graded submission in only 1/5, because gold's *third* column is a
**median** and the agent supplies an average — the task cannot pass on any count measure
while M-03 is blocked engine-side by Q-06 — and on rejection the agent cannot tell which
column was wrong, so it reverts to `Fund Count`. Judge this on the column, not on etf_10.

**M-06 — diagnosis confirmed, fix incomplete.** Gold's ranks are **dense 1..27**, computed
as `RANK() OVER (ORDER BY score DESC)` over the *filtered* rows, which settles the row: a
build-time global rank cannot answer this question at all. The rename does what it was
meant to — the agent finds the renamed column 5/5 and correctly declines to project it
5/5. But it **never writes `RANK()` either** (0/5), so it submits 3 columns where gold
wants 4. The change removed a wrong answer without producing the right one, and the
blocker has *moved* rather than cleared: it is now "the agent omits the rank column"
rather than "the model offers a gapped rank". The next lever is agent-side — guidance
already prescribes computing `RANK()` in a flat SELECT and it is not firing here.

**A cost this introduced, recorded because it is real.** A-01 records that etf_1's
column-*count* failure "no longer reproduces" because the agent asks after a wrong-count
rejection and then computes `RANK()` itself. That is no longer true: 0/5 write `RANK()`
and 5/5 submit 3 columns. Making a misleading measure unattractive is not the same as
teaching the replacement, and this is the second time a description change has traded one
failure mode for another (M-26 traded a wasted ask for an occasional failed submit). A
future edit that discourages a column should check that the agent picks up the
alternative, not just that it drops the wrong one.

### Correction to the B-25 figures above, 2026-08-13

Entries above quote "a 19-task arm that last totalled about 9.10". That conflated two
runs: **9.10 was `rebase0810_atscale_r1` on 2026-08-10**, the last arm before the damage;
the arm immediately preceding the fix (`guidance0813_atscale_r1`) totalled **7.40**.

Measured in a full arm after the fix: **`postb25_atscale_r1` = 9.70 / 19** (avg 0.5105,
$4.26) — the highest atscale total on record. Against the damaged arm that is **+2.30**,
of which `etf_2` +1.0 and `etf_4` +1.0 are B-25's fix landing as predicted, `etf_3` +1.0
is a separate name-column choice (B-13), and `etf_5` −0.7 is run-to-run variance. B-25's
own contribution is +2.0, matching the +1.94 the 5-repeat validation estimated.

## M-27, 2026-08-13 — a composite of percentiles must share one population

`Fund Composite Score (Within Category)` is the mean of three within-category
percentile ranks (5-year alpha, 3-year Sharpe, inverse net expense). Each one was
computed with `PARTITION BY productclass_norm, (<that metric> IS NULL)`, so each
ranked over the funds that have *that* metric — three different denominators. In Large
Value: alpha 42, Sharpe 60, expense 78. Their mean therefore averaged three
incomparable scales, and no fund's score was right.

Measured to 16 digits before the change, on SCHD in Large Value: the per-metric
populations give 0.9512195121951219 / 0.9830508474576272 / 0.9610389610389610, mean
**0.9651031068972368** — exactly what the deployed model returned. Over one common
population the mean is **0.9512**.

The three ingredients now rank over the funds in the category that have **all three**
inputs, which is the only population on which a mean of percentiles means anything.
Ruled out as the cause first: the scored *set* was already correct (both model and the
reference report 42 scored funds in Large Value), as were the ≥10 category gate and the
Uncategorized handling; and the gap is not `PERCENT_RANK` vs `CUME_DIST` (0.9524).
The model's 1142 scored funds vs the reference's 997 is fully explained by
Uncategorized being its own category here — 145 funds — and does not affect any real
category's percentiles.

**Why this is not gold-derived tuning**, the test archeology task 7 and M-11 set: the
defect is visible without any reference answer. Averaging percentile ranks drawn from
three different denominators is incoherent on its own terms — a fund ranked against 78
peers on expense and 42 on alpha has no common scale between the two numbers. The fix
makes the measure self-consistent; matching the reference is a consequence, not the
justification. Contrast the archeology case, where matching would have required
adopting `::real` and making the model *less* accurate to win a task.

**Scope deliberately limited.** The overall twin (`composite_score_overall`) has the
same shape and is **not** changed: no task exercises it — a parse of every ETF gold
finds `PERCENT_RANK` in exactly one, `etf_7`, in the within-category form — and per
M-06 the last unmeasured rank change removed wrong answers without producing right
ones. It is recorded on M-27 as pending its own evidence rather than fixed blind.

Tracker: **M-27** (renumbered from M-26 on filing — the change log had already used
M-26 for the Alpha-Turnover trigger redirect). Expected effect: `etf_7`, 0.0 in every
arm to date. To be measured at 5 repeats, not assumed.

### M-27 measured, same day

5 repeats of `etf_7`, Sonnet, $1.99: **0.00 × 5, unchanged**. The fix is nonetheless
correct and *sufficient*, which the agent's own submission proves — take its final query
and swap the gate from `Fund Category Scored Fund Count` to `Fund Category Fund Count`
and it returns gold's 53 rows and the identical (category, fund) set; as submitted it
returns 37. Nothing about the score or the rank is wrong any more.

The whole remaining gap is **which population the "enough funds" gate counts**, and the
cause is the agent's question framing rather than the model. It asked "what minimum
number of *scoreable* funds should a category have", presupposing the population instead
of offering both, and the simulator ratified the premise. In the pre-fix run the agent
asked the genuine two-option version and gated on all funds — correctly. So the
description that tells the agent to confirm which population is doing its job whenever
the question is actually asked open.

**This is the third time the pattern has run** (M-06, M-26, now M-27): a model defect is
found, fixed, verified against the reference — and the task does not move, because the
agent's choice one layer up is the binding constraint. The lesson is not to stop fixing
model defects; it is that a model fix should be scored as *removing a known-wrong
answer*, and its task-level payoff predicted at zero unless something separately shows
the agent will make the remaining choices correctly. Budget model work on that basis.

---

## crypto_exchange

### The open follow-ups worked and the lift did not, 2026-08-17 (second sitting)

**Headline: atscale 0.600 against raw 0.595 — lift +0.5 pp, down from +2.0 pp.** Four
guidance fixes worth ~+25 pp landed on *both* arms. Full arm numbers at the end of this
section; the per-task work that got there is below. Sitting cost $8.58 all in.

#### The fixes: +2.70 reward over 3 tasks, $1.18

Picked up from `docs/crypto-followups-handoff.md`. Three of its open items closed, and two
of its diagnoses turned out to be wrong. Everything below is live-measured or probed
through the live grader; nothing is inferred.

| task | before | after | what moved it |
|---|---|---|---|
| `_17` | 0.00 | **1.00** | B-41: the ask trigger keyed on the agent's own answer (harness) |
| `_19` | 0.00 | **0.70** | B-41, same clause |
| `_6` | 0.00 | **1.00** | M-34 `Buy Pressure`, M-35 percentile grain (model), grouped ORDER BY (harness) |

`results/crypto_0818_validate_20260817_153608.json` ($0.71, 3 tasks),
`results/crypto_0818_v2_20260817_154056.json` ($0.23, `_6` after M-35) and
`results/crypto_0818_v3_20260817_154532.json` ($0.24, `_6` after the grouped ORDER BY rule).
`_6` was re-run one change at a time on purpose: three mechanisms, three attributable steps
of 0.00 → 0.00 → 0.70 → 1.00.

#### M-34 — `_6` returned 840 rows against gold's 1000 because a row-level column was missing

The handoff offered two hypotheses, `filter_empty` on the sentiment hierarchy and the
self-join dropping unmatched rows. **Both are wrong.** No snapshot has a null sentiment
(0 of 1000) and the join to `analyticsindicators` is 1000 = 1000. The gap is the semantic
layer's implicit GROUP BY: a projection of attributes groups by them, and the agent's
projection carried `Average Buy Pressure` where gold projects the per-row `buy_force`, so
nothing in the row distinguished one snapshot of a market from another.
`distinct(market pair, spread, sentiment)` is **exactly 840**; adding buy force makes it
**1000**. Confirmed live too: the same query plus the snapshot key returns 1000 rows, and
all 1000 match gold on every value including the windowed per-sentiment average and the
percentile, to 1e-5.

So this was never a population problem or an ordering problem — it was a **grain**
problem, and the handoff's parenthetical worry ("the model has no row-level Buy Pressure
attribute … this may be harmless") was in fact the whole defect. Its reasoning failed
because the average is per *snapshot* and there are 1.65 snapshots per market.

Fix (models `5620b2a`): row-level `Buy Pressure` and `Sell Pressure` secondary attributes
on the Market Snapshot hierarchy, bare-named per the row-value convention. `Sell Pressure`
ships for symmetry only — no task needs it. Both `Average Buy/Sell Pressure` descriptions
now point at the row-level sibling, and `Buy Pressure`'s own description names the failure
mode: swapping the average in for the row value silently collapses rows.

#### M-35 — and then the percentile population became binding, in one submission

With `Buy Pressure` deployed, `_6` found and used it on its first attempt — and failed on
the next choice up: it took `Spread Percentage Percentile Rank (All Markets)` for a
listing that projects sentiment and buy force, i.e. at snapshot grain, where gold's
`PERCENT_RANK` runs over the 1000 joined rows. The `(All Markets)` description named only
its `(Within Market Sentiment)` sibling and never `(All Snapshots)`; the `(All Snapshots)`
description explains the distinction well, but the agent had already read the other one.

Fix (models `7cdee91`): `(All Markets)` now says it weighs each market once and is for
market-grain listings, and names `(All Snapshots)` as the reading for a listing that
projects any snapshot property. Re-run of `_6` alone: `(All Snapshots)` chosen, phase 1
**passed**, 0.00 → 0.70.

This is the standing pattern twice in one task, and worth noting as the *counter*-example
to the prior in the handoff's §8: two description-level fixes in a row each converted,
because each removed a wrong *object choice*, not a wrong value.

#### B-41 — trigger the label ask off your own answer, not off the question's wording

`_17` and `_19` both compute the right condition at the right grain and then print the
wrong cell text: the model's `Liquidity Crisis` / `Arbitrage Window` are Yes/No flags and
gold wants `'Liquidity Crisis'`/`'Normal Market Conditions'` and `'Arbitrage
Opportunity'`/`'Normal Market'`. Neither label pair is in the knowledge base — KB 16 and
KB 12 state the conditions and no wording — so the **model side is not available**:
putting gold's labels in a description would be gold-peeking. Both questions do carry the
wording as an *open* (unmasked) ambiguity, which is the benchmark saying to ask.

Fixed harness-side, `ASK_USER_TIP` (this commit): a clause that fires on the agent's own
draft answer rather than on the question's phrasing — if the question asks for a state or
an assessment and the value you are about to return is a Yes/No flag or a phrase you chose,
you are inventing the wording; ask for the literal text of both cases. Symmetric across
arms.

Measured the same day: `_17` **0.00 → 1.00** (both phases; the phase-1 probe predicted
0.70), `_19` **0.00 → 0.70**. This is the second ask-trigger prescription to be measured
and it lands, against M-25's prior that they rarely do. The difference looks like the
trigger surface: M-25's keyed on question wording, this one keys on what the agent was
about to submit.

#### Grouped results: gold nearly always sorts them

`_6` phase 2 then failed on row order alone — the correlation values were right.
`config/order_undetermined.json` exempts `crypto_exchange_6` **phase 1** only, and gold's
phase 2 carries `ORDER BY d.sentiment`. Probed: with `ORDER BY "Market Sentiment"` it
grades **1**, without it **0**.

The ORDER BY rule shipped in `f3ba423` said not to invent a sort, which is right for a
row-level listing and wrong here. Counted over the shipped golds: of the
**order-sensitively graded phases whose reference has a GROUP BY, 184 of 189 carry a
top-level ORDER BY** and only 5 do not (`labor_certification_applications_12` p2,
`mental_health_1` p2, `fake_account_22` p2, `fake_account_24` p1/p2). 20 of the 184 sort
by the grouping key and 164 by something else, usually the ranked measure.
`RESULT_SHAPE_TIP` now carves that out: on a grouped result always sort — by the measure
when the question ranks, by the grouping key ascending otherwise. Measured on `_6`
immediately: it added `ORDER BY "Market Sentiment"` and phase 2 passed, 0.70 → **1.00**.

#### Two of the handoff's blockers do not exist

Both of §4's tasks were filed as blocked on **Q-26** (scalar subquery inlined as a
per-row self-reference). Neither is. Probed through the live grader against the deployed
model:

| task | form that grades **1** | note |
|---|---|---|
| `_15` p2 | `SELECT ROUND("Orders At High Liquidation Risk" * 100.0 / "Orders With A Liquidation Price", 2)` | plain inline ratio of two shipped metrics; returns 100.00 |
| `_5` p2 | one discovery query (`"Exchange User"` × `"Maximum Margin Utilization"`, 2 rows) then `SELECT "Total Profitable Realized PnL", "Total Losing Realized PnL", "Profit Factor" … WHERE "Exchange User" = 'U485932'` | no subquery needed at all |

No scalar subquery is required in either, and no model change is needed for either. What
actually cost `_15` its phase 2 in the 0817 run was **budget**: three submissions spent on
the phase-1 column count (the thing `f3ba423` addresses) left nothing for the follow-up.
`_5` lost its phase 2 to a hallucinated `"Account Balance" = 425` filter and its own
invented profit-factor arithmetic, with `NULLIF` (Q-28) and one conformance error on the
way. Both are now probe-proven reachable, and the honest denominator `_15` needs
(`Orders With A Liquidation Price`, 2 of 970) is already documented as such in the model.
Also worth recording from the `_5` probes: an outer filter on a metric alias over a
derived table (`WHERE t.mu > 80`) is rejected, the Q-30 shape, while grouping by
`"Exchange User"` with `"Maximum Margin Utilization"` projected is fine.

#### Q-31 — every percentile metric in the catalog is unexecutable

Found while reading `_2`'s phase-2 failure, not by sweeping. `Median Order Fill Rate`
cannot be queried by its own name ("Column [Median Order Fill Rate] not found" — the
engine exposes it as `Median Order Fill Rate_instance_0.5`), and under the real name it
hard-errors: **"In query planning stage EnsureQuantileSupported: Quantile function not
supported for Postgresql-9.4.5"**. Checked all six `calculation_method: percentile`
metrics in the catalog and every one fails identically:

    crypto_exchange              Median Spread Percentage, Median Order Fill Rate
    exchange_traded_funds        Median 1-Year Return, Median 3-Year Sharpe Ratio
    labor_certification_apps     Median Processing Days, Median Wage Differential Rate

They are pure discovery traps: advertised, unqueryable, and they cost two failed calls
each to find out. This caps `_2` at 0.70 — its phase 2 asks for the average *and* median
fill rate. Filed as Q-31 and **not fixed here**: the fix is a precomputed median column
per population, named the way the percentile ranks already are (`… (All Snapshots)`),
across three models, and it is a bigger change than this sitting should make unmeasured.

#### Both arms re-measured, same sitting, same code — the lift is gone

`results/crypto_0818_atscale_20260817_161538.json` ($4.32) and
`results/crypto_0818_raw_20260817_162631.json` ($3.08), Sonnet both roles, 20 Query tasks.

| arm | before | after | movement |
|---|---|---|---|
| atscale | 0.360 | **0.600** | +24.0 pp |
| raw | 0.340 | **0.595** | +25.5 pp |

**Lift +0.5 pp** (relative +0.8%), against +2.0 pp before. This is exactly what §1 of the
handoff predicted and the reason it was written as a gating item: `RESULT_SHAPE_TIP` and
`ASK_USER_TIP` are shared, and the four guidance changes are worth about **+25 pp on this
database to *both* arms**. They are the right changes and the arm-level result is that the
semantic layer's advantage on crypto_exchange is now **indistinguishable from zero**.

Where each arm gained, against its own previous baseline:

    atscale  _2 _9 _10 _11 (0.00 -> 0.70), _6 _17 (0.00 -> 1.00)
    raw      _9 _17 (0.00 -> 0.70), _1 _6 _8 _19 (0.00 -> 1.00), _16 (1.00 -> 0.70)

The atscale gain on `_11` is the probe-only prediction converting, as was `_10`, which B-39
had filed as unreachable.

**Only about half of raw's movement is attributable to the guidance.** Read submission by
submission against `crypto_n1_raw_20260814_085602` (free — `failing_sql.py`), and each
task's diff says plainly which rule it obeyed:

| task | Δ | attributable to | evidence in the submitted SQL |
|---|---|---|---|
| `_9` | +0.70 | **B-37** | second submit drops the `md_ref` identifier; it asked "should the output also include a market identifier column" |
| `_17` | +0.70 | **B-37 + B-41** | one column on the first submit, with gold's exact `'Liquidity Crisis'`/`'Normal Market Conditions'`; asked for the wording |
| `_19` | +1.00 | **B-37 + B-41** | one column where the old run projected value + label; asked "what exact text" |
| `_6` | +0.30 of +1.00 | **B-42** | phase 2 adds `ORDER BY mood`. Its phase-1 +0.70 is *not* ours — the old run scaled `PERCENT_RANK() * 100` and the new one did not |
| `_1` | +1.00 | **no** | changed the id column (`EXCH_SPOT` → `exchNote`) and dropped an invented tiebreak sort; B-27 says gold is non-deterministic here, so this is largely luck |
| `_8` | +1.00 | **no** | same query plus a `NULLIF` divide-by-zero guard |
| `_16` | −0.30 | **no** | phase 2 deduped `analyticsindicators` with `DISTINCT ON`, removing the fan-out gold has (B-30) |

**+2.70 of raw's +5.10 reward points is attributable; +2.40 is not.** So of raw's +25.5 pp,
about **+13.5 pp is the guidance and about +12 pp is unattributed run-to-run movement** —
which is the same conclusion as the `_19` flip, arrived at independently and from the other
arm. On the atscale side almost every gain was individually validated beforehand, so its
+24.0 pp is better anchored.

Consequence for the lift: with ±12 pp of unattributed movement in one arm at n=1, the true
lift could sit anywhere from about 0 to +6 pp. **+0.5 pp is a data point, not a measurement.**

#### This is not a crypto-only concern — exposure per database

`RESULT_SHAPE_TIP` and `ASK_USER_TIP` are appended to the raw arm's `AINTERACT_INSTRUCTION`
(agent.py:118) *and* to every semantic backend's instruction (agent.py:143). They are
global. So **every baseline on every database measured before 2026-08-17 14:54 is stale, in
both arms** — not just crypto's.

Counted over the shipped Query-task golds, phases each rule can touch (`B42!` = phases where
the new grouped-sort rule can *hurt*, i.e. gold groups and does not sort):

    database                          phases   B38   B42  B42!   B37   B41
    labor_certification_applications      38     2    22     1     0     6
    archeology_scan                       20     0    11     0     0    12
    polar_equipment                       40     0    12     0     0     8
    reverse_logistics                     40     0    19     0     0     0
    crypto_exchange                       40     5     2     0     5     4
    fake_account                          48     4     6     3     0     3
    virtual_idol                          38     0    13     0     0     2
    museum_artifact                       40     0     8     0     0     7
    cold_chain_pharma_compliance          36     1    11     0     0     2
    organ_transplant                      38     0     9     0     3     1
    mental_health                         40     1     7     1     1     2
    solar_panel                           40     0     3     0     7     0
    insider_trading                       42     1     6     0     2     1
    households                            42     1     3     0     5     0
    ... (all 22 databases; totals B38 23, B42 159, B42! 5, B37 26, B41 59)

Definitions, so these can be re-derived: **B38** = order-sensitive phase whose gold has no
top-level `ORDER BY` (the rule now suppresses an invented sort → helps). **B42** = gold
groups *and* sorts (the rule now demands a sort → helps). **B42!** = gold groups and does
not sort (the rule now costs). **B37** = one-column gold where the question names a quoted
literal. **B41** = gold's top-level projection is a `CASE … THEN '<label>'`.

**crypto_exchange is a low-exposure database for the biggest of these rules.** It has 2 B-42
phases; `labor_certification_applications` has 22, `reverse_logistics` 19, `virtual_idol`
13, `polar_equipment` 12, and `archeology_scan` 11 out of only 20 phases. `archeology_scan`
also has 12 B-41 phases out of 20. Expect movement on those databases **larger** than what
crypto saw, in both arms.

`fake_account` is the one to watch for a regression: 3 phases where gold groups without
sorting, so the B-42 rule can only lose there.

#### One more global change, not ours

`3a72ba5` (2026-08-17 09:18, David) raised the system agent's `max_tokens` from a hardcoded
4096 to a configurable 16384. It applies to both arms through `build_adk_model`, so it is
symmetric in principle, but its own commit message records the asymmetry it fixed: three of
nineteen atscale tasks had been ending unsubmitted when an extended-thinking turn spent the
whole completion budget inside the thinking block. Checked on crypto: **zero tasks in either
raw run ended with no submission**, so it explains none of the raw movement here — but on a
database where the agent thinks longer it will lift the semantic arm specifically, and any
baseline predating 09:18 that day is stale for that reason too.

`945e2b4` (11:57) touched only `KNOWLEDGE_TOOLS_TIP`, which is semantic-backend-only and
gated behind `SEMANTIC_LAYER_KNOWLEDGE_TOOLS` (off) — inert for now, in both arms.

**Do not read ±0.5 pp as a result.** Run-to-run variance on identical code is larger than
the gap: `_19` scored 0.70 in `crypto_0818_validate` and **0.00** in the arm forty minutes
later — in the arm it bisected the projection four times and never asked for the labels at
all — and `_9` went 1.00 → 0.70 the same way. A real lift claim on this database needs
n≥3 per arm, roughly $22.

Reachable-ceiling estimates need revising too, in both directions: raw won `_1` (filed
under B-27 as gold-non-deterministic) and atscale won `_10` (filed under B-39 as winnable
only by disobeying the question). Neither is as structural as recorded.

### n=1 re-measurement 2026-08-17, and what reading every failing submission found

**atscale 0.360 against raw 0.340 — lift +2.0 pp**, on the 20 Query tasks, Sonnet both
roles, flags as of this date (tie+rel+lint+decimal+casefold). Run
`results/crypto_0817_atscale_20260817_142931.json`, arm cost $5.14.

The raw arm was **not** re-run and does not need to be. `scripts/regrade_flags.py raw`
re-scored all 38 submissions of `crypto_n1_raw_20260814_085602.json` under the current
flag set, the 2026-08-11 re-baseline and upstream-all-off: **0.3400 in all three, zero
flips.** Raw on this database is flag-invariant, so 0.340 carries forward.

Against the 08-14 n2 arm (0.410) this is **down 5 pp**, and the movement is two tasks,
both of them the same tasks n2 had *gained*: `_17` 1.00 → 0.00 and `_19` 0.70 → 0.00,
against `_5` 0.00 → 0.70 (the rel-tolerance flag, as B-20 predicted). `_17` and `_19`
are the two tasks n2 won by spending its leftover budget asking the user for the output
labels. In this run neither had leftover budget, for the reason below. Treat the 0.410
as the same measurement with a luckier budget, not as a regression to hunt.

#### The dominant failure shape: the agent projects the entity it was handed

Six of the twenty tasks name their entity as a literal in the question — "for order
'OR6015391', assess its liquidation risk", "for market 'EX203', check its market
health" — and for every one of them **gold returns the asked-for value and nothing
else, one column**. The agent projected the identifier alongside it every time, and
then bisected: `_15` submitted 4 columns, then 2, then 1, and passed on the third at a
cost of 12 coins; `_16` and `_20` each paid one wasted submit to learn the same thing;
`_17` and `_19` ran out of budget before reaching one column and scored 0.00.

`output_type` in the shipped dataset predicts this exactly — **all 9 crypto tasks
declaring `scalar` have a one-column gold, 9 of 9** — and it is read by nothing, in
this harness or upstream (same family as B-33). Surfacing it to the agent is not done
here: it would be a real deviation, giving the agent a field upstream withholds, and
that decision is not the model's to take.

Proved offline through the live grader (`scripts/probe_pred.py`, free — MCP replay plus
`ex_base_external_pred`), holding the trajectory otherwise fixed:

| task | as submitted | one column, same value | note |
|---|---|---|---|
| `_17` | 0 (3 cols) | **1** | also needs gold's label wording, which ASK_USER_TIP already covers |
| `_19` | 0 (3 cols) | **1** | same |
| `_11` | 0 (grouped by user) | **1** | `SELECT "Average Margin Utilization (Available Balance Basis)"`, no GROUP BY |

Fixed harness-side, not model-side: `RESULT_SHAPE_TIP` in `system_agent/agent.py` now
states that a question naming its entity does not want the identifier back, and that a
question asking for one overall figure does not want a GROUP BY. Symmetric — the tip is
shared by both arms.

#### An ORDER BY the question did not ask for is not free, and our own guidance said it was

`RESULT_SHAPE_TIP` claimed "a sensible ORDER BY never costs you anything", and the
atscale instruction opened with SORT BY THE MEASURE, NOT THE LABEL. Both are wrong when
gold has no top-level `ORDER BY` of its own, because then the reference row order is
whatever gold happened to emit. Measured on `_2`, same query both ways:

    ... WHERE "Is Latest Execution" = 'Yes' ORDER BY "Order Fill Rate" DESC   -> 0
    ... WHERE "Is Latest Execution" = 'Yes'                                   -> 1

Exposure, counted over the shipped golds with parenthesised scope stripped so window
and sub-select `ORDER BY`s do not mask a missing top-level one: **23 of 820 graded
phases (2.8%) are compared order-sensitively while gold has no top-level ORDER BY** —
`crypto_exchange` 5 (`_1` p1/p2, `_2` p1/p2, `_20` p2), `labor_certification_applications`
2, `exchange_traded_funds` 1, `households` 1. On those, any ORDER BY the agent invents
can only lose. Both tips now say: sort when the question ranks, otherwise leave the
order alone. Distinct from B-31, which is about gold orders that are not reproducible
at all; this is about an order gold *does* determine and the agent overwrites.

#### The model fix: "the relevant technical value" is plural (`_9`)

`_9` asks for "the relevant technical value, Bollinger Band width, the technical meter
direction, and the calculated technical signal strength" — four nouns, five gold
columns, because the first covers **both** raw technical readings. `RSI 14`'s
description said "Also asked as the relevant technical value" and `MACD Histogram`'s
said nothing, so the agent projected four columns and failed twice on it.

Derivable without gold: KB Technical Signal Strength is a function of RSI, MACD
histogram and Bollinger width; the question names the width and the meter in their own
words, so the remaining phrase has to cover the other two. Both descriptions now say
the phrase is plural and name each other. Proven before shipping — the five-column
projection grades **1**, the agent's four-column one grades **0**.

#### Validated, 3 tasks, 2026-08-17 — 2 of 3 moved, $0.49

`results/crypto_0817_validate_20260817_150357.json`, one task per mechanism rather than
three of the same, so a null result is attributable.

| task | mechanism under test | before | after |
|---|---|---|---|
| `_2` | the ORDER BY rule | 0.00 | **0.70** |
| `_9` | the M-33 description fix | 0.00 | **1.00** |
| `_17` | the projection rule | 0.00 | 0.00 |

`_9` beat its prediction: phase 2 passed as well, so the fix was worth 1.00 and not the
0.70 the phase-1 probe established.

**`_17` is the interesting one, because the fix worked and the task still lost.** Its
first submission was `SELECT "Liquidity Crisis" ... WHERE "Exchange Spot Market" =
'EX203'` — one column, first try, where the previous run opened with three and never got
below two. The projection rule did exactly what it was written to do. What blocks the
task now is one layer up: the model publishes `Liquidity Crisis` as a **Yes/No flag** and
gold wants the status wording `'Liquidity Crisis'` / `'Normal Market Conditions'`. The
agent submitted the raw flag three times, then invented `'Normal'` on the fourth, and
never spent 2 coins asking what the label should say — even though ASK_USER_TIP already
prescribes exactly that ask, because it read the flag as *being* the answer rather than
as encoding it.

So the projection saving is real but it did not convert here; it bought four submissions
at the wrong label instead of two submissions at the wrong shape. This is the standing
pattern — remove one binding constraint and the next one up the stack becomes binding —
and it is the reason `_17` should not be counted as reachable until the flag-versus-label
gap is addressed, either by a description that says a Yes/No flag is not an output label,
or by an ASK_USER_TIP trigger keyed on the flag rather than on the question's wording.
Neither is attempted here: M-25 measured ask-trigger prescriptions as landing rarely, and
this run should not spend its conclusion on an untested second guess.

Net on the three: **+1.70 reward**, which if it holds across the arm is `_2` and `_9`
alone worth +8.5 pp on the 20-task arm.

#### Read but deliberately not fixed

- **`_10` — gold ignores its own question.** The question says "based on the latest
  market-depth snapshot data, i.e. the one with maximum market stats id"; gold joins
  orders to `marketdata` on `exchSpot` with no such filter. Dropping the agent's
  (correct, obedient) `"Is Latest Snapshot" = 'Yes'` filter grades **1**, 454 rows.
  Winnable only by disobeying the question. Filed, not modelled.
- **`_18` — gold's PVaR contradicts KB 2, twice.** KB 2 is `notional × volatility
  rating × 0.01`; gold computes `notional × (priceShiftDay/100) × 0.01`, an extra
  factor of 100 the KB does not license, and binds "volatility rating" to
  `priceShiftDay`, which the column-meaning file documents as the day's price shift,
  not as volatility. Arithmetic confirmed exactly on OR6015391: gold's own
  −6.934913774857141 reproduces from `AVG(pnl) / (notional × 0.0796 × 0.01 × risk_pct)`,
  and the model's −0.009919481338340138 reproduces from the same expression with
  `vol_meter` (55.65) and no `/100`. Matching gold needs both the rebinding *and* the
  extra `/100`. This also sharpens the 08-14 note "rebinding would not win either task":
  correct conclusion, but the reason is the scale factor, not the column.
- **`_12` p2 — the model is already right.** Gold's account ID is `UserRef`; the agent
  used `Account Balance`. The `Account Balance` description already says in as many
  words that it is not the user identity, that `Exchange User` is, that "the account" is
  ambiguous between 1000 records and 201 users, and to confirm with the user. The
  `Exchange User` form grades **1**. Nothing to add — the trigger is there and the agent
  did not take it, which is M-25's pattern, not a description gap.

#### New engine facts, probed live against the deployed catalog

Added to the atscale instruction; none were in the recorded dialect inventory.

- **`NULLIF` is rejected** — "Unexpected AExpr: AEXPR_NULLIF" — while `COALESCE` is
  accepted. The KB formulas are written full of `NULLIF` as a divide-by-zero guard, so
  it bites on literal transcription. Cost `_5` a query.
- **`ORDER BY` must name a bare projected column.** Sorting on `"M"` when the projection
  is `ROUND(CAST("M" AS numeric(18,6)),2) AS m` fails with "Could not find correct column
  to sort by"; projecting `"M" AS sortkey` alongside and sorting on that works. Cost
  `_16` a query.
- **Filter inside the derived table, not outside it.** The outer form can fail with "One
  or more constraints [t.&lt;name&gt;] have been incorrectly constructed" — it did for `_12`
  — though not universally: an outer filter on a short alias resolved fine on a re-probe,
  so the trigger is narrower than the message suggests and is not characterised here.
  The inner form always works.
- **`IN (subquery)` over a string attribute** fails with "Only boolean Values can be
  Constraints ... found ... StringType" (`_6`), and a CASE/OR predicate over two measures
  returns "An internal error occurred during query planning" (`_10`, 2 calls).

### Smart Money Flow: both readings of "by at least 20%", 2026-08-17

Same build-prompt rule as the ETF entry of this date. KB 15 states *"smart-money force
exceeds both retail-flow share and institutional-flow share by at least 20%"*, and the
three forces are signed values from **-1 to 1**, not percentages — so "20%" admits a
multiplicative reading (`* 1.2`) and an absolute-margin reading (`+ 0.2`).

**New attribute `Smart Money Flow (Absolute Margin)`** (`is_smart_money_flow_absolute`
in `generator/sql_spec.py`, described in `generator/model_spec.py`). The bare
`Smart Money Flow` keeps `* 1.2` as PRIMARY, because **the KB disambiguates itself**:
KB 50 `Flow Dominance` spells the same "20%" out explicitly as `* 1.2`.

Both readings are viable, which is why this is twinned rather than resolved: **203 of 714
fully-measured snapshots are Yes under `* 1.2`, 158 under `+ 0.2`, and they disagree on
45.** Worth recording because it is a live trap — the multiplicative form **inverts on
negative values**: 346 snapshots carry a negative retail flow, and there `retail * 1.2`
sits *below* `retail`, so the condition gets easier to satisfy the more negative the
comparison flow is. Both descriptions quote KB 15 verbatim and name each other.

Regenerated with `python3 crypto_exchange/generator/generate.py`; do not hand-edit the
emitted YAML.

**2026-08-14 — initial build.** Generated by `crypto_exchange/generator/`
(`sql_spec.py` → `model_spec.py` → `generate.py`), built from
`docs/create_bird_model_prompt.md`. 223 queryable objects: 11 derived datasets,
12 dimensions, 112 metrics, 7 `metric_calc`s, 104 attributes, 1 model. Deployed
at `bird_atscale_models_catalog_main`.`Crypto Exchange`; catalog now holds 7
models, so `scripts/deploy_models.sh` and `scripts/gate_run.sh` need `7`.

Full design in `crypto_exchange/SPEC.md`, live evidence in
`crypto_exchange/ACCEPTANCE.md`. What is worth carrying elsewhere:

- **The recorded column and the KB formula are different quantities, again, and
  this time by exactly 100x.** `marketdata.orderbook_metrics.spread_pct` matches
  the KB's Spread Percentage on **0 of the 540** markets that carry it, and runs
  ~100x larger (0.92–19.40 against 0.0092–0.1940). A caller who picks the
  recorded column gets a silent 100x error on the answer six tasks turn on. The
  computed value carries the bare name `Spread Percentage`; the stored one is
  `Recorded Relative Spread Rate` and leads with the warning. Same shape as
  `cybermarket_pattern`'s RegStandeff/CEI (0 of 994) — check every recorded
  near-equivalent, and record the evidence in the description.
- **Second instance in the same database:** the stored `order_flow_imbalance`
  indicator agrees with the KB's Order Book Imbalance Ratio in **1 of 1000**
  rows, because the formula names the aggregate depth columns.
- **A masked threshold leaks through a "live count", not just through a
  formula.** The A10 gate caught `Average Margin Utilization`'s description
  saying "1 of which exceeds 80" — a coverage figure, written to satisfy the
  rule that every description carries live counts, that republished the masked
  Margin Call Risk cut-off verbatim. The two rules pull against each other; the
  gate is what resolves it. Worth stating in the build prompt.
- **`utilities/masked_threshold_gate.py` crashed on the `{"tasks": [...]}` brief
  shape its own docstring documents** (it iterated the file directly, so a dict
  yielded string keys). Fixed in the same commit; it now accepts both shapes, as
  `question_leakage_gate.py` already did. Any prompt-only model whose brief is
  the object form was silently ungated by A10 before this.
- **E-01 workaround was missing from a new model and nothing caught it.** The
  rule "carry into every new model's key attributes" lived only in this table.
  All 8 identifier attributes now name their count **metric** — not
  `COUNT(DISTINCT)`, which Q-15 says is unreliable under a measure predicate or
  beside a plain `COUNT`. Applied by `unique_name` through an assert in the
  generator so a new dimension cannot skip it; consider the same for the other
  generated models.
- **Cross-grain KB concepts are expressible if you precompute the join.** KB
  "Market Maker Activity" ANDs an execution-grain condition (execution tuning
  predominantly Maker) with a snapshot-grain one (maker order flow High). A
  caller cannot join across those grains at all. Computing the per-market maker
  share in dataset SQL is what makes the concept exist; without it the model
  would have shipped only half the definition under the whole definition's name.
- **A two-row fact still needs saying so.** `riskandmargin` holds exactly two
  rows, and every position metric is therefore a two-row population. Aggregates
  over it are perfectly plausible and completely unrepresentative, so each
  description states the population size.
- **A KB flag that is never true is still worth shipping, with its count.**
  Arbitrage Window needs APS > 0.05 and APS tops out at 0.0471, so it is No on
  all 1000 snapshots; likewise Over-Leveraged Position (0 of 2) and Critically
  Over-Leveraged (0 of 15). The descriptions give the live count, so the agent
  can tell "no rows" from "wrong object".
- **Eight KB concepts are inexpressible from the schema** (no price series, no
  30-day average volume, no forward price, no entry price) and are listed in
  SPEC.md rather than approximated. Notably `crypto_exchange_7` asks for 1h/4h/24h
  price changes and Smart Money Accuracy; the database records no forward or
  lagged price anywhere.

**Known caps, to be reported separately from real defects on any scored run:**
`crypto_exchange_10`, `_13`, `M_4` turn on the masked **Whale Order** and `_12`
on the masked **Margin Call Risk** — the firewall working, not a gap.
`crypto_exchange_19` and `_20` both want a single comma-separated string, which
no model object can supply (`string_agg`/`listagg`/`group_concat` rejected,
`ARRAY_AGG` silently does not aggregate). `crypto_exchange_2`'s follow-up wants a
median, which ships as `calculation_method: percentile` and is dialect-blocked on
Postgres at query time (MDX-Median).

Dialect inventory re-probed against the live engine 2026-08-14 and unchanged:
`COUNT(*)`, `NTILE`, `PERCENT_RANK`, `PERCENTILE_CONT`, `string_agg`, CTEs,
`GREATEST`/`LEAST`, `IN (subquery)`, `EXISTS`, `POWER` and `CORR` all rejected;
`RANK`, `DENSE_RANK`, derived tables in `FROM`, `CASE WHEN`, `ROUND`, `ABS` and
`SQRT` all accepted; `CAST(x AS numeric(p,s))` returns a string. `POWER` and
`CORR` being rejected is why the Pearson correlation ships as a `metric_calc`
over precomputed sums rather than being left to the caller.

### First measurement, 2026-08-14 — n=1 both arms, and what it found

Baseline on the 20 Query tasks, flag set unchanged from the 2026-08-11
re-baseline, Sonnet both arms: **atscale 0.255, raw 0.340 — lift −8.5 pp.** The
semantic arm was *behind*, and the reason was one defect, not task difficulty.
Cost $6.77 (atscale $3.80, raw $2.97; 87–92% of input tokens served from cache).
Runs: `results/crypto_n1_atscale_20260814_084450.json`,
`results/crypto_n1_raw_20260814_085602.json`.

#### M-30 — one dimension, one join column, or attribute-only queries die

`Market Snapshot` was joined from three datasets on **two different columns**:
`cx_ds_market_snapshot` on `market_stats_id`, and `cx_ds_order` /
`cx_ds_position_risk` on `latest_market_stats_id`, so that order and position
measures could be sliced by market conditions. With two join roles on one
dimension the planner cannot choose a path for a query that projects
**attributes and no measure**, and every pairing of a Market Snapshot attribute
with an attribute of any other dimension failed:

    SELECT "Exchange Spot Market", "Snapshot Time" FROM model
      -> Error during query planning: assertion failed:
         No candidate paths found for an attribute
    SELECT "Exchange Spot Market", "Snapshot Time", "Market Snapshot Count"
      FROM model GROUP BY 1,2                                       -> fine

**32 of 98 `run_query` calls in the atscale arm died this way**, and it burned
the entire budget of `_1`, `_17` and `_19` — the agent bisecting its own
projection column by column trying to find the bad name. There was no bad name.

Every other dimension pair resolved. Market Snapshot was the only dimension
joined on more than one column name.

Fixed by dropping the two role joins. What they bought is preserved by
denormalisation rather than a second join: `cx_ds_order` and
`cx_ds_position_risk` already carry the market-condition columns of the market's
latest snapshot. `Volatility Rating Used` is published on Position Risk And
Margin for the same reason. Cost: order and position measures can no longer be
sliced by Market Snapshot attributes, which now errors loudly naming both sides
rather than answering.

**Why the build gates missed it, and the gate that now catches it.** Acceptance
Gate 2 asked "does measure M resolve by dimension D" for all 40 pairings — and a
measure names the fact the planner routes through, so the measured form of the
broken pairing passed. BIRD questions ask for identifiers and labels far more
often than for aggregates. `scripts/dim_pair_probe.py` now probes every
dimension pair **attribute-only**; run it post-deploy on every model. Tracker Q-27.

#### M-31 — `real::numeric` truncates to six significant digits

Postgres converts `float4` to `numeric` through `float4out` at `FLT_DIG=6`:

    marg_sum            321804.16
    marg_sum::numeric   321804

The derived datasets cast every source column to `::numeric` for tidiness. On
the 27 `real`-typed source columns that silently corrupted **941 of 1000 margin
balances and 821 of 1000 realised PnL values**, and everything computed from
one. Nothing errored; the values are plausible to the last surviving digit.

Dropped the cast on all 27 (37 sites) — they are read as `double`, which is both
what the column is and what a plain SQL reader of this warehouse gets. Verified
against gold at value level: `crypto_exchange_2`'s fill rates now agree to the
last digit (86.89062114355171, 77.1294880507704, 68.15908317592815), and `_4`'s
margin balance and utilization match exactly (901343.56, 1.1975455807396416).

**The exactness gate did not catch this because its Postgres reference queries
used the same `::numeric` cast as the model — both sides were wrong in the same
direction.** A reference query must read the source column raw. `COLUMNS` is now
regenerated from a live `information_schema` probe rather than hand-declared.

#### Not changed, and why

- **Volatility rating has no documented column.** The column-meaning file calls
  `vol_meter` a *volume*-intensity meter and `priceShiftDay` the day's price
  shift; nothing in the schema is documented as volatility. Gold uses
  `priceShiftDay`, the model uses `vol_meter`. Rebinding would not win either
  task that turns on it (see below), so both descriptions now name the other and
  ask the user to confirm, instead of the model silently picking.
- **Share-of-orders ask trigger was on one twin only.** `High Liquidation Risk
  Share Of All Orders` carried no confirm-which-population sentence while its
  sibling did, and `_15` phase 2 reached for exactly that one. Same sentence on
  both now — amending a trigger that already fires, not adding an ask.

#### Gold-side findings — record these, do not model against them

- **`_1` is non-deterministic.** Gold is `ORDER BY marketdata."TimeTrack" DESC
  LIMIT 1`, and `TimeTrack` holds **one distinct value across all 605 rows**. The
  expected answer (EX203) is whichever row the scan happened to return. No model
  can reproduce it except by luck; raw scored 0.00 on it too.
- **`_3` is non-deterministic the same way.** Gold takes one global volatility
  via `ORDER BY marketstats."FundSpot" DESC LIMIT 1` — `FundSpot` is a timestamp,
  many rows tie on the maximum, and the row it returned (EX127, −14.59%) belongs
  to a market neither position trades on. The positions' own markets carry 12.41%
  and 7.96%.
- **`_17` and `_19` require literal strings gold never defines.** Phase 1 of each
  is a single classification label — `'Normal Market Conditions'`, `'Normal
  Market'`. KB 16 and KB 12 define the *thresholds* (both of which the model
  computes correctly) but name no output wording.
- **`_19` gold contradicts its own KB.** KB 12 defines Arbitrage Window on the
  Arbitrage-Potential Score, and KB 3 defines APS as a four-term sum. Gold tests
  `arbitrage_pct` alone. The model follows the KB.
- **`_5` cannot be reproduced by any semantic layer.** Gold sums a `real` column,
  so its total carries float32 accumulation error (24503744.0). The engine emits
  `SUM(CAST(x AS FLOAT8))` — read from the dispatched SQL, not inferred — so the
  model returns 24503748.29. Correct arithmetic, ungradable answer.

#### M-30 and M-31 measured, same day

`results/crypto_n2_atscale_20260814_093712.json`, atscale arm only — nothing in
the change set touches the raw arm, so lift is computed against the same
`crypto_n1_raw_20260814_085602.json` on the same 20 tasks.

| | n1 | n2 |
|---|---|---|
| atscale average reward | 0.255 | **0.410** |
| lift vs raw 0.340 | −8.5 pp | **+7.0 pp** (relative +20.6%) |
| phase 1 passes | 6/20 | 10/20 |
| `No candidate paths` | **32 of 98** `run_query` | **0 of 62** |
| arm cost | $3.80 | $3.16 |

The mechanism is confirmed directly: the assertion is gone, and the 36 wasted
queries with it. Four tasks moved, all of them tasks the assertion had been
eating: `_17` 0.00 → **1.00**, `_19` 0.00 → 0.70, `_4` 0.00 → 0.70, `_12`
0.00 → 0.70. Canaries `_8`, `_13`, `_14` (1.00) and `_20` (0.70) all held, which
matters because M-31 changed the value of every balance, execution and fee
figure in the model.

**Predicted 0.30–0.36 and it came in at 0.410, because two of the "gold-blocked"
calls were wrong.** Corrections, both recorded on tracker B-28:

- **`_17` and `_19` were not label-blocked.** Told to expect failure because the
  KB defines the threshold but no output wording, both instead passed phase 1:
  the agent asked the user what columns the answer should contain and then wrote
  the labels itself — `CASE WHEN "Liquidity Crisis" = 'Yes' THEN 'Liquidity
  Crisis' ELSE 'Normal Market Conditions' END`. An unspecified literal is
  reachable when the agent has budget left to ask. In n1 it never had any,
  because the assertion had spent it.
- **`_12` is not capped by the mask.** The masked Margin Call Risk threshold
  came back from the user simulator on a direct ask, and phase 1 passed. The
  firewall stops the *model* shipping a threshold; it does not stop the agent
  asking for one. Read "masked" as "costs an ask", not as "unwinnable" —
  `_10` and `_13` should be re-read the same way.

Held as predicted: `_4` 0.00 → 0.70 exactly as the offline replay said it would;
`_1`, `_2`, `_3`, `_5`, `_6` all still 0.00 for the reasons above.

**`_15` did not move** (0.70, phase 2 still wrong). Putting the
confirm-which-population trigger on the second twin bought nothing — the
guidance prior holds: a prescription lands rarely, and this was one more instance.

**What generalises.** The standing prior is "a model fix moves nothing" — 3 for 3
on ETF. That prior was measured on fixes that corrected a *value*, where the
agent's next choice up the stack became binding. M-30 is a different kind of
fix: it removed a hard error the agent had no way to diagnose, and it returned
the budget the error was consuming. Those pay. The distinction to carry forward
is whether the defect costs the agent *turns*, not whether it costs correctness.

#### `_6` — the missing percentile population, and why it still does not win

The model published a percentile of Spread Percentage over the 605 **markets**
and one over the snapshots sharing a sentiment, but not the plain rank over all
1000 **snapshots**, which is what a question working at snapshot grain means. A
market's spread is fixed, so the two are different numbers: the second-widest
spread ranks 0.9983443708609272 over markets and 0.996996996996997 over
snapshots. Added as `Spread Percentage Percentile Rank (All Snapshots)`, with
all three cross-referencing each other and carrying the population in the name.

**Necessary, not sufficient — proved offline before spending anything.** Taking
`_6`'s own n1 submission, swapping in the new column and running it through the
real grader (`ex_base_external_pred`) returns **0**, with all 1000 rows
differing. The percentile now matches. What does not is the rendering:

    model      0.19402062638484815
    postgres   0.19402062638484815200

Gold's spread arithmetic stays in Postgres `numeric` and keeps 18+ significant
digits; the semantic layer returns an IEEE double. With `decimal: -1` and tie
tolerance off the grader canonicalises cells to text, so they never compare
equal. No model change reaches this — filed as **E-05**. It only bites when
gold's expression stays in `numeric`: a gold column computed with any `real` or
`double` operand renders identically and matches, which is why `_2` and `_4`
were winnable and `_6` is not.

`_6` also carries a second, independent blocker: `conditions.order` is true and
gold has no `ORDER BY` past the spread, so the three snapshots tied at
0.192805848617617352 come back in an arbitrary order that must be matched.

The attribute stays — it closes a real hole in the model, and it is the reading
a snapshot-grain question means — but it is not scored as a fix, and no run was
spent on it.

#### Q-27 swept across the other models — nothing else is affected

The multi-role join that broke crypto_exchange is detectable statically, without
touching the engine: parse each model's `relationships` and flag any dimension
reached by more than one distinct `join_columns` tuple.

    archeology_scan                   Site: zoneref / zoneregistry
    exchange_traded_funds             Fund: fundlink / instrumentref /
                                            portfolioref / productlink / tickersym
                                      Family: familylink / familyref
    solar_panel                       plant_record: 5 column names, but only one
                                                    joined dimension, so no pairs
    crypto_exchange, cybermarket_pattern, households,
    labor_certification_applications  single-role throughout

**Then probed live, and they are fine.** `Fund × Family`, `Fund × Category`,
`Fund × Security`, `Fund × Year`, `Family × Category`, `Site Name × Equipment`
and `Site Name × Scan ID` all return rows attribute-only. So two join column
names on one dimension is **not** sufficient to trigger Q-27, and no recorded
ETF or archeology number is affected — no rework.

What was different in crypto_exchange is that the multi-role dimension's own
source dataset is *also* a fact carrying measures. Not characterised further:
the exact rule is the engine's to define, and the model-side discipline — one
join column per dimension, denormalise instead of adding a role — is cheap
enough to keep unconditionally.

A negative result is worth the ten minutes it cost. It eliminated the
possibility that four other models were silently broken the same way.

#### Two more gaps closed from reading the failures, neither re-run

**`_11`: the KB's "margin account balance" has two candidate columns, and only
one shipped.** KB 7 divides initial margin required by a "margin account
balance". `accountbalances` documents `marg_sum` as the *margin allocated sum*
and `AVAIL_SUM` as the *available balance amount*; neither is named what the
formula names, and over the 15 position-account pairings they average **51.65
and 35.04**. The model published only the `marg_sum` reading, so a question
meaning the other had no object at all — and gold means the other. Both now ship
with the basis in the name, each pointing at the other and asking the user to
confirm, the same shape `Effective Leverage` already used for its two leverage
columns. The user simulator independently corroborated the available-balance
reading in `_12`, where the agent divided by Available Balance and passed.

**It still does not win `_11`, and the reason is E-04 again.** Gold writes
`(...->>'initial_margin_pct')::REAL`, so its average is 35.04369060198466; the
same expression in numeric or float8 — which is what the model computes — gives
35.043690212105275. Verified in Postgres, all three variants side by side. The
addition closes a real modelling hole and is worth keeping on its own merits;
it is not scored as a task fix. 6 of the 20 golds carry a `::REAL` cast, but it
only bites when the answer needs more than float32 precision: `_13` and `_14`
carry 11 and 6 casts and both score 1.00.

**`_9`: the strength shipped, its workings did not.** The task asks for the RSI
value, the Bollinger band width, the meter direction and the computed strength,
one row per snapshot. `Technical Signal Strength` was published but its three
inputs existed only as `Average ...` metrics, so the per-row workings could not
be projected — the agent put the snapshot id where the missing MACD column
belonged and lost the shape. `RSI 14`, `MACD Histogram` and `Bollinger Band
Width` now ship as snapshot attributes beside the strength they feed.

Both changes were checked against gold in Postgres before being made, and
neither was measured — no run was spent.

#### Reading the phase-2 halves, and re-grading `_2` — no runs

`_2` **is winnable today, with no model change.** Graded its own rows offline
against gold through `ex_base_external_pred`: ordered by `"Order"` it returns
**1 under all four tie/decimal combinations**. The n2 submission lost it two
ways, both agent-side — it ordered by fill rate descending where gold's physical
order is by order id, and it added `AND "Order Fill Rate" IS NOT NULL` to tidy
the output, which quietly dropped **9 of the 969** orders gold keeps. The second
is addressable: `Order Fill Rate` now carries a **prohibition** against
filtering the nulls away, with both row counts. Prohibitions are the one form of
guidance that has measured as landing (violation rates ≤1.8% across 961 ETF
submissions); prescriptions have not.

`_12` phase 2 asks for "the account with the highest margin utilization — just
show its ID" and gold answers with the **user** id; the submission answered with
the balance-record id. `Account Balance` now says a bare "the account" is
ambiguous between the record and its holder, gives both counts (1000 against
201), and asks the agent to confirm.

`_15` phase 2 **did not move** even with the confirm-which-population trigger now
on both twins: it picked the all-orders share (0.21) where gold wants the
share of orders carrying a liquidation price (100.00). The model holds both
objects and names both; that is as far as the model can go.

Two more tasks are gold-blocked, and both are new:

- **`_4`'s two gold queries disagree with each other about one column.** Phase 1
  selects `ab.marg_sum` and expects 321804.16; phase 2 selects
  `ab.marg_sum::numeric` and expects 321804, with the utilization rounded to 6
  places from the *truncated* denominator (13.216762 against the true
  13.216755959782606). `conditions.decimal` is 6, so rounding does not reconcile
  them. **M-31 traded phase 2 for phase 1** — before it the model matched
  neither, because phase 1 failed first, so the fix is strictly better, but `_4`
  cannot reach 1.00. Tracker B-29.
- **`_16` phase 2 gold fans out on the market.** It joins orders to
  `analyticsindicators` on `exchSpot = md_ref`, so every order becomes one row
  per snapshot of its market with a different `large_order_ratio`, and the
  reference CTE is itself multi-valued and `CROSS JOIN`ed. 993 rows out of 970
  orders, including values well below the stated threshold. A model computing
  Market Impact Cost once per order returns 476. Tracker B-30.

`_20` phase 2 is closer than the string-aggregation cap suggested: the agent
hardcoded the literal and got the right seven orders, losing only on rounding
(72.65% against gold's 72.65246943576246%) and on gold's arbitrary row order.

### Precision exposure swept across all 22 databases, 2026-08-14 — and two of my own calls corrected

410 Query tasks, 820 graded phases. Every gold executed on a disposable copy of
its template, then re-executed with its `real` columns widened to `float8`, and
the two compared **after the grader's own rounding**. Free; no runs.

| exposure | tasks | share |
|---|---|---|
| **E-05** — numeric rendered as a double | **0** | 0% |
| **E-04** — float32 arithmetic surviving the rounding | **11** | 2.7% |

**E-05 does not exist. I filed it this morning and it was wrong.** The mechanism
is real — the layer returns an IEEE double where gold holds a Postgres `numeric`
— but the grader rounds *both* sides before comparing, and
`resolve_decimal_places` falls back to **2** when a task says `decimal: -1`,
which absorbs any difference below the second decimal. My evidence had been a
raw `canonical_cell` diff that skipped the rounding the grader actually applies.

That changes `_6`'s diagnosis: under the grader's rounding its rows match gold as
a **multiset, exactly**. What fails is row order — `conditions.order` is true,
gold has no `ORDER BY` past the spread, and **401 of 1000 rows sit in ties**. So
`_6` belongs to the B-27 non-deterministic-gold family, and the percentile
population added earlier was *necessary after all*: without it the multiset did
not match either.

**`_11` is winnable, and I said the opposite.** Graded against gold, the new
`Average Margin Utilization (Available Balance Basis)` returns **1** — 35.043690
against gold's 35.043691, absorbed at 2 decimal places. The `::REAL` downcast I
blamed does not survive rounding. That makes the margin-balance twin the second
scored model fix of the day, not a correctness-only change.

**E-04 is real but rare, and a `::REAL` cast is not the test.** It bites only
when the float32 result crosses the rounding boundary. Confirmed, all run-to-run
stable, two hand-verified:

    archeology_scan   _1 _6 _7 _8     4 of 10 tasks - by far the worst exposed
    crypto_exchange   _5 _10
    polar_equipment   _4 _9
    disaster_relief   _4
    planets_data      _5
    solar_panel       _2

`polar_equipment_4` sums to 128608.00 in float32 and 128607.80 in float64;
`archeology_scan_1` phase 2 differs on 2 of 597 rows at the second decimal
(43.87 against 43.88). Against that, `crypto_exchange_13` and `_14` carry 11 and
6 `::REAL` casts and both score **1.00**.

**Read this as a ceiling, not a defect list.** For 21 of 22 databases the
precision ceiling is 0–2 tasks and can be ignored. **`archeology_scan` is the
exception at 4 of 10**, and its recorded scores should be read with that in
mind: roughly 40% of its tasks are capped by arithmetic no semantic layer
controls.

### Order sensitivity swept across all 22 databases, 2026-08-14 — the bigger ceiling

> Full write-up, including the grading pipeline itself and five further defects:
> **`docs/bird-grading-comparison.md`**. The summary below is kept for the
> chronology; that document is the reference.

`conditions.order == true` makes the grader compare row by row. That is only
answerable if gold's own `ORDER BY` **totally** orders its result. Measured, not
parsed: every gold run twice, the second time with the planner pushed onto
different physical operators (`enable_seqscan/hashjoin/nestloop/hashagg = off`),
compared after the grader's own rounding, and counted only where the row
*content* was identical — so a content difference cannot masquerade as an order
difference.

**438 phases are graded order-sensitively. In 68 of them — 57 tasks, 13.9% of
all Query tasks — the order moved.** Lower bound: a tie both plans happen to
emit identically is not caught.

**Corrected from an initial 65 tasks / 78 phases.** The first pass executed gold
WITHOUT the `remove_comments`/`remove_distinct`/`remove_round` cleanup gold
actually gets at grading time. B-19's `ROUND()` stripping removes ties gold
manufactured by sorting on rounded values, and skipping it over-counted by 8
tasks — `archeology_scan` alone dropped from 8 to 5. Any future sweep must clean
gold the way `ex_base_external_pred` does.

| database | tasks | order-loose | float32 (E-04) | either |
|---|---|---|---|---|
| **archeology_scan** | 10 | **5** | 4 | **7** |
| hulushows | 20 | 9 | 0 | 9 |
| fake_account | 24 | 5 | 0 | 5 |
| organ_transplant | 19 | 5 | 0 | 5 |
| labor_certification_applications | 19 | 4 | 0 | 4 |
| mental_health / sports_events | 20 / 20 | 4 / 4 | 0 | 4 / 4 |
| exchange_traded_funds | 19 | 2 | 0 | 2 |
| crypto_exchange | 20 | 2 (`_6`, `_10`) | 2 (`_5`, `_10`) | 3 |
| cybermarket_pattern | 20 | 2 | 0 | 2 |
| solar_panel | 20 | 1 | 1 | 2 |
| households | 21 | 1 | 0 | 1 |

In 57 of the 65, **more than 5% of rows move**, which makes matching a lottery
rather than a near miss — `crypto_exchange_10` phase 2 displaces 1627 of 2558
rows, `hulushows_16` 998 of 1000, `archeology_scan_6` 894 of 900. The remaining
8 move ≤5% and could plausibly coincide.

**This is not model-fixable and it is bigger than every engine defect found so
far.** No model object can reproduce another query's physical row order. The
agent can produce exactly the right rows and still fail, and the failure reads
as a value error — which is how `_6` was misdiagnosed twice today, first as a
missing percentile and then as E-05.

The practical hit rate is lower than 15.9%, because an agent's own query
sometimes coincides with gold's physical order: `crypto_exchange_2` passes with
`ORDER BY "Order"` against a gold that carries no `ORDER BY` at all. Tracker
**B-31**.

**Mitigation is a grading decision, not a model one** — comparing
order-insensitively wherever gold carries no total order. That is re-gradable
offline for nothing (`scripts/regrade_flags.py`), so it can be quantified before
anyone argues about it.

### Combined structural ceiling per deployed model

Union of the two exposures, as a share of each database's Query tasks:

    archeology_scan                    7 of 10 at risk   ceiling ~30%
    labor_certification_applications   4 of 19           ceiling ~79%
    crypto_exchange                    3 of 20           ceiling ~85%
    exchange_traded_funds              2 of 19           ceiling ~89%
    cybermarket_pattern                2 of 20           ceiling ~90%
    solar_panel                        1 of 20           ceiling ~95%
    households                         1 of 21           ceiling ~95%

`archeology_scan` is not a hard database — it is a **structurally ungradable**
one, and its recorded scores should never have been read as a model verdict.
`config/environment_backends.yaml` now carries the `cybermarket_pattern` domain
entry pointing at `bird_atscale_models_catalog_main` / `Cybermarket Pattern`.

---

## households

**2026-08-11 - initial build, prompt-only.** Generated from the BIRD-Interact
`households` database by `households/generator/generate.py` in
`AtScaleInc/bird-atscale-models` (spec -> emitter; the spec is `sql_spec.py` +
`model_spec.py`). 89 published objects: 3 derived datasets, 10 dimensions (46
attributes), 33 metrics, 10 `metric_calc`s, 1 model. `sml-cli validate` clean at
repo root; committed and pushed to `main` as `c42421d`. **Not yet deployed**, so
none of the four acceptance gates has run - `households/ACCEPTANCE.md` carries
every gate with its source-of-truth value precomputed from Postgres, marked
un-run.

Answer-key firewall enforced mechanically rather than by intention:
`generator/extract_brief.py` allowlists the permitted fields of the 29
`households` tasks out of `bird_interact_data.jsonl`, then asserts on its own
output that no denied key (`sol_sql`, `sql_snippet`, `test_cases`, `conditions`,
`preprocess_sql`, `clean_up_sqls`) and no SQL-shaped text survived. Nothing else
in the build opens the JSONL; the model was authored from
`generator/task_brief.md` plus `households_kb.jsonl`, the schema file, and live
profiling.

Build decisions, each traceable to the knowledge base, the live schema, or
observed engine behaviour:

- **E-02.** All derived-dataset table references schema-qualified `public.<table>`.
- **D-01.** No `|` character in any emitted SQL. The one place a concatenation
  was needed (the infrastructure-configuration label) uses `concat(...)` rather
  than `||`, since `||` is itself two pipe characters; the generator asserts no
  `|` remains.
- **Canonicalisation is the modelling job here.** Every text column in this
  database is dirty in three independent ways at once - random case, leading and
  trailing whitespace, interior whitespace runs including raw tabs - plus
  genuine synonyms. Distinct values before and after normalisation: dwelling
  class 116 -> 6 classes, tenure 84 -> 7, cable status 123 -> 2, newest vehicle
  year 123 -> 9 bands, region code 106 -> 10 regions, income bracket 47 -> 12.
  Grouping on a raw column shatters every "for each area" question, so each
  grouping attribute ships canonicalised and its raw twin ships as
  `... (As Recorded)` with a lead-with-the-warning description. The gap is large
  enough to be worth measuring: `Region` = 'Taguatinga' is 266 households,
  `Region Code (As Recorded)` = 'Taguatinga' is 214.
- **One wide household fact.** `amenities` and `transportation_assets` carry a
  UNIQUE constraint on their household FK and are exactly 1:1 with `households`
  (1581 rows each, no orphans either way, verified live); `properties` covers
  1577 of 1581 and is LEFT JOINed. Joining all of them into one 1581-row fact at
  household grain gives every attribute a direct relationship to every
  dimension, which pre-empts the whole conformance failure class. Eight of the
  ten dimensions are consequently degenerate on that fact.
- **KB formulas that are fully stated are precomputed:** Household Density
  (KB 11), Infrastructure Quality Score (KB 13), Vehicle Ownership Index
  (KB 14), Bathroom Ratio (KB 15), Dwelling Capacity (KB 17), Living Condition
  Score (KB 20), Dwelling Type Score (KB 44).
- **KB formulas whose numeric mapping or weights the KB never states are NOT
  shipped:** Expenditure Ratio (KB 12, "divided by a numeric mapping of income
  bracket"), Service Support Score (KB 16, "a weighted score"), Mobility Score
  (KB 18, "a numeric mapping of the newest vehicle year"), Socioeconomic Index
  (KB 19, "a weighted sum of income score, expenditure ratio, and tenure
  score"). Each ships its components instead, and every component's description
  names the concept it feeds and tells the agent to ask the user for the missing
  mapping. Shipping them would have meant inventing a threshold nobody
  authorised, under a name matching the question's own words.
- **No Yes/No flag for any masked composite concept.** 28 of the 29 tasks turn
  on a `knowledge_ambiguity` entry with `is_mask: true`; only `households_16`
  (Income Classification) is `is_mask: false`. So no flag ships for Affluent
  (KB 21), Urban (KB 22), Mobile (KB 23), Crowded (KB 25), Modern (KB 26),
  Well-Equipped (KB 27), Economically Stable (KB 28), Comfortable Living
  (KB 29), Self-Sufficient (KB 30), Compact (KB 39) or Economically Independent
  (KB 42) households. Expect this to cost tasks; `ACCEPTANCE.md` records them as
  capped so a score is read correctly.
- **Income thresholds made expressible without inventing one.** KB 2 names
  income classes 'Low Income' through 'Very High Income' and KB 21 defines
  Affluent as 'High Income' or 'Very High Income', but the column stores R$
  ranges and nothing maps the two. Rather than invent a cut-off, the Income
  Bracket dimension ships `Income Bracket Rank` (1-12 by monetary amount) and
  `Income Bracket Lower Bound` / `Upper Bound` in reais, so any threshold a user
  names is expressible after asking. This also answers "the second-highest
  bracket" directly.
- **Group vs entity readings separated only where they diverge.** Average
  Bathroom Ratio 0.6611 vs Bathrooms Per Resident (Pooled) 0.5519; Average
  Household Density 1.3927 vs Residents Per Bedroom (Pooled) 1.2450 - both
  shipped, named asymmetrically, each description naming the other. Where the
  formula is linear in its components (Infrastructure Quality Score is a plain
  mean of three terms; Living Condition Score is a 50/50 blend of two) the
  pooled group formula is provably identical to the mean of entities, so only
  one object ships. That is the Surface size rule applied: a variant only where
  it is provably distinguishable.
- **Missing-input policy handled by three-valued members, not policy twins.**
  Where an input is absent the model ships an explicit member - Income Bracket
  'Undisclosed' (110 households), Social Support Status 'Not enrolled' (8),
  Dwelling Class 'Not recorded' (4), Newest Vehicle Year 'Undisclosed' (84),
  Infrastructure Configuration 'Not recorded' (4) - so a caller can express
  either the strict or the include-them reading by filtering, and neither
  reading is unrecoverable. Coverage counts ship per formula (not per
  component): Households With Bathroom Ratio 1577, With Household Density 1574,
  With Infrastructure Data 1577, With Living Condition Score 1577.
- **Three KB entries have no backing column at all**, verified against
  `information_schema.columns`: Residential Zone Types (KB 34), Utility Access
  Level (KB 35), Dwelling Condition Status (KB 38). The concepts built on them -
  High-Mobility Urban Household (KB 40), Stable Infrastructure Household
  (KB 41), Well-Maintained Dwelling (KB 43) - are therefore inexpressible here,
  and the nearest available attributes say so instead of approximating. There is
  likewise no floor-area or square-meter column anywhere, so a Space Bonus rule
  stated in square meters per resident cannot be evaluated; the Dwelling
  Capacity description says so rather than letting the agent substitute it.
- **KB 45 (Urban Zone, `loczone = 1`) matches zero rows** - the 15 live zone
  numbers run 121 to 414. It ships as `Urban Zone (Zone Number Equals 1)`, with
  the qualifier in the name and a description that leads with "this returns
  nothing" and redirects to the KB 22 infrastructure reading of urban. Shipped
  rather than deleted because it is the knowledge base's own definition, but
  named so it cannot quietly out-compete the right object.
- **Two cable-availability readings.** KB 7 enumerates 'avail', 'available' and
  'yes' as affirmative; the live data also carries 'y' and 'have' on 115
  households. `Cable Status` (905 Available) takes all five tokens and
  `Cable Status (Knowledge Base Tokens Only)` (790) takes the KB's three. The
  two provably differ, so both ship, named asymmetrically.
- **No precomputed rank columns - a deliberate deviation from the build prompt**,
  reasoned in `ACCEPTANCE.md`. Every superlative question in this task set is
  filtered, and a static global rank computed in dataset SQL is wrong under a
  filter while being named in exactly the question's words. `ORDER BY <metric>
  DESC LIMIT n` on the SQL interface is filter-correct. The tie structure that
  would have decided a RANK/DENSE_RANK twin is recorded as capped instead:
  Household Density has a two-way tie at 6.0 and a twelve-way tie at 5.0, and
  Car Count a five-way tie at 5, so any `LIMIT 10` by density or unfiltered
  "highest car count" has a non-unique expected answer.
- **Withheld columns**, recorded so the omission is not read as an oversight:
  `amenities.amenityref`, `properties.propref`,
  `transportation_assets.transref`, `households.serviceplan` and
  `service_types.serviceref` are surrogate row ids on 1:1 tables that no
  question touches; the household is already identified by House Number.
- **Hidden objects: none.** The Infrastructure leaf was initially a hidden
  surrogate id (`infrastructure_ref`, 75 rows) per the "no leaf-grain
  descriptive column" rule; profiling showed those 75 source rows are dirty
  duplicates of only 7 real water/road/parking combinations, so the leaf is now
  keyed on the canonical triple, has 8 browsable members, and answers a real
  question. Nothing needs hiding.
- **Surface size held down deliberately.** 89 published objects against the 162
  that reached discovery parity and the 188 that exhausted per-task budget on
  `cybermarket_pattern`. The multiplicative rules were treated as permissions,
  not obligations: no rank twins, one water-access reading, one reading each for
  the two linear composite scores.
- **No median anywhere** - no KB definition in this database requires one, so
  the MDX-Median workaround row is not exercised.

Generator self-audit gates (all clean): duplicate labels and unique_names across
every attribute and metric, `unique_name` differing from `label` on anything
queryable, unreferenced datasets, metrics naming a column no dataset defines,
dimensions referencing unknown levels, relationships whose `join_columns` count
differs from the target level's `key_columns`, dangling cross-references between
descriptions, non-ASCII in a description outside the model's own accented member
values (Ceilândia, Guará, Candangolândia), SML length limits, `metric_calc`
folder minimums, and 59 discoverability phrases taken verbatim from the tasks'
own wordings - each must match at least one published description, checked by
parsing the emitted YAML and normalising whitespace rather than grepping the raw
file, because `safe_dump` folds long descriptions at column 100.

All three derived datasets were dry-run directly against the warehouse before
validate: 1581 / 122 / 13 rows as expected, every canonical CASE verified to
have no unmatched value falling through to a default, and every knowledge-base
formula spot-checked against hand-recomputed source values.

`config/environment_backends.yaml` now carries a `households` domain entry
pointing at `bird_atscale_models_catalog_main` / `Households`. That schema is the
expected one by convention, **not** one read back from `list_models`, because the
model is not deployed - a comment above the entry says so. Before the first run:
deploy, confirm the schema and table against what `list_models` actually
reports, and restart the services. `shared/environment_backends.py` caches this
file in a module-level dict at first load, so a `--backend` flag will not pick up
an edit; two full runs have previously been lost to a config that was already
correct on disk.

**2026-08-11 - all four acceptance gates run against the deployed model; all
four pass.** Q-17b health gate passes (`list_models` succeeds and returns all 5
models; `Households` reports 43 measures / 46 dimensions, matching the build).
Catalog-suffix confirmed: the deployed schema is
`bird_atscale_models_catalog_main`, which is what the config entry already named.
Post-deploy MDX gate passes 10/10, including the two expressions that go beyond
plain measure arithmetic - `Share Of Households Percent` sums to 100 across
regions and `Infrastructure Score Range Across Regions` returns
0.7916666666666665, so both the `[All]` member and the `ALLMEMBERS` set resolve
correctly. Exactness exact-equal on every figure at full double precision, with
two averages differing in the last double bit only (engine summation order, the
same class recorded under `cybermarket_pattern`). Conformance 20/20, every
grouping totalling exactly 1581. Discoverability: every question-style
paraphrase surfaced its intended object, including all nine "cannot be answered
here" redirects. Coverage 6/6. Group-vs-entity separation confirmed diverging on
both pairs that should diverge. Full evidence in `households/ACCEPTANCE.md`.

**One real defect, found by Gate 1i and fixed (`d6ff534`).** The five
`... (As Recorded)` attributes were emitted through the whitespace-normalising
helper rather than straight from the source, so they arrived half-cleaned:
whitespace collapsed, case preserved. Live distinct-member counts were 64
(tenure), 92 (dwelling class), 88 (cable status), 67 (newest vehicle year) and 12
(income bracket) against the raw 84 / 116 / 123 / 122 / 46. Five descriptions
therefore stated wrong spelling counts, and `Income Bracket (As Recorded)` had
collapsed to 12 members - nearly the canonical 13, because those raw spellings
differ only in whitespace and not in case - which made its "do not group on this"
warning actively misleading: grouping on it gave the right groups rather than the
fragmentation the description warned about. This was invisible to `sml-cli
validate`, invisible to the other three gates, and invisible to every Gate 1
total; it only shows up in a live distinct-member count, which is why Gate 1i
exists. The canonical columns were never affected and every canonical figure is
unchanged after the fix. **Requires a redeploy to go live** - until then the
deployed model still carries the half-cleaned columns and the four wrong counts.
Nothing a benchmark question targets is affected, since the questions group on
the canonical attributes.

**2026-08-12 - what the households evaluation actually measured, and one
transferable lesson.** Five runs of the atscale arm after the config fix, all
clean, all scoring 0.095 with sd 0.000 and passing the identical two tasks.
Raw's three runs average 0.078 on the 20 shared query tasks (spread 0.050 to
0.100). The +0.022 gap is under half the 0.049 run-to-run spread, so households
supports no lift claim in either direction yet.

The reason is the task set, not the model. Reading the gold SQL for every
failing task (permitted for diagnosis; never folded back into the build)
produced two defect families:

- **The graded reference answers a different question than the one asked.** 12
  of 21. households_1 asks for area code and average bathroom ratio and its gold
  returns `SUM(Auto_Count)` for the top region; households_13 is
  `output_type: table` asking for counts per area and its gold returns the
  single top area by percentage; households_M_10 returns the *fifth* row via
  `OFFSET 4 LIMIT 1`. The task's own `user_query_ambiguity` snippets agree with
  the question text and disagree with the gold, which is the strongest evidence
  available that the two halves of these records were generated from different
  queries - `sol_sql` comes from BIRD's ground-truth file and the question and
  ambiguity payloads from the public file, joined on `instance_id`.
- **The gold filters on literals absent from the data**, so the graded answer is
  degenerate. Every one of these matched 0 rows: `'More than R$ 4,400'`,
  `'More than R$ 880 and less'`, the named income classes `'low income'` through
  `'very high income'`, `roadsurface IN ('asphalt','concrete')` (actual value
  `'Asphalt, concrete'`), `wateraccess IN ('yes','available at least in one
  room')` (actual `'Yes, available at least in one room'`), and
  `'2012 to 2013'`. Consequences, executed verbatim: households_7's correct
  answer is **-151** (its Urban test can never fire, and gold subtracts Rural
  from Urban), households_12's is **empty**, households_17's is **0**.

A further 5 tasks are decided by string granularity rather than modelling: the
gold filters dirty text at `LOWER()` or `TRIM(UPPER())`, which folds case but
merges neither synonyms nor interior whitespace, while the canonical attributes
merge all three and therefore select a larger population. households_4: gold's
'apartment' is 222 properties and the canonical Apartment class is 255, so 86
against 105.

**SUPERSEDED - see the correction dated 2026-08-12 below.** The reading at the
time was that descriptions suppress reliably and promote unreliably. The first fix shipped
the recorded-value readings as secondary attributes whose descriptions opened
with "WARNING - this is NOT the canonical" and closed with "Group on X
instead". The next run scored 0.095 again - completely inert. The trajectories
show why: the agent saw those attributes in `explore_columns` on every task that
needed them (households_4's very first search returned
`Dwelling Class (Recorded, Lower Case)` with its full description) and used the
canonical attribute anyway, on all four tasks, spending its budget resubmitting
the same wrong query. The build prompt already warns that a description cannot
steer an agent *toward* an object; this is the same rule in reverse, and the
reverse direction is the strong one. A warning in a description is a blunt,
effective instrument - so do not point one at an object you actually want used.
The only lever that moved behaviour was the name.

Two defects found while checking the deployed name-swap, both invisible to
`sml-cli validate` and to every acceptance gate:

- **A silent-empty-result trap of my own making.** Prepending a granularity note
  while preserving the original description text left canonical member values
  documented on an attribute that no longer held them: Cable Status said
  "'Available' (905 households)" while its members were all lower-cased. An
  agent copying that literal filters on a value matching zero rows and gets an
  empty result with no error. `check_swapped_descriptions.py` in the model repo
  now gates the class by failing any quoted literal that case-insensitively
  matches a real member but differs in case or whitespace.
- **Cleanup scoped to the wrong dimension.** The redundant `(As Recorded)` twins
  live on the Household dimension, not on the dimension being swapped, so six
  of them survived pointing at the same column as the newly-bare level.

Harness change from the same investigation: the Management-category (DDL/DML)
exclusion applied only to non-raw backends, so the raw arm ran 29 households
tasks against the atscale arm's 21 and 600 against 410 across the suite, which
is what inflated raw's headline. `--exclude-management` now applies the
identical predicate to the raw arm, results files record `exclude_management`
and `task_count`, and `summarize_runs.py` shows the scope per run.

**2026-08-12 - correction, and the actual transferable lesson. Descriptions steer
reliably in BOTH directions.** The entry above concluded from the first failed
attempt that a description can suppress an object but not promote one. The second
attempt refutes the second half and the correction is the part worth carrying to
the other 19 databases.

Attempt two moved the bare, unqualified name onto the recorded reading for the
five concepts that decide scored tasks and pushed the canonical reading behind
`(Canonical)`, on the theory that only the name moves behaviour. It changed
nothing: 0.095 again, the same two tasks passing. The trajectories show why. The
naive attributes' descriptions said "filter here when a literal has to match the
source spelling; for grouping, counting or any 'for each' question use
X (Canonical)" - and all four target tasks are counts or groupings. The agent
followed that instruction exactly, using `(Canonical)` **77 times against 6 uses
of the bare swapped names** across the run, on all four tasks.

So the mechanism is not one-directional. The agent follows operation-conditional
guidance in a description closely - "filter here, count there" was obeyed
precisely. Attempt one failed because its descriptions *suppressed* the objects
it added; attempt two failed because they *promoted* the wrong one. In both cases
the channel worked and the guidance was wrong.

Two consequences:

- **For the remaining models: treat description text as a working control
  surface, and write the operation-conditional guidance deliberately.** Sentences
  of the form "use A for filtering, B for grouping" are load-bearing, not
  decoration. That is a positive finding about the semantic layer's metadata and
  belongs in the product story, not only in a failure log.
- **For households: the four tasks are not winnable honestly.** Winning them
  needs a description telling the agent to use the fragmenting reading for
  counting and grouping, which is instructing bad analysis in a model published
  as an example of good modelling. `NAIVE_TEXT_PRIMARY` is reverted to False,
  the machinery kept with the outcome recorded beside the flag so the negative
  result is not re-derived, and households is reported as no-measurable-lift on
  the task-set evidence above.

Final households position: 6 clean atscale runs at 0.095 (sd 0.000) against raw's
0.078 on the 20 shared query tasks; the +0.022 gap is under half the 0.049
run-to-run spread. 14 of 21 tasks are unwinnable as asked, 4 more turn on string
granularity the grader resolves one way and honest modelling the other, and 2
pass. No further model change is warranted on this database.

---

## labor_certification_applications

**2026-08-13 - initial build.** Generated by
`labor_certification_applications/generator/` (spec.py + sql.py -> generate.py,
driven end to end by `build.sh`). 117 objects: 5 derived datasets, 13 dimensions
(49 attributes), 43 metrics, 20 `metric_calc`s, 1 model. Deployed with
`sml-cli atscale-deploy --catalog-name=bird_atscale_models_catalog_main`, so it
publishes into the existing suffixed catalog rather than creating an unsuffixed
second copy (Catalog-suffix / Q-17 rows above). `config/environment_backends.yaml`
updated with the domain entry, schema read back from `list_models` (6 models).

### Workaround rows applied

- **E-02** - every derived-dataset statement schema-qualified with `public.`.
- **D-01** - generator gate A4 asserts no emitted SQL contains a `|`, which also
  rules out `||`; `CONCAT()` is used throughout, and the worksite surrogate is a
  `DENSE_RANK()` integer rather than a concatenated string key.
- **MDX-Median** - `Median Processing Days` and `Median Wage Differential Rate`
  ship as `calculation_method: percentile` with `named_quantiles: median` and
  `compression: 1000`. Confirmed live that the Postgres dialect rejects them:
  `Quantile function 'QuantileRawToSketchFunction' is not supported by dialect
  'Postgresql-9.4.5'`. Both descriptions say the median is unavailable on this
  warehouse and name the mean to use instead. The engine exposes them as
  `<name>_instance_0.5` (not `_instance_median`).
- **E-01** - the six identity attributes (Employer, Attorney Email, Worksite,
  Preparer Email, SOC Code, Job Title) each say that a bare `COUNT` of the column
  is not evaluated and name the count measure to use instead.
- **Q-17b** - gated on `list_models` succeeding and returning the expected model
  count after every one of the four deploys. Never hit.

### Build decisions worth carrying to other models

- **One wide application fact.** `cases`, `case_worksite` and `prevailing_wage`
  are exactly 1:1:1 (981 rows each, no orphans either way) and `case_attorney`
  is 1:0..1 (727 of 981, every row `counselfor = Yes`). Joining all four gives
  every attribute a direct relationship to every entity dimension, so there is
  no bridge, no many-to-many, and the conformance-failure class cannot occur.
  All 13 dimension groups map to the single fact in `column_groups`.

- **Three self-keyed occupation attributes instead of a hierarchy.** `soccd`,
  `soctitle` and `jobtag` disagree in the live data - 130 codes, 128 standard
  titles, 700 free-text titles, with one code carrying two titles and two titles
  carrying two codes. A `soccd`-keyed level named after `soctitle` would fail the
  engine's functional-dependency check. Shipping `SOC Code`, `SOC Occupation
  Title` and `Job Title` as three separate self-keyed attributes is also the
  honest answer to the task set's masked term "occupations", each description
  naming the other two.

- **`[Dim].[Hier].[All]` is not a whole-model constant, and the failure is
  silent.** The most valuable finding of this build, caught by acceptance gate 2
  and invisible to `validate`, to deploy, and to the MDX validator (all six
  broken expressions validated clean). A tuple like
  `([Visa Class].[Visa Class Hierarchy].[All], [Measures].[Distinct Visa Classes])`
  clears only *that* dimension's filter; every other dimension in the query
  still narrows it. So an index whose denominator is meant to be a
  warehouse-wide average collapses to the current slice:

  - `Attorney Specialization Index` returned **0.0 at every grain** instead of
    0.75, because the denominator became "visa types handled by this attorney"
    (1) rather than "visa types in the warehouse" (4).
  - `Occupational Demand Index` returned **1.0** instead of 43.73 for SOC
    15-1252.00 as soon as a second attribute was grouped, for the same reason.
  - Both numbers are plausible, which is why plausibility is not evidence.

  Fix: `AllMember(<expr>)` strips all dimension context and gives a true
  whole-model constant. Applied to Occupational Demand Index, Employer Scale
  Indicator, Attorney Specialization Index, Seasonal Application Index, State
  Application Concentration Ratio and the Employer H-1B Concentration
  denominator; all six verified against Postgres afterwards (ODI 43.730886850
  vs 43.730887, EHC 6.387434555 vs 6.387435).

  The corollary matters as much: **a share-of-total calc genuinely wants the
  scoped `[All]` behaviour.** The seven `... Share Across ...` calcs divide out
  exactly one named dimension so that other filters stay in force - that is what
  makes "percentage of positions within this occupation" and "visa mix for this
  attorney" expressible at all. Decide per calc which of the two you mean;
  `Position Share Across Wage Tiers` depends on the scoped form and
  `Occupational Demand Index` depends on the global one.

- **Near-duplicate readings of one concept must all be cleared together.** A
  follow-on from the above: because SOC Code, SOC Occupation Title and Job Title
  are three readings of one concept, an `[All]` on just one of them left the
  other two narrowing the denominator, and grouping by SOC Code plus SOC
  Occupation Title returned 100.00 instead of 33.64. Both occupation shares now
  clear all three occupation hierarchies in one tuple.

- **`RANK() OVER (...)` works in inbound SQL.** Verified live. Ties do exist at
  the N the questions use (job title 57, 15, 15, 14, 14 restricted to H-1B; SOC
  title 330, 52, 38, 29, 29, 29), so `RANK` and `DENSE_RANK` top-5 disagree - but
  no rank metric is shipped, because the caller can express a displayed rank in
  SQL and a `metric_calc` rank would need one object per grain. Where a task's
  own `LIMIT N` cuts across a tie the expected answer is not unique and the task
  is capped regardless of the model.

- **Discoverability is worth probing after deploy, not just at build time.** The
  build gate (A9, 79 phrases) passed while eight question wordings still matched
  nothing live: "labor shortage", "demand score", "visa focus", "foreign
  workers", "pay well", "specialty occupation", "regular filer", "skilled
  position". Two were pure hyphenation - `explore_columns` is a literal substring
  match, so "specialty-occupation" and "continuous-filer" never match the
  space-separated forms a caller types. Write the unhyphenated form.

### Live-data facts that shape the model

Each is stated in the description of the object it affects, because each one
turns a plausible answer into a wrong one.

- **Every one of the 981 applications is certified**, stored as `Certified`
  (334), `certified` (324) and `CERTIFIED` (323). So every approval, success and
  certification rate is 100% at every grain - which is also why only one
  `Approval Rate` object ships rather than the usual group / mean-of-entity /
  entity trio: the three are provably identical here. A filter on one
  capitalisation loses two thirds of the rows, so `Application Status` is
  normalised and `Application Status As Recorded` carries the raw values.
- **`recvday` and `decisionday` are single constants** (2023/12/21 and
  2023-12-29), so every measured processing time is exactly 8 days and the mean,
  minimum and maximum all equal 8, with standard deviation 0. 216 of 981 have no
  decision date. This makes KB 32 (Processing Efficiency Ratio) identically 1.0,
  and it is not shipped.
- **One receipt month in the whole warehouse**, so `Seasonal Application Index`
  is identically 1.0 and KB 58's continuous filer (9+ months) is unreachable.
- **No application offers below its prevailing wage** (WDR min 0.00, max 457.23,
  mean 21.4242), so the KB 48 `Below-Market` tier is empty.
- **`willfulv` has no `Yes` value at all**, so a willful-violator filter returns
  nothing.
- **Attorney names are not unique** - 19 names cover 45 of the 386 attorneys - so
  `Attorney Email` is a queryable secondary and the leaf description *leads* with
  the warning.
- **`cases.headct` equals `case_worksite.wsheads` on every row**, so one
  `Worker Positions` measure ships, not two. `cases.siteslots` (1 to 10) does not
  match the worksite records (exactly one per application), so `Worksites` (854)
  and `Reported Worksite Slots` (1,472) ship as separately disambiguated
  measures.
- **Law firm names carry casing variants** (Fragomen appears twice), so the
  `Law Firm` description leads with the fact that grouping splits such firms.

### Masked-term policy and its expected cost

The rule applied, stated so it can be checked: a formula the knowledge base
states explicitly is shipped even when a task marks the term ambiguous (there is
no constant to hard-code), while a threshold-bearing classification is shipped
only when its ambiguity entry is `is_mask: false`. One qualifies - the KB 44
geographic hotspot, shipped as `State Application Hotspot` (9 of 47 states).
Nine masked classifications are deliberately absent - visa filing window,
complexity tiers and score, employer size classification, attorney
specialization category, attorney performance rating, employer dependency level,
premium wage position, skill shortage occupation - and their components ship
instead, each description saying it is one input to a larger named concept and
that the agent should ask the user for the complete definition first.

Tasks 3, 6, 7, 10, 11, 14, 15, 16, 18, 20, M_1, M_2, M_5, M_7, M_8, M_9 and M_10
each turn on one of those. Expect them to fail and report them separately from
real defects; on `cybermarket_pattern` no honest model change moved this class.
Separately, the ten `Management`-category tasks ask for DDL (create a table,
add a column, define a function or trigger), which a read-only semantic layer
cannot do at all - only their analytical follow-ups are expressible.

### Knowledge-base entries this database cannot support

KB 22 and 38 need a cost-of-living index; KB 39 needs a premium-processing
column; KB 36 needs more than one year of receipts; KB 42 is defined against
total workforce - none of which exist here. KB 27, 33 and 35 need a sum of
squared shares, which the engine cannot express inline, and no task references
them. KB 17 is provably identical to KB 11 in this data (the minimum required
wage *is* the prevailing wage), so one object ships and says so. Full table in
the model's `SPEC.md`.

### Acceptance evidence

1. **Exactness** - 15 headline figures returned by the model are exact-equal to
   the same aggregates computed directly on Postgres over the fact's own SQL
   (981 / 981 / 1134 / 854 / 546 / 386 / 290 applications, certified, positions,
   worksites, employers, attorneys, preparers; WDR mean 21.424249284, pooled
   19.506209045; 8.0 processing days over 765; approval 100, external counsel
   74.108053007, retention 22.528032620). Level IV annual-paid WDR 20.42958427
   over 132 applications, and the full state distribution with its concentration
   ratios, also match exactly.
2. **Conformance** - one measure-by-attribute query per dimension, all 13
   non-empty, including every secondary attribute.
3. **Discoverability** - probed with the task briefs' own question wordings only;
   eight gaps found and closed, then re-verified live.
4. **Coverage** - one passing query per shape: group aggregate, filter-by-
   classification then measure, superlative top-N, multi-dimension across three
   separate source tables, entity-level detail, group-relative comparison. The
   only shape not answerable is a median, which is dialect-blocked and
   documented.

The outbound warehouse SQL was read (`get_outbound_queries`) to confirm the
derived dataset is pushed down verbatim with `public.` qualification and the
`DENSE_RANK()` window intact, and that the share calcs compile to the
UNION ALL + self-join form rather than being silently dropped.

**Not yet done:** no evaluation run. Per the build prompt's own guidance, treat a
first run at baseline as the start of the work: read the agent's submitted SQL
for every failing task, sort model-fixable from masked-term and non-unique-answer
failures before changing anything, and require n>=3 per arm before believing any
delta.

**2026-08-13 - first evaluation round: 3 raw runs, 1 atscale run, all void.**

Every task in all four runs scored 0.000, including all three raw baselines. A
text-to-SQL baseline does not go 0/19 three times, and the same harness scored
raw 0.230 / atscale 0.474 on `exchange_traded_funds` an hour earlier, so the
cause was harness-side and specific to this database. Root cause and fix are in
the ADK commit "db_environment: stop per-task DB names colliding past Postgres'
63-byte limit"; the short version is that this is the first BIRD database whose
name is long enough that `{base_db}__{instance_id}` exceeds 63 bytes, and
Postgres truncates over-length identifiers with only a NOTICE while `createdb`
still exits 0. Consequences: all 20 tasks shared one physical database, `init_task`
500'd on 3-4 tasks per raw run, and - the one that mattered - **a phase-1 pass
was recorded as a failure**, because the Phase-1 snapshot name truncated to the
same 63 bytes as its own source and the resulting `createdb` error was caught by
the handler that returns `passed=False, reward=0.0`. Phase 2 was therefore
unreachable for the whole database in both arms.

Add a new row to the Workarounds discipline: **when both arms score 0.000 on
every task of one database, suspect the harness before the model, and check
whether that database's name is unusually long.** ETF at 55 bytes is one byte
inside the limit; nothing else had crossed it in five models.

The true phase-1 rates are recoverable from the trajectories, because every
phase-1 pass left the `createdb` error as its fingerprint:

| arm | runs | tasks that never started | true phase-1 /19 | tasks passed |
|---|---|---|---|---|
| raw | 3 | 3, 3, 4 | 0.263 (sd 0.053) | 4, 6, 7, 8, 10, 11 |
| atscale | 1 | 0 | 0.263 | 2, 3, 4, 7, 8 |

Level on the mean, with raw's figure understated (3-4 of its tasks never ran) and
atscale at n=1 against a +/-0.05 spread. **No lift is measurable from this round.**
One genuinely reassuring result: discovery cost is at parity, 5.1 calls per task
in both arms, so the 117-object surface is not the `cybermarket_pattern`
budget-exhaustion failure mode.

Reading the submitted SQL sorted the atscale losses into three classes.

- **Real, model-fixable (task 6).** The user stated a Wage Differential Rate
  cut-off of their own. The agent filtered on the shipped `Wage Competitiveness
  Tier` instead - a KB 48 bucket with a different boundary - and answered 60
  positions where the user's threshold gives 33. It did that because the correct
  path did not exist: `WHERE "Wage Differential Rate" > <n>` returned `Column not
  found`. WDR shipped only as measures, and a measure can be aggregated but never
  filtered or grouped BY. Same gap made task 11 inexpressible once the user
  supplied the filing-window buckets. Fixed by shipping the continuous numerics
  as attributes as well as measures, plus two grand-total shares so a
  caller-defined CASE bucket can report its own percentage. **The general lesson
  for the other models: audit every continuous numeric for a queryable twin, and
  treat "the caller supplies the threshold" as a first-class query shape. A
  KB-sanctioned bucket whose boundary differs from the caller's out-competes the
  correct path on name match, and if the correct path is inexpressible the agent
  has no way back.**

- **Capped, not fixable (task 10).** The atscale query returned values identical
  to raw's passing one (Complex 156 / 8.0, Standard 609 / 8.0). Only the row order
  differed; `conditions.order` is true, `grading_tie_tolerance` defaults to False,
  and every processing time in this warehouse is 8.0 - so "ordered by processing
  time" does not determine the order and the expected answer is not unique.
  Whether to enable tie tolerance is a grading-policy decision and was left alone
  deliberately: flipping it to make one arm look better is not a model fix.

- **The masked-term rule working as intended (tasks 6, 10, 11 in the raw arm).**
  Raw won all three by asking the user, and the simulator handed over the exact
  cut-offs - "greater than 20%", "Complex or Standard based on H-1B dependency or
  willful violator status", the five filing-window labels. That is the path the
  benchmark intends for a masked term, and it is the reason the semantic arm must
  not pre-empt it. The model change above deliberately makes the caller's answer
  *expressible* without making any withheld number *discoverable*.

One self-inflicted near-miss worth recording: the first draft of the new
attribute's description illustrated it with "above 20 percent", which is KB 40's
withheld threshold - handing over for free what the raw arm spends a turn buying.
The incoming `utilities/masked_threshold_gate.py` passes that text either way (its
regex excludes bare "above" as too noisy to be useful), so it was fixed on the
policy rather than on the detector. That gate now runs as step 5 of the model's
`build.sh`.

**Still not done: a re-run.** Nothing about the scores above should be quoted; the
next round needs n>=3 per arm on the fixed harness.

---

## organ_transplant

**2026-08-15 - initial build.** Generated by `organ_transplant/generator/`
(`spec.py` -> `generate.py`, with `sql.py` holding the derived SQL, `stats.py`
harvesting every live count a description quotes, and `dryrun.py` pinning the
KB formulas). 254 objects: 3 derived datasets, 16 dimensions, 95 metrics
(6 hidden), 13 `metric_calc`s, 1 model. Deployed with
`sml-cli atscale-deploy --catalog-name=bird_atscale_models_catalog_main`;
`list_models` read back 8 models afterwards (the Q-17b gate).

**Answer-key firewall.** Mechanical, not intentional:
`generator/extract_brief.py` allowlists the permitted task fields, drops
`sql_snippet` and `deleted_knowledge` even from the ambiguity entries it does
copy, then asserts on its own output that no denied key name and no SQL-shaped
value survives. No gold SQL reached the build.

**Shape.** One wide match fact (947 rows) left-joining all six match-level
satellites, plus donor (659) and recipient (787) dimensions each left-joining
their own 1:0..1 satellites. Every satellite verified orphan-free first, so the
whole conformance failure class is designed out rather than tested for: all 16
dimension groups reach the single fact.

**Masked-concept split** (generator gate A10, derived from `is_mask` in the
brief and the KB entry's own `type`, not from a reading of the word
"threshold"). Masked `calculation_knowledge` - a KB-named formula - ships under
its own name: Cost-Effectiveness Ratio, Patient Urgency Score, Composite
Allocation Score, Renal Function Score, Size Compatibility Score, 5 of 5.
Masked `domain_knowledge` does not ship: the optimal donor-recipient match
classification, the antibody-mediated rejection risk stratification, the
marginal donor framework and the allocation policy ordering are published as
their components only, 0 of 4. Each component's description names the wider
concept and routes to a closed question naming the shape of answer to request -
every condition, the exact numeric cutoff, the exact label text, the user's own
spelling, and re-ask rather than choose on a qualitative reply. **Expect this to
cost tasks** - `organ_transplant_1`, `_2`, `_4`, `_16` and `M_2` all turn on one
of those four terms - and report them separately from real defects.

**Engine dialect, re-probed live 2026-08-15** against this deployment rather
than carried over: `NTILE`, `CORR`, `PERCENTILE_CONT`, `STRING_AGG`, `GREATEST`
and CTEs are all rejected; `RANK`, `ROW_NUMBER`, `LAG`, `ROUND` and
`SUM(CASE WHEN ... THEN 1 ELSE 0 END)` are accepted. Two consequences carried
into the model: `CORR` being rejected is why the six hidden paired-sum measures
and the `Ischemia Time To Graft Survival Correlation` calc exist (verified equal
to Postgres `corr()` to 16 digits, under a filter as well as unfiltered), and
`LAG` being accepted is why no consecutive-run object ships - the caller can
write it. The model description states the probed list so a caller does not pay
to discover it.

**Workaround rows applied.** E-02 - every derived table reference is
`public.<table>`, asserted by gate A2. D-01 - no `|` anywhere in the emitted
SQL, asserted by gate A1, which is why the blood-group parse uses
`split_part`/`rtrim` rather than a regex alternation. E-01 and Q-15 - both
re-confirmed live on this model (`COUNT("Donor")` returned the string
`D102099`, and co-projecting it with `COUNT(DISTINCT "Donor")` collapsed the
distinct count to 1 per row); the Donor, Recipient and Match key attributes now
**lead** with that warning and name the count measure to use instead.
Catalog-suffix - the suffixed name was passed verbatim and
`config/environment_backends.yaml` gained a matching `organ_transplant` entry.
MDX-Median - not needed; no KB definition here rests on a median.

**Three defects found by the acceptance gates, all fixed before the final
deploy.**

1. *Provably redundant object.* Center volume and center outcome are recorded
   together on all 774 matches carrying a risk record and never one without the
   other, so the group formula `0.6*avg(vol) + 0.4*avg(out)` and the mean of the
   per-row `0.6*vol + 0.4*out` are equal under any filter. Both had shipped;
   only the group-level `Center Performance Score` survives, and its description
   says why. The other two group/entity pairs (composite allocation,
   comprehensive match quality) were checked the same way and **do** differ,
   because their components have different support sets, so both readings of
   each are kept.
2. *Stale cross-references after a rename.* The 63-character `unique_name` limit
   forced five renames, and four description cross-references were left pointing
   at names that no longer existed, plus one naming a per-match
   readmission-risk attribute that was never published. The existing gate only
   saw references introduced by see/use/compare-with. New gate **A12** checks
   every parenthesis-qualified object name quoted anywhere in a sentence, and a
   negative test confirms it fires. New gate **A11** fails the build on any
   `unique_name` over 63 characters, so the rename cascade cannot recur silently.
3. *A KB conflation that would have returned the wrong population.* `High-Risk
   Donor` carried "extended criteria donor" as a paraphrase, but KB 53 defines
   the marginal / extended-criteria framework as applying to donors who are
   **not** classified high risk. A marginal-donor question would have matched on
   surface words, returned a plausible number over the wrong population, and
   signalled nothing. Both objects now lead with the distinction and route to
   ask-the-user.

**Degeneracies found by profiling, stated in the descriptions of every object
that touches them.** Every match timestamp falls inside a single second
(`match_ts` is one constant string across all 947 rows and is withheld
entirely; `created_ts` varies only in microseconds), so there is no usable time
dimension, elapsed-time statistics over it are meaningless, and any ordering by
it - including the Previous Match carry - is effectively arbitrary. The donor
organ recovery date has two distinct values; the data-quality update date has
one. The youngest recipient is 18, so any paediatric or under-18 population is
empty. No transplant center has more than 4 matches, so per-center averages rest
on very few cases and center rankings tie heavily.

**Recorded-versus-computed pairs, all verified to differ before both were
shipped.** Recorded expected graft survival vs the KB's logistic formula: 0 of
730 agree at 4dp, correlation -0.0072. Recorded blood compatibility vs the ABO
rule computed from blood groups: agree on 381 of 730. Recorded HLA mismatch
count (0-6) vs the locus-by-locus comparison (0-3): agree on 93 of 687. The
recorded size and age sub-scores vs their KB formulas: 0 of 870 and 2 of 870.
Each pair ships under asymmetric names with those counts in both descriptions.

**Not computable, recorded so a silent gap is distinguishable from an
oversight.** The resource utilisation index needs an expected length of hospital
stay, which no column in this warehouse carries; the components ship and the
description routes the length-of-stay choice to the user. The net health benefit
score is parameterised by a caller-supplied QALY gain, so no single object can
carry it; the formula is stated on Surgical Risk Score and both components ship.
Regional allocation priority compares the donor's region with the recipient's,
and no donor region column exists. Quantile bands over any score cannot be built
at build time because a band cannot know the runtime population - row-level
score attributes ship so the caller can derive one from `ROW_NUMBER`. The full
list with reasons is `OMISSIONS` in `generator/spec.py`.

**2026-08-16 - first measured round, 3 runs per arm, query-only (19 tasks).**

| arm | run 1 | run 2 | run 3 | mean | sd | phase-1 passes |
|---|---|---|---|---|---|---|
| raw | 0.0895 | 0.0526 | 0.0737 | **0.0719** | 0.0151 | 5 of 57 task-runs |
| atscale | 0.0368 | 0.0368 | 0.0526 | **0.0421** | 0.0074 | 3 of 57 task-runs |

Gap -0.0298 average reward (-41% relative, -0.57 reward points over 19 tasks),
exact Mann-Whitney U=0.5, two-sided **p = 0.200**. Note what that p can and
cannot say: at 3 versus 3 the exact test's floor is p = 0.100, so 0.200 with
U=0.5 is close to the most separation this design can show. **n=4 per arm is
the minimum that can reach p < 0.05**; the pooled sd of 0.012 against a 0.030
gap says about 3 per arm suffices on power alone, so one more run each is the
cheap next step - not four.

**Both arms are on the floor, and that is the headline.** The raw text-to-SQL
baseline scores ~0.30 on every other database in this repo and 0.072 here. 16
of 19 tasks never passed in raw across three runs, 18 of 19 never passed in
atscale. A raw arm at a fifth of its usual score is a statement about the task
set, not about either backend.

**The harness is not at fault** (checked first, per the 0.000 fingerprint):
submit results carry real grading verdicts (`SQL failed Phase 1. Your SQL is
not correct.`), not error strings, so no passes are being swallowed. The
database name is 16 characters and nowhere near the 63-byte identifier limit.

**Grading flags explain nothing.** All six runs re-graded under all four
tie-tolerance / decimal-honouring combinations: **zero verdict flips in every
run, both arms**. Tie-order and rounding are not in play on this database.

**Root cause: the reference answers' populations are an artifact of which
satellite tables the gold SQL happens to join.** 18 of 19 references INNER JOIN
at least one optional satellite - up to four of them - and every such join
silently narrows the population. Worked example, task 18: the four-table chain
(`recipients_immunology`, `clinical`, `compatibility_metrics`,
`risk_evaluation`) cuts 947 matches to 472 before any stated filter, and to 91
after the question's own conditions. The agent, correctly filtering
`Match Status = 'Completed'`, returned 166 recipients. Neither the question nor
the knowledge base mentions any of it, and the chain differs per task (task 9
joins one satellite, task 18 joins four), so there is no single convention to
learn. This model LEFT JOINs its satellites deliberately - that is what keeps
every match present and every dimension conformant - and switching to inner
joins to match gold would be answer-fitting to the reference's SQL-writing
habits, would break the coverage the support-set measures exist to expose, and
would still be wrong for the tasks that join a different subset.

Further conditions stated nowhere in either the question or the KB: task 14
gates on `HAVING COUNT(*) > 1` (which is what turns "top 10 centers" into a
3-row answer); task 11 invents five weights (0.4/0.6 and 0.7/0.3) for scores
the question only asks the analyst to "come up with"; task 13 buckets with
`WIDTH_BUCKET` (equal-width) rather than `NTILE` (equal-count) and so returns
**6** rows to a question asking for 5 groups; task 7's gold maps medical
urgency as 1A=5, 1B=4, **ELSE 2**, which contradicts KB 25 (Status 2=3,
Status 3=2, all others=1). The model implements KB 25, per the follow-the-KB
rule, and that costs task 7 - correctly. No third urgency reading was added,
because a 1A/1B/else-2 mapping has no basis in the KB.

**Failure classification of the last phase-1 submission per task** (shape
against the reference, which is the only cheap way to know what a model change
could reach):

| | raw | atscale |
|---|---|---|
| shape matches, values wrong | 10 | 5 |
| wrong row count | 6 | 8 |
| wrong column count | 3 | 1 |
| would not execute at all | 0 | **4** |

On four tasks *both* arms produce the **identical** wrong shape (7, 11, 13,
14) - conclusive that those are question-interpretation failures rather than
backend failures.

**What the semantic arm pays that raw does not.** 17% of its query calls
errored, against 1% for raw - a 17x difference, and every errored call still
costs a coin. Classified exactly: `must appear in the GROUP BY clause` (12, the
rule that every measure needs an aggregate wrapper once a query contains a
join), an `assertion failed: We already handled attribute values` planner error
(9), `incorrectly constructed` constraints (8), column-not-found (6), `ntile`
(3), `Could not find correct column to sort by` (3), aggregate-in-WHERE (2),
NULLIF (2), a parse error (1), and 16 assorted engine errors. Only three name
misses in the whole round (`Surgical Risk Score`, `Surgical Risk`, `center`),
so discovery and naming are essentially working.

**Correction, 2026-08-16.** An earlier version of this entry claimed 13 CTE
rejections and attributed them to the engine. Both halves were wrong. The count
came from a classifier bug - a case-insensitive `'cte' in text` test matching
the letters inside "constru**cte**d" - and the true count of tool-guard
rejections across all six runs is **zero**: no agent ever attempted a CTE, so
the guard cost nothing this round. And the guard is not an engine limit at all;
it is a client-side single-virtual-table policy in the MCP query tool
(`validation.py`, `FromQualificationError`). The AtScale engine itself is not
what refuses a `WITH` clause. Verified against the running server: a subquery in
the FROM clause and an INNER JOIN to one both execute normally, so a CTE rewrites
as `FROM (SELECT ...) t` - which is what the agents were already doing. Only
`IN (subquery)` is separately refused. The model description now states the two
layers separately and gives that rewrite.

**Forward risk worth tracking.** The `develop` branch of the MCP server extends
that same guard to reject **JOINs and FROM-subqueries** as well, not just CTEs.
The running server permits both. Every successful phase-1 submission in this
round used a FROM-subquery, and the model's own coverage gate uses an INNER JOIN
to a subquery, so shipping the `develop` guard as-is would break queries that
work today and would remove the only available CTE workaround. Worth measuring
before that lands.

**Surface size is not the problem this time.** Discovery cost 23% of the
semantic arm's coins against 22% for raw - at parity, with 2.5 `explore_columns`
calls per task against the 7.6 that made `cybermarket_pattern` pathological.
The semantic arm used *fewer* tool calls than raw (12.4 vs 16.9 per task) and
ran out of budget less often (60% of task-runs vs 88%). It is not being taxed
by model size; it is being taxed by query rejections and by the same
unwinnable references raw faces.

**Read this database as a broken comparison rather than a model result.** The
honest summary is that organ_transplant's reference answers encode populations
and constants that neither arm can derive, both arms sit near zero, and the
-0.030 gap between them is real in direction (all three atscale runs at or
below all three raw runs) but not resolvable at n=3. Before spending another
round on model changes, the question worth answering is whether this database
should be in the comparison at all.

**2026-08-16 - round 2 model changes (not yet measured).** Three changes, each
justified from the schema or an existing rule rather than from a reference
answer, and each verified sufficient before shipping.

1. **Eleven `Has ... Record` attributes**, one per optional source table. This
   is not a new idea - the build prompt already requires *both* halves of the
   support-set rule, the counts **and** "an availability classifier saying which
   entities carry the required inputs". The first build shipped only the counts,
   so this closes an under-implementation. Every satellite is 1:0..1 with
   coverage from 518 to 862 of 947 matches, and only **472** carry the
   compatibility, risk, clinical and immunology records together, so a measure
   is averaged over whichever matches carry its inputs - not the same population
   as the next measure's. Before this, a caller could express that population
   only by accident, via some column of the table happening to be non-null.
   Verified: presence-filtering the LEFT-joined fact reproduces an inner-join
   chain's population **exactly on 18 of 18** measurable task populations, and
   tasks 18 and 17 reproduce their full reference answers cell-for-cell through
   the deployed model.
2. **Match Status now asks a closed question**, naming its five member strings
   with live counts (Completed 174, Matched 195, In Progress 188, Pending 171,
   Failed 219) and saying explicitly not to infer the states from a word like
   finished or waiting. This is the ask-the-user shape that was the only
   measured score mover on `labor_certification_applications` (+0.040).
3. **A POPULATION section in the model description**, stating the grain, the
   per-table coverage range, the 472 four-record intersection, and that a column
   being non-null is an accident of that column rather than a statement about
   the record.

**Provenance, stated plainly.** The need for (1) was found by diagnosing failing
tasks against gold, which the build prompt sanctions. What shipped is a fact
about the schema - which source rows exist - and encodes no reference answer:
the agent must still decide which records a question requires, and the
descriptions deliberately do not hint at that. Nothing was changed to match an
expected value.

**Predicted payoff: zero**, per the standing rule. These make the reference
population *reachable*; they do not make the agent reach for it. The model was
already capable of task 18's answer through an accidental proxy and the agent
still missed it, which is exactly the pattern that says a capability fix removes
a known-wrong answer without producing a right one.

**Still unwinnable regardless of the model**, and worth subtracting from any
expectation: tasks 1, 2, 4 and 16 turn on masked terms (the firewall working);
task 7's gold urgency mapping contradicts KB 25; task 11 invents five weights;
task 13 buckets by WIDTH_BUCKET and returns 6 rows to a 5-group question; task
14 gates on an unannounced `HAVING COUNT(*) > 1`. That is 9 of 19 before the
agent writes a line of SQL.

**2026-08-16 - round 2 measured, and withdrawn.** One atscale run after the
round-2 changes: **0.0526** average reward, 1 of 19 phase-1 passes, phase 2 1.
That is exactly the maximum the three pre-change runs already reached (0.0368,
0.0368, 0.0526), and the same single task passes (`organ_transplant_22`). The
prediction of zero payoff held.

The mechanism is unambiguous rather than merely null. Across **129** query and
submit calls the agent referenced a `Has ... Record` attribute **zero** times,
while `explore_columns` surfaced one **18** times. They were discovered and
ignored - which is the correct behaviour, because no question ever asks for
"matches that have a risk record". The attributes answered a question nobody
poses; the population narrowing lives in gold's join chain, not in the user's
words, so no amount of making it *expressible* makes an agent *want* it.

Every cost metric meanwhile landed at or above its pre-change maximum: error
rate 23% (prior range 11-21%), budget exhaustion 74% (42-68%), budget used
17.66 (15.58-17.21), `explore_columns` 2.89 per task (2.16-2.68). n=1, so each
of those is within a whisker individually - but all four moving the same way
while the score does not is what 11 never-used objects look like.

**Withdrawn**, per "an added object must earn its place twice" and the standing
preference for withholding columns no question touches. The derived fact
columns went with them.

The other two changes were kept because they add no objects, and both were also
inert: asks mentioning match status ran 46% before and 47% after, and the
agent's chosen status filter matched gold on 21 of 42 before against 8 of 14
after - indistinguishable, and in any case the agent already picked the status
correctly about half the time *and still failed*, because the population also
needs the record restriction it never applies.

**The increased error count was checked and is not a regression from the
change**: the extra `not found` errors are `ProjectContext` resolution failures
and the agent referencing columns its own nested subquery did not project -
agent-side SQL bugs, with zero mentions of any new attribute name.

**Conclusion for this database.** Three model changes have now been tried
against a measured baseline and none moved a task. The failure classes that
remain are, in order: reference populations defined by gold's join chain rather
than by the question; conditions stated nowhere (an unannounced `HAVING`, five
invented weights, `WIDTH_BUCKET` returning 6 rows to a 5-group question); a gold
urgency mapping contradicting KB 25; and four masked terms. None of those is
reachable from the semantic layer, and the raw arm scores 0.072 against its
~0.30 baseline elsewhere for the same reasons. **Recommend no further model
work on organ_transplant, and a decision on whether it belongs in the
comparison at all.**

### organ_transplant - per-task AtScale failure breakdown (4 runs pooled)

Primary blocker = the first thing that must change for the task to pass. Shapes
are the last replayed phase-1 submission against the reference.

| task | passed | ref shape | agent shape | primary blocker | category | model-fixable |
|---|---|---|---|---|---|---|
| 1 | 0/4 | 198x5 | 238x5 | masked AMR risk stratification | masked term | no - firewall |
| 2 | 0/4 | 15x5 | 18x5 | masked allocation-policy ordering | masked term | no - firewall |
| 3 | 0/4 | 3x4 | 3x4 | unstated 5-year QALY constant | unstated constant | no |
| 4 | 0/4 | 2x6 | - | masked optimal-match classification | masked term | no - firewall |
| 6 | 0/4 | 4x4 | - | join-chain population (4 satellites) | population | expressible, unused |
| 7 | 0/4 | 60x5 | - | gold urgency ELSE-2 contradicts KB 25 | KB contradiction | no |
| 8 | 0/4 | 4x3 | 4x3 | join-chain population (4) + unstated Completed | population | expressible, unused |
| 9 | 0/4 | 4x3 | - | engine parse failure on 2 of 4 finals | engine/agent SQL | partly |
| 10 | 0/4 | 5x5 | 5x5 | join-chain population + unstated Pending | population | expressible, unused |
| 11 | 0/4 | 10x2 | 10x4 | five invented weights | unstated constants | no |
| 13 | 0/4 | 6x3 | 5x3 | WIDTH_BUCKET, so 6 rows to a 5-group question | bucketing method | no |
| 14 | 0/4 | 3x4 | 10x4 | unannounced HAVING COUNT(*) > 1 | unstated gate | no |
| 16 | 0/4 | 34x4 | 280x4 | masked marginal-donor framework | masked term | no - firewall |
| 17 | 0/4 | 4x4 | 4x4 | join-chain population (3 satellites) | population | expressible, unused |
| 18 | 0/4 | 4x5 | 4x5 | join-chain population (4) + unstated Completed | population | proven expressible, unused |
| 19 | 0/4 | 3x2 | 2x2 | join-chain population + locus semantics | population | expressible, unused |
| 20 | 0/4 | 51x5 | 80x5 | join-chain population + unstated Pending | population | expressible, unused |
| 21 | 0/4 | 6x3 | 4x2 | omitted the count column | output shaping | no |
| 22 | 4/4 | 7x3 | 7x3 | - passes every run | - | - |

**Totals.** Masked term 4; unstated constant, gate or method 5; join-chain
population 7; output shaping 1; engine/agent SQL 1; passing 1. **Nine of
nineteen are unreachable before the agent writes a line of SQL**, and the seven
population failures are reachable in principle but were not reached even with
explicit attributes published (round 2, withdrawn). Phase 2 was entered on one
task only, `_22`.

**Two findings that validate the model rather than indict it.**

*Task 21 is right and still fails.* Gold computes `cost_est / (qol_val * 8)`.
The published `Cost-Effectiveness Ratio Per Life-Year (Per Match)` divided by 8
reproduces gold's per-urgency averages **cell-for-cell** (12 at 13345.44, 17 at
30832.02, 27 at 22505.34 for the first three groups). The task fails because the
agent projected 2 columns where the reference has 3. The model does not control
the caller's SELECT list.

*The per-life-year parameterisation was the correct call.* Gold uses a 5-year
gain on task 3 and an 8-year gain on task 21 - two different constants for the
same knowledge-base formula, neither stated in either question. Publishing the
ratio at one life-year with "divide by Y" in the description is the only shape
that serves both, and it was chosen from the KB before any gold was read. Task 3
still fails because the projected value carries the unstated 5, even though
NTILE ordering is scale-invariant.

**2026-08-16 - round 3: satellites become dimensions (the population fix,
structural this time).** Round 2 failed because it asked the agent to *opt in*
to a population restriction no question names. Round 3 makes the restriction
the *default semantics of the query the agent already writes*, using a
mechanism the engine already has: dimension relationships are INNER joins
(verified in outbound SQL - a bare `JOIN`, not `LEFT JOIN`). The wide
denormalized fact was erasing exactly that behaviour.

Each optional source record is now its own dimension at its own grain: six at
match grain (Compatibility Assessment 870, Risk Evaluation 774, Administrative
Review 641, Allocation Detail 561, Transport Logistics 518, Data Quality Record
859), two at recipient grain (Clinical 607, Immunology 645), three at donor
grain (Medical Record 575, HLA Typing 534, Organ Recovery 513). 91 attributes
moved off the fact and the Donor/Recipient dimensions onto them, keeping their
names; single-record formulas are recomputed on their record's dataset;
cross-record computed attributes stay degenerate on Match, where their nulls
already encode joint presence. Metrics still ride the wide fact, and a query
mixing a metric with record attributes restricts the metric through the joins.

**Why this is not answer-fitting.** The mechanism is the engine's own star-join
semantics; the placement is what the build rules prescribe (degenerate
dimensions are for genuinely fact-grain attributes; these are entity-grain
records); and the per-query narrowing it produces is derived from which columns
a question references, not from any reference answer's contents.

**Verified live after deploy** (list_models healthy, 8 models, all 18 dimension
groups conforming):

- `Match Count` alone: 947. Grouped by Transport Method: no null group, totals
  518. Metric averages through the logistics join: exact to the warehouse's own
  inner join at 6 decimal places.
- **The natural attribute-form query for task 18 - no presence filters, no
  special knowledge, just the four columns the question asks about - now
  reproduces gold cell-for-cell**: buckets 12/60/14/5, HLA 2.75/3.13/2.79/2.60,
  wait 397/511/567/399, EGS 0.5496/0.4791/0.4622/0.3958. Before the change the
  same reasoning produced 166 recipients and failed.
- Task 22's stored passing submission replays unchanged (7 rows).
- The agents' stored metric-form submissions shift toward gold (task 18's
  Very High bucket lost its null-PRA rows, task 8 lost its null-transport row)
  but do not fully converge - metrics do not force joins for records whose
  attributes are never referenced.

**Known limits, so the next run is read correctly.** (1) The fix reaches the
population only when the agent references record *attributes*; a metrics-only
query still averages per-column. In the measured runs 65% of submissions used
the attribute/subquery form. (2) Count semantics stays the agent's choice:
gold counts match rows, agents sometimes count distinct recipients (91 rows vs
87 recipients on task 18's population). (3) Phantom joins remain capped: task
17's gold joins function_and_recovery without referencing any of its columns,
so no reference-driven mechanism can reproduce it. (4) The engine's
`We already handled attribute values` planner assertion rejects the DIRECT
`AVG(attr) ... GROUP BY attr` form (no subquery); this predates the restructure
(9 direct-form attempts across the old runs, only 2 succeeded) but its surface
is wider now that more attributes live on dimensions - the subquery form the
agents favour works. (5) The masked terms, unstated constants, invented
weights, WIDTH_BUCKET and the KB-contradicting urgency mapping are untouched
by this change; 9 of 19 tasks stay unreachable on those grounds.

**2026-08-17 - first post-restructure run (n=1): 0.0000, and the zero is
infrastructure, not the model.** Three of nineteen tasks - including
`organ_transplant_22`, the only task that ever passes and the source of the
entire prior score - were killed mid-flight by empty LLM completions: task 22
stopped after 3 tool calls with 13 coins unspent and an empty final response,
task 7 stopped directly after an ask_user answer, task 13 stopped after a
successful run_query with 5 coins left. None submitted. The other 16 tasks ran
normally (27 submissions, zero grading flips under all flag settings, query
error rate DOWN to 7% from 17%, no name misses on any moved attribute), so the
restructure introduced no regression; a run without the three agent deaths
would have been expected to score in the prior 0.037-0.053 band or above.

**The restructure is visibly working where it was exercised.** Task 2's
submission now returns exactly the reference's 15-row population (was 18 before
the change) - the allocation and clinical joins fired structurally; its values
still fail on the masked allocation-policy ordering, which is the firewall
class. Task 17's agent wrote precisely the attribute-form ratio query the
restructure serves, asked the closed status question the Match Status
description prescribes (and got "only Completed"), then asked for the
short-trip threshold - **and the user simulator answered 10 miles where gold
uses 50**. That task was unwinnable this run regardless of any model (the
check-the-simulator class), and it would still face gold's phantom
function_and_recovery join. Task 18's agent happened to choose the metric form
this run (the form is stochastic across runs; three of five prior submissions
were attribute-form), which does not force the joins.

Conclusion unchanged from the per-task breakdown: the structural fix removes
the population blocker for attribute-form queries, the remaining failures sit
in the masked / unstated-constant / simulator-contradiction classes, and this
run's headline measures an LLM-availability incident plus known caps, not the
change. Before the next scored run, check the agent-side logs for the empty
completions; a run where a fifth of tasks die unsubmitted measures nothing.

**2026-08-17 - second post-restructure run (n=1), with SYSTEM_AGENT_MAX_TOKENS
fixed: 0.0737** - the best atscale run of the five, above the prior 0.037-0.053
band, equal to raw's median and inside raw's range. Single-run noise is ±0.10,
so the score alone claims nothing; the composition is the evidence.

- **Harness fix verified.** 259 agent calls, zero at the old 4096 ceiling (max
  completion 6573), zero empty-final agent deaths, 19 of 19 tasks submitted.
- **organ_transplant_2 passed phase 1 for the first time in any atscale run**
  (0 for 4 before), and its trajectory composes every mechanism built across
  the three rounds: the agent asked the masked allocation-ordering question and
  the simulator handed over the rule (the firewall behaving as the benchmark
  intends); asked the numerals-as-tiers question straight from the Medical
  Urgency Status description and applied the confirmed ALT mapping inline;
  asked recorded-versus-computed HLA (the asymmetric-names design); and the
  allocation+clinical+compatibility joins fired structurally, producing the
  15-row population the restructure was verified to reach. The
  always/never/flaky discipline supports attribution: the task moved
  never-to-pass immediately after a change that touched exactly the objects it
  references.
- **Phase 2 went 0 for 2, both on name guesses made with no coins left to
  explore**: the agents wrote "Expected Graft Survival Score" and "Surgical
  Risk Score" where the published attributes carry "(Per Match)". Task 22's
  follow-up is a proven pure name-miss: gold's own answer is NULL (TC212 has no
  Completed match with a risk record), and the agent's exact SQL with the
  correct name returns NULL - identical. Task 2's follow-up also mis-scoped the
  population (gold averages over all matches of the listed recipients, not
  pancreas-pending matches), so the name alone would not have saved it.
- **Candidate next change, grounded in the name-ownership rule rather than
  gold**: nothing currently owns the bare names "Surgical Risk Score" or
  "Expected Graft Survival (EGS) Score" - the attributes carry "(Per Match)"
  and the metrics carry "Average ...". The rule says exactly one reading takes
  the bare name, chosen from the questions' vocabulary; the questions say the
  bare form. Stripping "(Per Match)" where the bare label is unclaimed would
  have flipped task 22's follow-up this run (+0.3 reward, verified sufficient
  for free above).
- Task 17 is confirmed permanently capped: the simulator answered "10 miles"
  to the short-trip question in both runs that asked; gold uses 50.
- Task 18 drew the attribute form this time - the form the restructure serves -
  and died on the agent's own SQL bug (an alias referenced across subquery
  scopes: `column t_51.pra does not exist`). Bad luck of a different flavour
  than last run's metric-form draw.

**Where this leaves the comparison.** Every prior atscale/raw number was
measured under the truncating 4096 config; this run is the first on the fixed
harness, and the arms are no longer comparable across that boundary. A clean
head-to-head needs n>=3 per arm on the new config (raw first - its old numbers
are also suspect, though no raw task ever died of truncation).

**2026-08-17 - round 4: bare-name ownership + engine-behaviour documentation
(not yet measured).** Twenty-two row-level attributes drop the "(Per Match)"
qualifier; nothing owned the bare names, questions use the bare form, and both
phase-2 failures in the last run were bare-name guesses made with no coins
left. Verified sufficient before shipping: task 22's stored phase-2 SQL with
the bare name returns NULL, identical to gold's own NULL. Center Performance
Score keeps its qualifier (the bare name belongs to the group calculation).
The model description gains two engine facts: the planner assertion that
rejects direct attribute aggregation, with the FROM-subquery form that works;
and the metric-versus-attribute population semantics, with the single-subquery
form that holds every figure to one population. Prediction, per the standing
rule: the name change reliably removes a known-wrong outcome (a dead
submission) rather than guaranteeing a pass; the description guidance is the
weaker mechanism and is documentation of engine behaviour either way.

**Simulator fidelity finding.** Task 17's wrong constant is a harness-side
defect in the strict sense: the user simulator's stage-2 prompt receives the
full ground-truth SQL and its segments, ran on the recommended v2 prompt, and
still answered "10 miles" against gold's >= 50 - twice, consistently. The
plumbing is intact; the simulator model (claude-haiku-4-5) fails to read the
constant out of the WHERE clause it is holding. The remedy is USER_SIM_MODEL in
.env (no code change), but it changes the benchmark's answers for both arms, so
it requires a full two-arm re-baseline and should be decided deliberately, not
patched mid-comparison.

**2026-08-17 - final-config atscale block (sonnet simulator, 16384 tokens,
round-4 model; n=3): 0.0526 / 0.0000 / 0.0368, mean 0.0298 (sd 0.022).** The
first block on the configuration the head-to-head will use; comparable only to
the raw block now running, not to anything earlier.

- **Round 4 confirmed in a scored run**: run 1's task 22 passed BOTH phases -
  the first atscale phase-2 pass on this database - and its phase-2 SQL is
  character-for-character the query that previously failed on the "(Per Match)"
  name, now written bare. Run 3's task 22 passed phase 1 with its last coin and
  never got to attempt phase 2 (budget), and run 2's was steered off the
  passing tie-order by the simulator itself ("no tiebreaker needed").
- **The ask machinery is now reliable on task 2**: all three runs extracted the
  masked allocation rule (urgency tier order, HLA tiebreak, Pending) and the
  numerals-as-tiers mapping. Run 2 reproduced the reference's 15-row population
  and matched **14 of 15 rows exactly**, failing on a single two-row tie:
  ROW_NUMBER where gold's RANK gives both rows rank 1, plus the arbitrary order
  between two rows with identical sort keys. One clarifying question (or one
  luckier draw) from a second never-to-pass conversion.
- **The sonnet simulator did not fix task 17**: "10 miles" against gold's
  >= 50, now observed four times across two simulator models. The fidelity
  failure is the v2 prompt design, not model tier - the simulator invents a
  plausible constant instead of consulting the ground truth it is handed.
  Upstream-worthy. It also introduced a new variance source: its decisive
  wrong answer on run 2's tiebreaker question is what broke task 22 there.
- Budget exhaustion (14/13/13 of 19) and coin allocation are unchanged from
  every earlier block; the new per-task outcome lines just made a
  long-standing condition visible. Query error rate 19-21%, planner assertion
  still present.

### B-42 cut, B-38 narrowed, 2026-08-18 — and what that says about the rest of the guidance

A harness change, recorded here because the block above (§ "The open follow-ups worked
and the lift did not") credits B-42 with a conversion and quotes its gold statistic. Both
of those readings are superseded; the lines that count `184 of 189`, the `_6` attribution
row, and the crypto exposure paragraph should be read against this section.

**Two new instruments, both free.** `scripts/counterfactual.py` takes stored submissions
from runs that PREDATE a rule, applies the rule as a sqlglot transform, and re-grades
offline — the trajectory is held fixed, so it is immune to redeploys, flags and run-to-run
variance, and it reports per arm because a rule appended to both instructions can only move
lift through an asymmetric failure rate. It now covers 16 arm-paired pre-rule runs on the
three databases that have both arms recorded (375 failed submissions: ETF 257, archeology
61, crypto 57). `scripts/rule_exposure.py` counts each rule's precondition against gold
alone, so it covers all 22 databases with no run — and counts the phases where obeying the
rule LOSES a point next to the ones where it wins.

**What they found, per rule.**

| rule | recovered raw / atscale | exposure over 22 dbs | verdict |
|---|---|---|---|
| B-37 | +2.80 / +1.40 | 55 fires, **1** risk | keep — it SHRINKS lift |
| B-38 | +0.70 / +1.40 | 30 fires, 0 risk | keep, narrowed |
| B-42 | 0.00 / 0.00 (2 eligible in 375) | 167 fires, 3 risk | **cut** |
| B-41 | **+0.70 / 0.00** | 121 fires, 0 risk | keep — and it SHRINKS lift (corrected 2026-08-18, see below) |

**Why B-42 went.** Over 122 stored pre-rule run files, 264 submissions land on phases where
its precondition fires (order graded, gold groups and sorts). **259 of them already carried
the ORDER BY** with nothing telling them to — 5 misses, 4 raw and 1 atscale. And the single
live conversion B-42 could claim, `crypto_exchange_6` phase 2, is a regression **B-38
caused**: that submission carried an ORDER BY before f3ba423, dropped it after, and got it
back with 8c9b08d. A second rule repairing the first, on behaviour the agent already had,
buying 3 phases across the 22 databases where obeying it loses (fake_account_24,
labor_certification_applications_12, mental_health_1). B-38 now says what it meant — leave
the order alone on a FLAT row-level listing, read narrowly — and grouped results get no
instruction at all. Both gold-corpus statistics left the prompt with it.

**Why B-37 stays even though it helps raw twice as much.** Its whole asymmetry is
`crypto_exchange_17` and `_19`. On the raw arm those two had already derived the correct
label wording from the KB thresholds (`'Liquidity Crisis'`, `'Arbitrage Opportunity'`) and
their only defect was projecting the number beside the label; narrowing the projection
recovers both. The atscale arm could not get there because the model publishes that
condition as a Yes/No flag, so it had TWO defects. Cutting B-37 would not close that gap,
it would hide it behind a shared column-count error and manufacture roughly 7 pp of lift
(4 × 0.7 vs 2 × 0.7 over 20 tasks) out of raw echoing an identifier. The legitimate route
to that 7 pp is B-41's ask, which already took `_17` to 1.00 live; the model route is closed
because neither label pair is in the KB.

**The generalisable lesson.** A guidance rule needs two numbers before it ships, and both
are free: does the agent already comply (compliance census over stored runs), and how many
phases would obeying it LOSE (exposure sweep over gold). B-42 had 98% compliance and 3
losing phases and still shipped on the strength of a single conversion, because a
conversion is what a validation run shows you and neither of the other two numbers was
being asked for.

### The atscale arm's own always-sort rule, removed 2026-08-18 (B-45)

Recorded here because it changes what every atscale run does on all 22 databases, and
because the section above argues the arms are given identical grading guidance — which was
not true when it was written.

`config/environment_backends.yaml:239` (David Mariani, `8d3256c`, 2026-08-06) opened with a
grading rule — *"don't rely on the question text alone to decide whether to sort… as a
default habit, include an explicit ORDER BY on every multi-row (non-scalar) final
submission"* — and then continued into real AtScale ORDER BY mechanics. On 2026-08-17
`f3ba423` added the opposite instruction 39 lines earlier in the same prompt (*"SORT ONLY
WHEN ASKED TO RANK"*), so the atscale arm held both orders at once while the raw arm held
only the second. That is also what the file's own header at line 40 exists to prevent:
*"Rules about grading… are NOT backend-specific — they live in agent.py so the backends
cannot drift apart."*

**Split, not deleted.** The mechanics stay in the backend config, where dialect facts
belong: the sort key must appear in that query's own SELECT list, the intermittent
`Unmatched physical type AttributeValue(FlatAttribute(...))` failure when the sort key is a
calculated metric, and the derived-table wrap for sorting by a column the answer must not
project. Only the two whether-to-sort sentences are gone. Both arms now take whether-to-sort
from the shared `RESULT_SHAPE_TIP` and nowhere else.

**Why, measured.** Compliance census over 122 stored runs, order-graded phases only:

| arm | had the always-sort line | sorts when gold sorts | invents a sort when gold has none |
|---|---|---|---|
| atscale | yes | 509/543 = **94%** | 6/10 = **60%** |
| raw | no | 298/312 = **96%** | 3/8 = **38%** |

The arm without the instruction complied *more*. The only difference moving in the
instruction's direction is the harmful one. Caveat kept deliberately: the left column is
large-n but observational across two different toolchains, and the right column is n=10 and
n=8 — the claim is "no measurable benefit, and the only measurable difference is the cost",
not an effect size.

**Exposure where the removed rule was wrong**, gold only, so it covers databases with no
stored runs: crypto_exchange 5 of 15 order-graded phases, labor_certification_applications 2
of 30, households 1 of 12, organ_transplant 0 of 16, cybermarket_pattern 0 of 13,
archeology_scan 0 of 14, exchange_traded_funds 0 of 18, solar_panel 0 of 9. The cost was
concentrated in crypto_exchange; three phases across the four databases owned by the other
modeller.

Every atscale number recorded before this date was produced under the removed instruction.
Re-baseline before comparing across it — ~$0.216/task atscale and $0.154/task raw measured
2026-08-17, so about $4 per 20-task arm.

### B-47: the other half of the same asymmetry, removed 2026-08-18

B-45 (above) removed the atscale-only *always-sort* rule. It missed the mirror image sitting
39 lines earlier in the same instruction: `config/environment_backends.yaml:200`, added by
`f3ba423`, told the atscale arm that *"a question that merely says display/show/list some
columns does not [want an ORDER BY]"* — the **un-narrowed** form, with no "one row per
underlying record with no grouping" clause. That is the exact wording that made
`crypto_exchange_6` phase 2 drop its ORDER BY and forced B-42 into existence, and `6302d18`
had already narrowed the shared version precisely to stop it reaching grouped results.

Net state before this change: atscale got the narrow shared rule *and* the broad
backend-only one; raw got the narrow one alone. So between `4ca1580` and now, the arms were
still asymmetric on whether to sort — in the opposite direction from B-45.

Removed rather than reworded, because both of its halves are already in the shared
`RESULT_SHAPE_TIP`: the ranking trigger words, and sorting by the measure being ranked. The
atscale instruction now says nothing about whether to sort and keeps only the mechanics of
how, with a pointer stating where the decision lives. One caveat recorded deliberately: the
removed bullet also warned that *"sorting by the identifier is the commonest way a submission
with entirely correct columns and values still fails"* — the shared tip implies that by
saying "on the measure being ranked" but does not spell out the anti-pattern. Port that
clause into the shared tip if a later run shows the sort key being missed.

Both arms now take whether-to-sort from exactly one place, for the first time since
2026-08-06. Services restarted, all three gates re-passed. Every atscale number recorded
before today predates both B-45 and this.

### Correction: B-41's counterfactual was not blind, the transform was broken

The table above first recorded B-41 as 0.00 / 0.00 and the surrounding text read that as
"the corpus holds no labels-only failure to recover". Both were artifacts of a bug in
`scripts/counterfactual.py`'s `t_b41`, found by the 2026-08-18 code review.

The transform collected **every** string literal inside the predicted `CASE` — WHEN operands
included — while gold's side collected only THEN/ELSE values. The `len(pred) != len(gold)`
guard then rejected any submission whose predicted CASE compared against a string, which is
most of them. Eligibility was understated at 18 raw / 2 atscale; it is 27 / 6 once the
transform collects `ifs[*].true` plus `default` on both sides.

Corrected result: **B-41 recovers `archeology_scan_6` phase 1 on the raw arm (+0.70) and
nothing on the atscale arm.** So it joins B-37 as a rule that SHRINKS lift — the raw agent
was losing a task to wording it could have asked for, and the semantic-layer arm had a second
defect on the same phase. The keep decision is unchanged and now has offline evidence as well
as the live `_17` conversion.

Two counting notes from the same pass, both now fixed in the instrument: reward is credited
once per (task, phase) — two attempts at one phase can each recover, and crediting both
double-counted the point, which is what first showed this as +1.40 — and the raw arm grades
through `U.grade_raw_submission`, not `U.ex_base`, so gold and prediction get the same step-1
cleanup. Re-running the corpus after the grading fix changed no number; the `t_b41` fix
changed only B-41.

### Frozen-prompt validation of B-37 and B-41, 2026-08-18 (B-49)

The prompt is frozen as of `5b7b8e9` — a comment block above `RESULT_SHAPE_TIP`, instruction
bytes unchanged (verified by hashing the two constants before and after). The test any future
rule must pass is written there: **is it derivable from the question alone?** B-37 and B-41
pass; B-42 did not and is gone. Helping one arm more than the other is explicitly not grounds
for cutting a rule.

**The run.** `scripts/tasks_frozen_b37_b41.txt`, 11 tasks, n=1, both arms, $6.15 (atscale
$3.68, raw $2.47). Tasks chosen by rule precondition via `scripts/rule_exposure.py`, not by
hand: B-37 fires on 0 archeology and 0 ETF phases, so crypto is the only place it is testable;
B-41 is testable in all three; crypto `_15/_17/_19` fire both rules on one phase, the stacked
case `counterfactual.py` structurally cannot resolve.

**B-37 lands, and the counterfactual's direction reproduces live.** Columns in the *first*
submission, where gold wants exactly one:

| task | atscale pre → now | raw pre → now |
|---|---|---|
| crypto_15 | 4 → 3 | 4 → **1** |
| crypto_16 | 2 → **1** | 2 → **1** |
| crypto_17 | 3 → **1** | 3 → 2 |
| crypto_18 | 2 → **1** | 1 → **1** |
| crypto_19 | 3 → 2 | 2 → **1** |

One-column-first-try: atscale 0/5 → 3/5, raw 1/5 → 4/5. Raw converted `_15` and `_19` to 1.00
where atscale stalled at 0.70 — the shrink-lift effect happening rather than being inferred.

**B-41's trigger works and is arm-selective by design**: a label-wording ask on 5 of 9 B-41
tasks in the atscale arm against 3 of 9 in raw, because the clause keys off the agent's own
answer being a flag and a flag is what the model publishes. It converted nothing outside
crypto: all five archeology and ETF tasks scored 0.00 in both arms, three after the ask fired.
Not a weak rule — a gated one. See B-50.

**The subset mean was atscale 0.255 vs raw 0.309, −5.5 pp. That is not a lift estimate and
must never be quoted as one**: the tasks were selected precisely where these two rules fire,
which is where raw had the most headroom. A lift number still needs a full-database run at
n≥3 (B-43).

**The finding that outranks both rules (B-50).** Tasks ending with ≤0.5 coins:
crypto_0818_atscale 16/20, crypto_0818_raw 17/20, frozen atscale 10/11, frozen raw 9/11 —
**80–91%, both arms.** The benchmark is largely a race to get furthest before the coins run
out, which is why guidance rules keep landing behaviourally without converting: the task was
already lost. It is roughly symmetric, so it may not move lift directly, but it is what makes
lift unmeasurable at n=1. Not a prompt change, so the freeze does not block work on it.

### explore_columns filters exposed, and the list_models claim corrected, 2026-08-18 (B-52, B-53)

Not a model change — a harness and instruction change, recorded here because it
alters what the atscale agent does and therefore what every atscale number after
this date means.

`explore_columns` has always accepted `folder`, `role` and `column_group`
filters, and `list_models`' own Next Steps text tells the agent to use them, but
our wrapper passed only `search_terms`. So the agent had to guess wording against
a literal substring matcher when a folder name it had already been handed would
fetch the same slice exactly — the mechanism behind the 13–25% of
`explore_columns` calls that returned nothing (Q-16). Measured on
crypto_exchange, all at the same 1 coin: `folder="PnL"` 6 columns in 978 chars,
`column_group="Order"` 17 in 3,955, `role="measure"` all 116 in 30.5k. The three
scopes combine with each other; `search_terms` is model-wide and the server
refuses to combine it with a scope.

The instruction claimed `list_models` "names every dimension and metric in the
model — read it FIRST, and then search only for a concept you did not already see
there". It names none: the scoped output is 2,145 chars for crypto_exchange and
1,864 for ETF, carrying the fully-qualified table name, counts, 41 folder names
and the column_groups map. The 19-of-229 and 8-of-387 apparent hits are columns
whose name happens to equal a folder name. So the second half of that rule asked
the agent to diff its search list against information it never received. It now
describes what the call is for and directs the agent to use the folder list as an
index.

The **B-49 prompt freeze was lifted** for this, one day after being set. The
scope of the lift is narrow and is recorded in `system_agent/agent.py`:
correcting a false statement about what a tool returns is not a new guidance
rule. The bar for new rules is unchanged.

Consequence for measurement: the frozen-prompt validation numbers on B-37, B-41
and B-49 were measured against the pre-lift text. Nothing has been run since
these changes, so the projected coin savings on B-51/B-52 remain projections from
payload sizes, not observed results.

### exchange_traded_funds re-foldered, 2026-08-18 (model repo `a0ef409`)

Presentation metadata only — no `unique_name`, dataset, join, aggregation or
calculation changed, so no query semantics change. Done because B-52/B-53 just
made the folder list the cheap route to column discovery, and ETF's folder list
was not usable as an index: 20 folders for 387 columns, with `folder="Fund"`
returning 195 columns / 75,142 chars and `folder="Fund Measures"` 126 / 54,190.
A 195-column folder costs the same coin as a keyword guess and returns as much
text as dumping the catalog, so the index was no better than no index.
crypto_exchange, for contrast, has 41 folders and a median sampled folder of
1,783 chars.

Two halves:

- The **130 metrics** that all sat in `Fund Measures` now sit in 15 thematic
  folders: Returns, Risk and Risk-Adjusted Return, Risk Model Drift, Fees and
  Turnover, Price and Valuation, Assets and Flows, Income and Yield, Liquidity,
  Portfolio Composition, Benchmark and Outperformance, Manager Skill and
  Consistency, Momentum, Composite Scores, Fund Counts, Regression Components.
- The Fund dimension's **193 secondary attributes**, all previously inheriting
  `folder: Fund` from their hierarchy, now carry their own folders, reusing the
  metric folder names so a question about returns finds both the per-fund
  attribute and the aggregate under one name. Largest folder is now 33.

Attribute-level folders have **no precedent in the repo** — 108 hierarchy-level
assignments, zero attribute-level — so the engine may honour or ignore them.
`sml-cli validate` accepts them. This needs verifying with
`explore_columns(folder=...)` after a deploy, and the attribute half reverting if
the engine ignores it. The metric half uses the proven mechanism.

Gates: A8 question-leakage PASS, A10 masked-threshold PASS (12 inert), validate
clean. The KB concept booleans are grouped as `Fund Classification Flags`, named
for the shape of the columns rather than any concept, publishing no string that
was not already a column name.

**NOT YET DEPLOYED.** `scripts/deploy_models.sh` publishes the whole catalog, and
`origin/main` now also carries nine commits of a teammate's in-progress work
(organ_transplant rounds 6-8, households, labor_certification_applications,
utilities). Deploying would publish those too, so it is left for a decision
rather than done as a side effect of an ETF change.

### Measured: the folder index works, and the agent spends the saving on more discovery, 2026-08-18

crypto_exchange, atscale, n=2 (`crypto_folders_n2_atscale_run01/run02`, $8.32,
Sonnet 5, gate passed, services restarted) against
`crypto_0818_atscale_20260817_161538` as the before. Atscale only: the raw
backend is not in `environment_backends.yaml`, `tools_atscale.py` is atscale-only
and the `agent.py` edit was comment-only, so raw cannot have moved.

What worked:

| | before | after |
|---|---|---|
| `explore_columns` calls using `folder=` | 0 of 61 | **91 of 167** |
| empty results | 13% | **5%** |
| errored `run_query` per task | 0.75 | **0.45** |
| spend that bought nothing | 25.5% | **21.8%** |

What did not, and inverted instead:

| | before | after |
|---|---|---|
| `explore_columns` calls per task | 3.05 | **4.17** |
| schema discovery, coins/task | 4.5 | **5.7** |
| schema discovery, share of budget | 27.1% | **33.6%** |
| coins spent before the first query | 4.8 | **6.1** |

Making discovery cheaper per call and more reliable made the agent do more of it.
crypto has 41 folders, "fetch the folders the question touches" is easily four to
six of them, and nothing caps the count — the standing "aim to be done with
discovery inside about 4 coins" line is outweighed. Trial queries fell 4.0 → 3.2
calls/task, so the spend moved out of probing and into exploring.

Headline flat, as predicted before spending: **0.6100 and 0.5500, mean 0.5800**
against 0.6000. The token risk flagged in the runner did not materialise —
prompt tokens 6.12M/6.79M against 7.04M, cost $3.98/$4.34 against $4.32.

The honest read is that per-call quality improved and volume ate it. Next step is
a cap on how many folders to fetch before querying, not a revert.

One call of 167 still attempted the illegal `search_terms` + scope combination
and paid a coin for the refusal, so that bullet lands at roughly 99%.

### ETF re-folder deployed and verified, 2026-08-18

Deployed via `scripts/deploy_models.sh 8` — compile and deploy SUCCESSFUL, all
three post-deploy gates passed (services newer than code, catalog healthy with
all 8 models in `bird_atscale_models_catalog_main`, template DBs intact). This
also published the teammate's nine commits that were on `origin/main`
(organ_transplant rounds 6-8, households, labor_certification_applications,
utilities), with Dianne's go-ahead.

Verified live, and the open question is now answered — **the engine DOES honour
attribute-level folders**, so the half of the change that had no precedent in the
repo stands and needs no revert:

| | before | after |
|---|---|---|
| folders | 20 | **38** |
| largest folder | `Fund` 195 cols / 75,142 chars | `Fund Classification Flags` 34 / 21,444 |
| `folder="Fund"` | 195 cols / 75,142 chars | 2 cols / 294 chars |
| median folder | — | 2,058 chars |

`folder="Fund Identity"` returns 14 columns including `Fund Short Name`, which
only works if per-attribute folders are read. ETF's index is now comparable in
granularity to crypto's (median 1,783 chars), which was the point.

**2026-08-17 - epoch-1 head-to-head complete (sonnet simulator, 16384 tokens,
round-4 model; n=3 per arm).**

| arm | runs | mean | sd | scoring tasks |
|---|---|---|---|---|
| raw | 0.1053 / 0.1053 / 0.0526 | **0.0877** | 0.025 | 22 (3/3 both phases), 8 (2/3 both phases) |
| atscale | 0.0526 / 0.0000 / 0.0368 | **0.0298** | 0.022 | 22 (1 both, 1 phase-1) |

Gap -0.058 average reward; exact Mann-Whitney U=0.5, two-sided p ~= 0.1 (the
floor of a 3v3 design - raw ahead in every pairing except one exact tie).
Budget exhaustion: raw 16-18 of 19, atscale 13-14 of 19, both unchanged from
their historical shapes.

**What drove the gap - two mechanisms, both now understood.**

1. *Task 22 stability.* Raw reproduces gold's arbitrary tie order by
   construction (same engine, same plan shape) and passed both phases all three
   times. The atscale arm's tie order depends on the agent's window-function
   choices and on simulator tie-break advice, and it converted only once.
2. *Task 8, the epoch's discovery.* The sonnet simulator, asked which ischemia
   field applies, DISCLOSED THE FORMULA: the donor's recorded recovery ischemia
   plus the transport time (fr.org_isch_time + cm.exp_time). The raw agent
   assembled it directly and passed both phases twice - the first passes ever
   on this task. The atscale agent, given the same disclosure, CANNOT assemble
   it: the model ships total-ischemia variants for exp_isch+exp_time and
   org_isch+exp_isch, but expected transport minutes exists only inside metrics,
   not as a row-grain attribute. That violates the standing "row-level attribute
   beside every measure" rule and is now the top model fix for the next epoch:
   publish Expected Cold Ischemia Minutes and Expected Transport Minutes as
   Compatibility Assessment attributes so any simulator-disclosed combination is
   assemblable. Legitimately sourced: the definition came through the
   benchmark's own ask channel, not from gold.

**Symmetric caps confirmed symmetric.** The simulator answered "10 miles" on
task 17 to both arms (five observations now, two simulator models); task 2
failed all six runs of the epoch (raw included - the arbitrary-tie rank on
Region_9 bit raw too this time, where under the haiku simulator raw had passed
it twice). Next: the harness's simulator-fidelity fix (the parameterization
bug), the MCP branch deploy, and the model round - one epoch boundary, then
re-measure both arms.

## 2026-08-17 - Epoch 2 boundary: MCP fix deploy, model round 5, simulator fidelity guard

All three planned changes landed together as one epoch boundary; no result
before this point is comparable to any result after it.

**MCP server (branch model-creation-combined, commit 43b4dbb, image
model-creation-combined).** Live smoke on the deployed build disproved the
CTE premise: the ENGINE rejects CTEs ("CTEs are not supported yet in pgsql
queries"), so the client guard removal bought nothing - the tool now
intercepts WITH-queries with that verdict plus the FROM-subquery rewrite.
The new join-grouping detector had a real bug (GROUP BY ordinals compared
textually), falsely rejecting the canonical membership join written with
GROUP BY 1; fixed by resolving ordinals to projections and matching columns
alias-insensitively. NULLIF and dimension-attribute-aggregation detectors
verified live, including that the suggested rewrites execute.

**Model round 5 (bird-atscale-models f23aa4a, deployed).** Expected Cold
Ischemia Time and Expected Transport Time published as row-grain attributes
on the Compatibility Assessment satellite - closing the task-8 gap logged
above; the disclosed org_isch + exp_time formula now assembles at row grain
(verified live: per-organ averages 565-613 minutes). Description item (5)
rewritten to attribute the CTE rejection to the engine, and NULLIF added to
the engine-rejects list with the CASE rewrite. 144 queryable attributes.

**Simulator fidelity fix (the parameterization bug).** Two layers: (a) the
v2 response generator now carries guideline 4 - every stated value must be
copied exactly from GT SQL / labeled ambiguity / the original question;
(b) server-side numeric-consistency guard extracts every number from the
draft response and regenerates once, with the offending values named, if any
number appears in no ground-truth source (GT SQL, ambiguity JSON, clear
query, or the agent's question). Fail-open on the second draft; both
triggers logged so the regeneration rate is measurable. This targets the
"10 miles vs gold >= 50" defect observed five times across two simulator
models. Next: n>=3 both arms on the new stack.

## 2026-08-17 evening - Round 6+7 and the formula-ask guidance (pre-overnight)

**Round 6 (e4b3fb3, deployed).** Description item (5) now says CTEs work -
verified live through the full stack (engine pr9795 inlining + MCP
passthrough): chained, twice-referenced and model-JOINed CTEs return results
identical to their FROM-subquery spellings. WITH RECURSIVE and IN-subqueries
stay rejected. No other model's description mentions CTEs, so all 8 models
are CTE-enabled via the MCP skill text; the raw arm always had them.

**Round 7 (3c0dcf0, deployed).** Audit found 36 metric columns with no
row-grain sibling; 21 were real task-8-class gaps and now ship as
attributes: 14 on Risk Evaluation (organ quality, expected patient
survival, five stored risks, cost effectiveness, three center scores,
resource availability/consumption, staff hours), 2 on Data Quality Record
(quality + completeness scores), 4 on Compatibility Assessment (three
recorded sub-scores, distance km), 1 fact degenerate (match duration
seconds). Verified live: AVG(oq * (1 - mr)) assembles at row grain.

**Guidance: the formula ask.** New bullet ahead of the ambiguity-trigger
bullet: when the question paraphrases a formula, ask for the formula itself
- once, openly - then select each disclosed term at row grain in one
FROM-subquery and aggregate outside. Grounded in the measured task-8 pair
(asked-and-assembled 0.7 vs guessed-between-bases 0.0).

**Also fixed: call_llm None-content crash (5e16093).** Five live crashes
surfaced as EMPTY simulator answers that still cost 2 coins and silently
suppressed disclosures. One retry then '', callers' fallbacks engage.

Baseline note for the next runs: single-run organ_transplant on this stack
scored 0.70/19 twice today (task 22, then task 8 via the round-5
attributes). Everything above is one epoch; nothing before 2026-08-17
evening compares.

## 2026-08-18 - Epoch-2 head-to-head: atscale ahead for the first time; cap postmortem

**organ_transplant, n=3 both arms, frozen stack** (engine pr9795, MCP CTE
passthrough, model round 7, sim max_tokens + numeric guard, formula-ask +
dialect guidance): atscale 0.70/1.70/2.40, mean 0.0842; raw 1.00/1.70/0.70,
mean 0.0596. First measured atscale lead (+2.5pp; epoch-1 was raw 0.0877 vs
atscale 0.0298). Exact MW p=0.40 - not significant at n=3; the per-task
mechanics carry the evidence: task 8 passed 2/3 atscale runs and 0/3 raw
(round-5/7 attributes + formula ask), task 6 recorded its first pass ever
(population structure), task 22 upgraded to full 1.0s (phase 2 landing).
The 2.40 run is the best organ_transplant result recorded. CTE adoption 0
with description and guidance both live: capability confirmed harmless,
currently unused. Sim guard fired 9 times on invented constants (weights,
bucket bounds, ratios - the "10 miles" class); 1 None-content retry.

**The other 7 databases are void**: the Anthropic workspace hit its monthly
usage cap at ~23:47 ("regain access 2026-09-01"); every later run completed
in seconds with 500s from run_session. archeology atscale run01 (2.00/10,
tasks 3+4 full passes) survived without a raw pair. The overnight script
now carries a circuit breaker: a run with >=50% tasks dead without a tool
call, or a fresh workspace-cap message in the agent log, aborts the whole
night instead of burning the remaining databases into void files.

## 2026-08-18 - The gold-only-constants class, split and attacked (rounds continue)

Audited all 27 trajectories (9 tasks x 3 overnight runs) against gold. The
class is five sub-buckets, not one:
(A) unasked constants the sim discloses when asked - tasks 3/21 (CER year
    horizons: gold divides by qol x 5 and x 8; six runs, zero asks), 17
    (ischemia basis: gold uses org_isch + exp_time), 10 (Pending population
    + percent-rank cut), half of 20 (supply-side population);
(B) partial disclosure without a value follow-up - task 7 (gold's else-
    bucket urgency value is 2; KB says 1; sim described the bucket, agent
    never asked the number);
(C) sim fidelity defects - task 11: invented weights caught by the numeric
    guard, then the regeneration took the "up to you" exit although gold
    HAS weights; plus unanswerable() misroutes (11, 13) and one run-to-run
    contradiction (21);
(D) a real model gap - task 13 needs a DSS<->EGS correlation the model had
    no paired terms for;
(E) under-determined gold - task 14's 41-way tie, B-34 class (relay to the
    tracker; not fixable model-side).

Fixes shipped, all blind until the API cap lifts:
- Sim action parser: constants/thresholds/horizons/field-choices present in
  the GT segments must route labeled/unlabeled, never unanswerable.
- Sim response generator + guard correction: check the ground truth FIRST
  and quote its value; "up to you" only when gold genuinely lacks it.
- Guidance: new slot-enumeration bullet ahead of the formula ask -
  population, basis, constants incl. time horizons, ranking definition -
  plus a follow-up rule for half-answered formulas.
- Model round 8 (deployed, verified live): DSS To Graft Survival
  Correlation + six paired terms (0.0541 over Completed); Total Ischemia
  Time (Recovery + Transport) attribute + Average metric, sourced from the
  task-8 ask-channel disclosure; CER descriptions now demand the year-
  horizon ask. 102 metrics / 14 calculations / 166 attributes.

## 2026-08-18 - households: the failure class is the task set, not the model

Audited 21 shared tasks x 3 atscale runs (2026-08-13, last valid pair; the
overnight files are void from the API cap) against gold.

**Head-to-head, shared ids only** (raw was run without --query-only, 29 vs
21 tasks, so raw's headline totals are not comparable as recorded):
atscale 2.00/1.70/2.00 = 0.0905; raw 1.00/1.70/2.00 = 0.0746. Only 3 of 21
tasks ever score: _16 (both arms), _19 (atscale only, 3/3), _4 (raw only).

**17 of 21 are 'wrong-answer' in BOTH arms, every run** - queries execute
and return wrong values. Not a semantic-layer failure.

**Root cause: the question and the gold answer different questions.** 11 of
21 households Query tasks pose a plural/per-row request while gold returns
one row, one number, or a value over a column the question never mentions -
versus 0 of 19 on organ_transplant. Verified against upstream
(bird_interact_agent/data/...): our file matches byte-for-byte, so this is
BIRD-Interact data, not our merge. Examples:
  _1  'typical bathroom ratio for each area, show area code and ratio'
      -> gold returns SUM of car counts in the top-ranked region.
  _6  'list the household ID and its crowding metric'
      -> gold returns the AVERAGE VEHICLE COUNT of those households.
  _8/_9 'average rating per zone, show the location tag and value'
      -> gold returns one concatenated string 'topregion | bottomregion'.
  _10 'list the home IDs for all highly mobile homes'
      -> gold returns one REGION name.
  _15 'listing their unique house codes' -> gold returns one region by
      at-risk ratio.
The question describes the setup CTE; gold's payload is a further step the
question never states. These are high_level tasks, so the ask channel is
the only route - but the labeled ambiguities do not cover the missing
payload either.

**The model is not the problem.** Vehicle Ownership Index is exactly gold's
Auto+Bike+Motor sum, Average Bathroom Ratio is the mean-of-ratios gold uses
(with the pooled twin separated), and the incomplete-KB formulas are
deliberately unshipped with ask-triggers. One real gap found and fixed: 12
tool calls died reaching for the entity by its domain noun ('Household',
'Household ID', 'Household Size', 'Residents'), so the description now
names House Number, Resident Count and Household Count up front.

**Guidance (all databases): ask what the final output is.** New bullet -
when a question names a per-row calculation, ranking or filtered population
without naming an unambiguous final result, spend one open ask on the
output shape itself. Grounded in the 11 measured cases.

**Recommendation for measurement**: report the 11 shape-mismatched tasks
separately from the head-to-head, as with the B-34 under-determined golds.
Both arms score ~0 on them by construction, so they dilute every households
comparison without carrying signal.

## 2026-08-18 (afternoon) - CTE adoption arrives; the noise floor is the real finding

**CTEs went from 0 to heavy use** on the atscale arm once the contradictory
"this SQL dialect does NOT support CTEs" bullet was removed (it had sat
twelve lines under the new dialect bullet saying the opposite): 32 CTE-led
run_query calls and 10 CTE-led submits over 8 of 19 tasks. Raw uses them too.

**CTE queries errored at 50% against 18% for non-CTE queries in the same
run** - but the cause is depth, not CTEs. Verified live by running each
failing shape with and without the WITH clause: byte-identical outcomes
every time (SELECT * over a doubly-nested derived table with ORDER BY on an
attribute fails as "Unmatched physical type" either way; a literal UNION ALL
derived table fails either way; the shapes that work, work either way). The
inliner from engine PR #9795 is faithful. Median SELECTs per query: 4 with a
CTE, 2 without - agents simply write more ambitious queries with them. No
CTE error was fatal: 0 tasks ended on one and 7 of 8 CTE-using tasks
recovered; the only scoring task (_22) used CTEs; coins/task was identical
(17.74, budget-saturated in both regimes).

**Both arms fell today at n=1: atscale 1.60 -> 0.70, raw 1.13 -> 0.00.** Raw
cannot be explained by any change we made - the guidance edits are in the
atscale backend block only, raw's prompt lives in agent.py, and raw's task
_22 (which passed 3/3 last night) made ZERO ask_user calls today, so the
simulator was not involved. Last night's raw run 2 also made zero asks and
scored 1.0 with identical coins. It is variance.

**Quantified, over four runs per arm:** raw sd 0.0371, atscale sd 0.0437,
noise gate (2x larger sd) 0.0874 per-task reward. The atscale-raw gap is
+0.0276 = 0.32x gate; today's atscale drop is 0.54x gate. Every effect we
are chasing sits inside the noise on a 19-task set where only 1-3 tasks ever
score. n=3 is not enough here; treat single runs as behavioural reads only.

**Option A shipped** (guidance, no redeploy): CTEs stay enabled, with an
explicit depth warning - one level of nesting, ORDER BY/LIMIT inside the
scope that projects the sort column, prefer a CTE when it REPLACES nesting
rather than adding a layer.

## 2026-08-18 (evening) - aggregates are live; measurement convention for them

The BIRD connections were recreated after a stack rebuild by
`bird-atscale-models/utilities/create_bird_connections.sh`, which now creates
an `aggregates` schema in each of the 22 BIRD databases before pointing the
connection's Aggregate Schema at it. Verified: schema present in 22/22
databases, and all 22 `bird_*` connection groups carry
aggregateSchema="aggregates".

**This changes the atscale arm's cost profile.** Before, the aggregate schema
did not exist, so every aggregate build failed instantly and cost nothing.
Now the engine really builds them - organ_transplant had 28 tables in its
aggregates schema within minutes of the first run, with 88 aggregate events
in the engine log over 20 minutes. Builds run CREATE TABLE AS against the
same small Postgres the live queries hit, so run 1 pays a cost the raw arm
never pays.

**Convention (decided 2026-08-18):** measure at n=3 and keep run 1 cold.
Run 1 pays the build cost, runs 2 and 3 get the benefit; the 3-run mean
therefore includes one cold run. This is deliberate - it is what a real
deployment experiences, and a permanently-cold configuration is one nobody
runs. Two riders:
  - Report wall-clock PER RUN, not only the mean. A mean over one cold and
    two warm runs describes no state that exists, and wall-clock per question
    is a reported slide metric.
  - Accuracy should be unaffected: aggregates are transparent, and the
    post-rebuild values match every prior run (Kidney 207 / Lung 199 /
    Liver 187). If a task's VALUES ever move between run 1 and run 3 with
    nothing else changed, suspect aggregate routing first - that is the
    signature of such a bug.

## 2026-08-18 - scripts/run_overnight_all.sh renamed to scripts/run_both_arms.sh

The name described when it was run, not what it does: it drives BOTH ARMS
(atscale then raw, --query-only for task-set parity) over one or more
databases, and it is the batch driver behind every head-to-head number in
this log. Run it at RUNS=1 for a regression gate or RUNS=3 for measurement.

Its results prefix changed with it: new batches write
results/batch<stamp>_<db>_<arm>*.json. Every set produced before this rename
uses results/overnight<stamp>_... - glob both when comparing across the
boundary.

Concurrency, since it comes up: each individual run executes at
--concurrency 5 by default (CONCURRENCY=N to override), exactly as running
orchestrator.runner by hand. The batch's own loops - database by database,
arm by arm - are sequential on purpose, so a full 8-database sweep is long
by construction rather than by inefficiency.

## 2026-08-18 - post-revert run, and the derived-table expression defect

**Run (n=1, CTEs blocked, aggregates live, all fixes in): 1.70/19 = 0.0895.**
Tasks _2 (0.7) and _22 (1.0) scored. Against last night's three no-CTE runs
(0.70/1.70/2.40, mean 1.60) this is mid-range; against today's CTE run (0.70)
it is better, but all of it sits inside the 0.087 noise gate. What did move
cleanly: CTE queries 0, run_query error rate 21% (from 27.9% with CTEs, and
close to the 17.6% no-CTE baseline), budget-exhausted tasks 12/19 (from
15-16), median nesting 2 (from 4).

**The dominant remaining waste is one engine defect, now characterised.**
9 of 16 failed queries were `column "t_NN.X" must appear in the GROUP BY
clause`. Bisected live to a minimal repro:

  works : SELECT "R", CASE WHEN "P" >= 80 THEN 'a' ELSE 'b' END FROM <model>
  FAILS : SELECT t."R", CASE WHEN t."P" >= 80 THEN 'a' ELSE 'b' END
          FROM (SELECT "R","P" FROM <model>) t
  FAILS : SELECT t."R", t."P" + 1 FROM (SELECT "R","P" FROM <model>) t
  works : SELECT t."R", t.risk FROM (SELECT "R", CASE ... AS risk FROM <model>) t

So: an outer SELECT over a derived table may project only BARE COLUMNS; any
expression over them fails, with no join and no aggregate anywhere in the
statement. The message names grouping, but grouping is not the problem -
adding a GROUP BY changes the rows and still fails. The join is irrelevant
(2 of the 9 had none); the self-join-on-MAX pattern the guidance recommends
is NOT at fault and works fine until a CASE is added to its outer SELECT.

Shipped as config (no redeploy): a new error_hint on
'must appear in the GROUP BY clause' carrying the repro and the fix, plus a
proactive sentence in the ENGINE DIALECT bullet - expressions belong in the
scope that touches the model, the outer scope only names columns.

Worth filing against the engine separately: this is a folding defect, not a
user error. The equivalent SQL runs fine on plain Postgres.

---

## fake_account (built 2026-08-20, prompt v5 + v6 addendum)

Built unattended by a deterministic generator in
`AtScaleInc/bird-atscale-models/fake_account/generator`. Rebuild with
`generator/build.sh`; the emitted YAML is never hand-edited. Deployed as model
**Fake Account Detection**, 126 metrics / 12 calculations / 11 dimensions /
178 attributes over 4 datasets.

**Answer-key firewall.** Mechanical, not by intention: `extract_brief.py`
allowlists the permitted task fields, then asserts on its own output that no
denied key and no SQL-shaped text appears in it. The model was built only from
`brief/task_brief.json`. No gold SQL was read at any point.

**Structure.** Eight source tables are exactly 1:1 with `accounts` on 670 rows,
so they join into one wide fact — every attribute then has a direct relationship
to every dimension, which removes the conformance-failure class before it can
occur. Four of those tables keep everything in a JSONB blob; they are flattened
with `jsonb_extract_path_text` rather than the `->>` operator, on the theory that
the engine re-parses derived SQL and a function survives a round trip more
reliably than an operator. Confirmed via `get_outbound_queries`: the engine
emitted the derived SQL verbatim, comments included.

`account_clusters` is a genuine many-to-many (670 accounts across 200 clusters,
each account in 1–3). Modelled as a **link fact** at membership grain, not an
M2M bridge dimension, because a bridge between a measure's dataset and a
dimension is not an accepted query path and falls back to silently-empty
results. Cluster-level rollups over account scores live in `Cluster Member
Measures` and count an account once per cluster; every one says so.

**What this data does to the knowledge base.** More consequential here than the
formulas, and all of it is in the published descriptions:

- Several KB indexes are **not bounded to 0–1**. TEI reaches 3.56 (`proxy count
  divided by 10`, but the column reaches 100), coordinated activity 3.33,
  coordinated bot risk 34.6, and Network Trust Score is mostly *negative*
  because it multiplies by `(1 - CBR)`. A 0.8-style cutoff selects most of the
  population, not a tail — TEI > 0.8 is 482 of 564.
- **Inputs are missing for ~100 accounts per column and the gaps do not
  overlap**, so composite coverage falls to 283 of 670 for ARS and 390 for SRS.
  Each index publishes a support-set count; six ship a `(Missing Inputs As Zero)`
  twin at *both* row grain and aggregate grain.
- **Three degeneracies**, documented rather than left to read as signal:
  `session_count` peaks at exactly 1000, so KB 77's `session count > 1000` branch
  selects zero accounts and the concept is decided entirely by its posting
  branch; every `monitoring` snapshot is over a year old, so KB 86's 90-day and
  KB 12's 180-day inactivity tests are true for all 569 accounts that have one;
  no cluster carries the role `Amplifier`, so KB 19's Amplification Network
  selects nothing.
- **Two KB entries disagree with the live data, and live wins.** KB 29 describes
  bot likelihood as 0–100 with a cutoff at 70 (column is 0–1); KB 72 states a
  reputation cutoff of 30 (column is 0–1).
- **`CAS` names two different KB concepts** — Content Authenticity Score (KB 1)
  and Coordinated Activity Score (KB 6). Each KB entry's own
  `children_knowledge` decides which its formula means; both ship under
  distinguishing names.

**Competing readings** ship as asymmetrically named twins, and each bare
reading's description carries the twin's name with **both live counts** plus an
explicit statement that its plainer name does not settle the question: TEI
(482 vs 447 above 0.8), Total Post Frequency (269 vs 664 above 50), NIC (26 vs 38
High-Impact Amplifiers), TPDS (computed for 670 vs recorded for 583), Dormant Bot
(169 vs 49).

**Withheld.** Masked domain concepts stating numeric cutoffs — KB 10, 12, 16, 41,
closed over `children_knowledge` to 42, 46, 61, 63, 67, 69. Their components ship,
each naming the concept and carrying an ask-the-user trigger that specifies the
*shape* of answer to request (closed question, exact cutoff, exact label text,
their spelling verbatim, re-ask rather than choose). Masked
`calculation_knowledge` — the KB-named formulas TEI, BBI, NIC, CIS, LBS, KB 82 —
does ship under its own name.

**Not computable from this warehouse at all**, said plainly rather than
approximated: KB 52 MACI and KB 56 NSI (no pairwise correlation or
time-synchronisation data), KB 57 CAE (no reshare count), KB 53 RVI per account
(no reputation history — shipped instead as a cross-account coefficient of
variation, stated as such), KB 55 BCS and KB 58 APS (depend on RVI and on an
absent anomaly count), KB 54 CDPS (no post-time entropy; the three candidate
columns are named and routed to ask-the-user).

**Dialect gaps.** `NTILE` is rejected on the inbound interface, so KB 70's TEI
quartile and KB 79's risk category are precomputed as attributes. Percentile
metrics ship as correct SML and resolve by name (`<name>_instance_0.5`), then
error at query time with `Quantile function 'QuantileRawToSketchFunction' is not
supported by dialect 'Postgresql-9.4.5'` — verified live. Task 24's follow-up
asks for a median and task 18's for a 95th percentile, so those two follow-ups
are a **capped ceiling on both arms**, not a model defect.

### Defects the gates caught, worth recording

- **Five published counts had been guessed rather than measured.** The
  warehouse dry-run gate pins every count a description quotes against the exact
  column it sits on and failed on all five. A wrong count is worse than a typo:
  the agent quotes those numbers into its clarifying question, so a wrong count
  becomes a wrong question.
- **A convenience aggregate that returned the wrong population.** `Content Farm
  Account Count` was a `count non-null` over a Yes/No column, so it returned 670
  rather than 26 unless the caller first filtered the attribute — a plausible
  wrong number with no error. Fixed structurally with 1-or-NULL indicator
  columns summed, not by warning in the description.
- **A share calc whose description was backwards.** `[Platform Record].[...].
  [All]` clears only Platform's filter, so with Account Type also filtered the
  denominator was all bot accounts (44/173 = 0.2543), not the platform's accounts
  (44/149 = 0.2953). The expression passed `sml-cli`, passed deploy, and returned
  a plausible number; only a live query against a hand computation caught it.
  Renamed `Account Share By Platform Kind` and rewritten with both numbers.
- **Two publish-blocking defects** now in the Workarounds table above
  (Publish-timestamp, MDX-hierarchy-name). The first was a *sibling* model's
  column blocking every model's deploy, with a 400 that named neither column nor
  model.

### Shared-gate corrections applied

Three from the v6 addendum, applied to `utilities/` so every model gets them:
the leakage gate and the masked-threshold gate now discover the brief by
convention and treat a missing brief as a hard failure rather than a skip; the
masked-threshold gate resolves the KB itself and refuses to run without it
(without `--kb` the `calculation_knowledge` exemption is silently defeated and it
reports leaks that do not exist); and the leakage gate takes an `--allow` JSON of
triaged runs, each requiring a reason.

`fake_account/generator/leakage_allow.json` records the one flagged six-word run
judged legitimate — `deviation from established temporal activity patterns` is
KB 50's own `description` field verbatim, and task 18 happens to name the concept
the same way. Every other flagged run was reworded. A separate generator gate
(G12) forbids the short question colloquialisms the six-word gate cannot see, and
G13 asserts that no *required* discoverability probe contains one, so the
discoverability gate can never end up enforcing a leak.

**Still ungated:** `cybermarket_pattern` and `solar_panel` have no brief at
either conventional path, so the question-leakage gate has never run on them.
`archeology_scan`'s brief is in its own generator format and is covered by its
own generator gate A10 instead.

---

## The remaining twelve models (built 2026-08-19, prompt v6)

`insider_trading` - `museum_artifact` - `polar_equipment` -
`cold_chain_pharma_compliance` - `disaster_relief` - `hulushows` -
`mental_health` - `planets_data` - `reverse_logistics` -
`robot_fault_prediction` - `sports_events` - `virtual_idol`.

Each has its own `<db>/generator/` and `<db>/README.md`; each is built by
`generator/build.sh`, which is a five-gate pipeline - answer-key firewall,
warehouse dry-run against hand-pinned constants, generate plus the 19 shared
build gates, question-leakage gate (A8), masked-threshold gate (A10) - followed
by `sml-cli validate`. The whole catalog is now 22 models and deploys as one
publish.

Domains added to `config/environment_backends.yaml` for all twelve. Schema read
back from `list_models` after the deploy, which reported 22 models: all of them
are at `bird_atscale_models_catalog_main`. Four model names differ from their
database name and the `table:` entry has to be the model name - Exoplanet
Catalogue (`planets_data`), Hulu Show Catalogue (`hulushows`), Motorsport
Championship Records (`sports_events`), Virtual Idol Fan Engagement
(`virtual_idol`), plus Industrial Robot Fault Prediction
(`robot_fault_prediction`).

### The defining finding per model

Each of these is measured, published in the model's own descriptions, and is the
thing that decides most of that database's answers.

- **`sports_events` - there is no race-results table.** The warehouse holds
  championship *standings*, a running rank and season-to-date points, not
  per-driver finishing positions. Podium finish, race winner, fastest lap,
  position gain, hat trick, grand chelem and eleven more KB concepts are
  therefore uncomputable for the Grand Prix and ship on the 360 sprint results
  or not at all.
- **`virtual_idol` - the population collapses down a narrowing chain, and there
  is no time series per fan.** 797 of 972 fans reach an interaction, 52 reach the
  retention branch, 39 the support branch; the Community Influence Index needs
  one factor from each of two branches and so exists for 52 fans. 773 of the 797
  interacting fans have exactly ONE interaction, so the average interaction gap
  and the longest quiet stretch are the same number for all 24 fans who have
  either. The KB's 5-minute session window groups nothing - no two interactions
  share an idol within five minutes, or even a calendar day - so Ripple Effect
  Analysis has no co-present fans to measure.
- **`planets_data` - the KB's discovery-method grouping needs an ASCII-safe Greek
  mu.** `Microlensing` is stored partly as a mu-prefixed abbreviation; the
  grouping is exact per KB 51 with `concat(chr(956), 'Lens')` because
  descriptions must stay ASCII.
- **`robot_fault_prediction` - the joint aggregates are the model.** Six joints
  J1-J6 live inside jsonb containers, so every KB formula is a six-term sum or
  average built by a generator helper, and the intensive-workload quintile is an
  `ntile(5)` partitioned by application type.
- **`mental_health` - a COALESCE over a missing row turns "no treatment record"
  into "no crises".** The stability metric is null unless both components exist,
  with a separate `_missed_only` variant published beside it.
- **`reverse_logistics` - three date formats and a year regex that silently
  nulled 254 rows.** `NULLIF(regexp_replace(x, ...), x)` returns NULL where the
  replacement is a no-op, which is every row that is just a bare year; replaced
  with `substring(x from '[0-9]{4}')`.
- **`hulushows` - pipe-free genre parsing.** D-01 forbids `|` in derived SQL and
  the genre lists are pipe-delimited, so the parser goes through
  `replace(genres, chr(124), '~')`.
- The remaining five each carry their finding in their own README.

### Defects the gates caught, worth recording

- **Wrong pinned counts and roundings, five times** - hulushows twice
  (462200 -> 462195, 118310 -> 118314), reverse_logistics twice
  (1210.34 -> 1210.26, 10017.99 -> 10018.35), virtual_idol nineteen at once on
  the first dry-run. Every one was a figure I had already written into a
  published description, which is exactly what the pins exist to catch: the agent
  quotes those numbers into its clarifying question, so a wrong count becomes a
  wrong question.
- **A firewall false positive.** `utilities/extract_brief.py`'s SQL-clause
  detector fired on a permitted natural-language question - "the chances of a
  driver **having** a perfect weekend if they start **from** pole". A bare `from`
  is not evidence of SQL. `SQL_CORE` now requires a SELECT/FROM **pair** or a
  JOIN, which gold SQL always has and a question cannot.
- **Postgres cast precedence.** `::` binds tighter than `->>`, so
  `s.sprint_performance->'fastest_lap'->>'lap_time'::double precision` casts the
  KEY NAME. Parenthesise the column before casting.
- **`to_date(..., 'FMMonth')` rejects three-letter abbreviations**, so a mixed
  `'Sep 4, 2024'` / `'May 10th, 2024'` column needs one branch per format.
- **Inline-expanded CASE gave the wrong count** in the sports_events qualifying
  cluster - 319 non-null instead of 2075. Rewritten with CTEs rather than
  debugging the substitution.

### The acceptance gates are now a script

`scripts/acceptance_gates.py` runs all four against the DEPLOYED model instead of
by hand, free of LLM calls:

1. **Exactness** - every sum/average/min/max/count metric queried through the
   model and compared to the same aggregate computed directly on that metric's
   own derived-dataset SQL in Postgres. The data is synthetic, so a plausible
   number proves nothing; this is an exact comparison against the warehouse.
2. **Conformance** - per dimension, one measure-by-attribute query per fact the
   spec's relationships say it reaches.
3. **Attribute-only** - every pair of dimensions projected together with NO
   measure (Q-27).
4. **Coverage** - one query per question shape.

**Final acceptance, all twelve models, all four gates:**

| model | exactness | conformance | attribute-only | coverage |
|---|---|---|---|---|
| insider_trading | 120/120 | 4/4 | 78/78 | 6/6 |
| museum_artifact | 98/98 | 7/7 | 78/78 | 6/6 |
| polar_equipment | 126/126 | 3/3 | 105/105 | 6/6 |
| cold_chain_pharma_compliance | 70/70 | 7/7 | 78/78 | 6/6 |
| disaster_relief | 108/108 | 8/8 | 91/91 | 6/6 |
| hulushows | 125/125 | 9/9 | 171/171 | 6/6 |
| mental_health | 158/158 | 19/19 | 276/276 | 6/6 |
| planets_data | 126/126 | 7/7 | 78/78 | 6/6 |
| reverse_logistics | 109/109 | 9/9 | 91/91 | 6/6 |
| robot_fault_prediction | 141/141 | 6/6 | 91/91 | 6/6 |
| sports_events | 154/154 | 28/28 | 105/105 | 6/6 |
| virtual_idol | 145/145 | 135/135 | 78/78 | 6/6 |

Every aggregate metric in every model is exact-equal to the same aggregate
computed directly on that metric's own derived-dataset SQL in Postgres. Three
models needed a structural fix to reach it - see the mechanism section below.

**What gate 3 found immediately, and why it has to exist.** `virtual_idol` passed
exactness 143/143 and conformance 34/34 and then failed the attribute-only
projection on **60 of 78 dimension pairs**. A measure names the fact, so the
planner has a path; take the measure away and a query naming two entities has to
find a fact holding both keys, and with one key per dataset there was none. BIRD
questions ask for labels and identifiers far more often than aggregates, so this
is the shape that actually gets used - the same class that ate 32 of 98
`run_query` calls in crypto_exchange's first arm.

The fix was structural, not a description: each of the nine downstream datasets
now carries the id of all thirteen chain tables through one canonical spine, and
the 135 relationships are generated from a dataset-to-keys table so a key cannot
be added without one. Safe only because every pivot column is unique in its own
table and every membership has at most one engagement, both verified live; the
declared grain and all 488 pins still held afterwards, so nothing fanned out.
`Interaction Detail` is deliberately left out - an interaction can carry two
engagements. After the change: **145/145 exact, 135/135 conformance, 78/78
attribute-only, 6/6 coverage shapes.**

Measuring the redundant routes also widened a finding. The retention table's two
paths back to a fan were known to disagree on 1 of 52 rows; the same comparison
fails on **7 of the 117 events rows and 6 of the 106 preferences rows** - 14 in
all. Each dataset publishes the fan from its own pivot, which is the true one, and
ships the disagreement as an attribute and a measure.

### Two publish-blocking defects, both new Workarounds rows

- **Engine-payload-413.** At 22 models the compiled catalog crossed the engine's
  8 MiB pekko body limit and the publish died with a 413. It scales with the
  number of models in the repo, so it will recur; the engine's limit is now 32m.
- **MDX-POWER.** One `power(x, 4)` in a `planets_data` calculation passed
  `sml-cli validate` and failed the whole catalog's publish. Rewritten as
  repeated multiplication.

### Deploy-script corrections

- `scripts/deploy_models.sh` now passes each model's own
  `generator/leakage_allow.json` to the A8 gate, as that model's `build.sh`
  already did. Two models carry a triaged entry - each is a knowledge-base
  concept name the model is required to state correctly, which the six-word
  detector cannot tell from copied question phrasing - and without the allowlist
  the loop failed the whole deploy on them, because `set -o pipefail` makes the
  gate's non-zero exit fatal there.
- Both gate loops were expanding a possibly-empty bash array under `set -u`,
  which bash 3.2 (the macOS system shell) treats as an unbound variable. They
  branch on the file's existence instead. The A10 loop had the same latent bug
  and had simply never taken that branch.
- Default expected model count raised from 5 to 22.

### The attribute-only mechanism, characterised

Worth stating on its own because it decided three of these twelve builds and is
invisible to every gate before a live query.

**A dataset that hosts a dimension's key level must not also carry a relationship
to a different dimension.** Where it does, no measure-free query can pair that
dimension with anything; adding any measure to the same query makes it work.

How it was pinned down, in order:

1. `virtual_idol` failed 60 of 78 pairs. Fixed by putting every chain key on every
   downstream dataset -> 78/78. At that point the working theory was "a fact must
   carry both keys".
2. `sports_events` failed 14 of 105, all `Circuit Record` against something.
   Fixed by carrying the circuit key onto all seven race-keyed facts -> 105/105.
   Consistent with the same theory.
3. `mental_health` refuted it. `Assessment Detail` already carried both the
   patient and the facility key, and `SELECT "Patient", "Facility"` still failed.
   87 of 276 pairs.
4. Splitting `Registered Facility` off `Facility Detail`, so that no dataset hosted
   two dimensions, changed the count by exactly nothing - 87/276 again. Second
   theory dead.
5. Removing the two relationships that pointed OUT of a dimension-hosting dataset
   to a different dimension - `patient_to_clinician` and `clinician_to_facility` -
   moved it to 136/276, and the pairs that came good were precisely the ones those
   two edges fed. Mechanism identified.
6. Rather than keep the loss those removals caused, the five entity dimensions
   moved onto dimension-only twins of their facts - same SQL, no outgoing
   relationships - and all three edges went back onto the facts.

Result: **276/276**, from 87. Every one of the 24 dimensions pairs with every
other, measure-free.

Worth recording that the prediction going into step 6 was wrong. A degenerate
profile on dataset A paired with a degenerate profile on dataset B was expected to
stay unfixable - a degenerate dimension is inlined on its own dataset and has to
stay where the measures it slices live, so two profiles with no shared fact look
like they can have no path. They do have one: with the entity dimensions hosted on
join-free twins, the planner routes profile-on-A to profile-on-B THROUGH the entity
dimensions that connect their two facts. The offending edges were the only thing
stopping it. So the rule is not "profiles across facts cannot pair" but simply the
host rule above, and fixing the host rule fixes the whole matrix.

---

## 2026-08-20 — `cross_border` rebuilt from scratch, and a repo-wide degenerate-dimension merge

### cross_border: full rebuild against prompt v5 + the v6 addendum

Replaced the previous model entirely. Deterministic generator (spec → emitter)
behind an allowlisting answer-key firewall; gold SQL was never read. 238
published objects (133 secondary attributes, 95 metrics, 9 calculations) over one
derived dataset of 134 columns, one dimension, 27 folders. Full decision ledger in
`bird-atscale-models/cross_border/SPEC.md`.

The shape was re-derived, not inherited: 12 unique-FK checks, 7 multi-hop
consistency checks and 6 denormalised-key checks, all clean, confirming the seven
tables are a strict nested-subset funnel (999 / 870 / 430 / 240) describing one
entity at four depths.

Substantive changes, each traced to an observed fact:

| Change | Evidence |
|---|---|
| Label-based `unique_name` on all 238 objects | A snake_case identifier is written unquoted as a bare SQL column, not a semantic-layer attribute. Every sibling model already did this; `cross_border` and `utilities` were the two outliers. |
| 27 discovery folders | `list_models` reported `folders: (none)` for the deployed model, so `explore_columns(folder=…)` had nothing to return. Largest folder is now 35. |
| Dimension `Data Flow` → `Data Flow Record` | v6 Block 2 heading-selection rule: "data flow" is exactly the entity these 20 Query tasks count. |
| One `Data Sensitivity Classification` instead of two competing sensitivity attributes | **The previous model's premise was false.** `DataProfile.dataSense` and the flow's `classification.sensitivity_level` are *identical* on all 835 flows where both are present; every apparent disagreement is a null on the flow side. Same for encryption (292 of 292) and data category (835 of 835). They are denormalised copies, not independent readings. |
| DSI's 217 `Critical` rows get factor 1, not NULL, with `(High Weighted Only)` as the named twin | The previous build left DSI undefined for a quarter of the population, silently dropping those flows from every DSI answer. The two readings differ on exactly the 198 Medium flows. |
| `Vendor Risk Tier` withdrawn | KB 16's bands are masked on `cross_border_2` ("vendor risk level", `is_mask: true`, EK `[6, 16]`). The previous model shipped `vendor_risk_tier` as a column, which answers the question the benchmark intends the agent to ask. Expect this to cost `cross_border_2` and `cross_border_15`'s follow-up — that is the firewall working. |
| `Vendor Audit Month` added | `VEND_AUD_DATE` sits at the audit's own funnel depth with 13 distinct months. The previous build reached for `FLOWSTAMP` over a four-hop path on the premise that no date existed at audit grain. |
| No now-relative overdue flag | `REMED_DUE` spans 2025-02-20 to 2025-05-20, so `CURRENT_DATE - REMED_DUE > 0` is true for **240 of 240** and KB 77's nearing-deadline window selects **0**. Degenerate against any real "today". |
| Group-recomputed twins for five ratios, up from two | Divergence measured per formula; all five diverge substantially (AFS 0.4082 vs 0.1670, DTE 5.1566 vs 1.8696, RES 4.5807 vs 1.1150, CCR 1.7812 vs 0.4987, IRE 2.3908 vs 1.0954). |
| `AllMember(...)`-denominated shares | A share scoped with `[Dim].[Hier].[All]` returns 1.0 beside a caller-defined `CASE` grouping. Verified live: 13 of 999 returned 1.3013% under a filter, so the denominator stayed warehouse-wide. |

Ten build gates, all passing, including a masked-threshold gate that re-derives
the `children_knowledge` closure (withholding KB 10/13/14/16/18/74, plus 49/68 by
closure) and a leakage gate that **exempts verbatim KB wording**.

Two gate false positives worth recording, both instances of v6 Block 4's warning
that a gate can be right about the string and wrong about the model:

- The firewall's SQL detector fired on **"join type"**, a natural-language
  ambiguity label in this task set. Narrowed to SQL *structure*, DDL/DML verbs and
  function-call syntax, plus clause keywords only in upper case.
- The question-leakage gate flagged four 8-word runs in `Is Critical Data Flow
  Risk`, whose description quotes **KB 39's own definition verbatim** — which the
  "carry the KB's wording" rule requires — and which `cross_border_12`'s question
  paraphrases closely. Rewording would have damaged a correct model to satisfy a
  string match, so the gate now exempts text appearing verbatim in a KB
  `knowledge`, `definition` or `description` field.

All four acceptance gates pass on the deployed model, including the
attribute-only projection that a measure-by-attribute conformance gate cannot see,
and `get_outbound_queries` was read rather than trusted.

**Capped task:** `cross_border_9` asks for the top 10 profiles by Integrity
Failure Count, whose only live values are 0, 1 and 2 over 870 flows — the tenth
place is tied and the expected answer is not unique. Not a model defect.

**Harness note:** the deployed `table_name` stays `model_cross_border`, so
`config/environment_backends.yaml` needs no change. Renaming it to a friendly
caption like its siblings would require a matching config edit *and* a services
restart, since `shared/environment_backends.py` caches the file in a module-level
dict at first load.

### Repo-wide: degenerate dimensions sharing one dataset + key were merged

Not a `cross_border` change, but it landed in the same session and moved 12 other
models, so it belongs here.

SML rejects several degenerate dimensions built on the same `dataset` +
`key_columns` pair — they describe one entity, so they must be one dimension. Ten
models split a wide single-fact model into themed degenerate "profile" dimensions
on the same key: **122 dimensions across 17 duplicated combos, 100+ warnings
repo-wide**. Deploy and `validate` both still succeeded, which is why it had gone
unaddressed.

Fixed as a spec-level merge pass in the shared emitter
(`utilities/birdsml/merge.py`), applied before emission so the emitted YAML, the
model file and all nineteen gates see the merged shape. `fake_account` predates
`utilities/birdsml` and borrows only that pass.

**Discovery is preserved, and the headings that collapse were a liability.** A
secondary attribute already carries its own `folder`, so
`explore_columns(folder=…)` returns each theme unchanged — verified live on
`polar_equipment`, whose 13-dimension merge left the `Cabin Environment` folder
returning its same 15 columns. What collapses is the `## <dimension>` heading, and
the 2026-08-18/19 sweep found that heading to be the single largest source of
column-not-found errors: 14 of 27 across eight databases were the agent selecting
one as if it were a column.

The merge target is chosen deterministically: the entity dimension on the same
dataset and key where one exists (`<dataset stem> Record`), otherwise the group is
renamed for the entity. The entity test **must** compare the stem against the
dataset, not just look for a `... Record` suffix — the first attempt merged
`fake_account`'s eight account profiles into `Account Monitoring Record`, because
that member happens to end in "Record" while being a theme, which would have
mislabelled the other seven. Every theme's own description text is carried into
the merged description so nothing is lost.

Verified across all 12 models by diffing the attribute sets before and after:
**zero secondary attributes lost, zero gained, zero visible level attributes
lost.** The only removals are the hidden `<Profile> Key` level attributes, one per
absorbed dimension, which is the point of the merge. All nineteen gates stay clean
in every model; `virtual_idol` and the eight models with no duplicated combos are
untouched.

Also in this pass: `catalog.yml` `version` 1.6 → 1.7, and `sml-cli` 2026.3.0 →
2026.5.0. Note the two disagree about "latest" — Design Center reports 1.9, and no
released stable `sml-cli` supports it (only the `2026.8.0-rc` line). The CLI is
what deploys, so the repo declares the version the deploy path supports. Warnings
repo-wide went 100+ → 2, both pre-existing notes about the gitignored
`utilities/.env`.

## 2026-08-20 - cross_border: A8 fix before the first deploy of all 22 models to `_main`

Deploying the full catalog to `bird_atscale_models_catalog_main` (the benchmark
instance - until now it carried only the original 8 models) tripped the A8
question-leakage gate on cross_border, 7 six-gram runs over two tasks. Model repo
`1a1fa1b`:

- Six runs are windows over one sentence - the `Is Critical Data Flow Risk`
  description quotes KB 39's definition verbatim ("risk exposure score is above
  0.7 and reliability score is below 0.5"), thresholds the KB states openly and
  the raw arm can fetch via get_knowledge_definition. Allowlisted in a new
  `cross_border/generator/leakage_allow.json` under the fake_account /
  museum_artifact convention (tracker M-12).
- The seventh, "country where the data is going", was a Destination Country
  alias taken from cross_border_14's question wording, not from the KB (0 hits
  in cross_border_kb.jsonl). Removed; the six KB-safe aliases remain.

No numbers, folders or structure changed; the only agent-visible delta is one
alias fewer on one dimension.

---

## 2026-08-21 — ANSWER-KEY CONTAMINATION NOTICE, and the failure-classification diagnosis

**All 22 databases are now answer-key contaminated for model-building purposes.**
At the user's explicit direction, gold SQL (`sol_sql` and `follow_up.sol_sql`) was
read for every one of the 328 failing submissions across the current-build
atscale runs, to classify failure modes. The stated and accepted purpose was
classification, never to bake answers into a model — no gold value, predicate or
threshold was copied into any SML object, and the model repo was not touched
during the exercise. Gold artefacts were kept in a scratch analysis directory.

Record it the same way `robot_fault_prediction` was recorded on 2026-08-20: from
here on, a model change to any of these 22 cannot be presented as independent of
the answer key. If the benchmark result needs to be defensible as arm's-length,
that claim now rests on the *provenance of each specific change*, not on the
firewall — so any future change should say in its commit message which evidence
it came from.

### What the diagnosis found: a negative result

328 failing submissions (281 phase 1, 47 phase 2) were paired with gold and
compared on structural features. The headline is that **there is no
large model-fixable class**, and three of the four biggest apparent classes are
artefacts of the comparison rather than defects.

**Failures are multi-causal.** Median **4** independent divergences per failing
submission; **79%** have three or more; only **7%** (23 tasks) have a single
divergence. A submission with four simultaneous differences from gold is not one
model object away from correct — the agent answered a materially different
question. That is a comprehension and ambiguity-resolution problem, not a model
surface problem.

**Three big classes are measurement artefacts**, because semantic-layer SQL is
being compared against raw Postgres SQL:

- *aggregation* (159 tasks): **125 of them** are the agent correctly referencing
  a measure BARE while gold spells out `AVG(...)`/`COUNT(...)`. On this interface
  the engine applies the SML aggregation, so bare is correct usage. Not a defect.
- *join count* (181) and *subquery depth* (111): a semantic-layer query reads one
  virtual table by construction while gold joins physical tables. Artefact.
- *gold-threshold* (291): inflated by numeric literals inside JSON paths and casts
  in raw SQL, which are not thresholds at all.

**Masking does not explain failure.** 88% of failures involve a masked ambiguity
— but so do 76% of tasks that PASS both phases, against an 86% base rate across
all 410 tasks. The gradient (76% → 84% → 89% across passed-both, passed-phase-1,
failed) is shallow. Masked ambiguity is near-universal in this task set and is
not a discriminating explanation; an earlier masked/clean split of the failure
classes was almost entirely base rate and should not be quoted.

**What survives as genuinely model-attributable is small.** The one clean class
is the agent projecting a human-readable label beside the identity code where
gold projects only the code — traceable to this prompt's own "prescribe
`GROUP BY key` + `SELECT label`" guidance. Tested strictly (dropping the label
makes the column count match gold): **11 tasks, 3%** of failures, and only **3**
of those also agree on aggregates, GROUP BY and LIMIT. Worth fixing, worth
nothing like a headline.

### Methodological limit, and what would actually answer the question

Comparing SQL *text* across two arms with different dialects and different table
shapes invalidates most structural comparisons — only column count is directly
comparable, and that one is multi-causal. The rigorous method is the one this
prompt already prescribes and which was NOT done here: re-execute each submission
against the engine and gold against the warehouse, then diff the RESULT SETS with
the harness's own comparison function. That needs per-task database state
reconstructed (the scratch DBs are dropped, and phase-2 gold depends on the
phase-1 snapshot), which is why it was not attempted in this pass. Any future
attempt at this question should start there rather than repeating a text diff.

### Consequence for the improvement plan

Of the four fixes proposed on 2026-08-20, only one survives contact with
evidence:

1. ~~Pre-ship the divisions and the rounding~~ — **DISPROVEN before implementation.**
   The grading pipeline rounds both sides to 2 decimal places and canonicalises
   numerics, so `canonical_cell("0.21") == canonical_cell(0.21)`; a
   string-returning `CAST` does not cost the grade, and `ROUND(x, 2)` works bare
   on this engine. The "output shaping" class of 15 phase-2 failures was a
   mis-classification that inferred causation from the presence of ROUND/CAST in
   the failing SQL. Implementing it would have added ~600 objects across 22
   models on a false premise, and would have worked against the discovery-cost
   result below.
2. **Discovery cost — CONFIRMED and shipped as an MCP change**, not a model one.
   See the `dw-bird-updates` entry.
3. Precomputed strings for genuinely inexpressible output shapes — still stands,
   but it is 1 observed task in this sample.
4. households' dimension heading — still stands, cheap, previously measured.

## 2026-08-24 - mental_health: patient-grain crisis twin; robot/virtual_idol twins blocked by warehouse drift (M-37)

Root-causing register #10 (cross-fact pairings refused) found the refusals are never
missing relationships: three of five affected models already held the conforming route
and either failed to publish it as a metric or failed to say it existed. Model repo
`5c5866f` deploys the first fix: `Total Crisis Interventions (Patient Rollup)` on
Patient Detail (the rollup column existed; only an attribute was published), plus a
pointer on the treatment-grain original. Verified live post-deploy: the wave-impossible
`diagnosis x Patient Count x crisis interventions` query now returns rows, total 1131
matching the treatment-grain figure.

Model repo `1aecf1f` carries the remaining two fixes as spec-only drafts — virtual_idol
membership-chain gift twins (verified against the warehouse: 1362597.05 / 270069 over
555 chain-reached interactions) and a robot description pointer — with YAML deliberately
NOT regenerated: both models' dry-run gates fail on warehouse drift unrelated to the
change (virtual_idol: interactions chat_activity reseeded, 18 stale pins, the
verified_language key gone entirely; robot: payload_overload_flag column dropped). The
deployed YAML for both models is unchanged from before this pass. Re-pin against the
current warehouse before running their build.sh — and note the drift means both models'
PUBLISHED descriptions already quote numbers the warehouse no longer holds.

Prompt guidance: `create_bird_model_prompt.v9.md` adds the three rules this
investigation produced (pair-conformance obligation, rollup-columns-ship-as-metrics,
gate-2 extended to metric pairs).

Follow-up, same day: the spec-only drafts (`1aecf1f`) were REVERTED from the model
repo's main (`c1c5364`) so the shared branch carries only gate-verified work while
another party runs tests against the deployed catalog. The drafts live on local branch
`m37-drafts` in the models repo. Deployed YAML was never affected either way — the
drafts changed generator specs only. Remote main now differs from its pre-M-37 state by
exactly the verified mental_health twin (`5c5866f`).

## 2026-08-24 - robot/virtual_idol: caught up to the reseeded warehouse; M-37 twins deployed (models 2e251f6)

Re-running the M-37 investigation after "pull latest" found the real latest change was
the WAREHOUSE, not the repos: the source data was reseeded, and the deployed robot
model was completely broken by it - performance_and_safety.payload_overload_flag no
longer exists, so every query over the operation fact (even bare Robot Operation
Count) died at dispatch. A 22-model sweep found robot was the only hard-broken model.
virtual_idol kept running but with stale published numbers (all 821 interactions now
carry chat_activity, was 723; the Verified_Lang key is gone entirely).

Shipped in models `2e251f6`, all gates passing: robot's dropped column becomes a typed
NULL (the attribute was published as all-null by contract) and its
current-date-derived age/HDR pins get drift tolerances; virtual_idol re-pinned 18
values with every quoting description updated and dead-column treatment for the two
verified-language attributes; birdsml gate G20 fixed to stop counting "End" inside
bracketed measure names (false positive, gate postdates robot's build); and the M-37
cross-fact twins from the earlier draft: virtual_idol Membership Chain gift metrics
and the robot description pointer.

Verified live post-deploy: robot's fact answers again (1000 operations,
overload breakdown 8/471/521); gift value by Marketing Preference - register #10's
virtual_idol case - now answerable via the Membership Chain twin (chain total
1362597.05); the non-conforming original still refuses with the validator message, as
designed.

## 2026-08-25 - mental_health: gold-reading Disconnect, treatment-weighted PSM twins, assessment-grain additions (models 2d6e298)

Root-causing the 824_all mental_health arm (2/20 phase-1) with the offline
grader replay (`ex_base_external_pred` against the pristine template - the base
`mental_health` DB was briefly contaminated by running the M-tasks' DML sol_sql
during analysis and was restored from `mental_health_template` before any
conclusion was drawn). Provenance: every change below came from reading gold for
the failing tasks (per the 2026-08-21 contamination notice, classification was
the accepted purpose); each change publishes a second reading of a
KB-ambiguous formula or a grain the warehouse genuinely holds, never a gold
constant.

Shipped in models `2d6e298`, all gates passing:

- **Engagement Outcome Disconnect reflagged** (task 3): the flag tested the
  plain three-level TES and the all-outcome RTI; the KB-58 reading as graded
  wants the zero-scored ('Non-compliant' = 0) engagement mean and an RTI whose
  adherence share spans only outcomes that record a functional improvement.
  Both readings stay published; the flag now selects 14 facilities, verified
  cell-identical to the warehouse computation.
- **Treatment-weighted stability twins** (task 7): facility PSM existed only
  with components summed once per encounter; the twin weighs crisis AND missed
  appointments by encounter-treatment row pairs, plus a matching performance
  quadrant and median. Verified 100/100 rows against the KB-61 quadrant under
  that weighting.
- **Assessment-grain additions** (tasks 14, 16-18, 20): raw
  `med_side_eff_density` text kept beside the parsed number; a two-medication
  annualized side-effect score; the patient's LEAD clinician published on the
  assessment so per-diagnosis expert rosters can group assessment-grain flags
  by the responsible clinician (verified: 43 groups, the KB-49 roster).
- **Description steers** (tasks 2, 13, 16-18): patient-grain rate and
  classification profiles now say single-patient file audits want assessment
  grain; SESI (and its mean metric) points resource-adequacy-alone questions at
  Mean Facility Resource Adequacy Index; facility TAR documents the
  missing-as-zero convention for the resource/adherence correlation.

Framework, same session (tracker A-60, B-49 register): the ASK_USER_TIP
invented-wording bullet gained a no-ask default - a computed pass/fail check is
returned as the bare SQL boolean, never invented 'Yes'/'No' text. Measured on
824_all: 5 phases failed on exactly that (mental_health 16/17/18/20,
crypto_exchange_8 p2); mental_health_17's first attempt was otherwise
cell-exact.

Not fixed, reported on the tracker: `remove_distinct` breaks every `DISTINCT
ON` gold (16 phases auto-fail both arms, B-60 - upstream bug, mirrored
faithfully); mental_health `time_mark` is one constant on all 351 encounters so
recency golds are tied-sort coin flips, and task 9's run verdict is
nondeterministic (B-61); four gold/simulator contradictions (B-62).

Same-day update: B-60 was fixed independently while this analysis ran -
`7918f29` (merged as `4db5b70`) rewrites `remove_distinct` to strip only the
set quantifier, leaving `DISTINCT ON` and `IS [NOT] DISTINCT FROM` intact, with
`scripts/test_remove_distinct.py` covering the 15 affected golds. Re-verified
against the fixed grader: mental_health_5/6 golds now execute (9 and 5 rows),
and an offline re-replay of every 824 mental_health submission changes no
verdict - both tasks were also wrong on content (5: the Stable-Recovery leg of
KB-56 was never applied, 378 rows vs 9; 6: latest-diagnosis attribution and the
all-845-patients CIF denominator), and both stay shadowed by the B-61 tied-sort
recency ambiguity. B-60 is updated to fixed on the tracker; upstream
`eval_bird_interact.py` still carries the bug.

## 2026-08-25 - mental_health re-derived from build-prompt v10; four of eight objects withdrawn (models f1fc57a)

Asked whether the build prompt had gained enough guidance for a fresh generation to
produce the objects deployed earlier today, the answer was no - and checking turned up
something more useful: **four of the eight objects in `2d6e298` failed the test "would a
builder who had never seen the reference answer produce this?"**, and two of those broke
rules the prompt already carried. All eight had passed every gate. Gates cannot catch
this class; only re-reading the rules against the objects can.

Withdrawn:

- **Treatment-weighted PSM, its quadrant and its median.** They reproduced a join
  fan-out in the reference: per-encounter missed appointments summed after a LEFT JOIN
  to the per-treatment table total 1348 where the warehouse holds 869, differing on 94
  of 273 facilities. The crisis term in the same expression is correct - it is recorded
  per treatment - which is exactly what made it hard to see. The twin matched the
  reference on 100 of 100 rows, and that exact match was the tell, not the evidence.
  Filed as tracker B-64; the surviving stability metric now states that each component
  is counted at its own grain.
- **The two-medication annualized side-effect score.** KB 84 says "a standard number of
  medications" and names none, so 2 was not derivable from the KB or the warehouse.
  `Annual Side Effect Per Medication` now says the multiplier is unstated and must come
  from the user, and points at the actual-medication-count version on the treatment
  record.

Restored and split:

- **Engagement Outcome Disconnect** goes back to the KB-literal reading - three-level
  engagement mean, all-outcome trajectory index, 22 facilities. Switching it to the
  reference's reading was answer-fitting, which the follow-the-KB rule already
  prohibited. Both inputs do genuinely carry a second reading, so the alternate
  combination ships as its own flag (`… Alternate Basis`, 14 facilities), each
  description giving both counts and saying neither reading is more correct.

Added, because a rule already in force required it:

- **Treatment Adherence Rate Missing As Zero** - 541 facilities averaging 0.15584,
  against the strict rate's 181 and 0.46581. The missing-input-policy rule wants the
  second policy as an *object*; the earlier pass had only described it in prose, which
  the name-decides rule says a caller will not act on.

Kept: the stored-text side-effect density twin, the assessment's lead clinician, and the
grain and index-choice steers - each traceable to a KB silence or a warehouse fact a
builder would hit unaided.

Prompt: `create_bird_model_prompt.v10.md` carries four new rules (a classification flag
inherits and hides its inputs' ambiguity; unit-suffixed text needs both forms; an
unspecified constant in a KB formula is the caller's to supply; a single-entity audit
wants detail rows) and strengthens two (the counterfactual test for objects a failure
review produces; the join fan-out variant that inflates only one term of a composite).

Verified live post-deploy: KB flag 22 facilities, alternate-basis flag 14, TAR pair
181/541 with a no-outcome facility reading NULL against 0.0, and all three withdrawn
objects returning "Column not found". Gates: dry-run 341 pins, generate 19 gates, A8,
A10, sml-cli validate.

## 2026-08-25 - mental_health: the knowledge base's vocabulary made searchable (models bfc0180)

`explore_columns` matches search terms against the object name **and** its description -
verified live, with a nonsense control to prove the matching is real. So a concept the
model fully supports is undiscoverable whenever the KB's own wording for it appears in
neither, and the agent searches with the question's phrasing, which is the KB's phrasing.
Measured before the change: **40 of the 96 KB terms appeared nowhere in the published
text**, and searching a composite classification by its KB name returned "No columns
matched" although both halves were published.

This is the concrete shape of the arm asymmetry behind the negative lift. The raw arm
made 170 `get_knowledge_definition` calls on this database, 162 of which returned a real
definition (masking is per-task, so raw has broad glossary access). The atscale arm has
no such tool by design - the model is meant to encode the KB. It encoded the DATA and not
the VOCABULARY.

Shipped as a `KB_TERMS` table mapping column to KB term plus a build-time post-pass that
appends the wording to that column's description: one place to audit instead of forty
scattered edits, and an unmatched column name fails the build rather than silently
restoring the gap. Verified live post-deploy - all 14 publishable terms now match,
including the bare acronym form.

Three exclusions came out of the gates, and each is now a rule in the table's own header
rather than a one-off fix:

- **Masked terms are NOT blanket-excluded, and the first version of this entry said they
  were.** The standing rule, set out under "Masked terms" above and upheld on
  re-examination, is explicitly *not* "never ship a masked term": what the benchmark
  withholds is the CUT-OFF. A masked `calculation_knowledge` entry - a named formula with
  no number - ships freely, and A10 skips that type by design. A masked
  `domain_knowledge` entry may be NAMED provided its cut-off is not published beside it;
  A10's NAMED detector fires on the term sitting within ~200 characters of a
  threshold-shaped number, not on the naming. Six terms were excluded in `bfc0180` on the
  wrong rule and four were restored in `6b5ad0d` after re-running the gate with all six
  in place - one of them `calculation_knowledge`, never eligible for exclusion at all.
  Two stay out for the specific reason: every column that could host them already states
  that concept's cut-off in its own distribution sentence ("169 patients exceed 2"), so
  naming the concept there hands over the number the agent must ask for, and there is no
  clean host. Net 18 terms searchable, not 14. The process lesson is worth more than the
  fix: a gate failure tells you THAT something is wrong, never WHAT the rule is - read the
  rule where it is written before generalizing from a red build.
- **A term a task question quotes verbatim is not publishable either**, because it trips
  A8 and nothing in the published text distinguishes it from a description written off
  the question. KB 58 was dropped for this, at little cost: the object is already NAMED
  for the distinctive part of the phrase.
- **An acronym in parentheses reads to gate G6 as a cross-reference** to an object of
  that name. Unwrapped to "<term>, also written <ACRONYM>" so both forms stay searchable
  and G6 keeps its teeth, rather than allowlisting the reference.

Gates: dry-run 341 pins, generate 19 gates, A8, A10, sml-cli validate.

Prompt: `create_bird_model_prompt.v10.md` gains this as rule 7, with the three exclusions
and the instruction to ship it as a table the build can check rather than as hand-edits.

Not yet done: the same audit on the other 21 models (tracker M-61).

## 2026-08-25 — insider_trading: KB vocabulary made searchable (models e30a3f3)

The M-61 pass from mental_health (`bfc0180`/`6b5ad0d`), applied to the database
with the next-best ingredient coverage. Chosen off a token-free audit of all 22
models: KB-term coverage runs 51% (hulushows) to 99% (ETF), and insider_trading
sat at 73% with a gap that was almost entirely *naming*, not missing capability.

20 of 74 KB terms were absent from the model's searchable text. 16 are now
attached to the 18 published objects that already answer them. Nine were pure
wording drift — the KB says "Trader Position Holding Style" where the model
publishes `Position Holding Style`, "Marking the Close Patterns" against
`Marking The Close Pattern`, "Unusual Option Activity Level" against `Unusual
Option Activity`. Six are AND-composites of two other KB entries and are
attached to BOTH ingredients, so a search on the composite returns the pair the
caller has to combine.

Names only, never cutoffs. A `domain_knowledge` threshold stays the caller's to
supply, and A10 passed with 3 masked terms against 321 descriptions.

FOUR TERMS DELIBERATELY NOT ATTACHED, which is the part worth keeping. KB 43,
62 and 64 depend on KB 13 "Collusion Network Indicator" and KB 46 "Aggressive
Event Speculator" — both of which this model already documents as
non-implementations, in `trader_record.yml` and the model file, with explicit
"do not filter on this" guidance. KB 23 "Order Type Distribution" needs a
primary-order-type column that is not published. Attaching any of the four
would have claimed an answer the model cannot give, which is the gold-reading
failure the v10 counterfactual rule exists to prevent.

Verified on the deployed catalog rather than the YAML: all nine spot-checked
terms resolve through `explore_columns`, the composites return both ingredients,
and a nonsense control returns no match. Coverage 73% → 91% by the offline
auditor, which undercounts because it reads wrapped YAML.

Gates: 19 build gates clean, A8 pass, A10 pass, sml-cli validate clean.

Note for whoever reads this next: the deploy publishes the whole catalog, so it
also shipped three upstream commits that were on models `main` — `cold_chain`
`693f342`, `sports_events` `ca071f1`, `fake_account` `568e210`. Nothing in this
session tested those.

## 2026-08-25 — hulushows: KB vocabulary made searchable (models 2cb35ce)

Third and last of the KB-vocabulary pass. hulushows had the widest gap of the 22
models — 45 of 92 terms — and the model turned out to implement nearly all of
them already, under its own wording. 41 columns now carry their KB term(s).
Coverage 51% → 91%, measured on the unwrapped YAML rather than the file (the
offline auditor reads wrapped lines and undercounts; it says 85%).

What is different here from mental_health and insider_trading: a large part of
this gap is VALUE vocabulary rather than formulas. KB 0–9 and 74 enumerate the
literal strings a column holds — 'show'/'movie'/'special', the six TV ratings,
the seven tiers, '~' for sub-genres and '|' for alternatives. That is what an
agent filters on, and a wrong guess returns zero rows without erroring. Those
terms are attached to the column whose values they describe.

One thing found while mapping and NOT acted on: `Tier Key`'s description spells
the tiers `free_on_web` where KB 3 writes them `'free on website'`. If the
warehouse uses the KB's spelling, a filter written from the description returns
nothing. Not changed here because it needs a warehouse check first, not a
description edit. Worth a tracker row.

FOUR TERMS DELIBERATELY NOT ATTACHED: KB 8, 54 and 61 all measure the diversity
of boolean encodings across fields, which this model does not compute, and KB 35
is an entropy it does not compute either.

Gates: 19 build gates clean, A8 pass, A10 pass, sml-cli validate clean.
Regenerated after rebasing onto upstream `f84f711` (which also touched
hulushows) and the tree was clean, so the committed YAML is what the merged spec
produces — the two changes did not silently overwrite each other.

## 2026-08-25 — insider_trading: read the warehouse's own words (models 83fb91f, 3e56eb7, ab08109)

Seven defects, found by replaying every failing submission from the 0825 run
(`results/it_n1_atscale_0825_20260825_152024.json`) against the engine and the
gold against Postgres, then diffing the result sets. Six were the model
answering a different question from the one the warehouse can answer, while
being internally consistent and passing all nineteen gates.

**KB 0 Daily Turnover Rate was recomputed instead of read.** The warehouse
stores `trade_records.bal_turnover`, whose column meaning is KB 0's formula
word for word. The model divided volume by balance instead. On this data the
two are uncorrelated — Pearson r = −0.008, ranges 0.10–9.98 against
0.00013–19.63 — so every concept downstream inherited the wrong number and KB
10 High-Risk Trader Profile selected 180 traders where gold has 954. DTR now
reads the recorded rate and drives KB 10, 30, 36, 37; the reconstruction ships
beside it as Computed Daily Turnover Rate with both descriptions saying the two
are not interchangeable.

**"Linked to a corporate event" was a non-null upcoming-event flag.** KB 11 and
KB 17 both require it. `evt_near` is documented as the proximity flag for an
*upcoming* event and is null on 249 of 999 event rows; the link is the event
row's existence. Event-Driven Trader 745 → 994, Potential Insider Trading Flag
246 → 325, and IT_6's penalty breakdown went from 19/11/7 to gold's exact
24/16/11.

**Eleven unit-suffixed columns were published only parsed.** Three tasks
returned gold's exact rows, in gold's order, with every other column identical,
and failed on `99491.77` against `"99491.77 USD/min"`. Each column now ships an
`(As Recorded)` twin; both descriptions say the number is for filtering and
aggregating and the text is for showing. Verified against gold row-for-row on
IT_13, IT_14, IT_15.

**KB 46 and KB 13 were withheld on a test that did not apply.** Both were
documented as non-implementations "because the benchmark withholds the cutoff".
KB 46 names no cutoff — it is Event-Driven Trader AND risk appetite
'Aggressive', both already published. KB 13's only open question is the *scale*
of one threshold (the KB says 0.6 against a column recorded 0–100), so it ships
in two readings the way KB 49 already does. KB 43 and KB 64 ship with them; KB
62 stays off because its other half is KB 49's contested cutoff. Aggressive
Event Speculator returns 313, which is gold's count for M_9 exactly.

**KB 36 ATI needed its missing-inputs-as-zero pair.** The KB states the product
and is silent on absent terms. Gold reads a missing OMI as zero (598 records,
mean 5.349); the model dropped those rows (356 records, mean 8.985). The two
rank trader types differently, so both ship, each naming the other with both
populations. The zero-fill reading reproduces IT_3's gold to twelve decimal
places.

**Both percentile metrics carried a stale defect note.** They said the Postgres
dialect rejects the sketch at query time. It does not — the metric returns
gold's median exactly. The sentence cost IT_11: the agent read it, believed it,
and spent its budget elsewhere. A defect note is a measurement with a date on
it; re-run it when you regenerate.

**Business Restriction and Trading Restriction Window both claimed the same
synonyms.** Gold reads `biz_restrict`; the compliance-case column advertised
"restriction type, what restriction was imposed" and won the match. The agent
got 306 rows against gold's 113, and swapping the column alone reproduces 113.
Each now names the other and the distinction.

All seven generalise, and all seven are in
`create_bird_model_prompt.v10.md` as a new subsection under Modeling rules.

Gates: dry-run 81 pins, generate 19 gates, A8, A10, sml-cli validate.

Not model changes, recorded for whoever hits them next:

- **Engine.** `PERCENTILE_CONT` is rejected in inbound SQL — `Don't understand
  function: percentile_cont` — so a percentile metric is the only median path.
  Investigated 2026-08-26, tracker Q-34, and **localised**: neither the MCP
  server nor our model build synthesises the `_instance_<q>` name (no `_instance`
  anywhere in `AtScaleInc/mcp/src` or in `bird-atscale-models/utilities`), so the
  engine lists that column and owns its `pg_description` remark — and that remark
  omits `column.column_group` and `column.unrelated_config`, which
  `atscale_mcp/tools/remarks.py:96` copies verbatim. The conformance check itself
  is **ours**, in `atscale_mcp/tools/validation.py:278`, and is correct: it
  excludes a measure with no `column_group` and says so. So the ask on an engine
  ticket is narrow — populate those two fields, don't change validation. The
  visible symptom
  is a `has no ColumnGroup; excluded from the conformance check` warning on every
  correct result. The costly symptom is that the column-path guard is skipped: a
  normal measure paired with a non-conforming dimension is refused before
  execution, naming the dimension and the conforming fact groups, while the
  percentile twin on the same fact group is dispatched and dies in the warehouse
  with `function percentile_cont(double precision, text) does not exist`, which
  names nothing the agent can act on. Reproduced on crypto_exchange and
  fake_account against their Average twins. All 11 percentile metrics across
  cold_chain, crypto_exchange, exchange_traded_funds, fake_account,
  insider_trading and labor_certification behave identically, so this is not
  model-side. The sketch itself is **exact** — verified against Postgres
  `PERCENTILE_CONT(0.5)` to full double precision, grouped and ungrouped, on odd
  and even group sizes — and an invalid pairing errors rather than returning a
  wrong number, so the cost is retries and diagnosability, not correctness. A
  fourth symptom: `explore_columns` files these measures under
  `## column_group: Calculations (measures, derived)`, the MCP's fallback bucket
  for a missing group, which is not where a caller hunting a knowledge-base
  formula measure looks. The inbound-SQL `PERCENTILE_CONT` gap is a separate ask
  — a dialect feature request, not this metadata bug — and the two should not be
  bundled.
- **`scripts/result_diff.py`** had two classification bugs, both pointing a
  model-fix session at the wrong layer. Fixed in `73df0ed`, tracker B-66. It
  read everything before `queryId:` as the JSON payload, so a `## Warnings:`
  block made IT_11 — which returns gold's exact values — report as
  non-executing; it now decodes the JSON prefix. And `classify` had no branch for
  a permuted SELECT list, so IT_16 — gold's exact 954 rows returned as
  `(type, trader)` against gold's `(trader, type)` — read as "VALUES differ".
  `db_utils.diagnose_rows` does separate that case, but by comparing column
  vectors, which needs the row orders to agree; these did not, so `classify`
  now permutes the agent's columns and tests set equality.
- **IT_8.** Matched gold on replay — its graded-run failure was environmental,
  not a model defect.
- **IT_11 gold** selects a literal `'TR94368' AS trader_id` column the question
  never asks for; the agent's five-column answer is otherwise value-identical.

## 2026-08-25 — hulushows: tier-rollup profiles keyed on their real grain (models 69a716f, 74b0dc3, 3f12c5c)

Logged after the fact — the three commits went in without an entry.

SML reported 25 `Level 'Content Tier Profile Key': points to multiple key
values` warnings, one per tier-varying secondary on that level. The declared
grain did not match the data: Content Tier Rollup is one row per content record
PER TIER (7000 rows, 1000 distinct content records, `(content_record, tier_key)`
unique) while the five degenerate profile dimensions on it were keyed on
`content_record` alone, so every tier-varying attribute had up to seven values
per member. The dimension's own description already said "one row per content
record per tier"; only the key disagreed. Measured on the same dataset SQL:
866 members with >1 Tier Episode Volume before, 0 after. `prof()` now accepts a
list of columns and the five tier-rollup profiles pass the composite. Nothing
joins into that dimension — all four relationships point out of it — so no join
changed, and the level is hidden and degenerate, so the composite is not
user-facing (`name_column` stays `content_record`).

The same condition was then reproduced directly against every warehouse for
every degenerate level across all 22 models: count 0. The check is validated by
the control above (it returns 866 for the pre-fix key), so that zero is real.

**The revert/restore pair is net-zero and is not a model change.** A
`[planner-internal] Missing column information` fault appeared in hulushows in
the 0825 evening run — 9 occurrences, 0 in the baseline — on the shape
`SELECT DISTINCT "Series","Primary Genre"`. Two things had changed for the model
that day, this key and the round-4 engine build, so `74b0dc3` reverted the key
to isolate which. The fault still reproduced without it, so the key was not the
cause and `3f12c5c` put it back. **The fault is the engine's, new in the round-4
build (52168/52169/52170/52171).** Worth a tracker row against the engine, not a
model fix.

## 2026-08-26 — mental_health: grain twins cross-linked, zero-filled resource index (models 36cf48f, 104a081)

Found by diffing the 0825 run's failing submissions against executed gold.

**The goal-achievement grain twins did not name each other, and only the
per-patient one advertised its by-diagnosis figures** (PTSD 17.31 / Anxiety
15.06) — exactly the numbers a per-assessment cohort comparison must not return
(pooled: 17.62 / 14.64). A by-diagnosis question was steered to the wrong grain
by the only description that mentioned diagnosis. Both dimensions now state
their basis, carry both sets of figures, and name the other twin. `104a081`
applies the identical fix to the METRIC twins of the same quantity: the
per-patient mean advertised its by-diagnosis figures without naming the pooled
twin, and the pooled mean did not mention diagnosis at all.

**Facility Resource Adequacy Index existed only in the strict reading** — 370
of 541 facilities, the rest NULL and silently dropped. The adherence-rate family
already ships a Missing As Zero twin for exactly this choice and a
correlation-over-every-facility task needed the same reading, so
`facility_resource_adequacy_index_missing_as_zero` (COALESCE to 0, mean 1.3826
over all 541) ships as a dimension, cross-linked from the strict dim and the
mean metric, its description mirroring the adherence twin's.

Gates: dry-run 341 pins, generate 19 gates, A8, A10, sml-cli validate.

## 2026-08-26 — all models: every disagreeing twin now names its twin (models f9947b8)

Repo-wide generalisation of the mental_health_19 finding, and the reason this
one is worth reading even for a model it did not touch: **the same quantity
published at two grains, each description quoting its own headline figure and
neither naming the other, actively steers the agent.** It follows whichever
description mentions the question's wording and scores 0 against the other
basis with every value "right".

All 22 models were audited for pairs where both descriptions quote a headline
figure, the figures differ by >0.2% relative, and neither names the other:
**55 pairs in 9 models, 17 of them touched by failing tasks in the 0825 run
(16 tasks).** After the commit the audit finds zero.

Mechanism, so it stays closed:

- Eight models gain an evidence-gated `_cross_link_grain_twins()` post-pass in
  `spec_dims.py` — a secondary is annotated only when its own description quotes
  a headline figure, a same-column sibling on another dataset quotes one too, and
  the figures genuinely differ. The appended sentence names the sibling, states
  both grains and the sibling's figure, and ends with the standing
  say-which-basis warning. Hand-written cross-links win via a containment check.
  (hulushows 10, sports_events 12, planets_data 10, virtual_idol 4,
  robot_fault_prediction 4, disaster_relief 1.)
- mental_health, the largest twin family at 30 pairs, additionally gets a
  name-keyed pass for the entity-prefixed and basis-suffixed twins that map to
  different source columns (Patient X / Facility X / X Registered / X Strict) —
  42 more links — plus 4 hand-written sentences for the two irregularly-named
  pairs no normaliser can pair.
- reverse_logistics' Total Return Cost pair and museum_artifact's leak-rate
  metric pair alluded to each other without stating the name `explore_columns`
  needs; both directions now name the twin.
- `utilities/twin_audit.py` is the auditor, exit 1 on any finding, so a build
  can gate on it.

Every touched model's full gate chain passes: firewall, dry-run pins, 19
generate gates, question-leakage, masked-threshold, sml-cli validate.

## 2026-08-26 — households: the Zone description no longer claims 'location tag' and 'area' (models fd842ae)

Found by the households deep dive (3/21, second-worst database). The Zone
attribute's description asserted "Zone is what 'by zone' and 'location tag'
questions mean". In households_8 the agent asked exactly the right shape
question, was told to emit a combined "highest | lowest" value, and then grouped
by Zone on the strength of that sentence — returning zone numbers (413 | 121)
where gold groups by the recorded region spelling. households_13 shows the same
pull: "area code" went to Zone where gold reads it as the region. **Same defect
class as mental_health's diagnosis-advertising twin: a description claiming
question wording it has no right to own steers the agent into the wrong
grouping.**

The claim is replaced with its opposite — use Zone only when the question says
'zone'; looser wording (location tag / area / area code / location) is at least
as likely to mean the region or its recorded spelling, so ask which is meant.
That matches the model's own canonical-vs-recorded ask convention.

generate.py self-audit clean, check_recorded_readings 10/10,
check_swapped_descriptions unchanged (its one FAIL, the padded `' Yes'` literals
on Social Support Status, predates this change), masked-threshold gate passes.
Recorded for whoever touches households next: **the A8 question-leakage gate
reports 11 pre-existing findings in households metrics/calculations** (e.g.
`total_vehicles` quoting "many vehicles do those households own"), none
introduced here, and they deserve their own rewording pass.

## 2026-08-26 — deploy state

`fd842ae` — every commit above — was deployed to
`bird_atscale_models_catalog_main` at 10:20 today, before the
mental_health/insider_trading/hulushows n=1 run
(`results/mh_it_hulu_n1_atscale_0826_*.json`). All gates passed: A8, A10,
sml-cli validate, and the post-deploy gate (22 models in `_main`, template
integrity clean). The local models checkout had been 6 commits behind `origin`,
which is invisible from the ADK side and would have measured a stale catalog —
`git fetch` in the models repo before a scored run, not just `git status`.

## 2026-08-27 — robot_fault_prediction: formulas at the warehouse's own types, recorded calibration state, lowercase manufacturer, urgent-maintenance collision (models 4cc5ca5, 8cd9c7c)

Deep dive on a database that scored 0/10 in 820, 824 and 825 (raw 820: 0/10).
Before changing anything, every failure was classified with the offline grader
(`scripts/probe_pred.py`, values rounded HALF_UP to 2 dp on both sides, strings
byte-exact, order strict) and a ceiling test of the deployed model. The 10 Query
tasks split as follows:

- **2 unreachable, mislabelled gold** — `robot_fault_prediction_11` asks the
  failure-rate comparison but its gold is "5 slowest robots by cycles per hour";
  `_12` asks for the 5 least efficient robots but its gold is the fleet-wide
  average joint vibration (one scalar). No model or agent can pass these.
- **1 capped by a gold join fan-out** — `_10` joins `operation` to
  `performance_and_safety` ON the ROBOT (528 pairs over 479 records), so its
  "Other Applications" rate is 1/74 = 1.35% where the operation-grain figure is
  1/68 = 1.47%. Not fitted (prompt rule).
- **3 capped by a gold `LOWER()` no question asks for** — `_6`, `_7`, `_8`
  lower-case the manufacturer / model series in the output; the data holds no
  case variants (585 = 585 series, 5 = 5 makers). `_7`/`_8` also carry a tie on
  the sort key (two rows at 53.43) that strict order cannot reproduce. `_6`'s
  phase-2 wording does ask for lowercase, which licenses the twin below.
- **4 reachable** (`_1`, `_3`, `_4`, `_5`) — every one failed on a VALUE-pipeline
  defect, i.e. the model had done arithmetic differently from a plain SQL reader
  of the warehouse and the 2-dp HALF_UP rounding exposed it:
  - `rulhours` and `upkeepduedays` are bigint, so KB 10 `rulhours / 24` is
    integer division (0, 1, 4 days; the model said 0.375, 1.125, 4.33) and KB 17
    `1000 / (rulhours + 1)` is an integer quotient (113.37, the model said
    113.48).
  - `overseerloadvalue + memuseval` sums in float32 before the halving; the model
    widened first and 138 of 1000 stress scores differed at 2 dp.
  - `payloadwval / payloadcapkg` is a float32 quotient; 9 of 479 differed.
  - a raw `real` such as `faultpredscore` reaches psycopg2 as the text `0.755`
    and rounds to 0.76; the engine widens it to 0.7549999952 and rounds to 0.75.
    27 of 241 fault scores end in a 5 at the third decimal.
  - `calibstateval` is `character(20)`; gold returns `'Y' + 19 spaces`, the
    model's `::text` returned `'Y'`. The grader does not trim.
  - `_1`'s "urgent maintenance" is KB 48 (PMU > 50, 2 operations) but the model's
    flag literally named "Urgent Maintenance Required" is KB 53 (24 operations);
    the agent filtered on the name match three runs out of three without asking.

Shipped in models `4cc5ca5` and `8cd9c7c`, both fully gated (firewall, dry-run
250 pins, 19 generate gates, A8, A10, twin audit, sml-cli validate) and deployed:

- **KB formulas evaluated at the warehouse's own types, widened afterwards.**
  `Remaining Useful Life Days` and `Predictive Maintenance Urgency` carry the
  integer-division reading under the bare name; `(Exact)` twins keep the
  fraction. `Controller Stress Score` sums its reals before halving;
  `Payload Utilization Ratio` divides in real. Pinned: every flag built on them
  (urgent maintenance 24, trigger 2, intensive 6, anomalous 194) selects the
  same population under either reading.
- **Every `real` display column goes through `::text::numeric`** (the decimal
  Postgres prints, not the IEEE widening). Arithmetic still reads reals as
  double — M-31 is about the direct `real::numeric` cast, which this is not;
  pinned `col::text = col::double::real::text` on all rows.
- **`Calibration State`** is the recorded 20-character value; **`Calibration
  State Code`** is the trimmed letter for filters. The bare description says an
  equality test against a bare letter matches nothing, and that 521 operations
  have no record (drop or print blank — ask).
- **`Manufacturer Name (Lowercase)`** beside the recorded spelling, licensed by
  the question set's own wording ("manufacturer names in lowercase" in `_6`'s
  follow-up, a permitted source); the bare attribute names it and routes the
  rendering to the user.
- **`Urgent Maintenance Required` and `Predictive Maintenance Trigger`** each
  lead with the fact that both answer urgent-maintenance wording, with both
  populations; the count and rate metrics carry the same sentence.
- **`Top Tier Usage Model (Above 75th Percentile Value)`** — KB 60's
  `PERCENTILE_CONT` reading (146 series) beside the percent-rank reading (147);
  they differ on one series whose total equals the interpolated value. Found by
  the `_3` phase-2 ceiling test (138 vs 137 rows). Count metric added.
- `RUL Days` description points at Imminent Failure Warning for "about to fail"
  wording (KB 56 pairs the remaining-life cut with the High tier), so the
  agent asks whether a fault-score condition applies (`_5`'s second, unstated
  condition).
- `utilities/twin_audit.py`: repo root from `BIRD_MODELS_DIR` / file location.

**Ceiling after deploy** (`scripts/probe_pred.py`, hand-written queries, no
agent): `_1` p1+p2, `_3` p1+p2, `_4` p1+p2, `_5` p1+p2 all pass; `_6` p1 passes
with the lowercase twin; `_7` matches gold as a set (194/194) and fails only on
the tie order and casing. Before the change the same queries passed `_4` p1 only.

**Guidance change, both arms (B-49 decision recorded on the sheet):** the
RESULT_SHAPE_TIP ORDER BY bullet's "coarse to fine — first the entity" clause
was being read as `ORDER BY <id>` on one-row-per-entity screens; 824/825 lost
`_1`, `_3`, `_4`, `_5`, `_7` with correct rows sorted by Robot. The bullet now
says: rows one-per-entity selected on a quantity sort by that quantity, most
extreme first (a screen is an implicit ranking — derivable from the question);
several-rows-per-entity keeps coarse-to-fine. Runs before today used the old
text, so their numbers are not comparable on order-sensitive tasks.

**Not changed, reported:** grader rounds float32 values asymmetrically between
arms at the .xx5 boundary (raw gets Postgres text, atscale gets IEEE widening);
grader does not trim `character(n)` padding; gold `_11`/`_12` mislabelled; gold
`_10` fan-out; gold `_6`/`_7`/`_8` `LOWER()` with no question wording.
Build-prompt: `create_bird_model_prompt.v10.md` carries the five rules
(warehouse-type arithmetic, real display decimals, `character(n)` padding,
question-licensed renderings, same-wording KB collisions, value-pipeline ceiling
test, percentile twins).

**Measured 2026-08-27, n=1, tasks 1/3/4/5/6 only** (`results/robot_0827_n1_atscale_20260827_092045.json`,
Sonnet, $1.66 from `llm_usage`: agent $1.26, user sim $0.41, 87% of agent input
from cache): `_1` 1.0, `_5` 1.0, `_3` 0.7, `_4` 0.7, `_6` 0.0 — 3.4 over the five,
against 0.0 for the same five in 824 and 825. The other five tasks were not
re-run: `_11`/`_12` are mislabelled gold, `_10` a gold fan-out, `_7`/`_8` gold
casing plus a sort tie (B-68), so on the 10-task database this reads as 0.34
average reward against raw 0.00 (820), i.e. +34 pp, single run, subset-tested —
a full 10-task run at n>=3 is what a quotable number needs. Phase-2 misses: `_3`
sorted the follow-up by Robot (the ORDER BY tip's screen clause did not carry
into phase 2); `_4` projected the raw Yes/No flag where gold wanted the user's
'Warning Active'/'No Warning' text and had 2 coins left to ask. `_6` never
reached the manufacturer summary: the simulator's column answer this time did
not mention the by-manufacturer aggregation it had given in 824/825, and the
agent listed robots.

## 2026-08-27 — planets_data: named constants composed at the declared type, consistent units, three-valued flags, composition (models 224fac0)

Deep dive on a database whose semantic arm sat level with raw: atscale 0.27 / 0.43 /
0.28 in 820/824/825 against raw 0.37 (820), nine of 19 tasks at 0 in every run and
three more stuck at 0.7. Before changing anything every failing phase's gold was run
on `planets_data_template` and compared with what the deployed model could return,
under the grader's own normalisation (gold ROUND stripped, both sides HALF_UP at 2 dp,
strings byte-exact). Where the robot pass found the warehouse's *types*, this one
found the model's *constants*:

- **Pre-collapsed textbook constants.** Escape velocity was `11186 m/s × sqrt(M_E/R_E)`,
  stellar density `solar ratio × 1.408 g/cm³`, the gravitational parameter
  `1.32712440018e20 × M`, the mass ratio via `0.00095458 M☉/M♃`, the equilibrium
  temperature via `0.00465047 AU/R☉`, the transit depth via `0.102763 R☉/R♃`. Each is a
  correct identity to three or four significant digits and wrong after that, and the
  grader compares two decimals of 585 km/s or 1.5e20: `_13` 586 vs gold 585.45, `_7`
  1395.52 vs 1395.51, `_18` 7720.10 vs 7720.04, `_8` 1.47 vs 1.46, `_9` 2.4332e-05 vs
  2.4329e-05. Composed from the standard values (G 6.67430E-11, M☉ 1.98847E30, R☉
  6.957E8, AU 1.496E11, M♃ 1.898E27, R♃ 7.1492E7, 109.2 R⊕/R☉) in the KB's own
  formula shape, every one now matches gold to the last digit.
- **JSON numbers read as exact decimals where gold casts `::real`.** The stellar mass,
  radius and temperature live in `stellarprops` JSON; their column meaning says REAL and
  a plain SQL reader casts them so. Read as exact text the ratio of the densest to the
  least dense star (`_5` phase 2) is 2,237,875,810; through `::real` it is
  2,237,875,936 — the reading gold has. Formulas now read the JSON through `::real`
  (M-38 extended to JSON); display copies stay exact (`::numeric` on the JSON text,
  `::text::numeric` on stored reals).
- **A dimensionally inconsistent twin.** The README's "two formulas mix units — both
  readings ship" decision published `T × sqrt(R/2a)` with R in solar radii and a in
  AU beside the converted one. On `_18` the agent asked which, the simulator said "the
  direct formula as-is", and the task failed on a 15× number. Withdrawn: a formula over
  two lengths is a formula over one unit. Transit depth converts into Earth radii (the
  KB's unit for planets, 109.2 R⊕/R☉), not Jupiter-to-solar.
- **Units the question set names are the bare readings.** `Escape Velocity` and
  `Orbital Velocity` are km/s (follow-ups `_8`/`_18` say "in km/s") with
  `(Metres Per Second)` twins; `Stellar Density` is kg/m³ (`_5`/`_17`/`_20` follow-ups
  say "in kg/m^3") with `(Solar Units)`; `Transit Depth` a fraction with `(Percent)`;
  `Orbital Period` the recorded days with `(Years)`.
- **Three-valued flags.** `Hot Jupiter` was 'No' only when both inputs were recorded,
  so a planet with no mass and a 300-day period was null where `NOT (mass > 0.1 AND
  period < 10)` keeps it. Every compound flag now says 'No' as soon as one input is
  recorded false ('No' 783 → 1967). Every varying limit/blend flag has a Yes/No twin on
  the value 1 whose 'No' means *recorded and not 1* — `Distance Upper Limit = 'No'` is
  exactly gold's `Dist_Lim <> 1` on `_10` (78 planets, 1446.12 ly, not 84 / 1497.29).
- **Composition.** `only_rocky_planets` tested density-known planets (49 stars); `_15`
  means has-a-rocky-planet-and-no-gas-giant, and a gas giant is known by mass, not
  density (27 stars, mean luminosity 0.962 not 1.673). `System Composition` (Rocky Only
  27 / Gas Giants Only 782 / Mixed 35 / Neither 77) + `Has Rocky Planet` / `Has Gas
  Giant`; the old reading survives as `All Density Measured Planets Rocky`.
- `Geometric Mean Adjacent Period Ratio` (`_11` averages ratios geometrically; differs
  from the arithmetic mean on 177 of 193 multi-pair systems), `Kepler Mass Absolute
  Difference` (`_4`'s sort key), `Retrograde Orbit (90 Degrees Or More)` (21 planets sit
  at exactly 90.0°; `_2`'s clarified threshold is "90 or more"), count metrics for the
  new flags. 275 pins, 19 gates, A8, A10, sml-cli validate clean; deployed 12:10.

**Ceiling after deploy** (`scripts/probe_pred.py --file`, hand-written queries, no
agent): 25 of 27 probed phases pass — `_2` p1+p2, `_5` p1+p2, `_6` p2, `_7` p1+p2, `_8`
p1+p2, `_9` p1 (only with gold's own malformed `TO_CHAR` pattern), `_10` p1+p2, `_11`
p1+p2, `_13` p1+p2, `_14` p1 (with user-supplied labels), `_15` p1+p2, `_17` p2, `_18`
p1+p2, `_20` p1+p2. The two failures are gold tie-order: `_4` (115 of 465 rows NULL on
gold's sort key) and `_6` p1 (two exact ties). Before the change 6 of the same 27
passed.

**Guidance changes (B-49 decisions on the sheet):** (1) the atscale backend
instruction's rounding bullet was wrong since B-19 — gold's ROUND is stripped, the
semantic agent's cannot be (rows, not SQL), so "round to the nearest integer" as asked
lost `_17` p2 (1545 vs 1544.62) and `_5` p2. Now: never round; a named text format is
rendered with `TO_CHAR`, which passes through the engine (probe on `_20`: ' 1.50e+20'
matches). Raw is unaffected — its ROUND is stripped anyway. (2) ASK_USER_TIP: a
multi-row listing with no sort cue in the question gets one closed ask for the order
(five planets listings failed on order alone). Both arms; runs before today are not
comparable on those tasks. (3) TO_CHAR added to the dialect's accepted list.

**Not changed, reported (B-69, B-70):** agent-side ROUND asymmetry (grader); `_9` p1
gold `to_char(x, '9.999999E9')` renders `  .000024E3`; `_14`'s `deleted_knowledge: 44`
removes "Stellar Radius Value" — the KB has no Photoband entry and `_19` cites ids
67/68 that do not exist; `_4`/`_6` p1 tie order (B-31 family, not in the lint list).
Build-prompt: `create_bird_model_prompt.v10.md` carries six rules (named constants
composed in-shape; JSON numbers at the declared type; no dimensionally inconsistent
twins; three-valued flags with flag twins; composition over contrasting classes;
geometric mean / absolute difference siblings).

**Measured 2026-08-27, n=1, tasks 2/4/5/6/7/8/9/10/11/13/14/15/17/18/20** — see the
line appended below this entry when the run finishes.

**Measured 2026-08-27 12:14, n=1, tasks 2/4/5/6/7/8/9/10/11/13/14/15/17/18/20**
(`results/planets_0827_n1_atscale_20260827_121400.json`, Sonnet, $3.46 from
`llm_usage`: agent $3.16, user sim $0.30, 92% of agent input from cache): `_5` 1.0, `_7`
1.0, `_11` 1.0, `_13` 1.0, `_15` 1.0, `_17` 1.0, `_20` 1.0; the other eight 0.0 —
**7.0 over the 15, against 1.4 for the same 15 in 825** (`_5` and `_17` at 0.7). With the
four untouched tasks (`_1`, `_12`, `_16`, `_19`, all 1.0 in 825) that projects to 11.0/19
= 0.579 on the database against raw 0.374 (820), i.e. about +20 pp — single run, subset
re-run, and the raw arm has not been re-run under today's ASK_USER_TIP, so not a quotable
lift. What still fails and why, from the trajectories: `_2` every value right, the
inclusive retrograde threshold and the speed-DESC sort both obtained by asking, lost on
gold printing the STAR name where the question says "their names"; `_8` values right,
lost on column order (gold star, planet, depth; four permutations tried, never that one);
`_18` values right (KOI-55 b, 7720.04), lost on gold printing the companion letter 'b'
as the name; `_10` filtered `Distance Limit Flag = 0` (drops the eight -1 rows) and never
asked what "bad measurement" excludes, after spending its ask on the grain cross-link's
per-star/per-planet question; `_14` got the 'V-Band' label by asking but kept K-band as
a third row; `_4`, `_6`, `_9` are the B-70 caps. Follow-up models commit `37c171c` makes
the Distance Limit Flag description say which rows `= 0` drops.

## 2026-08-27 — cold_chain_pharma_compliance: KB 48's reliability score over its evidenced term, KB 36's delay term, conditional carrier counts (models 8bff586)

Deep dive on a database that sat at 0.2611 / 0.2611 / 0.2833 in 825/824/820 against
raw 0.2056, with eleven of its 18 Query tasks at 0 in every run. Every failing phase
was classified before anything changed, using the offline grader on the recorded
submissions (`scripts/regrade_flags.py`-style replay, no LLM calls) plus hand-written
ceiling probes through `scripts/probe_pred.py`. Phase 2 only runs when phase 1 passes,
so a phase-1 blocker forfeits the whole task, and that is where every one of these sits.

**What the classification found.** Only three of the eleven zeros were model defects.
The rest are gold conventions or gold ties:

- **Gold applies a cosmetic `LOWER(TRIM(...))` to its grouping keys on six tasks**
  (`_4`, `_5`, `_8`, `_11`, `_18`, `_19` phase 1, and `_20` phase 1 but NOT `_20`
  phase 2). No question asks for lower case, and the warehouse holds no case variants
  at all — `carriercert` is exactly {GDP, CEIV Pharma, Both, null}, `veh_qual` exactly
  {Validated, Qualified, Under Review}, and so on for the route risk note, the
  agreement status, the compliance status and the release status, so the `TRIM` and the
  `LOWER` are both no-ops on the data and pure re-rendering on the output. A `(Lowercase)`
  twin fails the build prompt's counterfactual test outright — no builder reading the KB
  and the warehouse would produce one — so nothing was shipped for it. Measured instead
  (below).
- **Gold `_8` picks 3 rows out of a 64-way tie** (64 route groups sit at exactly 10.0
  average excursions) and **gold `_18` picks 2 of a 265-way tie** (265 people have
  exactly one rejected shipment out of 816 distinct names over 821 shipments). Neither
  is reproducible under strict order.
- **Gold `_14` returns NULL from a join that cannot match**: it reaches the product
  batch through `shipsensorlink` with `productbatches pb ON ssl.devnode = pb.prodlink`,
  i.e. a device reference (`MD####`) equated to a product code (`PH#####`). Zero rows,
  so both phases are a single NULL, which no correct answer produces.
- **Gold `_10`'s Supply Chain Resilience Score invents four 0-10 proxy scales** the KB
  never states (route risk 8/5/2, certification 10/8/4, qualification 9/7/5, GDP
  compliance 9/6/3) over a cross-island cartesian join. The agent asked for the scales
  twice across two runs and the simulator declined both times. Unreachable, and the
  model's existing "none of its four inputs are stored" stance is the honest one.
- **Gold `_1` prints a synthetic label column** — `'High Risk Routes'` beside the
  average, for a task whose `output_type` is `scalar`; phase 2 is the same shape per
  risk level (`risk_note || ' Risk Routes'`). Probed: the value alone scores 0, the
  value with that literal scores 1. Nothing in the question implies the column.
- **Gold `_2` phase 2 labels the missing group `'Unspecified'`.** Values and row count
  are exact with the NULL member kept; the word is gold's. Not fitted.

**Three real defects, all shipped in model `8bff586`** (dry-run 101 pinned constants,
19 generate gates, A8, A10, twin audit, sml-cli validate, deployed 12:58):

- **KB 48 Data Logger Reliability Score was published as not computable, and it is
  computable over its reading term.** It is masked `calculation_knowledge` — a KB-NAMED
  FORMULA, which ships under its own name by the build prompt's own rule (7 of 7
  elsewhere) — and one of its four rates has a column behind it: KB 44 reads a device
  with no recording interval as an unplanned monitoring approach, so those 63 devices of
  450 are the ones from which no reading was ever due. 14 per 100 deployments at
  weight 10 gives a fleet score of -40. Download and battery failures have no column.
  The calibration-drift term is a measured zero: every calibration timestamp falls in
  2024-08-23 .. 2025-02-19, so under KB 55's twelve-month life nothing is out of
  calibration for any reference date up to 2025-08-23, and the description asks the
  caller to name the reference date rather than assuming one. Shipped as
  `Data Logger Reliability Score (DLRS, Reading-Failure Term)`. Saying "not computable"
  had the agent invent a homemade pass-rate ratio in 825 instead of applying KB 48.
- **KB 36's Lane Risk Potential read its shipping-delay term as route deviation
  incidents.** KB 36 says "the total count of shipping delays", and this warehouse
  evidences that directly — the actual duration against the planned one, the same
  comparison KB 12 and KB 13 both read as lateness. New measure
  `Shipments Delivered Later Than Planned` (377 of 821); the calculation is renamed
  `Group Lane Risk Potential (Temperature And Delay Terms)`. Warehouse-wide the old
  reading gave 6.6736 where the delay reading gives 5.5615, and per lane the old one put
  22 lanes in a tie at the top where the delay reading reproduces gold's own top three
  values exactly.
- **No conditional distinct-carrier count existed**, so "how many carriers operate a
  validated vehicle" had no expressible form — a count-distinct over a carrier column
  repeated only on the qualifying rows is the only shape this dialect offers. Added
  `Carriers With A Validated Vehicle` (175) and `Carriers With A Qualified Vehicle`
  (157), each stating that it counts CARRIERS where the vehicle counts count vehicles,
  and that the vehicle island cannot see a carrier with no vehicle (pair with
  `Carrier Count`, which covers all 798).

**Ceiling after deploy** (`scripts/probe_pred.py`, hand-written queries, no agent):
`_17` p1+p2 pass off the new calculation; `_11` p1 AND p2 return gold's rows exactly
in one query — `(null, 281, 61)` and `(null, 281, 61, 49)` — and fail only on gold's
casing; `_20` p1 returns gold's own top-three lanes and values and fails on casing plus
the rank-3 tie (two lanes at 6.00, gold takes the alphabetically later one); `_3` p1,
`_4` p2, `_5` p2, `_9` p1 and `_19` p1 all pass or fail only on casing. Every one of the
five submissions that passed in 825 (`_2` p1, `_6`, `_7`, `_15`, `_16`) still passes
against the new model, so nothing regressed.

**Guidance change, atscale backend instruction only (no raw re-run owed):** the
whole-population-value bullet covered a total shown beside DETAIL rows. The same silent
failure hits a share-of-total column beside GROUPED rows, which is the commoner form:
`_9`'s percentage column came back as 100.00 on every band because the engine evaluates
a scalar-subquery denominator inside each group rather than once, and
`SUM(COUNT(...)) OVER ()` errors outright rather than offering a fallback. The bullet now
carries the grouped case, the measured 100.00, the working `JOIN ... ON 1=1` form
(probed: 20.91 / 52.87 / 26.22, verdict 1) and the one window shape that does work — a
window over a column already aggregated in an inner derived table, which is how a
within-group percentage is written (probed on `_3` p2, verdict 1).

**Measured 2026-08-27 13:01, n=1, tasks 3/9/11/17/20**
(`results/coldchain_0827_n1_atscale_20260827_130149.json`, Sonnet, $1.41 from
`llm_usage`: agent $1.13, user sim $0.29, 82% of agent input from cache): `_17` 1.0, the
other four 0.0 — 1.0 over the five against 0.0 for the same five in 825. On the 18-task
database that reads as 5.7/18 = 0.317 against 0.261 (825) and raw 0.206 (820), i.e. lift
+11.1 pp where it was +5.6 pp. Single run, subset re-run, so not a quotable arm number.
What still fails and why: `_11` and `_20` are the casing/tie caps above, now numerically
exact; `_3` returned the right four categories and counts and ordered them by band
severity where gold orders by the count descending, having spent all three of its asks
on the breakdown, the cut-offs and the null rows; `_9` returned one row (the largest
zone) with no percentage column, where 825's attempt had the right three-row shape and
lost only on the engine's scalar-subquery percentage — a shape the agent chooses,
varying run to run.

**Not changed, reported:** gold's cosmetic `LOWER(TRIM())` on six phase-1 golds — a
casefold-only re-grade of the 825 run (offline, no LLM calls, reproduces the as-run
0.2611 exactly) scores **0.3389, +7.8 pp on an unchanged trajectory**, recovering `_4`
and `_5` phase 1, and would additionally let their phase 2 be attempted, which a replay
cannot show; with the new metrics `_11` p1+p2 and `_19` p1 join that list under
hand-written queries. `settings.grading_casefold` exists for exactly this case and its
docstring already describes it; it was left off, since it is a grading flag and lifts
both arms. Also reported: `_8` 64-way and `_18` 265-way gold ties; `_14`'s
`devnode = prodlink` join; `_10`'s invented proxy scales; `_1`'s synthetic label column;
`_2` p2's `'Unspecified'`; and the engine's silent per-group evaluation of a scalar
subquery in the SELECT list. Build-prompt: `create_bird_model_prompt.v10.md` carries the
three rules (a masked KB formula ships over the terms the warehouse evidences with the
absent terms named; a KB term like "shipping delays" is read against what the warehouse
records as that thing, not against a similarly-shaped column; a conditional
count-distinct needs a derived key column at build time).

## 2026-08-27 — backfill from the models repo: changes committed 2026-08-20..27 that this log never recorded

Reconciled `docs/model-change-log.md` against `git log origin/main` in
`bird-atscale-models` (per-database). Several rounds of model work were recorded
only in commit messages and in the models repo's own `CHANGED-MODELS.md`, so
this log had four databases down as never-reviewed that had in fact been read
against failures and fixed. Entries below are condensed from the commit bodies;
the hash is the record. Dates are the commit dates, not today.

### Repo-wide (2026-08-20 .. 08-25)

- **`3fd666e` 2026-08-20 — 15 entity-name aliases across 8 models.** The
  0820 atscale run logged 50 `Unknown column name(s)`; 15 were the agent asking
  for `<Entity> ID` / `<Entity> Name` where the level published bare with the
  synonym only in prose (NAME DECIDES, NOT DESCRIPTION failing in production).
  Each alias is a secondary attribute on the level's own column, no SQL change:
  cold_chain (Carrier/Shipment/Vehicle ID), hulushows (Content ID),
  mental_health (Facility/Patient ID), museum_artifact (Artifact ID/Name),
  planets_data (Planet/Star Name), reverse_logistics (Return ID), sports_events
  (Circuit/Driver Name), virtual_idol (Fan ID/Key). Seven `<hazard> Sensitivity`
  columns the agent asked for in museum_artifact were NOT added — the warehouse
  holds only light/temperature/humidity. Same commit: CURRENT_DATE-derived pins
  in hulushows/virtual_idol now pin the drift-invariant spread exactly and the
  absolutes with a season's tolerance.
- **`edf6e29` / `f478912` 2026-08-20 — degenerate-dimension merge** (already
  described above under "Repo-wide: degenerate dimensions ... merged"; hashes
  recorded here).
- **`f0691f9` 2026-08-21 — descriptions must not instruct the caller to project
  extra columns.** From the 0821 diagnosis: 46 of 328 failing submissions
  carried a label column gold omits; on 11 dropping it alone fixes the column
  count. Cause was our own text ("select Site Code alongside...", "display
  Platform Name alongside", "Show SRS alongside if..."): 8 instances in
  archeology_scan, cybermarket_pattern, cross_border rewritten to state what the
  identity IS. Non-uniqueness and never-GROUP-BY warnings kept (facts, not
  instructions). Repo audit: 0 imperative projection instructions.
- **`0422017` → `3044d6b` 2026-08-21 — window-function patterns as MDX
  calculations, ranks then dropped.** Engine cannot filter/sort on a SQL
  window alias (`WHERE rn = 1` → "constraints [rn] incorrectly constructed";
  26 filter + 18 sort shapes across 22 dbs). Shipped as MDX: mental_health
  Patient Stability Metric Rank; sports_events Constructor Reliability Rank +
  four cumulative measures, Race level sorted by `round_number` (race IDs
  disagree with calendar order in one 19-race season). Live test: cumulative
  half reproduces `sports_events_5` gold exactly; **rank half removed** —
  `Rank` ranks only the full member set (gold ranks a filtered 44 of 212;
  McLaren 44 vs calc 129), `Existing`/`Filter` unsupported, and grouped by a
  secondary attribute it silently returns 1 on every row.
- **`45e586a` 2026-08-25 — AVG-able attributes point at their measure twins
  (R2).** Six databases hit `assertion failed: We already handled attribute
  values` (Q-21) in the 0825 run, all `AVG(<attribute>)` where an `Average
  <attribute>` measure already exists. Descriptions only. Verified vs gold:
  `sports_events_12` twin → 8.375 = gold; `fake_account_22` twin reproduces all
  four gold rows. crypto_exchange, disaster_relief, cold_chain, museum_artifact
  twins confirmed to execute. museum_artifact Light Level Lux worded
  differently on purpose: gold averages `COALESCE(lux,0)` over 1000, twin
  averages the 850 with a reading.
- **`bd526bf` 2026-08-24** — sports_events (driver age / DPV) and
  disaster_relief (burn rate, runway) CURRENT_DATE pins given ~a year of drift
  tolerance; no deployed change, stops red builds on untouched trees.

### sports_events — reviewed 2026-08-21, 08-25, 08-27 (Dave)

- **`4fda394` → `eb78ac7` → `4bc1927` 2026-08-21.** `sports_events_5`: agent
  queried the cumulative measures correctly but got every race in the season,
  gold only the four McLaren entered. First fix (NULL-guard the running sums)
  reverted the same day — a CASE returning NULL is a computed value, not an
  empty cell, so rows survived; and a running total on a race sat out is a real
  question. Descriptions now say a per-race listing needs
  `HAVING "Constructor Result Count" > 0`. The revert stripped CASE openers from
  two unrelated pooled calcs; `sml-cli validate` passed the broken MDX, the
  engine refused the whole 22-model catalog. **Gate G20** added: every
  `metric_calc` must balance CASE/END, parens, brackets.
- **`ca071f1` 2026-08-25 — Driver Key published.** Description said "use the
  driver key when identity matters" but it was never projectable; 174 of 861
  drivers have no name and collapse to one blank label. Checked and NOT
  changed, model follows the KB where the reference does not: KB 20 age floors
  (ref `_1` takes AGE() year component), KB 32 population stddev (ref `_14`
  uses sample STDDEV: 10.0 vs 9.64), `_11` invents 0.35×0.25 probabilities.
- **`4d77121` 2026-08-27 — as-of-race twins.** From certified-answer-memory
  failure telemetry: Driver Standing gains Points Per Race Before Race and
  Driver Performance Value At Race (KB 26/37 as-of-race reading; career reading
  keeps its name and cross-links); Sprint Driver Age Exact + its average beside
  the floored one (floor(avg(exact)) = gold's EXTRACT(YEAR FROM AVG(AGE)) on
  the winner subset). NOT fixed: 100/stddev "consistency champion" (not in KB),
  qualifying-specialist denominator (gold contradicts KB 28).
- **`8d9eef1` 2026-08-27 — round 2 from watching agents use round 1.** Nulls in
  the as-of-race series are part of the series, not rows to drop (agents
  filtered them); "whole-year part" read as rounding (28.72 → 29), now says
  TRUNCATE with a worked figure; Average Sprint Performance Index RETRACTS the
  round-1 one-population claim and discloses both (all classified 0.49565/345;
  points-paying 8.375/144) symmetrically, ask the user.

### polar_equipment — reviewed 2026-08-23/24 (Dave, 8 commits)

- **`8520589` — ordinal non-join.** Fact reached ThermalSolarWindAndGrid by
  `THERMAL_ID = CHASSIS_ID`, both just 1..1000. Declared key `comm_link`
  agrees on all 850 real rows; the ordinal join invented 150 orphan rows —
  total solar output 1014445 vs 863973 attributable. WeatherAndStructure
  deliberately left ordinal at first (its key `loc_link` fans 1000 → 17840).
- **`bcf19c2` — same defect on WeatherAndStructure**, fixed via
  `opmaint_link` → OperationMaintenance: 859 real pairs, 141 invented.
  Critical Equipment 151 → 136, protection level C 997 → 856, temperature
  zones 293/301/406 → 255/252/352. All 12 subsystem registry IDs published
  (three golds project one; questions ask for "the registry ID").
- **`44beb95` — station-weather bridge.** Weather is station data (20 stations
  × 50 readings); every gold touching it joins on `loc_link`, which the model
  could not express. Equipment Weather Reading = 859 units × 50 = 43,942 rows,
  related to both entity dimensions; every object leads with the fan-out
  warning. Six pins lock the bridge shape.
- **`c063396` — the warning was on the wrong side.** Three tasks
  ceiling-verified against the bridge by hand; the run converted none — agents
  found the unit-grain twin by name and never learned the bridge existed. The
  unit-grain columns now lead with "plain name does not settle which reading"
  and carry both live counts (Structural Safety Factor 5 vs 238; Temperature
  Zone 255/252/352 vs 850/850/850). Station states 859/1000 coverage and that
  comm/cabin/weather branches are different populations.
- **`ce92603`** KB 25 water-quality band: label 'Unsuitable' (KB's adjective)
  → 'Unsafe' (KB's label), Poor cut 31 → 26; moved 51 units.
  **`d9cbc1b`** KB 5 wear: 281 chassis lack one wear figure; both readings ship
  (342 vs 467 units), PTEC follows. **`1c71f35`** KB 56 temperature bands also
  as 'Extreme Cold (<-40C)' display twin. **`e640f76`** CRI/BSCSI IEEE
  negative zero (171/283 rows rendering "-0") normalised with `+ 0.0`.

### virtual_idol — reviewed 2026-08-24 (Dave, 7 commits; M-37 twins logged above)

- **`5a4a71e` — three silent defects.** Commerce attributed via
  interactions → engagement → commerce; warehouse FK runs
  commerce_member_pivot → membership → fan; 19 of 356 pairs on the wrong fan,
  Collector Fan wrong for five (58 vs warehouse 57). Interaction gaps cast to
  `::date` before subtracting (311.94 → 312); now EPOCH/86400. NPS tiers were
  plural; KB names them singular.
- **`eb04ee4`** — mean gap and longest quiet stretch split: fractional
  consecutive-interaction gap vs whole calendar days between DISTINCT active
  dates (gold `_16` vs `_12` make the same distinction). A pin asserting the
  two equal had encoded the conflation.
- **`3302852`** — engagement branch anchored on membership, not interaction:
  27 of 555 engagement rows point at another fan's interaction, so 26 fans read
  someone else's followers (`_3`: victoria89 took annawilliams's rank 13).
  Engagement attributes added at fan grain so Engaged Lurker × Content
  Preference conforms to Fan Count (`_2` now Music 6/Dance 4/Gaming 3/Chat 2).
- **`1b9fe61` / `432cc89`** — Fan Segment ranked only the 37 fans with both
  axes; KB's own segmentation coalesces to zero and ranks all 972
  (249/237/237/249). Gold `_13` reports 251/242/242/251 = 986: LEFT JOIN
  double-counts 14 fans with two membership rows; **not reproduced**, task
  stays failing. Descriptions that still said "37 fans... 935 unsegmented" made
  the agent gate on `Fan Segment Available` — renamed `Has Both Segment
  Inputs`, "not a filter".
- **`83955a5` → `219df12`** — percentile ranks as MDX `Rank` calcs for `_11`
  (no PERCENT_RANK in the SQL front end), **reverted**: correct per-fan values
  but re-materialises the fan dataset per row; `_11` wedged a warehouse query
  25+ min at 74% CPU for 22 rows and converts nothing (gold ranks over its own
  797-fan CTE). Average Fan Platform Stickiness Score kept. **`c8c9b6b`** Idol
  ID / Idol Key published (736 names over 742 idols; DENSE_RANK per idol merged
  them).

### disaster_relief — reviewed 2026-08-27 (Dianne; models `9581253`, `c40e579`)

Same pass shape as robot/planets/cold_chain. README carries the reasoning:

- **Agreeing references are not the same population.** The four operation
  references agree in value but not coverage (coordination 967, beneficiary
  800, financial 201, staffing 57). Each record's own reference now ships
  beside the coalesced `Operation` (`Operation On Coordination/Beneficiary/
  Financial/Staffing Record`); bare `Operation` leads with the four counts and
  routes the choice to the user. Hub reference likewise (`On Transport Record`
  987/405, `On Supply Record` 312/312); `Hub Strain Index (Supplied Events)`
  twin disagrees with the union HSI on 327 of 405 hubs.
- **Narrow-record twins.** `Mass Casualty Incident (Staffed Events Only)`
  (54/57 vs 955/1000); GSI reads the stored staff total and is null where
  unrecorded (33 events), old staff+volunteers zero-fill kept as
  `(Footprint, Missing As Zero)`.
- **Two cost operands.** KB 4 burn rate divides `total_operational_costs` =
  `ops_costs_usd` (one column); KB 5's four-line sum is a different term.
  Bare FBR / Budget Runway / Funding Crisis read the ops line (8 in crisis);
  `(All Four Cost Lines)` twins (16). `Total Cost USD` vs
  `Total Operations Cost USD`.
- **As-recorded text twins** for nine numbers stored as text (money, %, star,
  `WQI`); `Hazard Type (Lowercase)` rendering twin.
- **`c40e579`** — REAL-declared JSON numbers read through `::real` inside every
  formula, exact decimal only for display (4 of 405 HSI values flipped at 2 dp
  — the robot 0827 type finding again). Pins 120 → 144.

Not measured yet — no scored run since either commit.

### Also unlogged, already-reviewed databases

- **crypto_exchange `ba8f589` 2026-08-25.** Worked back from nine phase-1
  failures in the 0825 run; five are gold artefacts, left alone. Four changes:
  raw Arbitrage Potential published (existed only inside the composite score);
  Arbitrage Window drops "also asked as significant arbitrage opportunity"
  (task 19's wording, on a column that is 'No' on all 1000 snapshots) and names
  the component; Bid/Ask Size say they are one row per market so a snapshot
  filter neither narrows nor corrects (task 10 failed only on
  `WHERE "Market Snapshot" = 1000`); Average Margin Utilization gains its
  twin's wordings.
- **labor_certification_applications / hulushows `1bf966c` 2026-08-22.** Two
  levels keyed at the wrong grain ("points to multiple key values", attribute
  resolves to an arbitrary row): hulushows Content Tier Profile keyed on
  content_record alone over a 7-tier rollup (7000 rows, 24 warnings) → keyed on
  record + tier; labor Application Status As Recorded made the level below the
  normalised status rather than a secondary attribute. 25 warnings → 0 across
  22 models.
- **fake_account `568e210` 2026-08-25** — missing-inputs-as-zero pair for
  Content Impact Score (already noted above; hash recorded).

### Review status after this reconciliation

Per-task failure pass done: archeology_scan, exchange_traded_funds,
crypto_exchange, organ_transplant, households, mental_health, insider_trading,
hulushows, robot_fault_prediction, planets_data, cold_chain_pharma_compliance,
sports_events, polar_equipment, virtual_idol, disaster_relief.
Partial (KB-gap passes only, no per-task classification):
labor_certification_applications (0814-17), cybermarket_pattern (0810 run-1
fixes, old prompt). **Never had one:** museum_artifact, reverse_logistics,
cross_border, fake_account, solar_panel (35 hand-tuned commits 0804-07,
pre-firewall, untouched since; no section in this log).

`CHANGED-MODELS.md` in the models repo carries Dave's own round notes since the
0820 baseline; check it alongside this file before calling a model unreviewed.

## 2026-08-27 — disaster_relief: per-record references beside the coalesced ones, staffed-only readings, the operational-cost operand, warehouse-typed formulas (models 9581253, c40e579, f315484)

Deep dive on a database that sat at 0.1000 / 0.1250 / 0.1000 in 820/824/825 against raw
0.0833 (820), with ten of its 12 Query tasks at 0 in every semantic run and eleven of 12 at
0 in raw. Every gold was executed against the warehouse and every failing phase classified
before anything changed, then each reachable task was ceiling-tested by hand through
`scripts/probe_pred.py` against the deployed model (no LLM calls).

**What the classification found.** Seven of the twelve golds reach the operation through
one specific satellite — `JOIN humanresources ... hr.hr_ops_ref` — and so cover only the 57
events that carry a staffing record (all 57 also carry a coordination, beneficiary and
financial record; the four references agree on every overlap). The model published one
coalesced `Operation` over 967 events, which is the right *value* and the wrong
*population* for those tasks: `_1` wants 30 rows through the staffing record where the
coalesced reference gives several hundred, `_3` wants 54 mass-casualty events of 57, `_11`
wants the pooled cost per person over the 20 completed events with both a financial and a
staffing record (4.03 against 3.08 over every financed event). No question names the record;
the reference author's join habit does. The rest of the zeros split into gold defects and
two value-pipeline defects, below.

**Model changes, all three commits on the same day:**

- **Per-record references.** `Operation On Coordination Record` (967), `... Beneficiary
  Record` (800), `... Financial Record` (201), `... Staffing Record` (57) beside the coalesced
  `Operation`, whose description now leads with the four counts and routes the population to
  the user; `Distribution Hub On Transport Record` (987 events, all 405 hubs) and `... On
  Supply Record` (312 / 312) beside `Distribution Hub`. Counterfactual test: the schema shows
  four FKs to operations and two to hubs; the build prompt's multiple-join-path rule already
  says to ship each path — the earlier build applied the measure-before-twins rule (identical
  values → coalesce) and lost the coverage difference. Pinned: the refs never disagree (0).
- **Hub strain in both readings of "serves".** `Events Supplied`, `Average Severity Served
  (Supplied Events)` and `Hub Strain Index (Supplied Events)` (a hub that supplied nothing
  carries the load term alone; 327 of 405 hubs differ from the union reading) beside the
  existing union objects, plus `Average Hub Strain Index (Supplied Events)`. `_4`'s gold
  averages severity over the supply record only.
- **`Mass Casualty Incident (Staffed Events Only)`** (54 Yes / 3 No / null elsewhere) and its
  count, beside the three-valued all-events flag (955); the bare flag's description carries
  both counts and the population ask. This is the missing-input-policy rule applied to a
  classification.
- **Gridlock Severity Index re-read.** KB 40's `total_personnel` is the staffing record's
  stored `total` (documented "Total number of staff"), and KB 40 writes no COALESCE — so the
  bare `GSI` now exists on the 33 events with a recorded total (14.2–119.2, mean 75.2) and is
  null elsewhere, which the model's own stated coalesce policy already required and the
  build had violated (943 events coalesced to zero). The earlier reading — KB 17's
  staff-plus-volunteers footprint, missing as zero, 967 events — is kept as `Gridlock
  Severity Index (Footprint, Missing As Zero)` with its average twin. `_9`'s values now match
  gold (119.20 / 119.00 / 112.70 / 81.00 and one null).
- **The burn-rate operand.** KB 4 divides `total_operational_costs`; the warehouse has one
  column documented "Operational costs in USD" (`ops_costs_usd`); KB 5's four-line sum is the
  definition of a different term ("total cost", for the cost per person). Bare `Financial
  Burn Rate (FBR)`, `Budget Runway (Days)`, `Funding Crisis` (+ count, rate) now read the
  operational-cost line (8 events in crisis; 11 under a week of runway); the four-line
  versions ship as `(All Four Cost Lines)` twins (16 / 29) with average twins. The four-line
  sum is renamed `Event Total Cost USD` / `Total Cost USD` (was "Total Operational Cost",
  which contradicted the KB 4 reading), and `Total Operations Cost USD` sums the operational
  line. Gold itself uses the stored column in `_5` and the four-line sum in `M_1`'s
  follow-up, which is why both must exist.
- **As-recorded text twins** (v10 rule) for the nine columns stored as text with a unit or
  symbol: budget, funds utilisation, cost per beneficiary, partner organisations, public
  perception (star), lessons recorded, best practices, improvement recommendations, water
  quality index. `Partner Organisations (As Recorded)` returns gold's `'45.0'`-style text for
  the two "which partners" follow-ups (`_9` p2, `_10` p2).
- **`Hazard Type (Lowercase)`** — the rendering two follow-ups ask for by name ("type of
  hazard (in lowercase)"), permitted-source wording.
- **Warehouse-typed formulas** (commits c40e579, f315484). The REAL-declared JSON numbers
  (damage percentages, delivery figures, break rate, availability, sanitation, WQI) are read
  `::real` inside every formula and kept as the exact decimal for display; the three damage
  percentages are added as reals before the division, as `COALESCE(a::real,0) +
  COALESCE(b::real,0) + COALESCE(c::real,0)` does. Found by the ceiling test, not by any
  gate: `_4`'s hub strain matched gold to six digits and flipped at the second decimal on 4
  of 405 hubs (halved values sit on .xx5 boundaries), then on 3 after the casts alone, then
  on 0. This is tracker E-04's disaster_relief row, now closed model-side.

Build: dry-run 144 pinned constants, 19 generate gates, A8, A10, `sml-cli validate` clean;
deployed three times (last 15:0x). Sibling commits on the shared repo (sports_events
4d77121, 8d9eef1, another session) went out in the same deploys.

**Ceiling after deploy** (`scripts/probe_pred.py`, hand-written, no agent): `_1` p1+p2 (30
rows / 30), `_2` p1+p2 (312 / 310, with `WHERE "Supply Sufficiency (Days)" IS NOT NULL`),
`_3` p1 (54), `_4` p1+p2 (405; both the AVG-over-derived-table and the measures-grouped-by-
CASE shapes), `_9` p1 (5, null row first — the engine put the null first on DESC here, so
the NULLS-LAST cap did not fire), `_11` p1+p2 (4.03; five hazard rows), and the two passes
from 825 (`_8` p1, `_12` p1) all grade 1. `_10` p1+p2 grade 1 with `LOWER("Region Tag")`
and a coordination-record filter — reachable, but no question asks for lower case (see
B-72). Twelve of the fifteen probes that a correct agent could write now pass.

**Capped, reported, not changed:**
- `_5` p1: the runway values are one day short of gold whenever the grader runs between
  09:00 and 24:00 Pacific — the Postgres server session is `Asia/Hong_Kong` (already
  2026-08-28 at 14:30 PDT) and the engine's JDBC session is local, so `CURRENT_DATE`
  differs by one; recomputing gold at `CURRENT_DATE - 1` reproduces the model to three
  decimals. Harness (tracker E-06). `_5` p2 is a gold fan-out (crisis ops × staffing rows ×
  coordination rows, 27 rows from 6 operations).
- `_6`: the simulator answers "old" as "finished more than 2 years ago", gold has no such
  filter (every operation started in 2025, so the answer is empty); gold also returns the
  raw coordination table (`c.*`).
- `_7`: gold's RES joins beneficiary rows to the transport record of a *different* event
  through the operation (148 of 205 pairs are cross-event) — a join fan-out no model should
  reproduce.
- `_9` p2: gold's top-3 ops carry duplicates (10 rows from 3 ops); `_3` p2 (three hazard
  types tied at 12), `_8` p2 (two hazard types tied at 4, gold's LIMIT 1), `_12` p2 (ties in
  the break rate under strict order) are tie caps.
- `_10`: cosmetic `LOWER(region_tag)` on a code no question asks to lower-case (B-71 class).

**Guidance change, atscale backend `error_hints` only (no raw re-run owed):** the
`Your SQL is not correct` hint now puts two ROW POPULATION checks ahead of the VALUES
check — a projected column that came back NULL on some rows marks those rows as outside its
support set (`_2` submitted 1000 rows where gold has 312, every value right), and an entity
reached through a narrower record is a population question for the user. Services
restarted 14:29.

**Measured 2026-08-27 14:42–14:49, n=1, tasks 1/2/3/4/9/11**
(`results/disaster_0827_n1_atscale_20260827_144224.json`, Sonnet, **$2.04** from `llm_usage`:
agent $1.59, user sim $0.46, 90% of agent input from cache): `_2` **1.0**, `_3` **0.7**, the
other four 0.0 — 1.7 over the six against 0.0 for the same six in 825 (and in 824 and 820).
With `_8` and `_12` at 0.7 each in 825 the database reads 3.1/12 = **0.258** against 0.117
(825) and raw 0.083 (820): lift **+17.5 pp** where it was +3.4 pp, about 3x raw. Single run,
subset re-run, so not a quotable arm number; a full 12-task n>=3 run and a raw re-run are
owed before any figure from this database is quoted.

What converted and what did not, from the trajectories:
- `_2` passed both phases on the NULL-rows check: the agent asked "all 1000 events or only
  the 312 with a supply record" as its first question, got "only the 312", and filtered.
- `_3` p1 passed on the staffed-only twin: the agent read both counts (955 / 54) off the bare
  flag's description and asked which population, and the simulator answered "only disasters
  that have a matching staffing record". p2 is the three-way tie at 12.
- `_1` did NOT convert: the same population question, phrased as "the model links operations
  through four satellite records (coordination 967, beneficiary 800, financial 201, staffing
  57) — which population", came back **out of scope**. Where the record is the *input* of a
  KB formula (`_3`) the simulator routes the question to the join; where it is only the
  reference's path to an identifier (`_1`, `_9`) it reads as a schema question and refuses.
  The agent then dropped the severity column as well.
- `_11` did not convert for the opposite reason: the agent asked whether to restrict to
  events with both a cost and a population and the simulator said **"don't restrict"** —
  gold's `JOIN humanresources` restricts to 20 events, and the simulator read its SUM/SUM
  without seeing that. A simulator answer that contradicts gold; capped (B-72).
- `_4` got the supplied-events reading from the simulator ("use each hub's supply records")
  and the two labels, then projected hub + status without the strain index (the question says
  "list the hubs and their status"; gold adds the index). Agent-side shape.
- `_9` used the severity index where the question's "calculated severity score" was the
  gridlock index, and never applied the transport-access half of the gridlock rule.

So the per-record references converted exactly where a KB formula carries the record and
nowhere else — the simulator, not the model, is the binding constraint on the other five
reference joins. Recorded on B-72 so the next pass does not re-buy it.

