# Prompt: build an AtScale semantic model for a BIRD-Interact database

**How this prompt was made.** Distilled from six full build-and-refine cycles — the
`exchange_traded_funds` prompt-only build (`create_etf_prompt.txt` plus every post-build
fix recorded in `docs/model-change-log.md`), the `solar_panel` build log (initial prompt
plus the defects found by live evaluation), the `cybermarket_pattern` build, the first
to use this prompt rather than an ad-hoc one and therefore the first real test of it,
and the `labor_certification_applications` build of 2026-08-13/15, the first taken
through four measured evaluation rounds to a settled result, and the `crypto_exchange`
build of 2026-08-14/17, whose defects were found by reading outbound SQL and live query
failures — plus the ETF evaluation work of 2026-08-13/14, which measured what model
fixes are actually worth, and the `cross_border` rebuild of 2026-08-20 — the first
time a model already in the catalog was replaced rather than extended, which is what
exposed three of its design premises as wrong. Each rule traces to a concrete,
observed failure;
database-specific details and anything derived from gold SQL were stripped. This file
supersedes `create_etf_prompt.txt`; the modeling rules are also mirrored in the MCP
`sml-create-metric` skill — propagate new lessons to both.

Replace `<db>` throughout (e.g. `exchange_traded_funds`, `solar_panel`).

**What changed in this revision (`cross_border` rebuilt from scratch, plus a repo-wide
warnings cleanup, 2026-08-20).** Seventeen rules. The rebuild was the first time a model
already in the catalog was replaced rather than extended, which is what surfaced most of
these: three of its design premises were wrong in ways only a fresh measurement catches.
Listed so each can be reviewed or reverted independently. Three are corrections to rules
already here.

1. **New**: two columns that read like independently-recorded versions of one concept may
   hold the *identical* value wherever both are present. Measure that before shipping
   twins — three such pairs in one schema turned out to be denormalised copies, and the
   previous build had shipped competing readings for them (Sources).
2. **New**: a KB formula that enumerates its input's values can be silently incomplete,
   and completing it with NULL drops that whole slice out of every answer built on the
   formula — a quarter of the population, in the observed case (Sources).
3. **Correction**: a `NOW()`-based column is not automatically safe. Profile it for
   degeneracy against the benchmark's own calendar first; one such flag selected 240 of
   240 rows and its complement selected 0 (Grain and time).
4. **New engine constraint**: several degenerate dimensions built on one `dataset` +
   `key_columns` pair are rejected outright, and the themed-profile pattern that produces
   them is *the same* heading-selection liability this prompt already names — so merging
   them pays twice (Engine constraints, Modeling rules).
5. **New engine constraint**: a dimension over the model's only fact dataset must be
   declared `is_degenerate: true`, and the model file still requires a `relationships:`
   key even when there is nothing to relate (Engine constraints).
6. **New**: `atscale-deploy` runs `validate` first, so a validation error *anywhere* in a
   shared repo is reported as a deploy failure that never mentions validation (Engine
   constraints).
7. **New**: the CLI and the web UI disagree about the latest SML version. The CLI is what
   deploys, so the repo declares the CLI's number (Engine constraints).
8. **New**: warnings are not free. A repo that prints a hundred of them has trained
   everyone to ignore its output, and the two that mattered were buried in the noise
   (Build process).
9. **New, and the highest-leverage change of this round**: put a rule in the shared
   emitter, not in twelve generators. One 160-line pass fixed twelve models; the same fix
   hand-propagated would have been twelve edits across 39,000 lines (Build process).
10. **New**: a mechanical rename that picks its target from *inside* the group it is
    merging inherits one member's identity and mislabels the rest. Derive the name from
    something outside the group (Build process).
11. **New**: verify a mechanical refactor by diffing the **queryable surface**, not file
    or line counts. A naive `unique_name` count read as a 21-object loss where the true
    loss was zero (Acceptance).
12. **New**: a cross-model refactor invalidates in-flight comparisons across every model
    it touches. Say so when you land one (After acceptance).
13. **Correction**: the answer-key firewall's own SQL detector must test for SQL
    *structure*, not for keywords. A bare prose keyword is not a leak signal — the phrase
    "join type" is a natural-language ambiguity label in at least one task set
    (Answer-key firewall).
14. **Correction**: the KB triage that Block 4 asks for by hand should be **mechanical**.
    Exempt text appearing verbatim in a KB field and the gate stops flagging correct
    models (Build process).
15. **New**: read the deployed model's folder count back from `list_models`.
    `folders: (none)` is a visible symptom of a model with no cheap discovery channel at
    all, and it went unnoticed through a whole evaluation round (Acceptance).
16. **New**: check the repo's prevailing `unique_name` convention before authoring. A
    catalog can drift, and a model that drifted alone is invisible until someone counts
    (Keys, identity, and naming).
17. **New**: the interpreter belongs in the pre-run environment check. Two scripts in one
    repo disagreed about which `python` to use, so the services ran healthily for hours
    while the runner died instantly on a missing dependency (After acceptance).

**What changed in v6 (evaluation sweep of all eight deployed models,
2026-08-18/19).** Ten rules, from a three-run head-to-head across every deployed
database plus eight single-model runs testing fixes. Listed so each can be reviewed or
reverted independently. Two are corrections to rules already here, not additions.

1. **New**: a dimension's `unique_name` is what `explore_columns` prints as a `## `
   heading, and agents select headings as if they were columns — 14 of 27
   column-not-found errors across eight databases (Modeling rules).
2. **Correction**: "each description naming its twin" is not sufficient. Measured, the
   bare-named reading is chosen roughly 40:1 and the twin goes unused; what converts is
   the bare description carrying **both live counts** and saying its plain name does not
   settle the question (Modeling rules).
3. **New**: that steering is **demand-gated**. Where the agent already asks and already
   gets the right answer, neither disclosure nor a new twin moves anything — verified
   twice on one model (Modeling rules).
4. **New**: a disambiguation applied at row grain must be applied to every aggregate
   built on it, or a question asking for an average hits the silent reading (Modeling
   rules).
5. **New**: a published count must name the reading it was counted under. Shipping a
   `LOWER(TRIM())` count on a LOWER-only attribute is not a typo — the agent quotes
   those numbers into its clarifying question (Modeling rules).
6. **New**: a convenience aggregate whose population is wider than the common question
   invites the agent to skip the scope filter, and returns a plausible wrong number with
   no error (Modeling rules).
7. **New engine constraints**, four, none previously listed: an expression beside a bare
   column over a derived table; `ORDER BY` on a column the outer `SELECT` hides; a
   two-argument window function; a scalar subquery in the select list (Engine
   constraints).
8. **Correction**: the masked-threshold gate must be run with `--kb`, or the
   `calculation_knowledge` exemption is silently defeated and it reports leaks that do
   not exist (Build process).
9. **New**: a gate that cannot find its brief does not run and says nothing. Two models
   had never been leak-checked; both were failing when finally checked (Build process).
10. **New**: the question-leakage gate over-flags legitimate KB concept names, and a
    discoverability gate that *requires* phrases can enforce a leak (Build process).

**What changed in v5 (crypto_exchange and ETF, 2026-08-14/18).** Five rules
from the ETF and crypto_exchange model work, listed so each can be reviewed or reverted
independently.

1. **New**: a threshold whose unit is ambiguous against the stored column ships in both
   readings, with the KB's own wording carried verbatim into the description — and gold
   can read the same term both ways inside a single task, so it cannot break the tie
   (Sources).
2. **New**: object folders are the cheap discovery channel now that `explore_columns`
   takes a folder argument, so folder size is a build-time decision rather than
   presentation (Surface size).
3. **New**: a per-row quantity that exists only inside a metric collapses a projection's
   row count through the engine's implicit group-by — the count is wrong, not the query
   shape unavailable (Placement and conformance).
4. **New engine constraint**: `real::numeric` truncates to six significant digits,
   silently and plausibly (M-31) — and an exactness reference query must read the source
   column raw, or both sides are wrong in the same direction (Engine constraints,
   Acceptance).
5. **New**: one join role per dimension, or attribute-only queries have no path at all —
   a failure the conformance gate as written cannot see, because adding any measure
   makes it resolve (Placement and conformance, Acceptance).

**What changed in v4 (`labor_certification_applications`, 2026-08-13/15).** That build reached parity with the raw baseline from a clear deficit,
across four three-run evaluation rounds. Listed so each change can be reviewed or
reverted independently.

1. **New engine constraint, and the most expensive of this round**: an MDX
   `[Dim].[Hier].[All]` tuple clears only *that* dimension's filter, so an index whose
   denominator is meant to be a warehouse-wide constant silently collapses to the
   current slice. `AllMember()` is the fix (Engine constraints). Six calcs were wrong;
   all six validated clean.
2. **New**: a sum of squared shares — Herfindahl, concentration, diversity indexes —
   *is* expressible as an ordinary additive measure via a per-row contribution. This
   retires "the engine cannot express this inline" for a whole family of KB formulas
   (Modeling rules, Group vs entity level).
3. **New**: a description that states a **fact** helps; one that prescribes an
   **answer** competes with the user and costs tasks. Two observed, both self-inflicted
   (Definitions and labels).
4. **New**: an added object must earn its place **twice** — once by being in the KB,
   once by not shadowing a neighbour. A legitimate KB concept cost a task by
   out-competing a masked one it shared vocabulary with (Surface size).
5. **New**: KB completeness is a *fairness* requirement, not a scoring lever. Ten KB
   concepts added: zero discovery cost, zero queries, zero score change (Surface size).
6. **New, and the only change this round that moved the score**: the ask-the-user
   trigger must name the **shape of the answer** to request — a closed question with
   explicit options, the exact number, the exact label text, their spelling verbatim,
   and re-ask rather than choose (After acceptance). Measured +0.040 average reward.
7. **New**: where the ambiguity is *which object*, the model can enumerate its own
   inventory as a ready-made closed question. That publishes nothing withheld (Sources).
8. **New**: gold SQL can contradict its own KB. Follow the KB and expose the choice; do
   not switch to gold's reading (Answer-key firewall).
9. **New**: before concluding the comparison is unfair, verify the mechanism. A
   suspected masked-threshold leak turned out to be filtered exactly as documented
   (After acceptance).
10. **New**: pool across rounds and test properly; and know the run count your question
   actually needs before spending it (After acceptance).
11. **New**: when *both* arms score 0.000 on every task of one database, suspect the
   harness — and check whether the database's name is unusually long (After acceptance).
12. Inexpressible-dialect inventory extended: `json_agg`, `json_build_object` and
   `COUNT(*) FILTER` confirmed rejected, with the `SUM(CASE ...)` substitution that
   works for the last one (Engine constraints).
13. Tie-order: gold's tied row order follows no rule, and a raw arm reproduces it by
   construction where a semantic layer cannot. Grading flags applied symmetrically lift
   both arms equally, so they neither explain nor close a gap (After acceptance).

**What changed in v3 (ETF evaluation, 2026-08-13/14).**
1. **Restored four rules that a previous merge dropped**, each of which had already been
   paid for: the dialect-inexpressible inventory and its "do not drop this" warning
   (Engine constraints); a pre-built rank's population belongs in its *name* (Ranks); a
   name that mirrors a question's phrasing must satisfy *every* condition in it (Keys);
   and the `is_mask` operational test based on the KB entry's `type` (Answer-key
   firewall).
2. **New**: a composite of percentile ranks must share one population, and rank on the
   undivided sum (Group vs entity level). One model defect, two distinct failures.
3. **New**: predict a model fix's task-level payoff at **zero** by default, and verify
   sufficiency for free before spending a run on it (After acceptance). Measured 3 for
   3.
4. **New**: "confirm with the user" in a description only works when the agent asks the
   question *open*; a leading question gets ratified (After acceptance).
5. **`Sharper n≥3 rule`**: run-to-run variance is arm-asymmetric, with measured numbers
   and a per-arm repeat budget (After acceptance).

**What changed in v2, the earliest recorded revision (from the `cybermarket_pattern`
build).** That build passed every acceptance gate below, deployed clean, validated clean
— and scored level with the raw text-to-SQL baseline. Everything in that revision came
from closing that gap.

1. **Reversed the advice on description-based steering** (Definitions and labels, first
   bullet). The previous revision said to redirect a caller via description text. That
   was tried in four places and failed in all four; only structural fixes worked. The
   old guidance is now explicitly marked as insufficient.
2. **Added a name-ownership rule** for every place this prompt tells you to ship more
   than one reading of a concept (Sources; referenced from Ranks, Group vs entity,
   Grain).
3. **Strengthened the rule on invented classifications** to a default prohibition.
4. Continuous values questions group *by* need a queryable attribute, not only a
   measure.
5. **Surface size**, making object count a budgeted quantity. Eight rules in this prompt
   multiply object count and nothing previously bounded it.
6. Missing-input policy is a separate reading with its own object.
7. Pre-ship shares and rates as calculations, because a caller's numeric cast returns a
   string.
8. **After acceptance.** The four gates prove correctness, not usability.
9. Repo target corrected to the shared `bird-atscale-models` repo, with the consequence
   that deploying publishes the whole catalog.
10. Precondition 1 corrected — `create_bird_connections.sh` has moved repos.
11. Two new engine constraints: no `|` in derived SQL (D-01); numeric casts need
   precision/scale and return strings.
12. New engine constraint Q-17b (non-idempotent publish, asymmetric failure) and the
   pre-run health gate that follows from it; plus the config-cache restart requirement.
13. Discoverability promoted from an acceptance check to a build-time assertion, with
   the YAML-folding trap that makes a naive version report false failures.
14. Sharper `explore_columns` examples: a plural and a voice change are each enough to
   miss.
15. Non-unique-label warnings must lead the description, not follow it.
16. Median-split concepts: precompute the median in dataset SQL, since the engine's
   percentile aggregation is dialect-blocked.
17. The answer-key firewall now recommends enforcing itself mechanically (an
   allowlisting extractor that asserts on its own output) rather than by intention, and
   the `is_mask` rule now says plainly to expect it to cost tasks and to report those
   separately.
18. Smaller propagations of the same evidence, each one line to a few: join exactly-1:1
   source tables into one wide fact to pre-empt the conformance class; prefer a compound
   SML leaf key where an entity has no single identifier; ship one rank twin where the
   live data shows no ties, and record a `LIMIT`-across-a-tie task as capped rather than
   failing; check an entity-grain variant is distinguishable before shipping it; verify
   a recorded column and its computed near-equivalent actually differ, and record the
   evidence; consider not exposing a concept component that has no independent use; have
   the generator fail on a dangling cross-reference between descriptions; note that an
   unpushed fix deploys the old model and looks like the fix did nothing.

---

Build an AtScale semantic model over the BIRD-Interact data in
`bird_interact_agent/data/bird-interact-full` at the BIRD-Interact fork root. Target the
`<db>` database through the `bird_<db>` connection, in the shared model repo
`AtScaleInc/bird-atscale-models`, in a new top-level folder named for the database,
committing to main. Note the consequence of the shared repo: deploying publishes the
**whole** catalog, so every model in it goes out together, and a redeploy for an
unrelated sibling model can break yours (see Q-17b under Engine constraints). Build via
a deterministic generator script parameterized by database name (see Build process). Run
unattended.

## Preconditions

1. An AtScale connection exists for the target database
   (`utilities/create_bird_connections.sh` in **`AtScaleInc/bird-atscale-models`** — not
   in the BIRD-Interact fork, where it used to live — provisions a connection per BIRD
   database). It reads `utilities/.env`, which is gitignored and must stay that way;
   copy `utilities/.env.example` and fill in `ATSCALE_CLIENT_SECRET` and `PG_PASSWORD`.
2. The AtScale MCP server is running and connected.
3. Deploy credentials: `ATSCALE_API_URL` is the SML API base URL without `/v1/public`
   (locally `http://local.atscaleinternal.com:3001`); `ATSCALE_API_TOKEN` — locally, use
   `ATSCALE_MCP_TEST_API_TOKEN` from `AtScaleInc/mcp/.env`.

## Answer-key firewall — read before opening any JSONL

Anything answer-bearing in `bird_interact_data.jsonl` is out of bounds while modeling:
`sol_sql` and `follow_up.sol_sql`, `sql_snippet` on any ambiguity entry, `test_cases`
and `conditions` (top level and inside `follow_up`), `preprocess_sql`, `clean_up_sqls`.
The cleanest guarantee is to extract the permitted fields (listed under Sources) into a
brief up front and model only from the brief, so the gold answers never reach your
context. Say which approach you took. Prefer to enforce this mechanically rather than by
intention: a short extractor that allowlists the permitted keys and then asserts that no
denied key and no SQL-shaped text appears in its own output is cheap, auditable, and
removes the question entirely. Gold SQL is fair game only later, if asked to diagnose
specific failing tasks — never folded back into the build.

Two working rules that keep the build honest:

- Every model change must be justifiable from the KB, the schema, or the engine's own
  observed behaviour — never from "this matches the expected answer".
- Hard-code a KB constant or threshold into the model only when its ambiguity entry is
  `is_mask: false` (an openly stated convention). When `is_mask` is true the benchmark
  intends the agent to resolve it by asking the user; baking it into the model answers
  the question for the agent. Still ship the masked concept's components — but each
  component's description must say it is one input to a larger named concept and that
  the agent should ask the user for the complete definition, every condition and
  threshold, before filtering. Observed failure otherwise: the agent anchors its
  clarifying question on the one component it found, gets a partial yes, and never
  learns the rest. Expect this rule to cost you tasks and do not try to buy them back:
  on `cybermarket_pattern` every one of the four tasks that failed on every run of both
  backends turned on a masked term, and no honest model change would have moved any of
  them. Report those separately from real defects so the score is read correctly.

  **The operational test is the KB entry's `type`, not your reading of the word
  "threshold."** Verified 2026-08-12 across `solar_panel`, `households` and
  `archeology_scan`: masked `calculation_knowledge` entries — KB-NAMED FORMULAS — ship
  under their own names in every model, 7 of 7 (Effective Power Output, Annual
  Degradation Rate, Temperature-Corrected Performance, System Unavailability,
  Infrastructure Quality Score, Household Density, Bathroom Ratio), because there the
  ambiguity is "which index did you mean", which competing named metrics answer
  honestly. Masked `domain_knowledge` entries that state a numeric cutoff do NOT ship, 0
  of 17. The single apparent exception, `Accelerated Aging Asset`, is `domain_knowledge`
  whose definition states no number at all ("a high Annual Degradation Rate and signs of
  Major Module Degradation"), so there is nothing precise to hand over. Apply the same
  split rather than re-deciding per model, and enforce it mechanically: derive the
  masked set from `is_mask` in the brief, close it over the KB's own
  `children_knowledge` edges (a concept that depends on a masked one leaks the same
  cutoff), and fail the build if any member is implemented. `archeology_scan`'s
  generator gate A10 does this and reproduces its hand-written omission list exactly.
  `utilities/masked_threshold_gate.py` is the portable version for models without a
  generator; wire it into the build rather than auditing by hand, and note that it can
  legitimately report an entry as **inert** — masked only on a task category this
  backend does not run, and therefore published at no measurement cost.

**Gold SQL can contradict its own knowledge base. Follow the KB.** Observed on
`labor_certification_applications` KB 11, which states that both wages "are converted to
the same payment unit before calculation"; gold instead *excluded* the rows whose units
disagreed. Two of 981 rows, and they reordered a headline top-5. The honest resolution
is neither to silently keep your reading nor to adopt gold's: follow what the KB says,
and ship an attribute that lets the caller select the other population, with both
descriptions stating the live counts. Switching your formula to match gold is
answer-fitting even when you found the divergence legitimately while diagnosing a
failure; exposing the choice is not, because it does not guarantee the task passes.


**The firewall's own SQL detector must test for SQL *structure*, not for keywords.** An
extractor that asserts "no SQL-shaped text in my output" is the right idea, and a
keyword list is the wrong implementation: it fires on ordinary English. Observed
immediately on first run — the detector rejected the phrase **"join type"**, which is a
natural-language ambiguity label in the task set, not SQL. A keyword list tuned until it
stops firing is worse than useless, because each loosening is invisible. Test instead for
three narrow signals, which prose does not produce: SQL *structure* (`select` … `from` in
one string), DDL/DML verbs (`insert into`, `update … set`, `create table`), and
function-call syntax (`count(`, `cast(`, `row_number(`), plus clause keywords only when
written in SQL's upper case. And when the detector does fire, read the match before
loosening it — the first one was a true positive about the detector and a false positive
about the data, which is the only way to tell a bad gate from a real leak.

## Sources — and only these

Verify everything against the live database; the metadata files drift, so live wins.

- `<db>_schema.txt` and `<db>_column_meaning_base.json`. Profile the live tables
  yourself and fold what you find into the descriptions.
- `<db>_kb.jsonl` — every business definition, no exceptions, including any that
  individual tasks hide. Where the engine can't express one inline, say so rather than
  approximating silently — but read the sum-of-squared-shares pattern under Group vs
  entity level first, because that excuse has already been wrong once for a whole family
  of formulas. Some databases' KB files lost LaTeX backslashes to JSON unescaping: raw
  control characters stand where escape sequences belong (0x09 for `\t` as in `\text{}`,
  0x0C for `\f` as in `\frac{}`, likewise `\n` `\r` `\b`). Check for raw control
  characters after parsing and restore them before reading formulas; most KBs are clean
  — don't transform ones that are.
- The natural-language questions in `bird_interact_data.jsonl` (filter on
  `selected_database`), for naming, synonyms, and coverage only: `amb_user_query`,
  `follow_up.query`, `category`, `output_type`, `high_level`, `follow_up.type`,
  `external_knowledge`, and the term/type/is_mask of each entry in `knowledge_ambiguity`
  and `user_query_ambiguity`. Don't hard-code any single task's thresholds or column
  picks. Where a term is genuinely ambiguous, ship a candidate object per reading, each
  description naming the alternative.

**Name readings asymmetrically.** This applies everywhere below that tells you to ship
more than one reading of a concept — ambiguous terms, competing join paths, the three
group/entity objects, RANK/DENSE_RANK twins, `(Current)` variants. Exactly one reading
carries the bare concept name; every other carries a qualifier stating its narrowing
(`(Recorded Only)`, `(Missing X As Zero)`, `(Computed)`, `(Current)`, `(All Entities)`,
`(Per Application)`). Choose which one is bare from the questions' own vocabulary, not
from which reading is more technically correct. Two objects with equally plausible names
is the failure mode, not a service to the caller — see the first bullet under
Definitions and labels for why the descriptions will not save you.

**Where the ambiguity is *which object*, enumerate your own inventory.** A masked term
often is not a hidden number at all but a choice between columns the model already
publishes — "occupations" meaning a standard code, a standard title, or the employer's
free-text title. There the model can hand the agent a ready-made closed question: name
all the candidates in each of their descriptions and tell the agent to *ask which one*,
rather than to *pick*. This publishes nothing withheld — it is the model's own contents
— and it converts an open question into the closed form that measurably gets a specific
answer (see After acceptance). Distinguish it sharply from a masked cutoff, where naming
the candidate values would be a leak.

**A threshold whose unit is ambiguous against the stored column gets both readings, and
the KB's own words verbatim.** A KB definition states a cutoff in prose (*annual
portfolio turnover is less than 30%*), while the stored column may be on a different
scale — so the definition admits two readings, the literal number or the number
converted. Count both against the live population first: a reading is *viable* only if
it selects a proper, non-degenerate subset, judged on the screen the questions actually
ask for. Exactly one viable reading → ship it alone and give the number that rejected
the other (High-Conviction Portfolio: holdingpct is a 0–1 fraction, so > 8 selects 0 of
2297 top holdings and only > 0.08 selects 743). Two viable readings → ship both,
asymmetrically named per the rule above, each description naming its twin; a threshold
is the one thing a caller cannot recover from a result they cannot see. Either way the
KB's original wording, units included, must survive into the description's opening KB
'<Term>': … — a description that reinterprets a cutoff without carrying the KB's own
phrasing is a build defect, and a mechanically checkable one.

Gold is not a tiebreak here, and can disagree with itself: on `etf_18` gold filters
`Turnover_Ratio` < 0.3 in phase 1 and < 30 in phase 2 — the same KB term (id 12, "less
than 30%") read both ways in one task, counting 53 rows against 145. No single reading
wins both phases, which is precisely why both must exist as named objects rather than
one being chosen for the caller.

Do not read any other semantic model on this machine, nor its git history. If you open
one by accident, say so in your report.


**Two columns that look like two readings may be one recorded value — measure before
shipping twins.** Where the same concept appears in two places (a classification on the
event and the same classification on its detail row, an encryption status in both), the
instinct is to treat them as independently-recorded readings and ship both, each naming
the other. Check first, with a join and a mismatch count. Observed on three pairs in one
schema: sensitivity agreed on all 835 rows where both were present, encryption on all
292, category on all 835 — every apparent disagreement was a null on one side, not a
disagreement. They were denormalised copies. The previous build of that model had shipped
competing twins for them and written a design note explaining that the two sources
"disagree in source", which the data does not support. Where they do prove identical,
ship **one** object, `COALESCE` the sources for coverage (998 of 999 rows against 963
from the wider one alone), and put the verification count in the description so the next
reader does not re-litigate it. Where they genuinely differ, the existing twin rules
apply — the point is that this is a measurement, not a judgement.

**A KB formula that enumerates its input's values can be silently incomplete, and NULL is
not the safe completion.** A sensitivity index defined as "3 if high, 2 if medium, 1 if
low" met a stored column carrying a fourth level on a quarter of the rows. This is not a
masked threshold and not an ambiguity the KB is hiding — it is a gap in the KB's own
definition. Implementing it literally, so the unnamed level yields NULL, is the reading
that looks most faithful and is the most damaging: every top-N, every total and every
average built on the formula then silently omits that quarter of the population, and
nothing errors. Ship both completions — the unnamed value falling through to the base
factor, and whatever reading the question set's own wording implies — named
asymmetrically, and give the count of rows on which they **differ** rather than the count
each selects at some threshold, so the disclosure does not become a leak. Scan every
KB formula that switches on a categorical for this: compare the values the formula names
against the values the column actually stores, and treat any surplus as a finding.

## Modeling rules

**Placement and conformance**
- An attribute that describes an entity goes on that entity's dimension, so it conforms
  wherever the entity does — not on the fact or derived table that computed it.
  Degenerate dimensions are for genuinely fact-grain attributes only.
- A filter or grain flows to a measure only along a relationship path the engine
  accepts, and some structures that look like paths in the SML are not accepted at query
  time: a many-to-many bridge between the measure's dataset and the dimension, a
  degenerate dimension sourced from a different fact, a measure declared on a coarser
  dimension's dataset. When no accepted path exists the query falls back to
  `unrelated_dimensions_handling` — silently empty results with an easy-to-miss warning.
  Where a pairing must work and the path is one of these shapes, denormalize the value
  onto a dataset with a direct relationship at the grain you need (a degenerate
  dimension repointed via `dataset:` alone still fails — convert to secondary attributes
  on the real dimension). The conformance acceptance check is what proves each pairing;
  trust it, not the diagram.
- Where several source tables are exactly 1:1 on the same key (verify live: equal row
  counts, no orphans either way), joining them into one wide fact is usually worth it —
  it gives every attribute on them a direct relationship to each entity dimension and
  removes the whole conformance failure class above before it can occur. A 1:0..1 table
  (an optional attorney, an optional preparer) joins in the same way and removes a
  bridge you would otherwise have to build.
- Set unrelated-dimensions handling explicitly on every measure — prefer error, so a bad
  pairing fails loudly instead of silently returning empty.
- Where an entity can reach another by more than one join path (a direct FK vs a
  many-to-many bridge), ship attributes for both readings with descriptions saying which
  path each uses and when to prefer which. Don't assume the structurally "more correct"
  path is the one questions mean. If the bridge's pairs exactly mirror pairs derivable
  from the fact (verify live), model it as a plain link-count fact instead of an M2M
  bridge.
- **One join role per dimension, or attribute-only queries have no path.** Where a
  dimension is reached from several datasets on different columns, the planner cannot
  choose a path for a projection that names attributes and no measure, and every pairing
  of that dimension's attributes with another's dies on `assertion failed: No candidate
  paths found for an attribute`. Adding any measure to the same projection makes it
  resolve — which is why a conformance gate built from measure-by-attribute queries
  passes while the model is broken for every attribute-only question. Measured: 32 of 98
  `run_query` calls in one benchmark arm, exhausting the entire budget of three tasks.
  Drop the extra roles and recover what they bought by denormalising the column onto the
  dataset that needs it; the lost pairing then errors loudly under
  `unrelated_dimensions_handling` instead of answering.
- Key each dimension leaf on the column the fact's FK actually references (watch
  numeric-id FKs against text labels — type mismatch); keep the descriptive string as
  `name_column`. Where the source has no single identifier for an entity, use a compound
  SML leaf key over its natural columns rather than concatenating a surrogate in dataset
  SQL — see D-01 under Engine constraints for why concatenation is actively dangerous.
- **A continuous numeric that questions might group *by*, rather than aggregate, needs a
  queryable attribute as well as a measure.** Scan the question set for "per X" / "by X"
  / "for each X" phrasing over stored scores, rates and ratios. A measure-only numeric
  silently makes an entire question shape *inexpressible* — not merely awkward — and the
  caller has no workaround. Observed twice: a 1000-distinct-value score shipped as a
  measure only, where the questions group by it directly; and a rate shipped only as
  average/min/max, so `WHERE "<rate>" > <n>` returned `Column not found` and the agent
  fell back to a KB bucket whose cutoff was a different number. **Treat "the caller
  supplies the threshold" as a first-class query shape.** It is the normal case for
  every masked concept, and it is the case a measure-only numeric cannot serve. Ship the
  row-level attribute beside every measure whose concept a question could band, filter
  or bucket: rates, elapsed times, lead times, scores, counts of factors.
- **A per-row quantity that exists only as a metric also breaks projections, not just
  group-bys.** Where a question projects one row per source row, the row-distinguishing
  column must be queryable, or the engine's implicit group-by silently collapses the
  result. Observed: a per-snapshot buy-force reading shipped only as an average metric
  left the projection grouping on (market pair, spread, sentiment) and returned 840 rows
  where the reference had 1000 — confirmed both ways, since `distinct(pair, spread,
  sentiment)` is 840 in Postgres and adding the buy-force column makes it 1000. The row
  count is wrong rather than the query shape unavailable, so nothing errors and nothing
  looks odd.

**Ranks and top-N**
- Expose the ranks and orderings that superlative and top-N questions need, at each
  grain they could ask about, stating sort direction, null placement, and tie
  convention. "The top N" means the first N rank positions under `RANK` and the N
  highest distinct values under `DENSE_RANK` — different row sets whenever values tie.
  Check the live data at the N the questions use; wherever the two disagree, ship both
  as separately named twins whose descriptions say which question each answers and name
  the other. The caller cannot recover the missing reading: a window alias used in
  `WHERE` must also be projected on this engine, which changes the column count.
- Where the two agree in the live data — no ties at the N the questions use — ship only
  one. Twins that never disagree are pure surface cost (see Surface size).
- **A pre-built rank's *population* is part of its definition, and belongs in its
  name.** A rank computed over every entity returns a gapped sequence the moment the
  caller filters (1, 2, 3, 5, 8...), which is not the dense within-filter rank a "top N
  of the entities that ..." question means. A within-filter rank is not expressible at
  build time — the rank cannot know a runtime `WHERE` — so the honest fix is to put the
  population in the *name* (`... Rank (All Entities)`), not only in the description,
  because an object whose name matches the question's vocabulary is picked on surface
  word match and by then the caller has already filtered. Where questions ask both ways,
  ship both readings.
- Note the limit of what this can buy you: when the question's own `LIMIT N` cuts across
  a tie, the expected answer is *not unique*, and no model can make it so. Record such
  tasks as capped rather than failing.
- Before shipping any rank object, confirm the inbound interface cannot already express
  it. `RANK() OVER (...)` in the projection is accepted, so a displayed rank often needs
  no model object at all; a `metric_calc` rank has to be bound to one hierarchy's set,
  which means one object per grain. Prefer the caller's window function and spend the
  surface elsewhere.

**Group vs entity level**
- Group-level and entity-level versions of a statistic are separate, separately named
  objects. Where the definition is a formula over other quantities (ratio, difference,
  weighted score, share), the group-level version must recompute the formula from
  aggregated components, as a calculated metric referencing component measures. Do not
  compute it per row in dataset SQL and average that column — that answers "the typical
  entity", not "this group", and once components are collapsed per row the group reading
  is unrecoverable. That makes **three** separately named objects: the formula over
  aggregated components, the mean of per-entity values, and the entity's own value —
  each description saying which question it answers and naming the others. Every
  component must exist as its own measure.
- Before shipping all three, check whether the entity-level variant is actually
  distinguishable from its base at entity grain. Where it is provably identical, ship
  one. The same test retires a whole trio: where a rate is 100% for every row in the
  warehouse, the group figure and the mean of per-entity figures are provably equal, so
  ship one object and say why in its description.
- **A composite of percentile ranks must rank every ingredient over ONE population**,
  and that population is the entities carrying *all* the ingredients. Ranking each
  ingredient over its own non-null set gives each a different denominator, so their mean
  averages incomparable scales and no entity's score is right. Observed: within one
  category the three ingredient populations were 42, 60 and 78, the composite was wrong
  for every fund, and 7 of 48 group winners changed. The defect is visible without any
  reference answer — a value ranked against 78 peers has no common scale with one ranked
  against 42 — so this is a correctness fix, not tuning.
- **Rank on the undivided sum, not on the mean.** Ordering by a sum and by that sum
  divided by a constant is the same ordering in exact arithmetic, but the division is
  lossy in floating point and *invents ties*: two distinct sums (`2.0` and
  `1.9999999999999998`) collapsed to one double and produced two rank-1 entities where
  there is one. Publish the mean as the score if that is the natural scale, and rank on
  the sum.
- **A sum of squared shares IS expressible — do not record it as an engine limitation.**
  Herfindahl-style concentration and diversity indexes (`sum((share_i)^2)`, `1 —
  sum((share_i)^2)`) look impossible because no aggregation squares a share, and three
  of them were written off on that basis before the pattern was found. Give each row its
  group's squared share divided by that group's row count, and a plain `SUM` over any
  set of rows reproduces the formula exactly:

      SUM over rows of (share_g^2 / rows_g)  =  SUM over groups of share_g^2

  They then behave as ordinary additive measures — no second fact table, no extra
  conformance surface, and correct under any filter the caller applies. Verify against a
  direct computation over the source tables and pin both numbers as dry-run assertions.
  The same trick covers any "sum over groups of f(group)" where `f` is computable per
  row. State in the description that the index is read as a single figure for the
  filtered population, *not* grouped by the dimension it sums over — grouping by that
  dimension returns each group's own term rather than the index.

**Grain and time**
- Where the fact grain is finer than the entity (one row per reading/snapshot per
  entity), state on every flag and measure whether it answers "has this entity *ever*
  had X" or "does it have X *as of its latest reading*" — a model silent on that
  distinction produces plausible wrong answers. Ship latest-state "(Current)" variants
  of state/cost/output measures as objects distinct from history-wide aggregates. Where
  questions ask "as of right now", a NOW()-based dataset column works: it is pushed down
  and re-evaluated per query, not frozen at deploy.
- Don't trust `semi_additive (position: last)` for "latest snapshot per entity": it
  needs the trigger level to sit inside a hierarchy that also contains the entity, and a
  snapshot-keyed hierarchy plus a separate entity hierarchy cannot express it — the
  failure is silent, falling back to base aggregation with plausible numbers. Use
  `FIRST_VALUE(...) OVER (PARTITION BY entity ORDER BY snapshot DESC)` window-carry
  columns instead, and confirm via `get_outbound_queries` that the warehouse SQL
  contains the window function, not a plain `MAX()`.
- Document each measure's natural row grain. Averaging over entities silently differs
  depending on whether the inner grain is the snapshot or the entity; a coarser-grain
  figure requires an explicit reduction first, and the description should say so.
- Profile every date and every headline numeric for **degeneracy** before modelling on
  it. A column that is a single constant across the whole warehouse makes every
  statistic over it trivial and every sort by it fully tied. Observed: receipt and
  decision dates were one value each, so every processing time was the same 8 days;
  every application carried the same status, so every approval rate was 100%. Say so in
  the description of every object that touches such a column — a caller who does not
  know will read a real signal into a constant — and expect any task that sorts by one
  to have a non-unique expected answer.

**Surface size**

Because it was the single largest cost measured on `cybermarket_pattern` and nothing
else in this prompt bounds it. Eight of the rules here multiply object count.

- Object count is a direct tax on the agent's budget: `explore_columns` is a substring
  match with no relevance ranking, so every near-duplicate description is sifted on
  every search. Measured on a 188-metric model: **62.5% of the per-task coin budget
  spent on discovery, 151 `explore_columns` calls over 20 tasks, and 19 of 20 tasks
  exhausting budget immediately after phase 1** — leaving nothing for the follow-up.
  Cutting to 162 metrics brought discovery to parity with the raw baseline. Nothing
  about the tools changed; the model got smaller.
- **Folders are a discovery surface, not decoration.** `explore_columns` takes a folder
  argument, so a named folder returns its whole contents for the same one coin as a
  keyword guess — which makes folder size a build-time decision. ETF shipped 20 folders
  for 387 columns, two of which held most of the model: one returned 195 columns and
  75,142 characters, no better than dumping the catalog, and the index stopped being an
  index. Split by theme until no folder dominates (ETF's 130 metrics went to 15 thematic
  folders, largest 33), and give secondary attributes their own folders rather than
  letting them inherit the hierarchy's, so an agent that finds a theme gets both the
  per-entity attribute and the aggregate. Attribute-level folders may be honoured or
  ignored by the engine — `sml-cli validate` accepts them, so verify with
  `explore_columns(folder=...)` after deploy and revert that half if they are ignored.
- Watch for the symptom, since it looks like a scoring mystery rather than a defect: a
  model with no visible flaw, correct on every gate, scoring at the baseline, with tasks
  running out of budget right after their first answer.
- The multiplicative rules above are permissions, not obligations. Ship a variant only
  where it is **provably** distinguishable in the live data — check ties before shipping
  a rank twin, check identity before shipping an entity-grain variant.
- Withholding peripheral columns that no question touches is legitimate and preferred
  over shipping them for completeness. Record which ones and why, in the spec, next to
  the exclusion — a silent omission is indistinguishable from an oversight later.
- **An added object must earn its place twice: once by being in the KB, once by not
  shadowing a neighbour.** Object count is not the only cost — *vocabulary collision*
  is. A legitimate KB concept can out-compete the concept a question actually needs when
  the two share words, and the added one wins because it is a ready-made classification.
  Observed: shipping KB 57's delay-risk bands (Low/Moderate/High) cost a task that
  wanted KB 51's complexity split (Complex/Standard); the agent grouped by the new
  object, then had to ask the user and re-submit, three coins down. Before adding, ask
  which existing concept the new one is nearest in *wording*, and if the answer is a
  masked concept, give the new object a description that leads with the collision and
  routes that question to ask-the-user. Both times that treatment was applied it was
  followed by the task recovering.
- **KB completeness is a fairness requirement, not a scoring lever — fund it as such.**
  The raw arm can look definitions up with a tool; the semantic arm usually cannot
  (`semantic_layer_knowledge_tools` defaults off), so anything the KB defines and the
  model omits is a straight structural disadvantage. Close the gaps. But measure the
  expectation honestly: ten KB concepts added to `labor_certification_applications` cost
  nothing in discovery (5.1 to 5.0 calls per task, budget exhaustion actually fell) and
  were **never once queried**, because no task in the set asked for them. Do it so the
  comparison is fair; do not book a score improvement against it.

**Support sets and hidden objects**
- Any measure computed over a subset of rows must expose its support set, and both
  pieces must be visible to the discovery API — never hidden. Ship the count of entities
  that actually entered the computation (the regression n, the non-null count) and,
  where a caller would select that population, an availability classifier saying which
  entities carry the required inputs. The generic entity count is not a substitute — it
  over-selects. Where a formula has several components, the support set is the
  **intersection** of entities where every component is present — one count per formula,
  never per-component counts, never the widest one.
- **A support-set count is itself a reading, and a "group with enough entities" gate can
  mean either it or the generic count.** Where you ship both, say in each description
  that the choice changes which groups clear any given minimum, give the live counts for
  both, and direct the caller to confirm which population the question means. Expect the
  ask to be framed badly anyway (see After acceptance) — the two counts must at least be
  separately named and separately documented, because a caller who picks the wrong one
  gets a plausible, wrong row set with no error.
- **The missing-input policy is itself a reading, and needs its own object.** Where a
  formula's inputs are absent for some entities, ship both the strict version that
  excludes them and the zero/coalesce version that keeps them, named asymmetrically,
  each carrying its coverage count. A caller cannot recover one policy from the other.
  Observed: only the strict reading shipped, dropping 387 of 954 entities, where the
  questions wanted all of them.
- Hidden is only for terms with no standalone meaning (a sum of squares, a rebased
  denominator). Before declaring the model done, list every hidden object and state what
  question could be asked about it; if you can phrase one, unhide it. Report the list
  with evidence. Also confirm every defined object is referenced by the model file — no
  orphans that exist but cannot be queried.

**Definitions and labels**
- **Where two objects can answer one question, the name decides — not the description.**
  Verified repeatedly and expensively: the agent picks the object whose name best
  matches the question's words, and does not act on description text pointing it
  elsewhere, *even when that text is the description's first sentence*. In one case a
  description reading "prefer X" was ignored on two consecutive runs. In another, a task
  used the correct value, the correct population and the correct sort across three runs
  and never all three in one submission, because two objects shared one concept.
  Descriptions still carry disambiguation for a human reader and to trigger the
  ask-the-user path, but never rely on one to steer a choice. Resolve competition
  structurally, in this order: (1) if a reading has no basis in the KB, **delete it**;
  (2) otherwise move the plain, unqualified name onto the reading the questions actually
  mean and push every other behind a qualifier.
- **A description that states a FACT helps; one that prescribes an ANSWER competes with
  the user.** This is the sharp edge of the rule above and it was learned twice on one
  model, both times self-inflicted, both times costing tasks:
- "Premium means the position pays well relative to what is required" — added to satisfy
  a discovery phrase, it told the agent to answer a *different* KB concept's question
  with this attribute, and it did, returning 60 where the caller's threshold gave 33.
- "Firm names are stored with mixed capitalisation ... collapse casing yourself if one
  row per firm is required" — the agent did exactly that, `GROUP BY UPPER(...)`, and the
  reference does not merge casing, so the whole top-five changed.

  The rule that replaces both: **where a data-quality quirk has more than one defensible
  treatment, state the quirk with its live numbers and route the decision to the user;
  never pick one on their behalf.** "Fragomen appears in 4 casings (56, 44, 12 and 11
  applications); whether to merge them changes which firms rank where, so ask the user"
  is useful. "Collapse casing yourself" is the model making an analytical choice that
  the question may not share. Audit every description for the imperative mood: an
  instruction to *do* something with the data, rather than a statement of what the data
  *is*, is the smell.
- Model every KB-defined metric, even composite ones. A missing KB metric doesn't fail
  loudly — queries silently fall back to a simpler, wrong aggregate.
- Where the KB defines named multi-condition concepts ("X failure" = A OR B; "major Y" =
  three ANDed conditions), don't just describe the logic — precompute it once,
  correctly, as a Yes/No attribute the agent can filter on directly. Description text
  alone is not reliably turned into correct SQL, even when read. Two second-order
  effects to plan for: the raw component columns compete with the flag on surface word
  match (a question phrased in a component's words gets filtered on that component
  alone, losing the OR branch); and a Yes/No flag hides the quantity it was derived from
  — note on the flag which underlying measure the answer likely still needs to display.
  Say in each component's description that it is an *input* to the concept and direct
  filtering to the flag — but treat that as documentation, not as a fix. It is not
  sufficient on its own, per the first bullet above: a component whose name contains the
  question's own word will still be chosen sometimes. Where the component has no
  independent use, consider not exposing it at all.
- **Do not invent a bucketing the KB does not define.** Expose the raw value and the
  pieces a bucketing would be built from — deltas, threshold comparisons, a boolean per
  condition. An invented bucket is worse than a missing one: it is usually named in
  exactly the words a question would use, so it out-competes the correct object on match
  while encoding a threshold nobody authorised. Both objects deleted from
  `cybermarket_pattern` were of this kind, and each had been chosen by the agent in
  preference to the correct object. Where the KB *does* name buckets, ship them, and say
  in the description that the label strings are this model's convention and the caller
  should re-label to the question's wording. Where the KB names a bucket but states no
  number for one of its conditions ("a statistically significant number of
  applications"), ship the components and no flag — a half-defined bucket is an invented
  one.
- **Pre-ship the divisions.** Any share, rate or percentage a question is likely to ask
  for should exist as a calculation rather than being left to the caller to divide two
  measures. On this SQL interface a caller's explicit numeric cast returns a **string**
  (see Engine constraints), so a hand-computed ratio cannot be rounded downstream and
  fails on presentation with the right value underneath. Scan the follow-up questions
  for "what percentage / what share / what proportion" and ship one calculation per
  answer shape; on `cybermarket_pattern` that was 13 of them, and most phase-2
  follow-ups were of this form. Say in the description whether the value is a **fraction
  (0-1) or a percentage (0-100)**, and give a live example value: a share shipped as a
  fraction where the question asks "what percentage" is a silent 100× error the caller
  will not notice. **Ship one grand-total share as well as the per-dimension ones.**
  Every dimension-scoped share divides out one *named* dimension, which a caller-defined
  `CASE` bucket is not, so those return 100.00 beside an ad-hoc grouping. A share whose
  denominator is `AllMember(<measure>)` works beside any grouping at all, including
  categories the user invented in conversation — which is the normal shape of a
  masked-concept follow-up. Ship both and say in each description which one ignores
  filters and which respects them; the two readings are not recoverable from each other.
- Verify formula inputs mean what the formula requires — gross vs net, pre- vs post-
  adjustment, units and scale (kW vs MW is a silent 1000x error; check internal
  consistency across metrics that share a column). Where a raw recorded column and a
  computed near-equivalent both exist, use whichever the KB formula names — they are not
  interchangeable. Check a specific live value end-to-end against the source; a
  plausible result computed from the wrong basis is silently wrong (double-counting a
  loss ratio, for example). Verify the two are actually different before shipping both,
  and say so in the descriptions with the evidence (observed: 0 of 994 entities had the
  recorded column equal to the computed formula).

**Keys, identity, and naming**
- If the human-readable label is not actually unique in the live data, expose the true
  unique key as a queryable (not hidden) secondary attribute. `COUNT(DISTINCT label)` on
  a non-unique label silently under-counts. Separate identity from display in both
  descriptions: the key is identity (count and group on it, but it's an internal code),
  the label is what to show — prescribe `GROUP BY key` + `SELECT label`. When you warn
  against a column for one purpose, say what it *is* for; a caution with no counterpart
  guidance is read as "never use this column". **Lead with the warning** — descriptions
  are read top-down, and a caveat that is not first is a caveat that is not read.
  Observed: a non-uniqueness warning in the second sentence, and both tasks that listed
  those entities grouped by the label anyway, silently collapsing ~9 entities per row.
- **A name that mirrors a question's phrasing must satisfy *every* condition in that
  phrasing.** A measure named in the question's own words that quietly drops one of its
  qualifiers is worse than a neutrally-named one: it is the obvious pick, it returns a
  plausible number over a larger population, and nothing signals the mismatch. Either
  carry every qualifier in the name, or name it for what it actually computes and let
  the description carry the paraphrases.
- **Quote the KB's own wording for every member value you emit.** Where the KB names the
  state ("the employer is *self-represented*"), use that string; a synonym you preferred
  ("Not Represented") is an invented label that fails an exact-value comparison for no
  reason. Audit the emitted member values against the KB text, not just the category
  set.
- Keep `unique_name` and label identical for anything an agent will query. The tools
  surface `unique_name`, so a friendly label attached to a snake_case technical name is
  invisible where it matters — and a snake_case identifier gets written unquoted, as a
  bare SQL column rather than a semantic-layer attribute. Descriptions that
  cross-reference other objects must use their queryable names, or the model's own
  metadata points at names that don't resolve. Have the generator fail the build on a
  dangling cross-reference, so a description can never name an object that is not
  published.
- **Check the repo's prevailing `unique_name` convention before authoring, and assert it.**
  The rule above says to keep `unique_name` and label identical because the tools surface
  `unique_name`. In a shared repo that is not enough — the *convention* itself can drift.
  Observed: twenty-two models in one catalog, twenty of them using label-based names with
  spaces and two using snake_case, which had gone unnoticed because nothing errors and each
  model looks self-consistent from the inside. The two outliers were the ones whose
  identifiers an agent would write unquoted as bare SQL columns. Count the convention
  across the repo before you pick one, and have the generator assert the choice, so a new
  model cannot quietly become the next outlier.

**Descriptions**
- Every measure and attribute description carries: formula and provenance, units and
  scale, live null and coverage counts, disambiguation from near-twins, and the
  paraphrases someone would actually ask with. `explore_columns` is a contiguous,
  case-insensitive substring match, not fuzzy search, and the near misses are much
  cheaper than they look: an inserted word ("count of years" does not match "count of
  calendar years"), **a plural** ("dodgy buyers" does not match "dodgy buyer"), **a
  change of voice** ("how quickly we handled threats" does not match "how quickly
  threats were handled"), and **a hyphen** ("specialty-occupation" does not match
  "specialty occupation") each make the object invisible. Include several wordings
  verbatim, in both singular and plural, in both active and passive phrasing, and
  unhyphenated. Descriptions on objects the discovery API doesn't expose don't count.
  The model's own description should be an orientation guide, not a one-liner.


### Naming, competing readings, and counts — what the 2026-08-18/19 sweep changed

- **A dimension's `unique_name` is a discovery heading, and headings get selected as
  columns.** `explore_columns` groups its output under `## <column_group>`, and the
  column group *is* the dimension's `unique_name`. Measured across eight databases, **14
  of 27 column-not-found errors were the agent selecting a heading it had just read** —
  `Household`, `Market`, `Buyer`, `Platform`. It is worst where the heading is
  near-identical to the model name *and* to the entity the questions count: a group
  called `Household`, in a model called `Households`, on a task set asking how many
  households qualify, produced 15 of that database's 29 query errors over three runs.
  Renaming it `Household Record` took heading-selection from 4.7 per run to zero. So: no
  dimension `unique_name` may equal, or differ only in number from, the model name or a
  primary entity the questions count. `<Entity> Record` is a safe form. The agent is not
  inventing a name here — it is using one it genuinely read, so the usual "only use a
  name you saw" instruction does not protect against it.

- **Naming the twin is not enough — the bare-named reading wins about 40 to 1.** The rule
  above already says each description names its twin. Measured, that does not get the
  twin *selected*: `(Recomputed For Group)` twins were used 2 times against 39 uses of
  the bare primaries, and recorded-case twins 5 times against 204 uses of the canonical
  attributes — with the lower-case reading that one task's grading actually required
  used **zero** times. What converts is the **bare reading's own description** carrying
  the twin's name, **both live counts**, and an explicit statement that its plainer name
  does not settle which the question wants. Two verified conversions: a dwelling-class
  attribute whose canonical form merges an abbreviation (255 households against 222 when
  only case is folded) took a task from 0-of-3 to passing in both later runs, with the
  previously-unused twin selected; a total-ischemia measure declared "one of three
  readings, and its plainer name does not make it the default" took another from 0-of-3
  to 2-of-2. In both, the agent asked the user which reading was meant — quoting the two
  counts back — and used the answer.

- **That steering is demand-gated, not coverage-gated.** Before shipping a twin, confirm
  the failure is *"the agent does not know a choice exists"* and not *"the agent knows
  and still fails"*. On one model the agent **already** asked the population question in
  the baseline and was **already** told "treat missing values as zero"; adding a
  population-choice clause did not raise asking (2.3 to 2.0 per run) and shipping the
  `(Missing X As Zero)` twin produced **zero uses** across a full run despite appearing
  in the discovery response. Both interventions moved nothing. A twin fixes a discovery
  problem; it does not fix a comprehension problem, and the two look identical in the
  gold SQL.

- **Fix the aggregate twin whenever you fix the attribute.** A row-grain measure was
  disambiguated and converted its task; the `Average …` metric built on it was left
  silent, so any question asking for an average still hit the undisclosed reading. A
  disambiguation applied at row grain must be applied to every aggregate over it.

- **A published count must name the reading it was counted under.** One model shipped
  `'brickwork house' 1211, 'apartment' 229` on an attribute that lower-cases *and
  nothing else*; the live values are 1092 and 222, because the published figures were
  the `LOWER(TRIM())` counts — contradicting the same description's own next sentence.
  Treat this as worse than a typo: the agent reads those numbers and quotes them
  verbatim into its clarifying question to the user, so a wrong count becomes a wrong
  question. Verify every count against the exact attribute it sits on.

- **A convenience aggregate invites the agent to skip the scope filter.** A `… Count`
  measure spanning every status was used unfiltered by a task that needed only completed
  rows; it returned a plausible wrong number with no error — the silent class, which
  only a graded benchmark catches. Any pre-aggregated measure whose population is wider
  than the common question must say so and name the filter to add.


### One entity, one dimension — what the 2026-08-20 rebuild changed

- **One degenerate dimension per `dataset` + `key_columns` pair, and no more.** Splitting
  a wide single-fact model into many themed degenerate "profile" dimensions on the same
  key is a natural way to organise 200 attributes, and it is wrong twice over. SML rejects
  it outright (see Engine constraints), and the headings it creates are the same
  heading-selection liability this prompt already names — measured, 14 of 27
  column-not-found errors across eight databases were the agent selecting one of those
  headings as if it were a column. Observed at scale: ten models in one repo had done it,
  122 dimensions across 17 duplicated pairs.

  The merge costs nothing in discovery, which is the part worth knowing before resisting
  it: **a secondary attribute carries its own `folder`**, so `explore_columns(folder=…)`
  returns each theme exactly as before. Verified on a 13-dimension merge — the folder
  still returned its same 15 columns afterwards. What collapses is only the `## ` heading.
  So theme with folders, not with dimensions, and let one dimension own the key.

- **Name the merged dimension for the entity, not for whichever theme won.** See Build
  process for why a mechanical rule that picks from inside the group gets this wrong.

- **Before shipping a `NOW()`-relative flag, profile it against the benchmark's own
  calendar.** The rule above under Grain and time says a `NOW()`-based dataset column
  "works" because it is pushed down and re-evaluated per query. That is true of the
  mechanism and says nothing about the values. Observed: every remediation deadline in a
  schema fell in a three-month window two years before the real current date, so
  `CURRENT_DATE - deadline > 0` was true for **240 of 240** rows and the
  nearing-deadline complement selected **0**. An overdue flag there is degenerate — it
  selects the whole population and discriminates nothing, while looking like a real
  screen. Where the questions supply their own reference date, ship the raw date and let
  the caller subtract; where you ship the now-relative figure anyway, put the degeneracy
  in the **first** sentence of its description, not the last.

## Engine constraints (learned the hard way)

These work around tracked engine/tool defects — parenthesized IDs reference the team's
defect tracker and are provenance, not something to resolve. Check the Workarounds table
in BIRD-Interact-ADK's `docs/model-change-log.md` for whether each still applies.

- **`[Dim].[Hier].[All]` in an MDX tuple is not a whole-model constant — it clears only
  that dimension's filter.** Every other dimension in the query still narrows it. So an
  index whose denominator is meant to be a warehouse-wide average silently collapses to
  the current slice and returns a plausible wrong number:
- an attorney specialization index returned **0.0 at every grain** instead of 0.75,
  because "visa types in the warehouse" became "visa types this attorney handles";
- an occupational demand index returned **1.0** instead of 43.73 as soon as any second
  attribute was grouped.

  Use `AllMember(<expr>)`, which strips all dimension context, wherever the denominator
  is a genuine constant. **The corollary matters as much**: a share-of-total calculation
  genuinely *wants* the scoped `[All]` behaviour, because that is what makes "percentage
  of this attorney's cases by visa type" expressible. Decide per calculation which of
  the two you mean, and say so in the description. Six expressions were wrong on one
  model and all six passed `sml-cli validate`, deploy, **and** `validate_mdx_expression`
  — only a live query against a hand-computed reference caught them.
- **Near-duplicate readings of one concept must all be cleared in the same tuple.** A
  follow-on from the above: where three columns are three readings of "occupation", an
  `[All]` on one of them leaves the other two narrowing the denominator, and a query
  that groups by two of them returns 100.00. Put every reading's `[All]` in the one
  tuple.
- **Precompute whatever the query dialect cannot express.** A caller cannot work around
  a missing language feature; they discover it by spending submits on queries that never
  execute. Any concept the questions need that the dialect cannot say is a model object,
  not a caller problem — move the computation into a measure or attribute so that SQL is
  never written. Currently inexpressible on this engine: percentile/median (see below),
  quantile bucketing (`NTILE` rejected — so quartile/decile/percentile-band questions
  are unanswerable unless the band ships as an attribute; `ROW_NUMBER` and `RANK` are
  both accepted, so it is `NTILE` specifically), string aggregation
  (`string_agg`/`listagg`/ `group_concat` rejected, `ARRAY_AGG` accepted but silently
  does not aggregate), JSON aggregation and construction (`json_agg` and
  `json_build_object` both rejected with "Don't understand function"), `COUNT(*) FILTER
  (WHERE ...)` (rejected — use `SUM(CASE WHEN ... THEN 1 ELSE 0 END)`, which is accepted
  and is the working pivot idiom), `GREATEST`/`LEAST`, `IN (subquery)`/`EXISTS`, CTEs,
  and `COUNT(*)`. Re-probe the list against the live engine before each build; a
  workaround that stops being needed is dead weight, and a new gap is a silent failure.

  > **Do not drop this bullet.** A previous revision removed it along with the inventory
  > above, and the cost showed up immediately: `archeology_scan_7` had `NTILE` rejected,
  > then spent five of its twelve `run_query` calls hand-rolling a quartile from
  > `ROW_NUMBER` and hardcoding the row count as the denominator. A caller cannot
  > discover a missing language feature except by paying for it (Q-19).

  > **Some of these are a ceiling, not a workaround.** Where a follow-up asks for output
  > *shaped* as a JSON array or object, no model object substitutes — the answer format
  > itself is unreachable. Count those tasks up front and report them as a capped
  > ceiling on the arm, separately from model defects: three of nineteen query tasks on
  > one database, worth 0.047 of average reward, larger than the entire measured gap to
  > raw.
- **Schema-qualify derived-dataset SQL** with the connection's declared schema —
  `public.<table>` for all current BIRD connections. The engine executes derived SQL
  without that schema on the `search_path`; bare references deploy clean and then fail
  every query with `relation does not exist` (E-02).
- **Never use `|` in derived SQL** (D-01). The engine re-parses and re-emits
  derived-dataset SQL, and a `'|'` string literal does not survive the round trip: every
  query touching the dataset dies with a raw warehouse `syntax error at or near "'|'"`.
  Other literals in the same SQL (`'$'`, `','`, `' km'`, `'Yes'`, `'2FA'`) round-trip
  fine, so this is specific to the pipe character. Validate and deploy both pass; it
  only surfaces on a live query, and it killed every query on two datasets. Where a
  composite key needs representing, use a compound SML leaf key rather than a
  concatenated surrogate. Assert in the generator that no emitted SQL contains a `|`.
  Note this also rules out `||` concatenation — use `CONCAT()`.
- **A numeric cast needs explicit precision and scale, and returns a string.** Bare
  `CAST(x AS numeric)` and `x::numeric` are both rejected, so a caller must write
  `CAST(x AS numeric(p,s))` — which comes back through the SQL interface as a string
  (`'0.27800000000000000000'`), silently defeating any downstream rounding. Ship the
  ratios yourself as calculations rather than leaving the division to the caller (see
  Definitions and labels).
- **Read a real-typed column at its own type; never cast it through ::numeric.**
  Postgres converts `float4` via `float4out` at `FLT_DIG=6`, so `real::numeric` silently
  truncates to six significant digits — 321804.16 becomes 321804. A derived dataset
  casting every source column for tidiness corrupted 941 of 1000 margin balances and 821
  of 1000 realised PnL values, and every figure computed from one. Nothing errors, and
  the values stay plausible to the last digit that survives (M-31). Read such columns as
  double — what the column is, and what a plain SQL reader of the warehouse gets — and
  re-probe the emitted declarations against `information_schema` in a generator gate.
- **Median** must be a `calculation_method: percentile` aggregation with
  `named_quantiles`, never a `metric_calc` — MDX `Median()` is rejected at deploy. On
  the Postgres dialect the percentile sketch is then rejected at query time; ship it
  anyway (correct SML, costs nothing, works when the dialect does) and record the
  limitation. The engine exposes percentile metrics as `<name>_instance_<q>` — the plain
  label returns `Column not found`, and metadata is cached until `list_models
  force_refresh`. (The suffix is the quantile value, e.g. `_instance_0.5`, not the word
  `median`.) Consequence for concepts *defined by* a median rather than reporting one (a
  median split, an above-median flag): the engine's own percentile cannot be used, so
  precompute the median in the dataset SQL — `percentile_cont(0.5) WITHIN GROUP (ORDER
  BY x)` in a cross join — and ship the resulting flag. Otherwise the concept is simply
  unreachable.
- **Postgres has no `COUNT(DISTINCT ...) OVER ()`.** Where a derived dataset needs a
  distinct count per partition, use the dense-rank identity — ranking ascending plus
  ranking descending, minus one — rather than restructuring into a join.
- **Catalog naming**: pick a catalog name not already deployed. Deploying from Design
  Center (the web UI) appends the git branch to the catalog name (`_main`); `sml-cli
  atscale-deploy` uses it verbatim — the two paths publish to different schemas. Pass
  the already-suffixed name explicitly (`--catalog-name="<catalog>_main"`) to publish
  into the existing catalog rather than creating an unsuffixed second copy of every
  model, which is a Q-17 corruption risk. After any redeploy, read the schema back from
  `list_models`; if the ADK eval harness is in play, make its
  `config/environment_backends.yaml` match — a stale entry fails every task with no hint
  that config is the cause. `shared/environment_backends.py` caches that file in a
  module-level dict at first load, so **the services must be restarted** for an edit to
  take effect; a `--backend` flag will not pick it up. Two full runs were lost to a
  config that was already correct on disk.
- Two deployed models sharing a name render corrupted metadata (Q-17); keep deployed
  model names unique across the engine.
- **Q-17b — publishing is not idempotent, and it fails asymmetrically.** A published
  model is materialised as a real relation, and the code path that creates it does so
  with no `IF NOT EXISTS` and no preceding drop, so once the relation exists from an
  earlier publish, metadata calls die with `relation "<Model>" already exists`. The
  asymmetry is the dangerous part: `list_models`, `explore_columns` and `focus_columns`
  hard-fail while `run_query` catches the error, skips path validation and returns
  **correct results** — so the deploy looks healthy while the agent is blind. Neither
  redeploying nor restarting the MCP server clears it; drop the stale relation in the
  catalog schema. Because a shared repo publishes the whole catalog, a redeploy of an
  unrelated sibling model can trigger it. **Before any evaluation run, gate on
  `list_models` succeeding AND returning the expected model count. A working `run_query`
  is not evidence the catalog is healthy** — that is precisely the trap. Three runs
  scored 0.000 on every task before this was understood.
- **The engine caches a failed connection.** After the warehouse has been down, the
  first query through the SQL interface can fail with `Connection <group> unavailable`
  naming a *different* database's connection group. Retry once before diagnosing
  anything.


- **An expression beside a bare column over a derived table emits an invalid `GROUP BY`.**
  When the outer `SELECT` reads from a FROM-subquery and projects any expression
  *alongside at least one bare column*, the planner appends a `GROUP BY` covering only
  the expression's ordinal, and the warehouse rejects the engine's own SQL
  (`column "t_14.X" must appear in the GROUP BY clause`). The boundary is precise:
  an expression **alone** passes, all-bare passes, and a literal passes — and the error
  always names the **bare** column, never the expression. Reproduced on two structurally
  unrelated models, so it is not a modelling artefact. There is **no workaround** when
  the expression spans two joined derived tables — the leave-one-out or
  compare-row-to-its-group-average shape — because it cannot be pushed into either side;
  wrapping the join fails identically at every nesting depth. Precompute that shape.
- **`ORDER BY` on a column the outer `SELECT` does not project returns an internal render
  fault**, `Unmatched physical type … when rendering sql`, rather than the legible
  message the engine emits for the same mistake on other paths. This was the
  widest-reaching failure of the sweep: 20 occurrences across seven of eight databases,
  plus 20 submissions that died without receiving a grade. Put the `ORDER BY` **and its
  `LIMIT`** inside the derived table that projects the sort column, and leave the outer
  `SELECT` with no `ORDER BY`.
- **A two-argument window function fails in the planner** — `LAG(col, 1)` raises
  `requirement failed: A SameTypeWindowFunction always takes exactly one argument`.
  Single-argument window calls plan normally, so lag/lead *with an explicit offset* is
  unavailable and must be precomputed.
- **A scalar subquery in the select list trips a planner assertion**
  (`assertion failed: We already handled attribute values`), so a scalar benchmark cannot
  be placed beside detail rows inline.

- **Several degenerate dimensions on one `dataset` + `key_columns` pair are rejected.**
  `validate` reports it once per dimension *and* once per model, so ten offending models
  produced over a hundred warnings from one mistake. It is a warning rather than an error,
  so `validate` still succeeds and the deploy still lands — which is exactly why it
  survives. Merge them into one dimension and theme with attribute folders (see Modeling
  rules).
- **A dimension over the model's only fact dataset must be `is_degenerate: true`.**
  Without it, `validate` fails with `The dimension '<name>' should be degenerative` — and
  the model file then *still* requires a `relationships:` key, even though a degenerate
  dimension is listed as a plain string with nothing to relate. Emit
  `relationships: []`; omitting the key fails with
  `must have required property 'relationships'`. Note this is not the failing shape this
  prompt warns about elsewhere (a degenerate dimension sourced from a *different* fact) —
  here there is only one fact, and the live conformance check confirms it resolves,
  including for projections that name attributes and no measure.
- **`atscale-deploy` runs `validate` first, and reports the failure as a deploy failure.**
  In a shared repo that means a validation error in *any* model — including one you are
  still writing — makes the deploy look broken for reasons that have nothing to do with
  the deploy, with no mention of validation in the message. Run `validate` on its own
  before concluding anything about a deploy, and read its output for **errors**
  specifically: in a repo that already prints a hundred warnings, one error scrolls past.
- **The CLI and the web UI disagree about the latest SML version, and the CLI is what
  deploys.** Observed 2026-08-20: Design Center reported 1.9 as latest while `sml-cli`
  2026.3.0 supported 1.6 and 2026.5.0 supported 1.7, with no released stable CLI
  supporting 1.9 at all (only a release-candidate line). Setting `catalog.yml` to the UI's
  number just moves the warning onto the deploy path. Declare the version the CLI
  supports, upgrade the CLI first if you want a higher one, and expect the UI to keep
  warning.

## Build process

- `A deterministic, re-runnable generator script (spec → emitter). Changes are made by
  editing the spec and re-running, never by hand-editing emitted YAML — any identity
  that must survive (model name, catalog) belongs in the generator as a parameter, or
  regeneration silently reverts it.`
- Have the generator self-audit its output: duplicate labels, unreferenced datasets,
  metrics naming columns no dataset defines, dangling cross-references between
  descriptions — `sml-cli validate` misses all of these. In a shared repo, also assert
  that no `unique_name` or `label` collides with a **sibling model**; print only the
  colliding strings so the check does not put another model's design in your context.
- **Assert discoverability at build time, not only at acceptance.** Keep a list of the
  question wordings the task set actually uses and fail the build if any of them matches
  no published description. Finding these one at a time as they surface is slow and
  repeats: the same class recurred on three consecutive acceptance runs before it became
  a build check, and 34 phrases are currently gated. The check must **parse the emitted
  YAML and normalise whitespace** — `safe_dump` line-wraps long descriptions at column
  100 and the consumer sees the folded value, so grepping raw file text reports false
  failures on phrases that are in fact present. Note the gate passing is necessary, not
  sufficient: probe the *deployed* model with the same phrases too (see Acceptance gate
  3), because a build-time list only covers the wordings you thought of.
- Before validate/deploy, dry-run every derived dataset's SQL directly against the
  warehouse (row count, declared grain is unique, every declared column resolves, plus a
  hand-recomputed spot value). This catches same-level alias references and formula
  transpositions that no SML layer can. Pin any independently-derived constant (a
  concentration index, a hotspot count) as an assertion, so a later SQL edit that
  changes it fails loudly.
- Follow the SML authoring skills from `get_sml_skills`; `sml-cli validate` clean;
  commit and push before deploying (deploy resolves the model from the git remote — an
  unpushed fix deploys the old model and looks like the fix did nothing); deploy.
- Record every post-build change — the kind of change and why, naming the tracker row if
  it works around a defect — in BIRD-Interact-ADK's `docs/model-change-log.md`.


- **Run the masked-threshold gate with `--kb`, always.** Without it the gate cannot read
  the concept types, the `calculation_knowledge` exemption is silently defeated, and a
  masked calculation term whose named formula legitimately ships is reported as a leak.
  This produced a false defect report that survived into a commit message before it was
  caught. A gate invoked without its inputs must fail loudly rather than judge.
- **A gate that cannot find its brief does not run, and nothing says so.** Of eight
  models, one used a non-standard brief filename and two had no brief at all, so the
  question-leakage gate had **never run** on them. When briefs were reconstructed and the
  gate finally ran, both were failing — 23 and 6 leaked phrases. Ship a brief for every
  model at one canonical path, produced by `extract_brief.py`, have the gate discover it
  by convention rather than by an argument someone must remember, and treat a missing
  brief as a hard failure rather than a skip.
- **Absolute paths make a gate machine-locked.** One model's KB paths were two hardcoded
  `/Users/<name>/…` entries, so its masked-threshold gate could only ever run on one
  person's checkout. Try environment variables first and keep the hardcoded paths last as
  fallbacks.
- **Triage question-leakage flags against the KB's own term list before rewording
  anything.** The gate matches 6-word runs and cannot tell "the model copied the
  question" from "the model correctly names the KB concept the question also names":
  five of one model's six flags were the legitimate concept name
  `Maintenance Cost to Revenue Impact Ratio`. Rewording those would damage a correct
  model to satisfy a string match. Judge each flag; only genuine question phrasing —
  colloquialisms like "sending to the grid right now", or an `Answers '<question>'`
  clause — is a leak.
- **A discoverability gate that *requires* phrases can enforce a leak.** One generator
  asserts that 59 discovery phrases are present in published descriptions — the inverse
  of a leakage check. Several of those probes had been harvested from the evaluation
  questions, so the build now *fails* if they are removed, and descriptions wrap them in
  `Answers '<question fragment>'` clauses that quote the question verbatim. A
  discoverability probe must come from the KB or the column's own meaning, never from a
  question, and no description should ever contain `Answers '<question text>'`.

- **Put the rule in the shared emitter, not in each generator.** This was the
  highest-leverage change of the 2026-08-20 round. Where a repo has grown a common build
  package — emitter, gates, type probe, dry-run harness — a model's generator should be a
  five-line driver, and a rule learned on one model belongs in the shared half where every
  model gets it. Measured: one 160-line pass fixed twelve models at once; the same fix
  hand-propagated would have been twelve edits across 39,000 lines of generator code, and
  the reason the defect existed in twelve models at all is that the earlier generators
  were copies and a rule learned on one was never propagated. When you do add a shared
  pass, apply it **before** emission so the emitted YAML, the model file and every gate
  see the same shape — a pass that runs after emission leaves the gates validating
  something that is no longer what ships.
- **A mechanical rename that picks its target from inside the group inherits one member's
  identity.** Merging N themed dimensions into one needs a name, and "prefer the member
  whose name ends in `Record`" looks like a safe rule until a member is called
  `<Entity> <Theme> Record` — then thirteen themes end up filed under one of them, and
  every other theme is mislabelled. Derive the name from something **outside** the group:
  test the candidate against the dataset's own name (`<dataset stem> Record`) and fall
  back to a name built from the dataset (`<dataset stem> Profile`) when no member
  qualifies. Caught before it shipped only because the chosen name read wrong in the
  build log — so print what a mechanical rename decided, every time.
- **Verify a mechanical refactor by diffing the queryable surface, not the file counts.**
  A `unique_name` grep across the emitted YAML reported a 21-object loss per model, which
  is alarming and wrong: it was counting hierarchy level entries alongside attributes. The
  check that answers the question is a set diff of the **secondary attributes** and the
  **visible level attributes** before and after — which came back zero lost, zero gained,
  across all twelve models, with the only removals being hidden key attributes, one per
  absorbed dimension, which is the point of the merge. Line counts, file counts and
  regex tallies all move for uninteresting reasons; the queryable surface does not.
- **Make the KB triage mechanical.** The rule above says to triage question-leakage flags
  against the KB's own term list by hand before rewording anything. Do it in code instead:
  exempt any matched run that appears verbatim in a KB entry's `knowledge`, `definition`
  or `description` field. Observed: the gate flagged four 8-word runs in one flag's
  description, which was quoting its KB definition verbatim *because this prompt requires
  that*, and which the task's question happened to paraphrase closely. Hand-triage gets
  this right once and then someone reworders it next time; the exemption gets it right
  permanently, and what remains flagged is genuine question phrasing.
- **Warnings are not free, and a hundred of them is a broken signal.** One repo printed
  over a hundred `validate` warnings from two underlying causes. Nobody read them, so both
  causes survived for months and a genuine new error in the same output was easy to miss.
  Treat the warning count as something to drive to near zero and keep there; the value is
  not the warnings themselves but that the output becomes worth reading again. When some
  warnings must stay, say which and why, so the residue is a known set rather than noise.

## Acceptance — not done until all four pass, with evidence

`validate` is layer 1 only; every defect class above deployed clean and only surfaced
via live `run_query`, `get_outbound_queries`, or reading the agent's actual failed
queries. Budget time to test live, and never take a plausible number as evidence a
feature fired — read the outbound warehouse SQL for any semi-additive or window-based
construct.

1. **Exactness.** Smoke queries through the model exact-equal to the same query on the
   source database. The data is synthetic — never judge a result by plausibility. The
   reference query must read the source column raw: where it shares a cast with the
   model's derived SQL, both sides are wrong in the same direction and the gate passes
   on corrupted values — which is exactly how the `real::numeric` truncation above
   survived it.
2. **Conformance.** Per dimension, one measure-by-attribute query per fact that
   dimension should reach, returning non-empty. Empty or erroring is a model bug, not a
   limitation to document — the sole exception is metrics already documented as
   dialect-blocked (e.g. percentile medians on Postgres). **Read the values, not just
   the row count**: the `[All]`-tuple defect above produces non-empty, plausible, wrong
   numbers and would pass a non-emptiness check. Compare at least one calculated index
   against a hand computation. Measure-by-attribute queries alone cannot see a missing
   attribute-only path, since adding a measure is what makes that case resolve: add one
   projection per dimension pairing that names attributes and no measure.
3. **Discoverability.** Search the deployed model with question-style paraphrases only,
   never an object's own name — take the probe phrases from the task briefs' own
   `amb_user_query` wordings; the intended object must surface. If not, fix the
   description.
4. **Coverage.** One passing query per question shape: group aggregate,
   filter-by-classification then measure, superlative/top-N, cross-fact, entity-level
   detail, group-relative comparison. Close any gap or state explicitly what was left
   out.


5. **Read the deployed model's folder count back from `list_models`.** `folders: (none)`
   is a one-line symptom of a model with no cheap discovery channel at all — every
   `explore_columns(folder=…)` returns nothing, and the agent is left guessing keywords
   against the whole catalog. Observed on a model that had already been through a full
   evaluation round with nobody noticing, because nothing errors and the model looks
   complete from the YAML. While you are there, check the measure and dimension counts
   against what the generator printed: a silent mismatch means the deploy did not take
   what you think it took.
6. **Verify a mechanical refactor by diffing the queryable surface, not the file counts.**
   Where a change was applied by a script across many objects, the acceptance question is
   "which queryable names moved", and the answer is a set diff of the secondary
   attributes and the visible level attributes before and after — not a line count, not a
   file count, and not a `unique_name` grep, which counts hierarchy entries alongside
   attributes and reported a 21-object loss where the true loss was zero. State the
   expected removals up front (hidden keys, one per absorbed dimension) so the diff has
   something to be checked against rather than merely inspected.

## After acceptance — the gates prove correctness, not usability

The most important thing the `cybermarket_pattern` build had to say. That model passed
all four gates, validated clean, deployed clean, satisfied every rule above — and its
first evaluation run scored 0.295 average reward, level with the raw text-to-SQL
baseline. Every point of lift after that came from work this prompt previously did not
ask for. Expect the same, and treat a first run at baseline as the start of the work
rather than a failure.

- **When *both* arms score 0.000 on every task of one database, suspect the harness
  before the model — and check whether the database's name is unusually long.** A raw
  text-to-SQL baseline does not go 0/19; if it does, something structural is broken.
  Observed: BIRD's `instance_id` already begins with the database name, and the harness
  prefixes it again, so the per-task database name is the database name twice. At 32
  characters that exceeded Postgres's 63-byte identifier limit, which truncates **with
  only a NOTICE while `createdb` still exits 0** — so all tasks collapsed onto one
  physical database, and the Phase-1 snapshot collided with its own source, converting
  every phase-1 *pass* into a recorded failure. Phase 2 was unreachable for the whole
  database in both arms. The fingerprint of a swallowed pass is worth knowing: an error
  string in the submit result rather than a grading verdict.
- **Read the agent's actual submitted SQL** in the results JSON for every failing task.
  Almost every defect in the classes added in these revisions — object competition, an
  invisible phrasing, an inexpressible shape, a string-typed cast, a prescriptive
  description — is invisible to `validate`, invisible to the four gates, and invisible
  to live `run_query`, and obvious in one look at what the agent wrote. Note the graded
  submission is the **last** trajectory entry carrying an `sql` key, not the first.
- **Classify every failure mechanically rather than by eye.** Re-execute each submission
  against the engine and the reference against the warehouse, then score them with the
  harness's own comparison function under four settings — as graded, order-insensitive,
  case-folded, both. That splits the failures into tie-order, casing, wrong-shape and
  genuinely-wrong in one pass, and it is the only cheap way to know which of them a
  model change could possibly address. Wrong *shape* — a different column count or row
  count from the reference — is not a model defect at all; the model does not control
  the caller's `SELECT` list.
- **Predict a model fix's task-level payoff at zero, and price it that way.** Measured 3
  for 3 on ETF: a defect was found, fixed, verified against the reference, and the task
  did not move, because the agent's next choice up the stack became the binding
  constraint — it stopped projecting a misleading rank but never computed the right one;
  it stopped computing a wrong composite but then gated the population on the wrong
  count. A model fix reliably *removes a known-wrong answer*; it does not reliably
  produce a right one. Score it on that basis, and don't fund a model change on a
  predicted score gain.
- **Verify sufficiency for free before spending a run.** Take the agent's own stored
  submission, run it through `run_query` against the fixed model, and diff it against
  the reference result — value by value, row count and all. That costs nothing and
  answers "is the model now capable of the right answer" definitively. Only then decide
  whether a scored run is worth it. Doing this caught a fix that was
  correct-but-insufficient before any benchmark spend, and isolated the one remaining
  condition exactly.
- **Make the ask-the-user trigger name the shape of the answer to request.** This was
  the only change across four rounds on `labor_certification_applications` that moved
  the score. Measured over 170 `ask_user` exchanges across both arms: a question
  proposing **explicit options** got a specific answer back **71-94%** of the time, an
  open-ended one **25%**; and after a qualitative reply both arms **gave up rather than
  re-asking about 60% of the time**. So a trigger reading "ask the user for the complete
  definition" leaves the lever unused. Write it as: *ask as a closed question with
  explicit options — the exact numeric cutoff, and the exact label text for each band —
  use their spelling verbatim, and if the answer comes back qualitative ask again
  offering options rather than choosing one yourself.* Saying what *kind* `of answer to
  request publishes no cutoff. Effect: +0.040 average reward, pooled over six runs
  either side, and the mechanism confirmed in the trajectories (re-ask rate 38% → 50%)
  rather than assumed.`
- **"Confirm with the user" in a description only works if the agent asks the question
  *open*.** Observed on the same task twice: asked as a genuine two-option question
  ("the total count, or only those with a computable score?") the agent chose correctly;
  asked as a leading one ("what minimum number of *scoreable* entities...") the
  simulator simply ratified the premise and the task failed. You cannot fix the framing
  from the model, so where a wrong choice is silent, make the two objects separately
  named and separately documented with live counts, and expect to lose the task some
  fraction of the time.
- **Check what the user simulator actually said before blaming the model.** A task can
  be unwinnable because the simulator's own answer differs from the reference: on one
  task the model produced every count and percentage exactly right and failed only on
  category labels, because the simulator said "4-6 Months Before" where the reference
  wanted "Optimal Window (4-6 Months)". No modelling and no better asking recovers that.
  Record it as capped.
- **Verify a suspected unfairness before reporting it.** It is easy to find a mechanism
  that appears to hand the raw arm something the semantic arm is denied — and to be
  wrong. Observed: the raw arm was seen fetching masked knowledge entries verbatim,
  which looked decisive, until a per-task check showed the harness filters each task's
  own masked entry and there were **zero** same-task fetches. The 51 hits were of terms
  masked on *other* tasks. Check the mechanism at the granularity the claim needs before
  it reaches a report.
- **`n≥3 per arm before believing any delta, and spend the repeats on the noisier
  arm.`** A single run moves by roughly ±0.10 average reward from agent variance alone;
  the measured noise floor on a final `cybermarket_pattern` configuration was sd
  0.012–0.018. A before/after comparison built from one run per arm says nothing, and it
  is easy to spend a day chasing a change that was noise. Run-to-run variance is also
  *asymmetric*: measured on a 19-task ETF set, the semantic arm moved on 1 task of 19
  across repeats (sd 0.71 points) while the raw arm moved on 7 of 19 (sd 0.91 points,
  single-run totals ranging 5.40-7.40). 13 of 19 raw tasks were perfectly stable and the
  whole spread came from six. The semantic layer appears to constrain the agent to a
  narrow path while raw SQL lets it re-pick a formulation every run. Budget roughly **4
  repeats on raw, 1-2 on the semantic arm**; a single run per arm can read anywhere from
  +7 to +32 percentage points of lift on identical code.
- **Pool across rounds, test properly, and know the run count your question needs before
  spending it.** Two independent three-run blocks either side of a change are far
  stronger evidence than one three-run comparison, and they cost the same. Run an exact
  Mann-Whitney on the pooled samples rather than eyeballing means: on
  `labor_certification_applications the +0.040 improvement reached p = 0.167 at 6 vs 6 —
  real enough to keep, not enough to claim — and the residual −0.037 against raw came
  out at p = 0.298, i.e.` **not distinguishable from noise**`. Before opening another
  round, compute what it would take: at sd ≈ 0.04, detecting a 0.037 gap at 80% power
  needs about` **18 runs per arm**, a 0.075 gap about 4. If the honest answer is "these
  are the same", say so and stop rather than buying a sixth round.
- **A per-task pass rate of "flaky" is data, not noise to be smoothed away.** `Track
  which tasks are always/never/flaky per arm across rounds. A task moving never → flaky
  after a change is the signal that the change worked; a phase-2 count oscillating 0, 2,
  0, 3 across four rounds is one flaky task and should not be reported as a regression.
  Before attributing any movement to your change, check whether the change touched any
  object the moved task actually references — the answer is often no.`
- **Compute lift on the task intersection, never on arm totals**, and never quote a
  single pair of runs. The raw arm runs the Management-category tasks that a read-only
  semantic layer structurally cannot serve; drop them from both sides. Quote the mean of
  the repeats with its range, in percentage points, with relative alongside. One outlier
  run paired against one good run produced a headline that was double the settled value.
- **Sort failures into model-fixable and not, and say which is which** before changing
  anything. A task whose question turns on an ambiguity marked `is_mask: true` cannot
  honestly be fixed in the model — that failure is the firewall rule working, not a gap.
  Likewise a task whose expected answer is non-unique (a `LIMIT` across a tie) is capped
  regardless of the model. Reporting these together with real defects makes the model
  look worse than it is and invites a dishonest fix.
- **Tie-order is not a model problem, and the grading flags will not close a gap.**
  Where the reference's `ORDER BY` key is constant across its rows, its row order is
  arbitrary plan order following *no* rule — verified against alphabetical,
  reverse-alphabetical and every other column. A raw arm tends to reproduce it by
  construction (same engine, same plan, similar SQL) while a semantic layer's different
  engine cannot, so strict order comparison quietly favours raw. It is tempting to
  enable `grading_tie_tolerance` or `grading_casefold` — measure first: applied
  **symmetrically**, both lifted each arm by exactly the same +0.070 and the gap was
  unchanged. And note `grading_casefold` as implemented is semantic-path-only, so
  enabling it as-is moves one arm and would close a gap for entirely the wrong reason.
  Leave the public benchmark settings alone unless you have measured that a change is
  symmetric.
- **Before each run, verify the environment with the harness's own credentials**`, not
  through your own MCP connection: run a full initialize → session → tools/call`
  handshake using the token the harness will use. Three runs were lost to an HTTP 401
  that a check through a different connection had pronounced healthy. Combined with the
  Q-17b gate above, these two habits account for six voided runs — more elapsed time
  than every model fix in that build put together.
- **Know when to stop.** Four measured rounds on `labor_certification_applications`
  produced one probable win (the ask trigger), one regression introduced and withdrawn
  (a KB concept shadowing a masked one), and two of the model's own descriptions found
  to be steering wrong. The arm went from a clear deficit to statistically
  indistinguishable from raw. The residual was made of output shaping, masked label
  strings, tie-order and a dialect gap — none of which a semantic model controls. When
  the remaining failure classes are all outside the model, say so and write it up; a
  database that reaches parity honestly is a result, and so is one that does not.
- **Say when a change makes earlier runs non-comparable.** A refactor that touches many
  models at once — a shared-emitter rule, a dimension merge, a naming convention — changes
  the discovery surface of every model it touches, so any earlier number for those models
  measures a different artefact. That is not a reason to avoid the refactor; it is a
  reason to land it deliberately and label it, because the alternative is someone reading
  a pre-change number against a post-change one and attributing the difference to
  whatever they were actually testing. Take the baseline first if you still need it, or
  accept that the comparison starts over.
- **Run hygiene is a whole class of voided runs, and the interpreter belongs in it.** This
  prompt already says to verify the environment with the harness's own credentials rather
  than through your own connection. Add the interpreter to the same check: observed, the
  service-start script resolved a project-local environment while the run script called a
  bare `python`, so the services ran healthily for hours on the right interpreter and the
  runner died instantly on `ModuleNotFoundError` — a failure that looks like a broken repo
  and is a two-line disagreement between two scripts. Where several scripts need the same
  interpreter, resolve it in one place; where they cannot, have each one assert it can
  import a dependency it needs and fail with a sentence instead of a traceback.
