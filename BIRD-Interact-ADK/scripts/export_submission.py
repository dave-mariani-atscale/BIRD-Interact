#!/usr/bin/env python3
"""Turn a leaderboard-mode results file into a BIRD-Interact submission.

The disclosure document that ships with a submission is tracked at
docs/leaderboard-submission-methodology.md (submissions/ is gitignored);
copy it into the bundle when zipping.

The BIRD-Interact submission guidelines (a-Interact, prediction-file mode) ask
for one JSONL row per task with `instance_id`, `subtask_1_predicted_sql`,
`subtask_2_predicted_sql` and a `prompt_flow` (every prompt and response with
the model that produced it), plus per action the `action`, `action_cost`,
`remaining_budget` and token counts. The BIRD team executes the predicted SQL
on THEIR PostgreSQL, so it must be Postgres SQL:

  * Query tasks on a semantic-layer backend submit logical SQL, which cannot run
    there. The harness records, on every graded submission, the OUTBOUND SQL
    the AtScale engine dispatched for that execution (db_environment/server.py,
    leaderboard mode only). That is what goes in the file. Multi-statement
    outbounds are joined with ";\\n" and flagged; a submission whose outbound
    could not be fetched falls back to the logical SQL and is flagged, because
    it will not execute on the evaluator.
  * Management tasks (and every task on the raw backend) submitted Postgres SQL
    already; it is carried verbatim.

Which attempt is exported: the PASSING submission of each phase when there is
one, otherwise the last attempt of that phase - the same answer the run was
scored on.

--validate re-grades every exported Query-task SQL the way the BIRD evaluator
will: executed against `<db>_template` next to the gold SQL, compared with the
UPSTREAM rules (no corrections, whatever this process's mode). It reports the
pass rates that grading implies and every task where it disagrees with the live
verdict. Management tasks cannot be re-graded this way (their phase 2 needs the
phase-1 state); their live verdict is used, which in a leaderboard-mode run was
already produced by the raw path under upstream rules. Do not run --validate
while an evaluation is in progress: it reads the template databases the harness
clones per task.

Usage:
    PYTHONPATH=. .venv-adk/bin/python scripts/export_submission.py results/leaderboard_20260912_atscale_run01_*.json --validate
Writes submissions/<results stem>.jsonl and submissions/<results stem>.summary.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")
from shared.config import settings  # noqa: E402

TEAM = "AtScale"
METHOD_DEFAULT = "AtScale Semantic Layer"


def load_tasks(path: str) -> dict:
    tasks = {}
    with open(path) as f:
        for line in f:
            if line.strip():
                t = json.loads(line)
                tasks[t["instance_id"]] = t
    return tasks


def _phase_of(step: dict, seen_p1_pass: bool) -> int:
    if step.get("phase") in (1, 2):
        return int(step["phase"])
    return 2 if seen_p1_pass else 1


def _passed(step: dict) -> bool:
    if "passed" in step:
        return bool(step["passed"])
    return "correct" in str(step.get("result", "")).lower() and "not correct" not in str(step.get("result", "")).lower()


def pick_sql(result: dict, notes: list) -> tuple[str | None, str | None, dict]:
    """(subtask_1_sql, subtask_2_sql, info) for one task result."""
    semantic = (result.get("backend") or "raw") != "raw"
    submits = {1: [], 2: []}
    seen_p1_pass = False
    for s in result.get("tool_trajectory") or []:
        if s.get("tool") != "submit_sql":
            continue
        ph = _phase_of(s, seen_p1_pass)
        submits[ph].append(s)
        if ph == 1 and _passed(s):
            seen_p1_pass = True
    out, info = {}, {"phase1_attempts": len(submits[1]), "phase2_attempts": len(submits[2])}
    for ph in (1, 2):
        cands = submits[ph]
        if not cands:
            out[ph] = None
            continue
        chosen = next((s for s in cands if _passed(s)), cands[-1])
        logical = (chosen.get("args") or {}).get("sql") or ""
        if semantic:
            outbound = chosen.get("outbound_sql")
            if outbound:
                if len(outbound) > 1:
                    notes.append(f"phase{ph}: engine dispatched {len(outbound)} outbound statements; joined")
                sql = ";\n".join(x.rstrip().rstrip(";") for x in outbound)
                # An aggregate table in the outbound SQL means the BIRD evaluator
                # cannot run it: their Postgres has no `aggregates` schema.
                agg = re.search(r'\b(?:"?aggregates"?\.)?"?(as_agg_\w+)"?', sql)
                if agg:
                    notes.append(f"phase{ph}: outbound references aggregate table {agg.group(1)} - "
                                 "run with LEADERBOARD_MODE so run_query carries disable_aggregates")
            else:
                sql = logical
                notes.append(f"phase{ph}: NO OUTBOUND SQL recorded - exporting logical SQL, which the "
                             f"BIRD evaluator cannot execute")
        else:
            sql = logical
        out[ph] = sql
        info[f"phase{ph}_exported_attempt_passed_locally"] = _passed(chosen)
    return out[1], out[2], info


def build_prompt_flow(result: dict, agent_model: str) -> list:
    """Every prompt and response of the run, in order, with the model that
    produced it and - on tool calls - the action, its cost, the budget left and
    the token usage of the model turn that issued it."""
    steps = [s for s in (result.get("tool_trajectory") or [])]
    cursor = 0
    flow = []
    for ev in result.get("adk_events") or []:
        if ev.get("type") == "user_message":
            flow.append({"role": "user", "type": "message", "content": ev.get("message", "")})
            continue
        author = ev.get("author", "")
        usage = ev.get("usage")
        role = "model" if author not in ("user", "system") else author
        for part in (ev.get("content") or {}).get("parts") or []:
            kind = part.get("type")
            if kind == "text":
                entry = {"role": role, "type": "text", "content": part.get("text", "")}
                if role == "model":
                    entry["model"] = agent_model
                if usage:
                    entry["tokens"] = usage
                flow.append(entry)
            elif kind == "function_call":
                name = part.get("name", "")
                # Match this call to its trajectory step (same tool, in order) for
                # the cost and budget the harness charged.
                step = None
                for j in range(cursor, len(steps)):
                    if steps[j].get("tool") == name:
                        step = steps[j]
                        cursor = j + 1
                        break
                entry = {"role": "model", "type": "action", "model": agent_model,
                         "action": name, "action_args": part.get("args") or {}}
                if step is not None:
                    entry["action_cost"] = step.get("cost")
                    entry["remaining_budget"] = step.get("budget_after")
                    if step.get("query_id"):
                        entry["engine_query_id"] = step["query_id"]
                if usage:
                    entry["tokens"] = usage
                flow.append(entry)
            elif kind == "function_response":
                flow.append({"role": "environment", "type": "observation",
                             "action": part.get("name", ""), "content": part.get("response", "")})
    return flow


def export(results_path: str, out_dir: str, data_path: str, validate: bool, method: str) -> dict:
    d = json.load(open(results_path))
    tasks = load_tasks(data_path)
    stem = Path(results_path).stem
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(out_dir) / f"{stem}.jsonl"
    agent_model = d.get("agent_model") or "unknown"
    sim_model = d.get("user_sim_model") or "unknown"
    warnings = Counter()
    rows = []
    if not d.get("leaderboard_mode"):
        print("WARNING: this results file was NOT produced in leaderboard mode - it carries corrected grading "
              "and/or a customised simulator and is not submission-grade. Exporting anyway for inspection.")
    for r in d.get("results", []):
        tid = r.get("task_id")
        t = tasks.get(tid, {})
        notes: list = []
        if r.get("error"):
            notes.append(f"task errored in the run: {str(r['error'])[:200]}")
        sql1, sql2, info = pick_sql(r, notes)
        for n in notes:
            warnings[n.split(":")[1].strip()[:60] if ":" in n else n[:60]] += 1
        rows.append({
            "instance_id": tid,
            "selected_database": r.get("database") or t.get("selected_database"),
            "category": r.get("category") or t.get("category", "Query"),
            "backend": r.get("backend") or d.get("backend"),
            "subtask_1_predicted_sql": sql1,
            "subtask_2_predicted_sql": sql2,
            "agent_model": agent_model,
            "user_simulator_model": sim_model,
            "team": TEAM,
            "method": method,
            "local_verdict": {"phase1_passed": bool(r.get("phase1_passed")),
                              "phase2_passed": bool(r.get("phase2_passed")),
                              "total_reward": r.get("total_reward", 0.0)},
            "budget": {"used": r.get("budget_used"), "remaining": r.get("budget_remaining")},
            "attempts": info,
            "prompt_flow": build_prompt_flow(r, agent_model),
            "notes": notes,
        })
    validated = validate_rows(rows, tasks) if validate else None  # annotates rows first
    with open(out_path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    n = len(rows)
    summary = {
        "results_file": results_path, "submission_file": str(out_path),
        "leaderboard_mode": bool(d.get("leaderboard_mode")), "agent_model": agent_model,
        "user_simulator_model": sim_model, "grading_regime_live": (d.get("deviations") or {}).get("grading_regime"),
        "tasks": n,
        "tasks_by_category": dict(Counter(r["category"] for r in rows)),
        "missing_phase1_sql": sum(1 for r in rows if not r["subtask_1_predicted_sql"]),
        "warnings": dict(warnings),
        "local": {
            "phase1_rate": sum(r["local_verdict"]["phase1_passed"] for r in rows) / n if n else 0,
            "phase2_rate": sum(r["local_verdict"]["phase2_passed"] for r in rows) / n if n else 0,
            "normalized_reward": 100 * sum(float(r["local_verdict"]["total_reward"] or 0) for r in rows) / n if n else 0,
        },
    }
    if validated is not None:
        summary["validated"] = validated
    with open(Path(out_dir) / f"{stem}.summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    return summary


def validate_rows(rows: list, tasks: dict) -> dict:
    """Re-grade every Query task's exported SQL on the template database under
    upstream rules - the verdict the BIRD evaluator should reach."""
    from shared.db_utils import _get_or_init_pool, grade_raw_submission, create_task_db, drop_task_db
    saved = settings.leaderboard_mode
    settings.leaderboard_mode = True  # grading_regime -> "upstream" for the whole check
    # Validate on a CLONE of each template, never the template itself. Two reasons:
    # the template write-guard (shared.db_utils._guard_template_write) fails closed on
    # SQL sqlglot cannot parse, and the engine's outbound SQL is nested derived tables
    # it often cannot parse - which silently scored 19 correct answers as failures the
    # first time this ran; and a clone cannot corrupt the clone source (tracker B-25).
    clones = {}
    for row in rows:
        db = row["selected_database"]
        if row["category"] == "Query" and db and db not in clones:
            clones[db] = create_task_db(db, "val")
    print(f"validating against {len(clones)} template clones")
    try:
        p1 = p2 = 0
        disagreements = []
        skipped_mgmt = 0
        for row in rows:
            t = tasks.get(row["instance_id"], {})
            if row["category"] != "Query":
                skipped_mgmt += 1
                v = row["local_verdict"]
                row["validated_verdict"] = {"phase1_passed": v["phase1_passed"], "phase2_passed": v["phase2_passed"],
                                            "source": "live raw-path verdict (Management task; not re-gradable offline)"}
                p1 += int(v["phase1_passed"]); p2 += int(v["phase2_passed"])
                continue
            db = clones[row["selected_database"]]
            pool = _get_or_init_pool(db)
            conn = pool.getconn()
            try:
                v1 = v2 = False
                sql1 = row["subtask_1_predicted_sql"]
                if sql1:
                    sol = t.get("sol_sql") or []
                    sol = [sol] if isinstance(sol, str) else sol
                    v1 = bool(grade_raw_submission([sql1], sol, db, conn, t.get("conditions") or {}))
                fu = t.get("follow_up") or {}
                sql2 = row["subtask_2_predicted_sql"]
                if v1 and sql2 and fu.get("sol_sql"):
                    sol2 = fu["sol_sql"]
                    sol2 = [sol2] if isinstance(sol2, str) else sol2
                    v2 = bool(grade_raw_submission([sql2], sol2, db, conn, fu.get("conditions") or {}))
            finally:
                pool.putconn(conn)
            row["validated_verdict"] = {"phase1_passed": v1, "phase2_passed": v2, "source": "upstream re-grade on template"}
            lv = row["local_verdict"]
            if v1 != bool(lv["phase1_passed"]) or v2 != bool(lv["phase2_passed"]):
                disagreements.append({"instance_id": row["instance_id"], "local": [lv["phase1_passed"], lv["phase2_passed"]],
                                      "validated": [v1, v2], "notes": row["notes"]})
            p1 += int(v1); p2 += int(v2)
        n = len(rows) or 1
        return {"phase1_rate": p1 / n, "phase2_rate": p2 / n,
                "normalized_reward": 100 * (0.7 * p1 + 0.3 * p2) / n,
                "management_tasks_using_live_verdict": skipped_mgmt,
                "disagreements_with_live_verdict": len(disagreements),
                "disagreements": disagreements[:50]}
    finally:
        settings.leaderboard_mode = saved
        for c in clones.values():
            try:
                drop_task_db(c)
            except Exception:  # noqa: BLE001
                print(f"warning: could not drop validation clone {c}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--out", default="submissions")
    ap.add_argument("--data", default=None, help="bird_interact_data.jsonl (default: settings.data_path)")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--method", default=METHOD_DEFAULT)
    a = ap.parse_args()
    s = export(a.results, a.out, a.data or settings.data_path, a.validate, a.method)
    print(json.dumps({k: v for k, v in s.items() if k != "validated"}, indent=2))
    if "validated" in s:
        v = dict(s["validated"]); dis = v.pop("disagreements")
        print("validated (upstream grader on templates):", json.dumps(v, indent=2))
        for x in dis[:20]:
            print("  disagreement:", json.dumps(x, default=str)[:300])


if __name__ == "__main__":
    main()
