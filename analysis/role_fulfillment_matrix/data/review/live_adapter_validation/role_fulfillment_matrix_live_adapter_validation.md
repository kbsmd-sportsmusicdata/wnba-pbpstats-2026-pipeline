# Role Fulfillment Matrix — PBPStats Live Adapter Validation

Review status: **approved**

Approved by: **Krystal Beasley**

Approval date: **2026-08-22**

Live output remains disabled. This package validates the adapter boundary only.

## Source and grain

- Source: PBPStats 2026 regular-season player and team game logs
- Source player rows: 5,483
- Canonical participating rows: 5,482
- Explicit non-participation exclusions: 1
- Coverage through: 2026-08-22
- Canonical grain: unique `player_id + game_id`

## Gate result

**Adapter status: `review_ready`.**

- Reviewed assignments matched: 37 of 37
- Reviewed-player refresh failures: 0
- Global refresh failures: 2
- Locked parity matches: 11 of 11
- Maximum locked-field difference: 0.000000000
- Locked parity window: 2026-08-07 through 2026-08-20

Warnings:
- 2 unrelated player refresh failures do not affect reviewed-role coverage

## Automated checks

| Check | Status | Observed | Expectation |
|---|---|---:|---|
| `player_game_key_uniqueness` | **pass** | 5482 | 0 duplicate player-game keys |
| `team_game_join_coverage` | **pass** | 5482 | 5482 expected |
| `nonparticipation_exclusion` | **pass** | 1 | zero-minute rows without possession evidence |
| `possession_identity` | **pass** | 5482 | total_poss equals off_poss plus def_poss |
| `manifest_freshness` | **pass** | 2026-08-22 | recent end 2026-08-21 |
| `manifest_source_date_consistency` | **pass** | 2026-08-22 | manifest coverage 2026-08-22 |
| `reviewed_assignment_coverage` | **pass** | 37 | 37 expected |
| `reviewed_candidate_refresh_failures` | **pass** | 0 | must be zero |
| `manifest_failure_ledger_consistency` | **pass** | 2 | manifest declares 2 |
| `global_refresh_failures` | **warn** | 2 | allowed only outside reviewed population |
| `locked_11_player_parity` | **pass** | 11 | 11 expected |

## Eleven-player parity

| Player | Role | Fields | Maximum difference | Match |
|---|---|---:|---:|---|
| Isobel Borlase | `downhill_pressure_wing` | 15 | 0.000000000 | yes |
| Madina Okot | `interior_finisher_rim_runner` | 15 | 0.000000000 | yes |
| Makayla Timpson | `interior_finisher_rim_runner` | 15 | 0.000000000 | yes |
| Angel Reese | `interior_hub_rebounder` | 15 | 0.000000000 | yes |
| Caitlin Clark | `lead_creator` | 15 | 0.000000000 | yes |
| Olivia Miles | `lead_creator` | 15 | 0.000000000 | yes |
| Janelle Salaun | `perimeter_scorer_spacer` | 15 | 0.000000000 | yes |
| Kaitlyn Chen | `secondary_creator_connector` | 15 | 0.000000000 | yes |
| Mai Yamamoto | `secondary_creator_connector` | 15 | 0.000000000 | yes |
| Marine Fauthoux | `secondary_creator_connector` | 15 | 0.000000000 | yes |
| Pauline Astier | `secondary_creator_connector` | 15 | 0.000000000 | yes |

## Zero-omitted-count decision

Only allowlisted additive statistics are filled with zero. Offensive and defensive possessions are filled only after participation is established; total possessions must reconcile exactly. Identities, dates, game ids, team affiliations, minutes, and team-game possessions are never imputed.

## Reviewer decision

Approval is recorded and permits wiring this reviewed adapter into a still-disabled live pipeline. It does not publish, schedule, or enable live output.
