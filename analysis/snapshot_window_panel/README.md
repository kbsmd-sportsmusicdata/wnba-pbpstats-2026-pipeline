# Snapshot Window Panel

Turns the daily PBPStats cumulative-snapshot archive into a **game-window panel** — one row
per team or player per window of games — so that the season-total feeds can support trend,
form and trajectory analysis.

This is the base layer for team identity-shift work, playoff-readiness modelling, and player
trajectory / hidden-value boards. Those all need a time dimension the PBPStats endpoints do
not publish.

## Outputs

`data/processed/`

| File | Grain | Rows (2026 as of 2026-08-11) |
|---|---|---|
| `team_window_panel_2026.csv` | team x window | 370 windows, 15 teams, 488 team-games |
| `player_window_panel_2026.csv` | player x window | 3,699 windows, 224 players, 4,827 player-games |
| `window_panel_qa_2026.csv` | data-quality event | Every restatement and quarantine, with counts |
| `run_manifest_2026.json` | run | Source manifest, config hash, coverage stats |

## Running

```bash
PYTHONPATH=scripts python scripts/build_snapshot_window_panel.py \
  --config analysis/snapshot_window_panel/config/snapshot_window_panel_config.json
```

Options: `--stage {team,player,all}`, `--pbpstats-data-root`, `--output-root`. CI equivalent
is the **Snapshot Window Panel** workflow.

The panel should be rebuilt after every PBPStats refresh — each new snapshot adds a window.

## Key Columns

| Column | Meaning |
|---|---|
| `window_index`, `is_baseline_block` | Window 0 is the pre-archive block of games |
| `covered_game_date_start` / `_end` | Inclusive game dates in the window; join key to schedule and opponents |
| `games_in_window` | Games the entity played in the window |
| Counting stats (`points`, `off_poss`, `at_rim_fga`, ...) | Window totals, not season totals |
| `off_rating`, `def_rating`, `net_rating`, `pace` | Team, per 100 possessions |
| `*_per_75` | Player production per 75 possessions |
| `shotquality_pbp_avg`, `shot_making_over_shotquality` | Expected vs actual shooting, per window |
| `on_court_poss_share` | Player's share of team possessions played — the role-change signal |
| `usage`, `on_off_rtg`, `on_def_rtg` | Reconstructed per window, not season averages |

## Reading the Panel Correctly

- **Sum, don't average.** To build a multi-game split, sum the counting columns and
  recompute rates from those totals. Averaging per-window rates weights a 60-possession
  window the same as a 90-possession one.
- **Filter or keep the baseline block deliberately.** It covers several games at once, so it
  belongs in season reconciliation but usually not in "last N games" form measures.
- **Never use minutes as a denominator.** The source re-based `seconds_played` on
  2026-08-07; use possessions. See `methodology.md`.
- **Check `window_panel_qa_2026.csv` before trusting a column.** Nulls in the panel are
  deliberate — they mark values the source restated.

## Verification

- Window totals reconcile exactly to season cumulative totals for all 15 teams.
- All 297 single-game team windows match independent ESPN box scores on team and opponent
  points.
- Player possession shares sum to 5.000 per fully covered team window.
- 26 unit tests: `python -m unittest tests.test_snapshot_window_panel`.

Full method, data-integrity handling and limitations: [`methodology.md`](methodology.md).
