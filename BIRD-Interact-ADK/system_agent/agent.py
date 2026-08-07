"""BIRD-Interact ADK System Agent."""

import logging
from typing import Any

from shared.config import settings

try:
    from google.adk import Agent
    from google.adk.tools import FunctionTool
    from google.genai import types
    ADK_AVAILABLE = True
    ADK_IMPORT_ERROR = ""
except ImportError as exc:
    Agent = Any
    FunctionTool = None
    types = None
    ADK_AVAILABLE = False
    ADK_IMPORT_ERROR = str(exc)

logger = logging.getLogger(__name__)


from shared.llm import build_adk_model as _build_model

# ── c-interact instruction ──
# Schema and knowledge are injected via session state placeholders {db_schema}, {external_kg}
CINTERACT_INSTRUCTION = """You are a data scientist with great PostgreSQL writing ability.
You have a DB called "{db_name}".

# DB Schema Info:
{db_schema}

# External Knowledge:
{external_kg}

# Instructions:
You are tasked with generating PostgreSQL to solve the user's query. However, the query may be ambiguous. You can ask clarification questions using the ask_user tool, or submit your final SQL using the submit_sql tool.

You have at most {max_turn} clarification turns. After that you must submit.

Strategy:
- Ask ONE clarification question at a time using ask_user.
- When you have enough clarity, call submit_sql with your PostgreSQL query.
- If a submission fails, analyze the error and try again.
- After a successful Phase 1, you may receive a follow-up question for Phase 2.
"""

# Shared across both a-interact instructions below so they can never drift out
# of sync — the grading function (shared/db_utils.py ex_base/ex_base_external_pred)
# compares result ROWS as exact tuples against a reference answer for BOTH
# backends, so this applies identically regardless of which one is active.
RESULT_SHAPE_TIP = "- Match the exact output shape the grading expects: return the column(s) the question actually asks for, in the order asked, with no extra descriptive or ID columns (e.g. don't add a plant name or snapshot ID column unless the question asks to see it). Your submission is graded by comparing result rows to a reference answer as exact tuples, so a wrong column count fails even when the requested value itself is correct — and this cuts BOTH ways: an unrequested extra column and a missing implied column are equally fatal. Before submitting, ask what a person would expect to see, not just the literal nouns in the sentence: a request to identify or list the entities that qualify on some quantity (worst offenders, biggest claims, top spenders) usually expects that quantity shown next to the identifier, and a request to rank or sort implies the value being ranked by is part of the answer. When a pre-computed Yes/No flag encodes the qualifying condition, it tells you WHICH rows qualify but does not supply the underlying number — include that number too if the question is about how much or how many."

# ── a-interact instruction ──
AINTERACT_INSTRUCTION = """You are a helpful PostgreSQL agent that interacts with a user and a database to solve the user's question.

Task description:
Your goal is to understand the user's ambiguous question involving external knowledge retrieval and generate the correct SQL query to solve it.
You can:
1. Interact with the user to ask clarifying questions or submit the SQL query.
2. Interact with the database environment to explore the database and retrieve relevant information.

The interaction ends when you submit the correct SQL query or the budget runs out.
Each action costs bird-coins, so you should be efficient.

Available tools and costs:
- execute_sql: execute a PostgreSQL query. Cost: 1
- get_schema: get the database schema. Cost: 1
- get_all_column_meanings: get all column meanings. Cost: 1
- get_column_meaning: get the meaning of one column. Cost: 0.5
- get_all_external_knowledge_names: get all external knowledge names. Cost: 0.5
- get_knowledge_definition: get one external knowledge definition. Cost: 0.5
- get_all_knowledge_definitions: get all external knowledge definitions. Cost: 1
- ask_user: ask the user a clarification question. Cost: 2
- submit_sql: submit the SQL for evaluation. Cost: 3

Important strategy tips:
- First explore the database schema, column meanings, and relevant external knowledge to understand the task.
- If the user's intent is ambiguous, ask clarifying questions to figure out the real intent before committing to SQL.
- Ask one clarification question at a time.
- Be efficient with your actions to conserve budget.
- Make sure the submitted SQL is valid and addresses all aspects of the question.
- Keep track of the remaining budget and prioritize actions accordingly.
- Be careful with broad retrieval tools such as get_all_column_meanings and get_all_knowledge_definitions because they may return a long context.
- Test SQL with execute_sql before submit_sql when useful.
- If a submission fails and budget remains, debug and try again.
- After a successful phase-1 submission, you may receive a follow-up question for phase 2.
""" + RESULT_SHAPE_TIP + "\n"


def build_agent(mode: str = "c-interact") -> Agent:
    """Build the system agent for the given mode.

    Args:
        mode: "c-interact" for conversational, "a-interact" for agent with tools.
    """
    if not ADK_AVAILABLE:
        raise RuntimeError(f"google-adk runtime unavailable: {ADK_IMPORT_ERROR}")

    model = _build_model(settings.system_agent_model)
    if mode == "a-interact":
        from system_agent.callbacks import (
            before_model_callback, before_tool_callback, after_tool_callback,
        )
        if settings.environment_backend == "raw":
            from system_agent.tools import get_ainteract_tools
            tools = get_ainteract_tools()
            instruction = AINTERACT_INSTRUCTION
        else:
            from shared.environment_backends import get_backend_instruction, get_backend_tools_factory
            tools = get_backend_tools_factory(settings.environment_backend)()
            instruction = get_backend_instruction(settings.environment_backend) + RESULT_SHAPE_TIP + "\n"
        return Agent(
            model=model,
            name="bird_interact_agent",
            description="Text-to-SQL agent for BIRD-Interact a-interact benchmark.",
            instruction=instruction,
            tools=tools,
            before_model_callback=before_model_callback,
            before_tool_callback=before_tool_callback,
            after_tool_callback=after_tool_callback,
            generate_content_config=types.GenerateContentConfig(temperature=0.0),
        )
    else:
        from system_agent.tools import ask_user, submit_sql
        from system_agent.callbacks_cinteract import (
            before_model_callback as c_before_model,
            before_tool_callback as c_before_tool,
            after_tool_callback as c_after_tool,
        )
        return Agent(
            model=model,
            name="bird_interact_agent",
            description="Text-to-SQL agent for BIRD-Interact c-interact benchmark.",
            instruction=CINTERACT_INSTRUCTION,
            tools=[FunctionTool(ask_user), FunctionTool(submit_sql)],
            before_model_callback=c_before_model,
            before_tool_callback=c_before_tool,
            after_tool_callback=c_after_tool,
            generate_content_config=types.GenerateContentConfig(temperature=0.0),
        )
