"""Build the opaque-name brief (schema.txt, task_brief.json, facts.md) for the obf / obfao arms.

Usage: python scripts/ao/obf_brief.py <bare model dir> <map.json> <dst model dir> <funds facts section file>
Translates the bare brief's schema.txt and facts.md through map.json (lowercase identifiers outside
single-quoted strings, plus sequence names inside nextval('...')), adds the flag column to t09's DDL,
and replaces facts.md's t09 table section with <funds facts section file> (re-measured on the live
table, test rows included). task_brief.json and deleted_ids.txt are copied as is.
"""

import json
import os
import re
import shutil
import sys


def main(src: str, map_path: str, dst: str, funds_section: str) -> None:
    m = json.load(open(map_path))
    ident = {v: k for k, v in m["tables"].items()} | {v: k for k, v in m["columns"].items()}
    word = re.compile(r"\b[a-z_][a-z0-9_]*\b")

    tables = sorted(m["tables"].values(), key=len, reverse=True)

    def seq(name: str) -> str:  # <table>_<column>; table names contain underscores, so match whole names
        t = next(t for t in tables if name.startswith(t + "_") and name[len(t) + 1:] in ident)
        return f"{ident[t]}_{ident[name[len(t) + 1:]]}"

    def tr(text: str) -> str:
        text = re.sub(r"nextval\('(\w+)_seq'", lambda x: f"nextval('{seq(x.group(1))}_seq'", text)
        parts = re.split(r"('(?:[^']|'')*')", text)
        return "".join(p if i % 2 else word.sub(lambda w: ident.get(w.group(0), w.group(0)), p)
                       for i, p in enumerate(parts))

    sb, db = os.path.join(src, "brief"), os.path.join(dst, "brief")
    os.makedirs(db, exist_ok=True)
    schema = tr(open(os.path.join(sb, "schema.txt")).read())
    schema = re.sub(r'(CREATE TABLE "t09" \(\n(?:.*\n)*?)(    PRIMARY KEY)',
                    r"\1c134 smallint NOT NULL DEFAULT 0,\n\2", schema, count=1)
    open(os.path.join(db, "schema.txt"), "w").write(schema)
    for f in ("task_brief.json", "deleted_ids.txt"):
        shutil.copy(os.path.join(sb, f), db)

    facts = tr(open(os.path.join(src, "facts.md")).read())
    facts = facts.replace("exchange_traded_funds_nokeys", "exchange_traded_funds_obf")
    facts = re.sub(r"### t09 \(rows=\d+\)\n(?:.*\n)*?(?=### )", open(funds_section).read().rstrip() + "\n\n",
                   facts, count=1)
    open(os.path.join(dst, "facts.md"), "w").write(facts)
    print("schema t09 has c134:", "c134 smallint" in schema, "| facts t09 replaced:", "c134 |" in facts)


if __name__ == "__main__":
    main(*sys.argv[1:5])
