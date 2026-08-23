"""Recent/baseline aggregation from additive game-level fixture counts."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


COUNT_COLUMNS = [
    "minutes", "off_poss", "team_possessions", "points", "assists", "turnovers",
    "fga", "fgm", "fta", "ftm", "at_rim_fga", "at_rim_fgm",
]
LIVE_V1_COUNT_COLUMNS = [
    "def_poss", "total_poss", "fg3a", "fg3m", "rebounds", "off_rebounds",
]
IDENTITY_COLUMNS = ["player_id", "player_name", "team_abbreviation"]
BASE_DERIVED_COLUMNS = [
    "games", "possession_share_sd", "minutes_per_game", "possession_share",
    "assists_per_75", "assist_turnover_ratio", "true_shooting_attempts",
    "true_shooting_pct", "rim_fga_share", "rim_fg_pct", "turnover_rate",
]
LIVE_V1_DERIVED_COLUMNS = [
    "three_point_fga_share", "fta_rate", "rebounds_per_75_total_possessions",
    "offensive_rebounds_per_75_off_poss",
]
DERIVED_COLUMNS = BASE_DERIVED_COLUMNS + LIVE_V1_DERIVED_COLUMNS


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator is None or not np.isfinite(denominator) or denominator <= 0:
        return float("nan")
    return float(numerator) / float(denominator)


def aggregate_window(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    columns = IDENTITY_COLUMNS
    active_live_counts = [column for column in LIVE_V1_COUNT_COLUMNS if column in frame.columns]
    active_counts = COUNT_COLUMNS + active_live_counts
    active_derived = BASE_DERIVED_COLUMNS + (
        LIVE_V1_DERIVED_COLUMNS if active_live_counts else []
    )
    if frame.empty:
        value_columns = [f"{prefix}_{column}" for column in active_counts + active_derived]
        return pd.DataFrame(columns=columns + value_columns)

    numeric = frame.copy()
    for column in active_counts:
        numeric[column] = pd.to_numeric(numeric[column], errors="coerce")
    grouped = numeric.groupby(columns, as_index=False, dropna=False)[active_counts].sum(min_count=1)
    games = numeric.groupby(columns, as_index=False)["game_id"].nunique().rename(columns={"game_id": "games"})
    grouped = grouped.merge(games, on=columns, how="left")

    per_game_share = numeric.assign(_share=numeric["off_poss"] / numeric["team_possessions"])
    share_sd = (
        per_game_share.groupby(columns, as_index=False)["_share"]
        .std(ddof=0)
        .rename(columns={"_share": "possession_share_sd"})
    )
    grouped = grouped.merge(share_sd, on=columns, how="left")

    grouped["minutes_per_game"] = grouped.apply(lambda r: _safe_ratio(r.minutes, r.games), axis=1)
    grouped["possession_share"] = grouped.apply(
        lambda r: _safe_ratio(r.off_poss, r.team_possessions), axis=1
    )
    grouped["assists_per_75"] = grouped.apply(
        lambda r: 75.0 * _safe_ratio(r.assists, r.off_poss), axis=1
    )
    grouped["assist_turnover_ratio"] = grouped.apply(
        lambda r: _safe_ratio(r.assists, r.turnovers), axis=1
    )
    grouped["true_shooting_attempts"] = grouped["fga"] + 0.44 * grouped["fta"]
    grouped["true_shooting_pct"] = grouped.apply(
        lambda r: _safe_ratio(r.points, 2.0 * r.true_shooting_attempts), axis=1
    )
    grouped["rim_fga_share"] = grouped.apply(lambda r: _safe_ratio(r.at_rim_fga, r.fga), axis=1)
    grouped["rim_fg_pct"] = grouped.apply(
        lambda r: _safe_ratio(r.at_rim_fgm, r.at_rim_fga), axis=1
    )
    grouped["turnover_rate"] = grouped.apply(
        lambda r: _safe_ratio(r.turnovers, r.off_poss), axis=1
    )
    if active_live_counts:
        grouped["three_point_fga_share"] = grouped.apply(
            lambda r: _safe_ratio(r.fg3a, r.fga), axis=1
        )
        grouped["fta_rate"] = grouped.apply(lambda r: _safe_ratio(r.fta, r.fga), axis=1)
        grouped["rebounds_per_75_total_possessions"] = grouped.apply(
            lambda r: 75.0 * _safe_ratio(r.rebounds, r.total_poss), axis=1
        )
        grouped["offensive_rebounds_per_75_off_poss"] = grouped.apply(
            lambda r: 75.0 * _safe_ratio(r.off_rebounds, r.off_poss), axis=1
        )

    renamed = {
        column: f"{prefix}_{column}" for column in grouped.columns if column not in columns
    }
    return grouped.rename(columns=renamed)


def build_window_metrics(player_game: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    windows = config["windows"]
    dates = player_game["game_date"]
    baseline = player_game[
        dates.between(pd.Timestamp(windows["baseline_start"]), pd.Timestamp(windows["baseline_end"]))
    ]
    recent = player_game[
        dates.between(pd.Timestamp(windows["recent_start"]), pd.Timestamp(windows["recent_end"]))
    ]
    season = player_game[dates.le(pd.Timestamp(windows["recent_end"]))]
    recent_agg = aggregate_window(recent, "recent")
    baseline_agg = aggregate_window(baseline, "baseline")
    season_agg = aggregate_window(season, "season")
    identity = ["player_id", "player_name", "team_abbreviation"]
    return (
        recent_agg.merge(baseline_agg, on=identity, how="outer")
        .merge(season_agg, on=identity, how="outer")
    )
