# Grading defects to take upstream to `bird-bench/BIRD-Interact`

Written 2026-08-14 from measurements on all 22 databases, 410 Query tasks, 820
graded phases. Every number below came from local Postgres and the ADK's own
grader — **no API tokens, no benchmark runs.** Reproduce any of it with
`scripts/bird_order_lint.py` and `scripts/bird_precision_lint.py`.

This is about the **benchmark**, not our semantic models. Three of these defects
make tasks unanswerable by *any* system, including a perfect one, and they are
invisible in a score: the failure reads as a wrong value.

---

## 1. What grading actually does

Per task, `conditions = {decimal, distinct, order}` drives a four-step pipeline.
References are to this repo (`shared/db_utils.py`) and to **upstream's own
evaluator**, `evaluation/src/eval_bird_interact.py`, which is checked out one
level up at `/Users/dianne/go/src/github.com/BIRD-Interact/`. Every behaviour
below was read in both and matches unless noted.

1. **Clean gold** — `remove_comments` → `remove_distinct` → `remove_round`
   (`ex_base_external_pred`, ~line 845). Upstream does this too. Stripping
   `ROUND()` from gold matters more than it looks: it removes ties gold
   *manufactured* by sorting on rounded values.
2. **Execute both sides** on the same database.
3. **Round both sides** to `resolve_decimal_places(conditions)` — the task's
   `decimal`, or **2** when it says `-1`. Upstream is simpler and always rounds
   to 2 (`preprocess_results(results, decimal_places=2)`, called with no
   argument), so honouring `decimal` at all is an ADK deviation. Either way, a
   difference below the second decimal is invisible to grading.
4. **Compare** (`_compare_rows`):
   - `order: true` → **exact list equality**, row by row.
   - `order: false` → `set(pred) == set(gt)`.

Two things in step 4 deserve upstream attention on their own.

**The unordered branch uses `set()`, not a multiset — confirmed upstream.**
`eval_bird_interact.py:250` is `return 1 if set(predicted_res) == set(ground_res)
else 0`, character-for-character the same decision this repo makes. A prediction
returning every gold row five times grades as **correct**. Demonstrated against
`crypto_exchange_4` (15 gold rows, `order: false`) through the real grader:

    exact gold rows        15 rows -> 1
    every row duplicated   30 rows -> 1
    every row x5           75 rows -> 1
    one row only            1 row  -> 0

So it is not that anything passes — dropping rows is caught. It is specifically
**multiplicity that is ignored**, on every `order: false` task in the benchmark.

Worse, the two halves of the pipeline pull against each other. Upstream strips
the `DISTINCT` keyword from *both* queries (`remove_distinct`, called on pred and
sol at lines 260–262), which **manufactures** duplicate rows, and then compares
with `set()`, which **erases** them. A task whose whole point is de-duplication
cannot be failed on it.

And `conditions["distinct"]` is **never read** — not in this repo, not upstream.
It is dead metadata in both. So is `remove_order_by`, defined at
`eval_bird_interact.py:183` and called from nowhere.

**The ordered branch assumes gold totally orders its own result.** It does not.
That is defect A.

---

## 2. Defect A — `order: true` on a gold that does not determine an order

**57 of 410 Query tasks (13.9%), 68 of 438 order-sensitive phases.**

`conditions.order: true` makes the grader compare row by row. That is only
answerable if gold's `ORDER BY` *totally* orders its result. Where it has ties —
or is absent entirely — the "expected" order is whatever Postgres's chosen plan
happened to emit, and no other query can reproduce it except by luck.

Measured, not parsed: each gold runs twice, the second time with the planner
pushed onto different physical operators (`enable_seqscan/hashjoin/nestloop/
hashagg = off`), compared after the grader's own rounding, counting only cases
where the row *content* was identical so a value difference cannot masquerade as
an order difference. **Lower bound** — a tie both plans happen to emit
identically is not caught.

    archeology_scan   5 of 10      hulushows        9 of 20
    organ_transplant  5 of 19      fake_account     5 of 24
    labor_cert_apps   4 of 19      mental_health    4 of 20
    sports_events     4 of 20      disaster_relief  3 of 12
    reverse_logistics 3 of 20      crypto_exchange  2 of 20  (_6, _10)
    cybermarket       2 of 20      exchange_traded_funds 2 of 19
    polar_equipment   2 of 20      robot_fault      2 of 10
    virtual_idol      2 of 19      households / museum / solar_panel 1 each

In 57 of the 65 pre-cleanup hits more than 5% of rows displace, which makes
matching a lottery rather than a near miss: `crypto_exchange_10` phase 2
displaces 1627 of 2558 rows, `hulushows_16` 998 of 1000, `archeology_scan_6` 894
of 900.

**Worked example.** `crypto_exchange_6` — under the grader's own rounding the
model's rows match gold as a **multiset, exactly**. 401 of 1000 rows sit in ties.
It scores 0.00, and the failure looks like a value error. It was misdiagnosed
twice in one day before the ordering was measured.

### What to propose upstream

**A1. A dataset lint, run in CI.** For every task with `order: true`, assert the
gold result order is plan-independent. `scripts/bird_order_lint.py` is a working
implementation — replan-and-compare, no SQL parsing, no engine assumptions. A
task that fails the lint is a data bug, not a hard task.

**A2. Fix the 57, one of two ways.** Where the question genuinely says "sorted by
X", append a deterministic tie-break to gold's `ORDER BY` (the row's primary key
is usually enough). Where the order was incidental to writing the query, set
`order: false`. Both are one-line data edits; the lint tells you which tasks and
`conditions` tells you the intent.

**A3. Grade ties as ties.** Even with A2 done, two engines will not agree on the
order of rows equal on the sort expression — SQL guarantees nothing there.
Comparing *tied blocks as multisets, in sequence* grades what the question
asked. This repo already implements it
(`_ordered_match_tolerating_ties`), behind `GRADING_TIE_TOLERANCE`. Note the
caveat honestly when proposing it: our version **infers** the sort key from
gold's result (`_sort_key_indices` — the coarsest monotonic non-constant
column), because `conditions` does not record what gold sorted by. Upstream
could do far better by **recording the sort key in `conditions`** and grading
against it directly. That is the cleaner proposal and it removes the heuristic.

---

## 3. Defect B — gold computes in float32, everything else computes in float64

**11 of 410 Query tasks (2.7%).** Concentrated: `archeology_scan` 4 of 10, then
`crypto_exchange` `_5` `_10`, `polar_equipment` `_4` `_9`, `disaster_relief_4`,
`planets_data_5`, `solar_panel_2`.

Gold parses values — often text inside JSON — to `real`, a 32-bit float with ~7
significant digits, then computes in that type:

```sql
COALESCE((e.ambient_cond->>'Ambic_Temp')::real, 20.0)   -- ::real, not ::numeric
```

`archeology_scan_7` does this 4 times, `_6` 11 times. Archeology's base tables
contain **no float columns at all** — the entire exposure is these hand-written
casts. Any system reading the same text will parse to `numeric` or `double`,
both more accurate, and on rows where the true value sits near a rounding
boundary the two land on opposite sides:

    archeology_scan_6 p1   34 of 900 rows differ   755326.63 vs 755326.64
    archeology_scan_7 p1   24 of 900 rows differ       18.4  vs     18.5
    archeology_scan_8 p2   16 of 122 rows differ        6.4  vs      6.5
    archeology_scan_1 p2    2 of 597 rows differ       43.87 vs     43.88

One differing row fails the phase, so 0.3% of rows is as fatal as 13%.

**Counting `::real` casts is the wrong test** and would have produced a badly
wrong answer: `crypto_exchange_13` and `_14` carry 11 and 6 casts each and both
score 1.00. Only a difference that survives the grader's rounding counts, which
is what `scripts/bird_precision_lint.py` measures — it re-runs each gold with its
real columns widened to `float8` and compares after rounding.

### What to propose upstream

**B1. Drop `::real` from gold.** For a value stored as text there is no reason to
choose the lowest-precision numeric type available. `::numeric` is the correct
cast and is what the rest of the query already implies. Pure data fix, ~11 tasks.

**B2. Compare numerics with a relative tolerance.** A benchmark that grades to
the last representable digit is measuring float semantics rather than SQL
correctness. `1e-6` relative is far tighter than any real disagreement and
neutralises this class entirely. This repo has it as `GRADING_REL_TOLERANCE`
(off). Rounding to `decimal` places is **not** a substitute: the boundary case is
exactly where rounding disagrees.

---

## 4. Defect C — golds that no correct query can reproduce

Four shapes, all found by reading gold for diagnosis. Small counts, but each is
strictly unanswerable and each currently reads as a model failure.

**C1. `ORDER BY <all-ties> LIMIT 1`.** `crypto_exchange_1`:
`ORDER BY marketdata."TimeTrack" DESC LIMIT 1`, where `TimeTrack` holds **one
distinct value across all 605 rows**. The expected answer is whichever row the
scan returned. `crypto_exchange_3` is the same shape — `ORDER BY "FundSpot" DESC
LIMIT 1` where many rows tie on the maximum, landing on a market unrelated to
the question. *Lint: any gold with `LIMIT n` must have an `ORDER BY` that
uniquely determines its first n rows.* This is A1 extended to `LIMIT`, and it is
mechanical.

**C2. Two phases of one task disagreeing about one column.**
`crypto_exchange_4` phase 1 selects `ab.marg_sum` and expects `321804.16`; phase
2 selects `ab.marg_sum::numeric` and expects `321804` — Postgres truncates
float4→numeric at 6 significant digits — with the derived percentage rounded
from the truncated denominator. `conditions.decimal` is 6, so rounding does not
reconcile them. No single reading of the column satisfies both phases.
*Lint: within a task, the same source column should be read the same way.*

**C3. Accidental join fan-out.** `crypto_exchange_16` phase 2 joins orders to
`analyticsindicators` on `exchSpot = md_ref`, so each order becomes one row per
snapshot of its market, and the reference CTE is itself multi-valued and
`CROSS JOIN`ed: **993 rows from 970 orders**, including values below the
threshold the question states. Hard to lint automatically; a reviewer checklist
item — *does gold's row count match the grain the question names?*

**C4. Output labels the knowledge base never defines.** `crypto_exchange_17`
expects the literal `'Normal Market Conditions'` and `_19` expects
`'Normal Market'`. KB 16 and KB 12 define the *thresholds* — which a correct
model computes — but name no wording. The answer turns on guessing gold's
prose. *Either the KB entry should specify the labels, or the task should ask for
the boolean it actually tests.* (Both tasks did eventually pass here, by the
agent asking the user what to output — so this is a fairness issue, not an
impossibility.)

---

## 5. Sizing it: what this costs the benchmark

Union of A and B, per database we have a deployed model for:

    archeology_scan                   7 of 10 at risk   ceiling ~30%
    labor_certification_applications  4 of 19           ceiling ~79%
    crypto_exchange                   3 of 20           ceiling ~85%
    exchange_traded_funds             2 of 19           ceiling ~89%
    cybermarket_pattern               2 of 20           ceiling ~90%
    solar_panel                       1 of 20           ceiling ~95%
    households                        1 of 21           ceiling ~95%

`archeology_scan` is not a hard database, it is a **structurally ungradable**
one, and its recorded scores were never a model verdict. That single sentence is
probably the most valuable thing in this document.

---

## 6. A session plan

**Everything in steps 1–3 is free.** No API tokens, no benchmark runs. The lints
talk to local Postgres only, on disposable copies of the templates — never write
to a `*_template` database (B-25).

### Step 1 — reproduce, ~15 minutes

    source .venv-adk/bin/activate && export PYTHONPATH=.
    python scripts/bird_order_lint.py     <all 22 db names>   # -> /tmp/order_sweep.json
    python scripts/bird_precision_lint.py <all 22 db names>   # -> /tmp/precision_sweep.json

Expect 57 tasks / 68 phases from the first and 11 tasks from the second. If the
order count comes back at 65, the `clean()` step that applies gold's own
`remove_round` has been dropped — that difference is exactly the B-19 effect and
it is the single easiest way to over-report this defect.

### Step 2 — price the local mitigation before proposing anything

Both grader-side mitigations already exist here as flags and are **off**:
`GRADING_TIE_TOLERANCE` (defect A3) and `GRADING_REL_TOLERANCE` (defect B2).
`scripts/regrade_flags.py` re-scores a finished run offline under flag
combinations, with no LLM calls. Run it over the stored runs — start with
`results/crypto_n2_atscale_*.json` and the archeology runs — and record how many
submissions flip.

Read `docs/model-change-log.md` § "Tie tolerance is off, and B-19 is why" first.
The flag was measured a **no-op** on the semantic arm once B-19 stripped gold's
`ROUND()`. This sweep post-dates that fix and still finds 57 loose tasks, so the
premise for keeping it off should be re-tested rather than assumed — but test it,
don't assert it. A flag that only rescues one arm is a deviation, not a fix.

### Step 3 — file upstream

One issue per defect class against `github.com/bird-bench/BIRD-Interact`, each
carrying a mechanism-grade repro rather than a score:

| issue | ask | evidence to paste |
|---|---|---|
| A | lint + fix 57 tasks, and record the sort key in `conditions` | the lint script, the per-database table, `crypto_exchange_6` worked through |
| B | drop `::real` from gold; add relative tolerance | the four archeology row-diffs, and `_13`/`_14` as the counter-example |
| C1 | extend the lint to `LIMIT` | `crypto_exchange_1`: `SELECT count(*), count(DISTINCT "TimeTrack") FROM marketdata` → `605, 1` |
| C2 | intra-task column consistency | `crypto_exchange_4`'s two golds side by side |
| C4 | KB entries should name their output labels | `crypto_exchange_17` / `_19` against KB 16 / KB 12 |
| D | compare unordered results as multisets, and either honour `conditions.distinct` or drop it | `eval_bird_interact.py:250`, plus the 15/30/75-row demonstration above |

Every claim in §1 has been checked against upstream's own evaluator, which is
checked out at `/Users/dianne/go/src/github.com/BIRD-Interact/`. The `set()`
comparison, the unconditional `remove_distinct` on both sides, the unread
`conditions["distinct"]` and the uncalled `remove_order_by` are all upstream
behaviour, not ADK deviations — cite the line numbers when filing. The one ADK
deviation in the pipeline is honouring `conditions.decimal`; upstream always
rounds to 2.

### Step 4 — only then, if a number is wanted

A scored run costs ~$0.25 per task-run. Nothing in this document needs one: every
claim is established offline. If someone wants the headline "what would archeology
score under corrected grading", that is `regrade_flags.py` over the existing
archeology results — still free — not a new arm.

---

## 7. What is *not* in scope here

Engine defects (`Q-27` attribute-only join planning, `E-01` `COUNT(attribute)`,
`Q-15` `COUNT(DISTINCT)`, `Q-17b` non-idempotent publish) belong to AtScale, not
to BIRD, and are tracked separately. `E-05` was filed this morning and
**withdrawn the same day** — the grader rounds both sides before comparing, which
absorbs it; 0 of 410 tasks affected. Do not carry it upstream.
