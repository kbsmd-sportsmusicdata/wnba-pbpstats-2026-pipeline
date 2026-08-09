# WNBA Standings & Playoff Forecast

This season-parameterized project builds a reproducible WNBA standings and playoff forecast bundle. It preserves the existing upstream ingestion workflows and follows the repository's thin-builder, importable-package analysis pattern. One validated machine-readable bundle owns the standings, official tiebreak ordering, matchup probabilities, simulations, leverage, and deterministic broadcast insights used by every presentation surface.

## Source Workflows

The forecast consumes, rather than replaces, the active upstream sources:

- `scripts/fetch_wnba_sportsdataverse_2026.py` and `.github/workflows/sportsdataverse-wnba-2026.yml` for schedule, team box, and standings data.
- `scripts/pbpstats_2026_pull_clean.py`, `scripts/pbpstats_2026_features.py`, and `.github/workflows/pbpstats-wnba-2026.yml` for optional latest-snapshot team-feature enrichment and QA.

## Data and Output Roots

The reusable normalized team-game layer lives at `data/processed/wnba_team_game/season=<season>/team_game.parquet`. Forecast-specific machine-readable outputs live under `analysis/standings_playoff_forecast/data/processed/season=<season>/latest/`, while presentation artifacts live under `analysis/standings_playoff_forecast/deliverables/season=<season>/latest/`.

The four deliverables are:

1. Excel analysis workbook: `wnba_standings_playoff_forecast.xlsx`.
2. Broadcaster Markdown brief: `wnba_broadcast_forecast_brief.md`.
3. One-page broadcast stat-pack insert: `wnba_playoff_stat_pack_insert.html`.
4. Interactive HTML playoff-race dashboard: `dashboard/index.html`.

## Season and Historical Scope

The CLI requires an explicit `--season` parameter. Season-specific competition rules and source paths are configured per verified season; unknown seasons fail closed. The initial target is 2026. Prior normalized partitions may provide descriptive context, optionally bounded by `--history-start`, but historical model training is out of scope for V1. `--skip-history` produces a valid empty history output and does not prevent the current-season forecast.

The cutoff defaults to the latest completed game in the qualified source schedule, never the wall clock. The default seed is deterministically derived from the season and resolved cutoff. Latest-cutoff builds reconcile derived GP/W/L exactly to the SportsDataverse standings snapshot before simulation; a stale or inconsistent mandatory snapshot fails the build instead of being silently repaired.

## Run and Test

Build the 2026 machine-readable bundle with a small local simulation count:

```bash
python scripts/build_standings_playoff_forecast.py \
  --season 2026 \
  --simulations 500 \
  --render none
```

Supported runtime options are `--cutoff YYYY-MM-DD`, `--simulations`, `--conditional-simulations`, `--random-seed`, `--history-start`, `--skip-history`, `--render {none,all}`, `--sportsdataverse-data-root`, `--pbpstats-data-root`, and `--output-root`. V1 derives conditional leverage from the retained main simulations, so a nonzero `--conditional-simulations` request fails rather than claiming a second run occurred. Presentation rendering is added in Tasks 13–15; until then, use `--render none`.

Refresh upstream sources, then build:

```bash
python scripts/fetch_wnba_sportsdataverse_2026.py
python scripts/pbpstats_2026_pull_clean.py
python scripts/pbpstats_2026_features.py
python scripts/build_standings_playoff_forecast.py --season 2026
```

Run the forecast test suite:

```bash
python -m unittest discover -s tests -p "test_standings_playoff_forecast*.py"
```
