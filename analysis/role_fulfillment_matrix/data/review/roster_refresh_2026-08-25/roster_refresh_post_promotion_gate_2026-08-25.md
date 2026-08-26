# Role Fulfillment Matrix — Post-Promotion Gate Report

Review date: **2026-08-25**

Roster promotion status: **approved and promoted**
Live pipeline status: **blocked at downstream review gates**
Scheduling status: **disabled**

## Dataset and grain

The promoted player core is a 237-row ESPN identity dimension. It preserves historical inactive
and free-agent identities while using the August 25 ESPN team pages for current active membership,
team affiliation, and position. The current standings cutoff is August 23.

## Gate results

| Gate | Result | Evidence | Interpretation |
|---|---|---|---|
| Base freshness | Pass | Oldest/newest source date `2026-08-25`; standings cutoff `2026-08-23`; one snapshot | The August 22 freshness blocker is resolved. |
| Base uniqueness | Pass | 237 rows; 237 unique ESPN athlete IDs | No duplicate identity grain. |
| Current membership | Pass | 211 active, 6 inactive, 20 free agents | Dantas is inactive with Indiana; Bonner is a free agent without affiliation. |
| Reviewed eligibility identities | Pass | 235 rows; 235 unique player IDs and ESPN IDs; all reviewed | The refreshed identities plus Kara Dunn are reviewed under `experience_years <= 3`. |
| Current PBPStats eligibility coverage | Pass | 229/229 unique PBPStats players covered | No current PBP player is silently dropped for missing eligibility. |
| Full active-roster eligibility | Pass | 211/211 active ESPN roster identities covered | Kara Dunn is reviewed as eligible; Phoenix remains outside the current contender funnel. |
| Top-six role coverage | Pass | 36/36 active eligible contender players have reviewed roles | Buenavida and Balogun have reviewed roles but remain sample-suppressed without PBPStats records. |
| PBPStats live-adapter audit | Pass | 38/38 reviewed assignments matched; 0 reviewed-player and 0 global refresh failures; 11/11 locked parity matches | The incremental retry refreshed all three prior failures, including Antonia Delaere, and the adapter returned `review_ready`. |
| Scheduling | Pass | `scheduling_enabled = false`; no workflow invokes the live builder | No recurring live execution is authorized. |

## Approved roster decisions

- Damiris Dantas remains affiliated with Indiana and is marked inactive, preserving her reviewed
  context while suppressing live scoring.
- DeWanna Bonner is marked free-agent with no team affiliation after the August 24 Mercury
  contract buyout.
- Kiana Williams is active with Toronto.
- Michelle Onyiah is recorded at center; Morgan Maly is recorded at guard.
- Christyn Williams, Elena Buenavida, and Elizabeth Balogun have reviewed ESPN-only eligibility
  identities. Their placeholder IDs must be reconciled if they later appear in PBPStats.

## Remaining actions before another manual live run

Resolved on August 25–26:

1. Kara Dunn was approved as eligible and remains outside the top-six contender pool.
2. Elena Buenavida and Elizabeth Balogun received reviewed primary roles with current-team sample
   safeguards.
3. The end-to-end dry run was approved with 10 scored, five season-context, and three
   inactive-suppressed results. Scheduling remains a separate, unapproved gate.

## Source notes

- ESPN roster-page snapshot and per-page hashes:
  `espn_roster_pages_2026-08-25.json`.
- Promotion evidence and output hashes:
  `roster_refresh_promotion_manifest_2026-08-25.json`.
- Damiris Dantas status source:
  `https://fever.wnba.com/news/damiris-dantas-injury-update`.
- DeWanna Bonner status source:
  `https://ca.sports.yahoo.com/news/mercury-buy-dewanna-bonner-contract-214605380.html`.
