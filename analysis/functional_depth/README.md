# Functional Depth Score

Depth treated as a playoff variable, not a roster adjective. Instead of "the bench averages 27.4
PPG", each team gets a **Functional Depth Score** built from five components, plus a
`star dependency ←→ distributed resilience` roster strip.

## The five components

| Component | Question | Built from |
|---|---|---|
| Production distribution | How concentrated is scoring / creation? | per-game player layer (Gini of rotation scoring & creation) |
| Rotation trust | How many players earn meaningful minutes? | per-game player layer (rotation size, minutes entropy) |
| Role redundancy | Can two players supply the same required skill? | per-game player layer (providers per skill vs league median) |
| Replacement resilience | What happens when a starter sits? | possession-impact `bench_dropoff` |
| Performance floor | How badly does the weakest segment hurt? | possession-impact `bench_heavy_net_rating` |

Each component becomes a league-relative 0–100 sub-score (percentile across teams, signed so higher
always means deeper), then blended by configured weights into `functional_depth_score`.

## Outputs

`data/processed/`

| File | Grain | What it is |
|---|---|---|
| `functional_depth_2026.csv` | team | Headline: component metrics, five sub-scores, composite, rank, profile, current availability |
| `functional_depth_components_2026.csv` | team × component | Long form of the five sub-scores, ready to plot |
| `functional_depth_strip_2026.csv` | team | The one-axis star-dependency ↔ distributed-resilience strip |
| `run_manifest_2026.json` | run | Source manifest, config hash, availability stats |

## Running

```bash
python scripts/build_functional_depth.py \
  --config analysis/functional_depth/config/functional_depth_config.json
```

Options: `--game-layer-root`, `--possession-impact-root`, `--output-root`. CI equivalent is the
**Functional Depth** workflow.

## Depth on paper vs. depth right now

The five components describe depth *over the season*; they do not know who is available tonight. The
build overlays the shared [injury / availability report](../injuries/README.md) so a reader can hold
both readings at once:

| Column | Meaning |
|---|---|
| `rotation_minutes_out` | Per-game minutes vacated by rotation players currently out with an injury |
| `rotation_minutes_out_share` | Those minutes as a share of a 200-minute game |
| `current_availability` | `Intact` / `Thinned` (≥10% MPG out) / `Depleted` (≥25% MPG out) |
| `players_out_now`, `players_out_for_season_now` | Counts behind the label |

A team can top the score on paper yet read `Depleted` right now — Connecticut, deepest by the
season-long components, is currently missing roughly half its rotation minutes. Vacated minutes
count any injury plus season-long absences of any category (a player who has left the team for the
year frees their minutes whether it is an injury or a departure); short-term non-injury absences —
national-team duty, a coach's decision — are excluded, since those minutes come back. The overlay is
additive and optional: with no feed, every team reads `Intact` and the score is unchanged.

## Two things to keep in mind

- **Depth is not quality.** The score measures how *distributed and resilient* production is, not how
  *good* a team is. A weak team with no dominant scorer reads as "distributed"; a strong team built
  around one star reads as "star-dependent". That separation is the point — it is meant to sit
  alongside team strength in a playoff-readiness view, not replace it.
- **Two components lag.** Replacement resilience and the performance floor come from the
  possession-impact feed, which trails the game layer (see that module's coverage note). When it has
  not yet covered a team, those two components are flagged unavailable and the score is renormalized
  over the three current components (`components_used` records how many of five were used) rather than
  scored on a silent zero. There is no on-court 5-player lineup data in this repo, so replacement and
  redundancy are bench-segment and player-skill approximations, not lineup-exact.
