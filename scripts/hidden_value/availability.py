"""Injury context for the hidden-value board.

The board answers "who is contributing more than their role implies, and who is trending up for
September". Injuries touch both edges of that question:

* **A player who is out for the season cannot matter for September.** Their skill signal is still
  real and worth recording, but selling them as a live watchlist pickup is wrong, so they are
  flagged non-actionable rather than silently ranked alongside available players.
* **An injury ahead of a player on the depth chart is opportunity.** When a starter goes down, the
  minutes and usage do not vanish -- they flow to whoever is next, which is exactly the "role
  expanding" signal the board already prizes. :func:`build_injury_opportunity` measures how much
  of that has opened up on each player's team, weighted toward their own position.

Both are context layered onto the panel; neither changes the validated composite weights.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .features import percentile


_AVAILABILITY_COLUMNS = {
    "availability_status": "Available",
    "is_out": False,
    "is_out_for_season": False,
    "is_day_to_day": False,
    "absence_category": "",
    "injury_type": "",
    "expected_return_date": "",
}


def attach_availability(panel: pd.DataFrame, injury_current: pd.DataFrame) -> pd.DataFrame:
    """Annotate each panel player with current availability, defaulting to Available.

    Adds an ``actionable`` flag that is false only for players ruled out for the season: a
    short-term "Out" or a day-to-day tag still describes a player worth watching for the stretch.
    """
    out = panel.copy()
    for column, default in _AVAILABILITY_COLUMNS.items():
        out[column] = default
    out["actionable"] = True
    if out.empty:
        return out

    if injury_current is None or injury_current.empty or "pbpstats_player_id" not in injury_current:
        return out

    injuries = injury_current.copy()
    injuries = injuries[injuries["pbpstats_player_id"].notna()]
    if injuries.empty:
        return out
    # Drop the crosswalk's text id / match columns so the numeric key can take the "player_id" name.
    injuries = injuries.drop(columns=[c for c in ("player_id", "player_id_match") if c in injuries.columns])
    injuries = injuries.rename(columns={"pbpstats_player_id": "player_id", "absence_reason": "injury_type"})
    injuries["player_id"] = pd.to_numeric(injuries["player_id"], errors="coerce").astype("Int64")
    keep = [
        "player_id",
        "availability_status",
        "is_out",
        "is_out_for_season",
        "is_day_to_day",
        "absence_category",
        "injury_type",
        "expected_return_date",
    ]
    injuries = injuries[[c for c in keep if c in injuries.columns]].drop_duplicates("player_id")

    out["player_id"] = pd.to_numeric(out["player_id"], errors="coerce").astype("Int64")
    merged = out.drop(columns=[c for c in _AVAILABILITY_COLUMNS if c in out.columns]).merge(
        injuries, on="player_id", how="left"
    )
    for column, default in _AVAILABILITY_COLUMNS.items():
        if column in ("is_out", "is_out_for_season", "is_day_to_day"):
            merged[column] = merged[column].fillna(False).astype(bool)
        else:
            merged[column] = merged[column].fillna(default)
    merged["availability_status"] = merged["availability_status"].replace("", "Available")
    merged["actionable"] = ~merged["is_out_for_season"]
    return merged


def build_injury_opportunity(
    panel: pd.DataFrame,
    injury_current: pd.DataFrame,
    player_roles: pd.DataFrame,
    *,
    position_weight: float = 0.5,
) -> pd.DataFrame:
    """Score the opportunity a player's injured teammates open up.

    ``player_roles`` is the full player universe (``player_id``, ``team_abbreviation``,
    ``position``, ``minutes``, ``games_played``) -- injured stars are scored on the role they held
    before going down, which is why the full feature table is used rather than the eligible panel.

    For each team we sum the per-game minutes vacated by teammates who are currently out with an
    *injury* (roster housekeeping -- national-team duty, coach's decisions -- is excluded, since it
    does not reliably free minutes). The blend rewards same-position vacancies: a sidelined guard
    helps the guards behind them most. The 0-100 score is a percentile among players who are
    themselves available -- a player who is also out cannot seize the opening, so their score is null.
    """
    out = panel.copy()
    out["injury_vacated_mpg_team"] = 0.0
    out["injury_vacated_mpg_position"] = 0.0
    out["injured_teammates_out"] = 0
    out["injury_opportunity_score"] = np.nan
    if out.empty:
        return out

    if injury_current is None or injury_current.empty or player_roles is None or player_roles.empty:
        return out

    roles = player_roles.copy()
    roles["player_id"] = pd.to_numeric(roles.get("player_id"), errors="coerce").astype("Int64")
    roles["minutes"] = pd.to_numeric(roles.get("minutes"), errors="coerce")
    roles["games_played"] = pd.to_numeric(roles.get("games_played"), errors="coerce")
    roles["mpg"] = np.where(
        roles["games_played"].fillna(0) > 0, roles["minutes"] / roles["games_played"], np.nan
    )
    roles["position"] = roles.get("position").astype(str).str.upper().str[0]

    injured = injury_current.copy()
    injured = injured[
        injured.get("pbpstats_player_id").notna()
        & injured.get("is_out").fillna(False)
        & injured.get("absence_category").eq("injury")
    ]
    if injured.empty:
        return out
    # Take team, position and minutes from the feature table (the same source the panel uses), so
    # an injured player's position matches the panel players competing for their minutes.
    drop_cols = ("player_id", "player_id_match", "team_abbreviation", "position", "athlete_position")
    injured = injured.drop(columns=[c for c in drop_cols if c in injured.columns])
    injured = injured.rename(columns={"pbpstats_player_id": "player_id"})
    injured["player_id"] = pd.to_numeric(injured["player_id"], errors="coerce").astype("Int64")
    injured = injured.merge(roles[["player_id", "team_abbreviation", "position", "mpg"]], on="player_id", how="left")
    injured = injured.dropna(subset=["team_abbreviation", "mpg"])
    if injured.empty:
        return out

    team_vacated = injured.groupby("team_abbreviation")["mpg"].sum()
    team_count = injured.groupby("team_abbreviation")["player_id"].nunique()
    position_vacated = injured.groupby(["team_abbreviation", "position"])["mpg"].sum()

    team_series = out["team_abbreviation"]
    position_series = out.get("position").astype(str).str.upper().str[0]
    out["injury_vacated_mpg_team"] = team_series.map(team_vacated).fillna(0.0)
    out["injured_teammates_out"] = team_series.map(team_count).fillna(0).astype(int)
    out["injury_vacated_mpg_position"] = [
        position_vacated.get((team, position), 0.0)
        for team, position in zip(team_series, position_series)
    ]

    raw = (1.0 - position_weight) * out["injury_vacated_mpg_team"] + position_weight * out[
        "injury_vacated_mpg_position"
    ]
    # Only players who can actually absorb the minutes are scored; the rest stay null.
    available = ~out.get("is_out", pd.Series(False, index=out.index)).fillna(False)
    raw_available = raw.where(available & (raw > 0))
    out["injury_opportunity_score"] = percentile(raw_available)
    return out
