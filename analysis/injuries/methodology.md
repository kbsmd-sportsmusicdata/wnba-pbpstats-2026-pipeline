# Injury / Availability Report — methodology

## Source

The raw feed (`data/raw/injuries/injuries_2026.parquet`) is the ESPN WNBA injury report, captured as
a series of daily snapshots (`as_of_date`). Each row is one injury listing for one athlete on one
date, keyed on ESPN `athlete_id` / `team_id`. ESPN splits status across three columns:

- `status` — `Out` / `Day-To-Day`
- `type_name` — `INJURY_STATUS_OUT` / `INJURY_STATUS_DAYTODAY`
- `detail_fantasy_status` — `OUT` / `OFS` (out for season) / `GTD` (game-time decision)

plus a free-text reason (`detail_type`, e.g. Knee, Personal, Coach's Decision), side, injury date,
expected return date and short/long comments.

## Normalization

**Availability status.** The three status columns are collapsed to one ordered label:

| `availability_status` | Rule | Means |
|---|---|---|
| `Out for season` | `detail_fantasy_status == OFS` | Ruled out for the remainder of 2026 |
| `Day-to-day` | `GTD`, or `status` in {Day-To-Day, questionable, doubtful} | Listed but may play |
| `Out` | everything else on the feed | Unavailable for the next game |

`detail_fantasy_status` is consulted first because it carries the sharpest read (`OFS`/`GTD` are
distinctions `status` alone loses). An unrecognized code resolves to `Out`, never dropped: a player
on the injury feed is by definition not fully available, and discarding an unknown status would
silently overstate a roster.

**Absence category.** `detail_type` is classified as `injury` unless it is roster housekeeping —
`Not Injury Related` (typically FIBA World Cup / national-team duty in this window), `Personal`,
`Coach's Decision`, or `Rest` — which map to `non_injury`. This is the field that lets a consumer
treat a season-ending knee (durable opportunity for a backup) differently from a one-game absence.

**Current view.** `injury_report_current_2026.csv` filters the feed to the most recent `as_of_date`
and keeps one row per athlete. When an athlete has multiple active listings on that date, ties break
on the most limiting `availability_status`, then the more recent `injury_date`.

## Identity resolution

The feed's `athlete_id` is ESPN's id space; every downstream analysis runs on the pbpstats
`player_id` (`entity_id`) space. The bridge is the reviewed crosswalk the role-fulfillment matrix
maintains (`analysis/role_fulfillment_matrix/config/player_eligibility_2026.csv`), which pairs
`player_id` with `espn_athlete_id`:

1. exact `espn_athlete_id` match (`player_id_match = espn_athlete_id`);
2. normalized-name fallback — NFKD accent-fold, lowercase, strip non-alphanumerics
   (`player_id_match = normalized_name`);
3. otherwise `unmatched`, kept with a null `pbpstats_player_id`.

On the current feed this resolves ~93% of listed players. The unresolved remainder are deep-bench and
international players with no pbpstats game record, who do not clear the possession/games eligibility
gates in any consuming analysis, so leaving their id null costs nothing downstream.

## Team abbreviations

ESPN `team_id` → repo abbreviation is a fixed reference map for the 15 franchises (including the 2026
expansion teams: Golden State `GSV`, Toronto `TOR`, Portland `PDX`), with a team-display-name fallback
so a reissued id or renamed team still resolves.

## Scope and limits

- **Team rollup is count-based** by design; weighted "cost of absence" is left to the consuming
  analysis, which owns the minutes/usage.
- **Descriptive, not predictive.** The report states current status; it does not forecast return
  dates or model the on-court effect of an absence. Expected return dates are ESPN's, passed through.
- **Snapshot-bound.** "Current" is the latest `as_of_date` in the committed feed. Refreshing the
  parquet (and re-running the build) is what advances it.
