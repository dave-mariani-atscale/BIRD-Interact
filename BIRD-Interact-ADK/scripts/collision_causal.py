#!/usr/bin/env python3
"""Stage 3 of 3: does a live vocabulary collision actually EXPLAIN the failure?

A collision is causal only if gold reaches for the RIVAL object's source column
and not the one the agent picked. If gold uses the agent's pick, the agent read
the competing descriptions and still chose correctly — the point was lost
somewhere else, and rewording those descriptions recovers nothing.

This is the stage that stops the audit from over-claiming. Measured on the 0825
run: 35 live collisions on 31 failing tasks, of which **2** survive here. That
result is why the description-disambiguation lever looks smaller than it does
from the latent count alone.

The test is a proxy, and its limits are worth stating: it resolves each model
object to the warehouse columns it names (plus one level of expression
reference) and looks for those column names in gold's text. A gold that reaches
the same column through a view, or an object whose only distinguishing feature
is a filter rather than a column, is undecidable here and is reported as latent
rather than causal — the audit under-claims by construction.

    python scripts/collision_causal.py <grading_audit.jsonl>
        [--live results/live_collisions.json] [--results-dir results/825_all]
        [--arm atscale] [--models-repo PATH] [--out results/causal_collisions.json]
"""
import argparse
import collections
import glob
import json
import os
import re

import yaml

DEFAULT_MODELS = os.environ.get(
    "BIRD_MODELS_REPO",
    "/Users/dianne/go/src/github.com/AtScaleInc/bird-atscale-models")
QUOTED = re.compile(r'"([^"]{2,80})"')
EXPR_REF = re.compile(r"\[(?:Measures|[^\]]+)\]\.\[([^\]]+)\]")


def object_columns(model_dir, max_depth=4):
    """unique_name -> set of warehouse column names it resolves to.

    Calculations reference other measures rather than columns, so references are
    followed to a fixed point (capped, since a model can define a cycle).
    """
    resolved = collections.defaultdict(set)

    def walk(node):
        if isinstance(node, dict):
            name = node.get("unique_name")
            if name:
                for key in ("column", "name_column"):
                    if isinstance(node.get(key), str):
                        resolved[name].add(node[key])
                for key in ("key_columns", "columns"):
                    value = node.get(key)
                    if isinstance(value, list):
                        resolved[name].update(v for v in value if isinstance(v, str))
                if isinstance(node.get("expression"), str):
                    for ref in EXPR_REF.findall(node["expression"]):
                        resolved[name].add("@" + ref)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in glob.glob(os.path.join(model_dir, "*", "*.yml")):
        try:
            walk(yaml.safe_load(open(path, errors="ignore")))
        except Exception:
            continue

    for _ in range(max_depth):
        changed = False
        for name, cols in resolved.items():
            refs = {c for c in cols if c.startswith("@")}
            if not refs:
                continue
            cols.difference_update(refs)
            for ref in refs:
                new = resolved.get(ref[1:], set())
                if not new <= cols:
                    changed = True
                cols.update(new)
        if not changed:
            break
    return {n: {c for c in cols if not c.startswith("@")} for n, cols in resolved.items()}


def mentions(gold_lower, columns):
    return any(re.search(r"\b" + re.escape(c.lower()) + r"\b", gold_lower)
               for c in columns if len(c) > 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audit_file")
    ap.add_argument("--live", default="results/live_collisions.json")
    ap.add_argument("--results-dir", default="results/825_all")
    ap.add_argument("--arm", default="atscale")
    ap.add_argument("--models-repo", default=DEFAULT_MODELS)
    ap.add_argument("--out", default="results/causal_collisions.json")
    args = ap.parse_args()

    live = json.load(open(args.live))
    by_task = collections.defaultdict(list)
    for line in open(args.audit_file):
        if line.strip():
            row = json.loads(line)
            by_task[row["task_id"]].append(row)

    columns_cache, causal, latent = {}, [], []
    for key, entry in live.items():
        db, phrase = key.split("|", 1)
        if db not in columns_cache:
            columns_cache[db] = object_columns(os.path.join(args.models_repo, db))
        model_columns = columns_cache[db]
        for tid in entry["tasks"]:
            for row in by_task.get(tid, []):
                if row["passed"] or row["phase"] != 1:
                    continue
                gold = " ".join(row["sol_sql"]) if isinstance(row["sol_sql"], list) else (row["sol_sql"] or "")
                gold_lower = gold.lower()
                pred = row["pred_sql"] if isinstance(row["pred_sql"], str) else json.dumps(row["pred_sql"])
                used = {m.strip() for m in QUOTED.findall(pred)}
                picked = [n for n in entry["names"] if n in used]
                if not picked:
                    continue
                picked_cols = {c for n in picked for c in model_columns.get(n, ())}
                gold_uses_picked = mentions(gold_lower, picked_cols)
                rivals = []
                for other in (n for n in entry["names"] if n not in used):
                    other_cols = model_columns.get(other, set())
                    if other_cols and mentions(gold_lower, other_cols) and not (other_cols & picked_cols):
                        rivals.append(other)
                record = dict(db=db, phrase=phrase, task=tid, picked=picked,
                              rival=rivals, gold_uses_picked=gold_uses_picked)
                (causal if rivals and not gold_uses_picked else latent).append(record)
                break

    seen, out = set(), []
    for record in causal:
        key = (record["db"], record["task"], record["phrase"])
        if key not in seen:
            seen.add(key)
            out.append(record)

    print(f"CAUSAL: gold uses the rival's column, not the agent's pick — {len(out)} findings\n")
    for record in sorted(out, key=lambda r: (r["db"], r["task"])):
        print(f"{record['db']}  {record['task']}")
        print(f"    phrase claimed by both  : \"{record['phrase']}\"")
        print(f"    agent used              : {', '.join(record['picked'])}")
        print(f"    gold's column belongs to: {', '.join(record['rival'])}")
    print(f"\nlatent (gold agrees with the agent's pick, or undecidable): {len(latent)}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
