# Role Fulfillment Matrix — Current-Standings Manual Live-Run Post-Review

Review status: **approved**

Owner approval: **approved by Krystal Beasley on 2026-09-30**

Scheduling status: **disabled and outside this approval**

## Technical summary

This is the second explicitly approved manual Role Fulfillment Matrix live run. It publishes live
output for the current 244-row 2026-09-28 roster against the 2026-09-23 standings cutoff, following
the merged dry-run approval for the same roster. It does **not** overwrite or supersede the immutable
2026-08-23 baseline manual run (`manual_live_run`), which retains its recorded hashes; the new run is
recorded separately under `current_standings_manual_live_run` with its own isolated output directory
(`analysis/role_fulfillment_matrix/live/runs/2026-09-30T033842Z/`).

This recommendation approves the completed manual run only. It does not approve recurring execution,
a GitHub Actions workflow, or any forecast-dashboard integration.

## Reviewed run boundary

- Run generated: 2026-09-30 03:38:43 UTC
- Manual run id: `2026-09-30T033842Z`
- Formula: `rfm-live-v1`
- Analysis cutoff: 2026-09-23
- Baseline window: 2026-08-26 through 2026-09-08
- Recent window: 2026-09-09 through 2026-09-22
- PBPStats and roster coverage: through 2026-09-24
- Roster source as-of: 2026-09-28 (244 rows, 218 active)
- Execution contract: `manual_only`; `scheduling_enabled = false`

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| Approved configuration | **Pass** | Recomputed live-config fingerprint `ab66f6fe921351cef308beffe0014262dabb54b2e1b6ce95834cafa5230ce623` matches the approval manifest. |
| Result population | **Pass** | 23 included candidates: 7 `live_scored`, 12 `season_context_only`, 2 `inactive_suppressed`, 1 `unavailable`, 1 `insufficient_role_evidence`. |
| Live/dry-run parity | **Pass** | Same 23-candidate population and 7 scored players as the merged 244-roster dry run; only the intended `live` / `live_scored` provenance labels differ. |
| Role safeguards | **Pass** | Reviewed six-role assignments only; the three assignments below the 0.50 confidence floor remain season-context-only. |
| Eligibility | **Pass** | 242 reviewed eligibility rows; current PBPStats population fully covered. |
| Funnel integrity | **Pass** | 244 players considered; the 23 included keys match the 23 output rows exactly. |
| Adapter quality | **Pass with warning** | Candidate coverage 50 of 50; locked parity 11 of 11 (max absolute difference `4.878044634892831e-10`); zero candidate, global, and manifest refresh failures; empty failure ledger; coverage through 2026-09-24. |
| Sample suppression | **Pass** | 2 reviewed ESPN-only role assignments (`espn:4398589`, `espn:5208984`) are sample-suppressed until a reviewed PBPStats identity is available. |

## Identity note

Alicia Florez's ESPN athlete_id was corrected from `5349415` to `5208985` (ESPN reassignment) prior
to this run, so the published live artifacts carry the corrected id. Her PBPStats player_id
(`1643644`) and all statistics are unchanged, so her candidate status (season-context-only) and every
score in this run are identical to the reviewed dry run.

## Scope

This approval covers the completed 2026-09-30 manual run for the 244-row roster only. Recurring
execution, scheduling, GitHub Actions integration, and forecast-dashboard publishing all remain
disabled and outside this approval.
