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


# Stand-in for the planned server-side scoped list_models response
# (docs/mcp-column-index-spec.md). The server's own Next Steps still tell the
# caller to make the wide explore_columns call that the inlined Column Index
# makes redundant, so the whole block is replaced, not patched — server-side
# text is the strongest behavioural lever on record (B-56) and a contradiction
# here would undo the index. Step 3 is the server's current text verbatim.
# Retire all of this when the server ships the spec.
_NEXT_STEPS = """## Next Steps
1. Shortlist from the Column Index above — it already names every column in this model. Then `focus_columns` ONCE on every name you consider a candidate; that is where descriptions, sampled values, grain and units come from, and a name alone is not enough to put a column in a query.
2. `explore_columns` is for what the index cannot tell you: `search_terms` (multi-word, several per call) match description text, so a business concept or KB rule is findable even when no column name suggests it, and `folder`/`column_group` scopes fetch a small named slice at full detail. A scope and terms in one call return the union of the two.
3. Before querying, verify that each measure's `column_group` appears in the model's `column_groups` for your chosen dimension. Calculations are carved out of that rule: `Calculations` is a discovery bucket rather than a fact dataset, and `focus_columns` keeps reporting an empty `column_group` for one. A calculation's conformance is a property of the measures inside its expression — pair it with a dimension those measures conform to, and never read the empty value as conforming to nothing."""

_COLUMN_INDEX_HEADER = (
    "## Column Index (names only)\n"
    "Every column in this model — the complete inventory. There is nothing "
    "findable by name that is not listed here.\n\n"
)


def _with_column_index(scoped: str, index: str) -> str:
    """Append the whole-model names index to the scoped list_models output and
    swap in the matching Next Steps. On any sign the index fetch failed, return
    the scoped output untouched — a missing index must never break list_models."""
    if index.startswith("Error calling") or "column_name" not in index:
        logger.warning("list_models: column index fetch failed; returning without index")
        return scoped
    head, sep, _ = scoped.partition("\n## Next Steps")
    body = head.rstrip() + "\n\n" + _COLUMN_INDEX_HEADER + index.strip()
    if not sep:
        logger.warning("list_models: no Next Steps section found; appending index only")
        return body
    return body + "\n\n" + _NEXT_STEPS


async def list_models(tool_context: ToolContext) -> str:
    """List the semantic model available for this task: its shape, the exact
    catalog/schema/table name your FROM clause needs, and a Column Index naming
    EVERY column in the model (names only, grouped by column_group). Use this
    first; after it, discovery means focus_columns on your shortlist, not
    searching. Cost: 1 bird-coin.

    Returns:
        The model as text. Query it under exactly the schema/table shown here.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    scoped = _scope_to_domain(await _call("list_models", {}), domain)
    index = await _call(
        "explore_columns",
        {**domain, "role": ["dimension", "measure"], "detail": "names"},
    )
    return _with_column_index(scoped, index)


async def explore_columns(
    search_terms: Optional[List[str]] = None,
    folder: Optional[List[str]] = None,
    role: Optional[List[str]] = None,
    column_group: Optional[List[str]] = None,
    detail: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
) -> str:
    """Search the model's column DESCRIPTIONS for a concept, or fetch a small
    named slice (folder/column_group) at full detail. For column NAMES you do
    not need this tool at all: list_models' Column Index already lists every
    column in the model. Cost: 1 bird-coin per call, whatever you pass.

    The two uses that earn the coin: (1) a business concept, KB rule or screen
    you cannot match to any name in the index — search_terms match description
    text, so the definition and the implementing column come back together;
    (2) one folder or the Calculations bucket at full detail instead of
    focusing its columns name by name.

    BATCH EVERYTHING INTO ONE CALL. Every scope takes a LIST whose members are
    OR'd, terms are OR'd, and a scope plus search_terms returns the UNION of
    the two — the whole scope plus everything the terms match anywhere in the
    model, never a narrowed search. A folder name that does not exist, or a
    term that matches nothing, is harmless: it is reported in a warning and
    does not suppress the rest. Paying a coin per guess is the most expensive
    habit available here.

    Matching is an ordered substring test against a column's name and
    description, so keep terms specific and multi-word: ["order id"] returns 3
    columns, ["id"] returns 89. Breadth comes from the NUMBER of terms, never
    from shortening them.

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
        detail: "full" (default) for names with descriptions, or "names" for
            names only — same columns, same order, roughly a tenth of the text.

    Returns:
        Matching columns with descriptions, grouped by column_group. An
        unrecognised folder or column_group name is reported in a warning above
        the results it did find, and a scope that exists but holds nothing says
        so in different words — so read the first line before concluding the
        model lacks a concept. Under detail="names" the columns and their order
        are identical and every heading names the kind it holds.
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
    # detail is deliberately NOT one of the criteria — it selects a rendering,
    # so a call carrying only detail is still a no-criteria call.
    args = {k: v for k, v in args.items() if v}
    if args and detail:
        # The server takes "full" or "names" and rejects anything else, so only
        # normalise case — never silently substitute a value the agent did not ask for.
        args["detail"] = detail.strip().lower() if isinstance(detail, str) else detail
    if not args:
        return ("No search criteria given, so nothing was searched. Pass "
                "search_terms (many, each specific), or a scope — folder / role "
                "/ column_group, with folder and column_group names taken from "
                "list_models — or both in the same call, which returns the "
                "union of the two.")
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
