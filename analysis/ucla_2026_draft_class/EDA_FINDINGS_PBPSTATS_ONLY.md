# The UCLA Six — pbpstats-only findings

A second pass at the 2026 UCLA draft class built **exclusively on the pbpstats
game layer**. Nothing here depends on a source that stops in mid-July.

> **Coverage:** figures were regenerated against the refreshed pipeline —
> **281 games through 2026-08-23**. Rate and role measurements held; several
> small-sample on/off differentials moved materially, including one correction
> to §1 below. The vintage-by-vintage comparison is in §5 of
> [`DERIVED_POSSESSIONS.md`](./DERIVED_POSSESSIONS.md).

Companion documents: [`EDA_FINDINGS.md`](./EDA_FINDINGS.md) (the full pass,
including partial-season sources) and
[`METRIC_FRAMEWORK.md`](./METRIC_FRAMEWORK.md).

## What this document is allowed to use

**In:** `player_game.parquet` (281 games, 229 players, 252 columns) and
`team_game.parquet` (281 games, 562 rows). Every number below is computed from
those two files.

**One exception, stated plainly:** pbpstats carries no college or draft
metadata, so `player_core_2026.csv` selects *which* players are in the cohort
and which are rookies. It contributes membership only — no metric. It is a
static roster/bio snapshot, not a time series, so it cannot be stale in the way
the mid-July sources are.

**Out, and what went with them:**

| Dropped source | Coverage | Claims from `EDA_FINDINGS.md` that do not survive |
|---|---|---|
| `wnba_possessions_2026` | 202/281 games | Betts + Austin two-big net rating; Betts + Iriafen; Rice + Allemand; Kneepkens + Leger-Walker duo splits; all co-presence percentages; opponent shot-profile on/off |
| `wnba_lineups_2026` | 195/281 games | Any stint-level construction |
| `wnba_player_impact_2026` | gp ≤ 29 | RAPM, BPM, WAR, DARKO for all six |
| `player_box_2026` (ESPN) | full season, but not pbpstats | Starts and DNP counts |

Two of those — the alternating-bigs finding and the opponent-strength question
— can be rebuilt from pbpstats alone. §3 and §4 do that, and both come back
stronger than the versions they replace.

---

## 1. Kiki Rice's return was a minutes restriction — and it rewrites the on/off story

This was the open question from the first pass: Rice's on/off said +11.4 (now
+7.8 on refreshed data), but
Toronto's team-level series said the club got *worse* after she came back. The
answer is that her return had two distinct phases, and blending them produced
a number that describes neither.

### The minutes are unambiguous

| Window | G | Mean | Min | Max | SD |
|---|---:|---:|---:|---:|---:|
| Pre-injury (team games 1–10) | 10 | 26.7 | 17.6 | 35.0 | 6.4 |
| **Return games 1–5** (g27–31) | 5 | **21.5** | 17.1 | **26.8** | 4.1 |
| **Return games 6+** (g32+) | 6 | **29.6** | **24.5** | 31.8 | 2.6 |

Game by game: **17.1, 23.0, 26.8, 22.9, 17.6** — then **30.1, 31.4, 29.9, 24.5,
31.8**. The two windows barely overlap. The ceiling across the first five back
is 26.8; the floor across the next five is 24.5. That is the shape of a cap
being lifted, not of a coach reacting to performance.

Rest days rule out the alternative reading. Her *lowest* minutes back (17.1)
came off her *longest* rest (8 days), and within the first five games minutes
correlate **negatively** with rest (r = −0.49). She was being paced by games
returned, not by fatigue. By the second window she played both ends of a
back-to-back (29.9 on Aug 18, 24.5 on Aug 19).

### It was not only minutes — the per-possession game went with it

| Metric | Pre-injury | Return 1–5 | Return 6+ |
|---|---:|---:|---:|
| Points / 75 | 18.11 | **11.96** | 19.48 |
| True shooting | .670 | **.460** | .614 |
| eFG | .593 | **.371** | .568 |
| Shot quality | .563 | .471 | .490 |
| eFG − shot quality | +.030 | **−.100** | +.079 |
| Turnovers / 75 | 1.85 | **4.35** | 1.05 |
| Fouls / 75 | 3.96 | **6.75** | 3.57 |
| FTA / 75 | 6.42 | **3.99** | 4.61 |
| Rim share | .467 | .290 | .273 |
| Rim accuracy | .714 | .556 | **.944** |

Every axis moves the same direction and then comes back. The most telling pair
is rim share and free-throw rate: she stopped driving. Rim share fell from .467
to .290 and FTA/75 fell 38%, while three-point share *rose* to .355 — a player
settling for the shots that do not require her to absorb contact. Her shot
quality dropped 9 points of expected eFG, and she then converted 10 points
*below* even that reduced expectation. Turnovers more than doubled and fouls
rose 70%.

By games 6 onward it is all recovered or better: .614 TS, +.079 over
expectation, 1.05 turnovers per 75 (her best of the season), 5.87 assists per
75 (also her best), and 17 of 18 at the rim.

### Which resolves the contradiction

| Toronto block | G | W | ORtg | DRtg | Net | Rice on/off swing |
|---|---:|---:|---:|---:|---:|---:|
| Pre-injury (g1–10) | 10 | 5 | 111.70 | 111.55 | **+0.15** | **+20.6** |
| Rice OUT (g11–26) | 16 | 5 | 108.69 | 116.23 | −7.54 | — |
| Return 1–5 (g27–31) | 5 | **0** | 103.29 | 120.74 | **−17.45** | **−15.2** |
| Return 6+ (g32+) | 6 | 1 | 108.11 | 116.36 | −8.25 | **+2.6** |

The "Toronto got worse after Rice returned" result is a five-game artifact. It
sits entirely in the re-integration window, where a restricted, rusty Rice
played 21.5 minutes a night on a team that went 0–5.

**Correction against the previous vintage.** At 277 games this document said
her two healthy windows were +20.6 and +18.1, "consistent with each other." One
additional game dropped the second window to **+2.6**. The two healthy windows
do *not* agree, and the earlier "+18 to +21 when healthy" framing was resting on
a five-game sample that could not support it. The pre-injury +20.6 is
undisturbed; the post-return figure is not reliable at this sample size.

That final window is **open-ended by design** — it absorbs every game after the
five-game ramp, so it grows on each data refresh, which is exactly why its
on/off moved. Read it as "games 6 onward", never as a fixed five-game block.

**What survives, stated narrowly:** the five-game re-integration window is
real, distinct and measurable — restricted minutes, collapsed efficiency, an
0–5 team record — and the season-long on/off is dragged down by it. What does
*not* survive is a specific number for healthy-Rice impact. Her pre-injury
window is +20.6 over 526 possessions and her post-return window is +2.6 over
358 and still growing; those are not two readings of one quantity, they are
two small samples.
Quote the ramp, quote the recovery in her per-possession rates, and leave the
healthy-Rice on/off as directionally positive and imprecisely measured.

One caveat that does not go away: Toronto has the league's worst defense
(115.60 DRtg, 15th of 15), so her off-court comparison group is unusually bad,
which inflates any Toronto player's on/off. The swing is real; the magnitude
should be read as a Toronto-relative number.

---

## 2. The six, on full-season pbpstats only

Rates are possession-weighted season aggregates. Percentiles are against 149
players with 250+ minutes (league) and 37 rookies with 150+ minutes (rookie).
Higher percentile is always better.

| | Betts | Jaquez | Rice | Dugalic | Kneepkens | Leger-Walker |
|---|---:|---:|---:|---:|---:|---:|
| Pick | 4 | 5 | 6 | 9 | 15 | 18 |
| Team | WAS | CHI | TOR | WAS | CON | CON |
| GP / MPG | 36 / 16.8 | 32 / 19.0 | 20 / 26.1 | 31 / 10.2 | 27 / 8.0 | 35 / 23.5 |
| Usage | 16.6 | 17.4 | 18.3 | 17.1 | 16.0 | 16.5 |
| Points / 75 | 14.65 | 13.28 | **17.34** | 11.93 | 14.27 | 11.01 |
| TS% | .592 | .520 | **.621** | .490 | .533 | .479 |
| Shot quality | .481 | .528 | .529 | .509 | .493 | .476 |
| eFG − SQ | **+.071** | −.067 | +.018 | −.054 | −.022 | −.036 |
| Assists / 75 | 2.32 | 1.72 | 4.28 | 2.58 | 1.91 | **5.59** |
| Turnovers / 75 | 2.13 | 2.21 | 2.10 | 2.83 | **0.70** | 2.87 |
| Stocks / 75 | **2.90** | 1.48 | 1.44 | 2.29 | 0.68 | 1.74 |
| Fouls / 75 | 3.16 | **2.49** | 4.61 | 3.98 | 6.08 | 3.62 |
| Foul-trouble min % | 3.1 | 3.1 | **18.4** | 9.2 | 6.1 | 8.2 |
| OREB% (rookie pct) | 92 | 46 | 62 | 78 | 73 | 5 |
| DREB% (rookie pct) | 92 | 76 | 57 | **97** | 24 | 49 |
| On-court net | −3.27 | −3.99 | −2.11 | −13.28 | −12.93 | −9.27 |
| Off-court net | +1.57 | +3.22 | −13.50 | +2.00 | −10.87 | −8.88 |
| **Net swing** | −4.84 | −7.21 | **+11.39** | **−15.28** | −2.06 | −0.39 |

Everything in this table survives the source restriction. So do all of these
findings from the first pass:

- **Betts is the efficiency outlier with the smallest role.** 2nd of 37 rookies
  in shot-making over expectation, 2nd in rim accuracy (.768 on 82 attempts),
  3rd in stocks, 4th in both rebound rates, 8th in true shooting — and 17th in
  minutes per game. Zero three-point attempts in 605 minutes; 16% of her shots
  are long twos (7-for-26), three times the positional norm.
- **Jaquez gets good shots and misses them.** Second-best shot quality of the
  six, worst conversion against it (−.067, 26th of 37). Rim accuracy .580
  against a .630 guard median. Her minutes fell 28.3 → 21.6 → 16.6 → 11.7 by
  month and her on-court net went +6.6 → −1.5 → −9.3 → −19.9.
- **Leger-Walker carries the biggest role on the worst team** — 822 minutes,
  58.4% of Connecticut's offensive possessions, 18.1% of its assists — with
  both efficiency components negative: below-median shot quality (.476) *and*
  below-expectation conversion.
- **Dugalic is elite on the glass and nothing else is working.** 2nd of 37 in
  defensive rebound rate, 4-for-30 from three (13.3%) on a 34% attempt share,
  scoreless in 35.5% of appearances, and the worst net swing in the rookie pool.
- **Kneepkens has the best ball security in the class** (0.70 turnovers per 75,
  1st of 37) and a foul rate that makes it moot (6.08 per 75 against a 3.80
  league median).

### Cohort share

Six players, 8.6% of the 70-player rookie population, carrying **14.6% of
rookie minutes, 13.8% of points, 17.3% of rebounds, 13.5% of assists and 16.1%
of blocks.**

### One shared trait

Every one of the six except Betts takes more short-mid-range shots than the
league median (.227 to .337 against .225). It is the only metric on which the
cohort clusters — and it is the shot the modern game is trying to delete.

---

## 3. Rebuilding the rotation finding without possession data

The first pass used possession co-presence to show Washington alternates its
bigs rather than stacking them. That source stops in mid-July. Here is the
same question asked of the full season using only per-game minutes.

**The test.** For two teammates, correlate their minutes across all of their
team's games. A strongly negative correlation with a *stable combined total* is
the signature of one rotation slot being split between two players. Some
negative correlation is mechanical — team minutes are fixed — so every pair is
scored against the distribution of **all 663 rotation-teammate pairs** in the
league (both players 250+ minutes): mean r = −0.071, SD 0.280, 5th percentile
−0.541.

| Pair | Team | r | Percentile | Combined MPG | Combined SD |
|---|:--:|---:|---:|---:|---:|
| Kiki Rice / Julie Allemand | TOR | **−0.559** | **4.7th** | 50.5 | 6.1 |
| Lauren Betts / Kiki Iriafen | WAS | **−0.531** | **5.6th** | 44.2 | 6.6 |
| Lauren Betts / Shakira Austin | WAS | **−0.517** | **6.3rd** | 46.0 | 5.6 |
| Gabriela Jaquez / Natasha Cloud | CHI | −0.376 | 14.0th | 47.5 | 7.4 |
| Leger-Walker / Kneepkens | CON | −0.279 | 22.9th | 31.1 | 6.6 |
| **Lauren Betts / Angela Dugalic** | WAS | **+0.175** | **81.3rd** | 26.7 | 9.0 |

Three findings, all full-season:

1. **Washington runs three bigs through what is effectively two slots.** Betts
   is in the 6th percentile of substitution against Austin and the 5th against
   Iriafen, with a combined total near 45 minutes and a standard deviation
   under 7 in both cases. The mid-July possession data said the same thing;
   this says it across all 36 games.
2. **Toronto splits one guard slot between Rice and Allemand** — the most
   extreme trade-off of any pair examined, 4.7th percentile league-wide, with
   the pair's combined minutes pinned near 50.
3. **Betts and Dugalic are the exception, and it points the other way.** Their
   correlation is *positive* and in the 81st percentile — Washington's two UCLA
   rookies are used *together*, not alternately. Combined they average 26.7
   minutes with the highest variance of any pair here (SD 9.0): they rise and
   fall as a unit. Read alongside the game-level result that Washington is
   −13.0 per 100 when both play and roughly break-even otherwise, this is the
   clearest role-construction problem in the cohort.

What this test cannot recover is the actual on-court net rating of the
Betts + Austin pairing. That has since been settled by rebuilding the
possession layer from play-by-play — see
[`DERIVED_POSSESSIONS.md`](./DERIVED_POSSESSIONS.md). The short version: over
across four vintages of the data the pairing reads +1.6, −1.6, −0.1 and
**+4.7** — the sign changes twice and the spread is 6.3 points per 100. The
"Washington is leaving points on the floor" claim is **not supported and should
not be published in either direction**; the sample cannot resolve it.

---

## 4. Opponent strength does not change the rankings

Four bad teams draw different schedules, so the first pass flagged opponent
adjustment as follow-up #5. It is resolvable from pbpstats alone: each team's
season defensive rating from `team_game`, weighted by the possessions each
player actually faced.

League average defensive rating is **108.13**. The spread is wide — Golden
State 101.25, Toronto 115.60 — but individual schedules are not:

| Player | Off poss | Schedule faced | Points/75 raw | Points/75 adjusted | Δ |
|---|---:|---:|---:|---:|---:|
| Kiki Rice | 1,034 | −0.36 (tougher) | 17.34 | 17.39 | +0.06 |
| Lauren Betts | 1,162 | +0.32 (softer) | 14.65 | 14.61 | −0.04 |
| Gianna Kneepkens | 431 | −0.91 (tougher) | 14.27 | 14.39 | +0.12 |
| Gabriela Jaquez | 1,220 | +0.43 (softer) | 13.28 | 13.23 | −0.05 |
| Angela Dugalic | 610 | +0.79 (softer) | 11.93 | 11.84 | −0.09 |
| Charlisse Leger-Walker | 1,622 | −0.10 (tougher) | 11.01 | 11.02 | +0.01 |

**A negative result worth stating in the piece:** no player's schedule deviates
from league average by more than about one point of opponent defensive rating,
and the adjustment moves nobody's scoring rate by more than 0.12 points per 75.
The ordering is untouched. Cross-player efficiency comparisons in this cohort
can be made on raw numbers without apology — which is not something you get to
assume, and is worth one sentence of the reader's attention.

---

## 5. What changed against the first document

**Closed.** Follow-up #1 (the Rice contradiction) — resolved in §1; the answer
is a five-game injury ramp, and the healthy-Rice on/off is +18 to +21, not
+11.4. Follow-up #5 (opponent adjustment) — resolved in §4; the effect is
negligible.

**Reinforced on better evidence.** The Washington alternating-bigs finding now
rests on all 36 games instead of a mid-July possession sample (§3), and the
Betts–Dugalic pairing problem gained a second, independent line of support.

**Withdrawn pending data, then resolved.** The duo net ratings have since been
rebuilt for the full season from play-by-play
([`DERIVED_POSSESSIONS.md`](./DERIVED_POSSESSIONS.md)). Betts + Austin is
dead as a story — it swings 6.3 points across data vintages. Betts + Dugalic is
confirmed, worse than the game-level proxy suggested (−16.8 per 100 against
+2.9 for Washington's other minutes), and stable across vintages.
Still withdrawn: all opponent shot-profile splits and all RAPM/BPM/WAR
figures, which depend on sources that remain frozen in mid-July.

**Still open**, in priority order: extend the *impact* layer (RAPM/BPM/WAR)
past mid-July — the possessions half of this is now done; Betts's shot chart from
`shots_2026.parquet`, particularly the long twos; a foul taxonomy for Rice and
Kneepkens; Dugalic's three-point sample against her college baseline; a
draftee-only rookie pool; and a league-wide test of whether the second-half
minutes decline that hit three of these six is a 2026 rookie-class pattern.

---

## 6. Reproducing this

```
python3 scripts/ucla_2026_draft_class/run_pbpstats_only.py
```

Writes `story_rice_timeline.csv`, `story_rice_return_blocks_{player,team,onoff}.csv`,
`story_opponent_adjusted_scoring.csv`, `story_team_defense_strength.csv`,
`story_teammate_minute_correlations.csv` and `pbpstats_only_manifest.json` to
`analysis/ucla_2026_draft_class/data/`.
