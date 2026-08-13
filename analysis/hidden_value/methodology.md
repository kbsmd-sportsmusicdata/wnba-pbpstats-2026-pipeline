# Hidden Value Methodology

## Purpose

The board answers one question: **who is contributing more than their situation explains?**

It was designed to answer a second — who is improving fast enough to matter in September —
but held-out testing found no trend signal capable of supporting that claim on this
season's data (see Trajectory below). Improvement is therefore sought through a *mechanism*
(shot quality running ahead of results) rather than through extrapolating a trend.

`board_track` names whichever signal carries a player's case, so a reader can see at a
glance whether the claim rests on the residual or on recent form.

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

## Trajectory, And Why It Carries Almost No Weight

From the snapshot window panel, over the trailing windows: a possession-weighted
least-squares slope for production, efficiency, usage, possession share and on-court net
rating.

**Held-out testing showed this signal does not forecast what comes next, so it carries a
weight of 0.05 rather than the 0.25 it was first given.**

The test: hold out each player's last four windows, fit the trend over the k windows
before them, and ask whether the trend improves a prediction of held-out performance over
simply knowing the player's current level. Matched sample, so every k is judged on the same
players. Predicting the held-out *level* rather than a before/after difference, which
avoids the mechanical regression-to-the-mean trap.

| Window length k | Incremental R² over level | Slope coefficient |
|---:|---:|---:|
| 8 | +0.024 | −1.04 |
| 10 | +0.030 | −1.39 |
| 12 | +0.050 | −2.41 |
| 15 | +0.074 | −3.80 |
| 18 | +0.044 | −3.83 |

The trend does carry information, but **the sign is inverted**: a rising production trend
predicts *worse* subsequent production once level is controlled for. This is mean
reversion, and lengthening the window measures it more sharply rather than fixing it —
which is why the window stays at 10. Ranking players on a rising trend would be selecting
players about to regress.

The other trajectory inputs fare no better against future production:

| Signal | Incremental R² | Sign |
|---|---:|---|
| Production slope | +0.023 | negative |
| Possession-share slope | +0.004 | negative, negligible |
| DARKO projection | +0.015 | negative |
| TS% slope | ~0.000 | no signal |

Trailing TS% is the starkest: over 15 windows it explains 0.003 of held-out efficiency. At
window granularity, efficiency trend is noise.

One claim did survive: **role expansion persists.** Possession-share slope predicts future
possession share with a positive coefficient (+1.82), though the gain is small (+0.011 on
an R² already at 0.772 from current share) and it predicts opportunity, not production.

Caveats on the evidence: 81–118 players, one season, one holdout design. Mean reversion at
this granularity is an expected effect rather than a surprise, so this confirms a known
pattern rather than discovering one. It is enough to say the component should not be ranked
on, not enough to invert it.

The slopes remain in the outputs as **descriptive context**, and the track is named
`Recent Form` rather than `Trending Up` for the same reason: the label must not imply a
forecast the data does not support.

### How the trend is computed

Every slope is still **shrunk toward zero in proportion to how little data supports it**
(`slope × n / (n + k)`, default k = 6). Ten windows of WNBA basketball is not enough to read
a trend at face value, and un-shrunk trend-chasing is how watchlists like this go wrong.

Windows are weighted by possessions, so a 40-possession appearance does not move the trend
as much as a 90-possession one. The baseline block is excluded — it aggregates many games
into one row and would dominate any slope it appeared in.

`on_court_poss_share_slope` is called out separately as **role expansion**. It is the one
trend that persists, but note what it does and does not do: it predicts a player's *future
opportunity*, not their future production. A growing role is worth knowing about; it is not
evidence that the player will produce more per possession.

The DARKO projected rating is folded in where available as an independent read. It did not
improve a forecast of held-out production in the testing above either, so it is weighted
alongside the other trend inputs rather than treated as authoritative.

## Regression Upside

This is where the board looks for improvement, and it carries 0.30 — up from 0.20 — because
it is the *correctly signed* version of the idea the trajectory component was reaching for.
Rather than extrapolating that a player who has been improving will keep improving, it
identifies a **mechanism**: the shots are already good, the results have not caught up yet.

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
then weighted (config): role residual 0.40, regression upside 0.30, playoff fit 0.25,
trajectory 0.05, minus a volatility penalty of 0.10.

**0.95 of the weight sits on signals measured at a player's current level**, and only 0.05
on the direction they have been moving. That split is the direct consequence of the
held-out testing above.

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
- Trajectory does not forecast future performance on this season's data and is weighted
  accordingly; treat `Recent Form` as description, never as a prediction.
- Playoff-fit weights are a judgement about how playoff basketball differs, not an
  empirical fit to playoff outcomes.
- Start rate comes from opening-possession lineups, so an unusual opening five counts as a
  start.
- No injury or availability information beyond games played.
