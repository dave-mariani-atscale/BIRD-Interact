"""Loader for config/environment_backends.yaml — semantic-layer backend config.

See that file's header comment for the schema. `get_backend_config(name)`
returns the backend's dict (mcp_url_env/mcp_token_env/domains); the caller
resolves the actual URL/token via shared.config.settings.
"""

import importlib
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import sqlglot
import yaml
from sqlglot import expressions as exp

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "environment_backends.yaml"

_cache: Dict[str, Any] = {}


def load_backends() -> Dict[str, Any]:
    if "backends" not in _cache:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _cache["backends"] = data.get("backends", {})
    return _cache["backends"]


def get_backend_config(name: str) -> Dict[str, Any]:
    backends = load_backends()
    if name not in backends:
        raise ValueError(f"Unknown environment backend '{name}' in {_CONFIG_PATH}. Available: {sorted(backends.keys())}")
    return backends[name]


def get_domain_config(backend_name: str, selected_database: str) -> Dict[str, str]:
    """Return {catalog, schema, table} for this domain under this backend, or
    None if the domain has no semantic model configured yet."""
    backend = get_backend_config(backend_name)
    return backend.get("domains", {}).get(selected_database)


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
        statement = sqlglot.parse_one(query)
    except Exception as e:
        logger.warning("domain guard: could not parse query (%s); allowing through", e)
        return None
    if statement is None:
        return None

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
