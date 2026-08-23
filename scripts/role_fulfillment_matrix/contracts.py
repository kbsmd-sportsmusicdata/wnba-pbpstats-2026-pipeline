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


def require_fixture_mode(config: Mapping[str, Any]) -> None:
    if config.get("mode") != "fixture":
        raise LiveScoringBlocked(
            "Live scoring remains blocked until reviewed live role thresholds are added. "
            "Eligibility and player-role assignments are approved; use the fixture config "
            "until the final governance gate is complete."
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
