# Team Identity Shift Methodology

## Purpose

Two questions, for every team:

1. **Has the way this team plays actually changed** since earlier in the season, or does it
   only look that way because a handful of games went differently?
2. **Did the change help or hurt**, and is the reason something that will hold up in the
   playoffs or something that is about to regress?

Both need a time dimension the PBPStats season totals do not publish, so this analysis is
built on the [snapshot window panel](../snapshot_window_panel/methodology.md).

## Periods

The default source is the shared per-game team layer, where **each window is one game**
(`periods.source: "game_layer"`). The recent/baseline split then lands exactly on the target game
count rather than on a snapshot boundary, and the permutation null below scrambles real games. The
snapshot window panel is a fallback (`periods.source: "window_panel"`, or automatic when the layer
is absent); everything below is identical either way — with multi-game snapshot windows the recent
block can exceed the target slightly, whereas per-game windows hit it exactly.

The recent period is the smallest trailing set of windows that reaches the target game
count (default 10). Windows are never split, so the block widens rather than cutting a
window in half. Everything earlier is the baseline period, which must contain at least
`min_baseline_games` (default 8) or the team is skipped.

Period rates are always recomputed from **summed window totals**, never averaged across
windows. Averaging would give a 60-possession window the same weight as a 90-possession
one. Reconstructed averages (shot quality) cannot be summed, so they are re-averaged
against the weight column the panel ships beside each one.

## The Style Vector

Identity is expressed as thirteen possession- or attempt-normalized rates, chosen because
they describe *how* a team plays rather than how well:

| Group | Dimensions |
|---|---|
| Shot diet | three-point attempt rate, rim share, midrange share, corner share of threes |
| Pressure | free-throw attempt rate, penalty possession share |
| Ball security | turnover rate, live-ball turnover rate |
| Second chances | offensive rebounds per 100, second-chance possession share |
| Ball movement | assist rate, assisted-points share |
| Tempo | pace |

### Scaling

Each dimension is scaled by the **cross-team standard deviation of the full-season rate**,
not by game-to-game variance. A movement of 1.0 therefore means "moved by one league
standard deviation of team-to-team difference" — the natural unit for a question about
identity. Game-to-game variance would be the wrong denominator: it is large enough that
every real change would look trivial.

`identity_shift_l1` is the sum of absolute scaled movements across dimensions.
`identity_shift_euclidean` is also reported.

**Mahalanobis distance is deliberately not used.** It is the textbook answer for correlated
dimensions, but with 15 teams and 13 dimensions the covariance matrix is not estimable, and
inverting a near-singular estimate would manufacture confidence that is not there.

## Is the Shift Real? The Permutation Null

A raw before/after difference always looks like something. With roughly two dozen windows
per team, most of it is week-to-week noise.

Each team's observed shift is therefore compared against **its own games in scrambled
order**. Window order is permuted 4,000 times; each window keeps its own totals, only its
position in the season changes. Periods are re-derived by the same games-from-the-end rule,
and the shift score is recomputed. The observed score's percentile in that distribution is
the evidence that the change is temporal rather than incidental.

This null is per team, so it automatically accounts for a team's own volatility and its
number of windows. A volatile team needs a larger move to clear the same bar.

| Percentile | Label |
|---|---|
| ≥ 0.95 | Significant |
| ≥ 0.80 | Moderate |
| below | Within noise |

**Calibration check.** Drawing pseudo-observed values from the null and scoring them
against an independent null gives a mean percentile of 0.503, a 4.9% rate at the 0.95
threshold, a 19.2% rate at the 0.80 threshold, and a flat decile histogram. The test is
calibrated, so the labels mean what they say.

`shift_vs_null_ratio` (observed ÷ null median) is the plain-language version: 1.0 means a
team moved exactly as much as reshuffling its own season would produce. Values below 1.0
indicate a team that is *more* stable than chance — a consistent identity, which is itself
worth knowing.

## Did It Help? The Offensive Decomposition

Offensive rating alone cannot answer this, because a team can score more simply by making
shots it was already taking. The change is split using an exact identity:

```
off_rating = 200 * (Q + M) * A + 100 * F
```

- **Q** — expected eFG% from shot location (PBPStats shot quality). What the shot diet is
  *worth*.
- **M** — shot-making residual, actual eFG% minus Q. Whether shots went in beyond that.
- **A** — field-goal attempts per possession. Driven by turnovers and offensive rebounding.
- **F** — free-throw points per possession.

Each factor's contribution uses the symmetric two-factor rule
`d(XY) = mean(X)*dY + mean(Y)*dX`, which reconciles to the total exactly instead of
stranding an interaction term. Components:

| Component | Reads as |
|---|---|
| `shot_quality_effect` | Design. The team changed which shots it takes. Tends to persist. |
| `shot_making_effect` | Conversion. The same shots fell more or less often. Tends to regress. |
| `shot_rate_effect` | Possession. More or fewer shots per trip. |
| `free_throw_effect` | Free-throw scoring rate. |

`shift_nature` names the largest component: **Design-led (structural)**, **Conversion-led
(cosmetic)**, or **Possession-led**. This is the single most useful field for judging
whether a hot stretch is a new team or a hot month.

The decomposition reconciles to within 3e-14 on the 2026 data. `decomposition_residual`
is published and should be inspected: the identity assumes
`points == 2*FG2M + 3*FG3M + FT points`, and any source inconsistency surfaces there rather
than being absorbed silently into a component.

The defensive side is reported as `def_rating_delta` only. PBPStats team totals describe a
team's own offense, so opponent shot-location detail is not available to decompose against.

## Strength of Schedule

Net rating measured against weaker opponents is inflated by roughly the amount those
opponents are weaker. If a team's recent opponents average `d` points per 100 worse than
its earlier ones, the observed change overstates the real one by `-d`, so:

```
opponent_adjusted_net_rating_delta = net_rating_delta + opponent_net_rating_delta
```

Opponents come from joining each window's covered game dates to the schedule; opponent
strength is that opponent's full-season net rating from the same panel.

**This adjustment changes conclusions.** On the 2026 data it flips several teams between
improving and declining, so `shift_direction` is taken from the adjusted figure wherever
schedule data exists. `shift_direction_basis` records which figure was used.

Note this is a first-order adjustment against season-long opponent strength, not a full
opponent-adjusted rating model, and it does not account for rest, travel or injuries.

## Known Limitations

- Opponent strength is the opponent's season net rating, which itself includes the games
  against this team.
- The baseline period is a single block; a team that changed twice reads as one net move.
- Defensive identity is thin — only rating, rebounding and steal/block/foul rates, with no
  opponent shot-location data.
- Multi-game windows cannot be attributed to individual opponents, so schedule context is
  computed at window granularity.
- `shift_nature` describes offense only.
- Style dimensions are unweighted in the L1 score; every dimension counts equally, which is
  a modelling choice rather than a fact about basketball.
