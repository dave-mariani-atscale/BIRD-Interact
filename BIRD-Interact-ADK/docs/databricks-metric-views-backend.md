# The Databricks backends of the AtScale comparison

## The scenarios (consolidated 2026-11-08)

In every scenario, the BIRD agent (Sonnet 5) hands each question to **Genie One**, grounded in the
workspace's Genie Ontology, and submits the SQL Genie wrote. Each scenario is compared with the
2026-09-10 AtScale sweep. The scenarios differ only in what Genie One can read:

| # | Scenario | Backend | Identity | What Genie One can read |
| ---: | --- | --- | --- | --- |
| 1 | Genie One on raw data (no Metric Views) | `dbx_genie_ontology_no_mv` | `bird-benchmark-ontology` | the 244 base tables of `bird` |
| 2 | Genie One + Genie-generated Metric Views | `dbx_genie_ontology_genie_mv` | `bird-benchmark-genie-mv` | the base tables + the 121 metric views Genie One authored in `bird_genie_mv.<db>` |
| 3 | Genie One + AtScale-generated Metric Views | `dbx_genie_ontology` | the workspace owner | the base tables + the 119 metric views generated from the AtScale SML models, and anything else the owner can read |

```bash
REPEAT=3 bash scripts/run_databricks_scenario.sh 1   # or genie-one-raw / genie-one-genie-views / genie-one-atscale-views
python scripts/genie_one_by_db.py --backend dbx_genie_ontology_genie_mv   # per database, vs AtScale and the other two
```

- **Old numbering.** Runs before 2026-11-08 used scenarios 3 (still 3), 4 (now 1) and 5 (now 2).
- **Retired scenarios.** "Metric Views + 3rd-party agent" (`dbx_metric_views`, described first below)
  and "Metric Views + Genie space" (`dbx_genie_space`, at the end) are no longer offered by the
  launcher. Their config blocks and code are kept, so their runs stay reproducible.

The rest of this page documents each backend in the order it was built.

# The Databricks metric-view backend (`dbx_metric_views`, retired 2026-11-08)

The third arm of the benchmark: the same LLM agent, the same user simulator and the same
grader as the `atscale` arm, with the semantic layer replaced by a schema of Unity Catalog
**metric views** on Databricks. It was "scenario 1" of the Databricks comparison until 2026-11-08: a
one-for-one analog of the AtScale arm in which the agent writes SQL against a curated
semantic model. The Genie One backends (the three current scenarios) are described after it.

## What the agent sees

| AtScale arm | Databricks arm | |
| --- | --- | --- |
| one SML model per database | one **schema** per database, `bird.<db>`, holding that database's metric views (`<db>_<grain>`) and the `MANY TO ONE` relationships declared between them | the metric views were built from the SML models, the knowledge base and the task briefs (`bird-atscale-models/databricks/`); never from gold |
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

A domain entry is `{catalog: bird, schema: <db>, objects: metric_views}`.
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

## Genie One and the Genie Ontology (`dbx_genie_ontology`; scenario 3 since 2026-11-08)

Built 2026-11-04. The agent **never writes SQL**. It passes the user's question, and later
the user's clarifications, verbatim to Genie One (Databricks' natural-language data agent,
grounded in the Genie Ontology, reached through the workspace's managed MCP), and submits
the SQL Genie produced. Genie works over the **base tables** of `bird.<db>` only:
the metric views are invisible to it because the whole arm runs as a principal that has no
privilege on them, and Genie draws only on assets its caller can access.

### The benchmark principal

Service principal `bird-benchmark-ontology` (application id
`27c3bcaa-2103-4b25-b9ad-792c9cf728ef`, workspace id 147725060338631), created 2026-11-04
with the SCIM API, entitlements `workspace-access` and `databricks-sql-access`, `CAN_USE` on
warehouse `b1a1ad089fa01319`, and these Unity Catalog grants (made as the catalog owner):

```sql
GRANT USE CATALOG ON CATALOG bird TO `27c3bcaa-2103-4b25-b9ad-792c9cf728ef`;
GRANT USE SCHEMA ON SCHEMA bird.<db> TO `27c3bcaa-...`;          -- each of the 22 schemas
GRANT SELECT ON TABLE bird.<db>.<base table> TO `27c3bcaa-...`;  -- each of the 244 base tables
-- nothing on the 119 metric views (or the 31 information_schema views)
```

Verified as the principal (`SELECT current_user()` returns the application id): a base
table reads (`SELECT COUNT(*) FROM bird.solar_panel.plants` = 939), a metric view is
refused (`INSUFFICIENT_PERMISSIONS ... does not have SELECT on Table
bird.solar_panel.solar_panel_plants`), `information_schema.tables` lists 244 MANAGED
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
owner) stays what the metric-view arm (`dbx_metric_views`) runs as.

### The backend

| | `dbx_genie_ontology` |
| --- | --- |
| config block | both backends files; `executor: databricks`, `dialect: databricks`, `token_env: DATABRICKS_TOKEN_ONTOLOGY`, domains `{catalog: bird, schema: <db>, objects: tables}` for the 22 databases |
| tools | `ask_genie` (1 coin), `ask_user` (2), `submit_sql` (3); no SQL-authoring tool (`system_agent/tools_genie_one.py`, factory `get_ainteract_tools_genie_one`) |
| `ask_genie(question)` | `genie_ask` on the Genie One MCP (`/ai-gateway/mcp-services/system.ai.genie_one_mcp`, bearer = the principal's token) with the task's conversation (one Genie conversation per task, created on the first call and continued across turns and phases: `genie_conversation_id` in session state), `genie_poll_response` every 5 s to completion (540 s cap, then `genie_cancel_response`), `genie_get_query_result` for the rows of the last query. Returns Genie's answer text (deep links stripped), Genie's notes, every SQL it ran with the last one marked as the answer's, and that SQL's rows as typed JSON (first 200) |
| domain guard | `objects: tables`: a submission may read only base tables of the task's schema (CTE names and `information_schema` allowed); the object list is read as the principal |
| grading | the existing `executor: databricks` branch; `_run_query_via_databricks` runs the submission as the principal (`token_env` is stamped onto the domain by `get_domain_config`), so a submission is graded with exactly the grants the agent had |
| instruction | the `dbx_metric_views` instruction with the intro, the tool list and the bullets that name a discovery or query tool rewritten for Genie; every other strategy tip is verbatim |

The rewritten bullets (generated from the `dbx_metric_views` block; the generator asserts each
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
("In the bird.<db> database: ..."), as the raw arm knows the database too. The
ontology learns from the questions it answers, so this arm should run before the metric-view
arms pour queries into its learning history; the smoke tests below and the metric-view arm's run
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

## Scenario 1: Genie One on raw data, no Metric Views (`dbx_genie_ontology_no_mv`; scenario 4 before 2026-11-08)

Scenario 3 (`dbx_genie_ontology`) has run as the owner since 5439e72, so Genie One can pick
metric views, base tables or anything else. Scenario 4 is the same arm with the metric views
hidden. It uses the same instruction, tools and coin costs, but runs as the benchmark
principal above (`token_env: DATABRICKS_TOKEN_ONTOLOGY`) with all 22 domains `objects: tables`.
Genie One, the domain guard and grading therefore all see only the 244 base tables.

```bash
REPEAT=3 bash scripts/run_databricks_scenario.sh 1     # or: genie-one-raw
```

**Hiding depends on the catalog's grants, not on the harness.** Unity Catalog has no deny.
On 2026-11-06 the catalog carried a catalog-wide grant to `account users` (USE CATALOG,
USE SCHEMA, SELECT, BROWSE, READ METADATA). Every user and service principal belongs to that
group, so the principal could read all 119 metric views and their comments. The grant was
revoked that day. The principal's grants and the revoke are recorded in
`bird-databricks-models/grants/benchmark_principal.sql`. The pre-run check of
`run_databricks_scenario.sh 1` runs as the principal and refuses to start unless all of
these hold:
- the backend is `token_env` + `objects: tables`;
- `current_user()` is not the owner;
- `information_schema.tables` shows MANAGED 244 and METRIC_VIEW 0;
- `bird.solar_panel.solar_panel_plants` is refused;
- the Genie One MCP lists its tools with the principal's token.

Checked 2026-11-06 after the revoke:
- The pre-run check passes.
- Asked as the principal to list every table and metric view in `bird.solar_panel`, Genie
  One answered "10 tables, no metric views" (its SQL read `information_schema.tables`, all
  MANAGED).
- Asked how many plants there are and their capacity, it read `bird.solar_panel.plants`
  (939 plants, 238,380.36 MW).
- End-to-end smoke run of `solar_panel_1` and `solar_panel_2` (Sonnet 5 / Sonnet 5, on this
  checkout's ports 6200-6202):
  - Tools used: `ask_genie` 9 times (6 base-table reads, 3 turns with no SQL), `ask_user` 3,
    `submit_sql` 3.
  - Every graded submission read only base tables.
  - `solar_panel_1` passed both phases (10 coins, 151 s). `solar_panel_2` failed phase 1 and
    used all 18 coins (269 s).

## Scenario 2: Genie One + Genie-generated Metric Views (`dbx_genie_ontology_genie_mv`; scenario 5 before 2026-11-08)

Scenario 3 with the AtScale-derived metric views replaced by **121 metric views Genie One authored itself**
in `bird_genie_mv.<db>`. It worked from the base tables, the BIRD knowledge base and the gold-free task
briefs, the same inputs as the AtScale SML models. The authoring protocol, prompts, transcripts and
deployed DDL are in `bird-databricks-models/genie_metric_views`.

It runs as a third principal, `bird-benchmark-genie-mv` (`token_env: DATABRICKS_TOKEN_GENIE_MV`).
- It reads the 244 base tables and the 121 Genie views.
- It does not read the AtScale-derived views or the authoring inputs.
- It is not the authoring identity, because Genie One remembers earlier conversations per user.

The domains are `{catalog: bird, schema: <db>, objects: tables, views_catalog: bird_genie_mv}`. The new
`views_catalog` key lets the domain guard accept the metric views of `bird_genie_mv.<db>`, and
`objects_read` counts them as metric views, so the route split (metric views / base tables / both) means
the same as in scenario 3.

The instruction is scenario 3's with one change: the question prefix is "In the bird.<database>
database, whose metric views are in bird_genie_mv.<database>: ...", because the views no longer sit in
the task schema.

```bash
REPEAT=3 bash scripts/run_databricks_scenario.sh 2     # or: genie-one-genie-views
```

The pre-run check asserts, as the run principal:
- `current_user()` is not the owner, and the identity is neither the scenario 1 nor the authoring one;
- `bird` shows 244 MANAGED and 0 METRIC_VIEW;
- `bird_genie_mv` shows 121 METRIC_VIEW and no table (no `build_inputs`);
- an AtScale view is refused, and a Genie view is queryable;
- Genie One is reachable.

Checked 2026-11-06 (worktree `BIRD-Interact-genie-mv`, ports 6300-6302):
- The pre-run check passes.
- Smoke run of `solar_panel_1` and `solar_panel_2`: 1 of 2, the same as scenario 1's smoke run.
  - `solar_panel_1` passed both phases.
  - Of Genie's 10 turns, 5 read its own view `solar_snapshot_performance` and 5 read base tables.
  - The guard rejected nothing.

## Genie over the metric views (`dbx_genie_space`, retired 2026-11-08)

Genie as the SQL author inside the BIRD agent loop. Sonnet stays the agent with its budget,
its asks and its submits; its only data tool is `ask_genie` (1 coin), which carries the
user's question and clarifications into one Genie conversation per task, in a Genie
**space** per database that holds only that database's metric views. No discovery tools of
our own: Genie does the discovery over the views, whose comments carry the knowledge base.

- **Spaces:** `scripts/provision_genie_spaces.py` creates or updates "BIRD <db> (metric
  views)" for all 22 databases (5 to 13 views each, under Genie's 30-object cap), with no
  instructions, example SQL or sample questions, verifies each holds exactly its views, and
  writes the space ids into the `dbx_genie_space` domains. One space per database mirrors
  one SML model per database; one per view would cut the model's relationships, and one for
  all 22 exceeds the cap and Databricks' one-domain-per-space guidance.
- **Tools:** `system_agent/tools_genie_space.py` (Conversation API; retries 429 and
  transient errors; the answer layout is shared with the Genie One arm).
- **Credential and fallback:** the owner token (decided 2026-11-04), so Genie can read the
  database's base tables as well as its metric views (Unity Catalog permissions, not the
  space, bound what it queries). That fallback is ALLOWED, as it would be for a customer
  whose principal can read the tables: the domains are `objects: any` (the whole schema;
  other databases are still refused). It is recorded, never signalled to the agent:
  every graded submission carries `objects_read` and `reads_base_tables` in the grading
  audit, and every Genie turn's `objects_read` is kept in session state. Two figures come
  out of one run: the overall pass rate (the customer-realistic one) and the views-only
  pass rate, which counts a pass only when the passing SQL read nothing but metric views
  (the like-for-like figure against the AtScale arm, whose agent cannot reach Postgres).
  `scripts/compare_vs_baseline_runs.py --audit results/grading_audit.jsonl` prints both,
  the fallback counts, and a paired McNemar for the views-only figure.
- **Cost:** `ask_genie` costs 1 coin when Genie runs a query (an execute) and 0.5 when it does
  not (it asks back, explains or declines), the BIRD Universal Cost Scheme's small-action
  price (decided 2026-11-04). The full coin is reserved before the call and the difference
  refunded after it (`small_action_costs` in the config, `system_agent/callbacks.py`). The
  first full-cost run was stopped after 64 tasks for this: 35 of its first 60 tasks ran out
  of budget against 22 for the metric-view arm, and 100 of its 340 Genie turns returned no
  SQL yet cost a full coin.
- **Run:** `scripts/run_dbx_genie_space_vs_0910.sh` (ports 6200-6202, concurrency 3 because
  the Genie API rate-limits; compared with the 09-10 AtScale sweep like the metric-view arm).

Smoke (2026-11-04, solar_panel_1 and 2): both graded on the warehouse; one P1 pass. Genie wrote
`MEASURE()` SQL over the views, found `system_unavailability` through its "downtime score"
synonym, asked its own clarifying questions, and declined to pass a recorded figure off as a
projection because the view's comment says it is not one. Both tasks spent 17-18 of 18 coins
(every Genie turn, its own clarifying questions included, costs a coin), so expect phase 2
to suffer from budget; turns took 7-57 s.
