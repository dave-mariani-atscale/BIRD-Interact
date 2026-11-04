# The Databricks metric-view backend (`dbx_metric_views`)

The third arm of the benchmark: the same LLM agent, the same user simulator and the same
grader as the `atscale` arm, with the semantic layer replaced by a schema of Unity Catalog
**metric views** on Databricks. It is "scenario 1" of the Databricks comparison: a
one-for-one analog of the AtScale arm in which the agent writes SQL against a curated
semantic model. Scenario 2 (Genie One and the Genie Ontology over the base tables, no
metric views) is the backend `dbx_genie_ontology`, described at the end of this page.

## What the agent sees

| AtScale arm | Databricks arm | |
| --- | --- | --- |
| one SML model per database | one **schema** per database, `bird_interact.<db>`, holding that database's metric views (`<db>_<grain>`) and the `MANY TO ONE` relationships declared between them | the metric views were built from the SML models, the knowledge base and the task briefs (`bird-atscale-models/databricks/`); never from gold |
| `list_models` | `list_metric_views` | every view's comment, every field and measure, the relationships, then the dialect and discovery notes |
| `explore_columns` / `focus_columns` | `describe_metric_view(view, columns)` | comments, synonyms, sample values for named string fields |
| `get_sml_skills` | (folded into `list_metric_views`) | |
| `run_query` (AtScale logical SQL via MCP) | `run_query` (Databricks SQL on the warehouse) | `MEASURE()` around measures, fields grouped by |
| `ask_user`, `submit_sql` | same | backend-agnostic |

Tool costs mirror the AtScale arm (list 1, describe 0.5, run 1, ask 2, submit 3). The
instruction is the AtScale instruction with the tool list and the three
semantic-layer-mechanics bullets rewritten; every strategy tip is verbatim
(`config/environment_backends.yaml`, generated 2026-11-04), so the arms differ in the
semantic layer and nothing else.

## Domain = schema + object kind

A domain entry is `{catalog: bird_interact, schema: <db>, objects: metric_views}`.
`shared.environment_backends._schema_domain_violation` checks every table reference of a
statement (parsed with sqlglot's Databricks dialect): it must be a metric view of that
schema (CTE names and `information_schema` reads are allowed; base tables and other
schemas are refused). The same guard runs in `run_query` and before grading, so a
submission cannot be scored on base tables. The object list comes from
`information_schema.tables` once per process (`shared.databricks_sql.schema_objects`).

## Execution and grading

`shared/databricks_sql.py` is the one Statement Execution API client both sides use. The
agent's `run_query` and the grader's re-execution run the statement with the domain's
catalog and schema as defaults on warehouse `DATABRICKS_WAREHOUSE_ID`. Rows come back
typed from the result manifest (int, float, Decimal, date, datetime, bool, dict for
VARIANT) because the grader compares them with gold rows psycopg2 returns typed from
Postgres; the JSON_ARRAY wire format is all strings.

`db_environment/server.py`: a backend whose config carries `executor: databricks` takes
the new branch in `_submit_sql_sync` (`_run_query_via_databricks`), then the existing
`ex_base_external_pred` row comparison and `record_graded_submission` (the Databricks
statement id is recorded where the AtScale path records the engine `query_id`).

`.env` needs `DATABRICKS_HOST`, `DATABRICKS_TOKEN` (a PAT) and `DATABRICKS_WAREHOUSE_ID`. A
backend whose block names a `token_env` runs as that variable's principal instead
(`shared/databricks_auth.py`; scenario 2 below), on the agent's side, in the domain guard's
object listing and in the grader's re-execution alike.

## Running

```bash
# smoke: two tasks of one database
bash scripts/run_eval.sh --mode a-interact --backend dbx_metric_views --databases solar_panel --limit 2
# the n=1 head-to-head against the AtScale arm (Sonnet 5 / Sonnet 5, corrected grading, cold stores)
nohup bash scripts/run_dbx_vs_atscale_n1.sh > logs/dbx_vs_atscale_n1/launcher.log 2>&1 &
```

The backend block exists in both `config/environment_backends.yaml` and
`config/environment_backends.no_gold_930.yaml`; the comparison uses the latter so the
AtScale arm runs on the no-gold-930 catalog the n=3 runs measured.

## Known engine differences that can fail a task for no modeling reason

- `SUM` over a Postgres `real` column accumulates in 4-byte float on Postgres and in
  DOUBLE here (sixth significant digit); `AVG` agrees.
- NULL ordering is the opposite of Postgres; the dialect note tells the agent to write
  `NULLS FIRST/LAST`.
- Identifiers are lower-case; Postgres enum columns are strings; `char(n)` keeps padding.
- `current_date()` is UTC on the warehouse; the Postgres container runs Asia/Hong_Kong.

## Scenario 2: Genie One and the Genie Ontology over the base tables (`dbx_genie_ontology`)

Built 2026-11-04. The agent **never writes SQL**. It passes the user's question, and later
the user's clarifications, verbatim to Genie One (Databricks' natural-language data agent,
grounded in the Genie Ontology, reached through the workspace's managed MCP), and submits
the SQL Genie produced. Genie works over the **base tables** of `bird_interact.<db>` only:
the metric views are invisible to it because the whole arm runs as a principal that has no
privilege on them, and Genie draws only on assets its caller can access.

### The benchmark principal

Service principal `bird-benchmark-ontology` (application id
`27c3bcaa-2103-4b25-b9ad-792c9cf728ef`, workspace id 147725060338631), created 2026-11-04
with the SCIM API, entitlements `workspace-access` and `databricks-sql-access`, `CAN_USE` on
warehouse `b1a1ad089fa01319`, and these Unity Catalog grants (made as the catalog owner):

```sql
GRANT USE CATALOG ON CATALOG bird_interact TO `27c3bcaa-2103-4b25-b9ad-792c9cf728ef`;
GRANT USE SCHEMA ON SCHEMA bird_interact.<db> TO `27c3bcaa-...`;          -- each of the 22 schemas
GRANT SELECT ON TABLE bird_interact.<db>.<base table> TO `27c3bcaa-...`;  -- each of the 244 base tables
-- nothing on the 119 metric views (or the 31 information_schema views)
```

Verified as the principal (`SELECT current_user()` returns the application id): a base
table reads (`SELECT COUNT(*) FROM bird_interact.solar_panel.plants` = 939), a metric view is
refused (`INSUFFICIENT_PERMISSIONS ... does not have SELECT on Table
bird_interact.solar_panel.solar_panel_plants`), `information_schema.tables` lists 244 MANAGED
tables in 22 schemas and no `METRIC_VIEW` row, and Genie One, asked how many plants
solar_panel has, reports "Single table; inspecting plants" (asked the same as the owner it
had said "inspecting the plants table and plants metric view").

The workspace refuses on-behalf-of PATs for service principals (`FEATURE_DISABLED`), so the
principal's credential is an OAuth secret, created with
`databricks service-principal-secrets-proxy create 147725060338631 --lifetime 7776000s`
(expires 2027-02-02; re-run that command and replace the value in `.env` before then).
`.env` holds it as `DATABRICKS_TOKEN_ONTOLOGY=oauth-m2m:<client_id>:<client_secret>`;
`shared/databricks_auth.resolve_token` exchanges it for a one-hour access token at
`<host>/oidc/v1/token` (client_credentials, scope all-apis) and refreshes it five minutes
before expiry. A plain PAT in the same variable is used as is. `DATABRICKS_TOKEN` (the
owner) stays what scenario 1 runs as.

### The backend

| | `dbx_genie_ontology` |
| --- | --- |
| config block | both backends files; `executor: databricks`, `dialect: databricks`, `token_env: DATABRICKS_TOKEN_ONTOLOGY`, domains `{catalog: bird_interact, schema: <db>, objects: tables}` for the 22 databases |
| tools | `ask_genie` (1 coin), `ask_user` (2), `submit_sql` (3); no SQL-authoring tool (`system_agent/tools_genie_one.py`, factory `get_ainteract_tools_genie_one`) |
| `ask_genie(question)` | `genie_ask` on the Genie One MCP (`/ai-gateway/mcp-services/system.ai.genie_one_mcp`, bearer = the principal's token) with the task's conversation (one Genie conversation per task, created on the first call and continued across turns and phases: `genie_conversation_id` in session state), `genie_poll_response` every 5 s to completion (540 s cap, then `genie_cancel_response`), `genie_get_query_result` for the rows of the last query. Returns Genie's answer text (deep links stripped), Genie's notes, every SQL it ran with the last one marked as the answer's, and that SQL's rows as typed JSON (first 200) |
| domain guard | `objects: tables`: a submission may read only base tables of the task's schema (CTE names and `information_schema` allowed); the object list is read as the principal |
| grading | the existing `executor: databricks` branch; `_run_query_via_databricks` runs the submission as the principal (`token_env` is stamped onto the domain by `get_domain_config`), so a submission is graded with exactly the grants the agent had |
| instruction | the `dbx_metric_views` instruction with the intro, the tool list and the bullets that name a discovery or query tool rewritten for Genie; every other strategy tip is verbatim |

The rewritten bullets (generated from the scenario 1 block; the generator asserts each
original appears once and that no `list_metric_views`, `describe_metric_view`, `run_query`,
`MEASURE(` or "semantic layer" survives): the first sentence and the "Your goal" line, the
"You can: 2." line, the tool list, "THE MODEL FLAGS ITS OWN AMBIGUITIES" (now "GENIE FLAGS
ITS OWN ASSUMPTIONS"), "THE SEMANTIC LAYER DESCRIBES ITS OWN DIALECT" (now "GENIE DOES THE
DISCOVERY AND THE SQL; YOU CARRY THE USER'S WORDS"), "A RATE, SHARE, RATIO ... READ THE
MEASURES" (now "... GENIE PICKS THEM UNLESS YOU NAME THEM"), "Before a column goes into a
submitted query, read its comment" (now "Before you submit, read Genie's SQL and rows against
what the user settled") and the follow-up budget bullet (4 coins: one ask_genie, one
submit).

### Fairness

No knowledge-base text, gold SQL or task question lives in Databricks: the ontology sees the
base tables, their column comments (the BIRD column meanings, loaded 2026-11-03) and the
questions Genie is asked during the run. The agent names the database in its first question
("In the bird_interact.<db> database: ..."), as the raw arm knows the database too. The
ontology learns from the questions it answers, so this arm should run before the metric-view
arms pour queries into its learning history; the smoke tests below and the scenario 1 run
of 2026-11-04 (`results/dbx_vs_0910`) already precede it.

### Running

```bash
# smoke: two tasks of one database (the services must be running on the current code)
bash scripts/run_eval.sh --mode a-interact --backend dbx_genie_ontology --databases solar_panel --limit 2
# the n=1 arm (Sonnet 5 / Sonnet 5, corrected grading, non-leaderboard, 410 Query tasks)
mkdir -p logs/dbx_ontology_n1 && nohup bash scripts/run_dbx_ontology_n1.sh > logs/dbx_ontology_n1/launcher.log 2>&1 &
```

The launcher checks, as the principal, that 244 base tables in 22 schemas are visible and
no metric view is (it refuses otherwise), that the Genie One MCP answers, and that the
backend has 22 domains; it does not touch the AtScale engine, feedback store or aggregates.
Every graded submission is a line in `results/grading_audit.jsonl` with
`backend: dbx_genie_ontology`, the submitted SQL, the Databricks statement id and the rows.

### Smoke test (2026-11-04, solar_panel_1 and solar_panel_2, Sonnet 5 / Sonnet 5)

`results/dbx_ontology_smoke/solar_panel_2_20261104_134700.json`; both tasks graded without
infrastructure errors, four grading-audit lines with `backend: dbx_genie_ontology`:

| task | phase | attempt | passed | statement id | submitted SQL (Genie's) |
| --- | --- | --- | --- | --- | --- |
| solar_panel_1 | 1 | 1 | yes | 01f1d899-93bd-1be9-ae6d-9083273b2994 | `SELECT TRY_DIVIDE(o.mttrh, o.mtbfh + o.mttrh) AS downtime_score FROM plants p JOIN plant_record ...` |
| solar_panel_1 | 2 | 1 | yes | 01f1d899-b69e-1058-93db-8fe71d693a3f | `WITH su AS (SELECT p.sitelabel, o.mttrh / (o.mtbfh + o.mttrh) AS su FROM plants p JOIN ...` |
| solar_panel_2 | 1 | 1 | no | 01f1d899-bdb5-1817-ad8a-207f0f77d667 | `WITH s AS (SELECT p.sitekey, CAST(e.elec_perf_snapshot:efficiency.cumulative_deg_pct AS DOUBLE) ...` (63,354,700.25) |
| solar_panel_2 | 1 | 2 | yes | 01f1d89a-0206-1a47-b76d-31b5572798b3 | same shape, degradation used as stored (73,801,690.91) |

solar_panel_1: reward 1.0 (both phases), 13 of 18 coins, 194 s: ask_genie, ask_user (the
formula), ask_genie with the clarification, ask_genie (value alone), submit; follow-up:
two ask_genie, submit. solar_panel_2: reward 0.7 (phase 1 on the second submit), all 18
coins, 320 s; the budget ran out before the follow-up. Genie turns took 14-80 s. The agent
prefixed every question with the database name and sent clarifications as "The user
clarified: ..." follow-ups in the one conversation, as the instruction asks.
