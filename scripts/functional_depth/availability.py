"""Current availability overlay for the Functional Depth Score.

The five depth components describe how a team's production is distributed and how it holds up when
starters sit -- depth *on paper*, over the season. They do not know who is available tonight. A team
that reads as deep can still be thin *right now* if several rotation players are hurt.

This overlay closes that gap without touching the score: for each team it measures how many
rotation minutes are currently vacated by a durable absence -- any injury, plus a season-long
absence of any category (a player gone for the year frees their minutes whether it is an injury or a
departure) -- as a share of a 200-minute game, so a reader can hold "deep on paper" and "thin right
now" side by side. It is additive and optional -- with no injury feed, every team reads fully
available.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from injuries.report import frees_rotation_minutes


_AVAILABILITY_COLUMNS = {
    "players_out_now": 0,
    "players_out_for_season_now": 0,
    "rotation_minutes_out": 0.0,
    "rotation_minutes_out_share": 0.0,
    "current_availability": "Intact",
    "players_out_now_names": "",
}


def build_player_mpg(player_game: pd.DataFrame) -> pd.DataFrame:
    """Per-player minutes-per-game and the team they most recently played for."""
    columns = ["player_id", "team_abbreviation", "games", "minutes_total", "mpg"]
    if player_game is None or player_game.empty:
        return pd.DataFrame(columns=columns)

    frame = player_game.copy()
    frame["player_id"] = pd.to_numeric(frame.get("player_id"), errors="coerce").astype("Int64")
    frame["minutes"] = pd.to_numeric(frame.get("minutes"), errors="coerce")
    frame = frame.dropna(subset=["player_id"])
    if "game_date" in frame.columns:
        frame = frame.sort_values("game_date")

    grouped = frame.groupby("player_id")
    latest_team = grouped["team_abbreviation"].last()
    minutes_total = grouped["minutes"].sum()
    games = grouped["minutes"].apply(lambda s: int(s.notna().sum()))
    out = pd.DataFrame(
        {
            "player_id": minutes_total.index,
            "team_abbreviation": latest_team.values,
            "games": games.values,
            "minutes_total": minutes_total.values,
        }
    )
    out["mpg"] = np.where(out["games"] > 0, out["minutes_total"] / out["games"], np.nan)
    return out.reset_index(drop=True)


def attach_current_availability(
    depth: pd.DataFrame,
    player_game: pd.DataFrame,
    injury_current: pd.DataFrame,
    *,
    game_minutes: float = 200.0,
    thinned_share: float = 0.10,
    depleted_share: float = 0.25,
) -> pd.DataFrame:
    """Annotate each team row with how much of its rotation is currently sidelined by injury."""
    out = depth.copy()
    for column, default in _AVAILABILITY_COLUMNS.items():
        out[column] = default
    if out.empty:
        return out
    if injury_current is None or injury_current.empty or "pbpstats_player_id" not in injury_current:
        return out

    mpg = build_player_mpg(player_game)
    if mpg.empty:
        return out

    # Vacated minutes count any injury plus season-long absences of any category (a player gone
    # for the year frees their minutes); short-term non-injury absences do not.
    injured = injury_current.copy()
    injured = injured[injured["pbpstats_player_id"].notna() & injured.get("is_out").fillna(False)]
    injured = injured[frees_rotation_minutes(injured)]
    if injured.empty:
        return out
    injured = injured[["pbpstats_player_id", "is_out_for_season", "athlete_display_name"]].rename(
        columns={"pbpstats_player_id": "player_id"}
    )
    injured["player_id"] = pd.to_numeric(injured["player_id"], errors="coerce").astype("Int64")
    # Team and minutes come from the game layer -- the same source the depth score is built on -- so
    # an injured player's minutes land on the team the score credited them to.
    injured = injured.merge(mpg[["player_id", "team_abbreviation", "mpg"]], on="player_id", how="left")
    injured = injured.dropna(subset=["team_abbreviation", "mpg"])
    if injured.empty:
        return out

    rollup = injured.groupby("team_abbreviation").agg(
        players_out_now=("player_id", "nunique"),
        players_out_for_season_now=("is_out_for_season", "sum"),
        rotation_minutes_out=("mpg", "sum"),
        players_out_now_names=("athlete_display_name", lambda s: "; ".join(sorted(s))),
    )
    rollup["rotation_minutes_out_share"] = (rollup["rotation_minutes_out"] / game_minutes).round(4)

    for column in ("players_out_now", "players_out_for_season_now", "rotation_minutes_out",
                   "rotation_minutes_out_share", "players_out_now_names"):
        out[column] = out["team_abbreviation"].map(rollup[column])
    out["players_out_now"] = out["players_out_now"].fillna(0).astype(int)
    out["players_out_for_season_now"] = out["players_out_for_season_now"].fillna(0).astype(int)
    out["rotation_minutes_out"] = out["rotation_minutes_out"].fillna(0.0)
    out["rotation_minutes_out_share"] = out["rotation_minutes_out_share"].fillna(0.0)
    out["players_out_now_names"] = out["players_out_now_names"].fillna("")

    out["current_availability"] = np.select(
        [out["rotation_minutes_out_share"] >= depleted_share, out["rotation_minutes_out_share"] >= thinned_share],
        ["Depleted", "Thinned"],
        default="Intact",
    )
    return out
