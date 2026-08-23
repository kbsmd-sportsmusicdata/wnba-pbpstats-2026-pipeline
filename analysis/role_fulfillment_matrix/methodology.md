# Role Fulfillment Matrix Methodology

## Analytical sequence

```text
contender requirement
  -> reviewed age/experience eligibility
  -> reviewed role assignment
  -> recent sample and denominator gates
  -> role behavior + efficiency + mistake control
  -> separate Fulfillment / Opportunity / Stability scores
  -> matrix and expandable evidence
```

## Field inventory

| Requirement | Prototype fields | Status | Live-source disposition |
|---|---|---|---|
| Contender identification | `team_abbreviation`, `current_rank`, `cutoff_date` | Available | Direct from validated current standings; carry cutoff. |
| Age/experience eligibility | `eligibility_type`, `age_on_cutoff`, `experience_years`, `eligible_flag`, review metadata | Real data / pending review | ESPN player core covers all 227 PBPStats players; the deterministic `experience_years <= 3` output remains blocked until human approval. |
| Player identity | `player_id`, `player_name`, `team_abbreviation` | Available | PBPStats key is canonical. ESPN identity requires a reviewed crosswalk. |
| Opportunity level | `minutes`, `off_poss`, `team_possessions`, games | Available / derivable | Recompute MPG and possession share from player-game counts. |
| Opportunity change | recent and baseline possession share | Derivable | Recent minus baseline; keep both windows and denominators. |
| Role assignment | `role_code`, `assignment_confidence`, reviewer metadata | Fixture only / live blocked | Existing generic archetypes are an unreviewed proxy, not assignments. |
| Creator behavior | assists, offensive possessions | Available / derivable | `75 * assists / off_poss`. |
| Rim behavior | rim attempts, total FGA | Available / derivable | Rim-attempt share and rim accuracy. |
| Efficiency | points, FGA, FTA; rim makes/attempts | Available / derivable | Recompute TS% and role-specific accuracy from counts. |
| Mistake control | assists, turnovers, offensive possessions | Available / derivable | A/TO or turnover rate depending on assigned role. |
| Team impact | on-court ratings, RAPM, lineup/possession inputs | Evidence-only / lagging | True on-off is not materialized; RAPM coverage lags the fresh game layer. |
| Recent-vs-baseline | `game_date`, additive counts | Available / derivable | Use explicit non-overlapping date windows. |
| Stability/confidence | games, possessions, game-level opportunity share, assignment confidence | Derivable | Never use scoring direction as confidence. |
| Provenance | source path, rows, columns, config hash, formula version | Available | Persist in manifest and evidence. |

## Current fixture roles

### Backup Creator

- behavior: assists per 75 offensive possessions;
- efficiency: true shooting percentage;
- mistake control: assist-to-turnover ratio.

### Rim Pressure Finisher

- behavior: rim-attempt share;
- efficiency: rim field-goal percentage;
- mistake control: turnovers per offensive possession.

These are implementation fixtures, not reviewed live role definitions.

## Formula contract

Each role metric declares a floor, target, direction, weight, and denominator. Higher-is-better
metrics use:

```text
clamp((value - floor) / (target - floor), 0, 1) * 100
```

Lower-is-better metrics reverse the numerator. Fulfillment is the weighted mean of all required
role metrics only when every metric is available.

Opportunity is the weighted mean of normalized recent minutes per game, recent possession share,
and possession-share change versus baseline.

Stability combines recent-game sample, recent possession volume, consistency of game-level
possession share, and reviewed assignment confidence. A player can therefore be consistently poor:
high Stability with low Fulfillment is valid and covered by a regression test.

## Scoring safeguards

1. No composite score is calculated or exported.
2. Non-fixture mode fails before source loading.
3. Missing required evidence produces `unavailable`; it is never replaced by zero, 50, or league
   average.
4. Rates are recomputed from summed numerators and denominators, not averaged from per-game rates.
5. The contender rule and date windows are config-versioned.
6. Eligibility and assignment review status are hard funnel gates.
7. Role codes must exist in the role registry.
8. Minimum recent games and offensive possessions are hard sample gates.
9. Stability describes confidence, not direction or quality of performance.
10. Every score row carries `score_status`, `coverage_pct`, `formula_version`, and `analysis_mode`.
11. Every evidence row carries source, window, denominator, and safeguard text.
12. Fixture output is labeled in the page, payload, processed tables, and manifest.
13. Lagging RAPM/on-court context is excluded from headline fixture scores.
14. Output paths are confined to `analysis/role_fulfillment_matrix/`.

## Blockers to live scoring

| Blocker | Why it matters | Required remediation |
|---|---|---|
| Eligibility table pending review | The requested population is source-backed but not yet approved for scoring. | Review the 227 decisions and identity crosswalk, then add reviewer and timestamp metadata without changing the deterministic eligibility rule. |
| No reviewed player-role assignments | Strong production does not prove that a team need was fulfilled. | Add role code, evidence, assignment source, reviewer, date, and confidence. |
| ESPN/PBPStats identity mismatch | Direct numeric joins drop players because the namespaces differ. | Add and test an explicit one-to-one crosswalk before using roster/DNP context. |
| Impact feed lags player-game feed | Recent opportunity and stale impact are not comparable on one clock. | Rebuild to a shared cutoff or keep impact evidence-only with lag labels. |
| True player on/off not materialized | On-court net rating is not on-minus-off impact. | Validate a separate possession/lineup pipeline after the prototype is approved. |
| Role thresholds unvalidated | Fixture floors/targets only prove plumbing. | Basketball review plus hand-calculated validation set. |

## Test plan

| Layer | Covered now | Promotion additions |
|---|---|---|
| Contracts | Missing columns, missing sources, fixture-only mode, live block | Duplicate eligibility IDs, incomplete candidate coverage, source-citation format. |
| Funnel | Contender, reviewed eligibility, valid assignment, games, possessions | Boundary ranks, trades, two-team players, cutoff mismatch. |
| Metrics | Recompute rates from counts, recent/baseline separation | Zero denominators, overtime, traded-player team windows. |
| Scores | Independent dimensions, formula version, stability/performance separation | Hand-calculated reviewer set, role thresholds, sensitivity analysis. |
| Evidence | Source, windows, denominators, safeguards | Cross-source lag and crosswalk quality labels. |
| Web | Exact bundle, direct-file payload, null-safe score formatting, unavailable-point omission, safe text rendering, accessible dialog | Browser keyboard, contrast, and print QA. |
| Workflow | Manual-only, fixture config, no commit/push | Protected review gate before any live job is introduced. |
| Isolation | No forecast path changes | Retain as a permanent regression check. |
