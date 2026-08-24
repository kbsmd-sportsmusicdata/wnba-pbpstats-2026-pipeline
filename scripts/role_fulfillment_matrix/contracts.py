"""Fail-closed source contracts for the Role Fulfillment Matrix experiment."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


class ContractError(ValueError):
    """Raised when an input cannot support the declared analysis."""


class LiveScoringBlocked(ContractError):
    """Raised when a non-fixture run reaches the unapproved governance boundary."""


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
