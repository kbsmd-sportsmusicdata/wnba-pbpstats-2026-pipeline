# Injury / Availability Report

A shared availability layer for the rest of the pipeline. The raw ESPN injury feed carries one row
per (injury, snapshot date) in ESPN's own status vocabulary and on ESPN's `athlete_id`. This module
turns it into a single current answer to two questions — *is this player available, and is the
absence a real injury or roster housekeeping?* — and bridges it onto the pbpstats `player_id` every
other analysis runs on.

## What it produces

`data/processed/`

| File | Grain | What it is |
|---|---|---|
| `injury_report_current_2026.csv` | player | Most recent snapshot, one row per player: normalized `availability_status`, injury type/side, expected return, resolved `player_id` |
| `team_availability_2026.csv` | team | Current rollup — counts out / out-for-season / day-to-day, injury vs non-injury, names |
| `injury_report_history_2026.csv` | player × snapshot | Every snapshot in the feed, normalized, for trend work |
| `forecast_availability_context_2026.csv` | team | Playoff-forecast odds beside current injury load, with a health flag (see below) |
| `run_manifest_2026.json` | run | Source manifest, config hash, id-match rate, availability stats |

## Key derived fields

- **`availability_status`** — ordered `Out for season` > `Out` > `Day-to-day`, collapsed from ESPN's
  `status` and `detail_fantasy_status` (`OFS` → out for season, `GTD` → day-to-day). When a player
  carries several active listings on the current date, the most limiting one wins.
- **`absence_category`** — `injury` (Knee, Ankle, Illness, Concussion, …) vs `non_injury` (Personal,
  Coach's Decision, Rest, Not Injury Related — e.g. FIBA World Cup call-ups). A season-ending knee
  creates durable opportunity for a backup; a one-game coach's decision does not, and consumers can
  weight the two differently.
- **`pbpstats_player_id`** — resolved through the reviewed role-fulfillment crosswalk by exact ESPN
  `athlete_id`, then by normalized name (`player_id_match` records which). Players with no numeric
  pbpstats id (deep-bench / international, who never clear an analysis eligibility gate) are kept with
  a null id rather than dropped.

## Running

```bash
python scripts/build_injury_report.py \
  --config analysis/injuries/config/injuries_config.json
```

Options: `--injuries-path`, `--crosswalk-path`, `--output-root`. CI equivalent is the **Injury
Report** workflow.

### Forecast × availability companion

```bash
python scripts/build_forecast_availability_context.py \
  --config analysis/injuries/config/forecast_availability_config.json
```

This joins the standings / playoff forecast's own output (`forecast_summary.csv`, on the shared ESPN
`team_id`) to the current injury report and writes `forecast_availability_context_2026.csv` —
projected seed and playoff odds beside each team's injury load, minutes-weighted from the game layer,
with an `availability_flag` (`Healthy` / `Minor absences` / `Key player lost for season` / `Depleted`
/ `Depleted contender`, the last reserved for teams still live in the playoff race). It reads the
forecast's committed output only; it does not touch the Monte Carlo simulation or its renderers, and
produces nothing when either the forecast or the feed is absent.

## Two things to keep in mind

- **Counts only at the team level.** `team_availability_2026.csv` is deliberately count-based. A
  minutes- or usage-weighted *how much does this actually hurt* belongs to the analysis that owns
  those weights (hidden value, functional depth), not to the shared feed.
- **Never a hard dependency.** The feed is optional everywhere it is read: a downstream build with the
  parquet missing writes an `injuries_missing` status and continues on its existing inputs rather than
  failing. Availability is context layered on top of the existing analyses, not a new prerequisite.
