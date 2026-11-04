"""ADK tools for a-interact mode on a Databricks backend whose semantic layer is a
schema of Unity Catalog METRIC VIEWS (backend `dbx_metric_views`).

The Databricks analog of tools_atscale.py. The AtScale arm's model is one SML
model; here the model is the task database's schema in `bird_interact`, holding
that database's metric views and the relationships declared between them. The
agent discovers them, writes Databricks SQL over them (MEASURE() for measures)
and runs it on the SQL warehouse; grading re-executes the submitted statement
on the same warehouse (db_environment/server.py, executor: databricks).

    get_schema()                -> list_metric_views()
    get_column_meaning()        -> describe_metric_view(name, columns)
    execute_sql()               -> run_query(query)

ask_user/submit_sql are unchanged and imported from tools.py (backend-agnostic).
Per-domain catalog/schema comes from config/environment_backends.yaml, keyed by
the task's `db_name` (session state, set by orchestrator/ainteract.py).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from shared.config import settings
from shared.databricks_sql import AGENT_ROW_CAP, DatabricksSQL, DatabricksSQLError, schema_objects
from shared.environment_backends import get_domain_config, query_domain_violation

logger = logging.getLogger(__name__)


def _db_name(tool_context: Optional[ToolContext]) -> str:
    return tool_context.state.get("db_name", "") if tool_context else ""


def _backend_name(tool_context: Optional[ToolContext]) -> str:
    if tool_context and tool_context.state.get("backend"):
        return tool_context.state["backend"]
    return settings.environment_backend


def _domain_or_error(tool_context: Optional[ToolContext]):
    db_name = _db_name(tool_context)
    backend = _backend_name(tool_context)
    domain = get_domain_config(backend, db_name)
    if not domain:
        return None, (f"No metric-view schema configured for database '{db_name}' under backend "
                      f"'{backend}' — see config/environment_backends.yaml.")
    return domain, None


def _sql() -> DatabricksSQL:
    return DatabricksSQL()


# Per-process cache of DESCRIBE output per metric view: the catalog is fixed for a run.
_describe_cache: Dict[str, dict] = {}


def _describe(fq: str) -> dict:
    """{'comment': str, 'fields': [...], 'measures': [...], 'relationships': [...]} for a
    metric view, from DESCRIBE TABLE EXTENDED. Each field/measure: name, type,
    comment, synonyms, display_name."""
    if fq in _describe_cache:
        return _describe_cache[fq]
    res = _sql().execute(f"DESCRIBE TABLE EXTENDED {fq}")
    if res.error:
        raise DatabricksSQLError(res.error)
    out = {"comment": "", "fields": [], "measures": [], "relationships": []}
    section = "columns"
    for row in res.rows:
        name, dtype, comment = (row + (None, None, None))[:3]
        meta = row[3] if len(row) > 3 else None
        if name is None or name == "":
            continue
        if name.startswith("#"):
            section = name.strip("# ").lower()
            continue
        if section == "columns":
            entry = {"name": name, "type": (dtype or "").replace(" measure", ""), "comment": comment or ""}
            try:
                m = json.loads(meta) if meta else {}
            except (TypeError, ValueError):
                m = {}
            if m.get("synonyms"):
                entry["synonyms"] = m["synonyms"]
            if m.get("display_name"):
                entry["display_name"] = m["display_name"]
            (out["measures"] if (dtype or "").endswith(" measure") else out["fields"]).append(entry)
        elif section == "constraints":
            out["relationships"].append(f"{name}: {dtype}")
        elif section == "detailed table information" and name == "Comment":
            out["comment"] = dtype or ""
    _describe_cache[fq] = out
    return out


_DIALECT_NOTE = (
    "## Query dialect\n"
    "Databricks SQL. A metric view is queried like a table whose measures are wrapped in "
    "MEASURE(): SELECT field_a, field_b, MEASURE(measure_x) AS x FROM <catalog>.<schema>.<view> "
    "WHERE <field predicates> GROUP BY ALL ORDER BY x DESC LIMIT n. Fields are grouped by, "
    "measures are aggregated at the grain of the fields you select; never wrap a measure in "
    "SUM/AVG and never MEASURE() a field. A measure-only query (no fields, no GROUP BY) "
    "returns one row. HAVING works on MEASURE(...) results; a WHERE must use fields. "
    "Window functions, CTEs and subqueries over a metric-view query are ordinary SQL once "
    "the MEASURE() query is in a derived table. Two metric views of the schema are joined "
    "on the columns their declared relationships name. ORDER BY ... DESC puts NULLs LAST and "
    "ASC puts them FIRST on this engine, the opposite of Postgres, so write NULLS FIRST/LAST "
    "explicitly when ranking a nullable value. Text matches are case-sensitive; identifiers "
    "are lower-case. ROUND(x, n) returns a DECIMAL; CAST(x AS DECIMAL(18,4)) also works. "
    "Dates: date_format, datediff, months_between, current_date(). Medians and percentiles "
    "are published as measures where the model has them.\n"
    "## Discovery\n"
    "list_metric_views names every field and measure of every metric view in this task's "
    "schema; describe_metric_view gives full comments, synonyms and sample values for the "
    "names you pass. A rate, share, ratio or knowledge-base formula is usually already a "
    "measure: read its comment before building your own."
)


async def list_metric_views(tool_context: ToolContext) -> str:
    """List the metric views that make up this task's semantic model: each view's grain
    and comment, EVERY field and measure it publishes (names with display names), and the
    relationships between the views. Use this first; after it, discovery means
    describe_metric_view on your shortlist. Cost: 1 bird-coin.

    Returns:
        The model as text, with the exact catalog.schema.view names your FROM clause needs,
        followed by the query dialect and discovery notes.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    try:
        views = sorted(schema_objects(domain["catalog"], domain["schema"], "metric_views"))
    except DatabricksSQLError as e:
        return f"Error listing metric views: {e}"
    if not views:
        return f"No metric views found in {domain['catalog']}.{domain['schema']}."
    parts = [f"# Semantic model for this task: schema {domain['catalog']}.{domain['schema']} "
             f"({len(views)} metric views)\n"]
    for v in views:
        fq = f"{domain['catalog']}.{domain['schema']}.{v}"
        try:
            d = _describe(fq)
        except DatabricksSQLError as e:
            parts.append(f"## {fq}\n(could not describe: {e})\n")
            continue
        parts.append(f"## {fq}\n{d['comment']}\n")
        parts.append("Fields (" + str(len(d["fields"])) + "): " + ", ".join(
            f"{f['name']}" + (f" [{f['display_name']}]" if f.get("display_name") and
                              f["display_name"].lower().replace(" ", "_") != f["name"] else "")
            for f in d["fields"]))
        parts.append("Measures (" + str(len(d["measures"])) + "): " + ", ".join(
            f"{m['name']}" + (f" [{m['display_name']}]" if m.get("display_name") and
                              m["display_name"].lower().replace(" ", "_") != m["name"] else "")
            for m in d["measures"]))
        if d["relationships"]:
            parts.append("Relationships: " + "; ".join(d["relationships"]))
        parts.append("")
    parts.append(_DIALECT_NOTE)
    return "\n".join(parts)


async def describe_metric_view(view: str, columns: Optional[List[str]] = None,
                               tool_context: Optional[ToolContext] = None) -> str:
    """Full metadata for a metric view: every field and measure with its type, comment
    (the definition, the knowledge-base formula it implements, its competing readings)
    and synonyms. Pass `columns` to restrict to those names and to get up to 15 sample
    values for each STRING field named, so you can confirm filter literals without
    spending a query. Cost: 0.5 bird-coins.

    Args:
        view: The metric view name as list_metric_views printed it (bare or qualified).
        columns: Optional exact field/measure names to detail (with sample values for
            string fields). Omit for the whole view without samples.

    Returns:
        Per-column metadata as text.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    name = view.split(".")[-1].strip("`").lower()
    try:
        allowed = schema_objects(domain["catalog"], domain["schema"], "metric_views")
    except DatabricksSQLError as e:
        return f"Error: {e}"
    if name not in allowed:
        return (f"'{view}' is not a metric view of this task's schema. The views are: "
                + ", ".join(sorted(allowed)))
    fq = f"{domain['catalog']}.{domain['schema']}.{name}"
    try:
        d = _describe(fq)
    except DatabricksSQLError as e:
        return f"Error: {e}"
    want = {c.strip().strip("`").lower() for c in (columns or [])}
    lines = [f"# {fq}", d["comment"], ""]
    unknown = set(want)
    for kind, entries in (("field", d["fields"]), ("measure", d["measures"])):
        for e in entries:
            if want and e["name"].lower() not in want:
                continue
            unknown.discard(e["name"].lower())
            line = f"- {e['name']} ({kind}, {e['type']})"
            if e.get("display_name"):
                line += f" display: {e['display_name']}"
            if e.get("synonyms"):
                line += f" synonyms: {', '.join(e['synonyms'])}"
            if e.get("comment"):
                line += f"\n    {e['comment']}"
            if want and kind == "field" and e["type"].lower() in ("string", "boolean"):
                res = _sql().execute(f"SELECT DISTINCT `{e['name']}` AS v FROM {fq} "
                                     f"WHERE `{e['name']}` IS NOT NULL ORDER BY 1 LIMIT 15",
                                     catalog=domain["catalog"], schema=domain["schema"])
                if not res.error:
                    line += "\n    sampled_values: " + ", ".join(repr(r[0]) for r in res.rows)
            lines.append(line)
    if unknown:
        lines.append("Not in this view: " + ", ".join(sorted(unknown)))
    if d["relationships"]:
        lines.append("Relationships: " + "; ".join(d["relationships"]))
    return "\n".join(lines)


_READ_ONLY_RE = re.compile(r"^\s*(with|select)\b", re.IGNORECASE)


async def run_query(query: str, tool_context: ToolContext) -> str:
    """Run a Databricks SQL query against this task's metric views and return the rows.
    Use it to explore data or verify a query before submitting. Reference the views as
    <catalog>.<schema>.<view> exactly as list_metric_views printed them (a bare view name
    also resolves within the task's schema). Cost: 1 bird-coin.

    Args:
        query: The SELECT (or WITH ... SELECT) statement to run.

    Returns:
        The rows as a JSON array of objects (first 200 rows, with the total noted), or
        the engine's error message.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    if not _READ_ONLY_RE.match(query or ""):
        return "Only SELECT / WITH queries are allowed in run_query."
    violation = query_domain_violation(query, domain)
    if violation:
        logger.warning("run_query blocked (wrong schema): %s", query)
        return violation
    try:
        res = _sql().execute(query, catalog=domain["catalog"], schema=domain["schema"],
                             row_cap=AGENT_ROW_CAP + 1)
    except DatabricksSQLError as e:
        return f"Error calling the SQL warehouse: {e}"
    if res.error:
        return f"Error: {res.error}"
    n = len(res.rows)
    shown = res.to_json_rows(limit=AGENT_ROW_CAP)
    total = res.total_row_count if res.total_row_count is not None else n
    note = f"\nrows: {total}" + (f" (first {AGENT_ROW_CAP} shown)" if n > AGENT_ROW_CAP else "")
    return shown + note + f"\nstatementId: {res.statement_id}"


def get_ainteract_tools_databricks():
    """Return the FunctionTool list for a-interact mode on the 'dbx_metric_views' backend."""
    from system_agent.tools import ask_user, submit_sql  # backend-agnostic

    return [
        FunctionTool(list_metric_views),
        FunctionTool(describe_metric_view),
        FunctionTool(run_query),
        FunctionTool(ask_user),
        FunctionTool(submit_sql),
    ]
