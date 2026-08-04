"""ADK callbacks for a-interact mode: budget management and turn limiting."""

import json
import logging
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


def _tool_cost(tool_name: str):
    """Look up a tool's bird-coin cost: the backend-agnostic/raw table above,
    falling back to the ACTIVE backend's own tool_costs from config. Resolved
    per-call (not cached) since the backend can change at runtime via
    /set_backend."""
    if tool_name in TOOL_COSTS:
        return TOOL_COSTS[tool_name]
    if settings.environment_backend == "raw":
        return None
    from shared.environment_backends import get_backend_tool_costs
    return get_backend_tool_costs(settings.environment_backend).get(tool_name)


def _normalize_sql(sql: str) -> str:
    """Collapse a submitted query to a form that ignores differences the engine
    ignores too — whitespace, case, a trailing semicolon, and the optional
    leading catalog qualifier — so a resubmission that only re-spells the table
    name is recognised as the same query. Used solely to refuse duplicate
    submissions (see before_tool_callback); never to rewrite what is executed.
    """
    s = re.sub(r'"atscale_catalogs"\s*\.\s*', "", sql)
    return re.sub(r"\s+", " ", s).strip().rstrip(";").lower()


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
    cost = _tool_cost(tool_name)
    if cost is None:
        return None

    budget = tool_context.state.get("budget_remaining", 0)

    # Refuse a submission identical to one that already failed. The verdict is
    # deterministic, so re-running it can only burn 3 coins for no information —
    # observed 7 times across the 2026-07-31..08-03 etf runs (21 coins), always
    # as the agent re-spelling the table name after an uninformative rejection.
    if tool_name == "submit_sql":
        normalized = _normalize_sql(args.get("sql", ""))
        if normalized and normalized in tool_context.state.get("_failed_submits", []):
            tool_context.state["_budget_before"] = budget
            tool_context.state["_free_call"] = True
            return {
                "error": "Identical to a submission that already failed (ignoring "
                "whitespace, case and the optional catalog prefix), so it would "
                "fail the same way. Not charged. Change something that affects the "
                "result — the projected columns, their order, the row ordering, or "
                "the filter — before submitting again."
            }

    # Refuse a bundled clarification. The user simulator's action parser resolves
    # exactly one labeled ambiguity per turn (user_simulator/server.py's
    # _parse_action), so a multi-part question gets its first part answered and
    # the rest comes back as filler — etf_5 asked "how many funds?" and "what
    # info?" together and got gold's exact column list plus "a reasonable sample
    # size" in place of the LIMIT 100 it needed. Not charged; the agent re-asks
    # one thing. A single question carrying a parenthetical example keeps one "?"
    # and passes; a false positive only costs a free re-ask.
    if tool_name == "ask_user" and args.get("question", "").count("?") > 1:
        tool_context.state["_budget_before"] = budget
        tool_context.state["_free_call"] = True
        return {
            "error": "That asks more than one question. The user answers one at a "
            "time, so the extra parts come back vague. Not charged. Re-ask only "
            "the single question whose answer most changes your query."
        }

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
    cost = _tool_cost(tool_name) or 0
    if tool_context.state.get("_free_call", False):
        cost = 0  # short-circuited by before_tool_callback, budget untouched
        tool_context.state["_free_call"] = False
    elif tool_name == "submit_sql" and "failed" in str(tool_response).lower():
        failed = tool_context.state.get("_failed_submits", [])
        normalized = _normalize_sql(args.get("sql", ""))
        if normalized and normalized not in failed:
            tool_context.state["_failed_submits"] = failed + [normalized]
    budget_before = tool_context.state.get("_budget_before")
    budget_after = tool_context.state.get("budget_remaining")
    initial = tool_context.state.get("initial_budget", 0)

    trajectory = tool_context.state.get("tool_trajectory", [])
    trajectory.append({
        "type": "tool",
        "tool": tool_name,
        "args": args,
        "result": _preview(tool_response),
        "cost": cost,
        "budget_before": budget_before,
        "budget_after": budget_after,
    })
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
        return str(tool_response) + budget_note
    return None
