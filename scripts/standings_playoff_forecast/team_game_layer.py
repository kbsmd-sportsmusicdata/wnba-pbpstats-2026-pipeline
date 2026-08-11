"""Canonical directional team-game normalization for completed WNBA games."""

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .contracts import SeasonConfig
from .data_sources import ForecastSources


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPORTSDATAVERSE_REGULAR_SEASON_TYPE = 2
REGULAR_SEASON_EVENT_ABBREVIATIONS = frozenset({"STD", "CC"})


@dataclass(frozen=True)
class LedgerValidationResult:
    completed_game_count: int
    directional_row_count: int
    game_ids: tuple[str, ...]


def normalize_id(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def _normalize_completion_flags(values: pd.Series) -> pd.Series:
    normalized: list[bool] = []
    invalid: list[str] = []
    for value in values:
        if pd.api.types.is_bool(value):
            normalized.append(bool(value))
            continue
        if pd.api.types.is_number(value) and not pd.isna(value):
            numeric = float(value)
            if math.isfinite(numeric) and numeric in (0.0, 1.0):
                normalized.append(bool(numeric))
                continue
        if isinstance(value, str):
            token = value.strip().lower()
            if token in {"0", "false"}:
                normalized.append(False)
                continue
            if token in {"1", "true"}:
                normalized.append(True)
                continue
        invalid.append(repr(value))
        normalized.append(False)
    if invalid:
        raise ValueError(
            "schedule has invalid status_type_completed values: "
            + ", ".join(sorted(set(invalid)))
        )
    return pd.Series(normalized, index=values.index, dtype=bool)


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


def validate_completed_game_ledger(
    schedule: pd.DataFrame,
    team_games: pd.DataFrame,
    cfg: SeasonConfig,
    cutoff: object | None,
) -> LedgerValidationResult:
    """Validate schedule parity and reciprocal completed-game invariants."""

    qualified = qualify_regular_season_schedule(schedule, cfg)
    completed = qualified.loc[
        _normalize_completion_flags(qualified["status_type_completed"])
    ].copy()
    if cutoff is not None:
        completed = completed.loc[
            completed["game_date"].dt.normalize()
            <= pd.Timestamp(cutoff).normalize()
        ].copy()
    completed["game_id"] = completed["game_id"].map(normalize_id)
    expected_game_ids = set(completed["game_id"])

    required_columns = {
        "game_id",
        "game_date",
        "team_id",
        "opponent_id",
        "home_away",
        "is_home",
        "win",
        "loss",
        "points_for",
        "points_against",
        "margin",
    }
    missing_columns = sorted(required_columns.difference(team_games.columns))
    if missing_columns:
        raise ValueError(
            "team_games is missing required ledger columns: "
            + ", ".join(missing_columns)
        )

    ledger = team_games.reset_index(drop=True).copy()
    for column in ("game_id", "team_id", "opponent_id"):
        ledger[column] = ledger[column].map(normalize_id)
    if ledger[["game_id", "team_id", "opponent_id"]].isna().any().any():
        raise ValueError("completed team-game ledger has invalid identifiers")
    actual_game_ids = set(ledger["game_id"])
    if expected_game_ids != actual_game_ids:
        missing_ids = ",".join(sorted(expected_game_ids - actual_game_ids)) or "none"
        unexpected_ids = ",".join(sorted(actual_game_ids - expected_game_ids)) or "none"
        raise ValueError(
            "completed game-id parity failed: "
            f"missing={missing_ids}; unexpected={unexpected_ids}"
        )

    duplicate_rows = ledger.duplicated(["game_id", "team_id"], keep=False)
    if duplicate_rows.any():
        duplicate_text = ", ".join(
            f"{row.game_id}/{row.team_id}"
            for row in ledger.loc[
                duplicate_rows, ["game_id", "team_id"]
            ].drop_duplicates().itertuples(index=False)
        )
        raise ValueError(f"duplicate directional team-game rows: {duplicate_text}")

    schedule_games = completed.set_index("game_id")
    for game_id in sorted(expected_game_ids):
        rows = ledger.loc[ledger["game_id"].eq(game_id)].copy()
        if len(rows) != 2:
            raise ValueError(
                "completed game must have exactly two directional rows: "
                f"{game_id}"
            )
        schedule_game = schedule_games.loc[game_id]
        rows["home_away"] = (
            rows["home_away"].astype("string").str.strip().str.lower()
        )
        is_home = rows["is_home"].astype("boolean")
        home_rows = rows.loc[rows["home_away"].eq("home") & is_home.fillna(False)]
        away_rows = rows.loc[rows["home_away"].eq("away") & ~is_home.fillna(True)]
        if len(home_rows) != 1 or len(away_rows) != 1:
            raise ValueError(
                f"directional participants do not match schedule: {game_id}"
            )
        home = home_rows.iloc[0]
        away = away_rows.iloc[0]
        if (
            home["team_id"] != schedule_game["home_id"]
            or home["opponent_id"] != schedule_game["away_id"]
            or away["team_id"] != schedule_game["away_id"]
            or away["opponent_id"] != schedule_game["home_id"]
            or home["team_id"] != away["opponent_id"]
            or away["team_id"] != home["opponent_id"]
        ):
            raise ValueError(
                f"directional participants do not match schedule: {game_id}"
            )
        game_dates = pd.to_datetime(rows["game_date"], errors="coerce").dt.normalize()
        if game_dates.isna().any() or not game_dates.eq(
            pd.Timestamp(schedule_game["game_date"]).normalize()
        ).all():
            raise ValueError(f"directional game_date does not match schedule: {game_id}")

        scores = rows[["points_for", "points_against"]].apply(
            pd.to_numeric, errors="coerce"
        )
        if scores.isna().any().any() or not scores.map(math.isfinite).all().all():
            raise ValueError(f"completed game must have numeric scores: {game_id}")
        home_points_for = float(scores.loc[home.name, "points_for"])
        home_points_against = float(scores.loc[home.name, "points_against"])
        away_points_for = float(scores.loc[away.name, "points_for"])
        away_points_against = float(scores.loc[away.name, "points_against"])
        if (
            home_points_for != away_points_against
            or home_points_against != away_points_for
        ):
            raise ValueError(
                f"completed game must have reciprocal points_for/points_against: {game_id}"
            )

        margins = pd.to_numeric(rows["margin"], errors="coerce")
        if margins.isna().any() or not margins.map(math.isfinite).all():
            raise ValueError(f"completed game must have numeric margins: {game_id}")
        home_margin = float(margins.loc[home.name])
        away_margin = float(margins.loc[away.name])
        if (
            home_margin == 0
            or away_margin == 0
            or home_margin != -away_margin
            or home_margin != home_points_for - home_points_against
            or away_margin != away_points_for - away_points_against
        ):
            raise ValueError(
                f"completed game must have opposite nonzero margins: {game_id}"
            )

        results = rows[["win", "loss"]].apply(pd.to_numeric, errors="coerce")
        if (
            results.isna().any().any()
            or not results.isin([0, 1]).all().all()
            or not results.sum().eq(1).all()
            or not results.sum(axis=1).eq(1).all()
        ):
            raise ValueError(f"completed game must have one winner and one loser: {game_id}")
        for row in (home, away):
            margin = float(margins.loc[row.name])
            win = int(results.loc[row.name, "win"])
            if (margin > 0) != bool(win):
                raise ValueError(
                    f"completed game result does not match score margin: {game_id}"
                )

    game_ids = tuple(sorted(expected_game_ids))
    return LedgerValidationResult(
        completed_game_count=len(game_ids),
        directional_row_count=len(team_games),
        game_ids=game_ids,
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


def _active_franchise_map(
    schedule: pd.DataFrame, team_history: pd.DataFrame, cfg: SeasonConfig
) -> pd.DataFrame:
    required = {"season", "sportsdataverse_team_id", "franchise_id"}
    missing = sorted(required.difference(team_history.columns))
    if missing:
        raise ValueError(
            "team_history is missing required columns: " + ", ".join(missing)
        )
    active = team_history.loc[
        pd.to_numeric(team_history["season"], errors="coerce").eq(cfg.season),
        ["sportsdataverse_team_id", "franchise_id"],
    ].copy()
    active["team_id"] = active["sportsdataverse_team_id"].map(normalize_id)
    if (
        active["team_id"].isna().any()
        or active["team_id"].eq("").any()
        or active["franchise_id"].isna().any()
    ):
        raise ValueError(f"team_history has invalid active rows for season {cfg.season}")
    if active["team_id"].duplicated().any():
        duplicate_ids = ", ".join(
            sorted(active.loc[active["team_id"].duplicated(False), "team_id"].unique())
        )
        raise ValueError(
            f"team_history has duplicate active team mappings for season {cfg.season}: "
            f"{duplicate_ids}"
        )

    schedule_ids = set(
        pd.concat([schedule["home_id"], schedule["away_id"]], ignore_index=True)
    )
    history_ids = set(active["team_id"])
    schedule_only = schedule_ids - history_ids
    history_only = history_ids - schedule_ids
    if schedule_only and not history_only:
        missing_text = ", ".join(sorted(schedule_only))
        raise ValueError(
            f"missing franchise mappings for season {cfg.season}: {missing_text}"
        )
    if (
        schedule_ids != history_ids
        or len(history_ids) != cfg.team_count
        or len(schedule_ids) != cfg.team_count
    ):
        schedule_only_text = ",".join(sorted(schedule_only)) or "none"
        history_only_text = ",".join(sorted(history_only)) or "none"
        raise ValueError(
            "active team-history universe does not match qualified schedule: "
            f"expected_cfg_teams={cfg.team_count}; "
            f"schedule_teams={len(schedule_ids)}; history_teams={len(history_ids)}; "
            f"schedule_only={schedule_only_text}; history_only={history_only_text}"
        )
    return active[["team_id", "franchise_id"]]


def _normalize_team_winner(value: object) -> bool | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "t", "yes", "y", "1"}:
        return True
    if text in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _completed_schedule_as_of(
    schedule: pd.DataFrame, cutoff: object | None
) -> pd.DataFrame:
    completed = schedule.loc[
        _normalize_completion_flags(schedule["status_type_completed"])
    ].copy()
    if cutoff is not None:
        completed = completed.loc[
            completed["game_date"].dt.normalize()
            <= pd.Timestamp(cutoff).normalize()
        ].copy()
    return completed


def _directional_schedule_metadata(completed: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for game in completed.itertuples(index=False):
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
                    "game_id": game.game_id,
                    "team_id": game.home_id,
                    "opponent_id": game.away_id,
                    "home_away": "home",
                    "team_abbreviation": game.home_abbreviation,
                    "team_name": game.home_display_name,
                    "opponent_abbreviation": game.away_abbreviation,
                    "opponent_name": game.away_display_name,
                    "game_minutes": game_minutes,
                },
                {
                    "game_id": game.game_id,
                    "team_id": game.away_id,
                    "opponent_id": game.home_id,
                    "home_away": "away",
                    "team_abbreviation": game.away_abbreviation,
                    "team_name": game.away_display_name,
                    "opponent_abbreviation": game.home_abbreviation,
                    "opponent_name": game.home_display_name,
                    "game_minutes": game_minutes,
                },
            ]
        )
    return pd.DataFrame(rows)


def build_team_game_layer(
    sources: ForecastSources, cfg: SeasonConfig, cutoff: object | None = None
) -> pd.DataFrame:
    """Build two directional rows per completed regular-season game.

    ``possessions_est`` averages each team's
    ``FGA - OREB + TO + 0.44 * FTA`` estimate. ``pace_est`` normalizes that
    game estimate to the WNBA's 40-minute regulation length.
    """

    schedule = qualify_regular_season_schedule(sources.schedule, cfg)
    franchise_map = _active_franchise_map(schedule, sources.team_history, cfg)
    completed = _completed_schedule_as_of(schedule, cutoff)
    expected_game_ids = set(completed["game_id"])
    if not expected_game_ids:
        result = pd.DataFrame(columns=TEAM_GAME_COLUMNS)
        validate_completed_game_ledger(sources.schedule, result, cfg, cutoff)
        _write_team_game_partition(result, cfg)
        return result

    team_box = sources.team_box.copy()
    required_team_box_columns = {
        "game_id",
        "team_id",
        "opponent_team_id",
        "team_home_away",
        "team_score",
        "opponent_team_score",
        "team_winner",
    }
    missing_team_box_columns = sorted(
        required_team_box_columns.difference(team_box.columns)
    )
    if missing_team_box_columns:
        raise ValueError(
            "team_box is missing required completed-game columns: "
            + ", ".join(missing_team_box_columns)
        )
    team_box["game_id"] = team_box["game_id"].map(normalize_id)
    team_box["team_id"] = team_box["team_id"].map(normalize_id)
    team_box["opponent_team_id"] = team_box["opponent_team_id"].map(normalize_id)
    team_box = team_box.loc[team_box["game_id"].isin(expected_game_ids)].copy()
    boolean_scores = team_box[["team_score", "opponent_team_score"]].map(
        pd.api.types.is_bool
    )
    if boolean_scores.any().any():
        raise ValueError("team_box scores must not be boolean")
    for column in BOX_SCORE_COLUMNS:
        if column not in team_box.columns:
            team_box[column] = pd.NA
        team_box[column] = pd.to_numeric(team_box[column], errors="coerce")
    team_rows = team_box[
        [
            "game_id",
            "team_id",
            "opponent_team_id",
            "team_home_away",
            "team_score",
            "opponent_team_score",
            "team_winner",
            *BOX_SCORE_COLUMNS,
        ]
    ].rename(
        columns={
            "opponent_team_id": "opponent_id",
            "team_home_away": "home_away",
            "team_score": "points_for",
            "opponent_team_score": "points_against",
        }
    )
    team_rows["home_away"] = (
        team_rows["home_away"].astype("string").str.strip().str.lower()
    )
    team_rows["is_home"] = team_rows["home_away"].eq("home")
    team_rows["points_for"] = pd.to_numeric(
        team_rows["points_for"], errors="coerce"
    )
    team_rows["points_against"] = pd.to_numeric(
        team_rows["points_against"], errors="coerce"
    )
    team_rows["margin"] = team_rows["points_for"] - team_rows["points_against"]
    team_rows["win"] = team_rows["team_winner"].map(_normalize_team_winner).astype(
        "boolean"
    )
    team_rows["loss"] = ~team_rows["win"]
    team_rows[["win", "loss"]] = team_rows[["win", "loss"]].astype("Int64")
    team_rows = team_rows.drop(columns="team_winner")
    schedule_dates = completed[["game_id", "game_date"]]
    team_rows = team_rows.merge(
        schedule_dates,
        on="game_id",
        how="left",
        validate="many_to_one",
    )
    team_rows["season"] = cfg.season
    team_rows["season_type"] = cfg.season_type
    team_rows["source_game_completed"] = True
    team_rows["source_team_box_path"] = str(sources.team_box_path)
    validate_completed_game_ledger(sources.schedule, team_rows, cfg, cutoff)

    directional_metadata = _directional_schedule_metadata(completed)
    team_rows = team_rows.merge(
        directional_metadata,
        on=["game_id", "team_id", "opponent_id", "home_away"],
        how="left",
        validate="one_to_one",
    )
    opponent_box = team_rows[["game_id", "team_id", *BOX_SCORE_COLUMNS]].rename(
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
