"""Arm T T2 step 1: extract distinct tpcds SELECTs from Snowflake QUERY_HISTORY (read-only).
Writes t/extract_raw.jsonl (raw names, prep-only). Run from this dir with the venv python."""
import sys, os, json, base64, time, datetime
sys.path.insert(0, os.path.expanduser("~/go/src/github.com/AtScaleInc/mcp/plans/saxo-query-log-mining/scripts"))
import sf
T = os.path.expanduser("~/go/src/github.com/AtScaleInc/mcp/plans/saxo-query-log-mining/t")
OUT = f"{T}/extract_raw.jsonl"
WIN = 14
FILT = """query_type='SELECT' AND execution_status='SUCCESS'
 AND query_text ILIKE '%tpcds%'
 AND NOT CONTAINS(LOWER(query_text),'aggs') AND NOT CONTAINS(LOWER(query_text),'as_agg_')
 AND NOT CONTAINS(LOWER(query_text),'query_history') AND NOT CONTAINS(LOWER(query_text),'information_schema')
 AND NOT CONTAINS(LOWER(query_text),'account_usage')"""

def qr(sql, limit):
    for i in range(6):
        try:
            return sf.q(sql, limit)
        except Exception as e:
            print("retry", i, str(e)[:100], file=sys.stderr); time.sleep(5 * (i + 1))
    raise RuntimeError("sf failed")

def windows():
    end = datetime.datetime.utcnow().date() + datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=380)
    d = start
    while d < end:
        yield d, min(d + datetime.timedelta(days=WIN), end)
        d += datetime.timedelta(days=WIN)

def main():
    t0 = time.time()
    groups = {}  # hash -> dict
    nexec = 0
    for a, b in windows():
        rows = qr(f"""SELECT query_hash, COUNT(*), TO_VARCHAR(MIN(start_time)), TO_VARCHAR(MAX(end_time)), MIN(user_name), MIN(query_id)
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= '{a}' AND start_time < '{b}' AND {FILT}
GROUP BY query_hash""", 1000)
        rows = [r for r in rows[1:] if len(r) == 6]
        if len(rows) >= 1000: print("WARN window full", a, file=sys.stderr)
        for h, c, mn, mx, u, qid in rows:
            g = groups.setdefault(h, dict(hash=h, count=0, first=mn, last=mx, user=u, query_id=qid, qids=[]))
            g["count"] += int(c); nexec += int(c)
            g["first"] = min(g["first"], mn); g["last"] = max(g["last"], mx)
            if u < g["user"]: g["user"] = u
            g["qids"].append((a, qid))
        print(a, len(rows), file=sys.stderr, flush=True)
    print("distinct hashes", len(groups), "executions", nexec, file=sys.stderr)
    items = list(groups.values())
    done = set()
    if os.path.exists(OUT):
        done = {json.loads(l)["hash"] for l in open(OUT)}
    with open(OUT, "a") as f:
        todo = [g for g in items if g["hash"] not in done]
        i = 0
        while i < len(todo):
            page = todo[i:i + 100]
            ids = ",".join("'%s'" % g["query_id"] for g in page)
            lo = min(g["qids"][0][0] for g in page) - datetime.timedelta(days=1)
            rows = qr(f"""SELECT query_id, BASE64_ENCODE(TO_BINARY(query_text,'UTF-8'))
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE start_time >= '{lo}' AND query_id IN ({ids})""", 200)
            txt = {r[0]: r[1] for r in rows[1:] if len(r) == 2}
            for g in page:
                if g["query_id"] in txt:
                    g["text"] = base64.b64decode(txt[g["query_id"]]).decode("utf-8", "replace")
                    del g["qids"]
                    f.write(json.dumps(g) + "\n")
                else:
                    print("missing text", g["query_id"], file=sys.stderr)
            f.flush(); i += 100
            print("fetched", i, "/", len(todo), file=sys.stderr, flush=True)
    print("elapsed_s", round(time.time() - t0), file=sys.stderr)

if __name__ == "__main__":
    main()
