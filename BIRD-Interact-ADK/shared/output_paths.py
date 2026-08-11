"""Run-stamped output paths for evaluation results.

Every run writes to its own file so runs stay comparable. Without this a
re-run silently overwrites the previous results, which makes a
before/after comparison impossible after the fact -- the earlier numbers
are simply gone, and a small score delta can't be told apart from
run-to-run variance.
"""

from datetime import datetime
from pathlib import Path

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def timestamped_output_path(output_path: str, timestamp: str | None = None) -> str:
    """Insert `_<timestamp>` before `output_path`'s extension.

    results/eval_atscale.json -> results/eval_atscale_20260806_173000.json

    Sortable, so a plain directory listing is in run order. Call ONCE per
    run and reuse the result: callers that save incrementally must keep
    writing to the same file rather than re-stamping per save.

    Idempotent-ish guard: a path already ending in a timestamp of this
    exact shape is returned unchanged, so wrapping twice (e.g. a caller
    that stamps, then passes the stamped path to a helper that also
    stamps) doesn't accumulate suffixes.
    """
    p = Path(output_path)
    stem = p.stem
    if _ends_with_timestamp(stem):
        return str(p)
    ts = timestamp or datetime.now().strftime(TIMESTAMP_FORMAT)
    return str(p.with_name(f"{stem}_{ts}{p.suffix}"))


def _ends_with_timestamp(stem: str) -> bool:
    parts = stem.rsplit("_", 2)
    if len(parts) < 3:
        return False
    date_part, time_part = parts[-2], parts[-1]
    if not (len(date_part) == 8 and len(time_part) == 6):
        return False
    if not (date_part.isdigit() and time_part.isdigit()):
        return False
    try:
        datetime.strptime(f"{date_part}_{time_part}", TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True
