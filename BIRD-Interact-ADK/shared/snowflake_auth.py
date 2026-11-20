"""Credentials for the Snowflake backends, resolved from an environment variable.

Every Snowflake scenario runs as its own role (`role` in the backend's config block)
with that role's programmatic access token (PAT), named by `token_env`. The variable
holds either the token itself or `file:<path>` (`~` expanded), so a token can stay in
a 0600 file outside `.env` and outside any log. A PAT is restricted to one role on
this account, so the role and the token must belong together; the preflight of
scripts/run_snowflake_scenario.sh checks CURRENT_ROLE() before a run.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

_FILE_PREFIX = "file:"
_cache: Dict[str, str] = {}


def resolve_token(env_name: Optional[str]) -> str:
    """The bearer token the variable `env_name` designates (see module doc)."""
    name = env_name or "SNOWFLAKE_TOKEN"
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set in the environment (.env)")
    if not value.startswith(_FILE_PREFIX):
        return value
    path = Path(value[len(_FILE_PREFIX):].strip()).expanduser()
    key = str(path)
    if key not in _cache:
        try:
            token = path.read_text().strip()
        except OSError as e:
            raise RuntimeError(f"{name} points at {path}, which cannot be read: {e.strerror}") from None
        if not token:
            raise RuntimeError(f"{name} points at {path}, which is empty")
        _cache[key] = token
    return _cache[key]


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN"}
