"""Select and reconcile remaining regular-season matchups."""

import math

import pandas as pd

from .contracts import SeasonConfig
from .team_game_layer import normalize_id, qualify_regular_season_schedule


_IDENTITY_COLUMNS = (
    "home_abbreviation",
    "home_display_name",
    "away_abbreviation",
    "away_display_name",
)

_SEASON_SCHEDULE_COUNT_COLUMNS = (
    "team_id",
    "completed_gp",
    "remaining_games",
    "configured_games",
    "total_games",
    "status",
)


def validate_season_schedule_counts(
    current_standings: pd.DataFrame,
    remaining_schedule: pd.DataFrame,
    cfg: SeasonConfig,
) -> pd.DataFrame:
    """Require every configured team to reconcile to its season game count."""

    standings_required = {"team_id", "games_played"}
    missing_standings_columns = sorted(
        standings_required.difference(current_standings.columns)
    )
    if missing_standings_columns:
        raise ValueError(
            "current standings is missing required columns: "
            + ", ".join(missing_standings_columns)
        )
    standings = current_standings.loc[:, ["team_id", "games_played"]].copy()
    standings["team_id"] = standings["team_id"].map(normalize_id)
    invalid_team_ids = standings["team_id"].isna() | standings["team_id"].eq("")
    if invalid_team_ids.any() or standings["team_id"].duplicated().any():
        raise ValueError("current standings has an invalid team universe")
    if standings["games_played"].map(pd.api.types.is_bool).any():
        raise ValueError("current standings has invalid completed games_played")
    completed_games = pd.to_numeric(standings["games_played"], errors="coerce")
    invalid_completed_games = (
        completed_games.isna()
        | ~completed_games.map(math.isfinite)
        | completed_games.lt(0)
        | completed_games.gt(cfg.regular_season_games_per_team)
        | completed_games.mod(1).ne(0)
    )
    if invalid_completed_games.any():
        raise ValueError("current standings has invalid completed games_played")
    standings["completed_gp"] = completed_games.astype(int)
    if len(standings) != cfg.team_count:
        raise ValueError(
            "current standings team universe failed: "
            f"expected {cfg.team_count} teams; observed {len(standings)}"
        )

    remaining_required = {"game_id", "home_id", "away_id"}
    missing_remaining_columns = sorted(
        remaining_required.difference(remaining_schedule.columns)
    )
    if missing_remaining_columns:
        raise ValueError(
            "remaining schedule is missing required columns: "
            + ", ".join(missing_remaining_columns)
        )
    remaining = remaining_schedule.loc[:, ["game_id", "home_id", "away_id"]].copy()
    for column in ("game_id", "home_id", "away_id"):
        remaining[column] = remaining[column].map(normalize_id)
    invalid_game_ids = remaining["game_id"].isna() | remaining["game_id"].eq("")
    if invalid_game_ids.any():
        raise ValueError("remaining schedule has invalid game_id values")
    if remaining["game_id"].duplicated().any():
        raise ValueError("remaining schedule contains duplicate game_id values")
    invalid_participants = (
        remaining["home_id"].isna()
        | remaining["away_id"].isna()
        | remaining["home_id"].eq("")
        | remaining["away_id"].eq("")
    )
    if invalid_participants.any():
        raise ValueError("remaining schedule has invalid home/away participants")
    if remaining["home_id"].eq(remaining["away_id"]).any():
        raise ValueError("remaining schedule has same-team participants")

    team_ids = set(standings["team_id"])
    participant_ids = set(remaining["home_id"]).union(remaining["away_id"])
    unknown_team_ids = sorted(participant_ids.difference(team_ids))
    if unknown_team_ids:
        raise ValueError(
            "remaining schedule has unknown team IDs: " + ", ".join(unknown_team_ids)
        )

    remaining_games = pd.concat(
        [remaining["home_id"], remaining["away_id"]], ignore_index=True
    ).value_counts()
    result = standings.sort_values("team_id", kind="stable").reset_index(drop=True)
    result["remaining_games"] = (
        result["team_id"].map(remaining_games).fillna(0).astype(int)
    )
    result["configured_games"] = cfg.regular_season_games_per_team
    result["total_games"] = result["completed_gp"] + result["remaining_games"]
    if result["total_games"].ne(cfg.regular_season_games_per_team).any():
        counts = ", ".join(
            f"{row.team_id}={row.total_games}"
            for row in result.loc[
                result["total_games"].ne(cfg.regular_season_games_per_team),
                ["team_id", "total_games"],
            ].itertuples(index=False)
        )
        raise ValueError(
            "season schedule count mismatch: "
            f"expected {cfg.regular_season_games_per_team} games per team; "
            f"observed {counts}"
        )
    result["status"] = "validated"
    return result.loc[:, _SEASON_SCHEDULE_COUNT_COLUMNS]


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
