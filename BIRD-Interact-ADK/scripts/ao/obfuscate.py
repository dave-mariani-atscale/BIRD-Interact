"""Build an obfuscated copy of a warehouse: opaque table and column names, plus the matching query log.

Usage: python scripts/ao/obfuscate.py <columns.tsv> <constraints.tsv> <queries.csv> <out dir>
  columns.tsv      `table<TAB>column` for every public column (psql -At -F$'\\t' output)
  constraints.tsv  `table<TAB>constraint` for every public constraint
Writes to <out dir>:
  map.json         {"tables": {opaque: original}, "columns": {opaque: original}}
  rename.sql       renames columns, constraints (and so their indexes) and tables; drops public
                   functions and triggers (their names and bodies carry business meaning)
  queries_obf.csv  the query log with every table/column identifier outside single-quoted strings
                   replaced by its opaque name (JSON keys inside quotes are data, left as is)
Column names are unique across the ETF tables, so one global column map suffices; the script
fails if that ever stops being true.
"""

import csv
import json
import re
import sys
from pathlib import Path


def main(cols_tsv: str, cons_tsv: str, queries: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cols = [ln.split("\t") for ln in Path(cols_tsv).read_text().splitlines() if ln.strip()]
    cons = [ln.split("\t") for ln in Path(cons_tsv).read_text().splitlines() if ln.strip()]
    tables = sorted({t for t, _ in cols})
    names = [c for _, c in cols]
    assert len(names) == len(set(names)), "column names repeat across tables; need a per-table map"
    tmap = {t: f"t{i:02d}" for i, t in enumerate(tables, 1)}
    cmap = {c: f"c{i:03d}" for i, c in enumerate(sorted(names), 1)}
    (out / "map.json").write_text(json.dumps(
        {"tables": {v: k for k, v in tmap.items()}, "columns": {v: k for k, v in cmap.items()}}, indent=1))

    sql = ["BEGIN;",
           "DO $$ DECLARE r record; BEGIN",
           "  FOR r IN SELECT tgname, tgrelid::regclass AS t FROM pg_trigger WHERE NOT tgisinternal LOOP",
           "    EXECUTE format('DROP TRIGGER %I ON %s', r.tgname, r.t); END LOOP;",
           "  FOR r IN SELECT p.oid::regprocedure AS f FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace LOOP",
           "    EXECUTE format('DROP ROUTINE %s CASCADE', r.f); END LOOP;",
           "END $$;"]
    sql += [f'ALTER TABLE public."{t}" RENAME COLUMN "{c}" TO {cmap[c]};' for t, c in cols]
    per_table: dict[str, int] = {}
    for t, k in cons:
        per_table[t] = per_table.get(t, 0) + 1
        sql.append(f'ALTER TABLE public."{t}" RENAME CONSTRAINT "{k}" TO {tmap[t]}_k{per_table[t]};')
    sql += [f'ALTER TABLE public."{t}" RENAME TO {tmap[t]};' for t in tables]
    sql.append("COMMIT;")
    (out / "rename.sql").write_text("\n".join(sql) + "\n")

    ident = {**tmap, **cmap}
    word = re.compile(r"\b[A-Za-z_]\w*\b")

    def rewrite(q: str) -> str:
        parts = re.split(r"('(?:[^']|'')*')", q)  # odd parts are single-quoted literals
        return "".join(p if i % 2 else word.sub(lambda m: ident.get(m.group(0).lower(), m.group(0)), p)
                       for i, p in enumerate(parts))

    with open(queries) as f, open(out / "queries_obf.csv", "w", newline="") as g:
        r, w = csv.DictReader(f), None
        for row in r:
            if w is None:
                w = csv.DictWriter(g, fieldnames=r.fieldnames)
                w.writeheader()
            row["query_text"] = rewrite(row["query_text"])
            w.writerow(row)
    print(f"tables {len(tmap)}, columns {len(cmap)}, constraints {len(cons)}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
