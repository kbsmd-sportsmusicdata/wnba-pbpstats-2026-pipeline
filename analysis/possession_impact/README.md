# Possession Impact

RAPM, bench net rating and clutch net rating, computed from the possession-level feed.
All three need to know who was on the floor, and all three were previously unavailable in
this repo for want of validated possession/stint data.

## Outputs

`data/processed/`

| File | Grain | Rows (2026) |
|---|---|---:|
| `rapm_player_2026.csv` | player | 207 (163 reliable sample) |
| `bench_net_rating_2026.csv` | team | 15 |
| `clutch_net_rating_2026.csv` | team | 15 |
| `rapm_alpha_cv_2026.csv` | penalty candidate | 10 |
| `run_manifest_2026.json` | run | Coverage window, fit diagnostics, external comparison |

## ⚠️ Read the coverage date first

The possession feed lags the rest of the pipeline. These outputs currently cover
**195 games through 2026-07-22**, while the snapshot panel reaches 2026-08-11.

Every output carries a `coverage_through` column on every row, so the lag is visible even
if you open a single CSV. Don't compare these numbers to season-to-date figures from the
other modules without accounting for it.

## Running

```bash
python scripts/build_possession_impact.py \
  --config analysis/possession_impact/config/possession_impact_config.json
```

Options: `--sportsdataverse-data-root`, `--pbpstats-data-root`, `--output-root`. CI
equivalent is the **Possession Impact** workflow. Runs in about six seconds.

Refresh the SportsDataverse download first — this is only as current as
`wnba_possessions_2026.parquet`.

## Key Columns

**`rapm_player_2026.csv`**

| Column | Meaning |
|---|---|
| `o_rapm` / `d_rapm` / `rapm` | Points per 100 possessions above average; higher is better on both sides |
| `off_poss` / `def_poss` / `total_poss` | Sample behind the estimate |
| `sample_flag` | `Reliable` at ≥500 possessions, else `Low sample` |
| `rapm_rank` | Rank on total RAPM across all reported players |

**`bench_net_rating_2026.csv`** — `starters_only_*`, `any_bench_*` and `bench_heavy_*`
ratings with possession counts, plus `bench_dropoff` (starters-only minus any-bench net
rating): how far a team falls off when it goes to the bench.

**`clutch_net_rating_2026.csv`** — offensive, defensive and net rating in possessions
starting late in close games, with possession and game counts.

## Interpreting These

- **Rank order beats magnitude.** Half a season of possessions is heavily shrunk by design,
  so the spread is narrow. Who is above whom is the signal.
- **Always check the possession count.** Starters-only slices in particular run 336–730
  possessions per team, the noisiest numbers in the set.
- **Clutch is descriptive.** 55–188 possessions per team is not a predictive sample.
- `rapm` here is an independent estimate. The `rapm` column in the published
  `wnba_player_impact` feed is DARKO-derived; the two correlate 0.87, which is a check, not
  a target.

## Verification

- Possession-weighted team RAPM correlates **0.982** with team net rating.
- Intercept + half home-court advantage reproduces league points per 100 to within 0.2.
- Starters derived here match the independent lineups feed on 195 of 195 games.
- 26 unit tests: `python -m unittest tests/test_possession_impact.py`.

Full method, diagnostics and limitations: [`methodology.md`](methodology.md).
