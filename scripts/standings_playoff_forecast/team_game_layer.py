"""Canonical directional team-game normalization for completed WNBA games."""

from pathlib import Path

import pandas as pd

from .contracts import SeasonConfig
from .data_sources import ForecastSources


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPORTSDATAVERSE_REGULAR_SEASON_TYPE = 2
REGULAR_SEASON_EVENT_ABBREVIATIONS = frozenset({"STD", "CC"})


def normalize_id(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def _qualifying_cup_games(
    schedule: pd.DataFrame, cfg: SeasonConfig
) -> pd.DataFrame:
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


def qualify_regular_season_schedule(
    schedule_df: pd.DataFrame, cfg: SeasonConfig
) -> pd.DataFrame:
    """Return the normalized, fully reconciled configured-season schedule."""

    schedule = schedule_df.copy()
    for column in ("game_id", "home_id", "away_id"):
        schedule[column] = schedule[column].map(normalize_id)
    schedule["game_date"] = pd.to_datetime(schedule["game_date"])
    schedule = schedule.loc[
        pd.to_numeric(schedule["season"], errors="coerce").eq(cfg.season)
        & pd.to_numeric(schedule["season_type"], errors="coerce").eq(
            SPORTSDATAVERSE_REGULAR_SEASON_TYPE
        )
        & schedule["type_abbreviation"]
        .astype("string")
        .str.strip()
        .str.upper()
        .isin(REGULAR_SEASON_EVENT_ABBREVIATIONS)
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
    if schedule["game_id"].isna().any():
        raise ValueError("schedule has invalid game_id values")
    if schedule["game_id"].duplicated().any():
        raise ValueError("schedule contains duplicate game_id values")
    invalid_participants = (
        schedule["home_id"].isna()
        | schedule["away_id"].isna()
        | schedule["home_id"].eq("")
        | schedule["away_id"].eq("")
        | schedule["home_id"].eq(schedule["away_id"])
    )
    if invalid_participants.any():
        raise ValueError("schedule has invalid home/away participants")
    schedule = _qualifying_cup_games(schedule, cfg)
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
    return schedule.sort_values(["game_date", "game_id"], kind="stable").reset_index(
        drop=True
    )


BOX_SCORE_COLUMNS = [
    "field_goals_made",
    "field_goals_attempted",
    "three_point_field_goals_made",
    "free_throws_made",
    "free_throws_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "turnovers",
]
TEAM_GAME_COLUMNS = [
    "season",
    "season_type",
    "game_id",
    "game_date",
    "season_game_number",
    "season_progress_pct",
    "team_id",
    "franchise_id",
    "team_abbreviation",
    "team_name",
    "opponent_id",
    "opponent_franchise_id",
    "opponent_abbreviation",
    "opponent_name",
    "home_away",
    "is_home",
    "win",
    "loss",
    "points_for",
    "points_against",
    "margin",
    "field_goals_made",
    "field_goals_attempted",
    "three_point_field_goals_made",
    "free_throws_made",
    "free_throws_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "turnovers",
    "possessions_est",
    "pace_est",
    "ortg_est",
    "drtg_est",
    "net_rating_est",
    "efg_pct",
    "opp_efg_pct",
    "tov_pct",
    "opp_tov_pct",
    "oreb_pct",
    "opp_oreb_pct",
    "ftr",
    "opp_ftr",
    "rest_days",
    "back_to_back",
    "wins_to_date",
    "losses_to_date",
    "win_pct_to_date",
    "point_diff_to_date",
    "source_game_completed",
    "source_team_box_path",
]


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.where(denominator.ne(0))
    return numerator / denominator


def _write_team_game_partition(result: pd.DataFrame, cfg: SeasonConfig) -> None:
    normalized_root = Path(cfg.normalized_team_game_root)
    if not normalized_root.is_absolute():
        normalized_root = REPOSITORY_ROOT / normalized_root
    output_path = normalized_root / f"season={cfg.season}" / "team_game.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)


def build_team_game_layer(
    sources: ForecastSources, cfg: SeasonConfig, cutoff: object | None = None
) -> pd.DataFrame:
    """Build two directional rows per completed regular-season game.

    ``possessions_est`` averages each team's
    ``FGA - OREB + TO + 0.44 * FTA`` estimate. ``pace_est`` normalizes that
    game estimate to the WNBA's 40-minute regulation length.
    """

    schedule = qualify_regular_season_schedule(sources.schedule, cfg)
    if cutoff is not None:
        schedule = schedule.loc[schedule["game_date"] <= pd.Timestamp(cutoff)].copy()

    standings_team_ids = set(sources.standings["team_id"].map(normalize_id).dropna())
    completed = schedule.loc[
        schedule["status_type_completed"].fillna(False).astype(bool)
        & schedule["home_id"].isin(standings_team_ids)
        & schedule["away_id"].isin(standings_team_ids)
    ].drop_duplicates("game_id")

    rows: list[dict] = []
    for game in completed.itertuples(index=False):
        home_score = game.home_score
        away_score = game.away_score
        regulation_periods = getattr(game, "format_regulation_periods", 4)
        if pd.isna(regulation_periods):
            regulation_periods = 4
        final_period = getattr(game, "status_period", regulation_periods)
        if pd.isna(final_period):
            final_period = regulation_periods
        game_minutes = 10 * regulation_periods + 5 * max(
            final_period - regulation_periods, 0
        )
        rows.extend(
            [
                {
                    "season": cfg.season,
                    "season_type": cfg.season_type,
                    "game_id": game.game_id,
                    "game_date": game.game_date,
                    "team_id": game.home_id,
                    "team_abbreviation": game.home_abbreviation,
                    "team_name": game.home_display_name,
                    "opponent_id": game.away_id,
                    "opponent_abbreviation": game.away_abbreviation,
                    "opponent_name": game.away_display_name,
                    "home_away": "home",
                    "is_home": True,
                    "win": int(home_score > away_score),
                    "loss": int(home_score < away_score),
                    "points_for": home_score,
                    "points_against": away_score,
                    "margin": home_score - away_score,
                    "game_minutes": game_minutes,
                    "source_game_completed": True,
                    "source_team_box_path": str(sources.team_box_path),
                },
                {
                    "season": cfg.season,
                    "season_type": cfg.season_type,
                    "game_id": game.game_id,
                    "game_date": game.game_date,
                    "team_id": game.away_id,
                    "team_abbreviation": game.away_abbreviation,
                    "team_name": game.away_display_name,
                    "opponent_id": game.home_id,
                    "opponent_abbreviation": game.home_abbreviation,
                    "opponent_name": game.home_display_name,
                    "home_away": "away",
                    "is_home": False,
                    "win": int(away_score > home_score),
                    "loss": int(away_score < home_score),
                    "points_for": away_score,
                    "points_against": home_score,
                    "margin": away_score - home_score,
                    "game_minutes": game_minutes,
                    "source_game_completed": True,
                    "source_team_box_path": str(sources.team_box_path),
                },
            ]
        )

    if not rows:
        result = pd.DataFrame(columns=TEAM_GAME_COLUMNS)
        _write_team_game_partition(result, cfg)
        return result

    team_rows = pd.DataFrame(rows)
    team_box = sources.team_box.copy()
    team_box["game_id"] = team_box["game_id"].map(normalize_id)
    team_box["team_id"] = team_box["team_id"].map(normalize_id)
    team_box = team_box.loc[team_box["game_id"].isin(team_rows["game_id"])].copy()
    for column in BOX_SCORE_COLUMNS:
        if column not in team_box.columns:
            team_box[column] = pd.NA
        team_box[column] = pd.to_numeric(team_box[column], errors="coerce")
    team_box = team_box[["game_id", "team_id", *BOX_SCORE_COLUMNS]].drop_duplicates(
        ["game_id", "team_id"]
    )
    team_rows = team_rows.merge(
        team_box, on=["game_id", "team_id"], how="left", validate="one_to_one"
    )
    opponent_box = team_box.rename(
        columns={
            "team_id": "opponent_id",
            **{column: f"opp_{column}" for column in BOX_SCORE_COLUMNS},
        }
    )
    team_rows = team_rows.merge(
        opponent_box,
        on=["game_id", "opponent_id"],
        how="left",
        validate="one_to_one",
    )

    team_history = sources.team_history.loc[
        sources.team_history["season"].eq(cfg.season),
        ["sportsdataverse_team_id", "franchise_id"],
    ].copy()
    team_history["team_id"] = team_history["sportsdataverse_team_id"].map(
        normalize_id
    )
    franchise_map = team_history[["team_id", "franchise_id"]].drop_duplicates(
        "team_id"
    )
    team_rows = team_rows.merge(
        franchise_map, on="team_id", how="left", validate="many_to_one"
    )
    opponent_franchise_map = franchise_map.rename(
        columns={
            "team_id": "opponent_id",
            "franchise_id": "opponent_franchise_id",
        }
    )
    team_rows = team_rows.merge(
        opponent_franchise_map,
        on="opponent_id",
        how="left",
        validate="many_to_one",
    )
    missing_team_ids = set(
        team_rows.loc[team_rows["franchise_id"].isna(), "team_id"]
    ) | set(
        team_rows.loc[
            team_rows["opponent_franchise_id"].isna(), "opponent_id"
        ]
    )
    if missing_team_ids:
        missing_text = ", ".join(sorted(missing_team_ids))
        raise ValueError(
            f"missing franchise mappings for season {cfg.season}: {missing_text}"
        )

    team_possessions = (
        team_rows["field_goals_attempted"]
        - team_rows["offensive_rebounds"]
        + team_rows["turnovers"]
        + 0.44 * team_rows["free_throws_attempted"]
    )
    opponent_possessions = (
        team_rows["opp_field_goals_attempted"]
        - team_rows["opp_offensive_rebounds"]
        + team_rows["opp_turnovers"]
        + 0.44 * team_rows["opp_free_throws_attempted"]
    )
    team_rows["possessions_est"] = (team_possessions + opponent_possessions) / 2
    team_rows["pace_est"] = 40 * _safe_divide(
        team_rows["possessions_est"], team_rows["game_minutes"]
    )
    team_rows["efg_pct"] = _safe_divide(
        team_rows["field_goals_made"]
        + 0.5 * team_rows["three_point_field_goals_made"],
        team_rows["field_goals_attempted"],
    )
    team_rows["opp_efg_pct"] = _safe_divide(
        team_rows["opp_field_goals_made"]
        + 0.5 * team_rows["opp_three_point_field_goals_made"],
        team_rows["opp_field_goals_attempted"],
    )
    team_rows["tov_pct"] = _safe_divide(
        team_rows["turnovers"], team_rows["possessions_est"]
    )
    team_rows["opp_tov_pct"] = _safe_divide(
        team_rows["opp_turnovers"], team_rows["possessions_est"]
    )
    team_rows["oreb_pct"] = _safe_divide(
        team_rows["offensive_rebounds"],
        team_rows["offensive_rebounds"] + team_rows["opp_defensive_rebounds"],
    )
    team_rows["opp_oreb_pct"] = _safe_divide(
        team_rows["opp_offensive_rebounds"],
        team_rows["opp_offensive_rebounds"] + team_rows["defensive_rebounds"],
    )
    team_rows["ftr"] = _safe_divide(
        team_rows["free_throws_attempted"], team_rows["field_goals_attempted"]
    )
    team_rows["opp_ftr"] = _safe_divide(
        team_rows["opp_free_throws_attempted"],
        team_rows["opp_field_goals_attempted"],
    )
    team_rows["ortg_est"] = 100 * _safe_divide(
        team_rows["points_for"], team_rows["possessions_est"]
    )
    team_rows["drtg_est"] = 100 * _safe_divide(
        team_rows["points_against"], team_rows["possessions_est"]
    )
    team_rows["net_rating_est"] = team_rows["ortg_est"] - team_rows["drtg_est"]

    team_rows = team_rows.sort_values(
        ["team_id", "game_date", "game_id"], kind="stable"
    )
    team_rows["season_game_number"] = team_rows.groupby("team_id").cumcount() + 1
    team_rows["season_progress_pct"] = (
        team_rows["season_game_number"] / cfg.regular_season_games_per_team
    )
    team_rows["wins_to_date"] = team_rows.groupby("team_id")["win"].cumsum()
    team_rows["losses_to_date"] = team_rows.groupby("team_id")["loss"].cumsum()
    team_rows["win_pct_to_date"] = (
        team_rows["wins_to_date"] / team_rows["season_game_number"]
    )
    team_rows["point_diff_to_date"] = team_rows.groupby("team_id")[
        "margin"
    ].cumsum()
    days_between_games = team_rows.groupby("team_id")["game_date"].diff().dt.days
    team_rows["rest_days"] = (days_between_games - 1).astype("Int64")
    team_rows["back_to_back"] = team_rows["rest_days"].eq(0).fillna(False)
    result = team_rows.reset_index(drop=True)[TEAM_GAME_COLUMNS]
    _write_team_game_partition(result, cfg)
    return result
