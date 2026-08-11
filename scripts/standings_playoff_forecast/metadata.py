"""Deterministic run provenance for standings forecast output bundles."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .standings import ExternalStandingsQA
from .team_game_layer import LedgerValidationResult, normalize_id


SOURCE_OF_TRUTH = {
    "current_standings": "derived_from_schedule_and_team_box",
    "schedule": "mandatory",
    "team_box": "mandatory",
    "external_standings": "optional_validation",
}
EXTERNAL_STANDINGS_QA_STATUSES = frozenset(
    {"matched", "mismatch", "unavailable", "unparseable"}
)
SEASON_SCHEDULE_VALIDATION_COLUMNS = {
    "team_id",
    "completed_gp",
    "remaining_games",
    "configured_games",
    "total_games",
    "status",
}


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


def _ledger_validation_manifest(
    validation: LedgerValidationResult,
) -> dict[str, str]:
    if not isinstance(validation, LedgerValidationResult):
        raise TypeError("ledger_validation must be a LedgerValidationResult")
    completed_game_count = _normalized_nonnegative_int(
        validation.completed_game_count, "ledger_validation completed_game_count"
    )
    directional_row_count = _normalized_nonnegative_int(
        validation.directional_row_count, "ledger_validation directional_row_count"
    )
    if directional_row_count != completed_game_count * 2:
        raise ValueError(
            "ledger_validation directional_row_count must equal twice "
            "completed_game_count"
        )
    if not isinstance(validation.game_ids, tuple):
        raise TypeError("ledger_validation game_ids must be a tuple")
    normalized_game_ids = tuple(normalize_id(value) for value in validation.game_ids)
    if (
        any(value is None or value == "" for value in normalized_game_ids)
        or len(normalized_game_ids) != completed_game_count
        or len(set(normalized_game_ids)) != len(normalized_game_ids)
        or normalized_game_ids != tuple(sorted(normalized_game_ids))
    ):
        raise ValueError(
            "ledger_validation game_ids must be unique, normalized, sorted, and "
            "match completed_game_count"
        )
    return {"status": "validated"}


def _season_schedule_validation_manifest(
    validation: pd.DataFrame,
    cfg: object,
    expected_completed_game_count: int,
) -> dict[str, int | str]:
    if not isinstance(validation, pd.DataFrame):
        raise TypeError("season_schedule_validation must be a pandas DataFrame")
    missing = sorted(SEASON_SCHEDULE_VALIDATION_COLUMNS.difference(validation.columns))
    if missing:
        raise ValueError(
            "season_schedule_validation is missing required columns: "
            + ", ".join(missing)
        )
    if len(validation) != int(cfg.team_count):
        raise ValueError(
            "season_schedule_validation team count must match configured team_count"
        )
    team_ids = validation["team_id"].map(normalize_id)
    if team_ids.isna().any() or team_ids.eq("").any() or team_ids.duplicated().any():
        raise ValueError("season_schedule_validation contains invalid team IDs")
    if not validation["status"].map(
        lambda value: isinstance(value, str) and value == "validated"
    ).all():
        raise ValueError(
            "season_schedule_validation status must be validated for every team"
        )

    counts: dict[str, pd.Series] = {}
    for column in (
        "completed_gp",
        "remaining_games",
        "configured_games",
        "total_games",
    ):
        raw = validation[column]
        if raw.map(lambda value: isinstance(value, (bool, np.bool_))).any():
            raise ValueError(
                f"season_schedule_validation {column} must contain non-negative integers"
            )
        numeric = pd.to_numeric(raw, errors="coerce")
        if (
            numeric.isna().any()
            or not np.isfinite(numeric.to_numpy(dtype=float)).all()
            or numeric.lt(0).any()
            or not np.equal(numeric, np.floor(numeric)).all()
        ):
            raise ValueError(
                f"season_schedule_validation {column} must contain non-negative integers"
            )
        counts[column] = numeric.astype(int)

    configured_games_per_team = _normalized_nonnegative_int(
        cfg.regular_season_games_per_team,
        "configured regular_season_games_per_team",
    )
    if configured_games_per_team == 0:
        raise ValueError("configured regular_season_games_per_team must be positive")
    if (
        counts["configured_games"].ne(configured_games_per_team).any()
        or counts["total_games"].ne(configured_games_per_team).any()
        or (
            counts["completed_gp"] + counts["remaining_games"]
        ).ne(counts["total_games"]).any()
    ):
        raise ValueError(
            "season_schedule_validation counts must reconcile to configured games"
        )
    completed_directional_count = int(counts["completed_gp"].sum())
    if (
        completed_directional_count % 2 != 0
        or completed_directional_count // 2 != expected_completed_game_count
    ):
        raise ValueError(
            "season_schedule_validation completed games must match ledger validation"
        )
    return {
        "status": "validated",
        "configured_games_per_team": configured_games_per_team,
    }


def _external_standings_qa_manifest(
    validation: ExternalStandingsQA, cfg: object
) -> dict[str, Any]:
    if not isinstance(validation, ExternalStandingsQA):
        raise TypeError("external_standings_qa must be an ExternalStandingsQA")
    if validation.status not in EXTERNAL_STANDINGS_QA_STATUSES:
        raise ValueError("external standings QA status is invalid")
    compared_team_count = _normalized_nonnegative_int(
        validation.compared_team_count,
        "external standings QA compared_team_count",
    )
    configured_team_count = _normalized_nonnegative_int(
        cfg.team_count, "configured team_count"
    )
    if configured_team_count == 0:
        raise ValueError("configured team_count must be positive")
    if compared_team_count > configured_team_count:
        raise ValueError(
            "external standings QA compared_team_count cannot exceed configured team_count"
        )
    if not isinstance(validation.mismatch_team_ids, tuple):
        raise TypeError("external standings QA mismatch_team_ids must be a tuple")
    mismatch_team_ids = tuple(
        normalize_id(value) for value in validation.mismatch_team_ids
    )
    if (
        any(value is None or value == "" for value in mismatch_team_ids)
        or len(set(mismatch_team_ids)) != len(mismatch_team_ids)
        or mismatch_team_ids != tuple(sorted(mismatch_team_ids))
    ):
        raise ValueError(
            "external standings QA mismatch_team_ids must be unique, normalized, "
            "and sorted"
        )
    if not isinstance(validation.message, str) or not validation.message.strip():
        raise ValueError("external standings QA message must be non-blank")
    if validation.status == "matched" and (
        compared_team_count != configured_team_count or mismatch_team_ids
    ):
        raise ValueError(
            "matched external standings QA must cover every configured team "
            "without mismatches"
        )
    if validation.status == "mismatch" and not mismatch_team_ids:
        raise ValueError("mismatch external standings QA must name mismatched teams")
    if validation.status in {"unavailable", "unparseable"} and (
        compared_team_count != 0 or mismatch_team_ids
    ):
        raise ValueError(
            "unavailable or unparseable external standings QA cannot contain comparisons"
        )
    return {
        "status": validation.status,
        "compared_team_count": compared_team_count,
        "mismatch_team_ids": list(mismatch_team_ids),
    }


def _validate_external_source_coherence(
    source_files: Mapping[str, str | Path | Mapping[str, Any]],
    qa_status: str,
) -> None:
    if not isinstance(source_files, Mapping):
        raise TypeError("source_files must be a name-to-source mapping")
    has_external_source = "external_standings" in source_files
    if qa_status in {"matched", "mismatch", "unparseable"}:
        if not has_external_source:
            raise ValueError(
                f"external standings QA status {qa_status} requires "
                "external_standings source provenance"
            )
    elif qa_status == "unavailable" and has_external_source:
        raise ValueError(
            "unavailable external standings QA must omit external_standings "
            "source provenance"
        )


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
        if _pbpstats_provenance_kind(team_strength) == "last_saved_at_utc_upper_bound":
            return "safe_for_cutoff_via_last_saved_upper_bound"
        return "safe_for_cutoff"
    if available:
        return "available_not_safe_for_cutoff"
    return "unavailable"


def _pbpstats_provenance_kind(team_strength: pd.DataFrame) -> str:
    if team_strength.empty or "pbpstats_provenance_kind" not in team_strength.columns:
        return "unavailable"
    kinds = set(team_strength["pbpstats_provenance_kind"].dropna().astype(str))
    if not kinds:
        return "unavailable"
    if len(kinds) != 1:
        raise ValueError("PBPStats provenance kind must agree across team rows")
    kind = next(iter(kinds))
    if kind not in {"snapshot_as_of", "last_saved_at_utc_upper_bound"}:
        raise ValueError(f"unsupported PBPStats provenance kind: {kind}")
    return kind


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
    ledger_validation: LedgerValidationResult,
    season_schedule_validation: pd.DataFrame,
    external_standings_qa: ExternalStandingsQA,
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
    external_qa_manifest = _external_standings_qa_manifest(
        external_standings_qa, cfg
    )
    _validate_external_source_coherence(
        source_files, external_qa_manifest["status"]
    )
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
        "source_of_truth": dict(SOURCE_OF_TRUTH),
        "ledger_validation": _ledger_validation_manifest(ledger_validation),
        "season_schedule_validation": _season_schedule_validation_manifest(
            season_schedule_validation,
            cfg,
            int(ledger_validation.completed_game_count),
        ),
        "external_standings_qa": external_qa_manifest,
        "pbpstats_enrichment_status": _pbpstats_enrichment_status(
            team_strength, model_cfg
        ),
        "pbpstats_provenance_kind": _pbpstats_provenance_kind(team_strength),
        "history_seasons_used": _history_seasons_used(
            historical_context, int(cfg.season)
        ),
        "official_tiebreak_fallback_count": fallback_count,
        "git_sha": git_sha,
        "git_sha_status": git_status,
    }
