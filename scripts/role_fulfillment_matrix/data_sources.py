"""Source loading for fixture and approved live-dry-run execution."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .contracts import (
    ContractError,
    authorize_execution,
    validate_frame,
    validate_role_definitions,
)
from .adapter_parity import build_adapter_parity
from .live_policy import derive_analysis_windows, validate_locked_parity_windows
from .metrics import build_window_metrics
from .pbpstats_adapter import adapt_pbpstats_player_game, audit_live_adapter
from .roster_adapter import adapt_espn_roster
from .standings_adapter import adapt_forecast_standings


@dataclass
class LoadedSources:
    standings: pd.DataFrame
    player_game: pd.DataFrame
    eligibility: pd.DataFrame
    role_assignments: pd.DataFrame
    role_definitions: Dict[str, Any]
    source_manifest: Dict[str, Dict[str, Any]]
    roster_status: pd.DataFrame
    adapter_audit: Dict[str, Any]
    effective_config: Dict[str, Any]


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


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise ContractError(f"source does not exist: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def require_pbp_eligibility_coverage(
    player_game: pd.DataFrame, eligibility: pd.DataFrame
) -> None:
    """Reject new PBPStats player identities until their eligibility rows are reviewed."""
    covered_ids = set(eligibility["player_id"].astype(str))
    missing = (
        player_game.loc[
            ~player_game["player_id"].astype(str).isin(covered_ids),
            ["player_id", "player_name"],
        ]
        .drop_duplicates("player_id")
        .sort_values(["player_name", "player_id"])
    )
    if not missing.empty:
        labels = [
            f"{row.player_name} ({row.player_id})"
            for row in missing.itertuples(index=False)
        ]
        raise ContractError(
            "PBPStats player population missing reviewed eligibility rows: "
            + ", ".join(labels)
        )


def _load_role_definitions(configured: Dict[str, Any]) -> tuple[Dict[str, Any], Path]:
    role_path = resolve_path(configured.get("role_definitions", ""))
    with role_path.open(encoding="utf-8") as handle:
        role_definitions = json.load(handle)
    validate_role_definitions(role_definitions)
    return role_definitions, role_path


def _fixture_roster(player_game: pd.DataFrame, eligibility: pd.DataFrame) -> pd.DataFrame:
    teams = (
        player_game.sort_values("game_date")
        .drop_duplicates("player_id", keep="last")
        [["player_id", "player_name", "team_abbreviation"]]
    )
    status = eligibility[["player_id", "active", "status_type"]]
    return teams.merge(status, on="player_id", how="left", validate="one_to_one")


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    # Authorization is deliberately before path resolution so unapproved runs touch no live data.
    authorize_execution(config)
    if config.get("mode") in {"live_dry_run", "live"}:
        return _load_reviewed_live(config)
    return _load_fixture(config)


def _load_fixture(config: Dict[str, Any]) -> LoadedSources:
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

    role_definitions, role_path = _load_role_definitions(configured)
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
        roster_status=_fixture_roster(player_game, tables["eligibility"]),
        adapter_audit={},
        effective_config=config,
    )


def _load_reviewed_live(config: Dict[str, Any]) -> LoadedSources:
    configured = config.get("sources", {})
    if not configured.get("locked_parity_inputs"):
        raise ContractError("reviewed live execution requires locked_parity_inputs")
    try:
        parity_windows = validate_locked_parity_windows(
            config.get("locked_parity_windows")
        )
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    paths = {key: resolve_path(value) for key, value in configured.items() if key != "roster_source_as_of"}

    raw_standings = _read_table(paths["standings"])
    standings_manifest = _read_json(paths["standings_manifest"])
    standings_result = adapt_forecast_standings(raw_standings, standings_manifest)
    cutoff_date = standings_result.quality["cutoff_date"]
    policy = config.get("window_policy", {})
    effective_config = deepcopy(config)
    effective_config["analysis_cutoff_date"] = cutoff_date
    effective_config["windows"] = derive_analysis_windows(
        cutoff_date,
        recent_days=int(policy.get("recent_days", 0)),
        baseline_days=int(policy.get("baseline_days", 0)),
        lag_days=int(policy.get("lag_days", -1)),
    )

    eligibility = _read_table(paths["eligibility"])
    assignments = _read_table(paths["role_assignments"])
    eligibility["player_id"] = eligibility["player_id"].astype(str)
    assignments["player_id"] = assignments["player_id"].astype(str)
    validate_frame("eligibility", eligibility)
    validate_frame("role_assignments", assignments)
    role_definitions, role_path = _load_role_definitions(configured)

    player_raw = _read_table(paths["pbpstats_player_game"])
    team_raw = _read_table(paths["pbpstats_team_game"])
    adapter_result = adapt_pbpstats_player_game(player_raw, team_raw)
    require_pbp_eligibility_coverage(adapter_result.player_game, eligibility)
    ingest_manifest = _read_json(paths["pbpstats_manifest"])
    failures = _read_json(paths["pbpstats_failures"])
    if not isinstance(failures, list):
        raise ContractError("PBPStats player failure ledger must be a JSON list")
    adapter_audit = audit_live_adapter(
        adapter_result,
        assignments=assignments,
        manifest=ingest_manifest,
        failures=failures,
        recent_end=effective_config["windows"]["recent_end"],
    )
    if adapter_audit["status"] != "review_ready":
        raise ContractError("live adapter audit blocked: " + "; ".join(adapter_audit["blockers"]))
    parity_path = paths["locked_parity_inputs"]
    parity_config = deepcopy(effective_config)
    parity_config["windows"] = parity_windows
    parity = build_adapter_parity(
        build_window_metrics(adapter_result.player_game, parity_config),
        _read_table(parity_path),
    )
    parity_matches = int(parity["parity_match"].sum())
    parity_maximum = float(parity["max_abs_difference"].max())
    adapter_audit.update(
        {
            "locked_parity_players": int(len(parity)),
            "locked_parity_matches": parity_matches,
            "locked_parity_max_abs_difference": parity_maximum,
            "locked_parity_windows": parity_windows,
        }
    )
    if parity_matches != len(parity):
        raise ContractError(
            f"live adapter locked parity failed for {len(parity) - parity_matches} players"
        )

    roster_result = adapt_espn_roster(
        _read_table(paths["roster"]),
        eligibility,
        raw_standings,
        source_as_of=str(configured.get("roster_source_as_of", "")),
        cutoff_date=cutoff_date,
    )
    standings = standings_result.standings
    player_game = adapter_result.player_game
    validate_frame("standings", standings)
    validate_frame("player_game", player_game)

    source_manifest = {
        "standings": {
            "path": portable_path(paths["standings"]),
            "manifest_path": portable_path(paths["standings_manifest"]),
            "rows": int(len(standings)),
            "columns": int(len(standings.columns)),
            "status": "validated_forecast_output",
            "quality": standings_result.quality,
        },
        "player_game": {
            "path": portable_path(paths["pbpstats_player_game"]),
            "team_path": portable_path(paths["pbpstats_team_game"]),
            "manifest_path": portable_path(paths["pbpstats_manifest"]),
            "failure_ledger_path": portable_path(paths["pbpstats_failures"]),
            "locked_parity_path": (
                None if parity_path is None else portable_path(parity_path)
            ),
            "rows": int(len(player_game)),
            "columns": int(len(player_game.columns)),
            "status": "reviewed_live_adapter",
            "quality": adapter_result.quality,
            "audit": adapter_audit,
        },
        "eligibility": {
            "path": portable_path(paths["eligibility"]),
            "rows": int(len(eligibility)),
            "columns": int(len(eligibility.columns)),
            "status": "reviewed_real_data",
        },
        "role_assignments": {
            "path": portable_path(paths["role_assignments"]),
            "rows": int(len(assignments)),
            "columns": int(len(assignments.columns)),
            "status": "reviewed_real_data",
        },
        "roster_status": {
            "path": portable_path(paths["roster"]),
            "rows": int(len(roster_result.roster)),
            "columns": int(len(roster_result.roster.columns)),
            "status": "current_roster_with_eligibility_coverage",
            "quality": roster_result.quality,
        },
        "role_definitions": {
            "path": portable_path(role_path),
            "rows": len(role_definitions),
            "columns": None,
            "status": "approved_live_configuration",
        },
    }
    return LoadedSources(
        standings=standings,
        player_game=player_game,
        eligibility=eligibility,
        role_assignments=assignments,
        role_definitions=role_definitions,
        source_manifest=source_manifest,
        roster_status=roster_result.roster,
        adapter_audit=adapter_audit,
        effective_config=effective_config,
    )
