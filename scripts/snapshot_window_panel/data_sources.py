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
    team_master: pd.DataFrame
    player_master: pd.DataFrame
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
    output_root: Optional[str] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    if pbpstats_data_root:
        updated["pbpstats_data_root"] = pbpstats_data_root
    if output_root:
        updated["output_root"] = output_root
    return updated


def resolve_output_root(config: Dict[str, Any]) -> Path:
    return path_from_config(config.get("output_root", "analysis/snapshot_window_panel"))


def ensure_output_dirs(output_root: Path) -> Dict[str, Path]:
    paths = {"processed": output_root / "data" / "processed"}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _file_record(path: Optional[Path], df: pd.DataFrame, timestamp_column: str) -> Dict[str, Any]:
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
    if timestamp_column in df.columns and not df.empty:
        stamps = pd.to_datetime(df[timestamp_column], errors="coerce", utc=True).dropna()
        if not stamps.empty:
            record["snapshots"] = int(stamps.nunique())
            record["first_snapshot_utc"] = stamps.min().isoformat()
            record["latest_snapshot_utc"] = stamps.max().isoformat()
    return record


def _resolve_master_file(config: Dict[str, Any], relative_path: str) -> Optional[Path]:
    root = path_from_config(config.get("pbpstats_data_root", "data/pbpstats_wnba_2026"))
    candidate = root / relative_path
    return candidate if candidate.exists() else None


def _read_csv_optional(path: Optional[Path]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    source_files = config.get("source_files", {})
    timestamp_column = config.get("panel", {}).get("timestamp_column", "_featured_at_utc")

    frames: Dict[str, pd.DataFrame] = {}
    manifest: Dict[str, Dict[str, Any]] = {}
    for key, default in (
        ("team_master", "features_master/2026/team_totals_features_master.csv"),
        ("player_master", "features_master/2026/player_totals_features_master.csv"),
    ):
        relative = source_files.get(key, default)
        path = _resolve_master_file(config, relative)
        frame = _read_csv_optional(path)
        frames[key] = frame
        manifest[key] = _file_record(path, frame, timestamp_column)
        if path is None:
            manifest[key]["status"] = "missing"
            manifest[key]["requested_path"] = str(
                path_from_config(config.get("pbpstats_data_root", "data/pbpstats_wnba_2026")) / relative
            )

    return LoadedSources(
        team_master=frames["team_master"],
        player_master=frames["player_master"],
        source_manifest=manifest,
    )


def write_github_step_summary(markdown: str) -> None:
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
