# Playoff Readiness

Who makes the WNBA 2026 playoffs, where they seed, and whether what they do well will
survive a series.

## Outputs

`analysis/playoff_readiness/data/processed/`

| File | Grain | Rows |
|---|---|---:|
| `playoff_odds_2026.csv` | team | 15 |
| `playoff_seed_probabilities_2026.csv` | team × seed | 225 |
| `playoff_readiness_2026.csv` | team | 15 |
| `remaining_game_leverage_2026.csv` | unplayed game × team | 226 |
| `team_ratings_2026.csv` | team | 15 |
| `run_manifest_2026.json` | run | Model validation, schedule reconciliation, source manifest |

## Running

```bash
python scripts/build_playoff_readiness.py \
  --config analysis/playoff_readiness/config/playoff_readiness_config.json
```

`--simulations N` overrides the configured 20,000 runs. CI equivalent is the **Playoff
Readiness** workflow, which also re-checks the two simulation identities before accepting
the artifacts. Reads the possession-impact and identity-shift outputs when they exist and
degrades to what it can compute when they do not.

## Where The 2026 Race Actually Is

Eight teams sit above .500 and the ninth is five games back with fifteen to play, so the
top-eight cut is close to settled. The live contest is the **top-four line** — home court in
round one — and the board's lenses are set by odds rather than assumption to reflect that.

| | Teams | What the metrics ask |
|---|---|---|
| **Top seed** | MIN GSV LVA ATL IND DAL | Does the edge hold when the game slows and the rotation shortens? |
| **Bubble** | NYL WAS CHI PHX PDX LAS | What is left on the schedule, and where is the leverage? |
| **Out of contention** | TOR CON SEA | Reported, not scored |

## Key Columns

### Odds

| Column | Meaning |
|---|---|
| `p_playoffs`, `p_top_four`, `p_top_two`, `p_top_seed` | Seed probabilities from 20,000 simulated seasons |
| `p_advance_first_round`, `p_reach_finals`, `p_title` | From the simulated bracket, not a separate model |
| `projected_wins_p10` / `_p90` | The spread, not just the mean |
| `clinched_playoffs`, `eliminated` | **Arithmetic** certainty — a different claim from a probability of 1.0 |
| `status` | The simulation's view: Effectively in / Comfortable / Bubble / Long shot / Effectively out |
| `magic_number`, `tragic_number` | Against the current first team out, or first team in |

### Readiness

| Column | Meaning |
|---|---|
| `set_net_rating` | Half-court net rating: possessions starting after a make, dead ball or timeout |
| `transition_reliance` | How much better a team is in early offence than in the half court |
| `quality_gap` | Margin above what the rating model expected, against the playoff field only |
| `bench_dropoff` | Starters-only net rating less any-bench net rating — see the caveat below |
| `rotation_concentration` | Share of the last ten games' minutes going to the top seven |
| `clutch_net_rating_shrunk` | Clutch net rating shrunk toward zero by its possession count |
| `remaining_difficulty` | Average expected margin conceded over the run-in, home advantage netted out |
| `total_playoff_leverage` | How much of a team's season is still genuinely undecided |
| `readiness_index` | Equal-weight average of the lens's components. **A sort key, not a model** |

## Reading This Correctly

- **`readiness_index` is not fitted.** The playoffs have not happened, so there is nothing to
  fit weights against. The components are the deliverable; the index just orders them.
- **`clinched` and a probability of 1.000 are different claims.** The first is a counting
  argument, the second is 20,000 simulations. Both are published, separately.
- **The half-court split lags.** It reflects games through 2026-07-22; the odds run to
  2026-08-01.
- **`bench_dropoff` is partly about opponents.** Starters-only possessions cluster at period
  openings against the other team's starters, so a negative dropoff is as likely to be that
  artefact as a genuinely superior bench. `rotation_concentration` is the clean half of the
  rotation picture.
- **The mid-September break is not modelled.** The schedule pauses 30 August to 14 September
  for the World Cup and the model treats games either side identically.

## Verification

- Schedule reconciles to **44 games for all fifteen teams** — 217 played, 113 remaining —
  after removing the All-Star game, the Commissioner's Cup final and a superseded
  postponement shell. A failure here stops the build.
- Rating model beats both baselines on held-out games: log loss **0.584** against 0.599
  (win percentage) and 0.695 (home field). The margin over the record baseline is thin and
  the manifest records it every run.
- Recency weighting and the margin cap were both set by expanding-window backtest; weighting
  by recency made the model worse at every half-life tested.
- Simulation identities hold: playoff probabilities sum to 8.0001, title probabilities to
  1.0000.
- 46 unit tests: `python -m unittest tests/test_playoff_readiness.py`.

Full method, the backtest tables and the limitations: [`methodology.md`](methodology.md).
