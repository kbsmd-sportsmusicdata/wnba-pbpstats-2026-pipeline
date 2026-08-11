# Snapshot Window Panel Methodology

## Purpose

The PBPStats endpoints publish season-to-date totals only. A row fetched today says what a
team or player has done across the whole season, not what they did last week. That makes
the feed unusable on its own for anything time-varying: trend, form, identity shift,
trajectory, or breakout detection.

The repository has been snapshotting those totals daily since 2026-06-02 into
`data/pbpstats_wnba_2026/features_master/`. Differencing consecutive snapshots for a single
entity recovers what happened between them. This module turns that archive into a panel of
game windows — one row per entity per window — across the full ~250-column PBPStats
feature set, including the shot-zone, second-chance and penalty detail that exists nowhere
else at sub-season grain.

## Window Construction

For each entity, snapshots are sorted by `_featured_at_utc` and differenced. A window is
kept when `games_played` increased, so windows correspond to real games rather than to
pulls where nothing happened.

The first snapshot in the archive is emitted as **window 0**, the baseline block. It holds
the cumulative totals for every game played before snapshotting began (roughly the first
seven to nine games of the 2026 season). Without it the panel would silently drop the start
of the season; with it, window totals sum exactly to the season totals.

Duplicate rows for the same entity and instant are resolved by keeping the later row.

## Column Handling

| Class | Treatment |
|---|---|
| Additive counting stats (`points`, `off_poss`, `at_rim_fga`) | Differenced directly |
| Signed additive stats (`plus_minus`) | Differenced, but exempt from monotonicity checks |
| Ratios and rates (`efg_pct`, `at_rim_frequency`, `usage`) | Never differenced |
| Cumulative averages with a known weight | Reconstructed (below) |
| Labels, percentiles, identifiers | Carried or dropped |

Classification is pattern-based, in `panel.is_additive_column`.

### Weighted-Average Reconstruction

A cumulative average cannot be differenced, but it can be re-expressed as an additive
quantity when its weight is available:

```
window_average = (avg_t * w_t - avg_{t-1} * w_{t-1}) / (w_t - w_{t-1})
```

This recovers per-window values for metrics that would otherwise be locked at season grain.
Configured pairs:

| Column | Weight | Notes |
|---|---|---|
| `shotquality_pbp_avg` | Total FGA | Expected points per shot — the input to the shot-quality vs shot-making split |
| `usage` | On-court offensive possessions | Player only |
| `on_off_rtg` | On-court offensive possessions | Player only |
| `on_def_rtg` | On-court defensive possessions | Player only |
| `off_fgrebound_pct` | Own missed FGA | **Approximate.** Missed field goals stand in for the OREB + opponent DREB denominator |

`off_fgrebound_pct` is the only approximation; every other reconstruction is exact. Each
reconstructed column ships alongside a `<column>_weight` column so downstream consumers can
weight or filter on sample.

## Data Integrity

A live feed restates itself. Three failure modes are handled, and every intervention is
logged to `window_panel_qa_2026.csv`.

### 1. Corrupt snapshots (quarantine)

A cumulative total must lie between its neighbours in time. When a large share of additive
columns break that envelope on the same snapshot across most entities, the pull itself is
damaged rather than any single stat.

The 2026 archive has exactly one such snapshot, **2026-06-03T18:58:03Z**, where a column
shift moved values into adjacent fields — `penalty_points_excluding_take_fouls` held the
value belonging to `first_chance_points`, and so on. Column-level repair is the wrong remedy
there, because a shifted row leaves fields holding plausible-looking numbers that belong to
a different stat.

The whole snapshot is dropped and the surrounding windows bridge across it, so **no games
are lost**. Snapshots are removed one at a time, worst first, and the archive is re-screened
after each removal: a corrupt snapshot also sits inside its neighbours' envelopes and drags
them out of range, so a single pass would over-quarantine.

The threshold is a *share* of columns (default 2%), so it scales with the width of the
archive. Measured separation on the 2026 data is large — the corrupt snapshot scores 0.037
(team) and 0.076 (player) against a median of 0.000 and a next-worst of 0.005.

### 2. League-wide restatements

On **2026-08-07** the source re-based `seconds_played` league-wide by roughly 3.4x and
cleared a backlog of negative values. Before that date the column was simply wrong: 2,261
player rows carried negative minutes and the league total was about a third of what 15 teams
playing 200 minutes a game implies.

Rather than hard-coding the date, the engine flags a column whose per-game delta exceeds a
multiple of the entity's own median for a majority of entities on the same snapshot. That
combination is a restatement; a single team having a huge game is not. Affected
column/window pairs are set to null, leaving the rest of the row intact.

### 3. Downward revisions

Any individual negative delta on a non-signed additive column means the source revised a
cumulative total downward, so the window value is not a real observation. It is nulled and
reported.

**Consequence for analysis: do not use minutes as a denominator.** `minutes_in_window` and
`minutes_per_game` are emitted, but roughly 27% of player windows carry null minutes and
values either side of 2026-08-07 are not comparable. Every rate in this module uses
possessions or attempts instead.

## Game-Date Attribution

The daily pull runs mid-morning UTC, so a snapshot stamped date D reflects games played
through D-1 in the league's local calendar. A window from snapshot S to snapshot E therefore
covers game dates `[S_date, E_date)`, exposed as `covered_game_date_start` and
`covered_game_date_end` (both inclusive) for joining to schedule, opponent and standings
data.

This attribution is validated, not assumed: all **297** single-game team windows in the 2026
archive match the independent ESPN box scores exactly on both team and opponent points.

## Derived Metrics

All rates are computed from window totals, never by differencing a cumulative rate.

**Team** — offensive/defensive/net rating per 100 possessions, pace, eFG%, TS%, shot-zone
shares (rim, short mid, long mid, corner three, above-break three), three-point and
free-throw attempt rates, turnover and live-ball turnover rate, assist rate, assisted-points
share, rebounding per 100 possessions, second-chance and penalty possession shares, and
`shot_making_over_shotquality` (window eFG% minus window expected eFG%).

**Player** — per-75-possession production (points, rebounds, assists, turnovers, steals,
blocks, free-throw attempts, field-goal attempts), shooting splits, shot-diet shares,
assist-to-turnover, reconstructed usage and on/off ratings, and on-court net rating.
Possession denominators use `total_poss`, matching the convention already used by the
All-Star Value Board.

### On-Court Possession Share

`on_court_poss_share` is each player's share of team possessions played in the window — the
leading indicator for role change, since a rising share precedes rising production.

Player rows are only appended when their totals change, so a player who sat out can have a
window spanning several of their team's windows, and boundaries cannot be joined directly.
The team side is instead aggregated over every team window contained in the player's
game-date range, and kept only when those team windows cover the range exactly end to end.
Partial coverage is left null rather than approximated, which is why coverage is 84.6%
rather than 100%.

Validation: within a fully covered team window, player shares sum to **5.000** at the median
and across the interquartile range — the arithmetic identity of five players on the floor.

## Verification Summary

| Check | Result |
|---|---|
| Window totals vs. season cumulative totals | Exact for all 15 teams, zero gap on every column |
| Single-game windows vs. ESPN box scores | 297 / 297 exact on team and opponent points |
| Player possession shares per team window | Median 5.000, IQR 5.000–5.000 |
| Unit tests | 26 covering differencing, restatements, quarantine, reconstruction, derived metrics |

## Known Limitations

- Windows spanning multiple games cannot be split further; roughly 20% of team windows cover
  more than one game, and opponent-level attribution for those requires the schedule join.
- `off_fgrebound_pct` reconstruction is approximate (see above).
- The baseline block aggregates the pre-archive games into a single row, so no sub-window
  detail exists before 2026-06-02.
- Minutes are unusable as a denominator; see Data Integrity.
- The panel inherits any error the source itself never restated.
