#!/usr/bin/env python3
"""Stage 2 of 3: which latent vocabulary collisions did a failing task exercise?

A collision from scripts/vocab_collision.py matters only where both halves are
true on a real task:

  (a) the task's own wording contains the claimed phrase, so the agent was
      steered by it at all; and
  (b) the agent then used one of the colliding objects in the SQL it submitted.

Everything else is a phrase two objects both claim that no task ever put in
front of the agent. Measured on the 0825 run: 300 latent -> 35 live, on 31
failing tasks.

Live is still not causal — the agent may have picked the object gold agrees
with. Stage 3 (collision_causal.py) decides that.

Needs a grading audit (GRADING_AUDIT_PATH) for the run, because that is where
the submitted SQL is recorded. No MCP, no LLM, no re-run.

    python scripts/collision_impact.py <grading_audit.jsonl> [--results-dir results/825_all]
        [--collisions results/vocab_collisions.json] [--arm atscale]
        [--out results/live_collisions.json]
"""
import argparse
import collections
import glob
import json
import os
import re

QUOTED = re.compile(r'"([^"]{2,80})"')


def load_run(results_dir, arm):
    """task_id -> database, and task_id -> phase1_passed, from a split run dir."""
    db_of, passed = {}, {}
    for path in glob.glob(os.path.join(results_dir, f"*_{arm}.json")):
        db = os.path.basename(path)[:-len(f"_{arm}.json")]
        for row in json.load(open(path))["results"]:
            db_of[row["task_id"]] = db
            passed[row["task_id"]] = row["phase1_passed"]
    return db_of, passed


def task_wording(task):
    """Everything the agent was steered by: the question, the follow-up, and the
    ambiguity terms the benchmark itself names as the masked readings."""
    amb = task.get("user_query_ambiguity", {})
    return " ".join([
        task.get("amb_user_query") or "",
        (task.get("follow_up") or {}).get("query") or "",
        " ".join(x.get("term", "") for x in (amb.get("critical_ambiguity") or [])
                 + (amb.get("non_critical_ambiguity") or [])),
    ]).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audit_file", help="the run's grading audit jsonl")
    ap.add_argument("--results-dir", default="results/825_all")
    ap.add_argument("--arm", default="atscale")
    ap.add_argument("--collisions", default="results/vocab_collisions.json")
    ap.add_argument("--data", default="bird-interact-full/bird_interact_data.jsonl")
    ap.add_argument("--out", default="results/live_collisions.json")
    args = ap.parse_args()

    collisions = json.load(open(args.collisions))
    audit = [json.loads(line) for line in open(args.audit_file) if line.strip()]
    tasks = {}
    for line in open(args.data):
        rec = json.loads(line)
        tasks[rec["instance_id"]] = rec
    db_of, _passed = load_run(args.results_dir, args.arm)

    hits = collections.defaultdict(list)
    for row in audit:
        tid = row["task_id"]
        db = db_of.get(tid)
        if not db or db not in collisions or row["passed"]:
            continue
        task = tasks.get(tid)
        if not task:
            continue
        wording = task_wording(task)
        pred = row["pred_sql"] if isinstance(row["pred_sql"], str) else json.dumps(row["pred_sql"])
        used = {m.strip() for m in QUOTED.findall(pred)}
        for phrase, names in collisions[db].items():
            if phrase not in wording:
                continue
            picked = [n for n in names if n in used]
            if picked:
                hits[(db, phrase, tuple(names))].append((tid, row["phase"], picked[0]))

    rows = sorted(hits.items(), key=lambda kv: -len({t for t, _, _ in kv[1]}))
    n_tasks = len({t for v in hits.values() for t, _, _ in v})
    print(f"{len(rows)} live collisions, touching {n_tasks} failing tasks\n")
    for (db, phrase, names), seen in rows:
        print(f'{db}  "{phrase}"')
        print(f"    claimed by {len(names)}: " + " | ".join(names))
        print("    agent picked: " + ", ".join(sorted({p for _, _, p in seen})))
        print("    on failing tasks: " + ", ".join(sorted({t for t, _, _ in seen})))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({f"{db}|{phrase}": {"names": list(names),
                                      "tasks": sorted({t for t, _, _ in seen})}
                   for (db, phrase, names), seen in rows}, f, indent=1)
    print(f"\n-> {args.out}. Live is not causal: run scripts/collision_causal.py next.")


if __name__ == "__main__":
    main()
