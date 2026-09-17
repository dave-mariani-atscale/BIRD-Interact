#!/usr/bin/env python3
"""Classify a leaderboard run's task errors by cause, as disclosable markdown.

Every error in a results file is a task scored 0. Readers need to know WHY:
a vendor outage, the model's context ceiling, and a harness race are three very
different claims about the number. Causes are recovered from the agent log by
timestamp, because the results file records only that run_session returned 500.

    PYTHONPATH=. .venv-adk/bin/python scripts/error_ledger.py \
        --orchestrator logs/gpt5_cold.log --agent logs/system_agent.out results/r1.json [results/r2.json ...]

The two logs are different files and both are needed: the orchestrator log records
WHICH task failed, the agent log records WHY (the exception text has no task id and
no timestamp of its own, so the cause is matched by the nearest preceding timestamp).
"""
import json, re, sys
from collections import Counter

TS = re.compile(r'^(2026-\d\d-\d\d \d\d:\d\d:\d\d)')

def signals(agent_log, since):
    sig = {}
    last = None
    for line in open(agent_log, errors='replace'):
        m = TS.match(line)
        if m:
            last = m.group(1)
        if not last or last < since:
            continue
        if 'Input tokens exceed' in line:
            n = re.search(r'resulted in (\d+) tokens', line)
            sig.setdefault(last, set()).add(('overflow', int(n.group(1)) if n else 0))
        for p in ('InternalServerError', 'APIConnectionError', 'JSONDecodeError', 'RateLimitError'):
            if p in line:
                sig.setdefault(last, set()).add((p, 0))
    return sig

def secs(t):
    return int(t[11:13]) * 3600 + int(t[14:16]) * 60 + int(t[17:19])

def classify(t, url, sig, limit):
    if 'init_task' in url:
        return 'harness: init_task template-clone race', None
    found = set()
    for k, v in sig.items():
        if k[:10] == t[:10] and secs(t) - 95 <= secs(k) <= secs(t) + 5:
            found |= v
    over = [x[1] for x in found if x[0] == 'overflow']
    if over:
        v = max(over)
        return 'context overflow', f'{v:,} tokens, {100*v/limit-100:+.0f}% over the {limit:,} ceiling'
    if any(x[0] in ('InternalServerError', 'APIConnectionError') for x in found):
        return 'upstream API outage (server-side, recovered)', None
    if any(x[0] == 'JSONDecodeError' for x in found):
        return 'malformed tool-call JSON', None
    if any(x[0] == 'RateLimitError' for x in found):
        return 'rate limited', None
    return 'unclassified', None

def main():
    a = sys.argv[1:]
    orch = a[a.index('--orchestrator') + 1]
    agent_log = a[a.index('--agent') + 1]
    results = [x for x in a if x.endswith('.json')]
    limit = 272_000
    runs = []
    for i, p in enumerate(results, 1):
        d = json.load(open(p))
        errs = [t['task_id'] for t in d['results'] if 'phase1_passed' not in t]
        runs.append((f'r{i}', d, set(errs), (d['run_started'], d['run_finished'])))
    sig = signals(agent_log, '2026-01-01 00:00:00')

    lines = [l for l in open(orch, errors='replace') if 'ERROR Error:' in l]
    rows = []
    for l in lines:
        t = l[:19]
        m = re.search(r'Error: (\S+?):', l)
        task = m.group(1) if m else '?'
        url = 'init_task' if 'init_task' in l else 'run_session'
        import datetime as _dt
        ts = _dt.datetime.strptime(t, '%Y-%m-%d %H:%M:%S').timestamp()
        run = next((n for n, d, ids, (s0, s1) in runs if task in ids and s0 <= ts <= s1 + 300), None)
        if run is None:
            run = next((n for n, d, ids, _ in runs if task in ids), None)
        if run is None:
            continue
        cause, detail = classify(t, url, sig, limit)
        rows.append((run, t, task, cause, detail))

    print('## Errors, disclosed\n')
    print('Every row is a task scored 0. Causes recovered from the agent log by timestamp.\n')
    tally = Counter((r, c) for r, _, _, c, _ in rows)
    print('| run | cause | tasks |')
    print('|---|---|---|')
    for (run, cause), n in sorted(tally.items()):
        print(f'| {run} | {cause} | {n} |')
    print()
    print('| run | when | task | cause | detail |')
    print('|---|---|---|---|---|')
    for run, t, task, cause, detail in rows:
        print(f'| {run} | {t[11:]} | `{task}` | {cause} | {detail or ""} |')
    print()
    tot = len(rows)
    n_tasks = sum(len(d['results']) for _, d, _, _ in runs)
    print(f'**{tot} errors across {n_tasks} task-runs ({100*tot/n_tasks:.1f}%).**')
    print()
    print('Reading these: an *upstream API outage* is a vendor incident that hit whichever '
          'tasks were in flight - it depresses that run\'s score and says nothing about the '
          'model. A *context overflow* is real: the conversation exceeded the model\'s window, '
          'and the margin column shows how near the ceiling the task was - the large margins '
          'are structural to the task, the small ones are tasks that pass when the feedback '
          'store is empty and fail once memory is being injected. The *template-clone race* is '
          'a harness defect at concurrency 5, not a model failure.')

if __name__ == '__main__':
    main()
