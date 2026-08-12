# Semantic-model change log

Post-build changes to the AtScale semantic models in
[AtScaleInc/bird-atscale-models](https://github.com/AtScaleInc/bird-atscale-models),
one section per model. Record the kind of change and why; name the Workarounds
row when a change works around a tracked defect.

## Workarounds

Engine/tool defects the models deliberately work around. Check whether a row
still applies before carrying its workaround into a new model.

| ID | Defect | Workaround | Still applies? |
|---|---|---|---|
| E-02 | Derived-dataset SQL executes without the connection's schema on the `search_path`; bare table references deploy clean then fail every query with `relation does not exist`. | Schema-qualify every table reference in derived SQL (`public.<table>` for all BIRD connections). | Yes - applied in `cybermarket_pattern` (2026-08-10). Not re-tested against a fixed build. |
| Q-17 | Two deployed models sharing a name render corrupted metadata. | Keep deployed model names unique across the engine; do not publish the same catalog to two schemas. | Yes - see the deploy-path note under cybermarket_pattern. |
| Q-17b | **A published model is materialised as a real relation, and the code path that creates it is not idempotent.** The MCP server's `get_model_document` triggers `CREATE TABLE "<catalog_schema>"."<Model Name>" (...)` in the engine's own SQL store with no `IF NOT EXISTS` and no preceding drop, so once that relation exists from an earlier publish every metadata call dies with `ERROR: relation "<Model>" already exists`. Verified in the engine container log: `STATEMENT: CREATE TABLE "bird_atscale_models_catalog_main"."Cybermarket Pattern" ("Accepted Payment Type Code" TEXT, ...`, alongside the MCP server logging `validate_query_paths: get_model_document failed; skipping path validation`. **The failure is asymmetric and that is the dangerous part:** `list_models`, `explore_columns` and `focus_columns` hard-fail, while `run_query` catches the error, skips path validation and returns CORRECT results - so the deploy looks healthy while the agent is blind. Neither redeploying nor restarting the MCP server clears it (both tried); the error appears to "move" between model names only because the failing path touches a different model first. | Drop the stale materialised relations in the catalog schema inside the engine's SQL store so the path can recreate them; republishing alone does not. Before any run, gate on `list_models` succeeding AND returning the expected model count - a working `run_query` is NOT evidence the catalog is healthy, which is exactly the trap here. | Yes - 2026-08-10/11. Voided three atscale runs (every task 0.000, 81-84% of tool calls erroring). `scripts/summarize_runs.py` now flags such runs SUSPECT and excludes them rather than reporting a lift from them. |
| MDX-Median | `Median()` is rejected at deploy as a `metric_calc`; must be `calculation_method: percentile` with `named_quantiles`. On the Postgres dialect the percentile sketch is then rejected at query time. Percentile metrics are exposed as `<name>_instance_<q>`; metadata is cached until `list_models force_refresh`. | Ship the percentile form anyway and record the dialect limitation. | Not exercised by `cybermarket_pattern` - no knowledge-base definition in that database requires a median. |
| D-01 | The engine re-parses and re-emits derived-dataset SQL, and a `'|'` string literal does not survive the round trip: every query touching the dataset fails with a raw warehouse `syntax error at or near "'|'"`. Other literals (`'$'`, `','`, `' km'`, `'Yes'`, `'2FA'`) round-trip fine, so this is specific to the pipe character. Layer 1 validation and deploy both pass - it only surfaces on a live query. | Never use `|` in derived SQL. Where a composite key needs representing, use a compound SML leaf key (`sml-create-dimension` R5) rather than concatenating a surrogate. | Yes - found and fixed in `cybermarket_pattern` on 2026-08-10 (acceptance run 1). |
| Catalog-suffix | Deploying from Design Center appends the git branch to the catalog name (`_main`); `sml-cli atscale-deploy` uses the catalog name verbatim. The two paths publish to different schemas. | Read the schema back from `list_models` after any redeploy and make `config/environment_backends.yaml` match. | Yes - the two existing models are published at `bird_atscale_models_catalog_main`. |

---

## cybermarket_pattern

**2026-08-10 - initial build.** Generated from the BIRD-Interact
`cybermarket_pattern` database by
`cybermarket_pattern/generator/generate.py` (spec -> emitter; the spec is
`sql_spec.py` + `model_spec.py`). 304 objects: 8 derived datasets, 7 dimensions,
178 metrics, 10 `metric_calc`s, 1 model. `sml-cli validate` clean at repo root.

Build decisions worth recording, each traceable to the knowledge base, the live
schema, or observed engine behaviour:

- **E-02.** All derived-dataset table references schema-qualified `public.<table>`.
- **Derived datasets throughout.** The source stores numbers as unit-suffixed or
  currency-formatted text (`'$98.60 '`, `'2140.32 km'`, `'0.12 Threats/hour'`,
  `'11.61 Score/violation'`) and packs most attributes into `jsonb`. Parsing is
  done in the dataset SQL so the semantic layer can aggregate it.
- **One wide transaction fact.** `transactions`, `transaction_products`,
  `risk_analytics`, `communications`, `connection_security` and `alerts` are all
  exactly 1:1 on the transaction key (1000 rows each, no orphans, verified live).
  Joining them into one fact gives every transaction-grain attribute a direct
  relationship to Platform / Vendor / Buyer / Product Listing, which removes the
  conformance failure class where a measure on one fact cannot be sliced by a
  degenerate dimension sourced from another.
- **Recorded columns are not the KB formulas.** Verified live: 0 of 994 vendors
  have `RegStandeff` equal to the computed CEI; the same holds for
  `turnover_rate_val` vs WTR and `Threat_handle_rate` vs the computed THR. These
  source columns are shipped as separate measures suffixed `Recorded`, with
  descriptions stating they are different quantities.
- **Units traps documented in descriptions.** `markets.RepScore` is
  dollar-formatted but is a 0-100 reputation score; `vendors.TotalTxns` is
  dollar-formatted but is a transaction count.
- **Live data beats the metadata files** where they disagree.
  `connection_security.AnonLevel`, `risk_analytics.ML_Risk`,
  `connection_security_metrics.data_protection_class` and
  `encryption_strength_scr` are all described in
  `cybermarket_pattern_column_meaning_base.json` as small categorical label sets
  but are continuous numerics live (1000, 1000, 1000 and 250 distinct values).
  `transactions.GeoDistScore`'s metadata example shows a
  `USD/border-crossing` value but the column is km. Descriptions state the live
  reality and name the metadata's claim.
- **Non-unique label.** `markets.PlatName` has only 100 distinct values across
  954 platforms, so `Platform Identifier Code` is exposed as a queryable (not
  hidden) secondary attribute and both descriptions prescribe grouping on the
  code while displaying the name.
- **`protection_meas_count` sentinel.** 5 platforms store `-1`, which makes
  their DPE negative. Documented on the DPE metrics rather than silently
  filtered, because the definition does not authorise dropping them.
- **Multi-condition concepts precomputed.** High Risk Vendor (investigation OR
  law-enforcement interest), Secure Platform (vulnerabilities AND protection
  measures), Premium Authentication (2FA OR multi-factor), Fraud-Flagged,
  Tier-3 Escalation and Advanced Verification ship as Yes/No attributes. Each
  raw component's description says it is an *input* and redirects filtering to
  the flag, because a question phrased in a component's words otherwise gets
  filtered on that component alone and loses the other OR branch (240 or 146
  vendors instead of 345).
- **Deliberate omissions where the KB states no threshold.** Suspicious Buyer,
  Traceable Communication and Escrow Compliance are defined qualitatively ("low
  consistency and high risk per dollar", "high volume of flagged keywords",
  "consistently routes payments through escrow") with no stated cut-off, and the
  corresponding `user_query_ambiguity` entries are `is_mask: true`, meaning the
  benchmark intends the agent to resolve them by asking. No flag is shipped for
  these three; the comparable component measures are exposed instead and each
  description says so. Secure Platform and Fraud-Flagged, by contrast, carry
  explicit thresholds stated openly in the knowledge base, so those are
  precomputed.
- **Bucketed tiers are labelled as this model's convention.** `Anonymity Tier`
  buckets a continuous 1.00-9.99 score into Low/Medium/High by even thirds
  because the KB names those tiers but the source stores no such labels. The
  description says the strings are this model's convention and points at
  `Anonymity Score Average` for other boundaries.
- **RANK / DENSE_RANK twins.** Ties are real: 17 message threads share the
  maximum keyword match count, and two tie at SSD rank 10. Both flavours ship
  for MRS, CEI, PLR, SSD, keyword match count and alert resolve hours, each
  description naming its twin and the reading it answers. Ranks are computed over
  the whole population, not a query's filtered subset - stated in each
  description.
- **Formula families.** Each of the 10 KB formulas ships as: a per-entity
  average, a `Group Formula` `metric_calc` recomputing the definition from
  aggregated component measures, a `Single <Entity> Value` for entity-grain
  lookup, every component as its own measure, and exactly one support-set count
  per formula (the intersection where all components are present, not a
  per-component non-null count). The group/average divergence is material -
  BRDR is 0.04790105 pooled vs 0.09419090 as a mean of per-buyer ratios.
- **`unrelated_dimensions_handling: error`** on every metric, so a
  non-conforming pairing fails loudly instead of returning empty.
- **No time dimension.** Each platform, vendor and buyer appears exactly once in
  its source table, so there is no snapshot-per-entity grain and the
  "ever vs as-of-latest" distinction does not arise for entity attributes; the
  semi-additive and window-carry guidance therefore has nothing to apply to
  here. Where a transaction-derived entity flag was still needed
  (`Ever Had Fraud Flagged Transaction`, `Ever Purchased Cross Border`) it is
  precomputed and explicitly named "ever" / history-wide. None of the 20 query
  tasks asks for a date rollup, so transaction date parts are exposed as
  attributes rather than as a `type: time` dimension.

### Deploy path - open decision (Q-17, Catalog-suffix)

`catalog.yml` is shared at the repo root, so `sml-cli atscale-deploy` publishes
the **whole catalog** - all three models - to schema
`bird_atscale_models_catalog` (catalog name used verbatim). The two existing
models are already published at `bird_atscale_models_catalog_main` (Design
Center appends the branch). Deploying via `sml-cli` would therefore put a second
copy of `Solar Panel` and `Exchange Traded Funds` on the engine under a
different schema, which is exactly the Q-17 duplicate-model-name condition and
would corrupt metadata for the two working models.

This model is committed, pushed and Layer-1 clean but **not yet deployed**
pending a choice of deploy path. Whichever path is used, read the schema back
from `list_models` afterwards and add the matching `domains` entry to
`config/environment_backends.yaml`:

```yaml
      cybermarket_pattern:
        catalog: atscale_catalogs
        schema: <schema read back from list_models>
        table: Cybermarket Pattern
```

**2026-08-10 - acceptance run 1 (post-deploy).** Deployed to
`atscale_catalogs.bird_atscale_models_catalog_main.Cybermarket Pattern`,
alongside the two existing models in one catalog - no duplicate model names, so
Q-17 avoided.

Found and fixed:

- **D-01** (new workarounds row): `|| '|' ||` in `Product Listing Detail` and
  `Transaction Event` made every query on those two datasets fail. About half of
  Gates 1, 2 and 4 were unqueryable. Replaced the concatenated
  `product_listing_key` with a compound natural leaf key on the source's
  four-part PK; the generator now asserts no `|` remains in any emitted SQL.
- Three discoverability gaps: `how much cash flow they handle per day`,
  `dodgy buyers` and `how anonymous a session appears` returned no candidate
  from `explore_columns` (ordered substring match, so a differently-phrased
  concept returns nothing). Added those phrasings, plus `how often they hide
  their identity`, `how the buyer verified their identity` and `pass the secure
  criteria`.
- Two baselines in `cybermarket_pattern/ACCEPTANCE.md` had been written by
  padding digits onto 6-decimal figures. The model was correct in both cases;
  the document was wrong and is corrected from full-precision source values.

Everything runnable without the two affected datasets passed exact-equal: 15 of
25 exactness rows, 9 of 15 conformance probes, 4 of 6 coverage shapes. The
group-vs-average separation is confirmed working (CEI 14.905 pooled vs 23.265
mean; likewise DPE, BRDR, TVR, PLR). Pooled Group Formula calcs agree with the
source to ~15 significant figures - the engine's summation order differs from
Postgres's, a last-unit double difference, not a modelling error.

**2026-08-10 - acceptance run 2 (after redeploying the D-01 fix). All four gates
pass.** Exactness 25/25 exact-equal against source, Conformance 15/15 pairs
non-empty, Discoverability 14/14 paraphrases, Coverage 6/6 shapes.

- D-01 confirmed fixed: the transaction and product-listing halves of the model
  are queryable, and the compound leaf key does not fan out (Transaction Count
  still totals exactly 1000 when grouped through Product Listing).
- Group-vs-average separation verified on all nine ratio formulas, diverging
  1.43x (ACI) to 4.09x (TVR). A Group Formula returning its average twin's
  number would have meant the MDX was wrong.
- Rank twins verified: `SSD Rank Descending <= 10` returns 11 rows because two
  threads tie at position 10 - the RANK reading of "top N", which is why the
  DENSE_RANK twin ships beside it.
- Negative test: `Buyer Count` grouped by `Completion State` was refused before
  execution, naming the conforming fact groups, at no warehouse cost. That is
  `unrelated_dimensions_handling: error` working as intended.
- **Re-verification gotcha.** Source columns declared `real` (float4) must be
  re-checked with `::float8`, not `::numeric`. The engine casts `real -> FLOAT8`
  and preserves the binary value; `::numeric` rounds each value to its shortest
  round-trip decimal and produces a spurious 8th-significant-digit mismatch.
  This caused a false alarm on ACI and THR before being tracked down.

`config/environment_backends.yaml` now carries the `cybermarket_pattern` domain
entry pointing at `bird_atscale_models_catalog_main` / `Cybermarket Pattern`.

---

## archeology_scan

**2026-08-11 - initial build from `create_bird_model_prompt.v2.md`, prompt-only.**
Model lives in `AtScaleInc/bird-atscale-models/archeology_scan/`; full rationale,
exclusions and evidence in that folder's `SPEC.md`.

**2026-08-11 - republished from Design Center; catalog schema is now `_main`.**
Supersedes the paragraph below: `bird_atscale_models_catalog_main` now holds all
four BIRD models including `Archeology Scan`, and `list_models` reports no
unsuffixed copies at all. `config/environment_backends.yaml` gained an
`archeology_scan` entry naming `bird_atscale_models_catalog_main` /
`Archeology Scan`. No model content changed - deploy path only. The
Catalog-suffix workaround row stands: read the schema back from `list_models`
after any redeploy rather than assuming which path published last.

**Superseded 2026-08-11 (see above). Catalog schema is `bird_atscale_models_catalog`, NOT `..._main`.** `sml-cli
atscale-deploy` uses the catalog name verbatim, where a Design Center deploy
appends the branch. Deploying this build therefore republished the whole shared
catalog into the unsuffixed schema, so all four BIRD models now exist in BOTH
`bird_atscale_models_catalog` and `bird_atscale_models_catalog_main`. The
`_main` copies are whatever Design Center last published and do NOT contain
`Archeology Scan`. Any `config/environment_backends.yaml` entry for this
database must name `bird_atscale_models_catalog` / `Archeology Scan`, and
remember `shared/environment_backends.py` caches that file in a module-level
dict, so the services need restarting for an edit to take effect.

Shape: 4 fact grains - `scan_fact` (1000, one scan), `site_equipment_fact` (998,
one site-and-equipment pairing), `site_quality_fact` (900, one site),
`conservation_fact` (455). Site is the only dimension reaching all four. 94
metrics, 10 calculations, 120 queryable attributes.

### Acceptance - all four gates pass

- **Exactness.** Every probe exact-equal to the source to 12 decimal places:
  scan/site/project/operator counts (1000/900/905/900), total points
  (35,850,368,904), support sets (697 point cloud, 234 PCDR), per-site SQS and
  SCE, site ranks, risk-zone split (778/122), and a four-fact cross-fact
  aggregate (SQS 5.648103197666, MCR 3093.3410990582, DPQ 28.772710069248,
  DPQ support 364, conservation records 322).
- **Conformance.** Site reaches all four facts in one query; Project reaches
  scan and conservation; Operator, Scan Date and Scan Record reach scan;
  Equipment and Site Equipment Record reach site-equipment; Conservation Record
  reaches conservation. All non-empty. Negative test: `Scan Count` grouped by
  `Processing Software` was refused before execution, naming the conforming
  fact groups, at no warehouse cost.
- **Discoverability.** Probed with `amb_user_query` wordings only. All surfaced
  the intended object.
- **Coverage.** All six shapes pass: group aggregate, filter-by-classification,
  superlative/top-N, cross-fact, entity-level detail, group-relative comparison.

### Findings worth carrying to other databases

- **`count(*)` in a dry run does not evaluate the select list.** Postgres
  optimises the projection away, so a division-by-zero in a computed column
  survives to query time. Counting `md5(row::text)` instead surfaced two: 4 of
  944 scanners record 0% battery (EER), and ESI can approach -10 (EIF). Both
  denominators now use `NULLIF` and the support flags exclude those rows.
- **Engine MDX function set, probed with `validate_mdx_expression`:** `SQRT`,
  `ABS`, `LOG10` and `EXP` are supported; **`POWER` is not** (`end of input
  expected`). So `x^2` and `x^1.5` are rewritable as `x*x` and `x*SQRT(x)`, but
  `x^0.3` is not. This is worth probing before deciding a group-level formula is
  inexpressible - an earlier note in this build wrongly assumed none of these
  were available.
- **A dangling-cross-reference check keyed on `Name (ACRONYM)` is not enough.**
  It matches the published base name and stops, so a description can promise a
  `(Recomputed For Group)` twin that was never shipped - which is exactly what
  the acceptance run found. Adding a qualifier-aware check immediately caught
  two more, left stale by a rename whose phrase spanned a line break. Both
  checks now run in the generator.
- **The build-time discoverability gate caught missing OBJECTS, not just missing
  wordings.** The model had no Registration ID and no Scan Timestamp at all,
  both asked for by name in the task set. Worth treating a failing phrase as a
  possible modelling gap, not automatically as a description fix.
- **Four KB definitions select zero rows on this database** and are documented
  rather than shipped as always-'No' flags: Conservation Emergency and High
  Temporal Value Site (both need a CPI above 60-75, and CPI cannot exceed 46.98
  because the KB gives no scale for its Site Type rarity term and the column
  holds no rarity value), Texture-Critical Artifact (TDI maxes at 0.178 against
  a threshold of 8.0, and the required texture values do not occur), and Digital
  Conservation Priority. `dryrun.py` asserts each is still empty so the claims
  cannot go stale.

### Masked terms - expect these tasks to fail, and report them separately

`High Resolution Scan` (KB 10) and `High Fidelity Mesh` (KB 13) are `is_mask:
true` in every task that uses them, so neither ships as a flag; their components
do, each directing the agent to ask the user for the full definition. That also
rules out `Premium Quality Scan`, `Mesh Quality Classification` and `Full
Archaeological Digital Twin`, which depend on them. Tasks `archeology_scan_6`,
`archeology_scan_M_1` and `archeology_scan_M_3` turn on these terms and cannot
honestly be fixed in the model. `DPQ` (task 5) and `FEE` (task 9) are also
masked but are KB-named formulas rather than thresholds, so they ship under
their own names - the ambiguity there is "which index did you mean", which
competing named metrics answer honestly.

### First benchmark run, 2026-08-11 (n=1, 10 Query tasks, both arms)

atscale 0.000 / raw 0.100. The acceptance gates above are not wrong - they
measure the model against the SOURCE, and every probe still reproduces. What
they do not measure is the grader, and both arms are sitting on grading floors
rather than on model quality:

- Tasks 3 and 4 return an EXACT multiset match to gold and fail only on the
  order of tied rows (tracker B-15). The raw arm cannot hit this - it is the
  same Postgres that produced gold - so the flag is asymmetric here, unlike on
  ETF where it was measured symmetric. These two are the whole arm-to-arm gap.
- Task 10's gold projects a `jsonb` column and crashes the grader, which
  reports the crash as a wrong answer (tracker B-14). Unpassable on both arms.

The remaining seven are genuine misses and are the real work: mostly row-count
divergence (a filter or grain the agent did not reproduce), plus one
over-projection on task 1. Do not read 0.000 as a dead catalog - `list_models`
was healthy and 130 of 139 tool calls returned real data.

**Tie-tolerant re-grade of the same run (trajectory fixed, offline, free).**
With `GRADING_TIE_TOLERANCE=true`: raw 1.00 (unchanged - no raw submission was
tie-order-only), atscale 1.40, mean 0.100 vs 0.140, +40% uplift. The replay
reproduces all 37 live verdicts and the measured totals exactly under
`tie=false`, so the flip is the only variable. atscale's 1.40 is a LOWER BOUND:
both tasks earn phase 1 (0.7 each) but phase 2 was never attempted live, since
phase 1 failed at the time. If both follow-ups also passed the arm would reach
2.00 (mean 0.200, +100%), so the honest range for this flag is +40% to +100%.

The mechanism is not rounding - `preprocess_results` rounds both sides to the
same decimals whatever the SQL did, and stripping gold's `ROUND()` leaves the
tie counts identical (75/825 and 455/528 either way). It is simply that the raw
arm runs gold's own engine, so its tie permutation matches by construction,
while the AtScale engine returns an equally valid different one.

### Post-run teardown, 2026-08-11 - what the seven "genuine misses" actually are

Every failing atscale submission was replayed against gold offline and, where a
hypothesis needed testing, re-run live through `run_query`. The misses are not
seven separate problems; they are three, and only one of them is the agent's.

**1. Component averages use a support-set denominator; gold uses the population.
This is the big one.** The model's `Average <X>` measures average over the rows
that HAVE an X. Gold's formulas average over every row in scope and treat a
missing input as zero. The two differ by exactly the coverage ratio, so any
knowledge-base formula built on top of them is wrong by that factor.

Worked example, site SC3083 (2 scans, both with a point cloud, only 1 with a
spatial record):

| quantity | model | gold |
|---|---|---|
| Average Surface Area | 974.76 (over the 1 scan that has one) | 487.38 (974.76 / 2 scans) |
| PCDR | 12.95 | 25.89 |

`59806438.5 / (4739.5 x 974.76) = 12.95` vs `59806438.5 / (4739.5 x 487.38) =
25.89`. The numerator and the density code agree to the last digit; only the
denominator's row count differs. SC7585 behaves identically (9.22 vs 4.61).

Note the STRUCTURE was already right: `Point Cloud Density Ratio (PCDR)
(Recomputed For Group)` correctly divides aggregates rather than averaging
per-row ratios, which is what gold does. Switching to it does not help, because
its inputs carry the same support-set denominators - 816 of 900 sites still
differ either way. The fix belongs in the component measures, not in the ratio.

Affects tasks 5 (582/900 sites differ), 9 (816/900) and, through Model Fidelity
Score and the registration terms, 6. Task 9's gold is explicit about it:
`AVG(COALESCE((pc.cloud_metrics->>'Total_Pts')::bigint, 0))` over
`scans LEFT JOIN pointcloud`, not over pointcloud.

**1b. But the denominator is not the scan count either - gold's joins fan out,
and that half should NOT be chased.** Correcting only the support-set
denominator reproduces gold on 201 of the 243 sites where the components are
usable, and misses 42. The reason: `arcref` is not unique in any of these
tables - up to 4 rows in `scans`, 3 in `pointcloud`, 2 in `spatial` - so gold's
`ON sc.arcref = pc.arcref` fans out and its denominator is the JOINED row count.
SC1245 is 1 scan but 2 joined rows; SC1518 is 2 scans but 5. The two counts
differ on 92 of 900 sites.

Reproducing that would mean making a scans x pointcloud x spatial cross product
the fact grain, which would corrupt every other measure in the model to chase an
artifact of a sloppy join. Recommendation: fix 1, log 1b as a gold defect
(tracker B-17), and accept task 9 as unwinnable for this arm. Note the
consequence - because grading is all-or-nothing, fixing 1 alone buys NO score on
task 9; do it for model correctness, not for lift.

**2. A site with no rows in a fact disappears when any measure from that fact is
projected.** The Site dimension has all 900 members and returns 900 on its own,
but `SELECT "Site Code", "<any measure>"` returns 898. The missing two are
SC5861 and SC6651, which exist in `sites` and have a scan each but zero
`environment` and zero `conservation` rows. Sites that DO have fact rows with
null contents still come back (73 of them, with a NULL measure), so this is
specifically zero-fact-rows, not null-valued. Gold reaches all 900 by starting
`FROM sites` and LEFT JOINing. Costs tasks 6 and 7 - both are exactly 898 where
gold is 900.

Tested how far preserving those members gets task 7: to the exact 900 x 8 shape,
with 874 of 900 rows matching gold by site key. The 26 that differ do so only in
average temperature and humidity, by one unit in the last place (18.5 vs 18.4,
15.6 vs 15.7) - gold casts those to `::real`, so that is the float32 artifact
`GRADING_RELATIVE_TOLERANCE` exists for, not a model error. So the join fix is
necessary but not by itself sufficient; the residual is tie-order plus those 26.

**3. Task 1 was a won task thrown away on one column** (agent-side, now
mitigated). The submission had the right 648 rows and values correct to 15
significant digits, and scored 0 because `"Site Scan Quality Rank"` was in the
SELECT list purely so the ORDER BY could reference it. Dropping that one column
and ordering by the SQS measure already projected grades **1**, verified live. A
rank column is redundant with the measure it ranks, so it never needs to be
projected. Added as a rule to the atscale instructions in
`config/environment_backends.yaml`.

**4. Task 2 - the grain IS reachable; the classification is not.** Correcting an
earlier note here: gold's 926 rows are not beyond the model. They are 455
conservation records plus the 471 sites that have none, and `Conservation Record
ID` expresses exactly that grain - a query at that grain returns 455, and the
column's own description states the 455/429/471 split. What is missing is the
same spine problem as 2, one table over: `conservation_fact` has no row for a
site without an assessment, so the 471 cannot appear.

The harder half is the classification. Gold writes `c.structstate <> 'Stable'`,
but all three values in the data are sentences ('Stable condition, structure
secure for access', ...), so nothing equals `'Stable'` exactly and gold's
predicate is TRUE for every record - its risk test collapses to `Preservation
Status IN ('Poor','Critical')`. The model's `Degradation Risk Zone` uses
`NOT LIKE '%Stable%'`, which is FALSE on the 142 stable-condition records:
the two disagree on 142 of 455 (tracker M-11). The model's reading is the
defensible one, so this should NOT be changed to match gold - it means an agent
has to write a predicate that contradicts the model's own attribute to pass.

Not model defects, for the record: `list_models` was healthy throughout, and the
MCP server returned data on every well-formed call - the only errors were
malformed calls of mine during this teardown.

### site_equipment_fact spine, 2026-08-11 (M-10)

`generator/sqls.py` only - the emitted YAML is generated, per SPEC.md. The
`pairs` CTE that defines the fact's grain became `real_pairs` (the UNION over
mesh/processing/features/environment, 998 rows) plus a spine row for every site
present in none of them, carrying `equipref NULL` and `spine_row_count 0`; the
SELECT's literal `1 AS row_count` now reads `p.spine_row_count`.

The dataset goes from 998 rows to 1000 while still carrying 998 records, which
is what keeps it inert: `Site Equipment Record Count` is `sum(row_count)` and
stays 998, every `has_*_inputs` flag is a CASE that yields NULL on a spine row,
and every measure is an AVG, which ignores them. Verified live - `dryrun.py`
passes with `EXPECTED_ROWS` raised to 1000, every KB formula spot-check still
agrees, and `sml-cli validate` is clean. NOT YET DEPLOYED.

**It does not, on its own, convert task 7.** With the spine rows simulated in,
the answer reaches the exact 900 x 8 shape and 874 of 900 rows match gold, but
26 still differ in average temperature and humidity. Those are gold's `::real`
float32 casts landing on an exact `.x5` rounding boundary - agreement to ~1 part
in 10^8 that rounds apart at 1 decimal. Ordering is NOT the blocker: gold's own
row order still fails.

Three further levers were needed to make it pass, all in the harness:

1. Strip gold's `ROUND()` on the semantic-layer path. The raw arm already does
   (`test_case_default`); `ex_base_external_pred` executes gold verbatim. Until
   it does, the tolerant fallback is useless here by construction - gold's
   "pre-rounding" value IS the rounded one, so the fallback compares 18.4 to
   18.45 rather than 18.4499998 to 18.45. Tracker B-19.
2. `GRADING_RELATIVE_TOLERANCE=true`.
3. The tolerance actually applied - `grading_rel_tolerance_value` is declared in
   config and read nowhere, so the 1e-6 default in `_values_close` is fixed.
   Tracker B-20.

With all three and the tolerance at 1e-4, task 7 grades **1**. It still fails at
1e-5, so the residual is wider than the ESI gaps (~1.3e-6) alone. 1e-4 is loose,
and the honest caveat is that it rescues nothing wrong ON THIS TASK SET but has
not been justified beyond it.

**Collateral check.** Re-grading every archeology submission under these levers:
no verdict changes on the atscale arm at all, and the RAW arm gains task 6
(+0.70) from relative tolerance alone at the default 1e-6. So switching the
tolerance on with the trajectories as recorded moves raw 1.00 -> 1.70 and
atscale 1.40 -> 1.40. The task-7 gain is only reachable by re-running, because
the arm never submitted the unfiltered query live.

### Tasks 8 and 10 - closed out as unreachable

Task 8: gold joins `processing` to `scans` on `zoneref` (SITE, not scan) and
then to `pointcloud`, taking 821 processing rows to 1102. Its per-group averages
and its `workflow_count` column are all over that fan-out. The group set itself
is reachable - 122 distinct software x stage pairs, which the model has - but no
aggregate over them is. Same family as B-17.

Task 10: three independent blockers. Gold starts `FROM equipment` (944) and fans
out through mesh to 987; 166 of those equipment have no processing row at all,
which is M-10 one dimension over; and gold's sixth column is the raw
`system_usage` jsonb projected whole, which no semantic-layer measure can
return. The third is structural - task 10 is not winnable by this arm at any
model quality.

**Deployed 2026-08-11.** `sml-cli atscale-deploy . --catalog-name="bird_atscale_models_catalog_main"`
(the `--catalog-name` override is required - the flag defaults to the catalog's
own `unique_name`, which is the UNSUFFIXED schema, and deploying there would
have created the duplicate this model already suffered once). `ATSCALE_API_URL`
must be the bare host, not the `/v1/public` base - sml-cli appends that path
itself and a doubled URL 404s on `/v1/public/v1/public/repos`. Deploy resolves
the project from the git REMOTE, so the commit must be pushed first.

Q-17b gate after deploy: `list_models` succeeds and returns all five models in
`bird_atscale_models_catalog_main` - Archeology Scan, Cybermarket Pattern,
Exchange Traded Funds, Households, Solar Panel - with no unsuffixed duplicate.
Dave's Households model landed on main during this work and went out with it.

Verified live: `Site + ESI` and `Site + MFS` return 900 rows where they returned
898, SC5861 and SC6651 come back with a NULL measure, and every count is
unmoved - Site Equipment Record 998, Ambient Condition Reading 908, Mesh 839,
Processing Workflow 821, Feature Analysis 539, ESI non-null population 825.

Task 7 re-tested against the deployed model with no simulation: still 0 on its
own, and **1** once B-19 (strip gold's ROUND on the cross-source path) and B-20
(wire the tolerance value) are applied at 1e-4.

**B-19 fixed 2026-08-11 (67724b9), which changes the flag picture.** The
semantic-layer path now gives gold the same `remove_comments` ->
`remove_distinct` -> `remove_round` cleanup the raw path and upstream already
give it. Unflagged, because it retires a deviation rather than adding one.

The side effect matters more than the fix: stripping gold's `ROUND()` removes
the ARTIFICIAL ties it manufactured. Gold's `ORDER BY` was sorting on rounded
values, so its row order was arbitrary inside each tied block and no external
engine could reproduce it; unrounded, the order is strict and a full-precision
semantic layer matches it directly. `GRADING_TIE_TOLERANCE` is now a NO-OP on
the semantic-layer arm - identical pass counts with it on or off, on both
domains (archeology 5/21 submissions, ETF 17/74). The arm reaches 1.40 on
archeology under UPSTREAM grading flags.

So the archeology lift no longer depends on a deviation flag, and B-15 is
superseded: the cause is removed rather than the symptom forgiven. The flag now
only affects the RAW arm, which makes keeping it on a choice that slightly
favours raw rather than one that rescues the semantic layer.

### First valid benchmark measurement, 2026-08-12 (n=1, 10 Query tasks, both arms)

**atscale 0.270 vs raw 0.100, lift +0.170.** Phase 1 3/10 against 1/10, phase 2
2/10 against 1/10. Won tasks: `_4` (+1.00) and `_1` (+0.70); no raw wins. Files:
`archeology_n1_atscale_20260812_094731.json`,
`archeology_n1_raw_20260812_095452.json`.

The lift does NOT depend on any deviation flag. An offline replay of the same
submissions reproduces 2.70 under all four tie/decimal combinations, including
upstream (`tie=F dec=F`). Raw reproduced 0.100 exactly across two runs a day
apart (sd 0.000).

This supersedes the earlier reading of the 2026-08-11 run. That run, and a
second on 2026-08-12 at 09:25, both scored 0.000 - and neither was a model
result. Both were graded by harness code held in memory since 2026-08-11 11:26,
five hours before B-19 (16:28) and B-20 (17:10) landed. The signature was
unambiguous once looked for: `_3` and `_4` graded FAIL live and PASS offline on
byte-identical SQL under identical flags. After restarting the services the same
configuration scored 0.270. Tracked as B-23 and gated by `scripts/gate_run.sh`,
which refuses to run when the services predate the newest harness commit. The
existing Q-17b `list_models` gate does not catch this - it inspects the catalog,
not the code version - so both gates are needed.

Note what this says about the earlier prediction of 1.40 from replaying the
2026-08-11 trajectories: it was a floor, and a live re-run beat it (2.70).
Re-grading recorded submissions answers "what would the grader say about this
SQL", never "what would the agent do next time" - the void run's own agent
resubmitted identical SQL to budget -1 because the stale grader kept telling it
a correct answer was wrong.

Of the seven remaining failures, five match their prior diagnosis: `_6` masked;
`_2` M-11 plus a masked term; `_5` and `_9` M-09; `_10` unreachable (gold
projects raw `jsonb`). Two do NOT, and the difference is worth recording rather
than carrying the older reading forward:

- **`_7` never submitted at all.** 9 `run_query` calls, 0 `submit_sql`, and 3.5
  coins still unspent. The prior diagnosis - that it reaches gold's shape and
  loses on the `::real` float32 residual - was established by simulating the
  spine offline, and it did not describe this run. Whatever blocks `_7` live,
  it is upstream of the residual, so turning on a relative tolerance would not
  have converted it. Worth a look: this is the one failing task with unspent
  budget and no submission.
- **`_8` gave up early** - 1 submit, 11.0 of 20 coins used, 9.0 left. B-17's
  join fan-out still caps it, but the arm is not spending its budget trying.

The pattern in both is an arm stopping short rather than being blocked, which is
a different problem from the modelling defects above and is not addressed by any
of them.

**Caveat carried with this number:** it measures the model as deployed, which
still contains the M-12 question-phrasing leakage described below. The de-leaked
build is not yet deployed, so 0.270 is an upper bound on the honest figure.

### M-12 question-phrasing leakage removed, 2026-08-12

`generator/` only; the emitted YAML is generated, per SPEC.md. NOT YET DEPLOYED.

A cross-model scan found benchmark question wording copied verbatim into
published descriptions in all five BIRD models - archeology worst at 17 phrases
across 4 tasks. The leaked text is question grammar rather than business
vocabulary ("in descending order of quality values", "how many sites fall into
each ECCS category"), and one DPQ description quoted a benchmark question
outright in order to steer the agent to itself. A model built for a real
business would contain none of it, so it inflates the arm on exactly the
questions being measured.

Notably the leakage tracks the `DISCOVERY_PHRASES` build gate rather than the
lift: `solar_panel` carries the largest lift of any model (+0.370), predates
that gate, and has 2 phrases, while the two models built with the gate carry the
most. The gate as inherited asks that every question wording match some
published description, and the cheapest way to satisfy it is to paste the
question in.

Four changes, and the governing rule is that **the model may describe what a
thing is, never how a question asks for it**:

- **A8** - no published description may contain a verbatim 6-word run of any
  task question.
- **A9** - no `DISCOVERY_PHRASES` entry may be question-shaped: no question
  grammar, no 4-word run of a task question. An aggregation prefix over a real
  term is exempt, so `average Environmental Suitability Index` survives while
  `how many sites fall into each ECCS category` does not.
- The phrase list is pruned 78 to 75, dropping 14 question-shaped entries and
  adding 11 replacements each verified present in the knowledge base, the column
  meanings, the schema or a published object name.
- An emit-time filter in `write()` strips question-shaped synonyms from every
  `Ask for it as:` list. Applied there rather than in `spec.py` because there
  are 181 such lists whose literals are line-wrapped in the source, and a policy
  in one place stays true for synonyms added later.

Questions are read from the allowlisted brief `extract_brief.py` emits, never
from `bird_interact_data.jsonl`, so the answer-key firewall stays auditable - a
negative guard is safe by construction, since it asserts absence rather than
importing content. Independent verification (a scanner separate from the build
gates) now reports 0 phrases and 0 tasks for archeology, down from 17 and 4.

The trade is deliberate and worth stating: some question wordings are now less
findable, which may cost score. That is the point - measured findability bought
by copying the eval set is not findability a customer would ever have.

## Tie tolerance turned off, and B-20 wired, 2026-08-11

Two grading-side changes; no model change.

**`GRADING_TIE_TOLERANCE` is now `false` (upstream).** The open question left by
B-19 was whether the flag still earned its keep. It does not. Re-grading the
whole 0811 audit both ways - 168 submissions, both domains, both arms - changes
**zero** verdicts. Since B-19 it rescues nothing on the semantic-layer arm, so
keeping it on would only be a deviation that slightly favours raw.

The flag is global, so the two databases we happen to run are not enough to
clear it. Every order-sensitive gold in the dataset was executed - 505 of them
across all 22 databases - with gold put through the same
`remove_round`/`remove_distinct`/`remove_comments` B-19 now applies, so the ties
counted are real data ties and not rounding artefacts:

| | count |
|---|---|
| order-sensitive golds, all 22 dbs | 505 |
| whose gold has a genuinely tied sort key (flag can matter) | 168 |
| no ties, so the flag is provably a no-op | 306 |
| gold would not execute standalone (Management phase-2 DDL) | 31 |

None of the 168 sit in `archeology_scan` or `exchange_traded_funds` submissions
today, so turning the flag off costs nothing measurable now. It is not
risk-free forever: `hulushows` (24 exposed golds),
`labor_certification_applications` (13), `mental_health` (12), `cross_border`
(11) and `polar_equipment` (10) would each put correct-but-differently-tied
answers at risk, and that risk falls harder on the semantic-layer arm, which
runs on a different engine than gold. Revisit the flag before adding any of
those databases to the run set.

Turning it off also retires an over-reach found while checking the above
(tracker B-22). `_sort_key_indices` falls back to the last column when no
column of gold's result is monotonic and non-constant. On 11 of the 168 that
fallback column is constant, so the whole result becomes ONE tie group and the
ordered comparison silently degrades into an unordered set comparison -
`hulushows_16` and `_19` are 1000-row results compared with no order constraint
at all. That is much more permissive than the flag's documented behaviour, and
it should be fixed before the flag is ever turned back on.

**B-20: `grading_rel_tolerance_value` now actually reaches the comparison.** It
was declared in config, documented as configurable, and read nowhere;
`_values_close` hardcoded `rel_tol=1e-6` as a default argument. It now defaults
that argument to the setting, leaving explicit callers able to pin a value.

Verified end-to-end against the deployed model rather than in isolation: task 7
graded through `ex_base_external_pred` with the knob driven only through
settings scores 0 at 1e-5 and 1 at 1.5e-5 and looser, identically with tie
tolerance on or off.

The value task 7 needs is **tighter than the 1e-4 first reported**. Comparing
the live model against gold cell by cell, the worst of 3298 numeric cells is
1.13e-5 apart, with a median of 2.8e-8 and a p99 of 1.6e-6 - float64
accumulation-order noise on a summed composite index, not a modelling
difference. 2e-5 covers it with about 1.8x headroom. Swept across the whole
0811 audit, every tolerance from 1e-6 to 1e-2 rescues exactly the same single
submission, so loosening to 2e-5 buys task 7 and nothing else.

`GRADING_REL_TOLERANCE` itself stays **off**, and the config default stays
1e-6. Wiring the knob is a defect fix; turning it on and loosening it is a
scoring decision, and is left as one.

## GRADING_REL_TOLERANCE stays off, 2026-08-12

Revisiting yesterday's recommendation under a standing rule: err on the side of
current benchmark behaviour unless the argument for deviating is a really good
one, and expect all 22 databases in the run set eventually.

The argument for the flag was that gold's float32 casts produce artefacts no
correct semantic-layer answer can avoid. Measuring which arm it actually helps,
on the 0811 audit at 2e-5, reward-weighted:

| domain | arm | OFF | ON @2e-5 | delta |
|---|---|---|---|---|
| archeology_scan | raw | 1.000 | 1.700 | +0.700 |
| archeology_scan | atscale | 1.400 | 1.400 | +0.000 |
| | lift | +0.400 | -0.300 | -0.700 |
| exchange_traded_funds | raw | 6.100 | 6.100 | +0.000 |
| exchange_traded_funds | atscale | 6.800 | 6.800 | +0.000 |
| | lift | +0.700 | +0.700 | +0.000 |

Across all 95 atscale submissions in the audit it rescues **zero** at any value
from 1e-6 to 1e-2. The only submission it rescues is `archeology_scan_6` on the
RAW arm - a task the semantic layer cannot win anyway (B-12, masked KB term) -
so switching it on today inverts the sign of archeology's lift.

The future case does not save it either. If a re-run lands task 7 with the flag
on: atscale 2.100, raw 1.700, lift +0.400 - identical to the lift with the flag
off. It buys +0.7 absolute to each arm and nothing to the comparison. A grader
change that can only turn 0 into 1, moves both arms equally, and leaves lift
unchanged is just a larger number that is no longer comparable to published
BIRD-Interact figures.

Scale makes it worse rather than better: 183 golds across 11 of the 22
databases carry `::real` casts, so this is the benchmark's house style, not a
quirk of one task, and archeology says the inflation accrues to raw at least as
much as to us.

### Why task 7 diverges, and why the model is NOT being changed to match

Gold casts the JSON sensor fields to `real` (float32), then subtracts near-equal
magnitudes - `ABS(temp - 20)`, `ABS((hum - 50)/2)^1.5`. Cancellation amplifies
float32's ~1e-7 representation error into the 1.13e-5 measured against the live
model. The model casts the same fields to `::numeric`. That one choice is the
entire gap, and the model is computing the MORE accurate value.

Gold's convention is consistent enough to copy - every measure-like JSON field
`::real`, every count-like field `::bigint`, with only `Facet_Faces` and
`Facet_Verts` varying - so the model could match bit-for-bit with no grading
deviation at all. Deliberately not doing it: nothing about the source justifies
float32 (it is JSON text, there is no upstream type to mirror, and `double
precision` would not close the gap - only `real` does), so choosing it is
gold-derived tuning of the kind 824f90b stripped out of the instructions, and it
makes the model less accurate to win one task. Same call as M-11.

Task 7 therefore joins B-17's family: lost to a defect in gold, logged rather
than worked around. Costs archeology 0.7 absolute and costs the lift nothing.

**What would reopen this.** If, with the full database set in, atscale
submissions start failing where a sub-1e-4 gap is the only thing between them
and a pass, then exact comparison is measuring the grader rather than the
semantic layer, and that is a good argument. `GRADING_AUDIT_PATH` makes counting
it free and offline. Report it as a sensitivity number next to the headline,
never inside it.

B-20's wiring stands either way - a declared-but-unread config knob was a defect
regardless of which value we choose. Default stays 1e-6, `GRADING_REL_TOLERANCE`
stays off.
