# Semantic model change log

Every change made to an ETF semantic model **after** its initial build, with the date and
the reason. This is the record of how each deployed model has diverged from the artifact it
started as.

Not a file-by-file diff — describe the *kind* of thing that changed and why. The commit is
there for anyone who needs the detail.

## Adding an entry

Append to the top of the relevant model's section, newest first. Any session that changes a
model must add an entry in the same commit, including sessions that did not create the model.
An entry needs:

- **Date** and the commit (plus branch, if unmerged)
- **What kind of change** — descriptions, dataset SQL, a metric added or dropped, and so on
- **Why** — the behaviour that forced it, and the tracker ID if one exists

If a change only exists to work around an engine or tool defect, say so and name the tracker
row. Those are the entries to revisit when the defect is fixed — see *Workarounds* at the end.

---

## `bird_etf_prompt_only`

Repo `diannewood/bird-etf-prompt-only`. Deployed as
`atscale_catalogs.bird_etf_prompt_only."Exchange Traded Funds"`.

**Baseline** — commit `0ee3bac`, "BIRD exchange_traded_funds semantic model (prompt-only
build)". Generated from `create_etf_prompt.txt` alone, with no access to gold SQL, via
`specs.py` (declarative) → `generate.py` (deterministic emitter). Everything below is a
deliberate departure from that build. Because the emitter is deterministic, changes are made
by editing the spec and re-running the generator, not by hand-editing YAML.

### 2026-08-06 — Flag labels declared a re-labelable convention (`bcbae35`)

Appended a convention note to all 36 flag/classification attribute descriptions, stating that
the label strings are this model's own choice and that a caller wanting different wording
should re-label in the query rather than abandon the attribute.

A bucketing attribute fixes a *condition*; the words it prints are the modeller's. Nothing in
the model said so, which invites a caller to treat the labels as required output vocabulary.
Benchmark answers compare label text as cell values, so correct rows under the model's own
wording score zero. Descriptions only — verified structure-identical with descriptions
stripped, 191 descriptions before and after, all 36 changes pure appends.

A matching fifth Modeling rule was added to `create_etf_prompt.txt`, so a future build from
the prompt produces this natively instead of needing the patch.

### 2026-08-06 — Schema-qualified derived SQL; median metric dropped (`d358cfa`)

Two unrelated changes in one commit.

**Schema qualification.** Datasets defined by a SQL query now reference physical tables as
`public.<table>` rather than bare `<table>`. The engine executes derived-dataset SQL without
the connection's declared `schema: public` on the `search_path`, so bare references fail at
query time with `relation "<table>" does not exist` — even though the connection declares the
schema and the table exists. Tracker **E-02**. Nothing surfaces at validate or deploy; the
model deploys clean and then cannot answer anything.

**Median dropped.** MDX `Median` is rejected at deploy and the percentile-sketch alternative is
rejected by the Postgres dialect at query time, so there is no expressible median on this
warehouse. Recorded in `KB_COVERAGE` instead of shipping something that fails. Supersedes
`fdef3d1` below.

### 2026-08-06 — Punctuation-free paraphrases in descriptions (`9277ffb`)

Added paraphrases to column descriptions so a concept is findable under more than one wording.

`explore_columns` is an ordered substring match over names and descriptions, not a fuzzy or
keyword search, so a question phrased differently from the description returns nothing at all
— `enough history` and `track record` both missed a column that `history depth` and
`data coverage` hit. Widening the description surface is the only model-side lever. Tracker
**Q-16** (the tool-side defect).

### 2026-08-06 — Median 1-Year Return as a percentile metric (`fdef3d1`)

Added a median metric using a percentile formulation after the engine rejected MDX `Median`;
also made the generator clean its output directories on regeneration. **Superseded** — the
percentile form then failed at query time on the Postgres dialect and the metric was removed
in `d358cfa`. Kept here because the generator's clean-on-regen behaviour survives.

---

## `bird_atscale_models_catalog` (exchange_traded_funds)

Repo `AtScaleInc/bird-atscale-models`, directory `exchange_traded_funds`. Deployed as
`atscale_catalogs.bird_atscale_models_catalog."Exchange Traded Funds"`. **Not** a prompt-built
model — it predates that work and is used as the comparison arm. Shared repo: it also backs a
colleague's `solar_panel` model, so changes here are scoped to `exchange_traded_funds/`.

### 2026-08-06 — Schema-qualified physical table references (`7617eec`)

Branch `dianne/qualify-etf-dataset-schema` — **pushed, deployed, not merged.**

Datasets defined by a SQL query now reference physical tables as `public.<table>`. 31
references across 9 datasets, whitelisted to the 15 real tables so CTE aliases and constructs
like `EXTRACT(YEAR FROM calendaryear)` are untouched. Behaviour is otherwise unchanged —
`public` was always the intended schema.

Same engine defect as `d358cfa` above (**E-02**): every query against the deployed model failed
`relation "funds" does not exist`, and the model scored 0.0/5 across a 5-task run without a
single successful query. The sibling prompt-only model was unaffected only because it already
qualified everywhere.

> **Live deployment is ahead of `main`.** A redeploy from `main` reintroduces the defect. Merge
> the branch or re-apply before deploying this catalog from a clean checkout.

---

## Workarounds to revisit

These exist only because of a defect elsewhere. If the defect is fixed, the change can be
reconsidered — none of them is something a model *should* have to do.

| Change | Tracker | Revisit when |
|---|---|---|
| `public.` qualification in both models | **E-02** | Engine honours the connection's declared schema for derived-dataset SQL |
| Paraphrases in descriptions | **Q-16** | `explore_columns` ranks partial matches instead of requiring a verbatim ordered substring |
| Median dropped | **E-01**-adjacent (`Q-06`, `M-03`) | Engine supports a median/percentile the Postgres dialect can execute |

The flag-label convention note is **not** a workaround — the labels genuinely are the model's
convention, and saying so is correct regardless of how the benchmark grades.
