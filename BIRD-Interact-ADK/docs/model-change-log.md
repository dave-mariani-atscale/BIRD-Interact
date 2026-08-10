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

A redeploy is required before the remaining gate rows can run, and before the
benchmark: the deployed build still has D-01.
