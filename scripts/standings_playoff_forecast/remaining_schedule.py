"""Select and contextualize remaining regular-season matchups."""

import pandas as pd

from .contracts import SeasonConfig
from .team_game_layer import normalize_id


_IDENTITY_COLUMNS = (
    "home_abbreviation",
    "home_display_name",
    "away_abbreviation",
    "away_display_name",
)


def _qualifying_cup_games(schedule: pd.DataFrame, cfg: SeasonConfig) -> pd.DataFrame:
    standard = schedule.loc[schedule["type_abbreviation"].eq("STD")].copy()
    participant_counts = pd.concat(
        [standard["home_id"], standard["away_id"]], ignore_index=True
    ).value_counts().to_dict()
    qualifying_indexes: list[object] = []
    cup_games = schedule.loc[schedule["type_abbreviation"].eq("CC")].sort_values(
        ["game_date", "game_id"], kind="stable"
    )
    for game in cup_games.itertuples():
        home_count = participant_counts.get(game.home_id, 0)
        away_count = participant_counts.get(game.away_id, 0)
        if (
            home_count < cfg.regular_season_games_per_team
            and away_count < cfg.regular_season_games_per_team
        ):
            qualifying_indexes.append(game.Index)
            participant_counts[game.home_id] = home_count + 1
            participant_counts[game.away_id] = away_count + 1
    return pd.concat([standard, schedule.loc[qualifying_indexes]], ignore_index=True)


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


def _validate_reconciliation(schedule: pd.DataFrame, cfg: SeasonConfig) -> None:
    counts = pd.concat(
        [schedule["home_id"], schedule["away_id"]], ignore_index=True
    ).value_counts()
    if len(counts) != cfg.team_count or not counts.eq(
        cfg.regular_season_games_per_team
    ).all():
        count_text = ", ".join(
            f"{team_id}={count}" for team_id, count in counts.sort_index().items()
        )
        raise ValueError(
            "schedule reconciliation failed: "
            f"expected {cfg.team_count} teams with "
            f"{cfg.regular_season_games_per_team} games each; observed {count_text}"
        )


def build_remaining_schedule(
    schedule_df: pd.DataFrame, cutoff: object, cfg: SeasonConfig
) -> pd.DataFrame:
    """Return configured games not known complete at the requested cutoff."""

    schedule = schedule_df.copy()
    for column in ("game_id", "home_id", "away_id"):
        schedule[column] = schedule[column].map(normalize_id)
    schedule["game_date"] = pd.to_datetime(schedule["game_date"])
    schedule = schedule.loc[
        pd.to_numeric(schedule["season"], errors="coerce").eq(cfg.season)
        & pd.to_numeric(schedule["season_type"], errors="coerce").eq(2)
        & schedule["type_abbreviation"]
        .astype("string")
        .str.strip()
        .str.upper()
        .isin(("STD", "CC"))
    ].copy()
    schedule["type_abbreviation"] = (
        schedule["type_abbreviation"].astype("string").str.strip().str.upper()
    )
    schedule = schedule.loc[
        ~schedule["status_type_name"]
        .astype("string")
        .str.strip()
        .str.upper()
        .eq("STATUS_POSTPONED")
    ].copy()
    if schedule["game_id"].duplicated().any():
        raise ValueError("schedule contains duplicate game_id values")
    invalid_participants = (
        schedule["home_id"].isna()
        | schedule["away_id"].isna()
        | schedule["home_id"].eq(schedule["away_id"])
    )
    if invalid_participants.any():
        raise ValueError("schedule has invalid home/away participants")
    schedule = _qualifying_cup_games(schedule, cfg)
    _validate_reconciliation(schedule, cfg)
    schedule = schedule.sort_values(["game_date", "game_id"], kind="stable")
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
