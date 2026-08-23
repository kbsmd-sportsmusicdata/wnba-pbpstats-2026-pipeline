# Role Fulfillment Matrix — rfm-live-v1 Validation

Review status: **pending reviewer approval**

Live output remains disabled. This gate validates formulas and threshold behavior only.

## Validation scope

- Formula version: `rfm-live-v1`
- PBPStats player-game snapshot coverage: through 2026-08-21
- Reviewed recent window: 2026-08-07 through 2026-08-20
- Population: 11 reviewed-role players meeting 3 games and 100 offensive possessions
- Hand calculation tolerance: 0.00001 score points
- Sensitivity method: shift every metric floor and target by 10% of its threshold span

## Hand-calculation result

**11 of 11 production scores match the locked hand calculations.**

| Player | Role | Production | Hand calculation | Absolute difference |
|---|---|---:|---:|---:|
| Isobel Borlase | `downhill_pressure_wing` | 35.63 | 35.63 | 0.000000 |
| Madina Okot | `interior_finisher_rim_runner` | 38.91 | 38.91 | 0.000000 |
| Makayla Timpson | `interior_finisher_rim_runner` | 94.30 | 94.30 | 0.000000 |
| Angel Reese | `interior_hub_rebounder` | 82.06 | 82.06 | 0.000000 |
| Caitlin Clark | `lead_creator` | 82.24 | 82.24 | 0.000000 |
| Olivia Miles | `lead_creator` | 91.55 | 91.55 | 0.000000 |
| Janelle Salaun | `perimeter_scorer_spacer` | 54.49 | 54.49 | 0.000000 |
| Kaitlyn Chen | `secondary_creator_connector` | 71.44 | 71.44 | 0.000000 |
| Mai Yamamoto | `secondary_creator_connector` | 81.63 | 81.63 | 0.000000 |
| Marine Fauthoux | `secondary_creator_connector` | 40.88 | 40.88 | 0.000000 |
| Pauline Astier | `secondary_creator_connector` | 63.20 | 63.20 | 0.000000 |

## Threshold sensitivity result

- Maximum absolute score movement: **10.00 points**
- Median maximum movement: **5.50 points**
- Players crossing a descriptive score band: **2 of 11**
- No sensitivity scenario moves a player by more than one descriptive band.

Descriptive bands are review aids only: low `<50`, moderate `50–74.99`, high `>=75`.

| Player | Role | Lenient | Base | Strict | Max movement | Band changed |
|---|---|---:|---:|---:|---:|---|
| Janelle Salaun | `perimeter_scorer_spacer` | 64.49 | 54.49 | 44.49 | 10.00 | yes |
| Pauline Astier | `secondary_creator_connector` | 73.20 | 63.20 | 53.20 | 10.00 | no |
| Makayla Timpson | `interior_finisher_rim_runner` | 100.00 | 94.30 | 85.15 | 9.15 | no |
| Isobel Borlase | `downhill_pressure_wing` | 42.63 | 35.63 | 28.63 | 7.01 | no |
| Kaitlyn Chen | `secondary_creator_connector` | 78.44 | 71.44 | 64.44 | 7.00 | yes |
| Caitlin Clark | `lead_creator` | 87.74 | 82.24 | 76.74 | 5.50 | no |
| Madina Okot | `interior_finisher_rim_runner` | 43.41 | 38.91 | 35.00 | 4.50 | no |
| Angel Reese | `interior_hub_rebounder` | 84.86 | 82.06 | 77.76 | 4.30 | no |
| Mai Yamamoto | `secondary_creator_connector` | 85.63 | 81.63 | 77.63 | 4.00 | no |
| Marine Fauthoux | `secondary_creator_connector` | 43.88 | 40.88 | 40.00 | 3.00 | no |
| Olivia Miles | `lead_creator` | 94.05 | 91.55 | 89.05 | 2.50 | no |

## Safeguards verified

- Role-specific denominator failure suppresses Fulfillment only.
- Opportunity and Stability remain independently reportable when their evidence is valid.
- Assignment confidence below 0.50 suppresses all three scores.
- The live configuration remains fail-closed pending approval of this report.
- No composite score is calculated.

## Reviewer decision

Approve this validation to permit the next implementation gate: wiring the reviewed PBPStats adapter and live source checks. Approval does not by itself publish or schedule live output.
