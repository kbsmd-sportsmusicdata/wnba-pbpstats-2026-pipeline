# Role Fulfillment Matrix — Base Roster Refresh Review

Review status: **pending**

Source as of: **2026-08-25**
Standings cutoff: **2026-08-23**
ESPN team pages: **15**
Current active roster entries: **211**
Candidate identity rows: **237**

## Refresh method

The candidate overlays the current ESPN team-roster pages onto the historical player-core identity universe. Existing free-agent and inactive identities are retained. A player who was active in the prior input but is absent from every current ESPN team page is made inactive in the candidate with `pending-roster-review`; absence alone is not treated as proof of free-agent or inactive-rostered status.

## Material changes

| Change | Player | ESPN ID | Prior | Candidate | Review |
|---|---|---:|---|---|---|
| activated | Kiana Williams | 4282168 | False | True | pending |
| added_active | Christyn Williams | 4398965 | — | active | pending |
| added_active | Elena Buenavida | 5208984 | — | active | pending |
| added_active | Elizabeth Balogun | 4398589 | — | active | pending |
| position_changed | Michelle Onyiah | 4433744 | F-C | C | pending |
| position_changed | Morgan Maly | 4599199 | F | G | pending |
| removed_from_active_page | Damiris Dantas | 2955898 | active | pending-roster-review | pending |
| removed_from_active_page | DeWanna Bonner | 869 | active | pending-roster-review | pending |
| team_changed | Kiana Williams | 4282168 | 6 | 131935 | pending |

## Promotion blockers

- new active identities require eligibility review
- players removed from the active roster page require status review
- all material roster changes require explicit approval before promotion

## Source pages

| Team | Team ID | Players | Generated at (UTC) | Source | Page SHA256 |
|---|---:|---:|---|---|---|
| Atlanta Dream | 20 | 14 | 2026-08-25T23:21:30Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/atl) | `50cd6df5af7162b6701ff5bad59c9c8fe96046f8fc51dff1e8e7ccd6a088bf3c` |
| Chicago Sky | 19 | 14 | 2026-08-25T23:21:31Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/chi) | `8933a72193a5d613658bbe819e302d100701547fe50cdc2ef61b133e194c1e25` |
| Connecticut Sun | 18 | 14 | 2026-08-25T23:21:31Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/con) | `b79af2c7ba39a74475d214d7e677de805394ebffc551f56fe0bd8372e77bff67` |
| Dallas Wings | 3 | 15 | 2026-08-25T23:21:31Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/dal) | `8ab2a1bd1237e7ef06bada6e8a9096ee6f3cab711ee67f8c1f012c0364b7dc99` |
| Golden State Valkyries | 129689 | 15 | 2026-08-25T23:21:31Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/gs) | `f8832aa7646c0767199279e07e946cc92ebbb56318a3250ce6344c0b95fc0378` |
| Indiana Fever | 5 | 14 | 2026-08-25T23:21:31Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/ind) | `fcbeee38e3c22650dd3cecf03a15c951bf53df468df7fc00c340d5e782cbafa1` |
| Las Vegas Aces | 17 | 13 | 2026-08-25T23:21:31Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/lv) | `128a35d5e6ed86c9171daf60debca23b1f00c6bd6e41f027f9d195d39be0b0e9` |
| Los Angeles Sparks | 6 | 13 | 2026-08-25T23:21:32Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/la) | `b1808d1078d6d411cfda066788a45a020ed2d4b249b00865557563a3d6133263` |
| Minnesota Lynx | 8 | 14 | 2026-08-25T23:21:32Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/min) | `c7b5c2e24b575da37237b4b77ae14cf673c73811c972d2859e33c47472b2ba60` |
| New York Liberty | 9 | 14 | 2026-08-25T23:21:33Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/ny) | `68e9a9bd463607c107b168e7a9b4d1e1fd7536eb4e793104aab3d5a0e4097dd5` |
| Phoenix Mercury | 11 | 14 | 2026-08-25T23:21:33Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/phx) | `34eed76b83e213db2c53c55d78cba379e1759661fec51e982419042835f67dd7` |
| Portland Fire | 132052 | 15 | 2026-08-25T23:21:33Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/por) | `ce380fc581eb0be0e3dbecf1864e6f2055900c7699fcb6ae94bac89119377966` |
| Seattle Storm | 14 | 13 | 2026-08-25T23:21:33Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/sea) | `69b218e5339cbf77a3c69cc487d85e93340affbd8402b9d49566508e076ff047` |
| Toronto Tempo | 131935 | 15 | 2026-08-25T23:21:34Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/tor) | `0491c41459ef86abecf5be5a936e1a24450ae67980a335d8fda37a53706349ef` |
| Washington Mystics | 16 | 14 | 2026-08-25T23:21:34Z | [ESPN roster](https://www.espn.com/wnba/team/roster/_/name/wsh) | `d821c945dfdd79d6f7bce9163702f1cf97e04f28afbc544bc8219151e04834cb` |

## Required review decisions

1. Review every new active identity before extending eligibility coverage.
2. Classify each prior active player absent from the current pages as inactive-rostered, free-agent, or another sourced status.
3. Approve affiliation and position changes before replacing the live base snapshot.
4. After approval, rebuild the base input, retire only redundant addenda, and rerun the freshness and coverage gates with scheduling still disabled.
