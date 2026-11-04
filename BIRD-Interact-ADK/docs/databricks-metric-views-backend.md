# The Databricks metric-view backend (`dbx_metric_views`)

The third arm of the benchmark: the same LLM agent, the same user simulator and the same
grader as the `atscale` arm, with the semantic layer replaced by a schema of Unity Catalog
**metric views** on Databricks. It is "scenario 1" of the Databricks comparison: a
one-for-one analog of the AtScale arm in which the agent writes SQL against a curated
semantic model. Scenario 2 (Genie One and the Genie Ontology, no metric views) is a
separate backend still to build; see the end of this page.

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

`.env` needs `DATABRICKS_HOST`, `DATABRICKS_TOKEN` (a PAT) and `DATABRICKS_WAREHOUSE_ID`.

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

## Scenario 2 (not built yet)

Genie One / Genie Ontology over the base tables only: a backend whose tools ask Genie
(`genie_ask` on the Genie One managed MCP), whose domain is `{catalog, schema, objects:
tables}`, and which runs under a principal with `SELECT` on the base tables but not on the
metric views, so the ontology cannot draw on them. It should run before the metric-view
arms pour queries into the ontology's learning history.
