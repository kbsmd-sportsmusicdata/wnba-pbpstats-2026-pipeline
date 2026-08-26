"""Review-only adapter from raw PBPStats game logs to the RFM player-game contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd


class AdapterContractError(ValueError):
    """Raised when raw PBPStats inputs cannot support a trustworthy canonical table."""


PLAYER_REQUIRED = {
    "Date", "GameId", "Team", "PlayerId", "PlayerName", "Minutes",
    "OffPoss", "DefPoss", "TotalPoss", "Points", "Assists", "Turnovers",
    "FG2M", "FG2A", "FG3M", "FG3A", "FTA", "FtPoints",
    "AtRimFGM", "AtRimFGA", "Rebounds", "OffRebounds",
}
TEAM_REQUIRED = {"Date", "GameId", "TeamAbbreviation", "OffPoss"}
ZERO_OMITTED_COUNTS = (
    "Points", "Assists", "Turnovers", "FG2M", "FG2A", "FG3M", "FG3A",
    "FTA", "FtPoints", "AtRimFGM", "AtRimFGA", "Rebounds", "OffRebounds",
)


@dataclass
class AdapterResult:
    player_game: pd.DataFrame
    quality: Dict[str, Any]


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise AdapterContractError(f"{label} missing required columns: {', '.join(missing)}")


def _minutes(value: Any) -> float:
    if value is None or pd.isna(value):
        raise AdapterContractError("player game has missing Minutes")
    text = str(value).strip()
    if ":" not in text:
        try:
            return float(text)
        except ValueError as error:
            raise AdapterContractError(f"invalid Minutes value: {value}") from error
    minute_text, second_text = text.split(":", 1)
    try:
        seconds = float(second_text)
        if seconds < 0 or seconds >= 60:
            raise ValueError
        return float(minute_text) + seconds / 60.0
    except ValueError as error:
        raise AdapterContractError(f"invalid Minutes value: {value}") from error


def adapt_pbpstats_player_game(
    player_raw: pd.DataFrame,
    team_raw: pd.DataFrame,
) -> AdapterResult:
    """Normalize raw PBPStats rows without converting structural missingness into zero."""
    _require_columns(player_raw, PLAYER_REQUIRED, "player game log")
    _require_columns(team_raw, TEAM_REQUIRED, "team game log")
    if player_raw.duplicated(["PlayerId", "GameId"]).any():
        raise AdapterContractError("player game log has duplicate PlayerId and GameId keys")
    if team_raw.duplicated(["TeamAbbreviation", "GameId"]).any():
        raise AdapterContractError("team game log has duplicate TeamAbbreviation and GameId keys")

    players = player_raw.copy()
    players["_minutes"] = players["Minutes"].map(_minutes)
    no_possession_evidence = players[["OffPoss", "DefPoss", "TotalPoss"]].isna().all(axis=1)
    nonparticipation = players["_minutes"].eq(0) & no_possession_evidence
    excluded_nonparticipation = int(nonparticipation.sum())
    players = players.loc[~nonparticipation].copy()

    for column in ("OffPoss", "DefPoss", "TotalPoss") + ZERO_OMITTED_COUNTS:
        players[column] = pd.to_numeric(players[column], errors="coerce")

    zero_filled_cells: Dict[str, int] = {}
    for column in ("OffPoss", "DefPoss") + ZERO_OMITTED_COUNTS:
        zero_filled_cells[column] = int(players[column].isna().sum())
        players[column] = players[column].fillna(0.0)

    derived_total = players["OffPoss"] + players["DefPoss"]
    players["TotalPoss"] = players["TotalPoss"].fillna(derived_total)
    if ((players["TotalPoss"] - derived_total).abs() > 1e-9).any():
        raise AdapterContractError("TotalPoss does not equal OffPoss plus DefPoss")

    identity_columns = ["Date", "GameId", "Team", "PlayerId", "PlayerName"]
    if players[identity_columns].isna().any().any():
        raise AdapterContractError("player game log has missing identity fields")
    players["_game_date"] = pd.to_datetime(players["Date"], errors="coerce")
    if players["_game_date"].isna().any():
        raise AdapterContractError("player game log has invalid Date values")

    teams = team_raw.copy()
    teams["OffPoss"] = pd.to_numeric(teams["OffPoss"], errors="coerce")
    if teams[["GameId", "TeamAbbreviation", "OffPoss"]].isna().any().any():
        raise AdapterContractError("team game log has missing key or possession values")
    teams["_team_game_date"] = pd.to_datetime(teams["Date"], errors="coerce")
    if teams["_team_game_date"].isna().any():
        raise AdapterContractError("team game log has invalid Date values")
    team_possessions = teams[
        ["GameId", "TeamAbbreviation", "OffPoss", "_team_game_date"]
    ].rename(
        columns={"TeamAbbreviation": "Team", "OffPoss": "team_possessions"}
    )
    players = players.merge(
        team_possessions,
        on=["GameId", "Team"],
        how="left",
        validate="many_to_one",
    )
    if players["team_possessions"].isna().any():
        raise AdapterContractError("player rows failed the team-game possession join")
    if (players["_game_date"] != players["_team_game_date"]).any():
        raise AdapterContractError("player and team-game date values disagree")

    canonical = pd.DataFrame(
        {
            "game_date": players["_game_date"],
            "game_id": players["GameId"].astype(str),
            "player_id": players["PlayerId"].astype(str),
            "player_name": players["PlayerName"],
            "team_abbreviation": players["Team"],
            "minutes": players["_minutes"],
            "off_poss": players["OffPoss"],
            "def_poss": players["DefPoss"],
            "total_poss": players["TotalPoss"],
            "team_possessions": players["team_possessions"],
            "points": players["Points"],
            "assists": players["Assists"],
            "turnovers": players["Turnovers"],
            "fga": players["FG2A"] + players["FG3A"],
            "fgm": players["FG2M"] + players["FG3M"],
            "fg3a": players["FG3A"],
            "fg3m": players["FG3M"],
            "fta": players["FTA"],
            "ftm": players["FtPoints"],
            "at_rim_fga": players["AtRimFGA"],
            "at_rim_fgm": players["AtRimFGM"],
            "rebounds": players["Rebounds"],
            "off_rebounds": players["OffRebounds"],
        }
    )
    if canonical.duplicated(["player_id", "game_id"]).any():
        raise AdapterContractError("canonical player game has duplicate player_id and game_id keys")

    quality = {
        "source_player_rows": int(len(player_raw)),
        "canonical_player_rows": int(len(canonical)),
        "excluded_nonparticipation_rows": excluded_nonparticipation,
        "source_player_ids": int(player_raw["PlayerId"].astype(str).nunique()),
        "canonical_player_ids": int(canonical["player_id"].nunique()),
        "source_game_ids": int(player_raw["GameId"].astype(str).nunique()),
        "canonical_game_ids": int(canonical["game_id"].nunique()),
        "source_max_game_date": canonical["game_date"].max().date().isoformat(),
        "team_join_matched": int(canonical["team_possessions"].notna().sum()),
        "team_join_expected": int(len(canonical)),
        "zero_filled_cells": zero_filled_cells,
    }
    return AdapterResult(player_game=canonical, quality=quality)


def audit_live_adapter(
    result: AdapterResult,
    *,
    assignments: pd.DataFrame,
    manifest: Mapping[str, Any],
    failures: List[Mapping[str, Any]],
    recent_end: str,
) -> Dict[str, Any]:
    """Evaluate freshness and reviewed-population coverage without enabling live scoring."""
    blockers: List[str] = []
    warnings: List[str] = []
    coverage_through = pd.to_datetime(manifest.get("coverage_through"), errors="coerce")
    recent_end_date = pd.Timestamp(recent_end)
    source_max = pd.Timestamp(result.quality["source_max_game_date"])
    if pd.isna(coverage_through) or coverage_through < recent_end_date:
        blockers.append("manifest coverage does not reach the configured recent window end")
    if pd.isna(coverage_through) or coverage_through.normalize() != source_max.normalize():
        blockers.append("manifest coverage does not match the maximum player-game date")

    assignment_ids = assignments["player_id"].astype(str)
    if assignment_ids.duplicated().any():
        blockers.append("reviewed role assignments contain duplicate player ids")
    source_only_assignments = sorted(
        player_id for player_id in set(assignment_ids) if player_id.startswith("espn:")
    )
    pbp_assignment_ids = {
        player_id for player_id in set(assignment_ids) if not player_id.startswith("espn:")
    }
    if source_only_assignments:
        warnings.append(
            f"{len(source_only_assignments)} reviewed ESPN-only role assignments are "
            "sample-suppressed until a reviewed PBPStats identity is available"
        )
    source_ids = set(result.player_game["player_id"].astype(str))
    missing_ids = sorted(pbp_assignment_ids - source_ids)
    if missing_ids:
        blockers.append(f"reviewed-role players missing from adapted data: {', '.join(missing_ids)}")

    failure_ids = {str(item.get("player_id")) for item in failures}
    manifest_failure_count = manifest.get("players", {}).get("failed_players")
    if manifest_failure_count is None or int(manifest_failure_count) != len(failures):
        blockers.append("manifest player failure count does not match the failure ledger")
    assigned_failures = sorted(pbp_assignment_ids & failure_ids)
    if assigned_failures:
        blockers.append(
            "reviewed-role player refresh failures: " + ", ".join(assigned_failures)
        )
    elif failures:
        warnings.append(
            f"{len(failures)} unrelated player refresh failures do not affect reviewed-role coverage"
        )

    return {
        "status": "blocked" if blockers else "review_ready",
        "blockers": blockers,
        "warnings": warnings,
        "candidate_coverage": {
            "matched": int(len(pbp_assignment_ids & source_ids)),
            "expected": int(len(pbp_assignment_ids)),
        },
        "source_only_assignments": source_only_assignments,
        "candidate_refresh_failures": assigned_failures,
        "global_refresh_failures": int(len(failures)),
        "manifest_refresh_failures": (
            None if manifest_failure_count is None else int(manifest_failure_count)
        ),
        "failure_ledger_rows": int(len(failures)),
        "recent_end": recent_end_date.date().isoformat(),
        "coverage_through": None if pd.isna(coverage_through) else coverage_through.date().isoformat(),
        "source_max_game_date": result.quality["source_max_game_date"],
    }
