# Grader review, 2026-09-09: what is left after the six corrections

Scope: every failed submission of the 2026-09-06/07 semantic-layer run on census-achievable tasks (727 at phase 1,
356 at phase 2), classified mechanically against gold (`near_miss` method: shape, row overlap, kind of cell
difference), then re-scored under the six unconditional corrections (timestamp_date, order_requires_cue,
casefold_text, column_order_free, ties_as_ties, numeric_rel_tolerance) by replaying the recorded rows. The question
asked: is any remaining failure class a grading defect rather than an agent or model choice?

## Answer: no class of size remains. One tolerance is available and is not recommended.

| class (phase 1, achievable tasks) | failing submissions | what it is | grader angle |
| --- | ---: | --- | --- |
| values_wrong_1col | 57 | one numeric column differs | **all 57 are far misses** (no `num_near` case survives numeric_rel_tolerance): different formula, basis or population. Model/agent. |
| labels_wrong_1col | 22 | one text column differs | every case is gold's label text - KB band names (`Extreme Cold (<-40C)` vs `Extreme Cold`), CASE labels (`Low`/`Medium` vs `good`), stored reason text - not casing. Model: publish the label text. |
| shape_cols_fewer / more | 44 / 21 | column list differs | agent projection. Model (name the gold shape). |
| extra_columns_only | 23 | gold's columns all present, plus extras | the one grader-level candidate: accepting a superset would flip **6 task-runs across 3 tasks** (cross_border_17, mental_health_16, museum_artifact_8), ~0.5 pt. Not recommended: the question specified the output, both arms face the same rule, and it is a tolerance, not an asymmetry. |
| order_only | 14 | same rows, different sequence | **1 task-run** still fails under the six corrections (sports_events_7, repeat 2). Exhausted. |
| rounding_only (phase 2) | 17 | numbers differ at the rounding level | 9 now pass under numeric_rel_tolerance; the 8 left are exchange_traded_funds_14 (5) and crypto_exchange_4 (3) at phase 2 and need gold rows to diagnose - deferred until the template databases are free. |
| gold_error | 11 | gold fails or returns nothing on the template | hulushows_10 (9 of 9, already a tier-1 candidate); hulushows_7/8/9 are replay timeouts on heavy golds, not defects (hulushows_7 passed 3/3 live). |
| mixed, row_set_*, missing/extra_rows | 174 | several things differ / population differs | agent chose a different population or basis. Model/agent. |

Phase 2 has the same shape (356 failures: values 73, mixed 57, shape 63, labels 32, order 35 of which most were the
ties_as_ties flips) and no additional grader class.

## One latent asymmetry, documented rather than fixed

On the raw path `remove_round` is applied to BOTH the predicted and the gold SQL (`shared/db_utils.py`, the
`ex_base` wrapper); on the semantic-layer path it can only be applied to gold, because the prediction arrives as
rows. A semantic-layer agent that rounds in its query therefore fails where a raw agent that rounds is un-rounded
and passes. It is inert today because the semantic-layer instruction forbids rounding ("Do NOT round in your
submitted query") and 16 of the 17 rounding-class submissions carried no ROUND. It would bite if that instruction
were ever relaxed. The symmetric fix, should it be needed, is to stop un-rounding the raw prediction too - i.e. make
raw obey the same rule - not to guess a rounding for semantic-layer rows.

## What this means for the programme

The grader is no longer where the headroom is. Of the 61 achievable tasks not passing all three repeats, every
remaining failure is a choice the agent made - a formula basis, a population, a label, a column list - and the
lever is the model (names, twins, label text, shape signposts) or the agent's behaviour. The census ceiling for the
semantic-layer arm is 313 of 410; the run stood at 252 always-pass. That gap is model work.

Method note: this review used only the recorded predicted rows and the classifier's summaries, because an A/B
eval was running and gold replays hold connections to the template databases the harness clones per task
(see the harness's `no template queries during a run` rule). The two deferred items above are the only ones that
need gold rows.
