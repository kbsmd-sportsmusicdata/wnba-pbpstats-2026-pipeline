"""Current standings, directional head-to-head, and optional external QA."""

from dataclasses import dataclass

import pandas as pd

from .contracts import SeasonConfig
from .team_game_layer import normalize_id, qualify_regular_season_schedule


STANDINGS_COLUMNS = [
    "team_id",
    "franchise_id",
    "team_abbreviation",
    "team_name",
    "games_played",
    "wins",
    "losses",
    "win_pct",
    "points_for",
    "points_against",
    "point_differential",
    "games_back",
    "home_wins",
    "home_losses",
    "road_wins",
    "road_losses",
    "home_record",
    "road_record",
    "last10_wins",
    "last10_losses",
    "last10_record",
    "current_streak_type",
    "current_streak_length",
    "current_streak_label",
    "conference_wins",
    "conference_losses",
    "conference_record",
    "record_vs_current_500_plus_wins",
    "record_vs_current_500_plus_losses",
    "record_vs_current_500_plus",
    "record_vs_current_500_plus_pct",
    "current_rank",
    "playoff_cutline_flag",
]
HEAD_TO_HEAD_COLUMNS = [
    "team_id",
    "franchise_id",
    "opponent_id",
    "opponent_franchise_id",
    "games_played",
    "wins",
    "losses",
    "win_pct",
    "points_for",
    "points_against",
    "point_differential",
]
_TEAM_GAME_REQUIRED_COLUMNS = {
    "game_id",
    "team_id",
    "opponent_id",
    "win",
    "loss",
    "points_for",
    "points_against",
    "margin",
}


@dataclass(frozen=True)
class ExternalStandingsQA:
    """Non-blocking comparison of ledger-derived and external W/L records."""

    status: str
    compared_team_count: int
    mismatch_team_ids: tuple[str, ...]
    message: str


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def _validate_directional_team_games(team_games: pd.DataFrame) -> None:
    _require_columns(team_games, _TEAM_GAME_REQUIRED_COLUMNS, "team_games")
    duplicate_rows = team_games.duplicated(["game_id", "team_id"], keep=False)
    if duplicate_rows.any():
        duplicates = team_games.loc[duplicate_rows, ["game_id", "team_id"]]
        duplicate_text = ", ".join(
            f"{row.game_id}/{row.team_id}"
            for row in duplicates.drop_duplicates().itertuples(index=False)
        )
        raise ValueError(f"duplicate directional team-game rows: {duplicate_text}")


def _identity_columns(team_games: pd.DataFrame) -> list[str]:
    return [
        column
        for column in ("franchise_id", "team_abbreviation", "team_name")
        if column in team_games.columns
    ]


def _presentation_metadata(
    team_games: pd.DataFrame,
    key_columns: list[str],
    metadata_columns: list[str],
) -> pd.DataFrame:
    """Attach stable presentation metadata after aggregating stable identifiers."""

    available_columns = [
        column for column in metadata_columns if column in team_games.columns
    ]
    if not available_columns:
        return team_games[key_columns].drop_duplicates()

    metadata_counts = (
        team_games.groupby(key_columns, dropna=False)[available_columns]
        .nunique(dropna=False)
    )
    conflicts = metadata_counts.gt(1).any(axis=1)
    if conflicts.any():
        key = conflicts.index[conflicts][0]
        key_values = key if isinstance(key, tuple) else (key,)
        key_text = ", ".join(
            f"{column}={value}" for column, value in zip(key_columns, key_values)
        )
        raise ValueError(f"conflicting presentation metadata for {key_text}")
    return team_games[key_columns + available_columns].drop_duplicates(key_columns)


def _aggregate_records(
    team_games: pd.DataFrame, group_columns: list[str]
) -> pd.DataFrame:
    result = (
        team_games.groupby(group_columns, dropna=False, sort=True)
        .agg(
            games_played=("game_id", "size"),
            wins=("win", "sum"),
            losses=("loss", "sum"),
            points_for=("points_for", "sum"),
            points_against=("points_against", "sum"),
        )
        .reset_index()
    )
    result["point_differential"] = result["points_for"] - result["points_against"]
    result["win_pct"] = result["wins"] / result["games_played"]
    return result


def _validated_team_universe(
    team_universe: pd.DataFrame, cfg: SeasonConfig
) -> pd.DataFrame:
    required = {
        "team_id",
        "franchise_id",
        "team_abbreviation",
        "team_name",
    }
    _require_columns(team_universe, required, "team_universe")
    result = team_universe[list(required)].copy()
    result["team_id"] = result["team_id"].map(normalize_id)
    for column in ("franchise_id", "team_abbreviation", "team_name"):
        result[column] = result[column].astype("string").str.strip()
    if result.isna().any().any() or result.astype("string").eq("").any().any():
        raise ValueError("team_universe contains missing or blank identities")
    if result["team_id"].duplicated().any():
        raise ValueError("team_universe contains duplicate normalized team_id values")
    if result["franchise_id"].duplicated().any():
        raise ValueError("team_universe contains duplicate franchise_id values")
    if len(result) != cfg.team_count:
        raise ValueError(
            "team_universe must contain exactly "
            f"{cfg.team_count} configured teams"
        )
    return result[
        ["team_id", "franchise_id", "team_abbreviation", "team_name"]
    ].sort_values("team_id", kind="stable").reset_index(drop=True)


def _team_universe_from_sources(
    schedule: pd.DataFrame,
    team_history: pd.DataFrame,
    cfg: SeasonConfig,
) -> pd.DataFrame:
    qualified = qualify_regular_season_schedule(schedule, cfg)
    required_history = {
        "season",
        "sportsdataverse_team_id",
        "franchise_id",
    }
    _require_columns(team_history, required_history, "team_history")
    active = team_history.loc[
        pd.to_numeric(team_history["season"], errors="coerce").eq(cfg.season),
        ["sportsdataverse_team_id", "franchise_id"],
    ].rename(columns={"sportsdataverse_team_id": "team_id"})
    active["team_id"] = active["team_id"].map(normalize_id)

    home = qualified[
        ["home_id", "home_abbreviation", "home_display_name"]
    ].rename(
        columns={
            "home_id": "team_id",
            "home_abbreviation": "team_abbreviation",
            "home_display_name": "team_name",
        }
    )
    away = qualified[
        ["away_id", "away_abbreviation", "away_display_name"]
    ].rename(
        columns={
            "away_id": "team_id",
            "away_abbreviation": "team_abbreviation",
            "away_display_name": "team_name",
        }
    )
    presentation = pd.concat([home, away], ignore_index=True)
    presentation["team_id"] = presentation["team_id"].map(normalize_id)
    presentation = _presentation_metadata(
        presentation,
        ["team_id"],
        ["team_abbreviation", "team_name"],
    )
    universe = active.merge(
        presentation,
        on="team_id",
        how="outer",
        validate="one_to_one",
    )
    return _validated_team_universe(universe, cfg)


def build_current_standings(
    team_games: pd.DataFrame,
    cfg: SeasonConfig,
    *,
    team_universe: pd.DataFrame | None = None,
    schedule: pd.DataFrame | None = None,
    team_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate the normalized directional rows into unranked current standings."""

    _validate_directional_team_games(team_games)
    if team_universe is None and schedule is not None and team_history is not None:
        team_universe = _team_universe_from_sources(schedule, team_history, cfg)
    elif (schedule is None) != (team_history is None):
        raise ValueError("schedule and team_history must be supplied together")

    if team_universe is None:
        if team_games.empty:
            return pd.DataFrame(columns=STANDINGS_COLUMNS)
        metadata_columns = _identity_columns(team_games)
        result = _aggregate_records(team_games, ["team_id"])
        result = result.merge(
            _presentation_metadata(team_games, ["team_id"], metadata_columns),
            on="team_id",
            how="left",
            validate="one_to_one",
        )
        return result.reindex(columns=STANDINGS_COLUMNS)

    universe = _validated_team_universe(team_universe, cfg)
    metadata_columns = _identity_columns(team_games)
    game_metadata = _presentation_metadata(
        team_games, ["team_id"], metadata_columns
    )
    unexpected = set(game_metadata["team_id"].map(normalize_id)) - set(
        universe["team_id"]
    )
    if unexpected:
        raise ValueError(
            "team_games contains teams outside team_universe: "
            + ", ".join(sorted(unexpected))
        )
    shared_metadata = [
        column
        for column in ("franchise_id", "team_abbreviation", "team_name")
        if column in game_metadata.columns
    ]
    if shared_metadata:
        comparison = game_metadata.merge(
            universe,
            on="team_id",
            how="left",
            suffixes=("_game", "_universe"),
            validate="one_to_one",
        )
        conflicts = pd.Series(False, index=comparison.index)
        for column in shared_metadata:
            game_values = comparison[f"{column}_game"].astype("string").str.strip()
            universe_values = comparison[f"{column}_universe"].astype("string").str.strip()
            conflicts |= game_values.ne(universe_values).fillna(True)
        if conflicts.any():
            team_ids = ", ".join(
                sorted(comparison.loc[conflicts, "team_id"].astype(str))
            )
            raise ValueError(
                "team_games presentation metadata conflicts with team_universe: "
                + team_ids
            )
    aggregates = _aggregate_records(team_games, ["team_id"])
    result = universe.merge(
        aggregates,
        on="team_id",
        how="left",
        validate="one_to_one",
    )
    count_columns = [
        "games_played",
        "wins",
        "losses",
        "points_for",
        "points_against",
        "point_differential",
    ]
    result[count_columns] = result[count_columns].fillna(0)
    result["win_pct"] = (
        result["wins"] / result["games_played"]
    ).where(result["games_played"].gt(0), pd.NA)
    return result.reindex(columns=STANDINGS_COLUMNS)


def _record_context(
    games: pd.DataFrame,
    team_ids: pd.Index,
    prefix: str,
) -> pd.DataFrame:
    records = (
        games.groupby("team_id", sort=True)
        .agg(wins=("win", "sum"), losses=("loss", "sum"))
        .reindex(team_ids, fill_value=0)
    )
    records = records.rename(
        columns={"wins": f"{prefix}_wins", "losses": f"{prefix}_losses"}
    )
    records[f"{prefix}_record"] = (
        records[f"{prefix}_wins"].astype(str)
        + "-"
        + records[f"{prefix}_losses"].astype(str)
    )
    return records


def add_current_standings_context(
    standings: pd.DataFrame,
    team_games: pd.DataFrame,
    cfg: SeasonConfig,
) -> pd.DataFrame:
    """Add ledger-derived descriptive context to already-ranked standings.

    Conference fields remain nullable because the validated team-history contract
    does not currently provide conference membership.
    """

    _require_columns(
        standings,
        {"team_id", "wins", "losses", "win_pct", "current_rank"},
        "standings",
    )
    _validate_directional_team_games(team_games)
    _require_columns(team_games, {"game_date", "home_away"}, "team_games")
    if standings["team_id"].duplicated().any():
        raise ValueError("standings contains duplicate team_id values")

    ranks = pd.to_numeric(standings["current_rank"], errors="coerce")
    expected_ranks = list(range(1, cfg.team_count + 1))
    if (
        ranks.isna().any()
        or ranks.mod(1).ne(0).any()
        or sorted(ranks.astype(int).tolist()) != expected_ranks
    ):
        raise ValueError(
            "standings current_rank must be a complete permutation from "
            f"1 through {cfg.team_count}"
        )
    leader_rows = standings.loc[ranks.eq(1)]
    if len(leader_rows) != 1:
        raise ValueError("standings current_rank must contain exactly one rank 1")

    context_columns = [
        column
        for column in STANDINGS_COLUMNS
        if column not in STANDINGS_COLUMNS[:11] and column != "current_rank"
    ]
    result = standings.drop(columns=context_columns, errors="ignore").copy()
    result["current_rank"] = ranks.astype(int)
    team_ids = pd.Index(result["team_id"], name="team_id")
    games = team_games.copy()
    games["game_date"] = pd.to_datetime(games["game_date"], errors="coerce")
    if games["game_date"].isna().any():
        raise ValueError("team_games contains invalid game_date values")
    games["home_away"] = games["home_away"].astype("string").str.strip().str.lower()
    if not games["home_away"].isin({"home", "away"}).all():
        raise ValueError("team_games home_away must be home or away")
    games = games.sort_values(
        ["team_id", "game_date", "game_id"], kind="stable"
    ).reset_index(drop=True)

    leader = leader_rows.iloc[0]
    result["games_back"] = (
        (float(leader["wins"]) - pd.to_numeric(result["wins"]))
        + (pd.to_numeric(result["losses"]) - float(leader["losses"]))
    ) / 2.0

    home = _record_context(
        games.loc[games["home_away"].eq("home")], team_ids, "home"
    )
    road = _record_context(
        games.loc[games["home_away"].eq("away")], team_ids, "road"
    )
    result = result.merge(home, on="team_id", how="left", validate="one_to_one")
    result = result.merge(road, on="team_id", how="left", validate="one_to_one")

    last10_games = games.groupby("team_id", sort=False, group_keys=False).tail(10)
    last10 = _record_context(last10_games, team_ids, "last10")
    result = result.merge(last10, on="team_id", how="left", validate="one_to_one")

    streak_rows: list[dict[str, object]] = []
    for team_id, team_rows in games.groupby("team_id", sort=True):
        results = team_rows["win"].astype(int).tolist()
        streak_type = "W" if results[-1] == 1 else "L"
        streak_value = 1 if streak_type == "W" else 0
        streak_length = 0
        for value in reversed(results):
            if value != streak_value:
                break
            streak_length += 1
        streak_rows.append(
            {
                "team_id": team_id,
                "current_streak_type": streak_type,
                "current_streak_length": streak_length,
                "current_streak_label": f"{streak_type}{streak_length}",
            }
        )
    result = result.merge(
        pd.DataFrame(streak_rows), on="team_id", how="left", validate="one_to_one"
    )

    current_500_ids = set(
        standings.loc[standings["win_pct"].ge(0.500), "team_id"]
    )
    current_500_games = games.loc[games["opponent_id"].isin(current_500_ids)]
    current_500 = _record_context(
        current_500_games, team_ids, "record_vs_current_500_plus"
    ).rename(
        columns={
            "record_vs_current_500_plus_record": "record_vs_current_500_plus"
        }
    )
    qualifying_games = (
        current_500["record_vs_current_500_plus_wins"]
        + current_500["record_vs_current_500_plus_losses"]
    )
    current_500["record_vs_current_500_plus_pct"] = (
        current_500["record_vs_current_500_plus_wins"] / qualifying_games
    ).where(qualifying_games.gt(0), pd.NA)
    result = result.merge(
        current_500, on="team_id", how="left", validate="one_to_one"
    )

    result["conference_wins"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["conference_losses"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["conference_record"] = pd.Series(pd.NA, index=result.index, dtype="string")

    top4_limit = min(4, cfg.playoff_qualifiers)
    chase_limit = min(cfg.team_count, cfg.playoff_qualifiers + 2)

    def cutline_flag(rank: int) -> str:
        if rank <= top4_limit:
            return "top4"
        if rank <= cfg.playoff_qualifiers:
            return "playoff_field"
        if rank <= chase_limit:
            return "cutline_chase"
        return "outside"

    result["playoff_cutline_flag"] = (
        pd.to_numeric(result["current_rank"]).astype(int).map(cutline_flag)
    )
    return result.reindex(columns=STANDINGS_COLUMNS)


def build_head_to_head(team_games: pd.DataFrame) -> pd.DataFrame:
    """Aggregate ordered team-opponent pairs without collapsing reciprocal records."""

    _validate_directional_team_games(team_games)
    if team_games.empty:
        return pd.DataFrame(columns=HEAD_TO_HEAD_COLUMNS)

    key_columns = ["team_id", "opponent_id"]
    metadata_columns = [
        *_identity_columns(team_games),
        "opponent_franchise_id",
    ]
    result = _aggregate_records(team_games, key_columns)
    result = result.merge(
        _presentation_metadata(team_games, key_columns, metadata_columns),
        on=key_columns,
        how="left",
        validate="one_to_one",
    )
    return result.reindex(columns=HEAD_TO_HEAD_COLUMNS)


def _validate_derived_invariants(standings: pd.DataFrame) -> None:
    _require_columns(
        standings,
        {
            "team_id",
            "games_played",
            "wins",
            "losses",
            "points_for",
            "points_against",
            "point_differential",
        },
        "derived standings",
    )
    normalized_team_ids = standings["team_id"].map(normalize_id)
    if normalized_team_ids.isna().any() or normalized_team_ids.eq("").any():
        raise ValueError("derived standings contains invalid team_id values")
    if normalized_team_ids.duplicated().any():
        raise ValueError(
            "derived standings contains duplicate normalized team_id values"
        )

    numeric_columns = [
        "games_played",
        "wins",
        "losses",
        "points_for",
        "points_against",
        "point_differential",
    ]
    numeric = standings[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or (numeric[["games_played", "wins", "losses"]] < 0).any().any():
        raise ValueError("derived standings contains invalid record values")
    if not numeric["games_played"].eq(numeric["wins"] + numeric["losses"]).all():
        raise ValueError("derived standings violates games_played equals wins plus losses")
    if not numeric["point_differential"].eq(
        numeric["points_for"] - numeric["points_against"]
    ).all():
        raise ValueError(
            "derived standings violates point_differential equals points_for minus points_against"
        )


def _source_records(source_standings: pd.DataFrame) -> pd.DataFrame:
    _require_columns(source_standings, {"team_id", "stat_name", "value"}, "source standings")
    records = source_standings.copy()
    records["team_id"] = records["team_id"].map(normalize_id)
    records["stat_name"] = records["stat_name"].astype("string").str.strip().str.lower()
    records = records.loc[records["stat_name"].isin({"wins", "losses"})].copy()
    records["value"] = pd.to_numeric(records["value"], errors="coerce")
    if records["team_id"].isna().any() or records["value"].isna().any():
        raise ValueError("source standings has invalid team_id or record value")
    if records.duplicated(["team_id", "stat_name"]).any():
        raise ValueError("source standings has duplicate team record statistics")
    wide = records.pivot(index="team_id", columns="stat_name", values="value")
    if not {"wins", "losses"}.issubset(wide.columns):
        raise ValueError("source standings must include wins and losses for every team")
    if wide[["wins", "losses"]].isna().any().any():
        raise ValueError("source standings must include wins and losses for every team")
    wide["games_played"] = wide["wins"] + wide["losses"]
    return wide.reset_index()[["team_id", "games_played", "wins", "losses"]]


def compare_external_standings(
    derived_standings: pd.DataFrame,
    external_standings: pd.DataFrame | None,
) -> ExternalStandingsQA:
    """Validate derived invariants and compare optional ESPN long-form records."""

    _validate_derived_invariants(derived_standings)
    if external_standings is None:
        return ExternalStandingsQA(
            status="unavailable",
            compared_team_count=0,
            mismatch_team_ids=(),
            message="External standings are unavailable; derived standings remain authoritative.",
        )

    try:
        source_records = _source_records(external_standings)
    except Exception as error:
        return ExternalStandingsQA(
            status="unparseable",
            compared_team_count=0,
            mismatch_team_ids=(),
            message=f"External standings are unparseable: {error}",
        )

    derived_records = derived_standings[["team_id", "games_played", "wins", "losses"]].copy()
    derived_records["team_id"] = derived_records["team_id"].map(normalize_id)
    comparison = derived_records.merge(
        source_records,
        on="team_id",
        how="outer",
        suffixes=("_derived", "_source"),
        indicator=True,
    )
    mismatches = comparison.loc[
        comparison["_merge"].ne("both")
        | comparison["games_played_derived"].ne(comparison["games_played_source"])
        | comparison["wins_derived"].ne(comparison["wins_source"])
        | comparison["losses_derived"].ne(comparison["losses_source"])
    ]
    compared_team_count = int(comparison["_merge"].eq("both").sum())
    if not mismatches.empty:
        mismatch_team_ids = tuple(sorted(mismatches["team_id"].astype(str)))
        team_ids = ", ".join(
            f"team_id={team_id}" for team_id in mismatch_team_ids
        )
        return ExternalStandingsQA(
            status="mismatch",
            compared_team_count=compared_team_count,
            mismatch_team_ids=mismatch_team_ids,
            message=f"External standings mismatch: {team_ids}",
        )
    return ExternalStandingsQA(
        status="matched",
        compared_team_count=compared_team_count,
        mismatch_team_ids=(),
        message="External standings match all derived team records.",
    )
