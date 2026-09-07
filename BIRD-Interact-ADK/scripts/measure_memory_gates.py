#!/usr/bin/env python3
"""Measure each feedback-memory serving gate against the CURRENT store contents.

Read-only SQL against mcp_feedback (no MCP, no engine, no LLM). For every block
that list_models can serve, print how much of the store clears its gate and how
much each gate holds back — the numbers behind a "which gate killed this block"
verdict. Mirrors the gates in atscale_mcp/tools/feedback.py; if those change,
change this.

    python scripts/measure_memory_gates.py
"""
import math
import subprocess

PSQL = ["docker", "exec", "postgres", "psql", "-U", "atscale", "-d", "atscale", "-Atc"]

# Gates mirrored from atscale_mcp/tools/feedback.py
COLUMN_MIN_WILSON = 0.25
COLUMN_MIN_QUESTIONS = 2
PRIOR_MIN_QUESTIONS = 2
PRIOR_MIN_DELTA = 0.25
ASK_SLOT_MIN_QUESTIONS = 3
SHAPES_SUPPORT_BARS = (1, 2)


def q(sql: str) -> list[list[str]]:
    out = subprocess.run(PSQL + [sql], capture_output=True, text=True, check=True).stdout
    return [line.split("|") for line in out.splitlines() if line]


def wilson_lower(accepted: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    p = accepted / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - spread) / denom)


def main() -> None:
    norm = "lower(btrim(regexp_replace(question_text, '\\s+', ' ', 'g')))"
    norm_e = norm.replace("question_text", "e.question_text")

    print("== store size")
    for name, n in q(
        "select 'exchange', count(*) from mcp_feedback.exchange "
        "union all select 'feedback', count(*) from mcp_feedback.feedback "
        "union all select 'certified', count(*) from mcp_feedback.certified_query "
        "union all select 'certified accepted', count(*) from mcp_feedback.certified_query "
        "  where state in ('certified','verified')"
    ):
        print(f"  {name}: {n}")

    print("\n== exemplars (gate: serve mode; data requirement: >=1 accepted row per model)")
    for model, n in q(
        "select model, count(*) from mcp_feedback.certified_query "
        "where state in ('certified','verified') group by model order by model"
    ):
        print(f"  {model}: {n} accepted rows -> block would serve (mode gate was the block)")

    print("\n== shapes / query patterns (gate: distinct accepted questions per measures+dims)")
    rows = q(
        "select model, count(*) as groups, "
        f"count(*) filter (where acc >= 1 and acc > rej) as clears_1, "
        f"count(*) filter (where acc >= 2 and acc > rej) as clears_2 "
        "from (select model, "
        f"count(distinct {norm}) filter (where state in ('certified','verified')) as acc, "
        f"count(distinct {norm}) filter (where beta > alpha) as rej "
        "from mcp_feedback.certified_query where shape is not null "
        "and (shape->'measures' is not null or shape->'dimensions' is not null) "
        "group by model, jsonb_build_object('measures', shape->'measures', "
        "'dimensions', shape->'dimensions')) g group by model"
    )
    for model, groups, c1, c2 in rows:
        print(f"  {model}: {groups} patterns; clear bar=1: {c1}; clear bar=2 (old fixed): {c2}")

    print("\n== column track record (gates: accepted_questions >= "
          f"{COLUMN_MIN_QUESTIONS} AND wilson >= {COLUMN_MIN_WILSON})")
    rows = q(
        "select e.model, col, "
        "count(*) filter (where f.verdict='correct') as accepted, "
        "count(*) filter (where f.verdict='incorrect') as rejected, "
        f"count(distinct {norm_e}) filter (where f.verdict='correct') as aq "
        "from mcp_feedback.exchange e "
        "join mcp_feedback.feedback f using (exchange_id) "
        "cross join unnest(e.columns_used) as c(col) "
        "where col <> '' group by e.model, col"
    )
    by_model: dict[str, list[tuple[int, int, int]]] = {}
    for model, _col, a, r, aq in rows:
        by_model.setdefault(model, []).append((int(a), int(r), int(aq)))
    for model, cols in sorted(by_model.items()):
        n = len(cols)
        pass_q = sum(1 for a, r, aq in cols if a > 0 and aq >= COLUMN_MIN_QUESTIONS)
        pass_both = sum(
            1
            for a, r, aq in cols
            if a > 0 and aq >= COLUMN_MIN_QUESTIONS
            and wilson_lower(a, a + r) >= COLUMN_MIN_WILSON
        )
        pass_w_only = sum(1 for a, r, aq in cols if a > 0 and wilson_lower(a, a + r) >= COLUMN_MIN_WILSON)
        print(f"  {model}: {n} columns with verdicts; clear question-floor: {pass_q}; "
              f"clear wilson-floor: {pass_w_only}; clear both (served): {pass_both}")

    print(f"\n== answer-shape conventions (gates: both arms >= {PRIOR_MIN_QUESTIONS} "
          f"questions AND |delta| >= {PRIOR_MIN_DELTA})")
    facets = {
        "distinct": "coalesce((shape->>'distinct')::boolean, false)",
        "limit": "coalesce(shape ? 'limit' and shape->'limit' <> 'null', false)",
        "having": "coalesce((shape->>'having')::boolean, false)",
        "case": "coalesce((shape->>'case')::boolean, false)",
        "window": "coalesce((shape->>'window')::boolean, false)",
        "null_policy": "jsonb_array_length(coalesce(shape->'null_policy','[]')) > 0",
        "ordering": "jsonb_array_length(coalesce(shape->'ordering','[]')) > 0",
        "aggregations": "jsonb_array_length(coalesce(shape->'aggregations','[]')) > 0",
    }
    for model_row in q("select distinct model from mcp_feedback.certified_query"):
        model = model_row[0]
        served = 0
        detail = []
        for key, pred in facets.items():
            row = q(
                f"select count(distinct {norm}) filter (where {pred} and state in ('certified','verified')), "
                f"count(distinct {norm}) filter (where {pred} and beta > alpha), "
                f"count(distinct {norm}) filter (where not {pred} and state in ('certified','verified')), "
                f"count(distinct {norm}) filter (where not {pred} and beta > alpha) "
                "from mcp_feedback.certified_query "
                f"where shape is not null and model = '{model}'"
            )[0]
            pa, pr, aa, ar = (int(v) for v in row)
            if pa + pr < PRIOR_MIN_QUESTIONS or aa + ar < PRIOR_MIN_QUESTIONS:
                detail.append(f"{key}: arm too thin ({pa+pr} vs {aa+ar})")
                continue
            delta = pa / (pa + pr) - aa / (aa + ar)
            if abs(delta) < PRIOR_MIN_DELTA:
                detail.append(f"{key}: delta {delta:+.2f} < {PRIOR_MIN_DELTA}")
                continue
            served += 1
            detail.append(f"{key}: SERVES (delta {delta:+.2f})")
        print(f"  {model}: {served} facet(s) serve")
        for d in detail:
            print(f"    {d}")

    print(f"\n== clarification slots (gate: >= {ASK_SLOT_MIN_QUESTIONS} distinct accepted "
          "questions per ask kind per model)")
    rows = q(
        f"select e.model, count(distinct {norm_e}) "
        "from mcp_feedback.exchange e join mcp_feedback.feedback f using (exchange_id) "
        "where f.verdict = 'correct' and f.note like '%--- clarifications ---%' "
        "group by e.model"
    )
    if not rows:
        print("  no accepted verdict carries a clarification note at all")
    for model, n in rows:
        print(f"  {model}: {n} distinct accepted questions carry clarifications "
              "(upper bound across ALL kinds; per-kind counts are lower)")


if __name__ == "__main__":
    main()
