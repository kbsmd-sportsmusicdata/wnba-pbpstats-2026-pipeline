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
| Age/experience eligibility | `eligibility_type`, `age_on_cutoff`, `experience_years`, `eligible_flag`, review metadata | Available / reviewed | ESPN player core covers all 227 PBPStats players; the deterministic `experience_years <= 3` decisions were reviewed on 2026-08-22. |
| Player identity | `player_id`, `player_name`, `team_abbreviation` | Available | PBPStats key is canonical. ESPN identity requires a reviewed crosswalk. |
| Opportunity level | `minutes`, `off_poss`, `team_possessions`, games | Available / derivable | Recompute MPG and possession share from player-game counts. |
| Opportunity change | recent and baseline possession share | Derivable | Recent minus baseline; keep both windows and denominators. |
| Role assignment | `role_code`, optional `secondary_role_code`, `assignment_confidence`, reviewer metadata | Available / reviewed | Thirty-six roster-attached eligible players on top-six contenders have reviewed six-role assignments. Three confirmed free agents are excluded from the current assignment pool. |
| Creator behavior | assists, offensive possessions | Available / derivable | `75 * assists / off_poss`. |
| Rim behavior | rim attempts, total FGA | Available / derivable | Rim-attempt share and rim accuracy. |
| Perimeter behavior | three-point attempts, total FGA | Available / derivable | Three-point attempt share from additive game-level counts. |
| Interior rebounding | total and offensive rebounds, total and offensive possessions | Available / derivable | Rebounds per 75 total possessions and offensive rebounds per 75 offensive possessions. |
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

## Approved live role registry

`config/role_definitions_live_v1.json` contains the approved `rfm-live-v1` formulas for Lead
Creator, Secondary Creator / Connector, Perimeter Scorer / Spacer, Downhill Pressure Wing,
Interior Finisher / Rim Runner, and Interior Hub / Rebounder. Every component declares its source
denominator and a minimum denominator. The two-role fixture registry remains for regression tests;
the approved six-role registry is used only by the isolated `live_dry_run` path until final review.

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
2. Only fixture and approved `live_dry_run` modes may load sources; `live` publishing fails closed.
3. Missing required evidence produces `unavailable`; it is never replaced by zero, 50, or league
   average.
4. Rates are recomputed from summed numerators and denominators, not averaged from per-game rates.
5. The contender rule is config-versioned; adjacent baseline and recent windows are derived from
   the validated standings cutoff using the configured day counts and lag.
6. Eligibility and assignment review status are hard funnel gates.
7. Role codes must exist in the role registry.
8. Recent scoring requires at least three games and 100 offensive possessions in the approved window.
9. Players with at least 500 season offensive possessions may remain visible as
   `season_context_only` when the recent gate fails; no recent-form score is calculated.
10. `season_possessions_met`, `recent_games_met`, and `recent_possessions_met` remain separate
    flags so season volume never masquerades as recent evidence.
11. Free agents are excluded without deleting eligibility history; inactive rostered players keep
    their role with `inactive_suppressed` scoring status.
12. Stability describes confidence, not direction or quality of performance.
13. Every score row carries `score_status`, `coverage_pct`, `formula_version`, and `analysis_mode`.
14. Every evidence row carries source, window, denominator, and safeguard text.
15. Fixture output is labeled in the page, payload, processed tables, and manifest.
16. Lagging RAPM/on-court context is excluded from headline fixture scores.
17. Dry-run outputs are confined to
    `analysis/role_fulfillment_matrix/data/review/live_dry_run/`.
18. Assignment confidence below `0.50` suppresses all three scores.
19. A role-specific denominator failure sets Fulfillment to `insufficient_role_evidence` while
    leaving valid Opportunity and Stability scores available.
20. Live-v1 validation uses an independent locked expected-score table and a plus/minus 10% shift
    of every metric threshold band.
21. PBPStats blanks become zero only for allowlisted additive counts after participation is
    established; structural fields are never imputed.
22. The adapter excludes zero-minute rows only when all possession evidence is absent.
23. Player-game and team-game keys must be unique, every player row must join one team-game row,
    and total possessions must equal offensive plus defensive possessions.
24. Global refresh failures are warnings only when no reviewed-role player is affected; a reviewed
    candidate failure blocks the adapter gate.
25. ESPN standings codes are explicitly normalized to PBPStats codes before contender joins.
26. Current roster affiliation comes from the reviewed ESPN identity crosswalk and a roster snapshot
    no older than the standings cutoff.
27. Player metrics remain at player-team grain and join the funnel on both player and current team;
    an assignment for a prior team is excluded as `role_assignment_team_mismatch`.
28. Every real-data score is labeled `live_dry_run` / `dry_run_scored`; fixture labels are forbidden
    in the dry-run payload and dashboard.

## Blockers to live scoring

| Blocker | Why it matters | Required remediation |
|---|---|---|
| Eligibility promotion completed | The requested population now has source-backed, reviewed decisions. | Retain the pending snapshot, approval manifest, and one-to-one crosswalk as immutable review evidence. |
| Player-role assignments completed | Thirty-seven roster-attached candidates have reviewed primary roles; optional secondary roles remain unscored. | Preserve the reviewed registry and approval manifest. |
| ESPN/PBPStats identity crosswalk completed | All reviewed eligibility rows map through the approved ESPN identity field. | Preserve uniqueness and full reviewed-player coverage checks. |
| Impact feed lags player-game feed | Recent opportunity and stale impact are not comparable on one clock. | Rebuild to a shared cutoff or keep impact evidence-only with lag labels. |
| True player on/off not materialized | On-court net rating is not on-minus-off impact. | Validate a separate possession/lineup pipeline after the prototype is approved. |
| Live-v1 validation completed | All 11 production calculations match the locked expected values; sensitivity movement is at most 10 points, with two adjacent-band crossings. | Preserve the approved report and locked expected table. |
| Live adapter review completed | The adapter passes freshness, zero-omission, 37-player coverage, team-join, and 11-player parity checks. | Preserve these checks on every dry run. |
| End-to-end dry-run review | Real contender, roster, window, funnel, score, evidence, and UI paths passed review, including corrected live provenance labels. | Preserve the approved dry-run artifacts and hashes in `data/review/live_output_approval_manifest_2026.json`. |
| Manual live run completed | The standalone live path produced 11 scored, five season-context-only, and three inactive-suppressed results with live provenance. | Keep scheduling disabled until a separate scheduling review. |

## Test plan

| Layer | Covered now | Promotion additions |
|---|---|---|
| Contracts | Missing columns/sources, fixture, dry-run, explicit manual-live authorization, scheduling block, cutoff-derived windows | Preserve manual-only defaults until a separate scheduling review. |
| Funnel | Contender, eligibility, assignment, current affiliation, inactive suppression, sample fallback, trades, and two-team players | Final reviewer inspection of the current real cohort. |
| Metrics | Counts, recent/baseline separation, zero denominators, and current-team windows | Preserve parity after future source refreshes. |
| Scores | Independent dimensions, formula version, stability/performance separation, 11-player hand calculations, threshold sensitivity | Approved; preserve regression coverage. |
| PBPStats adapter | Zero-omitted counts, participation gate, unique keys, possession identity, team-game joins, candidate failures, freshness, 11-player parity | Preserve on every dry run. |
| Evidence | Source, windows, denominators, safeguards | Cross-source lag and crosswalk quality labels. |
| Web | Exact bundle, direct-file payload, null-safe score formatting, unavailable-point omission, safe text rendering, accessible dialog | Browser keyboard, contrast, and print QA. |
| Workflow | Manual-only fixture, dry-run, and live jobs; separate artifacts; no RFM schedule | Add scheduling only after a separate post-run approval. |
| Isolation | No forecast path changes | Retain as a permanent regression check. |
