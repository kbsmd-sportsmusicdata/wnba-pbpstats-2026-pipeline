# Impact layer — RAPM and WAR, computed in-repo

`wnba_player_impact_2026.parquet` is frozen at **gp ≤ 29** while everything
else runs through **281 games / 2026-08-23**. This rebuilds the part of it that
can be rebuilt honestly, on the full season.

**What is here:** RAPM (genuine, canonical construction) and WAR (genuine, with
one stated convention). **What is deliberately absent:** BPM — §5 explains why
it cannot be built from a single season without becoming the proxy this layer
exists to avoid.

---

## 1. Why RAPM is calculable and BPM is not

RAPM needs one thing: every possession with both five-player lineups and the
points scored. The derived possession layer is exactly that — 45,643
possessions across 281 games. Nothing is approximated.

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

The penalty is **chosen by 5-fold cross-validation, not assumed** — λ = 4000
minimises weighted out-of-sample MSE across the grid 500–32,000.

Two details are easy to get wrong and both were caught by the checks in §3:

**Centring.** Ridge fixes only the *sum* of the offensive and defensive blocks
against the intercept, not where league average sits within each. Left alone
that leaves an arbitrary constant in both — here +0.25 points per 100 — which
shifts every rating and silently inflates every WAR. Each block is centred to a
possession-weighted mean of zero, so league-average impact is exactly zero and
league-wide wins-above-average sums to zero.

**Scale.** Ridge deliberately shrinks. Aggregating the fitted coefficients back
to team level reproduces team net rating ordering almost perfectly (r = 0.995)
but spans only **64%** of the real spread. That is the bias half of the
bias-variance trade, and it matters the moment you convert to wins: a
replacement level of −2.0 is expressed in *real* points per 100, so applying it
to shrunk coefficients would compare two different scales. The table therefore
carries both `rapm` (raw estimator, for ranking) and `rapm_scaled` (divided by
the 0.64 attenuation, for magnitudes), and **WAR is computed from the scaled
column**.

## 3. Validation

| Check | Result |
|---|---|
| Possession-weighted mean RAPM | **0.0000** (centred by construction) |
| League-wide WAA | **0.00** (sums to zero, as it must) |
| Team additivity, raw ridge | r = 0.995, MAE 2.16, attenuation 0.64 |
| Team additivity, calibrated | r = 0.995, **MAE 0.47** |
| o_rapm + d_rapm = rapm | max residual 4.4e-16 |
| vs. the frozen sportsdataverse RAPM | r = 0.654 over different windows (n = 144) |

**Split-half reliability** — the honest error bar. Odd and even games fitted
separately, then correlated:

| Pool | n | Half-season r | Full-season reliability |
|---|---:|---:|---:|
| 200+ possessions | 179 | 0.467 | **0.637** |
| 500+ | 149 | 0.471 | 0.640 |
| 1000+ | 102 | 0.517 | **0.682** |

Around 0.64–0.68 is normal for single-season RAPM and is the reason
practitioners use multi-year windows. **Read ranks and tiers, not decimals.**

## 4. Wins

Two inputs, only one of which is a measurement.

**Points per win is estimated from this season**, not borrowed. Regressing team
win% on margin of victory across the 15 teams gives a slope of 0.0335 per point
at **R² = 0.918**, so points per marginal win is **29.87**. The fitted intercept
lands at **0.5003** — a team with zero margin is predicted to win half its
games, which is a good sign the specification is sound.

**Replacement level is a convention**, set to −2.0 points per 100 below
average. It cannot be measured off this data: ridge shrinkage pulls
low-possession players toward zero, so fringe players' RAPM is biased toward
average exactly where you would want to read replacement off. What *can* be
checked is whether the constant implies something sane — and it does. Since WAA
sums to zero, league-total WAR is purely a function of this constant, and −2.0
implies an all-replacement league would win **23.2%** of its games. Low twenties
is where that convention should land.

Sensitivity of the UCLA six's combined WAR to the choice:

| Replacement | −1.0 | −1.5 | **−2.0** | −2.5 | −3.0 |
|---|---:|---:|---:|---:|---:|
| Six combined WAR | −1.43 | −0.37 | **+0.70** | +1.76 | +2.82 |

The sign flips inside the plausible range. **Prefer WAA** — it needs no
convention at all — and quote WAR only with the replacement level stated.

## 5. Results

League leaders, 1000+ possessions:

| Player | Team | Poss | O | D | RAPM | Scaled | WAR |
|---|:--:|---:|---:|---:|---:|---:|---:|
| Jackie Young | LVA | 2,447 | +2.17 | +1.17 | **+3.35** | +5.23 | 5.92 |
| Natasha Howard | MIN | 2,210 | +1.72 | +1.19 | **+2.91** | +4.54 | 4.84 |
| Olivia Miles | MIN | 2,213 | +1.62 | +0.92 | **+2.54** | +3.96 | 4.42 |
| A'ja Wilson | LVA | 2,287 | +2.24 | +0.18 | **+2.42** | +3.79 | 4.43 |
| Angel Reese | ATL | 2,266 | +0.19 | +2.02 | **+2.21** | +3.46 | 4.14 |
| Veronica Burton | GSV | 1,895 | +0.64 | +1.50 | **+2.14** | +3.35 | 3.39 |
| Kelsey Mitchell | IND | 2,617 | +2.40 | −0.33 | **+2.07** | +3.24 | 4.59 |
| Kayla Thornton | GSV | 1,637 | +0.34 | +1.56 | **+1.90** | +2.96 | 2.72 |
| Jordin Canada | ATL | 2,255 | +1.24 | +0.65 | **+1.89** | +2.95 | 3.74 |
| Kayla McBride | MIN | 2,468 | +1.67 | +0.19 | **+1.86** | +2.91 | 4.06 |

Olivia Miles is the only rookie in the top ten — worth noting given she went
second in the same draft as the six.

### The UCLA six

| Player | Team | Poss | O | D | RAPM | Pctile | WAA | WAR |
|---|:--:|---:|---:|---:|---:|---:|---:|---:|
| Gabriela Jaquez | CHI | 1,258 | −0.85 | +0.66 | **−0.19** | 56 | −0.13 | +0.72 |
| Kiki Rice | TOR | 1,088 | +0.08 | −0.84 | **−0.76** | 35 | −0.43 | +0.29 |
| Lauren Betts | WAS | 1,220 | −1.44 | +0.63 | **−0.81** | 32 | −0.52 | +0.30 |
| Gianna Kneepkens | CON | 483 | −1.16 | +0.07 | **−1.10** | 20 | −0.28 | +0.05 |
| Angela Dugalic | WAS | 620 | −1.26 | −0.53 | **−1.79** | 7 | −0.58 | −0.16 |
| Charlisse Leger-Walker | CON | 1,673 | −1.55 | −0.30 | **−1.85** | 5 | −1.62 | −0.50 |

Percentile is against the 179 players with 200+ possessions.

Three readings worth carrying, all consistent with what the earlier documents
found by other routes:

- **Betts splits hard by end** — defence +0.63, offence **−1.44**. That is the
  spacing cost stated as impact: a centre with zero three-point attempts in 605
  minutes, whose own finishing is elite but whose presence shrinks the floor.
- **Leger-Walker's workload compounds a negative rate.** Her RAPM is the
  cohort's lowest *and* she played the most possessions of the six, so she also
  has the lowest WAA by some distance. Volume magnifies sign.
- **Jaquez grades best of the six**, at roughly league average — which sits
  oddly beside her collapsing minutes and −9.29 on/off swing. RAPM adjusts for
  teammates and opponents where raw on/off does not; the gap between the two is
  itself worth a look.

Kiki Rice's defensive coefficient (−0.84) runs *against* the raw on/off, which
had Toronto defending better with her on the floor. RAPM controls for who else
was out there; on/off does not. Neither is decisive at this sample.

## 6. Limits

1. **Reliability is 0.64.** Single-season RAPM. Ranks and tiers, not decimals.
2. **Two scales exist on purpose.** `rapm` for ordering, `rapm_scaled` for
   magnitudes and wins. Do not mix them in one chart.
3. **WAR carries a convention.** State the replacement level or quote WAA.
4. **Two of 229 players have no crosswalk name.** They receive coefficients and
   are included in all league aggregates; only their label is missing.
5. **Attenuation is estimated from 15 team-seasons.** The 0.64 factor is itself
   a small-sample estimate.
6. This does not replace the exact pbpstats on/off for single-player questions.
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
