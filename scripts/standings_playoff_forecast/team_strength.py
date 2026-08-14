"""Cutoff-safe team-strength inputs for the standings forecast."""

from collections.abc import Mapping

import pandas as pd

from .contracts import ForecastModelConfig, SeasonConfig
from .data_sources import TEAM_HISTORY_PATH
from .team_game_layer import normalize_id


_REQUIRED_GAME_COLUMNS = {
    "team_id",
    "game_id",
    "game_date",
    "win",
    "net_rating_est",
    "efg_pct",
    "opp_efg_pct",
    "tov_pct",
    "opp_tov_pct",
    "oreb_pct",
    "opp_oreb_pct",
    "ftr",
    "opp_ftr",
}
_IDENTITY_COLUMNS = ("team_id", "franchise_id", "team_abbreviation", "team_name")
_FACTOR_COLUMNS = ("efg_diff", "tov_diff", "oreb_diff", "ftr_diff")
PBPSTATS_CONTEXT_COLUMNS = (
    "games_played",
    "plus_minus",
    "off_poss",
    "def_poss",
    "total_poss",
    "efg_pct",
    "ts_pct",
    "pace",
    "shotquality_pbp_feature",
    "shot_making_over_shotquality_pbp",
)
_PBPSTATS_STATUS_COLUMNS = (
    "pbpstats_snapshot_available",
    "pbpstats_snapshot_as_of",
    "pbpstats_cutoff_safety_upper_bound",
    "pbpstats_provenance_kind",
    "pbpstats_snapshot_safe_for_cutoff",
)


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def _cutoff_games(team_games: pd.DataFrame, cutoff: object) -> pd.DataFrame:
    _require_columns(team_games, _REQUIRED_GAME_COLUMNS, "team_games")
    games = team_games.copy()
    games["game_date"] = pd.to_datetime(games["game_date"], errors="coerce")
    if games["game_date"].isna().any():
        raise ValueError("team_games has invalid game_date values")
    cutoff_date = pd.Timestamp(cutoff).normalize()
    games = games.loc[games["game_date"].le(cutoff_date)].copy()
    games = games.sort_values(["team_id", "game_date", "game_id"], kind="stable")
    games["efg_diff"] = games["efg_pct"] - games["opp_efg_pct"]
    games["tov_diff"] = games["opp_tov_pct"] - games["tov_pct"]
    games["oreb_diff"] = games["oreb_pct"] - games["opp_oreb_pct"]
    games["ftr_diff"] = games["ftr"] - games["opp_ftr"]
    return games


def _identity_metadata(games: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in _IDENTITY_COLUMNS if column in games.columns]
    return games[columns].drop_duplicates("team_id")


def _validated_team_universe(
    team_universe: pd.DataFrame, cfg: SeasonConfig
) -> pd.DataFrame:
    required = set(_IDENTITY_COLUMNS)
    _require_columns(team_universe, required, "team_universe")
    result = team_universe[list(_IDENTITY_COLUMNS)].copy()
    result["team_id"] = result["team_id"].map(normalize_id)
    for column in _IDENTITY_COLUMNS[1:]:
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
    return result.sort_values("team_id", kind="stable").reset_index(drop=True)


def _in_season_z_scores(
    result: pd.DataFrame, weights: Mapping[str, float]
) -> pd.DataFrame:
    """Return neutral z-scores for unavailable or zero-variance factors."""

    weight_map = dict(weights)
    missing = sorted(set(weight_map).difference(result.columns))
    if missing:
        raise ValueError(
            "explanatory strength references unavailable columns: "
            + ", ".join(missing)
        )
    z_scores = pd.DataFrame(index=result.index)
    for column in weight_map:
        values = pd.to_numeric(result[column], errors="coerce")
        standard_deviation = values.std(ddof=0)
        if pd.isna(standard_deviation) or standard_deviation == 0:
            z_scores[column] = 0.0
        else:
            z_scores[column] = ((values - values.mean()) / standard_deviation).fillna(
                0.0
            )
    return z_scores


def _normalized_provenance_date(value: object) -> tuple[str | None, pd.Timestamp | None]:
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(timestamp):
        return None, None
    date = pd.Timestamp(timestamp).date()
    return date.isoformat(), pd.Timestamp(date)


def _snapshot_provenance(
    pbp_team_features: pd.DataFrame | None,
) -> tuple[
    str | None,
    pd.Timestamp | None,
    str | None,
    pd.Timestamp | None,
    str | None,
]:
    """Separate exact coverage dates from conservative cutoff-safety bounds."""

    if pbp_team_features is None:
        return None, None, None, None, None
    metadata = pbp_team_features.attrs.get("pbpstats_snapshot_metadata")
    if isinstance(metadata, Mapping):
        snapshot_value = metadata.get("snapshot_as_of", metadata.get("as_of"))
        snapshot_text, snapshot_date = _normalized_provenance_date(snapshot_value)
        if snapshot_date is not None:
            return snapshot_text, snapshot_date, None, None, "snapshot_as_of"
        upper_value = metadata.get("cutoff_safety_upper_bound")
        upper_text, upper_date = _normalized_provenance_date(upper_value)
        if upper_date is not None:
            return (
                None,
                None,
                upper_text,
                upper_date,
                "last_saved_at_utc_upper_bound",
            )
    for key in ("pbpstats_snapshot_as_of", "snapshot_as_of"):
        value = pbp_team_features.attrs.get(key)
        if value is None:
            continue
        snapshot_text, snapshot_date = _normalized_provenance_date(value)
        if snapshot_date is not None:
            return snapshot_text, snapshot_date, None, None, "snapshot_as_of"
    upper_text, upper_date = _normalized_provenance_date(
        pbp_team_features.attrs.get("pbpstats_cutoff_safety_upper_bound")
    )
    if upper_date is not None:
        return (
            None,
            None,
            upper_text,
            upper_date,
            "last_saved_at_utc_upper_bound",
        )
    return None, None, None, None, None


def _attach_pbpstats_context(
    result: pd.DataFrame,
    pbp_team_features: pd.DataFrame | None,
    cfg: SeasonConfig,
    model_cfg: ForecastModelConfig,
    cutoff: object,
) -> pd.DataFrame:
    """Attach only a verified-safe current PBPStats snapshot to team rows."""

    (
        snapshot_text,
        snapshot_date,
        upper_bound_text,
        upper_bound_date,
        provenance_kind,
    ) = _snapshot_provenance(pbp_team_features)
    available = bool(
        pbp_team_features is not None
        and not pbp_team_features.empty
        and "team_id" in pbp_team_features.columns
    )
    cutoff_date = pd.Timestamp(cutoff).normalize()
    cutoff_evidence_date = snapshot_date or upper_bound_date
    safe_for_cutoff = bool(
        available
        and cutoff_evidence_date is not None
        and cutoff_evidence_date <= cutoff_date
    )
    result["pbpstats_snapshot_available"] = available
    result["pbpstats_snapshot_as_of"] = (
        snapshot_text if snapshot_text is not None else pd.NA
    )
    result["pbpstats_cutoff_safety_upper_bound"] = (
        upper_bound_text if upper_bound_text is not None else pd.NA
    )
    result["pbpstats_provenance_kind"] = (
        provenance_kind if provenance_kind is not None else pd.NA
    )
    result["pbpstats_snapshot_safe_for_cutoff"] = safe_for_cutoff
    for column in PBPSTATS_CONTEXT_COLUMNS:
        result[f"pbpstats_{column}"] = pd.NA

    if not (model_cfg.pbpstats_enrichment_enabled and safe_for_cutoff):
        return result

    features = pbp_team_features.copy()
    features["team_id"] = features["team_id"].map(normalize_id)
    features = features.dropna(subset=["team_id"])
    if features.duplicated("team_id").any():
        raise ValueError("pbp_team_features contains duplicate team_id values")
    team_history = pd.read_csv(TEAM_HISTORY_PATH)
    team_history = team_history.loc[
        pd.to_numeric(team_history["season"], errors="coerce").eq(cfg.season),
        ["pbpstats_team_id", "franchise_id"],
    ].copy()
    team_history["pbpstats_team_id"] = team_history["pbpstats_team_id"].map(
        normalize_id
    )
    pbpstats_to_franchise = team_history.set_index("pbpstats_team_id")[
        "franchise_id"
    ]
    features["strength_join_key"] = features["team_id"].map(pbpstats_to_franchise)
    features["strength_join_key"] = features["strength_join_key"].fillna(
        features["team_id"]
    )
    if features.duplicated("strength_join_key").any():
        raise ValueError("pbp_team_features contains duplicate strength join keys")
    features = features.set_index("strength_join_key")
    join_key = result["team_id"].copy()
    if "franchise_id" in result.columns:
        join_key = result["franchise_id"].where(
            result["franchise_id"].isin(features.index), join_key
        )
    for column in PBPSTATS_CONTEXT_COLUMNS:
        if column in features.columns:
            result[f"pbpstats_{column}"] = join_key.map(features[column])
    return result


def build_team_strength(
    team_games: pd.DataFrame,
    pbp_team_features: pd.DataFrame | None,
    cfg: SeasonConfig,
    model_cfg: ForecastModelConfig,
    cutoff: object,
    *,
    team_universe: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate cutoff-safe season and recent team strength.

    PBPStats enrichment is deliberately added only after the game-derived core;
    callers may pass ``None`` without making the forecast unavailable.
    """

    games = _cutoff_games(team_games, cutoff)
    universe = (
        None if team_universe is None else _validated_team_universe(team_universe, cfg)
    )
    identity_columns = (
        list(_IDENTITY_COLUMNS)
        if universe is not None
        else [column for column in _IDENTITY_COLUMNS if column in games]
    )
    output_columns = [
        *identity_columns,
        "season_games_played",
        "season_win_pct",
        "season_net_rating",
        "recent_games_played",
        "recent_net_rating",
        *_FACTOR_COLUMNS,
        "predictive_net_rating",
        *[
            f"z_{column}"
            for column in model_cfg.explanatory_strength
        ],
        "composite_strength",
        *_PBPSTATS_STATUS_COLUMNS,
        *[f"pbpstats_{column}" for column in PBPSTATS_CONTEXT_COLUMNS],
    ]
    if games.empty and universe is None:
        return pd.DataFrame(columns=output_columns)

    if games.empty:
        result = pd.DataFrame(
            columns=[
                *_IDENTITY_COLUMNS,
                "season_games_played",
                "season_win_pct",
                "season_net_rating",
                "recent_games_played",
                "recent_net_rating",
                *_FACTOR_COLUMNS,
                "predictive_net_rating",
                *[f"z_{column}" for column in model_cfg.explanatory_strength],
                "composite_strength",
            ]
        )
    else:
        season = (
            games.groupby("team_id", sort=True)
            .agg(
                season_games_played=("game_id", "size"),
                season_win_pct=("win", "mean"),
                season_net_rating=("net_rating_est", "mean"),
                **{column: (column, "mean") for column in _FACTOR_COLUMNS},
            )
            .reset_index()
        )
        recent = games.groupby("team_id", sort=False).tail(cfg.recent_window_games)
        recent = (
            recent.groupby("team_id", sort=True)
            .agg(
                recent_games_played=("game_id", "size"),
                recent_net_rating=("net_rating_est", "mean"),
            )
            .reset_index()
        )
        result = _identity_metadata(games).merge(
            season, on="team_id", how="inner", validate="one_to_one"
        ).merge(recent, on="team_id", how="inner", validate="one_to_one")
        result["predictive_net_rating"] = (
            model_cfg.season_net_rating_weight * result["season_net_rating"]
            + model_cfg.recent_net_rating_weight * result["recent_net_rating"]
        )
        z_scores = _in_season_z_scores(result, model_cfg.explanatory_strength)
        for column in z_scores:
            result[f"z_{column}"] = z_scores[column]
        composite = pd.Series(0.0, index=result.index, dtype="float64")
        for column, weight in model_cfg.explanatory_strength.items():
            composite = composite + weight * z_scores[column]
        result["composite_strength"] = composite

    if universe is not None:
        unexpected = sorted(set(result["team_id"]) - set(universe["team_id"]))
        if unexpected:
            raise ValueError(
                "team_games contains teams outside team_universe: "
                + ", ".join(unexpected)
            )
        observed_identity = result[list(_IDENTITY_COLUMNS)].copy()
        if not observed_identity.empty:
            identity_check = observed_identity.merge(
                universe,
                on="team_id",
                how="left",
                suffixes=("_game", "_universe"),
                validate="one_to_one",
            )
            conflicts = pd.Series(False, index=identity_check.index)
            for column in _IDENTITY_COLUMNS[1:]:
                conflicts |= identity_check[f"{column}_game"].astype("string").ne(
                    identity_check[f"{column}_universe"].astype("string")
                ).fillna(True)
            if conflicts.any():
                raise ValueError(
                    "team_games presentation metadata conflicts with team_universe: "
                    + ", ".join(sorted(identity_check.loc[conflicts, "team_id"]))
                )
        result = universe.merge(
            result.drop(columns=list(_IDENTITY_COLUMNS[1:]), errors="ignore"),
            on="team_id",
            how="left",
            validate="one_to_one",
        )
        neutral_columns = [
            "season_net_rating",
            "recent_net_rating",
            *_FACTOR_COLUMNS,
            "predictive_net_rating",
            *[f"z_{column}" for column in model_cfg.explanatory_strength],
            "composite_strength",
        ]
        result[["season_games_played", "recent_games_played"]] = result[
            ["season_games_played", "recent_games_played"]
        ].fillna(0).astype("int64")
        result[neutral_columns] = result[neutral_columns].fillna(0.0).astype(
            "float64"
        )
        result["season_win_pct"] = pd.to_numeric(
            result["season_win_pct"], errors="coerce"
        )
    result = _attach_pbpstats_context(result, pbp_team_features, cfg, model_cfg, cutoff)
    return result.reindex(columns=output_columns)
