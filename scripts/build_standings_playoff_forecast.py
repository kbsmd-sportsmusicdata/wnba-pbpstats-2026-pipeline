#!/usr/bin/env python3
"""Build the season-parameterized WNBA standings and playoff forecast."""

from __future__ import annotations

import argparse
import datetime as dt
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from standings_playoff_forecast.broadcast_insights import build_broadcast_insights
from standings_playoff_forecast.config import (
    CONFIG_ROOT,
    REPOSITORY_ROOT,
    load_model_config,
    load_season_config,
)
from standings_playoff_forecast.contracts import ForecastModelConfig, SeasonConfig
from standings_playoff_forecast.data_sources import (
    ForecastSources,
    load_forecast_sources,
)
from standings_playoff_forecast.historical_context import (
    HISTORICAL_CONTEXT_COLUMNS,
    build_historical_context,
    discover_history,
)
from standings_playoff_forecast.leverage import calculate_game_leverage
from standings_playoff_forecast.matchup_model import score_matchups
from standings_playoff_forecast.outputs import ForecastOutputBundle, write_output_bundle
from standings_playoff_forecast.remaining_schedule import build_remaining_schedule
from standings_playoff_forecast.simulation import simulate_season
from standings_playoff_forecast.standings import (
    build_current_standings,
    build_head_to_head,
    reconcile_standings,
)
from standings_playoff_forecast.team_game_layer import (
    build_team_game_layer,
    qualify_regular_season_schedule,
)
from standings_playoff_forecast.team_strength import build_team_strength
from standings_playoff_forecast.tiebreaks import rank_teams


@dataclass(frozen=True)
class OrchestrationResult:
    """Inspectable result of one successful machine-readable forecast build."""

    season: int
    cutoff: pd.Timestamp
    random_seed: int
    output_path: Path
    reconciliation_status: str
    stage_artifacts: Mapping[str, Any]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _iso_date(value: str) -> str:
    try:
        dt.date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must use YYYY-MM-DD") from error
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build WNBA standings and playoff forecast outputs."
    )
    parser.add_argument("--season", type=_positive_int, required=True)
    parser.add_argument("--cutoff", type=_iso_date, default=None)
    parser.add_argument("--simulations", type=_positive_int, default=None)
    parser.add_argument(
        "--conditional-simulations", type=_nonnegative_int, default=0
    )
    parser.add_argument("--random-seed", type=_nonnegative_int, default=None)
    parser.add_argument("--history-start", type=_positive_int, default=None)
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--render", choices=("none", "all"), default="none")
    parser.add_argument("--sportsdataverse-data-root", default=None)
    parser.add_argument("--pbpstats-data-root", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args(argv)


def apply_runtime_overrides(
    cfg: SeasonConfig,
    *,
    sportsdataverse_data_root: str | None = None,
    pbpstats_data_root: str | None = None,
    output_root: str | None = None,
) -> SeasonConfig:
    """Return a validated immutable config copy with path-only overrides."""

    replacements = {
        name: value
        for name, value in (
            ("sportsdataverse_data_root", sportsdataverse_data_root),
            ("pbpstats_data_root", pbpstats_data_root),
            ("output_root", output_root),
        )
        if value is not None
    }
    return replace(cfg, **replacements)


def _resolve_cutoff(
    requested_cutoff: str | None,
    schedule: pd.DataFrame,
    cfg: SeasonConfig,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    qualified = qualify_regular_season_schedule(schedule, cfg)
    completed = qualified.loc[
        qualified["status_type_completed"].fillna(False).astype(bool)
    ].copy()
    if completed.empty:
        raise ValueError("qualified schedule has no completed game for cutoff resolution")
    completed_dates = pd.to_datetime(completed["game_date"], errors="coerce")
    if completed_dates.isna().any():
        raise ValueError("qualified completed schedule contains invalid game_date values")
    latest_completed = pd.Timestamp(completed_dates.max()).normalize()
    if requested_cutoff is None:
        return latest_completed, latest_completed
    cutoff = pd.Timestamp(requested_cutoff).normalize()
    if pd.isna(cutoff):
        raise ValueError("cutoff must be a valid date")
    return cutoff, latest_completed


def _rank_current_standings(
    standings: pd.DataFrame,
    team_games: pd.DataFrame,
    cfg: SeasonConfig,
) -> pd.DataFrame:
    ranking = rank_teams(
        standings[["team_id", "wins", "losses", "point_differential"]],
        team_games,
        cfg,
    )
    current_rank = {
        team_id: rank
        for rank, team_id in enumerate(ranking.ordered_team_ids, start=1)
    }
    ranked = standings.copy()
    ranked["current_rank"] = ranked["team_id"].map(current_rank)
    if ranked["current_rank"].isna().any() or len(current_rank) != cfg.team_count:
        raise ValueError("official current ranking did not assign every configured team")
    ranked["current_rank"] = ranked["current_rank"].astype(int)
    return ranked


def _normalized_root(cfg: SeasonConfig) -> Path:
    root = Path(cfg.normalized_team_game_root)
    return root if root.is_absolute() else REPOSITORY_ROOT / root


def _source_files(sources: ForecastSources) -> dict[str, Path]:
    paths = {
        "schedule": sources.schedule_path,
        "team_box": sources.team_box_path,
        "standings": sources.standings_path,
        "team_history": sources.team_history_path,
    }
    if sources.pbp_team_features_path is not None:
        paths["pbp_team_features"] = sources.pbp_team_features_path
    return paths


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame(columns=HISTORICAL_CONTEXT_COLUMNS)


def _run_pipeline(
    options: argparse.Namespace,
    *,
    cfg: SeasonConfig,
    model_cfg: ForecastModelConfig,
    historical_context_override: pd.DataFrame | None,
) -> OrchestrationResult:
    sources = load_forecast_sources(cfg)
    cutoff, latest_completed = _resolve_cutoff(options.cutoff, sources.schedule, cfg)
    random_seed = (
        int(f"{cfg.season}{cutoff.strftime('%m%d')}")
        if options.random_seed is None
        else options.random_seed
    )
    simulation_count = (
        cfg.simulation_count if options.simulations is None else options.simulations
    )

    # Both builders receive the full raw schedule plus the same cutoff; future
    # rows remain available for rest and back-to-back context.
    team_games = build_team_game_layer(sources, cfg, cutoff=cutoff)
    current_standings = build_current_standings(team_games, cfg)
    head_to_head = build_head_to_head(team_games)
    current_standings = _rank_current_standings(
        current_standings, team_games, cfg
    )
    reconciliation_status = reconcile_standings(
        current_standings,
        sources.standings,
        cutoff=cutoff,
        latest_completed_game_date=latest_completed,
    )
    team_strength = build_team_strength(
        team_games,
        sources.pbp_team_features,
        cfg,
        model_cfg,
        cutoff,
    )
    if sources.pbp_team_features is None:
        warnings.warn(
            "Optional PBPStats enrichment is unavailable; core forecast continues.",
            RuntimeWarning,
            stacklevel=2,
        )
    elif not team_strength["pbpstats_snapshot_safe_for_cutoff"].all():
        warnings.warn(
            "PBPStats snapshot is not cutoff-safe; enrichment fields remain unavailable.",
            RuntimeWarning,
            stacklevel=2,
        )

    remaining_schedule = build_remaining_schedule(sources.schedule, cutoff, cfg)
    matchup_probabilities = score_matchups(
        remaining_schedule, team_strength, team_games, model_cfg
    )
    simulation_result = simulate_season(
        team_games,
        matchup_probabilities,
        cfg,
        simulation_count=simulation_count,
        seed=random_seed,
    )

    if historical_context_override is not None:
        historical_context = historical_context_override
    else:
        progress = float(
            current_standings["games_played"].mean()
            / cfg.regular_season_games_per_team
        )
        historical_context = build_historical_context(
            _normalized_root(cfg),
            cfg.season,
            target_progress_pct=progress,
            history_start=options.history_start,
        )
        if historical_context.empty or not historical_context[
            "availability_status"
        ].eq("available").any():
            warnings.warn(
                "Historical context is unavailable; current forecast continues.",
                RuntimeWarning,
                stacklevel=2,
            )

    playoff_leverage_games = calculate_game_leverage(
        matchup_probabilities, simulation_result, current_standings, cfg
    )
    broadcast_insights = build_broadcast_insights(
        simulation_result.forecast_summary,
        current_standings,
        team_strength,
        matchup_probabilities,
        playoff_leverage_games,
        cfg,
        historical_context=historical_context,
    )
    bundle = ForecastOutputBundle(
        current_standings=current_standings,
        head_to_head=head_to_head,
        team_strength=team_strength,
        remaining_schedule=remaining_schedule,
        matchup_probabilities=matchup_probabilities,
        simulation_result=simulation_result,
        playoff_leverage_games=playoff_leverage_games,
        historical_context=historical_context,
        broadcast_insights=broadcast_insights,
    )
    output_path = write_output_bundle(
        bundle,
        cfg=cfg,
        model_cfg=model_cfg,
        cutoff=cutoff,
        season_config_path=CONFIG_ROOT / "seasons" / f"{cfg.season}.json",
        model_config_path=CONFIG_ROOT / "forecast_model.json",
        source_files=_source_files(sources),
        conditional_simulation_count=0,
        repository_root=REPOSITORY_ROOT,
    )
    artifacts = {
        "team_games": team_games,
        "current_standings": current_standings,
        "head_to_head": head_to_head,
        "team_strength": team_strength,
        "remaining_schedule": remaining_schedule,
        "matchup_probabilities": matchup_probabilities,
        "simulation_result": simulation_result,
        "historical_context": historical_context,
        "playoff_leverage_games": playoff_leverage_games,
        "broadcast_insights": broadcast_insights,
    }
    return OrchestrationResult(
        season=cfg.season,
        cutoff=cutoff,
        random_seed=random_seed,
        output_path=output_path,
        reconciliation_status=reconciliation_status,
        stage_artifacts=artifacts,
    )


def run_forecast(options: argparse.Namespace) -> OrchestrationResult:
    """Run one forecast from parsed options and propagate mandatory failures."""

    if options.conditional_simulations:
        raise ValueError(
            "conditional simulations are not a separate V1 run; use "
            "--conditional-simulations 0"
        )
    if options.history_start is not None and options.history_start >= options.season:
        raise ValueError("history_start must be earlier than the forecast season")

    cfg = load_season_config(options.season)
    model_cfg = load_model_config()
    cfg = apply_runtime_overrides(
        cfg,
        sportsdataverse_data_root=options.sportsdataverse_data_root,
        pbpstats_data_root=options.pbpstats_data_root,
        output_root=options.output_root,
    )
    historical_context_override = None
    if options.skip_history:
        historical_context_override = _empty_history()
        warnings.warn(
            "Historical context was explicitly skipped.",
            RuntimeWarning,
            stacklevel=2,
        )
    result = _run_pipeline(
        options,
        cfg=cfg,
        model_cfg=model_cfg,
        historical_context_override=historical_context_override,
    )
    if options.render == "all":
        raise NotImplementedError(
            "presentation renderers are registered in Tasks 13-15; use --render none"
        )
    return result


def main(argv: Sequence[str] | None = None) -> None:
    result = run_forecast(parse_args(argv))
    print(f"cutoff resolved: {result.cutoff.date().isoformat()}")
    print(f"deterministic seed: {result.random_seed}")
    print(f"standings reconciliation: {result.reconciliation_status}")
    print(f"machine-readable outputs: {result.output_path}")


if __name__ == "__main__":
    main()
