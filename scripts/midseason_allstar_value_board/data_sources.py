from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


SEASON = 2026
REQUIRED_PLAYER_FEATURE_COLUMNS = {
    "entity_id_feature",
    "entity_name_feature",
    "team_abbreviation",
    "games_played",
    "minutes",
}
REQUIRED_TEAM_FEATURE_COLUMNS = {"team_abbreviation", "games_played"}


@dataclass
class LoadedSources:
    player_features: pd.DataFrame
    team_features: pd.DataFrame
    player_box: pd.DataFrame
    player_game_logs: pd.DataFrame
    player_season_stats: pd.DataFrame
    team_box: pd.DataFrame
    standings: pd.DataFrame
    team_season_stats: pd.DataFrame
    source_manifest: Dict[str, Dict[str, Any]]


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
    return path_from_config(config.get("output_root", "analysis/midseason_allstar_value_board"))


def ensure_output_dirs(output_root: Path) -> Dict[str, Path]:
    paths = {
        "processed": output_root / "data" / "processed",
        "viz": output_root / "data" / "viz",
        "editorial": output_root / "editorial",
    }
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
        record["modified_at_utc"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        record["size_bytes"] = stat.st_size
    if "game_date" in df.columns and not df.empty:
        dates = pd.to_datetime(df["game_date"], errors="coerce").dropna()
        if not dates.empty:
            record["latest_game_date"] = dates.max().date().isoformat()
    return record


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required CSV source is missing: {path}")
    return pd.read_csv(path)


def _read_parquet_optional(path: Optional[Path]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _resolve_sportsdataverse_file(config: Dict[str, Any], filename: str) -> Optional[Path]:
    primary_root = path_from_config(config.get("sportsdataverse_data_root", "data/raw/sportsdataverse/wnba_2026"))
    primary = primary_root / filename
    if primary.exists():
        return primary

    fallback_root = path_from_config(config.get("sportsdataverse_fallback_root", "2026_scout_report"))
    fallback = fallback_root / filename
    if fallback.exists():
        return fallback
    return None


def _coerce_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _validate_columns(df: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{label} missing required columns: {missing}")


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    pbp_root = path_from_config(config.get("pbpstats_data_root", "data/pbpstats_wnba_2026"))
    season = str(config.get("season", SEASON))
    player_features_path = pbp_root / "features_latest" / season / "player_totals_features_latest.csv"
    team_features_path = pbp_root / "features_latest" / season / "team_totals_features_latest.csv"

    player_features = _read_csv(player_features_path)
    team_features = _read_csv(team_features_path)
    _validate_columns(player_features, REQUIRED_PLAYER_FEATURE_COLUMNS, "player features")
    _validate_columns(team_features, REQUIRED_TEAM_FEATURE_COLUMNS, "team features")

    numeric_cols = [
        "games_played",
        "minutes",
        "off_poss",
        "def_poss",
        "total_poss",
        "points",
        "rebounds",
        "assists",
        "turnovers",
        "steals",
        "blocks",
        "fouls_drawn",
        "usage",
        "efg_pct_feature",
        "ts_pct_feature",
        "shotquality_pbp_feature",
        "shot_making_over_shotquality_pbp",
        "on_off_rtg",
        "on_def_rtg",
        "fta_rate_feature",
        "rim_fga_share",
        "three_point_fga_share",
        "midrange_fga_share",
    ]
    player_features = _coerce_numeric_columns(player_features, numeric_cols)
    team_features = _coerce_numeric_columns(
        team_features,
        ["games_played", "points", "opponent_points", "off_poss", "def_poss", "efg_pct_feature", "ts_pct_feature"],
    )

    sports_files = {
        "player_box": "player_box_2026.parquet",
        "player_game_logs": "player_game_logs_2026.parquet",
        "player_season_stats": "player_season_stats_2026.parquet",
        "team_box": "team_box_2026.parquet",
        "standings": "standings_2026.parquet",
        "team_season_stats": "team_season_stats_2026.parquet",
    }
    resolved = {key: _resolve_sportsdataverse_file(config, filename) for key, filename in sports_files.items()}
    player_box = _read_parquet_optional(resolved["player_box"])
    player_game_logs = _read_parquet_optional(resolved["player_game_logs"])
    player_season_stats = _read_parquet_optional(resolved["player_season_stats"])
    team_box = _read_parquet_optional(resolved["team_box"])
    standings = _read_parquet_optional(resolved["standings"])
    team_season_stats = _read_parquet_optional(resolved["team_season_stats"])

    standings = _coerce_numeric_columns(standings, ["wins", "losses", "win_pct", "points_pg", "opp_points_pg"])
    player_game_logs = _coerce_numeric_columns(player_game_logs, ["pts", "ast", "tov", "min", "reb"])

    manifest = {
        "player_features": _file_record(player_features_path, player_features),
        "team_features": _file_record(team_features_path, team_features),
        "player_box": _file_record(resolved["player_box"], player_box),
        "player_game_logs": _file_record(resolved["player_game_logs"], player_game_logs),
        "player_season_stats": _file_record(resolved["player_season_stats"], player_season_stats),
        "team_box": _file_record(resolved["team_box"], team_box),
        "standings": _file_record(resolved["standings"], standings),
        "team_season_stats": _file_record(resolved["team_season_stats"], team_season_stats),
    }

    return LoadedSources(
        player_features=player_features,
        team_features=team_features,
        player_box=player_box,
        player_game_logs=player_game_logs,
        player_season_stats=player_season_stats,
        team_box=team_box,
        standings=standings,
        team_season_stats=team_season_stats,
        source_manifest=manifest,
    )


def write_github_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as f:
        f.write(markdown.rstrip() + "\n")

