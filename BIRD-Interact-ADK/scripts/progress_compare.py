#!/usr/bin/env python3
"""Side-by-side progress of an in-flight leaderboard run against a finished baseline.

    python scripts/progress_compare.py LOG BASELINE.json

Parses the runner's per-task verdict lines ("<== task: PASS both phases ...") and
compares Query tasks finished so far with the baseline's verdicts on the SAME tasks.
"""
import json, re, sys, collections

log, base = sys.argv[1], sys.argv[2]
B = {}
for r in json.load(open(base))["results"]:
    tid = r.get("instance_id") or r["task_id"]
    B[tid] = (bool(r.get("phase1_passed")), bool(r.get("phase2_passed")), r.get("elapsed_seconds") or 0)

pat = re.compile(r"<== (\S+): (PASS both phases|PASS phase 1|fail|error)\s+reward=([0-9.]+)\s+\((\d+)/(\d+) done")
done = {}
total = 600
for line in open(log, errors="replace"):
    m = pat.search(line)
    if m:
        tid, verdict, reward, n, total = m.group(1), m.group(2), float(m.group(3)), int(m.group(4)), int(m.group(5))
        done[tid] = (verdict.startswith("PASS"), verdict == "PASS both phases", verdict == "error")
q = {t: v for t, v in done.items() if "_M_" not in t}
shared = [t for t in q if t in B]
def rate(k, n): return f"{k}/{n} ({100*k/n:.1f}%)" if n else "-"
p1 = sum(1 for t in shared if q[t][0]); p2 = sum(1 for t in shared if q[t][1]); e = sum(1 for t in q.values() if t[2])
b1 = sum(1 for t in shared if B[t][0]); b2 = sum(1 for t in shared if B[t][1])
won = sum(1 for t in shared if q[t][0] and not B[t][0]); lost = sum(1 for t in shared if B[t][0] and not q[t][0])
mgmt = [t for t in done if "_M_" in t]
print(f"progress: {len(done)}/{total} tasks done ({len(q)} Query, {len(mgmt)} Management); errors so far: {e}")
print(f"{'Query tasks finished so far':30s}{'rebased (live)':>16s}{'baseline 09-16 r1':>20s}")
print(f"{'P1':30s}{rate(p1,len(shared)):>16s}{rate(b1,len(shared)):>20s}")
print(f"{'P2':30s}{rate(p2,len(shared)):>16s}{rate(b2,len(shared)):>20s}")
print(f"paired P1 on those tasks: rebased won {won}, baseline won {lost}, net {won-lost:+d}")
by = collections.defaultdict(lambda: [0,0,0,0])
for t in shared:
    db = t.rsplit("_",1)[0]; a = by[db]; a[0]+=1; a[1]+=q[t][0]; a[2]+=B[t][0]; a[3]+= (q[t][0]!=B[t][0])
if by:
    print(f"{'database':32s}{'n':>4s}{'rebased P1':>12s}{'baseline P1':>13s}{'flips':>7s}")
    for db, a in sorted(by.items()):
        print(f"{db:32s}{a[0]:>4d}{a[1]:>12d}{a[2]:>13d}{a[3]:>7d}")
