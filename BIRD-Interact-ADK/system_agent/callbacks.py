"""ADK callbacks for a-interact mode: budget management and turn limiting."""

import json
import logging
import os
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.tool_context import ToolContext
from google.genai import types as genai_types
from shared.config import settings

logger = logging.getLogger(__name__)

MAX_MODEL_TURNS = 60

# "raw" backend tools + the two backend-agnostic actions every backend
# shares. Any non-raw backend's own tool costs live in that backend's
# `tool_costs` entry in config/environment_backends.yaml (see
# shared.environment_backends.get_backend_tool_costs) - not here, so a new
# semantic-layer backend never requires editing this file.
TOOL_COSTS = {
    "execute_sql": 1.0,
    "get_schema": 1.0,
    "get_all_column_meanings": 1.0,
    "get_column_meaning": 0.5,
    "get_all_external_knowledge_names": 0.5,
    "get_knowledge_definition": 0.5,
    "get_all_knowledge_definitions": 1.0,
    # backend-agnostic
    "ask_user": 2.0,
    "submit_sql": 3.0,
}


def cost_scheme_name() -> str:
    """Which cost table a run charged - recorded in results and on /health.
    "universal_cost_scheme" is the BIRD submission guidelines' rule for custom
    agents: ask user 2, submit 3, execute 1 (fixed), and every other action 0.5
    when its input is under 250 tokens and its average output under 1000,
    otherwise 1. Under it explore_columns costs 0.5, not the 1 our A/B runs
    charge (measured 2026-09-11 on 40 live calls each: explore_columns 17 in /
    831 out, focus_columns 27 in / 772 out; list_models and get_sml_skills
    exceed 1000 out and stay at 1). scripts/cost_scheme_audit.py re-measures."""
    return "universal_cost_scheme" if settings.leaderboard_mode else "harness_default"


def effective_tool_costs(backend: str) -> dict:
    """The complete tool -> bird-coin table for a backend under the current
    scheme: the raw/base table, then the backend's own tool_costs, then - in
    leaderboard mode - its leaderboard_tool_costs (config/environment_backends.yaml)."""
    costs = dict(TOOL_COSTS)
    if backend != "raw":
        from shared.environment_backends import (
            get_backend_tool_costs, get_backend_leaderboard_tool_costs,
        )
        costs.update(get_backend_tool_costs(backend))
        if settings.leaderboard_mode:
            costs.update(get_backend_leaderboard_tool_costs(backend))
    return costs


def _session_backend(tool_context) -> str:
    """The backend this session's agent was built for. Read from session state
    (stamped by AdkRuntime.init_session), because a process can serve a raw
    session and a semantic-layer session at once; the process-wide setting is
    only the fallback for a session created without one."""
    if tool_context is not None:
        name = tool_context.state.get("backend")
        if name:
            return name
    return settings.environment_backend


def _tool_cost(tool_name: str, tool_context=None):
    """Look up a tool's bird-coin cost for THIS session's backend. Resolved
    per-call (not cached): the table depends on the session and on the cost
    scheme, and the process backend can still change via /set_backend."""
    return effective_tool_costs(_session_backend(tool_context)).get(tool_name)


#: The engine's id for an executed query, appended by the MCP server as a
#: trailing `queryId: <uuid>` block. Matched against the untruncated response.
_QUERY_ID_RE = re.compile(
    r"queryId:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def _preview(value: Any, limit: int = 2000) -> Any:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text[:limit] + "...<truncated>" if len(text) > limit else text


async def before_model_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Cap LLM invocations at MAX_MODEL_TURNS."""
    turns = callback_context.state.get("model_turns", 0) + 1
    callback_context.state["model_turns"] = turns
    if turns > MAX_MODEL_TURNS:
        logger.warning("Max model turns (%d) reached, forcing stop.", MAX_MODEL_TURNS)
        return LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(
                    text="Maximum interaction turns reached. Task ended."
                )],
            ),
        )

    if callback_context.state.get("task_done", False):
        return LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(text="Task completed.")],
            ),
        )

    budget = callback_context.state.get("budget_remaining", None)
    if budget is not None and budget < 0:
        return LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(text="Budget exhausted. Task ended.")],
            ),
        )

    return None


async def before_tool_callback(
    tool, args: dict, tool_context: ToolContext
) -> dict | None:
    """Deduct budget. Free submit exit when exhausted."""
    tool_name = tool.name if hasattr(tool, "name") else str(tool)
    cost = _tool_cost(tool_name, tool_context)
    if cost is None:
        return None

    budget = tool_context.state.get("budget_remaining", 0)

    if budget < cost:
        tool_context.state["_budget_before"] = budget
        if tool_name == "submit_sql":
            tool_context.state["budget_remaining"] = -1
            return None  # free exit, -1 signals stop after this
        return {
            "error": f"Budget exhausted ({budget:.1f} remaining). "
            "You MUST call submit_sql now with your best SQL."
        }

    tool_context.state["_budget_before"] = budget
    remaining = budget - cost
    # After submit drains budget to 0, signal stop with -1
    if tool_name == "submit_sql" and remaining <= 0:
        remaining = -1
    tool_context.state["budget_remaining"] = remaining
    return None


async def after_tool_callback(
    tool, args: dict, tool_context: ToolContext, tool_response
) -> dict | None:
    """Record tool event in trajectory and append budget note to response."""
    tool_name = tool.name if hasattr(tool, "name") else str(tool)
    cost = _tool_cost(tool_name, tool_context) or 0
    budget_before = tool_context.state.get("_budget_before")
    budget_after = tool_context.state.get("budget_remaining")
    initial = tool_context.state.get("initial_budget", 0)

    trajectory = tool_context.state.get("tool_trajectory", [])
    full_text = (json.dumps(tool_response, ensure_ascii=False)
                 if isinstance(tool_response, (dict, list)) else str(tool_response))
    # Engine query ids, read from the FULL response before _preview truncates it.
    # The MCP server appends `queryId: <uuid>` after the result rows, so a query
    # returning more than ~2000 characters of rows lost its id entirely - about a
    # quarter of run_query calls, and a third of final passing queries, which are
    # the ones worth joining to the engine's aggregate and cache tables. The
    # grading audit records the id of the graded execution (see
    # shared.db_utils.extract_query_id); this keeps the agent's own exploratory
    # queries linkable too.
    step = {
        "type": "tool",
        "tool": tool_name,
        "args": args,
        "result": _preview(tool_response),
        # Full response length. The preview above truncates at 2000 characters,
        # which made average output size (the Universal Cost Scheme's criterion)
        # unmeasurable from a run; scripts/cost_scheme_audit.py reads this.
        "result_chars": len(full_text),
        "cost": cost,
        "budget_before": budget_before,
        "budget_after": budget_after,
    }
    qids = _QUERY_ID_RE.findall(full_text)
    if qids:
        step["query_ids"] = qids
    # submit_sql's own text carries no id - the grading execution happens inside
    # the environment service - so the id comes from state, where the tool put
    # it. This is the one that matters: grading re-executes every submission, so
    # it exists even for SQL the agent never ran itself, and it lands in a
    # results JSON that is one run by construction.
    if tool_name == "submit_sql":
        graded = tool_context.state.get("_last_submit_query_id")
        if graded:
            step["query_id"] = graded
        # The grader's verdict and phase for this attempt, and the engine's
        # outbound Postgres SQL (leaderboard mode, semantic-layer path) - the
        # fields scripts/export_submission.py builds the submission file from.
        step["passed"] = bool(tool_context.state.get("_last_submit_passed"))
        if tool_context.state.get("_last_submit_phase") is not None:
            step["phase"] = tool_context.state.get("_last_submit_phase")
        if tool_context.state.get("_last_submit_outbound_sql"):
            step["outbound_sql"] = tool_context.state.get("_last_submit_outbound_sql")
    trajectory.append(step)
    tool_context.state["tool_trajectory"] = trajectory

    task_id = tool_context.state.get("task_id", "?")
    budget_str = f"{budget_after:.1f}/{initial:.1f}" if budget_after is not None else "?"
    logger.info(
        "[%s] turn %d: %s(%s) -> %s  [budget %s]",
        task_id, len(trajectory), tool_name, _preview(args, limit=200),
        _preview(tool_response, limit=200), budget_str,
    )

    # Append budget note to agent-visible response (matches reference implementation)
    if budget_after is not None and budget_after >= 0:
        budget_note = f"\n\n[SYSTEM NOTE: Remaining budget: {budget_after:.1f}/{initial:.1f}]"
        return str(tool_response) + _error_hints(tool_response, _session_backend(tool_context)) + budget_note
    return None


def _error_hints(tool_response, backend: str) -> str:
    """Hints THIS session's backend declares for errors whose own message
    misleads — config/environment_backends.yaml's `error_hints`, matched
    case-insensitively against the response text. Costs nothing: the response is
    already paid for. Kept config-driven so this file never learns a specific
    engine's error strings; "raw" has no backend config and so never gets any."""
    if backend == "raw":
        return ""
    # A/B 2026-09-09 (server-side dialect guidance): HARNESS_ERROR_HINTS=0 turns the
    # client-side hints off so the semantic layer's own error repairs are measured alone.
    if os.environ.get("HARNESS_ERROR_HINTS", "1").strip().lower() in ("0", "false", "off"):
        return ""
    try:
        from shared.environment_backends import get_backend_error_hints
        hints = get_backend_error_hints(backend)
    except Exception:
        return ""
    text = str(tool_response).lower()
    matched = [h["hint"] for h in hints if h.get("match", "").lower() in text and h.get("hint")]
    return "".join(f"\n\n[SYSTEM NOTE: {h.strip()}]" for h in matched)
