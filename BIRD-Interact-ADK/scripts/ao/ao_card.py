#!/usr/bin/env python3
"""AO -> model bridge card.

Maps AO's warehouse-level knowledge (terms, column descriptions, join evidence, sql
attributes) onto the objects of a deployed SML model, emitting a vocabulary card.
Inputs are AO's own export and the model YAML only.

  ao_card.py <export.yaml> <model_dir> <column_index.txt> --out card.md --map map.json [--max-lines 120]
"""
import argparse, glob, json, os, re, sys
from collections import defaultdict
import yaml


def words(s, n=20):
    w = s.split()
    return " ".join(w[:n]) + ("..." if len(w) > n else "")


def short_desc(d):
    if not d:
        return ""
    d = re.sub(r"\s+", " ", d).strip()
    d = d.split(" — ")[0]
    d = re.sub(r"^The \S+ column (is an? [A-Z]+ field (that )?|\([^)]*\) )?(is |are )?(stores |contains |holds |records |represents |indicates |captures )?(the |a |an )?", "", d)
    d = re.sub(r"^\w+ \([A-Z0-9(),]+\) ", "", d)
    d = re.sub(r"^(is |are )", "", d)
    d = re.split(r",? (with samples|with examples|shown by|represented by|with observed|with typical|shown as|as seen|recorded with|recorded as|stored as|stored with|ranging|which can|typically|as shown|exemplified|such as|with values|e\.g\.|including|with sample)", d)[0]
    d = re.split(r"(?<=[a-z\)])\. ", d)[0].rstrip(".")
    return words(d)


def fmt_names(lab, dns):
    """dns: [(role fmt, deployed name)] -> compact deployed-name expression."""
    if len(dns) == 1:
        return dns[0][1]
    pre = [f.replace("{0}", "").strip() for f, _ in dns]
    plain = [n for (f, n), p in zip(dns, pre) if not p]
    pf = "/".join(p for p in pre if p)
    if plain:
        return f"{plain[0]} (also {pf} {lab})"
    return f"{pf} {lab}"


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


# ---------------------------------------------------------------- column index
def load_index(path):
    names, groups = {}, set()
    for ln in open(path):
        ln = ln.rstrip("\n")
        if ln.startswith("## column_group:"):
            g = re.sub(r"^## column_group: ", "", ln)
            g = re.sub(r" \((dimension attributes|measures|[^)]*)\)$", "", g)
            groups.add(g)
            names[norm(g)] = g
            continue
        if not ln or ln.startswith(("#", "column_name", " ")) or ":" in ln[:40] and ln.split(":")[0] in (
                "catalog.schema.table", "description", "columns", "calculations", "dimension folders", "metric folders"):
            continue
        names.setdefault(norm(ln), ln)
    return names, groups


# ---------------------------------------------------------------- AO side
class AO:
    def __init__(self, export_path):
        e = yaml.safe_load(open(export_path))
        ex = e["export"]
        self.col_by_id = {}
        self.tables = {}  # table -> set(cols)
        self.table_id = {}
        for c in ex["catalog"]:
            self.col_by_id[c["column_id"]] = (c["table_name"], c["column_name"])
            self.tables.setdefault(c["table_name"], set()).add(c["column_name"])
            self.table_id[c["table_id"]] = c["table_name"]
        self.catdesc = {(c["table_name"], c["column_name"]): c["column_description"] for c in ex["catalog"] if c.get("column_description")}
        self.attr = {}  # (table,col) -> (term, attrname, desc)
        self.term_of_table = {}
        self.term_by_id = {}
        for t in ex["terms"]:
            self.term_by_id[t["id"]] = t["name"]
            for tid in t.get("represents") or []:
                self.term_of_table[self.table_id.get(tid)] = t["name"]
            for a in t["columns_attributes"]:
                k = self.col_by_id.get(a["column_id"])
                if k and k not in self.attr:
                    self.attr[k] = (t["name"], a["name"], a.get("description") or "")
        self.fk = {}  # (src_table, src_col) -> (tgt_table, tgt_col, default)
        for g in e["semantic_fk_join_groups"]:
            self.fk[(g["source_table_name"], g["source_column_name"])] = (
                g["target_table_name"], g["target_column_name"], g["use_in_join_paths"])
        self.sqlattrs = [
            dict(name=s["name"], desc=s["description"], expr=s["expression"], term=self.term_by_id.get(s["term_id"], "?"))
            for s in ex["sql_attributes"]]
        self.logjoins = {}
        self.col_count = defaultdict(int)

    def load_log_joins(self, joins_md):
        on = False
        for ln in open(joins_md):
            if ln.startswith("## Joins observed"):
                on = True
                continue
            if on and ln.startswith("|") and not ln.startswith("| column") and not ln.startswith("|---"):
                a, b, n = [x.strip() for x in ln.strip().strip("|").split("|")]
                self.logjoins[frozenset((a, b))] = int(n)

    def describe(self, tc):
        if tc in self.attr:
            term, an, d = self.attr[tc]
            return term, (short_desc(d) or short_desc(self.catdesc.get(tc)) or an)
        return None, None


# ---------------------------------------------------------------- model side
def load_dir(d, sub):
    out = []
    for f in sorted(glob.glob(os.path.join(d, sub, "*.yml"))):
        y = yaml.safe_load(open(f).read().replace("\t", "  "))
        if y:
            out.append(y)
    return out


def base_table(name, ao):
    if name in ao.tables:
        return name
    n = re.sub(r"_dataset$", "", name)
    return n if n in ao.tables else None


def dataset_tables(ds, ao):
    if ds.get("table"):
        t = base_table(ds["table"], ao)
        return [t] if t else []
    sql = ds.get("sql") or ""
    ts = re.findall(r'(?:FROM|JOIN)\s+(?:["\w-]+\.){0,2}"?(\w+)"?', sql, flags=re.I)
    return [t for t in dict.fromkeys(ts) if t in ao.tables]


def build(export, model_dir, index_path):
    ao = AO(export)
    ao.load_log_joins(os.path.join(os.path.dirname(export), "ao_joins.md"))
    names, groups = load_index(index_path)

    datasets = {d["unique_name"]: d for d in load_dir(model_dir, "datasets")}
    ds_tables = {k: dataset_tables(d, ao) for k, d in datasets.items()}
    ds_cols = {k: {c["name"]: c for c in d.get("columns", [])} for k, d in datasets.items()}

    def resolve(ds, col):
        """dataset column -> set of warehouse (table, col)."""
        out = set()
        tabs = ds_tables.get(ds, [])
        c = ds_cols.get(ds, {}).get(col)
        cand = []
        if col in {x for t in tabs for x in ao.tables[t]}:
            cand.append(col)
        if c is not None and c.get("sql"):
            for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", c["sql"]):
                if tok != col:
                    cand.append(tok)
        for tok in cand:
            for t in tabs:
                if tok in ao.tables[t]:
                    out.add((t, tok))
        return out

    def deployed(n):
        return names.get(norm(n))

    # ---- objects: name -> {"kind","cols":set,"tier"}
    objs = {}

    def add(name, kind, cols, tier, extra=None):
        dn = deployed(name)
        if not dn or not cols:
            return None
        o = objs.setdefault(dn, dict(kind=kind, cols=set(), tier=tier, extra=extra))
        o["cols"] |= set(cols)
        o["tier"] = min(o["tier"], tier)
        return dn

    # metrics
    mdefs = {}
    mfolders = {}
    model = (load_dir(model_dir, "models") or [{}])[0]
    for m in model.get("metrics", []):
        if isinstance(m, dict) and m.get("folder"):
            mfolders[m["unique_name"]] = m["folder"]
    metrics = load_dir(model_dir, "metrics")
    mcols = {}
    for m in metrics:
        cols = resolve(m.get("dataset"), m.get("column"))
        for key in (m["unique_name"], m.get("label")):
            if key:
                mdefs[norm(key)] = m["unique_name"]
        mcols[m["unique_name"]] = cols
        add(m.get("label") or m["unique_name"], "metric", cols, 0 if m["unique_name"] in mfolders else 1)
        if m.get("label") != m["unique_name"]:
            add(m["unique_name"], "metric", cols, 0 if m["unique_name"] in mfolders else 1)

    # calcs
    for c in load_dir(model_dir, "calculations"):
        cols = set()
        for ref in re.findall(r"\[Measures\]\.\[([^\]]+)\]", c.get("expression", "")):
            u = mdefs.get(norm(ref))
            if u:
                cols |= mcols.get(u, set())
        add(c.get("label") or c["unique_name"], "calc", cols, 3)
        if c.get("label") != c["unique_name"]:
            add(c["unique_name"], "calc", cols, 3)

    # relationships (role play + joins)
    rels = model.get("relationships", [])
    dims = load_dir(model_dir, "dimensions")
    dim_label = {d["unique_name"]: d.get("label") or d["unique_name"] for d in dims}
    roles = defaultdict(set)  # dimension -> role formats
    for r in rels:
        dim = r["to"].get("dimension")
        if dim:
            roles[dim].add(r.get("role_play") or "{0}")

    # dimension attributes
    def walk(x, dim, out):
        if isinstance(x, dict):
            if x.get("unique_name") and x.get("dataset") and (x.get("key_columns") or x.get("name_column")):
                out.append(x)
            for v in x.values():
                walk(v, dim, out)
        elif isinstance(x, list):
            for v in x:
                walk(v, dim, out)

    dim_tables = defaultdict(set)
    for d in dims:
        fl = []
        walk(d, d["unique_name"], fl)
        for a in fl:
            dim_tables[d["unique_name"]] |= set(ds_tables.get(a["dataset"], []))
    role_dims_tier = {}
    attr_lines = []  # (label, [deployed names], cols, tier)
    for d in dims:
        found = []
        walk(d, d["unique_name"], found)
        big = any(k in d["unique_name"].lower() for k in ("date", "customer", "address"))
        seen = set()
        for a in found:
            lab = a.get("label") or a["unique_name"]
            if lab in seen:
                continue
            seen.add(lab)
            cols = set()
            for c in list(a.get("key_columns") or []) + ([a["name_column"]] if a.get("name_column") else []):
                cols |= resolve(a["dataset"], c)
            dns = []
            for fmt in sorted(roles.get(d["unique_name"], {"{0}"})):
                n = deployed(fmt.format(lab).strip())
                if n:
                    dns.append((fmt, n))
            if cols and dns:
                attr_lines.append((lab, dns, cols, 2 if big else 4))

    # group lines from relationships
    group_lines = []  # (group, term, text, tier)
    seen_g = set()
    for r in rels:
        dim = r["to"].get("dimension")
        ds = r["from"]["dataset"]
        fmt = r.get("role_play") or "{0}"
        g = fmt.format(dim_label.get(dim, dim)).strip()
        gname = names.get(norm(g))
        if not gname or gname not in groups:
            continue
        for jc in r["from"]["join_columns"]:
            for (t, c) in resolve(ds, jc):
                if (t, c) not in ao.fk:
                    continue
                tt, tc, default = ao.fk[(t, c)]
                if tt not in dim_tables.get(dim, {tt}):
                    continue
                key = (gname, t, c)
                if key in seen_g:
                    continue
                seen_g.add(key)
                n = ao.logjoins.get(frozenset((f"{t}.{c}", f"{tt}.{tc}")), 0)
                term = ao.term_of_table.get(tt) or ao.term_of_table.get(t) or "Other"
                text = f"{gname} — AO: {'default' if default else 'non-default'} join for {t} {term} ({c}); log joins {n}"
                big = any(k in (dim or "").lower() for k in ("date", "customer", "address"))
                group_lines.append((gname, term, text, 0 if big else 1, bool(default)))

    # ---- assemble per-term lines
    lines = []  # (term, tier, text, kind)
    mapping = defaultdict(list)
    for dn, o in objs.items():
        seen_t = set()
        for tc in sorted(o["cols"]):
            term, desc = ao.describe(tc)
            if not term or (term, desc) in seen_t:
                continue
            if o["kind"] == "calc" and term in {t for t, _ in seen_t}:
                continue
            seen_t.add((term, desc))
            lines.append((term, o["tier"], f"{dn} — AO: {term}: {desc}", o["kind"], dn))
            mapping[dn].append(dict(ao_column=f"{tc[0]}.{tc[1]}", term=term))
            if o["kind"] in ("metric", "calc"):
                break  # one line per metric/calc: first resolvable column
    for lab, dns, cols, tier in attr_lines:
        seen_t = set()
        for tc in sorted(cols):
            term, desc = ao.describe(tc)
            if not term or term in seen_t:
                continue
            seen_t.add(term)
            nm = fmt_names(lab, dns)
            lines.append((term, tier, f"{nm} — AO: {term}: {desc}", "attr", nm))
            pfx = "/".join(p for p in (f.replace("{0}", "").strip() for f, _ in dns) if p) if len(dns) > 1 else ""
            for _, n in dns:
                mapping[n].append(dict(ao_column=f"{tc[0]}.{tc[1]}", term=term))
            break
    for gname, term, text, tier, default in group_lines:
        lines.append((term, tier, text, "join", gname))
        mapping[gname].append(dict(join=text))

    # sql attributes -> objects via WHERE-clause columns
    col_to_names = defaultdict(set)
    for lab, dns, cols, tier in attr_lines:
        pfx = "/".join(p for p in (f.replace("{0}", "").strip() for f, _ in dns) if p) if len(dns) > 1 else ""
        if len(dns) == 1:
            pfx, lab2 = "", dns[0][1]
        else:
            lab2 = lab
        for tc in cols:
            col_to_names[tc].add((pfx, lab2))
    for dn, o in objs.items():
        if o["kind"] == "metric":
            for tc in o["cols"]:
                col_to_names[tc].add(("", dn))
    for s in ao.sqlattrs:
        m = re.search(r"\bWHERE\b(.*)$", s["expr"], flags=re.I | re.S)
        if not m:
            continue
        toks = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1)))
        tabs = [t for t in re.findall(r'(?:FROM|JOIN)\s+(?:["\w-]+\.){0,2}"?(\w+)"?', s["expr"], flags=re.I) if t in ao.tables]
        hit = []
        for t in tabs:
            for tok in sorted(toks):
                if tok in ao.tables[t]:
                    hit += sorted(col_to_names.get((t, tok), []))
        hit = list(dict.fromkeys(hit))[:4]
        if not hit:
            continue
        grp = defaultdict(list)
        for pf, lb in hit:
            grp[pf].append(lb)
        hit_txt = " / ".join((f"{pf} " if pf else "") + ", ".join(lbs) for pf, lbs in grp.items())
        hit = [lb for _, lb in hit]
        d = short_desc(s["desc"].split(". ")[0]) if s["desc"] else ""
        lines.append((s["term"], 1, f'{hit_txt} — AO pattern "{s["name"]}": {d}', "pattern", s["name"]))
        mapping["pattern:" + s["name"]].append(dict(objects=hit))
    return lines, mapping


def render(lines, max_lines):
    """Drop lowest-priority lines until the card fits; priority = metric-folder metrics and
    date/customer/address role groups first. Returns (card, cut counts, kept lines)."""
    uniq = list(dict.fromkeys(lines))

    def total(ls):
        return len(ls) + len({l[0] for l in ls})  # lines + one heading per term

    order = [lambda l: l[3] == "calc",
             lambda l: l[3] == "attr" and l[1] == 4,
             lambda l: l[3] == "metric" and l[1] == 1,
             lambda l: l[3] == "join" and l[1] == 1,
             lambda l: l[3] == "attr" and l[1] == 2,
             lambda l: l[3] == "pattern"]
    cut = defaultdict(int)
    cur = uniq
    for pred in order:
        if total(cur) <= max_lines:
            break
        dropped = [l for l in cur if pred(l)]
        cur = [l for l in cur if not pred(l)]
        for l in dropped:  # restore as many of this tier as fit
            if total(cur + [l]) <= max_lines:
                cur.append(l)
            else:
                cut[f"{l[3]}(tier {l[1]})"] += 1
    by = defaultdict(list)
    for l in cur:
        by[l[0]].append(l)
    out = []
    for term in sorted(by):
        out.append(f"## {term}")
        out += [l[2] for l in sorted(by[term], key=lambda x: (x[1], x[2]))]
    return "\n".join(out) + "\n", dict(cut), cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("model_dir")
    ap.add_argument("column_index")
    ap.add_argument("--out", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--max-lines", type=int, default=120)
    a = ap.parse_args()
    lines, mapping = build(a.export, a.model_dir, a.column_index)
    card, cut, kept = render(lines, a.max_lines)
    open(a.out, "w").write(card)
    kinds = defaultdict(int)
    for l in kept:
        kinds[l[3]] += 1
    json.dump(dict(objects=mapping, kept_by_kind=dict(kinds), cut=cut, total_before_cut=len(set(lines))),
              open(a.map, "w"), indent=1)
    print(f"{a.out}: {len(card.splitlines())} lines; kept {dict(kinds)}; cut {cut}; pre-cut {len(set(lines))}")


if __name__ == "__main__":
    main()
