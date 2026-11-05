"""ADK tools for a-interact mode on the Genie-space backend (`dbx_genie_space`).

The agent never writes SQL and has no discovery tools of its own. It passes the
user's question (and the user's clarifications) to Genie - Databricks' natural-language
data agent - in a Genie SPACE that holds only the task database's Unity Catalog metric
views, and submits the SQL Genie produced. Genie does the discovery over the views,
whose comments carry the knowledge base, as the SML models' descriptions do for the
AtScale arm. One space per database (scripts/provision_genie_spaces.py), with no
instructions, example SQL or sample questions.

Genie is reached through the Conversation API:
    POST /api/2.0/genie/spaces/{space}/start-conversation         first turn of a task
    POST /api/2.0/genie/spaces/{space}/conversations/{c}/messages  every later turn
    GET  .../messages/{m}                                          polled to a final status
    GET  .../messages/{m}/attachments/{a}/query-result             the rows of Genie's query

    ask_genie(question) -> one Genie conversation per task, continued across turns and
                           phases; returns Genie's answer, the SQL it ran and the rows.

ask_user/submit_sql are unchanged (tools.py). Grading re-executes the submitted SQL
on the warehouse (db_environment/server.py, executor: databricks). The rendering of
a turn is shared with the Genie One backend (tools_genie_one._render), so the two
Genie arms show the agent identical answer layouts.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from shared.config import settings
from shared.databricks_auth import resolve_token
from shared.environment_backends import objects_read, query_domain_violation
from system_agent.tools_genie_one import (GenieError, _STATE_CONVERSATION, _STATE_RESPONSES,
                                          _backend_name, _domain_or_error, _render)

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 3.0
POLL_TIMEOUT_S = 540.0
_FINAL = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}
#: Retried with backoff: rate limiting and transient server/transport errors.
_RETRY_STATUS = {429, 500, 502, 503, 504}


async def _call(c: httpx.AsyncClient, method: str, path: str, body: Optional[dict] = None,
                attempts: int = 6) -> dict:
    last = ""
    for i in range(attempts):
        try:
            r = await c.request(method, path, json=body)
            if r.status_code in _RETRY_STATUS and i < attempts - 1:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
            elif r.status_code >= 400:
                raise GenieError(f"HTTP {r.status_code}: {r.text[:400]}")
            else:
                return r.json()
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = f"{type(e).__name__}: {e}"
        wait = min(60.0, 2.0 ** (i + 1))
        logger.warning("genie %s %s: %s; retry %d/%d in %.0fs", method, path[-60:], last, i + 1, attempts - 1, wait)
        await asyncio.sleep(wait)
    raise GenieError(f"giving up after {attempts} attempts: {last}")


async def _genie_turn(host: str, token: str, space_id: str, question: str,
                      conversation_id: Optional[str]) -> Dict[str, Any]:
    """One Genie turn in `space_id`: send, poll to a final status, fetch the last query's
    rows. Returns the same dict shape as tools_genie_one._genie_turn."""
    started = time.time()
    base = f"/api/2.0/genie/spaces/{space_id}"
    async with httpx.AsyncClient(base_url=host, timeout=120.0, trust_env=False,
                                 headers={"Authorization": f"Bearer {token}"}) as c:
        if conversation_id:
            sent = await _call(c, "POST", f"{base}/conversations/{conversation_id}/messages", {"content": question})
            cid = conversation_id
            mid = sent.get("message_id") or sent.get("id")
        else:
            sent = await _call(c, "POST", f"{base}/start-conversation", {"content": question})
            cid = sent.get("conversation_id") or (sent.get("conversation") or {}).get("id")
            mid = sent.get("message_id") or (sent.get("message") or {}).get("id") or (sent.get("message") or {}).get("message_id")
        if not (cid and mid):
            raise GenieError(f"Genie returned no conversation/message id: {str(sent)[:400]}")
        msg: Dict[str, Any] = {}
        while True:
            msg = await _call(c, "GET", f"{base}/conversations/{cid}/messages/{mid}")
            status = str(msg.get("status", "")).upper()
            if status in _FINAL:
                break
            if time.time() - started > POLL_TIMEOUT_S:
                status = "TIMEOUT"
                break
            await asyncio.sleep(POLL_INTERVAL_S)
        texts: List[str] = []
        notes: List[str] = []
        items: List[Dict[str, str]] = []
        for a in msg.get("attachments") or []:
            if a.get("text"):
                t = (a["text"] or {}).get("content") or ""
                if t:
                    texts.append(t)
            q = a.get("query")
            if q:
                items.append({"item_id": a.get("attachment_id") or a.get("id") or "", "sql": q.get("query") or ""})
                if q.get("description"):
                    notes.append(q["description"])
        if msg.get("error"):
            texts.append(f"Genie error: {msg['error']}")
        result = None
        if items and status == "COMPLETED":
            aid = items[-1]["item_id"]
            try:
                qr = await _call(c, "GET", f"{base}/conversations/{cid}/messages/{mid}/attachments/{aid}/query-result")
                sr = qr.get("statement_response") or qr
                man = sr.get("manifest") or {}
                result = {
                    "columns": [{"name": col.get("name"), "type_text": col.get("type_text") or col.get("type_name")}
                                for col in (man.get("schema") or {}).get("columns", [])],
                    "rows": (sr.get("result") or {}).get("data_array") or [],
                    "total_row_count": man.get("total_row_count"),
                    "truncated": bool(man.get("truncated")),
                }
            except GenieError as e:
                logger.warning("genie query-result for %s/%s failed: %s", cid, mid, e)
                result = {"ready": False}
    return {
        "conversation_id": cid, "response_id": mid, "status": status.lower(),
        "answer": "\n\n".join(texts), "reasoning": " ".join(notes), "sql_items": items,
        "result": result, "elapsed_s": round(time.time() - started, 1), "raw": str(msg)[:4000],
    }


async def ask_genie(question: str, tool_context: ToolContext) -> str:
    """Ask Genie (Databricks' natural-language data agent, working over this database's
    semantic model: its Unity Catalog metric views) a data question. Genie finds the
    views, fields and measures, writes and runs the SQL, and this returns its answer,
    the SQL it ran and the result rows. Every call continues the same Genie conversation
    for this task, so a clarification or a correction is a follow-up ("the user says X;
    redo it with ..."). Pass the user's question verbatim and the user's clarifications
    verbatim. You never write SQL yourself. Cost: 1 bird-coin when Genie runs a query,
    0.5 when it does not (it asks you something back, explains or declines).

    Args:
        question: The question for Genie, in the user's words.

    Returns:
        Genie's answer text, the SQL it ran (to submit verbatim with submit_sql) and the
        rows that SQL returned (first 200), or an error message.
    """
    domain, err = _domain_or_error(tool_context)
    if err:
        return err
    space_id = domain.get("space_id")
    if not space_id:
        return (f"No Genie space configured for this database under backend "
                f"'{_backend_name(tool_context)}' - run scripts/provision_genie_spaces.py.")
    if not (question or "").strip():
        return "Error: the question is empty."
    try:
        token = resolve_token(domain.get("token_env"))
    except Exception as e:  # noqa: BLE001
        return f"Error resolving the Databricks credential: {e}"
    cid = tool_context.state.get(_STATE_CONVERSATION) if tool_context else None
    try:
        turn = await _genie_turn(settings.databricks_host.rstrip("/"), token, space_id, question, cid)
    except GenieError as e:
        return f"Error from Genie: {e}"
    except Exception as e:  # noqa: BLE001
        logger.warning("ask_genie: %s: %s", type(e).__name__, e)
        return f"Error calling Genie: {type(e).__name__}: {e}"
    if tool_context is not None:
        tool_context.state[_STATE_CONVERSATION] = turn["conversation_id"]
        ids = list(tool_context.state.get(_STATE_RESPONSES, []))
        ids.append({"response_id": turn["response_id"], "status": turn["status"],
                    "sql": [i.get("sql") for i in turn["sql_items"]], "elapsed_s": turn["elapsed_s"]})
        tool_context.state[_STATE_RESPONSES] = ids
    out = _render(turn)
    if tool_context is not None and not turn["sql_items"]:
        # Genie ran no query (it asked back, explained, declined or failed): a small
        # action, charged at the backend's small_action_costs (callbacks.after_tool_callback).
        tool_context.state["_small_action"] = True
    # The space holds only metric views, but under the owner token Genie can also read the
    # database's base tables (Unity Catalog permissions, not the space, bound what it
    # queries). That fallback is ALLOWED (objects: any), as it is for a customer whose
    # principal can read them, and recorded, never signalled to the agent. A statement
    # outside the task's database is still refused at grading, so that one is flagged now,
    # free, rather than after a 3-coin submit.
    last = turn["sql_items"][-1]["sql"] if turn["sql_items"] else ""
    read = objects_read(last, domain) if last else None
    if read and read["base_tables"]:
        logger.info("ask_genie fallback: %s read base tables %s (views %s)", domain.get("schema"),
                    read["base_tables"], read["metric_views"])
        if tool_context is not None:
            tool_context.state["genie_base_table_turns"] = tool_context.state.get("genie_base_table_turns", 0) + 1
    if tool_context is not None and read is not None:
        ids = list(tool_context.state.get(_STATE_RESPONSES, []))
        if ids:
            ids[-1] = {**ids[-1], "objects_read": read}
            tool_context.state[_STATE_RESPONSES] = ids
    violation = query_domain_violation(last, domain) if last else None
    if violation:
        logger.warning("ask_genie: Genie's SQL left the metric views (%s): %s", domain.get("schema"), last[:200])
        if tool_context is not None:
            tool_context.state["genie_off_model_turns"] = tool_context.state.get("genie_off_model_turns", 0) + 1
        out += ("\n\nNOTE: this SQL reads objects outside this task's database "
                f"({violation.split('references ', 1)[-1].split(',')[0]}). A submission of it will be rejected. "
                "Ask Genie to answer from this database only.")
    return out


def get_ainteract_tools_genie_space():
    """Return the FunctionTool list for a-interact mode on the 'dbx_genie_space' backend."""
    from system_agent.tools import ask_user, submit_sql  # backend-agnostic

    return [FunctionTool(ask_genie), FunctionTool(ask_user), FunctionTool(submit_sql)]
