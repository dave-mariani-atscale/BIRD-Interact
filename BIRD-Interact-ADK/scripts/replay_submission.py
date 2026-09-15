#!/usr/bin/env python3
"""Re-grade a shipped submission JSONL against gold. NO LLM calls, no agent.

This is Tier 1 of the verification package: it takes a `*.repaired.jsonl` exactly as
submitted, re-executes each Query task's predicted SQL against a clone of that task's
template database, and re-grades it under UPSTREAM rules (exact row comparison, no
corrections) - the verdict the BIRD evaluator should reach.

Nothing of ours takes part in the verdict except the SQL text, so the result is
exactly reproducible on the verifier's own warehouse. That is why this, and not the
full re-run, is the number to quote.

It differs from `export_submission.py --validate` in one respect that matters for a
third party: that command starts from one of OUR results files and re-exports it.
This starts from the submitted JSONL alone, which is the only artifact a verifier
actually has. The grading itself is the same code path - `validate_rows` - deliberately
reused rather than reimplemented, so the two cannot drift.

    PYTHONPATH=. .venv-adk/bin/python scripts/replay_submission.py \
        submissions/leaderboard_sonnet_20260912_atscale_run02_*.repaired.jsonl \
        --report out/run02.replay.json

Management tasks are not re-gradable offline (phase 2 needs the phase-1 database
state), so their recorded verdict is carried through - in a leaderboard-mode run that
verdict was already produced by the raw path under upstream rules. `category` on each
row says which path a task took.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from shared.config import settings                                    # noqa: E402
from scripts.export_submission import load_tasks, validate_rows       # noqa: E402


def _refuse_if_evaluation_running() -> None:
    """A replay clones every template it touches; an evaluation in progress is
    cloning those same templates per task. Running both at once corrupts neither
    silently - it just produces nonsense - so fail loudly instead.

    Per-task scratch databases are named `{db}__{task_id}` by create_task_db, so
    their presence is the signal.
    """
    try:
        from shared.db_utils import _get_or_init_pool
        pool = _get_or_init_pool("postgres")
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM pg_database "
                    "WHERE datname LIKE '%%\\_\\_%%' AND datname NOT LIKE '%%\\_\\_val%%'"
                )
                n = cur.fetchone()[0]
        finally:
            pool.putconn(conn)
    except Exception:  # noqa: BLE001 - if we cannot check, do not block the verifier
        return
    if n:
        sys.exit(
            f"REFUSING: {n} per-task scratch database(s) are present, which means an "
            "evaluation is in progress. It is cloning the same template databases this "
            "replay reads. Wait for it to finish, then re-run."
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("submission", help="a *.repaired.jsonl as submitted")
    ap.add_argument("--data", default=None, help="bird_interact_data.jsonl (default: settings.data_path)")
    ap.add_argument("--report", default=None, help="write the full JSON report here")
    ap.add_argument("--allow-concurrent", action="store_true",
                    help="skip the in-progress-evaluation guard (you should not need this)")
    a = ap.parse_args()

    if not a.allow_concurrent:
        _refuse_if_evaluation_running()

    rows = [json.loads(line) for line in Path(a.submission).read_text().splitlines() if line.strip()]
    if not rows:
        sys.exit(f"FAIL: {a.submission} has no rows")

    tasks = load_tasks(a.data or settings.data_path)
    missing = [r["instance_id"] for r in rows if r["instance_id"] not in tasks]
    if missing:
        sys.exit(
            f"FAIL: {len(missing)} submitted instance_ids are absent from the task file "
            f"(first: {missing[:3]}). The task file needs gold merged in - see "
            "combine_public_with_gt.py."
        )
    if not any(tasks[r["instance_id"]].get("sol_sql") for r in rows):
        sys.exit("FAIL: the task file carries no sol_sql. Merge the ground truth first.")

    n_query = sum(1 for r in rows if r.get("category") == "Query")
    print(f"replaying {len(rows)} rows ({n_query} Query, {len(rows) - n_query} Management) "
          f"from {Path(a.submission).name}")

    result = validate_rows(rows, tasks)

    # What the submission itself claimed, for the side-by-side.
    lp1 = sum(int(bool(r["local_verdict"]["phase1_passed"])) for r in rows)
    lp2 = sum(int(bool(r["local_verdict"]["phase2_passed"])) for r in rows)
    n = len(rows)
    report = {
        "submission": Path(a.submission).name,
        "rows": n,
        "query_tasks": n_query,
        "management_tasks": n - n_query,
        "submitted": {
            "phase1_rate": lp1 / n,
            "phase2_rate": lp2 / n,
            "normalized_reward": 100 * (0.7 * lp1 + 0.3 * lp2) / n,
        },
        "replayed": {k: v for k, v in result.items() if k != "disagreements"},
        "disagreements": result["disagreements"],
    }

    print(f"  submitted  success {100 * lp1 / n:.2f}  reward {report['submitted']['normalized_reward']:.2f}")
    print(f"  replayed   success {100 * result['phase1_rate']:.2f}  reward {result['normalized_reward']:.2f}")
    print(f"  disagreements with the submitted verdict: {result['disagreements_with_live_verdict']}")
    for d in result["disagreements"][:10]:
        print(f"    {d['instance_id']}: submitted {d['local']} -> replayed {d['validated']}"
              + (f"  [{d['notes']}]" if d.get("notes") else ""))

    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(json.dumps(report, indent=2, default=str))
        print(f"  wrote {a.report}")

    # A disagreement is the verifier's finding, not an error: exit 0 so the driver
    # continues and reports all runs together.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
