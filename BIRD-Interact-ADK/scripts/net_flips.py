#!/usr/bin/env python3
"""Net flips by database for an in-flight or finished targeted run, versus r5.
Usage: python3 scripts/net_flips.py results/<run>.json logs/<run>/run.log"""
import json, csv, re, sys, collections
res = {x['task_id']: x for x in json.load(open(sys.argv[1]))['results']}
for line in open(sys.argv[2]):
    m = re.search(r"<== (\S+): (PASS both phases|PASS phase 1|FAIL)", line)
    if m and m.group(1) not in res:
        res[m.group(1)] = {'phase1_passed': m.group(2) != 'FAIL', 'phase2_passed': m.group(2) == 'PASS both phases'}
pt = {r['task_id']: r for r in csv.DictReader(open('logs/nogold930_r5b/bundle/colleagues/per_task.csv'))}
c = collections.Counter(); n = collections.Counter()
for t, x in res.items():
    db = pt[t]['database']; n[db] += 1
    for ph in (1, 2):
        r5 = pt[t].get(f'r5_P{ph}'); now = int(x[f'phase{ph}_passed'])
        if r5 in ('', None): continue
        c[(db, ph, 'g')] += int(now and not int(r5)); c[(db, ph, 'l')] += int(int(r5) and not now)
print(f"{len(res)}/59 finished; P1 {sum(1 for x in res.values() if x['phase1_passed'])}  P2 {sum(1 for x in res.values() if x['phase2_passed'])}")
print("\n**Net flips vs r5:**\n\n| database | finished | P1 gained | P1 lost | P1 net | P2 gained | P2 lost | P2 net |\n|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|")
T = collections.Counter()
for db in sorted(n):
    g1, l1, g2, l2 = c[(db, 1, 'g')], c[(db, 1, 'l')], c[(db, 2, 'g')], c[(db, 2, 'l')]
    T['g1'] += g1; T['l1'] += l1; T['g2'] += g2; T['l2'] += l2
    print(f"| {db} | {n[db]} | {g1} | {l1} | **{g1-l1:+d}** | {g2} | {l2} | **{g2-l2:+d}** |")
print(f"| **all** | {len(res)} | {T['g1']} | {T['l1']} | **{T['g1']-T['l1']:+d}** | {T['g2']} | {T['l2']} | **{T['g2']-T['l2']:+d}** |")
