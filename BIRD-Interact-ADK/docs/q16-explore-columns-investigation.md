# Q-16 — `explore_columns` matches literal substrings, not keywords

**Brief for an agent investigating in `/Users/dianne/go/src/github.com/AtScaleInc/mcp`.**
Written 2026-08-06 from the BIRD-Interact benchmark harness side. Everything under
"Established" was verified live against the deployed engine; treat it as given and do not
re-derive it. Everything under "Unknown" is your job.

---

## Why this matters

`explore_columns` is how an agent finds columns in a semantic model. When it returns nothing,
the agent has no way to tell "no such column" from "wrong phrasing", so it rephrases and pays
again. In the most recent benchmark run **17 of 36 `explore_columns` calls returned nothing**;
one task burned 11 empty calls out of 16, reached a single submit, and scored 0 where it had
previously scored full marks.

It also corrupts measurement: discovery failure is indistinguishable from poor model quality in
the results, so any model-vs-model comparison is unreadable until this is fixed. It is the
top-priority (P0) query-side defect in the tracker.

---

## Established — verified live, do not re-derive

**The matcher is an ordered substring test against a column's name and description.** Not
fuzzy, not token-based, not word-count-limited.

Probes against the deployed model `atscale_catalogs.bird_etf_prompt_only."Exchange Traded
Funds"`, targeting the column **`Fund Years With Return Data`**, whose remark reads
*"Count of annual_returns years with a non-null fund return - history depth / data coverage for
the fund."*

| Term | Result | Why |
|---|---|---|
| `fund years` | **hit** | adjacent, in order, in the name |
| `years fund` | **EMPTY** | same two words, reversed |
| `years with return data` | **hit** | exact substring of the name |
| `return years` | **EMPTY** | both words in the name, not adjacent |
| `data coverage` | **hit** | exact substring of the remark |
| `coverage data` | **EMPTY** | same two words, reversed |

**Word order alone flips the result.** That rules out token-AND, token-OR, and any word-count
threshold.

**The word-count theory in older notes is wrong.** The tracker previously recorded "terms longer
than about 3 words match nothing." That was a symptom: a long phrase is simply unlikely to occur
verbatim. Corrected in tracker row Q-16 on 2026-08-06 — if you find a stale copy of the
word-count claim elsewhere, fix it.

**Agent-visible consequence.** Every word added to a term can only narrow the match towards
zero. From a real trajectory, same task, same concept:

```
EMPTY  "Yearly Outperformance Category Return Fund Return"
hit    "Yearly Outperformance"
EMPTY  "up market down market outperformance"
hit    "up market" / "down market"   (as two separate terms)
```

**Related history.** Harness commit `0cb6ae9` coerces a bare-string `search_terms` into a
single-element list, i.e. one phrase. Before it, the server tokenised a bare string on
whitespace and OR'd the tokens, which over-matched badly — one query returned 86,794 characters
of unranked catalog (tracker row Q-01). So the same code path has now failed in both
directions: **OR-everything (useless but non-empty) and exact-substring (empty)**. Neither
degrades gracefully. Any fix should address both, not swap one for the other.

---

## Unknown — what to find out

1. **Locate the matcher.** Start at `src/atscale_mcp/tools/handlers.py` (`explore_columns`
   handler); `tools/params.py` and `tools/responses.py` are likely relevant to how
   `search_terms` is parsed and results shaped. Find the exact predicate applied per term and
   per column, and what fields it searches (name only? description? synonyms? caption?).
2. **Confirm or refute the substring hypothesis in the code**, and record the actual predicate.
   The table above is black-box evidence; the brief needs the real implementation.
3. **Multiple terms** — are they OR'd or AND'd across the list? The harness passes
   `["up market", "down market"]` and gets both, suggesting OR, but confirm.
4. **Case and punctuation** — is matching case-insensitive? Are `-`, `/`, `(` normalised? The
   benchmark's column names contain all three.
5. **Is there a ranking or a limit?** `['years']` returned ~10.9k characters; `['data coverage']`
   returned 270. If a cap exists, what is dropped, and is the intended column reliably inside it?

---

## What a good fix looks like

The tracker's stated preference, unchanged since Q-01: **rank partial matches instead of
choosing between everything and nothing.** Concretely, in rough priority order:

1. **Never return an empty result when any token matches something.** Fall back from
   whole-phrase to per-token matching and rank by how many tokens hit. This alone would have
   recovered every empty call in the run above.
2. **Rank rather than filter.** Score columns (exact phrase > all tokens > some tokens; name
   match > description match) and return the top N with scores, so a caller can tell a strong
   match from a weak one.
3. **Say why a search failed.** "No columns matched" should distinguish "no token matched any
   column" from "matched too many, showing top N". A caller that knows which one it hit stops
   guessing.
4. **Do not simply revert `0cb6ae9`'s effect.** OR-ing whitespace tokens is the Q-01 failure —
   86k characters of noise is as unusable as an empty result.

Please also add regression tests covering the six probes in the table above; they are cheap,
and word-order sensitivity is exactly the kind of thing that silently returns.

---

## Reproducing

The engine is at `ATSCALE_API_URL=http://local.atscaleinternal.com:3001`; bearer token in
`.mcpServers["atscale-local"].headers.Authorization` of
`/Users/dianne/go/src/github.com/AtScaleInc/mcp/.mcp.json`.

From the harness repo (`BIRD-Interact-ADK`), driving the same MCP client the benchmark uses:

```python
import asyncio, sys
sys.path.insert(0, '.')
from system_agent.tools_atscale import _call

D = {'catalog': 'atscale_catalogs',
     'schema': 'bird_etf_prompt_only',
     'table': 'Exchange Traded Funds'}

async def probe(terms):
    out = await _call('explore_columns', {'search_terms': terms, **D})
    print(terms, 'EMPTY' if 'No columns matched' in out else f'{len(out)} chars')

asyncio.run(probe(['fund years']))   # hit
asyncio.run(probe(['years fund']))   # EMPTY
```

Two ETF models are deployed and both show the behaviour — swap `schema` for
`bird_atscale_models_catalog` to check the other.

---

## Out of scope — do not conflate

A separate, genuine gap surfaced alongside this and belongs to the **model**, not the tool:
`['enough history']` and `['track record']` return empty because no column name or description
contains those words, while `['history depth']` and `['data coverage']` find the intended
column. That is missing paraphrase coverage in the model's descriptions, and it would remain
after this tool is fixed — though a partial-match fallback would soften it. Do not treat it as
evidence about the matcher.
