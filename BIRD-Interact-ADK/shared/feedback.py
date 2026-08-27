"""Flag-gated bridge from the harness to the MCP server's certified-answer memory.

Off by default (settings.feedback_memory). When on, and only on a semantic-layer
backend, the harness:

  1. passes the task's ambiguous user question as run_query's `question` param,
  2. captures the `exchangeId: <uuid>` line the MCP server appends to run_query
     results — and STRIPS it before the agent sees the response, so the
     agent-visible surface is byte-identical to a flag-off run,
  3. records the simulated user's verdict about each submission (accepted ->
     correct, rejected -> incorrect) against the matching exchange via the
     server's record_feedback tool, fire-and-forget on a daemon thread.

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

import logging
import re
import threading
from typing import Any, MutableMapping

from shared.config import settings
from shared.mcp_client import MCPClient, MCPEndpoint

logger = logging.getLogger(__name__)

# The line run_query appends when the server's feedback memory is on.
_EXCHANGE_LINE = re.compile(r"\n?^exchangeId:\s*([0-9a-fA-F-]{36})\s*$", re.MULTILINE)

# Session-state keys (underscore prefix: internal, never surfaced to the agent).
STATE_EXCHANGE_BY_SQL = "_exchange_by_sql"
STATE_LAST_EXCHANGE = "_last_exchange_id"


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
        "note": (message or "")[:500],
    }

    def _send() -> None:
        try:
            client = MCPClient(
                MCPEndpoint(
                    url=settings.semantic_layer_mcp_url,
                    bearer_token=settings.semantic_layer_mcp_token,
                )
            )
            ex_id = exchange_id
            if not ex_id:
                # Create the exchange the verdict belongs to. The extra
                # warehouse execution is harness-side telemetry: no coins, and
                # the agent never sees it. A submission the engine rejects
                # produces no exchangeId line and the verdict is dropped —
                # there is no stored SQL to protect or poison in that case.
                text = client.call_tool("run_query", {"query": sql, "question": question})
                match = _EXCHANGE_LINE.search(text or "")
                if not match:
                    logger.info(
                        "submitted SQL produced no exchange (engine error or "
                        "model-less query); verdict dropped"
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
