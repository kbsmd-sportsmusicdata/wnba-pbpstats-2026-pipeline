"""Repository-relative source discovery for the standings forecast."""

import json
from collections.abc import Mapping
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


def _load_pbp_team_features(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    sidecar_path = path.with_suffix(".json")
    if not sidecar_path.is_file():
        return frame
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frame
    metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
    if not isinstance(metadata, Mapping):
        return frame
    as_of = metadata.get("snapshot_as_of") or metadata.get("last_saved_at_utc")
    run_id = metadata.get("run_id")
    row_count = metadata.get("row_count")
    feature_run_ids = (
        set(frame["_feature_run_id"].dropna().astype(str))
        if "_feature_run_id" in frame.columns
        else set()
    )
    if (
        as_of is None
        or pd.isna(pd.to_datetime(as_of, errors="coerce"))
        or row_count != len(frame)
        or (feature_run_ids and feature_run_ids != {str(run_id)})
    ):
        return frame
    frame.attrs["pbpstats_snapshot_metadata"] = {
        "as_of": as_of,
        "run_id": run_id,
        "sidecar": str(sidecar_path),
    }
    return frame


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
        pbp_team_features=_load_pbp_team_features(optional_path)
        if optional_path.is_file()
        else None,
        schedule_path=mandatory_paths["schedule"],
        team_box_path=mandatory_paths["team_box"],
        standings_path=mandatory_paths["standings"],
        team_history_path=history_path,
        pbp_team_features_path=optional_path if optional_path.is_file() else None,
    )
