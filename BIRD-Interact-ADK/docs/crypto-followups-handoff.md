# crypto_exchange follow-ups: what is done, what is open, and how to pick it up

Written 2026-08-17 at the end of the read-every-failing-submission round, to be read by a
session with no memory of it. Everything factual here is either committed, in the tracker
sheet, or reproducible with the commands given. Where something is a guess it says so.

Companion documents, not repeated here:

- `docs/model-change-log.md`, section `## crypto_exchange` — the full narrative of this
  round, the 08-14 rounds before it, and the per-task gold findings.
- `docs/lift-levers-handoff.md` — the five cross-database levers. Section 5 there says
  "no open model rows exist for crypto_exchange"; that is now out of date, see M-33.
- `docs/bird-grading-comparison.md` — the grading defect reference (B-19, B-31, B-32…).
- Tracker sheet, via `python scripts/sheet.py` only. Rows filed this round: **M-33,
  B-37, B-38, B-39, B-40, B-41, Q-28, Q-29, Q-30**.

---

## 0. State as of the end of the round

**Measurement.** atscale **0.360** against raw **0.340** on the 20 Query tasks,
`results/crypto_0817_atscale_20260817_142931.json`, arm cost $5.14. Sonnet both roles.
Flags as in `.env`: tie+rel+lint+decimal+casefold on, `FREE_WASTED_ACTIONS` and
`SEMANTIC_LAYER_KNOWLEDGE_TOOLS` off.

Raw was **not** re-run for that comparison. `scripts/regrade_flags.py raw` re-scored all
38 submissions of `crypto_n1_raw_20260814_085602.json` under three flag regimes and got
0.3400 in all three with zero flips. See §1 — that number is now stale for a different
reason and must be re-measured before any lift figure is quoted.

**Shipped and live.**

| what | where | state |
|---|---|---|
| guidance: projection rule + ORDER BY rule + 4 engine facts | ADK `f3ba423` | committed, services restarted |
| validation writeup | ADK `32b8361` | committed |
| M-33: RSI 14 / MACD Histogram descriptions | models `4ef40e2` | pushed, deployed, gated |

Untracked and intentionally so (`.gitignore` covers `scripts/run_*.sh`): the run scripts
`scripts/run_crypto_0817_atscale.sh`, the task subset
`scripts/tasks_crypto_0817_validate.txt`, and `logs/`.

**Before any run**, always:

    bash scripts/start_services.sh     # settings are cached at import; restart after any code change
    bash scripts/gate_run.sh 7         # services-newer-than-code, catalog health, template integrity

The gate has caught silently-voided runs three times. Do not skip it.

---

## 1. GATING ITEM — the raw arm has to be re-measured before any lift number

**Why this blocks everything downstream.** `RESULT_SHAPE_TIP` in `system_agent/agent.py`
is shared by *both* arms — the raw arm reads the same projection and ORDER BY rules that
`f3ba423` changed. The recorded raw 0.340 was produced under the **old** tip. crypto has
5 phases in the no-top-level-ORDER-BY bucket (B-38), so the ORDER BY rule plausibly helps
raw too, and until it is measured **the lift is unknown, not +2.0 pp and not +8.5 pp.**

Re-grading cannot answer this. The change alters what the agent *does*, not how it is
graded, so `regrade_flags.py` is the wrong instrument (see CLAUDE.md, "Grading changes:
re-grade, don't re-run").

    python -m orchestrator.runner --mode a-interact --backend raw --query-only \
      --databases crypto_exchange --output results/crypto_0818_raw.json

Cost ~$3, ~20 min. Do it in the same sitting as the atscale re-measure (§6) so both arms
see the same code, and never concurrently — the two arms share one set of services and
usage is attributed by timestamp window.

**Do not put a lift number in the sheet until both arms have run post-`f3ba423`.**

---

## 2. B-41 — a Yes/No flag submitted where gold wants a status label

**Highest-value open item: 2 tasks, both currently 0.00, both otherwise solved.**

`_17` asks "can you check its market health"; the model publishes `Liquidity Crisis` as a
**Yes/No** flag and gold wants `'Liquidity Crisis'` / `'Normal Market Conditions'`. In the
validation run the agent got the shape right on its first submission — one column, where
the previous run opened with three — then submitted the raw flag three times and invented
`'Normal'` on the fourth. It never spent 2 coins on the label ask. `_19` is the identical
shape: `Arbitrage Window` flag against `'Arbitrage Opportunity'` / `'Normal Market'`.

`ASK_USER_TIP` already prescribes that ask, but its trigger keys on the *question's*
wording ("label each as X or Y"), which neither question uses. What should trigger it is
the agent reaching for a Yes/No flag to answer a question asking for a status.

**Already proven** (`scripts/probe_pred.py`): the CASE-WHEN form with gold's labels grades
**1** on both tasks. The condition, the grain and the shape are all already correct — the
only wrong thing is the cell text.

**Why it was not attempted this round.** M-25 measured ask-trigger prescriptions as
landing rarely *and* carrying an opportunity cost against a fixed ask budget: language
that redirects an ask can lose a task elsewhere. Adding a second untested prescription in
the same session as the first would also have made the validation unattributable.

**Two candidate sites, pick deliberately:**

1. *Model side* — the flag descriptions say a Yes/No flag is not an output label and that
   a question asking for a status wants wording the user must supply. Narrow, and the
   `Account Balance` precedent shows a description trigger the agent then ignores (§5).
2. *Guidance side* — an `ASK_USER_TIP` clause keyed on the flag rather than the question.
   Generic across databases, and therefore the one that needs measuring on both arms.

Whichever you choose, validate on `_17` and `_19` only (~$0.5) before touching the arm.

---

## 3. `_6` — the model returns 840 rows where gold returns 1000

**New lead, uncharacterised, free to investigate.** `_6` was previously filed as an
ordering problem (E-05, then B-31). Both readings are now superseded: `_6` and `_10` are
both in `config/order_undetermined.json`, `GRADING_ORDER_LINT` is on, so their rows are
compared as multisets and **order is no longer the blocker**.

Replaying the agent's own submission through the grader returns 840 rows against gold's
1000, verdict 0. The gap is a population problem, not values and not order.

    python scripts/probe_pred.py crypto_exchange crypto_exchange_6 1 "<sql>"

Two hypotheses, neither tested: `filter_empty: yes` on the sentiment hierarchy dropping
snapshots with a null sentiment, or the self-join onto the per-sentiment average dropping
the unmatched ones. Start by counting snapshots by sentiment in the model against
`analyticsindicators` in Postgres — if 160 snapshots have no sentiment, it is the first.

Note also that the model has **no row-level `Buy Pressure` attribute**, only the
`Average Buy Pressure` metric, while gold projects the per-row `buy_force`. At snapshot
grain the average over one snapshot equals the row value, so this may be harmless — but
it is the same family as the row-level gaps M-30 and the percentile populations closed
earlier, and worth checking while you are in there.

Worth **+0.70** if it resolves.

---

## 4. `_15` and `_5` phase 2 — Q-26 scalar subquery, division by zero

Both phase-2 answers are simple in principle and both die on the same engine behaviour: a
scalar subquery over the model is inlined as a per-row self-reference (**Q-26**), so a
count-over-count percentage returns `ERROR: division by zero`.

`_15` p2 is worth checking first because **gold's answer is just `100.00`** — every order
is High Risk. Verified in Postgres. So the task needs a percentage the engine currently
refuses to compute, over a population where the answer is degenerate.

    # gold: SELECT ROUND((COUNT(*) FILTER (...) * 100.0 / NULLIF(COUNT(*),0)), 2) -> 100.00

Find a form the engine accepts (a ratio metric in the model would be the model-side
answer; a two-query approach with the agent doing the arithmetic is the guidance-side
one). Free to explore with `probe_pred.py`.

While you are here: the model's `liquidation_risk_level` uses `mid_price * 0.95` where
gold uses `mark_price * 0.95`. **Measured inert** — `riskandmargin` holds exactly 2 rows
and both are High Risk under either reading, 0 disagreements. Do not "fix" it on the
strength of the mismatch alone; it buys nothing and KB 11 says only "market price".

---

## 5. Decisions that are yours, not the model's

**`output_type` is read by nothing.** The shipped dataset carries it, and it predicts the
one-column gold shape exactly — **9 of 9** crypto tasks declaring `scalar` have a
one-column phase-1 gold. Neither this harness nor upstream's evaluator reads it (same
family as B-33, where three condition fields ship and one is read).

Surfacing it in the task prompt would very likely convert the whole B-37 family cheaply.
It is also **a real deviation**: it hands the agent a field upstream withholds, and would
break comparability with published numbers even though it is symmetric across arms. It
was deliberately not done. If you want it, it needs recording as a deviation in
`deviations` alongside the grading flags, and both arms re-run.

**`_12` phase 2 needs no model change and should not get one.** Gold's account ID is
`UserRef`; the agent used `Account Balance`. The `Account Balance` description *already*
says it is not the user identity, that `Exchange User` is, that "the account" is ambiguous
between 1000 records and 201 users, and to confirm with the user. The `Exchange User` form
grades **1** (probed). The trigger exists and the agent did not take it — M-25's pattern.
Adding more description text is the thing M-25 measured as not working.

---

## 6. When to re-measure the arm

After §2 and ideally §3/§4, not before — each fix validated on its own tasks first, so a
null result stays attributable. Then both arms, same sitting, same code:

    bash scripts/gate_run.sh 7
    python -m orchestrator.runner --mode a-interact --backend atscale \
      --databases crypto_exchange --output results/cryptoNNNN_atscale.json
    python -m orchestrator.runner --mode a-interact --backend raw --query-only \
      --databases crypto_exchange --output results/cryptoNNNN_raw.json

~$8 for the pair. Set `GRADING_AUDIT_PATH` per run so the trajectory stays re-gradable.
Report lift in **percentage points**, relative alongside, never as a fraction.

---

## 7. Per-task ledger

Baseline column is the 0817 run. "Evidence" says how strongly the target is known.

| task | 0817 | target | evidence | blocker / note |
|---|---|---|---|---|
| `_1` | 0.00 | — | — | **B-27** gold non-deterministic, `TimeTrack` has 1 distinct value over 605 rows |
| `_2` | 0.00 | **0.70** | measured live | fixed by the ORDER BY rule (B-38) |
| `_3` | 0.00 | — | — | **B-27**, ties on `FundSpot` |
| `_4` | 0.70 | 0.70 | — | **B-29**, the two golds disagree about `marg_sum`; p2 unreachable |
| `_5` | 0.70 | 1.00? | unknown | p2 blocked on Q-26, §4 |
| `_6` | 0.00 | 0.70 | lead only | 840 vs 1000 rows, §3 |
| `_7` | 0.00 | — | — | needs a forward/lagged price series; none exists in the schema |
| `_8` | 1.00 | 1.00 | passing | canary |
| `_9` | 0.00 | **1.00** | measured live | fixed by M-33 |
| `_10` | 0.00 | — | — | **B-39** gold ignores the latest-snapshot filter its question states |
| `_11` | 0.00 | 0.70 | probe only | bare scalar, no GROUP BY — should follow from B-37, untested live |
| `_12` | 0.70 | 1.00 | probe only | needs the agent to ask which "account"; §5 |
| `_13` | 1.00 | 1.00 | passing | canary |
| `_14` | 1.00 | 1.00 | passing | canary |
| `_15` | 0.70 | 1.00? | unknown | p1 shape freed by B-37; p2 is `100.00` behind Q-26, §4 |
| `_16` | 0.70 | 0.70 | — | **B-30** p2 gold fans out on the market, 993 rows from 970 orders |
| `_17` | 0.00 | 0.70 | probe only | **B-41**, §2 |
| `_18` | 0.00 | — | — | **B-40** gold's PVaR contradicts KB 2 by 100x and rebinds volatility |
| `_19` | 0.00 | 0.70 | probe only | **B-41**, §2. p2 wants a comma-separated string — unreachable |
| `_20` | 0.70 | 0.70 | — | p2 gold is a `STRING_AGG` at full float precision in gold's own emission order |

**Ceiling arithmetic.** Structurally unreachable: `_1 _3 _7 _10 _18` at 0.00 and
`_4 _16 _20` capped at 0.70. That is 7.9 of a possible 20 already gone, so the arm's
ceiling is about **0.605**. Measured today: 0.360. Proven live and not yet in an arm
number: +1.70 → **0.445**. Probe-only if they convert: +1.00 → 0.495. B-41 if solved:
+1.40 → 0.565.

---

## 8. Tools, and what not to redo

**Built this round, both committed, both free (no LLM calls):**

    python scripts/failing_sql.py <results.json> [instance_id ...] [--all]
        Per task: question, ambiguity flags (masked vs open), failed tool calls,
        every submission with its verdict, and gold per phase. This is the
        read-the-submitted-SQL loop in one command.

    python scripts/probe_pred.py <database> <instance_id> <phase> "<SQL>"
    python scripts/probe_pred.py --file probes.json
        Dispatches a candidate query through the same MCP run_query the arm uses and
        grades it with the same ex_base_external_pred, under the flags in .env.
        Answers "would this have scored" for ~0 cost against ~$0.26 for a live task.
        USE THIS BEFORE CHANGING ANYTHING. Every fix that landed this round was proven
        here first; the one that did not land was the one whose *next* constraint the
        probe could not see.

**Do not re-derive these — all measured, all in the tracker:**

- Raw is **flag-invariant** on crypto: 0.3400 under pre-0814, 0814, and upstream-all-off,
  zero flips over 38 submissions.
- `_6` is **not** blocked by row order. It is in `order_undetermined.json` and the lint is
  on. E-05 and the B-31 reading of it are both superseded.
- `_18` cannot be won by rebinding volatility to `priceShiftDay`: gold also applies an
  extra `/100` that KB 2 does not license. Arithmetic confirmed on OR6015391 both ways.
- `_15`'s mid/mark liquidation binding is inert: 0 disagreements over the 2 rows.
- `_12`'s model description is already correct and complete.
- The engine facts in the atscale instruction are probed live, not inferred: `NULLIF`
  rejected while `COALESCE` is fine (Q-28); `ORDER BY` needs a bare projected column
  (Q-29); filter inside the derived table (Q-30, trigger deliberately uncharacterised —
  do not quote it as "outer filters fail", an outer filter on a short alias passed).

**The standing prior, and the one exception found.** Model and guidance fixes that
correct a *value* mostly move nothing, because the agent's next choice up the stack
becomes binding — `_17` is this round's clean demonstration. Fixes that remove a hard
error or a wasted-turn tax *do* pay: M-30 was the first, and B-38 is the second. Predict
accordingly when deciding what to spend on.
