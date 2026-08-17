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


def resolve_decimal_places(conditions) -> int:
    """Rounding precision for a comparison, from the task's `conditions.decimal`.

    The dataset uses -1 for "this task states no precision requirement", NOT
    "round to the nearest 10" — which is what passing it through to
    round()/Decimal.scaleb() literally does. Falls back to 2, the precision this
    harness uses when a task is silent.

    Honoring `decimal` at all is an ADK choice: upstream BIRD-Interact always
    preprocesses at 2, so scores for tasks declaring `decimal >= 0 and != 2` are
    not directly comparable to published numbers. Gated on
    settings.grading_honor_decimal, which is off by default; see that field.
    """
    if not settings.grading_honor_decimal:
        return 2  # upstream: preprocess_results' default, conditions ignored
    dp = (conditions or {}).get("decimal")
    return dp if isinstance(dp, int) and dp >= 0 else 2


_ORDER_LINT: Optional[set] = None


def _order_lint_phases() -> set:
    """The (task_id, phase) pairs whose gold does not determine its own row
    order, loaded once from settings.grading_order_lint_path."""
    global _ORDER_LINT
    if _ORDER_LINT is None:
        path = settings.grading_order_lint_path
        if not os.path.isabs(path):
            # Resolved against the repo root, not the working directory: the
            # services are started from there but a script or a test need not
            # be, and a missing list degrades silently to upstream behaviour.
            path = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), path)
        try:
            with open(path) as f:
                doc = json.load(f)
            _ORDER_LINT = {(t, int(p)) for t, p in doc.get("phases", [])}
        except Exception:
            logger.warning("order lint list unreadable at %s — order graded as "
                           "upstream does", settings.grading_order_lint_path,
                           exc_info=True)
            _ORDER_LINT = set()
    return _ORDER_LINT


def apply_order_lint(conditions, task_id: str, phase: int):
    """Drop `order` from a phase whose gold does not determine an order.

    `order: true` makes the grader compare row by row, which is only answerable
    if gold's own ORDER BY totally orders its result. Measured over all 22
    databases by replanning gold (scripts/bird_order_lint.py): on 68 of 438
    order-sensitive phases — 57 tasks — it does not, and the "expected" order
    is whichever one Postgres's chosen plan happened to emit. Nothing
    reproduces that except by luck, and an engine that is not Postgres never
    gets the luck.

    So on those phases the order is not graded at all. That is coarser than
    _ordered_match_tolerating_ties, which still grades the part of the order
    gold DOES fix — but it needs no heuristic, it is decided by gold alone, and
    it covers the 20 phases where the sort key cannot be inferred at all. The
    two are complementary and both are on: this one where gold is provably
    arbitrary, the tie tolerance everywhere else.

    Returns `conditions` unchanged unless the flag is on AND the phase is
    listed, so a run with the flag off is bit-identical to upstream here.
    """
    if not settings.grading_order_lint or not conditions:
        return conditions
    if not conditions.get("order"):
        return conditions
    if (task_id, int(phase)) not in _order_lint_phases():
        return conditions
    lifted = dict(conditions)
    lifted["order"] = False
    lifted["_order_lint"] = True     # recorded in the grading audit
    return lifted


def canonical_cell(value) -> str:
    """Render a cell for cross-source string comparison.

    Postgres and a semantic layer spell the same number differently — 186709472
    vs 186709472.0, Decimal('6.90') vs 6.9 — so str() alone reports equal values
    as unequal. Numerics collapse to one fixed-point form.

    String values are case-folded when settings.grading_casefold is on. Gold SQL
    frequently wraps a text column in LOWER(...) (e.g. `LOWER(pm.pnlkind)`) that
    the agent has no way to see or replicate — a semantic layer's dimension
    attribute returns its own stored display casing (e.g. "Bifacial"), not gold's
    ad-hoc lowercased form ("bifacial"). Confirmed live: a submission with
    numerically-correct values to ~10 significant digits failed outright on this
    alone. Case-folding only matters for genuinely case-varying gold conventions
    the agent can't predict; it doesn't paper over an actually-wrong answer.

    A timestamp string is truncated to its date, which is what
    preprocess_results already does to a TYPED date/datetime
    (strftime("%Y-%m-%d"), time component discarded). Gold's timestamp column
    therefore reaches the comparison as '2025-02-19' while a semantic layer
    returns the JSON string '2025-02-19 16:29:00' or '2025-02-19T00:00:00' —
    which can never match, whatever the answer. Six phases across five
    databases project a date or datetime at all (crypto_exchange twice), so
    this is small but total where it lands. Applied to both sides, so a text
    column that merely looks like a timestamp is truncated on both and still
    compares equal.

    Only reached via _compare_rows' `cell` hook, and only from the cross-source
    path: on the raw path Python's own numeric equality already ignores
    representation, and collapsing to strings there would newly equate str '100'
    with int 100.
    """
    if isinstance(value, bool):
        return str(value)  # bool is an int subclass — keep it out of the numeric branch
    if isinstance(value, (int, float, Decimal)):
        # 'f' avoids normalize()'s sci notation (1.86709472E+8) for big ints
        return format(Decimal(str(value)).normalize(), "f")
    text = str(value)
    stamp = _TIMESTAMP_STR_RE.match(text.strip())
    if stamp:
        return stamp.group(1)
    return text.lower() if settings.grading_casefold else text


def _cell_cmp(a, b) -> Optional[int]:
    """Three-way compare of two cells, numerically when both look numeric and
    as case-folded strings otherwise. None means "not orderable" (a NULL, or a
    pair that can't be compared), which disqualifies a column from being
    treated as a sort key."""
    if a is None or b is None:
        return None
    an, bn = _try_parse_number(a), _try_parse_number(b)
    if an is not None and bn is not None:
        return (an > bn) - (an < bn)
    try:
        sa, sb = str(a).lower(), str(b).lower()
    except Exception:
        return None
    return (sa > sb) - (sa < sb)


def _sort_key_indices(gt_res) -> Optional[List[int]]:
    """Infer which columns the gold result is ORDERed BY, as column indices.
    None means "no column qualifies" — see the fallback note at the end.

    The tie-tolerant comparisons need to know which columns rows may be
    permuted within. This used to assume the sort column was the LAST one,
    which holds for the "label, value ORDER BY value" shape but silently breaks
    whenever the sorted measure is not last: with a 3-column
    (id, measure, category) result sorted on the measure, grouping by the
    category collapses the run structure and an entirely correct answer fails.
    Confirmed live on a task where 375 of 1000 rows tied on the sort column and
    the two engines broke those ties differently.

    A column qualifies if gold's values are monotonic across the whole result
    AND it has at least two distinct values. The constant-column exclusion
    matters: a single-valued column is trivially monotonic, and grouping on it
    would collapse every row into one group, silently turning an ordered
    comparison into an unordered one.

    Among qualifying columns, pick the one with the FEWEST distinct values.
    Several columns can be monotonic at once — an id or label column is often
    incidentally sorted too — and including those would make the key finer than
    the true sort expression, giving every row its own group and destroying the
    very tie tolerance this exists to provide. The sort measure is the coarsest
    of the monotonic columns; an identifier is the finest. Ties in distinct-count
    prefer the rightmost column, which reproduces the historical behaviour on
    the "label, value ORDER BY value" shape.

    When NOTHING qualifies this returns None and the callers forgive nothing.
    It used to fall back to the last column, which is the B-22 over-reach: if
    that column is constant, every row lands in ONE tie group and the ordered
    comparison silently becomes an unordered one. Measured over all 22
    databases (365 multi-row order-sensitive phases): the fallback fired on 33
    and collapsed to a single group on 10, `exchange_traded_funds_6` among
    them. A tie tolerance that cannot identify the sort key must not forgive a
    permutation. Cost, measured by replanning gold across the 68 phases whose
    order gold does not itself determine: rescues drop from 57 to 48. The other
    20 are covered by settings.grading_order_lint, which uses measured evidence
    rather than this heuristic.
    """
    if not gt_res:
        return None
    width = len(gt_res[0])
    best, best_distinct = None, None
    for c in range(width):
        col = [row[c] for row in gt_res]
        cmps = [_cell_cmp(col[i], col[i + 1]) for i in range(len(col) - 1)]
        if any(x is None for x in cmps):
            continue
        if not (all(x <= 0 for x in cmps) or all(x >= 0 for x in cmps)):
            continue
        if all(x == 0 for x in cmps):
            continue  # constant column — would collapse the whole result into one group
        # count distinct by adjacent change, since the column is monotonic
        distinct = 1 + sum(1 for x in cmps if x != 0)
        if best_distinct is None or distinct <= best_distinct:
            best, best_distinct = c, distinct
    return [best] if best is not None else None


def _ordered_match_tolerating_ties(pred_res, gt_res) -> bool:
    """True when pred differs from gold only by reordering rows that TIE on the
    (assumed) sort column.

    Gold SQL and a semantic layer are two different execution engines with no
    shared tie-breaking convention — SQL never guarantees a stable order among
    rows equal on the ORDER BY expression, and rounding to the task's decimal
    precision makes ties far more likely than the underlying raw data would
    suggest. Confirmed live: gold's own 336-row result for one task had 8 tied
    pairs after rounding, with neither gold's nor the agent's query supplying a
    secondary tiebreaker — an exact-order comparison fails on these even when
    every value is correct.

    The sort key is inferred by _sort_key_indices (every column gold is
    monotonic in, excluding constants) rather than assumed to be the last
    column, which was wrong whenever the sorted measure was not last. Group
    GOLD rows into consecutive runs sharing that key, then verify the PREDICTED
    rows occupying that same index range form the identical set (order within
    the tied group doesn't matter), and that groups appear in the same overall
    sequence. Falls back to an exact match on any structural mismatch (row
    count, or a tie-group heuristic that doesn't hold for this shape) rather
    than silently passing.

    Counter, not set(): a tie group holding the same row twice would compare
    equal to one holding it once alongside a different row.

    Called on canonical_cell output on the cross-source path, so 4.68 and
    Decimal('4.68') group together. Only equality is used, never `<` — nothing
    here breaks on strings the way an ordering comparison would.
    """
    if len(pred_res) != len(gt_res):
        return False
    if not gt_res:
        return True
    key_idxs = _sort_key_indices(gt_res)
    if key_idxs is None:
        return False        # no inferable sort key — forgive nothing (B-22)
    groups = []
    for row in gt_res:
        key = tuple(row[i] for i in key_idxs)
        if groups and groups[-1][0] == key:
            groups[-1][1].append(row)
        else:
            groups.append((key, [row]))
    idx = 0
    for _key, group_rows in groups:
        n = len(group_rows)
        if Counter(pred_res[idx:idx + n]) != Counter(group_rows):
            return False
        idx += n
    return True


def _try_parse_number(value) -> Optional[float]:
    """Best-effort float parse; None (not 0) for anything non-numeric, so
    callers can tell "not a number" apart from "the number zero"."""
    if isinstance(value, bool):
        return None  # bool is an int subclass — don't let True/False parse as 1.0/0.0
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _values_close(a, b, rel_tol: Optional[float] = None, abs_tol: float = 1e-9) -> bool:
    """Numeric values within a tight relative tolerance count as equal;
    everything else falls back to case-folded string equality (same rule
    canonical_cell applies to non-numerics).

    rel_tol defaults to settings.grading_rel_tolerance_value rather than to a
    literal, so the declared knob actually reaches the comparison. It used to
    default to 1e-6 here while the setting was read nowhere, which made the
    config field inert and silently un-tunable (tracker B-20). Callers may
    still pass a tolerance explicitly to pin one independent of the setting.
    """
    if rel_tol is None:
        rel_tol = settings.grading_rel_tolerance_value
    a_num, b_num = _try_parse_number(a), _try_parse_number(b)
    if a_num is not None and b_num is not None:
        return math.isclose(a_num, b_num, rel_tol=rel_tol, abs_tol=abs_tol)
    return str(a).lower() == str(b).lower()


def _rows_close(row_a, row_b) -> bool:
    return len(row_a) == len(row_b) and all(_values_close(x, y) for x, y in zip(row_a, row_b))


def _multiset_match_tolerant(pred_res, gt_res) -> bool:
    """Unordered row-set equality, but a row "matches" another if every cell
    is _values_close rather than ==. O(n^2); fine at the row counts this
    benchmark's queries return."""
    if len(pred_res) != len(gt_res):
        return False
    remaining = list(gt_res)
    for p in pred_res:
        for i, g in enumerate(remaining):
            if _rows_close(p, g):
                remaining.pop(i)
                break
        else:
            return False
    return True


def _ordered_match_tolerating_ties_numeric(pred_res, gt_res) -> bool:
    """_ordered_match_tolerating_ties, but both the tie-grouping key
    comparison and the within-group set comparison use _values_close instead
    of ==, so a numeric-precision-noise mismatch can't itself break the tie
    grouping it's meant to look past."""
    if len(pred_res) != len(gt_res):
        return False
    if not gt_res:
        return True
    key_idxs = _sort_key_indices(gt_res)
    if key_idxs is None:
        return False        # no inferable sort key — forgive nothing (B-22)
    groups = []
    for row in gt_res:
        key = tuple(row[i] for i in key_idxs)
        if groups and len(groups[-1][0]) == len(key) and all(
                _values_close(a, b) for a, b in zip(groups[-1][0], key)):
            groups[-1][1].append(row)
        else:
            groups.append((key, [row]))
    idx = 0
    for _key, group_rows in groups:
        n = len(group_rows)
        if not _multiset_match_tolerant(list(pred_res[idx:idx + n]), group_rows):
            return False
        idx += n
    return True


def _compare_rows_numeric_tolerant(pred_res, gt_res, conditions) -> bool:
    """Fallback comparison for the cross-source path: True if pred_res and
    gt_res match once numeric cells are compared with a tight relative
    tolerance instead of exact string equality.

    Exists to absorb float32-vs-float64 precision noise a semantic layer and
    Postgres can each introduce independently of the query being right or
    wrong — e.g. a warehouse casting one operand to `::real` mid-formula.
    Confirmed live: a semantic-layer answer matching gold to 9 significant
    figures still failed the exact comparison by about 1 part in 760 million,
    solely from gold's own float32 cast, with no error in either query.

    Deliberately only ever called AFTER the exact/tie-tolerant comparison in
    _compare_rows has already failed — it must never be the reason a
    genuinely wrong answer passes, only the reason a right-to-many-more-sig-
    figs-than-the-task-asks-for answer isn't marked wrong. Operates on the
    PRE-rounding row values (not the decimal-place-rounded ones _compare_rows
    sees), since rounding two nearby-but-not-identical floats can itself
    round them to different displayed values before this tolerance ever gets
    a chance to see how close they really were.
    """
    if conditions and conditions.get("order", False):
        if _rows_close_ordered(pred_res, gt_res):
            return True
        return _ordered_match_tolerating_ties_numeric(pred_res, gt_res)
    return _multiset_match_tolerant(pred_res, gt_res)


def _rows_close_ordered(pred_res, gt_res) -> bool:
    return len(pred_res) == len(gt_res) and all(_rows_close(p, g) for p, g in zip(pred_res, gt_res))


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
        if pred_cells == gt_cells:
            return 1
        # Same rows in a different order: only a tie permutation is forgiven,
        # and only when settings.grading_tie_tolerance is on. Upstream stops at
        # the strict compare above.
        if not settings.grading_tie_tolerance:
            return 0
        return 1 if _ordered_match_tolerating_ties(pred_cells, gt_cells) else 0
    return 1 if set(pred_cells) == set(gt_cells) else 0


def diagnose_rows(pred_res, gt_res, conditions, cell=None) -> str:
    """One sentence describing HOW a failed submission's rows differ from gold.

    Shape only — counts, and whether the rows match but their order doesn't.
    Never a value, a column name or a row, so it narrows the search without
    handing over the answer. Callers must gate this on
    settings.submit_feedback_level; see that field for the comparability
    caveat. Returns "" when it has nothing useful to add.
    """
    if not pred_res:
        return "Your query returned no rows."
    p_rows, g_rows = len(pred_res), len(gt_res)
    p_cols, g_cols = len(pred_res[0]), len(gt_res[0]) if gt_res else 0
    if p_cols != g_cols:
        return (f"Wrong number of columns: you returned {p_cols}, the expected answer has "
                f"{g_cols}. Row count {'matches' if p_rows == g_rows else f'is {p_rows} vs {g_rows}'}.")
    if p_rows != g_rows:
        return (f"Wrong number of rows: you returned {p_rows}, the expected answer has {g_rows}. "
                f"Column count matches ({p_cols}).")
    if cell is not None:
        pred_res = [tuple(cell(v) for v in row) for row in pred_res]
        gt_res = [tuple(cell(v) for v in row) for row in gt_res]
    if sorted(pred_res) == sorted(gt_res):
        return (f"Right {p_rows} rows and right {p_cols} columns, but in the wrong ORDER — "
                "add or correct the ORDER BY.")
    # Same columns, permuted. Compared as whole column VECTORS, so this only
    # fires when every column of gold is present exactly once and the rows line
    # up — a permutation is then the only difference left. Worth its own message
    # because the generic one below sends the agent back to the filter and the
    # grain, when all it has to do is reorder the SELECT list. Nothing here
    # names a column or a value, same as every other branch.
    # Counter, not sorted(): on the raw path these are typed values, so two
    # columns of different types (str ticker, float score) would raise TypeError
    # under comparison. Multiset equality needs no ordering.
    pred_cols = Counter(tuple(r[j] for r in pred_res) for j in range(p_cols))
    gt_cols = Counter(tuple(r[j] for r in gt_res) for j in range(g_cols))
    if pred_cols == gt_cols:
        return (f"Right {p_rows} rows with the right values, but your {p_cols} COLUMNS are in the "
                "wrong order — reorder the SELECT list.")
    return (f"Right shape ({p_rows} rows x {p_cols} columns) but the values differ — "
            "check the filter, the aggregation grain, and which columns you projected.")


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
    return [" ".join(t for t in q.split(" ") if t.lower() != "distinct") for q in sql_list]


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
    decimal_places = resolve_decimal_places(conditions)
    pred_raw, gt_raw = pred_res, gt_res
    pred_res = preprocess_results(pred_res, decimal_places)
    gt_res = preprocess_results(gt_res, decimal_places)
    if not pred_res or not gt_res:
        return 0
    score = _compare_rows(pred_res, gt_res, conditions)
    # Same tolerant fallback as the semantic-layer path (ex_base_external_pred),
    # deliberately the same function: grading must not differ by arm, or the
    # lift number measures the grader instead of the semantic layer. The gap it
    # tolerates comes from grading_rel_tolerance_value on both arms (B-20).
    if score == 0 and settings.grading_rel_tolerance:
        score = 1 if _compare_rows_numeric_tolerant(pred_raw, gt_raw, conditions) else 0
    return score


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
    sol_sqls = remove_round(remove_distinct(remove_comments(sol_sqls)))
    gt_res, gt_err, gt_to, _ = execute_queries(sol_sqls, db_name, conn)
    if gt_err or gt_to:
        return 0
    decimal_places = resolve_decimal_places(conditions)
    pred_rounded = preprocess_results(pred_res, decimal_places)
    gt_rounded = preprocess_results(gt_res, decimal_places)
    if not gt_rounded:
        return 0
    if _compare_rows(pred_rounded, gt_rounded, conditions, cell=canonical_cell):
        return 1
    # Merge 2026-08-11: the tolerant fallback arrived from
    # feature/atscale-mcp-semantic-layer ungated, i.e. on for every run. Kept
    # behind grading_rel_tolerance (default false, as it already was here)
    # because it can only turn a 0 into a 1, so leaving it always-on silently
    # raises scores on BOTH arms and makes a totals number non-comparable to
    # every earlier run and to published BIRD-Interact numbers. The flag is
    # recorded in the results deviations block; flip it to adopt the branch's
    # behaviour deliberately rather than as a side effect of a merge.
    if not settings.grading_rel_tolerance:
        return 0
    return 1 if _compare_rows_numeric_tolerant(pred_res, gt_res, conditions) else 0


def grade_raw_submission(pred_sqls, sol_sqls, db_name, conn, conditions=None) -> int:
    """Grade a raw-SQL submission end to end: step 1's cleanup on BOTH sides,
    then ex_base. The whole raw path, in one call.

    THE entry point for grading raw SQL, live or offline. `ex_base` deliberately
    does none of the cleanup — upstream's doesn't either, and dataset-supplied
    test cases call it with their own preparation — so calling it directly is a
    trap: gold keeps its ROUND() while the prediction loses its own, and the two
    are then compared at different precisions. That trap has now been walked
    into twice in offline tools (scripts/regrade_flags.py, then
    scripts/score_dual.py on the same day), and both times it was invisible
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
