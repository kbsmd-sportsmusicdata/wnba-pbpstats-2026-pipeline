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

from injuries.report import frees_rotation_minutes

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


def build_position_map(game_rosters: pd.DataFrame, crosswalk: pd.DataFrame) -> dict:
    """Map pbpstats ``player_id`` -> position (G/F/C) via the ESPN game rosters and the crosswalk.

    The pbpstats feature table has no position column, so same-position opportunity weighting has
    nothing to key on without this. Positions come from the ESPN game rosters (keyed on
    ``athlete_id``) and are joined to ``player_id`` through the reviewed crosswalk.
    """
    if game_rosters is None or game_rosters.empty or crosswalk is None or crosswalk.empty:
        return {}
    if "athlete_id" not in game_rosters.columns or "athlete_position" not in game_rosters.columns:
        return {}

    rosters = game_rosters[["athlete_id", "athlete_position"]].copy()
    rosters["athlete_id"] = pd.to_numeric(rosters["athlete_id"], errors="coerce").astype("Int64")
    rosters = rosters.dropna(subset=["athlete_id"])
    rosters["athlete_position"] = rosters["athlete_position"].astype(str).str.upper().str[0]
    rosters = rosters[rosters["athlete_position"].isin(("G", "F", "C"))]
    if rosters.empty:
        return {}
    position_by_athlete = rosters.groupby("athlete_id")["athlete_position"].agg(
        lambda values: values.mode().iloc[0] if not values.mode().empty else values.iloc[0]
    )

    xwalk = crosswalk.copy()
    if "espn_athlete_id" not in xwalk.columns or "player_id" not in xwalk.columns:
        return {}
    xwalk["espn_athlete_id"] = pd.to_numeric(xwalk["espn_athlete_id"], errors="coerce").astype("Int64")
    xwalk["pid_numeric"] = pd.to_numeric(xwalk["player_id"], errors="coerce").astype("Int64")

    result: dict = {}
    for row in xwalk.dropna(subset=["espn_athlete_id", "pid_numeric"]).itertuples(index=False):
        position = position_by_athlete.get(getattr(row, "espn_athlete_id"))
        if isinstance(position, str) and position:
            result[int(getattr(row, "pid_numeric"))] = position
    return result


def apply_position_map(frame: pd.DataFrame, position_map: dict) -> pd.DataFrame:
    """Populate/refresh a ``position`` column from a player_id -> position map, keeping any existing."""
    out = frame.copy()
    if not position_map or "player_id" not in out.columns:
        return out
    ids = pd.to_numeric(out["player_id"], errors="coerce").astype("Int64")
    mapped = ids.map(lambda value: position_map.get(int(value)) if pd.notna(value) else None)
    existing = out["position"] if "position" in out.columns else pd.Series(pd.NA, index=out.index)
    existing = existing.where(existing.notna() & existing.astype(str).str.strip().ne(""), other=pd.NA)
    out["position"] = existing.fillna(mapped)
    return out


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

    For each team we sum the per-game minutes vacated by teammates whose absence durably frees a
    rotation spot -- any injury, plus anyone out for the season regardless of category (a teammate
    gone for the year opens the same minutes whether it is an injury or a departure). Short-term
    non-injury absences (national-team duty, a coach's decision) are excluded, since those minutes
    return. The blend rewards same-position vacancies: a sidelined guard helps the guards behind
    them most. The 0-100 score is a percentile among players who are themselves available -- a
    player who is also out cannot seize the opening, so their score is null.
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

    # Minutes open up from any injury and from any season-long absence (a teammate gone for the
    # year frees their role whether it is an injury or a departure); short-term non-injury
    # absences -- national-team duty, a coach's decision -- do not, so they are excluded.
    injured = injury_current.copy()
    injured = injured[injured.get("pbpstats_player_id").notna() & injured.get("is_out").fillna(False)]
    injured = injured[frees_rotation_minutes(injured)]
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
