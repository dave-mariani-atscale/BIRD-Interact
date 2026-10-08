#!/usr/bin/env python3
"""Flag possible engine wrong-data cases in a run: a failed submission that asks the same thing as a
submission which passed in an earlier run, but got different rows back.

"Same thing" = the same numeric/string literals, the same output width, and model objects where one
query's set contains the other's (a key projected only to steady the grouping, like r5's Driver Key on
sports_events_7, must not hide a match). Aliases, nesting and whitespace are ignored. For every failed phase submission in the run's window of
results/grading_audit.jsonl, the earlier passing submissions of that task and phase are searched for
one with the same signature; a match whose rows differ (as multisets, numbers to 6 places) is a
suspect. Variance in the agent's reading cannot produce that: the question it put to the engine was
the same. It can still be benign (a projected key changes the engine's implicit grouping), so each
suspect is a lead to replay, not a verdict.

    python3 scripts/suspect_wrong_data.py results/<run>.json [--out logs/<run>/suspect_wrong_data.md]
"""
import argparse, collections, json, re

ap = argparse.ArgumentParser(); ap.add_argument("run"); ap.add_argument("--out")
a = ap.parse_args()
d = json.load(open(a.run)); t0 = d["run_started"]; t1 = d.get("run_finished") or 9e12

def sig(sql):
    objs = frozenset(o for o in re.findall(r'"([^"]+)"', sql) if not o.startswith("bird_") and o != "atscale_catalogs")
    s = re.sub(r'"[^"]*"', "", sql)
    lits = frozenset(re.findall(r"'[^']*'|\b\d+(?:\.\d+)?\b", s))
    return objs, lits

def rows(r):
    def c(v):
        try: return round(float(v), 6)
        except (TypeError, ValueError): return v
    return collections.Counter(tuple(c(v) for v in row) for row in r)

now, prior = [], collections.defaultdict(list)
for line in open("results/grading_audit.jsonl"):
    if '"backend": "atscale"' not in line: continue
    r = json.loads(line); ts = r.get("ts", 0)
    if t0 <= ts <= t1:
        if not r.get("passed"): now.append(r)
    elif ts < t0 and r.get("passed") and r.get("pred_sql"):
        prior[(r["task_id"], r["phase"])].append(r)

out = ["| task | phase | kind | rows now | rows in the earlier pass | rows only in the earlier pass | rows only now | earlier pass (date) |",
       "|---|:-:|---|:-:|:-:|---|---|---|"]
seen = set()
for r in now:
    key = (r["task_id"], r["phase"]); s = sig(r.get("pred_sql") or "")
    width = len(r["pred_rows"][0]) if r["pred_rows"] else None
    for p in reversed(prior.get(key, [])):
        po, pl = sig(p["pred_sql"])
        if pl != s[1] or not (po <= s[0] or s[0] <= po): continue
        if not p["pred_rows"] or width != len(p["pred_rows"][0]): continue
        A, B = rows(p["pred_rows"]), rows(r["pred_rows"])
        if A == B: break
        rest = lambda C: collections.Counter(k[1:] for k in C.elements())
        kind = ("row count differs" if len(r["pred_rows"]) != len(p["pred_rows"])
                else "tie swap (same values, other ids)" if width > 1 and rest(A) == rest(B) else "values differ")
        k = (key, len(r["pred_rows"]), len(p["pred_rows"]))
        if k in seen: break
        seen.add(k)
        import datetime
        out.append(f"| `{r['task_id']}` | {r['phase']} | {kind} | {len(r['pred_rows'])} | {len(p['pred_rows'])} | "
                   f"{json.dumps(list((A-B).elements())[:2])[:160]} | {json.dumps(list((B-A).elements())[:2])[:160]} | "
                   f"{datetime.datetime.fromtimestamp(p['ts']):%m-%d %H:%M} |")
        break
text = f"Suspect wrong-data cases in {a.run}: {len(out)-2}\n\n" + "\n".join(out)
print(text)
if a.out: open(a.out, "w").write(text + "\n")
