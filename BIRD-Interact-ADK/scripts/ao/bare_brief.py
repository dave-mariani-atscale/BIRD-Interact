"""Build the DDL-only brief and facts.md for the bare / bareao arms.

Usage: python scripts/ao/bare_brief.py <src model dir> <dst model dir>
<src> is a B2-style model folder (brief/ + facts.md); <dst> gets:
  brief/schema.txt        FOREIGN KEY lines removed (PRIMARY KEY kept)
  brief/task_brief.json   copied (f1_inputs.py reads amb_user_query only)
  brief/deleted_ids.txt   empty (there is no KB to withhold from)
  facts.md                sections 1, 2, 4a only, restricted to the 15 BIRD tables;
                          join cardinalities (3) and every KB section (4b, 5, 6) dropped.
No kb.jsonl, no column_meaning_base.json.
"""

import os
import re
import shutil
import sys

KEEP = {"1", "2", "4a"}


def main(src: str, dst: str) -> None:
    sb, db = os.path.join(src, "brief"), os.path.join(dst, "brief")
    os.makedirs(db, exist_ok=True)
    schema = open(os.path.join(sb, "schema.txt")).read()
    tables = set(re.findall(r'"?CREATE"? TABLE "?(\w+)', schema, re.I))
    lines = schema.splitlines(keepends=True)
    kept = [ln for ln in lines if not re.search(r"FOREIGN\"? KEY", ln, re.I)]
    open(os.path.join(db, "schema.txt"), "w").write("".join(kept))
    shutil.copy(os.path.join(sb, "task_brief.json"), db)
    open(os.path.join(db, "deleted_ids.txt"), "w").write("")

    facts = open(os.path.join(src, "facts.md")).read()
    parts = re.split(r"(?m)^(?=## )", facts)
    out = [
        "# facts.md - exchange_traded_funds (live warehouse, schema public)\n\n"
        "Measured against Postgres localhost:5433 database exchange_traded_funds_nokeys "
        f"({len(tables)} tables, no foreign-key constraints). Brief: schema.txt, task_brief.json.\n"
        "The live tables funds/performance/risk_metrics carry BOTH flat typed columns and the JSONB "
        "twins that schema.txt shows.\n\n"
    ]
    for p in parts[1:]:
        num = re.match(r"## (\w+)\.", p).group(1)
        if num not in KEEP:
            continue
        if num == "1":
            subs = re.split(r"(?m)^(?=### )", p)
            p = subs[0] + "".join(
                s for s in subs[1:] if re.match(r"### (\w+)", s).group(1) in tables
            )
        out.append(p)
    open(os.path.join(dst, "facts.md"), "w").write("".join(out).rstrip() + "\n")
    print(f"schema: {len(lines) - len(kept)} FK lines dropped; tables {len(tables)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
