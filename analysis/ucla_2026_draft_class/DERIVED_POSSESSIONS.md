# Rebuilding the possession layer — method, validation, and what it changed

The frozen `wnba_possessions_2026.parquet` is the reason the first two findings
documents had to withhold every lineup and duo result. This rebuilds that layer
for the full season from play-by-play, validates it against pbpstats, and
settles the claims that were left open.

**Headline:** the withheld "Betts + Austin two-big pairing is Washington's best
configuration" finding is **not supported**, and never was. It was noise around
zero in the frozen sample. The Betts + Dugalic problem, by contrast, is
confirmed and larger than the game-level estimate suggested.

---

## 1. Why the player game logs could not do this

`data/pbpstats_2026_player_game_logs/` was the natural first place to look, and
it does carry possession data — but the wrong shape of it.

Each row in `player_{id}_game_logs.json` is one **player-game**, carrying
`OffPoss`, `DefPoss`, `OnOffRtg`, `OnDefRtg` and 47 other aggregates. Those are
possession *counts*, not possession *records*. They say Lauren Betts was on the
floor for 1,162 offensive possessions; they never say which four teammates were
out there with her for any of them. **Co-presence is the missing dimension, and
no arithmetic over per-player aggregates recovers it** — two players' on-court
possession counts constrain their overlap only to a range, and for typical
rotation sizes that range spans nearly everything.

Those logs are also already fully used: `player_game.parquet` is built from
them, and the exact full-season on/off in the earlier documents comes from
exactly this data. There was nothing left in them to extract.

## 2. What could

`espn_pbp_2026.parquet` covers the full season — 279 games including two
all-star exhibitions, versus 202 in the frozen parquet — and carries **15,466
substitution events**, each naming both the entering and the exiting player,
with no nulls on either. Combined with `game_rosters_2026.parquet` (exactly
five flagged starters for all 554 game-teams), that is enough to replay every
game and hold a five-player lineup per side.

### Event attribution, derived rather than assumed

Which team a play-by-play row is logged against varies by event type, and
guessing wrong corrupts every possession boundary. Rather than assume, each
type was scored against the team that took the most recent shot:

| Event class | Logged against | Handling |
|---|---|---|
| All shot types, free throws, offensive rebounds | The team with the ball (100%) | Offense |
| Defensive rebound | The team gaining the ball (0%) | Possession flips |
| Turnovers (bad pass, lost ball, travel, shot clock, offensive foul) | The team losing the ball | Offense, then flips |
| Fouls, timeouts, jump balls, kicked ball | Ambiguous (49–82%) | Skipped |

### Possession definition

A possession runs **until the ball changes hands or the period ends**. Defining
it by the transition rather than by enumerating terminating events makes and-one
trips, missed free throws and offensive-rebound putbacks fall out correctly
with no special cases — the scoring team keeps the ball across all of them, so
no boundary is drawn.

### Calibration

Reconstructed possession counts run about 1.5% high against pbpstats — a level
difference in convention (team rebounds, end-of-period heaves), not a lineup
error. Each possession therefore carries a weight of
`pbpstats_off_poss / reconstructed_off_poss` for its team-game, which puts
every rate on the pbpstats scale without touching the lineup structure.

## 3. Validation

| Check | Result |
|---|---|
| Team-game **points** | **Exact on 100% of 554 team-games**, MAE 0.00 |
| Team-game possessions | r = 0.971, mean +1.20, MAE 1.32 on a base of ~80 |
| Player-game on-court possessions | **r = 0.9973**, MAE 1.19, median error +0.5% |
| Season on-court ORtg vs pbpstats (168 players, 250+ poss) | r = 0.975, MAE 1.03 |
| Season on-court NET vs pbpstats | r = 0.972, MAE 1.63 |

Points reproducing exactly across every team-game means the scoring
attribution is right. Player-game possessions correlating at 0.997 means the
lineup replay is right — which is the part that matters, since co-presence is
the whole reason the layer exists.

### How far it can be pushed

Comparing the derived single-player on/off against the exact pbpstats version:

| Pool | n | corr | MAE |
|---|---:|---:|---:|
| All players, 150+ poss | 185 | 0.856 | 3.72 |
| **Players in 95%+ of team games** | 58 | **0.907** | **2.47** |
| Players missing >5% of games | 127 | 0.844 | 4.30 |

The gap between those last two rows is **a definition difference, not error**.
pbpstats computes on/off only within games a player appeared in; the derived
layer's off-court pool also contains games she missed entirely. For Kiki Rice —
16 games missed — the two answer genuinely different questions, and the
pbpstats version (+7.8) is the one to quote, because the derived version
(+1.6) charges her off-court baseline with 16 games she had nothing to do with.

**So the two layers have different jobs.** pbpstats stays the source of truth
for single-player on/off, where it is exact arithmetic. The derived layer is
for co-presence, which pbpstats cannot express at all.

### The error bar that matters

Reconstruction noise on a net-rating differential is about ±2.5 points for
well-sampled players. Duo states typically hold 200–500 possessions, where
**sampling** error alone is worth roughly ±10 points per 100 regardless of
method. Treat duo gaps under about 15 points per 100 as indistinguishable.
That threshold decides both findings below.

---

## 4. What it changed

### The two-big number is unpublishable, and four vintages prove it

Full season, 281 games:

| WAS state | Off poss | ORtg | DRtg | Net |
|---|---:|---:|---:|---:|
| Austin without Betts | 1,661 | 105.8 | 104.5 | **+1.3** |
| Betts + Austin | 421 | 106.5 | 101.8 | **+4.7** |
| Betts without Austin | 799 | 98.8 | 106.2 | −7.4 |
| Neither | 53 | 115.8 | 151.4 | −35.6 |

Read in isolation this looks like support for the two-big pairing. It is not.
Track the same quantity across every vintage of the data we have:

| Source and window | Betts + Austin |
|---|---|
| Frozen sportsdataverse parquet, 202 games | **+1.6** over 200 poss |
| Derived layer, same 202 games | **−1.6** over 218 poss |
| Derived layer, 277 games | **−0.1** over 400 poss |
| Derived layer, 281 games | **+4.7** over 421 poss |

Four estimates of one pairing spanning **6.3 points per 100**, with the sign
changing twice. The last step is the most damning: **four extra team games
added 21 possessions to this split and moved it 4.8 points.** An estimate that
mobile is not measuring a property of the pairing, it is measuring noise.

The conclusion from the previous pass is unchanged and now better evidenced:
**do not publish a Betts + Austin number in either direction.** The honest
statement is that this sample cannot resolve whether the pairing helps.

### Betts + Dugalic is confirmed and worse than estimated

| WAS state | Off poss | ORtg | DRtg | Net |
|---|---:|---:|---:|---:|
| Neither | 1,326 | 108.6 | 105.7 | **+2.9** |
| Betts without Dugalic | 989 | 101.9 | 102.0 | −0.1 |
| Dugalic without Betts | 388 | 97.9 | 106.7 | −8.9 |
| **Betts + Dugalic** | 232 | 99.7 | **116.5** | **−16.8** |

A 20-point gap between the pairing and Washington's other minutes, comfortably
past the threshold — and, unlike Betts + Austin, **stable across vintages**:
the pairing sat at −16.8 at 277 games and −16.8 at 281. That stability is the
reason this one is publishable and the other is not. The game-level proxy in the first document put it at −13.0;
at possession level it is −16.8, and the damage is almost entirely defensive
(116.5 allowed, 12 points worse than the team's other lineups). Washington's
two UCLA rookies sharing the floor is the clearest role-construction problem in
the cohort, and it now has possession-level evidence across the full season.

### The other pairings

| Pair | Together | Best available state | Gap | Verdict |
|---|---:|---|---:|---|
| Leger-Walker + Kneepkens (CON) | −16.4 (267) | Leger-Walker alone −8.9 | 7.5 | Suggestive, inside noise |
| Rice + Allemand (TOR) | −11.8 (306) | Rice alone −5.3 | 6.5 | Suggestive, inside noise |
| Jaquez + Cloud (CHI) | −3.5 (688) | Neither +5.3 | 8.8 | Suggestive, inside noise |

All three point the same direction as the earlier partial-season reads, none
clears the bar for a published claim. The Rice + Allemand split is still worth
noting descriptively: Toronto plays them together for only 289 of Rice's 1,032
on-court possessions, which corroborates the full-season minutes-correlation
finding (4.7th percentile of substitution) through a second route.

### Betts's solo-five minutes remain the real issue

Betts without Austin: **−7.4 over 799 possessions**, against +1.3 for Austin
without Betts. That is the largest well-sampled split involving her and it
survives every check. It is a bench-unit effect, not a Betts effect — but it is
where her minutes actually go.

---

## 5. Data vintages, and what moves between them

The pipeline refreshes daily, and rebuilding on each new vintage has turned
into the most useful robustness check in this project. Coverage history:
**274 games / 08-21 → 277 / 08-22 → 281 / 08-23**, with every export
regenerated each time.

What four extra games (277 → 281) did to published figures:

| Figure | 277 games | 281 games | Verdict |
|---|---:|---:|---|
| Betts + Dugalic net/100 | −16.8 | **−16.8** | stable |
| Rice pre-injury on/off swing | +20.6 | **+20.6** | stable |
| Rice minutes, return 1–5 / 6–10 | 21.5 / 29.5 | **21.5 / 29.6** | stable |
| Betts + Austin net/100 | −0.1 | **+4.7** | unstable |
| Rice on/off swing, return block g32+ | +18.1 | **+2.6** | unstable |
| Rice season on/off swing | +11.4 | **+7.8** | drifting |
| Betts season on/off swing | −4.8 | **−1.7** | drifting |

The pattern is clean and worth stating in the piece: **rate and role
measurements are stable; small-sample on/off differentials are not.** Minutes,
shooting splits, shot diet and the large well-sampled pairing all reproduce.
Anything resting on a few hundred possessions moves by several points per 100
on a handful of games.

Two earlier vintage notes, retained: Jaquez's net swing fell −7.21 → −9.29 at
277 games as her decline continued, and Kneepkens flipped −2.06 → +0.53 on one
extra game.

## 6. Reproducing

```
python3 scripts/ucla_2026_draft_class/run_derived_possessions.py
```

Builds and calibrates the layer, prints the full validation report, and writes
`derived_possessions_2026.parquet` (45,643 possessions, 281 games) plus
`story_duo_splits_full_season.csv`, `story_derived_onoff_full_season.csv`,
`story_rice_blocks_derived.csv`, `derived_vs_exact_onoff.csv` and
`derived_stale_window_replication.csv`.

The layer is a drop-in replacement for `wnba_possessions_2026.parquet` in
shape — one row per possession, both five-player lineups, points, and a
calibration weight — so it can feed any analysis the frozen file used to.
