"""Score AO's saxo_bank joins against answer_key.yaml (Phase 6 level 1). No DB, no LLM.

Usage: ao_score_saxo.py <answer_key.yaml> <ao_joins.md> <out dir>
Joins are unordered column pairs. Sources: semantic FK edges (all / use_in_join_paths=True) and
joins observed in the query log (column__join), parsed from the rendered ao_joins.md.
Writes joins.json + joins.md. Metrics/attributes are judged separately (verdicts.json).
"""
import json
import re
import sys
from pathlib import Path

import yaml

key, joins_md, out = yaml.safe_load(open(sys.argv[1])), Path(sys.argv[2]).read_text(), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
pair = lambda a, b: frozenset({a, b})
fmt = lambda p: " = ".join(sorted(p))

sem, obs = {}, {}  # pair -> use_in_join_paths / statements
sec = None
for ln in joins_md.splitlines():
    if ln.startswith("# AO join groups"):
        sec = "sem"
    elif ln.startswith("## Joins observed"):
        sec = "obs"
    c = [x.strip() for x in ln.strip().strip("|").split("|")]
    if not ln.startswith("|") or len(c) < 3 or not re.match(r"^\w+\.\w+$", c[0]):
        continue
    if sec == "sem":
        sem[pair(c[0], c[1])] = c[3] == "True"
    elif sec == "obs":
        obs[pair(c[0], c[1])] = int(c[2])

R = {r["id"]: pair(f'{r["from_table"]}.{r["from_column"]}', f'{r["to_table"]}.{r["to_column"]}')
     for r in key["relationships"]}
D = {d["id"]: (pair(f'{d["from_table"]}.{d["from_column"]}', f'{d["to_table"]}.{d["to_column"]}'), d) for d in key["decoys"]}
unres = [re.compile(p) for p in [r"mk_officesid_.*", r"mk_employeesid_.*", r"mk_leadsid$", r"mk_instrumentsid$",
         r"mk_earningsid.*", r"mk_productcategoriesid.*", r"mk_endclienttraderprofilesid.*", r"mk_orderplacementtoolsid$"]]


def decoy_hit(p):
    for i, (dp, d) in D.items():
        if p == dp or (i == "D5" and {x.split(".")[0] for x in p} == {"accounts", "accountbalancedkkdemo"}
                       and "accountbalancedkkdemo.mk_accountsid_accountid" in p):
            return i


def score(found):
    tp = {i for i, p in R.items() if p in found}
    fps = [p for p in found if p not in R.values()]
    dec = {}
    for p in fps:
        if (i := decoy_hit(p)):
            dec[i] = fmt(p)
    inv = [fmt(p) for p in fps if any(u.match(x.split(".")[1]) for u in unres for x in p)]
    return {"found": len(found), "TP": len(tp), "FP": len(fps), "FN": len(R) - len(tp),
            "precision": round(len(tp) / len(found), 3) if found else None, "recall": round(len(tp) / len(R), 3),
            "found_R": sorted(tp, key=lambda x: int(x[1:])), "missed_R": sorted(set(R) - tp, key=lambda x: int(x[1:])),
            "roleplay_R5_R7": {i: i in tp for i in ("R5", "R6", "R7")}, "R20_selfjoin": "R20" in tp,
            "decoys_emitted": dec, "invented_targets_for_unresolvable": inv,
            "nondecoy_FPs": sorted(fmt(p) for p in fps if not decoy_hit(p))}


res = {"relationships": len(R), "semantic_fk_all": score(set(sem)),
       "semantic_fk_use_in_join_paths": score({p for p, u in sem.items() if u}),
       "log_observed": score(set(obs)), "union": score(set(sem) | set(obs))}
(out / "joins.json").write_text(json.dumps(res, indent=1))
rows = ["| source | found | TP | FP | FN | precision | recall | R5/R6/R7 | R20 | decoys | invented |", "|---|---|---|---|---|---|---|---|---|---|---|"]
for k, v in res.items():
    if k == "relationships":
        continue
    rp = "/".join("y" if x else "n" for x in v["roleplay_R5_R7"].values())
    rows.append(f"| {k} | {v['found']} | {v['TP']} | {v['FP']} | {v['FN']} | {v['precision']} | {v['recall']} | {rp} | "
                f"{'y' if v['R20_selfjoin'] else 'n'} | {','.join(v['decoys_emitted']) or '-'} | {len(v['invented_targets_for_unresolvable'])} |")
(out / "joins.md").write_text("\n".join(rows) + "\n")
print("\n".join(rows))
for k in ("semantic_fk_all", "log_observed"):
    print(k, "missed", res[k]["missed_R"], "nondecoy FPs", res[k]["nondecoy_FPs"], "inv", res[k]["invented_targets_for_unresolvable"])
