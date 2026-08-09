"""Repository-relative source discovery for the standings forecast."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .contracts import SeasonConfig


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEAM_HISTORY_PATH = (
    REPOSITORY_ROOT
    / "analysis"
    / "standings_playoff_forecast"
    / "config"
    / "team_history.csv"
)


@dataclass(frozen=True)
class ForecastSources:
    schedule: pd.DataFrame
    team_box: pd.DataFrame
    standings: pd.DataFrame
    team_history: pd.DataFrame
    pbp_team_features: pd.DataFrame | None
    schedule_path: Path
    team_box_path: Path
    standings_path: Path
    team_history_path: Path
    pbp_team_features_path: Path | None


def _configured_path(root: str, filename: str) -> Path:
    return REPOSITORY_ROOT / root / filename


def load_forecast_sources(
    cfg: SeasonConfig,
    *,
    schedule_path: Path | str | None = None,
    team_box_path: Path | str | None = None,
    standings_path: Path | str | None = None,
    team_history_path: Path | str | None = None,
    pbp_team_features_path: Path | str | None = None,
) -> ForecastSources:
    """Load source tables, with mandatory SDV paths failing closed."""

    mandatory_paths = {
        "schedule": Path(schedule_path)
        if schedule_path is not None
        else _configured_path(cfg.sportsdataverse_data_root, cfg.source_files["schedule"]),
        "team_box": Path(team_box_path)
        if team_box_path is not None
        else _configured_path(cfg.sportsdataverse_data_root, cfg.source_files["team_box"]),
        "standings": Path(standings_path)
        if standings_path is not None
        else _configured_path(cfg.sportsdataverse_data_root, cfg.source_files["standings"]),
    }
    for source_name, path in mandatory_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing mandatory {source_name} source: {path}")

    optional_path = (
        Path(pbp_team_features_path)
        if pbp_team_features_path is not None
        else _configured_path(
            cfg.pbpstats_data_root, cfg.source_files["pbp_team_features"]
        )
    )
    history_path = (
        Path(team_history_path) if team_history_path is not None else TEAM_HISTORY_PATH
    )
    if not history_path.is_file():
        raise FileNotFoundError(f"missing team-history source: {history_path}")
    return ForecastSources(
        schedule=pd.read_parquet(mandatory_paths["schedule"]),
        team_box=pd.read_parquet(mandatory_paths["team_box"]),
        standings=pd.read_parquet(mandatory_paths["standings"]),
        team_history=pd.read_csv(history_path),
        pbp_team_features=pd.read_csv(optional_path) if optional_path.is_file() else None,
        schedule_path=mandatory_paths["schedule"],
        team_box_path=mandatory_paths["team_box"],
        standings_path=mandatory_paths["standings"],
        team_history_path=history_path,
        pbp_team_features_path=optional_path if optional_path.is_file() else None,
    )
