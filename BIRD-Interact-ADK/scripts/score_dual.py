#!/usr/bin/env python
"""Score a finished run under BOTH grading regimes: as-run, and upstream-strict.

    python scripts/score_dual.py results/<run>.json [--regime NAME ...]

Every grading flag this repo adds is a deviation, and a score is only
interpretable next to the regime that produced it. This re-scores a completed
run offline from the grading audit — no LLM calls, no MCP replay, local
Postgres only — so a run can always be reported as a pair:

    as-run          what the .env flags gave
    upstream        every deviation off, i.e. the published leaderboard's rules

Requires GRADING_AUDIT_PATH to have been set for the run, and the run's results
JSON to carry `run_started` / `run_finished` (both are on by default since
2026-08-14). Audit rows are attributed to a run by that window, the same way
llm_usage rows are — sound because runs are sequential (see --repeat).

The trajectory is held FIXED, which makes this answer "what would the grader
have said about the SQL the agent actually wrote". Two consequences worth
stating when quoting a number:

  * a regime that passes MORE is a LOWER bound. If it flips a phase-1 attempt
    to a pass, the live agent would have gone on to attempt phase 2, and that
    phase-2 submission does not exist to be scored.
  * a regime that passes FEWER is exact.
"""
import argparse
import atexit
import collections
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
from shared.config import settings          # noqa: E402
from shared import db_utils as U            # noqa: E402

# Every regime is a full flag set, never a diff, so a printed number can be
# traced to exactly one row of this table.
REGIMES = {
    "upstream": dict(tie=False, decimal=False, casefold=False, rel=False,
                     rel_value=1e-6, lint=False),
    "as-run": None,     # filled in from the results JSON's own deviations block
    "platform": dict(tie=True, decimal=True, casefold=True, rel=True,
                     rel_value=1e-6, lint=True),
}


def apply(regime):
    settings.grading_tie_tolerance = regime["tie"]
    settings.grading_honor_decimal = regime["decimal"]
    settings.grading_casefold = regime["casefold"]
    settings.grading_rel_tolerance = regime["rel"]
    settings.grading_rel_tolerance_value = regime["rel_value"]
    settings.grading_order_lint = regime["lint"]


def base_conditions(cond):
    """The task's own conditions, with any order-lint lift undone — so each
    regime can decide the lift for itself rather than inheriting the run's."""
    c = dict(cond or {})
    if c.pop("_order_lint", False):
        c["order"] = True
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--regime", action="append", default=None,
                    help="regime to score (repeatable); default upstream + as-run")
    ap.add_argument("--audit", default=None, help="override the audit path")
    args = ap.parse_args()

    res = json.load(open(args.results))
    audit_path = args.audit or res.get("grading_audit_path") or settings.grading_audit_path
    t0, t1 = res.get("run_started"), res.get("run_finished")
    if not t0 or not t1:
        sys.exit(f"{args.results} carries no run_started/run_finished window — it "
                 f"predates the audit stamping, so its rows cannot be told apart "
                 f"from other runs' in {audit_path}.")
    if not audit_path or not os.path.exists(audit_path):
        sys.exit(f"no grading audit at {audit_path!r} — this run was not recorded.")

    rows = []
    for line in open(audit_path):
        d = json.loads(line)
        ts = d.get("ts")
        # No slack either side. Unlike an llm_usage row, which litellm can log
        # from a background task just after a run returns, an audit row is
        # written synchronously inside the submit that produced it, so it is
        # always strictly inside the window. Slack here would only pull in a
        # NEIGHBOURING run's rows — which is exactly what a stray concurrent
        # job did the first time this was tested.
        if ts is None or not (t0 <= ts <= t1):
            continue
        rows.append(d)
    if not rows:
        sys.exit(f"no audit rows inside this run's window in {audit_path}.")
    rows.sort(key=lambda d: d["ts"])

    tasks = {}
    for line in open(settings.data_path):
        d = json.loads(line)
        tasks[d["instance_id"]] = d
    db_of = {t: d.get("selected_database") for t, d in tasks.items()}

    # A run's window should contain that run's submissions and nothing else.
    # Anything else in there means a second run was writing to the same audit at
    # the same time, and every number below is then a mixture of the two.
    ran = {r.get("instance_id") for r in res.get("results", [])}
    strays = sorted({r["task_id"] for r in rows} - ran)
    if strays:
        sys.exit(f"{len(strays)} task(s) appear in this run's audit window but not "
                 f"in its results: {strays[:8]}{'...' if len(strays) > 8 else ''}\n"
                 f"Another run was writing to {audit_path} concurrently. Runs must "
                 f"be sequential (same reason as --repeat and llm_usage); this "
                 f"run cannot be re-scored from a mixed audit.")

    arm = res.get("backend") or rows[0].get("backend")
    dbs = {db_of.get(r["task_id"]) for r in rows} - {None}
    print(f"{args.results}: {len(rows)} graded submissions, arm={arm}, "
          f"databases={sorted(dbs)}")

    # One scratch copy per database; the templates are never touched (B-25).
    scratch, conns = {}, {}
    for db in sorted(dbs):
        scratch[db] = U.create_task_db(db, "scoredual")
        atexit.register(lambda d=scratch[db]: U.drop_task_db(d))
        conns[db] = U.get_connection_for_phase(scratch[db])

    dev = res.get("deviations") or {}
    REGIMES["as-run"] = dict(
        tie=dev.get("grading_tie_tolerance", False),
        decimal=dev.get("grading_honor_decimal", False),
        casefold=dev.get("grading_casefold", False),
        rel=dev.get("grading_rel_tolerance", False),
        rel_value=dev.get("grading_rel_tolerance_value", 1e-6),
        lint=dev.get("grading_order_lint", False),
    )
    wanted = args.regime or ["upstream", "as-run"]
    for name in wanted:
        if name not in REGIMES:
            sys.exit(f"unknown regime {name!r}; choose from {sorted(REGIMES)}")

    scores = {}
    for name in wanted:
        apply(REGIMES[name])
        verdicts = []
        for r in rows:
            db = db_of.get(r["task_id"])
            if db is None:
                verdicts.append((r["task_id"], r["phase"], r.get("attempt", 1), 0))
                continue
            cond = U.apply_order_lint(base_conditions(r["conditions"]),
                                      r["task_id"], r["phase"])
            sol = r["sol_sql"]
            sol = [sol] if isinstance(sol, str) else list(sol)
            try:
                if r["backend"] == "raw":
                    # The live grader resets the task DB before every submission,
                    # so a DML prediction or gold does not leak into the next one.
                    U.reset_task_db(scratch[db], f"{db}_template")
                    conns[db] = U.get_connection_for_phase(scratch[db])
                    pred = r["pred_sql"]
                    pred = [pred] if isinstance(pred, str) else list(pred)
                    v = U.ex_base(U.remove_round(U.remove_distinct(U.remove_comments(pred))),
                                  sol, scratch[db], conns[db], cond)
                else:
                    pred_rows = [tuple(x) for x in (r["pred_rows"] or [])]
                    v = U.ex_base_external_pred(pred_rows, sol, scratch[db],
                                                conns[db], cond)
            except Exception:
                v = 0
            verdicts.append((r["task_id"], r["phase"], r.get("attempt", 1), v))
        scores[name] = verdicts
        print(f"  scored under {name}", file=sys.stderr, flush=True)

    def reward(verdicts):
        """a-interact reward replay, in trajectory order: a phase passed on its
        FIRST submission pays 0.7/0.3, on a retry 0.5/0.2
        (db_environment/server.py:379). The audit records the attempt number the
        live grader assigned, so this is exact rather than a reconstruction."""
        FIRST, RETRY = {1: 0.7, 2: 0.3}, {1: 0.5, 2: 0.2}
        per = collections.defaultdict(float)
        phase_of = collections.defaultdict(lambda: 1)
        done = set()
        for tid, phase, attempt, v in verdicts:
            per.setdefault(tid, 0.0)
            if tid in done or phase != phase_of[tid] or not v:
                continue
            per[tid] += (FIRST if attempt == 1 else RETRY)[phase]
            if phase == 1 and (tasks.get(tid, {}).get("follow_up") or {}).get("sol_sql"):
                phase_of[tid] = 2
            else:
                done.add(tid)
        return per

    n_tasks = len({r["task_id"] for r in rows})
    base_name = wanted[0]
    base = reward(scores[base_name])
    print(f"\n{'regime':<12}{'total':>9}{'mean':>9}{'passes':>9}   vs " + base_name)
    for name in wanted:
        per = reward(scores[name])
        tot = sum(per.values())
        npass = sum(1 for _t, _p, _a, v in scores[name] if v)
        moved = sorted(t for t in per if abs(per[t] - base[t]) > 1e-9)
        delta = "" if name == base_name else (
            f"  {sum(per.values()) - sum(base.values()):+.2f} over {len(moved)} tasks "
            f"{moved if moved else ''}")
        print(f"{name:<12}{tot:>9.2f}{tot / max(n_tasks, 1):>9.4f}{npass:>9}{delta}")

    recorded = (res.get("metrics") or {}).get("total_reward")
    if recorded is not None and "as-run" in wanted:
        got = sum(reward(scores["as-run"]).values())
        flag = "reproduces" if abs(got - recorded) < 1e-6 else "DOES NOT REPRODUCE"
        print(f"\nas-run {flag} the recorded total ({got:.2f} vs {recorded:.2f}). "
              f"A mismatch means the audit and the results JSON disagree — trust "
              f"neither number until it is explained.")


if __name__ == "__main__":
    main()
