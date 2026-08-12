# BIRD-Interact-ADK

**Google ADK-based implementation of the [BIRD-Interact](https://bird-interact.github.io/) benchmark** — an interactive text-to-SQL evaluation framework with dynamic agent-environment interactions.

This is the official ADK agent implementation for running BIRD-Interact evaluations. It provides a modular, service-based architecture with parallel experiment execution, supporting both **Conversational Interaction (c-Interact)** and **Agentic Interaction (a-Interact)** modes.

> For the original BIRD-Interact benchmark, paper, leaderboard, and dataset details, see the [main repository](https://github.com/bird-bench/BIRD-Interact).

## Architecture

```
orchestrator/runner.py          Parallel evaluation runner (--mode, --concurrency)
        |
        ├── system_agent (6000)     Google ADK agent with tools + callbacks
        ├── user_simulator (6001)   Two-stage function-driven user simulator
        └── db_environment (6002)   SQL execution + evaluation + per-task DB isolation
                |
                └── PostgreSQL      BIRD-Interact databases (Docker)
```

<p align="center">
  <img src="docs/architecture.png" alt="BIRD-Interact-ADK Architecture" width="80%">
</p>

**Key features:**

- **Modular microservices** — three independent services communicating via HTTP. Deploy on different machines, swap any component (bring your own agent, user simulator, or DB backend), or scale services independently.
- **Extensible & research-friendly** — each service can be developed, tested, and replaced independently. Easy to plug in a new agent scaffold, experiment with different user simulation strategies, or adapt the evaluation environment for new tasks.
- **Unified ADK agent** — both c-interact and a-interact use the same `LlmAgent` with different tools and callbacks
- **Parallel execution** — `asyncio.Semaphore` + per-task DB copies for lock-free concurrency
- **Multi-provider LLM** — supports any [LiteLlm-compatible provider](https://docs.litellm.ai/docs/providers) (Anthropic, OpenAI, Ollama, etc.)
- **Per-task DB isolation** — each task gets its own database copy; SELECT-only enforcement for execute; Phase 1 snapshots for Phase 2
- **Budget system** — bird-coin tool costs (a-interact) and clarification turn limits (c-interact), both calculated per task from ambiguity count + patience
- **Phase control (c-interact)** — two-phase evaluation (P1 + follow-up P2), with one debug retry per phase

## Quick Start

### 1. Prerequisites

- Python 3.10+
- Docker (for PostgreSQL databases)

### 2. Set up PostgreSQL

If you already have the BIRD-Interact PostgreSQL container running (from the [original setup](https://github.com/bird-bench/BIRD-Interact)), you can reuse it directly — just ensure it's accessible on the configured port.

Otherwise, start the database:

```bash
docker compose up -d postgresql          # lite (18 DBs, 300 tasks)
docker compose up -d --profile full       # full (26 DBs, 600 tasks)
```

Wait for initialization to complete:

```bash
docker compose logs -f postgresql
# Look for: "database system is ready to accept connections"
```

### 3. Install dependencies

```bash
conda create -p ./.venv python=3.10 -y
source activate ./.venv
pip install -r requirements.txt
```

### 4. Configure

```bash
cp .env.example .env
# Edit .env with your settings:
#   - ANTHROPIC_API_KEY (or OPENAI_API_KEY for OpenAI models)
#   - SYSTEM_AGENT_MODEL / USER_SIM_MODEL
#   - DATASET: "lite" or "full"
```

### 5. Start services

```bash
bash scripts/start_services.sh
```

### 6. Run evaluation

```bash
# a-interact (agent mode) — 300 tasks, concurrency 3
python -m orchestrator.runner --mode a-interact --concurrency 3

# c-interact (conversational mode) — 300 tasks, concurrency 5
python -m orchestrator.runner --mode c-interact --concurrency 5

# Oracle test (ground-truth SQL, validates pipeline)
python -m orchestrator.runner --mode oracle --concurrency 5

# Specific tasks
python -m orchestrator.runner --mode a-interact --limit 10

# Full dataset
DATASET=full python -m orchestrator.runner --mode a-interact --concurrency 3

# One database, and a named semantic-layer backend from
# config/environment_backends.yaml instead of raw Postgres. --backend is pushed
# to the already-running services via /set_backend, so switching arms between
# runs needs no restart.
python -m orchestrator.runner --mode a-interact \
    --databases cybermarket_pattern --backend atscale

# Repeat the whole evaluation N times, one timestamped file per repetition
# (..._run01_<ts>.json, _run02_, ...). Agent variance moves a single run's
# average reward by up to ~0.10, so a before/after judgement needs N>=3 per arm.
python -m orchestrator.runner --mode a-interact --repeat 3 \
    --databases cybermarket_pattern --backend atscale \
    --output results/eval_cybermarket_pattern_atscale.json
```

`--repeat` is sequential on purpose. Two concurrent runs of the same database
collide on the per-task scratch DB (`create_task_db` names it
`{db}__{task_id}` with no run id, and force-drops it), and `/set_backend` is
global to the shared services, so parallel runs on different backends would
fight over one setting. Use `--concurrency` for parallelism *within* a run.

### 7. View results

```bash
# Generate HTML report. Every run writes its own timestamped file
# (results/eval_a_interact_YYYYMMDD_HHMMSS.json) so runs stay
# comparable instead of overwriting each other -- the runner logs the
# exact path it wrote. Newest first:
ls -t results/*.json | head
python -m orchestrator.report results/eval_a_interact_YYYYMMDD_HHMMSS.json

# Run test harness (validates endpoints without LLM calls)
python -m orchestrator.test_harness --concurrency 5
```

Summarise across runs — per-arm scores with their spread, lift, and which tasks
actually moved:

```bash
# Every database, every run it finds
python scripts/summarize_runs.py

# One database, and only the 3 most recent runs OF EACH ARM -- so a --repeat 3
# comparison is a clean 3-vs-3 however the two arms were interleaved
python scripts/summarize_runs.py --database cybermarket_pattern --lastn 3
```

It reports the runs found, the headline per-arm numbers, a like-for-like table,
per-task stability (always / never / flaky), and where the arms differ. Two
things it does deliberately:

- **Headline and like-for-like are kept apart.** The `raw` arm also runs the
  Management tasks (DDL/DML) that a read-only semantic-layer backend filters
  out, and scores differently on them — so headline numbers are *not* comparable
  across arms. Lift is computed only over the query tasks both arms attempted.
- **Spread is printed next to lift**, with the reminder that a lift smaller than
  roughly twice the largest single-arm standard deviation isn't distinguishable
  from variance.

The always/never/flaky breakdown is usually the most informative part: a task
that flips between runs can't support a conclusion in either direction.

### 8. Token and cost accounting

Every LLM call is logged with its tokens and dollar cost, so a run's score always
comes with what it cost to produce. Each run's results JSON gains an `llm_usage`
block and the runner prints a summary when it finishes:

```
LLM usage: 17 calls, $0.1306, in=179550 out=5702 cache_read=157166
  system_agent: 15 calls, $0.1206, in=172021 out=5206
  user_sim: 2 calls, $0.0100, in=7529 out=496
```

Spend splits by **role** (which service made the call) and by **model**, so a
model change or a prompt change shows up as a number rather than a guess. Roles
come from `BIRD_LLM_ROLE`, set per service in `scripts/start_services.sh` — model
name alone can't separate them once two roles share a model.

Raw rows land in `results/llm_usage.jsonl` (append-only, one JSON row per call);
set `LLM_USAGE_PATH=` empty to disable. Runs are attributed to their own time
window, which is sound because runs are sequential (see `--repeat` above).

`cache_read_tokens` reports prompt-cache hits, and is how you confirm caching is
still working — see below.

> Services register the accounting hook at import time. Restart them after
> changing `shared/usage.py` or `shared/llm.py`, or the run logs nothing and the
> runner warns that it found no rows.

### 9. Prompt caching

Input tokens dominate spend in agentic runs: the whole conversation, plus a fixed
instruction and tool block, is re-sent on every turn. `PROMPT_CACHING=true` (the
default) marks that prefix as reusable so repeats bill at a tenth of the input
rate. Measured on one task run both ways, identical reward and budget:
**$0.331 → $0.131**, with 87% of input tokens served from cache.

This is a billing change, not a protocol deviation. `cache_control` is metadata
about which prefix to reuse — it is not prompt content, so the agent receives the
same bytes and the score is unaffected.

`shared.llm.cache_breakpoints` places three of Anthropic's four allowed
breakpoints: one on the system message (which also covers the tool definitions,
since Anthropic orders the prefix tools → system → messages) and a rolling pair
at message indices `-1` and `-3`, so each turn's write is read back by the next.
Applied to the system agent only, and only for Anthropic-family models — the user
simulator is ~4% of spend and builds a fresh single-message prompt each call, so
it has no reusable prefix to cache.

Because the breakpoints are position-based, anything that reshapes the message
list can silently stop them landing. `cache_read_tokens` reading 0 on a
multi-turn run means caching broke, whatever the config says.

## LLM Configuration

LLM calls use [LiteLlm](https://docs.litellm.ai/docs/providers), which supports 100+ providers. Set the API key and model name in `.env`:

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
SYSTEM_AGENT_MODEL=anthropic/claude-sonnet-4-20250514
USER_SIM_MODEL=anthropic/claude-haiku-4-5-20251001

# OpenAI
# OPENAI_API_KEY=sk-...
# SYSTEM_AGENT_MODEL=openai/gpt-4o
# USER_SIM_MODEL=openai/gpt-4o-mini

# Ollama (local)
# SYSTEM_AGENT_MODEL=ollama_chat/llama3:instruct
```

See [LiteLlm providers](https://docs.litellm.ai/docs/providers) for the full list.

## Dataset


| Version  | Tasks | Databases | PostgreSQL Image                                | HuggingFace                                                                      |
| -------- | ----- | --------- | ----------------------------------------------- | -------------------------------------------------------------------------------- |
| **Lite** | 300   | 18        | `shawnxxh/bird-interact-postgresql:latest`      | [bird-interact-lite](https://huggingface.co/datasets/birdsql/bird-interact-lite) |
| **Full** | 600   | 26        | `shawnxxh/bird-interact-postgresql-full:latest` | [bird-interact-full](https://huggingface.co/datasets/birdsql/bird-interact-full) |


### Download & Setup

1. Download the dataset from HuggingFace and place it in the repo root:
  ```bash
   # Lite
   git clone https://huggingface.co/datasets/birdsql/bird-interact-lite bird-interact-lite
   # Full
   git clone https://huggingface.co/datasets/birdsql/bird-interact-full bird-interact-full
  ```
2. **Ground Truth & Test Cases**: The public dataset does not include `sol_sql` and `test_cases` fields. To obtain them, email [bird.bench25@gmail.com](mailto:bird.bench25@gmail.com) with the tag `[bird-interact-lite GT&Test Cases]` or `[bird-interact-full GT&Test Cases]` in the subject. You will receive the GT file automatically.
3. Combine public data with GT:
  ```bash
   python scripts/combine_public_with_gt.py \
     bird-interact-lite/bird_interact_data.jsonl \
     /path/to/bird_interact_gt_kg_testcases.jsonl \
     bird-interact-lite/bird_interact_data.jsonl
  ```

Each dataset directory contains:

- `bird_interact_data.jsonl` — task definitions
- `{db_name}/` — per-database schema, column meanings, external knowledge

Set `DATASET=lite` or `DATASET=full` in `.env`.

## Project Structure

```
.
├── system_agent/           # ADK agent service (port 6000)
│   ├── agent.py            # Agent builder (c-interact / a-interact)
│   ├── server.py           # FastAPI endpoints
│   ├── adk_runtime.py      # ADK session management
│   ├── callbacks.py        # a-interact: budget, turn limits
│   ├── callbacks_cinteract.py  # c-interact: phase enforcement
│   └── tools.py            # 9 ADK tools
├── db_environment/         # DB service (port 6002)
│   └── server.py           # SQL execution, evaluation, per-task DB
├── user_simulator/         # User sim service (port 6001)
│   ├── server.py           # Two-stage simulator (action parser + response generator)
│   ├── prompts.py          # Prompt templates
│   └── sql_parser.py       # SQL segmentation
├── shared/                 # Shared utilities
│   ├── config.py           # Centralized settings
│   ├── llm.py              # LLM provider (LiteLlm)
│   ├── db_utils.py         # PostgreSQL pooling & evaluation
│   └── models.py           # Pydantic models
├── orchestrator/           # Evaluation runners
│   ├── runner.py           # Parallel runner (--mode, --concurrency, --backend,
│   │                       #   --databases, --repeat)
│   ├── cinteract.py        # c-interact pipeline
│   ├── ainteract.py        # a-interact pipeline
│   ├── report.py           # HTML report generator
│   └── test_harness.py     # Endpoint validation (no LLM)
├── bird-interact-lite/     # Lite dataset (300 tasks)
├── bird-interact-full/     # Full dataset (600 tasks)
├── config/
│   └── environment_backends.yaml  # Named semantic-layer backends (--backend)
├── docker-compose.yml      # PostgreSQL containers
├── scripts/                # Service startup + eval scripts
│   ├── start_services.sh   # Launch the three services
│   ├── run_eval.sh         # Wrapper: starts services if needed, then the runner
│   └── summarize_runs.py   # Cross-run summary: per-arm scores, spread, lift
├── .env.example            # Configuration template
└── requirements.txt
```

## Evaluation Modes

### a-interact (Agentic Interaction)

The agent autonomously decides which tools to use within a budget. Tools: `execute_sql`, `get_schema`, `get_column_meaning`, `get_knowledge_definition`, `ask_user`, `submit_sql`, etc.

Budget formula: `6 + 2 * num_ambiguities + 2 * patience`

### c-interact (Conversational Interaction)

Fixed workflow driven by the orchestrator:

1. **Phase 1**: Clarify (ask_user × N) → Submit SQL (once) → Debug if wrong (once)
2. **Phase 2**: Follow-up question → Submit SQL (once) → Debug if wrong (once)

## Results

Evaluated on BIRD-Interact-Lite (300 tasks), Claude Sonnet 4.5, patience=3, v1 user simulator prompt (claude-haiku-4-5):


| Mode                       | P1 (%) | P2 (%) | Avg Reward |
| -------------------------- | ------ | ------ | ---------- |
| **c-interact (ADK)**       | 44.67  | 30.67  | 0.395      |
| **c-interact (reference)** | 40.47  | 27.09  | —          |
| **a-interact (ADK)**       | 36.67  | 23.67  | 0.328      |
| **a-interact (reference)** | 37.67  | 22.00  | —          |


## License

MIT License. See [LICENSE](LICENSE).

## Citation

```bibtex
@inproceedings{
huo2026birdinteract,
title={{BIRD}-{INTERACT}: Re-imagining Text-to-{SQL} Evaluation via Lens of Dynamic Interactions},
author={Nan Huo and Xiaohan Xu and Jinyang Li and Per Jacobsson and Shipei Lin and Bowen Qin and Binyuan Hui and Xiaolong Li and Ge Qu and Shuzheng Si and Linheng Han and Edward Alexander and Xintong Zhu and Rui Qin and Ruihan Yu and Yiyao Jin and Feige Zhou and Weihao Zhong and Yun Chen and Hongyu Liu and Chenhao Ma and Fatma Ozcan and Yannis Papakonstantinou and Reynold Cheng},
booktitle={The Fourteenth International Conference on Learning Representations},
year={2026},
url={https://openreview.net/forum?id=nHrYBGujps}
}
```

## Acknowledgement

BIRD Team & Google Cloud. Built with [Google ADK](https://google.github.io/adk-docs/).