#!/usr/bin/env python3
"""Where do the bird-coins go? Offline trajectory accounting, per arm (B-50).

    python scripts/coin_spend.py --runs results/<atscale>.json results/<raw>.json
    python scripts/coin_spend.py --database crypto_exchange --lastn 2 --intersect
    python scripts/coin_spend.py --lastn 3 --intersect --by-tool --pooled-only

Pass a matched pair of runs with --runs for an arm comparison; over a wider
corpus use --intersect, because the raw arm also runs the Management tasks and
more databases and an unrestricted arm-vs-arm share is not like-for-like.

No LLM calls: every number here is read out of `tool_trajectory`, which records
the charged `cost` and the `budget_before`/`budget_after` of each tool call.

Why this exists: 80-91% of tasks in both arms end with no coins left, so the
score is capped by spend rather than by SQL skill, and a rule that fires
correctly can still convert nothing. Before changing any budget default (an
upstream number -- see CLAUDE.md) you need to know which category the coins
actually went to, and whether the two arms spend them differently. A category
that is symmetric across arms bounds the *score*; only an asymmetric one moves
*lift*.

Categories are the four things a coin can buy:
  discovery  split into `schema` (schema/model exploration) and `knowledge`
             (the external-knowledge glossary), which are NOT comparable across
             arms -- see KNOWLEDGE_TOOLS and tracker B-12
  query      a trial query that was not a submission
  ask        a clarifying question to the user simulator
  submit     a graded submission, split by whether it scored

Read `actions bought ... per coin` as the headline: two arms can spend the same
number of coins and buy very different numbers of actions with them.

One inference to avoid: exhausted tasks score lower than tasks with coins to
spare, but that is confounded in both directions -- a task solved quickly stops
spending. `forced exit` is the unconfounded signal that the budget ended a task.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.summarize_runs import load_runs, run_health

QUERY_TOOLS = {"execute_sql", "run_query"}
# The external-knowledge glossary. Split out of discovery because the two arms
# do not have the same tools here: the semantic-layer arm has no glossary tools,
# so the raw arm gets three and the semantic-layer arm gets none (tracker B-12,
# and the rationale in shared/config.py). Comparing whole-discovery shares
# across arms without this split compares two different purchases.
# get_sml_skills is the atscale arm's stand-in and returns query-construction
# guidance rather than definitions, so it is counted here but is not equivalent.
KNOWLEDGE_TOOLS = {"get_all_external_knowledge_names", "get_knowledge_definition",
                   "get_all_knowledge_definitions", "get_sml_skills"}
ASK_TOOLS = {"ask_user"}
SUBMIT_TOOLS = {"submit_sql"}

# A submission's verdict is in its own result text -- the grader's reply is what
# the agent saw. "Phase N correct!" is the only shape that scores.
SCORED = re.compile(r"Phase \d+ correct!")
# Tool-level failure. The atscale arm's run_query rejects a query the semantic
# layer cannot resolve ("Error calling run_query: ..."); raw Postgres surfaces
# its own errors with the ERROR: prefix. Deliberately anchored: a result row can
# legitimately contain the word "error" in its data.
TOOL_ERROR = re.compile(r"^\s*(Error calling |Error:|ERROR:)|\bERROR:\s")


def category(tool: str) -> str:
    if tool in SUBMIT_TOOLS:
        return "submit"
    if tool in QUERY_TOOLS:
        return "query"
    if tool in ASK_TOOLS:
        return "ask"
    return "discovery"


def charged(t: dict) -> float:
    """What the call ACTUALLY cost, which is not always `cost`.

    after_tool_callback records the tool's list price, but before_tool_callback
    lets a final submit through for free when the budget can no longer afford it
    (the "free exit"), and drains the remainder to the -1 stop signal. So a
    3-coin submit can appear in the trajectory having been charged 1.5, or 0.
    Trust the budget delta, and fall back to list price only when the callback
    recorded no budget.
    """
    before, after = t.get("budget_before"), t.get("budget_after")
    cost = t.get("cost") or 0.0
    if before is None:
        return cost
    if after is None or after < 0:
        return min(cost, max(0.0, before))
    return before - after


def account(task: dict) -> dict:
    """One task's spend, broken out by category and by what it bought."""
    traj = [t for t in (task.get("tool_trajectory") or []) if t.get("tool")]
    initial = None
    for t in traj:
        if t.get("budget_before") is not None:
            initial = t["budget_before"]
            break

    a = {
        "id": task.get("instance_id") or task.get("task_id"),
        "db": task.get("database", "?"),
        "reward": task.get("total_reward", 0.0),
        "initial": initial if initial is not None else task.get("budget_used", 0.0),
        "spent": task.get("budget_used", 0.0),
        "left": max(0.0, task.get("budget_remaining", 0.0)),
        "coins": Counter(),      # category -> coins
        "calls": Counter(),      # category -> charged calls
        "by_tool": Counter(),    # tool -> coins
        "tool_calls": Counter(),  # tool -> charged calls
        "free": 0,               # calls refused at no charge
        "turns": len(traj),
    }
    # Coins spent before the agent first looked at any data. High here means the
    # agent is reading the model/schema instead of probing it.
    a["before_first_query"] = 0.0
    seen_query = False

    for t in traj:
        tool, cost = t["tool"], charged(t)
        cat = category(tool)
        result = str(t.get("result") or "")
        if not cost:
            a["free"] += 1
            if cat != "submit":   # a free-exit submit is still graded
                continue
        a["coins"][cat] += cost
        a["calls"][cat] += 1
        a["by_tool"][tool] += cost
        a["tool_calls"][tool] += 1
        if cat == "submit":
            key = "submit_scored" if SCORED.search(result) else "submit_failed"
            a["coins"][key] += cost
            a["calls"][key] += 1
        elif cat == "discovery":
            key = "knowledge" if tool in KNOWLEDGE_TOOLS else "schema"
            a["coins"][key] += cost
            a["calls"][key] += 1
        elif cat == "query" and TOOL_ERROR.search(result):
            a["coins"]["query_error"] += cost
            a["calls"]["query_error"] += 1
        if not seen_query and cat in ("query", "submit"):
            seen_query = True
        elif not seen_query:
            a["before_first_query"] += cost

    # Two thresholds, because they answer different questions. "Cannot submit"
    # is the one that ends a task -- a submission costs 3, so 2.5 coins left is
    # already terminal. "Empty" is the literal floor, and is the figure B-50 was
    # filed with.
    a["cannot_submit"] = a["left"] < 3.0
    a["empty"] = a["left"] <= 0.5
    # A task that never submits scores zero by construction, however good its
    # exploration was. Counted separately because it is the one failure the
    # budget causes outright rather than merely contributes to.
    a["never_submitted"] = a["calls"]["submit"] == 0
    # Cut off rather than finished: the run ended on a submission the agent
    # could no longer afford, which before_tool_callback lets through free as a
    # forced exit. This is the one unambiguous "the budget ended this task"
    # signal -- unlike the reward of exhausted tasks, which is confounded
    # (a task solved quickly stops spending, so low budget correlates with low
    # score in both causal directions).
    a["forced_exit"] = bool(traj) and traj[-1]["tool"] in SUBMIT_TOOLS and \
        charged(traj[-1]) < (traj[-1].get("cost") or 0)
    return a


def pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "    -"


CATS = ("discovery", "query", "ask", "submit")


def report_arm(label: str, arm: str, accounts: list, nruns: int, show_tools=False):
    coins, calls = Counter(), Counter()
    tool_coins, tool_calls = Counter(), Counter()
    for a in accounts:
        coins.update(a["coins"])
        calls.update(a["calls"])
        tool_coins.update(a["by_tool"])
        tool_calls.update(a["tool_calls"])
    total = sum(coins[c] for c in CATS)
    n = len(accounts)

    print(f"\n--- {label} / {arm}   {n} tasks, {nruns} run(s) ---")
    print(f"  budget {statistics.mean(a['initial'] for a in accounts):.1f} mean/task"
          f" | {total:.0f} coins charged"
          f" | {sum(a['left'] for a in accounts):.0f} unspent")
    ns, ne = sum(a["cannot_submit"] for a in accounts), sum(a["empty"] for a in accounts)
    print(f"  ended with <3 coins (cannot submit): {ns}/{n} ({100*ns/n:.0f}%)"
          f"   |  <=0.5 (empty): {ne}/{n} ({100*ne/n:.0f}%)")

    print(f"\n  {'category':<12}{'coins':>8}{'share':>8}{'calls':>7}{'per task':>10}{'coins/call':>12}")
    for cat in ("discovery", "  schema", "  knowledge", "query", "ask", "submit"):
        k = cat.strip()
        per_call = f"{coins[k]/calls[k]:>12.2f}" if calls[k] else f"{'-':>12}"
        print(f"  {cat:<12}{coins[k]:>8.0f}{pct(coins[k], total):>8}"
              f"{calls[k]:>7}{coins[k]/n:>10.1f}{per_call}")
    print(f"  {'TOTAL':<12}{total:>8.0f}{'100.0%':>8}"
          f"{sum(calls[c] for c in CATS):>7}{total/n:>10.1f}")

    waste = coins["submit_failed"] + coins["query_error"]
    print(f"\n  bought nothing:  {waste:>5.0f} coins ({pct(waste, total).strip()})"
          f"  = {calls['submit_failed']} failed submits ({coins['submit_failed']:.0f})"
          f" + {calls['query_error']} errored queries ({coins['query_error']:.0f})")
    print(f"  scored submits:  {calls['submit_scored']:>5} "
          f"({coins['submit_scored']:.0f} coins)")
    # A submission costs 3 -- three times a query -- and with
    # the harness returns upstream's bare "your SQL is not correct" and
    # nothing else. So repeated failed submits are the most expensive way to
    # learn the least, and the count per task says how much of that is guessing.
    hist = Counter(a["calls"]["submit_failed"] for a in accounts)
    print("  failed submits/task: "
          + "  ".join(f"{k}x:{hist[k]}" for k in sorted(hist)))
    forced = sum(a["forced_exit"] for a in accounts)
    print(f"  forced exit (ended on a submit it could not afford): {forced}/{n}"
          f" ({100*forced/n:.0f}%)")
    print(f"  actions bought:  {sum(calls[c] for c in CATS):>5} "
          f"= {sum(calls[c] for c in CATS)/total:.2f} per coin")
    print(f"  pre-first-query: {statistics.mean(a['before_first_query'] for a in accounts):>5.1f} /task"
          f"  ({pct(sum(a['before_first_query'] for a in accounts), total).strip()} of spend)")
    never = [a for a in accounts if a["never_submitted"]]
    if never:
        print(f"  NEVER submitted: {len(never):>5}/{n} tasks -- "
              f"{sum(a['spent'] for a in never):.0f} coins spent for a guaranteed 0: "
              + ", ".join(a["id"] for a in never))
    free = sum(a["free"] for a in accounts)
    if free:
        print(f"  refused free:    {free:>5}  (a turn, not a coin)")

    # Does spend actually cap the score? Compare the tasks that ran out against
    # the ones that did not. If the two groups spend alike, the budget is not
    # the discriminator and B-50 is the wrong lever.
    if show_tools:
        # Per tool, because the price list is not symmetric between the arms:
        # raw can buy one column's meaning or one knowledge definition for 0.5,
        # while most of the semantic layer's exploration costs 1.0. Same coins
        # can therefore buy the raw arm noticeably more calls.
        print(f"\n  {'tool':<32}{'coins':>7}{'calls':>7}{'coins/call':>12}")
        for t, c in tool_coins.most_common():
            print(f"  {t:<32}{c:>7.0f}{tool_calls[t]:>7}{c/tool_calls[t]:>12.2f}")

    print()
    for name, group in (("ran out", [a for a in accounts if a["cannot_submit"]]),
                        ("coins left", [a for a in accounts if not a["cannot_submit"]])):
        if not group:
            continue
        g = Counter()
        for a in group:
            g.update(a["coins"])
        gt = sum(g[c] for c in CATS) or 1
        print(f"  {name:<11} n={len(group):<3} reward {statistics.mean(a['reward'] for a in group):.2f}"
              f"  turns {statistics.mean(a['turns'] for a in group):>4.1f}   "
              + "  ".join(f"{c[0].upper()} {pct(g[c], gt).strip()}" for c in CATS))


def per_task(arm: str, accounts: list):
    print(f"\n  per task [{arm}]   D=discovery Q=query A=ask S=submit, ! = ran out")
    print(f"    {'task':<26}{'rwd':>5}{'bud':>5}{'D':>5}{'Q':>5}{'A':>5}{'S':>5}"
          f"{'fail':>6}{'left':>6}")
    for a in sorted(accounts, key=lambda a: a["id"]):
        c = a["coins"]
        print(f"    {a['id']:<26}{a['reward']:>5.2f}{a['initial']:>5.0f}"
              f"{c['discovery']:>5.0f}{c['query']:>5.0f}{c['ask']:>5.0f}{c['submit']:>5.0f}"
              f"{c['submit_failed']:>6.0f}{a['left']:>6.1f}"
              f"{'  !' if a['cannot_submit'] else ''}")


def load_explicit(paths: list) -> list:
    runs = []
    for p in paths:
        with open(p) as f:
            doc = json.load(f)
        results = doc.get("results") or []
        base = os.path.basename(p)
        arm = doc.get("backend") or ("raw" if "_raw" in base else "atscale")
        runs.append({"path": base, "arm": arm, "doc": doc,
                     "by_id": {r["task_id"]: r for r in results}})
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--database")
    ap.add_argument("--lastn", type=int, help="N most recent runs PER ARM")
    ap.add_argument("--runs", nargs="+", help="explicit run files, bypassing discovery")
    ap.add_argument("--per-task", action="store_true")
    ap.add_argument("--by-tool", action="store_true",
                    help="add the per-tool price/volume table")
    ap.add_argument("--intersect", action="store_true",
                    help="restrict to task ids BOTH arms attempted. The raw arm "
                         "also runs the Management tasks and more databases, so "
                         "an unrestricted arm-vs-arm share is not like-for-like")
    ap.add_argument("--pooled-only", action="store_true",
                    help="skip the per-database tables")
    ap.add_argument("--include-suspect", action="store_true",
                    help="keep runs summarize_runs flags as broken infrastructure")
    args = ap.parse_args()

    runs = (load_explicit(args.runs) if args.runs
            else load_runs(args.results_dir, args.database, args.lastn))
    if not runs:
        print("no runs found")
        return

    # Grouped by the TASK's database, not the run's: a validation run can span
    # three databases, and pooling them would hide exactly the per-database
    # difference these runs exist to show.
    by_arm = defaultdict(list)
    by_arm_db = defaultdict(list)
    nruns = Counter()
    skipped_empty = Counter()
    for r in runs:
        if not args.include_suspect:
            bad, why = run_health(r)
            if bad:
                print(f"skipping {r['path']}: {why}")
                continue
        if r["arm"] not in ("raw", "atscale"):
            # Pre-provenance runs: no `backend` key and nothing in the filename.
            # An unattributable arm cannot say anything about lift.
            print(f"skipping {r['path']}: arm not recorded")
            continue
        nruns[r["arm"]] += 1
        for t in r["by_id"].values():
            if not (t.get("tool_trajectory") or []):
                skipped_empty[r["arm"]] += 1
                continue
            a = account(t)
            by_arm[r["arm"]].append(a)
            by_arm_db[(a["db"], r["arm"])].append(a)

    if args.intersect:
        ids = [{a["id"] for a in by_arm[arm]} for arm in ("raw", "atscale") if by_arm.get(arm)]
        keep = set.intersection(*ids) if len(ids) == 2 else set()
        for d in (by_arm, by_arm_db):
            for k in list(d):
                d[k] = [a for a in d[k] if a["id"] in keep]
                if not d[k]:
                    del d[k]
        print(f"--intersect: {len(keep)} task ids attempted by both arms")

    print("=" * 76)
    print("COIN SPEND BY CATEGORY   a-interact, offline from tool_trajectory")
    print("=" * 76)
    if skipped_empty:
        print(f"  (skipped tasks with no recorded trajectory: {dict(skipped_empty)})")
    for arm in sorted(by_arm):
        report_arm("POOLED", arm, by_arm[arm], nruns[arm], show_tools=args.by_tool)
        if args.per_task:
            per_task(arm, by_arm[arm])
    if not args.pooled_only and len({db for db, _ in by_arm_db}) > 1:
        print("\n" + "=" * 76)
        print("PER DATABASE")
        print("=" * 76)
        for (db, arm) in sorted(by_arm_db):
            report_arm(db, arm, by_arm_db[(db, arm)], nruns[arm])
    print()


if __name__ == "__main__":
    main()
