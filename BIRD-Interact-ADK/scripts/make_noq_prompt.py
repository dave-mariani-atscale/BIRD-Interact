"""Derive docs/create_bird_model_prompt.v12-noq.md (+ .audit.md) from v12. Every edit must match exactly once.

Run from the ADK root: python3 scripts/make_noq_prompt.py
"""
import sys

SRC = "docs/create_bird_model_prompt.v12.md"
DST = "docs/create_bird_model_prompt.v12-noq.md"
s = open(SRC, encoding="utf-8").read()


def sub(old, new):
    global s
    n = s.count(old)
    if n != 1:
        sys.exit(f"expected 1 match, got {n}: {old[:80]!r}")
    s = s.replace(old, new)


def block(start, end, new):
    """Replace from `start` (inclusive) to `end` (exclusive)."""
    global s
    i = s.find(start)
    j = s.find(end, i + 1)
    if i < 0 or j < 0 or s.count(start) != 1:
        sys.exit(f"block anchor not unique/found: {start[:60]!r} .. {end[:60]!r}")
    s = s[:i] + new + s[j:]


# --- Firewall -----------------------------------------------------------------------
block("Anything answer-bearing in `bird_interact_data.jsonl` is out of bounds while modeling:",
      "Two working rules that keep the build honest:",
      """**No-questions arm: `bird_interact_data.jsonl` is out of bounds in full.** Not the answer
keys only - the questions too: `amb_user_query`, `follow_up`, `user_query_ambiguity`, the
ambiguity terms, `external_knowledge`, `high_level`, `output_type`. The one permitted touch is
`utilities/extract_brief_noq.py`, which reads each Query record's integer
`knowledge_ambiguity[*].deleted_knowledge` (with `category` used as a filter only) and emits
`brief/noq_brief.json` - the deleted ids plus every KB id whose `children_knowledge` reaches one -
and nothing else. `utilities/noq_gate.py` asserts every string in the brief is a KB entry name.
Model only from the KB, the schema, the column meanings and the warehouse. Gold SQL is never read
in this arm, not even to diagnose a failure.

""")
block("- **`extract_brief.py` drops `deleted_knowledge` by design**",
      "- Derive the withheld set mechanically",
      """- **The deleted ids are in `brief/noq_brief.json`** (`deleted_knowledge`), and
  `depends_on_deleted` lists them plus every KB entry whose `children_knowledge` reaches one.
  The rules in this section decide which of those are actually withheld.
""")
sub("""- Derive the withheld set mechanically from the brief's `deleted_knowledge` ids (the
  extractor may copy that field — it is the tool's own filter input, an integer, not an
  answer), closed over the KB's `children_knowledge` edges,""",
    """- Derive the withheld set mechanically from the brief's `deleted_knowledge` ids,
  closed over the KB's `children_knowledge` edges,""")
block("- **Masking is per TASK; the model is one artifact. Census the cost before building.**",
      "**Select the flags from the KB, not from the task list.**",
      """- **Masking is per task; the model is one artifact.** An id deleted on any Query task is
  withheld from the whole model. This arm takes no per-task census - it would need the task
  list - so it withholds the brief's set and nothing else.

""")
block("**Gold SQL can contradict its own knowledge base. Follow the KB.**",
      "**Apply the counterfactual test to every object",
      "")

# --- Sources --------------------------------------------------------------------------
block("- The natural-language questions in `bird_interact_data.jsonl` (filter on",
      "Do not read any other semantic model on this machine",
      "")
sub("""Application)`). Choose which one is bare from the questions' own vocabulary, not from which
reading is more technically correct.""",
    """Application)`). Choose which one is bare from the KB term's own name and definition; where the
KB is silent, from the column's documented meaning, and failing that the reading a plain SQL
reader of the warehouse writes - not from which reading is more technically correct.""")
block("**Where the ambiguity is *which object*, enumerate your own inventory.**",
      "**A threshold whose unit is ambiguous against the stored column",
      """**Where the ambiguity is *which object*, enumerate your own inventory.** A withheld term
often is not a hidden number at all but a choice between columns the model already publishes
— a standard code, a standard title, and a free-text title recorded for the same thing. There the
model hands the agent a ready-made closed question: name all the candidates in each of their
descriptions, with their distinct counts, and tell the agent to *ask which one*, rather than to
*pick*. That publishes nothing withheld, and it converts an open question into the closed form
that measurably gets a specific answer. Distinguish it sharply from a masked cutoff, where naming
the candidate values would be a leak. Find these from the model's own inventory: every everyday
noun two or more published columns can answer is one.

""")
sub("non-degenerate subset, judged on the screen the questions ask for.",
    "non-degenerate subset, judged on the KB's own screen, or over the whole population where the KB\nnames none.")
block("Gold is not a tiebreak here and can disagree with itself:",
      "**Two ways to break a unit tie, in order.**",
      "")
block("**A rendering the question set asks for is coverage, and it ships as a named twin.**",
      "**Two columns that look like two readings may be one recorded value",
      """**A rendering ships as a named twin only where the KB or the column meaning names it.** Where
the KB or a column's documented meaning states how a value is written ("stored in upper case",
"rounded to two decimals", "as recorded on the form"), publish `<Attribute> (<Rendering>)`
beside the recorded one, and have the **bare** attribute say the twin exists and route the
choice to the user. Otherwise ship the recorded value alone - a rendering nothing in the sources
names is a guess.

""")
sub("""whatever reading the question set's own wording implies — named asymmetrically,""",
    """whatever reading the KB's own wording implies (and the floor and zero rules below) — named
asymmetrically,""")

# --- Modeling rules -------------------------------------------------------------------
sub("""queryable attribute as well as a measure.** Scan the question set for "per X" / "by X" /
  "for each X" over stored scores, rates and ratios.""",
    """queryable attribute as well as a measure.** Treat every stored score, rate and ratio as
  something a caller may group by ("per X" / "by X" / "for each X").""")
sub("""it. Sweep for this at build time: for every indicator column on a dataset finer than an
  entity the model also names, "entities with at least one such row" is a question the task
  set will ask, and its absence is silent""",
    """it. Sweep for this at build time: for every indicator column on a dataset finer than an
  entity the model also names, "entities with at least one such row" is a natural question,
  and its absence is silent""")
sub("""DENSE_RANK` — different row sets whenever values tie. Check the live data at the N the
  questions use;""",
    """DENSE_RANK` — different row sets whenever values tie. Check the live data at N = 1, 3, 5
  and 10;""")
sub("""- Where the two agree in the live data — no ties at the N the questions use — ship only one.""",
    """- Where the two agree in the live data — no ties at any of those N — ship only one.""")
sub("""  superlative in the task set reaches for.**""",
    """  KB score and headline measure a superlative could reach for.**""")
sub("""  live at a measured coefficient of about −0.05 — that is, effectively never. The ceiling sweep
  recorded a pass and the live score would not have. So sweep your own objects for the shape
  before shipping:""",
    """  live at a measured coefficient of about −0.05 — that is, effectively never. So sweep your own
  objects for the shape before shipping:""")
sub("""  one beside it, and do not assume a sweep pass through a qualifier is a pass.""",
    """  one beside it.""")
sub("""  trivial and every sort by it fully tied. Observed: receipt and decision dates were one value
  each, so every processing time was the same 8 days; every application carried the same status,
  so every approval rate was 100%. Say so""",
    """  trivial and every sort by it fully tied: two constant dates make every duration between them
  one value, and a constant status makes every rate over it 0% or 100%. Say so""")
sub("""  complement selected **0**. Where the questions supply their own reference date, ship the raw
  date and let the caller subtract;""",
    """  complement selected **0**. Ship the raw date so a caller with their own reference date can
  subtract;""")
block("- **Decided 2026-09-26 for builds 18–20: a reading the $0 ceiling sweep selects takes the bare",
      "- Any measure computed over a subset of rows must expose its support set",
      "")
block("- **Do not publish a reading only because the simulator named it without a $0 regression",
      "- **Every LIVE key is pinned before the first deploy.**",
      "")

# --- Definitions and naming ---------------------------------------------------------------
QMEAN = "the reading the questions mean"
KBMEAN = "the reading the KB's own definition states"
n = s.count(QMEAN)
s = s.replace(QMEAN, KBMEAN)
print(f"replaced {n}x '{QMEAN}'")
sub("""  onto the reading the questions mean and push every other behind a qualifier.""".replace(QMEAN, KBMEAN),
    """  onto the reading the KB's own definition states (where the KB is silent, the plain SQL
  reader's reading) and push every other behind a qualifier.""")
block("- **The bare-name move is per family, and a $0 regression sweep decides it before deploying.**",
      "- **A generated \"when grouped by <column>\" clause",
      "")
sub("""  user.** Learned twice on one model, both self-inflicted, both costing tasks: "Premium means the
  position pays well relative to what is required", added to satisfy a discovery phrase, told the
  agent to answer a *different* KB concept's question with this attribute, and it did, returning 60
  where the caller's threshold gave 33; "Firm names are stored with mixed capitalisation … collapse
  casing yourself if one row per firm is required" produced exactly that `GROUP BY UPPER(…)`, and
  the reference does not merge casing, so the whole top-five changed.""",
    """  user.** Learned twice on one model, both self-inflicted, both costing tasks: a gloss added to
  satisfy a discovery phrase told the agent to answer a *different* KB concept's question with the
  attribute, and it did; and "names are stored with mixed capitalisation … collapse casing yourself
  if one row per entity is required" produced exactly that `GROUP BY UPPER(…)`, which changed the
  whole top-five.""")
sub("""its conditions ("a statistically significant number of applications"), ship the components and no
  flag""",
    """its conditions ("a statistically significant number of records"), ship the components and no
  flag""")
sub("""Scan the follow-up questions for "what percentage / what share / what proportion" and
  ship one calculation per answer shape — on one database that was 13 of them, and most phase-2
  follow-ups were of this form.""",
    """Ship one share calculation per count metric over its natural denominators — on one database
  that was 13 of them, and most follow-up questions were of this form.""")
sub("""  ("the employer is *self-represented*"), use that string; a synonym you preferred ("Not
  Represented")""",
    """  ("the account is *self-managed*"), use that string; a synonym you preferred ("Not
  Managed")""")
sub("""**a hyphen** ("specialty-occupation" does not match "specialty
  occupation")""",
    """**a hyphen** ("cross-border" does not match "cross
  border")""")
block("  - **Stating a vocabulary collision in the question's own words is itself a leak, so state it in",
      "  - **An acronym in parentheses reads as a cross-reference.**",
      """  - **State a vocabulary collision in the KB's words.** Write it from each concept's own KB
    definition and let the reader match their phrase themselves.
""")
block("**A question phrase too short for the leakage gate still chooses for the caller.**",
      "**Say when a twin pair is NOT a fork, or the agent pays to ask.**",
      "")

# --- Build process ------------------------------------------------------------------------
block("- **Assert discoverability at build time, not only at acceptance.**",
      "- **A discoverability gate that *requires* phrases can enforce a leak.**",
      """- **Assert discoverability at build time, not only at acceptance.** Keep a list of
  paraphrases of every KB definition and column meaning (the KB's own terms, their plurals, a
  passive and an unhyphenated form) and fail the build if any matches no published description.
  The check must **parse the emitted YAML and normalise whitespace** — `safe_dump` line-wraps
  long descriptions at column 100 and the consumer sees the folded value, so grepping raw file
  text reports false failures on phrases that are in fact present. Probe the *deployed* model
  with the same phrases too.
""")
sub("""- **A gate that cannot find its brief does not run, and nothing says so.**""",
    """- **In this arm the A8 question-leakage gate is replaced by `utilities/noq_gate.py`**, which
  asserts the brief holds only KB names and ids, no model file names a question field, and no
  emitted description uses a word a semantic layer cannot know. A8 would pass vacuously here.
- **A gate that cannot find its brief does not run, and nothing says so.**""")

# --- Acceptance -----------------------------------------------------------------------------
sub("""3. **Discoverability.** Search the deployed model with question-style paraphrases only, never an
   object's own name — take the probe phrases from the task briefs' own `amb_user_query` wordings;
   the intended object must surface.""",
    """3. **Discoverability.** Search the deployed model with paraphrases of KB definitions and column
   meanings only, never an object's own name; the intended object must surface.""")
block("**A ceiling sweep is cheap enough to ITERATE, and rounds two and three are where it pays.**",
      "**A published rank's population is fixed at build time",
      "")
sub("""same probe that found this showed the escape reaching an exact match against gold.""",
    """escape re-ranks correctly.""")
block("**A population rule stated as a sentence does not fire; the same rule stated as an ASK does.**",
      "**A caller's window function is applied BEFORE",
      """**Figures shown together share one population.** A plain SQL reader reaches each figure through
its own record and keeps only the rows where every record it read exists, so a listing or a group
aggregate pairing values from two records is computed over the INTERSECTION of their populations,
never over each column's own. Ship one coverage flag per record, put the rule in the model
description, and repeat it on every average that could be paired with another.

""")
block("**Ceiling-test the VALUE pipeline, not only the query shape.**",
      "## After acceptance",
      "")
i = s.find("## After acceptance")
s = s[:i] + """## After acceptance — none in this arm

The no-questions arm stops at acceptance. There is no ceiling sweep, no `gold_diff.py`, no
failure review and no iteration against the benchmark: each of those targets the task set by
construction. The model is deployed as accepted and measured once. A later, separately measured
step may tune against questions the builder wrote itself from the KB (plan 7a); that step never
reads the benchmark's questions either.
"""


sub("""  a shared clause. Where a permitted question states a constant, that is confirmation of the
  standard value, not a licence to fit.""", """  a shared clause.""")

AUDIT = '## Rule audit — every v12 rule that read questions or gold\n\n| v12 rule (section) | Decision | noq form |\n| --- | --- | --- |\n| Sources: questions in `bird_interact_data.jsonl` for naming, synonyms, coverage | strip | Sources are schema, meanings, KB, warehouse |\n| Firewall: extract permitted question fields into `task_brief.json` | rewrite | `extract_brief_noq.py`: deleted ids only (Query tasks), `noq_gate.py` asserts KB-only strings |\n| Masking census: count USE vs DELETE per task | strip | Withhold the brief\'s deleted set, no census |\n| "Gold SQL can contradict its own KB" (wage-unit example) | strip | Gold never read; example was this database\'s |\n| Bare name "from the questions\' own vocabulary" | rewrite | From the KB term\'s name and definition; else the column meaning; else the plain SQL reader |\n| Which-object fork (measured on this database\'s follow-ups) | rewrite | Same rule, generic example; forks found from the model\'s own inventory |\n| Unit viability "on the screen the questions ask for"; gold disagreeing with itself | rewrite / strip | KB\'s own screen, or the whole population |\n| Rendering twins scanned from `amb_user_query` | rewrite | Only where the KB or column meaning names the rendering |\n| Enumerated-ladder completion "the question set\'s wording implies" | rewrite | The KB\'s wording plus the floor/zero rules |\n| Group-by numerics "scan the question set for per X" | rewrite | Every stored score, rate, ratio is groupable |\n| Rank twins "at the N the questions use"; rank "for every superlative in the task set" | rewrite | N = 1, 3, 5, 10; every KB score and headline measure |\n| Degenerate-date example (this database\'s dates/status) | rewrite | Generic wording, no figures |\n| Builds 18-20: sweep-selected bare name; `gold_diff` [DIAG] | strip | — |\n| "Do not publish a reading the simulator named without a $0 regression" | strip | No iteration |\n| "Move the plain name onto the reading the questions mean" (5 places) | rewrite | "... the reading the KB\'s own definition states" |\n| Bare-name move decided by a $0 regression sweep | strip | — |\n| "Premium ..." / "Firm names ..." / "self-represented" / "specialty-occupation" examples | rewrite | Generic examples (these were this database\'s) |\n| Pre-ship divisions "scan the follow-ups for what percentage" | rewrite | One share per count metric over its natural denominators |\n| Collision stated in the question\'s words; verbatim task term; short question phrase vs A8 | strip | State collisions in the KB\'s words |\n| Build-time discoverability list "the question wordings the task set uses" | rewrite | Paraphrases of KB definitions and column meanings |\n| A8 question-leakage gate | replace | `noq_gate.py` (A8 passes vacuously on a question-free brief) |\n| Acceptance 3: probes from `amb_user_query` | rewrite | Paraphrases of KB definitions and column meanings |\n| Ceiling sweep, ceiling test, population/value ceiling tests | strip | Kept only the engine facts: rank population fixed at build time; window before grouping; shared population |\n| After acceptance: reading runs, diagnosing failures, gold/harness defects, spending, steering | strip | Stops at acceptance |\n\n'
HEADER = """# Prompt: build an AtScale semantic model for a BIRD-Interact database — NO-QUESTIONS arm (v12-noq)

**What this arm is.** The v12 build process with every input that comes from the benchmark's
task set removed: no question text, no gold, no task-targeted iteration. It measures how much of a
v12 model's lift comes from building with the questions in mind. Derived mechanically from
`create_bird_model_prompt.v12.md` by a replacement script.

**Questions were used historically to discover generic rules; the rules stay, the per-database
targeting goes.** The modeling rules, engine constraints, value pipeline, `birdsml` shared emitter
and `birdsml.ENGINE_NOTES` are unchanged, because they are facts about the interface identical for
every arm. What is gone is every instruction that reads this database's questions or gold.

**Where the model goes (overrides "Where the model goes" below).** Repo
`AtScaleInc/bird-atscale-models`, branch `no-questions` (worktree `../bird-atscale-models-noq`),
catalog `bird_models_noq`, model name `<Db Title> NoQ`. The branch holds only this arm's
databases; the tuned models live on `main` and are out of bounds, as is their history.

**Sources, complete list:** `<db>_schema.txt`, `<db>_column_meaning_base.json`, `<db>_kb.jsonl`,
the live warehouse, and `<db>/brief/noq_brief.json` (deleted KB ids only), plus the one v12
`spec.py` of a DIFFERENT database your packet names as a format reference for the `birdsml` spec
API (read it for shape, never for content). Nothing else - no other semantic model, no `results/` write-up, no change-log entry, no kickoff, no memory note about an
earlier build of this database.

**Rule audit.** The keep/strip/rewrite decision for every v12 rule that read questions or gold
is in `docs/create_bird_model_prompt.v12-noq.audit.md`. That file is for reviewers only: it names
which v12 examples came from which database, so **no build agent opens it**.

**Kept on purpose, although learned from questions or gold on other databases:** every other rule,
with its measurement. They are generic lessons about the interface and about plain-SQL readers;
dropping them would change the process being compared, not just its inputs.

**Also changed outside this prompt:** the brief extractor and the A8 replacement live in the
branch's `utilities/`; `utilities/` is v12's (`diannewood/bird-models-v12` at `7881d16`), so the
emitter and ENGINE_NOTES match build 18 exactly.

---

"""
i = s.find("# Prompt: build an AtScale semantic model for a BIRD-Interact database\n")
s = s[:i] + HEADER + s[i + len("# Prompt: build an AtScale semantic model for a BIRD-Interact database\n"):]

open(DST, "w", encoding="utf-8").write(s)
open(DST.replace(".md", ".audit.md"), "w", encoding="utf-8").write(
    "# v12-noq rule audit (REVIEWERS ONLY - never in a build agent's packet)\n\n"
    "Plan: `results/plan_no_questions_labor_certification_20260929.md`. Generator:\n"
    "`scripts/make_noq_prompt.py` (re-run it from the ADK root to regenerate both files).\n\n" + AUDIT)
print("wrote", DST, len(s.splitlines()), "lines")
