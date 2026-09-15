"""Centralized configuration.

Settings are loaded in this priority (highest wins):
  1. Environment variables (e.g. PATIENCE=6 python -m orchestrator.runner ...)
  2. .env file in project root (user-specific, gitignored)
  3. Defaults defined below

Users: copy .env.example to .env and edit.
See .env.example for all available settings.
"""

import logging
from pathlib import Path
from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings

# Load .env into os.environ so litellm/openai can read OPENAI_API_KEY etc.
load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The user simulators the BIRD-Interact leaderboard runs its own tracks on. The
#: board is GROUPED BY SIMULATOR, not pinned to one: bird-interact.github.io
#: publishes a full Claude-Haiku-4-5 board (Claude-Opus-4.6, Kimi-2.5, GLM-4.7,
#: MiniMax-M2.1, ...) AND a full GPT-4o board (GPT-5, Claude-Sonnet-4,
#: Gemini-2.5-Pro, O3-Mini, ...). Both are first-class; an entry is listed on the
#: board matching its simulator. Only a simulator outside this set makes a run a
#: "Customized-User" entry.
#:
#: A run is therefore comparable to the other entries on ITS OWN board and to no
#: other - the same agent scores differently under different simulators, so a
#: Haiku-track number must never be set beside a GPT-4o-track number.
LEADERBOARD_USER_SIM_MODELS = {
    "haiku": "anthropic/claude-haiku-4-5-20251001",
    "gpt4o": "openai/gpt-4o",
}

#: Default track when LEADERBOARD_TRACK is unset - the board our existing tabs
#: (Opus-4.6, Sonnet-5, Kimi-2.5) were measured on.
LEADERBOARD_USER_SIM_MODEL = LEADERBOARD_USER_SIM_MODELS["haiku"]

#: The comparison corrections this harness adds on top of upstream grading.
#: Applied under grading_regime == "corrected" (our A/B work) and NOT under
#: "upstream" (leaderboard mode), where the grader must score exactly as the
#: BIRD team's evaluator will. Names are the ones every results file records.
GRADING_CORRECTION_NAMES = (
    "timestamp_date",        # a timestamp STRING truncates to its date
    "order_requires_cue",    # order=true only when the question asks for one
    "casefold_text",         # text cells compare case-insensitively
    "column_order_free",     # a column permutation of the gold matches
    "ties_as_ties",          # ordered gold with ties: multiset within a tie group (key read from gold SQL)
    "numeric_rel_tolerance", # pre-rounding numerics compare within 1e-6 relative
)


class Settings(BaseSettings):
    # LLM provider
    llm_provider: str = "litellm"

    # PostgreSQL
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_user: str = "root"
    pg_password: str = "123123"
    pg_minconn: int = 1
    pg_maxconn: int = 5

    # Service ports
    system_agent_port: int = 6000
    user_sim_port: int = 6001
    db_env_port: int = 6002

    # ── LEADERBOARD MODE ── one switch, every deviation from the published
    # BIRD-Interact protocol off, so a run is comparable to the entries on
    # https://bird-interact.github.io/ and exportable as a submission.
    #
    # LEADERBOARD_MODE=true (env or .env) makes ALL of the following true, in
    # every process that reads settings (the three services and the runner):
    #   1. grading_regime == "upstream": the six comparison corrections are off
    #      and rows compare exactly as evaluation/src/eval_bird_interact.py does.
    #   2. user_sim_model is forced to LEADERBOARD_USER_SIM_MODEL and the
    #      simulator runs the UPSTREAM prompts and token limits - no fidelity
    #      rules, no numeric guard (user_simulator/prompts.py, server.py).
    #   3. system_agent_model defaults to leaderboard_agent_model (below).
    #   4. Management-category tasks are RUN, not filtered: on a semantic-layer
    #      backend each is routed per task to the raw Postgres tools and the
    #      raw grading path, so all 600 tasks score (orchestrator/ainteract.py).
    #   5. Tool costs follow the guidelines' Universal Cost Scheme
    #      (system_agent/callbacks.py LEADERBOARD_TOOL_COSTS).
    #   6. Every graded semantic-layer submission also records the engine's
    #      OUTBOUND Postgres SQL, which is what the submission file carries as
    #      the predicted SQL (db_environment/server.py, scripts/export_submission.py).
    # The runner refuses to start if any service reports a different value of
    # this flag than its own, so a half-switched stack cannot score a run.
    # scripts/run_leaderboard.sh is the one-command entry point.
    leaderboard_mode: bool = False
    # The agent under test in leaderboard mode. Opus 4.6 first, so the run
    # compares directly with Anthropic's Claude-Opus-4.6 entry (33.0% phase-1
    # success, Claude-Haiku-4-5 simulator); override with LEADERBOARD_AGENT_MODEL.
    leaderboard_agent_model: str = "anthropic/claude-opus-4-6"
    # Which leaderboard track (= which user simulator) this run belongs to:
    # "haiku" (default, our existing tabs) or "gpt4o" (the board's GPT-5 /
    # Sonnet-4 / Gemini-2.5-Pro track). Names a simulator from
    # LEADERBOARD_USER_SIM_MODELS; anything else is refused at startup rather
    # than silently producing an unlistable Customized-User run.
    leaderboard_track: str = "haiku"

    # Models (LiteLlm format: provider/model-name)
    user_sim_model: str = "anthropic/claude-haiku-4-5-20251001"
    system_agent_model: str = "anthropic/claude-sonnet-4-20250514"

    # LiteLlm proxy (optional — set if using a LiteLlm proxy server)
    litellm_api_base: str = ""
    litellm_api_key: str = ""

    # Per-call completion ceiling for the SYSTEM AGENT's LLM. Applies to both
    # arms identically (raw and semantic share build_adk_model), so changing it
    # is a symmetric harness setting, not a grading deviation. Why it exists:
    # at 4096, an extended-thinking model can spend the whole budget inside the
    # thinking block; the API then returns a thinking-only turn (text='',
    # thought=True) with stop_reason max_tokens, ADK's is_final_response()
    # treats it as the final answer, and the task ends unsubmitted with coins
    # unspent (observed 2026-08-17: 3 of 19 tasks, 6 calls at exactly 4096;
    # zero such deaths in any raw run, so the truncation biased against the
    # semantic arm, whose bigger prompts think longer). The user simulator's
    # own max_tokens is deliberately NOT covered by this setting - changing the
    # simulator changes the benchmark's answers, not its plumbing.
    system_agent_max_tokens: int = 16384

    # Same truncation disease as the agent's old 4096 default, in the simulator:
    # sonnet-class models spend completion budget on thinking (native blocks AND
    # the v2 prompts' own <think> protocol) before the <s>answer</s>. At the old
    # hard-coded 500/1024 the response hit finish=length mid-think - content came
    # back None or without <s>, surfacing as an EMPTY user answer that still cost
    # the asking agent 2 bird-coins (14 wasted asks in one measured run).
    user_sim_max_tokens: int = 8192

    # COST, not a deviation. Anthropic prompt caching for the system agent.
    # cache_control marks a prefix as reusable; it is not prompt content, so the
    # agent sees the same bytes and decides the same things either way — the only
    # difference is the bill. Every agent turn re-sends the whole conversation,
    # so the fixed system+tools prefix and the history are paid for again on each
    # call at full price with this off. Anthropic-family models only (the
    # breakpoints are meaningless elsewhere and other providers reject them).
    # Verify it actually landed via cache_read_tokens in llm_usage — see
    # shared/llm.py and the "API spend" section of CLAUDE.md.
    prompt_caching: bool = True

    # Dataset: "lite" or "full"
    dataset: str = "lite"

    # User simulator prompt version: "v1" (legacy) or "v2" (recommended)
    prompt_version: str = "v2"

    # Budget / turns
    patience: int = 3

    # Environment backend: "raw" (original Postgres tools) or a named backend
    # from config/environment_backends.yaml (e.g. "atscale"), which routes
    # exploration/query tools through that semantic layer's MCP server instead.
    # Set via the --backend CLI flag (scripts/start_services.sh,
    # orchestrator.runner), NOT via .env — this field's default ("raw") only
    # applies if a process is started without --backend. The MCP URL/token are
    # shared across backends (AtScale, Snowflake Semantic Views, Databricks UC
    # Metric Views, ...) — only one backend is active at a time, so one
    # URL/token pair covers whichever backend's MCP server that is.
    environment_backend: str = "raw"
    semantic_layer_mcp_url: str = ""
    semantic_layer_mcp_token: str = ""
    # The MCP server's unauthenticated admin port (its /configz route), used only
    # by the leaderboard-mode pre-flight: a leaderboard run on a semantic-layer
    # backend needs the server started with ATSCALE_MCP_DISABLE_AGGREGATES=true,
    # or the outbound SQL in the submission reads aggregate tables the BIRD
    # evaluator does not have (scripts/mcp_aggregates.sh on).
    semantic_layer_mcp_admin_url: str = "http://localhost:3003"

    # ── Grading corrections (unconditional, both arms) ──
    # Four corrections to upstream BIRD-Interact's comparison are applied on
    # every run and are deliberately NOT configurable: each removes an asymmetry
    # that scored a correct answer wrong, so they are bug fixes, not tolerances.
    #   1. timestamp_date      — a timestamp STRING is truncated to its date,
    #                            as preprocess_results already does to a TYPED
    #                            date/datetime.
    #   2. order_requires_cue  — order=true is honoured only when the phase's
    #                            question asks for an order (ORDER_CUE_RE).
    #   3. casefold_text       — text cells compare case-insensitively.
    #   4. column_order_free   — a column permutation of the gold matches.
    # They were env flags (GRADING_TIMESTAMP_DATE, GRADING_ORDER_REQUIRES_CUE,
    # GRADING_CASEFOLD_TEXT, GRADING_COLUMN_ORDER_FREE), all defaulted on, until
    # 2026-09-07. Every scored run of 2026-09-06/07 applied all four; the flags
    # are gone so no later run can quietly score without them, and a totals
    # number no longer needs a flag block to be comparable. Each one's rationale,
    # its measured effect on BOTH arms (they were adopted only because the arms
    # moved together) and the one cost of #1 — gold text that merely LOOKS like a
    # timestamp is truncated too — sit beside the code in shared/db_utils.py and
    # in docs/bird-grading-comparison.md. The grading process still names the
    # corrections it applies on /health, so a results file records what scored it
    # and the runner can refuse a service whose build predates this change.
    #
    # The opt-in grading tolerances that used to live here (tie permutations,
    # per-task decimal places, a relative numeric tolerance, an order lint) were
    # removed on 2026-09-04: every one stayed off for every scored run, so the
    # code behind them had never graded anything, and upstream's behaviour is
    # what off already did. Verified against the reference implementation checked
    # out beside this repo (bird_interact_agent/, evaluation/) on 2026-08-04 —
    # see the tracker's B-06, B-09 and B-10.


    # ACCOUNTING (not a deviation — nothing about a run changes). Path to a
    # JSONL file recording one row per LLM call (role, model, tokens, cache
    # tokens, dollar cost). Appended to by all three services; the orchestrator
    # aggregates the rows for a run's own time window into that run's results
    # JSON under "llm_usage". Empty disables it.
    #
    # Roles are tagged from BIRD_LLM_ROLE, set per service in
    # scripts/start_services.sh — without it every row reads role="unknown" and
    # spend can only be split by model, which collapses when both roles use the
    # same one. See shared/usage.py.
    llm_usage_path: str = "results/llm_usage.jsonl"

    # AUDIT (not a deviation — grading is unaffected). Path to a JSONL file
    # recording each graded submission's predicted rows, gold SQL and verdict,
    # so a later grading change can be re-scored offline against Postgres
    # instead of by re-running the benchmark. Empty disables it. The
    # semantic-layer path is the reason it exists: its predicted rows live only
    # in the MCP response and were previously discarded after scoring.
    #
    # Defaulted ON 2026-08-14. It was opt-in, and the runs that most needed
    # re-grading are exactly the ones nobody thought to enable it for. Every
    # grading flag below is a deviation, so every recorded score needs to stay
    # re-gradable offline — which is only possible if the rows were kept.
    # Costs a few MB per run and changes no verdict.
    grading_audit_path: str = "results/grading_audit.jsonl"

    # FEEDBACK MEMORY (semantic-layer path only; telemetry capture, P1 of the
    # certified-answer-memory PRD). True makes the harness (1) pass the task's
    # ambiguous question as run_query's `question` param, (2) capture — and
    # strip before the agent sees it — the exchangeId line the MCP server
    # appends to run_query results, and (3) record the simulated user's
    # accepted/rejected verdict about each submission via the server's
    # record_feedback tool (source=end_user_explicit, rater=bird_simulator),
    # fire-and-forget from the harness. The agent-visible surface, coin costs,
    # simulator and grader are all unchanged, so a flag-on run is directly
    # comparable to a flag-off run. Requires the MCP server started with
    # ATSCALE_MCP_FEEDBACK_MEMORY=true over an engine image carrying the
    # 20260826_create_mcp_feedback changelog; when the server side is absent,
    # every call degrades to a logged warning. Off preserves prior behavior
    # exactly. Recorded per run in the results JSON.
    feedback_memory: bool = False
    # A/B 2026-09-09 (question-scoped memory): when true, list_models is called
    # with the task's question so the server narrows the served memory blocks to
    # the entries relevant to it (ATSCALE_MCP_FEEDBACK_QUESTION_SCOPE_K). False
    # keeps the unscoped blocks — the control arm. Recorded in each run's
    # `deviations` so a result file says which arm it was.
    list_models_question: bool = False

    # Shared secret matching the MCP server's ATSCALE_MCP_FEEDBACK_RATER_TOKEN.
    # The server honors privileged feedback sources (end_user_explicit) only when
    # record_feedback carries this as raterToken; without it the verdict is
    # recorded at agent_inferred weight and never certifies on its own. Empty
    # means "send no token" - fine when the server has none configured.
    feedback_rater_token: str = ""

    @model_validator(mode="after")
    def _apply_leaderboard_mode(self):
        """Leaderboard mode pins the models. Done here, once, so every reader of
        settings.user_sim_model / system_agent_model - the services, the runner,
        the usage log - sees the pinned value and nothing has to remember to
        check the flag. A .env that names another simulator is overridden and
        logged, never silently honoured."""
        if not self.leaderboard_mode:
            return self
        log = logging.getLogger(__name__)
        track = (self.leaderboard_track or "haiku").strip().lower()
        if track not in LEADERBOARD_USER_SIM_MODELS:
            raise ValueError(
                f"LEADERBOARD_TRACK={self.leaderboard_track!r} is not a board track; "
                f"choose one of {sorted(LEADERBOARD_USER_SIM_MODELS)}. A simulator outside "
                "this set makes the run a Customized-User entry, not a listable one."
            )
        pinned = LEADERBOARD_USER_SIM_MODELS[track]
        if self.user_sim_model != pinned:
            log.warning("LEADERBOARD_MODE (track %s): USER_SIM_MODEL=%r ignored; the simulator "
                        "is pinned to %s", track, self.user_sim_model, pinned)
            self.user_sim_model = pinned
        if self.system_agent_model != self.leaderboard_agent_model:
            log.info("LEADERBOARD_MODE: system agent is %s (LEADERBOARD_AGENT_MODEL), not SYSTEM_AGENT_MODEL=%r",
                     self.leaderboard_agent_model, self.system_agent_model)
            self.system_agent_model = self.leaderboard_agent_model
        return self

    @property
    def grading_regime(self) -> str:
        """"upstream" scores exactly as BIRD's evaluator; "corrected" adds the
        six symmetric corrections. Derived from leaderboard_mode on purpose -
        there is no way to run the leaderboard stack with corrected grading."""
        return "upstream" if self.leaderboard_mode else "corrected"

    @property
    def grading_corrections(self) -> tuple:
        """The corrections in force for this process - what /health reports and
        every results file records. Empty under the upstream regime."""
        return GRADING_CORRECTION_NAMES if self.grading_regime == "corrected" else ()

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / f"bird-interact-{self.dataset}"

    @property
    def data_path(self) -> str:
        return str(self.data_dir / "bird_interact_data.jsonl")

    @property
    def db_data_path(self) -> str:
        return str(self.data_dir)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
