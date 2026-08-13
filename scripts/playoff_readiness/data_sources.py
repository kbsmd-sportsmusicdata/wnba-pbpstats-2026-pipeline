"""Loading, config and manifest plumbing, in the shape the rest of the pipeline uses."""

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
    schedule: pd.DataFrame
    possessions: pd.DataFrame
    game_logs: pd.DataFrame
    player_box: pd.DataFrame
    standings: pd.DataFrame
    bench: pd.DataFrame
    clutch: pd.DataFrame
    identity: pd.DataFrame
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
    with Path(config_path).open(encoding="utf-8") as handle:
        config = json.load(handle)
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
    sportsdataverse_data_root: Optional[str] = None,
    output_root: Optional[str] = None,
    simulations: Optional[int] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    if sportsdataverse_data_root:
        updated["sportsdataverse_data_root"] = sportsdataverse_data_root
    if output_root:
        updated["output_root"] = output_root
    if simulations:
        simulation = dict(updated.get("simulation", {}))
        simulation["simulations"] = int(simulations)
        updated["simulation"] = simulation
    return updated


def resolve_output_root(config: Dict[str, Any]) -> Path:
    return path_from_config(config.get("output_root", "analysis/playoff_readiness"))


def ensure_output_dirs(output_root: Path) -> Dict[str, Path]:
    paths = {"processed": output_root / "data" / "processed"}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _file_record(path: Optional[Path], frame: pd.DataFrame, *, requested: Optional[str] = None) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "path": str(path) if path else None,
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
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
    if "game_id" in frame.columns and not frame.empty:
        record["games"] = int(frame["game_id"].nunique())
    return record


def _read_optional(path: Optional[Path]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    """Read every input, recording what resolved and what did not.

    The schedule is the only hard requirement. The possession-derived and cross-project
    inputs are optional by design: they come from builds that lag or may not have run, and
    the board degrades to what it can compute rather than failing.
    """
    source_files = config.get("source_files", {})
    raw_root = path_from_config(config.get("sportsdataverse_data_root", "data/raw/sportsdataverse/wnba_2026"))
    impact_root = path_from_config(config.get("possession_impact_root", "analysis/possession_impact"))
    identity_root = path_from_config(config.get("team_identity_shift_root", "analysis/team_identity_shift"))

    specs = (
        ("schedule", raw_root, "schedule_2026.parquet"),
        ("possessions", raw_root, "wnba_possessions_2026.parquet"),
        ("game_logs", raw_root, "player_game_logs_2026.parquet"),
        ("player_box", raw_root, "player_box_2026.parquet"),
        ("standings", raw_root, "wnba_stats_standings_2026.parquet"),
        ("bench", impact_root, "data/processed/bench_net_rating_2026.csv"),
        ("clutch", impact_root, "data/processed/clutch_net_rating_2026.csv"),
        ("identity", identity_root, "data/processed/team_identity_shift_2026.csv"),
    )

    frames: Dict[str, pd.DataFrame] = {}
    manifest: Dict[str, Dict[str, Any]] = {}
    for key, root, default in specs:
        filename = source_files.get(key, default)
        candidate = root / filename
        path = candidate if candidate.exists() else None
        frame = _read_optional(path)
        frames[key] = frame
        manifest[key] = _file_record(path, frame, requested=filename)
        if path is None:
            manifest[key]["requested_path"] = str(candidate)

    return LoadedSources(source_manifest=manifest, **frames)


def write_github_step_summary(markdown: str) -> None:
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
