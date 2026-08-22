# Role Fulfillment Matrix Vertical Slice Design

## Status

Approved for implementation by the user's 2026-08-21 instruction. This design narrows the
Role Fulfillment Matrix Repo Audit V2 into a fixture-only experiment.

## Objective

Build a standalone, coach-readable prototype that demonstrates the complete analytical path:

`contender gate -> reviewed eligibility -> reviewed role assignment -> recent/baseline metrics -> separate scores -> matrix -> evidence drawer`

The prototype must not import from, write to, link from, or otherwise integrate with the
standings/playoff forecast dashboard.

## Safety boundary

- The only supported scoring mode in this phase is `fixture`.
- Non-fixture scoring fails closed before any candidate metrics are computed.
- Live scoring remains blocked until a reviewed age/experience eligibility table and reviewed
  player-role assignment table exist.
- Synthetic fixture players and teams are visibly labeled; no fixture output may be presented as
  2026 player evaluation.
- Fulfillment, Opportunity, and Stability remain separate scores. There is no composite ranking.

## Architecture

The slice follows the repository's existing analysis convention:

- `analysis/role_fulfillment_matrix/`: configuration, methodology, synthetic fixtures, and the
  generated standalone dashboard bundle.
- `scripts/role_fulfillment_matrix/`: input contracts, candidate funnel, aggregation, scoring,
  evidence construction, outputs, and dashboard rendering.
- `scripts/build_role_fulfillment_matrix.py`: one command-line entry point.
- `tests/test_role_fulfillment_matrix*.py`: fixture-only unit, integration, and web-contract tests.
- `.github/workflows/role-fulfillment-matrix.yml`: manual-only workflow that tests and packages the
  fixture artifact; it has no schedule and cannot commit outputs.

## Data contracts

The fixture adapter accepts four bounded sources:

1. standings: team rank and cutoff date;
2. player game: additive game-level counts and opportunity denominators;
3. eligibility: explicit eligibility decision and review status;
4. assignments: explicit role code, review status, and assignment confidence.

Rates are never averaged from precomputed game rates. The pipeline sums counts inside the recent
and baseline windows, then recomputes each rate from its proper denominator.

## Candidate funnel

Candidates advance only when all gates pass:

1. team is inside the configured contender rank cutoff;
2. player has a reviewed, eligible age/experience record;
3. player has a reviewed role assignment found in the role-definition registry;
4. player has the configured minimum recent games and possessions;
5. all required role metrics have valid denominators.

Every rejected row receives a stable exclusion reason. Funnel counts are exported and shown in
the dashboard.

## Scoring

### Fulfillment

Each role declares behavior, efficiency, and mistake-control metrics with a direction, floor,
target, minimum denominator, and weight. Values are normalized to 0-100 and combined only when
all required metrics are available.

### Opportunity

Opportunity combines recent minutes per game, recent share of team possessions, and change in
possession share versus baseline. It measures access to the role, not quality of play.

### Stability

Stability combines sample sufficiency, recent possession volume, consistency of game-to-game
opportunity, and reviewed assignment confidence. It measures confidence in the observation, not
performance quality.

All score rows expose formula version, score status, coverage, window boundaries, denominators,
and evidence records. Missing required inputs produce `unavailable`, never an imputed score.

## Standalone interface

The generated static bundle contains:

- fixture-only and live-blocked status banners;
- candidate-funnel counts;
- Fulfillment / Opportunity / Stability cards;
- an SVG matrix with Opportunity on x and Fulfillment on y;
- a sortable candidate table;
- an accessible evidence dialog with metric values, denominators, source windows, and safeguards.

The payload is embedded as JSON for direct local viewing and also written as a separate JSON file
for inspection. Rendering uses text nodes rather than untrusted HTML injection.

## Success criteria

- Fixture tests demonstrate every funnel gate and score contract.
- A fixture build produces a complete static bundle and processed outputs.
- A live-config attempt fails with a useful governance error.
- Focused tests and the relevant pre-existing analysis tests pass.
- `git diff` contains no forecast-dashboard paths.
