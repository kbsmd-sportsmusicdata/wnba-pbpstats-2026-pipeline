"""Select and contextualize remaining regular-season matchups."""

import pandas as pd

from .contracts import SeasonConfig
from .team_game_layer import qualify_regular_season_schedule


_IDENTITY_COLUMNS = (
    "home_abbreviation",
    "home_display_name",
    "away_abbreviation",
    "away_display_name",
)


def _team_rest(schedule: pd.DataFrame) -> pd.DataFrame:
    home = schedule[["game_id", "game_date", "home_id"]].rename(
        columns={"home_id": "team_id"}
    )
    away = schedule[["game_id", "game_date", "away_id"]].rename(
        columns={"away_id": "team_id"}
    )
    team_schedule = pd.concat([home, away], ignore_index=True).sort_values(
        ["team_id", "game_date", "game_id"], kind="stable"
    )
    previous_date = team_schedule.groupby("team_id")["game_date"].shift()
    team_schedule["rest_days"] = (
        team_schedule["game_date"] - previous_date
    ).dt.days - 1
    team_schedule["back_to_back"] = team_schedule["rest_days"].eq(0)
    return team_schedule[["game_id", "team_id", "rest_days", "back_to_back"]]


def build_remaining_schedule(
    schedule_df: pd.DataFrame, cutoff: object, cfg: SeasonConfig
) -> pd.DataFrame:
    """Return configured games not known complete at the requested cutoff."""

    schedule = qualify_regular_season_schedule(schedule_df, cfg)
    rest = _team_rest(schedule)
    home_rest = rest.rename(
        columns={
            "team_id": "home_id",
            "rest_days": "home_rest_days",
            "back_to_back": "home_b2b",
        }
    )
    away_rest = rest.rename(
        columns={
            "team_id": "away_id",
            "rest_days": "away_rest_days",
            "back_to_back": "away_b2b",
        }
    )
    schedule = schedule.merge(
        home_rest, on=["game_id", "home_id"], how="left", validate="one_to_one"
    ).merge(
        away_rest, on=["game_id", "away_id"], how="left", validate="one_to_one"
    )
    cutoff_date = pd.Timestamp(cutoff).normalize()
    completed_at_cutoff = (
        schedule["game_date"].le(cutoff_date)
        & schedule["status_type_completed"].fillna(False).astype(bool)
    )
    remaining = schedule.loc[~completed_at_cutoff].copy()
    columns = [
        "game_id",
        "game_date",
        "home_id",
        "away_id",
        *[column for column in _IDENTITY_COLUMNS if column in remaining.columns],
        "home_rest_days",
        "away_rest_days",
        "home_b2b",
        "away_b2b",
    ]
    return remaining.reset_index(drop=True)[columns]
