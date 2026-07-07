# WNBA Midseason All-Star Value Board

This module builds a reusable WNBA Midseason / All-Star Value Board from the existing 2026 SportsDataverse and PBPStats outputs.

It is an editorial analytics project, not an official All-Star ballot prediction model. The goal is to rank player value cases, explain the shape of each case, and create clean datasets for dashboards, reports, and social graphics.

## Run

```bash
python scripts/build_midseason_allstar_value_board.py \
  --config analysis/midseason_allstar_value_board/config/allstar_value_board_config.json \
  --stage all
```

Supported stages:

| Stage | Writes |
|---|---|
| `processed` | candidate pool, metric panel, value board, archetypes, run manifest |
| `viz` | visualization-ready CSVs from existing processed outputs |
| `editorial` | Substack asset manifest and draft from existing processed outputs |
| `all` | all processed, viz, and editorial outputs |

## Source Contract

The module consumes existing latest pipeline outputs. It does not download SportsDataverse data or rebuild PBPStats features.

Primary PBPStats inputs:

```text
data/pbpstats_wnba_2026/features_latest/2026/player_totals_features_latest.csv
data/pbpstats_wnba_2026/features_latest/2026/team_totals_features_latest.csv
```

Primary SportsDataverse root:

```text
data/raw/sportsdataverse/wnba_2026
```

Local fallback root used by this checkout:

```text
2026_scout_report
```

## Outputs

Processed outputs:

```text
analysis/midseason_allstar_value_board/data/processed/candidate_pool_2026.csv
analysis/midseason_allstar_value_board/data/processed/player_metric_panel_2026.csv
analysis/midseason_allstar_value_board/data/processed/allstar_value_board_2026.csv
analysis/midseason_allstar_value_board/data/processed/player_archetypes_2026.csv
analysis/midseason_allstar_value_board/data/processed/run_manifest_2026.json
```

`candidate_pool_2026.csv` and `player_metric_panel_2026.csv` keep every player for diagnostics. Eligibility uses SportsDataverse player box-score minutes and games, joined by player name plus team. PBPStats minutes are retained as `pbpstats_minutes` for diagnostics only and are not used as an eligibility fallback. `allstar_value_board_2026.csv` is the public board and includes only rows where `eligible_flag == True`.

Visualization-ready outputs:

```text
analysis/midseason_allstar_value_board/data/viz/board_rankings_viz_2026.csv
analysis/midseason_allstar_value_board/data/viz/score_components_viz_2026.csv
analysis/midseason_allstar_value_board/data/viz/archetype_scatter_viz_2026.csv
analysis/midseason_allstar_value_board/data/viz/team_representation_viz_2026.csv
analysis/midseason_allstar_value_board/data/viz/social_card_players_2026.csv
```

The ranked board and social-card datasets inherit the eligible-only public board filter.

Editorial outputs:

```text
analysis/midseason_allstar_value_board/editorial/substack_asset_manifest_2026.md
analysis/midseason_allstar_value_board/editorial/substack_draft_2026.md
```

## GitHub Actions

The manual workflow at `.github/workflows/midseason-allstar-value-board.yml` can run tests and any combination of processed, viz, and editorial stages. It writes a GitHub Step Summary with row counts and the top 10 board.

The workflow does not commit outputs unless `commit_outputs` is set to `true`.
