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

# ── PROMPT FREEZE LIFTED 2026-08-18 (tracker B-49) ─────────────────────────
# Lifted on the same day it was set, for the accuracy fix in B-53: the atscale
# instruction claimed list_models "names every dimension and metric", and it
# names none of them, so an agent was being told its 1-coin call had finished a
# job it had not started. The bar the freeze was protecting still stands, and
# what changed is only its scope: correcting a false statement about what a tool
# returns is not a new guidance rule, and does not need a B-49 decision.
#
# No NEW guidance rule goes in without a decision recorded on B-49, because this
# family has cost two self-inflicted defects already — B-42 was a rule invented
# to repair B-38, and B-47 was the un-narrowed half of B-38 left in one arm — and
# because a prompt that keeps growing makes the framework, not the semantic
# model, the thing under measurement.
#
# The test any future rule must pass: is it derivable from the QUESTION alone?
# B-37 passes (the question names the entity). B-41 passes (the question asks for
# a state; only the user knows the wording). B-42 failed it — its justification
# was a count of gold ORDER BYs — and is gone. Helping one arm more than the
# other is NOT a reason to cut a rule: B-37 and B-41 both help raw more, which is
# what makes the lift number defensible rather than tuned.
# ───────────────────────────────────────────────────────────────────────────
# Shared across both a-interact instructions below so they can never drift out
# of sync — the grading function (shared/db_utils.py ex_base/ex_base_external_pred)
# compares result ROWS as exact tuples against a reference answer for BOTH
# backends, so this applies identically regardless of which one is active.
#
# The ORDER BY bullet used to be two: one saying "don't invent a sort" and a
# second one carving grouped results back out of it (tracker B-42). Both are now
# one narrowed bullet. Measured 2026-08-18 with scripts/counterfactual.py and
# scripts/rule_exposure.py over 122 stored runs: on the 264 submissions where the
# carve-out applied, 259 already sorted their grouped result with nothing telling
# them to, and the single live conversion it could claim (crypto_exchange_6 phase
# 2) was a regression the un-narrowed first bullet had itself caused. A second
# rule repaired the first, on behaviour the agent already had, and cost 3 phases
# across the 22 databases where obeying it loses a point — so it is gone.
RESULT_SHAPE_TIP = (
    "- Match the exact output shape the grading expects: return the column(s) the question actually asks for — in the order the question fixes, and where it fixes none (a prose list of figures, two figures asked as separate sentences, a follow-up that adds a column without saying where) in the order the USER gives when asked, because the reference's column order is not reliably the order the words come in — with no extra descriptive or ID columns (e.g. don't add a plant name or snapshot ID column unless the question asks to see it). Your submission is graded by comparing result rows to a reference answer as exact tuples, so a wrong column count fails even when the requested value itself is correct — and this cuts BOTH ways: an unrequested extra column and a missing implied column are equally fatal. Before submitting, ask what a person would expect to see, not just the literal nouns in the sentence: a request to identify or list the entities that qualify on some quantity (worst offenders, biggest claims, top spenders) usually expects that quantity shown next to the identifier, and a request to rank or sort implies the value being ranked by is part of the answer. When a pre-computed Yes/No flag encodes the qualifying condition, it tells you WHICH rows qualify but does not supply the underlying number — include that number too if the question is about how much or how many. And once the user has TOLD you which columns the result should hold ('a count per group along with the average'), the answer is exactly those columns, in the order they named them — not those plus the total you had already computed, and not the ones you had in mind before asking. Measured: an agent asked, was told 'count and average', submitted count, total AND average, and lost the phase on the extra column. Likewise, quantities the question says to include, show or give alongside the main figure ('include the daily recovery value and the total days in the calculation', 'along with the flag count and weight') are COLUMNS of the answer, not merely inputs you use and drop — a single-column answer to such a question is a wrong column count; if you cannot tell whether a named quantity is to be shown or only used, ask.\n"
    "- When the question NAMES the entity — 'for order OR6015391, what is its X', 'for market EX203, is it Y' — the identifier is NOT part of the answer. You were given it; the answer is the value asked for and nothing else, usually a single column of a single row. Projecting the id alongside the value is a wrong column count and fails, and bisecting your way to that by resubmitting one column shorter each time costs more than the task is worth. The same holds for a question that asks for one overall figure ('calculate the X across all Y'): that is one row, so do not add a GROUP BY that turns it into one row per member.\n"
    "- A yes/no determination in the answer ('is he meeting it', 'does it qualify', 'flag anything over the limit') is a NUMERIC column, not text: write 1 for yes/true and 0 for no/false. Reference answers compute such flags as bare comparisons or CASE ... THEN 1 ELSE 0 - measured across the corpus, 43 of the 46 golds that emit a flag emit it numerically - so 'Yes'/'No' text fails the exact-tuple comparison even when every other value in the row is right (measured live: a task with every number correct scored 0 on exactly this). The exception is when the user names the words they want to see ('just a plain Yes or No is fine') - then use their words verbatim.\n"
    "- Row ORDER is part of that comparison, and NOT only when the question sounds like a ranking. Whenever a ranking IS implied — 'top', 'best/worst', 'highest/lowest', 'most/least' — always add an explicit ORDER BY on the measure being ranked, even if the question does not say 'sorted by'. But a plain multi-row listing is order-compared too, and assuming otherwise is a measured way to lose a task whose rows were already correct: a listing of per-center events returned exactly the right rows and still failed, because it sorted by the timestamp alone where the reference sorted by the center and then the timestamp. So whenever the answer has more than one row, sort deliberately, and read the question to decide how. When the rows are ONE PER ENTITY and the question selected them on a quantity — a threshold, a screen, an 'over the limit' / 'at risk' / 'too high' condition — a screen is an implicit ranking: sort by the quantity that qualified them, most extreme first (highest urgency, shortest remaining life, largest error), and when two quantities were screened on, by the one the question names first and then the other. Do NOT sort such a listing by the identifier: an id order is never what a person expects from a screen, and it is a measured way to fail a listing whose rows were already right. When SEVERAL ROWS BELONG TO ONE ENTITY (events per center, snapshots per plant, records per patient), sort COARSE TO FINE — the entity the report is organized around first (the id, center, region or category the question groups by), then the key that orders rows within it (time, rank, or the measure) — rather than by a time column on its own. A RANK column in the answer does not fix the row order: when the rows are time periods (months, years) and a rank is printed beside them, the reference is as often in calendar order as in rank order (measured: a top-3-months answer with every value and rank right failed on order alone, resubmitted three times in rank order) — ask once, and if a submit whose values you have confirmed fails, change the ORDER BY before resubmitting the same shape. A sensible ORDER BY never costs you anything and its absence can fail an otherwise correct answer."
)

# Backend-agnostic for the same reason as RESULT_SHAPE_TIP: the user simulator
# is one service shared by every backend, so how to interrogate it must not live
# in a per-backend config. Keyed off the same trigger words as the ORDER BY tip
# above — a ranking word implies both a sort and, usually, an unstated cutoff.
ASK_USER_TIP = (
    "- Ask about exactly ONE ambiguity per ask_user call. The user answers one thing per turn: a bundled question gets its first part answered and the rest comes back as filler, and you still paid 2 coins. Ask the question whose answer most changes the query, then ask the next.\n"
    "- When the question implies a cutoff but never names it — 'highest', 'top', 'some', 'enough', 'sufficient', 'significant' — that number is something the user knows and you cannot derive. Ask for it outright ('exactly how many rows should the result contain?'). If the answer is qualitative ('a reasonable sample', 'the top ones'), ask again offering explicit options ('10, 25, 50, or 100?'). That second ask is worth 2 coins: a wrong cutoff fails the exact-tuple comparison however correct everything else is.\n"
    "- The same applies when the rows themselves are named categories rather than a single classification column — one row per HLA locus, per score band, per status. The reference prints label text you cannot derive ('A-Locus Mismatch', not 'A'), so ask for the exact wording of every row label. And when the question names the categories in a particular sequence, that sequence is usually the column or row order the reference uses: do not silently re-sort them alphabetically, and ask which order is wanted if the question does not make it plain.\n"
    "- Watch for categories that are INDEPENDENT FLAGS rather than mutually exclusive states. If a single record can be in more than one of them at once (a match can mismatch on the A locus AND the B locus), a CASE chain is wrong — it assigns each record to the first branch that matches and undercounts every later one. Count each category separately (a SUM(CASE WHEN <flag> THEN 1 ELSE 0 END) per category, or one SELECT per category combined with UNION ALL) so a record can contribute to all the categories it satisfies.\n"
    "- When the answer needs a classification, status or summary COLUMN — 'show whether each one has drifted', 'add a summary', 'label each as X or Y' — the exact wording that column prints is the user's to decide and you cannot derive it. Ask for the literal text of every case ('what exact text should that column show for each one?'), and use their spelling verbatim. Those labels are compared as cell values, so correct rows under wording you invented score zero.\n"
    "- When the answer is a MULTI-ROW LISTING and the question gives no sort cue at all — no ranking word, no screened quantity, no 'by'/'in order of', just 'list them' or 'show me' — the row order is an open slot exactly like an unstated cutoff or an unstated label. A bare 'sort the results' / 'sort them properly' / 'also sort them' with no column named is THIS case, not a cue: it says the order matters and nothing about what it is (measured: a grouped count sorted by its label where the reference sorted by the count, on a question that said only 'sort the results'; the sibling task that asked got 'by compliance ID' in one turn and passed): only the user knows which column the list is ordered by and which direction, and the reference is compared row by row. Ask it once, as a closed question naming the columns you will show ('should the rows be ordered by X, by Y, or something else — ascending or descending?'), and sort by the answer. Do NOT ask when the question does cue a sort (a ranking word, a screen on a quantity, a stated order); sort as the ORDER BY guidance says and spend the coins elsewhere. Measured: five multi-row listings on one database failed only on order, sorted by an identifier or by the screened quantity where the reference sorted by a displayed value the question never named. When the listing is ONE FIGURE PER GROUP ('on each platform, what is the average X', 'per cluster, the total Y') and you will not spend the ask, never fall back to the group label or to no ORDER BY at all - order by the figure, largest first. Measured: two per-platform averages on one database returned the right four rows and failed only on order, one sorted by the platform label and one not sorted; the reference ordered both by the figure, largest first.\n"
    "- When the question wants ONE overall figure for a whole population ('the overall risk score for the collection', 'the suitability for artifacts from X') and the underlying quantity exists per entity, the AGGREGATE is an open slot: maximum, average, sum and count are all defensible readings of 'overall' and only the user knows which. Ask it once, as a closed question naming the options ('the highest single score, the average across them, or the total?'), before choosing - a measure named Average is not evidence the question wants an average.\n"
    "- The same slot opens when the question is a bare 'show me the X' / 'find the X' / 'give me the X' with NO per-entity cue - no 'each', 'list', 'per', 'which ones', no column list - and X is a computed score, a rate, or a set that qualifies on a rule ('the failing showcases', 'the suitability for artifacts from X'). Such a question is as often answered by ONE figure (a count of the qualifying entities, one average) as by one row per entity, and the two shapes cannot both be right. Ask once before the first submit ('do you want the single overall figure - the count / the average - or one row per entity, and if rows, which columns?'), instead of submitting a listing and resubmitting it re-sorted: a shape guess that misses costs every submit that follows.\n"
    "- The aggregate slot is ALSO open when a per-record amount is broken down BY a category with no aggregate word — 'break down the handling cost by region', 'which route produces the most emissions', 'how expensive is it to process items in each state'. The total per group and the average per group are both defensible readings, they rank the groups differently, and only the user knows which. Ask once, as a closed question ('the total per group, or the average per record in it?'). Do NOT ask when the question already carries the word: total / sum / spend / altogether / overall spend cue the total; average / mean / typical / usually / per return cue the average. Measured: two grouped breakdowns on one database submitted the Total three times each where the reference was the Average, and the one task that asked got the answer in one turn.\n"
    "- A share, portion, proportion, ratio or rate asked WITHOUT a scale ('what portion of records are flagged', 'what share of orders') is either a fraction (0-1) or a percentage (0-100), and the reference picks one you cannot derive. When the question says 'percentage' or 'percent', return 0-100. Otherwise ask once ('as a percentage, or as a fraction between 0 and 1?') before the first submit — a published rate's description says which scale IT uses, not which the question wants. Measured: a task returned the correct 0.208 twice against a reference of 20.8 and never asked.\n"
    "- COLUMN ORDER is an open slot whenever ONE answer row holds two or more figures and nothing fixes their left-to-right order: the question lists them in prose ('the score along with the flag count and the weight'), asks them as separate sentences ('how expensive is X? What about Y?'), or a follow-up ADDS a column without saying where it goes ('also include the number of records while keeping the average'). The reference is compared as an ordered tuple, and its order is NOT reliably the order the words come in — measured on one database, two phase-1 answers with every value right failed only on the two figures being swapped, and an added count went BEFORE the kept measure in every one of four follow-ups where the agent had appended it. Ask once, naming the columns ('in what order should the columns appear — X, Y, Z?'), and use the answer. Do NOT ask when the wording fixes the position ('next to X', 'after X', 'first ..., then ...') — then use that.\n"
    "- Trigger that ask off YOUR OWN ANSWER, not only off the question's phrasing. If the question asks for a state or an assessment — 'check its market health', 'assess its risk', 'is it showing signs of X' — and the value you are about to return is a Yes/No flag, a code, or a phrase you chose yourself, then you are inventing the wording. Yes/No is how a precomputed flag stores the condition; it is not what the answer column prints, and neither is a word you picked for the other case. Ask for the literal text of BOTH cases before submitting. One ask covers it, and it is worth spending on: when the condition and the grain are already right, the cell text is the only thing left that can fail, and resubmitting different phrasings until one lands costs 3 coins a try and usually runs out first.\n"
)

# Appended to a semantic-layer backend's instruction ONLY when
# settings.semantic_layer_knowledge_tools is on, because that is the same flag
# that puts the three tools in the tool list (system_agent/tools_atscale.py).
# Advertising them unconditionally would have the agent spend turns calling
# tools it does not have. Not needed for the raw backend, whose static
# AINTERACT_INSTRUCTION has always listed them.
KNOWLEDGE_TOOLS_TIP = (
    "- get_all_external_knowledge_names (0.5) lists the task's glossary of defined domain terms; get_knowledge_definition (0.5) returns one entry's formula and thresholds; get_all_knowledge_definitions (1) returns every entry at once and can be long.\n"
    "- Search the semantic model FIRST. It is built from this same glossary and already encodes it: a named term usually exists as its own column whose description quotes the glossary entry it came from, so explore_columns/focus_columns normally answer the definitional question and the query-construction question in one call. Paying for a glossary entry you then have to go and find in the model anyway is the most common way to waste budget here.\n"
    "- Reach for the glossary when the model does NOT settle it: the term is nowhere in the model, or the description names a condition without its threshold, or the description says it resolved an ambiguity (a unit, a scale, which of two readings) and you need the original wording to check that reading against the question. When you want more than one entry, call get_all_knowledge_definitions once (1) rather than get_knowledge_definition repeatedly (0.5 each) — past runs have spent 15 coins one entry at a time.\n"
    "- Where a column description and a glossary entry genuinely disagree, the glossary is what the answer is graded against; prefer it, and compute from the underlying columns rather than the precomputed flag that encodes the other reading.\n"
    "- A term in neither the model nor that list has no official definition: that is when to ask_user. Do not ask the user to define a term either source already defines."
)

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
- Be efficient with your actions to conserve budget.
- Make sure the submitted SQL is valid and addresses all aspects of the question.
- Keep track of the remaining budget and prioritize actions accordingly.
- Be careful with broad retrieval tools such as get_all_column_meanings and get_all_knowledge_definitions because they may return a long context.
- Test SQL with execute_sql before submit_sql when useful.
- If a submission fails and budget remains, debug and try again.
- After a successful phase-1 submission, you may receive a follow-up question for phase 2.
""" + RESULT_SHAPE_TIP + "\n" + ASK_USER_TIP


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
            instruction = (get_backend_instruction(settings.environment_backend)
                           + RESULT_SHAPE_TIP + "\n" + ASK_USER_TIP)
            if settings.semantic_layer_knowledge_tools:
                instruction += "\n" + KNOWLEDGE_TOOLS_TIP
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
