"""Loader for config/environment_backends.yaml — semantic-layer backend config.

See that file's header comment for the schema. `get_backend_config(name)`
returns the backend's dict (mcp_url_env/mcp_token_env/domains); the caller
resolves the actual URL/token via shared.config.settings.
"""

import os
from pathlib import Path
from typing import Any, Dict

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "environment_backends.yaml"

_cache: Dict[str, Any] = {}


def load_backends() -> Dict[str, Any]:
    if "backends" not in _cache:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _cache["backends"] = data.get("backends", {})
    return _cache["backends"]


def get_backend_config(name: str) -> Dict[str, Any]:
    backends = load_backends()
    if name not in backends:
        raise ValueError(f"Unknown environment backend '{name}' in {_CONFIG_PATH}. Available: {sorted(backends.keys())}")
    return backends[name]


def get_domain_config(backend_name: str, selected_database: str) -> Dict[str, str]:
    """Return {catalog, schema, table} for this domain under this backend, or
    None if the domain has no semantic model configured yet."""
    backend = get_backend_config(backend_name)
    return backend.get("domains", {}).get(selected_database)


def get_configured_domains(backend_name: str) -> set:
    """The set of selected_database values that have a semantic model configured
    for this backend — used to filter which tasks are eligible to run."""
    backend = get_backend_config(backend_name)
    return set(backend.get("domains", {}).keys())
