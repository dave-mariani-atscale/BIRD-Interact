# v12-noq rule audit (REVIEWERS ONLY - never in a build agent's packet)

Plan: `results/plan_no_questions_labor_certification_20260929.md`. Generator:
`scripts/make_noq_prompt.py` (re-run it from the ADK root to regenerate both files).

## Rule audit — every v12 rule that read questions or gold

| v12 rule (section) | Decision | noq form |
| --- | --- | --- |
| Sources: questions in `bird_interact_data.jsonl` for naming, synonyms, coverage | strip | Sources are schema, meanings, KB, warehouse |
| Firewall: extract permitted question fields into `task_brief.json` | rewrite | `extract_brief_noq.py`: deleted ids only (Query tasks), `noq_gate.py` asserts KB-only strings |
| Masking census: count USE vs DELETE per task | strip | Withhold the brief's deleted set, no census |
| "Gold SQL can contradict its own KB" (wage-unit example) | strip | Gold never read; example was this database's |
| Bare name "from the questions' own vocabulary" | rewrite | From the KB term's name and definition; else the column meaning; else the plain SQL reader |
| Which-object fork (measured on this database's follow-ups) | rewrite | Same rule, generic example; forks found from the model's own inventory |
| Unit viability "on the screen the questions ask for"; gold disagreeing with itself | rewrite / strip | KB's own screen, or the whole population |
| Rendering twins scanned from `amb_user_query` | rewrite | Only where the KB or column meaning names the rendering |
| Enumerated-ladder completion "the question set's wording implies" | rewrite | The KB's wording plus the floor/zero rules |
| Group-by numerics "scan the question set for per X" | rewrite | Every stored score, rate, ratio is groupable |
| Rank twins "at the N the questions use"; rank "for every superlative in the task set" | rewrite | N = 1, 3, 5, 10; every KB score and headline measure |
| Degenerate-date example (this database's dates/status) | rewrite | Generic wording, no figures |
| Builds 18-20: sweep-selected bare name; `gold_diff` [DIAG] | strip | — |
| "Do not publish a reading the simulator named without a $0 regression" | strip | No iteration |
| "Move the plain name onto the reading the questions mean" (5 places) | rewrite | "... the reading the KB's own definition states" |
| Bare-name move decided by a $0 regression sweep | strip | — |
| "Premium ..." / "Firm names ..." / "self-represented" / "specialty-occupation" examples | rewrite | Generic examples (these were this database's) |
| Pre-ship divisions "scan the follow-ups for what percentage" | rewrite | One share per count metric over its natural denominators |
| Collision stated in the question's words; verbatim task term; short question phrase vs A8 | strip | State collisions in the KB's words |
| Build-time discoverability list "the question wordings the task set uses" | rewrite | Paraphrases of KB definitions and column meanings |
| A8 question-leakage gate | replace | `noq_gate.py` (A8 passes vacuously on a question-free brief) |
| Acceptance 3: probes from `amb_user_query` | rewrite | Paraphrases of KB definitions and column meanings |
| Ceiling sweep, ceiling test, population/value ceiling tests | strip | Kept only the engine facts: rank population fixed at build time; window before grouping; shared population |
| After acceptance: reading runs, diagnosing failures, gold/harness defects, spending, steering | strip | Stops at acceptance |

