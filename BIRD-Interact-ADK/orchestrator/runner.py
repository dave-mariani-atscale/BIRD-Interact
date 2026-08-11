"""Unified parallel evaluation runner for BIRD-Interact benchmark."""

import asyncio
import argparse
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Awaitable, Dict, List

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import settings
from shared.output_paths import timestamped_output_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def run_parallel_evaluation(
    tasks: List[dict],
    run_single_task: Callable[[dict], Awaitable[Dict[str, Any]]],
    output_path: str,
    concurrency: int = 5,
    mode: str = "a-interact",
    meta: Dict[str, Any] = None,
):
    semaphore = asyncio.Semaphore(concurrency)
    results: List[Dict[str, Any]] = []
    results_lock = asyncio.Lock()
    total_reward = 0.0
    p1_count = 0
    p2_count = 0
    completed = 0
    # Stamped once here, not per _save(), so incremental saves keep
    # appending to this run's own file instead of starting a new one.
    output_path = timestamped_output_path(output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Writing results to %s", output_path)

    async def _save():
        n = len(results)
        if n == 0:
            return
        output = {
            "mode": mode,
            # Run provenance so a summary tool can group runs without parsing
            # filenames -- which arm and which repetition this file is.
            **(meta or {}),
            # Anything but "none" makes these scores non-comparable to published
            # BIRD-Interact numbers, so the run records which regime produced it.
            "submit_feedback_level": settings.submit_feedback_level,
            # Deviations from upstream's protocol, all off by default. Recorded
            # so a totals number always carries the regime that produced it.
            "deviations": {
                "grading_tie_tolerance": settings.grading_tie_tolerance,
                "grading_honor_decimal": settings.grading_honor_decimal,
                "grading_casefold": settings.grading_casefold,
                "grading_rel_tolerance": settings.grading_rel_tolerance,
                "free_wasted_actions": settings.free_wasted_actions,
                # Not a grading change: it changes what the semantic-layer arm
                # can DO, so two runs differing only here are not comparable.
                "semantic_layer_knowledge_tools": settings.semantic_layer_knowledge_tools,
            },
            "metrics": {
                "total_tasks": n,
                "total_reward": total_reward,
                "average_reward": total_reward / n,
                "phase1_rate": p1_count / n,
                "phase2_rate": p2_count / n,
                "phase1_count": p1_count,
                "phase2_count": p2_count,
            },
            "results": results,
        }
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)

    async def _run_one(i: int, td: dict):
        nonlocal total_reward, p1_count, p2_count, completed
        instance_id = td["instance_id"]
        async with semaphore:
            logger.info("=== Task %d/%d: %s ===", i + 1, len(tasks), instance_id)
            try:
                r = await run_single_task(td)
            except Exception as e:
                logger.error("Error: %s: %s", instance_id, e)
                traceback.print_exc()
                r = {"task_id": instance_id, "error": str(e), "total_reward": 0}

        async with results_lock:
            results.append(r)
            total_reward += r.get("total_reward", 0)
            if r.get("phase1_passed"):
                p1_count += 1
            if r.get("phase2_passed"):
                p2_count += 1
            completed += 1
            if completed % 5 == 0 or completed == len(tasks):
                await _save()

    await asyncio.gather(*[_run_one(i, td) for i, td in enumerate(tasks)])
    await _save()

    n = len(tasks)
    if n:
        logger.info(
            "\nDone! Tasks: %d, Avg Reward: %.4f, P1: %d/%d (%.1f%%), P2: %d/%d (%.1f%%)",
            n, total_reward / n, p1_count, n, p1_count / n * 100,
            p2_count, n, p2_count / n * 100,
        )


def load_tasks(data_path: str, limit: int = None, databases: List[str] = None, query_only: bool = False,
               tasks_filter: List[str] = None) -> List[dict]:
    tasks = []
    with open(data_path) as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))

    if query_only and settings.environment_backend == "raw":
        before_count = len(tasks)
        tasks = [t for t in tasks if t.get("category") == "Query"]
        logger.warning("--query-only: excluded %d Management-category tasks (%d Query tasks remain)",
                        before_count - len(tasks), len(tasks))

    if settings.environment_backend != "raw":
        # Semantic layers are read-only — Management-category (DDL/DML) tasks
        # are structurally inapplicable, not a harness bug to route around
        # (see docs/semantic-layer-environment-backends.md's "Task scope").
        # Verified: a Query phase-1 task never has a Management follow-up, so
        # filtering on phase-1 category alone is sufficient.
        before_count = len(tasks)
        tasks = [t for t in tasks if t.get("category") == "Query"]
        logger.warning("Non-raw backend '%s': excluded %d Management-category tasks (%d Query tasks remain)",
                        settings.environment_backend, before_count - len(tasks), len(tasks))

        # Only domains with a real semantic model configured are eligible —
        # run the whole suite at once, coverage grows as domains get modeled.
        from shared.environment_backends import get_configured_domains
        configured = get_configured_domains(settings.environment_backend)
        before_count = len(tasks)
        tasks = [t for t in tasks if t.get("selected_database") in configured]
        logger.warning("Non-raw backend '%s': %d/%d tasks have a configured semantic model (domains: %s)",
                        settings.environment_backend, len(tasks), before_count, sorted(configured))

    if databases:
        wanted = set(databases)
        available = {t.get("selected_database") for t in tasks}
        unknown = wanted - available
        if unknown:
            logger.warning("--databases requested unknown database(s) not present in %s: %s", data_path, sorted(unknown))
        before_count = len(tasks)
        tasks = [t for t in tasks if t.get("selected_database") in wanted]
        logger.warning("--databases filter: %d -> %d tasks (databases: %s)", before_count, len(tasks), sorted(wanted & available))
    if tasks_filter:
        # Explicit instance_id list — the iteration lever. Most tasks in a
        # database carry no signal about a given change (many score identically
        # on every run), so a targeted subset buys the same information for a
        # fraction of the API spend. Ordering follows the list given, not the
        # file, so a cheap regression canary can run first.
        wanted = [t.strip() for t in tasks_filter if t.strip()]
        by_id = {t["instance_id"]: t for t in tasks}
        missing = [w for w in wanted if w not in by_id]
        if missing:
            # Loud, because a typo'd id silently shrinking the set would look
            # like a score change rather than a smaller denominator.
            logger.warning("--tasks: %d requested id(s) not present after the other filters: %s",
                           len(missing), missing)
        before_count = len(tasks)
        tasks = [by_id[w] for w in wanted if w in by_id]
        logger.warning("--tasks filter: %d -> %d tasks", before_count, len(tasks))
    if limit:
        tasks = tasks[:limit]
    return tasks


async def run_oracle_task(task_data: dict) -> Dict[str, Any]:
    """Submit ground-truth SQL directly — no LLM, tests evaluation pipeline."""
    import httpx
    db_env = f"http://localhost:{settings.db_env_port}"
    user_sim = f"http://localhost:{settings.user_sim_port}"

    async def _post(url, payload, timeout=60.0):
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as c:
            r = await c.post(url, json=payload)
            r.raise_for_status()
            return r.json()

    instance_id = task_data["instance_id"]
    sol_sql = task_data.get("sol_sql", [])
    if isinstance(sol_sql, str):
        sol_sql = [sol_sql]
    fu = task_data.get("follow_up", {})
    fu_sql = fu.get("sol_sql", [])
    if isinstance(fu_sql, str):
        fu_sql = [fu_sql]
    has_follow_up = bool(fu and fu_sql)

    await _post(f"{db_env}/init_task", {
        "task_id": instance_id,
        "task_data": {**task_data, "_interact_mode": "a-interact"},
    })

    try:
        p1_passed = False
        p2_passed = False
        total_reward = 0.0

        if sol_sql:
            r1 = await _post(f"{db_env}/submit", {"task_id": instance_id, "sql": sol_sql[0]})
            p1_passed = r1.get("passed", False)
            if p1_passed:
                total_reward += r1.get("reward", 0.0)

            if p1_passed and has_follow_up:
                try:
                    await _post(f"{user_sim}/init_task", {"task_id": instance_id, "task_data": task_data})
                    await _post(f"{user_sim}/phase_transition", {"task_id": instance_id})
                except Exception:
                    pass
                r2 = await _post(f"{db_env}/submit", {"task_id": instance_id, "sql": fu_sql[0]})
                p2_passed = r2.get("passed", False)
                if p2_passed:
                    total_reward += r2.get("reward", 0.0)

        return {
            "task_id": instance_id,
            "instance_id": instance_id,
            "database": task_data["selected_database"],
            "phase1_passed": p1_passed,
            "phase2_passed": p2_passed,
            "has_follow_up": has_follow_up,
            "total_reward": total_reward,
        }
    finally:
        try:
            await _post(f"{db_env}/cleanup_task", {"task_id": instance_id})
        except Exception:
            pass


def _set_service_backend(backend: str) -> None:
    """The system_agent and db_environment services are separate long-lived
    processes (started via scripts/start_services.sh) that read
    settings.environment_backend from their own process memory, not this
    --backend flag. Push it to both over HTTP so no restart is needed —
    system_agent additionally rebuilds its cached ADK agent so the new
    backend's tool set actually takes effect."""
    checks = [
        ("system_agent", f"http://localhost:{settings.system_agent_port}/set_backend"),
        ("db_environment", f"http://localhost:{settings.db_env_port}/set_backend"),
    ]
    for name, url in checks:
        try:
            resp = httpx.post(url, json={"backend": backend}, timeout=10.0, trust_env=False)
            resp.raise_for_status()
            confirmed = resp.json().get("environment_backend")
        except Exception as exc:
            raise SystemExit(
                f"Could not set backend {backend!r} on {name} ({url}): {exc}. Is it running? "
                f"(scripts/start_services.sh)"
            )
        if confirmed != backend:
            raise SystemExit(f"{name} confirmed environment_backend={confirmed!r}, expected {backend!r}.")
        logger.info("%s: environment_backend set to %r", name, confirmed)


def main():
    parser = argparse.ArgumentParser(description="BIRD-Interact parallel evaluation")
    parser.add_argument("--mode", choices=["a-interact", "c-interact", "oracle"], default="a-interact")
    parser.add_argument("--data", default=settings.data_path)
    parser.add_argument("--output", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--repeat", type=int, default=1,
                         help="Run the whole evaluation N times in sequence, writing one "
                              "timestamped output file per repetition. Sequential on purpose: "
                              "concurrent runs of the same database would collide on the "
                              "per-task scratch DB name (create_task_db has no run id and "
                              "force-drops it), and /set_backend is global to the shared "
                              "services. Use --concurrency for parallelism within a run.")
    parser.add_argument("--databases", type=str, default=None,
                         help="Comma-separated selected_database values to run (e.g. 'solar_panel,hulushows'). Default: all.")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated instance_ids, or a path to a file of them "
                             "(one per line, # comments allowed). Runs only those, in the "
                             "order given. Use for cheap iteration on a task subset.")
    parser.add_argument("--query-only", action="store_true",
                         help="Run only Query-category tasks on the raw backend (non-raw backends already exclude Management tasks).")
    parser.add_argument("--backend", type=str, default="raw",
                         help="Environment backend: 'raw' (original Postgres tools, default) or a named "
                              "backend from config/environment_backends.yaml (e.g. 'atscale'). Pushed to "
                              "the already-running system_agent/db_environment services via /set_backend "
                              "at startup — no service restart needed.")
    args = parser.parse_args()

    settings.environment_backend = args.backend

    output = args.output or f"results/eval_{args.mode.replace('-', '_')}.json"

    if args.mode == "oracle":
        run_single_task = run_oracle_task
    elif args.mode == "a-interact":
        from orchestrator.ainteract import run_single_task
    else:
        from orchestrator.cinteract import run_single_task

    _set_service_backend(args.backend)

    databases = [d.strip() for d in args.databases.split(",") if d.strip()] if args.databases else None
    tasks_filter = None
    if args.tasks:
        # Accept either a comma-separated list or a path to a file of ids
        # (one per line, '#' comments allowed) so a saved subset is reusable.
        if os.path.isfile(args.tasks):
            with open(args.tasks) as f:
                tasks_filter = [ln.split("#", 1)[0].strip() for ln in f]
        else:
            tasks_filter = args.tasks.split(",")
        tasks_filter = [t for t in tasks_filter if t]
    tasks = load_tasks(args.data, args.limit, databases, args.query_only, tasks_filter)
    logger.info("%s: Evaluating %d tasks with concurrency=%d", args.mode, len(tasks), args.concurrency)

    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    for run_index in range(1, args.repeat + 1):
        # Tag each repetition's filename so a directory listing is unambiguous
        # even if two runs somehow land in the same wall-clock second.
        run_output = output
        if args.repeat > 1:
            p = Path(output)
            run_output = str(p.with_name(f"{p.stem}_run{run_index:02d}{p.suffix}"))
            logger.info("=== repetition %d of %d ===", run_index, args.repeat)
        asyncio.run(run_parallel_evaluation(
            tasks=tasks,
            run_single_task=run_single_task,
            output_path=run_output,
            concurrency=args.concurrency,
            mode=args.mode,
            meta={"backend": args.backend, "run_index": run_index,
                  "repeat_total": args.repeat},
        ))


if __name__ == "__main__":
    main()
