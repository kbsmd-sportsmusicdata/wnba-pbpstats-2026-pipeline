#!/usr/bin/env python3
"""Build the season-parameterized WNBA standings and playoff forecast."""

from __future__ import annotations

import argparse
import datetime as dt
import math
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
    ExternalStandingsLoadStatus,
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
from standings_playoff_forecast.remaining_schedule import (
    build_remaining_schedule,
    validate_season_schedule_counts,
)
from standings_playoff_forecast.render_dashboard import render_dashboard
from standings_playoff_forecast.render_excel import render_excel
from standings_playoff_forecast.render_markdown import render_markdown
from standings_playoff_forecast.render_stat_pack import render_stat_pack
from standings_playoff_forecast.simulation import simulate_season
from standings_playoff_forecast.standings import (
    ExternalStandingsQA,
    add_current_standings_context,
    build_current_standings,
    build_head_to_head,
    compare_external_standings,
)
from standings_playoff_forecast.team_game_layer import (
    LedgerValidationResult,
    build_team_game_layer,
    normalize_completion_flags,
    normalize_id,
    qualify_regular_season_schedule,
    resolve_team_game_output_path,
    validate_completed_game_ledger,
)
from standings_playoff_forecast.team_strength import (
    PBPSTATS_CONTEXT_COLUMNS,
    build_team_strength,
)
from standings_playoff_forecast.tiebreaks import rank_teams


@dataclass(frozen=True)
class OrchestrationResult:
    """Inspectable result of one successful machine-readable forecast build."""

    season: int
    cutoff: pd.Timestamp
    random_seed: int
    output_path: Path
    ledger_validation: LedgerValidationResult
    external_standings_qa: ExternalStandingsQA
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
    parser.add_argument("--team-game-output-path-file", default=None)
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
        )
        if value is not None
    }
    effective_output_root = Path(
        cfg.output_root if output_root is None else output_root
    ).expanduser()
    if not effective_output_root.is_absolute():
        effective_output_root = REPOSITORY_ROOT / effective_output_root
    replacements["output_root"] = str(effective_output_root)
    return replace(cfg, **replacements)


def _resolve_cutoff(
    requested_cutoff: str | None,
    schedule: pd.DataFrame,
    cfg: SeasonConfig,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    qualified = qualify_regular_season_schedule(schedule, cfg)
    completed = qualified.loc[
        normalize_completion_flags(qualified["status_type_completed"])
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


def _source_files(
    sources: ForecastSources, historical_context: pd.DataFrame
) -> dict[str, Path | Mapping[str, str | Path]]:
    paths = {
        "schedule": sources.schedule_path,
        "season_config_default": CONFIG_ROOT / "seasons" / "default.json",
        "team_box": sources.team_box_path,
        "team_history": sources.team_history_path,
    }
    if sources.external_standings_path is not None:
        paths["external_standings"] = sources.external_standings_path
    if sources.pbp_team_features_path is not None:
        paths["pbp_team_features"] = sources.pbp_team_features_path
    sidecar_fields = (
        getattr(sources, "pbp_team_features_sidecar_path", None),
        getattr(sources, "pbp_team_features_sidecar_evidence_kind", None),
        getattr(sources, "pbp_team_features_sidecar_evidence_date", None),
    )
    if any(value is not None for value in sidecar_fields):
        sidecar_path, evidence_kind, evidence_date = sidecar_fields
        if (
            not isinstance(sidecar_path, Path)
            or evidence_kind
            not in {"snapshot_as_of", "last_saved_at_utc_upper_bound"}
            or not isinstance(evidence_date, str)
        ):
            raise ValueError("validated PBPStats sidecar provenance is incomplete")
        paths["pbp_team_features_sidecar"] = {
            "path": sidecar_path,
            "evidence_kind": evidence_kind,
            "evidence_date": evidence_date,
        }
    historical_paths = historical_context.attrs.get(
        "historical_team_game_paths", []
    )
    for supplied_path in historical_paths:
        path = Path(supplied_path)
        partition_name = path.parent.name
        if not partition_name.startswith("season="):
            raise ValueError(
                f"historical provenance path has invalid partition: {path}"
            )
        season_text = partition_name.removeprefix("season=")
        if not season_text.isascii() or not season_text.isdecimal():
            raise ValueError(
                f"historical provenance path has invalid season: {path}"
            )
        season = int(season_text)
        paths[f"historical_team_game_{season}"] = path
        season_config_path = CONFIG_ROOT / "seasons" / f"{season}.json"
        if season_config_path.is_file():
            paths[f"historical_season_config_{season}"] = season_config_path
    return paths


def _external_standings_qa(
    current_standings: pd.DataFrame,
    sources: ForecastSources,
) -> ExternalStandingsQA:
    status = sources.external_standings_load_status
    if status == ExternalStandingsLoadStatus.UNPARSEABLE:
        if (
            sources.external_standings is not None
            or sources.external_standings_path is None
        ):
            raise ValueError(
                "unparseable external standings load evidence is inconsistent"
            )
        return ExternalStandingsQA(
            status="unparseable",
            compared_team_count=0,
            mismatch_team_ids=(),
            message=(
                "External standings file is present but could not be loaded: "
                f"{sources.external_standings_path}"
            ),
        )
    if status == ExternalStandingsLoadStatus.UNAVAILABLE:
        if (
            sources.external_standings is not None
            or sources.external_standings_path is not None
        ):
            raise ValueError(
                "unavailable external standings load evidence is inconsistent"
            )
    elif status == ExternalStandingsLoadStatus.LOADED:
        if (
            not isinstance(sources.external_standings, pd.DataFrame)
            or sources.external_standings_path is None
        ):
            raise ValueError("loaded external standings evidence is inconsistent")
    else:
        raise TypeError("external_standings_load_status is invalid")
    return compare_external_standings(
        current_standings,
        sources.external_standings,
    )


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame(columns=HISTORICAL_CONTEXT_COLUMNS)


def _warn_for_history(historical_context: pd.DataFrame) -> None:
    """Emit one precise warning for absent or partially unavailable history."""

    if historical_context.empty:
        warnings.warn(
            "Historical context is unavailable; current forecast continues.",
            RuntimeWarning,
            stacklevel=2,
        )
        return
    statuses = historical_context["availability_status"]
    available = statuses.eq("available").any()
    unavailable_seasons = historical_context["context_level"].eq(
        "availability"
    ) & statuses.ne("available")
    if not available:
        warnings.warn(
            "Historical context is unavailable; current forecast continues.",
            RuntimeWarning,
            stacklevel=2,
        )
    elif unavailable_seasons.any():
        warnings.warn(
            "Historical context is partially unavailable; available seasons "
            "are retained with explicit unavailable-season status rows.",
            RuntimeWarning,
            stacklevel=2,
        )


def _enforce_required_pbpstats(
    sources: ForecastSources,
    team_strength: pd.DataFrame,
    model_cfg: ForecastModelConfig,
    cfg: SeasonConfig,
) -> None:
    """Fail closed when the configured required enrichment lacks safe evidence."""

    if not model_cfg.pbpstats_enrichment_required:
        return
    if not model_cfg.pbpstats_enrichment_enabled:
        raise ValueError(
            "required PBPStats enrichment cannot be disabled by model config"
        )
    if sources.pbp_team_features is None or sources.pbp_team_features.empty:
        raise ValueError("required PBPStats enrichment source is unavailable")
    safe_column = "pbpstats_snapshot_safe_for_cutoff"
    if (
        safe_column not in team_strength.columns
        or team_strength.empty
        or not team_strength[safe_column].eq(True).all()
    ):
        raise ValueError(
            "required PBPStats enrichment is not cutoff-safe for every team"
        )
    normalized_team_ids = team_strength["team_id"].map(normalize_id)
    if (
        len(team_strength) != cfg.team_count
        or normalized_team_ids.isna().any()
        or normalized_team_ids.duplicated().any()
    ):
        raise ValueError(
            "required PBPStats enrichment lacks complete configured-team coverage"
        )
    required_context = [
        f"pbpstats_{column}" for column in PBPSTATS_CONTEXT_COLUMNS
    ]
    missing_columns = sorted(set(required_context).difference(team_strength.columns))
    if missing_columns:
        raise ValueError(
            "required PBPStats enrichment lacks complete non-null context: "
            + ", ".join(missing_columns)
        )
    numeric_context = team_strength[required_context].apply(
        pd.to_numeric, errors="coerce"
    )
    complete_context = numeric_context.map(math.isfinite).all(axis=1)
    if not complete_context.all():
        incomplete_team_ids = ", ".join(
            normalized_team_ids.loc[~complete_context].astype(str)
        )
        raise ValueError(
            "required PBPStats enrichment lacks complete non-null context for: "
            + incomplete_team_ids
        )


def _run_pipeline(
    options: argparse.Namespace,
    *,
    cfg: SeasonConfig,
    model_cfg: ForecastModelConfig,
    historical_context_override: pd.DataFrame | None,
) -> OrchestrationResult:
    sources = load_forecast_sources(cfg)
    cutoff, _ = _resolve_cutoff(options.cutoff, sources.schedule, cfg)
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
    team_game_output_path = resolve_team_game_output_path(
        cfg,
        qualify_regular_season_schedule(sources.schedule, cfg),
        cutoff=cutoff,
    )
    ledger_validation = validate_completed_game_ledger(
        sources.schedule,
        team_games,
        cfg,
        cutoff,
    )
    current_standings = build_current_standings(
        team_games,
        cfg,
        schedule=sources.schedule,
        team_history=sources.team_history,
    )
    head_to_head = build_head_to_head(team_games)
    current_standings = _rank_current_standings(
        current_standings, team_games, cfg
    )
    current_standings = add_current_standings_context(
        current_standings,
        team_games,
        cfg,
    )
    external_standings_qa = _external_standings_qa(current_standings, sources)
    team_strength = build_team_strength(
        team_games,
        sources.pbp_team_features,
        cfg,
        model_cfg,
        cutoff,
        team_universe=current_standings[
            ["team_id", "franchise_id", "team_abbreviation", "team_name"]
        ],
    )
    _enforce_required_pbpstats(sources, team_strength, model_cfg, cfg)
    if sources.pbp_team_features is None:
        warnings.warn(
            "Optional PBPStats contextual data is unavailable; core forecast continues.",
            RuntimeWarning,
            stacklevel=2,
        )
    elif not team_strength["pbpstats_snapshot_safe_for_cutoff"].all():
        warnings.warn(
            "PBPStats context is not cutoff-safe under its provenance bound; "
            "context fields remain unavailable.",
            RuntimeWarning,
            stacklevel=2,
        )

    remaining_schedule = build_remaining_schedule(sources.schedule, cutoff, cfg)
    season_schedule_counts = validate_season_schedule_counts(
        current_standings,
        remaining_schedule,
        cfg,
    )
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
            min_prior_seasons=cfg.historical_context_min_prior_seasons,
        )
        _warn_for_history(historical_context)

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
        source_files=_source_files(sources, historical_context),
        ledger_validation=ledger_validation,
        season_schedule_validation=season_schedule_counts,
        external_standings_qa=external_standings_qa,
        conditional_simulation_count=0,
        repository_root=REPOSITORY_ROOT,
    )
    artifacts = {
        "team_games": team_games,
        "team_game_output_path": team_game_output_path,
        "current_standings": current_standings,
        "head_to_head": head_to_head,
        "team_strength": team_strength,
        "remaining_schedule": remaining_schedule,
        "season_schedule_counts": season_schedule_counts,
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
        ledger_validation=ledger_validation,
        external_standings_qa=external_standings_qa,
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
    elif not cfg.historical_context_enabled:
        historical_context_override = _empty_history()
        warnings.warn(
            "Historical context is disabled by season config.",
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
        render_excel(
            result.output_path,
            result.stage_artifacts["team_games"],
            cfg=cfg,
        )
        render_markdown(result.output_path, cfg=cfg)
        render_stat_pack(result.output_path, cfg=cfg)
        render_dashboard(result.output_path, cfg=cfg)
    return result


def main(argv: Sequence[str] | None = None) -> None:
    options = parse_args(argv)
    result = run_forecast(options)
    team_game_output_path_file = getattr(
        options, "team_game_output_path_file", None
    )
    if team_game_output_path_file is not None:
        output_path = result.stage_artifacts.get("team_game_output_path")
        if not isinstance(output_path, Path) or not output_path.is_file():
            raise ValueError(
                "canonical team-game output path evidence must identify an existing file"
            )
        evidence_path = Path(team_game_output_path_file)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            f"{output_path.resolve()}\n",
            encoding="utf-8",
        )
    print(f"cutoff resolved: {result.cutoff.date().isoformat()}")
    print(f"deterministic seed: {result.random_seed}")
    print("canonical ledger validation: validated")
    print(f"external standings QA: {result.external_standings_qa.status}")
    print(f"machine-readable outputs: {result.output_path}")


if __name__ == "__main__":
    main()
