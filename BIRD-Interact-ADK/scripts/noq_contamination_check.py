#!/usr/bin/env python3
"""No-questions arm, plan 7a.2: do the self-authored questions recall the benchmark's?

Counts 6-word runs shared between each self-authored question and the database's real
`amb_user_query` / `follow_up.query` texts. Prints ONLY counts and self-test ids - never a
benchmark word - so running it does not put the real questions in anyone's context. A hit
means drop that self-test question. It catches verbatim recall only, not paraphrase.

Usage: scripts/noq_contamination_check.py <questions.json> [--db labor_certification_applications]
"""
import argparse
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "bird-interact-full" / "bird_interact_data.jsonl"
N = 6


def grams(text):
    w = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {tuple(w[i:i + N]) for i in range(len(w) - N + 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions")
    ap.add_argument("--db", default="labor_certification_applications")
    a = ap.parse_args()

    real = set()
    for line in DATA.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("selected_database") != a.db:
            continue
        real |= grams(r.get("amb_user_query"))
        fu = r.get("follow_up")
        for f in (fu if isinstance(fu, list) else [fu]):
            if isinstance(f, dict):
                real |= grams(f.get("query"))

    qs = json.load(open(a.questions, encoding="utf-8"))
    hits = {q["id"]: len(grams(q["question"]) & real) for q in qs}
    bad = {k: v for k, v in hits.items() if v}
    print(f"{len(qs)} self-test questions checked against {len(real)} benchmark {N}-grams: "
          f"{len(bad)} with overlap")
    for k, v in sorted(bad.items()):
        print(f"  DROP {k}: {v} shared {N}-gram(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
