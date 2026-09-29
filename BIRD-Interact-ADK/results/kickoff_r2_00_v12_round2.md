# ROUND 2 — retrofit the newer process onto the 19 v12 models built before it

Decided by Dianne 2026-09-27. Backup of the pre-round-2 state:
`~/go/src/github.com/diannewood/bird-models-v12-backup-20260927_pre_r2` (at `46403da`).

## WHAT THIS IS

Builds 18-20 (labor_certification_applications, cybermarket_pattern, cold_chain_pharma_compliance)
were built under a process the first 19 models never saw. This pass retrofits that process onto the
other 19. **It is an UPDATE, not a rebuild.** Do not regenerate a model from scratch, do not restate
its spec, do not re-derive its datasets. Change only what the newer rules require, and leave
everything else byte-identical.

The goal, stated as a test: **the updated model should look like what the build would have produced
if the newer rules had been in force on its build date.**

## HARD CONSTRAINTS

- **$0. There are NO benchmark API credits.** No `run_evaluation`, no agent run, no paid arm, no
  `--repeat`, nothing that bills `ANTHROPIC_API_KEY`. Every measurement in this pass comes from
  `scripts/gold_diff.py` (MCP + Postgres only) and from hand-written SQL. If you find yourself
  wanting a paid run, write the question down in the report instead.
- **ANSWER-KEY FIREWALL.** Gold is read ONLY through `scripts/gold_diff.py`. Forbidden by PATH:
  `bird-interact-full/bird_interact_data.jsonl`, the keys `sol_sql`, `follow_up.sol_sql`,
  `sql_snippet`, `test_cases`, `conditions`, `preprocess_sql`, `clean_up_sqls`, and
  `results/bird_full_run_*/results/grading_audit_this_run.jsonl`. Gold SQL never enters the model:
  not its text, not a fragment, not a paraphrase of its construction — in no description, name,
  dataset SQL or spec comment.
- **You do not commit, push, deploy, or touch git.** The session does that centrally, because the
  deploy publishes the WHOLE catalog and every model goes out together. Leave your work as
  uncommitted changes in your own model folder.
- **You touch ONE model folder.** Never another model's folder, never `catalog.yml`, never
  `utilities/`. Other agents are working in parallel in the same repo; a repo-wide validate may show
  errors from their half-finished folders — ignore anything outside your own model.
- Never write to `<db>_template`. Never `source` the ADK `.env` — grep the one variable you need.
- Edits go in `generator/spec*.py`, never in the emitted YAML. A regenerate silently reverts a
  hand-edited YAML.

## THE NEWER LOGIC — the checklist to retrofit

**SUPERSEDED 2026-09-29 (Dianne): no model change may be motivated by `gold_diff` output.** Not a `[DIAG]` change, not a RENAME TO PLAIN settled by a sweep, not an ask or companion sentence whose options or columns were found by diffing against gold, not an object published because gold passes on it. Those are findings 2 and 3 of `results/v12_cheating_review_20260928.md`, and every round-3 change of that kind was reverted the same day. `gold_diff` MEASURES (sweeps, verdicts, ceilings); a model change must be derivable from the KB, the warehouse and the agent's trajectory alone, and its commit must say which of those motivated it. Sections 1, 2 (where a sweep settles the fork) and 3 below no longer apply.

### 1. RENAME TO PLAIN  (tag `[PLAIN]`)
Where a ceiling-sweep round shows the **bare** reading failing and an already-PUBLISHED twin
passing — both derived from the KB and the warehouse — **rename so the passing reading is bare.**
The losing reading keeps a qualifier naming what narrows it; the bare description names it with both
live counts; **no ask is generated for that pair.** Do not add a new object for this and do not write
any gold-derived text. Withheld composites and renderings that appear only in reference SQL stay out.

E-22 trap: renaming which reading owns the plain name leaves stale cached aggregates behind. **Rename
the entity's degenerate dimension in the same commit** (e.g. `Record` -> `Entry`). An engine restart
does NOT clear it.

### 2. UNSETTLED FORKS ARE ASKS  (tag `[PLAIN]`)
A fork the sweep CANNOT settle ships an `ask_user` closed question. It does **not** ship as a pair of
differently-named twins with the choice left to the agent. Three kinds qualify:
  (a) a numeric parameter the KB does not state — weights, cutoffs, thresholds, a scale — where the
      reference clearly used one and nothing published derives it;
  (b) a population narrowing that no published reading reproduces;
  (c) the graded axis — shape (which columns), label text, order.
An ask targets the graded axis, **never a reading choice the sweep settled**.
**Before you finish, grep the EMITTED YAML for asks and cut every instance that is a reading choice
the sweep settled.** Then list, in your report, every fork the sweep could not settle and the ask
that ships for it. A fork with no ask needs a real written reason (the KB does state it, or the axis
is ungraded). "Shipped as a twin" is not a reason.
Counter-rule (households, 2026-09-26): **a model's own forks spend the agent's asks.** Where the
references are plain SQL over the recorded value, the recorded value is the ONE reading of a
grouping/location column — delete the merged/folded twin and its ask rather than shipping both. An
ask whose answer never varies is a fact: state it. Budget is about two asks per task.

### 3. GOLD_DIFF DIAGNOSIS IS ALLOWED  (tag `[DIAG]`)
`scripts/gold_diff.py` may be run on any failing task, and what it prints (verdict, shape, row and
column counts, column order, differing cell values and labels, rounding) MAY inform a model change.
The old "switching your formula to match gold is answer-fitting" rule is suspended. The firewall on
gold SQL is not. A change the diagnosis motivates is still written as KB + warehouse columns plus a
convention stated in the KB's words, and no description says why a reading was chosen.
A COLUMN COUNT finding is not "caller projection, no model gap": put a companion-column sentence on
the projected object naming the columns gold prints and their live values, plus a shape ask.

### 4. Modelling rules added after this model's build date  (tag `[KB]`)
Apply the ones that bite. Check the build date in the ledger against when each rule landed:
- **Anchor age/recency to the data's own latest timestamp, never `NOW()`/`CURRENT_DATE`.** Grep the
  spec for `NOW()`, `CURRENT_DATE`, `CURRENT_TIMESTAMP` and fix every one that ages a record.
- **Keep a KB formula in the unit the KB writes it in.** No helpful conversion.
- **A never-stored input's concept is published NULL** where the KB says null means undetermined —
  only a published attribute can return "nothing".
- **A KB label ladder that matches no stored value may mean the raw value itself.** Publish the score
  bare and narrow the band-limits question to an ask.
- **A flag's SQL must match its own text**; a KB-less status label is an ask.
- **Figures shown together share one population** — the intersection, one coverage flag per record.
- **Descriptions that choose for the caller are the defect to hunt.** Grep the EMITTED YAML for
  imperative verbs (`Filter `, `Use `, `Show `, `Prefer `). A population sentence names the EXACT column.
- **Emit twin-naming sentences from a generated pass**, not by hand per object; every bare reading's
  description carries its twin's NAME and both live counts.
- **Count the nulls on every published Yes/No attribute**; a verdict flag null on more rows than it is
  non-null is a build failure.
- **Every LIVE key is pinned before deploy** — grep the emitted YAML for `(?` and fill from dataset SQL.
- **Signpost withheld concepts** in the model description: name which published columns are their
  inputs and say that searching the concept name returns nothing.
- **Do not publish an ordering this model invented.** State the convention in the formula's prose.
- **Lead every count metric with its population rule**; a satellite label's null is the absent record,
  not a group; ship one closed question on a Total/Average pair.

### 5. SWEEP STALL RULE
A sweep round that adds NO new pass ends the round-2 phase for that database. Do not run another
round against the same decision table. Write the unresolved findings into the report and stop.

## THE RECIPE

1. **Read first, at $0.** Your database's `results/kickoff_NN_<db>_v12.md`, its
   `results/<db>_v12_pass_*.md` (especially the cap list and any `R2-NN` deferred-lever rows), and
   its ledger row in `results/kickoff_00_v12_order.md`. The pass report's cap list tells you which
   failures were judged model-fixable and which were gold-bound — do not re-litigate a gold-bound cap.
2. **Baseline sweep against the CURRENTLY DEPLOYED model.** Reuse the build's final round file if one
   survived under `results/` (see the list your prompt gives you); otherwise write the ceiling queries
   yourself from the published objects. Two files: **full ceiling** (any published object, asks
   allowed to be answered as a human would) and **bare-name ceiling** (bare-named objects only, no
   ask). Run both for P1 and, where the build had one, P2:
   `PG_MAXCONN=60 .venv-adk/bin/python scripts/gold_diff.py --sweep <file>.json --phase 1|2 --backend atscale`
   Record both counts. This is your BEFORE.
3. **Diagnose every FAIL** with `gold_diff.py`. Classify each: sweep-settled fork (-> rename to
   plain), unsettled fork (-> ask), a rule from section 4 (-> fix), or a cap (-> leave it, say why).
4. **Edit `generator/spec*.py`** and rebuild:
   `PYTHON=<ADK>/.venv-adk/bin/python bash <db>/generator/build.sh`
   If step 6's repo-wide validate fails on ANOTHER model, ignore it; yours must be clean.
5. **Stop there and report.** The session deploys the whole catalog, then sends you back for the
   AFTER sweep. Do not deploy.

## DELIVERABLE (your final message — keep it under 60 lines)

- BEFORE: full ceiling P1 n/N, bare-name ceiling P1 n/N, P2 n/N.
- Every change you made, one line each, tagged `[PLAIN]` / `[DIAG]` / `[KB]`.
- Every fork the sweep could not settle, and the ask that ships for it (or the written reason none does).
- Ask count before -> after. Twin count before -> after.
- What you did NOT change and why (caps, gold-bound rows, rules that do not bite here).
- Anything that needs Dianne.

## RULINGS MADE DURING THIS PASS — read these, they were not in the original recipe

**RULE ORDERING: the sweep owns the NAME, the KB owns the ARITHMETIC.** planets_data hit a real
conflict — RENAME TO PLAIN says the sweep-settled reading takes the bare name, and "keep a KB formula
in the unit the KB writes it in" says the KB's unit wins. They do not actually collide: the unit rule
governs a formula's internal arithmetic (do not convert mid-formula, the way cold_chain's MKT stays
in Kelvin because KB 26 writes it in Kelvin), and RENAME TO PLAIN governs which of two PUBLISHED
readings owns the bare name. Publish the KB-unit reading as a twin and let the sweep decide which is
bare. On planets_data the sweep settles km/s over m/s five phases to zero, so km/s takes the name.

**`birdsml.ENGINE_NOTES` HAS GROWN and now eats the 7000-character model-description budget.** It is
appended to every v12 model description and has gained roughly 580 characters since 2026-09-25, which
is enough to fail the gate on a model that was comfortably inside it at build time. If your build
fails that gate, cut prose duplicated elsewhere in your own description. Never cut the
population/intersection rule, the withheld-concept signpost, or a named engine fact. Say in your
report how many characters you gave up. This is a programme-level problem, not a per-model one —
the session is tracking it.

**A THRESHOLD THE SWEEP CANNOT SETTLE IS NOT AUTOMATICALLY AN ASK.** sports_events found the
distinction and it matters: if sliding the cutoff moves the row count but a fixed core of gold rows
NEVER appears at any threshold, the fork is not a cutoff at all — it is a different basis, and a
user's answer to a cutoff question would not be actionable. Test it before shipping the ask, and if
the core-rows test fails, record it as a cap with the evidence instead.

**THE ANSWER-FITTING LINE, ruled for this pass.** Dianne's GOLD_DIFF DIAGNOSIS ALLOWED decision was
written for builds 18-20; this pass extends it to the 19 retrofits, because the instruction is to
apply the newer logic to them. Under it, searching candidate populations with `gold_diff` until a
value matches IS permitted. The test is not how the reading was FOUND, it is whether the reading is
derivable from the KB and the warehouse and stands on its own once written. mental_health `_13` meets
it — the every-facility CRAA is the existing `(Unrated As Zero)` rule extended to the second series,
and it reads correctly with no reference to gold. What stays forbidden is unchanged: gold SQL in any
form, and a description that says why a reading was chosen. Flagged to Dianne as a session judgment,
not presented as her decision.

**HARNESS TRAP, found on mental_health 2026-09-27: `gold_diff --backend raw` and direct psql can
return DIFFERENT answers for byte-identical SQL** — 18.14 against 5.38 on one task. The per-task
database is a template clone with the task's preprocess step applied, which the plain database does
not have. So direct psql exploration is unsafe for any task carrying a preprocess step, and nothing
warns you. Trust `gold_diff`; use psql only to understand the schema, never to settle a value.

**PAID EVIDENCE OUTRANKS A $0 SWEEP WHEN CUTTING AN ASK (ruled 2026-09-27, from robot_fault_prediction).**
RENAME TO PLAIN says a fork the sweep settles gets a rename and no ask. That is right for a fork with
no paid history. It is WRONG where the ask is recorded as a MEASURED converter in a paid run: the
sweep settles a fork for a human hand-writing SQL, and proves nothing about whether the live agent
picks the bare name. robot_fault_prediction's urgency and RUL asks were the measured converters for
`_1` and `_5` in the 2026-09-18 build, and the $0 sweep cannot see that. So: do the rename AND keep
the ask, wherever a paid run recorded that ask converting. Cut only asks with no paid evidence. The
asymmetry is deliberate — a kept ask costs one coin, a cut ask that was carrying a task costs the task.

**AN ENGINE-CAPABILITY CLAIM IS VERIFIED BEFORE IT IS PROPAGATED (2026-09-27).** Two claims that had
reached the shared notes and the build prompt were false: `NTILE` is accepted (the notes said it was
refused in any spelling) and a window column CAN be filtered in HAVING after a GROUP BY (the notes
said the reverse). Both were disproved with one query each against the live catalog. A third, "string
aggregation is not accepted in any spelling", was corrected on 2026-09-25 but still sits in one
deployed model description. Before writing "the engine refuses X" anywhere, run X.
