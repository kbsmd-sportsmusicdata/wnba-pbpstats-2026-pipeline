"""A per-game team window panel built from the shared game layer.

The identity-shift analysis is written against the snapshot window panel, whose "windows" are
deltas between snapshots of cumulative team totals -- so the recent/baseline split lands on a
snapshot boundary, not a game one, and its resolution depends on how often totals were captured.
The shared team-game layer carries one true row per team-game, so the same analysis can run with
**one window per game**: an exact recent/baseline split and a permutation null that scrambles real
games rather than snapshot windows.

This builder emits the exact panel schema :mod:`team_identity_shift.style`,
:mod:`team_identity_shift.shift` and the decomposition consume, so all of that machinery runs
unchanged -- only the time grain sharpens.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# pbpstats team counting stats the style dimensions, the metric builder and the offensive
# decomposition are computed from. Already snake_cased identically in the game layer.
_COUNTING_COLUMNS = (
    "off_poss", "def_poss", "total_poss", "points", "opponent_points",
    "fg2_a", "fg2_m", "fg3_a", "fg3_m", "fta", "ft_points",
    "at_rim_fga", "at_rim_fgm", "short_mid_range_fga", "short_mid_range_fgm",
    "long_mid_range_fga", "long_mid_range_fgm", "corner3_fga", "corner3_fgm",
    "arc3_fga", "arc3_fgm", "turnovers", "live_ball_turnovers",
    "off_rebounds", "def_rebounds", "assists", "pts_assisted2s", "pts_assisted3s",
    "second_chance_points", "second_chance_off_poss", "penalty_off_poss", "penalty_points",
    "steals", "blocks", "fouls",
)

# The shot-quality average is not additive, so it rides with a weight column and is re-averaged
# per period. In the game layer it is named ``shot_quality_avg``; the panel calls it
# ``shotquality_pbp_avg`` and weights it by field-goal attempts.
_SHOT_QUALITY_SOURCE = "shot_quality_avg"
_SHOT_QUALITY_PANEL = "shotquality_pbp_avg"


def build_game_team_panel(team_game: pd.DataFrame) -> pd.DataFrame:
    """One window per team-game, in the snapshot-window-panel schema.

    Games are ordered by date within each team; ``window_index`` is that order and
    ``games_in_window`` is 1, so the downstream recent/baseline split is exact.
    """
    if team_game is None or team_game.empty:
        return pd.DataFrame()

    frame = team_game.copy()
    frame = frame.sort_values(["team_abbreviation", "game_date", "game_id"]).reset_index(drop=True)

    counting = [c for c in _COUNTING_COLUMNS if c in frame.columns]
    panel = frame[["team_abbreviation", "game_date"] + counting].copy()
    panel["team_id"] = frame["team_id"] if "team_id" in frame.columns else np.nan
    panel["entity_id"] = panel["team_id"]
    panel["name"] = frame["team_abbreviation"]

    # One game per window; index and cumulative game count within each team.
    panel["window_index"] = panel.groupby("team_abbreviation").cumcount() + 1
    panel["cumulative_games_played"] = panel["window_index"]
    panel["games_in_window"] = 1
    panel["is_baseline_block"] = False
    panel["snapshot_span_days"] = 0

    panel["covered_game_date_start"] = panel["game_date"]
    panel["covered_game_date_end"] = panel["game_date"]
    game_ts = pd.to_datetime(panel["game_date"], errors="coerce").dt.tz_localize("UTC")
    panel["window_start_utc"] = game_ts
    panel["window_end_utc"] = game_ts

    # Shot quality: rename to the panel column and attach its field-goal-attempt weight so the
    # period aggregation re-averages it correctly across a period's games.
    if _SHOT_QUALITY_SOURCE in frame.columns:
        panel[_SHOT_QUALITY_PANEL] = pd.to_numeric(frame[_SHOT_QUALITY_SOURCE], errors="coerce")
        fga = pd.to_numeric(frame.get("fg2_a"), errors="coerce").fillna(0.0) + pd.to_numeric(
            frame.get("fg3_a"), errors="coerce"
        ).fillna(0.0)
        panel[f"{_SHOT_QUALITY_PANEL}_weight"] = fga

    return panel
