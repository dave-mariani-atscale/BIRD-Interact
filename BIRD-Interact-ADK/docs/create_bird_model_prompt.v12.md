# Prompt: build an AtScale semantic model for a BIRD-Interact database

Every rule below traces to a reproduced failure — a model that validated clean, deployed
clean, and then answered a different question from the one asked. The measurement stays
beside the rule, because a rule without its evidence gets reworded away by the next
reader. Database-specific detail and anything derived from gold SQL is stripped.

Replace `<db>` throughout with the target database name. The modeling rules are mirrored
in the MCP `sml-create-metric` skill — propagate new lessons to both.

**Maintaining this document.** Add a rule only when a concrete failure motivates it, and
record the measurement. Delete a rule when the defect it works around is fixed — but
re-measure first: a stale workaround and a stale claim that something is broken cost the
same. Apply the counterfactual test (Answer-key firewall) to every rule a failure review
produces, and write the answer down.

---

## The task

Build an AtScale semantic model over the BIRD-Interact data in
`bird_interact_agent/data/bird-interact-full` at the BIRD-Interact fork root. Target the
`<db>` database through the `bird_<db>` connection, in a **new top-level folder named for
the database** inside a multi-database model repo, committing to main. Build via a
deterministic generator script parameterized by database name (see Build process). Run
unattended.

### Where the model goes — settle this before writing a line of spec

**A model is a folder in a repo that already holds other models. It is not its own repo.**
The repo shape is: one root `catalog.yml`, one `utilities/` holding the shared build
machinery, and one top-level folder per BIRD database owning its own `generator/`,
`brief/` and emitted YAML. `AtScaleInc/bird-atscale-models` is that shape and so is
`diannewood/bird-models-v12`.

So, in order:

1. **Which repo?** If the brief names one, use it. If it names a *comparison arm* or a
   *build process* rather than a repo ("a from-scratch v12 model", "an arm to compare
   against the shared models"), the repo is the existing one for that arm — look for it
   before assuming there is none.
2. **Only start a new repo when no repo for that arm exists yet**, and then set it up
   multi-database from the first commit: root `catalog.yml`, shared `utilities/`, the
   database in a folder beside them. A repo holding exactly one model is fine; a repo
   whose *layout* only admits one model is the thing to avoid.
3. **If you cannot tell which of those you are in, ask — before building, not after.** One
   closed question naming the two candidate repos costs a minute. Getting it wrong costs a
   catalog, a schema, a second vendored `utilities/`, a `config/environment_backends.yaml`
   edit and a redeploy to undo. Measured 2026-09-19: the robot_fault_prediction and
   archeology_scan v12 models were each built into their own repo because their kickoffs
   said "new private repo" and nothing said the two were one arm; merging them afterwards
   took a whole pass's worth of care to do without disturbing a measured model.

Never a second catalog for a second database in the same arm. The catalog name is what
becomes the deployed schema, and one arm wants one schema with the models sitting in it —
that is also what keeps `config/environment_backends.yaml` honest, because every domain in
a backend then names the same schema and differs only in `table`.

Note the consequence of sharing a catalog: deploying publishes the **whole** catalog, so
every model goes out together, and a redeploy for an unrelated sibling model can break
yours (Q-17b, Engine constraints). Build and gate every model you have touched before
deploying, and expect each `build.sh` to validate the entire repo at its last step.

## Preconditions

1. An AtScale connection exists for the target database —
   `utilities/create_bird_connections.sh` in `AtScaleInc/bird-atscale-models` provisions
   one per BIRD database. It reads `utilities/.env`, which is gitignored and must stay
   that way; copy `utilities/.env.example` and fill in `ATSCALE_CLIENT_SECRET` and
   `PG_PASSWORD`.
2. The AtScale MCP server is running and connected.
3. Deploy credentials: `ATSCALE_API_URL` is the SML API base URL without `/v1/public`
   (locally `http://local.atscaleinternal.com:3001`); `ATSCALE_API_TOKEN` — locally, use
   `ATSCALE_MCP_TEST_API_TOKEN` from `AtScaleInc/mcp/.env`.

## Answer-key firewall — read before opening any JSONL

Anything answer-bearing in `bird_interact_data.jsonl` is out of bounds while modeling:
`sol_sql` and `follow_up.sol_sql`, `sql_snippet` on any ambiguity entry, `test_cases` and
`conditions` (top level and inside `follow_up`), `preprocess_sql`, `clean_up_sqls`. The
cleanest guarantee is to extract the permitted fields (listed under Sources) into a brief
up front and model only from the brief, so the gold answers never reach your context. Say
which approach you took. Prefer to enforce this mechanically: a short extractor that
allowlists the permitted keys and then asserts that no denied key and no SQL-shaped text
appears in its own output is cheap, auditable, and removes the question entirely. Gold SQL
is fair game only later, if asked to diagnose specific failing tasks — never folded back
into the build.

Two working rules that keep the build honest:

- Every model change must be justifiable from the KB, the schema, or the engine's own
  observed behaviour — never from "this matches the expected answer".
- Publish a KB concept unless the benchmark actually withholds it from the other arm. The
  test is mechanical, not a reading of the word "threshold" — see the next two bullets.

**What is withheld, exactly.** The harness's knowledge tool strips only the ids listed in
each task's `knowledge_ambiguity.deleted_knowledge`; every other KB entry is served
verbatim to the raw arm on every task, and the semantic arm has no KB tool at all
(`SEMANTIC_LAYER_KNOWLEDGE_TOOLS` defaults false). So:

- A masked `calculation_knowledge` entry — a KB-NAMED FORMULA with no number — ships under
  its own name, always. There the ambiguity is "which index did you mean", which competing
  named metrics answer honestly. This holds even when the entry is *deleted*: the raw arm
  reaches it by asking the user, and the semantic arm has no other route.
- A `domain_knowledge` entry stating a numeric cutoff ships under the KB's own name with
  the KB's own cutoff **unless that entry is deleted from the task's knowledge tool**.
  Withholding a non-deleted cutoff hands the raw arm a concept for one coin that the
  semantic arm cannot have at all. Measured: eight tasks that had failed at phase 1 in
  every run scored 5.7/8 once six such flags shipped.
- **`extract_brief.py` drops `deleted_knowledge` by design** (it keeps `term`/`type`/`is_mask`
  only), so the ids are not in the brief and a build that looks for them there finds none and
  silently withholds nothing. Read them with a script that opens the JSONL and prints the
  integers and nothing else — that is the one permitted touch of that file, and it is the
  tool's own filter input rather than an answer. Verified 2026-09-20 on insider_trading,
  where the brief showed `null` on all three masked entries and the real ids were 12, 13, 46.
- Derive the withheld set mechanically from the brief's `deleted_knowledge` ids (the
  extractor may copy that field — it is the tool's own filter input, an integer, not an
  answer), closed over the KB's `children_knowledge` edges, since a concept depending on a
  withheld one leaks the same cutoff. Fail the build if any member is implemented.
  `utilities/masked_threshold_gate.py` is the portable version for models without a
  generator gate; wire it into the build rather than auditing by hand. It can legitimately
  report an entry as **inert** — masked only on a task category this backend does not run,
  and therefore published at no measurement cost.
- **Masking is per TASK; the model is one artifact. Census the cost before building.** A cutoff
  deleted on one Query task is gone from the model on *all* of them, while the raw arm still looks
  it up for a coin elsewhere: on exchange_traded_funds, four task-uses forfeited to protect three.
  Count, per withheld id, the Query tasks that USE it against those that DELETE it, and report the
  difference as a ceiling on the arm. Do not close it by publishing — that leaks on the task where
  the entry is deleted.
- Read `deleted_knowledge` per task before deciding. A name that resembles a deleted entry
  is not the test: one database deletes a "High Fidelity Mesh" entry on one task, so it and
  everything depending on it stay withheld; another has a deleted rule and a non-deleted
  rule sharing a name stem, and only the deleted one is withheld.

**Select the flags from the KB, not from the task list.** Publishing exactly the concepts
the questions hit is question-informed selection even when each object is honest. The rule:
every `domain_knowledge` entry whose definition states a number and whose id is not deleted
ships as a flag, and only *data* grounds exclude one (a wall-clock definition that is
degenerate against the warehouse, an entry that repeats another's text). Measured, the
uniform rule added 20 third-order composites nobody asked about and cost one task, because
two KB entries carried near-identical names and the agent took the name match — that is
parity, not a defect, since the raw arm's KB list carries the same entry. The flag's
description must lead with the collision; do not trim the set back to the concepts the
questions touch.

**Still ship a withheld concept's components**, each description saying it is one input to
a larger named concept and that the agent should ask the user for the complete definition —
every condition and threshold — before filtering. **And say in the MODEL description which
published columns those components are, per withheld concept.** The components being
published is not the same as their being findable: the gate that stops a description naming
the withheld object also stops the agent reaching the inputs by searching the concept's
name, and the agent cannot tell "withheld" from "I have not found it yet". Measured
2026-09-20 on insider_trading: one task spent **10** `explore_columns` calls and another
**9**, one of them searching for the literal string `withheld` and another for a phrase
lifted out of a description, proving a negative no amount of searching could settle; a
third asked the right question only after **11** searches. Listing each withheld concept's
published inputs in the model description — which `list_models` serves once per task, so it
costs no coins — took those three to 1, 0 and 4 calls and converted one of them. Say also
that searching the concept's name again returns nothing, or the agent re-searches. Otherwise the agent anchors its
clarifying question on the one component it found, gets a partial yes, and never learns the
rest. Expect the firewall to cost tasks and do not buy them back: on one database every
task that failed on every run of both backends turned on a withheld term, and no honest
model change would have moved any of them. Report those separately from real defects so the
score is read correctly.

**A withheld classification still owns its label vocabulary.** Where a masked entry decides
a status by comparing a reading against thresholds it also states, the *label strings* are
not the threshold. Put them in the descriptions of the inputs with the instruction to ask
the user for each level's limit. Observed: an agent asked for the thresholds, was given
them, computed the status correctly, and failed on 'Over-Exposed' against the KB's 'Over
Exposure'.

**Withhold a concept only when its own definition is incomplete — not when a related entry
is unimplementable.** Three concepts were documented as non-implementations "because the
benchmark withholds the cutoff"; two named no cutoff at all and were built from a flag and
a dimension the model already published. The withholding had been inherited from a
`children_knowledge` entry that *was* unanswerable, which is a different test. Read the
concept's own `definition`: if every term resolves to a published object and no number is
masked, publish it.

**Gold SQL can contradict its own knowledge base. Follow the KB.** Observed: a KB stated
that two wages "are converted to the same payment unit before calculation"; gold instead
*excluded* the rows whose units disagreed — two of 981 rows, which reordered a headline
top-5. The honest resolution is neither to silently keep your reading nor to adopt gold's:
follow the KB, and ship an attribute that lets the caller select the other population, both
descriptions stating the live counts. Switching your formula to match gold is
answer-fitting even when you found the divergence legitimately while diagnosing a failure;
exposing the choice is not, because it does not guarantee the task passes.

**Apply the counterfactual test to every object a failure review produces, and write the
answer down.** A review does not feel like answer-fitting while you are doing it — each
step is a defensible inference from something you legitimately read. The test is mechanical:

> Would a builder who had never seen the reference answer produce this object, from the KB
> and the warehouse alone?

Ask it per object, not per session, and record the reasoning beside the object. Observed: a
review of one 20-task arm produced eight objects, all eight passing every gate in this
document, and **four failed the test** — a flag whose formula had been switched to the
reference's reading, a metric that reproduced a fan-out defect in the reference, a constant
lifted from the reference where the KB names none, and a policy shipped as a description
sentence where the rule already required an object. A useful corollary: an object that
fails the test is often pointing at a **real** finding one level up — three of those four
were genuine defects, in the reference or in this document's own coverage, and were worth
recording as such. What they were not worth was a model object.

**A question-mined alias is a leak even when the term is not masked.** Aliases come from
the KB's words and the column's own recorded meaning, never from a question. Observed: a
raw score attribute carried "how severe the risk is" and "danger" as harvested aliases,
while the KB entry that says "the overall level of risk" is a composite built on it — and
the agent took the raw score on that alias. The gate now fails on any masked question term
of two or more words appearing in a name or description unless it is the KB's own text;
that check removed four question-mined aliases one build had shipped without noticing.
Where a raw input and a KB composite compete for the same everyday phrase, the raw column's
description names the composite and says to ask.

**The firewall's own SQL detector must test for SQL *structure*, not for keywords.** A
keyword list fires on ordinary English: the first run rejected the phrase **"join type"**,
a natural-language ambiguity label in the task set. A keyword list tuned until it stops
firing is worse than useless, because each loosening is invisible. Test for three narrow
signals prose does not produce: SQL structure (`select` … `from` in one string), DDL/DML
verbs (`insert into`, `update … set`, `create table`), and function-call syntax (`count(`,
`cast(`, `row_number(`), plus clause keywords only in SQL's upper case. When the detector
fires, read the match before loosening it — that first hit was a true positive about the
detector and a false positive about the data, which is the only way to tell a bad gate from
a real leak.

## Sources — and only these

Verify everything against the live database; the metadata files drift, so live wins.

- `<db>_schema.txt` and `<db>_column_meaning_base.json`. Profile the live tables yourself
  and fold what you find into the descriptions.
- `<db>_kb.jsonl` — every business definition, no exceptions, including any that individual
  tasks hide. Where the engine can't express one inline, say so rather than approximating
  silently — but read the sum-of-squared-shares pattern under Group vs entity level first,
  because that excuse has already been wrong for a whole family of formulas. Some KB files
  lost LaTeX backslashes to JSON unescaping: raw control characters stand where escape
  sequences belong (0x09 for `\t` as in `\text{}`, 0x0C for `\f` as in `\frac{}`, likewise
  `\n` `\r` `\b`). Check for raw control characters after parsing and restore them before
  reading formulas; most KBs are clean — don't transform ones that are.
- The natural-language questions in `bird_interact_data.jsonl` (filter on
  `selected_database`), for naming, synonyms, and coverage only: `amb_user_query`,
  `follow_up.query`, `category`, `output_type`, `high_level`, `follow_up.type`,
  `external_knowledge`, and the term/type/is_mask of each entry in `knowledge_ambiguity`
  and `user_query_ambiguity`. Don't hard-code any single task's thresholds or column picks.

Do not read any other semantic model on this machine, nor its git history. If you open one
by accident, say so in your report.

**Name readings asymmetrically.** This applies everywhere below that tells you to ship more
than one reading of a concept — ambiguous terms, competing join paths, the three
group/entity objects, rank twins, `(Current)` variants. Exactly one reading carries the
bare concept name; every other carries a qualifier stating its narrowing (`(Recorded
Only)`, `(Missing X As Zero)`, `(Computed)`, `(Current)`, `(All Entities)`, `(Per
Application)`). Choose which one is bare from the questions' own vocabulary, not from which
reading is more technically correct. Two objects with equally plausible names is the failure
mode, not a service to the caller — the descriptions will not save you (Definitions and
labels).

**Where the ambiguity is *which object*, enumerate your own inventory.** A withheld term
often is not a hidden number at all but a choice between columns the model already publishes
— "occupations" meaning a standard code, a standard title, or an employer's free-text title.
There the model hands the agent a ready-made closed question: name all the candidates in
each of their descriptions and tell the agent to *ask which one*, rather than to *pick*.
That publishes nothing withheld, and it converts an open question into the closed form that
measurably gets a specific answer (After acceptance). Distinguish it sharply from a masked
cutoff, where naming the candidate values would be a leak.

**A threshold whose unit is ambiguous against the stored column gets both readings, and the
KB's own words verbatim.** A KB definition states a cutoff in prose (*annual portfolio
turnover is less than 30%*) while the stored column may be on a different scale. Count both
against the live population first: a reading is *viable* only if it selects a proper,
non-degenerate subset, judged on the screen the questions ask for. Exactly one viable
reading → ship it alone and give the number that rejected the other (a holdings percentage
stored 0–1: `> 8` selects 0 of 2297 rows, `> 0.08` selects 743). Two viable readings → ship
both, asymmetrically named, each description naming its twin; a threshold is the one thing a
caller cannot recover from a result they cannot see. Either way the KB's original wording,
units included, must survive into the description's opening `KB '<Term>': …` — a description
that reinterprets a cutoff without carrying the KB's own phrasing is a build defect, and a
mechanically checkable one.

Gold is not a tiebreak here and can disagree with itself: one task filtered the same KB term
("less than 30%") as `< 0.3` in phase 1 and `< 30` in phase 2, counting 53 rows against 145.
No single reading wins both phases, which is precisely why both must exist as named objects.

**Two ways to break a unit tie, in order.** (1) The KB's own downstream cutoff. A formula
`risk × (1 / control effectiveness)` over a column stored 0–100 has two readings 100× apart;
another KB entry screens that formula at 0.7, which selects 449 of 742 on the percentage
reading and 736 of 742 on the fraction reading — so the KB wrote its cutoff against the
percentage reading, which stays bare, and `(Control As Fraction)` ships beside it and is
carried down every consuming formula. (2) Where the cutoff does not decide, the unit does: a
"ratio" operand over a percent-formatted text column is the figure divided by 100, because a
percentage *is* a ratio times 100 and the column's own description says percentage; the
as-stored reading is the twin, and everything downstream follows the bare reading.

**A rendering the question set asks for is coverage, and it ships as a named twin.** Scan
`amb_user_query` and `follow_up.query` for instructions about how a value should be
*printed*: "in lowercase", "in upper case", "as recorded", "rounded to". Those are neither
thresholds nor column picks. Observed: a follow-up asked for names in lowercase and the
phase-1 reference printed them lower-cased too; the model published only the recorded
spelling and lost the task on casing alone, with counts and averages exact. Publish
`<Attribute> (Lowercase)` beside the recorded one, and have the **bare** attribute say the
twin exists and route the choice to the user. What this does *not* license: a rendering that
appears only in reference SQL — those stay capped and are reported as a reference quirk.

**Two columns that look like two readings may be one recorded value — measure before
shipping twins.** Where the same concept appears in two places (a classification on the
event and on its detail row), the instinct is to ship both as independently-recorded
readings. Check first, with a join and a mismatch count. Observed on three pairs in one
schema: sensitivity agreed on all 835 rows where both were present, encryption on all 292,
category on all 835 — every apparent disagreement was a null on one side. They were
denormalised copies, and the previous build had shipped competing twins with a design note
the data does not support. Where they prove identical, ship **one** object, `COALESCE` the
sources for coverage (998 of 999 rows against 963 from the wider source alone), and put the
verification count in the description so the next reader does not re-litigate it. Where they
genuinely differ, the twin rules apply — the point is that this is a measurement, not a
judgement.

**Same key, same values, different coverage: the coalesced reference is bare, and each
record's own reference ships beside it as `<Entity> On <Record>`.** The rule above is right
about the *value* and silent about the *population*. Observed: an operation reference sat on
four satellites — 967, 800, 201 and 57 events — agreeing on every overlap, and the model
published one coalesced reference over 967. Seven of twelve reference queries reached the
entity *through one specific record*, so "the operations for catastrophic disasters" meant
the 30 staffed catastrophic events, and a pooled cost per person over "completed missions"
was computed over the 20 events carrying both a financial and a staffing record (4.03
against 3.08 over every financed event). Nothing in any question names the record; the
reference author's join habit does, and a plain SQL reader shares the habit because the FK
it needs is *on* that table. So publish each satellite's reference as its own attribute
(`Operation On Staffing Record`, 57 events), keep the coalesced one bare, and have the bare
description lead with the four counts and say that a question reaching the entity through one
record means that record's events — as a population question for the user, not a column
choice for the agent. Apply the same split to every formula computed at the parent grain
over the children a record names: one entity's "average severity of what it serves" is a
different number over the 312 rows its supply record names than over the 987 its transport
record names (327 of 405 entities differ), so both ship, the union bare.

**A coalesced provenance attribute gets an as-recorded twin per source.** Even where two
sources agree on every overlapping row, 35 rows carrying the value on only one side mean a
question that names *that* source as its origin gets 246 where the record itself has 239.
Ship `(<Source> As Recorded)` and say in the bare description exactly which rows differ.

**A KB formula that enumerates its input's values can be silently incomplete, and NULL is
not the safe completion.** An index defined as "3 if high, 2 if medium, 1 if low" met a
column carrying a fourth level on a quarter of the rows. This is not a masked threshold —
it is a gap in the KB's own definition. Implementing it literally, so the unnamed level
yields NULL, is the reading that looks most faithful and is the most damaging: every top-N,
total and average built on it silently omits that quarter of the population, and nothing
errors. Ship both completions — the unnamed value falling through to the base factor, and
whatever reading the question set's own wording implies — named asymmetrically, and give the
count of rows on which they **differ** rather than the count each selects at some threshold,
so the disclosure does not become a leak. Scan every KB formula that switches on a
categorical: compare the values the formula names against the values the column stores, and
treat any surplus as a finding.

**An ordinal ladder with a stored level the KB does not name gets the extended-ladder twin,
not just the floor.** Where a KB weights High 3 / Medium 2 / Low 1 and the column also
carries Critical on 217 rows, "Critical as 1" (the floor) and "High only" are not the whole
set — "Critical as 4" is the completion a reader who sees the ladder reaches for. Ship it as
`(Critical Weighted 4)` with the disagreement count.

**The KB's named examples are a factor set of their own.** Where the KB says "for various
environmental factors like light, temperature, and humidity" and a stored JSON profile holds
five keys under that heading and ten overall, all three sets are defensible readings of
"various": a builder who read only the KB ships the three, a builder who read the data ships
five or ten. Ship all three, each with its own missing-input twin, and have the bare
description give each one's values on the profiled entities so the agent can put the choice
to the user with numbers.

**Enumerate a JSON profile's keys from the data before writing the first description.**
`SELECT DISTINCT jsonb_object_keys` at each nesting level. Observed: seven stored factors
had been recorded in a change log as "agent inventions" and left unpublished for a week; the
agent had been asking for columns the warehouse held.

**When the warehouse already stores the answer to a formula, read it — and prove the two
agree before choosing either.** A KB gave `Daily Turnover Rate = Daily Trading Volume /
Account Balance`; the warehouse held a column whose documented meaning was that formula word
for word. The model computed the ratio anyway. On generated data the identity did not hold:
Pearson **r = −0.008** between the stored column and the reconstruction, ranges 0.10–9.98
against 0.00013–19.63, and the KB's own high-risk profile then selected 180 entities where
the reference had 954. Synthetic warehouses are generated column by column; a stated identity
between two columns is a claim about intent, not about the data. So for every formula, grep
the column meanings for a column that already *is* it, and if one exists run `SELECT
corr(stored, recomputed) FROM …`. Correlation near 1 — publish one, mention the other. Near
0 — the stored column is the value, the reconstruction is a second reading, both ship under
distinct names, and both descriptions say they are not interchangeable and quote both ranges.

**A KB operand that names a stored column by its documented meaning is read as that column;
a composite another KB entry defines under a different term is the qualified twin.** One KB
entry divides `total_operational_costs` by days elapsed; the warehouse has exactly one column
documented "Operational costs in USD"; a *different* KB entry, defining cost per person, says
"total cost is the sum of ops, transport, storage and personnel costs". Reading the first
entry's operand as the second's four-line sum puts 16 operations under a week of runway where
the stored column puts 8 — a different eight. The borrowed composite is not wrong, it is
another entry's term, so it ships as `… (All Four Cost Lines)` with both counts in both
descriptions. The reference used each reading in a different task, which is the usual proof
that neither may be dropped. The same rule caught a second operand on the same database,
where a build read "total personnel" as a derived staff-plus-volunteers footprint and the
warehouse stores a column documented "Total number of staff".

**The record's own cost lines are a competing reading of "cost" even when no KB entry sums
them.** A KB named five components of a total; the stored breakdown held nine under its own
group names — the five plus a QA fee, repackaging, repair labour and repair parts. The build
correctly published the five. But "what did these returns cost" has a reader who sums the
record, and a reference used that reading in one task and the KB's in the next. Ship `…
(All Recorded Cost Lines)` beside the KB reading, carry it to every formula downstream (a
profit impact flips sign: −18,832.95 against +281,331.48), and have the bare readings name it
with both figures. Do not make it bare — the KB's own formula is the default reading of the
KB's own term.

**The KB graph decides what a formula's word refers to; a `value_illustration` gloss with the
same words is the competing reading, not the default.** Where a formula's `children_knowledge`
points at a composite, that composite is the operand; a gloss entry offering the raw column
under the same wording ships as the named twin (835 rows against 709). Check
`children_knowledge` before binding any operand.

**A KB term naming a real-world event is read against whatever the warehouse records as THAT
event, not against the column whose name is closest.** A lane-risk formula summed "temperature
excursions, shipping delays and customs delays"; the build read the shipping-delay term as a
route-deviation incident count — present, numeric, plausible. A shipping delay is a shipment
that took longer than planned, and the warehouse stored both durations; two other KB entries
already read that comparison as lateness. Warehouse-wide the two readings gave 6.6736 and
5.5615, and per group the wrong one produced a 22-way tie at the top where the right one
reproduced the reference's own top three. Before binding a formula term to a column, write the
term's real-world event in one sentence and check the column's documented meaning says that
event. Where the warehouse holds the *components* of the event (a planned and an actual
timestamp), the derived comparison is the term and a same-shaped stored column is not.

**"Linked to X" is the existence of the X row, not a non-null attribute on it.** Two KB
concepts required a transaction "linked to a corporate event". An event row existed for 999
of 999 records; the model instead tested an *optional* proximity flag, null on 249 of them —
and the column's own meaning read "flag indicating proximity of an **upcoming** corporate
event", a different fact. Where a concept says *linked to*, *associated with*, or *has a*,
express it as the foreign-key row existing, and narrow further only if the KB names the
narrowing.

**A masked KB FORMULA ships over the terms the warehouse evidences, with the absent terms
named.** "Not computable" is a claim about the whole formula and it is usually false. A
reliability score `100 − (10·Fr + 5·Fd + 3·Fc + 2·Fb)` was listed among concepts whose
"terms are simply not stored" and shipped as nothing. One of the four rates did have a
column; a second was a *measured* zero (every calibration timestamp fell inside a
twelve-month window, so no entity was out of calibration for any reference date a caller
could name); two had no column at all. The score was computable and worth −40 over the fleet
at weight 10. The cost of the omission was not that the agent gave up — it invented a
homemade pass-rate ratio instead of applying a formula it had been told was impossible.
Publish as `<Name> (<Which Terms>)` and enumerate all terms in the description, saying of
each whether it has a column, is a measured zero (with the measurement), or is absent.
Distinguish *absent* from *zero by measurement*: a reader can act on the second and must not
silently treat the first as it. Where a term depends on a date the warehouse does not record,
say to ask the user for it.

**A KB formula whose inputs are genuinely absent is not computable; do not ship a proxy under
its bare name.** A score comparing observed with expected *hourly* activity over 24 hours has
no inputs where the telemetry holds a regularity score and a three-bucket spread — yet a
three-bucket deviation shipped under the KB's own name. Rename it `(Spread Proxy)`, say in
the description that the KB's inputs do not exist here, and tell the agent to say so to the
user. Check the raw JSON for every input a formula names before deciding it is computable.

## Modeling rules

### Placement and conformance

- An attribute that describes an entity goes on that entity's dimension, so it conforms
  wherever the entity does — not on the fact or derived table that computed it. Degenerate
  dimensions are for genuinely fact-grain attributes only.
- A filter or grain flows to a measure only along a relationship path the engine accepts,
  and some structures that look like paths in the SML are not accepted at query time: a
  many-to-many bridge between the measure's dataset and the dimension, a degenerate
  dimension sourced from a different fact, a measure declared on a coarser dimension's
  dataset. When no accepted path exists the query falls back to
  `unrelated_dimensions_handling` — silently empty results with an easy-to-miss warning.
  Where a pairing must work and the path is one of these shapes, denormalize the value onto
  a dataset with a direct relationship at the grain you need (a degenerate dimension
  repointed via `dataset:` alone still fails — convert to secondary attributes on the real
  dimension). The conformance acceptance check is what proves each pairing; trust it, not
  the diagram.
- Where several source tables are exactly 1:1 on the same key (verify live: equal row
  counts, no orphans either way), joining them into one wide fact is usually worth it — it
  gives every attribute a direct relationship to each entity dimension and removes the whole
  conformance failure class before it can occur. A 1:0..1 table joins the same way and
  removes a bridge you would otherwise build. Read the `<Entity> On <Record>` rule under
  Sources before folding: the fold is right about values and hides the population.
- Set unrelated-dimensions handling explicitly on every measure — prefer error, so a bad
  pairing fails loudly instead of silently returning empty.
- **A measure pair the questions can demand must share a fact or ship a same-grain twin.**
  Two measures on different facts refuse to appear in one query, by design and correctly —
  so for every question shape that lists or compares values from two fact groups, publish a
  conforming route: the rollup re-hosted on the entity fact, the coarse value denormalized
  down to the querying grain, or both read through a chain dataset carrying both keys. The
  coarse-grain original's description must name its conforming twin and the dimension family
  each pairs with; a twin nobody is pointed at goes unused (the 40:1 rule below).
- **A rollup column computed in dataset SQL ships as a metric, not only as an attribute.**
  Observed: an entity-grain rollup was computed, published as a profile attribute and never
  given a metric — leaving the finer-grain metric as the only aggregate and every pairing
  with entity attributes refused. If the column was worth computing, the aggregate question
  that motivated it is worth a metric.
- Where an entity can reach another by more than one join path (a direct FK vs a
  many-to-many bridge), ship attributes for both readings with descriptions saying which path
  each uses and when to prefer which. Don't assume the structurally "more correct" path is
  the one questions mean. If the bridge's pairs exactly mirror pairs derivable from the fact
  (verify live), model it as a plain link-count fact instead of an M2M bridge.
- **One join role per dimension, or attribute-only queries have no path.** Where a dimension
  is reached from several datasets on different columns, the planner cannot choose a path for
  a projection that names attributes and no measure, and every pairing of that dimension's
  attributes with another's dies on `assertion failed: No candidate paths found for an
  attribute`. Adding any measure makes it resolve — which is why a conformance gate built
  from measure-by-attribute queries passes while the model is broken for every attribute-only
  question. Measured: 32 of 98 `run_query` calls in one arm, exhausting the entire budget of
  three tasks. Drop the extra roles and recover what they bought by denormalising the column
  onto the dataset that needs it.
- Key each dimension leaf on the column the fact's FK actually references (watch numeric-id
  FKs against text labels — type mismatch); keep the descriptive string as `name_column`.
  Where the source has no single identifier, use a compound SML leaf key over its natural
  columns rather than concatenating a surrogate in dataset SQL — see D-01 under Engine
  constraints for why concatenation is actively dangerous.
- **A continuous numeric that questions might group *by*, rather than aggregate, needs a
  queryable attribute as well as a measure.** Scan the question set for "per X" / "by X" /
  "for each X" over stored scores, rates and ratios. A measure-only numeric silently makes an
  entire question shape *inexpressible* — not merely awkward — and the caller has no
  workaround. Observed twice: a 1000-distinct-value score shipped as a measure only, where
  questions group by it directly; and a rate shipped only as average/min/max, so `WHERE
  "<rate>" > <n>` returned `Column not found` and the agent fell back to a KB bucket whose
  cutoff was a different number. **Treat "the caller supplies the threshold" as a first-class
  query shape** — it is the normal case for every withheld concept. Ship the row-level
  attribute beside every measure whose concept a question could band, filter or bucket.
- **A per-row quantity that exists only as a metric also breaks projections, not just
  group-bys.** Where a question projects one row per source row, the row-distinguishing column
  must be queryable, or the engine's implicit group-by silently collapses the result.
  Observed: a per-snapshot reading shipped only as an average metric left the projection
  grouping on three other columns and returned 840 rows where the reference had 1000 —
  confirmed both ways, since the distinct triple is 840 in Postgres and adding the reading
  column makes it 1000. The row count is wrong rather than the query shape unavailable, so
  nothing errors and nothing looks odd.
- **An attribute that lives only in a fact group which does not conform to the entity-count
  measure is unreachable, and the engine will answer anyway.** Observed: a preference
  attribute existed only in one fact group, the entity count lives in another, and the two do
  not conform — so "how many entities prefer each type" could not be asked. Asking it did not
  error: the engine picked a *different* conforming fact group (181 entities) and answered
  over that population, returning 23 where the truth was 547. For every attribute a question
  might group an entity count by, carry it down to that entity's grain and publish it there.
  Name the entity-grain copy for the entity and leave the source-grain one under its own
  name, each description saying which population it counts. Where the collapse is lossy — 6
  of 547 entities held two values — say so and publish a count of the multiples beside it.
  The symptom to watch for: when the engine *does* refuse, it names the conforming fact
  groups; when it does not refuse, nothing tells you it silently chose one.
- **A formula that mixes an entity input with a group input is defined at the entity-group
  PAIR grain; publish it there, on the link fact, with that group's values.** Where several
  KB formulas take one term from a cluster (its recorded influence, coordination or size) and
  the rest from the member, and a member belongs to one to three clusters, the member-grain
  column has to collapse the cluster terms first — and a per-cluster "average member score"
  built on the collapsed values is wrong for every cluster (0.536 where the per-pair average
  is 0.624). Ship the per-pair values as a degenerate dimension on the link fact
  (`Cluster Membership Record`: `… (Per Membership)`), re-base every "Average Member X"
  measure on them, keep the member-grain collapse as the bare attribute with an explicit
  `(Highest …)` twin, and **carry every dimension key the pair might be rolled up by onto the
  link fact** — otherwise a per-platform average of the per-pair value is "no candidate paths"
  on every attempt. Verified live: the engine accepts a degenerate dimension on a link fact
  beside the entity dimension, returns one row per pair, and accepts `GROUP BY` on a
  non-projected column.
- **A conditional distinct count needs a derived key column at build time; there is no
  query-time form.** "How many carriers operate at least one validated vehicle" cannot be
  written against a model publishing only `count distinct carrier` and
  `sum(validated_indicator)`: the first ignores the condition, the second counts vehicles, and
  the dialect has no `COUNT(DISTINCT CASE WHEN … END)`. Emit `CASE WHEN <condition> THEN <key>
  END AS <key>_when_<condition>` in the derived dataset and publish a `count distinct` over
  it. Sweep for this at build time: for every indicator column on a dataset finer than an
  entity the model also names, "entities with at least one such row" is a question the task
  set will ask, and its absence is silent — the agent writes something that returns a number.
  Each such metric's description must say which thing it counts and that the finer island
  cannot see an entity with no rows on it.

### Ranks and top-N

- Expose the ranks and orderings that superlative and top-N questions need, at each grain
  they could ask about, stating sort direction, null placement, and tie convention. "The top
  N" means the first N rank positions under `RANK` and the N highest distinct values under
  `DENSE_RANK` — different row sets whenever values tie. Check the live data at the N the
  questions use; wherever the two disagree, ship both as named twins whose descriptions say
  which question each answers and name the other. The caller cannot recover the missing
  reading: a window alias used in `WHERE` must also be projected on this engine, which
  changes the column count.
- Where the two agree in the live data — no ties at the N the questions use — ship only one.
  Twins that never disagree are pure surface cost (Surface size).
- **A pre-built rank's *population* is part of its definition, and belongs in its name.** A
  rank over every entity returns a gapped sequence the moment the caller filters (1, 2, 3, 5,
  8…), which is not the dense within-filter rank a "top N of the entities that …" question
  means. A within-filter rank is not expressible at build time, so put the population in the
  *name* (`… Rank (All Entities)`), not only in the description, because an object whose name
  matches the question's vocabulary is picked on surface word match and by then the caller has
  already filtered. Where questions ask both ways, ship both.
- Note the limit of what this buys: when the question's own `LIMIT N` cuts across a tie, the
  expected answer is *not unique* and no model can make it so. Record such tasks as capped. The tie
  can also sit in an aggregate the MODEL computed, and a `ROW_NUMBER` twin does not rescue it:
  measured 2026-09-21, all 20 groups of one antenna status averaged exactly 0, the reference cut
  three of them by plan order, and a row-number column with a name tie-break returned three rows
  and the wrong three. The model reached every one of the reference's nine rows and all nine of
  its values. Ship the row-number twin anyway — it is the only way to return N rows at all —
  and cap the task.
- Before shipping any rank object, confirm the inbound interface cannot already express it.
  `RANK() OVER (...)` in the projection is accepted, so a displayed rank often needs no model
  object at all — but read the next bullet before acting on that, and read the group-context
  rules below before concluding a rank is expressible caller-side.
- **"The caller can write it" is not "the caller writes it": ship a rank for every score a
  superlative in the task set reaches for.** A-01 measured `RANK()` written **0 times in 5 runs**
  of a task whose reference projects one. A rank over a published score needs no answer key and is
  found by `explore_columns`; a window function the caller must think of is found by nothing.
  Know the limit before spending surface on it: a pre-built rank's population is fixed before the
  caller's filter, so it cannot answer a *within-filter* rank. Measured 2026-09-23 on
  exchange_traded_funds, eight such ranks converted **nothing** — what may carry is the rank
  description's caller-side escape (`RANK()` in a FROM-subquery over the filtered rows).
- **A precomputed rank bucket gets a whole-population twin with nulls last.** A quartile
  materialised over the 564 entities carrying a score (141 per bucket) is not what "group
  every user into four buckets" means for all 670; a plain `NTILE(4) OVER (ORDER BY score)`
  puts the 106 null-score entities last, into quartile 4 (168/168/167/167). Ship both, carry
  the label ladder with it, and say in each description exactly where the null population
  lands. The engine rejects `NTILE` on the inbound interface, so the agent cannot build either
  itself — both must be materialised, and the tiebreaker must be stated.

### Group-context calculations (rank within a group, best in group)

"Rank X within its group" and "the best value in the group" are behind **64 of 1,200 gold
queries across 15 of 22 databases**, so it is worth getting right once. This is a **DAX** job.
Calculated measures accept DAX and MDX interchangeably — the engine auto-detects — and the
two are not equally capable here.

1. **Rank within a group with `RANKX`, and give the entity level to `ALL`.**

   ```
   RANKX(ALL('t'[Entity]), [Measure], , DESC[, DENSE])
   ```

   `ALL` names the level being **ranked away**, not the group being ranked within; the
   grouping survives because it is still in the query. So a per-parent leaderboard is
   `RANKX(ALL('t'[Child]), [Measure], …)` queried with parent and child — never
   `ALLEXCEPT(…, [Parent])`. Column references are `'anytable'[Column Name]`: the resolver
   ignores the table token and resolves by attribute name. `ALL`/`ALLEXCEPT` are
   **level**-granular, so `ALL('t'[Child Short Name])` leaves the `Child` filter intact — and
   when the group and the entity share one hierarchy (they often do), no `ALLEXCEPT`
   formulation can express this while `ALL(<entity level>)` still can. `RANKX` accepts only
   `ALL(columns)` / `ALLSELECTED(columns)` as its table argument, and happily takes another
   `metric_calc` (including an MDX one) as its ranked expression. Ties: the 5th argument takes
   effect — on one column `DENSE` gave a maximum rank of 558 against `SKIP`'s 795. Match
   whichever the question implies and say which in the description.

1a. **The `ALL(...)` exclusion must name every attribute of the ranked entity that the query
   groups by. Miss one and every row silently returns rank 1.** This is the single largest
   hazard in this area (ATSCALE-52370). `ALL` takes a list, so name them all:

   ```
   RANKX(ALL('t'[Entity], 't'[Entity Name], 't'[Entity Count], 't'[Entity Rate]), [Measure], , DESC)
   ```

   Proof: on a reliability rank, the one entity in the warehouse with a non-finish — so
   necessarily last — ranked **35** when the query grouped by the name alone, and **1** as soon
   as one more of its own attributes joined the `GROUP BY`. Adding that attribute to the
   exclusion restored the correct answer. Two consequences you cannot design away:

   - **The list can never be complete.** A consumer may group by any attribute, so every rank
     you publish is one unanticipated column away from all-1s. Mitigate on both sides: name
     the attributes questions plausibly select, AND put this in the description — *"select
     this rank beside the entity name or code only; adding other attributes of the same entity
     to the GROUP BY silently collapses every rank to 1. Put those columns in an enclosing
     FROM-subquery instead."*
   - **Verify under every attribute a question might group by, not just the level.** Testing
     by the key level alone is what let two already-shipped measures go out silently broken:
     both were correct grouped by the entity key and all-1 grouped by its display name — which
     is the column the questions actually ask for.

2. **`CALCULATE([Measure], ALL('t'[Entity]))` is query-scoped, not group-scoped. It returns
   wrong data at entity grain and there is no error.** It is the natural-looking way to write
   "the best value in this group" and it is wrong: with two groups broken out by entity, every
   row gets the maximum over the **whole query scope** — entities in one group handed another
   group's maximum. It is right only at group grain or with a single group in scope, which is
   exactly why it survives casual testing. Rank with `RANKX`; do not model a group-maximum
   this way.

3. **A group-context measure is not verified until two groups are broken out at entity grain
   in one query.** Single-group tests pass on a query-scoped measure. Group-grain tests pass on
   a query-scoped measure. Only two groups at entity grain separate the two, because only then
   do group scope and query scope differ — rule 2's measure was confirmed against six groups
   one at a time and shipped, and the first two-group query exposed it immediately. Add the
   narrowed-population check as a second control: filter the population and confirm the ranks
   recompute rather than reporting positions from the full set. Independently computing the
   expected answer in SQL is still the gold standard where the measure is small enough to
   hand-check; a per-group leaderboard whose values sum exactly to the group's published total
   is strong evidence for both at once.

4. **A rank inherits its base measure's conformance envelope. Run the grouping query before
   you write the description.** A rank over `[Patient Count]` can only be grouped by dimensions
   `Patient Count` conforms to. Two confident descriptions naming a grouping — "query it with
   Facility and Clinician together" — refused at run time, which costs the agent turns and
   teaches it to distrust the column. Worse, in one model the two candidate base measures had
   **disjoint** conforming fact groups, so the gold's shape was unreachable at any grain and the
   honest answer was a model change, not a calculation. State the envelope in the description —
   name the groupings that work and the obvious ones that do not.

5. **Before ranking a `Mean/Average X`, look for a `(Pooled)` twin.** These models routinely
   carry both an average-of-per-entity-averages and a pooled recomputation (`total numerator /
   total denominator`). They are different numbers, and the KB formula is almost always the
   pooled one; ranking the wrong twin changed a graded value from 0.11 to 0.12 at the
   question's own two-decimal rounding — a silent mismatch no gate catches. Read the candidate
   measure's `expression` or `column` before ranking it; a measure reading a **precomputed
   per-entity column** is usually computed at the wrong grain for a group-by-group ranking.

6. **Every rank measure's description must carry the `HAVING` workaround** (Engine
   constraints). A rank you cannot filter is half a rank, and "top N per group" is the main
   reason to define one.

**MDX `Rank` is the wrong tool here and is actively dangerous.** It ranks the level's full
member set with no way to narrow it, and when the query groups by a *secondary attribute* of
the ranked level it **silently returns 1 for every row** rather than erroring — and the
secondary attribute is usually the human-readable name, i.e. the common case is the one that
silently misreports. MDX remains right for scalar, set-free arithmetic: a share of a total, a
ratio of two measures, an index. Where you genuinely want a percentile over a level's whole
member set, this is still valid:

```
(Count([Dim].[Hier].[Level].Members)
 - Rank([Dim].[Hier].CurrentMember, [Dim].[Hier].[Level].Members, [Measures].[M]))
/ (Count([Dim].[Hier].[Level].Members) - 1.0)
```

— but read the silent-1 warning first, and prefer `RANKX` whenever the population is
anything narrower than the whole level.

**Do not try to express a filtered set inside an MDX aggregate.** `Sum(Filter(<members>,
<cond>), <measure>)` parses and resolves but cannot plan: it routes to a contextual
`AggX(Filter(Values(level), …))` whose filtered table does not carry the aggregated measure's
dependencies, so the engine correctly refuses rather than silently dropping the filter. It was
investigated to the bottom and closed Won't Do; DAX reaches the same goal without that path.

**What no calculation can express** — stop early and model it another way: **multi-key
ranking** (`ORDER BY a DESC, b ASC`), since `RANKX` takes one expression and ties share a rank
where a tie-broken rank gives distinct values; and **`ROW_NUMBER() … ORDER BY <timestamp> DESC`
"latest row per entity"**, which is a max-date measure or a flag on the row, not a rank.

Validate argument forms with `validate_mdx_expression`, but **never trust it as proof of
correctness** — it checks syntax and member resolution only. Four wrong formulations passed it
in one day, three of which returned wrong data. Proof is the live two-group query of rule 3.

**Reported, not changed.** A `(Pooled)` measure that returns NULL when one component's fact
rows are absent, where the KB's own formula would treat the missing component as zero,
mis-ranks every such entity — and in the worst direction, since "no adverse events recorded"
should read as *better*, not unmeasurable. In one model that hit 30% of the entities in scope,
and the score they should have had would have put them at the **top** of their group. It was
left alone on purpose: it is a shared measure, and whether an absent fact row means "zero" or
"unknown" is a modelling judgement for the owner, not something to reverse-engineer from one
task's gold. Raise it; do not silently flip it.

**Removing a blocker frees a task to meet the next one.** On a 39-task run the agent found
these measures and wrote them into its own SQL unprompted — 4 of 12 statements on one task, 6
of 14 on another, 18 of 26 on a third — so the descriptions do make them discoverable. One task
flipped from a unanimous three-run fail to a pass; two others used the rank correctly and
failed downstream on other defects. Do not forecast score from a capability landing. And when
counting a measure's usage, count occurrences inside SQL strings — counting names in the raw
result JSON overcounts badly, because the column catalog is re-served every turn.

### Readings that belong to an owner, not to the row that links them

- **A satellite row reaches ONE entity through its link, but the thing it describes may belong
  to that entity's OWNER, and then the question means all of the owner's rows.** Measured
  2026-09-21 on polar_equipment: a weather reading joins to an equipment through that
  equipment's own maintenance record, but the reading describes a STATION, and each station
  filed 40 to 60 of them. Two references read the station's whole history, not the one linked
  row, and the difference is not a nuance: on the linked reading the equipment split 255 / 252 /
  352 across three temperature zones with no overlap, and on the station's history all 850
  equipment appear in **all three**. One reference counted equipment per zone (850 / 850 / 850),
  another built a readiness rule whose structural term is met when the station has EVER recorded
  conditions clearing it (5 equipment qualify on the linked reading, 232 on the station's).
  Neither is expressible from the entity grain. Ship **a second dataset at (entity, owner's
  reading) grain** with its own degenerate dimension and every attribute suffixed, plus an
  entity-grain aggregate of the owner's readings (a max, or an EXISTS verdict) so a rule the
  caller assembles by hand can still reach the owner's scope. To find these before you spend,
  ask of every satellite: *does this row describe the entity, or something the entity belongs
  to?* A location, a station, a site, a batch and a shift all take this shape.
- **When you add the second grain, the first grain's column must learn to name it in the same
  commit.** The exposure grain above shipped and the entity-grain `Temperature Zone` was not
  touched; the agent never discovered the new dataset and grouped on the old column. This is the
  half-applied twin this document already warns about, in its dataset-shaped form.

### Group vs entity level

- Group-level and entity-level versions of a statistic are separate, separately named objects.
  Where the definition is a formula over other quantities (ratio, difference, weighted score,
  share), the group-level version must recompute the formula from aggregated components, as a
  calculated metric referencing component measures. Do not compute it per row in dataset SQL
  and average that column — that answers "the typical entity", not "this group", and once
  components are collapsed per row the group reading is unrecoverable. That makes **three**
  separately named objects: the formula over aggregated components, the mean of per-entity
  values, and the entity's own value — each description saying which question it answers and
  naming the others. Every component must exist as its own measure.
- Before shipping all three, check whether the entity-level variant is actually distinguishable
  from its base at entity grain. Where it is provably identical, ship one. The same test retires
  a whole trio: where a rate is 100% for every row in the warehouse, the group figure and the
  mean of per-entity figures are provably equal.
- **A pooled ratio is computed over ONE population, and the denominator's total over that
  population ships beside the bare one.** A KB divided recovery value by days lapsed; recovery
  value lives on a record covering 995 of 1500 returns, days lapsed on all 1500. Dividing the
  995-row numerator total by the 1500-row denominator gave 15.79 — a figure over no population
  at all, where the intersection reading is 740,008.86 / 31,776 = 23.29. Publish `Total Days
  Lapsed (Costed Returns)` and divide by that; keep the all-rows total bare with its own count,
  and have each description name the other with both figures. The same twin answers the
  question that asks to see the ratio's components beside it: a reader who joins the two
  records gets the same-population totals, and a caller reading the bare all-rows total beside
  a 995-row numerator is off by 47 percent with nothing to say so. Pin the restricted total in
  the dry-run.
- **A single-entity audit wants the entity's DETAIL ROWS, not the entity-grain rollup.** The
  rollup is the natural landing place for a question naming one entity — "check entity P's
  therapy hours", "audit account A's fees" — and where the entity carries several source records
  with different values, the rollup has already averaged away the answer. Observed: entity-grain
  averages of twelve stored rates, over entities carrying up to three records each, were
  selected for four separate single-entity audits; each returned one plausible row where the
  answer was two or three. Say so on the rollup group itself: name the detail grain, say how
  many source records an entity can carry, and state that an audit of one named entity usually
  wants that grain.
- **Entity-grain reading summaries beside a row-aligned fact.** Where a fact joins each event to
  the one reading row-aligned with it — a correct grain decision — but an entity carries one to
  three readings (906 / 45 / 1 entities), "the entity's current temperature", "its average
  temperature" and "is it unstable" are questions about the entity's readings, not the event's.
  Publish on the entity dataset: reading count, the latest reading's values and timestamp, the
  averages, every KB formula on both bases (`… (Average Of Readings)`, `… (Latest Reading)`),
  and every KB verdict at entity grain with its count measure. The aligned reading differed from
  the latest on 44 of 1000 rows, and a per-entity verdict is 67 entities where the per-event flag
  is 71 rows. The event-grain flag's description must say all of this and route a count of
  entities to the entity-grain measure.
- **A composite of percentile ranks must rank every ingredient over ONE population**, and that
  population is the entities carrying *all* the ingredients. Ranking each ingredient over its own
  non-null set gives each a different denominator, so their mean averages incomparable scales.
  Observed: within one category the three ingredient populations were 42, 60 and 78, the
  composite was wrong for every entity, and 7 of 48 group winners changed. The defect is visible
  without any reference answer, so this is a correctness fix, not tuning.
- **Rank on the undivided sum, not on the mean.** Ordering by a sum and by that sum divided by a
  constant is the same ordering in exact arithmetic, but the division is lossy in floating point
  and *invents ties*: two distinct sums (`2.0` and `1.9999999999999998`) collapsed to one double
  and produced two rank-1 entities where there is one. Publish the mean as the score if that is
  the natural scale, and rank on the sum.
- **A sum of squared shares IS expressible — do not record it as an engine limitation.**
  Herfindahl-style concentration and diversity indexes (`sum(share_i²)`, `1 − sum(share_i²)`)
  look impossible because no aggregation squares a share, and three were written off on that
  basis before the pattern was found. Give each row its group's squared share divided by that
  group's row count, and a plain `SUM` over any set of rows reproduces the formula exactly:

      SUM over rows of (share_g² / rows_g)  =  SUM over groups of share_g²

  They then behave as ordinary additive measures — no second fact table, no extra conformance
  surface, correct under any filter. Verify against a direct computation over the source tables
  and pin both numbers as dry-run assertions. The same trick covers any "sum over groups of
  f(group)" where `f` is computable per row. State in the description that the index is read as
  a single figure for the filtered population, *not* grouped by the dimension it sums over —
  grouping by that dimension returns each group's own term rather than the index.

### Grain and time

- Where the fact grain is finer than the entity (one row per reading/snapshot per entity),
  state on every flag and measure whether it answers "has this entity *ever* had X" or "does it
  have X *as of its latest reading*" — a model silent on that distinction produces plausible
  wrong answers. Ship latest-state `(Current)` variants of state/cost/output measures as objects
  distinct from history-wide aggregates.
- **A per-record rate or score whose entity has several records states its grain and names the
  open slot.** One value per snapshot where a plant has one to three snapshots: asked for a
  projected loss "across the risky plants", the agent reduced to each plant's latest snapshot
  where every snapshot counted, and was 8 percent off with everything else right. Every such
  description says: one value per snapshot, NOT one per entity; a sum or average across entities
  counts every snapshot unless first reduced to one row per entity; the two differ; when the
  question does not say which, ask.
- Don't trust `semi_additive (position: last)` for "latest snapshot per entity": it needs the
  trigger level to sit inside a hierarchy that also contains the entity, and a snapshot-keyed
  hierarchy plus a separate entity hierarchy cannot express it — the failure is silent, falling
  back to base aggregation with plausible numbers. Use `FIRST_VALUE(…) OVER (PARTITION BY entity
  ORDER BY snapshot DESC)` window-carry columns instead, and confirm via `get_outbound_queries`
  that the warehouse SQL contains the window function, not a plain `MAX()`.
- Document each measure's natural row grain. Averaging over entities silently differs depending
  on whether the inner grain is the snapshot or the entity; a coarser-grain figure requires an
  explicit reduction first, and the description should say so.
- **One age convention per model, and it is the warehouse's own date arithmetic.** A model
  published a current age as `EXTRACT(YEAR FROM AGE(NOW(), start))` (whole completed years) and
  the age at each snapshot as `(snapshot − start) / 365.25` (continuous), so one KB rate had two
  values for the same row, differing on 449 of 462 snapshots a year or more after the start
  date. A plain SQL reader writes `AGE()` for both — the warehouse-types rule applied to dates,
  so the native form is the bare name. Ship the continuous reading as an `(Fractional)` twin and
  carry it down every consuming formula. Verify with a count of rows where the two conventions
  round differently before deciding it does not matter.
- **A rate defined "since commissioning" is undefined before commissioning — NULL, never a
  negative number — and its description states how many rows that is.** 445 of 998 snapshots
  were timestamped before their entity's go-live date and 91 more inside the first year; the old
  formula returned negative rates silently and an "average across all snapshots" was meaningless.
  `count(*) where <event timestamp> < <start date>` finds this unaided; run it for every "since
  X" quantity.
- Profile every date and every headline numeric for **degeneracy** before modelling on it. A
  column that is a single constant across the whole warehouse makes every statistic over it
  trivial and every sort by it fully tied. Observed: receipt and decision dates were one value
  each, so every processing time was the same 8 days; every application carried the same status,
  so every approval rate was 100%. Say so in the description of every object that touches such a
  column, and expect any task that sorts by one to have a non-unique expected answer.
- **Before shipping a `NOW()`-relative flag, profile it against the benchmark's own calendar.** A
  `NOW()`-based dataset column works mechanically — it is pushed down and re-evaluated per query,
  not frozen at deploy — and that says nothing about the values. Observed: every deadline in a
  schema fell in a three-month window two years before the real current date, so
  `CURRENT_DATE − deadline > 0` was true for **240 of 240** rows and the nearing-deadline
  complement selected **0**. Where the questions supply their own reference date, ship the raw
  date and let the caller subtract; where you ship the now-relative figure anyway, put the
  degeneracy in the **first** sentence of its description.
- **A recorded monetary or loss column says it is realised and historical.** A question wanted a
  projected lifetime loss — a rate times an assumed volume, price and horizon, from a KB entry
  deleted on that task — and the agent summed the recorded column instead, twice. The description
  must say the column is realised and historical, that a projected / potential / expected /
  lifetime figure is a forward-looking formula this warehouse does not store, and that the agent
  should ask for the formula and constants rather than substitute this column.

### Support sets, missing inputs, and competing readings

- Any measure computed over a subset of rows must expose its support set, and both pieces must
  be visible to the discovery API — never hidden. Ship the count of entities that actually
  entered the computation (the regression n, the non-null count) and, where a caller would
  select that population, an availability classifier saying which entities carry the required
  inputs. The generic entity count is not a substitute — it over-selects. Where a formula has
  several components, the support set is the **intersection** of entities where every component
  is present — one count per formula, never per-component counts, never the widest one.
- **A support-set count is itself a reading**, and a "group with enough entities" gate can mean
  either it or the generic count. Where you ship both, say in each description that the choice
  changes which groups clear any given minimum, give the live counts for both, and direct the
  caller to confirm which population the question means.
- **A reading you exclude on data grounds still ships as an object the moment you name it in
  a description.** Excluding a degenerate reading is legitimate — a definition that selects
  every row discriminates nothing — but the instant the bare object's own text says "read
  the other way, all 994 qualify", the caller has been told a reading exists and left unable
  to select it, which is the half-applied twin this section already warns about. Measured
  2026-09-20 on insider_trading: "linked to a corporate event" read as the event row
  existing is true on all 999 rows, so the recorded-event reading was published bare and the
  degenerate one only described. The reference used the degenerate reading; the agent asked
  the right closed question and could not act on the answer. Publishing it as a named twin
  converted the task on the next run. Either publish it or do not mention it.
- **The missing-input policy is itself a reading, and needs its own object.** Where a formula's
  inputs are absent for some entities, ship both the strict version that excludes them and the
  zero/coalesce version that keeps them, named asymmetrically, each carrying its coverage count.
  Observed: only the strict reading shipped, dropping 387 of 954 entities where the questions
  wanted all of them. Note the half-applied failure mode: on a later model the divergence was
  found and written into the surviving object's *description* instead of being shipped as the
  second object. That is not compliance — the sentence tells a caller the other policy exists and
  still leaves them unable to select it, and by the name-decides rule they will not act on the
  sentence anyway.
- **"No record" and "a record with an empty field" are two different nulls, and only the second
  gets the zero twin.** A score defined per record is null both where the record is absent and
  where the record exists but one field it needs is empty, and a reference routinely reads the
  second as 0 while leaving the first null. Measured 2026-09-21 on polar_equipment: 47 of 859
  maintenance records carry no maintenance cycle, so the readiness score and all three scores
  built on it dropped those rows; the reference averaged them as 0 (one type: 34.30 over 132
  records against the strict 36.94 over 121). The twin must therefore be *conditioned on the
  record existing* — `CASE WHEN <record key> IS NULL THEN NULL WHEN <field> IS NULL THEN 0 ...` —
  and it must be carried down into **every** score built on it, each with both coverage counts.
  Shipping it converted the task outright: the same four-column query passes on the twin and
  fails on the strict reading by 11 of 24 cells.
- **A zero-filled twin zero-fills EVERY input, and every composite with a null population gets
  one, at row and aggregate grain.** A twin that coalesced only one of three terms was neither
  reading: a "high risk" screen returned 467 rows where either honest reading returns 431
  (strict, over 283 entities) or 431 (zero-filled, over all 670). And selecting "the six where
  the choice matters" was itself a defect — four other measures each lost 100–200 entities to
  nulls and had no twin, so "the average latest score across all accounts" could only be answered
  over the 558 with a score (0.648) where the all-accounts figure is 0.414. Ship the twin
  uniformly; each bare reading's description names it with both counts.
- **An average over a NAMED LIST of inputs has exactly two readings, not three.** Strict (a
  `CASE` with no `ELSE` propagates NULL through the sum, so any unrated factor voids the average)
  and coalesce-to-zero over the full denominator. Averaging over "whichever inputs are present" —
  renormalising the denominator — is a third policy no source states, and it was one model's
  *bare* object while the reference used the zero reading every time. Ship strict bare because
  the KB writes no `COALESCE`, and the `(Unrated As Zero)` twin beside it, on every formula
  downstream that a question reaches for. Say in every reading's description which inputs each
  profile leaves unrated, and that any other substitute weight is the user's to name and
  recomputable from the published factor attributes.
- **The coalesce policy is a per-formula assertion against the KB text, not a sentence in the
  model description.** A model stated correctly that it coalesces only where the KB writes
  `COALESCE` — and then its index coalesced a term to zero on 943 of 1000 events where the KB
  writes none, so every one of those events got an index decided by two of its three terms. The
  check is mechanical: for each formula, the emitted SQL contains `COALESCE` on an input if and
  only if the KB definition's text does. Put it in the generator beside the pinned constants, and
  pin the support-set count the strict reading produces so a later edit cannot quietly widen it.
- **A formula used in a "below X" screen gets its missing-input-as-zero twin.** 36 entities had
  no performance record, so the score is null there and a "reliability below 0.5" screen silently
  drops them where a zero-filled reading keeps 23 of them (174 vs 151). Apply it wherever a null
  input meets a less-than screen, and ship the flag's twin too.
- **A formula whose inputs sit on a narrow record gets a reading judged only over that record,
  beside the three-valued one.** A mass-casualty test `casualties + injured > 100 OR medical ratio
  < 0.01` needs a staffing record present on 57 of 1000 events. Under SQL's three-valued logic
  the flag is `Yes` on 955 events (the first branch settles it and the unknown ratio drops out of
  the `OR`); a reader who joins the staffing table evaluates the test on 57 and gets 54. Both are
  defensible, they differ by a factor of eighteen, and only the second is recoverable from the
  first — so ship `… (Staffed Events Only)` with its own count, name it in the bare flag's
  description with both counts, and route the population to the user.
- **Emit the "otherwise" branch from a GENERATED pass over the whole verdict list, and count the
  nulls on every flag before you ship.** The rule above is right and it is applied to the four
  flags you are thinking about and forgotten on the other seventeen, because each flag reads
  correctly on its own and no gate counts its nulls. Measured 2026-09-22 on virtual_idol: a build
  that had already applied it twice shipped **17 of 21** verdict flags null on the majority of the
  population - `Loyal Achiever` Yes on 4, No on 60 and **null on 914** of 972 fans; `Platform
  Promoter` 4 / 35 / 933; `Event Enthusiast` 114 / 3 / 863. What it cost, in one trajectory: the
  agent asked the user which reading of a segment to use, was told, wrote exactly the right query
  with `= 'No'` for "the other fans", and got **zero rows** off a flag that was null on 741 of 821
  rows at that grain. The agent did everything right and the model could not answer. So: drive the
  bare flag and its `(<Record> Record Only)` strict twin from one table of (flag, condition,
  record) and have the generator emit both, and add a build gate that fails when a published
  Yes/No attribute is null on more rows than it is non-null. Prose review cannot see this class.
- **A CASE formula's "otherwise" branch covers the entity that has no satellite row.** A score of
  3 / 2 / "1 otherwise" over a security profile's two columns met 440 of 870 profiles with no
  security record; the build scored them null, so a top-5 by sensitivity showing the score beside
  it lost four of its five rows. A profile with no security record is neither fully encrypted nor
  strongly controlled — that is what "otherwise" says — so the bare score is 1 over all 870 and
  `(Security Record Only)` keeps the 430. Do not read an unknown branch into a formula that has
  none; the null-preserving reading is the twin.
- **A classification flag inherits the ambiguity of every formula it is built from, and hides
  it.** A `Yes`/`No` column has no room to show which reading it tested: the caller sees a
  verdict, cannot tell it from the other reading's verdict, and has no way back to the inputs.
  Observed: a KB classification "engagement above X but outcome below Y" was built over two inputs
  that each had a documented competing reading, both readings of both inputs already published as
  separate attributes with counts. The flag silently picked one of the four combinations; the two
  plausible combinations select **14 entities and 22** out of 126 judgeable — an 8-entity swing
  invisible from the flag alone and invisible to every gate, because each individual number is
  right. The rule: a flag whose inputs have competing readings must (a) name in its own
  description the exact attribute each threshold is tested against, so the reading is
  recoverable, and (b) ship the twin flag under the alternate reading wherever the selected
  populations differ materially, each stating both counts. Where several ambiguous inputs
  combine, do not ship the cross-product — ship the KB-literal combination as primary and the
  single most plausible alternative as the twin, and say in both descriptions that the others
  exist and how to compute them from the published inputs.
- **When the KB's own vocabulary distinguishes a raw column from the composite, keep the
  composite as the operand and record the disagreement rather than shipping a twin for it.**
  Where one KB entry's formula names a cluster column by its recorded meaning and two other
  entries name the composite by its own title, two reference queries nonetheless read the
  composite's operand as the raw column. That is a reference deviating from its own KB, not a
  competing honest reading, and a twin for it would be gold-informed. Record it in the change log
  as a cap and move on.
- Hidden is only for terms with no standalone meaning (a sum of squares, a rebased denominator).
  Before declaring the model done, list every hidden object and state what question could be asked
  about it; if you can phrase one, unhide it. Report the list with evidence. Also confirm every
  defined object is referenced by the model file — no orphans that exist but cannot be queried.

### Values, types and units — the value pipeline

The reference answers and the raw baseline are plain SQL readers of the warehouse. Where the
model's arithmetic differs from a plain reader's, the values are right to many significant
digits and wrong after the grader's rounding — a failure class that looks like "genuinely
wrong" and that no agent guidance can move. On one database this was every one of the four
reachable tasks in a 0/10 arm.

- **Evaluate every KB formula at the warehouse's own column types, and widen to double only
  afterwards.** `bigint / 24` is integer division (9 hours is 0 days, 27 hours is 1);
  `1000 / (bigint + 1)` is an integer quotient (113.37, not 113.48); `real + real` sums in
  float32 before any halving (138 of 1000 scores differed at two decimals from the widen-first
  form); `real / real` is a float32 quotient (9 of 479). The grader rounds both sides HALF_UP at
  two decimals and compares strings, so each of those is a hard mismatch on an otherwise exact
  row. The habit that causes it is a good one applied one step too early: casting every operand
  to `double precision` for tidiness. Cast the **result** instead. Verify mechanically — `SELECT
  pg_typeof(<formula as the KB writes it, over the raw columns>)` tells you where the warehouse
  truncates, and a count of rows where `round(native,2) <> round(widened,2)` tells you whether it
  matters. Where the two differ, the **bare name carries the warehouse evaluation** and the
  exact-arithmetic reading ships as an `(Exact)` twin, each description saying the two select the
  same rows under any threshold (pin that) and differ only in the printed value.
- **A reference aggregate over a `real` column is rendered at SIX SIGNIFICANT FIGURES, and the
  semantic layer's answer is not.** `SUM(real)` returns `real` in Postgres, and the harness
  prints a float4 with six digits: a true 128607.78 arrives as `128608`, while the layer returns
  double precision and prints `128607.8`. The grader's numeric comparison is tighter than that
  1.6e-6 relative gap, so the cell is simply wrong. Measured 2026-09-21 on polar_equipment: a
  20-row group listing matched gold on the population, the recomputed ratio, the classification
  bands and the sort, and failed on 15 of 120 cells that were all in one column, all in the
  seventh digit; rounding that column to six significant figures by hand turned the task green.
  No model object emits that rounding and no agent writes it, so **this is a cap, not a fix** —
  but find it before you spend, with `SELECT pg_typeof(...)` on the summed column. Check it
  first whenever a probe returns the right shape, the right rows and one column of
  almost-right numbers.
- **Integer division is a FAMILY, not a special case: run `pg_typeof` over every KB ratio, not
  the ones that look like counts.** Measured 2026-09-22 on virtual_idol, where four of the
  knowledge base's ratios are integer quotients at the warehouse's own types and the measurement
  pass caught only two of them: Achievement Density and Loyalty Progression Rate disagree with the
  numeric reading on 63/64 and 62/64 rows, and Chattiness Score and Follower-to-Following Ratio -
  both reading a JSON leaf cast to `bigint` over a `smallint` - on **787 of 821** and **182 of
  185**. The downstream populations move with them: Engaged Lurker is 32 interactions on the
  numeric reading and 70 on the native one. The two ratios in the same model that need NO twin are
  the ones with a `real` operand, because a `real` promotes the integer and the quotient is
  already `double precision`. So the test is mechanical and per formula: cast each operand to its
  declared type, `pg_typeof` the quotient, and count the rows where the two roundings differ.
- **Where the addition happens matters, not only the cast.** Check `pg_typeof` of each
  *intermediate*, not of the result: `real * 10` and `real / 100` are already double on Postgres
  (the integer promotes to the category's preferred type), `real + real` is not. A plain reader's
  `COALESCE(a::real,0) + COALESCE(b::real,0) + COALESCE(c::real,0)` adds in float32 and only the
  `/ 3` widens; a model that widened each term first was right to six digits and flipped 4 of 405
  downstream indexes at the second decimal — every one a *halved* value, because halving parks a
  third of all values on a `.xx5` boundary where a 1e-7 disagreement decides the rounding. Write
  the formula in the reader's shape: `(a::real + b::real + c::real)::double precision / 3`.
- **A number the warehouse holds as JSON text has the type its column meaning declares, and a KB
  formula reads it at that type before widening.** A JSON field has no SQL type of its own, so the
  meaning's declaration (`REAL`) is the type and the read is `(doc->>'Field')::real` inside the
  arithmetic — exactly what a plain reader writes. Reading the text straight into double keeps
  digits the warehouse never had (0.91 against 0.9100000262), and it is not harmless: a ratio of
  extremes was 2,237,875,936 through `::real` and 2,237,875,810 through exact decimals — a
  126-unit disagreement on a value right to nine digits either way. The same applies to sums: 57
  per-snapshot rates summed at 75-million magnitude gave `.43` widened-first and `.34` through
  `::real`, a first-decimal disagreement on row values that agreed to six digits. Apply `::real`
  to every field the column meaning declares REAL (29 casts in one model's two JSON columns);
  keep TEXT-with-unit-suffix fields on their parsed double read. Display copies keep the exact
  decimal text (`::numeric` on JSON text, `::text::numeric` on a stored `real`); only arithmetic
  goes through the declared type. **Any ratio of extremes, any value of large magnitude, and any
  sum over thousands of rows amplifies float32 noise past the second decimal** — the "the grader
  normalises float32 noise" finding under After acceptance holds for row-level values and fails
  for these.
- **The opposite can hold too: a jsonb leaf read as EXACT DECIMAL.** jsonb stores numbers as
  `numeric`, so `::numeric` is sometimes the faithful read. Measured: `(0.1 - 0.0076)/0.3 + 0.007`
  is `0.315` exactly and `0.31499997` in float32, which the grader's HALF_UP turns into `0.32`
  against `0.31`. It moved 2 of 1011 rows on one formula and 0 on three others, so decide **per
  formula** — a model-wide switch risks every already-exact task. Both rules are measurements, not
  principles: count the rows where the two roundings differ and follow the count.
- **A `real` column published for display carries the decimal Postgres itself prints, not the
  IEEE widening.** A stored `real` 0.755 reaches every SQL client as the text `0.755` (Postgres
  prints the shortest round-tripping string) and the reference is graded from that; the engine
  reads the same column through JDBC as 0.7549999952. Rounded HALF_UP at two decimals the first
  is 0.76 and the second 0.75, so every value whose third decimal is 5 — 27 of 241 scores, 11% —
  fails with nothing else wrong. Publish display copies of `real` columns (and of `real`-typed
  formula results) as `(col)::text::numeric`. This is **not** the `real::numeric` cast below:
  that goes through `float4out` at six digits and truncates; `real::text::numeric` does not
  (verify on the column's largest value). Keep the double form for arithmetic. Verified: the fix
  took a three-row task from 0 to 1 with no other change, guarded by a pin
  `count(*) where col::text <> col::double precision::real::text = 0`.
- **A number stored as TEXT with a unit suffix needs both forms published.** Warehouses here
  routinely store a rate as `'1.6 points/month'`, `'99,491.77 USD/min'`, `'12.45
  connection-point/ownership%'`. Parsing the leading token is obvious and necessary; keeping the
  stored string is the half that gets forgotten, and questions ask for it. Observed: three tasks
  returned the right rows in the right order with every other column identical and failed on
  `99491.77` against `"99491.77 USD/min"`. Publish the parsed number for every filter,
  comparison, sort and aggregate, and the verbatim text as `<Name> (As Recorded)` for when the
  caller asks to see, show, list or report the value. Give the distinct-string count in the text
  column's description, and where the parse can fail or yield a non-finite value say so (one
  warehouse stored the literal `'inf'` on 197 rows). One shared helper for the wording keeps
  eleven descriptions saying the same thing — and note the failure mode: one model shipped the
  pair correctly for two of its twelve unit-suffixed columns and omitted it for the rest.
- **A PHYSICAL constant a KB formula needs but does not state is written out at its standard
  published value and composed inside the formula — never pre-collapsed into a textbook
  shortcut.** Distinguish this sharply from the *unspecified* constant below: "assuming a
  standard number of medications" is a number nobody can look up; G, the solar mass, the
  astronomical unit are numbers everybody can look up, and they are yours to write out —
  CODATA/IAU nominal values, as many digits as the source gives (`6.67430E-11`, `1.98847E30`,
  `6.957E8`, `1.496E11`, `1.898E27`, `7.1492E7`, `109.2` Earth radii per solar radius). What went
  wrong without this rule: escape velocity shipped as *Earth's 11186 m/s times the square root of
  the Earth-unit mass-radius ratio*, density as *the solar ratio times 1.408 g/cm³*, the
  gravitational parameter as *1.32712440018e20 times the solar mass*. Each is a correct identity
  to three or four significant digits and disagrees with `sqrt(2GM/R)`, `M/(4/3·π·R³)`, `GM`
  composed from the named constants in the fourth digit — 586 against 585.45, 1545 against
  1544.62 — and a plain SQL reader composes the constants. Two corollaries: (a) evaluate the
  formula in the *shape the KB writes it*, not an algebraically equal rearrangement, because
  floating point is not associative; (b) say which constants and values were used, once, through
  a shared clause. Where a permitted question states a constant, that is confirmation of the
  standard value, not a licence to fit.
- **An unspecified constant in a KB formula is a reading the CALLER supplies — never pick one.**
  A KB entry reading "assuming a standard number of X" defines everything except the number; any
  value you choose is either arbitrary or lifted from somewhere you should not have looked.
  Publish the **per-unit** figure and, where the warehouse records the count, the version computed
  from it, then say in the description that the KB's multiplier is unstated so the caller must
  supply it or ask. A caller told the multiplier is theirs can multiply; a caller handed a
  hardcoded one cannot tell it was invented.
- **A KB formula over two lengths, or two masses, is a formula over one unit — do not ship the
  dimensionally inconsistent reading as a twin.** This reverses what the twin rules would suggest:
  an equilibrium temperature `T × sqrt(R / 2a)` with `R` in solar radii and `a` in AU was
  published twice, "as written" (43 to 113,207) and converted (2.9 to 7720 K), each naming the
  other. That is not two readings of an ambiguous definition; the literal one is a unit error, and
  it cost a task directly — the agent, seeing two, asked the simulator which, and the simulator
  said "the direct formula as-is". Convert into the unit system the KB itself uses for that entity
  class, publish that reading bare, and where a *rendering* is plausible (percent beside fraction,
  km/s beside m/s) ship that as the twin.
- **Every Yes/No classification evaluates under SQL's three-valued logic, so that `= 'No'`
  reproduces `NOT (<definition>)`.** A compound flag written `CASE WHEN a AND b THEN 'Yes' WHEN a
  IS NOT NULL AND b IS NOT NULL THEN 'No' END` returns null for a row that is *definitely* not the
  thing and that a plain `WHERE NOT (…)` keeps. Write the 'No' branch as the disjunction of each
  input's recorded negation, so 'No' fires as soon as one recorded input settles it and null is
  reserved for rows nothing recorded settles. State the convention once on the profile holding the
  flags. The same rule gives every varying quality flag a Yes/No twin on the value it tests — 'Yes'
  when the flag equals it, 'No' when it is *recorded and different*, null when unrecorded —
  because a reference written `flag <> 1` excludes unrecorded rows and a caller filtering `flag =
  0` does not. Apply it to every flag that ever varies; a flag constant across the warehouse needs
  no twin (Surface size).
- **When the KB defines two or more contrasting classes over a child entity, publish the parent's
  COMPOSITION over them.** "Parents that only have class-X children" was implemented as *every
  measurable child is X* (49 parents) where the question meant *has an X and has no Y* (27),
  because X is classified by one measurement and Y by another, so a child with the second and not
  the first is a Y the first reading never sees. Ship `<Parent> Composition` with values `X Only`
  / `Y Only` / `Mixed` / `Neither`, judged over every child placeable in *any* class, plus one
  `Has X` / `Has Y` pair and the count metrics; keep the narrower reading under a qualified name
  with the differing count. The composition object also answers the follow-up the single flag
  could not.
- **A KB quantity that is a ratio gets a geometric mean; a difference gets its absolute value.**
  "Average period ratio" over a group's adjacent pairs was published as the arithmetic mean only;
  the conventional average of ratios is geometric (`exp(avg(ln x))`), the two agree on every
  two-member group and differ on 177 of 193 larger ones, and only the caller knows which was
  meant — ship both, say which is which and how many groups they disagree on. A
  recorded-versus-derived comparison ("fact-check the law") sorts by *how far apart* the two are,
  so the signed difference needs an `Absolute Difference` sibling as its sort key.
- **A percentile cut has two readings, and the live data usually disagrees on the boundary
  member.** "In the 75th percentile or higher" is `PERCENT_RANK() >= 0.75` read literally and
  `value > PERCENTILE_CONT(0.75)` read as a threshold on the interpolated value; they differ
  exactly when a member's value equals the interpolated cut (147 against 146 members on one
  database). Compute both, count the disagreement, and where it is non-zero ship the second as
  `(Above Nth Percentile Value)` with both counts in both descriptions.
- **A `character(n)` column's recorded value is the padded string, and `::text` trims it
  silently.** A state stored as `character(20)` is one letter followed by nineteen spaces; the
  reference returns it padded, the grader compares byte-for-byte, and a model that cast it to text
  returned `'Y'` against `'Y                   '` — every row right, every row failed. Publish the
  recorded width as the display attribute (`rpad(col::text, n)`, since every string cast trims)
  and the trimmed letter as a `… Code` twin for filters, and say on the display attribute that an
  equality test against the bare letter matches nothing. Check
  `information_schema.columns.data_type = 'character'` in the type probe; it is the only string
  type with this behaviour.
- **An absolute amount and the ratio built from it name each other as amount versus proportion.**
  Watts lost and a loss ratio both answer "how much power is lost internally", and the agent took
  the watts. Each description says which it is — "an ABSOLUTE amount in watts" / "a dimensionless
  PROPORTION" — names the other, and says the two are not interchangeable, so the model's own
  ask-trigger phrasing fires. Do this for every amount/ratio pair sharing an everyday phrase.

### Definitions, labels, and naming

- **Where two objects can answer one question, the name decides — not the description.** Verified
  repeatedly and expensively: the agent picks the object whose name best matches the question's
  words and does not act on description text pointing it elsewhere, *even when that text is the
  first sentence*. In one case a description reading "prefer X" was ignored on two consecutive
  runs. In another, a task used the correct value, the correct population and the correct sort
  across three runs and never all three in one submission, because two objects shared one concept.
  Descriptions still carry disambiguation for a human reader and to trigger the ask-the-user path,
  but never rely on one to steer a choice. Resolve competition structurally, in this order: (1) if
  a reading has no basis in the KB, **delete it**; (2) otherwise move the plain, unqualified name
  onto the reading the questions mean and push every other behind a qualifier.
- **A reference can read the same concept DIFFERENTLY in its two phases, so both twins must
  ship even when one looks like a unit error.** Measured 2026-09-21 on polar_equipment: phase 1
  wanted a vehicle composite with a text speed field converted and phase 2 wanted the same
  composite with the speed as stored. Neither is wrong and the conversion is not a bug fix —
  deleting either reading loses a phase. The agent's own failure mode here is to carry the
  choice forward: it filtered on the strict verdict and printed the converted composite, because
  the user had chosen "converted" one turn earlier. Say on every such verdict that **the value
  shown beside it is the one that decided it**, and that an earlier turn's choice of reading
  does not carry into a later one. That sentence converted the phase.
- **Naming the twin is not enough — the bare-named reading wins about 40 to 1.** Measured:
  `(Recomputed For Group)` twins were used 2 times against 39 uses of the bare primaries, and
  recorded-case twins 5 times against 204 uses of the canonical attributes, with the reading one
  task's grading actually required used **zero** times. What converts is the **bare reading's own
  description** carrying the twin's name, **both live counts**, and an explicit statement that its
  plainer name does not settle which the question wants. Two verified conversions: an attribute
  whose canonical form merges an abbreviation (255 entities against 222 when only case is folded)
  took a task from 0-of-3 to passing in both later runs, with the previously-unused twin selected;
  a measure declared "one of three readings, and its plainer name does not make it the default"
  took another from 0-of-3 to 2-of-2. In both the agent asked the user which reading was meant,
  quoting the two counts back, and used the answer.
- **An ask that fires where the agent was already right LOSES the task, and that is measurable.**
  The ask-budget rule says a needless trigger subtracts a coin; this is worse. Measured 2026-09-22
  on virtual_idol: a task passed the baseline because the agent wrote the strict reading of a
  concept unprompted. A twin was then published for the other reading with the recommended closed
  question naming both counts - and on the next run the agent asked exactly that question, the
  simulator answered **"neither of those definitions is quite right"** and invented a third reading,
  and the task went **0.7 to 0**. Publishing the twin was right; attaching the ask to it was not.
  So before adding a closed question to a bare object, check whether the baseline already gets that
  object right, and if it does, publish the twin **without** the ask - the reading stays selectable
  by name, which is what the caller needed.
- **THE ASK FIRING IS NOT THE WIN CONDITION — THE ANSWER IS, AND THE SIMULATOR OFTEN ANSWERS
  AGAINST THE REFERENCE.** This document's twin-plus-ask rule is right and it has a ceiling that
  is worth knowing before you spend a third iteration on description text. Measured 2026-09-21
  on polar_equipment, where the ask was moved to the FIRST sentence of five competing readings
  and then fired on 4 of 4 remaining tasks across three runs: it converted 2 of 7 phases, and
  both were cases where **the question itself settled the choice** ("within each type"; a
  verdict and the value beside it). On the other four the ask fired perfectly and the user
  simulator chose the reading the reference does not use, or named two join paths in one
  sentence, or asked for a combination of two adjustments that no twin carried, or refused
  outright ("this question is out of scope"). On one task the agent stated *in its own question*
  that the choice offered yields zero rows, and the simulator picked it anyway. Three
  consequences:
  - Count an ask as converting only when the score moves. Tally *ask fired* and *answer
    correct* separately in the report; they came apart 4 times out of 6 here.
  - When the ask fires and the answer is wrong, **more description text is spent money**. Go
    structural instead: move the plain name onto the reading the questions mean, which converted
    a task whose counts and averages already matched and which lost on a label alone.
  - Publishing a twin for an answer the simulator sometimes gives can turn a hand-written wrong
    answer into a cleanly-executed wrong answer, which is not a gain. That is the demand gate
    below, and this is what failing it looks like.
- **Count ask clauses against the coin budget, and count both sides the same way before believing
  a comparison.** Each trigger costs about two coins: on exchange_traded_funds 11-12 of 19 tasks
  exhausted their coins every run, one of them after ten `ask_user` calls and having been given the
  right answer. Grep the emitted YAML and name what each ask displaces. Beware the comparison: a
  loose grep for "the user" read 32 here against a tuned model's 24, and a strict grep for the
  trigger forms put both at **16** — the gap did not exist. Drop an ask where the baseline shows
  the agent already right; that is per-object evidence, not a headcount against another model.
- **That steering is demand-gated, not coverage-gated.** Before shipping a twin, confirm the
  failure is *"the agent does not know a choice exists"* and not *"the agent knows and still
  fails"*. On one model the agent **already** asked the population question in the baseline and
  was **already** told "treat missing values as zero"; adding a population-choice clause did not
  raise asking (2.3 to 2.0 per run) and shipping the twin produced **zero uses** across a full run
  despite appearing in the discovery response. A twin fixes a discovery problem; it does not fix a
  comprehension problem, and the two look identical in the gold SQL.
- **GENERATE the sentence that names a twin; do not hand-write it per object.** The rule
  above is the most valuable one in this section and the easiest to apply to four objects
  and forget on ten. Measured 2026-09-20 on insider_trading: after a build whose spec was
  written with this rule open, **12 of the 14 parsed/recorded pairs carried no reference to
  their twin at all**, and prose review had found none of them — the omission is invisible
  because each description reads fine on its own. It cost a task that returned gold's 246
  rows in gold's order and failed on `42.77` against `'42.77 connection-point/ownership%'`.
  Emit the clause from a pass over the attribute list, so a pair added later cannot miss it,
  and audit the EMITTED YAML for pairs whose partner is unnamed rather than trusting the
  spec source. Note what this did and did not buy: the pairs were all named on the next
  build and the task still chose the bare reading, because steering is demand-gated.
- **A generated sentence PREPENDED to a twinned reading displaces the clause that chooses
  between the twins, and the displacement costs the task.** The rule above says to generate
  repeated clauses from a pass; this is the trap in doing so. Measured 2026-09-23 on
  disaster_relief: a population sentence ("null on the 980 of 1000 disasters with no
  environment record …") was generated onto the first position of every knowledge-base
  reading, including readings that already led with the clause naming their twins. The agent
  reads top-down and picks on what it reads first: a task that had passed phase 1 selecting
  `Public Health Risk Score (Unrecorded Injured As Zero)` switched to the bare strict reading
  and failed, in **three consecutive runs including both halves of an n=2 close** — a
  deterministic loss, not variance. The population sentence converted nothing measurable in
  the same window. So the placement rule: **a reading that belongs to a twin group is chosen
  by its twin clause, so a generated population or provenance sentence TRAILS it; a reading
  with no twin group to choose within has its population as the deciding fact, so the sentence
  LEADS.** Decide placement per object from whether a twin group exists, not globally, and be
  aware that a generated pass applies your choice to every object at once — which is what
  makes it worth getting right and expensive to get wrong.
- **The bare-name move is per family, and a $0 regression sweep decides it before deploying.**
  Measured 2026-09-24 on fake_account: across two runs the agent took the bare strict composite on
  five tasks whose questions address every account, so the plain name moved onto the zero-filled
  reading of every KB composite. It converted two tasks in both phases (CAS per platform, an ARS
  screen) - and the regression sweep showed it made four other phases unreachable by name, on the
  two families where zero-filling an input inverts its meaning: `0.3 * (1 - trust)` with trust read
  as 0 adds the full 0.3 and inflates the Security Risk Score, and a listing of every account's
  evasion index wants the unscored ones null. Move the name family by family, re-run every passing
  ceiling query first, and revert the families it breaks.
- **A generated "when grouped by <column>" clause on a metric chooses the grouping for the caller.**
  "the typical value per platform when grouped by Platform Code" sat on ~85 generated metric
  descriptions; a task asking "on each platform" grouped by the 471-value code where the 4-value
  kind was meant, while the kind's own description was correct and read. Name no grouping column
  in generated metric text; say "grouped by any column".
- **A KB entry's NAME can carry a condition its definition omits, and the name is what questions
  use.** KB "Dormant Bot" is defined as status = 'Dormant' (169 accounts) while the name says bot;
  "how many bot accounts are dormant" means Bot form AND Dormant (49). Put the plain name on the
  reading that satisfies every word of the name and publish the definition-only reading as a
  qualified twin with both counts.
- **Restoring the placement is not the same as recovering the task.** The same measurement:
  the ordering was fixed, four canaries held at 1.0, and the target still selected the bare
  reading and still failed. Once the agent has been observed choosing the bare name twice,
  the remaining lever is structural — move the plain name onto the reading the questions mean
  — and more description text is spent money.
- **Fix the aggregate twin whenever you fix the attribute.** A row-grain measure was
  disambiguated and converted its task; the `Average …` metric built on it was left silent, so any
  question asking for an average still hit the undisclosed reading.
- **A published count must name the reading it was counted under.** One model shipped
  `'brickwork house' 1211, 'apartment' 229` on an attribute that lower-cases *and nothing else*;
  the live values are 1092 and 222, because the published figures were `LOWER(TRIM())` counts —
  contradicting the same description's next sentence. Treat this as worse than a typo: the agent
  quotes those numbers verbatim into its clarifying question, so a wrong count becomes a wrong
  question. Verify every count against the exact attribute it sits on.
- **Naming a twin is not routing a choice, and a generated sentence prescribes at scale.** Two
  sharpenings measured on one 20-task database, where **all five** model-side failures were this
  one defect and nothing else:
  - An object pair can satisfy the letter of the twin rules — each naming the other, each saying
    they are not interchangeable — and still lose the task, because the agent picks on **name
    match** and the question's words pick for it. A watts column and a ratio column both answering
    "how much power does it lose internally" cost the task at 30.85 against 0.06. The fix is not
    more cross-referencing: it is an explicit **closed question** in both descriptions, naming the
    two options and quoting both figures for one row. Once routed, the ask fired **5 for 5** across
    five objects.
  - **Audit generated description text separately from hand-written text.** The worst offender was
    a sentence emitted by a loop over nine flag metrics — *"Filter Latest Snapshot Of Plant = 'Yes'
    to judge each plant on its newest snapshot only"* — so one line put a prescription on nine
    objects at once. Prose review found three hand-written instances and missed this one until a
    canary dropped. Grep the **emitted** YAML for imperative verbs (`Filter `, `Use `, `Show `,
    `Prefer `, ` means this value`), not just the spec source.
  - A population sentence must name the **exact column**: *"the power columns are present on 361 of
    998"* sent the agent to a column non-null on 600, and a different row won.
  - Confirmation of the ask-shape rule: when the simulator answered *"I'm not sure I understand
    your question"*, the agent **re-asked offering explicit options** and got a usable answer,
    converting the task. Write the trigger so a qualitative reply is re-asked, not abandoned.
- **A description that states a FACT helps; one that prescribes an ANSWER competes with the
  user.** Learned twice on one model, both self-inflicted, both costing tasks: "Premium means the
  position pays well relative to what is required", added to satisfy a discovery phrase, told the
  agent to answer a *different* KB concept's question with this attribute, and it did, returning 60
  where the caller's threshold gave 33; "Firm names are stored with mixed capitalisation … collapse
  casing yourself if one row per firm is required" produced exactly that `GROUP BY UPPER(…)`, and
  the reference does not merge casing, so the whole top-five changed. The replacement rule: **where
  a data-quality quirk has more than one defensible treatment, state the quirk with its live
  numbers and route the decision to the user; never pick one on their behalf.** Audit every
  description for the imperative mood — an instruction to *do* something with the data, rather
  than a statement of what the data *is*, is the smell.
- **Never name an attribute the model does not publish.** Orientation text said "Bucketed tiers
  (Anonymity Tier) are this model's convention" and a measure said "the Anonymity Tier attribute
  buckets this score" — the column was computed in dataset SQL and never given an attribute. Two
  tasks spent two to four discovery calls hunting for it, one `focus_columns` errored on the name,
  and one submitted its own bucketing instead. Check every description against the published column
  list at emit time; a reference to a withheld or never-built object is a dead end the agent pays
  for. Say instead what does exist: which KB labels have no stored equivalent, and what to group by.
- Model every KB-defined metric, even composite ones. A missing KB metric doesn't fail loudly —
  queries silently fall back to a simpler, wrong aggregate.
- Where the KB defines named multi-condition concepts ("X failure" = A OR B; "major Y" = three
  ANDed conditions), don't just describe the logic — precompute it once, correctly, as a Yes/No
  attribute the agent can filter on directly. Description text alone is not reliably turned into
  correct SQL, even when read. Two second-order effects: the raw component columns compete with the
  flag on surface word match (a question phrased in a component's words gets filtered on that
  component alone, losing the OR branch), and a Yes/No flag hides the quantity it was derived from
  — note on the flag which underlying measure the answer likely still needs to display. Say in each
  component's description that it is an *input* and direct filtering to the flag, but treat that as
  documentation, not a fix. Where the component has no independent use, consider not exposing it.
- **A flag whose live count is zero is still worth shipping.** No snapshot met one KB condition,
  and the agent that rebuilt the formula by hand spent 19 calls and its whole budget doubting the
  empty result; a flag that says "0 of 998 qualify" lets the next one trust it and keep coins for
  phase 2.
- **Do not invent a bucketing the KB does not define.** Expose the raw value and the pieces a
  bucketing would be built from — deltas, threshold comparisons, a boolean per condition. An
  invented bucket is worse than a missing one: it is usually named in exactly the words a question
  would use, so it out-competes the correct object on match while encoding a threshold nobody
  authorised. Both objects deleted from one model were of this kind, and each had been chosen by
  the agent in preference to the correct object. Where the KB *does* name buckets, ship them and
  say in the description that the label strings are this model's convention and the caller should
  re-label to the question's wording. Where the KB names a bucket but states no number for one of
  its conditions ("a statistically significant number of applications"), ship the components and no
  flag — a half-defined bucket is an invented one.
- **Pre-ship the divisions.** Any share, rate or percentage a question is likely to ask for should
  exist as a calculation rather than being left to the caller to divide two measures: on this SQL
  interface a caller's explicit numeric cast returns a **string** (Engine constraints), so a
  hand-computed ratio cannot be rounded downstream and fails on presentation with the right value
  underneath. Scan the follow-up questions for "what percentage / what share / what proportion" and
  ship one calculation per answer shape — on one database that was 13 of them, and most phase-2
  follow-ups were of this form. Say in the description whether the value is a **fraction (0–1) or a
  percentage (0–100)** and give a live example value: a share shipped as a fraction where the
  question asks "what percentage" is a silent 100× error. **Ship one grand-total share as well as
  the per-dimension ones.** Every dimension-scoped share divides out one *named* dimension, which a
  caller-defined `CASE` bucket is not, so those return 100.00 beside an ad-hoc grouping. A share
  whose denominator is `AllMember(<measure>)` works beside any grouping at all, including
  categories the user invented in conversation — the normal shape of a withheld-concept follow-up.
  Ship both and say in each description which one ignores filters and which respects them.
- Verify formula inputs mean what the formula requires — gross vs net, pre- vs post-adjustment,
  units and scale (kW vs MW is a silent 1000× error; check internal consistency across metrics
  sharing a column). Where a raw recorded column and a computed near-equivalent both exist, use
  whichever the KB formula names — they are not interchangeable. Check a specific live value
  end-to-end against the source; a plausible result computed from the wrong basis is silently
  wrong. Verify the two actually differ before shipping both, and say so with the evidence
  (observed: 0 of 994 entities had the recorded column equal to the computed formula).
- **Never ship a description that asserts a capability is broken without re-testing the claim at
  build time.** Two percentile metrics carried "the Postgres dialect rejects the percentile sketch
  at query time on this engine, so expect this metric to error until that changes". It had been
  true; it no longer was, and the metric returned the gold median exactly. The sentence cost a
  task: the agent read it, believed it, and spent its budget looking for a median that was already
  there. A defect note is a measurement with a date on it — re-run it whenever you regenerate. If
  the workaround still applies, say what to do instead; if you cannot re-test it, delete the claim.

### Keys, identity, and naming

- If the human-readable label is not actually unique in the live data, expose the true unique key
  as a queryable (not hidden) secondary attribute. `COUNT(DISTINCT label)` on a non-unique label
  silently under-counts. Separate identity from display in both descriptions — and **lead with the
  warning**, because descriptions are read top-down and a caveat that is not first is a caveat that
  is not read. Observed: a non-uniqueness warning in the second sentence, and both tasks that
  listed those entities grouped by the label anyway, silently collapsing ~9 entities per row.
- **The key's description says it is what a listing SHOWS, not only what to group and count on.**
  One model's warning was already first and already said to group and count on the code — but the
  code's own text called it "an internal code rather than a display name, and <Name> is the
  readable form", which reads as "show the name", and two listings each spent 2 coins asking "name
  or code?". Say instead: this is the column that identifies the entity in any listing; a name
  shared by about nine entities identifies none of them; show the name only when the question asks
  for the name. When you warn against a column for one purpose, say what it *is* for — a caution
  with no counterpart guidance is read as "never use this column".
- **The key has to be *projectable*, not merely present.** A level whose `name_column` is the
  display name and whose key is reachable only as the level itself gives a caller no way to write
  `PARTITION BY <key>`, so any per-entity ranking partitions on the name and merges distinct
  entities. Observed: 736 names covered 742 entities — one name was three different entities and
  four more were shared by two — and a per-entity `DENSE_RANK` on the name shifted every rank in
  the affected partitions; publishing the key as a plain secondary attribute took the same query
  from 809 rows to a row-for-row match. Whenever one entity dimension publishes an `<Entity> ID`
  alias, check that its siblings do too; the omission is invisible until a window function needs it.
- **An alias attribute says it is identical to its twin.** Where `<Entity> Identifier Code` exists
  beside the `<Entity> Code` level so a key can be projected and counted, say it is exactly the
  same value row for row and that a result which failed with one fails identically with the other.
  Observed: two tasks resubmitted a failed listing with the twin swapped in, 3 coins each, same
  verdict.
- **A name that mirrors a question's phrasing must satisfy *every* condition in that phrasing.** A
  measure named in the question's own words that quietly drops one of its qualifiers is worse than
  a neutrally-named one: it is the obvious pick, it returns a plausible number over a larger
  population, and nothing signals the mismatch. Either carry every qualifier in the name, or name
  it for what it computes and let the description carry the paraphrases.
- **Quote the KB's own wording for every member value you emit.** Where the KB names the state
  ("the employer is *self-represented*"), use that string; a synonym you preferred ("Not
  Represented") is an invented label that fails an exact-value comparison for no reason. Audit the
  emitted member values against the KB text, not just the category set.
- Keep `unique_name` and label identical for anything an agent will query. The tools surface
  `unique_name`, so a friendly label attached to a snake_case technical name is invisible where it
  matters — and a snake_case identifier gets written unquoted, as a bare SQL column rather than a
  semantic-layer attribute. Descriptions that cross-reference other objects must use their
  queryable names; have the generator fail the build on a dangling cross-reference.
- **Check the repo's prevailing `unique_name` convention before authoring, and assert it.** In a
  shared repo the convention itself can drift: twenty-two models in one catalog, twenty using
  label-based names with spaces and two using snake_case, unnoticed because nothing errors and each
  model looks self-consistent from the inside. The two outliers were the ones whose identifiers an
  agent would write unquoted. Count the convention across the repo before picking one, and have the
  generator assert the choice.
- **No dimension `unique_name` may equal, or differ only in number from, the model name or a
  primary entity the questions count.** `explore_columns` groups its output under `##
  <column_group>`, and the column group *is* the dimension's `unique_name` — so headings get
  selected as columns. Measured across eight databases, **14 of 27 column-not-found errors were the
  agent selecting a heading it had just read**. It is worst where the heading is near-identical to
  the model name *and* to the entity the questions count: one such group produced 15 of that
  database's 29 query errors over three runs, and renaming it `<Entity> Record` took
  heading-selection from 4.7 per run to zero. The agent is not inventing a name here — it is using
  one it genuinely read, so "only use a name you saw" does not protect against it.
- **One degenerate dimension per `dataset` + `key_columns` pair, and no more.** Splitting a wide
  single-fact model into many themed degenerate "profile" dimensions on the same key is a natural
  way to organise 200 attributes and is wrong twice over: SML rejects it (Engine constraints), and
  the headings it creates are the heading-selection liability above. Observed at scale: ten models
  in one repo had done it, 122 dimensions across 17 duplicated pairs. The merge costs nothing in
  discovery — **a secondary attribute carries its own `folder`**, so `explore_columns(folder=…)`
  returns each theme exactly as before (verified on a 13-dimension merge: the folder still returned
  its same 15 columns). What collapses is only the `##` heading. Theme with folders, not with
  dimensions, and name the merged dimension for the entity, not for whichever theme won (Build
  process).

### Descriptions and discoverability

- Every measure and attribute description carries: formula and provenance, units and scale, live
  null and coverage counts, disambiguation from near-twins, and the paraphrases someone would
  actually ask with. `explore_columns` is a contiguous, case-insensitive substring match, not fuzzy
  search, and the near misses are much cheaper than they look: an inserted word ("count of years"
  does not match "count of calendar years"), **a plural** ("dodgy buyers" does not match "dodgy
  buyer"), **a change of voice** ("how quickly we handled threats" does not match "how quickly
  threats were handled"), and **a hyphen** ("specialty-occupation" does not match "specialty
  occupation") each make the object invisible. Include several wordings verbatim, singular and
  plural, active and passive, unhyphenated. Descriptions on objects the discovery API doesn't
  expose don't count. The model's own description should be an orientation guide, not a one-liner.
- **Carry the knowledge base's VOCABULARY, not only its formulas.** Discovery matches search terms
  against the object name *and* its description — verify this on your own backend, then rely on it.
  The consequence: a concept the model fully supports is **undiscoverable** whenever the KB's own
  wording for it appears in neither. The agent searches with the question's phrasing, the question
  uses the KB's term, and it gets "no columns matched" for a concept whose every input is
  published. Measured on one model: **40 of 96 KB terms appeared nowhere in the published text** —
  a composite classification whose two halves were both published returned nothing when searched by
  its KB name, and so did a compliance check whose only input was a plain per-month column already
  on the model. A raw arm with a glossary tool has no such problem, so this asymmetry shows up
  directly as negative lift. Ship it as a **table mapping column to KB term**, appended to that
  column's description by the generator, rather than hand-edits scattered across descriptions: one
  place to audit, and an unmatched column name can fail the build instead of silently restoring the
  gap. Where the KB concept is a composite the model publishes as halves, name it on **every** half.
  Three exclusions:
  - **A withheld term is not automatically excluded — apply the firewall's own test and do not
    invent a stricter one.** What the benchmark withholds is a *deleted* entry's cutoff. The
    placement constraint this adds: the KB term must not land next to a threshold-shaped number,
    and the masked-threshold gate enforces that over a window of a couple hundred characters. On
    one measured model, of 16 entries masked on a running task, four shipped without trouble and
    two could not, because every column that could host them already states their cutoff in its own
    distribution sentence ("169 patients exceed 2") — naming the concept there hands over the
    number. Where no clean host exists, drop the term; do not reword a correct description to get a
    string past the gate. Process lesson, because it cost a wrong commit: a first pass read two gate
    failures as evidence for a blanket "masked terms are never publishable" rule, applied it to six
    terms and shipped, needlessly removing four the documented policy permits. **A gate failure
    tells you *that* something is wrong, never *what the rule is*.**
  - **Stating a vocabulary collision in the question's own words is itself a leak, so state it in
    the KB's words.** Measured 2026-09-22: two KB concepts legitimately answered one everyday
    phrase and the natural sentence - "both answer the everyday phrase '<phrase>'" - quoted the
    task question verbatim and failed the gate, correctly. The collision still has to be published;
    write it from each concept's own KB definition ("a fan who consumes a large amount of content
    but participates minimally in social chat" against "low financial value with low support load")
    and let the reader match the phrase themselves.
  - **A term a task question quotes verbatim is not publishable either.** It trips the
    question-leakage gate, and rightly: the phrase's provenance may be the KB, but nothing in the
    published text distinguishes it from a description written off the question. Where such a term
    is not already the object's *name*, rename the object rather than allowlisting the leak.
  - **An acronym in parentheses reads as a cross-reference.** `Some Concept (SC)` looks to a
    dangling-reference gate exactly like a pointer to a published object of that name. Unwrap it —
    "…, also written SC" — so both stay searchable and the gate keeps its teeth.
- **When two KB rules answer the same everyday wording, both descriptions lead with the collision
  — and so do their count and rate metrics.** Observed: a database carried "Urgent Maintenance
  Required" (remaining life under a week or service overdue, 24 operations) *and* "Predictive
  Maintenance Trigger" (an urgency score over a cutoff, 2 operations), and a question about
  entities that "need urgent maintenance" meant the second. The agent filtered on the first without
  asking, three runs of three, because its name matched the question's words. Find these
  mechanically: for each KB rule, list the everyday phrasings it answers and flag any phrasing two
  rules share. Each such description opens with the collision — the other rule's name, both
  populations — and routes the choice to the user; the `… Count` and `… Rate` built on each carry
  the same sentence, or the aggregate question hits the silent reading. Do not put the other rule's
  cutoff in the sentence when that cutoff is withheld on a running task; name the rule and point at
  the attribute that states it.
- **Two composites that share an everyday phrase name the KB's OWN cutoffs on each.** Where a
  weighted sum and a product are both "the overall bot-and-coordination score", the simulator
  described the product and the agent took the weighted sum, because only one description carried
  the phrase. Put the phrase on both and let the KB break the tie the way the KB does: one entry
  screens the product at 0.8 and another screens the sum at 0.9, so "combined score above 0.8" fits
  the product. Give both counts (509 / 553 above 0.8) and ask as a closed question.
- **When two columns can answer the same phrase, both descriptions must say which is which.** A
  question asked what *trading restrictions* an enforcement action imposed. Gold read the
  enforcement column, published with the description "Business-restriction imposed, business
  restriction"; a different column described itself as "restriction type, restriction window,
  **what restriction was imposed**" — synonyms harvested for a *compliance-case* attribute that
  read as the better match. The agent picked it and got 306 rows where gold had 113; swapping the
  column alone reproduced 113 exactly. Before shipping, group the model's columns by the phrases
  their descriptions claim, and wherever two claim the same phrase add a disjoint clause to each
  naming the other and the distinction. A gate for this is cheap: for each pair of published
  descriptions, intersect their 3-grams after dropping the object's own name; a pair sharing a
  domain-specific 3-gram with no cross-reference between them is a finding.

**A question phrase too short for the leakage gate still chooses for the caller.** The A8 gate
matches 6-word runs; a five-word alias does not trip it. Measured 2026-09-24 on planets_data: the
arithmetic-mean period ratio described itself as "the average orbital period ratio" - the question's
own words - and the agent projected it on 2 of 2 runs where the reference used the other average
(the KB defines only the pairwise ratio, so neither reading is the KB's). Removing the phrase and
shipping a closed question naming both readings with live counts (identical on 375 stars, different
on 193) converted the task 2 of 2. Grep the emitted descriptions for the brief's ambiguity terms and
multi-word question nouns, not only for 6-grams.

**Say when a twin pair is NOT a fork, or the agent pays to ask.** A bare flag and its `(Inputs
Recorded Only)` twin return the same rows for `= 'Yes'` and differ only on No versus null; a KB flag
and a live recount that differ on one row are not a choice worth a question. Measured 2026-09-24 on
planets_data: both invited an ask where the agent was already right, and the second cost two wrong
submissions after the simulator picked the one-row-different reading. Generate the sentence "for a
Yes filter these return the same rows" onto every such pair, and give a near-identical pair its
difference count with the words "not a fork".

### Surface size

Because it was the single largest cost measured on one database and nothing else here bounds it.
Many of the rules above multiply object count.

- Object count is a direct tax on the agent's budget: `explore_columns` is a substring match with
  no relevance ranking, so every near-duplicate description is sifted on every search. Measured on
  a 188-metric model: **62.5% of the per-task coin budget spent on discovery, 151 `explore_columns`
  calls over 20 tasks, and 19 of 20 tasks exhausting budget immediately after phase 1** — leaving
  nothing for the follow-up. Cutting to 162 metrics brought discovery to parity with the raw
  baseline. Nothing about the tools changed; the model got smaller.
- **Folders are a discovery surface, not decoration.** `explore_columns` takes a folder argument,
  so a named folder returns its whole contents for the same one coin as a keyword guess — which
  makes folder size a build-time decision. One model shipped 20 folders for 387 columns, two of
  which held most of the model: one returned 195 columns and 75,142 characters, no better than
  dumping the catalog, and the index stopped being an index. Split by theme until no folder
  dominates (130 metrics went to 15 thematic folders, largest 33), and give secondary attributes
  their own folders rather than letting them inherit the hierarchy's, so an agent that finds a theme
  gets both the per-entity attribute and the aggregate. Attribute-level folders may be honoured or
  ignored by the engine — `sml-cli validate` accepts them, so verify with
  `explore_columns(folder=…)` after deploy and revert that half if they are ignored.
- Watch for the symptom, since it looks like a scoring mystery rather than a defect: a model with
  no visible flaw, correct on every gate, scoring at the baseline, with tasks running out of budget
  right after their first answer.
- The multiplicative rules above are permissions, not obligations. Ship a variant only where it is
  **provably** distinguishable in the live data — check ties before shipping a rank twin, check
  identity before shipping an entity-grain variant.
- Withholding peripheral columns that no question touches is legitimate and preferred over shipping
  them for completeness. Record which ones and why, in the spec, next to the exclusion — a silent
  omission is indistinguishable from an oversight later.
- **A twin whose QUALIFIER sounds authoritative out-competes the bare name, and the bare name was
  the point.** The naming rules say to move the plain name onto the reading the questions mean and
  push the other behind a qualifier - but the qualifier is also a name, and some qualifiers read as
  a recommendation. Measured 2026-09-22 on virtual_idol: the reference prints a singular member
  label, so the singular was moved onto the bare `NPS Score Tier` and the knowledge base's plural
  forms were parked as `NPS Score Tier (KB Category Names)`. The agent then selected the twin on
  both submissions - the qualifier says "these are the knowledge base's own names", which reads as
  the authoritative choice - and lost the task on the label after getting the population, the ratio
  and the route right. Name a parked reading for what NARROWS it (`(Recorded Only)`,
  `(Support Record Only)`, `(Per Membership)`), never for what endorses it: `(KB …)`, `(Official …)`,
  `(Standard …)`, `(Canonical …)` and `(Exact)` all invite the pick you are trying to avoid.
- **An added object must earn its place twice: once by being in the KB, once by not shadowing a
  neighbour.** Object count is not the only cost — *vocabulary collision* is. A legitimate KB
  concept can out-compete the concept a question needs when the two share words, and the added one
  wins because it is a ready-made classification. Observed: shipping one KB entry's risk bands
  (Low/Moderate/High) cost a task that wanted another's complexity split (Complex/Standard); the
  agent grouped by the new object, then had to ask the user and re-submit, three coins down. Before
  adding, ask which existing concept the new one is nearest in *wording*, and if the answer is a
  withheld concept, give the new object a description that leads with the collision and routes that
  question to ask-the-user. Both times that treatment was applied the task recovered.
- **KB completeness is a fairness requirement, not a scoring lever — fund it as such.** The raw arm
  can look definitions up with a tool; the semantic arm usually cannot, so anything the KB defines
  and the model omits is a straight structural disadvantage. Close the gaps. But measure the
  expectation honestly: ten KB concepts added to one model cost nothing in discovery (5.1 to 5.0
  calls per task, budget exhaustion actually fell) and were **never once queried**, because no task
  asked for them. Do it so the comparison is fair; do not book a score improvement against it.

## Engine constraints (learned the hard way)

These work around tracked engine/tool defects — parenthesized IDs reference the team's defect
tracker and are provenance, not something to resolve. Check the Workarounds table in
`docs/model-change-log.md` for whether each still applies, and re-probe the live engine before
each build: a workaround that stopped being needed is dead weight, and a new gap is a silent
failure.

**Wrong data, no error**

- **A `RANKX` measure silently returns 1 for every row when the query groups by an attribute of
  the ranked entity that its `ALL(...)` exclusion does not name (ATSCALE-52370).** The exclusion
  list, not the attribute's type, is what decides. Repro on a model where one entity is the only
  non-finisher and must therefore rank last:

  ```sql
  -- correct: the grouped attribute is in the exclusion
  GROUP BY "Entity Name"                          -> that entity ranks 35
  -- silently wrong: one more attribute of the same entity
  GROUP BY "Entity Name", "Reliability Rate Pct"  -> that entity ranks 1
  ```

  There is no formulation safe against an arbitrary grouping, so treat every published rank as
  carrying this hazard and follow rule 1a of the group-context section. (This is ATSCALE-52082
  item 3 on the DAX path; that ticket was closed on the mistaken belief that `RANKX` avoided it.)
- **MDX `Rank` silently returns 1 for every row when the query groups by a secondary attribute of
  the ranked level (ATSCALE-52082 item 3, open).** Grouping by the level itself is correct;
  grouping by its display-name attribute — the common case, since that is what questions ask for —
  is silently wrong rather than an error, and it cannot narrow the ranked population at all. Model
  rankings with DAX `RANKX`.
- **`[Dim].[Hier].[All]` in an MDX tuple is not a whole-model constant — it clears only that
  dimension's filter.** Every other dimension in the query still narrows it, so an index whose
  denominator is meant to be a warehouse-wide average silently collapses to the current slice: one
  specialization index returned **0.0 at every grain** instead of 0.75 because "types in the
  warehouse" became "types this entity handles"; a demand index returned **1.0** instead of 43.73
  as soon as any second attribute was grouped. Use `AllMember(<expr>)`, which strips all dimension
  context, wherever the denominator is a genuine constant. **The corollary matters as much**: a
  share-of-total calculation genuinely *wants* the scoped `[All]` behaviour, because that is what
  makes "percentage of this entity's cases by type" expressible. Decide per calculation which you
  mean and say so in the description. Six expressions were wrong on one model and all six passed
  `sml-cli validate`, deploy **and** `validate_mdx_expression` — only a live query against a
  hand-computed reference caught them.
- **Near-duplicate readings of one concept must all be cleared in the same tuple.** Where three
  columns are three readings of one concept, an `[All]` on one leaves the other two narrowing the
  denominator, and a query grouping by two of them returns 100.00.
- **`SUM` and `COUNT` over a *dimension attribute* return one row per member carrying the member's
  own raw value**, with no aggregation and no error. Measured on two unrelated models: `MIN`, `MAX`
  and `COUNT(DISTINCT …)` are correct; `AVG` fails the planner with `assertion failed: We already
  handled attribute values`; and `COUNT(<attribute>)` returned a row whose value was `null` — a
  count cannot be null under any semantics, which is the clearest available proof that nothing is
  being aggregated. **Correction, measured 2026-09-23 on disaster_relief: `MIN` over a dimension
  attribute is NOT universally safe.** `MIN("Affected Area")` in a scope reading the model directly
  was refused with the same shape of message as `AVG` — *"aggregates the dimension attribute … in a
  scope that reads the model directly, which fails in the engine planner. Select the attribute at
  row grain in a FROM-subquery and aggregate outside it."* So the safe statement is that **any**
  aggregate over a dimension attribute read directly from the model is suspect: `SUM`/`COUNT`
  silently return members, `AVG` and `MIN` are refused outright, and the FROM-subquery form is the
  route for all of them. Re-probe on your build rather than trusting the older `MIN`/`MAX` claim.
- **Three engine facts the agent pays coins to rediscover, now carried in `birdsml.ENGINE_NOTES`**
  (added 2026-09-23 after each cost a submission on disaster_relief): `AVG` over a dimension
  attribute is refused by the planner and needs the FROM-subquery form; **sorting by a column the
  query neither projects nor groups by is refused outright** with a message saying to add it to the
  select list; and **`ROUND` to fixed decimals goes through a numeric cast that must carry precision
  and scale** — a bare `CAST(x AS numeric)` is refused with *"Numeric values are only accepted with
  specified precision and scale"*, so `CAST(x AS numeric(18,4))` is the working form and its result
  returns as a string. The note demonstrably lands: on the next run the agent wrote the
  precision-and-scale form unprompted and the submission was accepted. Every one of these was
  already documented in this section and absent from the constant the agent actually reads — which
  is the gap worth closing, because a rule in prose here reaches nobody at query time. Consequence for modeling: any per-entity figure a question might average or
  total must be published as a **measure**, not only as an attribute, or it is unreachable.
- **`real::numeric` truncates to six significant digits, silently** (M-31). Postgres converts
  `float4` via `float4out` at `FLT_DIG=6`, so 321804.16 becomes 321804. A derived dataset casting
  every source column for tidiness corrupted 941 of 1000 balances and 821 of 1000 PnL values, and
  every figure computed from one. Nothing errors and the values stay plausible to the last
  surviving digit. Read such columns as double, and re-probe the emitted declarations against
  `information_schema` in a generator gate.
- **A generated column name can exceed Postgres's 63-byte identifier limit, which truncates with
  only a NOTICE.** When the twin suffix is generated rather than hand-written, a long stem plus a
  long qualifier goes over silently: measured 2026-09-22,
  `interaction_fan_is_community_influencer_exact_retention_record_only` is 67 characters, so the
  warehouse created it truncated while the dataset declared the full name and the build failed on
  "column not in dataset" - which reads as a generator bug and is a Postgres limit. Assert the
  length of every emitted column name in the generator, and shorten the qualifier rather than the
  concept.
- **Never use `|` in derived SQL** (D-01). The engine re-parses and re-emits derived-dataset SQL,
  and a `'|'` string literal does not survive the round trip: every query touching the dataset dies
  with a raw warehouse `syntax error at or near "'|'"`. Other literals in the same SQL (`'$'`,
  `','`, `' km'`, `'Yes'`) round-trip fine. Validate and deploy both pass; it only surfaces on a
  live query, and it killed every query on two datasets. Where a composite key needs representing,
  use a compound SML leaf key rather than a concatenated surrogate. Assert in the generator that no
  emitted SQL contains a `|` — this also rules out `||`, so use `CONCAT()`.

**Rejected or mis-planned, with the workaround**

- **`HAVING` on a rank measure leaks an internal plan dump instead of filtering
  (ATSCALE-52369).** Filtering a `RANKX` measure at its own level fails with a raw plan node
  (`Unmatched physical type SemanticWindowFunctionValue(WindowFunctionApplication(
  DenseRankWindowFunction, …))`). Only `HAVING` is affected — projection, `ORDER BY` + `LIMIT` and
  the FROM-subquery form all return correct results:

  ```sql
  SELECT * FROM (
    SELECT <keys>, <rank measure> AS rk FROM <model> GROUP BY <keys>
  ) t WHERE rk <= 3
  ```

  **Put the rewrite in every rank measure's description** until the defect lands. Observed cost
  when it is missing: the agent wrote the gold's exact query on its first attempt, hit the dump six
  times, abandoned the semantic measure entirely, and hand-wrote raw window functions — which the
  SQL front end then rejects for its own reasons.
- **MDX `Filter` inside an aggregate is a closed door (ATSCALE-52355, Won't Do).** See the
  group-context section; do not re-open it.
- **An expression beside a bare column over a derived table emits an invalid `GROUP BY`.** When the
  outer `SELECT` reads from a FROM-subquery and projects any expression *alongside at least one
  bare column*, the planner appends a `GROUP BY` covering only the expression's ordinal and the
  warehouse rejects the engine's own SQL (`column "t_14.X" must appear in the GROUP BY clause`).
  The boundary is precise: an expression **alone** passes, all-bare passes, a literal passes — and
  the error always names the **bare** column, never the expression. Reproduced on two structurally
  unrelated models. There is **no workaround** when the expression spans two joined derived tables
  — the leave-one-out or compare-row-to-its-group-average shape — because it cannot be pushed into
  either side and wrapping the join fails identically at every nesting depth. Precompute that shape.
- **`ORDER BY` on a column the outer `SELECT` does not project returns an internal render fault**
  (`Unmatched physical type … when rendering sql`) rather than a legible message. This was the
  widest-reaching failure of one sweep: 20 occurrences across seven of eight databases, plus 20
  submissions that died without receiving a grade. Put the `ORDER BY` **and its `LIMIT`** inside the
  derived table that projects the sort column, and leave the outer `SELECT` with no `ORDER BY`.
- **Projecting only a CAST or ROUND of a column does not count as projecting it for ORDER BY.**
  `SELECT id, CAST(x AS numeric(18,4)) ... ORDER BY x` is refused "Cannot sort by [x]: the query
  does not group by it"; ordering by the expression's alias is accepted (verified live 2026-09-24).
  Two fake_account tasks were refused on it in one run; now in `birdsml.ENGINE_NOTES`.
- **A two-argument window function fails in the planner** — `LAG(col, 1)` raises `requirement
  failed: A SameTypeWindowFunction always takes exactly one argument`. Single-argument window calls
  plan normally, so lag/lead *with an explicit offset* must be precomputed.
- **A scalar subquery in the select list trips a planner assertion** (`assertion failed: We already
  handled attribute values`), so a scalar benchmark cannot be placed beside detail rows inline.
- **A bare `CAST(x AS numeric)` is rejected** (`Numeric values are only accepted with specified
  precision and scale`); `CAST(x AS numeric(p,s))` works — and comes back over MCP as a JSON
  **string**, not a number, silently defeating any downstream rounding. `x::numeric` is the
  idiomatic Postgres route to exact decimal arithmetic before `ROUND(v, 2)`, since
  `round(double precision, int)` does not exist, so clients that speak Postgres write it
  constantly. Ship the ratios yourself as calculations rather than leaving the division to the
  caller.
- **Postgres has no `COUNT(DISTINCT …) OVER ()`.** Where a derived dataset needs a distinct count
  per partition, use the dense-rank identity — ranking ascending plus ranking descending, minus one
  — rather than restructuring into a join.
- **Precompute whatever the query dialect cannot express.** A caller cannot work around a missing
  language feature; they discover it by spending submits on queries that never execute. Currently
  inexpressible on this engine: percentile/median *in caller SQL* (the aggregation works, but only
  via a percentile metric the model published); quantile bucketing (`NTILE` rejected — so
  quartile/decile/percentile-band questions are unanswerable unless the band ships as an attribute;
  `ROW_NUMBER` and `RANK` are both accepted, so it is `NTILE` specifically); string aggregation
  (`string_agg`/`listagg`/`group_concat` rejected, `ARRAY_AGG` accepted but silently does not
  aggregate); JSON aggregation and construction (`json_agg`, `json_build_object` — "Don't
  understand function"); `COUNT(*) FILTER (WHERE …)` (rejected — use
  `SUM(CASE WHEN … THEN 1 ELSE 0 END)`, the working pivot idiom); `GREATEST`/`LEAST`;
  `IN (subquery)`/`EXISTS`; CTEs; and `COUNT(*)`. Window and statistical functions the SQL front end
  does not implement, measured live rather than inferred: `PERCENT_RANK`, `CUME_DIST`,
  `PERCENTILE_CONT`, `PERCENTILE_DISC`, `MEDIAN`, `MODE`, `CORR`, `REGR_SLOPE`, `WIDTH_BUCKET`,
  `NTH_VALUE`, and the bare `STDDEV`/`VARIANCE` spellings (`STDDEV_SAMP`, `STDDEV_POP`, `VAR_SAMP`,
  `VAR_POP` resolve). A dialect fix that teaches the *plan* layer to render a function does not make
  it parseable — `PERCENTILE_CONT` is rejected by the SQL front end before any dialect is consulted.

  > **Do not drop this inventory.** A previous revision removed it and the cost showed up
  > immediately: one task had `NTILE` rejected, then spent five of its twelve `run_query` calls
  > hand-rolling a quartile from `ROW_NUMBER` and hardcoding the row count as the denominator. A
  > caller cannot discover a missing language feature except by paying for it (Q-19).

  > **Some of these are a ceiling, not a workaround.** Where a follow-up asks for output *shaped*
  > as a JSON array or object, no model object substitutes — the answer format itself is
  > unreachable. Count those tasks up front and report them as a capped ceiling on the arm,
  > separately from model defects: three of nineteen query tasks on one database, worth 0.047 of
  > average reward, larger than the entire measured gap to raw.

**Medians and percentiles**

- **Median** must be a `calculation_method: percentile` aggregation with `named_quantiles`, never a
  `metric_calc` — MDX `Median()` is rejected at deploy. **The sketch works and is exact**:
  `compression: 100` matched Postgres `PERCENTILE_CONT(0.5) WITHIN GROUP` to full double precision,
  grouped and ungrouped, on odd and even group sizes. Do not describe it as broken — that exact
  stale claim cost a task. What is blocked is the *caller's* side, so a published percentile metric
  is the **only** median a caller can reach. That makes the metric's description load-bearing, and
  it must say two things: the engine exposes the metric as `<name>_instance_<q>` so it MUST be
  selected by that name (the plain label returns `Column not found`, the suffix is the quantile
  value — `_instance_0.5`, not the word `median` — and metadata is cached until `list_models
  force_refresh`); and that this is the only route, because `PERCENTILE_CONT` is not accepted in
  submitted SQL. Publish a percentile metric for every median a question could ask for. Concepts
  *defined by* a median rather than reporting one (a median split, an above-median flag) still need
  the median precomputed in dataset SQL — `percentile_cont(0.5) WITHIN GROUP (ORDER BY x)` in a
  cross join, which is plain warehouse SQL and unaffected — because a metric cannot be referenced
  from dataset SQL.

**Deploy, catalog and tooling**

- **Schema-qualify derived-dataset SQL** with the connection's declared schema — `public.<table>`
  for all current BIRD connections. The engine executes derived SQL without that schema on the
  `search_path`; bare references deploy clean and then fail every query with `relation does not
  exist` (E-02).
- **Several degenerate dimensions on one `dataset` + `key_columns` pair are rejected.** `validate`
  reports it once per dimension *and* once per model, so ten offending models produced over a
  hundred warnings from one mistake. It is a warning rather than an error, so `validate` still
  succeeds and the deploy still lands — which is exactly why it survives. Merge them into one
  dimension and theme with attribute folders.
- **A dataset may not share a name with a dimension.** `sml-cli validate` fails with `The
  "dataset" name "X" is not unique. The file dimensions/x.yml contains "dimension" with the
  same name`, reported once from each side, and it is an ERROR rather than a warning so the
  deploy is blocked. Naming the fact dataset for the entity and the degenerate dimension for
  the same entity is the natural thing to do and hits this every time; suffix the dataset
  (`<Entity> Detail`) and leave the dimension bare, since the dimension's name is what the
  agent sees.
- **A dimension over the model's only fact dataset must be `is_degenerate: true`.** Without it,
  `validate` fails with `The dimension '<name>' should be degenerative` — and the model file then
  *still* requires a `relationships:` key. Emit `relationships: []`; omitting it fails with `must
  have required property 'relationships'`. This is not the failing shape warned about elsewhere (a
  degenerate dimension sourced from a *different* fact); here there is only one fact, and the live
  conformance check confirms it resolves, including for attribute-only projections.
- **`atscale-deploy` runs `validate` first, and reports the failure as a deploy failure.** In a
  shared repo that means a validation error in *any* model — including one you are still writing —
  makes the deploy look broken for reasons unrelated to the deploy, with no mention of validation
  in the message. Run `validate` on its own before concluding anything, and read its output for
  **errors** specifically: in a repo that already prints a hundred warnings, one error scrolls past.
- **The CLI and the web UI disagree about the latest SML version, and the CLI is what deploys.**
  Observed: Design Center reported 1.9 as latest while the CLI supported 1.6 and 1.7, with no
  released stable CLI supporting 1.9. Setting `catalog.yml` to the UI's number just moves the
  warning onto the deploy path. Declare the version the CLI supports, upgrade the CLI first if you
  want a higher one, and expect the UI to keep warning.
- **Catalog naming**: pick a catalog name not already deployed. Deploying from Design Center
  appends the git branch to the catalog name (`_main`); `sml-cli atscale-deploy` uses it verbatim —
  the two paths publish to different schemas. Pass the already-suffixed name explicitly
  (`--catalog-name="<catalog>_main"`) to publish into the existing catalog rather than creating an
  unsuffixed second copy of every model, which is a Q-17 corruption risk. After any redeploy, read
  the schema back from `list_models`; if the ADK eval harness is in play, make its
  `config/environment_backends.yaml` match — a stale entry fails every task with no hint that
  config is the cause. `shared/environment_backends.py` caches that file in a module-level dict at
  first load, so **the services must be restarted** for an edit to take effect; a `--backend` flag
  will not pick it up. Two full runs were lost to a config that was already correct on disk.
- Two deployed models sharing a name render corrupted metadata (Q-17); keep deployed model names
  unique across the engine.
- **Q-17b — publishing is not idempotent, and it fails asymmetrically.** A published model is
  materialised as a real relation, and the code path that creates it does so with no `IF NOT
  EXISTS` and no preceding drop, so once the relation exists from an earlier publish, metadata
  calls die with `relation "<Model>" already exists`. The asymmetry is the dangerous part:
  `list_models`, `explore_columns` and `focus_columns` hard-fail while `run_query` catches the
  error, skips path validation and returns **correct results** — so the deploy looks healthy while
  the agent is blind. Neither redeploying nor restarting the MCP server clears it; drop the stale
  relation in the catalog schema. Because a shared repo publishes the whole catalog, a redeploy of
  an unrelated sibling model can trigger it. **Before any evaluation run, gate on `list_models`
  succeeding AND returning the expected model count. A working `run_query` is not evidence the
  catalog is healthy** — that is precisely the trap. Three runs scored 0.000 on every task before
  this was understood.
- **`focus_columns` serves cached column metadata.** After changing a description it will show you
  the old text and make a correct deploy look like it failed. Pass `force_refresh: true` before
  concluding anything; do not re-deploy chasing it.
- **`validate_mdx_expression` is a syntax and member-resolution check, not a correctness check.**
  It passes expressions that return wrong data — four wrong formulations in a single day, three of
  which returned wrong numbers, one already written into a shipped measure. The only proof is a
  live query against an independently known answer. Cheap harness: add a temporary `metric_calc`,
  deploy, query it, compare, then remove it and redeploy.
- **The MCP `run_query` validator checks conformance over the union of every column reference in
  the statement, not per `SELECT` scope** (`referenced_columns` in `tools/validation.py`). Two
  subqueries that each conform — entity code + entity-grain rate; entity code + route complexity +
  transaction count — joined on the entity key are refused with "does not conform", and the agent
  that wrote exactly that shape was refused five times before submitting a flat version the engine
  then failed to plan (`Error during query planning: None.get`). Both are worth a repro; neither is
  a model defect, so record tasks lost to them as caps.
- **The engine caches a failed connection.** After the warehouse has been down, the first query
  through the SQL interface can fail with `Connection <group> unavailable` naming a *different*
  database's connection group. Retry once before diagnosing anything.

## Build process

- A deterministic, re-runnable generator script (spec → emitter). Changes are made by editing the
  spec and re-running, never by hand-editing emitted YAML — any identity that must survive (model
  name, catalog) belongs in the generator as a parameter, or regeneration silently reverts it.
- **The engine's own SQL rules go in the model description, from the shared constant.**
  `birdsml.ENGINE_NOTES` carries them and gate G27 refuses a model whose description does not
  cover them. They are facts about the interface, identical for every database, and they were the
  strongest single lever measured in a pass: three of them converted **5 of 5** tasks in one run,
  two of which had gone to zero holding the right filters and the right cutoffs and losing on
  `COUNT(*)` and on `SUM` over a dimension attribute. `list_models` serves the model description
  once per task, so they cost no coins. Extend the constant when a run shows the agent paying to
  discover a new one; do not delete an entry without re-probing it live.
- **Put the rule in the shared emitter, not in each generator.** Where a repo has grown a common
  build package — emitter, gates, type probe, dry-run harness — a model's generator should be a
  five-line driver, and a rule learned on one model belongs in the shared half where every model
  gets it. Measured: one 160-line pass fixed twelve models at once; the same fix hand-propagated
  would have been twelve edits across 39,000 lines of generator code, and the reason the defect
  existed in twelve models at all is that the earlier generators were copies. Apply a shared pass
  **before** emission, so the emitted YAML, the model file and every gate see the same shape — a
  pass that runs after emission leaves the gates validating something that is no longer what ships.
- Have the generator self-audit its output: duplicate labels, unreferenced datasets, metrics naming
  columns no dataset defines, dangling cross-references between descriptions — `sml-cli validate`
  misses all of these. In a shared repo, also assert that no `unique_name` or `label` collides with
  a **sibling model**; print only the colliding strings so the check does not put another model's
  design in your context.
- **Assert discoverability at build time, not only at acceptance.** Keep a list of the question
  wordings the task set uses and fail the build if any matches no published description. Finding
  these one at a time as they surface is slow and repeats: the same class recurred on three
  consecutive acceptance runs before it became a build check. The check must **parse the emitted
  YAML and normalise whitespace** — `safe_dump` line-wraps long descriptions at column 100 and the
  consumer sees the folded value, so grepping raw file text reports false failures on phrases that
  are in fact present. The gate passing is necessary, not sufficient: probe the *deployed* model
  with the same phrases too, because a build-time list only covers the wordings you thought of.
- **A discoverability gate that *requires* phrases can enforce a leak.** One generator asserted
  that 59 discovery phrases appear in published descriptions — the inverse of a leakage check — and
  several had been harvested from the evaluation questions, so the build *failed* if they were
  removed and descriptions wrapped them in `Answers '<question fragment>'` clauses quoting the
  question verbatim. A discoverability probe must come from the KB or the column's own meaning,
  never from a question, and no description should ever contain `Answers '<question text>'`.
- **Run the masked-threshold gate with `--kb`, always.** Without it the gate cannot read the
  concept types, the `calculation_knowledge` exemption is silently defeated, and a masked
  calculation term whose named formula legitimately ships is reported as a leak. That produced a
  false defect report which survived into a commit message. A gate invoked without its inputs must
  fail loudly rather than judge.
- **A gate that cannot find its brief does not run, and nothing says so.** Of eight models, one
  used a non-standard brief filename and two had no brief at all, so the question-leakage gate had
  **never run** on them; when briefs were reconstructed and it finally ran, both were failing — 23
  and 6 leaked phrases. Ship a brief for every model at one canonical path, produced by
  `extract_brief.py`, have the gate discover it by convention rather than by an argument someone
  must remember, and treat a missing brief as a hard failure rather than a skip.
- **Absolute paths make a gate machine-locked.** One model's KB paths were two hardcoded
  `/Users/<name>/…` entries, so its gate could only ever run on one person's checkout. Try
  environment variables first and keep hardcoded paths last as fallbacks.
- **Make the KB triage mechanical.** The question-leakage gate matches 6-word runs and cannot tell
  "the model copied the question" from "the model correctly names the KB concept the question also
  names" — five of one model's six flags were the legitimate concept name. Exempt, in code, any
  matched run appearing verbatim in a KB entry's `knowledge`, `definition` or `description` field.
  Hand-triage gets it right once and then someone rewords it next time; the exemption gets it right
  permanently, and what remains flagged is genuine question phrasing (colloquialisms, or an
  `Answers '<question>'` clause).
- **A build gate can fail on exactly what this document requires, and then the fix belongs in the
  gate.** Three did in one build: the leakage gate flagged a knowledge-base entry's own name, the
  withheld-name gate flagged the firewall signpost the firewall section mandates, and the
  masked-threshold NUMBER detector fired on an unmasked concept's numeral corroborated only by that
  warehouse's entity noun. All three were fixed in the shared gate, not by rewording a correct
  description. **A gate failure tells you *that* something is wrong, never *what the rule is*.**
- Before validate/deploy, dry-run every derived dataset's SQL directly against the warehouse (row
  count, declared grain is unique, every declared column resolves, plus a hand-recomputed spot
  value). This catches same-level alias references and formula transpositions that no SML layer
  can. Pin any independently-derived constant as an assertion, so a later SQL edit that changes it
  fails loudly.
- **Pin the shape, not only the totals.** The pinned constants that caught one widened segmentation
  were the per-bucket counts plus an assertion that *no* entity had a null segment; a total alone
  would have passed unchanged. Where a fix changes a population, add a constant that would fail if
  the fix were silently reverted.
- **A pinned constant protects the number; nothing protects the prose that quotes it.** A fix that
  changed what the data says and left the descriptions saying the old thing is worse than no fix,
  because the agent reads the descriptions. Observed twice in one round: a segmentation was widened
  from 37 entities to all 972, but every description still read *"just 37 … the other 935 are
  unsegmented, and a quadrant count that omits that is misleading"*, so the agent gated its query on
  the coverage flag and returned an `Unsegmented` bucket of 935 — it followed the documentation
  exactly, and the documentation was wrong. Separately, a coverage count read 344 in prose and 354
  in data since an *earlier* fix and survived every gate in between. Two habits fix this: whenever a
  generated dataset's SQL changes, re-derive the published figures from the warehouse and diff them
  against the prose — grep the spec for each old number rather than trusting memory of which
  descriptions mention it; and when a coverage flag stops meaning "this entity can be classified"
  and starts meaning "this entity's classification is well-evidenced", **rename it**, because a flag
  whose name still reads as a validity gate will be used as one no matter what its description says.
- **A mechanical rename that picks its target from inside the group inherits one member's
  identity.** Merging N themed dimensions into one needs a name, and "prefer the member whose name
  ends in `Record`" looks safe until a member is called `<Entity> <Theme> Record` — then thirteen
  themes end up filed under one of them. Derive the name from something **outside** the group: test
  the candidate against the dataset's own name (`<dataset stem> Record`) and fall back to a name
  built from the dataset when no member qualifies. Caught before it shipped only because the chosen
  name read wrong in the build log — so print what a mechanical rename decided, every time.
- **Warnings are not free, and a hundred of them is a broken signal.** One repo printed over a
  hundred `validate` warnings from two underlying causes. Nobody read them, so both causes survived
  for months and a genuine new error in the same output was easy to miss. Drive the warning count to
  near zero and keep it there; the value is not the warnings themselves but that the output becomes
  worth reading again. When some must stay, say which and why, so the residue is a known set rather
  than noise.
- Follow the SML authoring skills from `get_sml_skills`; `sml-cli validate` clean; commit and push
  before deploying (deploy resolves the model from the git remote — an unpushed fix deploys the old
  model and looks like the fix did nothing); deploy.
- Record every post-build change — the kind of change and why, naming the tracker row if it works
  around a defect — in `docs/model-change-log.md`.

## Acceptance — not done until all gates pass, with evidence

`validate` is layer 1 only; every defect class above deployed clean and only surfaced via live
`run_query`, `get_outbound_queries`, or reading the agent's actual failed queries. Budget time to
test live, and never take a plausible number as evidence a feature fired — read the outbound
warehouse SQL for any semi-additive or window-based construct.

1. **Exactness.** Smoke queries through the model exact-equal to the same query on the source
   database. The data is synthetic — never judge a result by plausibility. The reference query must
   read the source column **raw**: where it shares a cast with the model's derived SQL, both sides
   are wrong in the same direction and the gate passes on corrupted values, which is exactly how the
   `real::numeric` truncation survived it.
2. **Conformance.** Per dimension, one measure-by-attribute query per fact that dimension should
   reach, returning non-empty. Empty or erroring is a model bug, not a limitation to document, and
   there is no dialect exemption to claim: a percentile metric returns real values and must be
   probed by its `<name>_instance_<q>` name, since the plain label returns `Column not found` and a
   gate that probes the plain label reports a false failure. **Read the values, not just the row
   count** — the `[All]`-tuple defect produces non-empty, plausible, wrong numbers and would pass a
   non-emptiness check; compare at least one calculated index against a hand computation.
   Measure-by-attribute queries alone cannot see a missing attribute-only path, since adding a
   measure is what makes that case resolve: add one projection per dimension pairing that names
   attributes and no measure. And one measure at a time cannot see a refused measure pair: enumerate
   the metric list mechanically, probe one representative pair per fact-group pair, and require
   every refusal to have a same-grain twin whose description points to it — or an explicit written
   exemption. 135/135 single-measure conformance passes coexisted with every cross-fact pairing in
   five models being unreachable.
3. **Discoverability.** Search the deployed model with question-style paraphrases only, never an
   object's own name — take the probe phrases from the task briefs' own `amb_user_query` wordings;
   the intended object must surface. If not, fix the description.
4. **Coverage.** One passing query per question shape: group aggregate, filter-by-classification
   then measure, superlative/top-N, cross-fact, entity-level detail, group-relative comparison.
   Close any gap or state explicitly what was left out.
5. **Read the deployed model's folder count back from `list_models`.** `folders: (none)` is a
   one-line symptom of a model with no cheap discovery channel at all — every
   `explore_columns(folder=…)` returns nothing and the agent is left guessing keywords against the
   whole catalog. Observed on a model that had already been through a full evaluation round with
   nobody noticing, because nothing errors and the model looks complete from the YAML. While you are
   there, check the measure and dimension counts against what the generator printed: a silent
   mismatch means the deploy did not take what you think it took.
6. **Verify a mechanical refactor by diffing the queryable surface, not the file counts.** A
   `unique_name` grep across emitted YAML reported a 21-object loss per model, which is alarming and
   wrong — it was counting hierarchy level entries alongside attributes. The check that answers the
   question is a set diff of the **secondary attributes** and the **visible level attributes**
   before and after; it came back zero lost, zero gained across all twelve models, the only removals
   being hidden key attributes, one per absorbed dimension, which is the point of the merge. State
   the expected removals up front so the diff has something to be checked against.

**A ceiling sweep is cheap enough to ITERATE, and rounds two and three are where it pays.**
Measured 2026-09-20 on insider_trading: round 1 of 21 hand-written queries reached 3 exact
passes; rounds 2-5 - swapping in a published twin, dropping a null group, adding the column
the finding named - took it to **11 of 21**, all at $0. Each round's FINDING says what to
change next: `COLUMN COUNT` is the caller's projection and not a model gap, `ROW COUNT` with
every expected row already present is a threshold the user has to supply, `VALUES` on the
right shape is the population or the wrong twin. Stopping at round 1 reports a model as
unable to reach tasks it reaches.

**The ceiling test: hand-write the query against the deployed model and grade it.** One query
answers the question a whole run cannot — *can* this be answered, or did the agent merely not find
it? Take gold's shape, express it in the model's own columns with no budget and no discovery, run it
through the semantic layer, and put the rows through the real grader. A pass means the raw material
and a route to it both exist and the gap is discovery; a fail localises the model defect
immediately. Used through one round it separated three genuine model bugs from three gold defects
and two agent errors, at a cost of minutes rather than four runs. It is also the honest way to
report a fix: a run can hide a working fix behind budget exhaustion or variance; the ceiling test
cannot.

**A published rank's population is fixed at build time, and the caller's filter does not
re-rank it.** Measured 2026-09-20: a pending-wait rank ranked every recipient carrying a recorded
wait, including those with no antibody score, so a listing showing that score beside the rank got
a different winner for one group of five - and adding the filter could not fix it, because the
column was computed before the filter. Say this in the rank's own description, give both
populations, and name the caller-side escape: a RANK window function over the filtered rows
inside a FROM-subquery, which this engine accepts and which DOES re-rank inside the filter. The
same probe that found this showed the escape reaching an exact match against gold.

**A population rule stated as a sentence does not fire; the same rule stated as an ASK does.**
Measured 2026-09-20 across a 19-task baseline and a targeted re-run. The model described the
shared-population rule in its model description and on four averages, and the agent still
submitted too broadly on five tasks - on one of them with the narrowing flag already in its
`focus_columns` output. Rewriting the six coverage flags and the entity level to LEAD with an
explicit closed population question moved one task's result from 237 rows to gold's exact 198.
Note what it did not do: it converted no task. Both halves are the finding - the ask is the form
that reaches the agent, and reaching the agent is not the same as winning the task.

**Ceiling-test the POPULATION too, and expect it to be the thing that is wrong.** The reference
is a plain SQL reader: it reaches each figure through its own record and keeps only the rows where
every record it read exists, so a listing or a group aggregate pairing values from two records is
computed over the INTERSECTION of their populations, never over each column's own. Measured
2026-09-20 on a database whose six satellites cover six different subsets of 947 matches: the four
transport-method averages of ischemia time and graft survival are 573.67 and 0.54 over each
column's own rows, and 661.00 and 0.53 over the intersection - the second pair matching gold
exactly, with no change to either formula. Ship one coverage flag per record, put the rule in the
model description, and repeat it on every average a question could pair with another. The
diagnostic habit that follows: when a ceiling probe returns the right SHAPE and the wrong VALUES,
suspect the population before the formula, because a formula defect usually moves the shape too.

**A caller's window function is applied BEFORE the query's own grouping collapses duplicates.**
`RANK() OVER (PARTITION BY g ORDER BY x DESC)` inside a FROM-subquery that also GROUPs runs
against the fact rows, so an entity carrying several fact rows is ranked once per row: measured
2026-09-20, a per-group longest-wait rank returned 189 rank-1 rows where the answer is 5, and the
same query became an exact match as soon as the population was narrowed to one row per entity.
Two consequences. A "top N per group" question IS reachable caller-side, so do not spend a DAX
`RANKX` measure on it by reflex (and avoid ATSCALE-52370 with it). But where the narrowing is not
available to the caller, precompute the rank over DISTINCT entities in dataset SQL and say in the
description why the caller's own window function is not equivalent.

**Ceiling-test the VALUE pipeline, not only the query shape.** Values right to six significant
digits and wrong at the second decimal pass every shape check. On one 10-task database the value
pipeline was the whole story: two tasks unreachable because the reference belongs to a different
question, one capped by a reference join fan-out, three capped by a reference `LOWER()` no question
asked for, and **four reachable — every one failing on integer division, float32 addition or a
padded `character(20)`**. Do this before the first run, not after the third.

## After acceptance — the gates prove correctness, not usability

One model passed all four gates, validated clean, deployed clean, satisfied every rule above — and
its first evaluation run scored level with the raw text-to-SQL baseline. Every point of lift after
that came from work the gates do not ask for. Expect the same, and treat a first run at baseline as
the start of the work rather than a failure.

**Reading a run**

- **A single-database run resolves to ±1–2 tasks. Do not measure a fix with one run.** Four runs on
  one 19-task database: 3, 5, 5, 4 passes. Only **three** tasks passed in all of the last three;
  three others churned freely with no model change between them. One "regression" was the same task
  returning numerically identical values under self-invented labels. A day of model work and the
  run-to-run noise are the same size. Either use `--repeat` and compare means, or verify the fix by
  ceiling test and treat the run as a smoke test. Say which you did.
- **A twin-heavy model is noisier than the figures below, and its own twins are the cause.**
  Measured 2026-09-20 on insider_trading, a v12 build publishing competing readings wherever
  the KB or the warehouse is genuinely ambiguous: **5 of 21 tasks flipped between two runs of
  the IDENTICAL model**, and 7 between two runs differing only in description text. Each flip
  traced to a different twin - the recorded turnover reading then the recomputed one, the
  strict then the zero-filled reading, the two event-link readings. The agent resolves each
  fork by asking a user simulator that answers differently run to run. The twin rules are
  still right - a caller cannot select a reading that is not published - but the cost is
  measurable and it lands on variance, not on the mean: budget n≥2 for the close run on any
  model with more than a handful of twins, and do not read a per-task delta smaller than
  about ±3 tasks as a result.
- **n ≥ 3 per arm before believing any delta, and spend the repeats on the noisier arm.** A single
  run moves by roughly ±0.10 average reward from agent variance alone; the measured noise floor on
  one final configuration was sd 0.012–0.018. Variance is also *asymmetric*: on a 19-task set the
  semantic arm moved on 1 task of 19 across repeats (sd 0.71 points) while the raw arm moved on 7 of
  19 (sd 0.91, single-run totals 5.40–7.40) — 13 of 19 raw tasks were perfectly stable and the whole
  spread came from six. The semantic layer appears to constrain the agent to a narrow path while raw
  SQL lets it re-pick a formulation every run. Budget roughly **4 repeats on raw, 1–2 on the
  semantic arm**; a single run per arm can read anywhere from +7 to +32 percentage points of lift on
  identical code.
- **Pool across rounds, test properly, and know the run count your question needs before spending
  it.** Two independent three-run blocks either side of a change are far stronger evidence than one
  three-run comparison, and cost the same. Run an exact Mann-Whitney on the pooled samples rather
  than eyeballing means: one +0.040 improvement reached p = 0.167 at 6 vs 6 — real enough to keep,
  not enough to claim — and the residual −0.037 against raw came out at p = 0.298, i.e. **not
  distinguishable from noise**. Before opening another round, compute what it would take: at sd ≈
  0.04, detecting a 0.037 gap at 80% power needs about **18 runs per arm**, a 0.075 gap about 4. If
  the honest answer is "these are the same", say so and stop rather than buying a sixth round.
- **A per-task pass rate of "flaky" is data, not noise to be smoothed away.** Track which tasks are
  always/never/flaky per arm across rounds. A task moving never → flaky after a change is the signal
  that the change worked; a phase-2 count oscillating 0, 2, 0, 3 across four rounds is one flaky
  task and should not be reported as a regression. Before attributing any movement to your change,
  check whether the change touched any object the moved task actually references — the answer is
  often no.
- **Compute lift on the task intersection, never on arm totals**, and never quote a single pair of
  runs. The raw arm runs the Management-category tasks a read-only semantic layer structurally
  cannot serve; drop them from both sides. Quote the mean of the repeats with its range, in
  percentage points, with relative alongside. One outlier run paired against one good run produced a
  headline double the settled value.
- **Say when a change makes earlier runs non-comparable.** A refactor touching many models at once —
  a shared-emitter rule, a dimension merge, a naming convention — changes the discovery surface of
  every model it touches, so any earlier number for those models measures a different artefact. That
  is not a reason to avoid the refactor; it is a reason to land it deliberately and label it, because
  the alternative is someone reading a pre-change number against a post-change one and attributing
  the difference to whatever they were actually testing.

**Diagnosing failures**

- **Classify every failure mechanically rather than by eye.** Re-execute each submission against the
  engine and the reference against the warehouse, then score them with the harness's own comparison
  function under four settings — as graded, order-insensitive, case-folded, both. That splits
  failures into tie-order, casing, wrong-shape and genuinely-wrong in one pass, and it is the only
  cheap way to know which a model change could possibly address. Wrong *shape* — a different column
  or row count from the reference — is not a model defect at all; the model does not control the
  caller's `SELECT` list. Read the grader's normalisation first (on this harness: numerics rounded
  HALF_UP to the task's precision, two decimals unless a flag says otherwise, then compared as
  strings; strings compared byte-for-byte, no trim, no case fold; row order strict when the task says
  so), because "genuinely wrong" hides the value-pipeline class above.
- **Read the agent's actual submitted SQL** in the results JSON for every failing task. Almost every
  defect class in this document — object competition, an invisible phrasing, an inexpressible shape,
  a string-typed cast, a prescriptive description — is invisible to `validate`, to the gates and to
  live `run_query`, and obvious in one look at what the agent wrote. The graded submission is the
  **last** trajectory entry carrying an `sql` key, not the first.
- **Read *every* attempt, not just the graded one.** Observed: an agent produced gold's exact answer
  on attempt 1, that submission was recorded as failed, and it then spent its remaining budget
  "fixing" a correct query into a wrong one. Reading only the last attempt would have recorded a
  model gap that had in fact been closed.
- **Once a model is good, budget is what ends tasks.** 10 to 18 of 19 tasks exhausted their coin
  budget in every run of one round, including tasks that had already found the right answer. Before
  attributing a failure to the model, check `budget_remaining` and the final response — `"Budget
  exhausted. Task ended."` is not a modeling signal.
- **The grading path cannot distinguish a wrong answer from a broken gold.** Gold-side errors and
  timeouts return 0, and the caller catches bare `Exception` into *"Your SQL is not correct."* — so a
  swallowed pass is invisible in the audit and, worse, the agent is told its correct query was wrong
  and goes off to "fix" it. Where you can, log the gold error before returning 0. The fingerprint is
  an error string in the submit result rather than a grading verdict.
- **When *both* arms score 0.000 on every task of one database, suspect the harness before the model
  — and check whether the database's name is unusually long.** A raw text-to-SQL baseline does not go
  0/19; if it does, something structural is broken. Observed: BIRD's `instance_id` already begins
  with the database name and the harness prefixes it again, so the per-task database name is the name
  twice. At 32 characters that exceeded Postgres's 63-byte identifier limit, which truncates **with
  only a NOTICE while `createdb` still exits 0** — so all tasks collapsed onto one physical database
  and the phase-1 snapshot collided with its own source, converting every phase-1 *pass* into a
  recorded failure.
- **A cap is a claim, and it must be falsified before it is written.** Measured 2026-09-19 on
  solar_panel: five phase-1 tasks were recorded as capped and **four of the five were not** — the
  tuned model of the same database scored 3/3 on every one of them. A cap row is worse than a
  missing finding, because it tells the next session not to spend there, so the bar is evidence
  that *no honest model reaches the task*, not that this one does not. Two cheap falsifiers, both
  $0, both mandatory before a cap row is written:
  - **Check another arm's per-task verdicts.** Any recorded run of the same database under a
    different model is a lower bound on what is reachable. A task another model passes is not
    capped, whatever your reasoning says. Read the *verdicts only* — reading the other model's
    objects contaminates a from-scratch build (Sources).
  - **Say which rule makes it unreachable, and re-read that rule.** Both of the two mis-cappings
    below were a rule applied to the wrong shape, and re-reading the rule was enough to see it.
- **Two rules that get mis-applied in the direction of withholding an object.** Both were caught
  by the arm comparison above, both cost a task, both are re-derivable without any answer key:
  - *"Do not ship the dimensionally inconsistent reading as a twin"* is about a formula over two
    **lengths** or two **masses** — a mismatch **between operands**. It does **not** cover one
    operand whose **scale** is ambiguous against its own column, which is the percent-versus-fraction
    case the twin rules say explicitly to ship. Observed: a KB formula `P / (1 - Thermal Loss
    Factor)` over a coefficient stored in percent per degree. Converting first gives 672.78;
    subtracting the stored figure gives −161.87, negative on 200 of 205 rows. The build published
    only the converted reading and the reference used the other. A negative or physically odd
    result is **not** grounds to withhold a reading — it is grounds to say so in the description.
  - *"An unspecified constant is the caller's to supply"* means **publish the per-unit figure and
    say the multiplier is unstated**. It does not mean publish nothing. Observed: a projection
    defined as `rate x annual production x price x lifetime` with all three multipliers unstated
    was recorded "not computable" and shipped as **no object at all**, so the concept was
    undiscoverable by its own KB name and the agent could not even ask about it. Ship the stored
    term under a name carrying the KB's vocabulary, and tell the agent to ask for the rest.
- **"Not computable" is a claim about the whole formula and is usually false** (see the masked-KB
  rule above). Before writing it, enumerate the formula's terms and say of each whether it has a
  column, is a measured zero, or is absent. If any term is stored, something ships.
- **Sort failures into model-fixable and not, and say which is which** before changing anything. A
  task turning on a withheld ambiguity cannot honestly be fixed in the model — that failure is the
  firewall working, not a gap. Likewise a task whose expected answer is non-unique (a `LIMIT` across
  a tie) is capped regardless of the model. Reporting these together with real defects makes the
  model look worse than it is and invites a dishonest fix.

**Gold and harness defects, which are common enough to check first**

In one 19-task database, **5 of 14 failures were benchmark artifacts**:

- *Join fan-out* (three tasks). Gold's `LEFT JOIN` chain multiplies a per-entity figure by an
  unrelated table's row count, or counts one entity in two groups. Fingerprint: gold's group counts
  sum to **more than the entity population** — 986 for 972, 976 for 972. One gold scored an entity
  182 when its true score was 91, because the entity had two interactions and the interactions table
  was in the join for no other reason. The variant that is hardest to see: gold joins two tables to
  build a two-term composite and the fan-out inflates only **one** term while the other is correct
  *because* it lives at the joined grain — a per-encounter count summed after a `LEFT JOIN` to a
  per-treatment table totalled **1348 against the warehouse's 869**, differing on 94 of 273 groups,
  while the other term in the same expression was right. So run the sum-vs-population check **per
  term**, not on the query's output, and resist the trap it sets: a model twin computed at the
  fanned grain will reproduce gold *exactly*, which reads like confirmation and is the strongest
  available evidence that you are fitting a defect. Re-derive the term from the KB and the warehouse
  instead.
- *Wall-clock dependence.* A gold that estimates a date as `NOW() − <duration>` has an expected
  answer that drifts: measured 394.70 one day and 396.47 three days later. No materialized model can
  track it, and two runs a week apart grade against different truths.
- *Arbitrary tie order.* Gold has an `ORDER BY` with many rows tied on the sort key and the grader
  demands exact order. One submission matched all 221 rows as a set and failed on the order among
  tied rows.

Compute the sum-vs-population check on gold before building anything to match it. Two more harness
facts worth knowing:

- **A wall-clock formula is capped for part of every day when the warehouse session and the engine
  session disagree on the date.** The grader runs the reference through a driver session inheriting
  the Postgres server's timezone; the engine's JDBC session sets the JVM's. `CURRENT_DATE` in the two
  differed by one day for fifteen hours a day on the measured host, so every burn rate, runway and
  days-since figure was one day short of the reference in that window and exact outside it — a
  six-row runway answer matched to three decimals at `CURRENT_DATE − 1` and nowhere else. The dataset
  SQL is identical on both paths; only the session differs. Recompute the reference at ±1 day before
  classifying a wall-clock value as a model defect; a match there is this cap, which is the
  harness's to fix.
- **A screened listing whose sort key is NULL on a qualifying row is not automatically capped.** The
  rule that this engine emits `DESC NULLS LAST` where Postgres defaults to `NULLS FIRST` held on the
  databases it was measured on; on another the same shape came back with the null row first and
  graded 1. Probe it on the model in hand rather than assuming either way.
- **Tie-order is not a model problem, and the grading flags will not close a gap.** Where the
  reference's `ORDER BY` key is constant across its rows, its row order is arbitrary plan order
  following *no* rule — verified against alphabetical, reverse-alphabetical and every other column. A
  raw arm tends to reproduce it by construction (same engine, same plan, similar SQL) while a
  semantic layer's different engine cannot, so strict order comparison quietly favours raw. It is
  tempting to enable `grading_tie_tolerance` or `grading_casefold` — measure first: applied
  **symmetrically**, both lifted each arm by exactly the same +0.070 and the gap was unchanged. And
  `grading_casefold` as implemented is semantic-path-only, so enabling it as-is moves one arm and
  would close a gap for entirely the wrong reason. Leave the public benchmark settings alone unless
  you have measured that a change is symmetric.

**Spending decisions**

- **Predict a model fix's task-level payoff at zero, and price it that way.** Measured 3 for 3 on
  one database: a defect was found, fixed, verified against the reference, and the task did not move,
  because the agent's next choice up the stack became the binding constraint — it stopped projecting
  a misleading rank but never computed the right one; it stopped computing a wrong composite but then
  gated the population on the wrong count. A model fix reliably *removes a known-wrong answer*; it
  does not reliably produce a right one.
- **Verify sufficiency for free before spending a run.** Take the agent's own stored submission, run
  it through `run_query` against the fixed model, and diff it against the reference result — value by
  value, row count and all. That costs nothing and answers "is the model now capable of the right
  answer" definitively. Doing this caught a fix that was correct-but-insufficient before any
  benchmark spend. `probe_pred.py` and `result_diff.py` are the standing tools for this; run them
  before changing anything, because they routinely show that several failing phases already grade 1
  against the *deployed* model and the remaining failures are agent behaviour, not model objects.
- **Measure a systemic hypothesis before acting on it.** Four cross-database theories looked
  compelling and were each worth exactly zero: float32 noise (**119 columns across 11 models**
  identified for change before grading both forms proved the grader normalizes it); shares published
  as fractions where 71 of 600 golds want percentages (those tasks pass at 31.6% against 30.6% for
  everything else); a real asymmetry where the grader strips trailing zeros from a `Decimal` but not
  from a numeric-looking *string* (re-grading all 407 recorded submissions with it patched flipped
  **zero** verdicts); and percentage-vs-fraction naming. Each cost under an hour to measure and would
  have cost days to act on. A defect can be entirely real and still worth nothing, and only
  re-grading the recorded submissions tells you which.
- **Verify a suspected unfairness before reporting it.** Observed: the raw arm was seen fetching
  masked knowledge entries verbatim, which looked decisive, until a per-task check showed the harness
  filters each task's own deleted entries and there were **zero** same-task fetches — the 51 hits
  were terms masked on *other* tasks. Check the mechanism at the granularity the claim needs before
  it reaches a report.
- **Run hygiene is a whole class of voided runs.** Before each run, verify the environment with the
  harness's own credentials, not through your own MCP connection: run a full initialize → session →
  tools/call handshake using the token the harness will use. Three runs were lost to an HTTP 401 that
  a check through a different connection had pronounced healthy. Add the interpreter to the same
  check — a service-start script resolved a project-local environment while the run script called a
  bare `python`, so the services ran healthily for hours and the runner died instantly on
  `ModuleNotFoundError`. Where several scripts need the same interpreter, resolve it in one place;
  where they cannot, have each assert it can import a dependency it needs and fail with a sentence
  instead of a traceback. With the Q-17b gate, these habits account for six voided runs — more
  elapsed time than every model fix in one build put together.

**Steering the agent**

- **Make the ask-the-user trigger name the shape of the answer to request.** This was the only
  change across four measured rounds on one database that moved the score. Measured over 170
  `ask_user` exchanges across both arms: a question proposing **explicit options** got a specific
  answer back **71–94%** of the time, an open-ended one **25%**; and after a qualitative reply both
  arms **gave up rather than re-asking about 60% of the time**. So a trigger reading "ask the user
  for the complete definition" leaves the lever unused. Write it as: *ask as a closed question with
  explicit options — the exact numeric cutoff, and the exact label text for each band — use their
  spelling verbatim, and if the answer comes back qualitative ask again offering options rather than
  choosing one yourself.* Saying what *kind* of answer to request publishes no cutoff. Effect: +0.040
  average reward pooled over six runs either side, with the mechanism confirmed in the trajectories
  (re-ask rate 38% → 50%) rather than assumed.
- **"Confirm with the user" in a description only works if the agent asks the question *open*.**
  Observed on the same task twice: asked as a genuine two-option question ("the total count, or only
  those with a computable score?") the agent chose correctly; asked as a leading one ("what minimum
  number of *scoreable* entities…") the simulator simply ratified the premise and the task failed.
  You cannot fix the framing from the model, so where a wrong choice is silent, make the two objects
  separately named and separately documented with live counts, and expect to lose the task some
  fraction of the time.
- **Check what the user simulator actually said before blaming the model.** A task can be unwinnable
  because the simulator's own answer differs from the reference: on one task the model produced every
  count and percentage exactly right and failed only on category labels, because the simulator said
  "4-6 Months Before" where the reference wanted "Optimal Window (4-6 Months)". Record it as capped.
- **Some failures are the agent's, and they get shared guidance rather than a model object.**
  Recurring shapes worth carrying in the agent's own instructions: a vague content noun ("what
  exactly should the output contain") opens a slot to ask about; an entity singled out by a
  superlative is the route to the figure, not part of the answer; a unique code beats a shared name
  without an ask; a question naming a rate when the warehouse records an amount needs the ratio, not
  the amount; and a "projected" or "lifetime" figure is a formula to ask for, not a recorded column
  to sum. Keep them out of the model, where they would be prescriptive descriptions (Definitions and
  labels).
- **Know when to stop.** Four measured rounds on one database produced one probable win, one
  regression introduced and withdrawn, and two of the model's own descriptions found to be steering
  wrong; the arm went from a clear deficit to statistically indistinguishable from raw, and the
  residual was made of output shaping, withheld label strings, tie-order and a dialect gap — none of
  which a semantic model controls. When the remaining failure classes are all outside the model, say
  so and write it up. A database that reaches parity honestly is a result, and so is one that does
  not.
