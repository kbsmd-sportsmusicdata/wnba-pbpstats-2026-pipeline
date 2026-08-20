"""Inputs for the Functional Depth Score.

Depth is scored as a playoff variable, not a roster adjective, so the inputs are the two layers
that describe *how a team's production is distributed and how it holds up when starters sit*:

* the shared per-game player layer (``data/processed/wnba_pbpstats_player_game``) -- current, and
  the source for production distribution, rotation trust and role redundancy;
* the possession-impact bench net ratings (``analysis/possession_impact``) -- possession-level, the
  source for replacement resilience and the performance floor. This feed lags the game layer, so
  those two components carry an availability flag rather than being silently dropped.

Both are joined on team abbreviation, which the two feeds share.
"""

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
    player_game: pd.DataFrame
    bench_net_rating: pd.DataFrame
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
    game_layer_root: Optional[str] = None,
    possession_impact_root: Optional[str] = None,
    output_root: Optional[str] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    if game_layer_root:
        updated["game_layer_root"] = game_layer_root
    if possession_impact_root:
        updated["possession_impact_root"] = possession_impact_root
    if output_root:
        updated["output_root"] = output_root
    return updated


def resolve_output_root(config: Dict[str, Any]) -> Path:
    return path_from_config(config.get("output_root", "analysis/functional_depth"))


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
        "status": "resolved" if path is not None else "missing",
    }
    if path and path.exists():
        stat = path.stat()
        record["modified_at_utc"] = (
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        )
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
    season = str(config.get("season", SEASON))
    source_files = config.get("source_files", {})

    game_layer_root = path_from_config(config.get("game_layer_root", "data/processed"))
    impact_root = path_from_config(config.get("possession_impact_root", "analysis/possession_impact"))

    targets = {
        "player_game": game_layer_root
        / source_files.get("player_game", f"wnba_pbpstats_player_game/season={season}/player_game.parquet"),
        "bench_net_rating": impact_root
        / source_files.get("bench_net_rating", "data/processed/bench_net_rating_2026.csv"),
    }

    frames: Dict[str, pd.DataFrame] = {}
    manifest: Dict[str, Dict[str, Any]] = {}
    for key, path in targets.items():
        frame = _read(path)
        frames[key] = frame
        manifest[key] = _file_record(path if path.exists() else None, frame)

    return LoadedSources(source_manifest=manifest, **frames)


def write_github_step_summary(markdown: str) -> None:
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
