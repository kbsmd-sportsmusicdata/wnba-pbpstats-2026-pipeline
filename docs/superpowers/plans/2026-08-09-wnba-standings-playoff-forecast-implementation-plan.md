# WNBA Standings & Playoff Forecast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a season-parameterized WNBA standings and playoff forecasting subsystem to `kbsmd-sportsmusicdata/wnba-pbpstats-2026-pipeline`, backed by a reusable multi-season normalized team-game layer and capable of producing one validated forecast bundle that powers an Excel analysis layer, broadcaster Markdown brief, one-page broadcast stat-pack insert, and interactive HTML playoff-race dashboard.

**Architecture:** Keep the repo's active SportsDataverse and PBPStats ingestion workflows as the upstream source of truth. Follow the repo's existing analysis pattern: a thin top-level builder under `scripts/`, an importable package under `scripts/standings_playoff_forecast/`, project configuration and deliverables under `analysis/standings_playoff_forecast/`, shared normalized season data under `data/processed/`, tests under `tests/`, and a dedicated GitHub Actions workflow. The forecast engine consumes normalized completed-game data, reproduces official standings/tiebreak ordering deterministically, derives team strength and remaining-schedule features, simulates final records and point margins, then writes standardized machine-readable outputs consumed by all four presentation artifacts.

**Tech Stack:** Python 3.11; pandas; numpy; pyarrow/Parquet; Python standard-library `json`, `dataclasses`, `statistics.NormalDist`, `hashlib`, and `unittest`; openpyxl for Excel rendering; vanilla HTML/CSS/JavaScript for the stat-pack and dashboard; GitHub Actions for reproducible builds.

## Global Constraints

- **Canonical repository:** `kbsmd-sportsmusicdata/wnba-pbpstats-2026-pipeline`.
- Preserve the active upstream source workflows:
  - `scripts/fetch_wnba_sportsdataverse_2026.py`
  - `scripts/pbpstats_2026_pull_clean.py`
  - `scripts/pbpstats_2026_features.py`
  - `.github/workflows/sportsdataverse-wnba-2026.yml`
  - `.github/workflows/pbpstats-wnba-2026.yml`
- Follow the repo-native analysis pattern demonstrated by `scripts/build_midseason_team_grades.py`, `scripts/midseason_team_grades/`, `analysis/midseason_team_grades/`, and `.github/workflows/midseason-team-grades.yml`.
- Do not duplicate or replace SportsDataverse/PBPStats ingestion logic inside the forecast package.
- The engine must not hardcode 2026 team count, regular-season game count, playoff qualifier count, or tiebreak sequence in model logic.
- Unknown seasons fail closed until an explicit verified season config exists.
- 2026 configuration must specify 15 teams, 44 regular-season games per team, eight playoff qualifiers, league-wide seeding, and the official WNBA tiebreak order.
- 2026 tiebreak order:
  1. head-to-head record;
  2. winning percentage against teams finishing .500 or better;
  3. head-to-head point differential;
  4. overall point differential.
- Multi-team ties restart from criterion 1 after one or more teams are eliminated at a step.
- Final-.500 membership must be recomputed inside each simulation.
- Simulated remaining games must generate non-zero point margins, not only W/L outcomes.
- Initial forecast season is 2026.
- The normalized team-game layer must support multiple seasons from V1.
- Historical context is optional. A 2026 forecast must run when no historical partitions exist.
- Historical model training is out of scope for V1.
- No presentation surface may independently calculate standings, tiebreaks, matchup probabilities, playoff probabilities, or rank probabilities.
- Core V1 predictive inputs must be reproducible from cutoff-safe game-level SportsDataverse data.
- PBPStats latest team features are optional current-snapshot enrichment/QA and must never be backfilled into historical dates.
- Default simulation count is 100,000.
- Fixed source snapshot + configs + cutoff + seed must produce deterministic simulation outputs.
- Every run records source/config/model provenance, cutoff, seed, simulation count, history seasons used, and git SHA when available.
- Do not refactor unrelated live-game, midseason, All-Star, or ingestion code.

---

## This Spec Supersedes

This document **replaces** the previous implementation plan that targeted `wnba-live-game-intel` and assumed `05_forecast/` / `04_refresh/` paths.

Do not implement those old paths.

The analytical design remains approved; only the canonical repo integration and repo-native structure are corrected.

---

## Verified Repository Baseline

Current repo conventions to preserve:

```text
scripts/
├── fetch_wnba_sportsdataverse_2026.py
├── pbpstats_2026_pull_clean.py
├── pbpstats_2026_features.py
├── build_midseason_team_grades.py
└── midseason_team_grades/
    ├── data_sources.py
    ├── metrics.py
    └── ...

analysis/
└── midseason_team_grades/
    ├── README.md
    ├── config/
    │   └── midseason_team_grades_config.json
    └── data/
        ├── processed/
        └── eda/

data/
├── raw/
│   └── sportsdataverse/
│       └── wnba_2026/
└── pbpstats_wnba_2026/
    ├── raw_latest/
    ├── clean_latest/
    └── features_latest/

tests/
├── test_sportsdataverse_2026_download.py
├── test_pbpstats_2026_pipeline.py
├── test_midseason_team_grades.py
└── ...

.github/workflows/
├── sportsdataverse-wnba-2026.yml
├── pbpstats-wnba-2026.yml
├── midseason-team-grades.yml
└── ...
```

Existing tests use `unittest` and put `ROOT / "scripts"` on `sys.path`. New forecast tests should follow that convention.

The normalized team-game table is reusable across analyses, so it belongs under shared top-level `data/processed/`; forecast-specific outputs remain under `analysis/standings_playoff_forecast/`.

---

## Target File Structure

```text
scripts/
├── build_standings_playoff_forecast.py
└── standings_playoff_forecast/
    ├── __init__.py
    ├── contracts.py
    ├── config.py
    ├── data_sources.py
    ├── team_game_layer.py
    ├── standings.py
    ├── tiebreaks.py
    ├── team_strength.py
    ├── remaining_schedule.py
    ├── matchup_model.py
    ├── simulation.py
    ├── historical_context.py
    ├── leverage.py
    ├── broadcast_insights.py
    ├── outputs.py
    ├── metadata.py
    ├── render_excel.py
    ├── render_markdown.py
    ├── render_stat_pack.py
    └── render_dashboard.py

analysis/
└── standings_playoff_forecast/
    ├── README.md
    ├── config/
    │   ├── seasons/
    │   │   ├── default.json
    │   │   └── 2026.json
    │   ├── forecast_model.json
    │   └── team_history.csv
    ├── templates/
    │   ├── playoff_stat_pack_insert.html
    │   ├── playoff_stat_pack_insert.css
    │   ├── dashboard_index.html
    │   ├── dashboard_styles.css
    │   ├── dashboard_app.js
    │   └── dashboard_charts.js
    ├── data/
    │   └── processed/
    │       └── season=2026/
    │           └── latest/
    │               ├── current_standings.csv
    │               ├── head_to_head.csv
    │               ├── team_strength.csv
    │               ├── remaining_schedule.csv
    │               ├── matchup_probabilities.csv
    │               ├── forecast_summary.csv
    │               ├── rank_probability_matrix.csv
    │               ├── playoff_leverage_games.csv
    │               ├── historical_context.csv
    │               ├── broadcast_insights.csv
    │               ├── forecast_payload.json
    │               └── run_manifest.json
    └── deliverables/
        └── season=2026/
            └── latest/
                ├── wnba_standings_playoff_forecast.xlsx
                ├── wnba_broadcast_forecast_brief.md
                ├── wnba_playoff_stat_pack_insert.html
                └── dashboard/
                    ├── index.html
                    ├── assets/
                    │   ├── styles.css
                    │   ├── app.js
                    │   └── charts.js
                    └── data/
                        └── forecast_payload.json

data/
└── processed/
    └── wnba_team_game/
        └── season=2026/
            └── team_game.parquet

tests/
├── test_standings_playoff_forecast_config.py
├── test_standings_playoff_forecast_team_game.py
├── test_standings_playoff_forecast_standings.py
├── test_standings_playoff_forecast_tiebreaks.py
├── test_standings_playoff_forecast_strength.py
├── test_standings_playoff_forecast_matchups.py
├── test_standings_playoff_forecast_simulation.py
├── test_standings_playoff_forecast_history.py
├── test_standings_playoff_forecast_broadcast.py
├── test_standings_playoff_forecast_outputs.py
└── test_standings_playoff_forecast_integration.py

.github/workflows/
└── standings-playoff-forecast.yml
```

---

# Data Ownership and Contracts

## Mandatory Inputs

Per configured season:

```text
schedule_<season>.parquet
team_box_<season>.parquet
standings_<season>.parquet
```

For 2026:

```text
data/raw/sportsdataverse/wnba_2026/
```

These drive current W/L, completed/remaining schedule, game scores, game-level metrics, home/away context, and source reconciliation.

## Optional PBPStats Enrichment

2026 latest team features:

```text
data/pbpstats_wnba_2026/features_latest/2026/team_totals_features_latest.csv
```

Rules:

- May enrich `team_strength.csv` and broadcast context.
- Must not be copied onto every historical game row.
- If a requested cutoff predates the PBPStats snapshot and no dated snapshot exists, enrichment is unavailable for that cutoff.
- Core V1 forecast remains runnable without PBPStats enrichment.

## Normalized Team-Game Contract

One row per:

```text
season × game_id × team_id
```

Required columns:

```text
season
season_type
game_id
game_date
season_game_number
season_progress_pct
team_id
franchise_id
team_abbreviation
team_name
opponent_id
opponent_franchise_id
opponent_abbreviation
opponent_name
home_away
is_home
win
loss
points_for
points_against
margin
field_goals_made
field_goals_attempted
three_point_field_goals_made
free_throws_made
free_throws_attempted
offensive_rebounds
defensive_rebounds
turnovers
possessions_est
pace_est
ortg_est
drtg_est
net_rating_est
efg_pct
opp_efg_pct
tov_pct
opp_tov_pct
oreb_pct
opp_oreb_pct
ftr
opp_ftr
rest_days
back_to_back
wins_to_date
losses_to_date
win_pct_to_date
point_diff_to_date
source_game_completed
source_team_box_path
```

Rules:

- `season_progress_pct = season_game_number / configured_regular_season_games_per_team`.
- Cumulative and rolling fields are calculated only after cutoff filtering.
- Regular-season only; include Commissioner's Cup games when they count in regular-season W/L.
- Exactly two team rows per completed game.
- Stable `franchise_id` comes from `team_history.csv`.
- Source IDs normalize to strings before joins.
- Missing advanced metrics stay nullable; missing metrics do not drop games.

Core formulas:

```python
efg_pct = (fgm + 0.5 * three_pm) / fga
ftr = fta / fga
ortg_est = 100 * points_for / possessions_est
drtg_est = 100 * points_against / possessions_est
net_rating_est = ortg_est - drtg_est
```

Use one documented possession estimate consistently. Reuse an existing validated generic helper if available at implementation time; otherwise implement locally with unit tests.

---

# Season and Model Configuration

## `analysis/standings_playoff_forecast/config/seasons/default.json`

Only cross-season defaults:

```json
{
  "league": "WNBA",
  "season_type": "Regular Season",
  "simulation_count": 100000,
  "recent_window_games": 10,
  "historical_context": {
    "enabled": true,
    "min_prior_seasons": 1
  }
}
```

No competition rules belong here.

## `analysis/standings_playoff_forecast/config/seasons/2026.json`

```json
{
  "season": 2026,
  "team_count": 15,
  "regular_season_games_per_team": 44,
  "playoff_qualifiers": 8,
  "seeding_scope": "league",
  "tiebreaks": [
    "head_to_head_win_pct",
    "record_vs_final_500_plus",
    "head_to_head_point_diff",
    "overall_point_diff"
  ],
  "multi_team_restart_after_elimination": true,
  "sportsdataverse_data_root": "data/raw/sportsdataverse/wnba_2026",
  "pbpstats_data_root": "data/pbpstats_wnba_2026",
  "source_files": {
    "schedule": "schedule_2026.parquet",
    "team_box": "team_box_2026.parquet",
    "standings": "standings_2026.parquet",
    "pbp_team_features": "features_latest/2026/team_totals_features_latest.csv"
  },
  "output_root": "analysis/standings_playoff_forecast",
  "normalized_team_game_root": "data/processed/wnba_team_game"
}
```

Unknown seasons fail if `seasons/<year>.json` is missing.

## `analysis/standings_playoff_forecast/config/forecast_model.json`

```json
{
  "model_version": "v1_heuristic_margin",
  "predictive_rating": {
    "season_net_rating_weight": 0.7,
    "recent_net_rating_weight": 0.3
  },
  "context_adjustments": {
    "home_court_points": 1.5,
    "rest_day_points": 0.35,
    "max_rest_day_adjustment": 2,
    "back_to_back_penalty_points": 0.75
  },
  "margin_model": {
    "minimum_sigma": 8.0,
    "maximum_sigma": 18.0
  },
  "explanatory_strength": {
    "season_net_rating": 0.35,
    "season_win_pct": 0.2,
    "recent_net_rating": 0.15,
    "efg_diff": 0.1,
    "tov_diff": 0.08,
    "oreb_diff": 0.07,
    "ftr_diff": 0.05
  },
  "pbpstats_enrichment": {
    "enabled": true,
    "required": false
  }
}
```

`predictive_net_rating` drives expected margin. `composite_strength` is an explanatory dashboard/broadcast rank.

---

# Standard Forecast Outputs

## `forecast_summary.csv`

One row per team:

```text
season
cutoff_date
team_id
franchise_id
team_abbreviation
current_rank
current_gp
current_wins
current_losses
current_win_pct
current_point_diff
projected_wins_mean
projected_losses_mean
wins_p10
wins_p50
wins_p90
expected_final_rank
playoff_probability
top4_probability
home_court_probability
rank_1_probability
...
rank_<team_count>_probability
out_probability
remaining_sos_rank
remaining_games
clinched_playoffs
eliminated_from_playoffs
status_note
most_leverage_game_id
```

For 2026:

```text
playoff_probability = ranks 1–8
out_probability = ranks 9–15
```

## `rank_probability_matrix.csv`

Long form:

```text
season
cutoff_date
team_id
team_abbreviation
final_rank
probability
playoff_rank
```

Preserve exact rank 1–15 probabilities; presentation layers may aggregate 9–15 as `OUT`.

## `forecast_payload.json`

```json
{
  "metadata": {},
  "standings": [],
  "forecast_summary": [],
  "rank_probability_matrix": [],
  "remaining_schedule": [],
  "leverage_games": [],
  "broadcast_insights": [],
  "historical_context": []
}
```

---

# Implementation Tasks

## Task 1 — Repository Integration Audit and Skeleton

**Files:**
- Create: `analysis/standings_playoff_forecast/README.md`
- Create: `scripts/build_standings_playoff_forecast.py`
- Create: `scripts/standings_playoff_forecast/__init__.py`
- Create: `tests/test_standings_playoff_forecast_config.py`

**Interfaces:** establishes repo-native package/project roots; no model code.

- [ ] Verify current paths:

```bash
git status --short
python --version
find scripts -maxdepth 2 -type f | sort
find analysis -maxdepth 3 -type f | sort | head -200
find data/raw/sportsdataverse/wnba_2026 -maxdepth 2 -type f | sort
find data/pbpstats_wnba_2026 -maxdepth 4 -type f | sort | head -200
find .github/workflows -maxdepth 1 -type f | sort
```

- [ ] README must document purpose, source workflows, normalized layer, output roots, four deliverables, season parameterization, historical scope, test command, and 2026 run command.

- [ ] Create CLI skeleton:

```python
#!/usr/bin/env python3
import argparse

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    return parser.parse_args()

def main():
    args = parse_args()
    print(f"WNBA forecast skeleton season={args.season}")

if __name__ == "__main__":
    main()
```

- [ ] Add import smoke test using existing `unittest` style and `ROOT / "scripts"` path injection.

- [ ] Run:

```bash
python -m unittest tests/test_standings_playoff_forecast_config.py
git commit -am "chore: scaffold WNBA standings forecast project"
```

---

## Task 2 — Config Loaders and Typed Contracts

**Files:**
- Create: `scripts/standings_playoff_forecast/contracts.py`
- Create: `scripts/standings_playoff_forecast/config.py`
- Create configs listed above
- Create: `analysis/standings_playoff_forecast/config/team_history.csv`
- Modify test config file

**Interfaces:**
- `SeasonConfig`
- `ForecastModelConfig`
- `load_season_config(season)`
- `load_model_config()`

- [ ] Test explicit 2026 rules and unknown-season failure.

```python
self.assertEqual(cfg.team_count, 15)
self.assertEqual(cfg.regular_season_games_per_team, 44)
self.assertEqual(cfg.playoff_qualifiers, 8)
with self.assertRaises(FileNotFoundError):
    load_season_config(2099)
```

- [ ] Implement frozen dataclasses and repo-root-relative JSON path resolution.

- [ ] Validate:

```text
team_count > playoff_qualifiers
games_per_team > 0
non-empty tiebreak list
mandatory source filenames exist in config
```

- [ ] Populate 2026 `team_history.csv` from validated source team IDs/names; do not invent unverified historical mappings.

- [ ] Run and commit:

```bash
python -m unittest tests/test_standings_playoff_forecast_config.py
git add scripts/standings_playoff_forecast analysis/standings_playoff_forecast/config tests/test_standings_playoff_forecast_config.py
git commit -m "feat: add season-parameterized forecast config"
```

---

## Task 3 — Source Loaders and Multi-Season Team-Game Layer

**Files:**
- Create: `scripts/standings_playoff_forecast/data_sources.py`
- Create: `scripts/standings_playoff_forecast/team_game_layer.py`
- Create: `tests/test_standings_playoff_forecast_team_game.py`

**Interfaces:**
- `load_forecast_sources(cfg, overrides...)`
- `build_team_game_layer(sources, cfg, cutoff=None)`
- writes `data/processed/wnba_team_game/season=<season>/team_game.parquet`

- [ ] Mandatory SportsDataverse files raise when missing; PBPStats feature file is optional.

- [ ] Normalize IDs:

```python
def normalize_id(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text
```

- [ ] Apply cutoff **before** rolling/cumulative features.

- [ ] Build:

```python
team_rows["season_game_number"] = team_rows.groupby("team_id").cumcount() + 1
team_rows["season_progress_pct"] = team_rows["season_game_number"] / cfg.regular_season_games_per_team
team_rows["wins_to_date"] = team_rows.groupby("team_id")["win"].cumsum()
team_rows["losses_to_date"] = team_rows.groupby("team_id")["loss"].cumsum()
team_rows["win_pct_to_date"] = team_rows["wins_to_date"] / team_rows["season_game_number"]
team_rows["point_diff_to_date"] = team_rows.groupby("team_id")["margin"].cumsum()
```

- [ ] Derive rest/B2B and game-level advanced metrics with safe division.

- [ ] Do not join latest PBPStats season totals onto historical game rows.

- [ ] Tests:

```text
two rows per completed game
mirrored opponent IDs
opposite margins
same date
cutoff mutation after cutoff leaves as-of table unchanged
```

- [ ] Run and commit.

---

## Task 4 — Standings and Head-to-Head

**Files:**
- Create: `scripts/standings_playoff_forecast/standings.py`
- Create: `tests/test_standings_playoff_forecast_standings.py`

**Interfaces:**
- `build_current_standings(team_games, cfg)`
- `build_head_to_head(team_games)`
- source reconciliation helpers

- [ ] Aggregate GP/W/L/PF/PA/point differential.

- [ ] Keep H2H directional.

- [ ] At the latest cutoff, reconcile derived GP/W/L exactly against SportsDataverse standings.

- [ ] For historical cutoffs where source standings are newer than cutoff, validate internally instead of comparing to the newer snapshot.

- [ ] Run and commit.

---

## Task 5 — Official WNBA Tiebreak Engine

**Files:**
- Create: `scripts/standings_playoff_forecast/tiebreaks.py`
- Create: `tests/test_standings_playoff_forecast_tiebreaks.py`

**Interfaces:**
- `rank_teams(final_team_state, all_games, cfg)`
- `resolve_tied_group(team_ids, final_team_state, all_games, cfg)`

- [ ] Unit-test criterion 1: H2H record.
- [ ] Unit-test criterion 2: record vs teams **finishing** .500+.
- [ ] Unit-test criterion 3: H2H point differential.
- [ ] Unit-test criterion 4: overall point differential.
- [ ] Unit-test multi-team restart after elimination.

Criterion registry:

```python
CRITERIA = {
    "head_to_head_win_pct": head_to_head_win_pct,
    "record_vs_final_500_plus": record_vs_final_500_plus,
    "head_to_head_point_diff": head_to_head_point_diff,
    "overall_point_diff": overall_point_diff,
}
```

If every official criterion remains tied, use stable normalized `team_id` only as a deterministic simulation fallback and count fallback usage in the run manifest. Never describe it as an official WNBA tiebreak.

- [ ] Run and commit.

---

## Task 6 — Team Strength + Safe PBPStats Enrichment

**Files:**
- Create: `scripts/standings_playoff_forecast/team_strength.py`
- Create: `tests/test_standings_playoff_forecast_strength.py`

**Interfaces:**
- `build_team_strength(team_games, pbp_team_features, cfg, model_cfg, cutoff)`

- [ ] Build season and last-N-game aggregates after cutoff filtering.
- [ ] Positive-is-good factors:

```python
efg_diff = efg_pct - opp_efg_pct
tov_diff = opp_tov_pct - tov_pct
oreb_diff = oreb_pct - opp_oreb_pct
ftr_diff = ftr - opp_ftr
```

- [ ] Predictive rating:

```python
predictive_net_rating = (
    model_cfg.season_net_rating_weight * season_net_rating
    + model_cfg.recent_net_rating_weight * recent_net_rating
)
```

- [ ] Explanatory composite uses in-season z-scores; zero-variance columns receive z=0.

- [ ] Output PBPStats snapshot status fields:

```text
pbpstats_snapshot_available
pbpstats_snapshot_as_of
pbpstats_snapshot_safe_for_cutoff
```

- [ ] Historical cutoff must leave unsafe PBPStats enrichment null.

- [ ] Run and commit.

---

## Task 7 — Remaining Schedule + Matchup Margin Model

**Files:**
- Create: `scripts/standings_playoff_forecast/remaining_schedule.py`
- Create: `scripts/standings_playoff_forecast/matchup_model.py`
- Create: `tests/test_standings_playoff_forecast_matchups.py`

**Interfaces:**
- `build_remaining_schedule(schedule_df, cutoff, cfg)`
- `score_matchups(remaining, strength, team_games, model_cfg)`

- [ ] Reconcile completed + remaining games to configured season length for every team.

- [ ] Compute future rest/B2B from full schedule order.

- [ ] Expected margin:

```python
avg_pace = (home_pace + away_pace) / 2
base_margin = (home_predictive_net_rating - away_predictive_net_rating) * avg_pace / 100

expected_home_margin = (
    base_margin
    + model_cfg.home_court_points
    + rest_diff * model_cfg.rest_day_points
    - model_cfg.back_to_back_penalty_points * int(home_b2b)
    + model_cfg.back_to_back_penalty_points * int(away_b2b)
)
```

- [ ] Estimate and clamp `margin_sigma` from completed-game residuals.

- [ ] Convert to probability with `statistics.NormalDist`; do not add SciPy.

- [ ] Test home+away probability sums to 1 and remains within [0,1].

- [ ] Run and commit.

---

## Task 8 — 100,000-Run Season Simulation

**Files:**
- Create: `scripts/standings_playoff_forecast/simulation.py`
- Create: `tests/test_standings_playoff_forecast_simulation.py`

**Interfaces:**
- `simulate_season(...) -> SimulationResult`

- [ ] Fixed seed must repeat exactly.

- [ ] Simulate non-zero integer margins:

```python
drawn = rng.normal(expected_home_margin, margin_sigma)
margin = int(np.rint(drawn))
if margin == 0:
    margin = 1 if drawn >= 0 else -1
```

- [ ] Build completed+simulated game state needed for all official tiebreaks.

- [ ] Recompute final .500+ membership inside each run.

- [ ] Rank all 15 teams each run.

- [ ] Preserve exact ranks 1–15; derive:

```text
playoff_probability = ranks 1–8
top4_probability = ranks 1–4
home_court_probability = ranks 1–4
out_probability = ranks 9–15
```

- [ ] Invariants:

```text
each team's rank probabilities sum to 1
each rank's league probability sum = 1
sum of team playoff probabilities = 8
each final team has 44 total games in 2026
```

- [ ] Run and commit.

---

## Task 9 — Optional Historical Context

**Files:**
- Create: `scripts/standings_playoff_forecast/historical_context.py`
- Create: `tests/test_standings_playoff_forecast_history.py`

**Interfaces:**
- `discover_history(normalized_root, forecast_season)`
- `build_historical_context(...)`

- [ ] Missing history returns a valid empty frame, not an error.

- [ ] First benchmarks:

```text
8th-place final wins / win%
9th-place final wins / win%
8th–9th cutline gap
seed-band Net Rating distributions
same-season-progress historical playoff rate
same-season-progress average final rank
```

- [ ] Compare by `season_progress_pct`, not raw game number.

- [ ] Freeze as-of features before joining final outcomes to prevent leakage.

- [ ] Run and commit.

---

## Task 10 — Playoff Leverage + Ten Broadcast Insights

**Files:**
- Create: `scripts/standings_playoff_forecast/leverage.py`
- Create: `scripts/standings_playoff_forecast/broadcast_insights.py`
- Create: `tests/test_standings_playoff_forecast_broadcast.py`

**Interfaces:**
- `calculate_game_leverage(...)`
- `build_broadcast_insights(...)`

- [ ] Conditional win/loss branches estimate:

```text
playoff-probability swing
top4-probability swing
expected-rank swing
```

- [ ] Add flags:

```text
direct_h2h_tiebreak_flag
cutline_matchup_flag
top4_matchup_flag
```

- [ ] Normalize leverage 0–100 and label:

```python
if score >= 85: "Critical"
elif score >= 65: "High"
elif score >= 35: "Moderate"
else: "Low"
```

- [ ] Ten default categories:

```text
leader_race
playoff_cutline
top4_race
tiebreak_watch
remaining_sos
most_likely_riser
most_vulnerable_seed
recent_form
high_leverage_game
historical_context
```

If history is unavailable, replace the last item with a second schedule/tiebreak story.

- [ ] Required fields:

```text
priority
category
team_or_race
data_point
quick_read_snippet
pregame_trigger
halftime_checkpoint
fourth_quarter_checkpoint
why_it_matters
source_fields
```

- [ ] Do not call an LLM in the production pipeline.

- [ ] Run and commit.

---

## Task 11 — Machine-Readable Output Bundle + Run Manifest

**Files:**
- Create: `scripts/standings_playoff_forecast/outputs.py`
- Create: `scripts/standings_playoff_forecast/metadata.py`
- Create: `tests/test_standings_playoff_forecast_outputs.py`

Required output files:

```text
current_standings.csv
head_to_head.csv
team_strength.csv
remaining_schedule.csv
matchup_probabilities.csv
forecast_summary.csv
rank_probability_matrix.csv
playoff_leverage_games.csv
historical_context.csv
broadcast_insights.csv
forecast_payload.json
run_manifest.json
```

- [ ] Use atomic writes.

- [ ] Manifest includes:

```json
{
  "season": 2026,
  "cutoff_date": "YYYY-MM-DD",
  "simulation_count": 100000,
  "conditional_simulation_count": 5000,
  "random_seed": 20260809,
  "model_version": "v1_heuristic_margin",
  "season_config_sha256": "...",
  "model_config_sha256": "...",
  "source_files": [],
  "pbpstats_enrichment_status": "...",
  "history_seasons_used": [],
  "official_tiebreak_fallback_count": 0,
  "git_sha": "..."
}
```

- [ ] Validate payload top-level keys before write.

- [ ] Run and commit.

---

## Task 12 — Repo-Native Orchestrator CLI

**Files:**
- Modify: `scripts/build_standings_playoff_forecast.py`
- Modify: `analysis/standings_playoff_forecast/README.md`
- Create: `tests/test_standings_playoff_forecast_integration.py`

Primary command:

```bash
python scripts/build_standings_playoff_forecast.py --season 2026
```

Supported options:

```text
--season
--cutoff
--simulations
--conditional-simulations
--random-seed
--history-start
--skip-history
--render {none,all}
--sportsdataverse-data-root
--pbpstats-data-root
--output-root
```

Runtime override flags should mirror `build_midseason_team_grades.py`.

Stage order:

```python
cfg -> sources -> cutoff -> team_game_layer -> standings -> reconciliation
-> strength -> remaining schedule -> matchup model -> simulation
-> historical context -> leverage -> broadcast insights
-> output bundle -> renderers
```

Fail non-zero for mandatory-source, reconciliation, schedule-count, probability-mass, or payload-contract failures. Warn rather than fail for optional history/PBPStats enrichment.

Default deterministic seed:

```python
int(f"{cfg.season}{cutoff.strftime('%m%d')}")
```

README refresh workflow:

```bash
python scripts/fetch_wnba_sportsdataverse_2026.py
python scripts/pbpstats_2026_pull_clean.py
python scripts/pbpstats_2026_features.py
python scripts/build_standings_playoff_forecast.py --season 2026
```

- [ ] Run small integration build:

```bash
python -m unittest tests/test_standings_playoff_forecast_integration.py
python scripts/build_standings_playoff_forecast.py --season 2026 --simulations 500 --render none
```

- [ ] Commit.

---

## Task 13 — Excel Companion Analysis Layer

**Files:**
- Create: `scripts/standings_playoff_forecast/render_excel.py`
- Modify: `requirements.txt`
- Modify output tests

Add:

```text
openpyxl
```

Do not add SciPy or Jinja2.

Required sheet order:

```text
Dashboard
Current Standings
Remaining Schedule
Forecast
Broadcast Insights
Team Games Source
Model Notes
```

Dashboard:

```text
current leader
8th/9th cutline
projected playoff field
Top-4/home-court race
most uncertain seed
hardest/easiest remaining SOS
highest-leverage games
headline storylines
historical cutline comparison when available
```

Current Standings:

```text
rank, GP, W, L, Win%, GB, point diff,
season/recent NetRtg, composite strength,
strength rank, seed-vs-strength gap,
H2H context, current .500+ context,
playoff probability, expected final rank
```

Remaining Schedule:

```text
date, away/home, ranks, playoff %, win probabilities,
expected margin, rest/B2B, leverage, H2H flag, checkpoint
```

Forecast:

```text
projected wins, P10/P50/P90,
playoff %, Top-4 %, expected rank,
exact ranks 1–15, OUT, SOS
```

Excel must consume forecast outputs rather than recomputing simulation results.

- [ ] Reopen and scan formulas for `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`.

- [ ] Commit.

---

## Task 14 — Broadcaster Markdown Brief

**Files:**
- Create: `scripts/standings_playoff_forecast/render_markdown.py`
- Modify output tests

Output:

```text
analysis/standings_playoff_forecast/deliverables/season=<season>/latest/wnba_broadcast_forecast_brief.md
```

Sections:

```text
Data cutoff and source status
Current playoff picture
Main findings
Top-4 / home-court race
Playoff cutline
High-leverage games
Useful broadcast checkpoints
Tiebreak watch
Historical context
Method / caveats
```

Broadcast checkpoints for key games:

```text
Pregame — win/loss swing.
Halftime — standings/tiebreak fact to revisit if competitive.
Entering Q4 — playoff/seeding consequence if close.
Postgame — probabilities/rank/H2H status to update.
```

- [ ] Test all ten quick-read insights appear.

- [ ] Commit.

---

## Task 15 — One-Page Stat-Pack Insert + Interactive Dashboard

**Files:**
- Create renderers and templates listed in Target File Structure
- Modify output tests

### Stat-pack insert

11×17 landscape print target.

Zones:

```text
Top: cutoff + current top eight + 8th/9th cutline
Left: projected standings + playoff % + expected rank + P10–P90
Center: exact-rank heat table for relevant race teams
Right: remaining SOS + leverage games + win/loss swings
Bottom: five broadcast nuggets + tiebreak watch + methodology
```

CSS:

```css
@page {
  size: 17in 11in;
  margin: 0.25in;
}
```

Verify one-page print at 100% in Chromium.

### Dashboard

Sections:

```text
Snapshot KPIs
Current standings/cutline
Projected standings
Exact-rank probability heatmap
Remaining schedule leverage
Team detail
Historical comparison
Broadcast insights
Method/cutoff
```

Payload load:

```javascript
async function loadForecast() {
  const response = await fetch("./data/forecast_payload.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Forecast payload failed: ${response.status}`);
  return response.json();
}
```

Required controls:

```text
Team selector
Race view: All / Top 4 / Playoff Cutline / Long Shots
Probability view: Playoff / Exact Rank / Wins Range
```

Every chart needs an accessible table/text equivalent.

Responsive acceptance:

```text
1440
1024
768
390
```

JavaScript may filter/sort/format/render only; no forecast math.

- [ ] Commit.

---

## Task 16 — End-to-End 2026 Validation

**Files:**
- Modify integration test
- Modify orchestrator as needed

Validate:

```text
exactly two rows per completed game
one winner/one loser
opposite margins
derived GP/W/L = source GP/W/L at latest cutoff
completed GP + remaining games = 44 per team
all probabilities in [0,1]
each team's exact-rank probabilities sum to 1
each final rank's league probability sums to 1
sum playoff probabilities = 8
```

Run:

```bash
python -m unittest discover -s tests -p "test_standings_playoff_forecast*.py"

python scripts/build_standings_playoff_forecast.py \
  --season 2026 \
  --simulations 100000 \
  --render all
```

Expected:

```text
cutoff resolved
team-game layer written/updated
standings reconciliation PASS
remaining schedule reconciliation PASS
100,000 simulations complete
probability invariants PASS
machine-readable outputs written
Excel written
Markdown written
stat-pack written
dashboard written
run manifest written
```

Manual QA all four deliverables and confirm identical cutoff/model metadata.

- [ ] Commit.

---

## Task 17 — Manual GitHub Actions Forecast Workflow

**File:**
- Create: `.github/workflows/standings-playoff-forecast.yml`

Inputs:

```yaml
on:
  workflow_dispatch:
    inputs:
      season:
        description: "WNBA season"
        required: true
        type: string
        default: "2026"
      cutoff:
        description: "Optional YYYY-MM-DD cutoff"
        required: false
        type: string
        default: ""
      simulations:
        description: "Monte Carlo runs"
        required: true
        type: string
        default: "100000"
      refresh_sportsdataverse:
        required: true
        type: boolean
        default: false
      refresh_pbpstats:
        required: true
        type: boolean
        default: false
      run_tests:
        required: true
        type: boolean
        default: true
      commit_outputs:
        required: true
        type: boolean
        default: false
```

Use repo-standard actions:

```yaml
- uses: actions/checkout@v7
- uses: actions/setup-python@v7
  with:
    python-version: "3.11"
```

Optional 2026 refresh:

```yaml
- name: Refresh SportsDataverse
  if: ${{ inputs.refresh_sportsdataverse && inputs.season == '2026' }}
  run: python scripts/fetch_wnba_sportsdataverse_2026.py

- name: Refresh PBPStats
  if: ${{ inputs.refresh_pbpstats && inputs.season == '2026' }}
  run: |
    python scripts/pbpstats_2026_pull_clean.py
    python scripts/pbpstats_2026_features.py
```

Forecast tests:

```yaml
- name: Run forecast tests
  if: ${{ inputs.run_tests }}
  run: python -m unittest discover -s tests -p "test_standings_playoff_forecast*.py"
```

Build cutoff safely:

```bash
ARGS=(--season "${{ inputs.season }}" --simulations "${{ inputs.simulations }}" --render all)
if [[ -n "${{ inputs.cutoff }}" ]]; then
  ARGS+=(--cutoff "${{ inputs.cutoff }}")
fi
python scripts/build_standings_playoff_forecast.py "${ARGS[@]}"
```

Upload:

```yaml
- uses: actions/upload-artifact@v7
  with:
    name: wnba-standings-forecast-${{ inputs.season }}-${{ github.run_id }}
    path: |
      analysis/standings_playoff_forecast/deliverables/season=${{ inputs.season }}/latest/**
      analysis/standings_playoff_forecast/data/processed/season=${{ inputs.season }}/latest/run_manifest.json
```

Default `commit_outputs` remains false. If true, commit only forecast analysis/normalized outputs, not unrelated source files.

- [ ] Commit workflow.

---

# Historical Expansion Path

To add a historical season:

1. validate raw data;
2. add `analysis/standings_playoff_forecast/config/seasons/<year>.json`;
3. build `data/processed/wnba_team_game/season=<year>/team_game.parquet`;
4. rerun current forecast;
5. historical context discovers prior partitions automatically.

Phase 2 backtesting example:

```bash
python scripts/build_standings_playoff_forecast.py \
  --season 2025 \
  --cutoff 2025-08-01 \
  --render none
```

Backtesting metrics:

```text
playoff Brier score
log loss
final-wins MAE
final-rank MAE
calibration buckets
```

Historical training comes only after backtesting/calibration review.

---

# Final Package Contract

One validated model produces:

## Excel

```text
wnba_standings_playoff_forecast.xlsx
```

Seven sheets:

```text
Dashboard
Current Standings
Remaining Schedule
Forecast
Broadcast Insights
Team Games Source
Model Notes
```

## Broadcaster brief

```text
wnba_broadcast_forecast_brief.md
```

## One-page stat-pack insert

```text
wnba_playoff_stat_pack_insert.html
```

11×17 landscape.

## Interactive dashboard

```text
dashboard/index.html
```

Reads:

```text
dashboard/data/forecast_payload.json
```

and performs no forecast math in-browser.

---

# Definition of Done

- Canonical repo is `kbsmd-sportsmusicdata/wnba-pbpstats-2026-pipeline`.
- No implementation dependency remains on `wnba-live-game-intel`.
- No `05_forecast/` or `04_refresh/` assumptions remain.
- Existing SportsDataverse/PBPStats workflows remain intact.
- `python scripts/build_standings_playoff_forecast.py --season 2026` runs from repo root.
- Unknown seasons require explicit rules config.
- Team-game layer is multi-season capable under `data/processed/wnba_team_game/season=<year>/`.
- Latest completed-game GP/W/L reconcile to SportsDataverse before simulation.
- Official WNBA tiebreak order and multi-team restart are unit-tested.
- Final-.500 criterion is recomputed per simulation.
- Remaining games simulate point margins.
- 2026 simulations assign exactly 15 ranks and eight playoff qualifiers.
- Exact ranks 1–15 are retained.
- History is optional.
- PBPStats latest enrichment cannot leak into historical cutoffs.
- Machine-readable outputs are produced before renderers.
- Excel has seven required sheets and no formula errors.
- Markdown has ten deterministic broadcaster insights plus pregame/halftime/Q4 checkpoints.
- Stat-pack prints on one 11×17 landscape page.
- Dashboard works at 390px and reads only static payload data.
- `python -m unittest discover -s tests -p "test_standings_playoff_forecast*.py"` passes.
- Full 100,000-run 2026 forecast completes.
- Run manifest records reproducibility/provenance.
- Manual Actions workflow uploads all four deliverables.

---

# Recommended Codex Execution Order

Execute Tasks 1–17 in order.

Do not begin presentation work until Tasks 1–12 are green.

Highest-risk review gates:

1. **Task 3 — normalized team-game layer**
2. **Task 5 — official tiebreak engine**
3. **Task 8 — season simulation**
4. **Task 16 — full 2026 acceptance run**

Recommended branch/worktree:

```bash
git checkout -b feat/wnba-standings-playoff-forecast
```

Keep commits small enough that the normalized data model, tiebreak engine, matchup model, simulation, output contract, and each renderer can be reviewed independently.
