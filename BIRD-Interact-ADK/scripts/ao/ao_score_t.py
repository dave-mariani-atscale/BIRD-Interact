"""Level-1 scoring of the AO export for the Arm-T database against t/answer_key_t.yaml. No DB, no LLM.

Usage: python scripts/ao/ao_score_t.py <export.yaml> <out dir> [--key PATH] [--joins-md ao_joins.md]
Joins are unordered column pairs (composite key entries need every column pair).
  semantic FK edges : export.yaml `semantic_fk_join_groups` (all / use_in_join_paths=True)
  log-observed joins: column__join pairs. Taken from the `## Joins observed` table of ao_joins.md
                      (default: ao_joins.md beside export.yaml) when present, else from
                      export.joins (table__join) resolved through catalog column ids.
Each source is scored separately: recall over all 106 key relationships, over the 56 evidenced,
precision, decoys D1-D9 emitted, non-decoy FPs. Writes joins.json, joins.md.
Metrics (59), calculations (28), attributes (109): AO has no metric objects, so this script builds
judge_input.json (gold + the AO terms/SqlAttributes touching its source columns) for a Sonnet judge
pass done exactly as for Saxo (in-session, by Claude; no script LLM calls). If verdicts.json
({id: "full"|"partial"|"none"}) exists beside the output it is tallied into metrics.md.
Also reports a mechanical attribute check: key attribute column present as an AO term column.
"""
import json, re, sys
from pathlib import Path
import yaml

KEY = Path.home() / "go/src/github.com/AtScaleInc/mcp/plans/saxo-query-log-mining/t/answer_key_t.yaml"
fmt = lambda p: " = ".join(sorted(p))
P = lambda a, b: frozenset({a, b})


def main(argv):
    if "-h" in argv or "--help" in argv or len(argv) < 2:
        print(__doc__); return
    export_p, out = Path(argv[0]), Path(argv[1])
    key_p, md_p, rest = KEY, export_p.parent / "ao_joins.md", argv[2:]
    for i, a in enumerate(rest):
        if a == "--key": key_p = Path(rest[i + 1])
        if a == "--joins-md": md_p = Path(rest[i + 1])
    key = yaml.safe_load(open(key_p)); ex = yaml.safe_load(open(export_p))
    out.mkdir(parents=True, exist_ok=True)
    e = ex["export"]
    col = {str(r["column_id"]): (r["table_name"], r["column_name"]) for r in e["catalog"]}

    sem = {}
    for g in ex.get("semantic_fk_join_groups") or []:
        sem[P(f"{g['source_table_name']}.{g['source_column_name']}", f"{g['target_table_name']}.{g['target_column_name']}")] = bool(g.get("use_in_join_paths"))

    obs, obs_src = {}, None
    if md_p.exists():
        sec = False
        for ln in md_p.read_text().splitlines():
            if ln.startswith("## Joins observed"): sec = True; continue
            c = [x.strip() for x in ln.strip().strip("|").split("|")]
            if sec and ln.startswith("|") and len(c) >= 3 and re.match(r"^\w+\.\w+$", c[0]):
                obs[P(c[0], c[1])] = int(c[2])
        obs_src = str(md_p)
    if not obs:
        for j in e.get("joins") or []:
            for jc in j.get("join_columns") or []:
                try:
                    a, b = (jc if isinstance(jc, (list, tuple)) else (jc["source_column_id"], jc["target_column_id"]))[:2]
                    obs[P("%s.%s" % col[str(a)], "%s.%s" % col[str(b)])] = 1
                except Exception:
                    pass
        obs_src = "export.joins"

    comp = lambda r: [P(f"{r['from_table']}.{f}", f"{r['to_table']}.{t}") for f, t in zip(r["from_column"].split(","), r["to_column"].split(","))]
    R = {r["id"]: comp(r) for r in key["relationships"]}
    EV = {r["id"] for r in key["relationships"] if r["evidence"] == "evidenced"}
    keypairs = {p for ps in R.values() for p in ps}
    D = {d["id"]: P(f"{d['from_table']}.{d['from_column']}", f"{d['to_table']}.{d['to_column']}") for d in key["decoys"]}
    num = lambda x: int(x[1:])
    KIND = {r["id"]: r["kind"] for r in key["relationships"]}
    REAL = {r["id"] for r in key["relationships"] if r.get("realised_in_copy")}

    def score(found):
        tp = {i for i, ps in R.items() if all(p in found for p in ps)}
        fps = [p for p in found if p not in keypairs]
        dec = {i: fmt(D[i]) for i in D if D[i] in found}
        return {"found": len(found), "recall_all": [len(tp), len(R), round(len(tp) / len(R), 3)],
                "recall_evidenced": [len(tp & EV), len(EV), round(len(tp & EV) / len(EV), 3)],
                "recall_realised": [len(tp & REAL), len(REAL), round(len(tp & REAL) / len(REAL), 3)],
                "missed_evidenced": {i: KIND[i] for i in sorted(EV - tp, key=num)},
                "precision": round(len(found & keypairs) / len(found), 3) if found else None,
                "FP": len(fps), "decoys_emitted": dec,
                "nondecoy_FPs": sorted(fmt(p) for p in fps if p not in D.values()),
                "found_R": sorted(tp, key=num), "missed_R": sorted(set(R) - tp, key=num)}

    res = {"key_relationships": len(R), "log_observed_source": obs_src,
           "semantic_fk_all": score(set(sem)),
           "semantic_fk_use_in_join_paths": score({p for p, u in sem.items() if u}),
           "log_observed": score(set(obs)), "union": score(set(sem) | set(obs))}
    (out / "joins.json").write_text(json.dumps(res, indent=1))
    rows = ["| source | found | recall all | recall evidenced | recall realised | precision | FP | decoys |", "|---|---|---|---|---|---|---|---|"]
    for k, v in res.items():
        if isinstance(v, dict):
            a, b = v["recall_all"], v["recall_evidenced"]
            rows.append(f"| {k} | {v['found']} | {a[0]}/{a[1]} = {a[2]:.0%} | {b[0]}/{b[1]} = {b[2]:.0%} | {v['recall_realised'][0]}/{v['recall_realised'][1]} | {v['precision']} | {v['FP']} | {','.join(v['decoys_emitted']) or '-'} |")
    (out / "joins.md").write_text("\n".join(rows) + "\n")
    print("\n".join(rows))

    # judge input + mechanical attribute presence
    ao_cols = {}  # "t.c" -> list of "term / attr: desc"
    terms = {str(t["id"]): t["name"] for t in e["terms"]}
    for t in e["terms"]:
        for a in t["columns_attributes"]:
            c = col.get(str(a["column_id"]))
            if c: ao_cols.setdefault("%s.%s" % c, []).append(f"{t['name']} / {a['name']}: {' '.join((a.get('description') or '').split())[:300]}")
    sqla = [f"{a['name']} :: `{' '.join((a.get('expression') or a.get('sql') or '').split())[:240]}`" for a in e["sql_attributes"]]
    items = []
    def touch(table, cols):
        names = [c for c in cols if c]
        return [s for s in sqla if any(re.search(rf"\b{re.escape(c)}\b", s) for c in names)][:6]
    for m in key["metrics"] + key["metrics_unobserved"]:
        cs = m.get("source_cols") or ([m["column"]] if "column" in m else [])
        items.append({"id": m["name"], "kind": "metric", "gold": {k: v for k, v in m.items() if k != "in_log"},
                      "ao_terms": {c: ao_cols.get(f"{m['table']}.{c}", []) for c in cs}, "ao_sql_attributes": touch(m["table"], cs)})
    for c in key["calculations"]:
        items.append({"id": c["name"], "kind": "calculation", "gold": c, "ao_sql_attributes": touch(None, [])})
    for a in key["attributes"]:
        nc = a["name_column"] if isinstance(a["name_column"], str) else None
        items.append({"id": f"{a['dimension']}/{a['attribute']}", "kind": "attribute", "gold": a,
                      "mechanical_present": bool(nc and f"{a['table']}.{nc}" in ao_cols),
                      "ao_terms": ao_cols.get(f"{a['table']}.{nc}", []) if nc else []})
    (out / "judge_input.json").write_text(json.dumps({"items": items}, indent=1))
    att = [i for i in items if i["kind"] == "attribute"]
    print(f"attributes mechanically present as AO term column: {sum(i['mechanical_present'] for i in att)}/{len(att)}; judge items: {len(items)}")
    vp = out / "verdicts.json"
    if vp.exists():
        v = json.load(open(vp)); L = ["| kind | full | partial | none |", "|---|---|---|---|"]
        for k in ("metric", "calculation", "attribute"):
            ids = [i["id"] for i in items if i["kind"] == k]
            c = [sum(1 for i in ids if (v.get(i) or {}).get("verdict", v.get(i)) == s) for s in ("full", "partial", "none")]
            L.append(f"| {k} ({len(ids)}) | {c[0]} | {c[1]} | {c[2]} |")
        (out / "metrics.md").write_text("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1:])
