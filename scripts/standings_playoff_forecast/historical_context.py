"""Descriptive, leakage-safe context from completed historical team-game seasons.

This module deliberately produces benchmarks only.  It does not train a model,
change simulation inputs, or make the current forecast depend on history.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import load_season_config
from .team_game_layer import normalize_id
from .tiebreaks import rank_teams


HISTORICAL_CONTEXT_COLUMNS = [
    "context_level",
    "metric",
    "season",
    "season_count",
    "seed_band",
    "qualifier_rank",
    "team_id",
    "target_progress_pct",
    "as_of_progress_pct",
    "as_of_net_rating",
    "final_rank",
    "value",
    "sample_size",
    "availability_status",
]

_REQUIRED_COLUMNS = {
    "season",
    "game_id",
    "team_id",
    "opponent_id",
    "season_game_number",
    "season_progress_pct",
    "win",
    "loss",
    "wins_to_date",
    "losses_to_date",
    "win_pct_to_date",
    "point_diff_to_date",
    "margin",
    "possessions_est",
    "net_rating_est",
}


def _empty_context() -> pd.DataFrame:
    return pd.DataFrame(columns=HISTORICAL_CONTEXT_COLUMNS)


def discover_history(
    normalized_root: str | Path,
    forecast_season: int,
    *,
    history_start: int | None = None,
) -> list[Path]:
    """Return prior numeric ``season=<year>`` partition directories by year.

    Current, future, malformed, and non-directory entries are intentionally
    ignored.  File existence is checked by the context builder so discovery can
    remain a simple, inspectable partition contract.
    """

    root = Path(normalized_root)
    if not root.exists():
        return []
    partitions: list[tuple[int, Path]] = []
    for candidate in root.iterdir():
        if not candidate.is_dir() or not candidate.name.startswith("season="):
            continue
        year_text = candidate.name.removeprefix("season=")
        if not year_text.isascii() or not year_text.isdecimal():
            continue
        season = int(year_text)
        if season < forecast_season and (
            history_start is None or season >= history_start
        ):
            partitions.append((season, candidate))
    return [path for _, path in sorted(partitions, key=lambda item: item[0])]


def _status_row(season: int, status: str) -> dict[str, Any]:
    row = {column: pd.NA for column in HISTORICAL_CONTEXT_COLUMNS}
    row.update(
        {
            "context_level": "availability",
            "metric": "historical_season_status",
            "season": season,
            "season_count": 0,
            "availability_status": status,
        }
    )
    return row


def _validate_history_frame(
    frame: pd.DataFrame, season: int, regular_season_games: int, team_count: int
) -> pd.DataFrame:
    missing = sorted(_REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        raise ValueError(
            f"historical season {season} missing required columns: {', '.join(missing)}"
        )
    result = frame.copy()
    if pd.to_numeric(result["season"], errors="coerce").ne(season).any():
        raise ValueError(f"historical partition season={season} contains another season")
    if result.duplicated(["season", "team_id", "game_id"]).any():
        raise ValueError(f"historical season {season} has duplicate season-team-game rows")
    for column in ("team_id", "opponent_id"):
        result[column] = result[column].map(normalize_id)
        if result[column].isna().any() or result[column].eq("").any():
            raise ValueError(f"historical season {season} has invalid {column}")
    result["season_progress_pct"] = pd.to_numeric(
        result["season_progress_pct"], errors="coerce"
    )
    progress = result["season_progress_pct"]
    if (~np.isfinite(progress)).any() or progress.le(0).any() or progress.gt(1).any():
        raise ValueError(f"historical season {season} has non-finite season_progress_pct")
    for column in (
        "season_game_number",
        "win",
        "loss",
        "point_diff_to_date",
        "margin",
        "possessions_est",
        "net_rating_est",
    ):
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isna().any() or (~np.isfinite(values)).any():
            raise ValueError(f"historical season {season} has invalid {column}")
        result[column] = values
    if (
        result["season_game_number"].mod(1).ne(0).any()
        or result["season_game_number"].le(0).any()
    ):
        raise ValueError(f"historical season {season} has invalid season_game_number")
    result["season_game_number"] = result["season_game_number"].astype(int)
    if (
        ~result["win"].isin((0, 1)).all()
        or ~result["loss"].isin((0, 1)).all()
        or result["win"].add(result["loss"]).ne(1).any()
    ):
        raise ValueError(f"historical season {season} violates win/loss invariant")
    expected_game_numbers = set(range(1, regular_season_games + 1))
    teams = result.groupby("team_id", sort=False)
    game_numbers = teams["season_game_number"].agg(set)
    row_counts = teams.size()
    if (
        len(game_numbers) != team_count
        or not game_numbers.map(lambda values: values == expected_game_numbers).all()
        or not row_counts.eq(regular_season_games).all()
    ):
        raise ValueError(f"historical season {season} has incomplete season outcomes")
    for _, game_rows in result.groupby("game_id", sort=False):
        if len(game_rows) != 2:
            raise ValueError(f"historical season {season} violates reciprocal game accounting")
        first, second = game_rows.itertuples(index=False)
        if (
            first.team_id == second.team_id
            or first.opponent_id != second.team_id
            or second.opponent_id != first.team_id
            or first.win + second.win != 1
            or first.loss + second.loss != 1
            or first.win != second.loss
            or first.loss != second.win
            or first.margin == 0
            or second.margin == 0
            or first.margin != -second.margin
        ):
            raise ValueError(
                f"historical season {season} violates reciprocal game accounting"
            )
    return result


def _final_standings(frame: pd.DataFrame, cfg: object) -> tuple[pd.DataFrame, int]:
    """Derive official-config final ranks from completed directional games."""

    final = (
        frame.sort_values(["team_id", "season_game_number", "game_id"], kind="stable")
        .groupby("team_id", as_index=False, sort=False)
        .agg(
            final_wins=("win", "sum"),
            final_losses=("loss", "sum"),
            final_point_diff=("point_diff_to_date", "last"),
            final_margin=("margin", "sum"),
            final_possessions=("possessions_est", "sum"),
        )
    )
    if final["final_possessions"].le(0).any():
        raise ValueError("historical season has non-positive final possessions")
    final["final_net_rating"] = 100 * final["final_margin"] / final["final_possessions"]
    final["final_win_pct"] = final["final_wins"] / (
        final["final_wins"] + final["final_losses"]
    )
    final_state = final.rename(
        columns={
            "final_wins": "wins",
            "final_losses": "losses",
            "final_point_diff": "point_differential",
        }
    )[["team_id", "wins", "losses", "point_differential"]]
    ranking = rank_teams(final_state, frame, cfg)
    rank_by_team = {
        team_id: rank for rank, team_id in enumerate(ranking.ordered_team_ids, start=1)
    }
    final["final_rank"] = final["team_id"].map(rank_by_team)
    if final["final_rank"].isna().any():
        raise ValueError("historical final ranking omitted a team")
    return final.sort_values("final_rank", kind="stable").reset_index(drop=True), ranking.fallback_count


def _seed_band(final_rank: int, playoff_qualifiers: int) -> str:
    if final_rank == 1:
        return "top_seed"
    if final_rank <= playoff_qualifiers:
        return "playoff_field"
    return "outside_playoff"


def _season_rows(
    frame: pd.DataFrame,
    season: int,
    cfg: object,
    target_progress_pct: float,
) -> list[dict[str, Any]]:
    final, fallback_count = _final_standings(frame, cfg)
    playoff_qualifiers = cfg.playoff_qualifiers
    qualifier = final.iloc[playoff_qualifiers - 1]
    first_out = final.iloc[playoff_qualifiers]
    rows: list[dict[str, Any]] = []

    def add(metric: str, value: float, **extra: Any) -> None:
        rows.append(
            {
                "context_level": "season",
                "metric": metric,
                "season": season,
                "season_count": 1,
                "seed_band": pd.NA,
                "qualifier_rank": playoff_qualifiers,
                "team_id": pd.NA,
                "target_progress_pct": target_progress_pct,
                "as_of_progress_pct": pd.NA,
                "as_of_net_rating": pd.NA,
                "final_rank": pd.NA,
                "value": float(value),
                "sample_size": 1,
                "availability_status": "available",
                **extra,
            }
        )

    add("final_qualifier_wins", qualifier.final_wins)
    add("final_qualifier_win_pct", qualifier.final_win_pct)
    add("final_first_out_wins", first_out.final_wins)
    add("final_first_out_win_pct", first_out.final_win_pct)
    add("final_cutline_gap_wins", qualifier.final_wins - first_out.final_wins)
    add("final_cutline_gap_win_pct", qualifier.final_win_pct - first_out.final_win_pct)
    add("final_tiebreak_fallback_count", fallback_count)
    for team in final.itertuples(index=False):
        rows.append(
            {
                "context_level": "season",
                "metric": "final_seed_band_net_rating",
                "season": season,
                "season_count": 1,
                "seed_band": _seed_band(int(team.final_rank), playoff_qualifiers),
                "qualifier_rank": playoff_qualifiers,
                "team_id": team.team_id,
                "target_progress_pct": target_progress_pct,
                "as_of_progress_pct": pd.NA,
                "as_of_net_rating": pd.NA,
                "final_rank": float(team.final_rank),
                "value": float(team.final_net_rating),
                "sample_size": 1,
                "availability_status": "available",
            }
        )

    # Freeze each team's latest row at or before target progress, then join only
    # those frozen features to fully completed final outcomes.
    eligible_as_of = frame.loc[frame["season_progress_pct"].le(target_progress_pct)].copy()
    as_of = eligible_as_of.sort_values(
        ["team_id", "season_progress_pct", "season_game_number", "game_id"],
        kind="stable",
    ).groupby("team_id", as_index=False, sort=False).tail(1)
    as_of_ratings = eligible_as_of.groupby("team_id", sort=False).agg(
        as_of_margin=("margin", "sum"),
        as_of_possessions=("possessions_est", "sum"),
    )
    if as_of_ratings["as_of_possessions"].le(0).any():
        raise ValueError(f"historical season {season} has non-positive as-of possessions")
    as_of_ratings["as_of_net_rating"] = (
        100 * as_of_ratings["as_of_margin"] / as_of_ratings["as_of_possessions"]
    )
    outcomes = final.set_index("team_id")
    for as_of_row in as_of.itertuples(index=False):
        outcome = outcomes.loc[as_of_row.team_id]
        rows.append(
            {
                "context_level": "team_as_of",
                "metric": "same_progress_team_outcome",
                "season": season,
                "season_count": 1,
                "seed_band": _seed_band(int(outcome.final_rank), playoff_qualifiers),
                "qualifier_rank": playoff_qualifiers,
                "team_id": as_of_row.team_id,
                "target_progress_pct": target_progress_pct,
                "as_of_progress_pct": float(as_of_row.season_progress_pct),
                "as_of_net_rating": float(
                    as_of_ratings.loc[as_of_row.team_id, "as_of_net_rating"]
                ),
                "final_rank": float(outcome.final_rank),
                "value": float(outcome.final_rank <= playoff_qualifiers),
                "sample_size": 1,
                "availability_status": "available",
            }
        )
    return rows


def _aggregate(rows: pd.DataFrame) -> list[dict[str, Any]]:
    season_rows = rows.loc[rows["context_level"].eq("season")]
    output: list[dict[str, Any]] = []
    for metric in (
        "final_qualifier_wins",
        "final_qualifier_win_pct",
        "final_first_out_wins",
        "final_first_out_win_pct",
        "final_cutline_gap_wins",
        "final_cutline_gap_win_pct",
        "final_tiebreak_fallback_count",
    ):
        values = season_rows.loc[season_rows["metric"].eq(metric), "value"]
        if values.empty:
            continue
        output.append(
            {
                "context_level": "aggregate",
                "metric": metric,
                "season": pd.NA,
                "season_count": int(values.size),
                "seed_band": pd.NA,
                "qualifier_rank": pd.NA,
                "team_id": pd.NA,
                "target_progress_pct": season_rows["target_progress_pct"].iloc[0],
                "as_of_progress_pct": pd.NA,
                "as_of_net_rating": pd.NA,
                "final_rank": pd.NA,
                "value": float(values.mean()),
                "sample_size": int(values.size),
                "availability_status": "available",
            }
        )
    as_of_rows = rows.loc[rows["context_level"].eq("team_as_of")]
    if not as_of_rows.empty:
        for metric, values in (
            ("same_progress_playoff_rate", as_of_rows["value"]),
            ("same_progress_average_final_rank", as_of_rows["final_rank"]),
        ):
            output.append(
                {
                    "context_level": "aggregate",
                    "metric": metric,
                    "season": pd.NA,
                    "season_count": int(as_of_rows["season"].nunique()),
                    "seed_band": pd.NA,
                    "qualifier_rank": pd.NA,
                    "team_id": pd.NA,
                    "target_progress_pct": as_of_rows["target_progress_pct"].iloc[0],
                    "as_of_progress_pct": pd.NA,
                    "as_of_net_rating": pd.NA,
                    "final_rank": pd.NA,
                    "value": float(values.mean()),
                    "sample_size": int(values.size),
                    "availability_status": "available",
                }
            )
    return output


def build_historical_context(
    normalized_root: str | Path,
    forecast_season: int,
    *,
    target_progress_pct: float = 1.0,
    season_config_loader: Callable[[int], Any] = load_season_config,
    history_start: int | None = None,
) -> pd.DataFrame:
    """Build optional historical benchmarks using only verified prior seasons.

    Nearest/as-of matching chooses each team's maximum observed progress that is
    less than or equal to ``target_progress_pct``.  It never looks ahead.  A
    prior partition without a verified season config or complete outcome is
    represented by an availability row and excluded from aggregates.
    """

    if not np.isfinite(target_progress_pct) or not 0 < target_progress_pct <= 1:
        raise ValueError("target_progress_pct must be finite and in (0, 1]")
    rows: list[dict[str, Any]] = []
    read_team_game_paths: list[Path] = []
    if history_start is not None and history_start >= forecast_season:
        raise ValueError("history_start must be earlier than forecast_season")
    for partition in discover_history(
        normalized_root, forecast_season, history_start=history_start
    ):
        season = int(partition.name.removeprefix("season="))
        try:
            cfg = season_config_loader(season)
        except (FileNotFoundError, ValueError, KeyError):
            rows.append(_status_row(season, "season_config_unavailable"))
            continue
        if getattr(cfg, "season", None) != season:
            rows.append(_status_row(season, "season_config_unavailable"))
            continue
        parquet_path = partition / "team_game.parquet"
        if not parquet_path.is_file():
            rows.append(_status_row(season, "team_game_unavailable"))
            continue
        frame = pd.read_parquet(parquet_path)
        read_team_game_paths.append(parquet_path)
        try:
            validated = _validate_history_frame(
                frame,
                season,
                cfg.regular_season_games_per_team,
                cfg.team_count,
            )
        except ValueError as error:
            if "incomplete season outcomes" in str(error):
                rows.append(_status_row(season, "incomplete_season_outcomes"))
                continue
            raise
        if cfg.playoff_qualifiers <= 0 or cfg.playoff_qualifiers >= cfg.team_count:
            rows.append(_status_row(season, "invalid_playoff_qualifier_rules"))
            continue
        rows.extend(
            _season_rows(
                validated, season, cfg, float(target_progress_pct)
            )
        )
    if not rows:
        empty = _empty_context()
        empty.attrs["historical_team_game_paths"] = read_team_game_paths
        return empty
    result = pd.DataFrame(rows, columns=HISTORICAL_CONTEXT_COLUMNS)
    aggregate = _aggregate(result)
    if aggregate:
        result = pd.concat(
            [result, pd.DataFrame(aggregate, columns=HISTORICAL_CONTEXT_COLUMNS)],
            ignore_index=True,
        )
    result = result[HISTORICAL_CONTEXT_COLUMNS]
    result.attrs["historical_team_game_paths"] = read_team_game_paths
    return result
