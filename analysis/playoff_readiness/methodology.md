# Playoff Readiness Methodology

## Two Questions, Not One

**Who gets in, and where do they seed?** A Monte Carlo over the 113 unplayed games.

**Will what they do well survive a playoff series?** A metric set, split by where a team
sits, because the question is genuinely different at the two ends of the table.

The first has a right answer that the season will reveal. The second does not yet, and the
method is built to keep the two apart rather than blend them into one number.

## Making The Season Add Up

Everything rests on knowing exactly which games have been played and which have not. Three
things in the ESPN schedule feed need handling and none of them announce themselves:

| Issue | Rows | Handling |
|---|---:|---|
| All-Star game | 1 | Dropped: neither team is a franchise |
| Commissioner's Cup championship | 1 | Dropped: `type_abbreviation == "CC"`, and it does not count in the standings |
| Postponement shell | 1 | Dropped: the makeup was played on 20 July under a new game id |

Cup **group** games are ordinary fixtures and do count, so the filter is the game-type flag
rather than the `notes_type == "event"` marker that also tags them.

After cleaning: **217 played, 113 remaining, 44 games for every one of the fifteen teams**.
That equality is checked on every run and a failure is **fatal**, not a warning. A schedule
that does not balance produces odds that look entirely reasonable and are wrong.

A postponed game that has *not* been made up is a different case, and dropping it would
lose a real fixture. The rule is therefore conditional: a postponement is restored as
unplayed when both teams would otherwise come up short of the season's game count.

Standings are derived from this reconciled game log rather than read from a standings feed.
The WNBA Stats standings file in this repo trails the schedule by roughly sixteen games,
and a forecast that disagrees with its own game log is not worth publishing.

## The Rating Model

One observation per completed game:

```
margin = rating(home) - rating(away) + home_advantage + error
```

fitted by ridge-penalised least squares. Every row sums to zero across the team columns, so
ratings are identified only up to a common shift; the ridge penalty resolves that by
selecting the minimum-norm solution, which means **ratings are centred on the league by
construction** and read directly as points per game above average. Home advantage is a
league constant and is never shrunk.

Current fit: **home advantage 1.29 points, residual SD 10.59 points**, alpha 2.0 chosen by
five-fold cross-validation on held-out margins.

### Two parameters set by backtest, not by taste

Both were swept over five expanding-window chronological cutoffs, scoring held-out games.

**Recency weighting makes it worse.** This was a surprise, and the parameter is in the
config at zero as a result:

| Half-life (days) | Held-out log loss |
|---:|---:|
| **none** | **0.5773** |
| 20 | 0.6005 |
| 30 | 0.5911 |
| 45 | 0.5856 |
| 60 | 0.5831 |
| 90 | 0.5809 |
| 150 | 0.5793 |

Every weighting scheme tested is worse than none, and the loss shrinks monotonically as the
weighting weakens. Twenty-nine games is not enough data to spend any of it down-weighting
the early part of the season. This is the same lesson the hidden-value board learned about
trend signals, arriving from a different direction.

**Blowouts are capped at 20 points.**

| Margin cap | Held-out log loss |
|---:|---:|
| 12 | 0.5812 |
| 15 | 0.5782 |
| **20** | **0.5756** |
| 25 | 0.5758 |
| 30 | 0.5773 |
| none | 0.5781 |

### The model is scored against baselines every run

The chronological split is the only split that matches how the model is used. Both
baselines are honest ones: "the home team wins" at the training-slice base rate, and a
logistic fit on the two teams' win-percentage gap.

| | Log loss | Brier |
|---|---:|---:|
| **Rating model** | **0.5842** | **0.1966** |
| Win-percentage baseline | 0.5991 | 0.2042 |
| Home-field baseline | 0.6949 | 0.2509 |

151 training games, 66 held out, accuracy 0.697, margin RMSE 13.02. The margin over the
record-only baseline is real but **thin** — about 0.015 of log loss. Point differential
carries more information than win-loss, and not a great deal more. If that gap ever closes,
it will be visible in the manifest rather than assumed away.

## Simulating The Rest

Each of the 113 unplayed games is simulated as a margin drawn around the model's
expectation, and the resulting records are seeded through the tiebreak ladder.

### Ratings are redrawn every simulation

This is the choice that most affects the published numbers, and it is not the default one.
Rather than fixing ratings at the point estimate, each simulated season draws a full rating
vector from the fit's posterior — currently about **1.7 points of standard deviation per
team**, which is what twenty-nine games buys against a residual SD of 10.6. The draw goes
through an eigenvalue decomposition rather than a Cholesky factorisation, because the
covariance is near-singular along exactly the common-shift direction the ridge pinned down.

Fixing the ratings instead makes the model more confident at both ends:

| Team | Posterior draw | Point estimate |
|---|---:|---:|
| WAS | 0.916 | 0.947 |
| NYL | 0.989 | 0.997 |
| CHI | 0.036 | 0.023 |
| PHX | 0.034 | 0.022 |
| LAS | 0.015 | 0.007 |
| PDX | 0.010 | 0.005 |

The long shots roughly **double**. Uncertainty about how good a team *is* outweighs
uncertainty about any single game once a race is close, and ignoring it is the standard way
a model of this kind ends up announcing 95% when it means something nearer 90%.

### Tiebreaks

The league's published ladder is head-to-head, then winning percentage within one's own
conference, then splits against playoff-eligible teams, then point differential. This
implements:

1. **Head-to-head** against exactly the teams a team is tied with — the rule for two-team
   ties and the natural reading for larger ones.
2. **Conference winning percentage.**
3. **Point differential.**
4. A seeded coin flip, which is what actually happens and keeps the result from depending
   on alphabetical order.

The playoff-eligible splits are skipped because they are circular to evaluate inside a
simulation: eligibility is the thing being decided.

The whole ladder runs vectorised across all simulations at once through a single
`np.lexsort`, which is why 20,000 seasons take under two seconds.

### Bracket

Eight teams seeded league-wide, as the WNBA has bracketed since 2016: 1v8, 2v7, 3v6, 4v5,
higher surviving seed into the higher half. Series lengths and home patterns come from
config — first round best-of-three, semi-finals best-of-five, finals best-of-seven — because
the league has changed its formats twice in five years. Each series is resolved by computing
the higher seed's series win probability with a short dynamic program over the running
score, then drawing once, rather than simulating individual games; same distribution, less
noise.

Two identities are checked on every run and asserted in CI: playoff probabilities sum to 8,
title probabilities sum to 1.

### Seed leverage

Every simulation records the outcome of every remaining game, so the swing a single game
creates is the difference between two conditional means **within one simulation set**:

```
leverage = P(makes playoffs | this team wins) - P(makes playoffs | this team loses)
```

Exact for the set, and about a hundred times cheaper than re-running the season twice per
game. Reported for both the top-eight cut and the top-four line.

### Clinching is arithmetic, not simulated

A probability of 1.0000 over twenty thousand runs is not the claim "cannot be caught", and
conflating them is how a model eliminates a team that is still alive. `clinched_playoffs`
and `eliminated` are counting arguments over maximum and minimum possible wins. They ignore
that remaining games are shared between teams, so they are conservative — they will confirm
a clinch slightly later than the league does, never earlier. The simulation's view is
reported separately as `status` (`Effectively in`, `Comfortable`, `Bubble`, `Long shot`,
`Effectively out`).

## Readiness

### Three lenses

Set by odds rather than by assumption, because in 2026 the interesting race is not the one
this analysis was expected to find. Eight teams are above .500 and the ninth is five games
back with fifteen to play; the live contest is the **top-four line**, not the cut.

| Lens | Rule | 2026 |
|---|---|---|
| Top seed | P(top 4) ≥ 0.25 | MIN, GSV, LVA, ATL, IND, DAL |
| Bubble | otherwise, P(playoffs) ≥ 0.005 | NYL, WAS, CHI, PHX, PDX, LAS |
| Out of contention | P(playoffs) < 0.005 | TOR, CON, SEA |

### There is no fitted composite

The playoffs have not happened, so there is nothing to fit weights against. Inventing them
would dress judgement up as evidence — the failure mode this pipeline has already run into
once, on the hidden-value board's trajectory component. `readiness_index` is a **plain
equal-weight average of percentile-scored components within a lens**, published as a
convenient ordering and labelled as one. The components are the deliverable; the index is a
sort key.

### Top-seed components

| Component | Source | Why |
|---|---|---|
| `set_net_rating` | possessions | Half-court efficiency, the part a series does not take away |
| `quality_gap` | game log + ratings | Performance against the field they will actually meet |
| `bench_dropoff` | possession impact | How much a shorter rotation is worth |
| `rotation_concentration` | player box | How close the current rotation already is to a playoff one |
| `clutch_net_rating_shrunk` | possession impact | The last five minutes, shrunk to its sample |
| `margin_sd` (inverted) | game log | Variance exposure; a wide spread is a short-series risk |

### Bubble components

`p_playoffs`, `remaining_difficulty` (inverted), `remaining_home_share`, `form_delta`, and
`set_net_rating`.

### Half-court, and what the proxy actually is

The possession feed carries a `possession_start_type`. Possessions beginning after a made
basket, a dead ball or a timeout start against a defence that is **already set**; the other
two starts — a defensive rebound or a live-ball turnover — are where transition lives.

Possession duration would be the better split, but the feed's start and end clock values are
identical for a large share of possessions, so a duration-based early-clock filter is not
available here. This is a proxy and is described as one.

It separates teams that the overall net rating does not:

| Team | Overall net | Set-defence net | Early-offence net | Gap |
|---|---:|---:|---:|---:|
| MIN | +11.6 | **+14.7** | +6.5 | −8.2 |
| GSV | +7.7 | **+9.4** | +5.1 | −4.3 |
| ATL | +5.0 | **+2.1** | +8.7 | **+6.7** |
| WAS | −3.3 | **+0.4** | −9.1 | −9.5 |

Atlanta's edge sits in the half of the game a playoff series suppresses first. Washington's
sits in the half that survives. Neither is visible in their overall numbers.

### `quality_gap` is a residual, not a schedule split

The obvious version — margin against the playoff field minus overall margin — is negative
for **all fifteen teams** by construction, because the playoff field is the strong half of
the league. It measures schedule, not quality, and the first build of this board published
it before the sign pattern gave it away.

The version here is the residual one: actual margin minus the margin the **rating model
expected**, over games against the playoff field only. Because a fitted team's residuals
sum to roughly zero across its full schedule, a positive value means a team saves its better
performances for the games that resemble a playoff series — the interaction an additive
rating model cannot express, which is exactly the part worth reporting separately. It now
runs from −7.6 to +1.9 and centres near zero.

### Clutch is shrunk

Clutch net rating comes off 110 to 370 possessions a team and swings across a fifty-point
range. Left raw it would dominate an equal-weight average. It is shrunk toward zero as
`rating × n / (n + 250)`, the same shrinkage form the hidden-value trajectories use, and both
the raw and shrunk values are published.

### Rotation: two metrics, one caveat

`rotation_concentration` — the share of the last ten games' minutes going to a team's top
seven — is clean and unconfounded. It runs from 0.767 (GSV, ten players over ten minutes a
night) to 0.889 (ATL, six).

`bench_dropoff` carries a real caveat that is worth stating plainly: starters-only
possessions cluster at the openings of periods, when the *opposing* starters are also on the
floor, so the split is partly a statement about which units a lineup faced rather than how
good it is. Five teams show negative dropoffs, which is more likely an artefact of that than
five benches genuinely outplaying five starting fives. Both metrics are reported and neither
settles the rotation question alone.

## Known Limitations

- **The rating model has no injury, rest or availability input.** A team that loses a
  starter tomorrow will carry today's rating until results move it.
- **The mid-September break is not modelled.** The schedule pauses between 30 August and 14
  September for the World Cup; games either side are treated identically, and returning
  national-team players are not accounted for.
- **The margin over a win-percentage baseline is thin** — 0.015 of log loss on 66 held-out
  games. This is a competent model, not a strong one, and the odds should be read with that
  in mind.
- **Readiness weights are equal by declaration**, not fitted. They will not be fitted until
  there are playoff outcomes to fit them against.
- **The half-court split is a start-type proxy**, not tracking data, and it lags: it reflects
  games through 22 July while the odds run to 1 August.
- Tiebreaks skip the playoff-eligibility rungs of the league's ladder.
- `rotation_concentration` counts minutes, not availability; a player injured last week still
  appears in the window that includes them.
