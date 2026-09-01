"""Flag-gated bridge from the harness to the MCP server's certified-answer memory.

Off by default (settings.feedback_memory). When on, and only on a semantic-layer
backend, the harness:

  1. passes the task's ambiguous user question as run_query's `question` param,
  2. captures the `exchangeId: <uuid>` line the MCP server appends to run_query
     results — and STRIPS it before the agent sees the response, so the
     agent-visible surface is byte-identical to a flag-off run,
  3. records the simulated user's verdict about each submission (accepted ->
     correct, rejected -> incorrect) against the matching exchange via the
     server's record_feedback tool, fire-and-forget on a daemon thread, with
     the task's ask_user clarifications attached to the verdict's note.

Integrity notes (binding — see the PRD's Section 7 and the harness tracker):
  - Nothing here changes what the agent sees, pays, or can do: record_feedback
    is called by the HARNESS, not the agent; it costs no bird-coins and its
    result never reaches the agent. The simulator, grader and coin table are
    untouched.
  - This is telemetry capture (P1 of the PRD). Any run where the server also
    SERVES memory back (exemplar enrichment in get_sml_skills) must state its
    cold/warm configuration in the method notes.
  - The MCP server must be started with ATSCALE_MCP_FEEDBACK_MEMORY=true (and
    an engine image carrying the 20260826_create_mcp_feedback changelog) or
    record_feedback returns a disabled error, which is logged and dropped.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, MutableMapping

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

# The line run_query appends when the server's feedback memory is on.
_EXCHANGE_LINE = re.compile(r"\n?^exchangeId:\s*([0-9a-fA-F-]{36})\s*$", re.MULTILINE)

# Session-state keys (underscore prefix: internal, never surfaced to the agent).
STATE_EXCHANGE_BY_SQL = "_exchange_by_sql"
STATE_LAST_EXCHANGE = "_last_exchange_id"


def _parse_sse_result(text: str) -> str:
    """Tool-result text from a streamable-HTTP response body (SSE or plain JSON)."""
    payload: dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                payload = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
    if not payload and text.strip():
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return ""
    content = (payload.get("result") or {}).get("content") or []
    # "\n" join, matching shared.mcp_client._stringify_result_content — the
    # exchangeId line is matched with a line-anchored regex downstream.
    return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))


class _RawMCP:
    """Minimal SYNC streamable-HTTP MCP caller for the verdict thread.

    The SDK client this replaced spawns an anyio task group, a GET event
    stream and a 1000ms reconnect loop per call — machinery that, run under
    asyncio.run inside a fire-and-forget thread, was observed hung for 30
    minutes holding open MCP connections (one per stuck thread) while the
    verdict was silently lost. Plain POSTs with hard timeouts cannot hang the
    thread past the timeout, and there is no event stream to reconnect.
    """

    def __init__(self, url: str, token: str, timeout_s: float) -> None:
        self._url = url
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10.0))
        self._session_id = ""

    def __enter__(self) -> "_RawMCP":
        resp = self._http.post(self._url, headers=self._headers, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "bird-feedback", "version": "1.0"}},
        })
        resp.raise_for_status()
        self._session_id = resp.headers.get("mcp-session-id", "")
        if self._session_id:
            self._headers["Mcp-Session-Id"] = self._session_id
        self._http.post(self._url, headers=self._headers,
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def __exit__(self, *exc: Any) -> None:
        self._http.close()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        resp = self._http.post(self._url, headers=self._headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        resp.raise_for_status()
        return _parse_sse_result(resp.text)


def enabled() -> bool:
    return bool(settings.feedback_memory)


def normalize_sql(sql: str) -> str:
    """Whitespace-collapsed, trailing-semicolon-stripped key for exchange lookup."""
    return " ".join(sql.split()).rstrip(";").strip()


def capture_exchange(state: MutableMapping[str, Any], sql: str, response_text: str) -> str:
    """Remember the response's exchangeId for this SQL; return the response
    with the exchangeId line removed (the agent never sees it)."""
    match = _EXCHANGE_LINE.search(response_text)
    if not match:
        return response_text
    exchange_id = match.group(1)
    # Reassign (not mutate) so ADK session state registers the change.
    mapping = dict(state.get(STATE_EXCHANGE_BY_SQL, {}))
    mapping[normalize_sql(sql)] = exchange_id
    state[STATE_EXCHANGE_BY_SQL] = mapping
    state[STATE_LAST_EXCHANGE] = exchange_id
    return _EXCHANGE_LINE.sub("", response_text)


def exchange_for(state: MutableMapping[str, Any], sql: str) -> str:
    """The exchangeId recorded for this exact SQL (whitespace-normalized), else "".

    Never falls back to the most recent exchange: a verdict is about the
    SUBMITTED SQL, and the agent routinely edits between its last run_query and
    submit_sql (trimming columns, most often). The fallback this function used
    to have credited task 15's run-1 win to a 5-column exploration query, which
    got certified, served as an exemplar, and cost the very same task in run 2
    when the agent replayed it verbatim — 3 of 17 certified rows in that
    sequence were SQL that never passed grading. Unmatched submissions get
    their own exchange in record_submission_verdict instead.
    """
    by_sql = state.get(STATE_EXCHANGE_BY_SQL, {})
    return by_sql.get(normalize_sql(sql), "")


# Budgets for the two halves of the recorded note. The simulator's verdict
# message is why THIS answer was judged as it was, so it is never crowded out;
# the clarifications are context and take what is left.
_NOTE_MESSAGE_CHARS = 500
_NOTE_CLARIFICATION_CHARS = 1500


def clarification_transcript(state: MutableMapping[str, Any], budget: int) -> str:
    """The task's ask_user exchanges as compact "Q -> A" lines, newest first.

    ask_user answers are the highest-signal intent data a run produces: they are
    the simulated user resolving the ambiguity the task was built around, in
    their own words. The agent pays 2 bird-coins per ask and the answer shaped
    every query that followed, yet none of it reached the memory — a run's whole
    disambiguation was discarded while its SQL was kept.

    Newest first because a later clarification usually refines an earlier one,
    so when the budget truncates, the binding constraint survives.
    """
    history = state.get("dialogue_history") or []
    pairs: list[str] = []
    pending_question = ""
    for turn in history:
        if not isinstance(turn, dict):
            continue
        content = " ".join(str(turn.get("content", "")).split())
        if turn.get("role") == "agent":
            pending_question = content
        elif turn.get("role") == "user" and content:
            pairs.append(f"Q: {pending_question} -> A: {content}" if pending_question else f"A: {content}")
            pending_question = ""
    out: list[str] = []
    used = 0
    for line in reversed(pairs):
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        used += len(line) + 1
    if not out and pairs:
        # One clarification longer than the whole budget: a truncated newest
        # line still says what was asked and how it was answered, where
        # dropping it silently loses the run's only disambiguation.
        return pairs[-1][:budget]
    return "\n".join(out)


def _submission_note(state: MutableMapping[str, Any], message: str) -> str:
    """The verdict message, plus the clarifications that led to the answer.

    Capture only. These are NOT served back to agents: the clarification text is
    the simulated user restating the task's own constraints, so serving it
    model-wide would hand back the disambiguation the benchmark exists to
    measure — the same leak that makes verbatim exemplars an explicit opt-in
    (ATSCALE_MCP_FEEDBACK_SERVE_MODE=query) rather than a side effect of capture.
    Analyse it offline out of mcp_feedback.feedback.note.
    """
    note = (message or "")[:_NOTE_MESSAGE_CHARS]
    clarifications = clarification_transcript(state, _NOTE_CLARIFICATION_CHARS)
    if clarifications:
        note = f"{note}\n\n--- clarifications ---\n{clarifications}" if note else clarifications
    return note


def record_submission_verdict(
    state: MutableMapping[str, Any], sql: str, passed: bool, message: str
) -> None:
    """Record the simulated user's verdict about a submission, fire-and-forget.

    The simulated user explicitly told the agent the answer was right/wrong, so
    source=end_user_explicit. When no exchange matches the submitted SQL (the
    agent edited it after its last run_query — trim-then-submit), one is created
    for it here by running the submitted SQL through run_query with the task
    question, so the verdict always lands on the SQL that was actually graded.
    No-op when the flag is off.
    """
    if not enabled():
        return
    exchange_id = exchange_for(state, sql)
    question = str(state.get("user_query", "") or "")
    if not exchange_id and not question:
        return
    payload = {
        "verdict": "correct" if passed else "incorrect",
        "source": "end_user_explicit",
        "rater": "bird_simulator",
        "note": _submission_note(state, message),
    }
    if settings.feedback_rater_token:
        # Authorizes the privileged source above; without it the server records
        # the verdict at agent_inferred weight, which never certifies alone.
        payload["raterToken"] = settings.feedback_rater_token

    def _send() -> None:
        try:
            # 120s ceiling: an exchange-creating run_query executes real
            # warehouse SQL; record_feedback itself is milliseconds. A raw
            # sync client with hard timeouts — never the SDK client, whose
            # per-call task group + GET-stream reconnect loop hung these
            # threads for 30 minutes and leaked one MCP connection per hang.
            with _RawMCP(settings.semantic_layer_mcp_url,
                         settings.semantic_layer_mcp_token, 120.0) as client:
                ex_id = exchange_id
                if not ex_id:
                    # Create the exchange the verdict belongs to. The extra
                    # warehouse execution is harness-side telemetry: no coins,
                    # and the agent never sees it. A submission the engine
                    # rejects produces no exchangeId line and the verdict is
                    # dropped — there is no stored SQL to protect or poison.
                    text = client.call_tool("run_query", {"query": sql, "question": question})
                    match = _EXCHANGE_LINE.search(text or "")
                    if not match:
                        logger.info(
                            "submitted SQL produced no exchange (engine error "
                            "or model-less query); verdict dropped"
                        )
                        return
                    ex_id = match.group(1)
                payload["exchangeId"] = ex_id
                client.call_tool("record_feedback", payload)
        except Exception as exc:  # telemetry only — never disturb the run
            logger.warning("record_feedback failed (exchange %s): %s", exchange_id or "new", exc)

    # Daemon thread: submit_sql is a sync ADK tool; MCPClient.call_tool uses
    # asyncio.run and must not run on a live event loop, and the run must not
    # wait on telemetry either way.
    threading.Thread(target=_send, daemon=True, name="bird-feedback").start()
