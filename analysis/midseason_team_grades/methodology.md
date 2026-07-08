# Midseason Team Grades Methodology

## Purpose

The Midseason Team Grades project creates analysis-ready datasets for team evaluation and editorial grading. It is built to support cross-dataset EDA across team style, four factors, bench usage, clutch scoring, player impact, All-Star value, and skill-profile fit.

## Team Four Factors

Team-game four factors are calculated from SportsDataverse team box scores:

| Metric | Formula |
|---|---|
| Offensive eFG% | `(FGM + 0.5 * 3PM) / FGA` |
| Turnover rate | `TOV / (FGA + 0.44 * FTA + TOV)` |
| Offensive rebound rate | `OREB / (OREB + opponent DREB)` |
| Free-throw attempt rate | `FTA / FGA` |

Defensive fields use the opponent's offensive four-factor row from the same game.

## Bench Impact And Depth

Bench rows are player-game rows where:

- `did_not_play != True`
- `starter == False`

Team bench metrics include bench points, points share, minutes share, TS%, eFG%, AST/TO, and plus-minus. Bench net rating remains unavailable until validated possession/stint data is available.

## Clutch Context

Clutch scoring uses ESPN PBP rows with:

- `start_game_seconds_remaining <= 300`
- absolute score margin at or below the close-game threshold used by the builder
- scoring plays with positive `score_value`

Current clutch output is scoring-context first. Possession-based clutch rating remains unavailable until possession validation is added.

## Player Impact And Fit

Player impact reuses the Midseason All-Star Value Board where available. Fit profiles come from player feature signals such as usage, true shooting, rim share, three-point share, and shot-diet labels.

## VORP And RAPM Policy

Actual VORP is not calculated from the current data because the repo does not contain an exact WNBA-compatible VORP formula or source field.

RAPM-style output is generated only when lineup data passes validation. The current implementation uses a reproducible ridge-regression approach with existing dependencies and labels the output as RAPM-style rather than official RAPM.
