#!/usr/bin/env bash
# Full 19-task ETF set, both arms, first run since the 2026-08-12/13 pass.
#
# WHAT CHANGED SINCE THE BASELINE. Mostly guidance (agent-side, no deploy) plus
# three model edits. None of it is fitted to a gold answer:
#   model     M-19 three identical PRIMARY/ALTERNATE pairs now say so (false
#             ambiguities were costing a 2-coin ask each)
#             M-20 Premier Income Fund named as a two-condition screen, cut-off
#             deliberately NOT carried
#             M-21 second 52-week price basis exposed as its own attribute
#             KB 81 masked threshold removed (M-22) and now gated by A10
#   guidance  phase-2 budget reserve (A-06); OFFSET is silently ignored (Q-22);
#             NULL ordering is inverted and un-overridable (Q-23); UNION over
#             the model returns zero rows (Q-25); never put a candidate answer
#             in an ask_user question (A-07)
#
# WHICH TASKS THE CHANGES SHOULD MOVE, so a null result is readable:
#   etf_1   M-20      etf_8   A-06 (phase-2 budget)   etf_3   A-07
#   etf_9   M-21      etf_18  M-21                    etf_14  A-06
#   etf_6   B-02 - NOT expected to move; its constants are still unasked and
#           only the generic A-07 bullet touches it. Treat a move here as a
#           bonus, not as the test.
# etf_2/_4/_13/_16/_17/_20 are the canaries: all 1.0 on atscale at baseline.
# Any of them dropping means a guidance edit broke working behaviour - read
# those first, before reading any improvement.
#
# BASELINE, rebase0811 n=1, same flags:
#            atscale 8.10/19 = 42.6%       raw 5.50/19 = 28.9%
#            LIFT +13.7 pp (relative +47.3%)
# Report lift in PERCENTAGE POINTS, with relative alongside. Relative lift is
# unstable here - the raw arm sits at 0.0 on many of these task sets, where it
# is undefined or swings on one task. Keep the x/19 totals visible: at n=1,
# +13.7 pp is 2.6 tasks, and a reader needs to see that.
#   atscale  _2 1.0 _4 1.0 _13 1.0 _16 1.0 _17 1.0 _20 1.0 _5 .7 _14 .7 _19 .7
#            _1 _3 _6 _7 _8 _9 _10 _11 _12 _18 all 0.0
#   raw      _16 1.0 _20 1.0 _4 .7 _5 .7 _14 .7 _18 .7 _19 .7
#            rest 0.0
# LIFT is the number, not either total. n=1 both arms, so treat anything under
# roughly a 2-task swing as noise.
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
source .venv-adk/bin/activate

# Keep the run re-gradable offline later (CLAUDE.md: re-grade, don't re-run).
# etf_3 was diagnosed this pass purely from a stored trajectory, which is only
# possible because a previous run left one behind.
export GRADING_AUDIT_PATH="results/guidance0813_audit.jsonl"

# atscale first: it is the arm with the external MCP dependency, so a
# misconfiguration fails before the raw arm spends anything.
echo "=== atscale start $(date) ==="
python -m orchestrator.runner --mode a-interact --backend atscale \
  --databases exchange_traded_funds \
  --output results/guidance0813_atscale_r1.json \
  > results/guidance0813_atscale_r1.log 2>&1
echo "=== atscale done $(date) ==="

if [ ! -s results/guidance0813_atscale_r1.json ]; then
  echo "ABORT: atscale output missing/empty; not starting raw"
  exit 1
fi

# --query-only for parity: the atscale arm drops Management-category tasks
# structurally (a read-only layer cannot serve DDL/DML), so the raw arm must
# drop the same ones or the two totals are over different task sets.
echo "=== raw start $(date) ==="
python -m orchestrator.runner --mode a-interact --backend raw --query-only \
  --databases exchange_traded_funds \
  --output results/guidance0813_raw_r1.json \
  > results/guidance0813_raw_r1.log 2>&1
echo "=== raw done $(date) ==="
echo ALL DONE
