"""Validated, atomic machine-readable standings forecast output bundle."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import tempfile
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .broadcast_insights import INSIGHT_COLUMNS
from .historical_context import HISTORICAL_CONTEXT_COLUMNS
from .leverage import LEVERAGE_COLUMNS
from .metadata import build_run_manifest
from .standings import ExternalStandingsQA, HEAD_TO_HEAD_COLUMNS, STANDINGS_COLUMNS
from .team_game_layer import LedgerValidationResult, normalize_id


PAYLOAD_KEYS = {
    "metadata",
    "standings",
    "forecast_summary",
    "rank_probability_matrix",
    "remaining_schedule",
    "leverage_games",
    "broadcast_insights",
    "historical_context",
}

CSV_FILENAMES = {
    "current_standings": "current_standings.csv",
    "head_to_head": "head_to_head.csv",
    "team_strength": "team_strength.csv",
    "remaining_schedule": "remaining_schedule.csv",
    "matchup_probabilities": "matchup_probabilities.csv",
    "forecast_summary": "forecast_summary.csv",
    "rank_probability_matrix": "rank_probability_matrix.csv",
    "playoff_leverage_games": "playoff_leverage_games.csv",
    "historical_context": "historical_context.csv",
    "broadcast_insights": "broadcast_insights.csv",
}

FORECAST_SUMMARY_COLUMNS = [
    "season",
    "cutoff_date",
    "team_id",
    "franchise_id",
    "team_abbreviation",
    "current_rank",
    "current_gp",
    "current_wins",
    "current_losses",
    "current_win_pct",
    "current_point_diff",
    "projected_wins_mean",
    "projected_losses_mean",
    "wins_p10",
    "wins_p50",
    "wins_p90",
    "expected_final_rank",
    "playoff_probability",
    "top4_probability",
    "home_court_probability",
]

AGGREGATE_ABSOLUTE_TOLERANCE = 1e-12


@dataclass(frozen=True)
class ForecastOutputBundle:
    current_standings: pd.DataFrame
    head_to_head: pd.DataFrame
    team_strength: pd.DataFrame
    remaining_schedule: pd.DataFrame
    matchup_probabilities: pd.DataFrame
    simulation_result: object
    playoff_leverage_games: pd.DataFrame
    historical_context: pd.DataFrame
    broadcast_insights: pd.DataFrame


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def _normalize_columns(
    frame: pd.DataFrame, columns: tuple[str, ...], name: str
) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = result[column].map(normalize_id)
    if result[list(columns)].isna().any().any() or result[list(columns)].eq("").any().any():
        raise ValueError(f"{name} contains missing or blank normalized identifiers")
    return result


def _reject_infinities(frame: pd.DataFrame, name: str) -> None:
    for value in frame.to_numpy(dtype=object).flat:
        if isinstance(value, (float, np.floating)) and math.isinf(float(value)):
            raise ValueError(f"{name} contains an infinite value")


def _validate_season(frame: pd.DataFrame, season: int, name: str) -> None:
    if "season" not in frame.columns or frame.empty:
        return
    values = pd.to_numeric(frame["season"], errors="coerce")
    if values.isna().any() or not values.eq(season).all():
        raise ValueError(f"{name} season values must match configured season {season}")


def _validate_probability_outputs(
    summary: pd.DataFrame, matrix: pd.DataFrame, team_ids: tuple[str, ...], cfg: object
) -> None:
    required_summary = {
        "team_id",
        "season",
        "projected_wins_mean",
        "projected_losses_mean",
        "wins_p10",
        "wins_p50",
        "wins_p90",
        "expected_final_rank",
        "playoff_probability",
        "top4_probability",
        "home_court_probability",
        "out_probability",
        *{f"rank_{rank}_probability" for rank in range(1, cfg.team_count + 1)},
    }
    _require_columns(summary, required_summary, "forecast_summary")
    _require_columns(
        matrix,
        {"season", "team_id", "final_rank", "probability", "playoff_rank"},
        "rank_probability_matrix",
    )
    if summary["team_id"].duplicated().any() or tuple(summary["team_id"]) != team_ids:
        raise ValueError("forecast_summary team order must match SimulationResult")
    expected_cells = {(team_id, rank) for team_id in team_ids for rank in range(1, cfg.team_count + 1)}
    final_rank = pd.to_numeric(matrix["final_rank"], errors="coerce")
    if (
        final_rank.isna().any()
        or not np.equal(final_rank, np.floor(final_rank)).all()
    ):
        raise ValueError("rank_probability_matrix final_rank must contain integers")
    actual_cells = list(zip(matrix["team_id"], final_rank.astype(int)))
    if len(actual_cells) != len(expected_cells) or set(actual_cells) != expected_cells:
        raise ValueError("rank_probability_matrix must contain every team-rank cell exactly once")
    probability = pd.to_numeric(matrix["probability"], errors="coerce")
    if not np.isfinite(probability.to_numpy(dtype=float)).all() or not probability.between(0, 1).all():
        raise ValueError("rank probabilities must be finite and within [0, 1]")
    raw_playoff_rank = matrix["playoff_rank"]
    playoff_rank = pd.to_numeric(raw_playoff_rank, errors="coerce")
    qualifying = final_rank.le(cfg.playoff_qualifiers)
    invalid_playoff_rank = (
        raw_playoff_rank.notna() & playoff_rank.isna()
    ) | (
        qualifying & playoff_rank.ne(final_rank)
    ) | (~qualifying & playoff_rank.notna())
    if invalid_playoff_rank.any():
        raise ValueError(
            "rank_probability_matrix playoff_rank must equal qualifying final_rank "
            "and be null otherwise"
        )
    pivot = matrix.assign(
        final_rank=final_rank.astype(int), probability=probability
    ).pivot(
        index="team_id", columns="final_rank", values="probability"
    ).reindex(team_ids)
    exact = summary.set_index("team_id").reindex(team_ids)[
        [f"rank_{rank}_probability" for rank in range(1, cfg.team_count + 1)]
    ].apply(pd.to_numeric, errors="coerce")
    if not np.array_equal(pivot.to_numpy(), exact.to_numpy(), equal_nan=True):
        raise ValueError("forecast_summary exact rank probabilities must match the rank matrix")

    summary_by_team = summary.set_index("team_id").reindex(team_ids)
    top4_limit = min(4, cfg.playoff_qualifiers)
    expected_aggregates = {
        "playoff_probability": pivot.loc[
            :, range(1, cfg.playoff_qualifiers + 1)
        ].sum(axis=1),
        "top4_probability": pivot.loc[:, range(1, top4_limit + 1)].sum(axis=1),
        "home_court_probability": pivot.loc[
            :, range(1, top4_limit + 1)
        ].sum(axis=1),
        "out_probability": pivot.loc[
            :, range(cfg.playoff_qualifiers + 1, cfg.team_count + 1)
        ].sum(axis=1),
        "expected_final_rank": pivot.mul(
            np.arange(1, cfg.team_count + 1), axis=1
        ).sum(axis=1),
    }
    for column, expected_values in expected_aggregates.items():
        supplied_values = pd.to_numeric(
            summary_by_team[column], errors="coerce"
        )
        if (
            not np.isfinite(supplied_values.to_numpy(dtype=float)).all()
            or not np.allclose(
                supplied_values.to_numpy(dtype=float),
                expected_values.to_numpy(dtype=float),
                rtol=0.0,
                atol=AGGREGATE_ABSOLUTE_TOLERANCE,
            )
        ):
            raise ValueError(
                f"forecast_summary {column} must match rank_probability_matrix"
            )


def _same_values(left: pd.Series, right: pd.Series) -> bool:
    left_missing = left.isna()
    right_missing = right.isna()
    if not left_missing.equals(right_missing):
        return False
    present = ~left_missing
    return bool(
        left.loc[present]
        .reset_index(drop=True)
        .eq(right.loc[present].reset_index(drop=True))
        .all()
    )


def _same_game_dates(left: pd.Series, right: pd.Series) -> bool:
    left_dates = pd.to_datetime(left, errors="coerce", utc=True)
    right_dates = pd.to_datetime(right, errors="coerce", utc=True)
    if left_dates.isna().any() or right_dates.isna().any():
        return False
    return bool(left_dates.eq(right_dates).all())


def _validated_count_series(
    frame: pd.DataFrame, column: str, evidence_name: str
) -> pd.Series:
    raw = frame[column]
    if raw.map(lambda value: isinstance(value, (bool, np.bool_))).any():
        raise ValueError(f"{evidence_name} {column} must contain integers")
    numeric = pd.to_numeric(raw, errors="coerce")
    if (
        numeric.isna().any()
        or not np.isfinite(numeric.to_numpy(dtype=float)).all()
        or numeric.lt(0).any()
        or not np.equal(numeric, np.floor(numeric)).all()
    ):
        raise ValueError(f"{evidence_name} {column} must contain integers")
    return numeric.astype(int)


def _validate_season_schedule_evidence(
    validation: pd.DataFrame,
    current_standings: pd.DataFrame,
    remaining_schedule: pd.DataFrame,
    cfg: object,
) -> None:
    required = {
        "team_id",
        "completed_gp",
        "remaining_games",
        "configured_games",
        "total_games",
        "status",
    }
    if not isinstance(validation, pd.DataFrame):
        raise TypeError("season_schedule_validation must be a pandas DataFrame")
    missing = sorted(required.difference(validation.columns))
    if missing:
        raise ValueError(
            "season_schedule_validation is missing required columns: "
            + ", ".join(missing)
        )
    evidence = validation.loc[:, list(required)].copy()
    evidence["team_id"] = evidence["team_id"].map(normalize_id)
    if (
        evidence["team_id"].isna().any()
        or evidence["team_id"].eq("").any()
        or evidence["team_id"].duplicated().any()
    ):
        raise ValueError("season schedule evidence contains invalid team IDs")
    current_team_ids = set(current_standings["team_id"])
    if set(evidence["team_id"]) != current_team_ids:
        raise ValueError(
            "season schedule evidence team universe must match current_standings"
        )
    evidence = evidence.set_index("team_id").reindex(sorted(current_team_ids))
    completed_gp = _validated_count_series(
        evidence, "completed_gp", "season schedule evidence"
    )
    remaining_games = _validated_count_series(
        evidence, "remaining_games", "season schedule evidence"
    )
    configured_games = _validated_count_series(
        evidence, "configured_games", "season schedule evidence"
    )
    total_games = _validated_count_series(
        evidence, "total_games", "season schedule evidence"
    )
    current = current_standings.set_index("team_id").reindex(evidence.index)
    current_games_played = _validated_count_series(
        current, "games_played", "current_standings"
    )
    if not completed_gp.equals(current_games_played):
        raise ValueError(
            "season schedule evidence completed_gp must match "
            "current_standings games_played"
        )
    participants = pd.concat(
        [remaining_schedule["home_id"], remaining_schedule["away_id"]],
        ignore_index=True,
    )
    expected_remaining = (
        participants.value_counts().reindex(evidence.index, fill_value=0).astype(int)
    )
    if not remaining_games.equals(expected_remaining):
        raise ValueError(
            "season schedule evidence remaining_games must match remaining_schedule"
        )
    configured_games_per_team = int(cfg.regular_season_games_per_team)
    if (
        configured_games.ne(configured_games_per_team).any()
        or total_games.ne(configured_games_per_team).any()
        or not total_games.equals(completed_gp + remaining_games)
    ):
        raise ValueError(
            "season schedule evidence configured and total games must match "
            "the configured season"
        )
    if not evidence["status"].map(
        lambda value: isinstance(value, str) and value == "validated"
    ).all():
        raise ValueError(
            "season schedule evidence status must be validated for every team"
        )


def _validate_and_normalize(
    bundle: ForecastOutputBundle, cfg: object
) -> dict[str, pd.DataFrame]:
    frames = {
        "current_standings": bundle.current_standings,
        "head_to_head": bundle.head_to_head,
        "team_strength": bundle.team_strength,
        "remaining_schedule": bundle.remaining_schedule,
        "matchup_probabilities": bundle.matchup_probabilities,
        "forecast_summary": bundle.simulation_result.forecast_summary,
        "rank_probability_matrix": bundle.simulation_result.rank_probability_matrix,
        "playoff_leverage_games": bundle.playoff_leverage_games,
        "historical_context": bundle.historical_context,
        "broadcast_insights": bundle.broadcast_insights,
    }
    for name, frame in frames.items():
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{name} must be a pandas DataFrame")
        _reject_infinities(frame, name)
        if name != "historical_context":
            _validate_season(frame, int(cfg.season), name)

    _require_columns(
        frames["current_standings"],
        set(STANDINGS_COLUMNS) | {"current_rank"},
        "current_standings",
    )
    _require_columns(
        frames["head_to_head"], set(HEAD_TO_HEAD_COLUMNS), "head_to_head"
    )
    _require_columns(
        frames["team_strength"],
        {
            "team_id",
            "season_games_played",
            "season_win_pct",
            "season_net_rating",
            "recent_games_played",
            "recent_net_rating",
            "efg_diff",
            "tov_diff",
            "oreb_diff",
            "ftr_diff",
            "predictive_net_rating",
            "composite_strength",
            "pbpstats_snapshot_available",
            "pbpstats_snapshot_as_of",
            "pbpstats_snapshot_safe_for_cutoff",
        },
        "team_strength",
    )
    schedule_required = {
        "game_id",
        "game_date",
        "home_id",
        "away_id",
        "home_rest_days",
        "away_rest_days",
        "home_b2b",
        "away_b2b",
    }
    _require_columns(frames["remaining_schedule"], schedule_required, "remaining_schedule")
    _require_columns(
        frames["matchup_probabilities"],
        schedule_required
        | {
            "expected_home_margin",
            "margin_sigma",
            "home_win_probability",
            "away_win_probability",
            "model_version",
        },
        "matchup_probabilities",
    )
    _require_columns(
        frames["playoff_leverage_games"],
        set(LEVERAGE_COLUMNS),
        "playoff_leverage_games",
    )
    _require_columns(
        frames["historical_context"],
        set(HISTORICAL_CONTEXT_COLUMNS),
        "historical_context",
    )
    _require_columns(
        frames["broadcast_insights"], set(INSIGHT_COLUMNS), "broadcast_insights"
    )

    id_columns = {
        "current_standings": ("team_id",),
        "head_to_head": ("team_id", "opponent_id"),
        "team_strength": ("team_id",),
        "remaining_schedule": ("game_id", "home_id", "away_id"),
        "matchup_probabilities": ("game_id", "home_id", "away_id"),
        "forecast_summary": ("team_id",),
        "rank_probability_matrix": ("team_id",),
        "playoff_leverage_games": ("game_id", "home_id", "away_id"),
    }
    normalized = dict(frames)
    for name, columns in id_columns.items():
        normalized[name] = _normalize_columns(frames[name], columns, name)

    current = normalized["current_standings"]
    if current["team_id"].duplicated().any() or len(current) != cfg.team_count:
        raise ValueError("current_standings must contain one row per configured team")
    ranks = pd.to_numeric(current["current_rank"], errors="coerce")
    if sorted(ranks.tolist()) != list(range(1, cfg.team_count + 1)):
        raise ValueError("current_standings current_rank must be a complete permutation")
    current["current_rank"] = ranks.astype(int)
    current = current.sort_values(["current_rank", "team_id"], kind="stable").reset_index(drop=True)
    normalized["current_standings"] = current
    team_ids = tuple(current.sort_values("team_id", kind="stable")["team_id"])
    simulation_team_ids = tuple(normalize_id(value) for value in bundle.simulation_result.team_ids)
    if set(simulation_team_ids) != set(team_ids) or len(set(simulation_team_ids)) != cfg.team_count:
        raise ValueError("SimulationResult team IDs must match current_standings")
    summary_ids = tuple(normalized["forecast_summary"]["team_id"])
    _validate_probability_outputs(
        normalized["forecast_summary"],
        normalized["rank_probability_matrix"],
        simulation_team_ids,
        cfg,
    )
    if summary_ids != simulation_team_ids:
        raise ValueError("forecast_summary team order must match SimulationResult")

    for name in ("team_strength",):
        frame = normalized[name]
        if frame["team_id"].duplicated().any() or set(frame["team_id"]) != set(team_ids):
            raise ValueError(f"{name} must contain one row per configured team")
    head_to_head = normalized["head_to_head"]
    if not (set(head_to_head["team_id"]) | set(head_to_head["opponent_id"])).issubset(team_ids):
        raise ValueError("head_to_head contains a team outside current_standings")
    if head_to_head.duplicated(["team_id", "opponent_id"]).any():
        raise ValueError("head_to_head contains duplicate directional pairs")

    remaining = normalized["remaining_schedule"]
    matchups = normalized["matchup_probabilities"]
    for name, frame in (("remaining_schedule", remaining), ("matchup_probabilities", matchups)):
        if frame["game_id"].duplicated().any():
            raise ValueError(f"{name} contains duplicate game_id values")
        if frame["home_id"].eq(frame["away_id"]).any():
            raise ValueError(f"{name} contains identical participants")
        if not (set(frame["home_id"]) | set(frame["away_id"])).issubset(team_ids):
            raise ValueError(f"{name} contains a team outside current_standings")
    shared_schedule_columns = [
        "game_date",
        "home_id",
        "away_id",
        "home_rest_days",
        "away_rest_days",
        "home_b2b",
        "away_b2b",
    ]
    schedule_keys = remaining[
        ["game_id", *shared_schedule_columns]
    ].sort_values("game_id").reset_index(drop=True)
    matchup_keys = matchups[
        ["game_id", *shared_schedule_columns]
    ].sort_values("game_id").reset_index(drop=True)
    if not schedule_keys["game_id"].equals(matchup_keys["game_id"]):
        raise ValueError("remaining_schedule and matchup_probabilities game keys must match")
    for column in shared_schedule_columns:
        equal = (
            _same_game_dates(schedule_keys[column], matchup_keys[column])
            if column == "game_date"
            else _same_values(schedule_keys[column], matchup_keys[column])
        )
        if not equal:
            raise ValueError(
                f"{column} in matchup_probabilities must match remaining_schedule"
            )
    if tuple(matchups["game_id"]) != tuple(
        normalize_id(value) for value in bundle.simulation_result.remaining_game_ids
    ):
        raise ValueError("matchup_probabilities game order must match SimulationResult")
    probabilities = matchups[["home_win_probability", "away_win_probability"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        not np.isfinite(probabilities.to_numpy(dtype=float)).all()
        or not probabilities.ge(0).all().all()
        or not probabilities.le(1).all().all()
        or not np.allclose(probabilities.sum(axis=1), 1.0, rtol=0, atol=1e-12)
    ):
        raise ValueError("matchup probabilities must be finite, bounded, and complementary")

    leverage = normalized["playoff_leverage_games"]
    leverage_keys = leverage[
        ["game_id", "game_date", "home_id", "away_id"]
    ].sort_values("game_id").reset_index(drop=True)
    matchup_leverage_keys = matchup_keys[
        ["game_id", "game_date", "home_id", "away_id"]
    ]
    if not leverage_keys[["game_id", "home_id", "away_id"]].equals(
        matchup_leverage_keys[["game_id", "home_id", "away_id"]]
    ):
        raise ValueError("playoff_leverage_games game keys must match matchup_probabilities")
    if not _same_game_dates(
        leverage_keys["game_date"], matchup_leverage_keys["game_date"]
    ):
        raise ValueError(
            "game_date in playoff_leverage_games must match matchup_probabilities"
        )
    scores = pd.to_numeric(leverage["leverage_score"], errors="coerce")
    if not np.isfinite(scores.to_numpy(dtype=float)).all():
        raise ValueError("playoff_leverage_games leverage_score must be finite")
    normalized["playoff_leverage_games"]["leverage_score"] = scores

    return normalized


def _forecast_summary(
    frames: dict[str, pd.DataFrame], cfg: object, cutoff_date: str
) -> pd.DataFrame:
    summary = frames["forecast_summary"].copy()
    current = frames["current_standings"].copy()
    identity = pd.DataFrame({"team_id": current["team_id"]})
    for column in ("franchise_id", "team_abbreviation"):
        identity[column] = current[column] if column in current else pd.NA
    current_fields = {
        "current_rank": "current_rank",
        "games_played": "current_gp",
        "wins": "current_wins",
        "losses": "current_losses",
        "win_pct": "current_win_pct",
        "point_differential": "current_point_diff",
    }
    for source, destination in current_fields.items():
        identity[destination] = current[source]
    for status in (
        "clinched_playoffs",
        "eliminated_from_playoffs",
        "status_note",
    ):
        if status not in summary and status in current:
            identity[status] = current[status]
    summary = summary.merge(identity, on="team_id", how="left", validate="one_to_one")
    summary["cutoff_date"] = cutoff_date

    matchups = frames["matchup_probabilities"]
    directional = pd.concat(
        [
            matchups[["game_id", "home_id", "away_id"]].rename(
                columns={"home_id": "team_id", "away_id": "opponent_id"}
            ),
            matchups[["game_id", "away_id", "home_id"]].rename(
                columns={"away_id": "team_id", "home_id": "opponent_id"}
            ),
        ],
        ignore_index=True,
    )
    summary_index = summary.set_index("team_id")
    directional["opponent_playoff_probability"] = directional["opponent_id"].map(
        summary_index["playoff_probability"]
    )
    remaining_games = directional.groupby("team_id")["game_id"].size()
    remaining_sos = directional.groupby("team_id")["opponent_playoff_probability"].mean()
    summary["remaining_games"] = summary["team_id"].map(remaining_games).fillna(0).astype(int)
    summary["remaining_sos_rank"] = pd.Series(pd.NA, index=summary.index, dtype="Int64")
    if not remaining_sos.empty:
        ranked_sos = (
            remaining_sos.rename("remaining_sos")
            .reset_index()
            .sort_values(["remaining_sos", "team_id"], ascending=[False, True], kind="stable")
        )
        ranked_sos["remaining_sos_rank"] = range(1, len(ranked_sos) + 1)
        rank_map = ranked_sos.set_index("team_id")["remaining_sos_rank"]
        summary["remaining_sos_rank"] = summary["team_id"].map(rank_map).astype("Int64")

    leverage = frames["playoff_leverage_games"]
    leverage_directional = pd.concat(
        [
            leverage[["game_id", "home_id", "leverage_score"]].rename(columns={"home_id": "team_id"}),
            leverage[["game_id", "away_id", "leverage_score"]].rename(columns={"away_id": "team_id"}),
        ],
        ignore_index=True,
    )
    if leverage_directional.empty:
        most_leverage = pd.Series(dtype=object)
    else:
        most_leverage = (
            leverage_directional.sort_values(
                ["team_id", "leverage_score", "game_id"],
                ascending=[True, False, True],
                kind="stable",
            )
            .drop_duplicates("team_id")
            .set_index("team_id")["game_id"]
        )
    summary["most_leverage_game_id"] = summary["team_id"].map(most_leverage)

    for status in ("clinched_playoffs", "eliminated_from_playoffs"):
        if status not in summary:
            summary[status] = None
    if "status_note" not in summary:
        summary["status_note"] = "not_evaluated"
    status_flags = summary[["clinched_playoffs", "eliminated_from_playoffs"]]
    for column in status_flags:
        invalid = status_flags[column].dropna().map(
            lambda value: not isinstance(value, (bool, np.bool_))
        )
        if invalid.any():
            raise ValueError(f"{column} must contain only booleans or null")
    contradictory = summary["clinched_playoffs"].eq(True) & summary[
        "eliminated_from_playoffs"
    ].eq(True)
    if contradictory.any():
        raise ValueError("a team cannot be both clinched and eliminated")

    rank_columns = [
        f"rank_{rank}_probability" for rank in range(1, cfg.team_count + 1)
    ]
    tail = [
        "out_probability",
        "remaining_sos_rank",
        "remaining_games",
        "clinched_playoffs",
        "eliminated_from_playoffs",
        "status_note",
        "most_leverage_game_id",
    ]
    return summary.reindex(columns=[*FORECAST_SUMMARY_COLUMNS, *rank_columns, *tail]).sort_values(
        ["current_rank", "team_id"], kind="stable"
    ).reset_index(drop=True)


def _rank_matrix(
    frames: dict[str, pd.DataFrame], cutoff_date: str
) -> pd.DataFrame:
    matrix = frames["rank_probability_matrix"].copy()
    current = frames["current_standings"]
    abbreviations = (
        current.set_index("team_id")["team_abbreviation"]
        if "team_abbreviation" in current
        else pd.Series(pd.NA, index=current["team_id"])
    )
    matrix["cutoff_date"] = cutoff_date
    matrix["team_abbreviation"] = matrix["team_id"].map(abbreviations)
    return matrix.reindex(
        columns=[
            "season",
            "cutoff_date",
            "team_id",
            "team_abbreviation",
            "final_rank",
            "probability",
            "playoff_rank",
        ]
    ).sort_values(["team_id", "final_rank"], kind="stable").reset_index(drop=True)


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        normalized = float(value)
        if math.isnan(normalized):
            return None
        if math.isinf(normalized):
            raise ValueError("JSON payload contains an infinite numeric value")
        return normalized
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, (bool, np.bool_)) and missing:
        return None
    if isinstance(value, str):
        return value
    raise TypeError(f"value is not JSON serializable: {type(value).__name__}")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return _json_safe(frame.to_dict(orient="records"))


def validate_forecast_payload(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("forecast payload must be a mapping")
    actual = set(payload)
    if actual != PAYLOAD_KEYS:
        missing = sorted(PAYLOAD_KEYS.difference(actual))
        unexpected = sorted(actual.difference(PAYLOAD_KEYS))
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if unexpected:
            detail.append("unexpected: " + ", ".join(unexpected))
        raise ValueError("invalid forecast payload top-level keys (" + "; ".join(detail) + ")")
    if not isinstance(payload["metadata"], Mapping):
        raise ValueError("forecast payload metadata must be a mapping")
    for key in PAYLOAD_KEYS.difference({"metadata"}):
        if not isinstance(payload[key], list):
            raise ValueError(f"forecast payload {key} must be a list")


def _json_text(value: Any) -> str:
    normalized = _json_safe(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def _csv_text(frame: pd.DataFrame) -> str:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="invalid value encountered in cast", category=RuntimeWarning)
        return frame.to_csv(index=False, lineterminator="\n", float_format="%.17g")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _ordered_frames(
    frames: dict[str, pd.DataFrame], forecast_summary: pd.DataFrame, rank_matrix: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    standings_extra_columns = [
        column
        for column in frames["current_standings"].columns
        if column not in STANDINGS_COLUMNS
    ]
    current_standings = frames["current_standings"].reindex(
        columns=[*STANDINGS_COLUMNS, *standings_extra_columns]
    )
    return {
        "current_standings": current_standings.sort_values(["current_rank", "team_id"], kind="stable").reset_index(drop=True),
        "head_to_head": frames["head_to_head"].sort_values(["team_id", "opponent_id"], kind="stable").reset_index(drop=True),
        "team_strength": frames["team_strength"].sort_values("team_id", kind="stable").reset_index(drop=True),
        "remaining_schedule": frames["remaining_schedule"].sort_values(["game_date", "game_id"], kind="stable").reset_index(drop=True),
        "matchup_probabilities": frames["matchup_probabilities"].sort_values(["game_date", "game_id"], kind="stable").reset_index(drop=True),
        "forecast_summary": forecast_summary,
        "rank_probability_matrix": rank_matrix,
        "playoff_leverage_games": frames["playoff_leverage_games"].sort_values("game_id", kind="stable").reset_index(drop=True),
        "historical_context": frames["historical_context"]
        .sort_values(
            HISTORICAL_CONTEXT_COLUMNS,
            kind="stable",
            na_position="last",
        )
        .reset_index(drop=True),
        "broadcast_insights": frames["broadcast_insights"].sort_values("priority", kind="stable").reset_index(drop=True),
    }


def write_output_bundle(
    bundle: ForecastOutputBundle,
    *,
    cfg: object,
    model_cfg: object,
    cutoff: object,
    season_config_path: str | Path,
    model_config_path: str | Path,
    source_files: Mapping[str, str | Path | Mapping[str, Any]],
    ledger_validation: LedgerValidationResult,
    season_schedule_validation: pd.DataFrame,
    external_standings_qa: ExternalStandingsQA,
    conditional_simulation_count: int = 0,
    repository_root: str | Path,
) -> Path:
    """Validate and atomically replace the canonical forecast output files."""

    frames = _validate_and_normalize(bundle, cfg)
    _validate_season_schedule_evidence(
        season_schedule_validation,
        frames["current_standings"],
        frames["remaining_schedule"],
        cfg,
    )
    matchup_versions = set(
        frames["matchup_probabilities"]["model_version"].dropna().astype(str)
    )
    if not frames["matchup_probabilities"].empty and matchup_versions != {
        str(model_cfg.model_version)
    }:
        raise ValueError("matchup model_version must match model config")
    cutoff_timestamp = pd.Timestamp(cutoff)
    if pd.isna(cutoff_timestamp):
        raise ValueError("cutoff must be a valid timestamp")
    cutoff_date = cutoff_timestamp.date().isoformat()
    forecast_summary = _forecast_summary(frames, cfg, cutoff_date)
    rank_matrix = _rank_matrix(frames, cutoff_date)
    output_frames = _ordered_frames(frames, forecast_summary, rank_matrix)
    manifest = build_run_manifest(
        cfg=cfg,
        model_cfg=model_cfg,
        simulation_result=bundle.simulation_result,
        cutoff=cutoff,
        season_config_path=season_config_path,
        model_config_path=model_config_path,
        source_files=source_files,
        ledger_validation=ledger_validation,
        season_schedule_validation=season_schedule_validation,
        external_standings_qa=external_standings_qa,
        team_strength=frames["team_strength"],
        historical_context=frames["historical_context"],
        conditional_simulation_count=conditional_simulation_count,
        repository_root=repository_root,
    )
    payload = {
        "metadata": manifest,
        "standings": _records(output_frames["current_standings"]),
        "forecast_summary": _records(forecast_summary),
        "rank_probability_matrix": _records(rank_matrix),
        "remaining_schedule": _records(output_frames["matchup_probabilities"]),
        "leverage_games": _records(output_frames["playoff_leverage_games"]),
        "broadcast_insights": _records(output_frames["broadcast_insights"]),
        "historical_context": _records(output_frames["historical_context"]),
    }
    validate_forecast_payload(payload)
    payload_text = _json_text(payload)
    manifest_text = _json_text(manifest)
    csv_text = {name: _csv_text(frame) for name, frame in output_frames.items()}

    output_root = (
        Path(cfg.output_root)
        / "data"
        / "processed"
        / f"season={int(cfg.season)}"
        / "latest"
    )
    for name, filename in CSV_FILENAMES.items():
        _atomic_write_text(output_root / filename, csv_text[name])
    _atomic_write_text(output_root / "forecast_payload.json", payload_text)
    _atomic_write_text(output_root / "run_manifest.json", manifest_text)
    return output_root
