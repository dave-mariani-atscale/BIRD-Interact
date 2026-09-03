#!/usr/bin/env python3
"""Stage 1 of 3: which question wordings does more than one model object claim?

The households/Zone defect and the mental_health twin family generalise to one
shape: an object's description asserts the phrasing a user would reach for, a
SECOND object asserts the same phrasing, and the agent picks whichever it read
last. `utilities/twin_audit.py` in the models repo pairs objects that publish the
same QUANTITY at two grains. This pairs them by the WORDS they claim, whatever
they compute — a different and larger family.

Two forms carry a claim in these models, and both are the model telling the agent
which words mean it:

  * the comma-run opener - "How many artifacts, number of artifacts, number of
    items, artifact count."
  * any phrase in quotes - the '"by zone" and "location tag" questions' pattern.

A collision here is latent, not a defect. Stage 2 (collision_impact.py) keeps
only the ones a failing task actually exercised; stage 3 (collision_causal.py)
keeps only the ones where gold disagrees with the agent's pick. Measured 0825:
300 latent -> 35 live -> 2 causal, which is why all three stages exist.

Reads the models repo only. No MCP, no LLM, no benchmark run.

    python scripts/vocab_collision.py [--databases a,b] [--models-repo PATH]
                                      [--out results/vocab_collisions.json]
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

# Words that carry no claim on their own, so a "phrase" made only of them is noise.
STOP = set("the a an of and or to for in on with by is are be its it that this "
           "as at from all any each per".split())


def objects(model_dir):
    """(unique_name, object_type, description) for every named object in a model.

    Walks the YAML rather than reading one directory, because a description can
    hang off a metric, a calculation, a dimension, a level attribute or a
    secondary attribute, and all five reach the agent through explore_columns.
    """
    out = []

    def walk(node, kind=None):
        if isinstance(node, dict):
            name, desc = node.get("unique_name"), node.get("description")
            if name and desc:
                out.append((name, node.get("object_type") or kind or "attribute", desc))
            for value in node.values():
                walk(value, node.get("object_type") or kind)
        elif isinstance(node, list):
            for value in node:
                walk(value, kind)

    for path in glob.glob(os.path.join(model_dir, "*", "*.yml")):
        try:
            walk(yaml.safe_load(open(path, errors="ignore")))
        except Exception:
            continue          # a model that will not parse is the build's problem, not this audit's
    return out


def claims(description):
    """The question wordings a description asserts it owns."""
    got = set()
    for quoted in re.findall(r'["‘’“”\']([a-z][a-z0-9 \-]{6,60})'
                             r'["‘’“”\']', description, re.I):
        got.add(quoted.lower().strip())
    head = description.split(".")[0]
    if head.count(",") >= 2:          # a comma-run opener, not prose that happens to have a comma
        for part in head.split(","):
            phrase = re.sub(r"^\s*(?:and|or)\s+", "", part.strip().lower())
            phrase = re.sub(r"[^a-z0-9 \-]", "", phrase).strip()
            if 2 <= len(phrase.split()) <= 6 and not set(phrase.split()) <= STOP:
                got.add(phrase)
    return {g for g in got if len(g) > 8}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--databases", help="comma-separated; default every model in the repo")
    ap.add_argument("--models-repo", default=DEFAULT_MODELS)
    ap.add_argument("--out", default="results/vocab_collisions.json")
    args = ap.parse_args()

    dbs = (args.databases.split(",") if args.databases else
           sorted(d for d in os.listdir(args.models_repo)
                  if os.path.isdir(os.path.join(args.models_repo, d))
                  and not d.startswith(".") and d != "utilities"))

    everything = {}
    for db in dbs:
        model_dir = os.path.join(args.models_repo, db)
        if not os.path.isdir(model_dir):
            print(f"{db:34s} no model in {args.models_repo} — skipped")
            continue
        objs = objects(model_dir)
        by_phrase = collections.defaultdict(set)
        for name, _kind, desc in objs:
            for phrase in claims(desc):
                by_phrase[phrase].add(name)
        colliding = {p: sorted(ns) for p, ns in by_phrase.items() if len(ns) > 1}
        everything[db] = colliding
        print(f"{db:34s} objects {len(objs):4d}  claimed phrases {len(by_phrase):4d}  "
              f"COLLIDING {len(colliding):3d}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(everything, f, indent=1)
    total = sum(len(v) for v in everything.values())
    print(f"\n{total} latent collisions across {len(everything)} models -> {args.out}")
    print("Latent is not a defect. Run scripts/collision_impact.py next.")


if __name__ == "__main__":
    main()
