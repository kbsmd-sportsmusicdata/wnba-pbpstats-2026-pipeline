"""Per-window rate metrics derived from the differenced counting stats.

Every metric here is computed from window totals, never by differencing a cumulative
rate. Denominators are possessions or attempts rather than minutes, because the WNBA 2026
archive re-stated ``seconds_played`` mid-season and minutes-based rates are not comparable
across that boundary.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from .panel import safe_divide


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[name], errors="coerce")


def _shot_totals(df: pd.DataFrame) -> Dict[str, pd.Series]:
    fg2a, fg3a = _col(df, "fg2_a"), _col(df, "fg3_a")
    fg2m, fg3m = _col(df, "fg2_m"), _col(df, "fg3_m")
    return {
        "fga": fg2a + fg3a,
        "fgm": fg2m + fg3m,
        "fg2_a": fg2a,
        "fg3_a": fg3a,
        "fg2_m": fg2m,
        "fg3_m": fg3m,
    }


def _add_shooting_metrics(df: pd.DataFrame, out: pd.DataFrame) -> None:
    shots = _shot_totals(df)
    fga, fgm, fg3m, fg3a = shots["fga"], shots["fgm"], shots["fg3_m"], shots["fg3_a"]
    points, fta = _col(df, "points"), _col(df, "fta")

    out["fga"] = fga
    out["fgm"] = fgm
    out["efg_pct"] = safe_divide(fgm + 0.5 * fg3m, fga)
    out["ts_pct"] = safe_divide(points, 2 * (fga + 0.44 * fta))
    out["points_per_fga"] = safe_divide(points, fga)
    out["fg2_pct"] = safe_divide(shots["fg2_m"], shots["fg2_a"])
    out["fg3_pct"] = safe_divide(fg3m, fg3a)
    out["ft_attempt_rate"] = safe_divide(fta, fga)
    out["three_point_attempt_rate"] = safe_divide(fg3a, fga)

    at_rim_fga = _col(df, "at_rim_fga")
    short_mid = _col(df, "short_mid_range_fga")
    long_mid = _col(df, "long_mid_range_fga")
    corner3 = _col(df, "corner3_fga")
    arc3 = _col(df, "arc3_fga")

    out["rim_fga_share"] = safe_divide(at_rim_fga, fga)
    out["short_mid_fga_share"] = safe_divide(short_mid, fga)
    out["long_mid_fga_share"] = safe_divide(long_mid, fga)
    out["midrange_fga_share"] = safe_divide(short_mid + long_mid, fga)
    out["corner3_fga_share"] = safe_divide(corner3, fga)
    out["above_break3_fga_share"] = safe_divide(arc3, fga)
    out["rim_and_three_fga_share"] = safe_divide(at_rim_fga + fg3a, fga)
    out["corner3_share_of_3pa"] = safe_divide(corner3, fg3a)
    out["rim_accuracy"] = safe_divide(_col(df, "at_rim_fgm"), at_rim_fga)

    if "shotquality_pbp_avg" in df.columns:
        out["shot_making_over_shotquality"] = out["efg_pct"] - _col(df, "shotquality_pbp_avg")


def build_team_window_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    """Add possession-normalized team identity and efficiency metrics."""
    if panel.empty:
        return panel

    out = panel.copy()
    off_poss, def_poss = _col(panel, "off_poss"), _col(panel, "def_poss")
    points, opponent_points = _col(panel, "points"), _col(panel, "opponent_points")
    games = _col(panel, "games_in_window")

    out["off_rating"] = safe_divide(points, off_poss) * 100
    out["def_rating"] = safe_divide(opponent_points, def_poss) * 100
    out["net_rating"] = out["off_rating"] - out["def_rating"]
    out["pace"] = safe_divide(off_poss, games)
    out["points_per_game"] = safe_divide(points, games)
    out["opponent_points_per_game"] = safe_divide(opponent_points, games)

    _add_shooting_metrics(panel, out)

    out["turnover_rate"] = safe_divide(_col(panel, "turnovers"), off_poss)
    out["live_ball_turnover_rate"] = safe_divide(_col(panel, "live_ball_turnovers"), off_poss)
    out["assist_rate"] = safe_divide(_col(panel, "assists"), out["fgm"])
    out["assisted_points_share"] = safe_divide(
        _col(panel, "pts_assisted2s") + _col(panel, "pts_assisted3s"), points
    )
    out["off_reb_per_100_off_poss"] = safe_divide(_col(panel, "off_rebounds"), off_poss) * 100
    out["def_reb_per_100_def_poss"] = safe_divide(_col(panel, "def_rebounds"), def_poss) * 100
    out["second_chance_points_share"] = safe_divide(_col(panel, "second_chance_points"), points)
    out["second_chance_off_poss_share"] = safe_divide(_col(panel, "second_chance_off_poss"), off_poss)
    out["penalty_off_poss_share"] = safe_divide(_col(panel, "penalty_off_poss"), off_poss)
    out["penalty_points_share"] = safe_divide(_col(panel, "penalty_points"), points)
    out["steals_per_100_def_poss"] = safe_divide(_col(panel, "steals"), def_poss) * 100
    out["blocks_per_100_def_poss"] = safe_divide(_col(panel, "blocks"), def_poss) * 100
    out["fouls_per_100_def_poss"] = safe_divide(_col(panel, "fouls"), def_poss) * 100
    return out


def build_player_window_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    """Add per-75-possession production and shot-profile metrics for players."""
    if panel.empty:
        return panel

    out = panel.copy()
    off_poss, def_poss = _col(panel, "off_poss"), _col(panel, "def_poss")
    total_poss = _col(panel, "total_poss")
    total_poss = total_poss.where(total_poss.notna(), off_poss + def_poss)
    out["total_poss_for_rates"] = total_poss
    games = _col(panel, "games_in_window")

    for column in (
        "points",
        "rebounds",
        "off_rebounds",
        "def_rebounds",
        "assists",
        "turnovers",
        "steals",
        "blocks",
        "fta",
    ):
        out[f"{column}_per_75"] = safe_divide(_col(panel, column), total_poss) * 75
    out["fga_per_75"] = safe_divide(_col(panel, "fg2_a") + _col(panel, "fg3_a"), total_poss) * 75
    out["stocks_per_75"] = out["steals_per_75"].fillna(0) + out["blocks_per_75"].fillna(0)
    out["assist_turnover_ratio"] = safe_divide(_col(panel, "assists"), _col(panel, "turnovers"))
    out["points_per_game"] = safe_divide(_col(panel, "points"), games)

    _add_shooting_metrics(panel, out)

    if {"on_off_rtg", "on_def_rtg"}.issubset(out.columns):
        out["on_court_net_rating"] = _col(out, "on_off_rtg") - _col(out, "on_def_rtg")

    # seconds_played is carried but deliberately not used as a rate denominator; it is
    # the one column the 2026 feed re-based mid-season.
    out["minutes_in_window"] = safe_divide(_col(panel, "seconds_played"), 60.0)
    out["minutes_per_game"] = safe_divide(out["minutes_in_window"], games)
    return out


def attach_team_possession_share(
    player_panel: pd.DataFrame,
    team_panel: pd.DataFrame,
) -> tuple[pd.DataFrame, Dict[str, float]]:
    """Derive each player's share of team possessions played, per window.

    A player's rows are only appended to the archive when their totals change, so a player
    who sat out can have a window spanning several of their team's windows. Boundaries
    therefore cannot be joined directly. Because each team's windows tile its season
    contiguously, the team side is instead aggregated over every team window contained in
    the player's game-date range, and the result is kept only when those team windows
    cover that range exactly end to end.
    """
    stats = {"matched_windows": 0.0, "total_windows": float(len(player_panel)), "match_rate": 0.0}
    if player_panel.empty or team_panel.empty:
        if not player_panel.empty:
            player_panel = player_panel.copy()
            player_panel["team_off_poss"] = np.nan
            player_panel["on_court_poss_share"] = np.nan
        return player_panel, stats

    keys = ["team_abbreviation", "covered_game_date_start", "covered_game_date_end"]
    if not set(keys).issubset(player_panel.columns) or not set(keys).issubset(team_panel.columns):
        out = player_panel.copy()
        out["team_off_poss"] = np.nan
        out["on_court_poss_share"] = np.nan
        return out, stats

    out = player_panel.copy().reset_index(drop=True)
    out["_window_key"] = np.arange(len(out))

    def _dates(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        return (
            pd.to_datetime(frame["covered_game_date_start"], errors="coerce"),
            pd.to_datetime(frame["covered_game_date_end"], errors="coerce"),
        )

    player_start, player_end = _dates(out)
    out["_start"], out["_end"] = player_start, player_end

    team_side = team_panel[["team_abbreviation", "off_poss"]].copy()
    team_start, team_end = _dates(team_panel)
    team_side["_team_start"], team_side["_team_end"] = team_start, team_end
    team_side = team_side.dropna(subset=["_team_start", "_team_end"])

    pairs = out[["_window_key", "team_abbreviation", "_start", "_end"]].merge(
        team_side, on="team_abbreviation", how="inner"
    )
    contained = pairs[(pairs["_team_start"] >= pairs["_start"]) & (pairs["_team_end"] <= pairs["_end"])]
    rolled = contained.groupby("_window_key").agg(
        team_off_poss=("off_poss", "sum"),
        _covered_start=("_team_start", "min"),
        _covered_end=("_team_end", "max"),
    )

    out = out.merge(rolled, left_on="_window_key", right_index=True, how="left")
    # Partial coverage would understate team possessions and inflate the share, so it is
    # dropped rather than reported.
    full_cover = out["_covered_start"].eq(out["_start"]) & out["_covered_end"].eq(out["_end"])
    out.loc[~full_cover, "team_off_poss"] = np.nan
    out["on_court_poss_share"] = safe_divide(_col(out, "off_poss"), _col(out, "team_off_poss"))

    out = out.drop(columns=["_window_key", "_start", "_end", "_covered_start", "_covered_end"])
    matched = float(out["team_off_poss"].notna().sum())
    stats["matched_windows"] = matched
    stats["match_rate"] = round(matched / len(out), 4) if len(out) else 0.0
    return out, stats
