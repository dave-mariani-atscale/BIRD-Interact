"""ADK tools for a-interact mode on the Genie Ontology backend (`dbx_genie_ontology`):
scenario 2 of the Databricks comparison.

The agent never writes SQL. It passes the user's question (and the user's
clarifications) to Genie One - Databricks' natural-language data agent, grounded in
the Genie Ontology - over the BASE TABLES of the task database in `bird_interact`,
and submits the SQL Genie produced. Genie is reached through the workspace's
managed MCP (`/ai-gateway/mcp-services/system.ai.genie_one_mcp`: genie_ask,
genie_poll_response, genie_get_query_result, genie_cancel_response), as the
benchmark principal the backend's `token_env` names - a service principal with
SELECT on the base tables and no privilege on the metric views, so Genie cannot
draw on them (Genie only sees assets its caller can access).

    ask_genie(question)   -> genie_ask (one Genie conversation per task, continued
                             across turns and phases), polled to completion, then
                             genie_get_query_result for the rows; returns Genie's
                             answer, the SQL it ran and the result rows.

ask_user/submit_sql are unchanged and imported from tools.py (backend-agnostic).
Grading re-executes the submitted SQL on the warehouse as the same principal
(db_environment/server.py, executor: databricks + token_env).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from shared.config import settings
from shared.databricks_auth import resolve_token
from shared.databricks_sql import AGENT_ROW_CAP, convert_cell, _jsonable
from shared.environment_backends import get_domain_config
from shared.mcp_client import _first_leaf

logger = logging.getLogger(__name__)

GENIE_ONE_MCP_PATH = "/ai-gateway/mcp-services/system.ai.genie_one_mcp"
#: Genie turns typically complete in 70-260 s; the MCP server asks for 2-5 s between polls.
POLL_INTERVAL_S = 5.0
POLL_TIMEOUT_S = 540.0

#: Session-state keys (per task; the orchestrator resets state per task).
_STATE_CONVERSATION = "genie_conversation_id"
_STATE_RESPONSES = "genie_response_ids"


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
    return domain, None


class GenieError(RuntimeError):
    pass


# ── MCP plumbing ──

def _payload(result) -> Dict[str, Any]:
    """The structured content of a tool result, or the JSON its text carries."""
    if result.structured_content:
        return dict(result.structured_content)
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else {"text": text}
    except (TypeError, ValueError):
        return {"text": text}


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def _genie_turn(host: str, token: str, question: str, conversation_id: Optional[str]) -> Dict[str, Any]:
    """One Genie turn over one MCP session: ask, poll to completion, fetch the rows of
    the last query. Returns {conversation_id, response_id, status, answer, reasoning,
    sql_items: [{item_id, sql}], result: {columns, rows, total_row_count, truncated}|None,
    raw: <poll markdown>}."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    url = f"{host}{GENIE_ONE_MCP_PATH}"
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=120.0,
                                 trust_env=False) as http_client:
        async with streamable_http_client(url, http_client=http_client) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                args: Dict[str, Any] = {"question": question}
                if conversation_id:
                    args["conversation_id"] = conversation_id
                res = await session.call_tool("genie_ask", args)
                if res.is_error:
                    raise GenieError(f"genie_ask failed: {_text(res)[:500]}")
                d = _payload(res)
                cid, rid = d.get("conversation_id"), d.get("response_id")
                if not (cid and rid):
                    raise GenieError(f"genie_ask returned no conversation/response id: {_text(res)[:500]}")
                status = d.get("status", "in_progress")
                poll = res
                started = time.time()
                while status == "in_progress":
                    if time.time() - started > POLL_TIMEOUT_S:
                        try:
                            await session.call_tool("genie_cancel_response", {"conversation_id": cid})
                        except Exception:  # noqa: BLE001 - best effort
                            pass
                        raise GenieError(f"Genie did not answer within {POLL_TIMEOUT_S:.0f}s; the turn was cancelled. "
                                         "Ask again, more simply.")
                    await asyncio.sleep(POLL_INTERVAL_S)
                    poll = await session.call_tool("genie_poll_response",
                                                   {"conversation_id": cid, "response_id": rid})
                    if poll.is_error:
                        raise GenieError(f"genie_poll_response failed: {_text(poll)[:500]}")
                    status = _payload(poll).get("status", "in_progress")
                pd = _payload(poll)
                raw = _text(poll)
                out: Dict[str, Any] = {
                    "conversation_id": cid, "response_id": rid, "status": status,
                    "answer": pd.get("final_answer") or "",
                    "reasoning": _reasoning(raw),
                    "sql_items": [i for i in (pd.get("query_items") or []) if isinstance(i, dict)],
                    "result": None, "raw": raw, "elapsed_s": round(time.time() - started, 1),
                }
                if not out["sql_items"]:
                    out["sql_items"] = _sql_items_from_text(raw)
                if out["sql_items"] and out["sql_items"][-1].get("item_id"):
                    qr = await session.call_tool("genie_get_query_result", {
                        "conversation_id": cid, "response_id": rid,
                        "item_id": out["sql_items"][-1]["item_id"]})
                    if not qr.is_error:
                        out["result"] = _payload(qr)
                return out


_REASONING_RE = re.compile(r"<details><summary>Genie's reasoning</summary>\s*(.*?)\s*</details>", re.S)
_ITEM_RE = re.compile(r"`item_id`:\s*`([^`]+)`\s*—\s*runs:\s*(.+)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\((?:https?://)[^)]*\)")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _reasoning(raw: str) -> str:
    m = _REASONING_RE.search(raw or "")
    return m.group(1).strip() if m else ""


def _sql_items_from_text(raw: str) -> List[Dict[str, str]]:
    """Fallback when the poll carries no structured query_items: the `Tool-call IDs`
    agent comment lists every item with the SQL it ran."""
    return [{"item_id": m.group(1), "sql": m.group(2).strip()} for m in _ITEM_RE.finditer(raw or "")]


def _plain(text: str) -> str:
    """Genie's markdown answer without deep links (they point into the Databricks UI,
    which the agent cannot open) and without the MCP server's agent comments."""
    text = _COMMENT_RE.sub("", text or "")
    text = _LINK_RE.sub(lambda m: m.group(1), text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _rows_json(result: Dict[str, Any]) -> Tuple[str, int, bool]:
    cols = [(c.get("name"), c.get("type_text") or c.get("type_name") or "STRING")
            for c in (result.get("columns") or [])]
    rows = result.get("rows") or []
    typed = [{n: _jsonable(convert_cell(v, t)) for (n, t), v in zip(cols, r)} for r in rows[:AGENT_ROW_CAP]]
    total = result.get("total_row_count")
    total = int(total) if total is not None else len(rows)
    return json.dumps(typed, default=str), total, bool(result.get("truncated")) or len(rows) > AGENT_ROW_CAP


def _render(turn: Dict[str, Any]) -> str:
    parts = [f"# Genie's answer (status: {turn['status']}, {turn['elapsed_s']}s)"]
    if turn["answer"]:
        parts.append(_plain(turn["answer"]))
    elif turn["status"] != "completed":
        parts.append(_plain(turn["raw"])[:3000])
    if turn["reasoning"]:
        parts.append(f"\nGenie's notes: {_plain(turn['reasoning'])}")
    items = turn["sql_items"]
    if items:
        if len(items) > 1:
            parts.append(f"\n# Queries Genie ran ({len(items)}; the LAST one produced the answer)")
            for i in items[:-1]:
                parts.append("```sql\n" + i.get("sql", "").strip() + "\n```")
            parts.append("# SQL of the answer (submit this verbatim with submit_sql if it answers the question)")
        else:
            parts.append("\n# SQL Genie ran (submit this verbatim with submit_sql if it answers the question)")
        parts.append("```sql\n" + items[-1].get("sql", "").strip() + "\n```")
    else:
        parts.append("\n(Genie ran no query for this turn. If it asked you something, answer it "
                     "with the user's own words; if it declined, rephrase the question.)")
    res = turn.get("result")
    if res:
        if res.get("ready") is False:
            parts.append("\n# Result rows: not ready yet (statement still running); ask Genie again to see them.")
        else:
            shown, total, truncated = _rows_json(res)
            note = f"rows: {total}" + (f" (first {AGENT_ROW_CAP} shown)" if truncated else "")
            parts.append(f"\n# Result rows of that SQL\n{shown}\n{note}")
    parts.append(f"genieResponseId: {turn['response_id']}")
    return "\n".join(parts)


# ── the tool ──

async def ask_genie(question: str, tool_context: ToolContext) -> str:
    """Ask Genie (Databricks' natural-language data agent, grounded in this database's
    Genie Ontology) a data question. Genie finds the tables, writes and runs the SQL,
    and this returns its answer, the SQL it ran and the result rows. Every call
    continues the same Genie conversation for this task, so a clarification or a
    correction is a follow-up ("the user says X; redo it with ..."). Pass the user's
    question verbatim, prefixed with the database name, and pass the user's
    clarifications verbatim. You never write SQL yourself. Cost: 1 bird-coin.

    Args:
        question: The question for Genie, in the user's words, naming the database
            (e.g. "In the bird_interact.solar_panel database: <the user's question>").

    Returns:
        Genie's answer text, the SQL it ran (to submit verbatim with submit_sql) and
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
        return f"Error resolving the Databricks credential for backend '{_backend_name(tool_context)}': {e}"
    cid = tool_context.state.get(_STATE_CONVERSATION) if tool_context else None
    if not cid and domain.get("schema", "").lower() not in (question or "").lower():
        logger.warning("ask_genie: first question of the task does not name the database %s: %r",
                       domain.get("schema"), question[:120])
    try:
        turn = await _genie_turn(settings.databricks_host.rstrip("/"), token, question, cid)
    except GenieError as e:
        return f"Error from Genie: {e}"
    except BaseException as e:  # noqa: BLE001 - anyio wraps transport errors in ExceptionGroups
        leaf = _first_leaf(e)
        if isinstance(leaf, (KeyboardInterrupt, SystemExit)):
            raise
        logger.warning("ask_genie: transport failure: %s: %s", type(leaf).__name__, leaf)
        return f"Error calling Genie: {type(leaf).__name__}: {leaf}"
    if tool_context is not None:
        tool_context.state[_STATE_CONVERSATION] = turn["conversation_id"]
        ids = list(tool_context.state.get(_STATE_RESPONSES, []))
        ids.append({"response_id": turn["response_id"], "status": turn["status"],
                    "sql": [i.get("sql") for i in turn["sql_items"]], "elapsed_s": turn["elapsed_s"]})
        tool_context.state[_STATE_RESPONSES] = ids
    return _render(turn)


def get_ainteract_tools_genie_one():
    """Return the FunctionTool list for a-interact mode on the 'dbx_genie_ontology' backend."""
    from system_agent.tools import ask_user, submit_sql  # backend-agnostic

    return [
        FunctionTool(ask_genie),
        FunctionTool(ask_user),
        FunctionTool(submit_sql),
    ]
