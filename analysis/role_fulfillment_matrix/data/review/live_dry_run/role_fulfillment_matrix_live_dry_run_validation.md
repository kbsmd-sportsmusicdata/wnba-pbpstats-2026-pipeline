# Role Fulfillment Matrix — Live Dry-Run Validation

Review status: **approved by Krystal Beasley, 2026-09-29**

Regenerated 2026-09-30 to carry the corrected Alicia Florez ESPN athlete_id (5208985); the analytical package (scores, counts, and statuses) is unchanged from the 2026-09-29 approval.

Live output remains disabled. This package exercises the approved real-data path only.

## Run boundary

- Analysis mode: `live_dry_run`
- Formula version: `rfm-live-v1`
- Analysis cutoff: 2026-09-23
- Baseline window: 2026-08-26 through 2026-09-08
- Recent window: 2026-09-09 through 2026-09-22
- Players considered: 244
- Candidates included: 23
- Players with all three scores: 7
- End-to-end gate status: `review_ready`

Candidate outcomes (23 included):

- `dry_run_scored`: 7
- `season_context_only`: 12
- `inactive_suppressed`: 2
- `unavailable`: 1
- `insufficient_role_evidence`: 1

## Source gate

- PBPStats adapter status: `review_ready`
- Reviewed assignment coverage: 50 of 50
- Locked 11-player parity: 11 of 11
- Maximum parity difference: 0.000000000
- Locked parity window: 2026-08-07 through 2026-08-20
- Zero-omitted cells filled: 28589 across allowlisted additive fields
- Reviewed-player refresh failures: 0
- Global refresh failures: 0

Warnings:
- 2 reviewed ESPN-only role assignments are sample-suppressed until a reviewed PBPStats identity is available

## Deferred inactive role reviews

- Janiah Barker (LVA): role assignment deferred while inactive; reactivation restores the review blocker.

## Review outcome

- Candidate affiliation, sample status, scores, and evidence provenance reviewed and approved by Krystal Beasley, 2026-09-29.
- This approval covers the dry-run package only; explicit live-output enablement remains a separate gate and is not granted here.
- No schedule, commit, forecast-dashboard integration, or publishing occurs here.
