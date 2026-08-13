# Outbound-SQL follow-ups — reload doc

Written 2026-08-13 to survive a context clear, and worked through the same day.
Self-contained: assumes the reader knows nothing about the session that produced it.
Read this top-to-bottom before running anything.

Everything here is **$0 in benchmark tokens** — MCP probes and Postgres reads only, no
LLM calls. Do not start a benchmark run for any of it.

**Next work is planned in `docs/etf-investigation-plan.md`** — five self-contained items
sized to be run one per fresh context. Start there; this doc is the evidence behind it.

> **That plan has since been worked through (2026-08-13). Outcomes live in the tracker,
> not here — go to the sheet rows named below, then come back to this doc only for the
> dispatch-level evidence.** One entry point, as the plan's definition of done asked for.
>
> | plan item | outcome | rows written |
> |---|---|---|
> | 1. Q-24 reach into real submissions | **Zero** confirmed instances in 19 graded submissions; explains 0 of the 6 unexplained failures. The agent already projects the key. B-06/B-07 forcing hypothesis did not arise. | Q-24, Q-26, Q-25 |
> | 2. Why `_12` fails | Gold's **row shape** — 2 cols × 11 rows with a labelled summary row last. Numbers were right, shape wrong; 0 under all four flag combos, 1 in gold's shape. `_12` stays WITH `_11`; the recommended split was reversed. | B-04 |
> | 3. Is the guidance landing? | **Yes.** Every bullet measurable at scale violates at ≤1.8%, most 0.0%. Only UNION-over-model predicts failure (10/10 scored 0). Two bullets found **over-stated** (E-01's absolute, and "COUNT(DISTINCT) must be ALONE"). Ask-budget question untouched — not SQL-visible. | M-25, E-01 |
> | 4. Six model-side defects | M-02 and M-06 **still reproduce** (M-06 under its renamed column); M-07 **fixed**; M-01 **obsolete** (subject dropped in a redeploy); M-03 engine-blocked; M-09 is archeology, not ETF. **Stopped for approval before spending.** | M-01, M-02, M-03, M-06, M-07, M-09 |
> | 5. Clause-fidelity gaps | Four gap areas closed, battery now 33 probes. One new defect shape: a **correlated** subquery in the SELECT list reports CLEAN and silently returns each row's own value. | Q-26, Q-19 |
>
> Re-runnable tooling added: `scripts/key_projection_audit.py` (Q-24 exposure per run) and
> `scripts/guidance_compliance.py` (per-bullet violation rates). Both encode detector bugs
> that produced confident wrong answers first — read their comments before trusting a rate.

**Status: all five items in THIS doc are worked through.** Items 1–4 are kept below as findings, not
as instructions. Item 5's tickets are drafted in `docs/engine-tickets.md` and are
Dianne's to file — she asked for drafts rather than for them to be filed directly.
What remains to do is marked as such.

---

## 0. Why this exists

The SQL an agent writes is not the SQL that runs. The AtScale engine rewrites it, and
several rewrites are **silent**: a clause is dropped or inverted, the result is
plausible, nothing errors. That family is the most common failure shape in the ETF
tracker. Reading the dispatched warehouse SQL is what makes it visible.

Five defects have been found this way (Q-22, Q-23, Q-24, Q-25, and Q-26 on the second
pass), and a sixth — SUM/COUNT over a dimension not aggregating — widened E-01. Three
conclusions were *overturned* the same way, and one probe that reported CLEAN was wrong
by a factor of 570; see "Already established" so you don't redo them.

### The tools

    scripts/outbound_sql.py "SELECT ..."        # run, then print what was dispatched
    scripts/outbound_sql.py --query-id <uuid>   # resolve an earlier run_query
    scripts/outbound_sql.py --full "SELECT ..." # include the inlined dataset SQL
    scripts/outbound_sql.py --tail 40 "..."     # last N lines only

It wraps the MCP tool `get_outbound_queries`, which resolves the dispatched SQL for any
`queryId` returned by `run_query`. By default the ~400 lines of inlined dataset SQL are
elided; the wrapper (GROUP BYs, ORDER BY, LIMIT) is where rewrites show up.

    scripts/clause_fidelity.py                  # 20-probe battery, inbound vs dispatched
    scripts/clause_fidelity.py --show-sql
    scripts/clause_fidelity.py --only offset

    scripts/grain_pairs.py                      # Q-24 blast radius, 11 shapes x 3 arms
    scripts/grain_pairs.py --only sum
    scripts/grain_pairs.py --show-groupby

All three are committed. The model under test:

    M='"bird_atscale_models_catalog_main"."Exchange Traded Funds"'

Column names are not guessable — get them from
`explore_columns` with `catalog` / `schema` / `table` (all three required) and
`role=measure` or `role=dimension`. Note that the per-fund values used below
(`"Fund Net Assets (AUM)"`, `"Fund 3-Year Beta"`) are **dimension** columns, not
measures; the measures are the aggregated `"Average ..."` / `"Total ..."` forms.

### Postgres helper (NOT committed — recreate it)

Scratchpads do not survive a context clear. Recreate this in the current one:

```python
#!/usr/bin/env python3
"""Run SQL against the ETF source Postgres. Source data only - firewall-safe."""
import sys
sys.path.insert(0, '/Users/dianne/go/src/github.com/BIRD-Interact/BIRD-Interact-ADK')
from shared.db_utils import perform_query
q = sys.stdin.read() if sys.argv[1:2] == ['-'] else sys.argv[1]
for row in perform_query(q, 'exchange_traded_funds')[0]:
    print(row)
```

Source column names differ from the model's and from the obvious guess —
it is `funds.networth`, not `net_worth`. Let the error's HINT tell you.

Never `source` the ADK `.env` — it holds other services' keys and a value with shell
metacharacters gets executed. `grep` the single variable you need.

---

## Already established — do not re-derive

- **The model's dataset SQL is fan-out free.** The dispatch is `public.funds` LEFT JOINed
  to five sources on `tickersym`; `annual_returns`, `holdings` and `bond_allocations` are
  each pre-aggregated (`GROUP BY portfolioref` / `instrumentref` / `fundlink`), and
  `performance` (2310/2310) and `risk_metrics` (1507/1507) are strictly 1:1 with
  `funds` (2310). So the E-01 / M-02 / Q-15 count anomalies are **engine rewriting, not
  the model**.
- **Q-24 is a DEDUP defect** — see Item 1 below for the proof and the blast radius. The
  earlier framing ("the outer aggregate runs over distinct values") was right about the
  effect and vague about the cause, which made it look shape-dependent when it is
  data-dependent.
- **Q-25**: a UNION whose branches read the model returns `[]` and is never dispatched.
  A FROM-less UNION over literals works (it never enters the rewrite path).
- **Q-22**: OFFSET dropped entirely. **Q-23**: `ASC` → NULLS FIRST, `DESC` → NULLS LAST,
  the reverse of Postgres, and `NULLS FIRST/LAST` are accepted then ignored.
- **B-24 stands**: the measure route dispatches exactly `SUM/COUNT` at fund grain with no
  rewrite. Its previously cited "second witness" (0.013368) was Q-24 firing, not
  corroboration.
- **`_6` is not an engine problem**: dispatch was faithful (inner ORDER BY survived,
  LIMIT intact, key preserved). Its cause is B-02.
- Clause fidelity is **necessary, not sufficient**: Q-24 preserves every clause and is
  invisible to `clause_fidelity.py`. It shows up only as two different numbers. The
  `nested-aggregate` probe made the same point the expensive way — CLEAN verdict, answer
  wrong by 570x. **Always check a probe's number against something, not just its
  clauses.**

---

## Item 1 — Q-24 blast radius across guidance-prescribed patterns — **DONE**

**Mechanism, proven, not inferred.** Any projection that omits the entity key is
**de-duplicated on the tuple of columns you projected**. This is not confined to derived
tables — a plain `SELECT "Fund 3-Year Beta" FROM M` returns **342 rows against 2310
funds**, and adding `"Fund"` restores all 2310 (AUM alone 2274; `"Exchange"`+AUM 2277).
The aggregate case is the same mechanism one level up. Q-24 was raised to **P0** on this,
because a wrong row set lands straight on the submitted answer. Two independent witnesses
for the aggregate half:

- Implied row count via `SUM/AVG` over `"Fund Consistency-Adjusted Information Ratio"`:
  **1010** with the measure alone, **1011** with `"Fund"` added, and the SUM identical
  in both. Exactly one duplicate CAIR value (a `0.0`) is dropped, which moves only the
  divisor — 46.072789476/1010 = 0.0456166, /1011 = 0.0455715, matching the model's own
  `Average` measure exactly.
- `SUM("Fund Net Assets (AUM)")` keyless is short by **exactly 160**. Source-side:
  2310 funds, 2273 distinct `networth`, and the 36 duplicate rows sum to exactly 160.

So the size of the error is a property of **the data**, not of the query.

**Blast radius** (`scripts/grain_pairs.py`, 11 shapes × 3 arms, each arm judged against
the model's own pre-built measure under the same filter):

| | plain | filtered | grouped | two-measure |
|---|---|---|---|---|
| AVG | **wrong** | correct* | **wrong** | correct* |
| SUM | **wrong** | **wrong** | **wrong** | — |
| MAX | correct | correct | — | — |
| MIN | correct | correct | — | — |

`*` correct **by luck of the data** — no duplicate tuples exist in that slice.

- **MIN/MAX are structurally immune**: dropping duplicates cannot move an extreme.
- **AVG and SUM are wrong wherever duplicates exist**, which the agent cannot know.
- **"Key in the inner WHERE only" tracked "key omitted" exactly in all 11 shapes** —
  the guidance claim is confirmed.

**Guidance updated** in `config/environment_backends.yaml`: the bullet now states the
dedup mechanism, states the rule as an absolute, and says explicitly that a matching
number is not evidence you got it right. Tracker Q-24 carries the mechanism and matrix.

**Watch the comparison tolerance if you extend this.** A relative floor of `1e-8`
reported three SUM shapes as clean; the real dedup gap there is `3e-11`, because the 36
dropped funds happen to total $160 against a $5.65e12 sum. `grain_pairs.py` now uses
`1e-12`, measured from the ~2e-15 agreement the two routes show when they agree at all.
Any floor set loose enough to feel safe hides real instances on data that happens to be
kind.

---

## Item 2 — the `JOIN ... ON 1=1` workaround for Q-20 — **DONE, and it is SOUND**

Read at dispatch level with two different filters live. The workaround survives intact:

- the join is dispatched as a real `JOIN ... ON true`;
- the detail side keeps fund grain, the aggregate side keeps its own;
- the outer detail filter does **not** leak into the aggregate subquery, and the
  aggregate's own population filter does not leak out (detail filtered to
  `Category = 'Large Blend'`, aggregate filtered to `AUM > 1e10` → 80, matching the
  standalone count; the aggregate returned the whole-population average, not the
  Large Blend one).

**One caveat, and it is Q-24 composing rather than a defect of this shape**: if the
aggregate side computes its value with raw SQL over a *keyless* derived table, the
dedup fires inside it (0.045617 instead of 0.045572). Use a model measure there, or
project the key.

So Q-20's "temp fix" status is correct and its workaround does not need replacing.

---

## Item 3 — dispatch the failing submissions — **DONE**, and it found Q-26

Run examined: `results/guidance0813_atscale_r1_20260813_095443.json` (trajectories are
grading-independent). Every failing task's **graded** submission was re-dispatched.

- **`_18` → new defect, filed as Q-26.** Its submission compares a column against a
  scalar subquery. The engine does not evaluate the subquery as a scalar: it **splices
  the inner SELECT's expression into the outer row's context**, so
  `"Fund 52-Week Range Move Pct" < (SELECT "Fund 52-Week Range Move Pct" FROM M LIMIT 1)`
  dispatches as `range_move_pct < range_move_pct`. The predicate is `x < x`, the count
  comes back `NULL`, nothing errors. Three further probes show the shape of it:
  cross-column returns a *plausible* wrong count (373, no error); a model measure as the
  threshold dispatches the aggregate expression into the WHERE clause and returns NULL
  where the identical literal threshold returns 242; a SQL `AVG` inside the subquery
  instead trips the Q-21 planner assertion. This is the same rewrite as Q-20's
  SELECT-list trap, in the more dangerous half of the query. Guidance bullet added.
- **`_11` → Q-25.** Its graded submission is the UNION-over-model form: `[]`, no
  warehouse query dispatched. Guidance already tells the agent to assemble a summary row
  as a FROM-less literal query; it followed the structure and not that requirement.
- **`_12` → dispatch faithful (negative result).** It uses the `JOIN ... ON 1=1` column
  form and returns the correct population share 0.9397 beside the top-10 rows. Its
  failure is not the UNION shape, so B-04 can no longer assert one cause for both tasks.
- **`_1`, `_2`, `_4`, `_7`, `_9`, `_10` → dispatch faithful (negative results).** Each
  dispatched one outbound query with its ORDER BY intact and nothing dropped. Causes are
  model, gold, or agent — not the engine.
- `_20` passed in this run (reward 1.0), so it was dropped from the list.

**Still to do:** `_12`'s own diagnosis (gold row-shape vs column typing), and the
`_1`/`_2`/`_4`/`_7`/`_9`/`_10` causes, which are now known *not* to be dispatch-level.

---

## Item 4 — extend the clause-fidelity battery — **DONE**, and it found the worst one

Battery is now 20 probes: 10 rewritten, 1 errored, 9 clean. Added: scalar subquery in
WHERE and in SELECT (Q-26 controls), `CASE` in WHERE, `CASE` in ORDER BY, a string
function, a nested aggregate over a grouped derived table, and a two-dimension GROUP BY
across datasets. Known defects are kept as controls — **if OFFSET ever stops being
reported, the probe broke, not the engine.**

What the new probes returned:

- **`nested-aggregate` came back CLEAN and was wrong by a factor of 570** — which is the
  whole argument for never trusting a clause-level verdict on its own. Chasing the
  number found the most consequential defect of the session: **`SUM()` over a dimension
  column with a `GROUP BY` neither sums nor groups.**
  `SELECT "Exchange", SUM("Fund Net Assets (AUM)") ... GROUP BY "Exchange"` returns
  **2277 rows** — one per distinct value, with the raw per-fund number in the `SUM`
  column — instead of the 4 real groups. The dispatched wrapper contains **no `SUM(` at
  all**; `v` is aliased straight off `t_5."net_worth"`. Silent, and every number in the
  result is genuine, so it reads as a longer answer rather than a wrong one.
  The aggregate boundary over the same column and GROUP BY: **SUM and COUNT silently
  ungrouped; AVG errors loudly (Q-21); MIN and MAX correct.** The two that are silent
  are the two that return plausible numbers. Recorded by widening **E-01**, whose
  COUNT half is the same symptom, and a guidance bullet was added.
  The model's own measure and the grain-forcing derived table both give the correct 4
  groups, so the existing workaround already covers this.
- `case-in-orderby` errors with "Could not find correct column to sort by" — this is the
  engine limitation the agent hit in `_6`, now reproduced on demand.
- `case-in-where` (252, matching the direct predicate), `string-function`, and
  `scalar-subquery-in-select` are all faithful at clause level; the last of those is
  semantically wrong (Q-26) and is kept precisely as a standing reminder that CLEAN
  means "no clause vanished", nothing more.
- `two-dataset-groupby` is correct apart from the engine adding its own
  `ASC NULLS FIRST`, which is Q-23 and already known.

Still not covered: date/`EXTRACT` handling, correlated subqueries, multi-dataset joins
written by hand, and window functions beyond `RANK`.

### Detector discipline (learned the hard way)

Seven pattern-matching bugs on 2026-08-13 each produced a confident wrong conclusion.
Every one encoded a single spelling of a concept:

- `HAVING`-only check missed a threshold applied in `WHERE`
- `ORDER BY "Col" DESC` missed `ORDER BY alias DESC`
- `[^\s]+` truncated a quoted multi-word column at its first space
- `'25' in sql` missed the equivalent `>= 26`, then `>= 25`
- a bundle regex flagged `or`-alternatives, which are the *good* question shape

An eighth, from this session, is worth adding because it is the opposite failure — a
detector that was too *loose*: extracting numbers from a result with a regex over the
raw JSON pulled the `3` out of the column NAME `"Min 3-Year Beta"` and reported a
disagreement that did not exist. Parse the structure; do not pattern-match it.

**When a pattern-match disagrees with the data, suspect the pattern first.** Prefer
computing semantics over matching text: for a threshold, parse the operator and operand
and compute the smallest included value.

---

## Item 5 (the only item left) — file the engine tickets

Ten engine/MCP defects, **zero tickets**. Every `Jira/Git` field is empty or points at a
guidance commit, i.e. agent-side mitigation only:

    Q-12  inner ORDER BY dropped when the derived table has no LIMIT
          (source line already pinned: RemoveInnerOrderBy.scala:19)
    Q-15  COUNT(DISTINCT dim) null / wrong under a measure predicate
    Q-20  whole-population value beside detail rows: 3 of 4 shapes silently wrong
    Q-21  bare MIN/MAX/AVG over a measure dies in query planning
    Q-22  OFFSET silently ignored
    Q-23  NULL ordering inverted and un-overridable
    Q-24  keyless derived table is deduped on the projected tuple      [P1, silent]
    Q-25  UNION over the model returns zero rows                       [P1, silent]
    Q-26  scalar subquery spliced into the outer row, WHERE and SELECT [P1, silent]
    E-01  COUNT *and SUM* over a dimension return members and drop the GROUP BY
          (widened 2026-08-13; MIN/MAX correct, AVG errors via Q-21)

**Drafted, not filed.** `docs/engine-tickets.md` holds ready-to-paste write-ups for the
six with dispatch-level repros — Q-22, Q-23, Q-24, Q-25, Q-26 and E-01. Each carries the
inbound SQL, the dispatched SQL, and a measured correct-vs-observed pair, so the engine
team needs none of our benchmark context to reproduce them. Dianne files them; nothing
has been sent anywhere.

The remaining four (Q-12, Q-15, Q-20, Q-21) are real but written up symptom-level rather
than dispatch-level. Give them the same treatment before filing — the six that got it
are markedly stronger for it, and Q-24 in particular only became credible once it was
corroborated against the source data.

---

## Constraints that still apply

- **Do not start a benchmark run** for any of this. All of it is probe-only.
  If a run ever becomes necessary: `bash scripts/gate_run.sh` first, Sonnet only for
  anything scored, and re-grade the baseline before comparing (see below).
- **Grading has moved three times.** Every stored baseline predates the current grader.
  Re-grade the baseline trajectory before quoting any comparison:
  `python scripts/regrade_flags.py atscale <results.json> --database exchange_traded_funds`
  — free, no LLM calls. Skipping this produced a phantom regression on 2026-08-13.
- **Noise floor:** ±0.70 points (~3.7 pp) on a 19-task arm; individual tasks swing the
  full 1.00. Judge changes by mechanism, not by score, at n=5.
- **Gold SQL** may be used to *diagnose* but must never reach the model, the guidance, or
  any code. Every number and rule shipped must trace to the KB, the schema, the task
  question, or the source data. The A10 gate (`utilities/masked_threshold_gate.py` in
  the model repo) enforces the masked-threshold half of this.
- **Tracker:** record findings only via `python scripts/sheet.py` (`cols` / `read` /
  `get <id>` / `set <id> Field=...` / `add "ID=..."`). Re-read before a batch of writes;
  append to Notes rather than replacing. `set` can time out silently — verify it landed.
  `results/etf_issues_tracker.tsv` is a stale snapshot; never read it as current state.
- **Model changes** go in `AtScaleInc/bird-atscale-models` (commit to `main`, push, then
  `bash scripts/deploy_models.sh`) and must be logged in `docs/model-change-log.md` in
  the same change. Before adding any ask-trigger text, read **M-25**: the agent's ask
  budget is ~3 questions, triggers compete for it, and ETF already carries 20
  trigger-bearing descriptions (up from 12 on 2026-08-13).
