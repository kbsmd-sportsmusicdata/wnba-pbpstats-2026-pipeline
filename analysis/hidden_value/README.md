# Hidden Value Watchlist

Which WNBA players are contributing more than their situation explains, and which are
improving fast enough to matter before the playoffs.

## Outputs

`data/processed/`

| File | Grain | Rows (2026) |
|---|---|---:|
| `hidden_value_board_2026.csv` | player | 176 (151 reliable) |
| `player_trajectory_2026.csv` | player | trend detail per tracked metric |
| `hidden_value_components_2026.csv` | player × component | long format, ready to plot |
| `run_manifest_2026.json` | run | Role-model diagnostics, source manifest |

## Running

```bash
python scripts/build_hidden_value.py \
  --config analysis/hidden_value/config/hidden_value_config.json
```

CI equivalent is the **Hidden Value** workflow. The recent-form trajectory reads the shared
per-game layer (`data/processed/wnba_pbpstats_player_game/`); the role model and impact inputs
still depend on the snapshot window panel and possession impact outputs, so rebuild those (and the
game layer) first if the data has moved.

## Two tracks, not one ranking

`board_track` splits the board because these are different bets and a reader should know
which one they are looking at:

- **Underrated Now** — the claim rests on the role-adjusted residual.
- **Recent Form** — the player's standout signal is their recent trend. **This is
  descriptive, not a forecast.** Held-out testing showed a rising trend predicts slightly
  *worse* subsequent production once level is accounted for, so the trend carries only 0.05
  of the score and the track is named to match.

## Key Columns

| Column | Meaning |
|---|---|
| `hidden_value_score` | Weighted composite of the four components, minus a volatility penalty |
| `role_residual_score` | Impact above what minutes, usage, starts, possession share and **team strength** predict |
| `trajectory_score` | Shrunk recent trend. Descriptive context only — weighted 0.05, see methodology |
| `regression_upside_score` | Shot quality running ahead of results, plus free-throw prior on three-point room |
| `playoff_fit_score` | Skills weighted for a shorter rotation and half-court game |
| `conviction` | Strong / Moderate / Monitor; low-sample players are downgraded one step |
| `watchlist_note` | One line saying why the player is on the board |

## Reading This Correctly

- **Team strength is regressed out.** This answers "better than their situation suggests",
  not "best". A star on a good team will score lower here than their raw quality — that is
  the design, not a bug.
- **Check `sample_flag` before quoting anyone.** 300 possessions is enough to appear and
  nowhere near enough to be sure.
- **Do not read `Recent Form` as a forecast.** The trend is anti-predictive on this
  season's data; it is in the outputs as context.
- **The impact input lags.** RAPM covers games through 2026-07-22; the player features run
  to 2026-08-11.

## Verification

- Role model R² 0.4256 with the residual decorrelated from team strength (r = 0.005).
- Trajectory weight set from held-out testing, not judgement: the composite now correlates
  0.09 with the trend and 0.62 / 0.60 / 0.57 with the three level-based components.
- Top 25 spans 13 teams rather than clustering on the league's best.
- 31 unit tests: `python -m unittest tests/test_hidden_value.py`.

Full method, the design decision behind the team term, and limitations:
[`methodology.md`](methodology.md).
