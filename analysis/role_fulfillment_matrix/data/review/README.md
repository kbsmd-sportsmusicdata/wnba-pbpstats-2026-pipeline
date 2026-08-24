# Eligibility Review Package

This directory preserves the real 2026 identity and experience review evidence. The approved
eligibility table is `../../config/player_eligibility_2026.csv`.

## Review summary

- PBPStats players through 2026-08-20: 227
- Exact normalized-name matches to ESPN player core: 227
- Crosswalk coverage: 100%
- Approved eligibility rows: 229 (227 PBPStats identities plus two reviewed ESPN roster-only
  identities)
- Eligible under `experience_years <= 3`: 121
- Ineligible: 108
- ESPN source-only records without a PBPStats game: 5
- Eligibility review status: original review approved on 2026-08-22; two-row roster-only addendum
  approved on 2026-08-23 by Krystal Beasley
- Live scoring status: enabled for approved manual execution; scheduling remains disabled

## Reviewer checklist

1. Confirm each matched ESPN identity belongs to the listed PBPStats player.
2. Review all players with `experience_years` equal to 3 or 4, because they sit at the eligibility
   boundary.
3. Confirm roster-only identities use reviewed `espn:<athlete_id>` placeholders until a PBPStats
   identity becomes available; the adapter must then fail closed pending a reviewed crosswalk.
4. Confirm the ESPN experience convention is acceptable for the approved `<= 3` rule.
5. Do not change `eligible_flag` manually. Correct source facts and rebuild if a value is wrong.
6. The reviewed promotion, two-row addendum, and their hashes are recorded in
   `eligibility_approval_manifest_2026.json`; do not overwrite the pending snapshot.

The experience/eligibility, player-role, formula, 11-player validation, PBPStats live-adapter, and
end-to-end dry-run gates are complete. The first approved manual live run completed on 2026-08-23;
its post-run evidence review and scheduling boundary are recorded in
`manual_live_run_post_review_2026-08-23.md`. Live execution remains manual-only, and no recurring
workflow is approved or enabled.
