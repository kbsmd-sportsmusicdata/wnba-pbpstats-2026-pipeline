"""Fail-closed source contracts for the Role Fulfillment Matrix experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


class ContractError(ValueError):
    """Raised when an input cannot support the declared analysis."""


class LiveScoringBlocked(ContractError):
    """Raised when a non-fixture run reaches the unapproved governance boundary."""


LIVE_APPROVAL_MANIFEST = (
    "analysis/role_fulfillment_matrix/data/review/"
    "live_output_approval_manifest_2026.json"
)


def live_config_fingerprint(config: Mapping[str, Any]) -> str:
    """Hash reviewed live inputs and rules while allowing per-run output routing."""
    excluded = {"_config_path", "output_root", "manual_run_id"}
    approved_fields = {
        key: value for key, value in config.items() if key not in excluded
    }
    encoded = json.dumps(
        approved_fields,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_live_approval(config: Mapping[str, Any]) -> None:
    manifest_reference = config.get("live_output_approval_manifest")
    if manifest_reference != LIVE_APPROVAL_MANIFEST:
        raise LiveScoringBlocked(
            "live execution requires the committed live-output approval manifest"
        )
    manifest_path = Path(__file__).resolve().parents[2] / LIVE_APPROVAL_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LiveScoringBlocked(
            "live execution could not read the committed approval manifest"
        ) from exc
    if (
        manifest.get("review_status") != "approved"
        or manifest.get("execution_mode") != "manual_only"
        or manifest.get("scheduling_enabled") is not False
    ):
        raise LiveScoringBlocked("live-output approval manifest is not active")
    if manifest.get("approved_config_sha256") != live_config_fingerprint(config):
        raise LiveScoringBlocked(
            "live configuration does not match the reviewed configuration hash"
        )


REQUIRED_COLUMNS = {
    "standings": {"team_abbreviation", "current_rank", "cutoff_date"},
    "player_game": {
        "game_date", "game_id", "player_id", "player_name", "team_abbreviation",
        "minutes", "off_poss", "team_possessions", "points", "assists", "turnovers",
        "fga", "fgm", "fta", "ftm", "at_rim_fga", "at_rim_fgm",
    },
    "eligibility": {
        "player_id", "player_name", "eligibility_type", "eligible_flag", "active",
        "status_type", "review_status",
    },
    "role_assignments": {
        "player_id", "player_name", "role_code", "assignment_confidence", "review_status",
    },
}


def authorize_execution(config: Mapping[str, Any]) -> None:
    """Permit fixtures, approved dry runs, and explicitly approved manual live runs."""
    mode = config.get("mode")
    if mode == "fixture":
        return
    if mode == "live_dry_run":
        approved = (
            config.get("validation_status") == "approved_11_player_review"
            and config.get("live_adapter_status") == "approved_review"
            and config.get("live_output_enabled") is False
        )
        if approved:
            return
        raise LiveScoringBlocked(
            "live dry run requires approved formula validation, approved adapter review, "
            "and live_output_enabled=false"
        )
    if mode == "live":
        approved = (
            config.get("validation_status") == "approved_11_player_review"
            and config.get("live_adapter_status") == "approved_review"
            and config.get("end_to_end_review_status") == "approved_19_player_review"
            and config.get("live_output_enabled") is True
            and config.get("execution_mode") == "manual_only"
            and config.get("scheduling_enabled") is False
        )
        if approved:
            _verify_live_approval(config)
            return
        raise LiveScoringBlocked(
            "live execution requires approved formula, adapter, and 19-player reviews; "
            "live_output_enabled=true; execution_mode=manual_only; and "
            "scheduling_enabled=false"
        )
    raise LiveScoringBlocked(
        f"unsupported Role Fulfillment Matrix execution mode: {mode}"
    )


def validate_frame(name: str, frame: pd.DataFrame) -> None:
    required = REQUIRED_COLUMNS[name]
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ContractError(f"{name} is missing required fields: {', '.join(missing)}")
    if frame.empty:
        raise ContractError(f"{name} is empty")


def validate_role_definitions(definitions: Mapping[str, Any]) -> None:
    if not definitions:
        raise ContractError("role_definitions is empty")
    for code, definition in definitions.items():
        metrics = definition.get("metrics", [])
        if not definition.get("label") or not metrics:
            raise ContractError(f"role_definitions.{code} requires label and metrics")
        weight = sum(float(metric.get("weight", 0)) for metric in metrics)
        if abs(weight - 1.0) > 1e-9:
            raise ContractError(f"role_definitions.{code} metric weights must sum to 1.0")
