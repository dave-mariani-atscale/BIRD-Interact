"""Per-call LLM token/cost accounting.

Why this exists: the three services are separate long-lived processes, and the
only cost signal a run produced was bird-coins — a benchmark budget, not money.
There was no way to tell whether a run's API spend went to the system agent or
the user simulator, or how much of it was history re-sent on every turn. That
made "cut costs" a guess, and the cheapest lever (prompt caching, which is not
enabled anywhere yet) invisible.

Design: one JSONL row per LLM call, appended by whichever process made it, and
aggregated by the orchestrator into each run's results JSON. A litellm logging
callback is the hook, because both LLM paths funnel through litellm — the
direct one (shared.llm.call_llm, used by the user simulator) and ADK's LiteLlm
wrapper (used by the system agent) — so one registration covers both without
touching either call site.

Attribution:
  role   comes from BIRD_LLM_ROLE, set per service in scripts/start_services.sh.
  model  is always recorded, so rows stay attributable even when the env var is
         missing -- unless both roles run the same model, which is exactly the
         Haiku-everywhere case, hence the env var.
  to a run: by timestamp window (see aggregate()).

Rows are appended, never rewritten, and a failure here is always swallowed:
accounting must not be able to break a run.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.config import settings

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()
_installed = False

# Rows are short (<500 bytes), so a single append write from each of the three
# processes is atomic in practice on POSIX and they can share one file without
# coordination. The lock below only covers threads inside one process (uvicorn).
_UNKNOWN_ROLE = "unknown"


def _role() -> str:
    return os.environ.get("BIRD_LLM_ROLE") or _UNKNOWN_ROLE


def _usage_path() -> str:
    return settings.llm_usage_path


def _record(row: Dict[str, Any]) -> None:
    path = _usage_path()
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, default=str) + "\n"
        with _write_lock:
            with open(path, "a") as f:
                f.write(line)
    except Exception as exc:  # never let accounting break a run
        logger.debug("usage accounting write failed: %s", exc)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cache_tokens(usage: Any) -> tuple[int, int]:
    """(cache_read, cache_write) from a litellm Usage object.

    litellm exposes Anthropic's cache counters under several names depending on
    version and provider, so try each. These read 0 until prompt caching is
    actually enabled -- which makes them the check for whether a caching change
    landed, rather than dead fields.
    """
    if usage is None:
        return 0, 0
    read = (
        getattr(usage, "cache_read_input_tokens", None)
        or getattr(usage, "_cache_read_input_tokens", None)
        or getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
    )
    write = (
        getattr(usage, "cache_creation_input_tokens", None)
        or getattr(usage, "_cache_creation_input_tokens", None)
    )
    return _int(read), _int(write)


def _row_from_call(kwargs: Dict[str, Any], response_obj: Any) -> Dict[str, Any]:
    slo = kwargs.get("standard_logging_object") or {}
    usage = getattr(response_obj, "usage", None)

    prompt_tokens = _int(slo.get("prompt_tokens") or getattr(usage, "prompt_tokens", 0))
    completion_tokens = _int(slo.get("completion_tokens") or getattr(usage, "completion_tokens", 0))
    cache_read, cache_write = _cache_tokens(usage)

    cost = slo.get("response_cost")
    if cost is None:
        # Older/newer payload shapes may not carry it; litellm can price the
        # response object directly from its own model map.
        try:
            import litellm

            cost = litellm.completion_cost(completion_response=response_obj)
        except Exception:
            cost = None

    return {
        "ts": time.time(),
        "role": _role(),
        "model": slo.get("model") or kwargs.get("model") or "",
        "call_type": slo.get("call_type") or "",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        # Uncached input is what you pay full price for; cache reads are ~0.1x.
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "cost_usd": float(cost) if cost is not None else None,
    }


def install() -> None:
    """Register the litellm logging callback. Idempotent, and a no-op when
    llm_usage_path is empty or litellm is not the active provider."""
    global _installed
    if _installed or not _usage_path():
        return
    try:
        import litellm
        from litellm.integrations.custom_logger import CustomLogger
    except Exception as exc:
        logger.debug("usage accounting unavailable (no litellm): %s", exc)
        return

    class _UsageLogger(CustomLogger):
        # Both hooks are needed: the user simulator calls litellm.completion
        # (sync) and ADK's LiteLlm calls litellm.acompletion (async).
        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            _record(_row_from_call(kwargs, response_obj))

        async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
            _record(_row_from_call(kwargs, response_obj))

    litellm.callbacks.append(_UsageLogger())
    _installed = True
    logger.info("LLM usage accounting -> %s (role=%s)", _usage_path(), _role())


def read_rows(since: Optional[float] = None, path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = path or _usage_path()
    if not path or not os.path.isfile(path):
        return []
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # torn line from a concurrent append
                if since is not None and float(row.get("ts", 0)) < since:
                    continue
                rows.append(row)
    except Exception as exc:
        logger.debug("usage accounting read failed: %s", exc)
    return rows


def _blank() -> Dict[str, Any]:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.0}


def _add(acc: Dict[str, Any], row: Dict[str, Any]) -> None:
    acc["calls"] += 1
    for k in ("prompt_tokens", "completion_tokens", "cache_read_tokens", "cache_write_tokens"):
        acc[k] += _int(row.get(k))
    acc["cost_usd"] += float(row.get("cost_usd") or 0.0)


def aggregate(since: Optional[float] = None, path: Optional[str] = None) -> Dict[str, Any]:
    """Totals for calls logged at or after `since` (a time.time() value).

    Runs are attributed by time window rather than by a run id, because the
    services are long-lived and know nothing about the orchestrator's run. That
    is sound only because runs are sequential -- --repeat is sequential by
    design, and two concurrent runs would already collide on the per-task
    scratch DB. A second run started in another terminal WOULD be double
    counted here; the raw rows in the JSONL remain the source of truth.
    """
    rows = read_rows(since=since, path=path)
    total = _blank()
    by_role: Dict[str, Dict[str, Any]] = {}
    by_model: Dict[str, Dict[str, Any]] = {}
    priced = 0
    for row in rows:
        _add(total, row)
        _add(by_role.setdefault(row.get("role") or _UNKNOWN_ROLE, _blank()), row)
        _add(by_model.setdefault(row.get("model") or "", _blank()), row)
        if row.get("cost_usd") is not None:
            priced += 1
    for acc in [total, *by_role.values(), *by_model.values()]:
        acc["cost_usd"] = round(acc["cost_usd"], 6)
    return {
        "calls": total["calls"],
        # Flagged rather than silently summed to 0: an unpriced row (model
        # missing from litellm's price map) makes cost_usd an undercount.
        "calls_missing_cost": total["calls"] - priced,
        "total": total,
        "by_role": by_role,
        "by_model": by_model,
        "source": path or _usage_path(),
    }


def format_summary(agg: Dict[str, Any]) -> str:
    t = agg.get("total") or {}
    parts = [
        f"LLM usage: {agg.get('calls', 0)} calls, "
        f"${t.get('cost_usd', 0):.4f}, "
        f"in={t.get('prompt_tokens', 0)} out={t.get('completion_tokens', 0)} "
        f"cache_read={t.get('cache_read_tokens', 0)}"
    ]
    for role, acc in sorted((agg.get("by_role") or {}).items()):
        parts.append(f"  {role}: {acc['calls']} calls, ${acc['cost_usd']:.4f}, "
                     f"in={acc['prompt_tokens']} out={acc['completion_tokens']}")
    if agg.get("calls_missing_cost"):
        parts.append(f"  ({agg['calls_missing_cost']} call(s) had no price -> cost is an undercount)")
    return "\n".join(parts)
