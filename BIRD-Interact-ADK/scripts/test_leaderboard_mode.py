#!/usr/bin/env python3
"""Unit tests for the leaderboard switch (shared/config.py leaderboard_mode).
Run: PYTHONPATH=. .venv-adk/bin/python scripts/test_leaderboard_mode.py

Each test flips settings.leaderboard_mode in-process and checks that every
behaviour the switch owns follows it: grading regime, simulator variant, cost
table, task routing, pinned models."""
import sys
from decimal import Decimal

sys.path.insert(0, ".")
from shared.config import Settings, LEADERBOARD_USER_SIM_MODEL, settings  # noqa: E402
from shared import db_utils as U  # noqa: E402

ORD, UNORD = {"order": True}, {"order": False}


def _cmp(pred, gold, cond):
    return U._compare_rows(U.preprocess_results(pred), U.preprocess_results(gold), cond,
                           cell=U.canonical_cell, raw=(pred, gold, None))


def with_mode(flag):
    class _Ctx:
        def __enter__(self):
            self.saved = settings.leaderboard_mode
            settings.leaderboard_mode = flag
        def __exit__(self, *a):
            settings.leaderboard_mode = self.saved
    return _Ctx()


def test_regime_names():
    with with_mode(False):
        assert settings.grading_regime == "corrected" and len(settings.grading_corrections) == 6
    with with_mode(True):
        assert settings.grading_regime == "upstream" and settings.grading_corrections == ()
        assert U.active_grading_corrections() == ()


def test_corrections_off_under_upstream():
    # casefold_text: passes corrected, fails upstream
    pred, gold = [("Bifacial", 1)], [("bifacial", 1)]
    with with_mode(False):
        assert _cmp(pred, gold, UNORD) == 1
    with with_mode(True):
        assert _cmp(pred, gold, UNORD) == 0
    # column_order_free
    pred, gold = [(1, "a")], [("a", 1)]
    with with_mode(False):
        assert _cmp(pred, gold, UNORD) == 1
    with with_mode(True):
        assert _cmp(pred, gold, UNORD) == 0
    # numeric_rel_tolerance
    pred, gold = [("a", 12.064999999)], [("a", Decimal("12.065"))]
    with with_mode(False):
        assert _cmp(pred, gold, UNORD) == 1
    with with_mode(True):
        assert _cmp(pred, gold, UNORD) == 0
    # order_requires_cue: relaxed only when corrected
    with with_mode(False):
        assert U.effective_conditions(ORD, "list the plants")["order"] is False
    with with_mode(True):
        assert U.effective_conditions(ORD, "list the plants")["order"] is True
    # timestamp_date
    with with_mode(False):
        assert U.canonical_cell("2025-02-19 16:29:00") == "2025-02-19"
    with with_mode(True):
        assert U.canonical_cell("2025-02-19 16:29:00") == "2025-02-19 16:29:00"
    # exact matches still pass under upstream
    with with_mode(True):
        assert _cmp([("a", 1)], [("a", 1)], ORD) == 1


def test_simulator_variant():
    from user_simulator import prompts as P
    with with_mode(False):
        act, resp = P.get_templates()
        assert P.simulator_variant() == "guarded"
        assert "CRITICAL ROUTING RULE" in act["v2"] and "FIDELITY OF VALUES" in resp["v2"]
    with with_mode(True):
        act, resp = P.get_templates()
        assert P.simulator_variant() == "upstream"
        assert "CRITICAL ROUTING RULE" not in act["v2"] and "FIDELITY OF VALUES" not in resp["v2"]
        assert "[[ROUTING_RULE]]" not in act["v2"] and "[[FIDELITY_RULE]]" not in resp["v2"]
        # upstream guideline list ends at 3
        assert "3. You should NOT ask any question." in resp["v2"]


def test_cost_tables():
    from system_agent.callbacks import effective_tool_costs, cost_scheme_name
    with with_mode(False):
        c = effective_tool_costs("atscale")
        assert c["explore_columns"] == 1.0 and c["focus_columns"] == 0.5 and c["ask_user"] == 2.0
        assert cost_scheme_name() == "harness_default"
    with with_mode(True):
        c = effective_tool_costs("atscale")
        assert c["explore_columns"] == 0.5 and c["run_query"] == 1.0 and c["submit_sql"] == 3.0
        assert cost_scheme_name() == "universal_cost_scheme"
        assert effective_tool_costs("raw")["get_column_meaning"] == 0.5


def test_instruction_costs_follow_table():
    from system_agent.agent import _patch_instruction_costs
    text = "- explore_columns: search. Cost: 1\n- focus_columns: meta. Cost: 0.5\n- ask_user: ask. Cost: 2\n"
    out = _patch_instruction_costs(text, {"explore_columns": 0.5, "ask_user": 2.0})
    assert "- explore_columns: search. Cost: 0.5" in out and "- ask_user: ask. Cost: 2" in out
    assert "- focus_columns: meta. Cost: 0.5" in out


def test_task_routing():
    from orchestrator.ainteract import task_backend
    saved = settings.environment_backend
    settings.environment_backend = "atscale"
    try:
        with with_mode(False):
            assert task_backend({"category": "Management"}) == "atscale"
        with with_mode(True):
            assert task_backend({"category": "Management"}) == "raw"
            assert task_backend({"category": "Query"}) == "atscale"
    finally:
        settings.environment_backend = saved


def test_pinned_models():
    s = Settings(leaderboard_mode=True, user_sim_model="anthropic/claude-sonnet-5",
                 system_agent_model="anthropic/claude-sonnet-5", _env_file=None)
    assert s.user_sim_model == LEADERBOARD_USER_SIM_MODEL
    assert s.system_agent_model == s.leaderboard_agent_model == "anthropic/claude-opus-4-6"
    s2 = Settings(leaderboard_mode=True, leaderboard_agent_model="anthropic/claude-sonnet-5", _env_file=None)
    assert s2.system_agent_model == "anthropic/claude-sonnet-5"
    s3 = Settings(leaderboard_mode=False, user_sim_model="anthropic/claude-sonnet-5", _env_file=None)
    assert s3.user_sim_model == "anthropic/claude-sonnet-5"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
    print("all leaderboard-mode tests passed")
