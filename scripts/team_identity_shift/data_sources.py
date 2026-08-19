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
    team_window_panel: pd.DataFrame
    schedule: pd.DataFrame
    team_game: pd.DataFrame = field(default_factory=pd.DataFrame)
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
    window_panel_root: Optional[str] = None,
    sportsdataverse_data_root: Optional[str] = None,
    output_root: Optional[str] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    if window_panel_root:
        updated["window_panel_root"] = window_panel_root
    if sportsdataverse_data_root:
        updated["sportsdataverse_data_root"] = sportsdataverse_data_root
    if output_root:
        updated["output_root"] = output_root
    return updated


def resolve_output_root(config: Dict[str, Any]) -> Path:
    return path_from_config(config.get("output_root", "analysis/team_identity_shift"))


def ensure_output_dirs(output_root: Path) -> Dict[str, Path]:
    paths = {"processed": output_root / "data" / "processed"}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _file_record(path: Optional[Path], df: pd.DataFrame) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "path": str(path) if path else None,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
    }
    if path and path.exists():
        stat = path.stat()
        record["modified_at_utc"] = (
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        )
        record["size_bytes"] = stat.st_size
    if "window_end_utc" in df.columns and not df.empty:
        stamps = pd.to_datetime(df["window_end_utc"], errors="coerce", utc=True).dropna()
        if not stamps.empty:
            record["latest_window_end_utc"] = stamps.max().isoformat()
    return record


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    source_files = config.get("source_files", {})
    manifest: Dict[str, Dict[str, Any]] = {}

    panel_path = path_from_config(config.get("window_panel_root", "analysis/snapshot_window_panel")) / source_files.get(
        "team_window_panel", "data/processed/team_window_panel_2026.csv"
    )
    panel = pd.read_csv(panel_path, low_memory=False) if panel_path.exists() else pd.DataFrame()
    manifest["team_window_panel"] = _file_record(panel_path if panel_path.exists() else None, panel)
    if not panel_path.exists():
        manifest["team_window_panel"]["status"] = "missing"
        manifest["team_window_panel"]["requested_path"] = str(panel_path)

    schedule_path = path_from_config(
        config.get("sportsdataverse_data_root", "data/raw/sportsdataverse/wnba_2026")
    ) / source_files.get("schedule", "schedule_2026.parquet")
    schedule = pd.read_parquet(schedule_path) if schedule_path.exists() else pd.DataFrame()
    manifest["schedule"] = _file_record(schedule_path if schedule_path.exists() else None, schedule)
    if not schedule_path.exists():
        manifest["schedule"]["status"] = "missing"
        manifest["schedule"]["requested_path"] = str(schedule_path)

    season = str(config.get("season", SEASON))
    game_layer_path = path_from_config(
        config.get("team_game_layer", f"data/processed/wnba_pbpstats_team_game/season={season}/team_game.parquet")
    )
    team_game = pd.read_parquet(game_layer_path) if game_layer_path.exists() else pd.DataFrame()
    manifest["team_game"] = _file_record(game_layer_path if game_layer_path.exists() else None, team_game)
    if not game_layer_path.exists():
        manifest["team_game"]["status"] = "missing"
        manifest["team_game"]["requested_path"] = str(game_layer_path)

    return LoadedSources(
        team_window_panel=panel, schedule=schedule, team_game=team_game, source_manifest=manifest
    )


def write_github_step_summary(markdown: str) -> None:
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
