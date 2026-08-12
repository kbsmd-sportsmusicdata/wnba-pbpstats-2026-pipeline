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

Team bench metrics include bench points, points share, minutes share, TS%, eFG%, AST/TO, and plus-minus. Bench net rating is not yet calculated; see Possession Data below for the source that now makes it possible.

## Clutch Context

Clutch scoring uses ESPN PBP rows with:

- `start_game_seconds_remaining <= 300`
- absolute score margin at or below the close-game threshold used by the builder
- scoring plays with positive `score_value`

Current clutch output is scoring-context first. Possession-based clutch rating is not yet calculated; see Possession Data below.

## Player Impact And Fit

Player impact reuses the Midseason All-Star Value Board where available. Fit profiles come from player feature signals such as usage, true shooting, rim share, three-point share, and shot-diet labels.

## Source Files

Sources are named in the config and resolved against `sportsdataverse_data_root`. The
play-by-play entries point at `espn_pbp_2026.parquet` (clutch) and `wnba_pbp_2026.parquet`
(RAPM).

An unresolved source used to look exactly like a genuinely empty feed, which let clutch and
RAPM return nothing without anything saying why. Each entry in the run manifest now carries
a `status` of `resolved` or `unresolved`, an unresolved entry records the filename that was
requested, and the run summary lists unresolved sources above the row counts. A test asserts
that every configured source resolves and that the play-by-play feeds carry the columns
their builders need.

## Exhibition Games

The 2026 All-Star Game (TEAM SPOON vs TEAM COOP) is tagged as regular season in the ESPN
feed, so it cannot be excluded on `season_type`. Left in, it grades two pseudo-teams as
league teams and inflates every team-count output from 15 to 17.

Box and play-by-play rows are therefore filtered to franchises listed in the standings,
which is used as the authoritative team list rather than a hard-coded set so the filter
survives expansion. Both sides of an excluded game are dropped, not just the non-franchise
side.

## VORP And RAPM Policy

Actual VORP is not calculated from the current data because the repo does not contain an
exact WNBA-compatible VORP formula or source field.

RAPM-style output is generated only when lineup data passes validation. The current
implementation uses a reproducible ridge-regression approach with existing dependencies and
labels the output as RAPM-style rather than official RAPM.

**RAPM currently produces no rows**, with status `skipped_missing_lineup_columns`. The
ridge model needs to know who was on the floor for each scoring event -- columns
`home_player1`-`home_player5`, `away_player1`-`away_player5` and
`player1_team_abbreviation`. Neither play-by-play file in this repository carries them:
`wnba_pbp_2026.parquet` identifies only the player involved in each event, not the ten on
the court. Producing RAPM again requires a lineup-bearing source (for example, possession
or stint data from the `pbpstats` library), not a configuration change.

## Possession Data

`wnba_possessions_2026.parquet` and `wnba_lineups_2026.parquet` are now pulled by the
SportsDataverse downloader. The possessions file carries one row per possession with the
offensive and defensive team, points scored, and **both five-player lineups on the floor**
(`off_player_1`-`off_player_5`, `def_player_1`-`def_player_5`), plus per-possession
shooting, rebounding and turnover detail.

This is the validated possession/stint data that three metrics in this methodology were
waiting on:

- **RAPM** can be estimated properly, regressing possession-level points on the ten
  on-court indicators, instead of the current scoring-event approximation.
- **Bench net rating** becomes computable from possessions rather than plus-minus.
- **Possession-based clutch rating** becomes computable.

`wnba_player_impact_2026.parquet` additionally supplies pre-computed RAPM, SPM, BPM, WAR
and DARKO projections, joining on `player_id` to PBPStats `entity_id` with no key mapping.

These are now computed in [`analysis/possession_impact`](../possession_impact/), which
owns every possession-derived metric. The team-grades builders still emit their own
plus-minus-based bench figures and scoring-context clutch table; the possession-based
versions live in that module and cover a shorter window, since the possession feed lags
this one.

Validation notes on the possession file: 221 of 221 on-court player ids match PBPStats
`entity_id`; league points per possession is 1.088 against 1.095 from the PBPStats totals;
about 3.5% of possessions carry an incomplete lineup and will need excluding.

## Upstream Data Caveats

`analysis/midseason_allstar_value_board/data/processed/allstar_value_board_2026.csv` is
damaged: it holds 192 rows for 98 players, including an embedded header row and
column-shifted duplicates where `allstar_value_score` contains band labels such as
`All-Star Case` rather than a number. Consumers here coerce the score to numeric, drop
non-numeric rows and keep one row per player, so the damage cannot multiply rows through a
join -- but the board itself should be regenerated at source.
