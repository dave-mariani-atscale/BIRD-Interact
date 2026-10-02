#!/usr/bin/env python3
"""Flip table for an in-flight or finished targeted run: each recorded task against r5, r4 and
the three 09-10 main runs (logs/nogold930_r5b/bundle/colleagues/per_task.csv).
Usage: python3 scripts/flip_report.py results/<run>.json"""
import json, sys, csv, collections
f = sys.argv[1]
d = json.load(open(f)); res = {x['task_id']: x for x in d.get('results', [])}
# The results file flushes behind the runner; the run log has every finished task's verdict line
# ("<== task: PASS both phases" / "PASS phase 1" / "FAIL ..."), so merge those in when given.
if len(sys.argv) > 2:
    import re
    for line in open(sys.argv[2]):
        m = re.search(r"<== (\S+): (PASS both phases|PASS phase 1|FAIL)", line)
        if m and m.group(1) not in res:
            res[m.group(1)] = {'phase1_passed': m.group(2) != 'FAIL', 'phase2_passed': m.group(2) == 'PASS both phases'}
pt = {r['task_id']: r for r in csv.DictReader(open('logs/nogold930_r5b/bundle/colleagues/per_task.csv'))}
def b(v): return None if v in ('', None) else int(v)
def fmt(v): return '-' if v is None else str(v)
def row(t, ph):
    p = pt.get(t, {}); now = int(res[t][f'phase{ph}_passed'])
    return now, b(p.get(f'r5_P{ph}')), b(p.get(f'r4_P{ph}')), [b(p.get(f'main_r{i}_P{ph}')) for i in (1, 2, 3)]
print(f"{len(res)}/59 recorded; P1 {sum(1 for x in res.values() if x['phase1_passed'])}  P2 {sum(1 for x in res.values() if x['phase2_passed'])}")
for ph in (1, 2):
    print(f"\n**Phase-{ph} flips vs r5:**\n\n| task | now | r5 | r4 | main r1/r2/r3 |\n|---|:-:|:-:|:-:|:-:|")
    for t in sorted(res):
        now, r5, r4, m = row(t, ph)
        if r5 is not None and now != r5:
            print(f"| `{t}` | **{'GAINED' if now else 'LOST'}** | {r5} | {fmt(r4)} | {' '.join(fmt(v) for v in m)} |")
print("\n**Still failing P1 that main passed (majority):**\n\n| task | r5 | r4 | main r1/r2/r3 |\n|---|:-:|:-:|:-:|")
for t in sorted(res):
    now, r5, r4, m = row(t, 1)
    if not now and sum(v or 0 for v in m) >= 2:
        print(f"| `{t}` | {fmt(r5)} | {fmt(r4)} | {' '.join(fmt(v) for v in m)} |")
c = collections.Counter(); c5 = collections.Counter()
for t in res:
    db = pt.get(t, {}).get('database') or t.rsplit('_', 1)[0]
    c[(db, 'n')] += 1; c[(db, 'p1')] += int(res[t]['phase1_passed']); c[(db, 'p2')] += int(res[t]['phase2_passed'])
    c5[(db, 'p1')] += b(pt.get(t, {}).get('r5_P1')) or 0; c5[(db, 'p2')] += b(pt.get(t, {}).get('r5_P2')) or 0
print("\n**By database (same tasks, now vs r5):**\n\n| database | recorded | P1 now | P1 r5 | P2 now | P2 r5 |\n|---|:-:|:-:|:-:|:-:|:-:|")
for db in sorted({k[0] for k in c}):
    print(f"| {db} | {c[(db,'n')]} | {c[(db,'p1')]} | {c5[(db,'p1')]} | {c[(db,'p2')]} | {c5[(db,'p2')]} |")
