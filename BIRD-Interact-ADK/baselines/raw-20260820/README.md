# RAW BASELINE — 2026-08-20

The raw (text-to-SQL, no semantic layer) baseline for all 13 evaluated databases.
**Frozen. Do not regenerate.** Every atscale comparison is measured against this.

`results/` is gitignored, so these are the only version-controlled copies. Files are
gzipped and mode 444. Verify integrity with `shasum -c SHA256SUMS`.

## Contents

| file | tasks | avg_reward | p1 | p2 | errors | start | min | cost | dbs |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| `cross_border_raw_run01_20260820_142145.json.gz` | 19 | 0.0895 | 2 | 1 | 0 | 14:21 | 6 | $4.52 | 1 |
| `cross_border_raw_run02_20260820_142751.json.gz` | 19 | 0.1105 | 3 | 0 | 0 | 14:27 | 7 | $4.34 | 1 |
| `cross_border_raw_run03_20260820_143434.json.gz` | 19 | 0.0368 | 1 | 0 | 0 | 14:34 | 6 | $4.33 | 1 |
| `new12_raw_run01_20260820_113016.json.gz` | 219 | 0.1973 | 51 | 25 | 0 | 11:30 | 52 | $41.63 | 12 |
| `new12_raw_run02_20260820_122226.json.gz` | 219 | 0.2384 | 60 | 34 | 0 | 12:22 | 53 | $42.49 | 12 |
| `new12_raw_run03_20260820_131510.json.gz` | 219 | 0.2201 | 56 | 30 | 0 | 13:15 | 49 | $42.09 | 12 |

## Baseline figures

- **12 databases (219 tasks):** mean **0.2186**, sd 0.0206 (0.1973 / 0.2384 / 0.2201)
- **cross_border (19 tasks):** mean **0.0789**, sd 0.0380 (0.0895 / 0.1105 / 0.0368)

All six runs completed with **zero task errors**.

## Provenance

```
python -m orchestrator.runner --mode a-interact --backend raw --query-only \
  --databases <13 dbs> --repeat 3 --concurrency 32
```

`--query-only` restricts raw to the same Query-category tasks the atscale arm
filters to itself, so both arms grade an identical task set.
