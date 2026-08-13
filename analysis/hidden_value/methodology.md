# Hidden Value Methodology

## Purpose

Two questions, deliberately kept apart because they are different bets:

1. **Underrated now** — who is contributing more than their situation explains?
2. **Trending up** — who is improving fast enough to matter in September?

Blending them into one ranking hides which claim is being made about a player, so the board
carries a `board_track` instead.

## The Role-Adjusted Residual

"Underrated" is meaningless without a baseline. The baseline here is what a player's
**situation** predicts: minutes, usage, start rate, share of team possessions played, and
team strength. Impact is regressed on those, and the residual is the part their situation
does not explain.

### Team strength belongs in the baseline

This is the design decision that makes the board work, and it was not the original plan.

The first build used role proxies alone and produced an **R² of 0.0096** — role explains
essentially nothing about RAPM, which is unsurprising once stated: RAPM is a
per-possession adjusted metric that deliberately does not reward volume. The residual came
out correlated **0.995** with impact itself, so "Underrated Now" was nothing but "high
RAPM" wearing a different label.

What actually predicts measured impact is the **team**. RAPM correlates +0.64 with team net
rating against +0.10 with minutes, because over half a season a shrunk RAPM still carries a
good deal of the team around a player. Adding team net rating to the baseline moved R² to
**0.4256** and had three effects worth stating:

| | Role proxies only | With team strength |
|---|---|---|
| R² | 0.0096 | **0.4256** |
| corr(residual, impact) | 0.995 | **0.762** |
| corr(residual, team net rating) | — | **0.005** |
| Teams in the top 25 | concentrated on MIN/GSV/NYL | **13 different teams** |

The board went from listing the best teams' rotations to surfacing players on ordinary
ones, which is the point of the exercise.

**The trade-off is real and worth knowing.** A player genuinely driving a good team is
partly penalised, because some of their contribution is absorbed by the team term. This
board answers "who is better than their situation suggests", not "who is best".

A mild ridge penalty is applied because the role proxies are strongly collinear — minutes,
starts and possession share all measure "how much the coach plays them" — and an
unpenalized fit would split that shared signal arbitrarily. The intercept is never shrunk.

Proxies named in config that are missing or constant are **reported** in the run manifest
under `proxies_dropped` rather than silently ignored: two of five vanished that way in the
first build.

## Trajectory

From the snapshot window panel, over the trailing windows: a possession-weighted
least-squares slope for production, efficiency, usage, possession share and on-court net
rating.

Every slope is **shrunk toward zero in proportion to how little data supports it**
(`slope × n / (n + k)`, default k = 6). Ten windows of WNBA basketball is not enough to read
a trend at face value, and un-shrunk trend-chasing is how watchlists like this go wrong.

Windows are weighted by possessions, so a 40-possession appearance does not move the trend
as much as a 90-possession one. The baseline block is excluded — it aggregates many games
into one row and would dominate any slope it appeared in.

`on_court_poss_share_slope` is called out separately as **role expansion**: a rising share
of team possessions tends to precede rising production rather than follow it.

The DARKO projected rating is folded in where available as an independent forward-looking
read.

## Regression Upside

The core signal is **shot making against shot quality**. A player generating good looks and
missing them is a buy; one converting mediocre looks at a high rate is a sell. Only players
above a shot-volume floor (default 120 FGA) are scored on it.

Free-throw percentage acts as a **prior on three-point talent**: it is a cleaner read on
touch and stabilises far sooner than three-point percentage. A good free-throw shooter
converting threes below what their touch implies has room; the gap is scored for players
with at least 40 three-point attempts.

## Playoff Fit

Playoff basketball is a shorter rotation and a slower half-court game, so the fit score
weights skills that survive that:

| Component | Weight | Why |
|---|---:|---|
| Self-creation (low assisted rate) | 0.25 | Playoff defences take the easy assisted looks away first |
| Rotation security (possession share) | 0.20 | A player who will not play is not actionable, however good |
| Foul drawing | 0.15 | The possession source that survives when everything tightens |
| Rim independence | 0.10 | Finishing without needing to be set up |
| Corner reliability | 0.10 | The most repeatable three |
| Shot diet | 0.10 | Rim and three over long twos |
| Ball security | 0.10 | Live-ball turnovers cost more in a slow game |

## Scoring And Conviction

Components are converted to percentiles so signals on different scales can be combined,
then weighted (config): role residual 0.35, trajectory 0.25, regression upside 0.20,
playoff fit 0.20, minus a volatility penalty of 0.10.

Conviction is `Strong` / `Moderate` / `Monitor` by score percentile, and **any player on a
low sample is downgraded one step**. A thin sample can top the board on noise, and the
label should say so rather than the reader having to check a column.

## Eligibility

Minimum 300 total possessions and 8 games. Players between 300 and 800 possessions are kept
but flagged `Low sample`. 176 of 226 players clear the floor, 151 of those are `Reliable`.

## Known Limitations

- **Impact is mostly RAPM, which lags.** It reflects games through 2026-07-22 while the
  player features run to 2026-08-11. On-court net rating stands in where RAPM is missing,
  on a cruder scale.
- Team strength in the baseline penalises genuine contributors on good teams, by design.
- Trajectory over ten windows is a weak signal even after shrinkage; treat the `Trending
  Up` track as a shortlist to watch, not a conclusion.
- Playoff-fit weights are a judgement about how playoff basketball differs, not an
  empirical fit to playoff outcomes.
- Start rate comes from opening-possession lineups, so an unusual opening five counts as a
  start.
- No injury or availability information beyond games played.
