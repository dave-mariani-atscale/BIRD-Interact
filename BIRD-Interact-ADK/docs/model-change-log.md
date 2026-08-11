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

**Catalog schema is `bird_atscale_models_catalog`, NOT `..._main`.** `sml-cli
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
