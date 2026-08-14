# How BIRD-Interact grades a submission, and everything wrong with it

Complete reference, written 2026-08-14. Supersedes `docs/bird-upstream-grading-plan.md`.

Everything here was measured on **all 22 databases, 410 Query tasks, 820 graded
phases**, using local Postgres and the graders' own code. **No API tokens, no
benchmark runs.** Every claim is reproducible with the commands in §7.

Two codebases are involved and both were read:

| | path | role |
|---|---|---|
| **ADK** (ours) | `shared/db_utils.py` in this repo | what our runs are scored by |
| **upstream** | `/Users/dianne/go/src/github.com/BIRD-Interact/evaluation/src/eval_bird_interact.py` | what the published leaderboard is scored by |

Line numbers below are as of 2026-08-14. Where the two differ it is called out
explicitly; assume they agree otherwise.

---

## 1. The pipeline

Each task carries `conditions = {decimal, distinct, order}`. A submission is
graded in four steps.

### Step 1 — clean both queries

    remove_comments  ->  remove_distinct  ->  remove_round

ADK: `db_utils.py:845` (semantic path), `:870-871` (raw path).
Upstream: `eval_bird_interact.py:258-263`. Same order, same functions.

`remove_distinct` deletes the **`DISTINCT` keyword** from the SQL text — from
*both* the prediction and gold. `remove_round` deletes `ROUND()` calls.

Stripping `ROUND()` matters far more than it looks, in two opposite directions:

* It **removes ties gold manufactured** by sorting on rounded values. This was
  the point of B-19 in our repo, and it is why any analysis of gold's row order
  must clean gold first — skipping it over-counts the order defect by 8 tasks
  (§2).
* It **destroys the precision the question asked for.** A task whose prose says
  "rounded to two decimal places" has that requirement deleted from gold before
  execution. `conditions.decimal` exists to restore it — and upstream never
  reads it (§6).

### Step 2 — execute both sides

Same database, same connection. Any error or timeout on either side scores 0.

### Step 3 — round both sides

ADK: `preprocess_results(rows, resolve_decimal_places(conditions))`.
`resolve_decimal_places` (`db_utils.py:288`) returns the task's `decimal` when
`GRADING_HONOR_DECIMAL` is on and the value is an int ≥ 0; **otherwise 2**.

Upstream: `preprocess_results(predicted_res)` — called with **no argument**, so
the default `decimal_places=2` (`eval_bird_interact.py:32`) applies to every
task in the benchmark.

**Consequence, true of both:** any difference below the second decimal place is
invisible to grading unless the ADK flag is on and the task declares more
precision. This single fact retired one defect I filed and re-diagnosed two
others — see §5.

### Step 4 — compare

ADK `_compare_rows` (`db_utils.py:566`):

```python
if conditions and conditions.get("order", False):
    if pred_cells == gt_cells:            # exact list equality, row by row
        return 1
    if not settings.grading_tie_tolerance:
        return 0
    return 1 if _ordered_match_tolerating_ties(pred_cells, gt_cells) else 0
return 1 if set(pred_cells) == set(gt_cells) else 0
```

Upstream `ex_base` (`eval_bird_interact.py:244-250`):

```python
if conditions is not None and conditions.get("order", False):
    return 1 if predicted_res == ground_res else 0
else:
    return 1 if set(predicted_res) == set(ground_res) else 0
```

Identical decisions. The ADK adds one optional tolerance (`GRADING_TIE_TOLERANCE`,
off) and a numeric fallback (`GRADING_REL_TOLERANCE`, off, `1e-6`).

### Which condition fields are actually used

| field | upstream | ADK |
|---|---|---|
| `order` | read (`:245`) | read |
| `decimal` | **never read** | read iff `GRADING_HONOR_DECIMAL` |
| `distinct` | **never read** | never read |

`remove_order_by` is defined upstream at `:183` and **called from nowhere**.

---

## 2. Defect A — `order: true` on gold that does not determine an order

**57 of 410 Query tasks (13.9%); 68 of 438 order-sensitive phases.**

`order: true` makes the grader compare row by row. That is only answerable if
gold's `ORDER BY` *totally* orders its result. Where it has ties — or is absent
entirely — the "expected" order is whatever Postgres's chosen plan emitted, and
no other query reproduces it except by luck.

**Method.** Each gold runs twice, the second time with the planner pushed onto
different physical operators (`enable_seqscan/hashjoin/nestloop/hashagg = off`).
Compared after the grader's own rounding, and only where the row **content** is
identical, so a value difference cannot masquerade as an order difference. Gold
is cleaned first exactly as step 1 does. **Lower bound** — a tie both plans
happen to emit identically is not caught.

    archeology_scan   5 of 10      hulushows              9 of 20
    organ_transplant  5 of 19      fake_account           5 of 24
    labor_cert_apps   4 of 19      mental_health          4 of 20
    sports_events     4 of 20      disaster_relief        3 of 12
    reverse_logistics 3 of 20      crypto_exchange        2 of 20  (_6, _10)
    cybermarket       2 of 20      exchange_traded_funds  2 of 19
    polar_equipment   2 of 20      robot_fault_prediction 2 of 10
    virtual_idol      2 of 19      households / museum_artifact / solar_panel  1 each

Severity is mostly total, not marginal: `crypto_exchange_10` phase 2 displaces
**1627 of 2558** rows, `hulushows_16` **998 of 1000**, `archeology_scan_6`
**894 of 900**.

**Worked example — `crypto_exchange_6`.** Under the grader's own rounding the
model's rows match gold as a **multiset, exactly**. 401 of 1000 rows sit in
ties. It scores 0.00 and the failure presents as a value error. It was
misdiagnosed twice in one day — first as a missing percentile column, then as a
float-rendering defect — before the ordering was measured.

> **Counting note.** An earlier pass reported 65 tasks / 78 phases. That pass
> executed gold **without** the step-1 cleanup. B-19's `ROUND()` stripping
> removes ties gold manufactured, and skipping it inflates the count by 8 tasks
> — `archeology_scan` alone dropped from 8 to 5. Any re-run must clean gold.

### What to propose

* **A1 — a dataset lint in CI.** For every `order: true` task, assert the gold
  result order is plan-independent. `scripts/bird_order_lint.py` is a working
  implementation: replan-and-compare, no SQL parsing, no engine assumptions.
* **A2 — fix the 57.** Where the question says "sorted by X", append a
  deterministic tie-break to gold's `ORDER BY` (usually the primary key). Where
  the order was incidental, set `order: false`. One-line data edits either way.
* **A3 — grade ties as ties.** Even after A2, two engines will not agree on the
  order of rows equal on the sort expression; SQL guarantees nothing there.
  Compare *tied blocks as multisets, in sequence*. The ADK implements this
  (`_ordered_match_tolerating_ties`, `db_utils.py:401`) behind
  `GRADING_TIE_TOLERANCE`. **Disclose the caveat when proposing it:** our
  version *infers* the sort key from gold's result (`_sort_key_indices`, `:353`
  — the coarsest monotonic non-constant column) because `conditions` does not
  record what gold sorted by. The better upstream fix is to **record the sort
  key in `conditions`** and grade against it directly, which removes the
  heuristic entirely.

---

## 3. Defect B — gold computes in float32, everything else in float64

**11 of 410 Query tasks (2.7%).**

    archeology_scan   _1 _6 _7 _8      (4 of 10 — by far the worst exposed)
    crypto_exchange   _5 _10
    polar_equipment   _4 _9
    disaster_relief   _4
    planets_data      _5
    solar_panel       _2

Gold parses values — often text inside JSON — to `real`, a 32-bit float carrying
~7 significant digits, then computes in that type:

```sql
COALESCE((e.ambient_cond->>'Ambic_Temp')::real, 20.0)   -- ::real, not ::numeric
```

`archeology_scan_7` does this 4 times, `_6` 11 times. **Archeology's base tables
contain no float columns at all** — the entire exposure is hand-written casts in
gold. Any other system reading the same text parses to `numeric` or `double`,
both more accurate, and where the true value sits near a rounding boundary the
two land on opposite sides:

    archeology_scan_6 p1   34 of 900 rows differ   755326.63 vs 755326.64
    archeology_scan_7 p1   24 of 900 rows differ       18.4  vs     18.5
    archeology_scan_8 p2   16 of 122 rows differ        6.4  vs      6.5
    archeology_scan_1 p2    2 of 597 rows differ       43.87 vs     43.88
    polar_equipment_4 p1                              128608.00 vs 128607.80

One differing row fails the phase, so 0.3% of rows is as fatal as 13%.

**Counting `::real` casts is the wrong test.** `crypto_exchange_13` and `_14`
carry 11 and 6 casts respectively and both score **1.00**. Only a difference
that survives the grader's rounding counts, which is what
`scripts/bird_precision_lint.py` measures — it re-runs each gold with its `real`
columns widened to `float8` and compares after rounding.

**Not fixable by an evaluated system.** The AtScale engine dispatches
`SUM(CAST(x AS FLOAT8))` — read from the outbound SQL, not inferred — so even
declaring a 32-bit column does not make the engine accumulate in 32 bits.

### What to propose

* **B1 — drop `::real` from gold.** For a value stored as text there is no
  reason to choose the lowest-precision numeric type available; `::numeric` is
  what the rest of the query already implies. Pure data fix, ~11 tasks.
* **B2 — compare numerics with a relative tolerance.** `1e-6` relative is far
  tighter than any genuine disagreement and neutralises the class. Grading to
  the last representable digit measures float semantics, not SQL correctness.
  The ADK has this as `GRADING_REL_TOLERANCE` (off). **Rounding to `decimal`
  places is not a substitute** — the boundary case is exactly where rounding
  disagrees.

---

## 4. Defect C — golds no correct query can reproduce

Small counts, each strictly unanswerable, each currently presenting as a model
failure. All found by reading gold for diagnosis.

**C1 — `ORDER BY <all-ties> LIMIT 1`.** `crypto_exchange_1` is
`ORDER BY marketdata."TimeTrack" DESC LIMIT 1`, and `TimeTrack` holds **one
distinct value across all 605 rows**:

    SELECT count(*), count(DISTINCT "TimeTrack") FROM marketdata;   -- 605, 1

The expected answer is whichever row the scan returned. `crypto_exchange_3` is
the same shape — `ORDER BY "FundSpot" DESC LIMIT 1` where many rows tie on the
maximum, landing on a market unrelated to the question.
*Lint: any gold with `LIMIT n` must have an `ORDER BY` that uniquely determines
its first n rows.* This is A1 extended to `LIMIT`, and it is mechanical.

**C2 — two phases of one task disagreeing about one column.**
`crypto_exchange_4` phase 1 selects `ab.marg_sum` and expects `321804.16`; phase
2 selects `ab.marg_sum::numeric` and expects `321804` — Postgres truncates
float4→numeric at 6 significant digits — with the derived percentage rounded
from the truncated denominator (`13.216762` against the true
`13.216755959782606`). `conditions.decimal` is 6, so rounding does not reconcile
them. **No single reading of the column satisfies both phases.**
*Lint: within a task, the same source column should be read the same way.*

**C3 — accidental join fan-out.** `crypto_exchange_16` phase 2 joins orders to
`analyticsindicators` on `exchSpot = md_ref`, so each order becomes one row per
snapshot of its market, and the reference CTE is itself multi-valued and
`CROSS JOIN`ed: **993 rows from 970 orders**, including values below the
threshold the question states. Hard to lint automatically; a reviewer checklist
item — *does gold's row count match the grain the question names?*

**C4 — output labels the knowledge base never defines.** `crypto_exchange_17`
expects the literal `'Normal Market Conditions'`, `_19` expects
`'Normal Market'`. KB 16 and KB 12 define the *thresholds* — which a correct
model computes — but name no wording. Both tasks did eventually pass here, by
the agent asking the user what to output, so this is a fairness cost rather than
an impossibility. *Either the KB entry should specify the labels, or the task
should ask for the boolean it actually tests.*

---

## 5. Defect D — unordered results compared as sets, not multisets

**Confirmed upstream**, `eval_bird_interact.py:250`:

```python
return 1 if set(predicted_res) == set(ground_res) else 0
```

Character-for-character the decision the ADK makes. It governs **382 of 820
graded phases (47%)** — every `order: false` phase in the benchmark.

**Demonstrated through the real grader** on `crypto_exchange_4` (15 gold rows,
`order: false`):

    exact gold rows        15 rows -> 1
    every row duplicated   30 rows -> 1
    every row x5           75 rows -> 1
    one row only            1 row  -> 0

Dropping rows **is** caught. Only **multiplicity** is ignored.

**The two halves of the pipeline fight each other.** Step 1 strips the `DISTINCT`
keyword from both queries, which *manufactures* duplicate rows; step 4 compares
with `set()`, which *erases* them. A task whose entire point is de-duplication
cannot be failed on it.

`conditions["distinct"]` is never read in either implementation.

**Blast radius:** this does **not** inflate our lift — both arms are graded
identically. What it means is that on 47% of phases the benchmark cannot test
cardinality or de-duplication at all.

### What to propose

`collections.Counter` instead of `set` — a two-line change. It makes grading
**stricter**, so it must be re-measured over stored runs before adoption. Paired
ask: honour `conditions["distinct"]`, or delete the field.

---

## 6. Defect E — the dataset ships three condition fields and upstream reads one

`decimal` is never read upstream: `preprocess_results(predicted_res)` is called
with no argument, so **every task in the benchmark is graded at 2 decimal places
regardless of what it declared.**

Measured distribution across the 820 graded phases:

    decimal = -1   412 phases      decimal = 0    24
    decimal =  2   267             decimal = 1    16
    decimal =  4    49             decimal = 8     3
    decimal =  3    45             decimal = 6     3
                                   decimal = 5     1

* **141 of 820 phases** declare a `decimal` other than 2 or −1 — the cases where
  honouring it differs from upstream.
* On **110 of those, gold's own values actually differ** between the two
  roundings. That is the upper bound on where the choice can change a verdict.
* Concentrated in databases not yet run: `fake_account` 25, `organ_transplant`
  17, `planets_data` 15. Only **29** fall in the seven databases we have
  deployed models for.
* **0 verdicts flipped** on the runs we hold: `regrade_flags.py` over crypto n1,
  crypto n2 and an ETF raw arm — **129 submissions, all four flag combinations
  identical.**

Note the direction is not uniform. Always-2 is **stricter** than asked on the 24
phases declaring `decimal: 0`, and **looser** on the 49 declaring `4` — where it
would pass answers wrong in the third decimal. It does not err on the safe side;
it ignores the field.

### What to propose

Read `decimal` in `preprocess_results` — a one-line change that makes grading
match what each task asks for. Make the same decision for `distinct`: honour it,
or remove it from the dataset so nobody assumes it does something.

### The local decision this implies

`GRADING_HONOR_DECIMAL=true` in our `.env` is a deviation from upstream. On the
evidence it is free to drop (0 flips), and dropping it restores comparability
with published numbers and retires a deviation. **Recommendation: turn the flag
off, keep the four-line `resolve_decimal_places` behind it** — 110 phases can
differ and 57 of them sit in the three databases coming next, so you will want
to measure it then rather than rediscover it. Not done yet: it changes the
measurement instrument, which is the owner's call.

---

## 7. Reproducing all of it

Free — local Postgres on disposable copies of the templates, no LLM calls.
**Never write to a `*_template` database** (B-25: a stray DML there corrupts the
grading reference for every future run).

```bash
source .venv-adk/bin/activate && export PYTHONPATH=.

# Defect A — expect 57 tasks / 68 phases
python scripts/bird_order_lint.py <all 22 db names>        # -> /tmp/order_sweep.json

# Defect B — expect 11 tasks, 0 for the withdrawn E-05 column
python scripts/bird_precision_lint.py <all 22 db names>    # -> /tmp/precision_sweep.json

# Defects D and E — flag sensitivity on a finished run, no LLM calls
python scripts/regrade_flags.py atscale results/<run>.json --database <db>
```

If the order lint returns **65** rather than 57, its `clean()` step — gold's own
`remove_comments`/`remove_distinct`/`remove_round` — has been dropped. That is
the single easiest way to over-report this defect.

The 22 database names are the `selected_database` values in
`bird-interact-full/bird_interact_data.jsonl`.

---

## 8. Combined structural ceiling, per deployed model

Union of defects A and B, as a share of each database's Query tasks:

    archeology_scan                    7 of 10 at risk   ceiling ~30%
    labor_certification_applications   4 of 19           ceiling ~79%
    crypto_exchange                    3 of 20           ceiling ~85%
    exchange_traded_funds              2 of 19           ceiling ~89%
    cybermarket_pattern                2 of 20           ceiling ~90%
    solar_panel                        1 of 20           ceiling ~95%
    households                         1 of 21           ceiling ~95%

**`archeology_scan` is not a hard database — it is a structurally ungradable
one**, and its recorded scores were never a model verdict. If one sentence from
this document survives, that is the one.

---

## 9. What was withdrawn, and why it is worth remembering

**E-05 — "numeric returned as a double" — filed and withdrawn the same day.
0 of 410 tasks.** The mechanism is real: the semantic layer returns an IEEE
double where gold holds a Postgres `numeric`, so `0.194020626384848152` comes
back as `0.19402062638484815`. But the grader rounds **both** sides before
comparing, and `resolve_decimal_places` falls back to 2, which absorbs it
entirely. The original evidence was a raw `canonical_cell` diff that skipped the
rounding the grader actually applies.

Two conclusions flipped with it, both worth carrying:

* **`crypto_exchange_6` is not engine-blocked.** Its rows match gold as a
  multiset exactly; only the tie order fails. It belongs to defect A.
* **`crypto_exchange_11` is winnable**, and I had said it was not. Graded against
  gold, the model's available-balance margin metric returns **1** — the `::REAL`
  downcast I blamed does not survive rounding.

**Do not carry E-05 upstream.** The general lesson: *any* claim about value
comparison must be tested through `preprocess_results` at the task's own
precision, never against raw returned values.

---

## 10. Ownership

**BIRD** (upstream `github.com/bird-bench/BIRD-Interact`): defects A, B, C1–C4,
D, E. All are data or evaluator issues, and none of them can be fixed by an
evaluated system.

**AtScale engine** (tracked separately, not in scope here): `Q-27` attribute-only
join planning, `E-01` `COUNT(attribute)` returning members, `Q-15`
`COUNT(DISTINCT)` unreliability, `Q-17b` non-idempotent publish, `E-04`'s engine
half (`SUM(CAST(x AS FLOAT8))`).

**This repo:** the two lints, the optional tolerances, and the decision in §6
about `GRADING_HONOR_DECIMAL`.

Tracker rows: **B-27** (non-deterministic gold), **B-29** (`_4`'s two golds
disagree), **B-30** (`_16` fan-out), **B-31** (defect A), **B-32** (defect D),
**E-04** (defect B), **E-05** (withdrawn). Update them rather than filing
duplicates.
