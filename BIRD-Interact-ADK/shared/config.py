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
    #
    # Only meaningful where the sort key can be inferred from gold's result.
    # Where it cannot, db_utils._sort_key_indices returns None and nothing is
    # forgiven (B-22) — grading_order_lint covers those phases instead.
    grading_tie_tolerance: bool = False

    # GRADING. Grade row order only where gold determines one. Measured over all
    # 22 databases by replanning gold (scripts/bird_order_lint.py): 68 of 438
    # order-sensitive phases carry `order: true` over a gold whose own ORDER BY
    # leaves the order to the plan. True compares those as multisets; False
    # keeps upstream's row-by-row compare. See db_utils.apply_order_lint.
    grading_order_lint: bool = False
    # The list the flag above consumes. Regenerate with
    #   python scripts/bird_order_lint.py --write config/order_undetermined.json <all 22 dbs>
    # An unreadable file degrades to upstream behaviour with a warning, never
    # to silently forgiving more.
    grading_order_lint_path: str = "config/order_undetermined.json"

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

    # GRADING. Upstream compares numerics only after rounding to a fixed
    # precision, with no tolerance. True adds a relative-tolerance retry on the
    # RAW pre-rounding rows, applied only after the exact comparison has already
    # failed — so it can turn a 0 into a 1 and never the reverse. It exists for
    # gold SQL that casts an operand to ::real (float32), which shifts an
    # otherwise-correct answer by ~1 part in 7.6e8; rounding cannot fix that,
    # because two values either side of a decimal boundary round apart. See
    # db_utils._rows_close. False keeps upstream's exact compare.
    grading_rel_tolerance: bool = False
    # The relative gap tolerated when the flag above is on. Read by
    # db_utils._values_close; until 2026-08-11 that function hardcoded 1e-6 and
    # this field was declared but never read, so the knob was inert (B-20).
    #
    # 1e-6 is ~700x looser than the float32 artefact it was chosen for, but it
    # is NOT loose enough for every real artefact: archeology_scan_7 asks for a
    # composite index summed over per-site groups, where float64 accumulation
    # order alone puts the two engines up to 1.13e-5 apart on the worst of 3298
    # cells (median 2.8e-8, p99 1.6e-6). That task needs >=1.5e-5. Raising this
    # to 2e-5 rescues it and nothing else — swept over the whole 0811 audit,
    # every value from 1e-6 to 1e-2 rescues exactly the same one submission —
    # but it is a real loosening, so it stays a deliberate choice rather than
    # the default.
    #
    # Re-measured 2026-08-14 over all 930 audited submissions, and the answer is
    # now a firm no: 2e-5 adds exactly one phase over 1e-6 — crypto_exchange_4
    # phase 2, on the RAW arm — and it works by absorbing gold's own
    # float4->numeric truncation to 6 significant digits (defect C2), not
    # cross-engine noise. At 2e-5 the forgiven gap on a 7-digit value is larger
    # than one unit at the precision the task is graded to, which is the line
    # that makes a tolerance defensible at all: it must stay below the graded
    # precision, or it stops distinguishing a representation artefact from a
    # different answer.
    grading_rel_tolerance_value: float = 1e-6

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
    # convertible back to upstream's regime (scripts/score_dual.py) — which is
    # only possible if the rows were kept. Costs a few MB per run and changes
    # no verdict.
    grading_audit_path: str = "results/grading_audit.jsonl"

    # BUDGET (a-interact only). Upstream's update_budget deducts a cost by
    # action TYPE and never inspects the outcome, so a duplicate submit and a
    # bundled question both cost full price. True refuses those two at no charge
    # instead; False charges for them as upstream does.
    free_wasted_actions: bool = False

    # CAPABILITY (semantic-layer backends only). The raw backend gets three
    # tools over the task's external_knowledge — the benchmark's glossary of
    # domain terms — while the semantic-layer backends get none:
    # system_agent/tools_atscale.py maps get_all_knowledge_definitions to
    # get_sml_skills, which returns query-construction guidance, not
    # definitions. Measured on the 19-task 0806/0810 ETF pair, the raw arm
    # spent 80.5 coins there (4.24 per task of an 18-coin budget) and the
    # semantic-layer arm 0, because it had no route to the same content. True
    # gives the semantic-layer backends the same three tools at the same
    # prices; False keeps them raw-only. Masked entries are unaffected either
    # way — db_environment/server.py's _filter_knowledge strips every id named
    # in knowledge_ambiguity.deleted_knowledge before the endpoints answer, so
    # the entries the agent is meant to ask the user about stay hidden.
    #
    # Whether this SHOULD be on is a scope question, not a bug: if a semantic
    # model is meant to replace the glossary, off is right and the handicap is
    # the point. If the comparison is meant to hold knowledge constant while
    # varying the schema layer, off understates the model. Recorded per run in
    # the results JSON either way. See tracker B-12.
    semantic_layer_knowledge_tools: bool = False

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
