# WNBA Standings & Playoff Forecast

This season-parameterized project will build a reproducible WNBA standings and playoff forecast bundle. It preserves the existing upstream ingestion workflows and follows the repository's thin-builder, importable-package analysis pattern; model behavior is added in later tasks.

## Source Workflows

The forecast consumes, rather than replaces, the active upstream sources:

- `scripts/fetch_wnba_sportsdataverse_2026.py` and `.github/workflows/sportsdataverse-wnba-2026.yml` for schedule, team box, and standings data.
- `scripts/pbpstats_2026_pull_clean.py`, `scripts/pbpstats_2026_features.py`, and `.github/workflows/pbpstats-wnba-2026.yml` for optional latest-snapshot team-feature enrichment and QA.

## Data and Output Roots

The reusable normalized team-game layer will live at `data/processed/wnba_team_game/season=<season>/team_game.parquet`. Forecast-specific machine-readable outputs will live under `analysis/standings_playoff_forecast/data/processed/season=<season>/latest/`, while presentation artifacts will live under `analysis/standings_playoff_forecast/deliverables/season=<season>/latest/`.

The four deliverables are:

1. Excel analysis workbook: `wnba_standings_playoff_forecast.xlsx`.
2. Broadcaster Markdown brief: `wnba_broadcast_forecast_brief.md`.
3. One-page broadcast stat-pack insert: `wnba_playoff_stat_pack_insert.html`.
4. Interactive HTML playoff-race dashboard: `dashboard/index.html`.

## Season and Historical Scope

The CLI requires an explicit `--season` parameter. Season-specific competition rules and source paths will be configured per verified season; unknown seasons will fail closed once configuration is implemented. The initial target is 2026. Historical partitions may provide context, but historical model training is out of scope for V1 and a 2026 forecast must run without historical partitions.

## Run and Test

Current skeleton run for 2026:

```bash
python scripts/build_standings_playoff_forecast.py --season 2026
```

Import smoke test:

```bash
/private/tmp/wnba_forecast_venv/bin/python -m unittest tests/test_standings_playoff_forecast_config.py
```
