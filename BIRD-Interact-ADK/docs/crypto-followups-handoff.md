# crypto_exchange follow-ups: what is done, what is open, and how to pick it up

Written 2026-08-17 after the read-every-failing-submission round, **revised the same day**
at the end of the sitting that worked the open items. Everything factual here is either
committed, in the tracker sheet, or reproducible with the commands given. Where something
is a guess it says so.

Companion documents, not repeated here:

- `docs/model-change-log.md`, section `## crypto_exchange` — the full narrative. Read the
  second-sitting section first; it supersedes several conclusions in the one below it.
- `docs/lift-levers-handoff.md` — the five cross-database levers.
- `docs/bird-grading-comparison.md` — the grading defect reference (B-19, B-31, B-32…).
- Tracker sheet, via `python scripts/sheet.py` only. Rows filed across both sittings:
  **M-33, M-34, M-35, B-37, B-38, B-39, B-40, B-41, B-42, Q-28, Q-29, Q-30, Q-31**.

---

## 0. State as of the end of the second sitting

**Both arms measured 2026-08-17, same sitting, same code:**

| arm | previous | now | movement | run |
|---|---|---|---|---|
| atscale | 0.360 | **0.600** | +24.0 pp | `crypto_0818_atscale_20260817_161538` ($4.32) |
| raw | 0.340 | **0.595** | +25.5 pp | `crypto_0818_raw_20260817_162631` ($3.08) |

**Lift +0.5 pp** (relative +0.8%), against +2.0 pp before. Sonnet both roles, 20 Query
tasks, flags as in `.env` (tie+rel+lint+decimal+casefold on, `FREE_WASTED_ACTIONS` and
`SEMANTIC_LAYER_KNOWLEDGE_TOOLS` off).

**Read that as: the guidance work is worth ~+25 pp and is symmetric, so the semantic
layer's advantage on this database is now indistinguishable from zero.** And do not read
±0.5 pp as a finding — see §1.

The five task-level fixes behind it, each validated on its own task before the arm:

| task | before | after | mechanism | run |
|---|---|---|---|---|
| `_2` | 0.00 | 0.70 | ORDER BY rule (B-38) | `crypto_0817_validate_20260817_150357` |
| `_9` | 0.00 | 1.00 | M-33 descriptions | same |
| `_17` | 0.00 | 1.00 | B-41 label ask | `crypto_0818_validate_20260817_153608` |
| `_19` | 0.00 | 0.70 | B-41, same clause | same |
| `_6` | 0.00 | 1.00 | M-34, then M-35, then B-42 | `…v2_154056`, `…v3_154532` |

**Shipped and live.**

| what | where | state |
|---|---|---|
| projection rule + ORDER BY rule + 4 engine facts | ADK `f3ba423` | committed, deployed |
| M-33: RSI 14 / MACD Histogram descriptions | models `4ef40e2` | pushed, deployed, gated |
| M-34: row-level `Buy Pressure` / `Sell Pressure` | models `5620b2a` | pushed, deployed, gated |
| M-35: percentile-rank grain steer | models `7cdee91` | pushed, deployed, gated |
| B-41 label-ask clause + B-42 grouped ORDER BY | ADK, this commit | committed, services restarted |

Untracked and intentionally so (`.gitignore` covers `scripts/run_*.sh`): the run scripts,
the task subsets `scripts/tasks_crypto_0817_validate.txt`,
`scripts/tasks_crypto_0818_validate.txt`, `scripts/tasks_crypto_0818_v2.txt`, and `logs/`.

**Before any run**, always:

    bash scripts/start_services.sh     # settings are cached at import; restart after any code change
    bash scripts/gate_run.sh 8         # services-newer-than-code, catalog health, template integrity

The gate has caught silently-voided runs three times. Do not skip it. It is `8` now, not
`7` — organ_transplant joined the catalog.

---

## 1. CLOSED, and the answer was the uncomfortable one — plus the new gating item

The first writing made re-measuring raw the gating item on the grounds that
`RESULT_SHAPE_TIP` and `ASK_USER_TIP` are shared by both arms. That was right and the
result is above: **raw gained more than atscale did (+25.5 pp against +24.0 pp) and the
lift fell from +2.0 pp to +0.5 pp.** Had only the atscale arm been re-run, this sitting
would have reported "+24 pp of lift" and been wrong by a factor of fifty.

Where each arm gained against its own previous baseline:

    atscale  _2 _9 _10 _11 (0.00 -> 0.70), _6 _17 (0.00 -> 1.00)
    raw      _9 _17 (0.00 -> 0.70), _1 _6 _8 _19 (0.00 -> 1.00), _16 (1.00 -> 0.70)

`_6` gained in the **raw** arm too, on B-42 alone — M-34 and M-35 are model-side and
invisible to it.

**THE NEW GATING ITEM: ±0.5 pp is inside the noise, and n=1 cannot tell you otherwise.**
Two tasks flipped on identical code within forty minutes: `_19` scored 0.70 in
`crypto_0818_validate` and **0.00** in the arm (where it bisected the projection four times
and never asked for the labels), and `_9` went 1.00 → 0.70 the same way. Nothing in this
sitting's numbers separates +0.5 pp from 0. A lift claim on crypto_exchange needs **n≥3 per
arm, roughly $22**:

    python -m orchestrator.runner --mode a-interact --backend atscale --repeat 3 \
      --databases crypto_exchange --output results/cryptoNNNN_atscale_n3.json
    python -m orchestrator.runner --mode a-interact --backend raw --query-only --repeat 3 \
      --databases crypto_exchange --output results/cryptoNNNN_raw_n3.json

Sequentially, never concurrently — the arms share one set of services and usage is
attributed by timestamp window. **Do not put a lift number in the sheet from n=1.**

Also revise, in both directions: raw won `_1` (filed under B-27 as gold-non-deterministic)
and atscale won `_10` (filed under B-39 as winnable only by disobeying the question).
Neither is as structural as the tracker records, and the ~0.605 ceiling estimate below is
built partly on those two rows.

---

## 2. Open: `_2` is capped at 0.70 by Q-31, and the fix spans three models

`_2` phase 2 asks for the average **and median** Order Fill Rate. Every
`calculation_method: percentile` metric in the catalog is unexecutable — six of them, in
three models — because the engine rejects quantiles against Postgres 9.4.5, and each one
fails twice: its plain name is "not found" (the engine exposes `…_instance_0.5`) and the
real name errors in query planning. Full evidence in Q-31.

The model-side answer is a **precomputed median column per population**, named the way the
percentile ranks already are (`Median Order Fill Rate (All Latest Executions)`), with the
population in the name because a precomputed median cannot recompute per group. That is
the existing convention in this model — the percentile ranks are precomputed for exactly
this reason ("the dialect rejects PERCENT_RANK").

Not done here deliberately: it touches crypto_exchange, exchange_traded_funds and
labor_certification_applications, and shipping it in the same sitting as four measured
changes would have made none of them attributable. Worth **+0.30** on `_2` and unknown
amounts elsewhere. Decide before the next arm run.

---

## 3. Open, probe-proven, no fix needed: `_15` p2 and `_5` p2

The first writing filed both as blocked on **Q-26** (scalar subquery inlined as a per-row
self-reference). **That was wrong — neither needs a subquery at all.** Both grade **1**
through `probe_pred.py` against the deployed model:

    # _15 p2 -> 100.00
    SELECT ROUND("Orders At High Liquidation Risk" * 100.0
                 / "Orders With A Liquidation Price", 2) FROM <model>

    # _5 p2 -> discovery query first (2 rows), then
    SELECT "Total Profitable Realized PnL", "Total Losing Realized PnL", "Profit Factor"
    FROM <model> WHERE "Exchange User" = 'U485932'
    #   discovery: SELECT "Exchange User", "Maximum Margin Utilization" FROM <model>
    #              GROUP BY "Exchange User"      -- U485932 681.42, U583322 3.81

What actually cost `_15` its phase 2 in the 0817 run was **budget** — three submissions
spent on the phase-1 column count, which `f3ba423` addresses — and `_5`'s was a
hallucinated `"Account Balance" = 425` filter plus invented profit-factor arithmetic. Both
are +0.30 each and both should now follow from the shipped guidance without further
changes. **Live-test them in the next arm run rather than fixing anything.**

Two smaller facts from those probes, worth not re-deriving:

- The honest denominator `_15` needs is `Orders With A Liquidation Price` (2 of 970), and
  its description already says it is the honest denominator. `Order Count` gives 0.21 and
  grades 0.
- An outer filter on a metric alias over a derived table (`WHERE t.mu > 80`) is rejected —
  the Q-30 shape — while grouping by `"Exchange User"` with `"Maximum Margin Utilization"`
  projected is fine.

---

## 4. Decisions that are yours, not the model's

**`output_type` is read by nothing.** The shipped dataset carries it and it predicts the
one-column gold shape exactly — **9 of 9** crypto tasks declaring `scalar` have a
one-column phase-1 gold. Neither this harness nor upstream's evaluator reads it (same
family as B-33). Surfacing it in the task prompt would likely convert the rest of the B-37
family cheaply, and it is **a real deviation**: it hands the agent a field upstream
withholds. Still deliberately not done. If you want it, record it in `deviations` alongside
the grading flags and re-run both arms.

**`_12` phase 2 needs no model change and should not get one.** Gold's account ID is
`UserRef`; the agent used `Account Balance`. That description *already* says it is not the
user identity, that `Exchange User` is, that "the account" is ambiguous between 1000
records and 201 users, and to confirm with the user. The `Exchange User` form grades **1**
(probed). The trigger exists and the agent did not take it.

Note the B-41 result complicates M-25's prior here rather than confirming it: an ask-trigger
prescription *did* land when it keyed on **what the agent was about to submit** instead of
on the question's wording. If `_12` is retried, that is the surface to aim at — not more
description text.

---

## 5. Re-measuring: done at n=1, and what the next run should be

Both arms ran post-B-42 (§0). `scripts/run_crypto_0818_both.sh` is the recipe — untracked
per `.gitignore`, and it carries the reasoning in its header. Reuse it with `--repeat 3` for
the n=3 pair §1 now calls for; ~$22, ~2h, sequential.

Set `GRADING_AUDIT_PATH` per run so the trajectory stays re-gradable. Report lift in
**percentage points**, relative alongside, never as a fraction.

Before spending that, the honest question is whether crypto_exchange is the database to
spend it on: both arms are now within 0.005 of each other and within 0.01 of the estimated
reachable ceiling, so there is very little headroom left for a lift to appear in. The
cross-database levers in `docs/lift-levers-handoff.md` are the better use of $22 unless a
crypto lift figure is specifically wanted.

---

## 6. Per-task ledger

All four columns are live arm numbers. `as` = atscale, `raw` = raw arm.

| task | as0817 | **as0818** | raw0814 | **raw0818** | note |
|---|---|---|---|---|---|
| `_1` | 0.00 | 0.00 | 0.00 | **1.00** | filed **B-27** non-deterministic; raw won it, so revisit |
| `_2` | 0.00 | 0.70 | 0.00 | 0.00 | B-38; capped at 0.70 by **Q-31**, §2 |
| `_3` | 0.00 | 0.00 | 0.00 | 0.00 | **B-27**, ties on `FundSpot` |
| `_4` | 0.70 | 0.70 | 0.70 | 0.70 | **B-29**, the two golds disagree about `marg_sum` |
| `_5` | 0.70 | 0.70 | 0.70 | 0.70 | p2 probe-proven reachable, §3 — did not convert live |
| `_6` | 0.00 | 1.00 | 0.00 | **1.00** | M-34 + M-35 in atscale; raw got there on B-42 alone |
| `_7` | 0.00 | 0.00 | 0.00 | 0.00 | needs a forward/lagged price series; none in the schema |
| `_8` | 1.00 | 1.00 | 0.00 | 1.00 | canary, now passing in both |
| `_9` | 0.00 | 0.70 | 0.00 | 0.70 | M-33; scored 1.00 in validate, 0.70 in the arm — variance |
| `_10` | 0.00 | 0.70 | 0.00 | 0.00 | filed **B-39** unreachable; atscale won it, so revisit |
| `_11` | 0.00 | 0.70 | 0.00 | 0.00 | the B-37 probe converting live |
| `_12` | 0.70 | 0.70 | 0.70 | 0.70 | needs the agent to ask which "account"; §4 |
| `_13` | 1.00 | 1.00 | 1.00 | 1.00 | canary |
| `_14` | 1.00 | 1.00 | 1.00 | 1.00 | canary |
| `_15` | 0.70 | 0.70 | 1.00 | 1.00 | raw takes p2; atscale's p2 is probe-proven, §3 |
| `_16` | 0.70 | 0.70 | 1.00 | 0.70 | **B-30** p2 gold fans out on the market |
| `_17` | 0.00 | 1.00 | 0.00 | 0.70 | B-41, in both arms |
| `_18` | 0.00 | 0.00 | 0.00 | 0.00 | **B-40** gold's PVaR contradicts KB 2 by 100x |
| `_19` | 0.00 | 0.00 | 0.00 | **1.00** | B-41 landed in raw and in validate; **missed in the atscale arm** |
| `_20` | 0.70 | 0.70 | 0.70 | 0.70 | p2 gold is a `STRING_AGG` at full float precision |
| **mean** | 0.360 | **0.600** | 0.340 | **0.595** | lift **+0.5 pp** |

**Ceiling arithmetic, and why it is now shaky.** The estimate was ~0.605 from `_1 _3 _7 _10
_18` unreachable at 0.00 and `_4 _16 _20` capped at 0.70. Both arms are now within 0.01 of
that, *and* two of its rows were falsified in this very run (`_1` in raw, `_10` in atscale).
Treat 0.605 as a lower bound on the ceiling, not the ceiling — but also note that neither
arm has much headroom left in practice, which is §5's point.

---

## 7. Tools, and what not to redo

**Free (no LLM calls), both committed:**

    python scripts/failing_sql.py <results.json> [instance_id ...] [--all]
        Per task: question, ambiguity flags (masked vs open), failed tool calls,
        every submission with its verdict, and gold per phase.

    python scripts/probe_pred.py <database> <instance_id> <phase> "<SQL>"
    python scripts/probe_pred.py --file probes.json
        Dispatches a candidate through the same MCP run_query the arm uses and
        grades it with the same ex_base_external_pred, under the flags in .env.
        USE THIS BEFORE CHANGING ANYTHING. Every fix that landed was proven here
        first — including the two the previous writing had mis-diagnosed.

**Do not re-derive these — all measured, all in the tracker:**

- Raw is **flag-invariant** on crypto: 0.3400 under pre-0814, 0814 and upstream-all-off,
  zero flips over 38 submissions. (Flag-invariant, *not* code-invariant — §1.)
- `_6` is **not** blocked by row order in phase 1; it is in `order_undetermined.json` and
  the lint is on. E-05 and the B-31 reading of it are superseded. Its **phase 2 is not
  exempt** and does need the ORDER BY (B-42).
- `_6`'s 840-vs-1000 gap was neither `filter_empty` nor an unmatched join: 0 of 1000
  snapshots have a null sentiment and the join is 1000 = 1000. It was the missing row-level
  `Buy Pressure` (M-34) — a grain defect.
- **Q-26 does not fire on crypto.** `_15` p2 and `_5` p2 are reachable with no subquery, §3.
- `_18` cannot be won by rebinding volatility to `priceShiftDay`: gold also applies an
  extra `/100` that KB 2 does not license. Confirmed on OR6015391 both ways.
- `_15`'s mid/mark liquidation binding is inert: 0 disagreements over the 2 rows. Do not
  "fix" it; KB 11 says only "market price".
- `_12`'s model description is already correct and complete.
- Neither B-41 label pair is in the knowledge base (KB 16, KB 12 give conditions, no
  wording), so this could only ever be fixed by an ask, never by a description.
- The engine facts in the atscale instruction are probed live: `NULLIF` rejected while
  `COALESCE` is fine (Q-28); `ORDER BY` needs a bare projected column (Q-29); filter inside
  the derived table (Q-30, trigger deliberately uncharacterised).

**The standing prior, revised.** The first writing held that model and guidance fixes
correcting a *value* mostly move nothing, because the agent's next choice up the stack
becomes binding, and that only fixes removing a hard error or a wasted-turn tax pay. The
second sitting is evidence for a sharper version: **fixes that remove a wrong OBJECT CHOICE
pay too.** M-34 and M-35 are both pure description/attribute work and both converted, one
after the other on the same task — and `_6` needed all three of its fixes, each exposing the
next. Predict "one fix reveals one more constraint", not "fixes don't pay".
