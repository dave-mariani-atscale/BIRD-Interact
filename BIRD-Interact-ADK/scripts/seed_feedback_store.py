#!/usr/bin/env python3
"""Re-seed the MCP feedback store from a run's grading audit. NO LLM calls.

Replays each recorded submission through the SAME two tool calls the harness
makes during a run: run_query(pred_sql, question) to create the exchange, then
record_feedback with the recorded verdict (source=end_user_explicit, rater
bird_simulator, the deployment rater token). The store that results is what the
run itself would have left behind — agent SQL and simulator verdicts only,
never gold.

Purpose: offline diagnosis of the memory serving gates (probe_memory_blocks.py)
when a run's store was not retained. Only run against a store you have backed
up (pg_dump -n mcp_feedback); this script never truncates anything itself.

    python scripts/seed_feedback_store.py --audit <audit.jsonl> \
        --databases hulushows,solar_panel [--limit N]
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import settings                       # noqa: E402
from shared.feedback import _EXCHANGE_LINE               # noqa: E402
from shared.mcp_client import MCPClient, MCPEndpoint     # noqa: E402

TASKS = Path("bird-interact-full/bird_interact_data.jsonl")


def questions_by_task() -> dict[str, str]:
    out: dict[str, str] = {}
    with TASKS.open() as f:
        for line in f:
            row = json.loads(line)
            out[row["instance_id"]] = row.get("amb_user_query") or ""
    return out


def clarifications_by_task(results_json: Path) -> dict[str, str]:
    """Task -> the run's ask_user transcript in the harness note format."""
    if not results_json.exists():
        return {}
    data = json.loads(results_json.read_text())
    out: dict[str, str] = {}
    for r in data.get("results", []):
        pairs, pending = [], ""
        for turn in r.get("dialogue_history") or []:
            content = " ".join(str(turn.get("content", "")).split())
            if turn.get("role") == "agent":
                pending = content
            elif turn.get("role") == "user" and content and pending:
                pairs.append(f"Q: {pending} -> A: {content}")
                pending = ""
        if pairs:
            out[r["task_id"]] = "\n".join(reversed(pairs))[:1500]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    ap.add_argument("--databases", required=True, help="csv of BIRD database names")
    ap.add_argument("--results-json", default="",
                    help="optional harness results file; its dialogue histories "
                         "supply the clarification transcripts the harness notes carry")
    ap.add_argument("--limit", type=int, default=0, help="max rows per database (0 = all)")
    args = ap.parse_args()
    dbs = {d.strip() for d in args.databases.split(",") if d.strip()}

    questions = questions_by_task()
    clarifications = (
        clarifications_by_task(Path(args.results_json)) if args.results_json else {}
    )
    cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                                bearer_token=settings.semantic_layer_mcp_token))

    per_db: Counter[str] = Counter()
    stats = Counter()
    t0 = time.time()
    with open(args.audit) as f:
        for line in f:
            row = json.loads(line)
            task = row.get("task_id", "")
            db = task.rsplit("_", 1)[0]
            if db not in dbs or row.get("backend") != "atscale":
                continue
            if args.limit and per_db[db] >= args.limit:
                continue
            sql, question = row.get("pred_sql") or "", questions.get(task, "")
            if not sql or not question:
                stats["skipped_no_sql_or_question"] += 1
                continue
            per_db[db] += 1
            try:
                text = cli.call_tool("run_query", {"query": sql, "question": question})
            except Exception as exc:
                stats["run_query_error"] += 1
                print(f"  {task}: run_query failed: {str(exc)[:120]}")
                continue
            match = _EXCHANGE_LINE.search(text or "")
            if not match:
                stats["no_exchange"] += 1
                continue
            note = "seeded from grading audit"
            clar = clarifications.get(task, "")
            if clar:
                note += f"\n\n--- clarifications ---\n{clar}"
            payload = {
                "exchangeId": match.group(1),
                "verdict": "correct" if row.get("passed") else "incorrect",
                "source": "end_user_explicit",
                "rater": "bird_simulator",
                "note": note,
            }
            if settings.feedback_rater_token:
                payload["raterToken"] = settings.feedback_rater_token
            try:
                cli.call_tool("record_feedback", payload)
                stats["recorded"] += 1
            except Exception as exc:
                stats["record_error"] += 1
                print(f"  {task}: record_feedback failed: {str(exc)[:120]}")

    print(f"done in {time.time() - t0:.0f}s: {dict(stats)}  per-db {dict(per_db)}")


if __name__ == "__main__":
    main()
