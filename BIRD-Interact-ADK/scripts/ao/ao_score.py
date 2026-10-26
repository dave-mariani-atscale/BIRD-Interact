"""Score one AO compile against BIRD gold: joins mechanically, meanings and KB via a judge file.

Usage (from the AO repo):
  uv run python <ADK>/scripts/ao/ao_score.py <ao_db> <gold brief dir> <out dir> [--map map.json]

<gold brief dir> holds the ORIGINAL schema.txt (with FOREIGN KEYs), column_meaning_base.json, kb.jsonl.
--map: {"tables": {opaque: original}, "columns": {opaque: original}} for an obfuscated warehouse;
AO names are translated back to the original names before scoring.

Writes <out>/joins.json + joins.md (recall/precision of AO semantic FKs and of joins AO observed in
the query log, against the schema's 16 FKs) and <out>/judge_input.json: every gold column meaning
next to the AO attribute description for that column, every KB entry, and every AO SqlAttribute and
Term, for a judge to grade (see results/arms_etf_bare/briefs/ao_judge.md).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import ao_render_context as rc  # noqa: E402  (loads the AO env and DAL on import)


def gold_fks(schema: str) -> set[frozenset]:
    out, cur = set(), None
    for ln in schema.splitlines():
        m = re.match(r'"?CREATE"? TABLE "?(\w+)', ln, re.I)
        if m:
            cur = m.group(1).lower()
        m = re.search(r'FOREIGN"? KEY \(\s*"?(\w+)"?\s*\) REFERENCES "?(\w+)"?\s*\(\s*"?(\w+)', ln, re.I)
        if m:
            out.add(frozenset({f"{cur}.{m.group(1).lower()}", f"{m.group(2).lower()}.{m.group(3).lower()}"}))
    return out


def prf(found: set, gold: set) -> dict:
    tp = len(found & gold)
    return {"found": len(found), "correct": tp, "recall": round(tp / len(gold), 3),
            "precision": round(tp / len(found), 3) if found else None,
            "missed": sorted("=".join(sorted(p)) for p in gold - found),
            "wrong": sorted("=".join(sorted(p)) for p in found - gold)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("gold")
    ap.add_argument("out")
    ap.add_argument("--map")
    a = ap.parse_args()
    out, gold = Path(a.out), Path(a.gold)
    out.mkdir(parents=True, exist_ok=True)
    mp = json.load(open(a.map)) if a.map else {"tables": {}, "columns": {}}

    def orig(qualified: str) -> str:
        t, c = qualified.split(".", 1)
        return f"{mp['tables'].get(t, t)}.{mp['columns'].get(c, c)}".lower()

    def deobf(text: str) -> str:  # translate opaque identifiers inside free text / SQL
        names = {**mp["tables"], **mp["columns"]}
        return re.sub(r"\b\w+\b", lambda m: names.get(m.group(0), m.group(0)), text or "") if names else (text or "")

    db_id = rc.store().query_read(
        rc.select(rc.s.catalog_database.c.id).where(rc.s.catalog_database.c.name == a.db))[0]["id"]
    rows = rc.fetch_export_rows([db_id])
    groups = rc.fetch_semantic_fk_join_groups(a.db)
    cols = {str(r["column_id"]): f'{r["table_name"]}.{r["column_name"]}' for r in rows["catalog"]}

    g = gold_fks((gold / "schema.txt").read_text())
    sem = {frozenset({orig(f"{x['source_table_name']}.{x['source_column_name']}"),
                      orig(f"{x['target_table_name']}.{x['target_column_name']}")}) for x in groups}
    obs = {frozenset({orig(x), orig(y)}) for x, y, _ in rc.observed_joins(a.db)}
    joins = {"gold_fks": len(g), "semantic_fk": prf(sem, g), "observed_in_log": prf(obs, g),
             "union": prf(sem | obs, g)}
    (out / "joins.json").write_text(json.dumps(joins, indent=1))
    md = ["| AO source | found | correct | recall | precision |", "|---|---|---|---|---|"]
    md += [f"| {k} | {v['found']} | {v['correct']} | {v['recall']} | {v['precision']} |"
           for k, v in joins.items() if k != "gold_fks"]
    (out / "joins.md").write_text("\n".join(md) + "\n")

    meanings = json.load(open(gold / "column_meaning_base.json"))
    ao_desc = {}
    for t in rows["terms"]:
        for at in t["columns_attributes"]:
            q = cols.get(str(at["column_id"]))
            if q and (at.get("description") or "").strip():
                ao_desc[orig(q)] = deobf(at["description"])
    columns = []
    for key, text in meanings.items():
        _, table, col = key.split("|")
        q = f"{table}.{col}".lower()
        columns.append({"column": q, "gold": text if isinstance(text, str) else json.dumps(text),
                        "ao": ao_desc.get(q, "")})
    judge = {
        "database": a.db,
        "columns": columns,
        "kb": [json.loads(l) for l in (gold / "kb.jsonl").read_text().splitlines() if l.strip()],
        "ao_sql_attributes": [{"name": deobf(x["name"]), "expression": deobf(x["expression"]),
                               "description": deobf(x["description"])} for x in rows["sql_attributes"]],
        "ao_terms": [{"name": deobf(t["name"]), "description": deobf(t["description"])} for t in rows["terms"]],
    }
    (out / "judge_input.json").write_text(json.dumps(judge, indent=1))
    print((out / "joins.md").read_text())
    print(f"columns with gold meaning {len(columns)}; with an AO description {sum(1 for c in columns if c['ao'])}; "
          f"kb {len(judge['kb'])}; sql_attributes {len(judge['ao_sql_attributes'])}; terms {len(judge['ao_terms'])}")


if __name__ == "__main__":
    main()
