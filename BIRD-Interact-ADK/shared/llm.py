"""Unified LLM call interface.

Release: uses LiteLlm (supports any provider).
Local override: place _local_provider.py in this directory (gitignored)
to use a custom backend.
"""

import logging

from shared.config import settings
from shared import usage as _usage

logger = logging.getLogger(__name__)

MAX_RETRIES = 5

# Token/cost accounting. Registered before the provider is chosen so it covers
# both LLM paths from one place — call_llm below and ADK's LiteLlm wrapper — and
# so a local _local_provider override still gets it, as long as that override
# also goes through litellm. No-ops when settings.llm_usage_path is empty.
_usage.install()


def cache_breakpoints(model_name: str):
    """Anthropic prompt-caching breakpoints for a multi-turn agent, or [].

    Returned as litellm `cache_control_injection_points`; litellm's
    AnthropicCacheControlHook consumes the param and stamps cache_control onto
    the named messages before the provider transform, so nothing here reaches
    the wire as-is.

    Three of Anthropic's four allowed breakpoints:

      system   the instruction, and with it the tool definitions — Anthropic
               orders the prefix tools, system, messages, so a breakpoint on
               system covers both. Identical on every turn of every task, and
               the single largest fixed block we re-send.
      -1, -3   a rolling pair over the conversation. -1 writes the whole
               history as a cache entry at the end of this turn; next turn that
               same position has slid back to about -3, where the second
               breakpoint scores the hit. One rolling breakpoint would write a
               cache nothing ever reads.

    A fourth is left free deliberately: a request carrying more than four is
    rejected outright, and litellm counts any breakpoint already on a message
    toward the limit.
    """
    if not settings.prompt_caching:
        return []
    # Bedrock/Vertex Claude route through litellm under other prefixes, so match
    # the family rather than the "anthropic/" provider. Non-Claude providers
    # error on an unexpected cache_control key instead of ignoring it.
    if "claude" not in model_name.lower() and "anthropic" not in model_name.lower():
        return []
    return [
        {"location": "message", "role": "system"},
        {"location": "message", "index": -1},
        {"location": "message", "index": -3},
    ]


# Try local override first (gitignored, not in release)
try:
    from shared._local_provider import call_llm, build_adk_model
except ImportError:
    # Default: LiteLlm
    import litellm

    # Some models (e.g. claude-sonnet-5) reject sampling params like
    # temperature/top_p entirely rather than accepting arbitrary values.
    # Drop unsupported params instead of erroring, per LiteLLM's own guidance.
    litellm.drop_params = True

    def call_llm(messages: list, model_name: str = None, temperature: float = 0, max_tokens: int = 1024) -> str:
        """Call LLM via LiteLlm. Retries on rate limit / transient errors."""
        import litellm
        model_name = model_name or settings.system_agent_model
        kwargs = dict(
            model=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            num_retries=MAX_RETRIES,
        )
        if settings.litellm_api_base:
            kwargs["api_base"] = settings.litellm_api_base
        if settings.litellm_api_key:
            kwargs["api_key"] = settings.litellm_api_key

        resp = litellm.completion(**kwargs)
        return resp.choices[0].message.content.strip()

    def build_adk_model(model_name: str = None):
        """Build ADK-compatible model via LiteLlm with retry config."""
        from google.adk.models.lite_llm import LiteLlm
        model_name = model_name or settings.system_agent_model
        kwargs = dict(
            model=model_name,
            max_tokens=settings.system_agent_max_tokens,
            num_retries=MAX_RETRIES,
        )
        if settings.litellm_api_base:
            kwargs["api_base"] = settings.litellm_api_base
        if settings.litellm_api_key:
            kwargs["api_key"] = settings.litellm_api_key
        points = cache_breakpoints(model_name)
        if points:
            # ADK forwards unrecognised LiteLlm kwargs straight to litellm's
            # completion call, which is where the hook that consumes this lives.
            kwargs["cache_control_injection_points"] = points
        return LiteLlm(**kwargs)
