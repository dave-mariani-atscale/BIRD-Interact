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

from shared.config import PROJECT_ROOT, settings
from shared import llm_routing
from shared.db_utils import active_grading_corrections
from shared.output_paths import timestamped_output_path
from shared import usage as llm_usage


def _routing_file_label() -> str:
    """The routing file as recorded in a results file: repo-relative when inside the repo."""
    f = llm_routing.routing_file()
    try:
        return str(f.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(f)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _cost_scheme_name() -> str:
    # Lives in system_agent.callbacks (needs google-adk); the runner only names it.
    return "universal_cost_scheme" if settings.leaderboard_mode else "harness_default"


def category_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-category (Query / Management) task counts, pass rates and reward.
    Category comes from the per-task record (written since 2026-09-11); older
    files fall back to the task-id convention `<db>_M_<n>`, which is right for
    all but three Query tasks and is only used for files that predate the field."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in results:
        cat = r.get("category") or ("Management" if "_M_" in str(r.get("task_id", "")) else "Query")
        c = out.setdefault(cat, {"total_tasks": 0, "phase1_count": 0, "phase2_count": 0, "total_reward": 0.0})
        c["total_tasks"] += 1
        c["phase1_count"] += int(bool(r.get("phase1_passed")))
        c["phase2_count"] += int(bool(r.get("phase2_passed")))
        c["total_reward"] += float(r.get("total_reward") or 0)
    for c in out.values():
        n = c["total_tasks"] or 1
        c["phase1_rate"] = c["phase1_count"] / n
        c["phase2_rate"] = c["phase2_count"] / n
        c["average_reward"] = c["total_reward"] / n
    return out


def time_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wall clock normalised by outcome.

    Mean elapsed per task compares arms unfairly: only tasks that pass phase 1
    go on to phase 2, so the arm that passes more does more work and looks
    slower. `seconds_per_reward_point` (total elapsed / total reward) is the
    headline efficiency number -- what a unit of correct answer costs in time.
    The phase split uses the `phase1_completed_at` stamp submit_sql writes into
    session state; runs recorded before that stamp existed report None here.
    """
    elapsed = [float(r.get("elapsed_seconds") or 0) for r in results]
    reward = sum(float(r.get("total_reward") or 0) for r in results)
    p1 = [float(r["phase1_elapsed_seconds"]) for r in results
          if r.get("phase1_elapsed_seconds") is not None]
    p2 = [float(r["phase2_elapsed_seconds"]) for r in results
          if r.get("phase2_elapsed_seconds") is not None]
    n = len(results) or 1
    return {
        "elapsed_seconds_total": round(sum(elapsed), 1),
        "elapsed_seconds_mean": round(sum(elapsed) / n, 1),
        "seconds_per_reward_point": round(sum(elapsed) / reward, 1) if reward > 0 else None,
        "phase1_elapsed_seconds_mean": round(sum(p1) / len(p1), 1) if p1 else None,
        "phase2_reached_count": len(p2),
        "phase2_elapsed_seconds_mean_reached": round(sum(p2) / len(p2), 1) if p2 else None,
    }


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
    # Marks the start of this run's LLM-usage window. The services are
    # long-lived and don't know about runs, so their usage rows are attributed
    # to a run by timestamp — sound because runs are sequential (see --repeat).
    run_started = time.time()
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
            # This run's wall-clock window. llm_usage rows were already
            # attributed by time; grading-audit rows now are too, which is what
            # lets a finished run be re-scored offline without a re-run.
            "run_started": run_started,
            "run_finished": time.time(),
            # HOW PARALLEL THIS RUN WAS. Per-task `elapsed_seconds` includes time
            # queued behind the other tasks in flight, so it is only comparable
            # between runs at the SAME concurrency: the 2026-08-20 waves ran the
            # raw arm ~31-way and the semantic-layer arm ~12-way, which made raw
            # look 449 s/task against 380 and put six databases on the wrong side
            # of the wall-clock comparison for three weeks. `concurrency` is the
            # requested semaphore width; `effective_parallelism` is what actually
            # overlapped (summed task time over the run's own duration), which is
            # lower whenever tasks finish unevenly.
            "concurrency": concurrency,
            "effective_parallelism": round(
                sum(float(r.get("elapsed_seconds") or 0) for r in results)
                / max(time.time() - run_started, 1e-9), 2),
            "grading_audit_path": settings.grading_audit_path,
            # What produced this totals number. `grading_corrections` are the
            # four unconditional comparison fixes (shared/config.py) — listed,
            # not flagged, so every run carries the same set and a score stays
            # self-describing; `feedback_memory` is a real switch that changes a
            # run. `deviations_as_graded` in meta is the grading process's own
            # view of the corrections, which is the authoritative one.
            "deviations": {
                "grading_regime": settings.grading_regime,
                "grading_corrections": list(active_grading_corrections()),
                "feedback_memory": settings.feedback_memory,
                "list_models_question": settings.list_models_question,
                "instruction_file": os.environ.get("ATSCALE_INSTRUCTION_FILE", ""),
                "harness_error_hints": os.environ.get("HARNESS_ERROR_HINTS", "1"),
                # How each model was routed (config/llm_routing.yaml or LLM_ROUTING_FILE):
                # gateway, provider pin, key NAME. Empty = the model's default endpoint.
                "llm_routing_file": _routing_file_label(),
                "llm_routing": {m: llm_routing.route_for(m)
                                for m in (settings.leaderboard_agent_model if settings.leaderboard_mode else settings.system_agent_model,
                                          settings.user_sim_model)},
            },
            # The leaderboard switch and everything it pins, so a results file
            # says on its face whether it is a leaderboard-comparable run.
            "leaderboard_mode": settings.leaderboard_mode,
            "agent_model": settings.system_agent_model,
            "user_sim_model": settings.user_sim_model,
            "cost_scheme": _cost_scheme_name(),
            # API spend for this run, split by role and model. Sits next to the
            # scores on purpose: a score is only interesting alongside what it
            # cost to get, and a cheaper agent model is only a saving if the
            # score held. cache_read_tokens stays 0 until prompt caching is
            # enabled — that field is how you check whether it took effect.
            "llm_usage": llm_usage.aggregate(since=run_started),
            "metrics": {
                "total_tasks": n,
                "total_reward": total_reward,
                "average_reward": total_reward / n,
                "phase1_rate": p1_count / n,
                "phase2_rate": p2_count / n,
                "phase1_count": p1_count,
                "phase2_count": p2_count,
                **time_metrics(results),
                # Query vs Management split. A leaderboard-mode run mixes the two
                # (Management routed to raw); the blended figures above are the
                # leaderboard's numbers, these say where they came from.
                "by_category": category_metrics(results),
            },
            "results": results,
        }
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)

    async def _run_one(i: int, td: dict):
        nonlocal total_reward, p1_count, p2_count, completed
        instance_id = td["instance_id"]
        async with semaphore:
            question = " ".join((td.get("amb_user_query") or "").split())
            if len(question) > 150:
                question = question[:150] + "..."
            logger.info("=== Task %d/%d: %s ===\n    Q: %s",
                        i + 1, len(tasks), instance_id, question)
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
            outcome = ("PASS both phases" if r.get("phase2_passed")
                       else "PASS phase 1" if r.get("phase1_passed")
                       else "error" if r.get("error") else "fail")
            logger.info("<== %s: %s  reward=%.1f  (%d/%d done, avg %.4f)",
                        instance_id, outcome, r.get("total_reward", 0),
                        completed, len(tasks), total_reward / completed)
            if completed % 5 == 0 or completed == len(tasks):
                await _save()

    await asyncio.gather(*[_run_one(i, td) for i, td in enumerate(tasks)])
    if settings.llm_usage_path:
        # litellm logs an async call from a background task in the calling
        # service's event loop, so the last few rows can land just after the
        # final task returns. Settle before the last aggregate, or a run's
        # reported spend quietly omits its own tail.
        await asyncio.sleep(2)
    await _save()

    n = len(tasks)
    if n:
        tm = time_metrics(results)
        logger.info(
            "\nDone! Tasks: %d, Avg Reward: %.4f, P1: %d/%d (%.1f%%), P2: %d/%d (%.1f%%), "
            "elapsed/task %.0fs, s per reward point %s",
            n, total_reward / n, p1_count, n, p1_count / n * 100,
            p2_count, n, p2_count / n * 100,
            tm["elapsed_seconds_mean"], tm["seconds_per_reward_point"],
        )
        agg = llm_usage.aggregate(since=run_started)
        if agg.get("calls"):
            logger.info("%s", llm_usage.format_summary(agg))
        elif settings.llm_usage_path:
            # Silence here means the hook never fired, not that a run was free —
            # most likely the services predate this change and need a restart
            # (scripts/start_services.sh), since they register the callback at
            # import time.
            logger.warning(
                "No LLM usage rows for this run in %s — restart the services to pick up "
                "usage accounting (scripts/start_services.sh).", settings.llm_usage_path,
            )


def load_tasks(data_path: str, limit: int = None, databases: List[str] = None, query_only: bool = False,
               tasks_filter: List[str] = None) -> List[dict]:
    tasks = []
    with open(data_path) as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))

    if query_only and settings.environment_backend == "raw":
        # Makes the raw arm's task set identical to a non-raw arm's, which is
        # what the headline scores have to share to be comparable at all:
        # without it raw ran 29 households tasks against the atscale arm's 21
        # (600 against 410 across the suite), and raw's larger set is most of
        # why its headline looked higher.
        #
        # Symmetry holds because this is the IDENTICAL predicate the non-raw
        # branch below applies, not a per-arm re-derivation of "is this DDL".
        # The predicate is category-based and deliberately not a perfect DDL
        # detector: households_M_1 is Management-category but its gold only
        # counts rows, and M_6 through M_9 ask read-only questions whose gold
        # wraps the answer in CREATE OR REPLACE VIEW. So it over-excludes a few
        # answerable tasks - but it over-excludes the same ones from both arms,
        # which is the property that matters.
        before_count = len(tasks)
        tasks = [t for t in tasks if t.get("category") == "Query"]
        logger.warning("--query-only: excluded %d Management-category tasks (%d Query tasks remain)",
                        before_count - len(tasks), len(tasks))

    if settings.environment_backend != "raw":
        if settings.leaderboard_mode:
            # Leaderboard mode scores all 600 tasks: Management-category tasks
            # are kept and routed per task to the raw tools and raw grading
            # (orchestrator.ainteract.task_backend), so only the Query tasks
            # need a semantic model.
            n_mgmt = sum(1 for t in tasks if t.get("category") != "Query")
            logger.warning("LEADERBOARD MODE: keeping %d Management-category tasks; they run on the "
                           "raw backend, the %d Query tasks on '%s'",
                           n_mgmt, len(tasks) - n_mgmt, settings.environment_backend)
        else:
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
        tasks = [t for t in tasks
                 if t.get("selected_database") in configured or t.get("category") != "Query"]
        logger.warning("Non-raw backend '%s': %d/%d tasks eligible (Query tasks need a configured "
                       "semantic model; domains: %s)",
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


def _get_health(name: str, port: int) -> dict:
    url = f"http://localhost:{port}/health"
    try:
        resp = httpx.get(url, timeout=10.0, trust_env=False)
        resp.raise_for_status()
        return resp.json() or {}
    except Exception as exc:
        raise SystemExit(f"Could not read {name}'s /health ({url}): {exc}. Is it running? "
                         f"(scripts/start_services.sh)")


def _check_services() -> dict:
    """Refuse to score a run on a stack that disagrees with this runner.

    The three services are long-lived processes that read settings at start-up;
    this runner cannot change what they hold. So before a run every one of them
    must report the SAME leaderboard_mode as the runner, the grading service the
    same regime and corrections, the agent service the same model and cost
    scheme, and the simulator the same model. A mismatch means a service was not
    restarted after the switch, and a run scored on it would carry a mixed
    protocol - exactly what happened on 2026-08-25/26, when a service had an
    order lint on while the recorded deviations said off, and two runs differing
    by exactly that were compared as comparable. Hard stop, with the fix named.

    Returns the grading service's own view of the regime, which is what the
    results file records as `deviations_as_graded`: grading runs there.
    """
    want_lb = settings.leaderboard_mode
    fix = ("Restart all three services so they pick up the same settings as this runner: "
           f"LEADERBOARD_MODE={'true' if want_lb else 'false'} bash scripts/start_services.sh")
    sa = _get_health("system_agent", settings.system_agent_port)
    us = _get_health("user_simulator", settings.user_sim_port)
    db = _get_health("db_environment", settings.db_env_port)
    problems = []
    for name, h in (("system_agent", sa), ("user_simulator", us), ("db_environment", db)):
        if "leaderboard_mode" not in h:
            problems.append(f"{name} predates the leaderboard switch (no leaderboard_mode on /health)")
        elif bool(h["leaderboard_mode"]) != want_lb:
            problems.append(f"{name} reports leaderboard_mode={h['leaderboard_mode']}, runner has {want_lb}")
    regime = (db.get("grading") or {})
    served = regime.get("corrections")
    if served is None:
        problems.append("db_environment reports no grading corrections list (old build)")
    else:
        want = list(active_grading_corrections())
        if regime.get("regime") != settings.grading_regime or sorted(served) != sorted(want):
            problems.append(f"db_environment grades under regime={regime.get('regime')!r} corrections={served}, "
                            f"runner expects {settings.grading_regime!r} {want}")
    if sa.get("model") and sa["model"] != settings.system_agent_model:
        problems.append(f"system_agent model is {sa['model']!r}, runner expects {settings.system_agent_model!r}")
    if us.get("model") and us["model"] != settings.user_sim_model:
        problems.append(f"user_simulator model is {us['model']!r}, runner expects {settings.user_sim_model!r}")
    if sa.get("cost_scheme") and sa["cost_scheme"] != _cost_scheme_name():
        problems.append(f"system_agent cost scheme is {sa['cost_scheme']!r}, runner expects {_cost_scheme_name()!r}")
    if want_lb and settings.environment_backend != "raw":
        # The submission carries the engine's OUTBOUND SQL. With aggregates on,
        # that SQL reads aggregates.as_agg_* tables the BIRD evaluator does not
        # have, and every such task scores zero there (seen live 2026-09-11). In
        # leaderboard mode the harness sends disable_aggregates=true on every
        # run_query, which needs an MCP server that understands the parameter
        # (it advertises that on /configz); a server-wide flag also satisfies it.
        url = f"{settings.semantic_layer_mcp_admin_url.rstrip('/')}/configz"
        try:
            cfg = httpx.get(url, timeout=10.0, trust_env=False).json()
        except Exception as exc:
            cfg = {"error": str(exc)}
        if not (cfg.get("per_query_disable_aggregates") is True or cfg.get("disable_aggregates") is True):
            problems.append(f"the MCP server at {url} neither accepts run_query(disable_aggregates=true) nor "
                            f"disables aggregates globally ({cfg}); deploy an MCP build with the per-query "
                            "parameter (or set SEMANTIC_LAYER_MCP_ADMIN_URL if the server is elsewhere)")
    if problems:
        raise SystemExit("SERVICE / RUNNER MISMATCH - refusing to run:\n  - " + "\n  - ".join(problems) + "\n" + fix)
    logger.info("Services agree: leaderboard_mode=%s, grading regime=%s (%s), agent=%s, simulator=%s (%s), cost scheme=%s",
                want_lb, regime.get("regime"), ", ".join(served) or "none", sa.get("model"), us.get("model"),
                us.get("simulator_variant"), sa.get("cost_scheme"))
    return regime


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

    if args.query_only and settings.leaderboard_mode:
        parser.error("--query-only cannot be combined with LEADERBOARD_MODE: a leaderboard run scores all "
                     "600 tasks (Management tasks are routed to the raw backend).")
    if settings.leaderboard_mode:
        logger.warning("LEADERBOARD MODE: upstream grading, simulator %s (upstream prompts), agent %s, "
                       "Universal Cost Scheme, Management tasks routed to raw, outbound SQL recorded.",
                       settings.user_sim_model, settings.system_agent_model)
    _set_service_backend(args.backend)
    graded_regime = _check_services()

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
                  "repeat_total": args.repeat,
                  # What the GRADING process's flags were, read from it directly.
                  # `deviations` below is this process's view of the same flags;
                  # when they differ, this is the one that scored the run.
                  "deviations_as_graded": graded_regime,
                  # Task scope, so a results file states its own comparability.
                  "query_only": args.query_only,
                  "task_count": len(tasks),
                  "task_categories": {c: sum(1 for t in tasks if t.get("category", "Query") == c)
                                      for c in sorted({t.get("category", "Query") for t in tasks})}},
        ))


if __name__ == "__main__":
    main()
