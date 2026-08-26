# Metric framework — UCLA 2026 draft class

Scope: 2026 WNBA regular season through **2026-08-24** (283 team games in the
pbpstats spine, 15 teams, 37–39 games played per club).

## 1. Which source layer to trust for what

| Layer | Path | Coverage | Use it for |
|---|---|---|---|
| **pbpstats player-game** | `data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet` | **283 games, full season**, 229 players, 252 cols | Primary. Everything individual + on-court team rating |
| **pbpstats team-game** | `data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet` | 283 games, 566 rows | Team denominators, on/off arithmetic, team style |
| pbpstats season features | `data/pbpstats_wnba_2026/features_latest/2026/player_totals_features_latest.csv` | Full season, 311 cols | Pre-built shot-diet shares, shot-quality, percentiles, labels |
| Derived team-game | `data/processed/wnba_team_game/season=2026/team_game.parquet` | Full season | Four Factors, pace, rest days, back-to-backs, record-to-date |
| ESPN bio / draft | `analysis/role_fulfillment_matrix/data/live_inputs/player_core_2026.csv` | 232 players | **The only source of `college_id`, `draft_year`, `draft_round`, `draft_selection`, `experience_years`** |
| ESPN player box | `data/raw/sportsdataverse/wnba_2026/player_box_2026.parquet` | Full season | **`starter` flag and DNPs — pbpstats has neither** |
| Possessions | `data/raw/sportsdataverse/wnba_2026/wnba_possessions_2026.parquet` | ⚠ **202 of 283 games (through mid-July)** | Lineup co-presence, opponent shot profile on/off |
| Lineups | `data/raw/sportsdataverse/wnba_2026/wnba_lineups_2026.parquet` | ⚠ 195 of 283 games | Stint construction |
| Player impact | `data/raw/sportsdataverse/wnba_2026/wnba_player_impact_2026.parquet` | ⚠ **gp ≤ 29 (through mid-July)** | RAPM, WAR — secondary only |

**Identity crosswalk.** pbpstats `player_id` (e.g. `1643427`) and ESPN
`athlete_id` (e.g. `5105737`) are different ID spaces. Join through
`analysis/role_fulfillment_matrix/data/review/player_identity_crosswalk_2026.csv`.
UCLA is `college_id == 26` — verified against known alumni already in the
league (Canada, Billings, Burke, Onyenwere, Gardner).

## 2. The metrics worth building the story on

### Tier 1 — the ones that separate these six

| Metric | Definition | Why it earns its place |
|---|---|---|
| `pace_neutral_pts_75` | points ÷ on-court off. possessions × 75 | Removes both pace and minutes. These six play on four very different-tempo teams |
| `ts_pct` | pts ÷ (2 × (FGA + 0.44 FTA)) | Single best scoring-efficiency summary |
| `shot_quality_avg` | pbpstats expected-eFG from shot location/type | **The whole point of pbpstats.** Grades the shots a player *takes*, independent of whether they fell |
| `shot_making_over_sq` | `efg_pct − shot_quality_avg` | Separates *shot selection* from *shot-making*. Correlation between the two league-wide is only **0.15**, so they are genuinely independent axes |
| `net_swing` | on-court net rating − off-court net rating | Team impact. Derived exactly (see §3), full season |
| `off_fgrebound_pct` / `def_fgrebound_pct` | share of available rebounds captured while on floor | Opportunity-denominated. Immune to pace and to teammates' shot volume, unlike RPG |
| `foul_trouble_min_pct` | Σ `period{N}_fouls{N}_minutes` ÷ minutes | pbpstats-only. Directly measures minutes lost to foul risk — the single biggest playing-time constraint in this cohort |
| `usage` + `on_poss_share` | pbpstats usage; player off-poss ÷ team off-poss | Separates "how big is their role when on the floor" from "how much of the team do they touch" |

### Tier 2 — role and fit

`unassisted_pts_share` (self-creation vs play-finishing) · `at_rim_pct_assisted`
· `ast_pts_created_75` (assist_points, not assists — credits the value created)
· `ftr` and `fta_75` (rim pressure) · `rim_share` / `mid_share` / `three_share`
/ `corner3_share` (shot diet) · `rim_accuracy` and `three_accuracy` ·
`blocked_rate` (fg2a_blocked + fg3a_blocked ÷ FGA — a physicality proxy) ·
`second_chance_points_pct` and `penalty_points_pct` (which game states a player
scores in) · `recovered_blocks ÷ blocks` (blocks your team keeps) ·
`self_oreb_pct`.

### Tier 3 — impact

**Use the in-repo layer**, not the frozen parquet: `rapm`, `rapm_scaled`, `waa`
and `war` from `impact_rapm_war_2026.csv`, rebuilt on all 283 games from the
derived possessions. Read ranks and tiers — split-half reliability is 0.59.
Quote `waa` in preference to `war`, which carries a replacement convention. Use
`rapm` for ordering and `rapm_scaled` for magnitudes; they differ by the
0.789 / 0.803 offensive and defensive ridge attenuation and must not be mixed
in one chart. Compare `rapm` against any external RAPM, never `rapm_scaled`,
which is deliberately de-shrunk. See
[`IMPACT_LAYER.md`](./IMPACT_LAYER.md).

**BPM is not available and should not be improvised.** It is a regression of
box-score rates onto long-run RAPM; fitting it on one season cross-validates at
R² = −0.09, worse than predicting the mean, and the published coefficients are
NBA-derived.

**Do not use anything from `wnba_player_impact_2026.parquet`.** Beyond being
frozen at gp ≤ 29: `adj_rapm` has sd 4.66 against `rapm`'s 0.85, `obpm`/`dbpm`
are miscentered at −3.4 / +2.8, and `darko_filtered_skill` correlates with
`rapm` at exactly 1.000 — a duplicate column, not an independent estimate.

### Metrics deliberately *not* used

Raw PPG/RPG/APG (minutes-confounded across a cohort spanning 8→26 mpg), raw
plus/minus (four bad teams), and per-36 rates (pace-confounded across teams
ranging 74.9 to 82.2 possessions/48).

## 3. The two derivations that do the heavy lifting

**Exact full-season on/off.** pbpstats gives each player their team's rating
*while they are on the floor* (`on_off_rtg`, `on_def_rtg`) plus their on-court
possession counts. Team totals come from the team-game layer, so the off-court
side is arithmetic, not an estimate:

```
on_pts_for      = on_off_rtg / 100 × off_poss
off_court_pts   = team_points − on_pts_for
off_court_poss  = team_off_poss − off_poss
net_swing       = (on_ortg − on_drtg) − (off_ortg − off_drtg)
```

Validated: summing on-court points across a team's players and dividing by
five reproduces the team's game total exactly. This matters because it gives a
**full-season** on/off (283 games) where the possessions parquet would cap you
at 202. Implementation: `scripts/ucla_2026_draft_class/onoff.py`.

**Possession-weighted season rates.** Every rate is rebuilt from summed
game-log counting stats, never averaged across games. Rate columns that arrive
pre-computed per game (`usage`, `shot_quality_avg`, rebound percentages,
`on_off_rtg`) are re-aggregated weighted by their natural denominator —
off_poss, def_poss or FGA. Implementation:
`scripts/ucla_2026_draft_class/metrics.py`. Cross-checked against the existing
`features_latest` layer: `efg_pct` and `shotquality_pbp` agree to four decimals.

## 4. Reference pools

Two pools, both stated explicitly on every percentile so the editorial layer
never has to guess:

- **League pool** — 149 players with 250+ minutes.
- **Rookie pool** — 37 rookies (`experience_years == 0`) with 150+ minutes,
  out of a 70-player rookie population. Note this pool includes undrafted and
  international first-year players (Juskaite, Conde, Astier, Taylor,
  Brochant), who occupy five of the rookie class's top twelve minute totals.
  A draftee-only pool is a different — and smaller — comparison.

`lower_is_better` metrics (`tov_75`, `foul_75`, `blocked_rate`, `mid_share`,
`drtg_swing`) have their percentiles inverted in the export so **higher
percentile always means better** in the story data.

## 5. Known data limits to state in the piece

1. The lineup parquet stops in mid-July. The possession layer no longer does
   (`DERIVED_POSSESSIONS.md`) and neither does impact (`IMPACT_LAYER.md`);
   both are rebuilt for the full season. Only stint-level construction still
   depends on a frozen source.
2. `wnba_stats_standings_2026.parquet` is stale (~27 games/team). Recompute
   standings from the team-game layer.
3. Kiki Rice has 21 games; Gianna Kneepkens has roughly 230 minutes. Neither clears a
   normal stability threshold for on/off or shooting splits.
4. No player-tracking, matchup, or defensive-assignment data exists in this
   repo, so all defensive claims are on/off and box-derived proxies.
