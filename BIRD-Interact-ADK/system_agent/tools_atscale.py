"""ADK tools for a-interact mode when ENVIRONMENT_BACKEND is a semantic-layer
backend (e.g. "atscale") instead of "raw".

These replace the raw Postgres exploration tools (get_schema, get_all_column_
meanings, get_column_meaning, get_all_external_knowledge_names/get_knowledge_
definition(s), execute_sql) with the semantic layer's own real MCP tools,
mapped per docs/semantic-layer-environment-backends.md:

    get_schema()                -> list_models()
    get_all_column_meanings()   -> explore_columns(search_terms)
    get_column_meaning()        -> focus_columns(columns)
    get_all_knowledge_definitions() -> get_sml_skills(skill_name)
    execute_sql()                -> run_query(query)

`ask_user`/`submit_sql` are unchanged and imported from tools.py — they're
backend-agnostic (see design doc's fairness principle).

Per-domain catalog/schema/table comes from config/environment_backends.yaml,
keyed by the task's `db_name` (set in session state at init — see
orchestrator/ainteract.py's `init_agent_session`).
"""

import json
import logging
import re
from typing import List, Optional

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from shared.config import settings
from shared.environment_backends import get_domain_config
from shared.mcp_client import MCPClient, MCPEndpoint, MCPClientError, MCPToolError

logger = logging.getLogger(__name__)

_GET_SML_SKILLS_NAME = "query-semantic-layer"


def _get_db_name(tool_context: Optional[ToolContext]) -> str:
    if tool_context:
        return tool_context.state.get("db_name", "")
    return ""


def _mcp_client() -> MCPClient:
    return MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url, bearer_token=settings.semantic_layer_mcp_token))


def _domain_or_error(tool_context: Optional[ToolContext]):
    """Resolve {catalog, schema, table} for the active task's domain, or None
    plus an error string if this domain has no semantic model configured."""
    db_name = _get_db_name(tool_context)
    domain = get_domain_config(settings.environment_backend, db_name)
    if not domain:
        return None, (
            f"No semantic model configured for database '{db_name}' under backend "
            f"'{settings.environment_backend}' — see config/environment_backends.yaml."
        )
    return domain, None


async def _call(tool_name: str, arguments: dict) -> str:
    try:
        return await _mcp_client().acall_tool(tool_name, arguments)
    except (MCPClientError, MCPToolError) as e:
        return f"Error calling {tool_name}: {e}"
    except Exception as e:
        return f"Error calling {tool_name}: {type(e).__name__}: {e}"


# ── Semantic-layer discovery/query tools ──
# All `async def` — ADK invokes tool functions from within its own running
# event loop, so these must `await` the MCP client directly rather than using
# a sync wrapper that calls asyncio.run() (which raises "cannot be called
# from a running event loop").

def _scope_to_domain(raw: str, domain: dict) -> str:
    """Trim list_models' output to the single model configured for this domain.

    The MCP tool takes no scope (ParamsListModels has only force_refresh), so it
    returns every model in the catalog. Its `## <Model>` headings carry only the
    model name — when two schemas hold a same-named model (the two ETF builds),
    they are indistinguishable, and the agent explores the configured schema but
    writes the other one into run_query, so every query fails "Column not found".
    Sections do carry `catalog.schema.table:`, so scope on that.

    Scope on schema ONLY — keep every section for the configured model. The
    server renders each model twice and the two passes disagree, each leaking a
    different field from the other build: pass 2 labelled bird_etf_prompt_only
    lists dimensions that model does not have, while pass 1 labelled
    bird_atscale_models_catalog carries a correct header but prompt_only's
    column_groups. Neither pass is authoritative, so dropping either one hides
    real structure — keeping only the first cost the catalog model its true
    (dataset-named) column_groups and the agent queried them as tables,
    "relation \"funds\" does not exist", 0.0 across all 5 tasks. See Q-17.
    """
    fq = f"{domain['catalog']}.{domain['schema']}.{domain['table']}"
    head, _, rest = raw.partition("\n")
    try:
        entries = [
            e for e in json.loads(head)
            if (e.get("table_catalog"), e.get("table_schema"), e.get("table_name"))
            == (domain["catalog"], domain["schema"], domain["table"])
        ]
        head = json.dumps(entries[:1])
    except (ValueError, TypeError):
        logger.warning("list_models: could not parse header JSON; passing through unscoped")
    kept, tail, seen = [], [], set()
    for sec in re.split(r"(?m)^## ", rest):
        if not sec.strip() or sec in seen:
            continue
        seen.add(sec)
        if f"catalog.schema.table: {fq}" in sec:
            kept.append("## " + sec.rstrip())
        elif sec.startswith("Next Steps"):
            tail = ["## " + sec.rstrip()]
    if not kept:
        logger.warning("list_models: no section matched %s; passing through unscoped", fq)
        return raw
    return "\n".join([head, *kept, *tail])


async def list_models(tool_context: ToolContext) -> str:
    """List the semantic model available for this task (dimensions, hierarchies,
    metrics). Use this first to see the model's shape before exploring columns.
    Cost: 1 bird-coin.

    Returns:
        The model as text. Query it under exactly the schema/table shown here.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    return _scope_to_domain(await _call("list_models", {}), domain)


async def explore_columns(search_terms: List[str], tool_context: ToolContext) -> str:
    """Search the semantic model's columns (dimensions/metrics) by keyword.
    Call repeatedly with different search terms as needed — this does not
    return everything at once. Returns descriptions grouped by column_group.
    Cost: 1 bird-coin.

    Not fuzzy: a term must appear verbatim and in order in a column's name or
    description. "fund years" matches "Fund Years With Return Data"; "years
    fund" and "return years" match nothing. Pass several one- or two-word terms
    rather than one long phrase, and on an empty result drop a word, never add
    one.

    Args:
        search_terms: Short keywords, e.g. ["sales price", "state", "year"].

    Returns:
        Matching columns with descriptions, grouped by column_group.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    # Models often emit a bare string here despite the List[str] signature. The
    # MCP server tokenises a bare string on whitespace and ORs the terms, so a
    # multi-word string matches far too much: "premium fund" returns 86,794
    # chars of unranked catalog where ["premium fund"], searched as one phrase,
    # returns 1,335 with the right column first. Coerce to a single phrase.
    if isinstance(search_terms, str):
        search_terms = [search_terms]
    return await _call("explore_columns", {**domain, "search_terms": search_terms})


async def focus_columns(columns: List[str], tool_context: ToolContext) -> str:
    """Get full metadata for known column names, including sample/distinct
    values (sampled_values) — use this instead of running an exploratory query
    to discover valid predicate values. Use exact names found via explore_columns.
    Cost: 0.5 bird-coins.

    Args:
        columns: Exact column names to look up, e.g. ["Marital Status", "Sales Price"].

    Returns:
        Per-column metadata: data type, role, description, sampled_values, etc.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    return await _call("focus_columns", {**domain, "columns": columns})


async def get_sml_skills(tool_context: ToolContext) -> str:
    """Get the semantic layer's query-construction guidance (how to resolve
    names, use calcs, confirm filter literals, build a query correctly).
    Cost: 1 bird-coin.

    Returns:
        The query-construction guide as text.
    """
    return await _call("get_sml_skills", {"skill_name": _GET_SML_SKILLS_NAME})


async def run_query(query: str, tool_context: ToolContext) -> str:
    """Run a query against the semantic model and return the results.
    Use this to explore data or verify a query before submitting.
    Reference registered models as "<schema>"."<table>" (or fully qualified
    "atscale_catalogs"."<schema>"."<table>") exactly as returned by list_models.
    Cost: 1 bird-coin.

    Args:
        query: The semantic-layer SQL query to run.

    Returns:
        The query results, or an error message.
    """
    return await _call("run_query", {"query": query})


# ── Build tool list for ADK Agent (semantic-layer backend) ──

def get_ainteract_tools_atscale():
    """Return list of FunctionTool instances for a-interact mode against the
    'atscale' environment backend."""
    from system_agent.tools import ask_user, submit_sql  # backend-agnostic

    return [
        FunctionTool(list_models),
        FunctionTool(explore_columns),
        FunctionTool(focus_columns),
        FunctionTool(get_sml_skills),
        FunctionTool(run_query),
        FunctionTool(ask_user),
        FunctionTool(submit_sql),
    ]
