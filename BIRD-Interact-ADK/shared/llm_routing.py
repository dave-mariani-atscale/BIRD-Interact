"""Per-model LiteLLM routing from a YAML file - config, not code.

Which gateway serves a model, which upstream provider OpenRouter may pick, which
environment variable holds the key: none of that belongs in Python. It lives in
config/llm_routing.yaml (or the file named by LLM_ROUTING_FILE, resolved against
the project root, so a sweep can carry its own file the way ATSCALE_INSTRUCTION_FILE
carries an instruction), and the resolved entries for the agent and the simulator
are copied into each results file's deviations block, so a run says on its face
how it was routed. The shipped default has no routes: every existing sweep is
byte-for-byte unaffected.

    routes:
      openai/gpt-4o:                       # model string exactly as the harness uses it
        api_base: https://openrouter.ai/api/v1
        api_key_env: OPENROUTER_API_KEY    # NAME of the env var, never the key
        extra_body:
          provider: {order: [OpenAI], allow_fallbacks: false}

Values are LiteLLM keyword arguments merged into every call for that model, in
both call paths (litellm.completion for the simulator, ADK's LiteLlm for the
agent). Only these keys are accepted, so a typo fails at load instead of
silently doing nothing: api_base, api_key_env, extra_body, extra_headers,
timeout. max_tokens is deliberately not routable - the agent's ceiling is
settings.system_agent_max_tokens and the simulator's is part of the benchmark
(shared/config.py explains both).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from shared.config import PROJECT_ROOT, settings

ALLOWED_KEYS = frozenset({"api_base", "api_key_env", "extra_body", "extra_headers", "timeout"})
_cache: dict[Path, dict[str, dict[str, Any]]] = {}


def routing_file(path: str | os.PathLike | None = None) -> Path:
    p = Path(path or settings.llm_routing_file)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_routes(path: str | os.PathLike | None = None) -> dict[str, dict[str, Any]]:
    """The validated `routes` mapping (model string -> raw entry). Cached per file."""
    f = routing_file(path)
    if f in _cache:
        return _cache[f]
    if not f.exists():
        raise FileNotFoundError(f"LLM routing file not found: {f} (LLM_ROUTING_FILE)")
    with open(f) as fh:
        data = yaml.safe_load(fh) or {}
    routes = data.get("routes") or {}
    if not isinstance(routes, dict):
        raise ValueError(f"{f}: 'routes' must be a mapping of model string -> kwargs")
    for model, entry in routes.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{f}: route for {model!r} must be a mapping")
        bad = set(entry) - ALLOWED_KEYS
        if bad:
            raise ValueError(f"{f}: route for {model!r} has unsupported key(s) {sorted(bad)}; "
                             f"allowed: {sorted(ALLOWED_KEYS)}")
    _cache[f] = routes
    return routes


def route_for(model_name: str, path: str | os.PathLike | None = None) -> dict[str, Any]:
    """The raw entry for a model (api_key_env by NAME) - safe to record in a results file."""
    return dict(load_routes(path).get(model_name or "", {}))


def route_kwargs(model_name: str, path: str | os.PathLike | None = None) -> dict[str, Any]:
    """The entry resolved into LiteLLM kwargs: api_key_env -> api_key from the environment."""
    entry = route_for(model_name, path)
    if not entry:
        return {}
    kw = {k: v for k, v in entry.items() if k != "api_key_env"}
    env = entry.get("api_key_env")
    if env:
        key = os.environ.get(env, "")
        if not key:
            raise RuntimeError(f"LLM route for {model_name!r} names api_key_env={env!r}, which is not set")
        kw["api_key"] = key
    return kw
