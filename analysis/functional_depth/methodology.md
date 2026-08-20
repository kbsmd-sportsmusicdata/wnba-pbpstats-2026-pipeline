# Functional Depth Methodology

## Why this exists

A week-12 read on the 2026 season made the case that depth decides playoff series and is badly
served by "bench averages 27.4 PPG". Minnesota beating Las Vegas with six of eight rotation players
in double figures is a *distribution* fact, not a bench-scoring fact. This score measures depth the
way that example implies: how spread a team's production is, and how well it holds up when the
starters are not all on the floor.

## The five components

Three are measured on the current per-game player layer
(`data/processed/wnba_pbpstats_player_game`); two on the possession-impact bench net ratings.

**Production distribution.** For each team's rotation (players at or above `rotation_minutes` per
game, default 12), the Gini concentration of scoring and of creation (a point-equivalent,
`points + 2 × assists`). A high Gini means one or two players carry the offense; a low Gini means it
is spread. The top scorer's share of rotation points is carried alongside as the plain-language
anchor.

**Rotation trust.** How many players clear the rotation-minutes bar, and the normalized Shannon
entropy of their minutes — a nine-deep team with even minutes scores higher than a seven-deep team
that leans on two players.

**Role redundancy.** Five skills a playoff rotation wants a backup for — scoring, playmaking,
perimeter shooting, rim protection, ball pressure — each as a per-75-possession rate. A "provider"
is a rotation player at or above the **league** rotation median for that skill; redundancy is the
fraction of the five skills for which the team has at least two providers.

**Replacement resilience.** The possession-impact `bench_dropoff`: starters-only net rating minus
any-bench net rating. A small or negative drop means the team does not fall apart when a starter
sits.

**Performance floor.** The possession-impact `bench_heavy_net_rating`: how the deepest-bench units
actually perform, i.e. how badly the weakest rotation segment hurts.

## From components to a score

Each component is turned into a **league-relative 0–100 sub-score** — a percentile rank across the
teams, signed so that higher always means deeper (concentration and bench drop-off are inverted).
Percentile-across-teams rather than an absolute scale keeps the unit meaningful: 100 is the deepest
team in the league on that component, not an arbitrary threshold. The composite is the weighted mean
of the sub-scores, default weights 0.25 / 0.15 / 0.20 / 0.20 / 0.20.

**The weights are a stated prior, not a validated forecast.** This score is descriptive: it
organizes public, defensible depth signals into one number and a picture. It is not claimed to
predict series outcomes, and — like the trajectory component in Hidden Value — it should not be read
as one. If it is ever used predictively, the weights want a held-out check first.

## Missing possession components

The possession feed lags the game layer, so a team may have no bench net ratings yet. Rather than
score those two components as zero (which would punish a team for a data lag), they are marked
unavailable and the composite is renormalized over the components that are present. `components_used`
records how many of the five contributed, so a five-of-five score and a three-of-five score are never
silently conflated.

## The roster strip

`star dependency ←→ distributed resilience` is a single axis in `[-1, +1]`, drawn from the three
distribution-family sub-scores (production distribution, rotation trust, role redundancy) mapped
around the league midpoint. It is deliberately *not* the full composite: the strip answers "how is
this team's production shaped", while the composite folds in the possession-fed resilience and floor.
A team can be distributed in its box score yet have a poor deep-bench floor, and the two views show
that.

## Depth is orthogonal to quality

The score says nothing about how good a team is. A weak team with no star will look distributed; a
title contender built around one MVP will look star-dependent. That is intentional — depth is a
*variable* to weigh next to team strength, not a proxy for it. Read the strip and the score alongside
the standings and the forecast, never instead of them.

## Tests

```bash
python -m unittest tests.test_functional_depth
```
