"""Loader for config/environment_backends.yaml — semantic-layer backend config.

See that file's header comment for the schema. `get_backend_config(name)`
returns the backend's dict (mcp_url_env/mcp_token_env/domains); the caller
resolves the actual URL/token via shared.config.settings.
"""

import importlib
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import sqlglot
import yaml
from sqlglot import expressions as exp

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# ENVIRONMENT_BACKENDS_FILE points a run at another copy of this config (e.g. one database's
# domain entry repointed at a different catalog). Relative paths resolve against the project
# root; the file used is recorded in each results file's deviations block.
_CONFIG_PATH = Path(os.environ.get("ENVIRONMENT_BACKENDS_FILE", "").strip() or "config/environment_backends.yaml")
if not _CONFIG_PATH.is_absolute():
    _CONFIG_PATH = _PROJECT_ROOT / _CONFIG_PATH

_cache: Dict[str, Any] = {}


def load_backends() -> Dict[str, Any]:
    if "backends" not in _cache:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _cache["backends"] = data.get("backends", {})
    return _cache["backends"]


#: The Databricks scenarios of the AtScale comparison (consolidated 2026-11-08), selectable with
#: `orchestrator.runner --databricks-scenario <n|name>` (or scripts/run_databricks_scenario.sh). In all
#: three the BIRD agent hands every question to Genie One (grounded in the workspace's Genie Ontology)
#: and submits the SQL Genie wrote; they differ only in what Genie One can read:
#:   1 genie-one-raw            : Genie One on raw data, no Metric Views. Runs as bird-benchmark-ontology
#:                                (DATABRICKS_TOKEN_ONTOLOGY): the 244 base tables of `bird`, nothing else.
#:   2 genie-one-genie-views    : Genie One + Genie-generated Metric Views. Runs as bird-benchmark-genie-mv
#:                                (DATABRICKS_TOKEN_GENIE_MV): the base tables plus the 121 metric views Genie
#:                                One authored in `bird_genie_mv.<db>` (bird-databricks-models/genie_metric_views).
#:   3 genie-one-atscale-views  : Genie One + AtScale-generated Metric Views: the base tables plus the 119
#:                                metric views generated from the AtScale SML models (`bird.<db>`). Runs as the
#:                                workspace owner (DATABRICKS_TOKEN), as in the 2026-11-05 n=3 run.
#: Retired 2026-11-08 (backends kept so their runs stay reproducible, no longer offered here):
#: dbx_metric_views (Metric Views + 3rd-party agent) and dbx_genie_space (Metric Views + Genie space).
#: Runs before the consolidation were numbered 3 (now 3), 4 (now 1) and 5 (now 2).
DATABRICKS_SCENARIOS = {
    "1": "dbx_genie_ontology_no_mv", "genie-one-raw": "dbx_genie_ontology_no_mv",
    "2": "dbx_genie_ontology_genie_mv", "genie-one-genie-views": "dbx_genie_ontology_genie_mv",
    "3": "dbx_genie_ontology", "genie-one-atscale-views": "dbx_genie_ontology",
}
DATABRICKS_SCENARIO_LABELS = {
    "dbx_genie_ontology_no_mv": "Scenario 1: Genie One on raw data (no Metric Views)",
    "dbx_genie_ontology_genie_mv": "Scenario 2: Genie One + Genie-generated Metric Views",
    "dbx_genie_ontology": "Scenario 3: Genie One + AtScale-generated Metric Views",
    # retired backends, labelled for old logs and reports
    "dbx_metric_views": "Retired: Metric Views + 3rd-party agent",
    "dbx_genie_space": "Retired: Metric Views + Genie Agent (Genie space)",
}


#: The Snowflake scenarios (2026-11-20), the same three setups on Snowflake: the BIRD agent hands every
#: question to a Cortex Agent grounded in the database's Cortex Sense context and submits the SQL it ran.
#: `orchestrator.runner --snowflake-scenario <n|name>` (or scripts/run_snowflake_scenario.sh).
#:   1 cortex-sense-raw            : Cortex Sense on raw data, no Semantic Views (role BIRD_S1).
#:   2 cortex-sense-coco-views     : Cortex Sense + the Semantic Views Cortex Code authored (role BIRD_S2).
#:   3 cortex-sense-atscale-views  : Cortex Sense + Semantic Views generated from the AtScale SML models (role BIRD_S3).
SNOWFLAKE_SCENARIOS = {
    "1": "sf_cortex_sense_raw", "cortex-sense-raw": "sf_cortex_sense_raw",
    "2": "sf_cortex_sense_coco_views", "cortex-sense-coco-views": "sf_cortex_sense_coco_views",
    "3": "sf_cortex_sense_atscale_views", "cortex-sense-atscale-views": "sf_cortex_sense_atscale_views",
}
SNOWFLAKE_SCENARIO_LABELS = {
    "sf_cortex_sense_raw": "Scenario 1: Cortex Sense on raw data (no Semantic Views)",
    "sf_cortex_sense_coco_views": "Scenario 2: Cortex Sense + Cortex Code-generated Semantic Views",
    "sf_cortex_sense_atscale_views": "Scenario 3: Cortex Sense + AtScale-generated Semantic Views",
}


def resolve_snowflake_scenario(value: str) -> str:
    """Backend name for a --snowflake-scenario value (1-3 or its name)."""
    key = str(value).strip().lower()
    if key not in SNOWFLAKE_SCENARIOS:
        raise ValueError(f"unknown Snowflake scenario {value!r}; use one of "
                         + ", ".join(sorted(k for k in SNOWFLAKE_SCENARIOS if not k.isdigit())) + " or 1-3")
    return SNOWFLAKE_SCENARIOS[key]


def is_warehouse_executor(backend_name: str) -> bool:
    """True for a backend whose submissions are graded by re-executing them on the vendor's own
    warehouse (`executor: databricks` or `executor: snowflake`)."""
    return get_backend_config(backend_name).get("executor") in ("databricks", "snowflake")


def resolve_databricks_scenario(value: str) -> str:
    """Backend name for a --databricks-scenario value (1-3 or its name)."""
    key = str(value).strip().lower()
    if key not in DATABRICKS_SCENARIOS:
        raise ValueError(f"unknown Databricks scenario {value!r}; use one of "
                         + ", ".join(sorted(k for k in DATABRICKS_SCENARIOS if not k.isdigit())) + " or 1-3")
    return DATABRICKS_SCENARIOS[key]


def get_backend_config(name: str) -> Dict[str, Any]:
    backends = load_backends()
    if name not in backends:
        raise ValueError(f"Unknown environment backend '{name}' in {_CONFIG_PATH}. Available: {sorted(backends.keys())}")
    return backends[name]


def get_domain_config(backend_name: str, selected_database: str) -> Dict[str, str]:
    """Return {catalog, schema, table} for this domain under this backend, or
    None if the domain has no semantic model configured yet."""
    backend = get_backend_config(backend_name)
    domain = backend.get("domains", {}).get(selected_database)
    if domain and backend.get("dialect") and "dialect" not in domain:
        # The SQL dialect the guard parses with (sqlglot name), set once per backend.
        domain = {**domain, "dialect": backend["dialect"]}
    if domain and backend.get("token_env") and "token_env" not in domain:
        # The principal a Databricks backend runs as (the agent's queries, the
        # domain guard's object listing and the grader's re-execution alike):
        # the name of the .env variable shared.databricks_auth.resolve_token reads.
        domain = {**domain, "token_env": backend["token_env"]}
    if domain:
        # Snowflake backends: the role the scenario runs as, the executor (which picks the object
        # listing in the guard below) and the Cortex agent's settings, set once per backend.
        for key in ("role", "executor", "agent_model", "views_database", "views_schema_prefix"):
            if backend.get(key) and key not in domain:
                domain = {**domain, key: backend[key]}
    return domain


def _lister(domain: Dict[str, str]):
    """(objects, views_kind): `objects(catalog, schema, kind)` lists a schema's objects as the domain's
    principal on its engine; `views_kind` is that engine's name for its semantic objects."""
    if domain.get("executor") == "snowflake":
        from shared import snowflake_sql
        return (lambda c, s, k: snowflake_sql.schema_objects(
            c, s, "semantic_views" if k == "metric_views" else k, domain)), "semantic view"
    from shared import databricks_sql
    from shared.databricks_auth import resolve_token
    return (lambda c, s, k: databricks_sql.schema_objects(
        c, s, k, token=resolve_token(domain.get("token_env")))), "metric view"


def query_domain_violation(query: str, domain: Dict[str, str]) -> Optional[str]:
    """An error string if `query`'s FROM target is not this domain's model, else None.

    Nothing else forces the agent onto the model the task is about. explore_columns
    and focus_columns are scoped server-side (the MCP tools take catalog/schema/table),
    but run_query takes only `query` — so with two same-labelled models deployed, an
    agent can explore one and query the other, and a submission can be *graded* against
    the wrong one. This is the only thing standing between those.

    Takes an already-resolved domain dict rather than a backend name, so it never has
    to special-case "raw" (which has no backend config entry at all).

    Deliberately permissive in two places, because a guard that blocks valid work is
    worse than the leak it prevents:
      - unparseable query -> None. The engine is a better judge of its own dialect, and
        its syntax error is more useful to the agent than ours would be.
      - single-part table name -> skipped. The MCP rejects those itself with a clearer
        message (validation.py's FromQualificationError); duplicating it here would only
        make the two disagree over time.
    """
    try:
        statement = sqlglot.parse_one(query, read=domain.get("dialect") or None)
    except Exception as e:
        logger.warning("domain guard: could not parse query (%s); allowing through", e)
        return None
    if statement is None:
        return None
    if domain.get("objects"):
        return _schema_domain_violation(statement, domain)

    want_schema = domain.get("schema", "").casefold()
    want_table = domain.get("table", "").casefold()
    want_catalog = domain.get("catalog", "").casefold()

    for tbl in statement.find_all(exp.Table):
        schema = tbl.text("db")
        if not schema:
            continue
        catalog = tbl.text("catalog")
        if (
            schema.casefold() == want_schema
            and tbl.name.casefold() == want_table
            and (not catalog or catalog.casefold() == want_catalog)
        ):
            continue
        found = ".".join(p for p in (catalog, schema, tbl.name) if p)
        return (
            f'Query rejected: it references "{found}", which is not the semantic model '
            f"for this task. This task is about "
            f'"{domain.get("schema")}"."{domain.get("table")}" — query only that model, '
            "exactly as list_models returned it. Another model may look similar or even "
            "share its label; results from it do not answer this question."
        )
    return None


def _schema_domain_violation(statement, domain: Dict[str, str]) -> Optional[str]:
    """Schema-level domains (Databricks backends). A domain is {catalog, schema,
    objects} where objects is "metric_views" or "tables": every table reference
    must be an object of that kind in that schema (or an information_schema read,
    which is metadata the discovery tools already expose). A CTE or subquery
    alias is not a table reference. Unqualified names are allowed because the
    statement executes with the domain's catalog and schema as defaults."""
    objects, views_kind = _lister(domain)  # lazy: only warehouse backends need a client

    want_catalog = domain.get("catalog", "").casefold()
    want_schema = domain.get("schema", "").casefold()
    try:
        allowed = objects(domain["catalog"], domain["schema"], domain["objects"])
    except Exception as e:  # noqa: BLE001 - a dead warehouse must not look like a wrong model
        logger.warning("domain guard: could not list %s of %s.%s (%s); allowing through",
                       domain.get("objects"), want_catalog, want_schema, e)
        return None
    # views_catalog (scenario 5): the domain's metric views live in <views_catalog>.<schema>, a second
    # catalog beside the base tables of <catalog>.<schema>; a reference to one of them is allowed too.
    views_catalog = (domain.get("views_catalog") or "").casefold()
    views = set()
    if views_catalog:
        try:
            views = objects(domain["views_catalog"], domain.get("views_schema") or domain["schema"], "metric_views")
        except Exception as e:  # noqa: BLE001
            logger.warning("domain guard: could not list metric views of %s.%s (%s); allowing through",
                           views_catalog, want_schema, e)
            return None
    views_schema = (domain.get("views_schema") or domain.get("schema", "")).casefold()
    ctes = {c.alias_or_name.casefold() for c in statement.find_all(exp.CTE)}
    kind = views_kind if domain["objects"] == "metric_views" else "table"
    if views_catalog:
        kind = f"table or {views_kind}"
    for tbl in statement.find_all(exp.Table):
        name = tbl.name.casefold()
        schema = tbl.text("db").casefold()
        catalog = tbl.text("catalog").casefold()
        if not schema and name in ctes:
            continue
        if schema == "information_schema":
            continue
        if views_catalog and catalog == views_catalog and schema == views_schema and name in views:
            continue
        if (catalog and catalog != want_catalog) or (schema and schema != want_schema) or name not in allowed:
            found = ".".join(p for p in (tbl.text("catalog"), tbl.text("db"), tbl.name) if p)
            return (
                f'Query rejected: it references "{found}", which is not a {kind} of this task\'s '
                f'schema "{domain.get("catalog")}"."{domain.get("schema")}"'
                + (f' or "{domain.get("views_catalog")}"."{domain.get("views_schema") or domain.get("schema")}"' if views_catalog else "")
                + f". Query only the {kind}s of {'those schemas' if views_catalog else 'that schema'}, by their exact names."
            )
    return None


def objects_read(query: str, domain: Dict[str, str]) -> Optional[Dict[str, List[str]]]:
    """For a schema-level Databricks domain: which of the schema's objects a statement
    reads, split into {"metric_views": [...], "base_tables": [...], "elsewhere": [...]} (lower-case;
    "elsewhere" holds qualified names of objects outside the task schema or catalog).
    None when the statement does not parse. CTE names and information_schema reads are
    not objects. Used to record a Genie fallback to base tables on every graded
    submission and Genie turn (backend dbx_genie_space, objects: any)."""
    try:
        statement = sqlglot.parse_one(query, read=domain.get("dialect") or None)
    except Exception:
        return None
    if statement is None:
        return None
    views_catalog = (domain.get("views_catalog") or "").casefold()
    views_schema = (domain.get("views_schema") or domain.get("schema", "")).casefold()
    try:
        if domain.get("executor") == "snowflake":
            objects, _ = _lister(domain)
            views = objects(domain["catalog"], domain["schema"], "metric_views")
            side_views = objects(domain["views_catalog"], views_schema, "metric_views") if views_catalog else set()
        else:
            from shared import databricks_sql
            views = databricks_sql.schema_objects(domain["catalog"], domain["schema"], "metric_views")
            side_views = (databricks_sql.schema_objects(domain["views_catalog"], domain["schema"], "metric_views")
                          if views_catalog else set())
    except Exception as e:  # noqa: BLE001
        logger.warning("objects_read: could not list metric views of %s.%s (%s)", domain.get("catalog"), domain.get("schema"), e)
        return None
    ctes = {c.alias_or_name.casefold() for c in statement.find_all(exp.CTE)}
    want_schema = domain.get("schema", "").casefold()
    want_catalog = domain.get("catalog", "").casefold()
    out: Dict[str, set] = {"metric_views": set(), "base_tables": set(), "elsewhere": set()}
    for tbl in statement.find_all(exp.Table):
        name, schema, catalog = tbl.name.casefold(), tbl.text("db").casefold(), tbl.text("catalog").casefold()
        if (not schema and name in ctes) or schema == "information_schema":
            continue
        if views_catalog and catalog == views_catalog and schema == views_schema and name in side_views:
            out["metric_views"].add(name)      # scenario 5: a metric view of <views_catalog>.<schema>
            continue
        if views_catalog and name in views and catalog != views_catalog:
            # scenario 5: a metric view of <catalog>.<schema> (the AtScale-derived ones) is not this
            # domain's; the principal cannot read them, so this only records an attempt.
            out["elsewhere"].add(".".join(p for p in (catalog or domain["catalog"].casefold(), schema or want_schema, name)))
            continue
        if (schema and schema != want_schema) or (catalog and catalog != want_catalog):
            # Another database or catalog: Genie One sees the whole workspace (scenario 3).
            out["elsewhere"].add(".".join(p for p in (catalog, schema, name) if p))
            continue
        out["metric_views" if name in views else "base_tables"].add(name)
    return {k: sorted(v) for k, v in out.items()}


def get_configured_domains(backend_name: str) -> set:
    """The set of selected_database values that have a semantic model configured
    for this backend — used to filter which tasks are eligible to run."""
    backend = get_backend_config(backend_name)
    return set(backend.get("domains", {}).keys())


def get_backend_instruction(backend_name: str) -> str:
    """The full a-interact system prompt for this backend (tool list, costs,
    dialect quirks), authored in config rather than hardcoded in agent.py so a
    new semantic-layer backend only needs a config entry, not a Python change.
    system_agent.agent.build_agent() appends the shared RESULT_SHAPE_TIP."""
    backend = get_backend_config(backend_name)
    instruction = backend.get("instruction")
    # A/B override (2026-09-09, instruction-size experiment): a file whose text
    # replaces the configured instruction for this backend. Off unless the env var
    # is set; the runner records the path in `deviations` so a result file says
    # which instruction it ran under.
    override = os.environ.get("ATSCALE_INSTRUCTION_FILE", "").strip()
    if override and backend_name != "raw":
        instruction = Path(override).read_text()
    if not instruction:
        raise ValueError(
            f"Backend '{backend_name}' in {_CONFIG_PATH} has no 'instruction' - "
            "every non-raw backend must define its a-interact system prompt in config."
        )
    return instruction


def get_backend_tool_costs(backend_name: str) -> Dict[str, float]:
    """This backend's tool-name -> bird-coin cost map, merged over the
    backend-agnostic base costs (ask_user, submit_sql) that live in
    system_agent/callbacks.py. Empty dict if the backend defines none."""
    backend = get_backend_config(backend_name)
    return backend.get("tool_costs", {})


def get_backend_leaderboard_tool_costs(backend_name: str) -> Dict[str, float]:
    """This backend's overrides for leaderboard mode - the costs the BIRD
    submission guidelines' Universal Cost Scheme assigns where they differ from
    the backend's own table (config key `leaderboard_tool_costs`). Applied on
    top of tool_costs by system_agent.callbacks.effective_tool_costs only when
    settings.leaderboard_mode is on. Empty dict if the backend defines none."""
    backend = get_backend_config(backend_name)
    return backend.get("leaderboard_tool_costs", {}) or {}


def get_backend_error_hints(backend_name: str) -> List[Dict[str, str]]:
    """This backend's [{match, hint}] list — a hint is appended to any tool
    response containing `match`. Lets a backend correct its own engine's
    misleading error text without system_agent/callbacks.py learning any
    engine's error strings. Empty list if the backend defines none."""
    backend = get_backend_config(backend_name)
    return backend.get("error_hints", []) or []


def get_backend_tools_factory(backend_name: str) -> Callable[[], List[Any]]:
    """Resolve this backend's ADK tool-list factory from its `tools_module` /
    `tools_factory` config (e.g. system_agent.tools_atscale.get_ainteract_tools_atscale)
    via dynamic import - system_agent.agent.build_agent() never hardcodes which
    backend-specific tools module to use, so adding a new semantic-layer
    backend only means a new tools_<name>.py plus a config entry pointing at
    it, not a change to agent.py."""
    backend = get_backend_config(backend_name)
    module_name = backend.get("tools_module")
    factory_name = backend.get("tools_factory")
    if not module_name or not factory_name:
        raise ValueError(
            f"Backend '{backend_name}' in {_CONFIG_PATH} is missing 'tools_module'/'tools_factory' - "
            "every non-raw backend must declare where its ADK tool-list factory lives."
        )
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name, None)
    if factory is None:
        raise ValueError(f"{module_name} has no attribute '{factory_name}' (backend '{backend_name}')")
    return factory
