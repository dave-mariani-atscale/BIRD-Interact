"""ADK tools for a-interact mode on the Snowflake backends (`sf_cortex_sense_*`):
the Snowflake counterpart of the Genie One scenarios (system_agent/tools_genie_one.py).

The agent never writes SQL. It passes the user's question (and the user's
clarifications) to a Cortex Agent grounded in the task database's Cortex Sense context
and submits the SQL that agent ran. The Cortex Agent is run inline through the Cortex
Agents REST API (`/api/v2/cortex/agent:run`) with one declared tool, `cortex_sense`,
bound to the database's context; the platform adds `system_execute_sql`, with which the
agent runs SQL as the scenario's role on the scenario's warehouse. Nothing here steers
which objects it reads: the role's grants decide what exists for it (base tables only, or
base tables plus a set of semantic views), every turn is classified (semantic views /
base tables / mixed / elsewhere) and logged, and every graded submission is classified
the same way in the grading audit.

    ask_cortex(question)  -> one agent:run per call; the task's earlier turns are sent
                             back as the conversation, so a clarification is a
                             follow-up. Returns the agent's answer, the SQL it ran and
                             the result rows. 1 bird-coin when it ran a query, 0.5 when
                             it did not (a clarifying question or a refusal).

ask_user/submit_sql are unchanged and imported from tools.py (backend-agnostic).
Grading re-executes the submitted SQL on the warehouse as the same role
(db_environment/server.py, executor: snowflake), read-only, and refuses a statement
that reads another database (a routing miss; the agent is told so here, in the same
turn, before it spends a submission).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from shared.config import settings
from shared.environment_backends import get_domain_config, objects_read, query_domain_violation
from shared.mcp_client import _first_leaf
from shared.snowflake_auth import auth_headers, resolve_token
from shared.snowflake_sql import AGENT_ROW_CAP, _jsonable, convert_cell

logger = logging.getLogger(__name__)

AGENT_RUN_PATH = "/api/v2/cortex/agent:run"
#: One agent run: context retrieval, one or more SQL statements, the answer.
RUN_TIMEOUT_S = 600.0
#: 429/5xx and dropped streams before any event arrived are retried; they cost time, not coins.
RETRY_BACKOFF_S = (5.0, 15.0, 30.0)
_RETRY_STATUS = {429, 500, 502, 503, 504}
SQL_TOOL_TYPES = ("system_execute_sql", "cortex_analyst_text_to_sql")

#: Session-state keys (per task; the orchestrator resets state per task).
_STATE_MESSAGES = "cortex_messages"
_STATE_TURNS = "cortex_turns"


class CortexError(RuntimeError):
    pass


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
        return None, (f"No schema configured for database '{db_name}' under backend "
                      f"'{backend}' — see config/environment_backends.yaml.")
    if not domain.get("context"):
        return None, f"Backend '{backend}' has no Cortex Sense context configured for database '{db_name}'."
    return domain, None


# ── the agent run ──

def request_body(domain: Dict[str, Any], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The inline agent: one cortex_sense tool bound to the database's context. The tool's
    warehouse is also what the auto-created system_execute_sql runs on."""
    name = f"{domain['schema'].lower()}_context"
    return {
        "models": {"orchestration": domain.get("agent_model") or "auto"},
        "messages": messages,
        "tools": [{"tool_spec": {
            "type": "cortex_sense", "name": name,
            "description": (f"Business context for the {domain['catalog']}.{domain['schema']} database: its tables, "
                            "columns, their meanings and how they relate."),
        }}],
        "tool_resources": {name: {
            "context_name": domain["context"],
            "execution_environment": {"type": "warehouse", "warehouse": settings.snowflake_warehouse},
        }},
    }


async def _stream_run(host: str, token: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """POST agent:run and read the event stream to its final `response` event. Returns that
    event's payload ({content: [...], ...}); raises CortexError on an `error` event, an HTTP
    error, or a stream that ends without a response."""
    headers = {**auth_headers(token), "Content-Type": "application/json", "Accept": "text/event-stream",
               "User-Agent": "bird-interact-harness/1.0"}
    final: Optional[Dict[str, Any]] = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(RUN_TIMEOUT_S, connect=30.0), trust_env=False) as client:
        async with client.stream("POST", f"{host}{AGENT_RUN_PATH}", headers=headers, json=body) as r:
            if r.status_code >= 400:
                text = (await r.aread()).decode(errors="replace")
                err = CortexError(f"HTTP {r.status_code}: {text[:500]}")
                err.status = r.status_code  # type: ignore[attr-defined]
                raise err
            event = None
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if event == "response":
                        final = json.loads(data)
                    elif event == "error":
                        raise CortexError(f"agent error: {data[:500]}")
    if final is None:
        raise CortexError("the agent's stream ended without a response")
    return final


async def _run_with_retry(host: str, token: str, body: Dict[str, Any]) -> Dict[str, Any]:
    for attempt in range(len(RETRY_BACKOFF_S) + 1):
        try:
            return await _stream_run(host, token, body)
        except CortexError as e:
            status = getattr(e, "status", None)
            if status not in _RETRY_STATUS or attempt == len(RETRY_BACKOFF_S):
                raise
            logger.info("agent:run transient failure (attempt %d), retrying: %s", attempt + 1, str(e)[:200])
        except (httpx.TransportError, httpx.TimeoutException) as e:
            if attempt == len(RETRY_BACKOFF_S):
                raise CortexError(f"{type(e).__name__}: {e}") from None
            logger.info("agent:run transport failure (attempt %d), retrying: %s", attempt + 1, e)
        await asyncio.sleep(RETRY_BACKOFF_S[attempt])
    raise CortexError("unreachable")


def parse_response(final: Dict[str, Any]) -> Dict[str, Any]:
    """From a final response: {answer, sql_items: [{sql, query_id, error, result}], context_docs:
    [entity keys the cortex_sense tool returned], content}. `result` is the SQL API result set
    ({data, resultSetMetaData}) of that statement, or None when it failed."""
    content = final.get("content") or []
    uses: Dict[str, Dict[str, Any]] = {}
    items: List[Dict[str, Any]] = []
    docs: List[str] = []
    texts: List[str] = []
    for block in content:
        kind = block.get("type")
        if kind == "text":
            texts.append(block.get("text") or "")
        elif kind == "tool_use":
            tu = block.get("tool_use") or {}
            uses[tu.get("tool_use_id", "")] = tu
            if tu.get("type") in SQL_TOOL_TYPES and (tu.get("input") or {}).get("sql"):
                items.append({"tool_use_id": tu.get("tool_use_id"), "sql": tu["input"]["sql"],
                              "query_id": None, "error": None, "result": None})
        elif kind == "tool_result":
            tr = block.get("tool_result") or {}
            tu = uses.get(tr.get("tool_use_id", ""), {})
            payloads = [c.get("json") for c in (tr.get("content") or []) if isinstance(c.get("json"), dict)]
            text = " ".join(c.get("text", "") for c in (tr.get("content") or []) if c.get("text"))
            if tu.get("type") == "cortex_sense":
                for p in payloads:
                    docs.extend(d.get("entity_key", "") for d in (p.get("documents") or []))
                continue
            item = next((i for i in items if i["tool_use_id"] == tr.get("tool_use_id")), None)
            if item is None:
                # An Analyst tool returns the SQL it wrote in its result rather than taking it as input.
                sql = next((p.get("sql") for p in payloads if p.get("sql")), None)
                if not sql:
                    continue
                item = {"tool_use_id": tr.get("tool_use_id"), "sql": sql, "query_id": None, "error": None, "result": None}
                items.append(item)
            for p in payloads:
                item["query_id"] = p.get("query_id") or item["query_id"]
                if isinstance(p.get("result_set"), dict):
                    item["result"] = p["result_set"]
                if p.get("error") or p.get("error_message"):
                    item["error"] = str(p.get("error") or p.get("error_message"))[:500]
            if tr.get("status") == "error" and not item["error"]:
                item["error"] = (text or json.dumps(payloads))[:500]
    return {"answer": "\n\n".join(t for t in texts if t.strip()), "sql_items": items,
            "context_docs": [d for d in docs if d], "content": content}


def answer_item(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The statement that produced the answer: the last one that returned rows."""
    ok = [i for i in items if i.get("result") is not None and not i.get("error")]
    return ok[-1] if ok else None


def _rows_json(result: Dict[str, Any]) -> Tuple[str, int, bool]:
    row_type = (result.get("resultSetMetaData") or {}).get("rowType") or []
    rows = result.get("data") or []
    typed = [{c.get("name"): _jsonable(convert_cell(v, c)) for c, v in zip(row_type, r)} for r in rows[:AGENT_ROW_CAP]]
    total = (result.get("resultSetMetaData") or {}).get("numRows")
    total = int(total) if total is not None else len(rows)
    return json.dumps(typed, default=str), total, total > len(typed)


def _render(turn: Dict[str, Any], elapsed_s: float) -> str:
    parts = [f"# Cortex's answer ({elapsed_s}s)"]
    if turn["answer"]:
        parts.append(turn["answer"].strip())
    items, last = turn["sql_items"], answer_item(turn["sql_items"])
    if last:
        others = [i for i in items if i is not last]
        if others:
            parts.append(f"\n# Other queries Cortex ran ({len(others)})")
            for i in others:
                parts.append("```sql\n" + i["sql"].strip() + "\n```" + (f"\n(failed: {i['error']})" if i.get("error") else ""))
            parts.append("# SQL of the answer (submit this verbatim with submit_sql if it answers the question)")
        else:
            parts.append("\n# SQL Cortex ran (submit this verbatim with submit_sql if it answers the question)")
        parts.append("```sql\n" + last["sql"].strip() + "\n```")
        shown, total, truncated = _rows_json(last["result"])
        note = f"rows: {total}" + (f" (first {AGENT_ROW_CAP} shown)" if truncated else "")
        parts.append(f"\n# Result rows of that SQL\n{shown}\n{note}")
    elif items:
        parts.append(f"\n# Queries Cortex ran ({len(items)}; none returned rows)")
        for i in items:
            parts.append("```sql\n" + i["sql"].strip() + "\n```" + (f"\n(failed: {i['error']})" if i.get("error") else ""))
        parts.append("(No query succeeded in this turn. Ask Cortex again; say what failed if it helps.)")
    else:
        parts.append("\n(Cortex ran no query for this turn. If it asked you something, answer it "
                     "with the user's own words; if it declined, rephrase the question.)")
    return "\n".join(parts)


def route_class(read: Optional[Dict[str, List[str]]]) -> str:
    """none | semantic_views | base_tables | mixed | elsewhere (anything outside the task
    database wins: it is a routing miss whatever else the statement reads)."""
    if not read:
        return "none"
    if read.get("elsewhere"):
        return "elsewhere"
    v, b = bool(read.get("metric_views")), bool(read.get("base_tables"))
    return "mixed" if v and b else "semantic_views" if v else "base_tables" if b else "none"


# ── the tool ──

async def ask_cortex(question: str, tool_context: ToolContext) -> str:
    """Ask Cortex (Snowflake's natural-language data agent, a Cortex Agent grounded in
    the Cortex Sense context of this database) a data question. Cortex finds the data,
    writes and runs the SQL, and this returns its answer, the SQL it ran and the result
    rows. Every call continues the same Cortex conversation for this task, so a
    clarification or a correction is a follow-up ("the user says X; redo it with ...").
    Pass the user's question verbatim, prefixed with the database name, and pass the
    user's clarifications verbatim. You never write SQL yourself. Cost: 1 bird-coin when
    Cortex runs a query, 0.5 when it does not.

    Args:
        question: The question for Cortex, in the user's words, naming the database
            (e.g. "In the BIRD_BENCH.SOLAR_PANEL database: <the user's question>").

    Returns:
        Cortex's answer text, the SQL it ran (to submit verbatim with submit_sql) and
        the rows that SQL returned (first 200), or an error message.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    if not (question or "").strip():
        return "Error: the question is empty."
    try:
        token = resolve_token(domain.get("token_env"))
    except Exception as e:  # noqa: BLE001
        return f"Error resolving the Snowflake credential for backend '{_backend_name(tool_context)}': {e}"
    history = list(tool_context.state.get(_STATE_MESSAGES, [])) if tool_context else []
    if not history and domain.get("schema", "").lower() not in question.lower():
        logger.warning("ask_cortex: first question of the task does not name the database %s: %r",
                       domain.get("schema"), question[:120])
    messages = history + [{"role": "user", "content": [{"type": "text", "text": question}]}]
    started = time.time()
    try:
        final = await _run_with_retry(settings.snowflake_host.rstrip("/"), token, request_body(domain, messages))
    except CortexError as e:
        if tool_context is not None:
            tool_context.state["_small_action"] = True   # no query ran: 0.5, like any queryless turn
        logger.info("ask_cortex route: db=%s route=error", domain.get("schema"))
        return f"Error from Cortex: {e}"
    except BaseException as e:  # noqa: BLE001 - anyio wraps transport errors in ExceptionGroups
        leaf = _first_leaf(e)
        if isinstance(leaf, (KeyboardInterrupt, SystemExit)):
            raise
        logger.warning("ask_cortex: transport failure: %s: %s", type(leaf).__name__, leaf)
        if tool_context is not None:
            tool_context.state["_small_action"] = True
        logger.info("ask_cortex route: db=%s route=error", domain.get("schema"))
        return f"Error calling Cortex: {type(leaf).__name__}: {leaf}"
    elapsed = round(time.time() - started, 1)
    turn = parse_response(final)
    last = answer_item(turn["sql_items"])
    out = _render(turn, elapsed)
    # Routing: which objects the SQL of the answer read. Recorded only, never signalled - except a
    # statement outside the task's database, which grading refuses, so that one is flagged now,
    # free, rather than after a 3-coin submit.
    last_sql = last["sql"] if last else ""
    read = objects_read(last_sql, domain) if last_sql else None
    route = route_class(read)
    logger.info("ask_cortex route: db=%s route=%s views=%s base=%s elsewhere=%s query=%s elapsed=%s context_docs=%d",
                domain.get("schema"), route, (read or {}).get("metric_views", []),
                (read or {}).get("base_tables", []), (read or {}).get("elsewhere", []),
                (last or {}).get("query_id"), elapsed, len(turn["context_docs"]))
    if tool_context is not None:
        # The conversation so far, replayed on the next call: the user's words and the agent's
        # answer text with the SQL it settled on (the retrieved documents are not replayed; the
        # agent retrieves again when it needs them).
        recap = turn["answer"].strip() or "(no answer text)"
        if last_sql:
            recap += f"\n\nSQL I ran for this answer:\n{last_sql.strip()}"
        tool_context.state[_STATE_MESSAGES] = messages + [
            {"role": "assistant", "content": [{"type": "text", "text": recap}]}]
        turns = list(tool_context.state.get(_STATE_TURNS, []))
        turns.append({"elapsed_s": elapsed, "sql": [i["sql"] for i in turn["sql_items"]],
                      "failed": sum(1 for i in turn["sql_items"] if i.get("error")),
                      "query_id": (last or {}).get("query_id"), "context_docs": turn["context_docs"],
                      "objects_read": read, "route": route})
        tool_context.state[_STATE_TURNS] = turns
        if not last:
            # A turn without a successful query (a clarifying question, a refusal, only failed
            # statements) is a small action: callbacks.after_tool_callback refunds down to
            # small_action_costs["ask_cortex"].
            tool_context.state["_small_action"] = True
    violation = query_domain_violation(last_sql, domain) if last_sql else None
    if violation:
        logger.warning("ask_cortex: the SQL left the task database (%s): %s", domain.get("schema"), last_sql[:200])
        out += ("\n\nNOTE: this SQL reads objects outside this task's database "
                f"({violation.split('references ', 1)[-1].split(',')[0]}). A submission of it will be rejected. "
                "Ask Cortex to answer from this database only.")
    return out


def get_ainteract_tools_cortex_sense():
    """Return the FunctionTool list for a-interact mode on the 'sf_cortex_sense_*' backends."""
    from system_agent.tools import ask_user, submit_sql  # backend-agnostic

    return [
        FunctionTool(ask_cortex),
        FunctionTool(ask_user),
        FunctionTool(submit_sql),
    ]
