"""Centralized configuration.

Settings are loaded in this priority (highest wins):
  1. Environment variables (e.g. PATIENCE=6 python -m orchestrator.runner ...)
  2. .env file in project root (user-specific, gitignored)
  3. Defaults defined below

Users: copy .env.example to .env and edit.
See .env.example for all available settings.
"""

from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env into os.environ so litellm/openai can read OPENAI_API_KEY etc.
load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parent.parent


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

    # ── Deviation from upstream BIRD-Interact's protocol ──
    # One remains, and it defaults ON. It is recorded in the results JSON so a
    # score stays self-describing. The opt-in grading tolerances that used to
    # live here (tie permutations, case folding, per-task decimal places, a
    # relative numeric tolerance, an order lint) were removed on 2026-09-04:
    # every one stayed off for every scored run, so the code behind them had
    # never graded anything, and upstream's behaviour is what off already did.
    # Verified against the reference implementation checked out beside this repo
    # (bird_interact_agent/, evaluation/) on 2026-08-04 — see the tracker's
    # B-06, B-09 and B-10.

    # GRADING (semantic-layer path only, via canonical_cell).
    # True truncates a timestamp STRING to its date. Unlike the other flags here
    # this defaults to ON, because it removes an asymmetry rather than adding a
    # tolerance: preprocess_results already truncates a TYPED date/datetime to
    # "%Y-%m-%d", so gold reaches the comparison as '2025-02-19' while the
    # semantic layer returns the JSON string '2025-02-19 16:29:00' and can never
    # match it, whatever the answer. Six phases across five databases project a
    # date at all. Set False for a sensitivity check — but note that it makes
    # those phases unwinnable for the atscale arm rather than upstream-faithful,
    # since upstream has no cross-source path for this code to be faithful to.
    #
    # The cost of ON, stated because it is a real one: gold text that merely
    # LOOKS like a timestamp is truncated on both sides, so '... 08:00:00' and
    # '... 23:59:59' compare equal. No shipped gold projects a timestamp as text
    # today; re-check the golds if one ever does.
    grading_timestamp_date: bool = True

    # DEVIATION (both arms, symmetric). The dataset marks 218 of 410 phase-1 golds
    # order=true, and upstream then compares ordered lists - but in most of those
    # tasks the question never asks for an order ("On each platform, what's the
    # typical score?"), so the agent must guess the gold's ORDER BY to pass. With
    # this on, order=true is honoured only when the phase's question contains an
    # ordering cue (sort, order, rank, top, bottom, highest, lowest, ascending,
    # descending, largest, smallest, first, last, best, worst, most, least);
    # otherwise the rows are compared as sets, exactly as upstream does for
    # order=false. Measured on the 2026-09-04 sweep before adopting: 53 AtScale
    # and 46 raw phase-1 task-runs flip (of 1230 each), 10 and 5 at phase 2 -
    # the two arms move together, so this is a protocol correction, not a lift
    # for either side. It applies to both grading paths (ex_base and
    # ex_base_external_pred) through db_environment/server.py, and the grading
    # audit records the effective conditions it graded with.
    grading_order_requires_cue: bool = True


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

    # Shared secret matching the MCP server's ATSCALE_MCP_FEEDBACK_RATER_TOKEN.
    # The server honors privileged feedback sources (end_user_explicit) only when
    # record_feedback carries this as raterToken; without it the verdict is
    # recorded at agent_inferred weight and never certifies on its own. Empty
    # means "send no token" - fine when the server has none configured.
    feedback_rater_token: str = ""

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
