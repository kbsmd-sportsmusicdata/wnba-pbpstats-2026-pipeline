from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


SEASON = 2026


@dataclass
class LoadedSources:
    player_features: pd.DataFrame
    team_features: pd.DataFrame
    player_window_panel: pd.DataFrame
    rapm: pd.DataFrame
    possessions: pd.DataFrame
    player_impact: pd.DataFrame
    source_manifest: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def hash_config(config: Dict[str, Any]) -> str:
    business_config = {k: v for k, v in config.items() if k != "_config_path"}
    return hashlib.sha256(stable_json_dumps(business_config).encode("utf-8")).hexdigest()


def load_config(config_path: Path) -> Dict[str, Any]:
    with Path(config_path).open(encoding="utf-8") as f:
        config = json.load(f)
    config["_config_path"] = str(config_path)
    return config


def path_from_config(value: str | Path, root: Optional[Path] = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (root or repo_root()) / path


def apply_runtime_overrides(
    config: Dict[str, Any],
    *,
    pbpstats_data_root: Optional[str] = None,
    sportsdataverse_data_root: Optional[str] = None,
    output_root: Optional[str] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    if pbpstats_data_root:
        updated["pbpstats_data_root"] = pbpstats_data_root
    if sportsdataverse_data_root:
        updated["sportsdataverse_data_root"] = sportsdataverse_data_root
    if output_root:
        updated["output_root"] = output_root
    return updated


def resolve_output_root(config: Dict[str, Any]) -> Path:
    return path_from_config(config.get("output_root", "analysis/hidden_value"))


def ensure_output_dirs(output_root: Path) -> Dict[str, Path]:
    paths = {"processed": output_root / "data" / "processed"}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _file_record(path: Optional[Path], df: pd.DataFrame, *, requested: Optional[str] = None) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "path": str(path) if path else None,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "status": "resolved" if path is not None else "unresolved",
    }
    if path is None and requested:
        record["requested_filename"] = requested
    if path and path.exists():
        stat = path.stat()
        record["modified_at_utc"] = (
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        )
        record["size_bytes"] = stat.st_size
    if "coverage_through" in df.columns and not df.empty:
        values = df["coverage_through"].dropna().unique()
        if len(values):
            record["coverage_through"] = str(values[0])
    return record


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    source_files = config.get("source_files", {})
    season = str(config.get("season", SEASON))
    manifest: Dict[str, Dict[str, Any]] = {}

    pbp_root = path_from_config(config.get("pbpstats_data_root", "data/pbpstats_wnba_2026"))
    sports_root = path_from_config(config.get("sportsdataverse_data_root", "data/raw/sportsdataverse/wnba_2026"))
    panel_root = path_from_config(config.get("window_panel_root", "analysis/snapshot_window_panel"))
    impact_root = path_from_config(config.get("possession_impact_root", "analysis/possession_impact"))

    targets = {
        "player_features": pbp_root / "features_latest" / season / "player_totals_features_latest.csv",
        "team_features": pbp_root / "features_latest" / season / "team_totals_features_latest.csv",
        "player_window_panel": panel_root / source_files.get("player_window_panel", "data/processed/player_window_panel_2026.csv"),
        "rapm": impact_root / source_files.get("rapm", "data/processed/rapm_player_2026.csv"),
        "possessions": sports_root / source_files.get("possessions", "wnba_possessions_2026.parquet"),
        "player_impact": sports_root / source_files.get("player_impact", "wnba_player_impact_2026.parquet"),
    }

    frames: Dict[str, pd.DataFrame] = {}
    for key, path in targets.items():
        frame = _read(path)
        frames[key] = frame
        manifest[key] = _file_record(path if path.exists() else None, frame, requested=path.name)

    return LoadedSources(source_manifest=manifest, **frames)


def write_github_step_summary(markdown: str) -> None:
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
