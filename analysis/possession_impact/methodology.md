# Possession Impact Methodology

## Purpose

Three metrics that all need to know **who was on the floor**, computed from the
possession-level feed: RAPM, bench net rating and clutch net rating. Each was previously
marked unavailable in the team-grades methodology for want of validated possession/stint
data.

## Coverage And Its Lag

The possession feed runs behind the rest of the pipeline. At the time of writing it covers
**195 games through 2026-07-22**, while the PBPStats snapshot panel reaches 2026-08-11 and
the ESPN box scores reach 2026-08-01.

That lag is published rather than hidden. `coverage_through` appears on **every row of
every output**, not just in the manifest, so the date travels with the file if a CSV is
opened on its own. The manifest also records `coverage_from` and `coverage_games`.

The feed carries game ids but no dates, so the window is dated by joining to the WNBA game
logs, which share the same id space.

## Possession Filtering

Two exclusions, both reported in the manifest:

| Exclusion | 2026 count |
|---|---:|
| Rows the feed does not count as a possession | 70 |
| Rows with any of the ten on-court slots missing | 1,121 |
| **Usable** | **31,074** of 32,265 (96.3%) |

Dropping incomplete lineups removes 7 games entirely, which is why coverage is 195 games
rather than the 202 in the raw file.

## RAPM

Each possession is one observation. The response is points per 100 possessions; the
predictors are the ten players on the floor.

```
points_per_100 = intercept + home + Σ(offensive players) − Σ(defensive players)
```

Offensive slots take +1 and defensive slots −1, so a larger coefficient means better on
both sides: it adds points when attacking and subtracts them when defending. `rapm` is the
sum of the offensive and defensive coefficients.

### Why ridge, and how the penalty is chosen

WNBA rotations are short, so teammates appear together constantly and an unpenalized fit
would be wildly collinear. The ridge penalty pulls every player toward league average.

How hard it pulls is **cross-validated, not assumed**. Alpha is chosen from a grid by
5-fold cross-validation, and folds are assigned **by game** so possessions from one game
never straddle a split — possessions within a game share lineups and context, and splitting
them at random would leak information into the held-out set. The chosen value on the 2026
data is 4,000, interior to the grid rather than at a boundary, so the grid is not binding.

The intercept and home-court terms are nuisance parameters and are estimated **without**
shrinkage. That leaves the system singular when a nuisance column is degenerate — which
happens for real if the play-by-play is unavailable and the home column is constant — so
the solver falls back to a minimum-norm least-squares solution rather than aborting.

### Home court

Taken from the WNBA play-by-play `location` field, which covers every game in the
possession feed and shares its game and team ids. The ESPN schedule is not used: it is a
different id space. Estimated home-court advantage on the 2026 data is **+2.55 points per
100 possessions**.

### Sample thresholds

Players below `min_possessions_reported` (100) are dropped; those below
`min_possessions_reliable` (500) are kept but flagged `Low sample`. Both bounds are config,
and possession counts ship alongside every estimate so a reader can apply their own.

## Bench Net Rating

Starters are the five on the floor at each team's opening possession, derived from the
possession feed itself. Cross-checked against the separate game-lineups feed: the two agree
on **all 195 games** where both exist.

Three slices per team, each points per 100 scored minus allowed:

| Slice | Definition |
|---|---|
| `starters_only` | No non-starters on the floor for that team |
| `any_bench` | At least one non-starter |
| `bench_heavy` | At least `bench_heavy_threshold` (default 3) non-starters |

`bench_dropoff` is `starters_only_net_rating − any_bench_net_rating`: how much a team falls
off when it goes to its bench. That is the number that matters for playoff rotations, which
shorten.

**Read the starters-only figures with care.** Starting fives play together less than the
slice names suggest — between 336 and 730 offensive possessions per team in 2026 — so those
ratings are the noisiest numbers in the file. The possession counts are published beside
every rating for exactly that reason.

## Clutch Net Rating

A possession is clutch when it starts late in a close game: period ≥ 4, no more than 300
seconds remaining, and an absolute score margin at or below 5. All three are config.

The margin is taken **before** the possession, reconstructed by accumulating points in
possession order and lagging by one. Using the margin after would let scoring on a
possession be what qualifies it as clutch.

## External Check

`rapm` here is compared against the pre-computed `wnba_player_impact` feed and the
correlation recorded in the manifest. This is a sanity check, not a target: that feed's
`rapm` column tracks `darko_filtered_skill` almost exactly (r = 0.999999), so it is a
different estimator. Agreement on the 2026 data is **r = 0.87**, high enough to be
reassuring and short of the identity that would suggest the two are the same calculation.

## Verification

| Check | Result |
|---|---|
| Cross-validation curve | Clean minimum at alpha 4,000, interior to the grid |
| Model calibration | Intercept + half home advantage = 108.69 vs 108.91 actual league points per 100 |
| Team aggregation | Possession-weighted team RAPM correlates **0.982** with team net rating |
| External comparison | r = 0.87 against the DARKO-derived published estimate |
| Starters derivation | Agrees with the independent lineups feed on 195 of 195 games |
| Unit tests | 26, including a synthetic league where a planted star must rank first |

## Known Limitations

- **The lag is the main one.** These metrics are roughly three weeks behind the snapshot
  panel and will stay so until the upstream feed catches up.
- RAPM over a half-season is heavily shrunk. Values are small by construction, and rank
  order is more trustworthy than magnitude.
- Bench definitions rest on opening-possession starters, so a late scratch or an unusual
  opening lineup is treated as the starting five for that game.
- Clutch samples are small — 55 to 188 possessions per team — and should be read as
  descriptive rather than predictive.
- No score-state or garbage-time weighting is applied to RAPM beyond the possession filter.
- The seven games with incomplete lineup data are excluded entirely rather than partially.
