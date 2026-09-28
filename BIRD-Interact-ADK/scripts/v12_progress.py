#!/usr/bin/env python3
"""What is a v12 build doing? Reads ARTIFACTS ON DISK, not the log's prose. $0.

    python3 scripts/v12_progress.py          # newest build
    python3 scripts/v12_progress.py 08       # a specific build
    python3 scripts/v12_progress.py 08 --tail 30

Milestones are files the build actually produced. An earlier version inferred them
from the log's tool calls and was wrong in both directions: Bash tool_use carries a
`description`, so matching it matched the human summary and never the command.
The ledger row is the one true completion test, same as the driver's.
"""
import argparse, glob, json, os, re, subprocess, sys, time

LOGDIR, ORDER = "logs/v12_programme", "results/kickoff_00_v12_order.md"
MODELS = os.path.expanduser("~/go/src/github.com/diannewood/bird-models-v12")

def runs_for(db, since):
    """Run JSONs belonging to this database, found by reading their task ids."""
    out = []
    for j in glob.glob("results/*/run*.json"):
        if os.path.getmtime(j) < since:
            continue
        try:
            d = json.load(open(j))
            ids = [r.get("instance_id", "") for r in (d.get("results") or [])[:1]]
            if ids and ids[0].rsplit("_", 1)[0] == db:
                out.append((os.path.getmtime(j), j, d.get("metrics", {})))
        except Exception:
            pass
    return sorted(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build", nargs="?")
    ap.add_argument("--tail", type=int, default=12)
    a = ap.parse_args()

    logs = sorted(glob.glob(f"{LOGDIR}/{a.build or '*'}_*.jsonl"), key=os.path.getmtime)
    if not logs:
        sys.exit(f"no build log for {a.build or 'any build'}")
    log = logs[-1]
    name = os.path.basename(log)[:-6]
    num, db = name[:2], name[3:]

    row = ""
    for line in open(ORDER):
        if re.match(rf"\|\s*0*{int(num)}\s*\|", line):
            row = line.strip()
    done = bool(row)

    # A RESUMED build runs as `claude -p --resume <sid> "Continue the build..."`, with no
    # kickoff path in its command line, so grepping for the kickoff misses it entirely and
    # reports a running build as STOPPED. Match the driver, any claude -p, or - most
    # reliably - a log that is still being written.
    def _pgrep(pat):
        return subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True).stdout.split()
    alive = _pgrep(f"kickoff_{num}_") or _pgrep("claude -p --resume") or _pgrep("run_v12_programme")
    writing = (time.time() - os.path.getmtime(log)) < 180
    alive = alive if (alive and writing) else (alive if alive else [])
    age = (time.time() - os.path.getmtime(log)) / 60
    print(f"BUILD {name}")
    if done:
        print("  COMPLETE - ledger row written")
    elif alive or writing:
        pid = f"pid {alive[0]} | " if alive else ""
        print(f"  RUNNING | {pid}last activity {age*60:.0f}s ago | log {os.path.getsize(log)/1e6:.1f} MB")
    else:
        print(f"  STOPPED, no ledger row | last activity {age:.0f} min ago | log {os.path.getsize(log)/1e6:.1f} MB")

    mf = f"{MODELS}/{db}"
    since = os.path.getmtime(log) - 12 * 3600
    rs = runs_for(db, since)
    checks = [
        ("facts.md measurement pass", os.path.exists(f"{mf}/generator/facts.md")),
        ("spec.py authored (F1)",     os.path.exists(f"{mf}/generator/spec.py")),
        ("model built",               bool(glob.glob(f"{mf}/models/*.yml"))),
        ("$0 ceiling sweep",          bool(glob.glob("results/*sweep*/*.report.txt") or glob.glob(f"results/*{db[:4]}*sweep*"))),
        ("benchmark runs",            f"{len(rs)} run(s)" if rs else False),
        ("pass report",               bool(glob.glob(f"results/{db}_v12_pass_*.md"))),
        ("ledger row",                done),
    ]
    print("\nMILESTONES")
    for label, ok in checks:
        mark = "x" if ok else " "
        extra = f"  ({ok})" if isinstance(ok, str) else ""
        print(f"  [{mark}] {label}{extra}")

    if rs:
        print("\nRUNS")
        for mt, j, m in rs:
            print(f"  {time.strftime('%H:%M', time.localtime(mt))}  {os.path.dirname(j).split('/')[-1]:<36}"
                  f" P1 {m.get('phase1_rate',0):.3f}  P2 {m.get('phase2_rate',0):.3f}"
                  f"  reward {m.get('average_reward',0):.3f}  n={m.get('total_tasks')}")
    if row:
        print(f"\nLEDGER\n  {row}")
        return

    ev = []
    for line in open(log, errors="replace"):
        try: o = json.loads(line)
        except ValueError: continue
        if o.get("type") == "assistant":
            for c in o["message"].get("content", []):
                if c.get("type") == "text" and c["text"].strip():
                    ev.append(("say", c["text"].strip().replace("\n", " ")))
                elif c.get("type") == "tool_use":
                    i = c.get("input", {})
                    ev.append((c["name"], str(i.get("command") or i.get("file_path")
                                             or i.get("description") or i.get("prompt", "")).replace("\n", " ")))
        elif o.get("type") == "result":
            ev.append(("RESULT", str(o.get("result"))[:200]))
    print(f"\nLAST {a.tail} ACTIONS")
    for k, v in ev[-a.tail:]:
        print(f"  [{k:8.8s}] {v[:115]}")

if __name__ == "__main__":
    main()
