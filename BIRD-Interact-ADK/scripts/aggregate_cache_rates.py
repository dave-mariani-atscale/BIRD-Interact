#!/usr/bin/env python3
"""Aggregate and cache rates for the final passing queries of each run.

usage: score_aggregates.py <results_run01.json> [run02.json ...]

Reads the graded engine query_id straight from each run's own results JSON, so
a run needs no timestamp matching against the long-lived services. Prefers the
`query_id` recorded on the submit_sql trajectory step (added 2026-09-04); falls
back, for runs recorded before that, to matching the submitted SQL against an
earlier run_query step's `queryId`. The fallback is lossy on purpose-visible
detail: the old recording truncated a tool response at 2000 characters and the
id sat after the result rows, so large-result queries have no id at all. Those
are disproportionately leaf-grain queries that do not route, which makes a
fallback-based rate OPTIMISTIC. The report says how many were unresolved.
"""
import json, os, re, subprocess, sys, collections

QID = re.compile(r'queryId:\s*([0-9a-fA-F-]{36})')
PHASE = re.compile(r'Phase\s+(\d)\s+(correct|incorrect|failed)', re.I)
#: Engine repository password. Read from PGPASSWORD, else ENGINE_PGPW_FILE, so
#: nothing secret lives in the repo and the path is not machine-specific.
PGPW_FILE = os.environ.get("ENGINE_PGPW_FILE", "")


def norm(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip().rstrip(';').lower()


def finals(path):
    """(task_id, phase, query_id or None, resolved_how) for each PASSING submit."""
    out = []
    d = json.load(open(path))
    for r in (d.get('results') if isinstance(d, dict) else d) or []:
        seen = []
        for s in r.get('tool_trajectory') or []:
            tool = s.get('tool')
            if tool == 'run_query':
                ids = s.get('query_ids') or QID.findall(str(s.get('result')))
                seen.append((norm((s.get('args') or {}).get('query')), ids[-1] if ids else None))
            elif tool == 'submit_sql':
                m = PHASE.search(str(s.get('result') or ''))
                if not m or m.group(2).lower() != 'correct':
                    continue
                phase = int(m.group(1))
                qid, how = s.get('query_id'), 'submit_sql'
                if not qid:
                    sql = norm((s.get('args') or {}).get('sql'))
                    for txt, q in reversed(seen):
                        if txt == sql:
                            qid, how = q, ('run_query match' if q else 'truncated')
                            break
                    else:
                        how = 'never ran'
                out.append((r['task_id'], phase, qid, how))
    return out


def engine(ids):
    """query_id -> (hit_aggregate, full_cache, partial_cache, subqueries)."""
    if not ids:
        return {}
    pw = os.environ.get("PGPASSWORD", "")
    if not pw and PGPW_FILE and os.path.exists(PGPW_FILE):
        pw = open(PGPW_FILE).read().strip()
    sql = """
create temp table q(id uuid);
copy q from stdin;
%s
\\.
select q.id,
       (a.query_id is not null),
       coalesce(d.full_local_cache_hit,false),
       coalesce(d.partial_local_cache_hit,false),
       coalesce(d.subquery_count,0)
from q
left join engine.query_details d on d.query_id=q.id
left join (select distinct query_id from engine.query_aggregate_usage) a on a.query_id=q.id;
""" % "\n".join(sorted(ids))
    p = subprocess.run(["docker", "exec", "-i", "-e", f"PGPASSWORD={pw}", "postgres",
                        "psql", "-U", "atscale", "-d", "atscale", "-X", "-A", "-F", "|", "-t"],
                       input=sql, capture_output=True, text=True)
    out = {}
    for line in p.stdout.splitlines():
        f = line.split("|")
        if len(f) == 5 and "-" in f[0]:
            out[f[0]] = (f[1] == "t", f[2] == "t", f[3] == "t", int(f[4] or 0))
    if not out:
        print("  engine lookup returned nothing:", p.stderr.strip()[:300], file=sys.stderr)
    return out


def main():
    runs = sys.argv[1:]
    if not runs:
        print(__doc__); sys.exit(2)
    per_run, allids = {}, set()
    for p in runs:
        f = finals(p)
        per_run[os.path.basename(p)] = f
        allids |= {q for _, _, q, _ in f if q}
    facts = engine(allids)

    print(f"{'run':46s} {'pass':>5s} {'id':>5s} {'agg':>7s} {'cache':>7s} {'subq':>5s}")
    print("-" * 82)
    tot = collections.Counter(); bydb = collections.defaultdict(collections.Counter)
    for name, f in per_run.items():
        c = collections.Counter()
        for tid, ph, qid, how in f:
            db = tid.rsplit('_', 1)[0]
            c['pass'] += 1; bydb[db]['pass'] += 1
            c[how] += 1
            if qid and qid in facts:
                agg, full, part, sq = facts[qid]
                c['id'] += 1; c['agg'] += agg; c['cache'] += full; c['subq'] += sq
                bydb[db]['id'] += 1; bydb[db]['agg'] += agg; bydb[db]['cache'] += full
        tot.update(c)
        n = c['id'] or 1
        print(f"{name:46s} {c['pass']:5d} {c['id']:5d} {c['agg']/n*100:6.1f}% "
              f"{c['cache']/n*100:6.1f}% {c['subq']/n:5.2f}")
    print("-" * 82)
    n = tot['id'] or 1
    print(f"{'BLENDED':46s} {tot['pass']:5d} {tot['id']:5d} {tot['agg']/n*100:6.1f}% "
          f"{tot['cache']/n*100:6.1f}% {tot['subq']/n:5.2f}")

    print(f"\nid resolution: submit_sql {tot['submit_sql']}, run_query match "
          f"{tot['run_query match']}, LOST to truncation {tot['truncated']}, "
          f"never ran {tot['never ran']}")
    if tot['truncated'] or tot['never ran']:
        unres = tot['truncated'] + tot['never ran']
        print(f"  WARNING: {unres} of {tot['pass']} passing queries have no id, so the rates "
              f"above cover {tot['id']/max(tot['pass'],1)*100:.0f}% of them and read HIGH "
              f"(the missing ones are large-result, leaf-grain queries that rarely route).\n"
              f"  A run recorded after the submit_sql query_id change reports 100% resolution.")

    print(f"\n{'model':34s} {'pass':>5s} {'id':>5s} {'agg':>7s} {'cache':>7s}")
    for db in sorted(bydb):
        c = bydb[db]; n = c['id'] or 1
        print(f"  {db:32s} {c['pass']:5d} {c['id']:5d} {c['agg']/n*100:6.1f}% {c['cache']/n*100:6.1f}%")


if __name__ == "__main__":
    main()
