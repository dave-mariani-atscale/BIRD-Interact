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
exposed three of its design premises as wrong, and the `virtual_idol` deep dive of
2026-08-24 — four measured runs against one 19-task database, which is what finally
showed how much of a single run's score is noise, and turned up a join-path bug that had
been handing 26 entities another entity's data since the model was built, and the
`mental_health` failure review of 2026-08-25 — a 20-task arm read submission by
submission against a re-run reference, which produced four new rules and, more usefully,
caught two changes that had already been made **in violation of rules this document
already carried**. Each rule
traces to a concrete, observed failure;
database-specific details and anything derived from gold SQL were stripped. This file
supersedes `create_etf_prompt.txt`; the modeling rules are also mirrored in the MCP
`sml-create-metric` skill — propagate new lessons to both.

Replace `<db>` throughout (e.g. `exchange_traded_funds`, `solar_panel`).

**What changed in this revision (group-context calculations pass, 2026-08-31, latest).** One new
capability, one silent-wrong-data trap, one mandatory test, and three engine constraints — from a
day spent trying to express "rank X within its group" and "the best value in the group", the shape
behind **64 of 1,200 gold queries across 15 of the 22 databases**. The headline is that this is a
**DAX** job, not an MDX one, and the previous revisions of this document pointed the wrong way.
Listed so each can be reviewed or reverted independently.

1. **New, and the most useful of this round**: rank-within-group and rank-within-a-filtered-
   population are expressible today as `RANKX(ALL('t'[Entity]), [Measure], , DESC[, DENSE])`.
   Verified live on three models; ranks restart per group and recompute over a narrowed
   population. Five such measures shipped (Modeling rules, group-context section).
2. **New, silent wrong data**: `CALCULATE([Measure], ALL('t'[Entity]))` looks like the same thing
   and is **query-scoped, not group-scoped**. At entity grain with two groups in the query it
   hands every row the maximum over the whole slice. It passed six single-group checks before a
   two-group query caught it (group-context section).
3. **New, mandatory test**: a group-context measure is not verified until **two groups are broken
   out at entity grain in one query**. Single-group and group-grain tests both pass on a measure
   that is silently query-scoped. This is the test that caught item 2 (group-context section;
   Acceptance).
4. **New**: a rank inherits its base measure's **conformance envelope**, so it can only be grouped
   by dimensions that base measure conforms to. Two descriptions shipped naming groupings that then
   refused; in one database the two candidate base measures had **disjoint** conforming fact groups,
   making the gold's shape unreachable at any grain (group-context section).
5. **New**: before ranking anything named `Mean/Average X`, check for a `(Pooled)` twin. Ranking the
   avg-of-avgs where the KB defines a pooled ratio changed a graded value from 0.11 to 0.12
   (group-context section).
6. **Corrected**: the standing "Reach for MDX before filing an engine request" advice now leads with
   DAX for group context, and carries the warning that MDX `Rank` **silently returns 1 for every
   row** when grouped by a secondary attribute (Modeling rules; Engine constraints).
6b. **New, and the sharpest edge in this document — `RANKX` has that same silent-`1` defect.** A rank
   is correct only where the query's grouping attributes are all named in its `ALL(...)` exclusion;
   group by one more attribute of the same entity and every row comes back rank 1, with no error.
   Two measures that had been verified and shipped were silently broken by it. Read the rule in the
   group-context section and the constraint in Engine constraints before publishing any rank
   (ATSCALE-52370).
7. **New engine constraint**: `HAVING` on a rank measure leaks an internal plan dump instead of
   filtering. "Top N per group" is the main reason to define a rank, so every rank measure's
   description must carry the FROM-subquery rewrite (Engine constraints; ATSCALE-52369).
8. **Reported, not changed**: a `(Pooled)` metric that returns NULL where the KB's own formula would
   `COALESCE` a missing component to zero mis-ranks 30% of its entities — and puts the ones that
   should lead the group last. Left alone deliberately: it is a shared measure and a missing-data
   judgement, not a benchmark detail to reverse-engineer (group-context section, Reported).

**What changed in the previous revision (`cybermarket_pattern` pass, 2026-08-27).** Three
description rules and a ceiling audit, from a 20-task database where the semantic arm has sat at
0.585 / 0.57 / 0.585 against raw 0.535 for three runs with the same eight tasks at 0 every time.
Read with `probe_pred.py` first (free): four of those eight (`_1 _4 _5 _9` phase 1) already
return the right rows from the deployed model and fail only on the order of tied rows -
629 distinct sort values over 954 rows, 799 / 807 / 649 over 1000 - and pass under
`GRADING_TIE_TOLERANCE`; three phase-2s (`_1 _5 _19`) are `LIMIT 1` / `LIMIT 10` over a tie;
two (`_2 _7`) are references five or six columns wider than the question. None of that is a
model object. What was the model's: the agent burned coins on things the descriptions left
open, which the three rules below close. Listed so each can be reviewed or reverted independently.

1. **New**: a description must not name an attribute the model does not publish. The
   orientation text and a measure both pointed at an `Anonymity Tier` attribute that was
   computed in dataset SQL and never shipped; two tasks spent 2-4 calls hunting for it and
   one `focus_columns` errored on the name (cybermarket_pattern section).
2. **New**: when an entity's display name is not unique, the key attribute's description says
   it is what a listing SHOWS - not only what to group and count on - and the name's says it
   cannot identify a row. The old text called the code "an internal code rather than a display
   name", and two listings each spent 2 coins asking "name or code?" (cybermarket_pattern
   section; paired guidance bullet).
3. **New**: an alias attribute (`<Entity> Identifier Code` beside the `<Entity> Code` level)
   says it is row-for-row identical and that swapping it in never changes a result. Two tasks
   resubmitted a failed listing with the twin swapped in, 3 coins each, same verdict
   (cybermarket_pattern section).
4. **Reported, not changed**: the MCP `run_query` validator unions every column reference in
   the statement before checking conformance, so a query built as two individually conforming
   subqueries joined on the entity key is refused as if it were one flat projection; a
   nine-column vendor listing died on it five times (cybermarket_pattern section, Reported).

**What changed in the previous revision (`solar_panel` pass, 2026-08-27).** Six rules and one
application of an existing one, from the 20-task database that carries the largest lift in the
suite (9.7 / 13.1 / 12.8 of 20 against raw 8.4) and still had six tasks at 0 in every run. Read
with `result_diff.py` and free probes first: five of the nine failing phases were already
reachable with the deployed model and failed on agent behaviour, which is what the paired
guidance bullets address; the model rules below are the other four. Listed so each can be
reviewed or reverted independently.

1. **New**: a model has ONE age convention, and it is the warehouse's own date arithmetic
   (`EXTRACT(YEAR FROM AGE())`, whole completed years). The model carried the current age in
   whole years and the snapshot age as `days / 365.25`, so one KB rate had two values for the
   same row, differing on 449 of 462 rows. The continuous reading ships as a `(Fractional)`
   twin (Modeling rules, solar_panel section).
2. **New**: a rate defined "since commissioning / since installation" is undefined before that
   date - NULL, not a negative number - and the description states how many rows that is.
   445 of 998 snapshots here predate their plant's go-live; `count(*) where <event> <
   <start>` finds this unaided (solar_panel section).
3. **Applied**: the JSON-`::real` rule, on a SUM this time. 57 per-snapshot rates summed at
   75M magnitude differed from a plain reader at the first decimal when widened first; every
   row-level value agreed to six digits. Every REAL field in the two JSON columns now reads
   `::real` (29 casts) (solar_panel section).
4. **New**: a per-record rate or score whose entity has several records states its grain and
   says that "across the plants / across the assets" is an open slot - every record, or one
   per entity - to be asked, not chosen (solar_panel section; paired guidance bullet).
5. **New**: an absolute amount and the ratio built from it name each other as amount versus
   proportion and say they are not interchangeable (watts lost versus loss ratio)
   (solar_panel section).
6. **New**: a recorded monetary or loss column says it is realised and historical, and that a
   projected / potential / lifetime figure is a formula the user supplies (solar_panel
   section; paired guidance bullet).
7. **Applied**: the uniform-flag rule - six non-deleted `domain_knowledge` cutoffs shipped,
   including one whose live count is zero, which is still worth shipping (solar_panel
   section).

**What changed in the previous revision (`cross_border` pass, 2026-08-27).** One rule
CORRECTED and five twins, from a 19-task database whose semantic arm sat at 0.22-0.32
against raw 0.04, with ten tasks at zero in every run:

1. **Corrected**: a masked question term does not withhold its KB entry. The harness's
   knowledge tool strips only `knowledge_ambiguity.deleted_knowledge` ids, so a masked
   `domain_knowledge` cutoff whose entry is not deleted is served verbatim to the raw arm
   on every task. Withhold only DELETED cutoffs; publish the rest under the KB's own name
   and cutoff, never with the question's wording as an alias (Answer-key firewall; the
   2026-08-27 cross_border section).
2. **New**: "one divided by X" over a 0-100 percentage column has two readings 100x apart;
   the KB's own downstream cutoff picks the bare one, the other ships as `(Control As
   Fraction)` and is carried down every consuming formula.
3. **New**: the KB's `children_knowledge` edge decides a formula's operand; a
   `value_illustration` gloss with the same words is the competing reading and ships as
   the named twin.
4. **New**: a CASE formula's "otherwise" branch covers the entity with no satellite row;
   the null-preserving reading is the twin, not the default.
5. **New**: an ordinal ladder with an unnamed stored level gets the extended-ladder twin;
   a coalesced provenance attribute gets an as-recorded twin per source; a formula used
   in a "below X" screen gets its missing-input-as-zero twin.

**Previous revision (`reverse_logistics` pass, 2026-08-27, late).** Two new
rules from a 20-task database whose semantic arm sat level with raw (0.41 against 0.42)
with eight tasks at zero in every run, six of them reachable once the model published the
right population and the agent asked the right question:

1. **New**: a pooled ratio's numerator and denominator must be totalled over ONE
   population. When the two terms live on records with different coverage (recovery value
   on the 995 costed returns, days lapsed on all 1500), the pooled figure divides over the
   intersection, and the denominator's total over that population ships as
   `<Measure> (<Population>)` beside the bare all-rows total — because a question that asks
   to see the ratio's components beside it means the same-population totals (Support sets).
2. **New**: when the warehouse's own record holds MORE cost lines than the KB formula
   names, the sum of every recorded line is a competing reading of "cost" even though no KB
   entry defines it — the record's own group names do. Ship it as `<Formula> (All Recorded
   Cost Lines)`, carry it to every formula downstream (the profit impact flips sign here),
   and have the bare readings name it with both figures (Modeling rules, twins).

**Previous revision (`museum_artifact` pass, 2026-08-27, night).** Five new
rules and one correction of the record, from a 20-task database whose semantic arm sat at
0.19 against raw 0.12, where the reference answers are decided by two source tables that
hold 10 and 3 rows. Listed so each can be reviewed or reverted independently.

1. **New**: an average over a *named list* of inputs has exactly the two readings the
   missing-input rule already names — strict, and coalesce-to-zero over the full
   denominator. Averaging over "whichever inputs are present" (renormalising the
   denominator) is a third policy no source states, and it was this model's *bare* object:
   the reference's every use of the formula was the zero reading, and the bare one matched
   none of them. The strict reading is bare because the KB writes no COALESCE (rule 3 of
   the previous revision); the zero twin ships beside it (Support sets).
2. **New**: when the KB names *example* members of a set ("various environmental factors
   like light, temperature and humidity") and the warehouse stores a superset, the
   named-example set is a reading in its own right beside the stored set — a builder who
   read only the KB shipped exactly those three, and two reference answers use them
   (Sources).
3. **New**: an entity with several child readings gets its own reading summaries at entity
   grain — latest reading, average of readings, and every KB verdict evaluated on each —
   even when the fact already carries a reading row-aligned with each event. "A showcase's
   current temperature" is the showcase's latest reading; the aligned one differed on 44
   of 1000 rows, and a per-showcase verdict ("failing showcases", "unstable showcases")
   is a count of showcases, not of the fact rows that carry them (Grain).
4. **New, and cheap**: a KB classification whose cutoff is masked still owns its *label
   vocabulary*; the labels go in the descriptions of its inputs, with the instruction to
   ask for the cutoff. An agent that asked for and received the cutoffs then failed on
   'Over-Exposed' against the KB's 'Over Exposure' (Answer-key firewall).
5. **New**: enumerate a JSON profile's keys from the data before deciding what "does not
   exist". Seven of the ten stored sensitivity factors had been recorded in the change log
   as "agent inventions" and left unpublished for a week; the agent had been asking for
   columns the warehouse held (Sources).

**Correction of the record**: the 2026-08-20 note "the warehouse holds only light,
temperature and humidity sensitivity" was wrong; `SensitivityData.env_handling_sensitivity`
stores ten rated factors under four keys.

**What changed in the previous revision (`disaster_relief` pass, 2026-08-27, evening).** Four
new rules and one sharpened, from a 12-task database whose semantic arm sat at 0.10–0.13
against raw 0.08 with ten tasks at 0 in every run. Hand-grading gold against the deployed
model localised seven of the ten to one structural fact the build had reasoned away, and
two to the value pipeline. Listed so each can be reviewed or reverted independently.

1. **New, and the one that generalises furthest**: when several satellite tables carry
   the *same* foreign key with *identical* values wherever two are present but *different
   coverage*, the coalesced reference is the bare object and each satellite's own
   reference ships beside it as `<Entity> On <Record>`. A plain SQL reader that reaches the
   entity *through* one record gets that record's rows — "operations for catastrophic
   disasters" was 30 rows through the staffing record and several hundred through the
   coalesced one — and the reference answers pick a record per task with no cue in the
   question. The bare description leads with the coverage counts and routes the
   population to the user (Sources; Placement and conformance).
2. **New**: a KB operand that names a stored column by its documented meaning
   (`total_operational_costs` against a column documented "Operational costs") is read as
   that column; a composite that another KB entry defines under a *different* term
   ("total cost is the sum of the four cost lines", for the cost per person) ships as the
   qualified twin. The reference used each reading in a different task, which is exactly
   why both must exist under distinct names (Modeling rules).
3. **New**: the coalesce policy is a per-formula check against the KB's own text, and it
   has to be *asserted*, not stated. A model that documented "where the KB does not state a
   coalesce, a missing input leaves the formula null" shipped a gridlock index with its
   personnel term coalesced to zero over 943 of 1000 events — and read that term as a
   *derived* KB concept (staff plus volunteers) where the warehouse stores a column
   documented as the total. Both are the read-the-stored-column rule again (Modeling
   rules).
4. **New**: a formula whose inputs sit on a narrow record (a ratio that needs the staffing
   row) gets a reading judged only over that record, beside the reading that lets SQL's
   three-valued `OR` decide it over every row — the two select 54 and 955 (Support sets).
5. **Sharpened**: the declared-type rule for JSON numbers (previous revision) is not only
   about the cast — it is about *where the addition happens*. `real + real + real` sums in
   float32 before any division, and a model that widened first was right to six digits and
   flipped 4 of 405 halved indexes at the second decimal, because halving parks values on
   `.xx5` boundaries (Engine constraints).

Two things this pass did **not** put in the model: the reference's cosmetic `LOWER()` on a
region code no question asks for (a grading question), and a one-day disagreement between
the warehouse session's `CURRENT_DATE` (Postgres server timezone Asia/Hong_Kong) and the
engine's JDBC session (local time) that caps every wall-clock formula for fifteen hours of
each day — a harness fact, recorded under After acceptance.

**What changed in the previous revision (`planets_data` pass, 2026-08-27, later the same day).**
Five new rules and one reversal, from a 19-task database whose semantic arm sat level with
raw (0.27–0.43 against raw 0.37, single runs) with nine tasks at 0 in every run. Hand-grading
each failing task's gold against the deployed model localised most of them to the *value
pipeline* again, but of a different kind from the robot pass: not the warehouse's types this
time but the **constants** the model had chosen. Listed so each can be reviewed or reverted
independently.

1. **New, and the one that generalises furthest**: a physical constant a KB formula needs
   but does not state (G, a solar mass, an astronomical unit) is written out at its
   standard published value and **composed inside the formula** — never replaced by a
   pre-collapsed textbook shortcut (Earth's escape speed times a square root, the Sun's
   mean density, GM☉). Every shortcut is right to three or four digits and wrong after
   that, and the grader compares two decimals of values that can be 585 or 1.5e20
   (Modeling rules).
2. **New**: a number the warehouse holds as JSON text has the type its column meaning
   declares, and a KB formula reads it through that type (`::real`) before widening —
   the warehouse-types rule of the previous revision, extended to JSON. A ratio of
   extremes moved by 126 units at two decimals between the two readings (Modeling
   rules, beside the warehouse-types rule).
3. **Reversal**: a KB formula over two lengths (or two masses) is a formula over one
   unit. Publishing the dimensionally inconsistent "as written" reading — solar radii
   over AU — as a twin beside the converted one was a mistake this document had endorsed:
   it invited the agent to ask which reading was meant and the simulator answered wrong.
   Convert into the unit system the KB itself uses for that entity class, and do not ship
   the literal reading (Modeling rules).
4. **New**: every Yes/No classification evaluates under SQL's own three-valued logic —
   'No' as soon as any input is recorded false, null only when nothing recorded settles
   it — so that `= 'No'` reproduces `NOT (<definition>)`, and every varying quality flag
   gets a Yes/No twin on the value it tests whose 'No' means *recorded and not that
   value*. A compound flag that returns 'No' only when every input is present answers a
   different question from a plain `NOT` (Modeling rules).
5. **New**: when the KB defines two or more contrasting classes over a child entity,
   publish the parent's **composition** over them ('X only', 'Y only', 'Mixed',
   'Neither'), judged over every child that can be placed in *any* of the classes — not
   a flag that looks only at children measurable for one class (Modeling rules).
6. **New**: a KB quantity that is a *ratio* gets its geometric mean published beside the
   arithmetic mean wherever a group of them is averaged; a KB quantity that is a
   *difference* gets its absolute value beside the signed one (Modeling rules).

Two things this pass did **not** put in the model, because they are not the model's: the
grader strips `ROUND()` from the reference but cannot strip it from a semantic-layer
agent's returned rows, so an agent that rounds "to the nearest integer" as asked fails
against an unrounded reference (an agent-guidance fact, recorded there); and two tasks
whose reference prints a `TO_CHAR` string, one of them with a malformed format pattern
that renders `  .000024E3`.

**What changed in the previous revision (`robot_fault_prediction` deep dive, 2026-08-27).** Four
new rules and one sharpened, from a 10-task database that scored 0/10 on three
consecutive runs while the raw baseline also scored 0/10. Read with the offline grader
(values rounded HALF_UP to two decimals on both sides, strings compared byte-for-byte,
row order strict), the ceiling test on the deployed model localised every failure to
something the model had done differently from a plain SQL reader of the warehouse.
Listed so each can be reviewed or reverted independently.

1. **New, and the one that generalises furthest**: evaluate every KB formula at the
   **warehouse's own column types** and widen afterwards. An integer column divided by a
   constant is integer division; two `real` columns added together sum in float32. The
   model had widened every operand to double first, and its values disagreed with a
   plain SQL reader's on every row of one formula and on 138 of 1000 rows of another
   once rounded to two decimals (Modeling rules).
2. **New**: a `character(n)` column's recorded value is the padded string. `::text` trims
   it silently, the grader does not trim, and a plain SQL reader returns it padded —
   so the display attribute must publish the recorded width, with a trimmed twin for
   filters (Modeling rules).
3. **New**: a **rendering** the question set asks for — lower case, upper case, as
   recorded — is coverage, not answer-fitting, when the wording is in a permitted
   source (`amb_user_query`, `follow_up.query`). Publish it as a named twin and have
   the bare attribute route the choice to the user (Sources).
4. **New**: when two KB rules answer the same everyday wording ("urgent maintenance"
   was two rules selecting 24 and 2), both descriptions must lead with the collision
   and route to the user; the metric twins too (Naming, competing readings, and
   counts).
5. **Sharpened**: the failure-classification step must include a **ceiling test of
   the value pipeline**, not only of the query shape: three of four reachable tasks
   failed on values that were right to six significant digits and wrong at the second
   decimal (After acceptance).

**What changed in the previous revision (`mental_health` failure review, 2026-08-25).** Four new
rules and two strengthened ones. The occasion is worth stating plainly, because it is the
most transferable thing in this revision: a review that produced eight model objects had
**four of them fail the test "would a fresh build produce this without ever reading the
reference answer?"** Two of those four broke rules already written here — the
follow-the-KB rule and the join-fan-out rule — and both were caught only by re-reading
this document, not by any gate. Every gate passed on all eight. Listed so each can be
reviewed or reverted independently.

1. **New**: a classification flag inherits the ambiguity of every formula it is built
   from, and hides it. Where an input has competing readings, the flag must name the
   reading it tests and ship the twin (Naming, competing readings, and counts).
2. **New**: a number the warehouse stores as text with a unit suffix needs **both** the
   parsed number and the stored text published (Modeling rules).
3. **New**: an unspecified constant in a KB formula — "assuming a standard number of X" —
   is a reading the *caller* supplies. Publish the per-unit figure and say the multiplier
   is unstated; never pick a value (Modeling rules).
4. **New**: a single-entity file audit wants the entity's **detail rows**, not the
   entity-grain rollup that averages them away (Group vs entity level).
5. **Strengthened**: the follow-the-KB rule now carries the test that catches its own
   violation — apply "would this object exist without the reference answer?" to every
   object a failure review produces, and record the answer (Sources).
6. **Strengthened**: the join-fan-out gold defect gains the case that is hardest to see,
   where the fan-out inflates a term that is *correct* in the same query (Acceptance).
7. **New**: the model must carry the knowledge base's own VOCABULARY, not just its
   formulas — a concept the model fully supports is undiscoverable when the KB's wording
   for it appears in no name and no description (Naming, competing readings, and counts).

**What changed in the previous revision (cross-fact conformance investigation, tracker
M-37, 2026-08-24).** Three rules, all from root-causing every refused measure pairing across
five deployed models. The refusals were never missing relationships: three of the five
models already held the conforming route (a rollup column, a denormalized ratio, an
execution-grain twin) and either failed to publish it as a metric or failed to say it
existed. Listed so each can be reviewed or reverted independently.

1. **New**: a measure pair the questions can demand must share a fact or ship a
   same-grain twin; pair conformance is a build obligation, not an engine limitation
   (Placement and conformance).
2. **New**: a rollup column computed in dataset SQL ships as a metric, not only as an
   attribute (Placement and conformance).
3. **New**: the conformance gate must probe metric pairs, not one measure at a time —
   135/135 single-measure passes coexisted with every cross-fact shape being
   unreachable (Acceptance).

**What changed in v8 (`virtual_idol` deep dive, four measured runs on one
database, 2026-08-24).** Fourteen rules. This round was different in kind from the
others: instead of building a model it iterated on a deployed one across four runs, and
the most valuable findings are about *measurement* — what a run can and cannot tell you —
and about a class of join bug that every gate in this document passed. Listed so each can
be reviewed or reverted independently. Two are corrections to rules already here.

1. **New, and the most damaging bug this document has yet recorded**: a rollup that
   reaches a branch through the wrong pivot silently gives one entity another entity's
   data, and gives nothing to the entity that owns it. Measure every pivot chain against
   the KB's own path before choosing one (Modeling rules).
2. **New**: an attribute that exists only in a fact group which does not conform to the
   entity-count measure is **unreachable**, and the engine does not say so — it falls
   through to a different conforming fact group and answers over the wrong population
   (Modeling rules).
3. **New**: a level whose display names are not unique needs a **projectable key**, or
   any per-entity ranking partitions on the name and silently merges distinct entities
   (Keys, identity, and naming).
4. **Correction**: pinning a computed constant is not enough — the **prose that quotes
   it** must be regenerated too. A fix that changed the data and left the descriptions
   saying the old thing made the agent follow the documentation into a wrong answer
   (Build process).
5. **New**: window functions the SQL front end lacks can be supplied as **model
   calculations**. Reach for MDX before filing an engine request (Modeling rules).
6. **New engine constraints**, two: `SUM`/`COUNT` over a dimension attribute silently
   returns per-member raw values instead of aggregating, and `AVG` fails the planner;
   a bare `CAST(x AS numeric)` is rejected (Engine constraints).
7. **New**: the **ceiling test** — hand-write the query against the deployed model and
   grade it — separates "the model cannot answer this" from "the agent did not find it",
   for the cost of one query instead of one run (Acceptance).
8. **New, and the finding that should change how these runs are read**: a 19-task
   single-database run resolves to **±1–2 tasks**. Three of five passes churned between
   runs with no model change between them. Do not measure a fix with one run (After
   acceptance).
9. **New**: gold defects are not rare. In one 19-task database, **5 of 14 failures** were
   benchmark artifacts — three join fan-outs that count entities twice, one answer that
   depends on the wall clock, one arbitrary tie order (After acceptance).
10. **New**: before acting on a systemic hypothesis, **measure it**. Four plausible
    cross-database theories were each worth zero, one of them after it had already
    identified 119 columns to change (After acceptance).
11. **New**: the grading path returns 0 indistinguishably for a wrong answer and for a
    **gold-side error or timeout**, so a swallowed pass looks exactly like a failure both
    in the audit and to the agent (After acceptance).
12. **New**: budget exhaustion, not model gaps, is what ends most tasks once a model is
    good. An agent with the correct answer in hand spent its remaining budget turning it
    into a wrong one (After acceptance).
13. **Correction**: "read the agent's submitted SQL" should be "read **every** attempt".
    The graded verdict can differ from what the best attempt deserved, and the difference
    is where the remaining information is (After acceptance).
14. **New**: a published count can go stale from an *earlier* fix and survive every gate,
    because nothing checks prose against data. Sweep them whenever the data moves
    (Build process).

**What changed in v7 (`cross_border` rebuilt from scratch, plus a repo-wide
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

**What changed in v4 (`labor_certification_applications`, 2026-08-13/15).** That
build reached parity with the raw baseline from a clear deficit,
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
16. Medians: the percentile sketch is exact and is the caller's ONLY route, since
   `PERCENTILE_CONT` is rejected in caller SQL — so publish a percentile metric for every
   median a question could ask for, and never describe the sketch as broken. Median-split
   concepts still precompute the median in dataset SQL (a metric is unreachable there).
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
  honestly. Masked `domain_knowledge` entries that state a numeric cutoff were withheld, 0
  of 17 -- **corrected 2026-08-27: withhold such a cutoff only when the harness deletes its
  KB entry from the task's knowledge tool (`knowledge_ambiguity.deleted_knowledge`); a masked
  question term whose entry stays in the tool is readable by the raw arm for one coin, so the
  flag ships under the KB's name and cutoff -- see the cross_border section below.** The single apparent exception, `Accelerated Aging Asset`, is `domain_knowledge`
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

**Apply the counterfactual test to every object a failure review produces, and write the
answer down.** The rule above is easy to agree with and easy to break, because a review
does not feel like answer-fitting while you are doing it — each step is a defensible
inference from something you legitimately read. The test that catches it is mechanical:

> Would a builder who had never seen the reference answer produce this object, from the
> KB and the warehouse alone?

Ask it per object, not per session, and record the reasoning beside the object. Observed:
a review of one 20-task arm produced eight objects, all eight passing every gate in this
document, and **four failed the test** — a flag whose formula had been switched to the
reference's reading (prohibited immediately above), a metric that reproduced a fan-out
defect in the reference (see Acceptance), a constant lifted from the reference where the
KB names none (see below), and a policy shipped as a description sentence where the rule
already required an object. The four that passed were each traceable to a KB silence or a
warehouse fact that a builder would hit unaided. Objects that fail the test are not
merely ungeneralizable — they raise the model's score on this task set specifically,
which is the definition of the thing being measured against.

A useful corollary: an object that fails the test is often pointing at a **real** finding
one level up. Three of the four above were genuine defects — two in the reference, one in
this document's own coverage — and were worth recording as such. What they were not worth
was a model object.


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

**A rendering the question set asks for is coverage, and it ships as a named twin.**
Scan the permitted question fields — `amb_user_query` and `follow_up.query` — for
instructions about how a value should be *printed*: "in lowercase", "in upper case",
"as recorded", "rounded to". Those are neither thresholds nor column picks; they are
vocabulary about the answer's surface, and a value the model can only return in its
stored casing is a value the caller cannot render as asked without knowing the engine
accepts `LOWER()` in the projection (it does, but agents do not try it). Observed: a
follow-up asked for "manufacturer names in lowercase" and the phase-1 reference printed
them lower-cased too; the model published only the recorded spelling and lost the task
on casing alone with counts and averages exact. Publish `<Attribute> (Lowercase)` beside
the recorded one, and have the **bare** attribute say the twin exists and route the
choice of rendering to the user — the 40:1 rule below means the twin is never chosen
unprompted. What this does *not* license: a rendering that appears only in the
reference SQL. Two other tasks on the same database lower-cased a model-series name
with no question wording anywhere asking for it; those stay capped and are reported as
a reference quirk.

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
- **A measure pair the questions can demand must share a fact or ship a same-grain
  twin.** Two measures on different facts refuse to appear in one query, by design and
  correctly — so for every question shape that lists or compares values from two fact
  groups, publish a conforming route: the rollup re-hosted on the entity fact, the
  coarse value denormalized down to the querying grain, or both values read through a
  chain dataset that carries both keys. The coarse-grain original's description must
  name its conforming twin and the dimension family each pairs with; a twin nobody is
  pointed at goes unused (see the 40:1 rule below).
- **A rollup column computed in dataset SQL ships as a metric, not only as an
  attribute.** Observed: a patient-grain crisis-intervention rollup was computed,
  published as a Profile attribute, and never given a metric — leaving the
  treatment-grain metric as the only aggregate and every pairing with patient
  attributes refused. If the column was worth computing, the aggregate question that
  motivated it is worth a metric.
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
- **A single-entity audit wants the entity's DETAIL ROWS, not the entity-grain rollup.**
  The rollup is the natural landing place for a question naming one entity — "check
  patient P's therapy hours", "audit account A's fees" — and where the entity carries
  several source records with different values, the rollup has already averaged away the
  answer. The reference for such a question is usually one row per source record, not one
  row per entity. Observed: entity-grain averages of twelve stored rates, over entities
  carrying up to three source records each, were selected for four separate
  single-entity audits; each returned one plausible row where the answer was two or
  three. Nothing errors, and the rollup is not wrong — it answers a different question.
  Say so on the rollup group itself: name the detail grain, say how many source records
  an entity can carry, and state that an audit of one named entity usually wants that
  grain. This is the same disclosure the group-vs-entity trio requires, pointed at the
  case where the *question* names one entity rather than a group.
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
  questions wanted all of them. Note the failure mode when this rule is half-applied: on
  a later model the divergence was found and written into the surviving object's
  *description* instead of being shipped as the second object. That is not compliance —
  the sentence tells a caller the other policy exists and still leaves them unable to
  select it, and by the name-decides rule below they will not act on the sentence anyway.

- **A number stored as TEXT with a unit suffix needs both forms published.** Warehouses
  in this benchmark routinely store a rate as `'1.6 points/month'` or
  `'0.5 side-effects/med/month'`. Parsing the leading token is obvious and necessary;
  keeping the stored string is the half that gets forgotten, and questions ask for it —
  "show the original density value" wants the recorded text, not the float. Publish the
  parsed number for arithmetic and the stored text beside it, named so the difference is
  visible (`… Value` / `… Text`), and give the distinct-string count in the text
  column's description. Observed: a model that had correctly shipped this pair for two of
  its twelve unit-suffixed columns and omitted it for the rest — the instinct was right
  and applied inconsistently, which is what a rule is for. Where the parse can fail or
  yield a non-finite value, that is a third fact to state (one warehouse stored the
  literal `'inf'` on 197 rows).

- **A PHYSICAL constant a KB formula needs but does not state is written out at its
  standard published value and composed inside the formula — never pre-collapsed into a
  textbook shortcut.** Distinguish this sharply from the *unspecified* constant in the
  next bullet: "assuming a standard number of medications" is a number nobody can look up,
  and it is the caller's; G, the solar mass, the astronomical unit, Jupiter's radius are
  numbers everybody can look up, and they are yours to write out — CODATA/IAU nominal
  values, as many digits as the source gives (`6.67430E-11`, `1.98847E30`, `6.957E8`,
  `1.496E11`, `1.898E27`, `7.1492E7`, `109.2` Earth radii per solar radius). What went
  wrong without this rule: escape velocity shipped as *Earth's 11186 m/s times the square
  root of the Earth-unit mass-radius ratio*, stellar density as *the solar ratio times
  1.408 g/cm³*, the gravitational parameter as *1.32712440018e20 times the solar mass*,
  the mass ratio via *0.00095458 solar masses per Jupiter mass*. Each is a correct
  identity to three or four significant digits; each disagrees with `sqrt(2 G M / R)`,
  `M / (4/3 π R³)`, `G M` and `M_J·1.898E27 / (M_☉·1.98847E30)` composed from the named
  constants in the fourth digit — 586 against 585.45 km/s, 1545 against 1544.62 kg/m³ —
  and a plain SQL reader of the same warehouse composes the constants. Two corollaries.
  (a) Evaluate the formula in the *shape the KB writes it*: `(M × M☉) / (4/3 × π × (R ×
  R☉)³)`, not an algebraically equal rearrangement, because floating point is not
  associative and a ratio of two such values can differ in its last digits. (b) Say
  which constants and values were used in the description, once, through a shared
  clause, so the caller can see the figure is composable and the next builder can check
  the digits. Where a follow-up question in a permitted source states a constant ("use
  1.98847E30 for solar mass to kg"), that is confirmation of the standard value, not a
  licence to fit — use the standard value whether or not a question names it.
- **A number the warehouse holds as JSON text has the type its column meaning declares,
  and a KB formula reads it at that type before widening.** The warehouse-types rule
  under Engine constraints says to evaluate at the warehouse's own column types; a JSON
  field has no SQL type of its own, so the meaning's declaration (`REAL`) is the type,
  and the read is `(doc->>'Mass_Value')::real` inside the arithmetic — exactly what a
  plain SQL reader of the same JSON writes. Reading the text straight into double keeps
  digits the warehouse never had (0.91 against 0.9100000262) and it is not harmless: the
  ratio of the densest star to the least dense was 2,237,875,936 through `::real` and
  2,237,875,810 through exact decimals — a 126-unit disagreement that two-decimal
  rounding sees in full, on a value right to nine digits either way. Display copies keep
  the exact decimal text (`::numeric` on the JSON text, `::text::numeric` on a stored
  `real`); only arithmetic goes through the declared type. The general shape of the
  hazard is worth naming: **any ratio of extremes, any value of large magnitude, any
  sum over thousands of rows amplifies float32 noise past the second decimal**, so the
  "the grader normalises float32 noise" finding under After acceptance holds for
  row-level values and fails for these.
- **A KB formula over two lengths, or two masses, is a formula over one unit — do not
  ship the dimensionally inconsistent reading as a twin.** This reverses what an earlier
  build did on the advice of this document's twin rules: an equilibrium temperature `T ×
  sqrt(R / 2a)` with `R` stored in solar radii and `a` in AU was published twice, "as
  written" (43 to 113,207) and converted (2.9 to 7720 K), each description naming the
  other. That is not two readings of an ambiguous definition; the literal one is a unit
  error, and it cost a task directly — the agent, seeing two, asked the simulator which,
  and the simulator said "the direct formula as-is". Convert into the unit system the KB
  itself uses for that entity class (planet sizes are in Earth radii here, so a
  planet-to-star radius ratio converts the star to Earth radii at 109.2, not the planet
  to solar radii), publish that reading under the bare name, and where a rendering of it
  is plausible (percent beside fraction, km/s beside m/s) ship *that* as the twin.
- **Every Yes/No classification evaluates under SQL's three-valued logic, so that
  `= 'No'` reproduces `NOT (<definition>)`.** A compound flag written `CASE WHEN a AND b
  THEN 'Yes' WHEN a IS NOT NULL AND b IS NOT NULL THEN 'No' END` returns null for a
  planet whose mass is unknown and whose period is 300 days — a planet that is
  *definitely* not a hot Jupiter, and that a plain `WHERE NOT (mass > 0.1 AND period <
  10)` keeps. Write the 'No' branch as the disjunction of each input's recorded negation
  (`mass <= 0.1 OR period >= 10`), so 'No' fires as soon as one recorded input settles
  it and null is reserved for rows nothing recorded settles. State the convention once
  on the profile that holds the flags. The same rule gives every quality flag (limit
  flags, blend flags) a Yes/No twin on the value it tests — 'Yes' when the flag equals
  it, 'No' when the flag is *recorded and different* (0 or -1), null when unrecorded —
  because a reference written `flag <> 1` excludes the unrecorded rows and a caller
  filtering `flag_indicator = 0` does not. Apply it to every flag that ever varies, not
  the two a question happened to touch; a flag constant at 0 across the warehouse needs
  no twin (Surface size).
- **When the KB defines two or more contrasting classes over a child entity, publish
  the parent's COMPOSITION over them.** "Stars that only have rocky planets" was
  implemented as *every density-measured planet is rocky* (49 stars) and the question
  meant *has a rocky planet and has no gas giant* (27): a gas giant is classified by
  mass and a rocky planet by density, so a planet with a mass and no density is a gas
  giant the first reading never sees. Ship `System Composition` with the values `X
  Only` / `Y Only` / `Mixed` / `Neither`, judged over every child that can be placed in
  *any* of the classes (density **or** mass recorded), plus one `Has X` / `Has Y` pair,
  plus the count metrics; keep the narrower reading under a qualified name with the
  differing count. The composition object also answers the follow-up ("stars with a gas
  giant and no rocky planet") that the single flag could not.
- **A KB quantity that is a ratio gets a geometric mean; a difference gets its absolute
  value.** "Average orbital period ratio" over a system's adjacent pairs was published
  as the arithmetic mean only; the conventional average of ratios is geometric
  (`exp(avg(ln x))`), the two agree on every two-member group and differ on 177 of 193
  larger ones, and only the caller knows which was meant — ship both, say which is
  which and how many groups they disagree on. A recorded-versus-derived comparison
  ("fact-check the law") sorts by *how far apart* the two are, so the signed difference
  needs an `Absolute Difference` sibling as its sort key.
- **An unspecified constant in a KB formula is a reading the CALLER supplies — never pick
  one.** A KB entry that reads "assuming a standard number of medications" or "a typical
  billing period" defines everything except the number. The temptation is to publish the
  formula with a plausible constant substituted; resist it, because the constant is not
  derivable from the KB or the warehouse and any value you choose is either arbitrary or
  lifted from somewhere you should not have looked. Publish the **per-unit** figure
  (`Annual Side Effect Per Medication`) and, where the warehouse actually records the
  count, the version computed from it. Then say in the description that the KB's
  multiplier is unstated, so the caller must supply it or ask. A caller who is told the
  multiplier is theirs can multiply; a caller handed a hardcoded one cannot tell it was
  invented.
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
- **The key has to be *projectable*, not merely present.** A level whose `name_column`
  is the display name and whose key is reachable only as the level itself gives a caller
  no way to write `PARTITION BY <key>`, so any per-entity ranking partitions on the name
  and merges distinct entities. Observed: 736 names covered 742 idols — one name was
  three different entities and four more were shared by two — and a per-entity
  `DENSE_RANK` on the name shifted every rank in the affected partitions. Publishing the
  key as a plain secondary attribute (`Idol ID`, alongside the `Fan ID` the same repo
  already had) took the same query from 809 rows to a row-for-row match with gold.
  Whenever one entity dimension publishes an `<Entity> ID` alias, check that its
  siblings do too; the omission is invisible until a window function needs it.
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

- **Carry the knowledge base's VOCABULARY, not only its formulas.** Discovery matches an
  agent's search terms against the object name *and* its description — verify this on
  your own backend before relying on it, then rely on it. The consequence is that a
  concept the model fully supports is **undiscoverable** whenever the KB's own wording
  for it appears in neither. The agent searches with the question's phrasing, the
  question uses the KB's term, and it gets "no columns matched" for a concept whose every
  input is published.

  Measured on one model: **40 of 96 KB terms appeared nowhere in the published text.** A
  composite classification whose two halves were both published returned nothing when
  searched by its KB name; so did a compliance check whose only input was a plain
  per-month hours column already on the model. Even the single most distinctive word of
  those phrases returned nothing, because the word was not in the model anywhere. A
  raw-SQL arm with a glossary tool has no such problem — it looks the term up in one
  call — so this asymmetry shows up directly as negative lift for the semantic layer.

  Ship it as a **table mapping column to KB term**, appended to that column's description
  by the generator, rather than as hand-edits scattered across descriptions: one place to
  audit, and an unmatched column name can then fail the build instead of silently
  restoring the gap. Where the KB concept is a composite the model publishes as separate
  halves, name it on **every** half. Three exclusions, each of which a gate will catch
  eventually but which are yours to apply first:

  - **A masked term is not automatically excluded — apply the existing type-based test,
    and do not invent a stricter one** (and since 2026-08-27 the test is narrower still:
    only a cutoff whose KB entry is *deleted* from the task's knowledge tool is withheld). The standing rule is explicitly *not* "never ship
    a masked term": what the benchmark withholds is the **cut-off**, so a masked
    `calculation_knowledge` entry (a named formula, no number) ships freely, and a masked
    `domain_knowledge` entry may be **named** provided its cut-off is not published beside
    it. What that adds here is a placement constraint: the KB term must not land next to
    a threshold-shaped number, and the masked-threshold gate enforces it over a window of
    a couple of hundred characters. On the measured model, 16 entries were masked on a
    running task; **four shipped without trouble and two could not**, because every column
    that could host them already states their cut-off in its own distribution sentence
    ("169 patients exceed 2") — naming the concept there hands over the number the agent
    is meant to ask for. Where no clean host exists, drop the term; do not reword a
    correct description to get a string past the gate.

    Worth recording as a process lesson, because it cost a wrong commit: the first pass
    at this read two gate failures as evidence for a blanket "masked terms are never
    publishable" rule, applied it to six terms, and shipped — needlessly removing four
    that the documented policy permits, one of them a `calculation_knowledge` entry the
    gate skips by design. A gate failure tells you *that* something is wrong, never *what
    the rule is*. Read the rule where it is written before generalizing from a red build.
  - **A term a task question quotes verbatim is not publishable either.** It trips the
    question-leakage gate, and rightly: the phrase's provenance may be the KB, but
    nothing in the published text distinguishes it from a description written off the
    question. Where such a term is not already the object's *name*, rename the object
    rather than allowlisting the leak.
  - **An acronym in parentheses reads as a cross-reference.** `Some Concept (SC)` looks
    to a dangling-reference gate exactly like a pointer to a published object called
    `Some Concept (SC)`. Unwrap it — "…, also written SC" — so both the full wording and
    the acronym stay searchable and the gate keeps its teeth.

- **When two KB rules answer the same everyday wording, both descriptions lead with the
  collision — and so do their count and rate metrics.** The shadowing rule under Surface
  size covers an *added* object out-competing a masked one. This is the case where the
  KB itself supplies both: a database carried "Urgent Maintenance Required" (remaining
  life under a week or service overdue, 24 operations) *and* "Predictive Maintenance
  Trigger" (an urgency score over a cutoff, 2 operations), and a question about robots
  that "need urgent maintenance" meant the second. The agent filtered on the first
  without asking, three runs out of three, because its name matched the question's
  words and nothing on it said another rule claimed the same wording. Find these
  mechanically: for each KB rule, list the everyday phrasings it answers ("needs
  maintenance urgently", "at risk of failing", "overworked") and flag any phrasing two
  rules share. Each such object's description then opens with the collision — the other
  rule's name, both populations — and routes the choice to the user; the `... Count` and
  `... Rate` built on each carry the same sentence, or the aggregate question hits the
  silent reading. Do not put the other rule's cutoff in the sentence when that cutoff is
  masked on a running task; name the rule and point at the attribute that states it.
- **A classification flag inherits the ambiguity of every formula it is built from, and
  hides it.** The twin rules above are written for attributes and measures, and they stop
  there — which leaves the boolean classifications built *on top* of those attributes as
  the one place a competing reading becomes invisible. A `Yes`/`No` column has no room to
  show which reading it tested. The caller sees a verdict, cannot tell it apart from the
  other reading's verdict, and has no way back to the inputs.

  Observed: a KB classification of the form "engagement above X but outcome below Y" was
  built over two inputs that each had a documented competing reading — an average whose
  ordinal scale left one stored level unscored (99 of 453 rows), and a ratio whose
  denominator could be all outcome rows or only the rows carrying the numerator's input.
  Both readings of both inputs were already published as separate attributes, correctly
  and with counts. The flag silently picked one of the four combinations. The two
  plausible combinations select **14 facilities and 22** out of 126 judgeable — an
  8-facility swing invisible from the flag alone, and invisible to every gate, because
  each individual number is right.

  The rule: a flag whose inputs have competing readings must (a) name in its own
  description the exact attribute each threshold is tested against, so the reading is
  recoverable, and (b) ship the twin flag under the alternate reading wherever the
  selected populations differ materially, each stating both counts. Where several
  ambiguous inputs combine, do not ship the full cross-product — ship the KB-literal
  combination as the primary and the single most plausible alternative as the twin, and
  say in both descriptions that the others exist and how to compute them from the
  published inputs.

  This is the flag-level case of "fix the aggregate twin whenever you fix the attribute"
  two bullets up, and it is missed for the same reason: the disambiguation was done, and
  then not carried to the object built on top of it.


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

### Join paths and reachability — what the 2026-08-24 deep dive changed

- **Measure every pivot chain before you choose one. A rollup that reaches a branch
  through the wrong pivot does not fail — it hands one entity another entity's data.**
  This is the most damaging defect class in this document, because every gate here passes
  it: the SQL is valid, the row counts are right, the values are plausible, and the model
  validates, deploys and answers.

  Observed: a fan-grain rollup reached the engagement branch by walking
  `fans -> interactions -> engagement`. But **27 of 555 engagement rows point at an
  interaction whose entity is not the entity on their own membership**. So 26 fans were
  given another fan's social, retention, loyalty, events and preferences figures, and the
  fans who own those rows but have no interaction of their own got nothing at all. One
  fan was reading another's follower count and content reach and took her place in a
  top-20 ranking; the real owner, having no interaction, was absent from every influence
  answer in the model.

  The check is cheap and there is no substitute for it. For each branch, compute the
  `(entity, branch_row)` pairs both ways and compare:

  ```sql
  WITH via_a AS (SELECT DISTINCT <entity>, <branch_key> FROM … /* path A */),
       via_b AS (SELECT DISTINCT <entity>, <branch_key> FROM … /* path B */)
  SELECT (SELECT count(*) FROM via_a) a,
         (SELECT count(*) FROM via_b) b,
         (SELECT count(*) FROM via_a JOIN via_b USING (<entity>, <branch_key>)) agree;
  ```

  Equal totals prove nothing — both paths gave 555 here and still disagreed on 27. It is
  `agree` that has to match. Where they differ, the pivot the branch row **carries itself**
  is the authoritative one, and the KB's own queries will use it; prefer that over
  whatever path the spine happens to make convenient. Branches that key off a row
  directly (a support record keyed on the interaction) stay on that row — the point is
  not "always use the membership", it is "use the pivot the branch declares".

- **An attribute that lives only in a fact group which does not conform to the
  entity-count measure is unreachable, and the engine will answer anyway.** Publishing a
  categorical attribute at its source grain is not the same as making it groupable by an
  entity count. Observed: a content-preference attribute existed only in the engagement
  fact group, `Fan Count` lives in the fan fact group, and the two do not conform — so
  "how many fans prefer each content type" could not be asked. Asking it did not error:
  the engine picked a *different* conforming fact group (social community, 181 fans) and
  answered over that population, returning 23 where the truth was 547.

  The rule: for every attribute a question might group an entity count by, carry it down
  to that entity's grain and publish it there. Name the entity-grain copy for the entity
  (`Fan Content Preference`) and leave the source-grain one under its own name, each
  description saying which population it counts. Where the collapse is lossy — 6 of 547
  entities held two different values — say so in the description and publish a count of
  the multiples beside it.

  The symptom to watch for in acceptance is the conformance error message itself: when
  the engine *does* refuse, it names the conforming fact groups. When it does not refuse,
  nothing tells you it silently chose one.

- **Reach for a model calculation before filing an engine request — and for group context,
  reach for DAX, not MDX.** Calculated measures accept **DAX and MDX interchangeably**; the
  engine auto-detects which one an expression is. That matters because the two languages are
  not equally capable here, and the split is not the one you would guess.

  **Rank within a group, or within a filtered population — use DAX `RANKX`:**

  ```
  RANKX(ALL('t'[Entity]), [Measure], , DESC)          -- ties share a rank, next rank skips
  RANKX(ALL('t'[Entity]), [Measure], , DESC, DENSE)   -- ties share a rank, no gap after
  ```

  Column references are `'anytable'[Column Name]`: the resolver ignores the table part and
  resolves by attribute name, so the table token is a placeholder. `ALL`/`ALLEXCEPT` are
  **level**-granular, not hierarchy-granular. `RANKX` accepts only `ALL(columns)` /
  `ALLSELECTED(columns)` as its table argument, and it happily takes another `metric_calc`
  (including an MDX one) as its ranked expression.

  It behaves correctly on both axes that matter: ranks **restart per group** when a second
  grouping is present, and **recompute over a narrowed population** when the query filters
  first — which is what "rank X among the Xs that qualify" needs.

  **MDX `Rank` is the wrong tool for this and is actively dangerous.** It ranks the level's
  full member set with no way to narrow it, and — worse — when the query groups by a
  *secondary attribute* of the ranked level it **silently returns `1` for every row** rather
  than erroring. The secondary attribute is usually the human-readable name, i.e. the common
  case is the one that silently misreports. Do not model a ranking with MDX `Rank`.

  **But `RANKX` is not a free pass — it has the same silent-`1` failure**, triggered by the
  exclusion list rather than by the attribute type (ATSCALE-52370). Read rule 1a of the
  group-context section before you publish a rank measure; the two languages are equally
  dangerous here, and DAX wins only because its exclusion is at least controllable.

  MDX is still right for scalar and set-free arithmetic — a share of a total, a ratio of two
  measures, an index. `PERCENT_RANK` is absent from the SQL surface, and where you genuinely
  want a percentile over a level's whole member set, this is still valid:

  ```
  (Count([Dim].[Hier].[Level].Members)
   - Rank([Dim].[Hier].CurrentMember, [Dim].[Hier].[Level].Members, [Measures].[M]))
  / (Count([Dim].[Hier].[Level].Members) - 1.0)
  ```

  — but read the silent-`1` warning above before shipping it, and prefer `RANKX` whenever the
  population is anything narrower than the whole level.

  **Do not try to express a filtered set inside an MDX aggregate.** `Sum(Filter(<members>,
  <cond>), <measure>)` parses and resolves but cannot plan: it routes to a contextual
  `AggX(Filter(Values(level), ...))` whose filtered table does not carry the aggregated
  measure's dependencies, so the engine correctly refuses rather than silently dropping the
  filter. This was investigated to the bottom and closed as **Won't Do** — DAX reaches the
  same goal without touching that path. Do not spend time here.

  **What no calculation can express**, so stop early and model it another way:
   - **multi-key ranking** (`ORDER BY a DESC, b ASC`) — `RANKX` takes one expression, so ties
     share a rank where gold's tie-broken rank gives distinct values;
   - **`ROW_NUMBER() ... ORDER BY <timestamp> DESC` "latest row per entity"** — that is a
     max-date measure or a flag on the row, not a rank.

  Validate the argument forms with `validate_mdx_expression`, but **never trust it as proof
  of correctness**: it checks syntax and member resolution only. Four separate wrong
  formulations passed it in one day, three of which returned wrong data. Proof is the live
  two-group query described in the group-context section.

### Reading the warehouse's own words — what the 2026-08-25 insider_trading pass changed

Six rules, each from a failure where the model was internally consistent, passed every
gate, and still answered a different question from the one the warehouse could answer.
All six are checkable at build time and none needs a benchmark run to find.

- **When the warehouse already stores the answer to a formula, read it — do not
  recompute it, and prove the two agree before choosing either.** A knowledge base gave
  `Daily Turnover Rate = Daily Trading Volume / Account Balance`. The warehouse also held
  a `bal_turnover` column whose documented meaning was *"the turnover rate of the
  trader's balance per day, calculated as the ratio of daily trading volume to the
  account balance"* — the formula word for word. The model computed the ratio anyway.
  On generated data the identity did not hold: Pearson **r = −0.008** between the stored
  column and the reconstruction, ranges 0.10–9.98 against 0.00013–19.63. Every concept
  downstream inherited the wrong one, and the KB's own high-risk profile selected **180
  traders where the gold answer had 954**. Synthetic warehouses are generated
  column-by-column; a stated identity between two columns is a claim about intent, not
  about the data. So: for every formula, grep the column meanings for a column that
  already *is* it, and if one exists, run
  `SELECT corr(stored, recomputed) FROM …`. Correlation near 1 — publish one, mention the
  other. Correlation near 0 — the stored column is the value, the reconstruction is a
  second reading, both ship under distinct names, and both descriptions say the two are
  not interchangeable and quote both ranges.

- **"Linked to X" is the existence of the X row, not a non-null attribute on it.** Two
  KB concepts required a transaction "linked to a corporate event". A `corporate_events`
  row existed for 999 of 999 records; the model instead tested `evt_near IS NOT NULL`,
  an *optional* proximity flag null on 249 of them. Both readings look defensible in
  isolation and the second is 25% smaller. The column meaning settles it — `evt_near`
  read *"flag indicating proximity of an **upcoming** corporate event"*, which is a
  different fact from "this trade is associated with an event". The join is the link.
  Where a concept says *linked to*, *associated with*, or *has a*, express it as the
  foreign-key row existing, and only narrow further if the KB names the narrowing.

- **A value stored as a number with its unit glued on must be published twice.** Eleven
  columns held text like `99,491.77 USD/min`, `0.98 score/hour`,
  `12.45 connection-point/ownership%`. The model published only the parsed number,
  because that is the only form a `WHERE` or an `AVG` can use. Three tasks then returned
  **the right rows, in the right order, with every other column identical**, and failed
  on `99491.77` against `"99491.77 USD/min"`. Publish the parsed numeric *and* the
  verbatim text as `<Name> (As Recorded)`, and say on both which is for what: the number
  for every filter, comparison, sort and aggregate; the recorded text when the caller
  asks to see, show, list or report the value, because it is what the warehouse holds.
  One shared helper for the wording keeps eleven descriptions saying the same thing.

- **Never ship a description that asserts a capability is broken without re-testing that
  claim at build time.** Two percentile metrics carried *"the Postgres dialect rejects
  the percentile sketch at query time on this engine, so expect this metric to error
  until that changes"*. It had been true. It no longer was — the metric returned the
  gold median exactly. The sentence cost a task: the agent read it, believed it, and
  spent its budget looking for a median that was already there. A defect note is a
  measurement with a date on it, so re-run the measurement whenever you regenerate. If
  the workaround still applies, say what to do instead; if you cannot re-test it, delete
  the claim rather than assert it.

- **Withhold a KB concept only when its own definition is incomplete — not when a
  related entry is unimplementable.** Three concepts were documented as
  non-implementations "because the benchmark withholds the cutoff". Two of them named no
  cutoff at all: `Aggressive Event Speculator = Event-Driven Trader AND risk appetite
  'Aggressive'`, both inputs already published as a flag and a dimension. The
  withholding had been inherited from a `children_knowledge` entry that *was*
  unanswerable, which is not the same test. Read the concept's own `definition` field:
  if every term in it resolves to a published object and no number is masked, publish
  the flag. Where the only open question is a threshold's *scale* — a KB stating `> 0.6`
  against a column recorded 0–100 — publish both readings under distinct names with both
  counts, the way competing readings are handled elsewhere in this prompt, rather than
  publishing neither.

- **When two columns can answer the same phrase, both descriptions must say which is
  which.** A question asked what *trading restrictions* an enforcement action imposed.
  Gold read `biz_restrict`, published as `Business Restriction` with the description
  "Business-restriction imposed, business restriction". A different column,
  `Trading Restriction Window`, described itself as "restriction type, restriction
  window, **what restriction was imposed**" — synonyms harvested for a *compliance-case*
  attribute that read as the better match. The agent picked it and got 306 rows where
  gold had 113; swapping the column alone reproduced 113 exactly. Before shipping, group
  the model's columns by the phrases their descriptions claim, and wherever two claim the
  same phrase, add a disjoint clause to each naming the other and the distinction —
  *"this is the enforcement action's restriction; the compliance case's restriction
  period is Trading Restriction Window"*. Synonyms are a discovery tool, and two columns
  competing for one synonym is worse than neither having it.

  A gate for this is cheap: for each pair of published descriptions, intersect their
  3-grams after dropping the object's own name; a pair sharing a domain-specific 3-gram
  with no cross-reference between them is a finding.

### What the 2026-08-27 cold_chain_pharma_compliance pass changed

Three rules, all checkable at build time, from a database whose semantic arm sat five
points over raw with eleven of eighteen tasks at zero.

- **A masked KB FORMULA ships over the terms the warehouse evidences, with the absent
  terms named — "not computable" is a claim about the whole formula, and it is usually
  false.** KB 48 defined a reliability score as `100 - (10*Fr + 5*Fd + 3*Fc + 2*Fb)` over
  four failure rates per 100 deployments. The model listed it among the concepts whose
  "terms are simply not stored" and shipped nothing. One of the four rates did have a
  column: another KB entry read a device with no recording interval as an unplanned
  monitoring approach, which makes those 63 devices of 450 exactly the population from
  which no reading was ever due. A second term was a *measured* zero — every calibration
  timestamp in the warehouse fell inside a twelve-month window, so no device was out of
  calibration for any reference date the caller could reasonably name. Two terms had no
  column at all. So the score was computable and worth 14 per 100 at weight 10, i.e.
  -40 over the fleet. The cost of the omission is not that the agent gave up: it invented
  a homemade pass-rate ratio instead of applying the formula it had been told was
  impossible. Publish as `<Name> (<Which Terms>)`, and in the description enumerate all
  four terms and say of each one whether it has a column, is a measured zero (with the
  measurement), or is absent — and where a term depends on a date the warehouse does not
  record, say to ask the user for it rather than assuming one. Distinguish *absent* from
  *zero by measurement*: a reader can act on the second and must not silently treat the
  first as it.

- **A KB term naming a real-world event is read against whatever the warehouse records
  as THAT event, not against the column whose name is closest.** A lane-risk formula
  summed "temperature excursions, shipping delays and customs delays". The model read the
  shipping-delay term as `route_deviation_incidents` — a tracking column, present, numeric
  and plausible. A shipping delay is a shipment that took longer than planned, and the
  warehouse stored both durations; two other KB entries already read that same comparison
  as lateness. Warehouse-wide the two readings gave 6.6736 and 5.5615, and per group the
  wrong one produced a 22-way tie at the top where the right one reproduced the reference's
  own top three exactly. Before binding a formula term to a column, write the term's
  real-world event in one sentence and check the column's own documented meaning says that
  event. Where the warehouse holds the *components* of the event (two timestamps, a
  planned and an actual), the derived comparison is the term and a same-shaped stored
  column is not.

- **A conditional distinct count needs a derived key column at build time; there is no
  query-time form.** "How many carriers operate at least one validated vehicle" cannot be
  written against a model publishing only `count distinct carrier` and
  `sum(validated_indicator)`: the first ignores the condition and the second counts
  vehicles. The dialect has no `COUNT(DISTINCT CASE WHEN … END)` over a model. Emit
  `CASE WHEN <condition> THEN <key> END AS <key>_when_<condition>` in the derived dataset
  and publish a `count distinct` over it. Sweep for this at build time: for every
  indicator column on a dataset whose grain is finer than an entity the model also names,
  the "entities with at least one such row" count is a question the task set will ask, and
  its absence is silent — the agent writes something that returns a number. Each such
  metric's description must say which thing it counts and that the finer island cannot see
  an entity with no rows on it.

### What the 2026-08-27 disaster_relief pass changed

Four rules, all checkable at build time, from a database where every satellite table was
exactly 1:1 with the fact and the build had — correctly — folded all seven onto one wide
row, and then lost seven of twelve tasks to what that fold hides.

- **Same key, same values, different coverage: the coalesced reference is bare, and each
  record's own reference ships beside it as `<Entity> On <Record>`.** The
  measure-before-twins rule above says that two columns holding the identical value
  wherever both are present are one recorded value, and to `COALESCE` them for coverage.
  That is right about the *value* and silent about the *population*. Observed: the
  operation reference sat on four satellites — coordination 967 events, beneficiary 800,
  financial 201, staffing 57 — agreeing on every overlap, and the model published one
  coalesced `Operation` over 967 events. Seven of the twelve reference queries reached the
  operation *through one specific record* (`JOIN humanresources ... hr.hr_ops_ref`), so
  "the operations for catastrophic disasters" meant the 30 staffed catastrophic events, a
  "regional summary" meant the 967 events with a coordination record, and the pooled cost
  per person for completed missions was computed over the 20 completed events that carry
  both a financial and a staffing record — 4.03 against 3.08 over every financed event.
  Nothing in any question names the record; the reference author's join habit does, and a
  plain SQL reader shares the habit because the FK it needs is *on* that table. So publish
  each satellite's reference as its own attribute (`Operation On Staffing Record`, 57
  events; `Distribution Hub On Supply Record`, 312), keep the coalesced one under the bare
  name, and have the bare description lead with the four counts and say that a question
  reaching the entity through one record means that record's events — as a population
  question for the user, not a column choice for the agent. Apply the same split to every
  formula computed *at the parent grain over the children a record names*: a hub's
  "average severity of the disasters it serves" is a different number over the 312
  disasters its supply record names than over the 987 its transport record names (327 of
  405 hubs differ), so both ship, the union under the bare name.

- **A KB operand that names a stored column by its documented meaning is read as that
  column, and a composite another KB entry defines under a different term is the qualified
  twin.** KB 4 divides `total_operational_costs` by the days elapsed; the warehouse has
  exactly one column documented "Operational costs in USD"; KB 5, defining the cost per
  person, says "*total cost* is the sum of ops, transport, storage and personnel costs".
  The build read KB 4's operand as KB 5's four-line sum — a reasonable-looking borrowing
  between entries that puts 16 operations under a week of runway where the stored column
  puts 8, a different eight. The read-the-stored-column rule above already decides this
  (the operand *names* the column); what is new is the second half: the borrowed composite
  is not wrong, it is *another KB entry's term*, so it ships as `... (All Four Cost
  Lines)` with both counts in both descriptions. The reference used the stored column in
  one task and the four-line sum in another, which is the usual proof that neither reading
  may be dropped. The same rule caught a second operand on the same database: KB 40's
  `total_personnel`, read by the build as KB 17's derived staff-plus-volunteers footprint
  where the staffing record stores a column documented "Total number of staff".

- **The coalesce policy is a per-formula assertion against the KB text, not a sentence in
  the model description.** The model said, correctly, that it coalesces a missing input to
  zero only where the knowledge base writes `COALESCE`, and that elsewhere "no staffing
  record is not no staff". Its gridlock index then coalesced the personnel term to zero on
  943 of 1000 events — KB 40 writes no `COALESCE` — and every one of those events got an
  index decided by two of its three terms. The check is mechanical: for each formula, the
  emitted SQL contains `COALESCE` on an input if and only if the KB definition's text
  does; put it in the generator beside the pinned constants, and pin the support-set count
  the strict reading produces (33 here) so a later edit cannot quietly widen it.

- **A formula whose inputs live on a narrow record gets a reading judged only over that
  record, beside the three-valued one.** KB 21's mass-casualty test is `casualties +
  injured > 100 OR medical ratio < 0.01`; the ratio needs the staffing record, present on
  57 of 1000 events. Under SQL's own three-valued logic the flag is `Yes` on 955 events
  (the first branch settles it and the unknown ratio drops out of the `OR`); a reader who
  joins the staffing table to compute the ratio evaluates the test on 57 events and gets
  54. Both are defensible readings of the same sentence, they differ by a factor of
  eighteen, and only the second is recoverable from the first (filter on the record's
  registry being non-null) — so ship `... (Staffed Events Only)` with its own count, name
  it in the bare flag's description with both counts, and route the population to the
  user. This is the missing-input-policy rule under Support sets applied to a
  classification rather than a measure.

### What the 2026-08-27 museum_artifact pass changed

Five rules, all checkable at build time, from a database where two source tables hold
10 and 3 rows and therefore decide every rating- and sensitivity-based answer.

- **An average over a named list of inputs has two readings, not three.** KB 2 averages
  "an artifact's various environmental sensitivity scores". The stored profile rates ten
  factors and two of the three profiles leave some unrated (3 and 2 of the ten). The
  build averaged over whichever factors were rated - a renormalised denominator - and
  shipped that bare. That is a third policy: neither the strict reading (a `CASE` with no
  `ELSE` propagates NULL through the sum, so any unrated factor voids the average) nor
  the coalesce reading (an unrated factor weighs 0 and the denominator stays at the list
  length). Ship strict bare because the KB writes no `COALESCE` - it covers 1 of the 3
  profiled artifacts here - and the `Unrated As Zero` twin beside it, on every formula
  downstream that a question reaches for (the vulnerability score's maximum, the
  compatibility average). Do not ship the renormalised one; nobody reading the KB writes
  it, and it matched nothing. Say in every reading's description which factors each
  profile leaves unrated, and that any other substitute weight is the user's to name and
  recomputable from the published factor attributes.

- **The KB's named examples are a factor set of their own.** KB 1 says "for various
  environmental factors like light, temperature, and humidity"; KB 4 multiplies exactly
  those three weights; the stored `environment` key holds five. A builder who read only
  the KB - as this model's first builder did - ships the three; a builder who read the
  data ships the five or the ten. All three sets are defensible readings of "various",
  so all three ship, each strict with its zero twin, and the bare description names the
  values of each on the profiled artifacts so the agent can put the choice to the user
  with numbers.

- **Entity-grain reading summaries beside a row-aligned fact.** The fact joins each
  assessment to the one environmental reading row-aligned with it - a correct grain
  decision - but a showcase carries one to three readings (906 / 45 / 1), and "the
  showcase's current temperature", "its average temperature", "is the showcase unstable"
  are questions about the showcase's readings, not about the assessment's. Publish on the
  entity dataset: reading count, the latest reading's values and timestamp, the averages,
  every KB formula on both bases (`... (Average Of Readings)`, `... (Latest Reading)`),
  and every KB verdict at entity grain with its count measure. The aligned reading
  differed from the latest on 44 of 1000 rows; the per-showcase failure-risk verdict is 67
  showcases where the per-assessment flag is 71 rows; and a reader who joins the rating in
  before testing gets 59 - so the `(Rated Showcases Only)` twin from the previous
  revision's narrow-record rule applies here too. The assessment-grain flag's description
  must say all of this and route a count of entities to the entity-grain measure.

- **A masked classification still owns its labels.** KB 58 prints 'Over Exposure' or
  'Within Limits' by comparing a reading against KB 57's per-level thresholds, and KB 57
  is masked, so the status cannot ship. Its two label strings are not the threshold: put
  them in the descriptions of the inputs (the sensitivity level, the humidity reading)
  with the instruction to ask the user for each level's limit. Observed: the agent asked
  for the thresholds, was given them, computed the status correctly and failed on the
  words 'Over-Exposed' / 'Within Acceptable Limits'.

- **Enumerate a JSON profile's keys from the data.** `SELECT DISTINCT jsonb_object_keys`
  at each nesting level, before the first description is written. The change log had
  recorded seven stored factors as "agent inventions ... stay absent" because a reviewer
  reasoned from the KB's examples rather than from the column; the agent asked for them
  by name in the 0820 run and was right.

Also in this pass: `Reading Year` and `Reading Date` on the only timestamp, because KB 54
talks about grouping readings by fixed interval and a distinct-day count is not a reading
count; the CPI `(Missing Inputs As Zero)` twin the missing-input rule already required.

**Capped, reported, not changed** (record so the score is read correctly): two phase-1
references that fail on tie order alone under the grader's default (`GRADING_TIE_TOLERANCE`
off - both grade 1 with it on); a reference that reads a JSON key with the wrong case and
so drops a factor; a reference that computes the priority index from a rating the KB does
not name; a reference whose "wrong environment" test selects the rows whose sensitivity
level *equals* the environment band; and an insurance value keyed on a loan status that
joins to no artifact, so every "by insurance value" answer is a plan-dependent pick.

### What the 2026-08-27 reverse_logistics pass changed

Two rules, both checkable at build time, from a database where one satellite (the
financial record) covers 995 of 1500 fact rows and every money question is decided by it.

- **A pooled ratio is computed over ONE population, and the denominator's total over that
  population ships beside the bare one.** KB 2 divides recovery value by days lapsed. The
  recovery value lives on the financial record (995 returns); days lapsed lives on the
  return row (all 1500). The build published `Total Days Lapsed` over 1500 and a pooled
  `Group Recovery Rate Per Day` that divided the 995-return recovery total by it - 15.79,
  a figure over no population at all. The intersection reading is 740008.86 / 31776 =
  23.29. Publish `Total Days Lapsed (Costed Returns)` - the denominator totalled over the
  rows that carry the numerator - and divide by that; keep the all-rows total under the
  bare name with its own count, and have each description name the other with both
  figures. The same twin answers the question that asks to see the ratio's components
  beside it ("the average per day, with the total recovered and the total days"): a reader
  who joins the two records gets the same-population totals, and a caller reading the bare
  all-rows total beside a 995-row recovery total is off by 47 percent with nothing to say
  so. Pin the restricted total in the dry-run. This is the "composite must share one
  population" rule applied to a ratio whose terms come from records of different coverage.

- **The record's own cost lines are a competing reading of "cost" even when no KB entry
  sums them.** KB 0 names five components of the total return cost; the financial record's
  `cost_breakdown` holds nine under its own groups (`fees`, `repair_costs`, `disposal`) -
  the five plus a QA fee, repackaging, repair labour and repair parts. The disaster_relief
  rule above covers a composite *another KB entry* defines; here nothing in the KB defines
  the nine-line sum, and the build correctly published only the five (and said the QA fee
  "is NOT part of it"). But "what did these returns cost" has a reader who sums the
  record, and a reference used that reading in one task (and the KB's in the next). Ship
  `Total Return Cost (All Recorded Cost Lines)` beside the KB reading, carry it to every
  formula downstream (`Return Profit Impact (All Recorded Cost Lines)`: -18832.95 against
  +281331.48 - the verdict flips), and have the bare readings say so with both figures so
  the agent puts the choice to the user. Do not make it bare: the KB's five-term formula is
  the default reading of the KB's own term; this is the qualified twin.

**Capped, reported, not changed:** a per-return cost listing that is set-equal to the
reference and fails on tie order alone (`GRADING_TIE_TOLERANCE` off); a "latest hundred"
that the reference orders by `ORDER BY <text date column> DESC` - a lexical sort over six
date shapes, so "latest" means alphabetically last ("September 9th, 2024"); a two-figure
answer whose reference prints the figures in the opposite order from the question's
sentences (now an ask in the shared agent guidance, not a model change).

### What the 2026-08-27 cross_border pass changed

One rule change with a verified mechanism behind it, and five twins from facts the KB or
the warehouse states.

- **A masked question term does not withhold its KB entry. Withhold a `domain_knowledge`
  cutoff only when the harness DELETES that entry from the task's knowledge tool.** The
  masked-cutoff rule above ("masked `domain_knowledge` entries that state a numeric cutoff
  do NOT ship") assumed the benchmark hides the cutoff from the agent. Checked at the
  mechanism, `db_environment/server.py::_filter_knowledge`: the raw arm's KB tool strips
  only the ids in `knowledge_ambiguity.deleted_knowledge`; every other entry is served
  verbatim on every task, and the semantic arm has no KB tool at all
  (`SEMANTIC_LAYER_KNOWLEDGE_TOOLS=false`). On cross_border the deleted ids are sixteen
  `calculation_knowledge` formulas plus two numberless concepts; the six cutoffs the model
  withheld (KB 10, 13, 14, 16, 18, 74 -- "high-pressure flows", "severe audits",
  "significant compliance issues", "vendor risk level") were readable by raw for one coin
  on every task that turned on them. What `is_mask` hides is the question's *wording* for
  a concept, not the concept: the raw agent still has to link "high-pressure flow" to
  "Overloaded Data Flow" in the KB list, and so does the semantic agent in `explore_columns`.
  So: publish the flag under the KB's own name with the KB's own cutoff (`Is Overloaded Data
  Flow`: BSI > 50 and DTE < 1.0, 56 of 820), name it from each input's description, and
  derive the withheld set mechanically from the brief's `deleted_knowledge` ids (the brief
  extractor now copies that field -- it is the tool's own filter input, an integer, not an
  answer) closed over `children_knowledge`. Two guards keep this honest: **never attach the
  masked wording as an alias** -- the gate now fails on any masked question term of two or
  more words appearing in a name or description unless it is the KB's own text, and that
  check removed four question-mined aliases the earlier build had shipped without noticing
  (`sensitivity score`, `subject request impact score`, `request types`, `JSON object`);
  and a *deleted* `calculation_knowledge` formula still ships (the standing 7-of-7 rule),
  because the raw arm reaches it by asking and the semantic arm has no other route.
  Measured cost of the old rule on this database: `_3` passed only when the simulator
  happened to restate KB 18 (824) and failed when it answered "I'm not sure I understand"
  (825); `_6` and `_10` never asked and never filtered. Measured gain: the eight tasks that
  had failed at phase 1 in every atscale run scored 5.7/8 in one n=1 run ($2.37) with the six
  flags shipped, five of them passing both phases.

  **Select the flags from the KB, not from the task list.** Publishing exactly the concepts
  the questions hit is question-informed selection even when each object is honest. The
  rule is: every `domain_knowledge` entry whose definition states a number and whose id is
  not deleted ships as a flag, and only data grounds exclude one (wall-clock definitions
  that are degenerate against the warehouse, an entry that repeats another's text). On
  cross_border that added 20 third-order composites nobody asks about. Measured (n=1, same
  eight tasks, $2.78): 4.0/8 — no task gained, and `_3` lost because KB 42 is literally named
  "High-Pressure Data Flow" (DSRP > 50 and BSI > 50) while the question's "high-pressure
  flows" means KB 18 "Overloaded Data Flow"; the agent took the name match. That is parity,
  not a defect — the raw arm's KB list carries the same entry — but it is the price of the
  uniform rule, and the flag's description must lead with the collision ("not the same
  concept as ..."), which this one did and which was not enough. Do not trim the set back to
  the concepts the questions touch to avoid it.

  **How much this generalises — checked before spending on it.** A survey of every 825
  phase-1 failure whose question masks a term standing for a readable KB cutoff (21
  databases) found that the old rule had only ever been *enforced* where a paraphrase-to-KB
  mapping was hand-made: cross_border (six concepts), archeology_scan (Mesh Quality
  Classification) and polar_equipment (EWRS). Every other model already publishes its masked
  cutoffs (planets_data's Rocky Planet "exceeds 3", robot_fault_prediction's Mechanical
  Degradation Alert "3.0 mm/s", polar_equipment's KB 52/53 bands, solar_panel's "exceeds 2",
  museum_artifact's Rotation Recommendation "below 0" ...), because the portable gate matches
  the masked *term*, which is a paraphrase, and so withholds nothing. Of 99 such failing
  concept-task pairs, 62 were in models that publish the cutoff (36 of them never even
  asked), and in the two still-withheld cases the simulator supplied the rule when asked
  and the task failed downstream. So this rule mostly codifies what 19 of 22 models already
  do; its measurable effect is confined to the strict outliers, and a multi-database run to
  "confirm" it would test nothing.

  **The deleted-entry test has teeth — check it per task before shipping.** archeology_scan's
  Mesh Quality Classification looked like the same case as cross_border's six, and is not:
  `archeology_scan_6` deletes KB 13 High Fidelity Mesh from its knowledge tool, so KB 13 and
  everything depending on it (KB 53) stay withheld under this rule. polar_equipment's readiness
  pair shows the other edge: KB 10 "EWR" is deleted and stays withheld; KB 50 "EWRS", a
  different rule with the same name stem, is not deleted and ships. Read `deleted_knowledge`
  for every Query task before deciding; a name that resembles a deleted entry is not the test.

- **"One divided by X" over a column stored as a 0-100 percentage has two readings, 100x
  apart, and the KB's own downstream cutoff tells you which is bare.** KB 2 RES = risk x
  (1 / control effectiveness); the column is `control_effectiveness_pct`. 1/85 and 1/0.85
  are both honest. KB 10 and KB 39 put RES against 0.7: on the pct reading that selects 449
  of 742 flows, on the fraction reading 736 of 742 -- so the KB wrote its cutoff against the
  pct reading, which stays bare, and `(Control As Fraction)` ships beside it and is carried
  down every formula that consumes RES (CBRF, CDVR). The earlier build's sentence "being a
  ratio of two columns on the same scale it is scale-free" was true of risk/ce and wrong
  about the formula: the KB divides one by control effectiveness alone.

- **The KB graph decides what a formula's word refers to; a `value_illustration` entry
  with the same words is the competing reading, not the default.** KB 9 CBRF = "overall
  risk score" x 2 or 1; its `children_knowledge` is `[2]`, so the overall risk score is RES.
  The earlier build used the raw assessment score with no KB anchor. KB 21 "Risk Assessment
  Score: the overall risk level determined in an assessment" is the honest anchor for that
  reading, so it ships as the named twin `(Raw Risk Score)` (835 flows against 709). Check
  `children_knowledge` before choosing an operand, and when a gloss entry offers the other
  operand, ship both with the graph's reading bare.

- **A CASE formula's "otherwise" branch covers the entity that has no satellite row.** KB
  5 SRS = 3 / 2 / "1 otherwise" over the security profile's two columns. 440 of 870 data
  profiles have no security record; the build scored them null, so a top-5 by sensitivity
  that shows SRS beside it lost four of its five rows. A profile with no security record is
  neither fully encrypted nor strongly controlled -- that is what "otherwise" says -- so the
  bare score is 1 over all 870 and `(Security Record Only)` keeps the 430. Do not read an
  unknown branch into a formula that has none; ship the null-preserving reading as the twin.

- **An ordinal ladder with a stored level the KB does not name gets the extended-ladder
  twin, not just the floor.** KB 4 weights High 3 / Medium 2 / Low 1; the classification
  carries Critical on 217 profiled flows. "Critical as 1" (bare, the floor) and "High
  only" were shipped; "Critical as 4" is the third completion and the one a reader who
  sees the ladder reaches for. Ship it as `(Critical Weighted 4)` with the disagreement
  count (exactly those 217).

- **A coalesced provenance attribute gets an as-recorded twin per source.** The build
  coalesced the flow record's classification with the profile's because they agree on
  every row where both exist -- correct -- but 35 flows have it only on the profile, so a
  question that names the flow record as its source ("classified as Critical in the
  DataFlow table") gets 246 where the record has 239. Ship `(Flow Record As Recorded)`
  and say in the bare description exactly which rows differ.

- **A formula used in a "below X" screen gets its missing-input-as-zero twin.** 36 flows
  have no performance record; DFRS is null there and a "reliability below 0.5" screen
  silently drops them, where a zero-filled reading keeps 23 of them (174 vs 151 under KB
  39). Same pattern as the zero-filled AFS twin already in the model; apply it wherever a
  null input meets a less-than screen, and ship the flag's twin too.

- **A question-mined alias is wrong even when the term is not masked, if it points at the
  raw column where the KB's composite is meant.** `Risk Score` carried "how severe the risk
  is" and "danger" as aliases; the KB entry that says "the overall level of risk" is RES
  (KB 2), and the agent took the raw score on that alias. Aliases come from the KB's words
  and the column's recorded meaning, never from a question; where a raw input and a KB
  composite compete for the same everyday phrase, the raw column's description names the
  composite and says to ask.

**Capped, reported, not changed:** a four-rows-per-audit `UNNEST` shape (`_7`: one row per
request category, "Access: N") that the engine cannot fan out and the agent cannot
construct; lower-cased text values in the reference (`_18`, `_20`: `LOWER(TRIM(...))` on
ids and names, `GRADING_CASEFOLD` off); a reference built on inline `VALUES` fake data
(`_19`); ties inside a screened listing (`_18`: 12 of 29 rows in tie groups,
`GRADING_TIE_TOLERANCE` off); a follow-up whose reference prints a Postgres boolean where
the grader stringifies `True` and neither 1/0 nor Yes/No matches (`_11` p2).

### What the 2026-08-27 fake_account pass changed

Six rules, each from a defect the free probes could reproduce against the warehouse
before any run was spent, plus one honesty correction. fake_account had scored
8.8 / 6.4 / 6.4 of 24 on the atscale arm against 5.1 raw, with thirteen tasks at 0 in
every run; `result_diff.py` split the 18 failing submissions into 8 value mismatches,
4 wrong column counts, 2 order-only and 4 row-count differences before anything was
changed.

- **A "ratio" operand over a percent-formatted text column is the figure divided by
  100; the as-stored reading is the twin.** KB 7 TEI = 0.4 x VPN ratio + ...; the column
  is `vpn_usage_pct`, described as "VPN usage percentage", stored as `'0.00%'` to
  `'1.00%'`. The earlier build took the number in front of the sign as the ratio (0.30%
  read as 0.30) and shipped `(VPN Percent Divided By 100)` as the twin. Both are honest
  and the KB's downstream cutoff (KB 16: TEI > 0.8, 482 vs 447 accounts) does not
  decide; when it does not, the unit conversion does - a percentage IS a ratio times
  100, and the column's own description says percentage. So the bare TEI now divides by
  100 and `(VPN Percent As Stored)` is the twin, and everything downstream of TEI (ARS,
  ABS, the quartile, the risk category) follows the bare reading. Read the cross_border
  RES rule together with this one: the cutoff decides when it can, the unit when it
  cannot.

- **A zero-filled twin zero-fills EVERY input, and every composite with a null
  population gets one, at row and aggregate grain.** The earlier TEI twin coalesced only
  the proxy count and left the VPN and country terms to propagate null - so the
  zero-filled ARS built on it was neither reading, and a "high authentication risk"
  screen returned 467 rows where either honest reading returns 431 (strict, 283
  accounts) or 431 (zero-filled, all 670). A twin named `(Missing Inputs As Zero)` that
  does not fill every input is a third, unnamed reading. And the "six where the choice
  matters" selection was itself a defect: NTS, CBR, NMI and LBS each lose 100-200
  accounts to nulls and had no twin, so "the average latest bot score across all
  accounts" could only be answered over the 558 with a score (0.648) where the
  all-accounts figure is 0.414. Ship the twin uniformly; the description of each bare
  reading names it with both counts.

- **A precomputed rank bucket gets a whole-population twin with nulls last.** KB 70's
  TEI quartile was materialised over the 564 accounts with a TEI (141 per bucket); a
  question that says "group every user into four buckets" means all 670, and a plain
  `NTILE(4) OVER (ORDER BY tei)` puts the 106 null-TEI accounts last, into quartile 4
  (168 / 168 / 167 / 167). Ship both as `TEI Quartile` and `TEI Quartile (All Accounts)`,
  carry the label ladder (`TEI Risk Category (All Accounts)`) with it, and say in each
  description exactly where the null population lands. The engine rejects NTILE on the
  inbound interface, so the agent cannot build either itself - both must be
  materialised, and the tiebreaker (account id) must be stated.

- **A formula that mixes an entity input with a group input is defined at the
  entity-group PAIR grain; publish it there, on the link fact, with THAT group's
  values.** KB 51 NIC, KB 6 CAS, KB 33 CBR and KB 37 CIS each take one term from the
  cluster (its recorded influence, coordination or size) and the rest from the account.
  An account is in one to three clusters, so the account-grain column has to collapse
  the cluster terms first (average, or highest) and the result is a different number
  from the formula evaluated per pair - and a per-cluster "average member NIC" that
  averages the collapsed account values is wrong for every cluster (CL0130: 0.536 where
  the per-pair average is 0.624). Ship the per-pair values as a degenerate dimension on
  the link fact (`Cluster Membership Record`: `Network Influence Centrality (Per
  Membership)`, `Coordinated Bot Risk (Per Membership)`, ...), re-base every "Average
  Member X" measure on them, keep the account-grain collapse as the bare account
  attribute with an explicit `(Highest Cluster Membership)` twin, and **carry every
  dimension key the pair might be rolled up by onto the link fact** - here the account's
  platform, so a per-platform average of the per-pair CIS is reachable (it was not:
  "no candidate paths" on every attempt). Verified live: the engine accepts a degenerate
  dimension on a link fact beside the entity dimension and returns one row per pair
  (1354 rows, 2 columns), and accepts `GROUP BY` on a non-projected column.

- **When the KB's own vocabulary distinguishes a raw column from the composite, keep
  the composite as the operand and record the disagreement rather than shipping a
  twin for it.** KB 51 says NIC = ... + 0.3 x "network influence score" (the cluster
  column, described "Network influence score"); KB 6 CAS and KB 37 CIS say "network
  influence centrality", KB 51's own title. Two reference queries on this database
  nonetheless read KB 6's operand as the raw column. That is a reference deviating from
  its own KB, not a competing honest reading, and a `(Cluster Influence Column)` twin
  would be gold-informed. Record it in the change log as a cap and move on.

- **Two composites that share an everyday phrase name the KB's OWN cutoffs on each.**
  NMI (0.6 BBI + 0.4 CAS) and CBR (BBI x CAS x size) are both "the overall
  bot-and-coordination score"; asked for the definition, the simulator described the
  product and the agent took the weighted sum because only NMI's description carried
  the phrase. Put the phrase on both, and let the KB break the tie the way the KB does:
  KB 40 puts CBR against 0.8, KB 49 puts NMI against 0.9, so "combined score above 0.8"
  fits KB 40's use of CBR. Both counts (509 / 553 above 0.8), ask as a closed question.

- **A KB formula whose inputs are absent from the warehouse is not computable; do not
  ship a proxy under its bare name.** KB 50 TPDS compares observed with expected hourly
  activity over 24 hours. No row anywhere carries an hourly series - the session
  telemetry's `activity_pattern` holds a regularity score and a three-bucket
  Morning/Afternoon/Night spread - yet the model shipped a three-bucket deviation as
  `Temporal Pattern Deviation Score (TPDS)`. It is now `(Spread Proxy)`, its description
  says KB 50's inputs do not exist here, and the agent is told to say so to the user.
  Check the raw JSON for every input a formula names before deciding it is computable;
  the reference for this task returns a single NULL row for exactly this reason.

**Measured, this pass:** the probe ceiling moved from 0 to 1 on `_4` (both phases),
`_16` p1, `_17` p2, `_15` (both phases), and `_5` p1 moved onto the all-accounts
category; `_10` and `_22` grade 1 with the aggregate sorted descending (a guidance
sentence, not a model change). Still 0 after the pass, all reported as caps: `_3`, `_9`,
`_12` and `_16` p2 are set-equal to gold and fail only on tie order
(`GRADING_TIE_TOLERANCE` off); `_24` matches gold to five decimals and fails because the
reference has no ORDER BY under `order: true`; `_11` and `_18` references are degenerate
(ten null-CMS rows sort first; a single NULL row); `_13`/`_14` follow the KB-6 deviation
above; `_7`, `_21` fail on what the simulator supplies against what the reference
projects.

### What the 2026-08-27 solar_panel pass changed

Read before changing anything: `result_diff.py` on the 825 run split the eight failing
submissions into 3 value mismatches, 2 order-only, 1 order-plus-case, 1 column count and 1
reference-returned-no-rows, and `probe_pred.py` (free) then showed that `_15` p1+p2, `_17` p2,
`_5` p2, `_6` p1+p2 and `_1` p2 already graded 1 against the DEPLOYED model. Five of nine
failing phases were the agent's - it never asked what a "projected" loss was and summed a
recorded one, it ran discovery to zero coins with the answer already in hand, it returned the
watts column where the glossary's ratio was meant - and those get guidance bullets, not model
objects. The model rules are the other four, plus two applications of rules already here.

- **One age convention per model, and it is the warehouse's own date arithmetic.** The model
  published a plant's current age as `EXTRACT(YEAR FROM AGE(NOW(), go_live))` (whole completed
  years) and its age at each snapshot as `(snapshot - go_live) / 365.25` (continuous). KB 7's
  Annual Degradation Rate divides by "age in years", so the same snapshot had two rates, and
  they differ on 449 of the 462 snapshots a year or more after go-live. A plain SQL reader of
  the same warehouse writes `AGE()` for both - that is the warehouse-types rule (Engine
  constraints) applied to dates: the native form is the bare name. `Age In Years` is now the
  whole-year count at the snapshot, `Age In Years (Fractional)` the continuous twin, and
  `Annual Degradation Rate (Fractional Age)` follows. Verify with a count of rows where the two
  conventions round differently before deciding it does not matter here.

- **A rate defined "since commissioning" is undefined before commissioning - NULL, never a
  negative number - and its description states how many rows that is.** 445 of 998 snapshots
  are timestamped before their plant's Go Live On date, 91 more inside the first year; the
  old ADR returned negative rates for the first group silently and an "average across all
  snapshots" was meaningless. Bare ADR is now NULL at age <= 0 and its description carries the
  three counts (445 / 91 / 462) so the agent can see that a question restricting itself to
  snapshots after go-live is already satisfied. A builder who runs `count(*) where <event
  timestamp> < <start date>` for every "since X" quantity finds this unaided; do it for each
  one.

- **The JSON-`::real` rule, applied to a SUM.** Per-snapshot ADR (Current) times three
  constants, summed over 57 snapshots at 75-million magnitude: `.43` when the JSON text was
  widened to double first, `.34` through `::real` as a plain reader writes it - a first-decimal
  disagreement on a row-level value that agreed to six digits. The `(doc->>'field')::real`
  read now applies to every field the column meaning declares REAL in both JSON columns (29
  casts); the two TEXT-with-unit-suffix fields keep their parsed double read. The general
  shape (any sum over many rows, any large magnitude) is stated under Modeling rules; this is
  its measured instance.

- **A per-record rate or score whose entity has several records states its grain and names
  the open slot.** ADR is one value per snapshot and a plant has one to three snapshots; asked
  for the projected loss "across the risky plants", the agent reduced to each plant's latest
  snapshot where every snapshot counted, and was 8 percent off with everything else right.
  Every such measure's description now says: one value per snapshot, NOT one per plant; a sum
  or average across plants counts every snapshot unless first reduced to one row per plant;
  the two differ; when the question does not say which, ask. Paired with a guidance bullet
  (ADK `system_agent/agent.py`) that opens the same slot from the question's wording alone.

- **An absolute amount and the ratio built from it name each other as amount versus
  proportion.** `Power Loss W` (watts lost) and `System Power Loss Ratio` (loss / (output +
  loss)) both answer "how much power is lost internally"; the agent took the watts. Each
  description now says which it is - "an ABSOLUTE amount in watts" / "a dimensionless
  PROPORTION" - names the other, and says the two are not interchangeable, so the model's own
  ask-trigger phrasing fires. Do this for every amount/ratio pair that shares an everyday
  phrase.

- **A recorded monetary or loss column says it is not a projection.** `Revloss Amount` is the
  revenue loss recorded at a snapshot; the question wanted a projected lifetime loss (a rate
  times an assumed volume, price and horizon - KB 11, deleted on that task, so the agent had to
  ask for the formula) and the agent summed the recorded column instead, twice. The
  description now says it is realised and historical, that a projected / potential / expected
  / lifetime figure is a forward-looking formula this warehouse does not store, and that the
  agent should ask for the formula and constants rather than substitute this column. Paired
  with a guidance bullet that says the same from the question's wording.

- **The uniform-flag rule (cross_border section), applied.** Six non-deleted
  `domain_knowledge` entries state a number or a fixed value test and none was published:
  `Chronic Downtime Asset` (System Availability < 0.95), `Tracker Malfunction` (Error or
  Maintenance), `Structural Integrity Warning` (Unstable or Check Required), `Critical
  Mechanical Health` (both, under three-valued AND), `High Degradation Panel Model` (spec rate
  > 0.7, evaluated on the plant's primary model), `High Environmental Risk Site` (tag High).
  All at snapshot grain on Plant Record with live counts in each description. **A flag whose
  live count is zero is still worth shipping**: no snapshot here meets Chronic Downtime, and
  the agent that rebuilt the formula by hand spent 19 calls and its whole budget doubting the
  empty result; a flag that says "0 of 998 qualify" lets the next one trust it and keep coins
  for phase 2.

**Firewall discrepancy, reported not changed.** This model predates the firewall (35 hand-tuned
commits 0804-07) and still publishes `Electrical Integrity Failure` (KB 30, `deleted_knowledge`
on `_9` and `_18`) and `Warranty Claim Risk` (KB 28, deleted on `_13`), plus an
`Operational Expenditure Index (Current)` sentence that is question-shaped ("a question that
ranks plants by cost and then asks for a second current figure..."). The rule in this document
would withhold both flags; `_9` and `_18` currently score 1.0 on the semantic arm against 0
raw. Whether to strip them is a measurement decision, not a modeling one - flagged for the
owner.

**Measured, this pass** (`probe_pred.py` then two n=1 runs, $2.00 total): the probe ceiling
moved 0 -> 1 on `_2` p1+p2 (the `::real` reads and the whole-year age); `_6`, `_15`, `_17`, `_5`
were already reachable and their failures were agent behaviour. First run, six tasks: 3.7/6
against 2.1 in the previous run and 1.4 raw - `_15`, `_17`, `_8` to 1.0; `_6` right value beside
an unasked plant name; `_2` snapshot-anchored age where "years since go-live" meant now. Both
ADR descriptions then named the two age anchors as an ask, and a guidance sentence said an
entity singled out by a superlative is the route to the figure, not part of the answer (the
corpus has two such questions, both scalar); re-run: `_6` 1.0, `_2` 1.0. Six targets 5.7/6;
projected 16.4/20 = 0.82 against raw 0.42, +40 pp (was +22).

**Caps, reported not changed:** tie order under `GRADING_TIE_TOLERANCE` off - `_10` p1 (336
rows, 328 distinct sort values), `_13` p1 (51 rows sorted on a column with three distinct
values) and `_13` p2 (reference picks one of the tied top plants with `LIMIT 1`); `_16` p1 is
set-equal and fails on the reference's cosmetic `LOWER()` of the group label
(`GRADING_CASEFOLD` off); `_8` p2 is the ROUND asymmetry already covered by the semantic-arm
instruction added on the planets pass (the runs read here predate it); `_10` p2 reinterprets
"the previous list" as each plant's latest snapshot WITH power readings rather than its latest
snapshot - not derivable.

### What the 2026-08-27 cybermarket_pattern pass changed

Read before changing anything: this model had already been tuned through two passes, and the
run-to-run picture was flat - 0.585, 0.57, 0.585 on the semantic arm (raw 0.535, n=1 each) with
`_1 _2 _3 _4 _5 _6 _7 _9` at 0 in every run and `_19` at 0.7 in every run. `probe_pred.py` on the
deployed model, before any edit, split those into three groups, and only the third is a model
concern:

- **Right rows, tied order** - `_1` (954 rows, 629 distinct sort values), `_4` (1000 / 799),
  `_5` (1000 / 807), `_9` (1000 / 649). Each phase-1 probe returned gold's rows and graded 0
  under the flags of record and 1 under `GRADING_TIE_TOLERANCE`. The raw arm passed `_5` in
  the same run by writing nearly gold's own SQL, so Postgres sorted its ties the same way -
  the asymmetry the flag was written for, and the reason a raw-vs-semantic comparison on this
  database measures the plan's tie order as much as the model. Two of the four are already in
  `config/order_undetermined.json` (`_4` p1, `_9` p1); the lint is a lower bound.
- **The reference picks one of several tied rows** - `_1` p2 (two platforms share the minimum
  score), `_5` p2 (positions 10 and 11 tie at exactly 1.0 under `LIMIT 10`), `_19` p2
  (seventeen threads tie at the top count under `LIMIT 1`). Not derivable; the simulator, asked,
  says "pick any one".
- **The reference is wider than the question** - `_2` (seven columns, tercile buckets and an
  anonymity breakdown over a column that is continuous live, so its three percentages are
  all zero), `_7` (eight columns for "how many live listings in each product type"), `_3`
  (nine), `_6` (seven). `_6` is the one that is reachable: asked "what exactly should the
  output contain", the simulator lists the five alert counts, and the run that asked passed
  phase 1 with the identical model. That is a guidance bullet (vague content noun opens a
  slot), not a model object.

The model rules are what the trajectories showed the agent paying for:

- **Never name an attribute the model does not publish.** The orientation text said
  "Bucketed tiers (Anonymity Tier) are this model's convention" and `Anonymity Score Average`
  said "the Anonymity Tier attribute buckets this score" - the column was computed in the
  dataset SQL and never given an attribute. Two tasks spent two to four discovery calls
  hunting for it, one `focus_columns` errored on the name, and one submitted its own NTILE
  bucketing instead of the score. Both sentences now say the knowledge base's High/Medium/Low
  tiers have no stored labels, no tier attribute exists, and 'each anonymity level' groups by
  the score. Check every description against the published column list at emit time; a
  reference to a withheld or never-built object is a dead end the agent pays for.

- **A non-unique display name: the key's description says it is what a listing shows.** The
  Platform Name warning was already first and already said to group and count on Platform
  Identifier Code - but the code's own text called it "an internal code rather than a display
  name, and Platform Name is the readable form", which reads as "show the name". Two listings
  each spent 2 coins asking "name or code?". The code now says it is the column that identifies
  a platform in any listing, that a name shared by about nine platforms identifies none of
  them, and to show the name only when the question asks for the name; the orientation text
  says the same. Paired with a guidance bullet that says a unique code beats a shared name
  without an ask.

- **An alias attribute says it is identical to its twin.** `Transaction Identifier Code` /
  `Transaction Code`, and the vendor and buyer pairs, exist so a key can be projected and
  counted as a plain attribute (the projectable-key rule under Keys, identity, and naming). Two
  tasks, after a failed listing, resubmitted with the other twin - 3 coins each for the same
  verdict. Each alias now says it is exactly the same value row for row and that a result that
  failed with one fails identically with the other.

**Reported, not changed.** (1) The MCP `run_query` validator (`referenced_columns` in
`tools/validation.py`) collects every `exp.Column` in the statement and validates the union, so
two subqueries that each conform - vendor code + vendor-grain rate; vendor code + route
complexity + transaction count - joined on the vendor code are refused with "does not conform",
and the agent that wrote exactly that shape was refused five times before submitting a flat
version the engine then failed to plan (`Error during query planning: None.get`). Validation
should be per SELECT scope. (2) `GRADING_TIE_TOLERANCE`: 2.8 phase-1 points on this database
are behind it on the semantic arm alone, with the raw arm collecting some of the same phases
by plan luck. (3) The `Group Formula` + `SUM(CASE ...)` flat projection that produced the
planner's `None.get` is an engine defect worth a repro.

**Measured, this pass:** see `docs/model-change-log.md` (cybermarket_pattern, 2026-08-27).

### Group-context calculations — what the 2026-08-31 RANKX pass changed

Six rules, from a day spent making "rank X within its group" and "the best value in the group"
expressible. That shape is behind **64 of 1,200 gold queries across 15 of the 22 databases**, so it
is worth getting right once. Five measures shipped to three models under these rules; each was
verified against live data, and two of the six rules exist because a measure I had already called
"verified" turned out to be wrong.

1. **Rank within a group with DAX `RANKX`, and give the entity level to `ALL`.**

   ```
   RANKX(ALL('t'[Entity]), [Measure], , DESC[, DENSE])
   ```

   `ALL` names the level being **ranked away**, not the group being ranked within. The grouping
   survives because it is still in the query. So a per-idol fan leaderboard is
   `RANKX(ALL('t'[Fan]), [Total Gift Value USD], ...)` queried with Idol and Fan — never
   `ALLEXCEPT(..., [Idol])`. Two consequences worth knowing: `ALL`/`ALLEXCEPT` are **level**-
   granular, so `ALL('t'[Fan Short Name])` leaves the `Fan` filter intact; and when the group and
   the entity share one hierarchy (they often do), no `ALLEXCEPT` formulation can express this,
   while `ALL(<entity level>)` still can.

   Ties: the 5th argument switches behaviour and does take effect — on one column, `DENSE` gave a
   maximum rank of 558 against `SKIP`'s 795, dense running consecutively where skip left gaps.
   Match whichever the question implies; say which in the description.

1a. **The `ALL(...)` exclusion must name every attribute of the ranked entity that the query
   groups by. Miss one and every row silently returns rank 1.** This is the single largest hazard in
   this whole area (ATSCALE-52370).

   `ALL` takes a list, so name them all:

   ```
   RANKX(ALL('t'[Entity], 't'[Entity Name], 't'[Entity Count], 't'[Entity Rate]), [Measure], , DESC)
   ```

   Proof of the failure mode: on a constructor reliability rank, the one team in the warehouse with a
   non-finish — so necessarily last — ranked **35** when the query grouped by the name alone, and
   **1** as soon as one more of its own attributes joined the GROUP BY. Adding that attribute to the
   exclusion restored the correct answer.

   Two consequences you cannot design away:

   - **The list can never be complete.** A consumer may group by any attribute, so every rank you
     publish is one unanticipated column away from all-1s. Mitigate on both sides: name the
     attributes questions plausibly select, AND put this in the description — *"select this rank
     beside the entity name or code only; adding other attributes of the same entity to the GROUP BY
     silently collapses every rank to 1. Put those columns in an enclosing FROM-subquery instead."*
   - **Verify under every attribute a question might group by, not just the level.** Testing by the
     key level alone is what let two already-shipped measures go out silently broken: both were
     correct grouped by the entity key and all-1 grouped by its display name — which is the column
     the questions actually ask for. Add this to the two-group test of rule 3.

2. **`CALCULATE([Measure], ALL('t'[Entity]))` is query-scoped, not group-scoped. It returns
   wrong data at entity grain and there is no error.**

   It is the natural-looking way to write "the best value in this group" and it is wrong: with two
   groups broken out by entity, every row gets the maximum over the **whole query scope**. Funds in
   one category were handed another category's maximum. It is right only when the query sits at
   group grain, or when a single group is in scope — which is exactly why it survives casual
   testing. Rank with `RANKX`; do not model a group-maximum this way.

3. **A group-context measure is not verified until two groups are broken out at entity grain in
   one query.**

   This is the whole rule and it is cheap. Single-group tests pass on a query-scoped measure.
   Group-grain tests pass on a query-scoped measure. Only two groups at entity grain separate the
   two, because only then do group scope and query scope differ. I confirmed rule 2's measure
   against six groups one at a time and shipped it; the first two-group query exposed it
   immediately. Add the narrowed-population check as a second control — filter the population and
   confirm the ranks recompute rather than reporting positions from the full set.

   Independently computing the expected answer in SQL is still the gold standard where the measure
   is small enough to hand-check; a per-group leaderboard whose values sum exactly to the group's
   published total is strong evidence for both at once.

4. **A rank inherits its base measure's conformance envelope. Run the grouping query before you
   write the description.**

   A rank over `[Patient Count]` can only be grouped by dimensions `Patient Count` conforms to.
   Twice in one session I wrote a confident description naming a grouping — "query it with Facility
   and Clinician together" — that then refused at run time, which costs the agent turns and teaches
   it to distrust the column. Worse, the two candidate base measures in that model had **disjoint**
   conforming fact groups (`Assessment Count` reached the diagnosis but not the clinician,
   `Patient Count` the reverse), so the gold's shape was unreachable at any grain and the honest
   answer was a model change, not a calculation. State the envelope in the description — name the
   groupings that work and the obvious ones that do not.

5. **Before ranking a `Mean/Average X`, look for a `(Pooled)` twin.**

   These models routinely carry both an average-of-per-entity-averages and a pooled recomputation
   (`total numerator / total denominator`). They are different numbers, and the KB formula is
   almost always the pooled one. Ranking the wrong twin changed a graded value from 0.11 to 0.12 at
   the question's own two-decimal rounding — a silent mismatch that no gate catches. Read the
   candidate measure's `expression` or `column` before you rank it; a measure that reads a
   **precomputed per-entity column** is also usually computed at the wrong grain for a
   group-by-group ranking.

6. **Every rank measure's description must carry the `HAVING` workaround** — see Engine
   constraints. A rank you cannot filter is half a rank, and "top N per group" is the main reason
   to define one.

**Reported, not changed.** A `(Pooled)` measure that returns NULL when one component's fact rows
are absent, where the KB's own formula would treat the missing component as zero, mis-ranks every
such entity — and mis-ranks them in the worst direction, since "no adverse events recorded" should
read as *better*, not unmeasurable. In one model this hit 30% of the entities in scope, and the
gold score they should have had would have put them at the **top** of their group. It was left
alone on purpose: it is a shared measure used by other questions, and whether an absent fact row
means "zero" or "unknown" is a modelling judgement for the owner, not something to reverse-engineer
from one task's gold. Raise it; do not silently flip it.

**What this bought, measured.** On a 39-task n=1 run the agent found the new measures and wrote them
into its own SQL unprompted — 4 of 12 statements on one task, 6 of 14 on another, 18 of 26 on a
third — so the descriptions do make them discoverable. One task flipped from a unanimous three-run
fail to a pass. The other two used the rank correctly and still failed downstream, on a `HAVING`
defect and a measure-semantics mismatch respectively. **Removing a blocker frees a task to meet the
next one**; do not forecast score from a capability landing. Two cautions on reading such a run: the
per-database delta was mostly *not* attributable to this work (of three gained tasks, one used a new
measure), and counting a measure's name in the raw result JSON overcounts badly because the column
catalog is re-served every turn — count occurrences inside SQL strings instead.


## Engine constraints (learned the hard way)

These work around tracked engine/tool defects — parenthesized IDs reference the team's
defect tracker and are provenance, not something to resolve. Check the Workarounds table
in BIRD-Interact-ADK's `docs/model-change-log.md` for whether each still applies.

- **WRONG DATA: a `RANKX` measure silently returns 1 for every row when the query groups by an
  attribute of the ranked entity that its `ALL(...)` exclusion does not name (ATSCALE-52370).**
  No error. The exclusion list, not the attribute's type, is what decides. Repro on the Motorsport
  model, where McLaren is the only non-finisher and must rank last:

  ```sql
  -- correct: the grouped attribute is in the exclusion
  GROUP BY "Constructor Name"                            -> McLaren 35
  -- silently wrong: one more attribute of the same entity
  GROUP BY "Constructor Name", "Reliability Rate Pct"    -> McLaren 1
  ```

  This is ATSCALE-52082 item 3 on the DAX path; that ticket was closed on the mistaken belief that
  `RANKX` avoided it. There is no formulation that is safe against an arbitrary grouping, so treat
  every published rank as carrying this hazard and follow rule 1a of the group-context section.

- **`HAVING` on a rank measure leaks an internal plan dump instead of filtering
  (ATSCALE-52369).** Filtering a `RANKX` measure at its own level fails with a raw plan node:

  ```
  Unmatched physical type SemanticWindowFunctionValue(WindowFunctionApplication(
  DenseRankWindowFunction, ...)) when rendering sql
  ```

  Only `HAVING` is affected — projection, `ORDER BY` + `LIMIT`, and the FROM-subquery form all
  return correct results. The working rewrite is the same one the engine's own designed
  rejections already prescribe elsewhere:

  ```sql
  SELECT * FROM (
    SELECT <keys>, <rank measure> AS rk FROM <model> GROUP BY <keys>
  ) t WHERE rk <= 3
  ```

  This matters more than its narrow trigger suggests: "top N per group" is the main reason to
  define a rank at all. **Put the rewrite in every rank measure's description** until the defect
  lands. Observed cost when it is missing: the agent wrote the gold's exact query on its first
  attempt, hit the dump six times, abandoned the semantic measure entirely, and hand-wrote raw
  window functions — which the SQL front end then rejects for its own reasons.

- **MDX `Rank` silently returns `1` for every row when the query groups by a secondary attribute
  of the ranked level (ATSCALE-52082 item 3, open).** Grouping by the level itself is correct;
  grouping by its display-name attribute — the common case, since that is what questions ask for —
  is silently wrong rather than an error. It also cannot narrow the ranked population at all.
  Model rankings with DAX `RANKX` instead (Modeling rules); do not reach for MDX `Rank`.

- **MDX `Filter` inside an aggregate is a closed door (ATSCALE-52355, Won't Do).**
  `Sum(Filter(<members>, <cond>), <measure>)` parses and resolves, then fails to plan because the
  filtered table does not carry the aggregated measure's dependencies. The engine refuses rather
  than dropping the filter, which is the correct behaviour. It was investigated to the bottom and
  closed deliberately: DAX reaches the same goals without that path. Do not re-open it.

- **`validate_mdx_expression` is a syntax and member-resolution check, not a correctness check.**
  It passes expressions that return wrong data — four wrong formulations passed it in a single
  day, three of which returned wrong numbers, and one of those was already written into a shipped
  measure. The only proof is a live query against an independently known answer. Cheap harness:
  add a temporary `metric_calc`, deploy, query it, compare, then remove it and redeploy.

- **`focus_columns` serves cached column metadata.** After changing a description, it will show
  you the old text and make a correct deploy look like it failed. Pass `force_refresh: true`
  before concluding anything. Do not re-deploy chasing this.

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
  never written. Currently inexpressible on this engine: percentile/median *in caller
  SQL* — the aggregation itself works, but only via a percentile metric the model
  published, so publish one for every median a question could ask for (see Modeling
  rules), quantile bucketing (`NTILE` rejected — so quartile/decile/percentile-band questions
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
- **Evaluate every KB formula at the warehouse's own column types, and widen to double
  only afterwards.** This is the general rule the `real::numeric` case below is one
  instance of, and it was learned on a database where the model was *right to six
  significant digits and wrong at the second decimal* on three of its four reachable
  tasks. The reference answers and the raw baseline are plain SQL readers of the
  warehouse, and a plain SQL reader gets the warehouse's arithmetic: `bigint / 24` is
  integer division (9 hours is 0 days, 27 hours is 1); `1000 / (bigint + 1)` is an
  integer quotient (113.37, not 113.48, for the largest urgency score); `real + real`
  sums in float32 before any halving (138 of 1000 stress scores differed at two
  decimals from the widen-first form); `real / real` is a float32 quotient (9 of 479).
  The grader rounds both sides HALF_UP at two decimals and then compares strings, so
  every one of those is a hard mismatch on a row whose value is otherwise exact.

  The habit that caused it is a good one applied one step too early: casting every
  operand to `double precision` for tidiness. Cast the **result** instead. Verify
  mechanically — for each formula, `SELECT pg_typeof(<formula as the KB writes it, over
  the raw columns>)` tells you where the warehouse truncates or rounds, and a count of
  rows where `round(native, 2) <> round(widened, 2)` tells you whether it matters. Where
  the two readings differ, the **bare name carries the warehouse evaluation**, because
  that is what a plain reader of the same data reports; the exact-arithmetic reading
  ships as an `(Exact)` twin, each description saying the two select the same rows
  under any threshold (pin that) and differ only in the printed value. This does not
  contradict M-31 below: widening a `real` to double is exact; it is *narrowing* it
  through numeric that destroys digits.

  **The display half of the same rule: a `real` column published for display carries
  the decimal Postgres itself prints, not the IEEE widening.** A stored `real` 0.755
  reaches every SQL client as the text `0.755` (Postgres prints the shortest string
  that round-trips), and the reference answer is graded from that. The engine reads the
  same column through JDBC as the double 0.7549999952. Rounded HALF_UP at two decimals
  the first is 0.76 and the second 0.75, so every value whose third decimal is 5 — 27 of
  241 fault scores, 11% — fails with nothing else wrong. Publish display copies of
  `real` columns (and of `real`-typed formula results such as a `real / real` ratio)
  as `(col)::text::numeric`: the text step is the shortest-precise print, the numeric
  step keeps it exact, and the value round-trips into the grader as `'0.755'`. This is
  **not** the M-31 cast: `real::numeric` directly goes through `float4out` at six
  digits and truncates; `real::text::numeric` does not (verify on the largest value in
  the column — 49921 stays 49921, 321804.16 stays 321804.16). Keep the double form for
  arithmetic, as M-31 says. Verified on one database: the fix took a three-row task
  from 0 to 1 with no other change, and a pin `count(*) where col::text <>
  col::double precision::real::text = 0` guards it.

  **The JSON half, sharpened (2026-08-27, disaster_relief): the declared-type rule is
  about where the ADDITION happens, not only the cast.** Three damage percentages held as
  JSON text and declared `REAL` were read `::real` — the previous revision's rule — and the
  index still disagreed with the reference in the seventh digit, because a plain reader's
  `COALESCE(a::real,0) + COALESCE(b::real,0) + COALESCE(c::real,0)` adds in float32 and
  only the `/ 3` widens, while the model widened each term first. Right to six digits,
  and 4 of 405 downstream hub indexes flipped at the second decimal — every one of them a
  *halved* value (`0.5 * load + 0.5 * severity`), because halving parks a third of all
  values on a `.xx5` boundary where a 1e-7 disagreement decides the rounding. Write the
  formula in the reader's shape — `(a::real + b::real + c::real)::double precision / 3`
  — and check `pg_typeof` of each *intermediate*, not of the result: `real * 10` and
  `real / 100` are already double on Postgres (the integer promotes to the category's
  preferred type), `real + real` is not. Display attributes keep the exact decimal read,
  as before.

- **A percentile cut has two readings, and the live data usually disagrees on the
  boundary member.** "In the 75th percentile or higher" is `PERCENT_RANK() >= 0.75`
  read literally and `value > PERCENTILE_CONT(0.75)` read as a threshold on the
  interpolated value; they differ exactly when a member's value equals the interpolated
  cut (147 against 146 series on one database, one series sitting on the value). The
  rank-twins rule above already covers `RANK` against `DENSE_RANK`; treat a percentile
  the same way — compute both, count the disagreement, and where it is non-zero ship
  the second as `(Above Nth Percentile Value)` with both counts in both descriptions.
- **A `character(n)` column's recorded value is the padded string, and `::text` trims it
  silently.** A calibration state stored as `character(20)` is one letter followed by
  nineteen spaces; the reference returns it padded, the grader compares strings
  byte-for-byte, and a model that cast it to text returned `'Y'` against
  `'Y                   '` — every row right, every row failed. Publish the recorded
  width as the display attribute (`rpad(col::text, n)`, since every string cast trims)
  and the trimmed letter as a `... Code` twin for filters, and say on the display
  attribute that an equality test against the bare letter matches nothing. Check
  `information_schema.columns.data_type = 'character'` in the type probe; it is the
  only string type with this behaviour.
- **Read a real-typed column at its own type; never cast it through ::numeric.**
  Postgres converts `float4` via `float4out` at `FLT_DIG=6`, so `real::numeric` silently
  truncates to six significant digits — 321804.16 becomes 321804. A derived dataset
  casting every source column for tidiness corrupted 941 of 1000 margin balances and 821
  of 1000 realised PnL values, and every figure computed from one. Nothing errors, and
  the values stay plausible to the last digit that survives (M-31). Read such columns as
  double — what the column is, and what a plain SQL reader of the warehouse gets — and
  re-probe the emitted declarations against `information_schema` in a generator gate.
- **Median** must be a `calculation_method: percentile` aggregation with
  `named_quantiles`, never a `metric_calc` — MDX `Median()` is rejected at deploy. **The
  sketch works and is exact** (measured 2026-08-25: `compression: 100` matched Postgres
  `PERCENTILE_CONT(0.5) WITHIN GROUP` to full double precision, grouped and ungrouped, on
  odd and even group sizes). Do not describe it as broken — see the re-test rule above;
  that exact stale claim cost a task. What is blocked is the *caller's* side:
  `PERCENTILE_CONT` is rejected by the SQL front end (see Engine constraints), so a
  published percentile metric is the **only** median a caller can reach. That makes the
  metric's description load-bearing, and it must say two things: the engine exposes the
  metric as `<name>_instance_<q>` so it MUST be selected by that name — the plain label
  returns `Column not found`, and metadata is cached until `list_models force_refresh`
  (the suffix is the quantile value, e.g. `_instance_0.5`, not the word `median`) — and
  that this is the only route, because `PERCENTILE_CONT` is not a function the dialect
  accepts in submitted SQL. Publish a percentile metric for every median a question could
  ask for; a median nobody pre-published is unreachable, and the caller finds that out by
  spending submits. Concepts *defined by* a median rather than reporting one (a median
  split, an above-median flag) still need the median precomputed in the dataset SQL —
  `percentile_cont(0.5) WITHIN GROUP (ORDER BY x)` in a cross join, which is plain
  warehouse SQL and unaffected — because a metric cannot be referenced from dataset SQL.
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

- **An aggregate function over a *dimension attribute* is not safe on the SQL front end,
  and two of its failure modes are silent.** Measured on two unrelated models:
  `MIN`, `MAX` and `COUNT(DISTINCT …)` are correct; `AVG` fails the planner with
  `assertion failed: We already handled attribute values`; and **`SUM` and `COUNT` return
  one row per member carrying the member's own raw value**, with no aggregation and no
  error. `COUNT(<attribute>)` returned a row whose value was `null` — a count cannot be
  null under any semantics, which is the clearest available proof that nothing is being
  aggregated. The consequence for modeling: any per-entity figure a question might
  average or total has to be published as a **measure**, not only as an attribute, or it
  is unreachable. This is what blocks a "cumulative spend in the first N days" answer
  even when every input column exists.
- **A bare `CAST(x AS numeric)` is rejected** (`Numeric values are only accepted with
  specified precision and scale`); `CAST(x AS numeric(p,s))` works. `x::numeric` is the
  idiomatic Postgres route to exact decimal arithmetic before `ROUND(v, 2)`, since
  `round(double precision, int)` does not exist in Postgres, so clients that speak
  Postgres write it constantly. When the cast does succeed with an explicit precision the
  value returns over MCP as a JSON **string**, not a number.
- **Window and statistical functions the SQL front end does not implement**, measured
  live rather than inferred: `PERCENT_RANK`, `CUME_DIST`, `PERCENTILE_CONT`,
  `PERCENTILE_DISC`, `MEDIAN`, `MODE`, `CORR`, `REGR_SLOPE`, `WIDTH_BUCKET`,
  `NTH_VALUE`, and the bare `STDDEV`/`VARIANCE` spellings (`STDDEV_SAMP`, `STDDEV_POP`,
  `VAR_SAMP`, `VAR_POP` resolve). `RANK`, `DENSE_RANK`, `ROW_NUMBER` and `NTILE` work.
  A dialect fix that teaches the *plan* layer to render a function does not make it
  parseable — `PERCENTILE_CONT` is rejected by the SQL front end before any dialect is
  consulted. Probe the list against the model you are building rather than assuming it
  carried over. Where a gap blocks you, try the MDX route under Modeling rules first.

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

- **A pinned constant protects the number; nothing protects the prose that quotes it.**
  A fix that changed what the data says and left the descriptions saying the old thing is
  worse than no fix, because the agent reads the descriptions. Observed twice in one
  round. A segmentation was widened from 37 entities to all 972, but every description
  still read *"just 37 … the other 935 are unsegmented, and a quadrant count that omits
  that is misleading"* — so the agent gated its query on the coverage flag and returned an
  `Unsegmented` bucket of 935. It followed the documentation exactly; the documentation
  was wrong. Separately, a coverage count had read 344 in prose and 354 in data since an
  *earlier* fix, and survived every gate in between.

  Two habits fix this. First, whenever a generated dataset's SQL changes, re-derive the
  published figures from the warehouse and diff them against the prose — grep the spec
  for each old number rather than trusting memory of which descriptions mention it.
  Second, when a coverage flag stops meaning "this entity can be classified" and starts
  meaning "this entity's classification is well-evidenced", **rename it**; a flag whose
  name still reads as a validity gate will be used as one no matter what its description
  says.
- **Pin the shape, not only the totals.** The pinned constants that caught the widened
  segmentation were the per-bucket counts and an assertion that *no* entity had a null
  segment. A total alone would have passed unchanged. Where a fix changes a population,
  add a constant that would fail if the fix were silently reverted.

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
   limitation to document, and there is no dialect exemption to claim: a percentile
   metric returns real values and must be probed like any other — by its
   `<name>_instance_<q>` name, since the plain label returns `Column not found` and a
   gate that probes the plain label reports a false failure. **Read the values, not just
   the row count**: the `[All]`-tuple defect above produces non-empty, plausible, wrong
   numbers and would pass a non-emptiness check. Compare at least one calculated index
   against a hand computation. Measure-by-attribute queries alone cannot see a missing
   attribute-only path, since adding a measure is what makes that case resolve: add one
   projection per dimension pairing that names attributes and no measure. And one
   measure at a time cannot see a refused measure pair: enumerate the metric list
   mechanically, probe one representative pair per fact-group pair, and require every
   refusal to have a same-grain twin whose description points to it — or an explicit
   written exemption. 135/135 single-measure conformance passes coexisted with every
   cross-fact pairing in five models being unreachable.
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

- **The ceiling test: hand-write the query against the deployed model and grade it.**
  One query answers the question a whole run cannot — *can* this be answered, or did the
  agent merely not find it? Take gold's shape, express it in the model's own columns
  with no budget and no discovery, run it through the semantic layer, and put the rows
  through the real grader. A pass means the raw material and a route to it both exist and
  the gap is discovery; a fail localises the model defect immediately. Used through this
  round it separated three genuine model bugs from three gold defects and two agent
  errors, at a cost of minutes rather than four runs.

  It is also the honest way to report a fix. A run can hide a working fix behind budget
  exhaustion or variance; the ceiling test cannot.

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
- **A single-database run resolves to ±1–2 tasks. Do not measure a fix with one run.**
  Four runs on one 19-task database: 3, 5, 5, 4 passes. Only **three** tasks passed in
  all of the last three; three others churned freely with no model change between them.
  One "regression" was the same task returning numerically identical values under
  self-invented labels (`Biggest Critics`/`Biggest Fans` instead of the model's own
  `Detractor`/`Promoter`). A day of model work and the run-to-run noise are the same
  size, so a single run cannot attribute the difference. Either use `--repeat` and
  compare means, or verify the fix by ceiling test and treat the run as a smoke test.
  Say which you did.
- **Read *every* attempt, not just the graded one.** The rule above says to read the
  agent's submitted SQL and take the last entry; that is right for knowing what was
  graded and wrong for knowing what happened. Observed: an agent produced gold's exact
  answer on attempt 1, that submission was recorded as failed, and it then spent its
  remaining budget "fixing" a correct query into a wrong one. Reading only the last
  attempt would have recorded a model gap that had in fact been closed.
- **Gold defects are common enough to check first.** In one 19-task database, **5 of 14
  failures were benchmark artifacts**, not model defects:
  - *Join fan-out* (three tasks). Gold's `LEFT JOIN` chain multiplies a per-entity figure
    by an unrelated table's row count, or counts one entity in two groups. Fingerprint:
    gold's group counts sum to **more than the entity population** — 986 for 972, 976 for
    972. One gold scored an entity 182 when its true score was 91, because the entity had
    two interactions and the interactions table was in the join for no other reason.

    The variant that is hardest to see, and the one that got past this rule on a later
    database: gold joins two tables to build a two-term composite, and the fan-out
    inflates only **one** term while the other is correct *because* it lives at the joined
    grain. A per-encounter count summed after a `LEFT JOIN` to a per-treatment table
    totalled **1348 against the warehouse's 869**, differing on 94 of 273 groups, while
    the crisis term in the very same expression was right — it is recorded per treatment,
    so the join grain is its own grain. Two consequences. First, run the
    sum-vs-population check **per term**, not on the query's output: the output is a
    ratio and looks unremarkable. Second, resist the specific trap this sets — a model
    twin computed at the fanned grain will reproduce gold *exactly*, on every row, which
    reads like confirmation and is actually the strongest available evidence that you are
    fitting a defect. An exact match against a reference you already suspect is not
    corroboration; re-derive the term from the KB and the warehouse instead.
  - *Wall-clock dependence*. A gold that estimates a date as `NOW() - <duration>` has an
    expected answer that drifts: measured 394.70 today and 396.47 three days out. No
    materialized model can track it, and two runs a week apart grade against different
    truths.
  - *Arbitrary tie order*. Gold has an `ORDER BY` with many rows tied on the sort key,
    and the grader demands exact order. One submission matched all 221 rows as a set and
    failed on the order among rows tied at the same value.

  Compute the sum-vs-population check on gold before building anything to match it.
- **Measure a systemic hypothesis before acting on it.** Four cross-database theories
  looked compelling and were each worth exactly zero:
  - float32 noise (source columns are `real`, so a `::double precision` cast exposes
    `9764.900390625` where gold shows `9764.90`) — **119 columns across 11 models** were
    identified for change before grading both forms proved the grader normalizes it;
  - shares published as fractions where 71 of 600 golds want percentages — those tasks
    pass at 31.6% against 30.6% for everything else;
  - a real asymmetry where the grader strips trailing zeros from a `Decimal` but not from
    a numeric-looking *string* (which is what the semantic-layer arm returns whenever the
    agent casts) — re-grading all 407 recorded submissions with it patched flipped
    **zero** verdicts;
  - percentage-vs-fraction naming.

  Each cost under an hour to measure and would have cost days to act on. The pattern is
  the same every time: a defect can be entirely real and still worth nothing, and only
  re-grading the recorded submissions can tell you which.
- **The grading path cannot distinguish a wrong answer from a broken gold.** Gold-side
  errors and timeouts return 0, and the caller catches bare `Exception` into
  *"Your SQL is not correct."* — so a swallowed pass is invisible in the audit and, worse,
  the agent is told its correct query was wrong and goes off to "fix" it. Observed once in
  ~400 recorded submissions, and not reproducible afterwards because the per-task database
  is dropped at task end. Where you can, log the gold error before returning 0.
- **Once a model is good, budget is what ends tasks.** 10 to 18 of 19 tasks exhausted
  their coin budget in every run of this round, including tasks that had already found
  the right answer. Before attributing a failure to the model, check `budget_remaining`
  and the final response — `"Budget exhausted. Task ended."` is not a modeling signal.
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
- **Ceiling-test the VALUE pipeline, not only the query shape — and read the grader's
  normalisation first.** The mechanical classification above sorts failures into
  tie-order, casing, wrong-shape and genuinely-wrong. "Genuinely wrong" hides a fifth
  class that a model can fix and a run cannot reveal: values right to many digits and
  wrong after the grader's own rounding. Before classifying, read what the grader does
  to a cell (on this harness: numerics rounded HALF_UP to the task's precision — two
  decimals unless a flag says otherwise — then compared as strings; strings compared
  byte-for-byte, no trim, no case fold; row order strict when the task says so), and
  then hand-write each reachable task's query against the deployed model and diff the
  rounded cells against the reference's. On one 10-task database that split a 0/10 arm
  into: two tasks unreachable because the reference belongs to a different question
  (mislabelled gold), one capped by a reference join fan-out (528 pairs over 479 rows),
  three capped by a reference `LOWER()` no question asked for, and **four reachable** —
  every one of which failed on a value-pipeline defect (integer division, float32
  addition, a padded `character(20)`) that the shape-only classification had filed as
  "genuinely wrong" and that no amount of agent guidance could have moved. Do this
  before the first run, not after the third.
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
- **A wall-clock formula is capped for part of every day when the warehouse session and
  the engine session disagree on the date.** The grader runs the reference through a
  driver session that inherits the Postgres server's timezone (Asia/Hong_Kong on the
  measured host); the engine's JDBC session sets the JVM's (Pacific). `CURRENT_DATE` in
  the two differs by one day for the fifteen hours a day between 09:00 and 24:00 Pacific,
  so every burn rate, runway and days-since figure the model computes is one day short
  of the reference in that window and exact outside it: a six-row runway answer matched
  to three decimals at `CURRENT_DATE - 1` and nowhere else. The dataset SQL is identical
  on both paths; only the session differs. Before classifying a wall-clock value as a
  model defect, recompute the reference at ±1 day; a match there is this cap, which is
  the harness's to fix (set both sessions' timezone) and not the model's.
- **A screened listing whose sort key is NULL on a qualifying row is not automatically
  capped.** The earlier rule that this engine emits `DESC NULLS LAST` where Postgres
  defaults to `NULLS FIRST` held on the databases it was measured on; on disaster_relief
  the same shape — five gridlocked operations ordered by an index that is null on one —
  came back with the null row first and graded 1. Probe it on the model in hand rather
  than assuming either way.
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
