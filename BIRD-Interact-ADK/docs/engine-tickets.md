# Engine ticket drafts — six dispatch-level defects

Drafted 2026-08-13 for filing by Dianne. Each ticket below is self-contained: it names
the inbound SQL, the SQL the engine actually dispatched, and a measured
correct-vs-observed pair. Nobody needs any of our benchmark context to reproduce them.

**Common preamble** — paste into each ticket, or state once if they are filed together:

> Reproduced against the deployed model
> `"bird_atscale_models_catalog_main"."Exchange Traded Funds"` (2310 funds, sourced from
> `public.funds` in the `exchange_traded_funds` Postgres). Every "dispatched" block below
> is the warehouse SQL returned by the MCP tool `get_outbound_queries` for the `queryId`
> that `run_query` returned, with the inlined dataset bodies elided — the wrapper is
> unmodified. Five of the six are **silent**: no error is raised, and the result is
> well-formed and plausible.

Severity in our tracker, for reference: E-01 and Q-24 P0; Q-23, Q-25, Q-26 P1; Q-22 P2.

---

## 1. `OFFSET` is silently ignored (our Q-22)

**Summary.** `OFFSET` is dropped from the dispatched query. Every offset returns the
first page, with no error and no warning.

**Inbound**

```sql
SELECT "Fund 1-Year Return"
FROM (SELECT "Fund", "Fund 1-Year Return"
      FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds"
      WHERE "Fund 1-Year Return" IS NOT NULL) t
ORDER BY "Fund 1-Year Return" ASC
LIMIT 1 OFFSET 50
```

**Dispatched** (tail of the wrapper)

```sql
ORDER BY
   1 ASC NULLS FIRST
LIMIT 1
```

`OFFSET 50` is absent. Result: `[{"Fund 1-Year Return": -0.9901}]` — the first row, i.e.
what `OFFSET 0` would give.

**Expected.** Either honour `OFFSET`, or reject the query. Silently returning a
different page than the one asked for is the worst of the three options: there is no
error text a caller can match on to detect it.

**Impact.** Any "nth largest / nth smallest" question is unanswerable and returns a
confidently wrong answer.

---

## 2. NULL sort order is inverted vs Postgres and cannot be overridden (our Q-23)

**Summary.** The engine forces its own NULL-ordering convention — `ASC` → `NULLS FIRST`,
`DESC` → `NULLS LAST` — which is the **opposite** of Postgres's default for `ASC`. An
explicit `NULLS FIRST` / `NULLS LAST` in the inbound query is accepted and then ignored.

**Inbound A**

```sql
SELECT "Fund", "Fund Bond Duration (Years)"
FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds"
ORDER BY "Fund Bond Duration (Years)" ASC NULLS LAST
LIMIT 5
```

**Dispatched A**

```sql
ORDER BY
   2 ASC NULLS FIRST
LIMIT 5
```

Result is five rows whose sort column is `null` — exactly what `NULLS LAST` was written
to prevent.

**Inbound B** (the mirror case)

```sql
... ORDER BY "Fund Bond Duration (Years)" DESC NULLS FIRST LIMIT 5
```

**Dispatched B**

```sql
ORDER BY
   2 DESC NULLS LAST
```

**Expected.** Honour an explicit `NULLS FIRST` / `NULLS LAST`. Failing that, reject it
rather than accepting and discarding it, and match the source dialect's default when no
override is given.

**Impact.** Silent. Any top-N over a nullable column returns nulls where the caller
asked for values, and there is nothing in the response to indicate the override was
dropped.

---

## 3. Any projection omitting the entity key is de-duplicated on its value tuple (our Q-24)

**Summary.** Whenever a projection omits an entity key, the engine collapses it to the
**distinct value tuples** — in a derived table *and in plain detail rows*.
`SELECT "Fund 3-Year Beta" FROM <model>` returns **342 rows** where there are **2310**
funds; adding `"Fund"` to the SELECT list returns all 2310. Row counts across four
projections: `"Fund"`+AUM 2310, AUM alone 2274, `"Fund"`+beta 2310, beta alone 342,
`"Exchange"`+AUM 2277. Nothing errors. The aggregate case below is the same mechanism
reaching an aggregate; this paragraph is the more damaging half, because it silently
changes the caller's **row set** rather than one number.

**In a derived table**, the same collapse means an outer aggregate runs over distinct
values rather than over entities. Nothing errors, and the magnitude of that error depends
entirely on how many duplicate values the data happens to contain.

**Inbound — key omitted**

```sql
SELECT AVG(t."Fund Consistency-Adjusted Information Ratio") AS v
FROM (SELECT "Fund Consistency-Adjusted Information Ratio"
      FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds") t
```
→ `0.045616623243724196`

**Inbound — key projected** (only difference is `"Fund"` in the inner SELECT list)

```sql
SELECT AVG(t."Fund Consistency-Adjusted Information Ratio") AS v
FROM (SELECT "Fund", "Fund Consistency-Adjusted Information Ratio"
      FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds") t
```
→ `0.045571502943779846`, which matches the model's own
`"Average Consistency-Adjusted Information Ratio"` measure (`0.04557150294377993`)
to 15 significant figures.

**Proof that the mechanism is de-duplication, not rounding.** Two independent witnesses:

1. Take `SUM` and `AVG` of the same column in one query and divide to recover the row
   count the engine used. Keyless: `46.072789476 / 0.045616623244` = **1010**. Keyed:
   `46.072789476 / 0.045571502944` = **1011**. The SUM is *identical* in both, so
   exactly one row was dropped and its value was `0.0` — a duplicate that changes only
   the divisor.
2. `SUM("Fund Net Assets (AUM)")` keyless is short of the model measure by **exactly
   160**. Source-side: `SELECT count(*), count(DISTINCT networth) FROM public.funds`
   → `(2310, 2273)`, and the 36 surplus rows sum to **exactly 160**.

**Blast radius** (each cell: inner derived table with vs without the entity key, judged
against the model's own measure under the same filter):

| aggregate | plain | filtered | grouped |
|---|---|---|---|
| `AVG` | wrong | correct¹ | wrong |
| `SUM` | wrong | wrong | wrong |
| `MAX` | correct | correct | — |
| `MIN` | correct | correct | — |

¹ correct only because that slice happens to contain no duplicate values.

`MIN`/`MAX` are structurally immune — dropping duplicates cannot move an extreme.
Putting the key in the inner `WHERE` instead of the inner `SELECT` list behaves
identically to omitting it, in all 11 shapes tested.

**Expected.** A projection should preserve row multiplicity. If the engine must re-group
to resolve grain, the entity key it grouped by at the innermost level should survive into
the next wrapper rather than being projected away.

**Impact.** Two separate harms. At detail level the caller silently receives a fraction of
the rows — 342 of 2310 in the case above — whenever the columns they asked for happen not
to be unique per entity, which is entirely a property of the data. At aggregate level, the
derived-table form is the shape we currently *recommend* as the workaround for resolving
grain, so the recommended workaround is itself silently wrong for `AVG` and `SUM`. In
neither case can a caller verify by comparing numbers: sometimes the keyless form is
exactly right.

**Repro harness.** `scripts/grain_pairs.py` in the BIRD-Interact-ADK repo runs the full
11-shape × 3-arm matrix and judges each arm against the model's own measure. No LLM
calls.

---

## 4. `UNION` over the model returns zero rows without dispatching (our Q-25)

**Summary.** A `UNION` / `UNION ALL` whose branches read the model returns an empty
result and no warehouse query is dispatched at all. No error is raised.

**Inbound**

```sql
SELECT "Exchange" FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds"
WHERE "Exchange" = 'BATS'
UNION ALL
SELECT "Exchange" FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds"
WHERE "Exchange" = 'NasdaqGM'
```

Result: `[]`. `get_outbound_queries` returns no warehouse SQL for the `queryId` — the
query was answered without ever reaching the warehouse.

**Control.** A `UNION ALL` over literals only
(`SELECT 'AAA' AS ticker, '1.23' AS score UNION ALL SELECT 'TOTAL', '456'`) works,
because it never enters the rewrite path. So the failure is specific to a branch that
reads the model.

**Expected.** Support `UNION` over the model, or reject it with an error. An empty result
set is indistinguishable from a legitimately empty answer.

**Impact.** Silent and total: the caller gets zero rows and no signal. Observed live in a
real submission (our task `etf_11`), which scored zero on an empty result.

---

## 5. A scalar subquery is spliced into the outer row's context (our Q-26)

**Summary.** A subquery on the right-hand side of a comparison is not evaluated as a
scalar. The engine inlines the inner `SELECT`'s expression into the **outer row**, so the
comparison becomes row-versus-itself. The subquery and its `LIMIT` disappear.

**Case A — same column on both sides.**

```sql
SELECT "Fund Count" FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds"
WHERE "Fund Turnover Ratio" < 0.3
  AND "Fund Relative Expense Ratio" > 0
  AND "Fund 52-Week Range Move Pct" <
      (SELECT "Fund 52-Week Range Move Pct"
       FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds" LIMIT 1)
```

**Dispatched**

```sql
WHERE
   t_11."turnover_ratio" < CAST(0.3 AS FLOAT8)
AND
   t_11."relative_expense" > 0
AND
   t_11."range_move_pct" < t_11."range_move_pct"
```

The predicate is `x < x`. Result: `[{"Fund Count": null}]` — a bare NULL, no error.
(Dropping the third predicate entirely returns 135.)

**Case B — different columns. This is the dangerous one.**

```sql
... WHERE "Fund Turnover Ratio" <
    (SELECT "Fund 52-Week Range Move Pct" FROM <model> LIMIT 1)
```
dispatches as `t_8."turnover_ratio" < t_8."range_move_pct"` and returns
`[{"Fund Count": 373}]` — a plausible number with no error, computed from a predicate
the caller never wrote.

**Case C — a model measure as the threshold.**

```sql
SELECT "Fund Count" FROM <model>
WHERE "Fund Net Assets (AUM)" > (SELECT "Average Net Assets (AUM)" FROM <model>)
```

**Dispatched**

```sql
t_5."net_worth" > CASE WHEN (COUNT(t_5."net_worth") = 0) THEN NULL
                       ELSE (SUM(CAST(t_5."net_worth" AS FLOAT8)) / COUNT(t_5."net_worth")) END
```

An aggregate expression evaluated inside `WHERE` at row grain. Result: `null`. The same
threshold written as a literal (`> 2447563700`) returns **242**.

**Case D — the same rewrite in the SELECT list**, which is presumably already known:
`SELECT "Fund", (SELECT "Average Net Assets (AUM)" FROM <model>) AS pop_avg FROM <model>`
gives each row its **own** AUM (`25170364`, `2666543104`, `1267852…`) rather than one
repeated population value.

**Case E.** Wrapping a SQL `AVG` in the subquery instead trips a planner assertion:
`Error during query planning: In query planning stage ExpandStatFunctions: assertion
failed: We already handled attribute values`. (Same assertion as our Q-21.)

**Case F — a CORRELATED subquery in the SELECT list.** Found 2026-08-13 by the
clause-fidelity battery, which reported this probe **CLEAN**: no clause disappeared, so
only the numbers give it away.

```sql
SELECT t."Fund",
       (SELECT MAX(s."Fund 3-Year Alpha")
        FROM <model> s WHERE s."Category" = t."Category") AS cat_max
FROM <model> t LIMIT 5
```

**Dispatched**

```sql
SELECT t_7."fund_gbakc2" AS "Fund", t_7."cat_max_gbakc3" AS "cat_max"
FROM (
   SELECT t_5."tickersym" AS "fund_gbakc2",
          MAX(t_5."alpha_3y") AS "cat_max_gbakc3",
          t_5."tickersym" AS "fund_gbakc1"
   FROM ( ) AS "t_5"
   WHERE true
   GROUP BY 1, 3
) AS "t_7"
```

The correlation predicate `s."Category" = t."Category"` is gone (`WHERE true`) and the
`MAX` is grouped by **`tickersym`** — the outer row's own key — instead of by category. So
`MAX` is taken over a single fund and `cat_max` is each fund's own alpha. Verified against
the source Postgres: `FLQE` → `-2.5`, `IGLB` → `-1.53`, `MAGA` → `-8.99`, each exactly the
fund's own `Alpha_3Y`. A per-category maximum would be shared by every fund in that
category.

**Case G — the same correlated subquery in `WHERE`** errors instead of lying:

```sql
SELECT t."Fund", t."Fund 3-Year Alpha" FROM <model> t
WHERE t."Fund 3-Year Alpha" >
      (SELECT AVG(s."Fund 3-Year Alpha") FROM <model> s WHERE s."Category" = t."Category")
```
→ `In query planning stage ExpandStatFunctions: assertion failed: We already handled
attribute values` (the Case E / Q-21 assertion). The asymmetry is the problem: the `WHERE`
form fails loudly and the `SELECT` form fails silently, so the shape an agent is most
likely to trust is the one that lies.

**Expected.** Evaluate an uncorrelated scalar subquery once and compare against its
scalar result, or reject it. Rewriting it into a self-reference produces a different
query than the one submitted. For the correlated form, honour the correlation predicate
and group by the correlated key — or reject it as unsupported, as the `WHERE` form
already does.

**Impact.** The `WHERE` form is worse than the already-known `SELECT`-list form because
it silently changes *which rows are counted*, not just which value is displayed. It
removes the natural way to express any threshold derived from the data. Observed live in
a real submission (our task `etf_18`).

---

## 6. `COUNT` **and `SUM`** over a dimension column return members and drop the `GROUP BY` (our E-01)

**Summary.** Previously reported for `COUNT` (and believed addressed by ATSCALE-48425 in
`release/2026.6.1`; still reproducing on `develop`). **`SUM` does the same thing**, and
because its result is numeric it is far harder to notice.

**Inbound**

```sql
SELECT "Exchange", SUM("Fund Net Assets (AUM)") AS v
FROM "bird_atscale_models_catalog_main"."Exchange Traded Funds"
GROUP BY "Exchange"
```

**Observed.** **2277 rows** — one per distinct value —
`[{"Exchange": "BATS", "v": 20.0}, {"Exchange": "BATS", "v": 25.0}, {"Exchange": "BATS",
"v": 1307549.0}, …]`. There are **4** exchanges.

**Dispatched.** The wrapper contains **no `SUM(` at all**; the output column is aliased
straight off the raw per-fund column:

```sql
SELECT
   t_11."exchange_gbakc2" AS "Exchange",
   t_11."v_gbakc3" AS "v"
FROM
(
   SELECT
      t_9."tradingvenue_c7" AS "exchange_gbakc2",
      t_5."net_worth" AS "v_gbakc3",
      ...
```

The aggregate function was deleted and the `GROUP BY` became a de-duplication over
`(Exchange, net_worth)`.

**Aggregate boundary**, same column, same `GROUP BY "Exchange"`:

| aggregate | behaviour |
|---|---|
| `SUM` | **silently ungrouped**, 2277 rows, aggregate deleted |
| `COUNT` | **silently ungrouped**, 2277 rows, returns the member value |
| `AVG` | errors loudly (`ExpandStatFunctions` assertion) |
| `MAX` | correct, 4 rows |
| `MIN` | correct, 4 rows |

So of the five, the two that fail silently are the two that come back looking like
ordinary numbers.

**Control.** The model's own `"Total Net Assets (AUM)"` measure with the same `GROUP BY`
returns the correct 4 rows
(`BATS 452518855542`, `NasdaqGM 1729766596348`, `NYSEArca 3471212641666`, `Other OTC …`),
as does a grain-forced derived table that projects the entity key.

**Expected.** Apply the aggregate and honour the `GROUP BY`, or reject the query as
`AVG` already does. The current behaviour returns a well-formed result set that answers
a different question.

**Impact.** Highest-frequency of the six in real traffic: bare `COUNT` over a dimension
appears in 2–6 of every 19 tasks in our runs continuously since 2026-08-06, and never in
the paired non-semantic-layer arm. The `SUM` half means a caller asking for four group
totals silently receives 2277 per-entity rows.

---

## Reproducing all six

From the BIRD-Interact-ADK repo, no LLM calls and no benchmark cost:

    scripts/outbound_sql.py "SELECT ..."       # run, then print what was dispatched
    scripts/clause_fidelity.py --show-sql      # 20-probe battery; 1, 2, 4, 5 are controls in it
    scripts/grain_pairs.py                     # the Q-24 matrix in full

`scripts/clause_fidelity.py` keeps the known defects as controls deliberately: if
`OFFSET` ever stops being reported there, the probe broke rather than the engine.
