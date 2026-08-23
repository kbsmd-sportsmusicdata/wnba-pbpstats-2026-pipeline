# The UCLA Six — 2026 rookie season EDA

**Season 2026 regular season, through 2026-08-21** · 274 team games · pbpstats
game layer + ESPN bio/box + sportsdataverse possessions.
Companion: [`METRIC_FRAMEWORK.md`](./METRIC_FRAMEWORK.md).

---

## 0. The cohort

Six players drafted in 2026 out of UCLA (`college_id == 26`) — a single-school
record. They landed on four teams, and two of the four took *two* of them.

| Pick | Player | Pos | Team | Team net rtg (rank) | GP / team GP | MPG | Starts |
|---:|---|:--:|:--:|---:|---:|---:|---:|
| 4 | **Lauren Betts** | C | WAS | −0.40 (8th) | 36 / 36 | 16.8 | **1** |
| 5 | **Gabriela Jaquez** | G | CHI | −1.13 (9th) | 32 / 37 | 19.0 | 15 |
| 6 | **Kiki Rice** | G | TOR | −6.76 (14th) | **20 / 36** | 26.1 | 12 |
| 9 | **Angela Dugalic** | F | WAS | −0.40 (8th) | 31 / 36 | 10.2 | 3 |
| 15 | **Gianna Kneepkens** | G | CON | −9.11 (15th) | 27 / 35 | 8.0 | 4 |
| 18 (R2) | **Charlisse Leger-Walker** | G | CON | −9.11 (15th) | 35 / 35 | 23.5 | 23 |

Structural fact worth leading with: **all six went to teams with a negative net
rating**, and three of the four employers rank 9th, 14th and 15th of 15. Every
raw plus/minus in this cohort is dragged by that. It is the reason the analysis
below leans on *on/off swing* rather than on/off level.

**They are 8.6% of the rookie population and carry far more than that:**

| | Players | Minutes | Points | Rebounds | Assists | Blocks |
|---|---:|---:|---:|---:|---:|---:|
| 2026 rookie class | 70 | 21,157 | 7,948 | 2,968 | 2,038 | 292 |
| UCLA six | 6 | 3,088 | 1,099 | 514 | 276 | 47 |
| **UCLA share** | **8.6%** | **14.6%** | **13.8%** | **17.3%** | **13.5%** | **16.1%** |

---

## 1. Headline read on each player

Percentiles below are **within the 37-rookie pool (150+ min)** unless marked
"lg" for the 149-player league pool. Higher is always better.

### Lauren Betts (#4, WAS) — the efficiency outlier nobody is playing

The single most striking result in the dataset. Betts is **2nd of 37 rookies in
shot-making over shot quality** (+0.071, i.e. her eFG beats the expected value
of her shot locations by 7 points), **2nd in rim accuracy** (76.8% on 82 at-rim
attempts vs a 68.6% median for centers), **3rd in stocks/75**, **4th in both
offensive and defensive rebound percentage**, and **8th in true shooting**
(.592, 70th pct lg). She played all 36 games.

She started **one** of them, and ranks 17th of 37 rookies in minutes per game.

Two structural details explain the gap between the production and the role:

- **She has attempted zero three-pointers in 605 minutes.** Not a low rate —
  zero. Meanwhile 16% of her shots are long twos, three times the positional
  median (.160 vs .050 for centers), and she makes 7 of 26 on them. Her best
  shot and her worst shot are both inside the arc, and the spacing cost of a
  non-shooting five is real on a team that already ranks 13th of 15 in
  offensive rating.
- **Washington is alternating, not stacking, its bigs.** Of Shakira Austin's
  1,312 offensive possessions, only 200 (15.2%) include Betts. Of Betts's 812,
  only 24.6% include Austin.

And the Betts–Austin pairing is Washington's best configuration in the sample:

| WAS lineup state | Off poss | PPP | Opp PPP | Net/100 |
|---|---:|---:|---:|---:|
| Betts **+** Austin | 200 | 1.095 | 1.079 | **+1.6** |
| Austin only | 1,112 | 1.009 | 1.003 | +0.6 |
| Betts only | 612 | 0.997 | 1.095 | **−9.8** |
| Neither | 138 | 1.043 | 1.162 | −11.8 |

Betts's own on/off (−4.8 net swing, 28th of 37) is therefore substantially a
*bench-unit* number: her solo-five minutes come with the second unit, and they
bleed 1.095 points per possession defensively. The Betts + Kiki Iriafen pairing
is the actual problem (−14.8/100 over 323 possessions), not Betts + Austin.

Her development curve is the cleanest of the six — TS .518 → .591 → .608 →
.646 by month, fouls/75 4.24 → 4.01 → 3.15 → **1.32**, assists/75 0.89 → 2.05 →
2.95 → 2.89. She spends **3.1% of her minutes in foul trouble against a league
median of 9.7%**. She also recovered 16 of her 26 blocks (61.5%) — blocks her
team keeps possession of, not swats into the third row.

### Kiki Rice (#6, TOR) — best per-minute rookie in the class, half a season of it

Rice is 4th of 37 rookies in true shooting (.621), 6th in points/75 (17.3), 6th
in minutes per game, 10th in assists/75, and **4th in on/off net swing
(+11.4)** — Toronto is 11.4 points per 100 better with her on the floor. She
scored 10+ in **70% of her games**, the highest rate in the cohort, with the
lowest scoring volatility (pts CV 0.51).

Her profile is a genuine lead-guard signature: **47.4% of her made-field-goal
points are unassisted** (guard median 38.0%), free-throw rate **.494 against a
.275 guard median** — 78 FTA in 521 minutes, the most aggressive rim-pressure
profile of the six — and 75 penalty-situation points, also the most.

Two hard caveats, and they matter:

1. **She missed 16 consecutive games** (team games 11–26). The absence is a
   clean natural experiment, and it does *not* say what the on/off says:

   | Toronto block | G | W | ORtg | DRtg | Net |
   |---|---:|---:|---:|---:|---:|
   | A: games 1–10 (Rice in) | 10 | 5 | 111.7 | 111.6 | **+0.2** |
   | B: games 11–26 (Rice out) | 16 | 5 | 108.7 | 116.2 | **−7.5** |
   | C: games 27–36 (Rice back) | 10 | 1 | 106.3 | 118.6 | **−12.4** |

   Toronto was worse without her and *worse still* after she returned. The
   team-level series and the possession-level on/off disagree, which is the
   honest finding: her minutes are clearly better than her replacements'
   minutes, but the club's overall trajectory is being driven by something
   other than Rice. **This needs a separate look before it goes in print.**
2. **Foul trouble is her real constraint.** Rice spends **18.4% of her minutes
   in foul trouble** — nearly double the league median and the highest in the
   cohort — on 4.61 fouls per 75 defensive possessions. Toronto also barely
   plays her with Julie Allemand (74 shared possessions), so a foul on Rice
   means the offense changes hands entirely.

### Charlisse Leger-Walker (#18, CON) — the biggest role, the thinnest efficiency

The second-round pick out-played her draft slot by workload: **822 minutes,
5th-most of any 2026 draftee and 12 slots ahead of her pick-based expectation**,
35 of 35 games, 23 starts, 58.4% of Connecticut's offensive possessions, and
**18.1% of the entire team's assists**. She is 7th of 37 rookies in assists/75
(5.59) and 8th in minutes.

The efficiency is the problem, and pbpstats isolates it as a two-part problem
rather than one:

- **Shot selection**: shot quality .476, the lowest of the six and below the
  league median of .511. The shots themselves are poor.
- **Shot-making**: −0.036 eFG over expectation on top of that.

Both signs negative is the worst combination in the framework. Add the lowest
rim pressure in the cohort (FTR .216, rim share .203) and the lowest offensive
rebounding rate (36th of 37 rookies), and the .479 TS follows mechanically.

Her role is also visibly mutating: minutes 21.6 → 18.7 → 28.5 → 25.5 by month
while usage *fell* 18.8 → 15.2 → 16.6 → 14.6 and three-point share rose .373 →
.333 → .436 → **.568**. Connecticut is converting her from on-ball creator to
off-ball connector in real time. Her full-season on/off is essentially neutral
(−0.4 net swing, 17th of 37) — on the worst team in the league, that is a
better result than it looks, and it is driven by defense (opponents score 1.077
PPP against her vs 1.126 without).

### Gabriela Jaquez (#5, CHI) — good shots, no conversion, and a fading role

Jaquez has the second-best shot quality of the six (.528) and the **worst
shot-making over expectation (−0.067, 26th of 37 rookies)**. Chicago is
generating good looks for her; she is missing them. Her rim accuracy is 58.0%
against a 63.0% guard median — a finishing problem, cleanly isolated, and the
most actionable development target in the entire cohort.

The trajectory is the concern. Minutes by month: **28.3 → 21.6 → 16.6 → 11.7**.
On-court net by month: +6.6 → −1.5 → −9.3 → **−19.9**. TS .571 → .528 → .465 →
.519. Her full-season net swing is −7.2 (30th of 37). Note the mid-July
possession snapshot still shows Chicago +12.7 points per 100 *better* on offense
with her on the floor — the collapse is concentrated in the final six weeks,
which the possessions dataset does not cover.

The genuinely positive signal: **2.49 fouls per 75, cleanest in the cohort**
(5th percentile among rookies for fouling), 3.1% of minutes in foul trouble,
and 53 fouls drawn. She is not costing her team possessions.

### Angela Dugalic (#9, WAS) — elite on the glass, out of the rotation

Dugalic is **2nd of 37 rookies in defensive rebound rate** (97th percentile,
94th lg) and 8th in offensive rebound rate, with 9th-best stocks/75. On the
glass she is already a league-average-or-better NBA-caliber contributor.

Everything else has gone backwards. Minutes by month: 12.5 → 15.0 → 5.5 → 4.0.
She was scoreless in **35.5% of her appearances**. Her three-point shot has
collapsed — **4 of 30, 13.3%**, 33rd of 37 rookies — while still taking 34% of
her shots from behind the arc, which is the single worst shot-diet/accuracy
mismatch in the cohort. Her on/off net swing of **−15.3 is 37th of 37**, last in
the rookie pool.

There is a real confound: 79.4% of her made two-point points are assisted and
77.7% of her rim makes are assisted, both the highest in the cohort — she is a
pure play-finisher, and she is finishing with Washington's weakest offensive
units (Betts + Dugalic together: −13.0/100 over 291 possessions; Dugalic without
Betts: −0.7).

### Gianna Kneepkens (#15, CON) — 215 minutes, and a foul problem

The smallest sample in the cohort (27 appearances, 8.0 mpg, 36th of 37 rookies
in minutes) and it should be read that way. Two things stand out anyway:

- **Best ball security of any rookie in the class.** 0.70 turnovers per 75 —
  **1st of 37** — and 2.75 assist-to-turnover. Four turnovers in 215 minutes.
- **A severe foul rate.** 6.08 fouls per 75 defensive possessions against a
  3.80 league median, 36 fouls in 215 minutes, peaking at 11.7/75 in July. At
  that rate she cannot hold rotation minutes regardless of anything else.

Her shot diet is converging on specialist: three-point share .424 → .400 → .700
→ .625 by month, .507 for the season, 81st percentile among rookies. The
accuracy has not followed yet (9 of 35, 25.7%). Connecticut's worst two-player
state in the possession sample is Kneepkens **with** Leger-Walker (−23.9/100
over 220 possessions) — a two-rookie-guard pairing the team should probably
stop running.

---

## 2. Cohort-level patterns

### Outliers and deviations against the rookie pool

| | Best in cohort | Rookie rank | Worst in cohort | Rookie rank |
|---|---|---:|---|---:|
| Shot-making over shot quality | Betts +0.071 | **2 / 37** | Jaquez −0.067 | 26 / 37 |
| True shooting | Rice .621 | **4 / 37** | Leger-Walker .479 | 27 / 37 |
| Def. rebound rate | Dugalic | **2 / 37** | Kneepkens | 29 / 37 |
| Off. rebound rate | Betts | **4 / 37** | Leger-Walker | 36 / 37 |
| Turnovers / 75 | Kneepkens 0.70 | **1 / 37** | Leger-Walker 2.87 | 25 / 37 |
| Stocks / 75 | Betts 2.90 | **3 / 37** | Kneepkens 0.68 | 35 / 37 |
| Rim accuracy | Betts .768 | **2 / 37** | Leger-Walker .543 | 29 / 37 |
| On/off net swing | Rice +11.4 | **4 / 37** | Dugalic −15.3 | **37 / 37** |
| Free-throw rate | Rice .494 | **3 / 37** | Leger-Walker .216 | 25 / 37 |

The cohort has **no metric where all six cluster**. They are six genuinely
different players who happened to share a college roster — which is itself the
most interesting editorial finding, and the strongest argument against a
"UCLA system product" framing.

### Shot diet vs positional norms

| Player | Rim | Short mid | Long mid | 3PT | Corner 3 | Shot qual | eFG − SQ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Betts | **.503** | .337 | **.160** | **.000** | .000 | .481 | **+.071** |
| Dugalic | .420 | .227 | .011 | .341 | .068 | .509 | −.054 |
| Rice | .380 | .259 | .070 | .291 | .044 | .529 | +.018 |
| Jaquez | .379 | .302 | .022 | .297 | .099 | .528 | **−.067** |
| Leger-Walker | .203 | .278 | .101 | .419 | .066 | **.476** | −.036 |
| Kneepkens | .159 | .261 | .072 | **.507** | .087 | .493 | −.022 |
| *League median (250+)* | *.282* | *.225* | *.065* | *.396* | *.077* | *.511* | *+.004* |

Every one of the six except Betts takes **more short-mid-range shots than the
league median** — .227 to .337 against .225. That is the one shared trait in the
cohort, and it is the shot the modern game is trying to eliminate.

### Draft slot vs delivered role

Ranking all 29 playing 2026 draftees by minutes and comparing to pick order:

- **Over-delivering**: Leger-Walker (pick 18, 5th in minutes — **+12 slots**),
  Serah Williams (33rd pick, 11th, +16), Flau'jae Johnson (+5).
- **Under-delivering**: Dugalic (pick 9, 17th in minutes — **−9 slots**),
  Kneepkens (pick 15, 19th, −5), Betts (pick 4, 8th, −4), Rice (pick 6, 9th,
  −3, but availability-driven).

Four of the six UCLA picks are getting *less* role than their slot implies. Only
the second-rounder is getting more.

### Development: the two clean arcs and the two clean declines

Second half vs first half of each player's own games:

| Player | Δ MPG | Δ Usage | Δ TS | Δ Fouls/75 | Δ 3PT share |
|---|---:|---:|---:|---:|---:|
| Betts | +0.8 | −2.6 | **+.056** | **−1.81** | 0.000 |
| Kneepkens | −3.4 | +1.0 | **+.072** | +3.27 | +.223 |
| Rice | −1.2 | +1.4 | −.096 | +1.31 | −.030 |
| Leger-Walker | **+8.6** | −1.0 | −.044 | −0.79 | +.119 |
| Jaquez | **−9.1** | −0.4 | −.062 | −1.02 | +.024 |
| Dugalic | **−9.3** | −3.7 | −.024 | −2.06 | +.015 |

Betts is the only player in the cohort whose efficiency, discipline and
playmaking all improved while her minutes held. Jaquez and Dugalic both lost
roughly nine minutes a game. Leger-Walker gained nearly nine while shedding
usage — the clearest role-redefinition in the group.

---

## 3. Team impact and role contribution

### Full-season on/off (exact, 274 games)

| Player | On ORtg | On DRtg | On net | Off net | **Net swing** | Poss share |
|---|---:|---:|---:|---:|---:|---:|
| Kiki Rice | 112.4 | 114.5 | −2.1 | −13.5 | **+11.4** | 65% |
| Charlisse Leger-Walker | 101.3 | 110.6 | −9.3 | −8.9 | −0.4 | 58% |
| Gianna Kneepkens | 96.8 | 109.7 | −12.9 | −10.9 | −2.1 | 20% |
| Lauren Betts | 99.1 | 102.4 | −3.3 | +1.6 | −4.8 | 41% |
| Gabriela Jaquez | 103.7 | 107.7 | −4.0 | +3.2 | −7.2 | 46% |
| Angela Dugalic | 94.9 | 108.2 | −13.3 | +2.0 | −15.3 | 25% |

League distribution of net swing (160 players, 400+ off poss): mean +0.4,
sd 8.5, range −29.6 to +23.8. Rice sits at the **91st percentile** of that pool and Dugalic at the **3rd**;
Leger-Walker 46th, Betts 26th, Jaquez 16th.

### The two intra-team pairings

**Washington (Betts + Dugalic).** The two rookies together: −13.0 net/100 over
291 possessions. Betts without Dugalic: −3.6. Dugalic without Betts: −0.7.
Neither: −0.8. The rookie-heavy frontcourt is Washington's worst state by a
wide margin, and Washington is a *playoff team* — this is a team that has
correctly identified its rookie units as a liability and minimized them.

**Connecticut (Kneepkens + Leger-Walker).** Together: −23.9 net/100 over 220
possessions. Leger-Walker alone: −9.7. Kneepkens alone: −14.2. Neither: −3.5.
Same conclusion, worse magnitude, on the league's worst team.

Both clubs stacked two UCLA guards/bigs and both two-rookie pairings are the
worst configuration available to them. That is a real, replicated finding
across two independent teams.

### Impact-metric cross-check (partial season, through mid-July)

| Player | RAPM | RAPM pct | BPM | WAR | Min |
|---|---:|---:|---:|---:|---:|
| Betts | +0.50 | 73rd | −0.7 | 1.38 | 425 |
| Rice | +0.48 | 72nd | −2.2 | 0.76 | 267 |
| Jaquez | +0.39 | 68th | −5.5 | 1.59 | 499 |
| Leger-Walker | −1.07 | 10th | −9.7 | 0.75 | 614 |
| Dugalic | −1.19 | 8th | −4.3 | 0.30 | 291 |
| Kneepkens | −0.94 | — | −10.7 | 0.28 | 177 |

RAPM broadly corroborates the on/off ordering with one instructive exception:
it likes **Jaquez** (68th pct) far more than her full-season on/off does — again
because the impact table stops before her late-season decline. Treat RAPM here
as a *first-two-thirds* verdict.

---

## 4. What to look at next

Ranked by how much they would change the story:

1. **Resolve the Kiki Rice contradiction.** Possession-level on/off says +11.4;
   the game-level before/during/after series says Toronto got worse after she
   came back. Rebuild the block comparison controlling for opponent strength,
   rest, and which *other* Toronto players were available in games 27–36. This
   is the single biggest unverified claim in the piece.
2. **Extend the possessions and impact layers past mid-July.** 72 games and six
   weeks are missing, and that window contains Jaquez's entire collapse and
   Rice's entire return. Every lineup and RAPM number here is provisional.
3. **Betts's shot chart.** 0-for-0 from three, 7-of-26 on long twos, 63-of-82 at
   the rim. `shots_2026.parquet` has x/y coordinates — a spatial view would show
   whether the long twos are pick-and-pop looks (a stretch skill in progress) or
   broken-possession bailouts (a problem).
4. **Two-big viability at Washington.** The Betts + Austin sample is 200
   possessions and positive. Extend it to the full season via the pbpstats layer
   and test whether it holds. If it does, it is a legitimate "Washington is
   leaving points on the floor" story.
5. **Opponent-adjusted efficiency.** Four bad teams draw different schedules.
   Adjust `pace_neutral_pts_75` and `ts_pct` for opponent defensive rating using
   the team-game layer before making cross-player efficiency claims.
6. **Foul taxonomy.** Rice (18.4% of minutes in foul trouble) and Kneepkens
   (6.08 fouls/75) are both minute-capped by fouling. pbpstats splits shooting /
   loose-ball / offensive / charge fouls — which type, and in which game states,
   is a self-contained development story.
7. **Dugalic's three-point shot.** 4-of-30 on a 34% attempt share. Small enough
   to be noise (the 90% CI on 30 attempts is enormous) and consequential enough
   to decide her role. Compare with her college volume and rate.
8. **A draftee-only rookie pool.** Five of the rookie class's top twelve minute
   earners are undrafted or international first-years. Re-running every
   percentile against draftees only would sharpen the draft-class framing.
9. **Rookie-wall test across the class.** Three of the six lost significant
   minutes in the back half. Check whether that is a UCLA-cohort effect or a
   league-wide 2026 rookie pattern.

## 5. Reproducing this

```
python3 scripts/ucla_2026_draft_class/build_datasets.py     # cohort + filtered slices
python3 scripts/ucla_2026_draft_class/run_cohort.py         # percentile tables
python3 scripts/ucla_2026_draft_class/run_trends.py         # monthly / split-half
python3 scripts/ucla_2026_draft_class/run_team_impact.py    # on/off, pairs, natural experiment
python3 scripts/ucla_2026_draft_class/run_possessions.py    # possession-level splits
python3 scripts/ucla_2026_draft_class/run_shot_profile.py   # shot diet, volatility, outliers
python3 scripts/ucla_2026_draft_class/run_rookie_class.py   # rookie leaderboard + slot analysis
python3 scripts/ucla_2026_draft_class/export_story_data.py  # design-ready story_*.csv bundle
```
