# Impact layer — RAPM and WAR, computed in-repo

`wnba_player_impact_2026.parquet` is frozen at **gp ≤ 29** while everything
else runs through **283 games / 2026-08-24**. This rebuilds the part of it that
can be rebuilt honestly, on the full season.

**What is here:** RAPM (genuine, canonical construction) and WAR (genuine, with
one stated convention). **What is deliberately absent:** BPM — §5 explains why
it cannot be built from a single season without becoming the proxy this layer
exists to avoid.

---

## 1. Why RAPM is calculable and BPM is not

RAPM needs one thing: every possession with both five-player lineups and the
points scored. The derived possession layer is exactly that — 45,945
possessions across 283 games. Nothing is approximated.

BPM is not a formula applied to a box score. It is a **regression of box-score
rates onto long-run RAPM**, and its published coefficients were fit on 14+ NBA
seasons. Every box input it needs is present here at 100% non-null; the
coefficients are the problem. Fitting that regression on this season gives:

| Target | In-sample R² | 5-fold CV R² |
|---|---:|---:|
| RAPM | 0.295 | **−0.091** |
| O-RAPM | 0.372 | −0.034 |
| D-RAPM | 0.151 | −0.185 |

A negative cross-validated R² means the fitted model predicts held-out players
*worse than guessing the mean*. The in-sample 0.295 is overfit. 169 players and
one noisy season cannot identify stable coefficients, so locally fitted "BPM"
would be noise wearing a metric's name — and transplanting the NBA set onto a
different scoring environment is the proxy we set out to avoid.

## 2. Method

Ridge regression over possessions. Each row carries +1 for the five offensive
players and +1 in a separate defensive block for the five defenders; the
response is points per 100 possessions. Possession weights come from the
calibration in `derive_possessions.py`, so everything sits on the pbpstats
scale.

The penalty is **chosen by 5-fold cross-validation, not assumed** — λ = 2000
minimises weighted out-of-sample MSE across the grid 500–32,000. Folds are
assigned **by game, not by row**: possessions within a game share lineups and
context, so a random row split leaks them across the boundary and the curve
stops describing out-of-game performance. `scripts/possession_impact/rapm.py`
already established that convention in this repo, so its `game_folds` helper is
reused rather than reimplemented.

Three details are easy to get wrong. Each is a place where a player's two
possession counts, or the two coefficient blocks, cannot be used
interchangeably:

**Centring.** Ridge fixes only the *sum* of the offensive and defensive blocks
against the intercept, not where league average sits within each. Left alone
that leaves an arbitrary constant in both — here +0.25 points per 100 — which
shifts every rating and silently inflates every WAR. Each block is centred to a
possession-weighted mean of zero, so league-average impact is exactly zero and
league-wide wins-above-average sums to zero.

**Scale.** Ridge deliberately shrinks. Aggregating the fitted coefficients back
to team level reproduces team rating ordering almost perfectly (r = 0.996 on
offence, 0.992 on defence) but spans only about **80%** of the real spread —
0.789 on offence and 0.803 on defence, estimated separately because the two
need not shrink alike. That is the bias half of the bias-variance trade, and it
matters the moment you convert to wins: a replacement level of −2.0 is
expressed in *real* points per 100, so applying it to shrunk coefficients would
compare two different scales. The table therefore carries both `rapm` (raw
estimator, for ranking) and `rapm_scaled` (each side divided by its own
attenuation, for magnitudes), and **WAR is computed from the scaled columns**.

Each side is aggregated through its own lineups and its own possession counts.
A team's offensive exposure is not its defensive exposure, so pushing the
combined coefficient through the offensive lineup alone would measure something
that is not the additive model's attenuation.

**Exposure.** A player's offensive and defensive possession counts differ —
substitutions land between possessions and periods end unevenly. The median gap
is small (about 1.5%) but it is not zero, so each coefficient is charged
against its own count: WAA is `o_rapm_scaled × off_poss + d_rapm_scaled ×
def_poss`, and the replacement rate, being a net quantity, is charged against
the mean of the two.

## 3. Validation

| Check | Result |
|---|---|
| Possession-weighted mean RAPM | **0.0000** (centred by construction) |
| League-wide WAA | **0.00** (sums to zero, as it must) |
| Team additivity, raw ridge (net) | r = 0.995, MAE 1.36, attenuation 0.78 |
| Team additivity, raw ridge (per side) | offence r = 0.996 / 0.789; defence r = 0.992 / 0.803 |
| Team additivity, calibrated (net) | r = 0.995, **MAE 0.44** |
| o_rapm + d_rapm = rapm | max residual 4.4e-16 |
| vs. the frozen sportsdataverse RAPM | r = 0.519 over different windows (n = 165, both pools 200+ poss) |

**Split-half reliability** — the honest error bar. Odd and even games fitted
separately, then correlated:

| Pool | n | Half-season r | Full-season reliability |
|---|---:|---:|---:|
| 200+ possessions | 179 | 0.414 | **0.586** |
| 500+ | 149 | 0.407 | 0.578 |
| 1000+ | 106 | 0.388 | **0.559** |

Around 0.56–0.59 is at the low end of normal for single-season RAPM and is the
reason practitioners use multi-year windows. **Read ranks and tiers, not
decimals.**

These numbers *fell* when the substitution-attribution bug was fixed (0.637 →
0.586 at 200+), which is worth stating rather than burying. Correcting the
lineups halved the cross-validated penalty (λ 4000 → 2000), and less shrinkage
always costs split-half stability. The validity checks moved the other way and
by more: attenuation rose from 0.65/0.66 to 0.79/0.80 and raw team-additivity
MAE fell from 2.14 to 1.36. Reliability measures how repeatable an estimate is;
attenuation and additivity measure whether it is aimed at the right thing. The
fix bought accuracy and paid for it in stability.

## 4. Wins

Two inputs, only one of which is a measurement.

**Points per win is estimated from this season**, not borrowed. Regressing team
win% on margin of victory across the 15 teams gives a slope of 0.0336 per point
at **R² = 0.920**, so points per marginal win is **29.72**. The fitted intercept
lands at **0.5003** — a team with zero margin is predicted to win half its
games, which is a good sign the specification is sound.

**Replacement level is a convention**, set to −2.0 points per 100 below
average. It cannot be measured off this data: ridge shrinkage pulls
low-possession players toward zero, so fringe players' RAPM is biased toward
average exactly where you would want to read replacement off. What *can* be
checked is whether the constant implies something sane — and it does. Since WAA
sums to zero, league-total WAR is purely a function of this constant, and −2.0
implies an all-replacement league would win **23.1%** of its games. Low twenties
is where that convention should land.

Sensitivity of the UCLA six's combined WAR to the choice:

| Replacement | −1.0 | −1.5 | **−2.0** | −2.5 | −3.0 |
|---|---:|---:|---:|---:|---:|
| Six combined WAR | −2.06 | −1.01 | **+0.05** | +1.11 | +2.17 |

The sign flips inside the plausible range. **Prefer WAA** — it needs no
convention at all — and quote WAR only with the replacement level stated.

## 5. Results

League leaders, 1000+ possessions:

| Player | Team | Poss | O | D | RAPM | Scaled | WAR |
|---|:--:|---:|---:|---:|---:|---:|---:|
| Jackie Young | LVA | 2,446 | +3.32 | +1.60 | **+4.92** | +6.19 | 6.76 |
| Natasha Howard | MIN | 2,280 | +2.77 | +1.82 | **+4.59** | +5.78 | 5.96 |
| A'ja Wilson | LVA | 2,298 | +3.91 | +0.64 | **+4.55** | +5.75 | 6.00 |
| Veronica Burton | GSV | 1,968 | +1.50 | +2.57 | **+4.07** | +5.10 | 4.69 |
| Kelsey Mitchell | IND | 2,633 | +3.87 | +0.14 | **+4.01** | +5.08 | 6.26 |
| Allisha Gray | ATL | 2,513 | +1.69 | +1.62 | **+3.32** | +4.17 | 5.21 |
| Jordin Canada | ATL | 2,344 | +2.66 | +0.60 | **+3.26** | +4.12 | 4.82 |
| Kaila Charles | GSV | 1,321 | +1.67 | +1.36 | **+3.03** | +3.81 | 2.59 |
| Olivia Miles | MIN | 2,278 | +2.12 | +0.82 | **+2.93** | +3.70 | 4.37 |
| Sydney Taylor | CHI | 1,312 | +1.37 | +1.06 | **+2.42** | +3.05 | 2.24 |

Two rookies make the top ten — Olivia Miles, who went second in the same
draft as the six, and Sydney Taylor.

### The UCLA six

| Player | Team | Poss | O | D | RAPM | Pctile | WAA | WAR |
|---|:--:|---:|---:|---:|---:|---:|---:|---:|
| Kiki Rice | TOR | 1,087 | +0.95 | −0.86 | **+0.09** | 63 | +0.05 | +0.78 |
| Lauren Betts | WAS | 1,195 | −2.46 | +1.95 | **−0.51** | 53 | −0.29 | +0.52 |
| Gabriela Jaquez | CHI | 1,238 | −1.77 | −0.05 | **−1.82** | 21 | −0.96 | −0.12 |
| Gianna Kneepkens | CON | 473 | −1.94 | +0.09 | **−1.86** | 20 | −0.37 | −0.06 |
| Charlisse Leger-Walker | CON | 1,671 | −1.51 | −0.73 | **−2.24** | 12 | −1.59 | −0.46 |
| Angela Dugalic | WAS | 610 | −2.64 | −1.30 | **−3.94** | 3 | −1.02 | −0.61 |

Percentile is against the 179 players with 200+ possessions.

Three readings worth carrying:

- **Betts splits hard by end** — defence **+1.95**, offence **−2.46**, the
  widest two-way split in the cohort. That is the spacing cost stated as
  impact: a centre with zero three-point attempts in 623 minutes, whose own
  finishing is elite but whose presence shrinks the floor. Her defensive
  coefficient is the best of the six by a wide margin.
- **Leger-Walker's workload compounds a negative rate.** Her RAPM is not the
  cohort's lowest — Dugalic's is — but she played the most possessions of the
  six by some distance, so she still carries the lowest WAA (−1.59). Volume
  magnifies sign.
- **Rice grades best of the six**, marginally above league average at the 63rd
  percentile, and is the only one of the six with a positive WAA. That is
  consistent with her +5.73 on/off swing, the only clearly positive one in the
  cohort.

Dugalic is the cohort's clear negative on both sides of the ball, at the 3rd
percentile, and that is the same finding the possession layer reaches
independently through the Betts + Dugalic pairing (−20.0 net together).

**These orderings changed when the substitution-attribution bug was fixed, and
the earlier version of this section said the opposite.** It previously had
Jaquez grading best of the six and Leger-Walker lowest; both are now wrong.
Correcting the lineups moved player RAPM by 0.66 on average (max 2.96) and
Spearman rank correlation between the two versions is 0.905 — close enough that
the league picture holds, loose enough that within-cohort orderings among six
players separated by fractions of a point did not. Six players inside a
1.5-point band was never a resolvable ordering at this reliability, which is
what caveat 1 says and what this reshuffle demonstrates.

## 6. Limits

1. **Reliability is 0.59.** Single-season RAPM. Ranks and tiers, not decimals.
2. **Two scales exist on purpose.** `rapm` for ordering, `rapm_scaled` for
   magnitudes and wins. Do not mix them in one chart.
3. **`off_poss` and `def_poss` are not interchangeable.** They differ by about
   1.5% at the median. `poss` is retained as an alias for `off_poss` for
   convenience, but wins are computed from both.
4. **WAR carries a convention.** State the replacement level or quote WAA.
5. **Two of 229 players have no crosswalk name.** They receive coefficients and
   are included in all league aggregates; only their label is missing.
6. **Attenuation is estimated from 15 team-seasons.** The 0.789 / 0.803
   factors are themselves small-sample estimates.
7. This does not replace the exact pbpstats on/off for single-player questions.
   RAPM answers a different question — impact adjusted for teammates and
   opponents — and the two disagreeing is information, not error.

## 7. Reproducing

```
python3 scripts/ucla_2026_draft_class/impact.py
```

Writes `impact_rapm_war_2026.csv` (229 players), `story_ucla_six_impact.csv`
(6), and `impact_manifest.json` carrying the CV curve, reliability, additivity,
points-per-win and replacement diagnostics. Runs in about a minute, most of it
the split-half refits.
