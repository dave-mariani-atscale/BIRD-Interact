"""Bearer tokens for the Databricks backends, resolved from an environment variable.

Scenario 1 (dbx_metric_views) runs as the workspace owner (DATABRICKS_TOKEN, a PAT).
Scenario 2 (dbx_genie_ontology) must run as a principal that can SELECT the base
tables of `bird_interact` but has no privilege on the metric views, so Genie cannot
draw on them; its config block names that principal's token variable (`token_env`).

The variable holds either
  - a static bearer token (a PAT, `dapi...`), used as is, or
  - `oauth-m2m:<client_id>:<client_secret>` — a service principal's OAuth
    credentials, exchanged for a one-hour access token at <host>/oidc/v1/token
    (client_credentials, scope all-apis) and refreshed five minutes before expiry.
    This is the form the benchmark principal uses: the workspace refuses
    on-behalf-of PATs for service principals, so an OAuth secret is its only
    credential (docs/databricks-metric-views-backend.md, scenario 2).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, Optional, Tuple

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

_OAUTH_PREFIX = "oauth-m2m:"
_REFRESH_MARGIN_S = 300.0
_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}   # (host, client_id) -> (token, expires_at)
_lock = threading.Lock()


def resolve_token(env_name: Optional[str], host: Optional[str] = None) -> str:
    """The bearer token the variable `env_name` designates (see module doc). An
    empty or unset `env_name` means the default DATABRICKS_TOKEN."""
    if not env_name:
        return settings.databricks_token
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise RuntimeError(f"{env_name} is not set in the environment (.env)")
    if not value.startswith(_OAUTH_PREFIX):
        return value
    try:
        _, client_id, client_secret = value.split(":", 2)
    except ValueError:
        raise RuntimeError(f"{env_name} must be 'oauth-m2m:<client_id>:<client_secret>'") from None
    return _oauth_m2m_token((host or settings.databricks_host).rstrip("/"), client_id, client_secret)


def _oauth_m2m_token(host: str, client_id: str, client_secret: str) -> str:
    key = (host, client_id)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[1] - time.time() > _REFRESH_MARGIN_S:
            return cached[0]
        with httpx.Client(timeout=60.0, trust_env=False) as c:
            r = c.post(f"{host}/oidc/v1/token", auth=(client_id, client_secret),
                       data={"grant_type": "client_credentials", "scope": "all-apis"})
        if r.status_code >= 400:
            raise RuntimeError(f"OAuth token exchange for {client_id} failed: HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        token = d["access_token"]
        _cache[key] = (token, time.time() + float(d.get("expires_in", 3600)))
        logger.info("databricks_auth: minted an OAuth access token for principal %s (expires in %ss)",
                    client_id, d.get("expires_in"))
        return token
