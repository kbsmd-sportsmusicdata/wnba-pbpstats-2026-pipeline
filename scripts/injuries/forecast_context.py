"""Cross the playoff forecast with current availability.

The standings / playoff forecast simulates the rest of the season from team strength and the
schedule; it does not know who is hurt. That is the right design for the Monte Carlo -- health is
volatile and modelling it would add noise -- but it leaves a gap a reader fills by hand: *which of
these contenders is actually depleted heading into the stretch?*

This joins the forecast's own output (playoff odds, seed) to the current injury report on the shared
ESPN ``team_id`` and flags contenders carrying real absences. It is descriptive context that sits
beside the forecast; it never feeds back into the simulation.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


CONTEXT_COLUMNS = [
    "season",
    "cutoff_date",
    "team_id",
    "team_abbreviation",
    "current_rank",
    "expected_final_rank",
    "playoff_probability",
    "top4_probability",
    "players_out",
    "players_out_for_season",
    "injury_absences",
    "rotation_minutes_out",
    "rotation_minutes_out_share",
    "out_for_season_names",
    "players_out_names",
    "availability_flag",
]


def _team_injury_rollup(injury_current: pd.DataFrame, player_mpg: Optional[pd.DataFrame], game_minutes: float) -> pd.DataFrame:
    """Per ESPN team_id: injury counts, names, and (if minutes are supplied) vacated rotation MPG."""
    columns = [
        "team_id",
        "players_out",
        "players_out_for_season",
        "injury_absences",
        "rotation_minutes_out",
        "out_for_season_names",
        "players_out_names",
    ]
    if injury_current is None or injury_current.empty or "team_id" not in injury_current:
        return pd.DataFrame(columns=columns)

    frame = injury_current.copy()
    frame["team_id"] = pd.to_numeric(frame["team_id"], errors="coerce").astype("Int64")
    frame = frame[frame["team_id"].notna() & frame.get("is_out").fillna(False)]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    if player_mpg is not None and not player_mpg.empty and "pbpstats_player_id" in frame:
        mpg = player_mpg.copy()
        mpg["player_id"] = pd.to_numeric(mpg["player_id"], errors="coerce").astype("Int64")
        mpg_by_id = mpg.dropna(subset=["player_id"]).drop_duplicates("player_id").set_index("player_id")["mpg"]
        frame["mpg"] = pd.to_numeric(frame["pbpstats_player_id"], errors="coerce").astype("Int64").map(mpg_by_id)
    else:
        frame["mpg"] = np.nan

    rows = []
    for team_id, group in frame.groupby("team_id", sort=True):
        injury_group = group[group["absence_category"].eq("injury")]
        ofs = group[group["is_out_for_season"]]
        rows.append(
            {
                "team_id": team_id,
                "players_out": int(len(group)),
                "players_out_for_season": int(group["is_out_for_season"].sum()),
                "injury_absences": int(len(injury_group)),
                # Minutes count injury absences only -- housekeeping does not free a rotation spot.
                "rotation_minutes_out": float(injury_group["mpg"].fillna(0.0).sum()),
                "out_for_season_names": "; ".join(sorted(ofs["athlete_display_name"].tolist())),
                "players_out_names": "; ".join(sorted(group["athlete_display_name"].tolist())),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _availability_flag(row: pd.Series) -> str:
    """A short, descriptive health tag for a team's stretch outlook."""
    playoff = pd.to_numeric(pd.Series([row.get("playoff_probability")]), errors="coerce").iloc[0]
    in_race = pd.notna(playoff) and 0.05 <= playoff <= 0.95
    ofs = int(row.get("players_out_for_season") or 0)
    injuries = int(row.get("injury_absences") or 0)
    share = pd.to_numeric(pd.Series([row.get("rotation_minutes_out_share")]), errors="coerce").iloc[0]
    share = 0.0 if pd.isna(share) else share

    if injuries == 0 and ofs == 0:
        return "Healthy"
    depleted = share >= 0.25 or ofs >= 2 or injuries >= 4
    if in_race and depleted:
        return "Depleted contender"
    if depleted:
        return "Depleted"
    if ofs >= 1:
        return "Key player lost for season"
    return "Minor absences"


def build_forecast_availability_context(
    forecast_summary: pd.DataFrame,
    injury_current: pd.DataFrame,
    player_mpg: Optional[pd.DataFrame] = None,
    *,
    game_minutes: float = 200.0,
) -> pd.DataFrame:
    """One row per team: forecast odds beside current injury load, with a health flag."""
    if forecast_summary is None or forecast_summary.empty:
        return pd.DataFrame(columns=CONTEXT_COLUMNS)

    forecast = forecast_summary.copy()
    forecast["team_id"] = pd.to_numeric(forecast.get("team_id"), errors="coerce").astype("Int64")

    rollup = _team_injury_rollup(injury_current, player_mpg, game_minutes)
    merged = forecast.merge(rollup, on="team_id", how="left")

    for column, default in (
        ("players_out", 0),
        ("players_out_for_season", 0),
        ("injury_absences", 0),
        ("rotation_minutes_out", 0.0),
    ):
        merged[column] = pd.to_numeric(merged.get(column), errors="coerce").fillna(default)
    merged["players_out"] = merged["players_out"].astype(int)
    merged["players_out_for_season"] = merged["players_out_for_season"].astype(int)
    merged["injury_absences"] = merged["injury_absences"].astype(int)
    for column in ("out_for_season_names", "players_out_names"):
        merged[column] = merged.get(column, "").fillna("")
    merged["rotation_minutes_out_share"] = (merged["rotation_minutes_out"] / game_minutes).round(4)
    merged["availability_flag"] = merged.apply(_availability_flag, axis=1)

    for column in CONTEXT_COLUMNS:
        if column not in merged.columns:
            merged[column] = "" if column.endswith("names") or column == "team_abbreviation" else np.nan

    result = merged[CONTEXT_COLUMNS].copy()
    sort_key = pd.to_numeric(result["expected_final_rank"], errors="coerce")
    return result.assign(_sort=sort_key).sort_values("_sort", na_position="last").drop(columns="_sort").reset_index(drop=True)
