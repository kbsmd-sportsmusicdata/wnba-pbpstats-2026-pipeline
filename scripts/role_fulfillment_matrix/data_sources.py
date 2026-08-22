"""Explicit fixture adapter for the Role Fulfillment Matrix vertical slice."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .contracts import require_fixture_mode, validate_frame, validate_role_definitions


@dataclass
class LoadedSources:
    standings: pd.DataFrame
    player_game: pd.DataFrame
    eligibility: pd.DataFrame
    role_assignments: pd.DataFrame
    role_definitions: Dict[str, Any]
    source_manifest: Dict[str, Dict[str, Any]]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def portable_path(path: Path) -> str:
    """Prefer a repository-relative path so committed manifests survive worktree moves."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(repo_root().resolve()).as_posix()
    except ValueError:
        return str(resolved)


def load_config(path: Path) -> Dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        config = json.load(handle)
    config["_config_path"] = portable_path(Path(path))
    return config


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root() / path


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        from .contracts import ContractError

        raise ContractError(f"source does not exist: {path}")
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    # This is deliberately before path resolution: an unapproved live run must not touch live data.
    require_fixture_mode(config)
    configured = config.get("sources", {})
    tables: Dict[str, pd.DataFrame] = {}
    manifest: Dict[str, Dict[str, Any]] = {}

    for name in ("standings", "player_game", "eligibility", "role_assignments"):
        path = resolve_path(configured.get(name, ""))
        frame = _read_table(path)
        validate_frame(name, frame)
        tables[name] = frame
        manifest[name] = {
            "path": portable_path(path), "rows": int(len(frame)), "columns": int(len(frame.columns)),
            "status": "synthetic_fixture",
        }

    role_path = resolve_path(configured.get("role_definitions", ""))
    with role_path.open(encoding="utf-8") as handle:
        role_definitions = json.load(handle)
    validate_role_definitions(role_definitions)
    manifest["role_definitions"] = {
        "path": portable_path(role_path), "rows": len(role_definitions), "columns": None,
        "status": "reviewable_configuration",
    }

    player_game = tables["player_game"].copy()
    player_game["game_date"] = pd.to_datetime(player_game["game_date"], errors="coerce")
    if player_game["game_date"].isna().any():
        from .contracts import ContractError

        raise ContractError("player_game contains invalid game_date values")

    standings = tables["standings"].copy()
    standings["current_rank"] = pd.to_numeric(standings["current_rank"], errors="coerce")
    if standings["current_rank"].isna().any():
        from .contracts import ContractError

        raise ContractError("standings contains invalid current_rank values")

    return LoadedSources(
        standings=standings,
        player_game=player_game,
        eligibility=tables["eligibility"],
        role_assignments=tables["role_assignments"],
        role_definitions=role_definitions,
        source_manifest=manifest,
    )
