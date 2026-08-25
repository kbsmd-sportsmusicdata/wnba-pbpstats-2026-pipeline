# Role Fulfillment Matrix — First Manual Live-Run Post-Review

Review status: **approved**

Owner approval: **approved by Krystal Beasley on 2026-08-24**

Scheduling status: **disabled and outside this approval**

## Technical summary

The first manual Role Fulfillment Matrix live run is approved as the immutable live-output baseline.
The review found no blocking discrepancy: all seven pinned live and dry-run artifacts retain their
approved hashes, the live configuration matches its approved fingerprint, the 19-player output
reconciles to the candidate funnel, and live scores match the approved dry run except for the
intended live provenance labels.

This recommendation approves the completed manual run only. It does not approve recurring
execution, a GitHub Actions workflow, or any forecast-dashboard integration.

## Reviewed run boundary

- Merged review commit: `f4385abbb8f5ee7c58f7aea0796832342f9d1524`
- Run generated: 2026-08-23 23:37:49 UTC
- Formula: `rfm-live-v1`
- Analysis cutoff: 2026-08-21
- Baseline window: 2026-07-24 through 2026-08-06
- Recent window: 2026-08-07 through 2026-08-20
- PBPStats and roster coverage: through 2026-08-22
- Execution contract: `manual_only`; `scheduling_enabled = false`

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| Immutable artifacts | **Pass** | Four live artifacts and three approved dry-run artifacts independently match their recorded SHA-256 hashes. |
| Approved configuration | **Pass** | Recomputed fingerprint `a013dbd8ca8387f3d84a5b9280228592fbf416a70c49f548f40aff7bb01aa782` matches the approval manifest. |
| Result population | **Pass** | 19 unique player-team rows: 11 `live_scored`, five `season_context_only`, and three `inactive_suppressed`. |
| Scored-row completeness | **Pass** | All 11 scored players have Fulfillment, Opportunity, and Stability values, 100% coverage, and the approved recent sample. |
| Season fallback | **Pass** | All five season-context players meet 500 season offensive possessions, fail the recent-possession minimum, and have no live score. |
| Inactive suppression | **Pass** | All three inactive rows remain visible and have all scores suppressed. |
| Role safeguards | **Pass** | All 37 reviewed assignments are unique and use the approved six-role registry; no assignment below 0.50 confidence is scored. |
| Eligibility | **Pass** | All 229 eligibility rows are unique and reviewed. |
| Funnel integrity | **Pass** | 232 unique player-team candidates; the 19 included keys match the 19 output keys exactly. |
| Evidence provenance | **Pass** | 113 evidence records cover only the 11 scored players, use reviewed live-source names, and contain no fixture provenance. |
| Live/dry-run parity | **Pass** | All 19 player-team keys and all score values match the approved dry run; only the intended `live` / `live_scored` labels differ. |
| Adapter quality | **Pass with warning** | 5,482 unique participating player-game rows, 5,482 of 5,482 team joins, exact possession identity, 37 of 37 reviewed-player coverage, and zero reviewed-candidate refresh failures. |
| Locked parity | **Pass** | 11 of 11 players match across 15 fields; maximum absolute difference is `4.878044634892831e-10`, with no missing fields. |
| Automated regression | **Pass** | 77 Role Fulfillment Matrix Python tests and three client tests pass from merged `origin/main`. |

## Data-quality interpretation

The adapter filled 23,485 omitted cells only in the approved additive-count allowlist after
participation was established. Identity, game, date, team, minutes, and team-possession fields were
not imputed. Total possessions reconcile to offensive plus defensive possessions for every
participating player-game row.

Two PBPStats refresh requests returned repeated HTTP 500 responses: Raegan Beers and Quionche
Carter. Neither player has a reviewed role assignment, both are outside the top-six contender
population in this run, and neither appears in the 19-row live output. The warning therefore does
not affect this approval, but the same failure must become blocking if a future refresh affects a
reviewed contender candidate.

## Known limitations

- The current model does not claim true on-minus-off impact; lagging impact context remains outside
  headline scoring.
- The approval manifest pins output artifacts and the reviewed configuration. The merged Git commit
  preserves this run's input files, but future scheduled runs should also record per-run input hashes
  or immutable snapshot identifiers directly in each run manifest.
- No cadence, retry policy, alert destination, retention policy, or automated rollback has been
  reviewed. Scheduling must remain disabled until those controls receive separate approval.

## Approval decision and next gate

**Approved decision:** the 2026-08-23 manual live run is the first accepted live-output baseline;
its pinned artifacts remain unchanged.

The next sequence gate is a separate scheduling design review. That review should define cadence
and cutoff timing, freshness thresholds, candidate-affecting failure
behavior, notifications, append-only retention, per-run input provenance, and the manual rollback or
disable procedure before any workflow is enabled.

## Evidence examined

- `analysis/role_fulfillment_matrix/data/review/live_output_approval_manifest_2026.json`
- `analysis/role_fulfillment_matrix/live/data/processed/run_manifest_2026.json`
- `analysis/role_fulfillment_matrix/live/data/processed/role_fulfillment_matrix_2026.csv`
- `analysis/role_fulfillment_matrix/live/data/processed/candidate_funnel_2026.csv`
- `analysis/role_fulfillment_matrix/live/data/processed/role_fulfillment_evidence_2026.json`
- `analysis/role_fulfillment_matrix/live/deliverables/role_fulfillment_matrix/data/role_fulfillment_payload.json`
- `analysis/role_fulfillment_matrix/data/review/live_adapter_validation/`
- `analysis/role_fulfillment_matrix/data/review/live_v1_validation/`
- `analysis/role_fulfillment_matrix/data/review/live_dry_run/`
