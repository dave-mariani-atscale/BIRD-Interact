"""Database utilities ported from BIRD-Interact evaluation code."""

import json
import logging
import math
import os
import re
import subprocess
import threading
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
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


def perform_query(query: str, db_name: str, conn=None):
    MAX_ROWS = 10000
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


def _drop_and_create_db(db_name: str, template_db: str):
    """Drop db_name (if exists) and recreate from template_db."""
    args, env_vars = _pg_env()
    close_pool(db_name)
    subprocess.run(
        ["psql", *args, "-d", "postgres", "-c",
         f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"],
        check=True, env=env_vars, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["dropdb", "--if-exists", *args, db_name],
        check=True, env=env_vars, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["createdb", *args, db_name, "--template", template_db],
        check=True, env=env_vars, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def reset_and_restore_database(db_name: str):
    template_db = f"{db_name}_template"
    _drop_and_create_db(db_name, template_db)


def create_task_db(base_db: str, task_id: str, template: str = None) -> str:
    """Create a per-task DB copy. Returns task DB name.

    Args:
        base_db: Base database name (used for naming the task DB).
        task_id: Task identifier (sanitized for DB naming).
        template: Template DB to copy from. Defaults to {base_db}_template.
    """
    safe_id = task_id.replace("-", "_").replace(".", "_")
    task_db = f"{base_db}__{safe_id}"
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


def process_decimals_recursive(item, decimal_places: int):
    quantizer = Decimal(1).scaleb(-decimal_places)
    if isinstance(item, Decimal):
        return item.quantize(quantizer, rounding=ROUND_HALF_UP)
    elif isinstance(item, float):
        return round(item, decimal_places)
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
    not directly comparable to published numbers.
    """
    dp = (conditions or {}).get("decimal")
    return dp if isinstance(dp, int) and dp >= 0 else 2


def canonical_cell(value) -> str:
    """Render a cell for cross-source string comparison.

    Postgres and a semantic layer spell the same number differently — 186709472
    vs 186709472.0, Decimal('6.90') vs 6.9 — so str() alone reports equal values
    as unequal. Numerics collapse to one fixed-point form.

    String values are case-folded. Gold SQL frequently wraps a text column in
    LOWER(...) (e.g. `LOWER(pm.pnlkind)`) that the agent has no way to see or
    replicate — a semantic layer's dimension attribute returns its own stored
    display casing (e.g. "Bifacial"), not gold's ad-hoc lowercased form
    ("bifacial"). Confirmed live: a submission with numerically-correct values
    to ~10 significant digits failed outright on this alone. Case-folding only
    matters for genuinely case-varying gold conventions the agent can't
    predict; it doesn't paper over an actually-wrong answer.

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
    return str(value).lower()


def _ordered_match_tolerating_ties(pred_res, gt_res) -> bool:
    """Ordered-list comparison that tolerates rows tied on the (assumed) sort
    column landing in a different relative order between two engines.

    Gold SQL and a semantic layer are two different execution engines with no
    shared tie-breaking convention — SQL never guarantees a stable order among
    rows equal on the ORDER BY expression, and rounding to the task's decimal
    precision makes ties far more likely than the underlying raw data would
    suggest. Confirmed live: gold's own 336-row result for one task had 8
    tied pairs after rounding, with neither gold's nor the agent's query
    supplying a secondary tiebreaker — an exact-order comparison fails on
    these even when every value is correct.

    Heuristic: assume the LAST column is the sort key (true for every
    "label, value ORDER BY value" query shape seen so far — the dominant
    style in this benchmark). Group GOLD rows into consecutive runs sharing
    that column's value, then verify the PREDICTED rows occupying that same
    index range form the identical set (order within the tied group doesn't
    matter), and that groups appear in the same overall sequence. Falls back
    to an exact match on any structural mismatch (row count, or a tie-group
    heuristic that doesn't hold for this shape) rather than silently passing.
    """
    if len(pred_res) != len(gt_res):
        return False
    if not gt_res:
        return True
    groups = []
    for row in gt_res:
        key = row[-1]
        if groups and groups[-1][0] == key:
            groups[-1][1].append(row)
        else:
            groups.append((key, [row]))
    idx = 0
    for _key, group_rows in groups:
        n = len(group_rows)
        if set(pred_res[idx:idx + n]) != set(group_rows):
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


def _values_close(a, b, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    """Numeric values within a tight relative tolerance count as equal;
    everything else falls back to case-folded string equality (same rule
    canonical_cell applies to non-numerics)."""
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
    groups = []
    for row in gt_res:
        key = row[-1]
        if groups and _values_close(groups[-1][0], key):
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
    That argument doubles as "are we on the cross-source (semantic-layer)
    path", since it's the only place a tie-tolerant order comparison is
    needed — the raw path executes both sides on the same engine, where ties
    resolve identically for identical query text.
    """
    if cell is not None:
        pred_res = [tuple(cell(v) for v in row) for row in pred_res]
        gt_res = [tuple(cell(v) for v in row) for row in gt_res]
    if conditions and conditions.get("order", False):
        if pred_res == gt_res:
            return 1
        if cell is not None and _ordered_match_tolerating_ties(pred_res, gt_res):
            return 1
        return 0
    return 1 if set(pred_res) == set(gt_res) else 0


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
                    processed_row.append(json.dumps(pi, sort_keys=True))
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
    pred_res = preprocess_results(pred_res, decimal_places)
    gt_res = preprocess_results(gt_res, decimal_places)
    if not pred_res or not gt_res:
        return 0
    return _compare_rows(pred_res, gt_res, conditions)


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
    the class of mismatch this fallback exists to see past.
    """
    if not pred_res or not sol_sqls:
        return 0
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
    return 1 if _compare_rows_numeric_tolerant(pred_res, gt_res, conditions) else 0


def test_case_default(pred_sqls, sol_sqls, db_name, conn, conditions=None):
    pred_sqls = remove_round(remove_distinct(remove_comments(pred_sqls)))
    sol_sqls = remove_round(remove_distinct(remove_comments(sol_sqls)))
    result = ex_base(pred_sqls, sol_sqls, db_name, conn, conditions)
    assert result == 1, f"ex_base returned {result} but expected 1."
    return result
