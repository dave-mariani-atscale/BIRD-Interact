#!/usr/bin/env python3
"""Assemble the F1 (design) input bundle for an arm build into files that each fit one Read.

Usage: scripts/f1_inputs.py <model_dir> <generate_output.md> <out_dir>

Writes <out_dir>/f1_inputs_a.md (generator notes, deleted ids, the user question wordings, KB)
and <out_dir>/f1_inputs_b.md (column meanings, schema). facts.md stays its own file. Each output
is kept under ~22k tokens (chars/3.3) so a single Read returns it whole; the script fails loudly
otherwise. Only amb_user_query is taken from task_brief.json - nothing else in that file is copied.
"""
import json, sys, os

LIMIT_TOKENS = 22000

def tokens(s): return len(s) / 3.3

def main(model_dir, gen_out, out_dir):
    b = os.path.join(model_dir, "brief")
    tb = json.load(open(os.path.join(b, "task_brief.json")))
    qs = "\n".join(f"- {t['instance_id']}: {t['amb_user_query']}" for t in tb["tasks"])
    a = (f"# F1 inputs (a): generator notes, withheld ids, user question wordings, knowledge base\n\n"
         f"## Generator output notes\n\n{open(gen_out).read()}\n\n"
         f"## deleted_ids.txt\n\n```\n{open(os.path.join(b,'deleted_ids.txt')).read()}```\n\n"
         f"## User question wordings (amb_user_query only; vocabulary for names and descriptions)\n\n{qs}\n\n"
         f"## kb.jsonl\n\n```\n{open(os.path.join(b,'kb.jsonl')).read()}```\n")
    bb = (f"# F1 inputs (b): column meanings and schema\n\n"
          f"## column_meaning_base.json\n\n```\n{open(os.path.join(b,'column_meaning_base.json')).read()}```\n\n"
          f"## schema.txt\n\n```\n{open(os.path.join(b,'schema.txt')).read()}```\n")
    os.makedirs(out_dir, exist_ok=True)
    for name, body in (("f1_inputs_a.md", a), ("f1_inputs_b.md", bb)):
        p = os.path.join(out_dir, name); open(p, "w").write(body)
        t = tokens(body); print(f"{p}: {len(body)} chars, ~{int(t)} tokens")
        if t > LIMIT_TOKENS: sys.exit(f"{name} exceeds {LIMIT_TOKENS} tokens; split it")
    f = os.path.join(model_dir, "facts.md")
    if os.path.exists(f): print(f"{f}: {os.path.getsize(f)} chars, ~{int(tokens(open(f).read()))} tokens (read separately)")

if __name__ == "__main__":
    main(*sys.argv[1:4])
