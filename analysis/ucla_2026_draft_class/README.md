# UCLA 2026 draft class — rookie-season EDA

Six players drafted out of UCLA in 2026 (a single-school record). This folder
holds the exploratory analysis and the filtered, design-ready data behind it.

| Player | Pick | Team | pbpstats id | ESPN id |
|---|---:|:--:|---:|---:|
| Lauren Betts | 4 | WAS | 1643427 | 5105737 |
| Gabriela Jaquez | 5 | CHI | 1643447 | 4858656 |
| Kiki Rice | 6 | TOR | 1643445 | 4565505 |
| Angela Dugalic | 9 | WAS | 1643455 | 4433411 |
| Gianna Kneepkens | 15 | CON | 1643429 | 4898898 |
| Charlisse Leger-Walker | 18 (R2) | CON | 1643449 | 4703609 |

## Read these

- **[`EDA_FINDINGS.md`](./EDA_FINDINGS.md)** — the full analysis: per-player
  reads, cohort patterns, team impact and role contribution, and a ranked list
  of what to dig into next. Uses every available source, including three that
  stop in mid-July.
- **[`EDA_FINDINGS_PBPSTATS_ONLY.md`](./EDA_FINDINGS_PBPSTATS_ONLY.md)** — a
  second pass built exclusively on the pbpstats game layer (274 games, through
  2026-08-21). States which first-pass claims do not survive the restriction,
  rebuilds two of them from full-season data, and resolves the Kiki Rice
  on/off contradiction: her return was a five-game minutes restriction, and
  and her per-possession rates collapse and recover with it. **Use this one for
  anything going into print.**
- **[`DERIVED_POSSESSIONS.md`](./DERIVED_POSSESSIONS.md)** — rebuilds the
  frozen possession layer for the full season from ESPN play-by-play, with the
  validation report and the duo findings it settles. Read this before quoting
  any lineup or pairing number.
- **[`METRIC_FRAMEWORK.md`](./METRIC_FRAMEWORK.md)** — which metrics to use,
  which to avoid and why, the two derivations that do the heavy lifting, and
  the data-coverage limits.

## Data bundle (`data/`)

Files prefixed `story_` are the tidy slices intended for the editorial build.
All are small enough to inline into an HTML artifact.

| File | Rows | Contents |
|---|---|---|
| `story_ucla_six_season_profile.csv` | 6 | Full season profile per player, every metric plus league and rookie percentiles/ranks |
| `story_metric_percentiles_long.csv` | 204 | Long/tidy `player × metric` — value, both percentiles, rookie rank, both pool medians, `lower_is_better` flag. Bind radars and bar charts to this |
| `story_ucla_six_game_logs.csv` | 181 | Per-game logs, trimmed to chart-relevant columns, with `game_no` for trend lines |
| `story_monthly_development.csv` | 24 | Monthly arcs — mpg, usage, pts/75, TS, ast/75, tov/75, foul/75, shot shares, on-court net |
| `story_rookie_pool_150min.csv` | 37 | Rookie reference pool, full metric set — for distribution and beeswarm plots |
| `story_league_pool_250min.csv` | 149 | League reference pool, same columns |
| `story_team_context.csv` | 15 | Team ratings, records and ranks; `has_ucla_rookie` flags the four employers |
| `story_manifest.json` | — | Pool sizes, thresholds, coverage dates, `lower_is_better` list |
| `story_rice_timeline.csv` | 36 | Every Toronto game in order with Rice's line, availability status and rest days |
| `story_rice_return_blocks_{player,team,onoff}.csv` | 3–4 | Pre-injury / out / return 1–5 / return 6–10 splits |
| `story_teammate_minute_correlations.csv` | 663 | Every rotation-teammate pair league-wide, minutes correlation and percentile |
| `story_opponent_adjusted_scoring.csv` | 6 | Schedule strength faced and opponent-adjusted scoring rate |
| `story_team_defense_strength.csv` | 15 | Team defensive rating and distance from league average |
| `derived_possessions_2026.parquet` | 45,643 | Full-season possession layer: both five-player lineups, points, calibration weight. Drop-in replacement for the frozen `wnba_possessions_2026.parquet` |
| `story_duo_splits_full_season.csv` | 24 | Every duo state (both on / one on / neither) with ORtg, DRtg, net |
| `story_derived_onoff_full_season.csv` | 6 | Possession-level on/off for the six |
| `story_rice_blocks_derived.csv` | 4 | Rice's return windows on the derived layer |
| `derived_vs_exact_onoff.csv` | 185 | Derived vs pbpstats-exact on/off, for error bars |

Supporting/intermediate: `on_off_all_players.csv` (exact full-season on/off for
all 227 players), `possession_on_off_splits.csv` (possession-level splits,
partial season), `rookie_class_2026_metrics.csv`, `season_metrics_with_percentiles.csv`.

**Percentile convention:** in `story_*` files, higher percentile always means
better — the `lower_is_better` metrics listed in the manifest are already
inverted.

## Notes for the editorial build

Charts the data is already shaped for, roughly in order of how much they carry:

1. **Shot quality vs shot-making scatter** — `shot_quality_avg` on x,
   `shot_making_over_sq` on y, the 149-player league pool as background, the
   six highlighted. The two axes correlate at only 0.15 league-wide, so the
   quadrants are meaningful: Betts top-left (bad looks, great conversion),
   Jaquez bottom-right (good looks, poor conversion).
2. **Role vs production dumbbell** — minutes-per-game percentile against
   points-per-75 percentile. Betts's gap is the visual thesis of the piece.
3. **Monthly small multiples** — six sparkline rows from
   `story_monthly_development.csv`. Betts's TS and foul rate move in opposite
   directions; Jaquez's and Dugalic's minutes fall off a cliff.
4. **On/off dumbbell** — on-net vs off-net from the season profile, with the
   league net-swing distribution behind it.
5. **Shot-diet stacked bars** — rim / short mid / long mid / corner 3 / above
   break 3, with the positional median as a reference rule.
6. **Toronto with/without Rice** — use the four-block series in §1 of
   `EDA_FINDINGS_PBPSTATS_ONLY.md` (pre-injury / out / return 1–5 / return
   6–10), not the three-block version in the first document. The five-game
   return ramp is the whole story and a chart that hides it misleads.
7. **Rice's return minutes** — a simple bar of her ten post-injury games
   (17.1, 23.0, 26.8, 22.9, 17.6 → 30.1, 31.4, 29.9, 24.5, 31.8) from
   `story_rice_timeline.csv`. The step between game 5 and game 6 back is
   visible without any annotation.

Three things to carry into the copy. The RAPM/BPM/WAR impact layer still stops
in **mid-July** while everything else runs through **2026-08-23** (281 games).
Rice (21 games) and Kneepkens (~230 minutes) are below any normal stability
threshold. And per §5 of `DERIVED_POSSESSIONS.md`, small-sample on/off
differentials move by several points per 100 on a handful of new games, while
minutes, shooting splits and shot diet reproduce across every vintage — prefer
the latter for anything stated as a fact.

Claims to leave out: all opponent shot-profile splits and all RAPM/BPM/WAR
figures, whose sources are still frozen in mid-July. The duo numbers are no
longer on that list — they were rebuilt for the full season, and the Betts +
Austin two-big angle died in the process (see `DERIVED_POSSESSIONS.md`). Treat
any duo gap under about 15 points per 100 as indistinguishable from noise.
