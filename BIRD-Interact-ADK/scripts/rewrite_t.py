"""Arm T T2 step 2: rewrite extract_raw.jsonl into renamed Postgres-dialect queries.csv.
Usage: python scripts/rewrite_t.py   (reads/writes under the saxo-query-log-mining/t dir)"""
import os, json, csv, re, collections, datetime, itertools, sys
import yaml, sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

T = os.path.expanduser("~/go/src/github.com/AtScaleInc/mcp/plans/saxo-query-log-mining/t")
MAP = yaml.safe_load(open(f"{T}/mapping_t.yaml"))
COLS = {t: {c[1].lower(): c[2] for c in []} for t in MAP}
for t, c, ty, *_ in json.load(open(f"{T}/tpcds_columns.json")):
    COLS.setdefault(t.lower(), {})[c.lower()] = "VARCHAR"
SCHEMA = {t: {c: "VARCHAR" for c in cs} for t, cs in COLS.items()}
TMAP = {t: v["table"] for t, v in MAP.items()}
CMAP = {t: {k.lower(): v for k, v in v["columns"].items()} for t, v in MAP.items()}
gaps = set()

class Drop(Exception):
    pass

def rewrite(text):
    try:
        tree = sqlglot.parse_one(text, read="snowflake")
    except Exception:
        raise Drop("unparseable")
    if not isinstance(tree, exp.Select) and not isinstance(tree, exp.Union) and not isinstance(tree, exp.Subquery):
        raise Drop("not_select")
    # lowercase every identifier; strip comments
    for n in tree.walk():
        n.comments = None
        if isinstance(n, exp.Identifier):
            n.set("this", n.name.lower()); n.set("quoted", False)
    ctes = {c.alias for c in tree.find_all(exp.CTE)}
    for t in list(tree.find_all(exp.Table)):
        if t.name in ctes and not t.db:
            continue
        if isinstance(t.this, exp.Identifier) is False:
            raise Drop("table_function")
        db = t.db
        if (db and db != "tpcds") or t.catalog not in ("", "atscale_tutorial_data"):
            raise Drop("table_outside_mapping")
        if t.name not in TMAP:
            raise Drop("table_outside_mapping")
        t.set("db", None); t.set("catalog", None)
    try:
        q = qualify(tree, schema=SCHEMA, dialect="postgres", validate_qualify_columns=True, identify=False)
    except Exception:
        raise Drop("unqualifiable")
    # classify columns by scope
    aliasmap = {}
    def al(name):
        name = name.lower()
        if name not in aliasmap:
            aliasmap[name] = f"a{len(aliasmap)+1}"
        return aliasmap[name]
    # first pass in appearance order: table aliases + select aliases + cte names
    for n in q.walk():
        if isinstance(n, exp.TableAlias):
            al(n.name)
            for c in n.columns: al(c.name)
        elif isinstance(n, exp.Alias):
            al(n.alias)
    colrename = []
    for sc in traverse_scope(q):
        sel_aliases = set()
        if isinstance(sc.expression, exp.Select):
            sel_aliases = {s.alias.lower() for s in sc.expression.expressions if s.alias}
        for c in sc.columns:
            tbl = c.table.lower() if c.table else ""
            src = sc.sources.get(tbl) if tbl else None
            if tbl and isinstance(src, exp.Table):
                real = src.name
                nn = CMAP.get(real, {}).get(c.name.lower())
                if nn is None:
                    gaps.add(f"{real}.{c.name}"); raise Drop("column_gap")
                colrename.append((c, nn))
            elif tbl and src is not None:
                colrename.append((c, al(c.name)))
            elif not tbl and c.name.lower() in sel_aliases:
                colrename.append((c, al(c.name)))
            else:
                raise Drop("unqualifiable")
    done = set()
    for c, nn in colrename:
        done.add(id(c))
        c.this.set("this", nn)
        if c.table: c.set("table", exp.to_identifier(al(c.table)))
    for c in q.find_all(exp.Column):  # order-by / other refs to select aliases
        if id(c) in done: continue
        if not c.table and c.name.lower() in aliasmap:
            c.this.set("this", aliasmap[c.name.lower()])
        else:
            raise Drop("unqualifiable")
    for t in q.find_all(exp.Table):
        if t.name in TMAP and not t.db and t.name not in aliasmap:
            t.this.set("this", TMAP[t.name])
        elif t.name in TMAP:
            t.this.set("this", TMAP[t.name])
        elif t.name in aliasmap:  # CTE reference
            t.this.set("this", aliasmap[t.name])
    for n in q.walk():
        if isinstance(n, exp.TableAlias):
            n.this.set("this", al(n.name))
            for c in n.columns: c.set("this", al(c.name))
        elif isinstance(n, exp.Alias):
            n.args["alias"].set("this", al(n.alias))
    for l in q.find_all(exp.Literal):
        if l.is_string and re.search(r"tpc|dsdgen", l.name, re.I):
            raise Drop("literal_leak")
    # join / table counts
    tabs = {t.name for t in q.find_all(exp.Table) if t.name in set(TMAP.values())}
    njoin = len(list(q.find_all(exp.Join)))
    if len(tabs) < 2 and njoin == 0:
        raise Drop("single_table")
    try:
        sql = q.sql(dialect="postgres")
    except Exception:
        raise Drop("render_error")
    if re.search(r"\b(HLL|REGEXP_EXTRACT|SEQ4|MONTHNAME|DAYNAME|GENERATOR|TABLE|QUARTER|APPROX_PERCENTILE_\w+)\(", re.sub(r"'[^']*'", "", sql)):
        raise Drop("snowflake_only_function")
    return sql, tabs

def main():
    t0 = datetime.datetime.now()
    rows = [json.loads(l) for l in open(f"{T}/extract_raw.jsonl")]
    drops = collections.Counter(); kept = {}
    for r in rows:
        try:
            sql, tabs = rewrite(r["text"])
        except Drop as d:
            drops[str(d)] += 1; continue
        except Exception as e:
            drops["rewrite_exception"] += 1; continue
        k = kept.setdefault(sql, dict(sql=sql, tabs=sorted(tabs), count=0, first=r["first"], last=r["last"], users=collections.Counter()))
        k["count"] += r["count"]; k["first"] = min(k["first"], r["first"]); k["last"] = max(k["last"], r["last"])
        k["users"][r["user"]] += r["count"]
    users = {}
    out = sorted(kept.values(), key=lambda k: k["first"])
    for k in out:
        u = k["users"].most_common(1)[0][0]
        users.setdefault(u, f"u{len(users)+1}"); k["user"] = users[u]
    fmt = "%Y-%m-%d %H:%M:%S"
    ev = []
    for i, k in enumerate(out):
        k["id"] = i + 1
        a = datetime.datetime.strptime(k["first"][:19], fmt); b = datetime.datetime.strptime(k["last"][:19], fmt)
        n = k["count"]
        for j in range(n):
            ts = b if n == 1 else a + (b - a) * j / (n - 1)
            ev.append((ts.strftime(fmt), k["sql"]))
    ev.sort()
    with open(f"{T}/queries.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["end_time", "query_text"]); w.writerows(ev)
    with open(f"{T}/queries_meta.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["sql_id", "user", "count", "first_seen", "last_seen", "tables"])
        for k in out: w.writerow([k["id"], k["user"], k["count"], k["first"], k["last"], " ".join(k["tabs"])])
    with open(f"{T}/queries_distinct.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["sql_id", "user", "ntables", "query_text"])
        for k in out: w.writerow([k["id"], k["user"], len(k["tabs"]), k["sql"]])
    tot = len(rows); nd = sum(drops.values())
    with open(f"{T}/queries_dropped.md", "w") as f:
        f.write(f"# T2 drops\n\nDistinct SELECTs extracted: {tot}\nDropped: {nd} ({100*nd/tot:.1f}%)\nKept distinct sql (after rewrite dedupe): {len(out)}; executions: {len(ev)}\n\n| reason | n |\n|---|---|\n")
        for r, n in drops.most_common(): f.write(f"| {r} | {n} |\n")
    if gaps:
        open(f"{T}/T2_mapping_gaps.txt", "w").write("\n".join(sorted(gaps)) + "\n")
    json.dump(dict(total=tot, drops=drops, kept=len(out), execs=len(ev), secs=(datetime.datetime.now()-t0).total_seconds()), open(f"{T}/rewrite_stats.json", "w"))
    print(tot, dict(drops), len(out), len(ev))

if __name__ == "__main__":
    main()
