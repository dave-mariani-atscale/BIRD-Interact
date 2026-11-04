"""Databricks SQL Statement Execution API client for the Databricks backends.

One thin client, shared by the agent's tools (system_agent/tools_databricks.py) and
the grader (db_environment/server.py), so a submitted statement is executed for
grading exactly the way the agent executed it while exploring.

Rows come back TYPED from the manifest's column types (int, float, Decimal, bool,
date, datetime, dict for VARIANT), because the grader compares them to gold rows
that psycopg2 returns typed from Postgres: the API itself serialises every cell as
a string (JSON_ARRAY format).

Config (shared.config.settings, from .env): DATABRICKS_HOST, DATABRICKS_TOKEN,
DATABRICKS_WAREHOUSE_ID. A backend whose config block names a `token_env` runs as
that variable's principal instead (shared.databricks_auth.resolve_token); the
Genie Ontology arm uses this so neither Genie nor the grader can see the metric
views. httpx is used with trust_env=False like the rest of the
harness, so a ~/.netrc entry for the host cannot replace the bearer token.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

#: Rows the agent-facing run_query returns; grading fetches everything.
AGENT_ROW_CAP = 200
#: Hard cap on rows fetched for grading (every chunk is paged until this).
GRADING_ROW_CAP = 100_000


class DatabricksSQLError(RuntimeError):
    pass


@dataclass
class DbxResult:
    statement_id: str
    columns: List[Tuple[str, str]]          # (name, type_name)
    rows: List[tuple]
    truncated: bool = False
    total_row_count: Optional[int] = None
    error: Optional[str] = None

    def to_json_rows(self, limit: Optional[int] = None) -> str:
        """The agent-facing rendering: one JSON array of {column: value} objects,
        the same shape the AtScale MCP run_query returns, so parse_semantic_layer_rows
        and the agent's habits both keep working."""
        rows = self.rows if limit is None else self.rows[:limit]
        return json.dumps([{c: _jsonable(v) for (c, _), v in zip(self.columns, r)} for r in rows],
                          default=str)


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v) if v != v.to_integral_value() else int(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


_INT_TYPES = {"INT", "BIGINT", "SMALLINT", "TINYINT", "LONG", "SHORT", "BYTE"}
_FLOAT_TYPES = {"FLOAT", "DOUBLE"}
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def convert_cell(value: Optional[str], type_name: str) -> Any:
    """A JSON_ARRAY cell (string or None) to the Python type psycopg2 would use."""
    if value is None:
        return None
    t = (type_name or "STRING").upper()
    if t.startswith("DECIMAL"):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    if t in _INT_TYPES:
        try:
            return int(value)
        except ValueError:
            return value
    if t in _FLOAT_TYPES:
        try:
            return float(value)
        except ValueError:
            return value
    if t == "BOOLEAN":
        return value.lower() == "true"
    if t == "DATE":
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    if t.startswith("TIMESTAMP"):
        m = _TS_RE.match(value)
        if m:
            try:
                return datetime.fromisoformat(m.group(1) + "T" + m.group(2) + (m.group(3) or ""))
            except ValueError:
                return value
        return value
    if t == "VARIANT" or t.startswith("STRUCT") or t.startswith("ARRAY") or t.startswith("MAP"):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


class DatabricksSQL:
    def __init__(self, host: Optional[str] = None, token: Optional[str] = None,
                 warehouse_id: Optional[str] = None, timeout: float = 120.0):
        self.host = (host or settings.databricks_host).rstrip("/")
        self.token = token or settings.databricks_token
        self.warehouse_id = warehouse_id or settings.databricks_warehouse_id
        if not (self.host and self.token and self.warehouse_id):
            raise DatabricksSQLError("DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_WAREHOUSE_ID must be set")
        self.timeout = timeout
        self._headers = {"Authorization": f"Bearer {self.token}"}

    # ── low level ──
    def _post(self, path: str, body: dict) -> dict:
        with httpx.Client(timeout=self.timeout, trust_env=False) as c:
            r = c.post(f"{self.host}{path}", headers=self._headers, json=body)
        if r.status_code >= 400:
            raise DatabricksSQLError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def _get(self, path: str) -> dict:
        with httpx.Client(timeout=self.timeout, trust_env=False) as c:
            r = c.get(f"{self.host}{path}", headers=self._headers)
        if r.status_code >= 400:
            raise DatabricksSQLError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def execute(self, statement: str, catalog: Optional[str] = None, schema: Optional[str] = None,
                row_cap: int = GRADING_ROW_CAP, poll_timeout: float = 600.0) -> DbxResult:
        """Run one statement and return typed rows. Never raises on a SQL error:
        the error text comes back in DbxResult.error (the agent needs to read it,
        and the grader scores it as a non-executable submission)."""
        body: Dict[str, Any] = {
            "warehouse_id": self.warehouse_id, "statement": statement,
            "wait_timeout": "50s", "on_wait_timeout": "CONTINUE",
            "format": "JSON_ARRAY", "disposition": "INLINE",
        }
        if catalog:
            body["catalog"] = catalog
        if schema:
            body["schema"] = schema
        d = self._post("/api/2.0/sql/statements", body)
        sid = d.get("statement_id", "")
        started = time.time()
        while d.get("status", {}).get("state") in ("PENDING", "RUNNING"):
            if time.time() - started > poll_timeout:
                try:
                    self._post(f"/api/2.0/sql/statements/{sid}/cancel", {})
                except DatabricksSQLError:
                    pass
                return DbxResult(sid, [], [], error=f"statement timed out after {poll_timeout:.0f}s")
            time.sleep(1.5)
            d = self._get(f"/api/2.0/sql/statements/{sid}")
        state = d.get("status", {}).get("state")
        if state != "SUCCEEDED":
            msg = d.get("status", {}).get("error", {}).get("message", state or "unknown failure")
            return DbxResult(sid, [], [], error=msg)
        cols = [(c.get("name"), c.get("type_name") or c.get("type_text", "STRING"))
                for c in d.get("manifest", {}).get("schema", {}).get("columns", [])]
        total = d.get("manifest", {}).get("total_row_count")
        truncated = bool(d.get("manifest", {}).get("truncated"))
        raw: List[list] = list(d.get("result", {}).get("data_array") or [])
        nxt = d.get("result", {}).get("next_chunk_internal_link")
        while nxt and len(raw) < row_cap:
            chunk = self._get(nxt)
            raw.extend(chunk.get("data_array") or [])
            nxt = chunk.get("next_chunk_internal_link")
        if len(raw) > row_cap:
            raw = raw[:row_cap]
            truncated = True
        rows = [tuple(convert_cell(v, t) for v, (_, t) in zip(r, cols)) for r in raw]
        return DbxResult(sid, cols, rows, truncated=truncated, total_row_count=total)


# ── schema object resolution (cached per process) ──
_object_cache: Dict[Tuple[str, str, str, str], Set[str]] = {}


def schema_objects(catalog: str, schema: str, kind: str, token: Optional[str] = None) -> Set[str]:
    """Lower-cased names of the objects of `kind` ('metric_views' or 'tables') in
    catalog.schema, from information_schema, as seen by `token`'s principal (the
    default token when None). Cached for the process lifetime: the set is fixed
    for a benchmark run."""
    key = (catalog.lower(), schema.lower(), kind, token or "")
    if key not in _object_cache:
        types = {"metric_views": "('METRIC_VIEW')", "tables": "('MANAGED','EXTERNAL')",
                 "any": "('METRIC_VIEW','MANAGED','EXTERNAL','VIEW')"}[kind]
        res = DatabricksSQL(token=token).execute(
            f"SELECT table_name FROM {catalog}.information_schema.tables "
            f"WHERE table_schema = '{schema}' AND table_type IN {types}")
        if res.error:
            raise DatabricksSQLError(res.error)
        _object_cache[key] = {r[0].lower() for r in res.rows}
    return _object_cache[key]
