from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


SEASON = 2026


@dataclass
class LoadedSources:
    player_box: pd.DataFrame
    team_box: pd.DataFrame
    standings: pd.DataFrame
    espn_pbp: pd.DataFrame
    wnba_stats_pbp: pd.DataFrame
    player_features: pd.DataFrame
    team_features: pd.DataFrame
    allstar_board: pd.DataFrame
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
    return path_from_config(config.get("output_root", "analysis/midseason_team_grades"))


def ensure_output_dirs(output_root: Path) -> Dict[str, Path]:
    paths = {
        "processed": output_root / "data" / "processed",
        "eda": output_root / "data" / "eda",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _file_record(
    path: Optional[Path],
    df: pd.DataFrame,
    *,
    requested: Optional[str] = None,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "path": str(path) if path else None,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        # A misconfigured filename used to look identical to a genuinely empty feed, which
        # let clutch and RAPM return nothing without anything saying why.
        "status": "resolved" if path is not None else "unresolved",
    }
    if path is None and requested:
        record["requested_filename"] = requested
    if path and path.exists():
        stat = path.stat()
        record["modified_at_utc"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        record["size_bytes"] = stat.st_size
    if "game_date" in df.columns and not df.empty:
        dates = pd.to_datetime(df["game_date"], errors="coerce").dropna()
        if not dates.empty:
            record["latest_game_date"] = dates.max().date().isoformat()
    return record


def _resolve_sports_file(config: Dict[str, Any], filename: str) -> Optional[Path]:
    primary_root = path_from_config(config.get("sportsdataverse_data_root", "data/raw/sportsdataverse/wnba_2026"))
    primary = primary_root / filename
    if primary.exists():
        return primary
    fallback_root = path_from_config(config.get("sportsdataverse_fallback_root", "2026_scout_report"))
    fallback = fallback_root / filename
    if fallback.exists():
        return fallback
    return None


def _read_parquet_optional(path: Optional[Path]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _coerce_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    source_files = config.get("source_files", {})
    sports_files = {
        "player_box": source_files.get("player_box", "player_box_2026.parquet"),
        "team_box": source_files.get("team_box", "team_box_2026.parquet"),
        "standings": source_files.get("standings", "standings_2026.parquet"),
        "espn_pbp": source_files.get("espn_pbp", "espn_pbp_2026.parquet"),
        "wnba_stats_pbp": source_files.get("wnba_stats_pbp", "wnba_pbp_2026.parquet"),
    }
    resolved = {key: _resolve_sports_file(config, filename) for key, filename in sports_files.items()}

    player_box = _read_parquet_optional(resolved["player_box"])
    team_box = _read_parquet_optional(resolved["team_box"])
    standings = _read_parquet_optional(resolved["standings"])
    espn_pbp = _read_parquet_optional(resolved["espn_pbp"])
    wnba_stats_pbp = _read_parquet_optional(resolved["wnba_stats_pbp"])

    numeric_box = [
        "minutes",
        "points",
        "field_goals_made",
        "field_goals_attempted",
        "three_point_field_goals_made",
        "free_throws_attempted",
        "rebounds",
        "assists",
        "turnovers",
        "plus_minus",
    ]
    player_box = _coerce_numeric_columns(player_box, numeric_box)
    team_box = _coerce_numeric_columns(
        team_box,
        [
            "team_score",
            "opponent_team_score",
            "field_goals_made",
            "field_goals_attempted",
            "three_point_field_goals_made",
            "free_throws_attempted",
            "offensive_rebounds",
            "defensive_rebounds",
            "turnovers",
        ],
    )
    standings = _coerce_numeric_columns(standings, ["wins", "losses", "win_pct"])
    espn_pbp = _coerce_numeric_columns(espn_pbp, ["home_score", "away_score", "score_value", "start_game_seconds_remaining"])
    wnba_stats_pbp = _coerce_numeric_columns(wnba_stats_pbp, ["score_value", "garbage_time"])

    season = str(config.get("season", SEASON))
    pbp_root = path_from_config(config.get("pbpstats_data_root", "data/pbpstats_wnba_2026"))
    player_features_path = pbp_root / "features_latest" / season / "player_totals_features_latest.csv"
    team_features_path = pbp_root / "features_latest" / season / "team_totals_features_latest.csv"
    player_features = _read_csv_optional(player_features_path)
    team_features = _read_csv_optional(team_features_path)

    allstar_root = path_from_config(config.get("allstar_value_board_root", "analysis/midseason_allstar_value_board"))
    allstar_board_path = allstar_root / "data" / "processed" / "allstar_value_board_2026.csv"
    allstar_board = _read_csv_optional(allstar_board_path)

    manifest = {
        "player_box": _file_record(resolved["player_box"], player_box, requested=sports_files["player_box"]),
        "team_box": _file_record(resolved["team_box"], team_box, requested=sports_files["team_box"]),
        "standings": _file_record(resolved["standings"], standings, requested=sports_files["standings"]),
        "espn_pbp": _file_record(resolved["espn_pbp"], espn_pbp, requested=sports_files["espn_pbp"]),
        "wnba_stats_pbp": _file_record(
            resolved["wnba_stats_pbp"], wnba_stats_pbp, requested=sports_files["wnba_stats_pbp"]
        ),
        "player_features": _file_record(player_features_path, player_features),
        "team_features": _file_record(team_features_path, team_features),
        "allstar_board": _file_record(allstar_board_path, allstar_board),
    }

    return LoadedSources(
        player_box=player_box,
        team_box=team_box,
        standings=standings,
        espn_pbp=espn_pbp,
        wnba_stats_pbp=wnba_stats_pbp,
        player_features=player_features,
        team_features=team_features,
        allstar_board=allstar_board,
        source_manifest=manifest,
    )
