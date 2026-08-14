"""Strength-of-schedule context for each period.

A team that looks transformed in August may simply have played easier opponents. Opponent
quality is measured for each period so a shift can be read against the schedule that
produced it.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from .style import BASELINE, RECENT, assign_periods, team_key


def build_game_opponents(schedule: pd.DataFrame) -> pd.DataFrame:
    """One row per team per scheduled game, with opponent and date."""
    columns = {"game_date", "home_abbreviation", "away_abbreviation"}
    if schedule.empty or not columns.issubset(schedule.columns):
        return pd.DataFrame(columns=["team_abbreviation", "opponent_abbreviation", "game_date", "home_away"])

    games = schedule.copy()
    games["game_date"] = pd.to_datetime(games["game_date"], errors="coerce").dt.date
    home = pd.DataFrame(
        {
            "team_abbreviation": games["home_abbreviation"].map(team_key),
            "opponent_abbreviation": games["away_abbreviation"].map(team_key),
            "game_date": games["game_date"],
            "home_away": "home",
        }
    )
    away = pd.DataFrame(
        {
            "team_abbreviation": games["away_abbreviation"].map(team_key),
            "opponent_abbreviation": games["home_abbreviation"].map(team_key),
            "game_date": games["game_date"],
            "home_away": "away",
        }
    )
    return pd.concat([home, away], ignore_index=True).dropna(subset=["game_date"])


def build_period_schedule_context(
    panel: pd.DataFrame,
    schedule: pd.DataFrame,
    season_frame: pd.DataFrame,
    *,
    recent_games: int,
) -> pd.DataFrame:
    """Average opponent net rating and home rate for each team's baseline and recent periods.

    Windows carry the inclusive game dates they cover, so each window's opponents are the
    scheduled games falling inside that range.
    """
    opponents = build_game_opponents(schedule)
    if opponents.empty or season_frame.empty:
        return pd.DataFrame(
            columns=["team_abbreviation", "period", "opponent_net_rating", "home_rate", "games_matched"]
        )

    strength = (
        season_frame.set_index("team_abbreviation")["net_rating"].apply(pd.to_numeric, errors="coerce")
        if "net_rating" in season_frame.columns
        else pd.Series(dtype=float)
    )

    rows: List[Dict] = []
    for team, group in panel.groupby("team_abbreviation", sort=True):
        ordered = assign_periods(group, recent_games=recent_games)
        team_games = opponents[opponents["team_abbreviation"] == team]
        if team_games.empty:
            continue

        for label in (BASELINE, RECENT):
            block = ordered[ordered["period"] == label]
            if block.empty:
                continue
            starts = pd.to_datetime(block["covered_game_date_start"], errors="coerce").dt.date
            ends = pd.to_datetime(block["covered_game_date_end"], errors="coerce").dt.date

            matched = []
            for start, end in zip(starts, ends):
                if pd.isna(start) or pd.isna(end):
                    continue
                matched.append(
                    team_games[(team_games["game_date"] >= start) & (team_games["game_date"] <= end)]
                )
            if not matched:
                continue
            played = pd.concat(matched, ignore_index=True).drop_duplicates(
                subset=["game_date", "opponent_abbreviation", "home_away"]
            )
            if played.empty:
                continue

            opponent_strength = played["opponent_abbreviation"].map(strength)
            rows.append(
                {
                    "team_abbreviation": team,
                    "period": label,
                    "opponent_net_rating": float(opponent_strength.mean(skipna=True))
                    if opponent_strength.notna().any()
                    else np.nan,
                    "home_rate": float((played["home_away"] == "home").mean()),
                    "games_matched": int(len(played)),
                }
            )

    return pd.DataFrame(rows)


def schedule_deltas(context: pd.DataFrame) -> pd.DataFrame:
    """Change in opponent quality and home rate between the two periods."""
    if context.empty:
        return pd.DataFrame(
            columns=[
                "team_abbreviation",
                "baseline_opponent_net_rating",
                "recent_opponent_net_rating",
                "opponent_net_rating_delta",
                "baseline_home_rate",
                "recent_home_rate",
                "home_rate_delta",
            ]
        )

    baseline = context[context["period"] == BASELINE].set_index("team_abbreviation")
    recent = context[context["period"] == RECENT].set_index("team_abbreviation")
    teams = baseline.index.intersection(recent.index)

    return pd.DataFrame(
        [
            {
                "team_abbreviation": team,
                "baseline_opponent_net_rating": baseline.loc[team, "opponent_net_rating"],
                "recent_opponent_net_rating": recent.loc[team, "opponent_net_rating"],
                "opponent_net_rating_delta": recent.loc[team, "opponent_net_rating"]
                - baseline.loc[team, "opponent_net_rating"],
                "baseline_home_rate": baseline.loc[team, "home_rate"],
                "recent_home_rate": recent.loc[team, "home_rate"],
                "home_rate_delta": recent.loc[team, "home_rate"] - baseline.loc[team, "home_rate"],
                "baseline_games_matched": baseline.loc[team, "games_matched"],
                "recent_games_matched": recent.loc[team, "games_matched"],
            }
            for team in teams
        ]
    )
