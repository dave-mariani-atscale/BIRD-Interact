# How BIRD-Interact grades a submission, and everything wrong with it

Complete reference, written 2026-08-14. This is the single source for the
benchmark's grading behaviour and its defects; nothing else in `docs/` restates it.

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
with published numbers and retires a deviation. **This section originally
recommended turning it off. Decided the other way on 2026-08-14 — see §11.**
Re-measured over the whole 930-submission audit rather than 129: turning it off
costs 1 atscale phase (`exchange_traded_funds_19` p2) and 2 raw
(`solar_panel_8` p1 and p2). Honouring a precision the dataset itself declares
is easier to defend than ignoring it, the number we report is lift under one
grader rather than parity with the leaderboard, and §11's dual reporting makes
the upstream number recoverable anyway.

---

## 6b. Defect F — golds that do not return the same answer twice

**27 of ~800 graded phases.** Found on 2026-08-14 while chasing an offline
re-grade that disagreed with the run it was replaying. **That mismatch turned
out to have a different cause** — a missing cleanup step in the replay tool, §11
— and the correction matters, because it is the difference between "the
benchmark scores differently every time you run it" and what is actually true.

Defect A asks whether gold determines its own row *order*. `bird_order_lint`
discards any pair of runs whose row *content* differs, as "not an order
question". It is a question about something worse. Re-run each gold under a
different plan and compare as multisets after the grader's own rounding:

    25 phases   values differ, and not by float noise   -- nobody can pass these
     2 phases   the 10000-row fetch cap, see below      -- not a gold defect
     1 phase    values differ within 1e-6 relative      -- float64 accumulation order

    households  4    mental_health  4    crypto_exchange  3    polar_equipment  3
    fake_account  2   labor_cert_apps  2   museum_artifact  2   + 6 databases with 1

**Two of them are not gold's fault.** `perform_query` fetches at most 10000 rows
for a SELECT (`db_utils.py:113`) — upstream's own cap, faithfully ported
(`evaluation/src/postgresql_utils.py:49`), so not an ADK deviation. A gold
returning more is silently cut to the first 10000, and *which* 10000 is whatever
the plan emitted. Swept over all 810 phases, exactly two hit it:
`polar_equipment_2` p1 and `polar_equipment_18` p2, both returning exactly
10000. Different defect, different fix: a cap that truncates silently should
error instead, which is three lines in the evaluator and cannot be wrong under
any reading of what the benchmark is for.

Severity runs to total: `polar_equipment_2` phase 1 differs on **9981 of 10000**
rows, `polar_equipment_18` phase 2 on **9202 of 10000**, `mental_health_13`
phase 2 on **98 of 100**.

The mechanism is a pick-one-per-group with a non-unique tiebreak. `households_8`
returns a different pair of cities every time the plan changes; `mental_health_2`
phase 2 returns diagnosis `f440` or `f429` depending on the plan. Only 3 of the
27 use an obvious `ROW_NUMBER()`/`DISTINCT ON` — a text search for row-pickers
would have found almost none of this, which is why it is measured.

**How far the non-determinism actually reaches, measured 2026-08-16.** All 28
were re-run under three ordinary conditions and compared against a plain
baseline: the same query again in the same session, again on a fresh
connection, and again with `max_parallel_workers_per_gather = 0` — the most
common real configuration difference between two machines.

    moves under an ordinary rerun            0 of 28
    moves only under forced planner operators   28 of 28

So, precisely: **a rerun on this machine scores the same, and our offline
re-grades of these tasks are reproducible.** What is defective is that the
answer is a property of the plan rather than of the query — which is exactly
what changes between Postgres versions, data volumes, `work_mem` settings and
machines. It is a latent defect for us and an active one for anyone whose
planner chooses differently, upstream's own leaderboard host included. Do not
report it as run-to-run flakiness; report it as an under-determined answer.

**This is not the same as defect A and does not overlap it.** A is an ordering
the grader should not be asking about; F is an *answer* that does not exist. No
grading flag can help — a tolerance cannot reconcile `f440` with `f429` — and
neither arm can win these if the host's planner disagrees with the one that
built the dataset. Strictly upstream, trackers **B-27** (the first two found)
and **B-34** (the benchmark-wide sweep).

### What upstream should actually change

The dataset stores **no expected answer** — only `sol_sql`, executed live at
grading time (confirmed: the 600 task records carry `sol_sql`, `conditions`,
`test_cases`, and no result field). So fixing a gold is a pure SQL edit. There
are no golden outputs to regenerate and no past scores invalidated by the
reference changing.

Two different problems hide under "no single answer", and they want different
fixes:

*Reproducibility* — gold must return the same thing on any host. **One line per
gold, no judgment required**, and the lint verifies each fix:

| what gold does | phases | the one-line fix |
|---|---|---|
| `ORDER BY ... LIMIT n` over a non-total order | ~15 | add a unique tiebreak (usually the key) |
| `ROW_NUMBER`/`RANK` picking one row per group | ~4 | add a tiebreak inside the window's `ORDER BY` |
| `LEAD`/`LAG` over a non-total order | 1 | same |
| `string_agg`/`array_agg` with no `ORDER BY` | 2 | `ORDER BY` inside the aggregate |
| `SUM` over `::real`, order-dependent in float32 | ~3 | drop the `::real` — already proposed as B1 (§3) |

*Answerability* — a solver must be able to know which of the tied answers is
wanted. Determinism does not give you this: pinning `f440` over `f429` makes the
task stable and still unguessable. That needs a prose edit per task ("break ties
by the earliest id"), or the task should ask for the tied set rather than one of
it. It is the expensive half, and it is the half that decides whether these
count as fair tasks or merely reproducible ones.

**The lightest touch that is still honest** is the first table plus a CI lint.
It makes the benchmark reproducible everywhere, needs no question rewrites and
no re-recording, and is mechanical enough to review in one sitting. If even that
is too much, the minimum is to mark the affected phases in `conditions` so
evaluators can park them — 25 of 820 phases is 3%, and losing them openly beats
scoring them randomly.

Whatever is fixed, **the lint is the durable ask**: without it in CI the next
dataset release reintroduces the same shapes.

*Lint: `scripts/bird_content_lint.py <db ...>`, same method and cost as the
other two.*

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

# Defect F — expect 27 non-deterministic + 1 float-noise phase
python scripts/bird_content_lint.py <all 22 db names>      # -> /tmp/content_sweep.json

# Regenerate the list the grader consumes for defect A
python scripts/bird_order_lint.py --write config/order_undetermined.json <all 22 db names>

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

**This repo:** the lints, the optional tolerances, and the flag decisions in
§11.

Tracker rows: **B-27** (non-deterministic gold), **B-29** (`_4`'s two golds
disagree), **B-30** (`_16` fan-out), **B-31** (defect A), **B-32** (defect D),
**E-04** (defect B), **E-05** (withdrawn). Update them rather than filing
duplicates.

---

## 11. What this repo grades on, decided 2026-08-14

Sections 1–10 describe the defects. This section is the decision record: which
of them we now correct for locally, which we deliberately do not, and what each
one is worth. Everything here was measured over the **930 recorded submissions**
in `results/grading_audit_0811.jsonl` (527 atscale, 403 raw, four databases)
and over all 22 databases' golds. No LLM calls.

The organising principle, and the only one that makes a local grading change
defensible: **the raw arm executes prediction and gold on the same engine, so a
cross-engine divergence cannot arise there at all.** Dave's `0fd631b` says the
same thing. Every change below removes a divergence that is an artefact of
being a different engine, and none of them touches whether the answer is right.

### Shipped

| | change | measured over the audit |
|---|---|---|
| **B-22 fix** | `_sort_key_indices` returns None instead of falling back to the last column; both tie-tolerant comparisons then forgive nothing | prerequisite, no verdict change |
| `GRADING_REL_TOLERANCE=true` @1e-6 | retry a failed comparison on pre-rounding rows | atscale **+2 phases**, raw **+1**, zero regressions |
| `GRADING_TIE_TOLERANCE=true` | forgive a permutation confined to ties | atscale +1 phase (subsumed by the above), raw 0 |
| `GRADING_ORDER_LINT=true` | don't grade an order gold does not determine | 68 phases eligible; 0 in this audit's four databases beyond the above |
| timestamp strings | `canonical_cell` truncates `YYYY-MM-DD HH:MM:SS` to the date, as `preprocess_results` already does to a typed datetime | 6 phases exposed benchmark-wide, 0 in this audit |
| audit on by default, rows stamped | `GRADING_AUDIT_PATH` defaults on; each row carries `ts`; runs record their window | no verdict change |

The three phases that move are `exchange_traded_funds_7` p1 and
`crypto_exchange_5` p1 (atscale) and `archeology_scan_6` p1 (raw).

### Re-baselined, on the runs we hold

All four re-grades reproduce their recorded totals exactly before anything is
changed, which is the check that the replay is tracking the real trajectory.

| run | as-run | re-graded | lift |
|---|---|---|---|
| `crypto_n2_atscale` | 8.20 | **8.90** (`crypto_exchange_5` p1) | crypto lift **+7.0 → +10.5 pts** |
| `crypto_n1_raw` | 6.80 | 6.80 | |
| `postb25_atscale_r2` (ETF) | 8.70 | 8.70 | ETF lift unchanged, +6.8 pts |
| `postb25_raw_r2` (ETF) | 7.40 | 7.40 | |

Direction is not uniform and should not be claimed as such: **per database, ETF
and crypto move the atscale arm only, archeology moves the raw arm only.** That
reproduces the 2026-08-12 finding behind B-20 — it just does not generalise,
because archeology is the database §8 shows is structurally ungradable (7 of 10
tasks at risk, ceiling ~30%). A grading change is defensible because it removes
an artefact, not because of which arm it happens to help.

**B-22 was not optional.** `_compare_rows_numeric_tolerant` calls
`_ordered_match_tolerating_ties_numeric` *unconditionally* — it is not gated on
`grading_tie_tolerance` — so turning on the relative tolerance alone would have
dragged the same heuristic in with it. Swept over all 22 databases: the old
fallback fired on **33 of 365** multi-row order-sensitive phases and collapsed
**10** of them into a single tie group, silently converting an ordered
comparison into an unordered one. `exchange_traded_funds_6` is one of the 10.

**The two order mechanisms are complementary, not redundant.** Feeding a
differently-planned gold back through the grader across the 68 phases whose
order gold does not determine: the fixed heuristic rescues **48**, and the
order lint covers all **68** because it needs no key inference at all. Neither
alone is enough — the lint is a lower bound (a tie both plans emit identically
is not caught), which is exactly what the heuristic still catches.

### Deliberately not done

* **`Counter()` instead of `set()` (defect D).** Real upstream defect, wrong
  change for us to make alone. Gold's own result contains duplicate rows on
  **25 of 810** phases, **12** of them `order: false` — and a semantic layer
  answering at a grain cannot emit a duplicate row at all. Take it upstream
  *paired* with dropping the DISTINCT strip; adopting it here would penalise
  the arm that de-duplicates by construction.
* **Raising `GRADING_REL_TOLERANCE_VALUE` to 2e-5.** Over the full audit it
  adds exactly one phase more than 1e-6 — `crypto_exchange_4` p2, on the **raw**
  arm — by absorbing gold's own float4→numeric truncation (C2). At 2e-5 the
  forgiven gap on a 7-digit value exceeds one unit at the graded precision. The
  rule that keeps a tolerance defensible: **it must stay below the precision the
  task is graded to.**
* **Relaxing column order.** Three atscale submissions failed on it; the raw arm
  gets the output shape wrong at the same rate (`+1` column on 45 atscale and 38
  raw submissions). Model behaviour, not an engine artefact.
* **Turning `GRADING_HONOR_DECIMAL` off**, as §6 proposed. See that section.

### Dual reporting

Every flag above is a deviation, so no single number is self-describing. Runs
now record `run_started` / `run_finished`, the audit stamps every row with `ts`,
and `scripts/score_dual.py <results.json>` re-scores a finished run under both
regimes offline — free, no MCP replay, local Postgres only:

    upstream    every deviation off, the published leaderboard's rules
    as-run      whatever the .env flags were
    platform    all of the above on

Quote runs as a pair. A regime that passes MORE is a lower bound (a phase-1
flip means the live agent would have gone on to attempt phase 2, and that
submission does not exist); a regime that passes FEWER is exact.

### Three replay bugs, and the gate that now catches them

Offline re-grading is how every decision above was made, so a re-grade that
silently disagrees with the run it is replaying corrupts all of it. Adding a
reproduction check found three bugs in two days, none of which touched a
recorded score — all were in the offline tools:

* **`ex_base` does none of step 1's cleanup.** The live raw path gets it from
  `test_case_default`; `regrade_flags.py` called `ex_base` directly and so
  graded `ROUND()`ed gold against a stripped prediction.
  `exchange_traded_funds_3` recorded 1.0 and replayed 0.0. `score_dual.py`
  then walked into the identical trap the same day.
* **The retry discount is c-interact only** (`db_environment/server.py:378`).
  Applying 0.5/0.2 in a-interact under-counts every task that passed on a
  retry.

**None of the three was catchable by an oracle smoke test**, because there the
prediction *is* gold and both sides agree however they are graded. Two things
close the class:

* `grade_raw_submission()` in `db_utils` is now the single entry point for
  grading raw SQL — cleanup on both sides, then `ex_base`. Offline tools call
  it; nothing calls `ex_base` directly except the live path and
  dataset-supplied test cases.
* Both tools now **refuse to print** rather than warn. `regrade_flags.py`
  exits if its baseline misses the recorded per-task reward; `score_dual.py`
  exits if its as-run regime disagrees with the live grader on any single
  submission — sharper, since a total can net out while two verdicts move in
  opposite directions. Verified by tampering with one recorded verdict and
  confirming the gate fires.

Defect F is not an excuse to soften either gate: all 28 of its phases were
measured stable across ordinary reruns (§6b).
