"""Deterministic run provenance for standings forecast output bundles."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_hash(path: str | Path, name: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"missing {name}: {resolved}")
    return _sha256(resolved)


def _normalized_nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be a non-negative integer")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return normalized


def _source_provenance(
    source_files: Mapping[str, str | Path | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(source_files, Mapping):
        raise TypeError("source_files must be a name-to-source mapping")
    if not source_files:
        raise ValueError("source_files must not be empty")
    provenance: list[dict[str, Any]] = []
    for name in sorted(source_files):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("source file names must be non-blank strings")
        supplied = source_files[name]
        if isinstance(supplied, Mapping):
            if "path" not in supplied:
                raise ValueError(f"source provenance for {name} is missing path")
            path = Path(supplied["path"]).expanduser().resolve()
            evidence = {
                key: value for key, value in supplied.items() if key != "path"
            }
        else:
            path = Path(supplied).expanduser().resolve()
            evidence = {}
        reserved_fields = {"name", "path", "size_bytes", "sha256"}
        extra_evidence = {
            key: value for key, value in evidence.items() if key not in reserved_fields
        }
        if path.is_file():
            entry = {
                "name": str(name),
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                **extra_evidence,
            }
        else:
            if not {"size_bytes", "sha256"}.issubset(evidence):
                raise FileNotFoundError(
                    f"source file is unavailable and lacks supplied stable evidence: {path}"
                )
            size_bytes = evidence["size_bytes"]
            if (
                isinstance(size_bytes, (bool, np.bool_))
                or not isinstance(size_bytes, (int, np.integer))
                or int(size_bytes) < 0
            ):
                raise ValueError(f"source provenance for {name} has invalid size_bytes")
            sha256 = evidence["sha256"]
            if (
                not isinstance(sha256, str)
                or len(sha256) != 64
                or any(character not in "0123456789abcdef" for character in sha256.lower())
            ):
                raise ValueError(
                    f"source provenance for {name} must include a valid SHA-256"
                )
            entry = {
                "name": str(name),
                "path": str(path),
                "size_bytes": int(size_bytes),
                "sha256": sha256.lower(),
                **extra_evidence,
            }
        provenance.append(entry)
    return provenance


def _history_seasons_used(historical_context: pd.DataFrame, forecast_season: int) -> list[int]:
    required = {"season", "availability_status"}
    missing = sorted(required.difference(historical_context.columns))
    if missing:
        raise ValueError(
            "historical_context is missing required columns: " + ", ".join(missing)
        )
    available = historical_context.loc[
        historical_context["availability_status"].eq("available"), "season"
    ].dropna()
    if available.empty:
        return []
    numeric = pd.to_numeric(available, errors="coerce")
    if numeric.isna().any() or not np.equal(numeric, np.floor(numeric)).all():
        raise ValueError("available historical rows contain invalid season values")
    seasons = sorted({int(value) for value in numeric})
    if any(season >= forecast_season for season in seasons):
        raise ValueError("history_seasons_used must contain only prior seasons")
    return seasons


def _pbpstats_enrichment_status(team_strength: pd.DataFrame, model_cfg: object) -> str:
    if not getattr(model_cfg, "pbpstats_enrichment_enabled"):
        return "disabled"
    required = {
        "pbpstats_snapshot_available",
        "pbpstats_snapshot_safe_for_cutoff",
    }
    missing = sorted(required.difference(team_strength.columns))
    if missing:
        raise ValueError(
            "team_strength is missing PBPStats safety columns: " + ", ".join(missing)
        )
    if team_strength.empty:
        return "unavailable"
    available_values = set(team_strength["pbpstats_snapshot_available"].tolist())
    safe_values = set(team_strength["pbpstats_snapshot_safe_for_cutoff"].tolist())
    if not available_values.issubset({True, False}) or not safe_values.issubset(
        {True, False}
    ):
        raise ValueError("PBPStats safety fields must be non-null booleans")
    if len(available_values) != 1 or len(safe_values) != 1:
        raise ValueError("PBPStats safety fields must agree across team rows")
    available = bool(next(iter(available_values)))
    safe = bool(next(iter(safe_values)))
    if safe and not available:
        raise ValueError("a cutoff-safe PBPStats snapshot must also be available")
    if safe:
        return "safe_for_cutoff"
    if available:
        return "available_not_safe_for_cutoff"
    return "unavailable"


def _git_provenance(repository_root: str | Path) -> tuple[str | None, str]:
    root = Path(repository_root).expanduser().resolve()
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "unavailable"
    sha = completed.stdout.strip()
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha.lower()):
        return None, "unavailable"
    return sha, "available"


def build_run_manifest(
    *,
    cfg: object,
    model_cfg: object,
    simulation_result: object,
    cutoff: object,
    season_config_path: str | Path,
    model_config_path: str | Path,
    source_files: Mapping[str, str | Path | Mapping[str, Any]],
    team_strength: pd.DataFrame,
    historical_context: pd.DataFrame,
    conditional_simulation_count: int = 0,
    repository_root: str | Path,
) -> dict[str, Any]:
    """Build a source-evidenced manifest without inferring unrun work."""

    cutoff_timestamp = pd.Timestamp(cutoff)
    if pd.isna(cutoff_timestamp):
        raise ValueError("cutoff must be a valid timestamp")
    cutoff_date = cutoff_timestamp.date().isoformat()
    conditional_count = _normalized_nonnegative_int(
        conditional_simulation_count, "conditional_simulation_count"
    )
    simulation_count = _normalized_nonnegative_int(
        simulation_result.simulation_count, "simulation_count"
    )
    if simulation_count == 0:
        raise ValueError("simulation_count must be positive")
    random_seed = _normalized_nonnegative_int(simulation_result.seed, "random_seed")
    fallback_count = _normalized_nonnegative_int(
        simulation_result.fallback_count, "official_tiebreak_fallback_count"
    )
    git_sha, git_status = _git_provenance(repository_root)
    return {
        "season": int(cfg.season),
        "cutoff_date": cutoff_date,
        "simulation_count": simulation_count,
        "conditional_simulation_count": conditional_count,
        "random_seed": random_seed,
        "model_version": str(model_cfg.model_version),
        "season_config_sha256": _config_hash(
            season_config_path, "season config"
        ),
        "model_config_sha256": _config_hash(model_config_path, "model config"),
        "source_files": _source_provenance(source_files),
        "pbpstats_enrichment_status": _pbpstats_enrichment_status(
            team_strength, model_cfg
        ),
        "history_seasons_used": _history_seasons_used(
            historical_context, int(cfg.season)
        ),
        "official_tiebreak_fallback_count": fallback_count,
        "git_sha": git_sha,
        "git_sha_status": git_status,
    }
