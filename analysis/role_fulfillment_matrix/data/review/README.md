# Eligibility Review Package

This directory preserves the real 2026 identity and experience review evidence. The approved
eligibility table is `../../config/player_eligibility_2026.csv`.

## Review summary

- PBPStats players through 2026-08-20: 227
- Exact normalized-name matches to ESPN player core: 227
- Crosswalk coverage: 100%
- Eligible under `experience_years <= 3`: 120
- Ineligible: 107
- ESPN source-only records without a PBPStats game: 5
- Eligibility review status: reviewed on 2026-08-22 by Krystal Beasley
- Live scoring status: blocked

## Reviewer checklist

1. Confirm each matched ESPN identity belongs to the listed PBPStats player.
2. Review all players with `experience_years` equal to 3 or 4, because they sit at the eligibility
   boundary.
3. Confirm the five `source_only` records are correctly excluded for having no PBPStats game row at
   the cutoff.
4. Confirm the ESPN experience convention is acceptable for the approved `<= 3` rule.
5. Do not change `eligible_flag` manually. Correct source facts and rebuild if a value is wrong.
6. The reviewed promotion and its hash are recorded in
   `eligibility_approval_manifest_2026.json`; do not overwrite the pending snapshot.

The experience/eligibility, original player-role review, formula, 11-player validation, and
PBPStats live-adapter review gates are complete. The adapter now runs only in the isolated
`live_dry_run` path. Live publishing remains disabled pending review of that report and a reviewed
primary role for every current contender candidate.
