# Midseason All-Star Value Board Methodology

## Purpose

The All-Star Value Board ranks WNBA players by current-season value signals through a midseason editorial lens. It favors a balanced case: production, efficiency, creation, on-court impact, availability, and team context.

The score is not a fan ballot forecast, award model, or official All-Star selector. It is a structured way to explain which players have the strongest value cases and why.

## Candidate Pool

The default candidate thresholds are:

| Rule | Default |
|---|---:|
| Minimum minutes | 300 |
| Watchlist minimum minutes | 180 |
| Minimum games | 8 |
| Minimum share of team games | 0.45 |

Candidate tiers:

| Tier | Meaning |
|---|---|
| `Core Candidate` | Meets minutes, games, and team-game share thresholds |
| `Watchlist` | Has enough workload to monitor but falls short of full eligibility |
| `Ineligible` | Below minimum board workload thresholds |

The candidate pool and metric panel retain all tiers for diagnostics. The main board, top 10 summary, and social-card outputs filter to `eligible_flag == True`, so watchlist and ineligible rows do not enter the public All-Star ranking.

Eligibility workload comes from SportsDataverse player box scores:

- `box_minutes` is the sum of non-DNP box-score minutes.
- `box_games_played` counts games with recorded box-score minutes.
- `mpg` and `availability_rate` use `box_minutes` and `box_games_played`.
- `pbpstats_minutes` and `pbpstats_games_played` remain in diagnostic outputs but do not serve as an eligibility fallback.

## Score Components

All component inputs are converted to 0-100 percentile-style scores before weighting.

| Component | Default Weight | Signals |
|---|---:|---|
| Production | 0.25 | points, rebounds, assists, stocks, turnover discipline |
| Efficiency | 0.20 | TS%, eFG%, shot quality, shot-making above shot quality, free-throw rate |
| Creation | 0.15 | usage, assist volume, assist-to-turnover ratio, turnover discipline |
| Impact | 0.20 | on-court net rating proxy, team-relative net rating, defensive events |
| Availability | 0.10 | minutes, games played, availability rate |
| Team context | 0.10 | team win percentage and team net context |

The final `allstar_value_score` is the weighted average of these six component scores.

## Archetypes

Archetypes are rule-based labels used to make the board more legible for editorial and visual storytelling.

Initial archetypes:

| Archetype | Signal |
|---|---|
| `Primary Engine` | High usage plus strong playmaking |
| `Two-Way Star` | Top composite score plus defensive event value |
| `Efficient Interior Anchor` | Paint-heavy profile plus rebounding volume |
| `Shot-Making Wing` | Strong shot-making delta with perimeter volume |
| `High-Leverage Connector` | Balanced profile without one dominant signal |
| `Rim-Pressure Finisher` | Rim-heavy scoring profile |
| `Spacing Guard/Wing` | High three-point volume |
| `Defense/Glass Value` | Defense and rebounding lead the case |
| `Rising Sample Watch` | Watchlist workload with promising signals |

## Source Notes

- PBPStats features provide possession, efficiency, shot profile, on/off-style, and engineered percentile inputs.
- SportsDataverse files provide position, game-log, standings, and box-score context.
- Numeric standings fields are coerced before use because some SportsDataverse standings snapshots store them as object/string columns.
- SportsDataverse files are read from `data/raw/sportsdataverse/wnba_2026` first, then from `2026_scout_report` as a local fallback.
