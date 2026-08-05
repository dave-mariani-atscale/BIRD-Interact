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

    # What a failed submit_sql tells the agent.
    #   "none"  - "Your SQL is not correct." and nothing else. Upstream
    #             BIRD-Interact's protocol: the 3-coin charge IS the penalty for
    #             guessing, so this is the default and the only setting whose
    #             scores are comparable to published BIRD-Interact numbers.
    #   "shape" - adds row/column counts and whether the rows match but the
    #             order doesn't. Never reveals a value, a column name or a row.
    # Applies to BOTH backends (raw and semantic-layer) — they share
    # _compare_rows — so a run's level is recorded in the results JSON to keep
    # scores self-describing.
    submit_feedback_level: str = "none"

    # ── Deviations from upstream BIRD-Interact's protocol ──
    # Each defaults to upstream behaviour, so a clean checkout reproduces
    # published numbers. Turning any of them on makes a run non-comparable, so
    # all four are recorded in the results JSON next to submit_feedback_level.
    # Verified against the reference implementation checked out beside this repo
    # (bird_interact_agent/, evaluation/) on 2026-08-04 — see the tracker's
    # B-06, B-09 and B-10.

    # GRADING. Upstream compares ordered results with a bare
    # `predicted_res == ground_res` (test_case_utils/test_utils.py). When gold's
    # ORDER BY key has duplicate values, the order within a tied block is
    # arbitrary and the two sources legitimately disagree. True forgives a
    # permutation confined to ties; False keeps upstream's strict compare.
    grading_tie_tolerance: bool = False

    # GRADING. Upstream never reads conditions["decimal"] — it always rounds to
    # 2 (preprocess_results' default). True honours each task's declared
    # precision, which differs from upstream on the 125 of 600 tasks that
    # declare `decimal >= 0 and != 2`. Note -1 means "unspecified" and resolves
    # to 2 either way, so 377 tasks are unaffected by this flag.
    grading_honor_decimal: bool = False

    # GRADING (semantic-layer path only). Gold SQL often wraps a text column in
    # LOWER(...) the agent cannot see, while a semantic layer returns its stored
    # display casing ("Bifacial" vs gold's "bifacial") — a numerically-correct
    # submission can fail on casing alone. True case-folds string cells in
    # canonical_cell; False compares them as-is. No effect on the raw path,
    # which never passes a `cell` hook to _compare_rows.
    grading_casefold: bool = False

    # BUDGET (a-interact only). Upstream's update_budget deducts a cost by
    # action TYPE and never inspects the outcome, so a duplicate submit and a
    # bundled question both cost full price. True refuses those two at no charge
    # instead; False charges for them as upstream does.
    free_wasted_actions: bool = False

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
