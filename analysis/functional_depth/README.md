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
| `functional_depth_2026.csv` | team | Headline: component metrics, five sub-scores, composite, rank, profile |
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
