"""Snowflake SQL API (v2 statements) client for the Snowflake backends.

One thin client, shared by the grader (db_environment/server.py, `executor: snowflake`)
and the domain guard (shared/environment_backends.py), so a submitted statement is
re-executed for grading as the same role, on the same warehouse, that the Cortex agent
ran it with.

Rows come back TYPED from the result's rowType (int, Decimal, float, bool, date,
datetime, dict/list for VARIANT), because the grader compares them to gold rows that
psycopg2 returns typed from Postgres: the SQL API serialises every cell as a string
(dates as days since the epoch, timestamps as epoch seconds).

Config (shared.config.settings, from .env): SNOWFLAKE_HOST, SNOWFLAKE_WAREHOUSE. The
role and the token variable come from the backend's config block (`role`, `token_env`;
shared.snowflake_auth.resolve_token). httpx runs with trust_env=False like the rest of
the harness.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from shared.config import settings
from shared.snowflake_auth import auth_headers, resolve_token

logger = logging.getLogger(__name__)

#: Rows the agent-facing tool shows; grading fetches everything up to GRADING_ROW_CAP.
AGENT_ROW_CAP = 200
GRADING_ROW_CAP = 100_000
_EPOCH = date(1970, 1, 1)


class SnowflakeSQLError(RuntimeError):
    pass


@dataclass
class SfResult:
    statement_id: str
    columns: List[Tuple[str, str]]          # (name, type)
    rows: List[tuple]
    truncated: bool = False
    total_row_count: Optional[int] = None
    error: Optional[str] = None


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v) if v != v.to_integral_value() else int(v)
    if isinstance(v, (date, datetime, dtime)):
        return v.isoformat()
    return v


def convert_cell(value: Optional[str], col: Dict[str, Any]) -> Any:
    """A SQL API cell (string or None) to the Python type psycopg2 would use, from the
    column's rowType entry ({type, scale, ...})."""
    if value is None:
        return None
    t = (col.get("type") or "text").lower()
    try:
        if t == "fixed":
            return int(value) if not int(col.get("scale") or 0) else Decimal(value)
        if t in ("real", "float", "double"):
            return float(value)
        if t == "boolean":
            return str(value).lower() in ("true", "1")
        if t == "date":
            return _EPOCH + timedelta(days=int(value))
        if t in ("timestamp_ntz", "timestamp_ltz"):
            return datetime(1970, 1, 1) + timedelta(seconds=float(Decimal(value)))
        if t == "timestamp_tz":
            # "<epoch seconds> <offset minutes + 1440>": keep the wall-clock time of that offset.
            secs, _, off = str(value).partition(" ")
            offset = timedelta(minutes=int(off) - 1440) if off else timedelta(0)
            return (datetime(1970, 1, 1) + timedelta(seconds=float(Decimal(secs))) + offset).replace(
                tzinfo=timezone(offset))
        if t == "time":
            s = float(Decimal(value))
            return (datetime(1970, 1, 1) + timedelta(seconds=s)).time()
        if t in ("variant", "object", "array"):
            return json.loads(value)
    except (ValueError, InvalidOperation, TypeError):
        return value
    return value


class SnowflakeSQL:
    def __init__(self, role: Optional[str] = None, token: Optional[str] = None, host: Optional[str] = None,
                 warehouse: Optional[str] = None, timeout: float = 120.0):
        self.host = (host or settings.snowflake_host).rstrip("/")
        self.warehouse = warehouse or settings.snowflake_warehouse
        self.role = role
        self.token = token
        if not (self.host and self.token and self.warehouse):
            raise SnowflakeSQLError("SNOWFLAKE_HOST, SNOWFLAKE_WAREHOUSE and a token (the backend's token_env) must be set")
        self.timeout = timeout
        self._headers = {**auth_headers(self.token), "Accept": "application/json",
                         "User-Agent": "bird-interact-harness/1.0"}

    # A dropped connection, a timeout or a 429/5xx is retried with backoff (2, 4, 8, 16 s): without
    # it a network blip at grading time scores a correct submission as non-executable. A statement's
    # own SQL error arrives as HTTP 422 and is never retried.
    _RETRY_STATUS = {429, 500, 502, 503, 504}

    def _request(self, method: str, path: str, body: Optional[dict] = None, attempts: int = 5) -> Tuple[int, dict]:
        last: Optional[Exception] = None
        for i in range(attempts):
            try:
                with httpx.Client(timeout=self.timeout, trust_env=False) as c:
                    r = c.request(method, f"{self.host}{path}", headers=self._headers, json=body)
                if r.status_code in self._RETRY_STATUS and i < attempts - 1:
                    last = SnowflakeSQLError(f"HTTP {r.status_code}: {r.text[:200]}")
                else:
                    try:
                        return r.status_code, r.json()
                    except ValueError:
                        raise SnowflakeSQLError(f"HTTP {r.status_code}: {r.text[:300]}") from None
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = e
            logger.warning("snowflake %s %s failed (%s); retry %d/%d", method, path[:60], last, i + 1, attempts - 1)
            time.sleep(2 ** (i + 1))
        raise SnowflakeSQLError(f"giving up after {attempts} attempts: {last}")

    def execute(self, statement: str, database: Optional[str] = None, schema: Optional[str] = None,
                row_cap: int = GRADING_ROW_CAP, poll_timeout: float = 600.0) -> SfResult:
        """Run one statement and return typed rows. Never raises on a SQL error: the error
        text comes back in SfResult.error (the grader scores it as non-executable)."""
        body: Dict[str, Any] = {"statement": statement, "timeout": int(poll_timeout), "warehouse": self.warehouse}
        if self.role:
            body["role"] = self.role
        if database:
            body["database"] = database
        if schema:
            body["schema"] = schema
        code, d = self._request("POST", "/api/v2/statements", body)
        sid = d.get("statementHandle", "")
        started = time.time()
        while code == 202:
            if time.time() - started > poll_timeout:
                try:
                    self._request("POST", f"/api/v2/statements/{sid}/cancel", {}, attempts=1)
                except SnowflakeSQLError:
                    pass
                return SfResult(sid, [], [], error=f"statement timed out after {poll_timeout:.0f}s")
            time.sleep(1.5)
            code, d = self._request("GET", f"/api/v2/statements/{sid}")
        if code != 200:
            return SfResult(sid, [], [], error=d.get("message") or f"HTTP {code}: {json.dumps(d)[:300]}")
        meta = d.get("resultSetMetaData") or {}
        row_type = meta.get("rowType") or []
        cols = [(c.get("name"), c.get("type") or "text") for c in row_type]
        total = meta.get("numRows")
        raw: List[list] = list(d.get("data") or [])
        for p in range(1, len(meta.get("partitionInfo") or [])):
            if len(raw) >= row_cap:
                break
            pc, pd = self._request("GET", f"/api/v2/statements/{sid}?partition={p}")
            if pc != 200:
                return SfResult(sid, cols, [], error=pd.get("message") or f"HTTP {pc} fetching partition {p}")
            raw.extend(pd.get("data") or [])
        truncated = len(raw) > row_cap
        rows = [tuple(convert_cell(v, c) for v, c in zip(r, row_type)) for r in raw[:row_cap]]
        return SfResult(sid, cols, rows, truncated=truncated, total_row_count=total)


def client_for(domain: Dict[str, Any]) -> SnowflakeSQL:
    """The client a backend's domain runs as: its `role` with its `token_env` token."""
    return SnowflakeSQL(role=domain.get("role"), token=resolve_token(domain.get("token_env")))


# ── schema object resolution (cached per process) ──
_object_cache: Dict[Tuple[str, str, str, str], Set[str]] = {}


def schema_objects(database: str, schema: str, kind: str, domain: Dict[str, Any]) -> Set[str]:
    """Lower-cased names of the objects of `kind` in database.schema as the domain's role sees
    them: 'tables' (base tables), 'semantic_views', or 'any' (tables, views and semantic views).
    Cached for the process lifetime: the set is fixed for a benchmark run."""
    key = (database.lower(), schema.lower(), kind, f"{domain.get('role')}|{domain.get('token_env')}")
    if key in _object_cache:
        return _object_cache[key]
    sf = client_for(domain)
    names: Set[str] = set()
    if kind in ("tables", "any"):
        types = "('BASE TABLE')" if kind == "tables" else "('BASE TABLE','VIEW')"
        res = sf.execute(f"SELECT TABLE_NAME FROM {database}.INFORMATION_SCHEMA.TABLES "
                         f"WHERE TABLE_SCHEMA = '{schema.upper()}' AND TABLE_TYPE IN {types}")
        if res.error:
            raise SnowflakeSQLError(res.error)
        names |= {r[0].lower() for r in res.rows}
    if kind in ("semantic_views", "any"):
        res = sf.execute(f"SHOW SEMANTIC VIEWS IN SCHEMA {database}.{schema}")
        if res.error:
            # A schema the role cannot see holds no semantic view it can read.
            logger.info("schema_objects: SHOW SEMANTIC VIEWS IN %s.%s: %s", database, schema, res.error[:160])
        else:
            i = [c[0].lower() for c in res.columns].index("name")
            names |= {r[i].lower() for r in res.rows}
    _object_cache[key] = names
    return names
