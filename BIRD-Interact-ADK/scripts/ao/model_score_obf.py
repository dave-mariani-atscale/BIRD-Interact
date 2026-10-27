"""Score OBF / OBFAO SML models: the 16 gold joins and the hidden test-row filter. Mechanical, $0.

Usage: python scripts/ao/model_score_obf.py NAME=REPO[@TAG] [NAME2=REPO2[@TAG]] [--out DIR]
Gold joins = the FOREIGN KEYs in B2's original ETF schema.txt, translated to opaque names with
results/ao_score/obf_build/map.json. A join is realised by an SML relationship or a dataset SQL join
(same parser as model_score_t.py). Filter = does every dataset reading t09 exclude c134 = 1 (c134 in
its SQL WHERE), or does any object mention c134 at all (attribute, filter, description).
"""
import json, re, sys
from pathlib import Path

import model_score_t as mt  # noqa: E402  (same directory)

ADK = Path(__file__).resolve().parents[2]
GOLD = Path.home() / "go/src/github.com/diannewood/bird-models-b2/exchange_traded_funds/brief/schema.txt"
MAP = ADK / "results/ao_score/obf_build/map.json"


def gold_pairs() -> set:
    m = json.load(open(MAP))
    t = {v: k for k, v in m["tables"].items()}; c = {v: k for k, v in m["columns"].items()}
    out, cur = set(), None
    for ln in GOLD.read_text().splitlines():
        x = re.match(r'"?CREATE"? TABLE "?(\w+)', ln, re.I)
        if x: cur = x.group(1).lower()
        x = re.search(r'FOREIGN"? KEY \(\s*"?(\w+)"?\s*\) REFERENCES "?(\w+)"?\s*\(\s*"?(\w+)', ln, re.I)
        if x: out.add(frozenset({(t[cur], c[x.group(1).lower()]), (t[x.group(2).lower()], c[x.group(3).lower()])}))
    return out


def score(name: str, spec: str) -> dict:
    docs = mt.load_repo(spec)
    a = mt.analyse(docs)
    gold = gold_pairs()
    pairs = a["sml"] | a["baked"]
    ds = [d for d in docs if d["object_type"] == "dataset"]
    reads_t09 = [d for d in ds if d.get("table") == "t09" or re.search(r"\bt09\b", d.get("sql") or "")]
    filtered = [d["unique_name"] for d in reads_t09
                if re.search(r"\bWHERE\b[^;]*\bc134\b", d.get("sql") or "", re.I | re.S)]
    mentions = sorted({d["unique_name"] for d in docs if "c134" in json.dumps(d)})
    return {"model": name, "spec": spec, "n_datasets": a["n_datasets"], "n_dimensions": a["n_dims"],
            "join_recall": [len(pairs & gold), len(gold)], "via_sml": len(a["sml"] & gold), "via_sql": len(a["baked"] & gold),
            "missed": sorted(" = ".join("%s.%s" % x for x in sorted(p)) for p in gold - pairs),
            "extra_pairs": sorted(" = ".join("%s.%s" % x for x in sorted(p)) for p in pairs - gold),
            "datasets_reading_t09": [d["unique_name"] for d in reads_t09], "t09_datasets_filtered": filtered,
            "objects_mentioning_c134": mentions}


def main(argv: list) -> None:
    out = ADK / "results/arms_etf_obf"; specs = []
    it = iter(argv)
    for x in it:
        if x == "--out": out = Path(next(it))
        else: specs.append(x)
    res = [score(*s.split("=", 1)) for s in specs]
    for r in res:
        (out / f"score_{r['model'].lower()}.json").write_text(json.dumps(r, indent=1))
        print(f"{r['model']}: joins {r['join_recall'][0]}/{r['join_recall'][1]} (SML {r['via_sml']}, SQL {r['via_sql']}), "
              f"extra {len(r['extra_pairs'])}; t09 datasets {len(r['datasets_reading_t09'])}, filtered {len(r['t09_datasets_filtered'])}; "
              f"c134 mentioned in {len(r['objects_mentioning_c134'])} objects")


if __name__ == "__main__":
    main(sys.argv[1:])
