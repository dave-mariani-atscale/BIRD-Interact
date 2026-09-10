# Wall-clock by outcome: why total elapsed penalises the arm that passes more, and what to report instead (2026-09-09)

## The finding

The results workbook compared arms on mean `elapsed_seconds` per task (Summary columns BB/BC).
Measured on the last full runs (AtScale 3 repeats 2026-09-06/07, raw 3 repeats 2026-09-08, about
1,230 task-runs per arm) with every second attributed to the agent turn that produced it, from the
per-turn timestamps in `logs/system_agent.out`:

| Component (s per task-run)                         | AtScale | Raw   | Gap    | Share of gap |
|----------------------------------------------------|--------:|------:|-------:|-------------:|
| Phase 2 work (only tasks that pass phase 1 get here) | 31.9  | 4.8   | +27.1  | 47%  |
| Phase 1 query-writing turns                          | 52.1  | 40.8  | +11.3  | 20%  |
| Phase 1 submit turns                                 | 23.4  | 13.2  | +10.1  | 18%  |
| Phase 1 ask_user turns                               | 29.2  | 21.5  | +7.7   | 13%  |
| Phase 1 recovery after a query error                 | 2.7   | 1.5   | +1.2   | 2%   |
| Phase 1 discovery                                    | 28.0  | 28.5  | -0.4   | -1%  |

AtScale reached phase 2 in 65% of task-runs, raw in 30%. Almost half of the elapsed gap is the
extra phase of work the passing arm does. Total elapsed per task therefore penalises the arm that
answers more questions correctly.

Engine-attributable time is small: recovery after all run_query errors is 2.8 s per task-run
(226 errors in 4,713 queries; engine defects with fixes on the branch account for 0.7 s), submit-time
engine failures under 0.3 s, and a dialect shape premium (derived tables, nesting) of about 0.8 s by
regression over 4,713 query turns. Engine execution latency is a saving, not a cost (run_query median
0.13 s against 5.3 s for execute_sql on the raw Postgres). The remaining per-query difference is
thinking time (18.0 s per query-writing turn against 8.4 s, holding even for flat single-SELECT
queries), which is model reasoning about named measures, calculations and dimension twins.

## What the sheet reports now

`Summary 09-07  Sonnet 5` gained a **TIME PER REWARD POINT** section (columns CD-CF):

* CD `AtScale s per reward point` = BB/AI (mean wall-clock per question / mean reward per question)
* CE `Raw s per reward point` = BC/AK
* CF `Time lift (x cheaper)` = CE/CD
* ALL row pools the 410 questions: SUMPRODUCT(wall-clock, Qs) / SUMPRODUCT(reward, Qs).

On the 09-06/09-08 runs: AtScale 280 s per reward point, raw 347, lift 1.24x. Per-task elapsed on the
same runs read 176 s against 115 s, which is the number that had reversed the trend.

## What the harness records now

* `system_agent/tools.py` `submit_sql` stamps `phase1_completed_at` (and `phase2_completed_at`) into
  session state when a phase passes.
* `orchestrator/ainteract.py` writes `phase1_elapsed_seconds`, `phase2_elapsed_seconds` (None unless
  phase 1 passed and a follow-up exists) and `phase1_completed_at` on every task result.
* `orchestrator/runner.py` `metrics` carries `elapsed_seconds_mean`, `seconds_per_reward_point`,
  `phase1_elapsed_seconds_mean`, `phase2_reached_count`, `phase2_elapsed_seconds_mean_reached`.
* `scripts/summarize_runs.py` prints a "3b. TIME" table with the same numbers per arm; runs recorded
  before the stamp show `n/a` for the phase split.

The per-turn attribution scripts used for the table above (log gap extraction, error census,
shape regression) live in the session scratchpad `engine/` directory and are not part of the harness.
