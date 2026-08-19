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
    possessions: pd.DataFrame
    wnba_pbp: pd.DataFrame
    player_impact: pd.DataFrame
    game_logs: pd.DataFrame
    player_features: pd.DataFrame
    team_features: pd.DataFrame
    game_dimension: pd.DataFrame = field(default_factory=pd.DataFrame)
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
    sportsdataverse_data_root: Optional[str] = None,
    pbpstats_data_root: Optional[str] = None,
    output_root: Optional[str] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    if sportsdataverse_data_root:
        updated["sportsdataverse_data_root"] = sportsdataverse_data_root
    if pbpstats_data_root:
        updated["pbpstats_data_root"] = pbpstats_data_root
    if output_root:
        updated["output_root"] = output_root
    return updated


def resolve_output_root(config: Dict[str, Any]) -> Path:
    return path_from_config(config.get("output_root", "analysis/possession_impact"))


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
    if "game_id" in df.columns and not df.empty:
        record["games"] = int(df["game_id"].nunique())
    return record


def _read_parquet_optional(path: Optional[Path]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    source_files = config.get("source_files", {})
    root = path_from_config(config.get("sportsdataverse_data_root", "data/raw/sportsdataverse/wnba_2026"))

    frames: Dict[str, pd.DataFrame] = {}
    manifest: Dict[str, Dict[str, Any]] = {}
    for key, default in (
        ("possessions", "wnba_possessions_2026.parquet"),
        ("wnba_pbp", "wnba_pbp_2026.parquet"),
        ("player_impact", "wnba_player_impact_2026.parquet"),
        # Only used to date the possession coverage: the possession feed carries game ids
        # but no dates, and the game logs share the same id space.
        ("game_logs", "player_game_logs_2026.parquet"),
    ):
        filename = source_files.get(key, default)
        candidate = root / filename
        path = candidate if candidate.exists() else None
        frame = _read_parquet_optional(path)
        frames[key] = frame
        manifest[key] = _file_record(path, frame, requested=filename)
        if path is None:
            manifest[key]["requested_path"] = str(candidate)

    season = str(config.get("season", SEASON))
    pbp_root = path_from_config(config.get("pbpstats_data_root", "data/pbpstats_wnba_2026"))
    player_path = pbp_root / "features_latest" / season / "player_totals_features_latest.csv"
    team_path = pbp_root / "features_latest" / season / "team_totals_features_latest.csv"
    player_features = _read_csv_optional(player_path)
    team_features = _read_csv_optional(team_path)
    manifest["player_features"] = _file_record(player_path if player_path.exists() else None, player_features)
    manifest["team_features"] = _file_record(team_path if team_path.exists() else None, team_features)

    # The shared game layer supplies the fresh, CI-native game_id -> date dimension used to date
    # possession coverage, replacing the dependency on the lagging SportsDataverse game logs.
    game_layer_path = path_from_config(
        config.get("team_game_layer", f"data/processed/wnba_pbpstats_team_game/season={season}/team_game.parquet")
    )
    game_layer = _read_parquet_optional(game_layer_path if game_layer_path.exists() else None)
    if not game_layer.empty and {"game_id", "game_date"}.issubset(game_layer.columns):
        game_dimension = (
            game_layer[["game_id", "game_date"]].drop_duplicates("game_id").reset_index(drop=True)
        )
    else:
        game_dimension = pd.DataFrame()
    manifest["game_dimension"] = _file_record(
        game_layer_path if game_layer_path.exists() else None, game_dimension
    )

    return LoadedSources(
        possessions=frames["possessions"],
        wnba_pbp=frames["wnba_pbp"],
        player_impact=frames["player_impact"],
        game_logs=frames["game_logs"],
        player_features=player_features,
        team_features=team_features,
        game_dimension=game_dimension,
        source_manifest=manifest,
    )


def write_github_step_summary(markdown: str) -> None:
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
