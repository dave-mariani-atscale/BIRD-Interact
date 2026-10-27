"""Level-2 scoring of built Arm-T SML models vs t/answer_key_t.yaml. Mechanical, no LLM, $0.

Usage: python scripts/ao/model_score_t.py NAME=REPO[@TAG] [NAME2=REPO2[@TAG]] [--key PATH] [--out DIR]
  e.g. model_score_t.py CM=~/go/src/github.com/diannewood/bird-models-tcm@t-tcm-frozen
Reads the repo's SML YAML (from the git tag if @TAG, else the working tree). Writes NAME.json
(lower-cased) and LEVEL2.md (one column per repo) into --out.

Relationship realised = (a) an SML relationship declares it, or (b) a dataset's SQL joins the two
tables on those columns (JOIN ... ON a.c = b.d, aliases and subquery aliases resolved to source
table.column). Composite keys need every column pair. Metrics are matched on source table,
source-column set and aggregation: full = same cols+agg, partial = same cols other agg or
overlapping cols same agg, none otherwise. Attributes: key attribute present when a model
dimension attribute's name/key column resolves to the same source column(s).
"""
import json, os, re, subprocess, sys
from pathlib import Path
import yaml

ADK = Path(__file__).resolve().parents[2]
KEY = Path(os.path.expanduser("~/go/src/github.com/AtScaleInc/mcp/plans/saxo-query-log-mining/t/answer_key_t.yaml"))
KW = {"on", "left", "right", "inner", "full", "cross", "join", "where", "group", "order", "limit", "union", "having", "using", "outer", "natural", "window"}

# ---------- repo loading ----------
def load_repo(spec):
    path, _, tag = os.path.expanduser(spec).partition("@")
    docs = []
    if tag:
        names = subprocess.check_output(["git", "-C", path, "ls-tree", "-r", "--name-only", tag], text=True).split("\n")
        get = lambda n: subprocess.check_output(["git", "-C", path, "show", f"{tag}:{n}"], text=True)
    else:
        names = [str(p.relative_to(path)) for p in Path(path).rglob("*.yml")]
        get = lambda n: (Path(path) / n).read_text()
    for n in names:
        if n.endswith((".yml", ".yaml")) and not n.startswith(("generator/", ".")) and "/brief/" not in n and "/context/" not in n:
            try:
                d = yaml.safe_load(get(n))
            except Exception:
                continue
            if isinstance(d, dict) and d.get("object_type"):
                docs.append(d)
    return docs

# ---------- SQL parsing ----------
def depth_scan(s):
    """yield (i, ch, depth) skipping quoted strings"""
    d, q = 0, None
    for i, c in enumerate(s):
        if q:
            if c == q: q = None
            continue
        if c in "'\"": q = c; continue
        if c == "(": d += 1
        elif c == ")": d -= 1
        yield i, c, d

def match_paren(s, i):
    for j, c, d in depth_scan(s[i:]):
        if c == ")" and d == -1 + 0 and False: pass
    d = 0
    for j in range(i, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return j
    return len(s) - 1

def top_level(s, pat):
    """positions of regex pat matches at paren depth 0 (outside quotes)"""
    depth = {i: d for i, c, d in depth_scan(s)}
    return [m for m in re.finditer(pat, s, re.I) if depth.get(m.start(), 0) == 0]

def split_commas(s):
    out, cur, d, q = [], "", 0, None
    for c in s:
        if q:
            cur += c
            if c == q: q = None
            continue
        if c in "'\"": q = c
        elif c == "(": d += 1
        elif c == ")": d -= 1
        if c == "," and d == 0: out.append(cur); cur = ""
        else: cur += c
    return out + [cur] if cur.strip() else out

def parse(sql):
    """-> scope {aliases:{a:('t',table)|('s',scope)}, select:{alias:expr}, joins:[(refA,refB)], tables:[...]}"""
    sql = sql.strip().rstrip(";")
    branches = top_level(sql, r"\bUNION(\s+ALL)?\b")
    if branches:
        parts, prev = [], 0
        for m in branches:
            parts.append(sql[prev:m.start()]); prev = m.end()
        parts.append(sql[prev:])
        scopes = [parse(p.strip().strip("()")) if p.strip().startswith("(") else parse(p) for p in parts]
        sc = scopes[0]
        sc["joins"] = sum((x["joins"] for x in scopes), [])
        sc["tables"] = sum((x["tables"] for x in scopes), [])
        return sc
    sc = {"aliases": {}, "select": {}, "joins": [], "tables": []}
    fm = top_level(sql, r"\bFROM\b")
    if not fm:
        return sc
    sel = re.sub(r"^\s*SELECT\s+(DISTINCT\s+)?", "", sql[:fm[0].start()], flags=re.I)
    for it in split_commas(sel):
        it = it.strip()
        m = re.match(r"(?s)(.*)\s+AS\s+\"?(\w+)\"?\s*$", it, re.I)
        if m: sc["select"][m.group(2)] = m.group(1).strip()
        else:
            m2 = re.match(r"^(?:\w+\.)?\"?(\w+)\"?$", it)
            if m2: sc["select"][m2.group(1)] = it
            elif re.fullmatch(r"(\w+)\.\*", it): sc.setdefault("stars", []).append(it[:-2])
    rest, base = "FROM " + sql[fm[0].end():], 0
    # walk from-items
    pos, items = 0, []
    depth = {i: d for i, c, d in depth_scan(rest)}
    for m in re.finditer(r"(?:\bFROM\b|\bJOIN\b|,)\s*(\(|[\w.\"]+)", rest, re.I):
        if depth.get(m.start(), 0) != 0: continue
        if m.group(0).startswith(",") is False and False: pass
        items.append(m)
    ons = {}
    for k, m in enumerate(items):
        end_item = items[k + 1].start() if k + 1 < len(items) else len(rest)
        if m.group(1) == "(":
            p = m.end() - 1
            q = match_paren(rest, p)
            inner = parse(rest[p + 1:q])
            tail = rest[q + 1:end_item]
            al = re.match(r"\s*(?:AS\s+)?(\w+)", tail, re.I)
            alias = al.group(1) if al and al.group(1).lower() not in KW else f"_sub{k}"
            sc["aliases"][alias] = ("s", inner); sc["tables"] += inner["tables"]; sc["joins"] += inner["joins"]
            seg = tail
        else:
            tbl = m.group(1).strip('"').split(".")[-1]
            tail = rest[m.end():end_item]
            al = re.match(r"\s*(?:AS\s+)?(\w+)", tail, re.I)
            alias = al.group(1) if al and al.group(1).lower() not in KW else tbl
            sc["aliases"][alias] = ("t", tbl); sc["tables"].append(tbl)
            seg = tail
        on = re.search(r"\bON\b(.*)", seg, re.I | re.S)
        if on:
            seg_on = re.split(r"\b(?:WHERE|GROUP\s+BY|ORDER\s+BY)\b", on.group(1), flags=re.I)[0]
            ons[k] = seg_on
    sc["_ons"] = list(ons.values())
    for on in ons.values():
        for a, b, c, d in re.findall(r"(\w+)\.\"?(\w+)\"?\s*=\s*(\w+)\.\"?(\w+)\"?", on):
            sc["joins"].append(((sc, a, b), (sc, c, d)))
    return sc

def resolve(sc, alias, col, seen=0):
    """(scope, alias, col) -> (table, col) or None"""
    if seen > 6: return None
    t = sc["aliases"].get(alias)
    if t is None:
        return None
    if t[0] == "t": return (t[1], col)
    inner = t[1]
    expr = inner["select"].get(col)
    if expr is None:  # a.* passes the column through from alias a
        return next((r for a in inner.get("stars", []) if (r := resolve(inner, a, col, seen + 1))), None)
    m = re.fullmatch(r"(?:(\w+)\.)?\"?(\w+)\"?", expr.strip())
    if not m: return None
    if m.group(1): return resolve(inner, m.group(1), m.group(2), seen + 1)
    tbls = [v for v in inner["aliases"].values() if v[0] == "t"]
    return (tbls[0][1], m.group(2)) if len(tbls) == 1 and len(inner["aliases"]) == 1 else None

def expr_refs(sc, expr):
    """set of (table,col) referenced by a select expression (qualified refs, or bare cols if one table)"""
    out = set()
    for a, c in re.findall(r"\b(\w+)\.\"?(\w+)\"?", expr):
        r = resolve(sc, a, c)
        if r: out.add(r)
    if not out and len(sc["aliases"]) == 1:
        (v,) = sc["aliases"].values()
        if v[0] == "t":
            out = {(v[1], c) for c in re.findall(r"\"(\w+)\"|\b([a-z_]\w*)\b", expr) for c in c if c} - {(v[1], "CAST")}
            out = {x for x in out if x[1].lower() not in {"cast", "as", "case", "when", "then", "else", "end", "null", "decimal", "numeric", "is", "and", "or", "not", "sum", "count", "avg", "between"}}
    return out

class Dataset:
    def __init__(self, d):
        self.name = d["unique_name"]; self.sql = d.get("sql")
        self.sc = parse(self.sql) if self.sql else None
        self.table = d.get("table")
    def col(self, name):
        """-> (set of source (table,col), is_const_one)"""
        if self.sc is None:
            return ({(self.table, name)} if self.table else set()), False
        e = self.sc["select"].get(name)
        if e is None:
            r = next((r for a in self.sc.get("stars", []) if (r := resolve(self.sc, a, name))), None)
            return ({r} if r else set()), False
        return expr_refs(self.sc, e), e.strip() == "1"

def pairs_of(sc):
    out = set()
    for (s1, a, b), (s2, c, d) in sc["joins"]:
        x, y = resolve(s1, a, b), resolve(s2, c, d)
        if x and y and x != y: out.add(frozenset({x, y}))
    return out

# ---------- model analysis ----------
def analyse(docs):
    ds = {d["unique_name"]: Dataset(d) for d in docs if d["object_type"] == "dataset"}
    dims = [d for d in docs if d["object_type"] == "dimension"]
    sml_pairs, baked = set(), set()
    for d in ds.values():
        if d.sc: baked |= pairs_of(d.sc)
    # SML relationships
    lvl_idx = {}
    def walk(o, dim):
        if isinstance(o, dict):
            if "name_column" in o and "dataset" in o: lvl_idx.setdefault((dim, o.get("unique_name")), o)
            for v in o.values(): walk(v, dim)
        elif isinstance(o, list):
            for v in o: walk(v, dim)
    for dm in dims: walk(dm, dm["unique_name"])
    for m in (d for d in docs if d["object_type"] == "model"):
        for r in m.get("relationships") or []:
            try:
                fd = ds[r["from"]["dataset"]]
                f = [fd.col(c)[0] for c in r["from"]["join_columns"]]
                lv = lvl_idx.get((r["to"].get("dimension"), r["to"].get("level")))
                if lv is None:
                    lv = next((v for (dn, _), v in lvl_idx.items() if dn == r["to"].get("dimension")), None)
                t = [ds[lv["dataset"]].col(c)[0] for c in (lv.get("key_columns") or [lv["name_column"]])]
                for fs, ts in zip(f, t):
                    for x in fs:
                        for y in ts: sml_pairs.add(frozenset({x, y}))
            except Exception:
                pass
    # attributes
    attrs = []
    for (dn, un), o in lvl_idx.items():
        dset = ds.get(o["dataset"])
        if not dset: continue
        cols = [o["name_column"]] + list(o.get("key_columns") or [])
        attrs.append(({r for c in cols for r in dset.col(c)[0]}, dset.col(o["name_column"])[0], un))
    # metrics
    mets = []
    for m in (d for d in docs if d["object_type"] == "metric"):
        dset = ds.get(m.get("dataset"))
        if not dset or "column" not in m: continue
        refs, one = dset.col(m["column"])
        mets.append({"name": m["unique_name"], "agg": str(m.get("calculation_method", "")).lower(), "refs": refs, "one": one})
    calcs = [{"name": c["unique_name"], "expr": c.get("expression", "")} for c in docs if c["object_type"] == "metric_calc"]
    return {"sml": sml_pairs, "baked": baked, "attrs": attrs, "metrics": mets, "calcs": calcs,
            "n_datasets": len(ds), "n_dims": len(dims)}

# ---------- scoring ----------
AGG = {"sum": {"sum"}, "average": {"average", "avg"}, "count non-null": {"count"}}

def score_metric(km, model_metrics):
    kt, kcols = km["table"], set(km.get("source_cols") or ([km["column"]] if "column" in km else []))
    best, why = "none", ""
    for mm in model_metrics:
        mc = {c for t, c in mm["refs"] if t == kt}
        if km.get("row_counter"):
            if mm["one"] and mm["agg"] == "sum" and mm["refs"] == set(): s = "full"
            elif mm["agg"] == "count": s = "full"
            elif mm["agg"] == "count distinct" and mc and kt in {t for t, c in mm["refs"]}: s = "partial"
            else: continue
        else:
            if not mc: continue
            same_agg = mm["agg"] in AGG[km["aggregation"]]
            if mc == kcols: s = "full" if same_agg else "partial"
            elif mc & kcols and same_agg: s = "partial"
            else: continue
        if s == "full" or best == "none":
            best, why = s, mm["name"]
        if best == "full": break
    return best, why

def score(name, spec, key):
    a = analyse(load_repo(spec))
    realised_pairs = a["sml"] | a["baked"]
    R = key["relationships"]
    comp = lambda r: [frozenset({(r["from_table"], f), (r["to_table"], t)})
                      for f, t in zip(r["from_column"].split(","), r["to_column"].split(","))]
    res, key_pairs = {}, set()
    for r in R:
        ps = comp(r); key_pairs |= set(ps)
        sm = all(p in a["sml"] for p in ps); bk = all(p in a["baked"] for p in ps)
        res[r["id"]] = "REL" if sm else ("SQL" if bk else "none")
    real = {i for i, h in res.items() if h != "none"}
    ev = {r["id"] for r in R if r["evidence"] == "evidenced"}
    strict = {r["id"] for r in R if r["realised_in_copy"]}
    D = {d["id"]: frozenset({(d["from_table"], d["from_column"]), (d["to_table"], d["to_column"])}) for d in key["decoys"]}
    extras = sorted(realised_pairs - key_pairs, key=lambda p: sorted(p))
    decoys = {i: sorted("%s.%s" % x for x in D[i]) for i in D if D[i] in realised_pairs}
    nd = [" = ".join("%s.%s" % x for x in sorted(p)) for p in extras if p not in D.values()]
    hit = len(realised_pairs & key_pairs)
    # metrics
    allm = [dict(m, unobserved=False) for m in key["metrics"]] + [dict(m, unobserved=True) for m in key["metrics_unobserved"]]
    mres = {}
    for m in allm:
        s, w = score_metric(m, a["metrics"])
        mres[m["name"]] = {"score": s, "model_metric": w, "observed": not m["unobserved"], "row_counter": bool(m.get("row_counter"))}
    cnt = lambda sub: {k: sum(1 for v in sub if v["score"] == k) for k in ("full", "partial", "none")}
    mv = list(mres.values())
    # calculations: depends_on resolved to model metrics matched for those key metrics, same set referenced
    mname2model = {k: v["model_metric"] for k, v in mres.items() if v["score"] != "none"}
    cres = {}
    for c in key["calculations"]:
        need = {mname2model.get(d) for d in c["depends_on"] if d in mres}
        ok = None not in need and need and any(
            {x for x in need} == set(re.findall(r"\[Measures\]\.\[([^\]]+)\]", mc["expr"]))
            for mc in a["calcs"])
        cres[c["name"]] = "full" if ok else "none"
    # attributes
    ares, n_attr = {}, 0
    for i, k in enumerate(key["attributes"]):
        nc = k["name_column"]
        if isinstance(nc, dict):
            srcs = {(k["table"], c) for c in re.findall(r"\"(\w+)\"", nc["expression"])}
            hitattr = any(srcs and srcs <= s for s, nm, _ in a["attrs"] if srcs & nm)
        else:
            hitattr = any((k["table"], nc) in nm or (k["table"], nc) in s and len(s) == 1 for s, nm, _ in a["attrs"])
        ares[f'{k["dimension"]}/{k["attribute"]}'] = hitattr
    n_attr = sum(ares.values())
    out = {
        "model": name, "spec": spec, "n_datasets": a["n_datasets"], "n_dimensions": a["n_dims"],
        "relationships": res, "n_key": len(R),
        "recall_all": [len(real), len(R), round(len(real) / len(R), 3)],
        "recall_evidenced": [len(real & ev), len(ev), round(len(real & ev) / len(ev), 3)],
        "recall_strict_realised_in_copy": [len(real & strict), len(strict), round(len(real & strict) / len(strict), 3)],
        "by_how": {h: sum(1 for v in res.values() if v == h) for h in ("REL", "SQL", "none")},
        "missed": sorted((i for i in res if res[i] == "none"), key=lambda x: int(x[1:])),
        "model_join_pairs": len(realised_pairs), "pairs_in_key": hit,
        "precision": round(hit / len(realised_pairs), 3) if realised_pairs else None,
        "decoys_used": decoys, "non_decoy_extra_joins": nd,
        "metrics": mres, "metric_counts_all": cnt(mv),
        "metric_counts_observed": cnt([v for v in mv if v["observed"]]),
        "metric_counts_unobserved": cnt([v for v in mv if not v["observed"]]),
        "calculations_full": sum(1 for v in cres.values() if v == "full"), "calculations_total": len(cres), "calculations": cres,
        "attributes_present": [n_attr, len(ares)], "attributes_recall": round(n_attr / len(ares), 3),
        "attributes_missing": [k for k, v in ares.items() if not v],
        "judge": "none (mechanical source-column/aggregation match); cost $0",
    }
    return out

def main(argv):
    out = ADK / "results/arms_tpcds_t/level2_models"; key = KEY; specs = []
    it = iter(argv)
    for a in it:
        if a == "--out": out = Path(next(it))
        elif a == "--key": key = Path(next(it))
        elif a in ("-h", "--help"): print(__doc__); return
        else: specs.append(a)
    if not 1 <= len(specs) <= 2: sys.exit("give 1 or 2 NAME=REPO[@TAG] args")
    out.mkdir(parents=True, exist_ok=True)
    key = yaml.safe_load(open(key))
    res = []
    for s in specs:
        n, _, spec = s.partition("=")
        r = score(n, spec, key); res.append(r)
        (out / f"{n.lower()}.json").write_text(json.dumps(r, indent=1))
    fr = lambda x: f"{x[0]}/{x[1]} = {x[2]:.0%}"
    mc = lambda c: f"{c['full']}/{c['partial']}/{c['none']}"
    rows = [("Datasets / dimensions", lambda r: f"{r['n_datasets']} / {r['n_dimensions']}"),
        ("Relationship recall, all 106", lambda r: fr(r["recall_all"])),
        ("Recall, evidenced subset", lambda r: fr(r["recall_evidenced"])),
        ("Strict recall (realised_in_copy true)", lambda r: fr(r["recall_strict_realised_in_copy"])),
        ("Realised via SML relationship / baked SQL join", lambda r: f"{r['by_how']['REL']} / {r['by_how']['SQL']}"),
        ("Distinct model join pairs (SML + SQL)", lambda r: r["model_join_pairs"]),
        ("Pairs in key / precision", lambda r: f"{r['pairs_in_key']} / {r['precision']:.0%}" if r["precision"] is not None else "n/a"),
        ("Non-decoy extra joins", lambda r: len(r["non_decoy_extra_joins"])),
        ("Decoys used (D1-D9)", lambda r: ", ".join(r["decoys_used"]) or "none"),
        ("Metrics full/partial/none, all 59", lambda r: mc(r["metric_counts_all"])),
        ("  observed 49", lambda r: mc(r["metric_counts_observed"])),
        ("  unobserved 10", lambda r: mc(r["metric_counts_unobserved"])),
        ("Calculations matched (of 28)", lambda r: r["calculations_full"]),
        ("Attributes present (of 109)", lambda r: fr(r["attributes_present"] + [r["attributes_recall"]]))]
    L = ["# Level 2 (Arm T): model quality vs answer_key_t.yaml", "",
         "Static YAML only, mechanical matching, no LLM judge ($0). " + "; ".join(f"{r['model']} = {r['spec']}" for r in res), "",
         "| Item | " + " | ".join(r["model"] for r in res) + " |", "|---|" + "---|" * len(res)]
    for lab, f in rows: L.append(f"| {lab} | " + " | ".join(str(f(r)) for r in res) + " |")
    for r in res:
        L += ["", f"## {r['model']}: missed relationships ({len(r['missed'])})", ", ".join(r["missed"]) or "none",
              "", f"{r['model']} non-decoy extra joins:"] + [f"- {x}" for x in r["non_decoy_extra_joins"]]
        L += ["", f"{r['model']} metrics scored none:", ", ".join(k for k, v in r["metrics"].items() if v["score"] == "none") or "none"]
    L += ["", "## Method notes", "",
          "- Relationship realised if an SML relationship or a baked JOIN..ON in a dataset's SQL joins the two source columns (composites need every column pair). Joins outside dataset SQL are not seen.",
          "- Precision = distinct model join pairs that are key pairs / all distinct model join pairs.",
          "- Metric: full = same source table, same source-column set, same aggregation; partial = same cols other aggregation or overlapping cols same aggregation (can overcount for expression metrics); row counters: sum of constant 1 or COUNT = full, COUNT DISTINCT on the table = partial.",
          "- Calculations: matched when a model calc references exactly the model metrics matched to the key calc's inputs.",
          "- Attribute: model dimension attribute whose name/key column resolves to the key's source column (expression attributes: same source columns)."]
    (out / "LEVEL2.md").write_text("\n".join(L) + "\n")
    print("\n".join(f"{lab}: " + " | ".join(str(f(r)) for r in res) for lab, f in rows))

if __name__ == "__main__":
    main(sys.argv[1:])
