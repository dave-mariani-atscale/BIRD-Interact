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
from shared.environment_backends import get_domain_config, query_domain_violation
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


async def explore_columns(
    search_terms: Optional[List[str]] = None,
    folder: Optional[List[str]] = None,
    role: Optional[List[str]] = None,
    column_group: Optional[List[str]] = None,
    tool_context: Optional[ToolContext] = None,
) -> str:
    """Find the semantic model's columns (dimensions/metrics), by folder/role/
    column_group, by keyword, or both together. Returns descriptions grouped by
    column_group. Cost: 1 bird-coin per call, whatever you pass — so pass a lot.

    PREFER THE STRUCTURAL FILTERS when you know what you want: list_models gives
    you the model's folder names and its column_group list, and folder=["PnL"]
    then returns that whole folder exactly, with no guessing. folder, role and
    column_group combine with each other to narrow further.

    NAME EVERY FOLDER YOU NEED IN ONE CALL. Each takes a LIST, the members are
    OR'd, and the call costs the same coin whether you pass one name or six — so
    folder=["PnL", "Spread", "Order Counts"] is one coin where three separate
    calls are three. A question's dimensions and its metrics usually live in
    different folders, so batching is the normal case, not the exception. A name
    that does not exist is called out in a warning and does not suppress the
    others, so an uncertain name is safe to include.

    You CAN pass search_terms together with a scope, and the result is the UNION:
    the whole scope, plus everything the terms match anywhere in the model. It
    does NOT narrow the search to the scope. Use it to get a folder you can name
    and the stragglers you can only describe in one coin.

    WHEN YOU USE search_terms, CAST A WIDE NET IN ONE CALL. Terms are OR'd and
    a term that matches nothing is harmless — measured, four real terms plus ten
    nonsense terms return byte-identical output — so put every wording of every
    concept you still need into a single call rather than paying a coin per
    guess. Searching one term per call is the most expensive habit available.

    Breadth comes from the NUMBER of terms, never from shortening them. Matching
    is an ordered substring test against a column's name and description, so a
    short generic word matches far too much: ["order id"] returns 3 columns,
    ["id"] returns 89. Keep every term specific and add more of them.

    Args:
        search_terms: Keywords, each matched as one phrase, OR'd together and
            searched model-wide. Pass many, e.g. ["market impact cost",
            "limit price", "order id"]. Can be combined with the three below;
            the results are unioned, not narrowed.
        folder: Folder names from list_models, OR'd, e.g. ["PnL", "Spread"].
            Case-insensitive. Pass every folder the question needs.
        role: Any of "dimension", "measure", "calculation_group", OR'd.
            Case-insensitive; any other value is rejected. Most models have no
            calc groups.
        column_group: column_group names from list_models, OR'd, e.g. ["Order"] —
            either side of its column_groups map works (a dimension group or a
            fact dataset). Case-insensitive.

    Returns:
        Matching columns with descriptions, grouped by column_group. An
        unrecognised folder or column_group name is reported in a warning above
        the results it did find, and a scope that exists but holds nothing says
        so in different words — so read the first line before concluding the
        model lacks a concept.
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
    args = {"search_terms": search_terms, "folder": folder, "role": role,
            "column_group": column_group}
    # The three scopes take a list or a bare string on the server since
    # 2026-08-18 (tracker B-54), so a model emitting either is fine and nothing
    # needs coercing here.
    # Omit rather than send nulls, and answer a no-criteria call locally: the
    # server rejects one ("requires at least one filter"), and the coin is
    # already deducted by then, so there is nothing to gain from the round trip.
    args = {k: v for k, v in args.items() if v}
    if not args:
        return ("No search criteria given, so nothing was searched. Pass EITHER "
                "search_terms (many, each specific) OR a scope — folder / role / "
                "column_group, with folder and column_group names taken from "
                "list_models.")
    return await _call("explore_columns", {**domain, **args})


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
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    violation = query_domain_violation(query, domain)
    if violation:
        logger.warning("run_query blocked (wrong model): %s", query)
        return violation
    return await _call("run_query", {"query": query})


# ── Build tool list for ADK Agent (semantic-layer backend) ──

def get_ainteract_tools_atscale():
    """Return list of FunctionTool instances for a-interact mode against the
    'atscale' environment backend."""
    from system_agent.tools import ask_user, submit_sql  # backend-agnostic

    tools = [
        FunctionTool(list_models),
        FunctionTool(explore_columns),
        FunctionTool(focus_columns),
        FunctionTool(get_sml_skills),
        FunctionTool(run_query),
        FunctionTool(ask_user),
        FunctionTool(submit_sql),
    ]

    # The task's external-knowledge glossary, off by default — see
    # settings.semantic_layer_knowledge_tools for why this is a scope choice
    # rather than a fix, and tracker B-12. These three are backend-agnostic
    # already: they POST only a task_id to the db environment's
    # /knowledge_names and /knowledge, which resolve the database from task
    # data and never inspect the active backend. Their costs need no wiring —
    # callbacks._tool_cost consults its own TOOL_COSTS table first, and all
    # three are in it (0.5 / 0.5 / 1.0). The matching instruction text is
    # appended by system_agent.agent.build_agent under the same flag, so the
    # agent is never told about a tool it has not been given.
    if settings.semantic_layer_knowledge_tools:
        from system_agent.tools import (
            get_all_external_knowledge_names,
            get_knowledge_definition,
            get_all_knowledge_definitions,
        )
        tools += [
            FunctionTool(get_all_external_knowledge_names),
            FunctionTool(get_knowledge_definition),
            FunctionTool(get_all_knowledge_definitions),
        ]

    return tools
