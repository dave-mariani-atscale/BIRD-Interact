"""Database utilities ported from BIRD-Interact evaluation code."""

import hashlib
import json
import logging
import math
import os
import re
import subprocess
import threading
import time
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2 import OperationalError
from psycopg2.pool import ThreadedConnectionPool

from shared.config import settings

logger = logging.getLogger(__name__)

_postgresql_pools: Dict[str, ThreadedConnectionPool] = {}
_pool_lock = threading.Lock()


def _get_or_init_pool(db_name: str) -> ThreadedConnectionPool:
    with _pool_lock:
        if db_name not in _postgresql_pools:
            _postgresql_pools[db_name] = ThreadedConnectionPool(
                settings.pg_minconn, settings.pg_maxconn,
                dbname=db_name, user=settings.pg_user,
                password=settings.pg_password, host=settings.pg_host,
                port=settings.pg_port,
            )
        return _postgresql_pools[db_name]


def close_pool(db_name: str):
    with _pool_lock:
        if db_name in _postgresql_pools:
            pool = _postgresql_pools.pop(db_name)
            pool.closeall()


class TemplateWriteBlocked(RuntimeError):
    """Raised when something tries to modify a *_template database."""


def _is_read_only(sql: str) -> bool:
    """True only if every statement in `sql` is a plain read.

    Parsed with sqlglot rather than matched with a prefix test: the existing
    `startswith("select")` check two functions down is exactly the kind of thing that
    misses `WITH x AS (...) DELETE ...`, a leading comment, or a second statement after
    a semicolon. Anything that fails to parse counts as a write — this guard fails
    closed, because being wrong in that direction only costs an error message.
    """
    try:
        import sqlglot
        from sqlglot import expressions as exp
    except Exception:                                            # noqa: BLE001
        return False
    try:
        statements = [s for s in sqlglot.parse(sql) if s is not None]
    except Exception:                                            # noqa: BLE001
        return False
    if not statements:
        return False
    for st in statements:
        if isinstance(st, (exp.Select, exp.Union)):
            continue
        # WITH ... SELECT parses as a Select carrying a `with`; WITH ... DELETE does not.
        if isinstance(st, exp.Subquery) and isinstance(st.this, (exp.Select, exp.Union)):
            continue
        return False
    return True


def _guard_template_write(query: str, db_name: str):
    """Refuse to modify a *_template database (B-25).

    The grader executes gold against whatever database it is handed, and a
    Management-category gold is DML. On 2026-08-12 a regrade pointed at
    `exchange_traded_funds_template` ran an archive-and-delete into it: 21574 rows
    left `annual_returns`, taking every non-NULL `categoryperf` with them. Templates
    are the source every per-task database is cloned from and the reference gold is
    graded against, so that silently redefined "correct" for two tasks and made them
    unwinnable in either arm for two days, with nothing erroring.

    Reads are always allowed. Set ALLOW_TEMPLATE_WRITES=1 for deliberate maintenance
    (restoring a template, rebuilding a baseline) — the point is to stop accidents,
    not to make templates immutable.
    """
    if not db_name.endswith("_template"):
        return
    if os.environ.get("ALLOW_TEMPLATE_WRITES") == "1":
        return
    if _is_read_only(query):
        return
    raise TemplateWriteBlocked(
        f"refusing to run a non-read-only statement against {db_name!r}. "
        "Templates are the clone source for every per-task DB and the reference the "
        "grader runs gold against, so writing to one silently changes what 'correct' "
        "means for every later run (B-25). Run this against a per-task copy instead "
        "(shared.db_utils.create_task_db), or set ALLOW_TEMPLATE_WRITES=1 if you are "
        f"deliberately maintaining the template. Statement: {' '.join(query.split())[:160]}"
    )


def perform_query(query: str, db_name: str, conn=None):
    MAX_ROWS = 10000
    _guard_template_write(query, db_name)
    pool = _get_or_init_pool(db_name)
    if conn is None:
        conn = pool.getconn()
    cursor = conn.cursor()
    cursor.execute("SET statement_timeout = '60s';")
    try:
        cursor.execute(query)
        conn.commit()
        lower_q = query.strip().lower()
        if lower_q.startswith("select") or lower_q.startswith("with"):
            rows = cursor.fetchmany(MAX_ROWS + 1)
            result = rows[:MAX_ROWS]
        else:
            try:
                result = cursor.fetchall()
            except psycopg2.ProgrammingError:
                result = None
        desc = cursor.description
        return result, conn, desc
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()


def execute_queries(queries, db_name: str, conn=None):
    """Execute queries and return (result, error, timeout, cursor_description)."""
    if isinstance(queries, str):
        queries = [queries]
    if not queries:
        return None, None, False, None
    result = None
    desc = None
    for query in queries:
        if not query or not query.strip():
            continue
        try:
            result, conn, desc = perform_query(query, db_name, conn=conn)
        except psycopg2.errors.QueryCanceled:
            return None, None, True, None
        except (OperationalError, psycopg2.Error) as e:
            return None, str(e), False, None
        except Exception as e:
            return None, str(e), False, None
    return result, None, False, desc


def _pg_env() -> tuple:
    """Return (common_args, env_vars) for subprocess commands."""
    env_vars = os.environ.copy()
    env_vars["PGPASSWORD"] = settings.pg_password
    args = ["-h", settings.pg_host, "-p", str(settings.pg_port), "-U", settings.pg_user]
    return args, env_vars


#: Postgres silently truncates any identifier longer than this to this length,
#: emitting only a NOTICE. `createdb` still exits 0, so an over-long database
#: name does not fail - it quietly becomes a DIFFERENT, shorter database, and
#: two names that differ only after byte 63 become the SAME database.
MAX_PG_IDENTIFIER = 63

#: Longest suffix that is later appended to a task DB name (the Phase-1
#: snapshot, created as `create_task_db(task_db, "p1snap")`). A task DB name has
#: to leave room for it, or the snapshot collides with the DB it snapshots.
SNAPSHOT_SUFFIX_LEN = len("__p1snap")


def fit_pg_identifier(name: str, reserve: int = 0) -> str:
    """Return `name` shortened to a Postgres-safe identifier, still unique.

    BIRD's `instance_id` already begins with the database name
    (`labor_certification_applications_10`), and the task DB name prefixes it
    again, so the name is the database name twice: 69 bytes for
    `labor_certification_applications`. Postgres kept the first 63, which cut
    off `ons_10` - the task number, the only part that distinguishes one task's
    database from another's - so all 20 tasks landed on one database and the
    snapshot collided with its own source.

    Rather than truncate, replace the overflowing tail with a hash of the full
    name: deterministic (a task always resolves to the same DB) and distinct per
    task. `reserve` holds back room for a suffix appended later.
    """
    limit = MAX_PG_IDENTIFIER - reserve
    if len(name.encode()) <= limit:
        return name
    digest = hashlib.sha1(name.encode()).hexdigest()[:8]
    return f"{name[:limit - len(digest) - 1]}_{digest}"


def _drop_and_create_db(db_name: str, template_db: str):
    """Drop db_name (if exists) and recreate from template_db."""
    # Loud rather than silent: past this length Postgres renames the database
    # out from under every caller, and the pg_terminate_backend filter below
    # stops matching `datname` (it compares the un-truncated literal), so
    # dropdb fails on live connections. Callers must go through
    # fit_pg_identifier().
    if len(db_name.encode()) > MAX_PG_IDENTIFIER:
        raise ValueError(
            f"database name is {len(db_name.encode())} bytes, over the Postgres "
            f"{MAX_PG_IDENTIFIER}-byte identifier limit, and would be silently "
            f"truncated to {db_name[:MAX_PG_IDENTIFIER]!r}: {db_name!r}"
        )
    args, env_vars = _pg_env()
    close_pool(db_name)
    _run_pg(
        ["psql", *args, "-d", "postgres", "-c",
         f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"],
        env_vars,
    )
    _run_pg(["dropdb", "--if-exists", *args, db_name], env_vars)
    _run_pg(["createdb", *args, db_name, "--template", template_db], env_vars)


def _run_pg(cmd: list, env_vars: dict):
    """Run a psql/createdb/dropdb command, surfacing stderr on failure.

    The previous version discarded stderr, so a `createdb` failure raised a
    bare CalledProcessError with no message - which is how the identifier
    collision above stayed invisible while it was voiding whole runs.
    """
    proc = subprocess.run(cmd, env=env_vars, timeout=60,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{cmd[0]} failed (exit {proc.returncode}): "
            f"{(proc.stderr or '').strip() or 'no stderr'}"
        )


def reset_and_restore_database(db_name: str):
    template_db = f"{db_name}_template"
    _drop_and_create_db(db_name, template_db)


def create_task_db(base_db: str, task_id: str, template: str = None,
                   reserve: int = SNAPSHOT_SUFFIX_LEN) -> str:
    """Create a per-task DB copy. Returns task DB name.

    Args:
        base_db: Base database name (used for naming the task DB).
        task_id: Task identifier (sanitized for DB naming).
        template: Template DB to copy from. Defaults to {base_db}_template.
        reserve: Bytes to hold back from the 63-byte identifier limit for a
            suffix appended later. Defaults to room for the Phase-1 snapshot;
            pass 0 when creating the snapshot itself, which gets no suffix.
    """
    safe_id = task_id.replace("-", "_").replace(".", "_")
    task_db = fit_pg_identifier(f"{base_db}__{safe_id}", reserve=reserve)
    template_db = template or f"{base_db}_template"
    _drop_and_create_db(task_db, template_db)
    return task_db


def reset_task_db(task_db: str, template_source: str):
    """Reset a per-task DB from a template/snapshot DB."""
    _drop_and_create_db(task_db, template_source)


def drop_task_db(task_db: str):
    """Drop a per-task DB and close its connection pool."""
    args, env_vars = _pg_env()
    close_pool(task_db)
    subprocess.run(
        ["psql", *args, "-d", "postgres", "-c",
         f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{task_db}' AND pid <> pg_backend_pid();"],
        check=True, env=env_vars, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["dropdb", "--if-exists", *args, task_db],
        check=True, env=env_vars, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def get_connection_for_phase(db_name: str):
    pool = _get_or_init_pool(db_name)
    return pool.getconn()


_NUMERIC_STR_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")
# 'YYYY-MM-DD' followed by a time: the form a semantic layer returns a Postgres
# date/timestamp in over JSON. See canonical_cell.
_TIMESTAMP_STR_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


def process_decimals_recursive(item, decimal_places: int):
    """Round every numeric cell to `decimal_places`, HALF_UP, whatever Python
    type it arrived as.

    Both rounding branches must agree on the rounding MODE. They did not: a
    Decimal was quantized ROUND_HALF_UP while a float went through Python's
    round(), which is banker's rounding (half-to-even). Gold SQL rounds inside
    the query (Postgres ROUND = half-up) and so reaches here as an
    already-rounded Decimal, while a semantic layer returns full-precision
    floats that get rounded here — so at an exact .5 boundary the two sides
    disagreed by one unit in the last place and the row compared unequal even
    though the answer was right. Confirmed live: 3 of 1000 rows on one task
    (17/16 -> gold 1.063 vs 1.062, 20/320 -> 0.063 vs 0.062, 3/80 -> 0.038 vs
    0.037). The numeric-tolerance fallback cannot rescue those, because gold's
    pre-rounding value is already the rounded one.

    Numeric-looking STRINGS are rounded too. A SQL interface may return a
    numeric as a string ('0.27800000000000000000' for a CAST(... AS
    numeric(p,s)) expression, which this benchmark's own agent instructions
    tell the agent to write), and a string previously fell straight through
    unrounded — so it could never match a gold scalar that had been rounded.
    The coercion is applied identically to both sides, so it can only make
    values that were equal-but-differently-represented compare equal; it cannot
    make genuinely different values match.
    """
    quantizer = Decimal(1).scaleb(-decimal_places)
    if isinstance(item, bool):
        return item  # bool is an int subclass — never treat it as a number here
    if isinstance(item, Decimal):
        return item.quantize(quantizer, rounding=ROUND_HALF_UP)
    elif isinstance(item, float):
        if item != item or item in (float("inf"), float("-inf")):
            return item  # NaN / +-inf have no decimal expansion to quantize
        return Decimal(str(item)).quantize(quantizer, rounding=ROUND_HALF_UP)
    elif isinstance(item, str) and _NUMERIC_STR_RE.match(item.strip()):
        try:
            return Decimal(item.strip()).quantize(quantizer, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return item
    elif isinstance(item, (list, tuple)):
        return type(item)(process_decimals_recursive(x, decimal_places) for x in item)
    elif isinstance(item, dict):
        return {k: process_decimals_recursive(v, decimal_places) for k, v in item.items()}
    return item


def canonical_cell(value) -> str:
    """Render a cell for cross-source string comparison.

    Postgres and a semantic layer spell the same number differently — 186709472
    vs 186709472.0, Decimal('6.90') vs 6.9 — so str() alone reports equal values
    as unequal. Numerics collapse to one fixed-point form.

    String values are returned as-is, as upstream compares them. Gold SQL
    frequently wraps a text column in LOWER(...) (e.g. `LOWER(pm.pnlkind)`) that
    the agent has no way to see or replicate — a semantic layer's dimension
    attribute returns its own stored display casing (e.g. "Bifacial"), not gold's
    ad-hoc lowercased form ("bifacial"). Confirmed live: a submission with
    numerically-correct values to ~10 significant digits failed outright on this
    alone. Case-folding only matters for genuinely case-varying gold conventions
    the agent can't predict; it doesn't paper over an actually-wrong answer.

    A timestamp string is truncated to its date when
    settings.grading_timestamp_date is on (the default), which is what
    preprocess_results already does to a TYPED date/datetime
    (strftime("%Y-%m-%d"), time component discarded). Gold's timestamp column
    therefore reaches the comparison as '2025-02-19' while a semantic layer
    returns the JSON string '2025-02-19 16:29:00' or '2025-02-19T00:00:00' —
    which can never match, whatever the answer. Six phases across five
    databases project a date or datetime at all (crypto_exchange twice), so
    this is small but total where it lands. Applied to both sides — which is
    what makes it symmetric, and also its one cost: gold text that merely LOOKS
    like a timestamp is truncated too, so '2025-02-19 08:00:00' and
    '2025-02-19 23:59:59' compare equal. That is why it is behind a flag and in
    the results deviations block.

    Only reached via _compare_rows' `cell` hook, and only from the cross-source
    path: on the raw path Python's own numeric equality already ignores
    representation, and collapsing to strings there would newly equate str '100'
    with int 100.
    """
    if isinstance(value, bool):
        # Parity with the raw path: there Python's own equality treats True == 1
        # and False == 0 (bool is an int subclass), so a submitted 1/0 flag
        # matches a gold boolean. Rendering "True"/"False" here made the same
        # flag unmatchable on the semantic-layer path only. 64 of the 600 golds
        # project a bare aliased comparison (mental_health_16/17/18/20 among
        # them), and the agent prompt tells both arms to write 1/0.
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        # 'f' avoids normalize()'s sci notation (1.86709472E+8) for big ints
        return format(Decimal(str(value)).normalize(), "f")
    text = str(value)
    if settings.grading_timestamp_date:
        stamp = _TIMESTAMP_STR_RE.match(text.strip())
        if stamp:
            return stamp.group(1)
    return text


def _compare_rows(pred_res, gt_res, conditions, cell=None) -> int:
    """Score two already-preprocessed row sets — 1 if they match, else 0.

    `cell` renders each value before comparing; None keeps the typed values.
    That argument is the only difference between the raw and semantic-layer
    comparisons, so it stays one visible knob rather than two copies of this
    tail that drift.
    """
    pred_cells, gt_cells = pred_res, gt_res
    if cell is not None:
        pred_cells = [tuple(cell(v) for v in row) for row in pred_res]
        gt_cells = [tuple(cell(v) for v in row) for row in gt_res]
    if conditions and conditions.get("order", False):
        return 1 if pred_cells == gt_cells else 0
    return 1 if set(pred_cells) == set(gt_cells) else 0


def preprocess_results(results, decimal_places: int = 2):
    if results is None:
        return []
    processed = []
    for row in results:
        processed_row = []
        for item in row:
            if isinstance(item, (date, datetime)):
                processed_row.append(item.strftime("%Y-%m-%d"))
            else:
                pi = process_decimals_recursive(item, decimal_places)
                if isinstance(pi, (dict, list)):
                    # default=str because process_decimals_recursive has already
                    # turned every numeric INSIDE the dict/list into a Decimal,
                    # which json.dumps cannot serialize. Without it this raises
                    # TypeError, which both grading paths swallow as "Your SQL is
                    # not correct." — so a task whose gold projects a raw jsonb
                    # column is unpassable on BOTH arms no matter what the agent
                    # writes. Live: archeology_scan_10's gold selects
                    # processing.system_usage whole, and 821 of its 987 rows carry
                    # a dict. Safe because it is applied to gold and prediction
                    # alike and both sides arrive quantized to the same
                    # decimal_places, so str() renders them identically.
                    processed_row.append(json.dumps(pi, sort_keys=True, default=str))
                else:
                    processed_row.append(pi)
        processed.append(tuple(processed_row))
    return processed


def remove_comments(sql_list: List[str]) -> List[str]:
    cleaned = []
    for sql in sql_list:
        no_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
        no_line = re.sub(r"--.*?(\r\n|\r|\n)", r"\1", no_block)
        no_blank = re.sub(r"\n\s*\n+", "\n", no_line)
        cleaned.append(no_blank.strip())
    return cleaned


def remove_distinct(sql_list: List[str]) -> List[str]:
    """Delete the set-quantifier DISTINCT, leaving Postgres' DISTINCT operators intact.

    Upstream drops every token equal to "distinct" so a prediction and a gold that
    differ only in de-duplication still compare equal. Postgres spells two *different*
    constructs with the same word, and deleting it from either produces invalid SQL:

      * `SELECT DISTINCT ON (col) ...` -> `SELECT ON (col) ...`
      * `a IS [NOT] DISTINCT FROM b`   -> `a IS [NOT] FROM b`

    Neither is a quantifier. `DISTINCT ON` picks one row per group and the
    parenthesised list belongs to the operator; `IS DISTINCT FROM` is a null-safe
    comparison operator.

    That is not cosmetic. Gold is cleaned by this function on BOTH arms
    (ex_base_external_pred, grade_raw_submission). A mangled gold fails to execute,
    both graders return 0, and the task becomes unpassable no matter what the agent
    submits - silently, because a gold that errors is indistinguishable in the
    results from an answer that is wrong.

    15 of the 600 bird-interact-full golds are affected: 9 use DISTINCT ON (7 in
    Phase-1 gold, 9 in Phase-2) and 7 use IS [NOT] DISTINCT FROM (all Phase-1, all
    Management-category, so they reach only the raw arm). In the 410-task query run
    all 5 affected Phase-1 tasks scored 0 on both arms.

    Keeping both is also the semantically right call - each is part of the answer,
    not a de-duplication nicety the grader should look past.

    Still splits on " " rather than re-tokenising, so whitespace handling is byte for
    byte what upstream produces and the output changes for these two operators and
    for nothing else.
    """
    cleaned = []
    for query in sql_list:
        tokens = query.split(" ")
        words = [t.strip().lower() for t in tokens]
        kept: List[str] = []
        for i, token in enumerate(tokens):
            # Matched on the RAW token, exactly as upstream does. A token carrying
            # adjacent whitespace ("DISTINCT\n") never compared equal there either, so
            # it stays untouched here rather than newly disappearing.
            if token.lower() == "distinct":
                after = next((w for w in words[i + 1:] if w), "")
                before = [w for w in words[:i] if w][-2:]
                # `on\b` rather than startswith: a column named `online` is not DISTINCT ON.
                is_distinct_on = bool(re.match(r"on\b", after))
                # `IS DISTINCT FROM` / `IS NOT DISTINCT FROM`, by the preceding words.
                is_null_safe_compare = before[-1:] == ["is"] or before == ["is", "not"]
                if is_distinct_on or is_null_safe_compare:
                    kept.append(token)
                continue
            kept.append(token)
        cleaned.append(" ".join(kept))
    return cleaned


def _remove_round_functions(sql_string: str) -> str:
    def find_matching_paren(text, start):
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "(": depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0: return i
        return -1

    def find_first_arg_end(text, start):
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "(": depth += 1
            elif text[i] == ")":
                if depth == 0: return i
                depth -= 1
            elif text[i] == "," and depth == 0: return i
        return len(text)

    result = sql_string
    while True:
        match = re.search(r"ROUND\s*\(", result, re.IGNORECASE)
        if not match: break
        start = match.start()
        open_p = match.end() - 1
        first_end = find_first_arg_end(result, open_p + 1)
        close_p = find_matching_paren(result, open_p)
        if close_p == -1: break
        first_arg = result[open_p + 1: first_end].strip()
        result = result[:start] + first_arg + result[close_p + 1:]
    return result


def remove_round(sql_list: List[str]) -> List[str]:
    return [_remove_round_functions(sql) for sql in sql_list]


def ex_base(pred_sqls, sol_sqls, db_name, conn, conditions=None) -> int:
    if not pred_sqls or not sol_sqls:
        return 0
    pred_res, pred_err, pred_to, _ = execute_queries(pred_sqls, db_name, conn)
    gt_res, gt_err, gt_to, _ = execute_queries(sol_sqls, db_name, conn)
    if any([pred_err, pred_to, gt_err, gt_to]):
        return 0
    pred_res = preprocess_results(pred_res)
    gt_res = preprocess_results(gt_res)
    if not pred_res or not gt_res:
        return 0
    return _compare_rows(pred_res, gt_res, conditions)


def _json_safe(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def record_graded_submission(**entry) -> None:
    """Append one graded submission to settings.grading_audit_path as JSONL.

    Why this exists: the semantic-layer path grades ROWS returned by the MCP,
    and those rows are not otherwise kept anywhere. That made every grader
    change a re-run — and a re-run costs API budget and carries run-to-run
    variance far larger than the change being measured, so a change worth less
    than about 0.06 average reward could not be evaluated at all. With the rows
    plus the gold SQL recorded, any later grading change can be re-scored
    offline against local Postgres for free, and two arms graded under
    different rules can be brought onto one grader after the fact.

    Off unless a path is configured. Never raises into the submit path: a
    failure to write an audit line must not fail the submission being audited.
    """
    path = settings.grading_audit_path
    if not path:
        return
    try:
        # Stamped so a row can be attributed to a run. The services are
        # long-lived and know nothing about runs, so the orchestrator records
        # its own window in the results JSON and the two are matched by time —
        # the same scheme llm_usage uses, and sound for the same reason (runs
        # are sequential; see --repeat). Without this the audit is one
        # undifferentiated pile and no completed run can be re-scored from it.
        entry.setdefault("ts", time.time())
        with open(path, "a") as f:
            f.write(json.dumps(_json_safe(entry), sort_keys=True) + "\n")
    except Exception:
        logger.warning("grading audit write failed", exc_info=True)


def parse_semantic_layer_rows(result_text: str) -> List[tuple]:
    """Parse a semantic-layer MCP tool's run_query output (a JSON array of row
    objects, e.g. `[{"col": "val"}, ...]`) into row tuples comparable with
    Postgres results. Returns [] if no JSON array line is found/parseable."""
    for line in result_text.splitlines():
        line = line.strip()
        if line.startswith("["):
            try:
                rows = json.loads(line)
            except Exception:
                continue
            if isinstance(rows, list):
                return [tuple(row.values()) for row in rows if isinstance(row, dict)]
    return []


#: The engine's own id for an executed query, which the MCP server appends to a
#: run_query response as a trailing `queryId: <uuid>` block.
_QUERY_ID_RE = re.compile(
    r"queryId:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def extract_query_id(result_text: str):
    """The engine query_id from a semantic-layer run_query response, or None.

    Why this is worth capturing at grading time. The engine's query repository
    (engine.queries, engine.query_details, engine.query_aggregate_usage) is
    keyed by this id, so it is the only exact join between a graded submission
    and whether that query hit an aggregate or the local cache. Without it the
    join has to be guessed from query text plus a time window, which cannot
    separate two runs of the same text and silently mis-attributes the rest.

    Grading re-executes every semantic-layer submission through run_query, so
    an id exists for every graded query by construction - including one the
    agent never ran itself. Reading it from the agent's own trajectory instead
    covers only about 64% of final passing queries, because the trajectory
    recording truncates a tool response at 2000 characters and the queryId
    block sits at the end.

    Returns the LAST id in the text: a response carrying more than one has the
    executed query's id last.
    """
    ids = _QUERY_ID_RE.findall(result_text or "")
    return ids[-1] if ids else None


def ex_base_external_pred(pred_res, sol_sqls, db_name, conn, conditions=None) -> int:
    """Like ex_base, but `pred_res` is already-computed rows (e.g. from a
    semantic layer's query tool via parse_semantic_layer_rows) rather than SQL
    to execute locally — the predicted query can't run against raw Postgres
    when it's in a different SQL dialect (e.g. AtScale logical SQL).

    Values are compared as strings on both sides: the semantic layer returns
    JSON-serialized values (e.g. "132.60") while Postgres returns typed values
    (Decimal, etc.) — string comparison is a coarser but safe common ground
    until a real per-domain semantic model exists (see
    config/environment_backends.yaml's placeholder-mapping warning).

    Both sides must be rounded to the same precision before that string
    comparison — a raw semantic-layer float (e.g. 0.013369130432692595) will
    otherwise almost never string-match a gold value rounded via
    preprocess_results, even when the underlying answer is correct. Equal
    precision is necessary but not sufficient, hence canonical_cell.

    If that rounded exact comparison fails, fall back to
    _compare_rows_numeric_tolerant on the PRE-rounding rows — see its
    docstring. Rounding first and only tolerance-comparing the rounded
    values would defeat the point: two floats close enough to be the same
    answer can round to visibly different decimals (76022464.2857143 vs
    76022464.18488877 -> "76022464.29" vs "76022464.18"), which is exactly
    the class of mismatch this fallback exists to see past. For that to hold,
    gold has to reach the fallback unrounded too, which is why sol_sqls is put
    through upstream's remove_comments/remove_distinct/remove_round first.
    """
    if not pred_res or not sol_sqls:
        return 0
    # Gold gets the same cleanup upstream gives it, and that test_case_default
    # already gives it on the raw path: remove_comments -> remove_distinct ->
    # remove_round (evaluation/src/eval_bird_interact.py:258-263). Only the gold
    # side is treated here because the prediction arrived as ROWS, not SQL.
    #
    # This is not a new deviation, it RETIRES one: until now the raw arm
    # compared against gold stripped and this arm compared against gold
    # verbatim, so the two arms graded differently and the lift measured the
    # grader (the same concern ex_base's own comment raises). Hence no flag —
    # the flags gate deviations FROM upstream, and this removes one.
    #
    # It also un-blocks the tolerant fallback below, which is documented to
    # work on PRE-rounding values. That is true of the prediction but was false
    # of gold whenever gold rounds inside its own SQL — 291 of the 600 tasks,
    # and 10 of archeology_scan's 13. In those, gold's "pre-rounding" value was
    # already rounded, so the fallback compared 18.4 against 18.45 instead of
    # 18.4499998 against 18.45 and could never fire. It went unnoticed because
    # the ETF golds it was built against don't round in SQL. See tracker B-19.
    #
    # Measured before adopting: 0 verdict changes either way across the 68
    # recorded semantic-layer submissions whose gold rounds, and 0 of 82 golds
    # across two domains change row count or fail to execute once stripped.
    #
    # remove_distinct is deliberately NOT in that chain, and this is the one
    # place the raw arm and this one must differ. Upstream's remove_distinct
    # normalises TWO SQL STRINGS so a prediction that omits DISTINCT still
    # matches a gold that has it; grade_raw_submission accordingly strips BOTH
    # sides (see its call below). Here the prediction is ROWS, already
    # de-duplicated by the engine exactly as the agent's own DISTINCT asked.
    # Stripping only the gold side is therefore not "the same cleanup" — it is
    # half of a two-sided normalisation, and the half that can only ever hurt:
    #   * conditions["order"] false -> _compare_rows compares SETS, so gold's
    #     new duplicates are discarded and stripping changes nothing;
    #   * conditions["order"] true  -> it compares ORDERED LISTS, so a gold
    #     whose DISTINCT collapses a fan-out join arrives with duplicate rows
    #     that no correct prediction can reproduce, and the task is unpassable
    #     however good the answer is.
    # That is the same "mangled gold makes a task unpassable" failure that
    # remove_distinct's own docstring already carves DISTINCT ON and
    # IS DISTINCT FROM out for; this is the third case and the only one that
    # needs the caller rather than the tokeniser, because whether the
    # quantifier is load-bearing depends on the join, not on the syntax.
    #
    # Measured across all 22 databases of the 2026-08-25 410-task run: 43
    # phase-1 golds contain a set-quantifier DISTINCT, 41 of which are no-ops
    # (stripping leaves the result unchanged, so this line never mattered for
    # them). Only 2 are load-bearing AND order-sensitive:
    #   museum_artifact_6  gold 545 rows -> 566 stripped, prediction 545
    #   fake_account_15    gold  46 rows -> 2476 stripped, prediction  46
    # The earlier "0 of 82 golds across two domains" check simply had no
    # fan-out-join gold in its two domains.
    #
    # Re-grading all 804 recorded phase-1 submissions of that run, with and
    # without this line, moves exactly ONE verdict and loses none:
    # museum_artifact_6 goes 0 -> 1, having returned gold's 545 rows in gold's
    # order and been marked wrong against a 566-row gold it could not produce.
    # fake_account_15 stays 0 and should: its 46 rows only COINCIDE in count
    # with gold's 46, and are different clients entirely. That the blast radius
    # is one task is the point — the strip is not worth the risk of making a
    # correct answer unpassable, and outside those 43 golds the code path here
    # is byte-identical, so nothing else can move.
    sol_sqls = remove_round(remove_comments(sol_sqls))
    gt_res, gt_err, gt_to, _ = execute_queries(sol_sqls, db_name, conn)
    if gt_err or gt_to:
        return 0
    pred_rounded = preprocess_results(pred_res)
    gt_rounded = preprocess_results(gt_res)
    if not gt_rounded:
        return 0
    return 1 if _compare_rows(pred_rounded, gt_rounded, conditions,
                              cell=canonical_cell) else 0


def grade_raw_submission(pred_sqls, sol_sqls, db_name, conn, conditions=None) -> int:
    """Grade a raw-SQL submission end to end: step 1's cleanup on BOTH sides,
    then ex_base. The whole raw path, in one call.

    THE entry point for grading raw SQL, live or offline. `ex_base` deliberately
    does none of the cleanup — upstream's doesn't either, and dataset-supplied
    test cases call it with their own preparation — so calling it directly is a
    trap: gold keeps its ROUND() while the prediction loses its own, and the two
    are then compared at different precisions. That trap has now been walked
    into twice in offline tools, on the same day, and both times it was invisible
    until a re-grade failed to reproduce the run it was replaying. An oracle
    smoke test cannot catch it, because there the prediction IS gold and both
    sides agree however they are cleaned.

    So: offline graders call this, never ex_base.
    """
    return ex_base(remove_round(remove_distinct(remove_comments(list(pred_sqls)))),
                   remove_round(remove_distinct(remove_comments(list(sol_sqls)))),
                   db_name, conn, conditions)


def test_case_default(pred_sqls, sol_sqls, db_name, conn, conditions=None):
    result = grade_raw_submission(pred_sqls, sol_sqls, db_name, conn, conditions)
    assert result == 1, f"ex_base returned {result} but expected 1."
    return result
