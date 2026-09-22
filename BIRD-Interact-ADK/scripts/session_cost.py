#!/usr/bin/env python3
"""Per-model token and list-price spend of Claude Code sessions, from local transcripts.

    python3 scripts/session_cost.py --session            # newest session in this repo + its subagents
    python3 scripts/session_cost.py --session <id-prefix>
    python3 scripts/session_cost.py --since 7            # every session touched in the last 7 days

Reads ~/.claude/projects/<encoded cwd>/*.jsonl and <session>/subagents/*.jsonl, dedupes by API
message id, and prices at published list rates. $0, no API calls. The figures size the work;
they are not an invoice.
"""
import argparse, collections, datetime, glob, json, os, re, sys

# $/MTok: input, output, cache read, cache write
PRICES = {
    "claude-fable-5-1": (10, 50, 0.25, 12.5),
    "claude-opus-5": (5, 25, 0.5, 6.25),
    "claude-sonnet-5": (2, 10, 0.2, 2.5),
    "claude-haiku-4-5": (1, 5, 0.1, 1.25),
}


def project_dir():
    return os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))


def tally(path, agg):
    seen = set()
    for line in open(path):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") != "assistant":
            continue
        m = o["message"]
        mid = m.get("id") or o.get("requestId")
        if mid in seen:
            continue
        seen.add(mid)
        u = m.get("usage") or {}
        a = agg[m.get("model", "?")]
        a[0] += u.get("input_tokens", 0)
        a[1] += u.get("output_tokens", 0)
        a[2] += u.get("cache_read_input_tokens", 0)
        a[3] += u.get("cache_creation_input_tokens", 0)
        a[4] += 1


def report(files, title):
    agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    for f in files:
        tally(f, agg)
    print(f"## {title}  ({len(files)} transcript files)")
    print("| model | requests | input | output | cache read | cache write | $ at list |")
    print("|---|---|---|---|---|---|---|")
    total = 0.0
    for mod, a in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        p = PRICES.get(mod)
        cost = (a[0] * p[0] + a[1] * p[1] + a[2] * p[2] + a[3] * p[3]) / 1e6 if p else float("nan")
        total += cost if p else 0
        print(f"| {mod} | {a[4]} | {a[0]/1e3:.0f}k | {a[1]/1e3:.0f}k | {a[2]/1e6:.1f}M | {a[3]/1e6:.2f}M | ${cost:.2f} |")
    print(f"| **total** | | | | | | **${total:.2f}** |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", nargs="?", const="", help="session id prefix; default newest")
    ap.add_argument("--since", type=float, help="days back; every session in the window")
    args = ap.parse_args()
    d = project_dir()
    mains = sorted(glob.glob(d + "/*.jsonl"), key=os.path.getmtime)
    if not mains:
        sys.exit(f"no transcripts under {d}")
    if args.since:
        cut = datetime.datetime.now().timestamp() - args.since * 86400
        files = [f for f in mains + glob.glob(d + "/*/subagents/*.jsonl") if os.path.getmtime(f) >= cut]
        report(files, f"last {args.since:g} days")
        return
    if args.session:
        cands = [f for f in mains if os.path.basename(f).startswith(args.session)]
        if not cands:
            sys.exit(f"no session starting with {args.session!r}")
        main_f = cands[-1]
    else:
        main_f = mains[-1]
    sid = os.path.basename(main_f)[:-6]
    subs = glob.glob(f"{d}/{sid}/subagents/*.jsonl")
    report([main_f], f"session {sid[:8]} — main thread")
    if subs:
        report(subs, f"session {sid[:8]} — {len(subs)} subagents")
    report([main_f] + subs, f"session {sid[:8]} — total")


if __name__ == "__main__":
    main()
