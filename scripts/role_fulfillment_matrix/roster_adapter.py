"""Reviewed ESPN roster overlay for current RFM affiliation and activity state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd

from .standings_adapter import normalize_team_abbreviation


class RosterAdapterError(ValueError):
    """Raised when the roster overlay is stale, incomplete, or ambiguous."""


@dataclass
class RosterAdapterResult:
    roster: pd.DataFrame
    quality: Dict[str, Any]


def _identity(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def adapt_espn_roster(
    player_core: pd.DataFrame,
    eligibility: pd.DataFrame,
    raw_standings: pd.DataFrame,
    *,
    source_as_of: str,
    cutoff_date: str,
) -> RosterAdapterResult:
    """Join reviewed ESPN identities to current status without changing eligibility facts."""
    core_required = {"athlete_id", "current_team_id", "active", "status_type"}
    eligibility_required = {
        "player_id",
        "player_name",
        "espn_athlete_id",
        "review_status",
    }
    standings_required = {"team_id", "team_abbreviation"}
    for label, frame, required in (
        ("player core", player_core, core_required),
        ("eligibility", eligibility, eligibility_required),
        ("standings", raw_standings, standings_required),
    ):
        missing = sorted(required - set(frame.columns))
        if missing:
            raise RosterAdapterError(f"{label} missing required columns: {', '.join(missing)}")

    source_date = pd.to_datetime(source_as_of, errors="coerce")
    cutoff = pd.to_datetime(cutoff_date, errors="coerce")
    if pd.isna(source_date) or pd.isna(cutoff):
        raise RosterAdapterError("roster source_as_of and cutoff_date must be valid dates")
    if source_date.normalize() < cutoff.normalize():
        raise RosterAdapterError("roster snapshot is older than the standings cutoff")
    if not eligibility["review_status"].eq("reviewed").all():
        raise RosterAdapterError("eligibility contains rows that are not reviewed")

    core = player_core.copy()
    core["_espn_athlete_id"] = core["athlete_id"].map(_identity)
    if core["_espn_athlete_id"].duplicated().any():
        raise RosterAdapterError("player core contains duplicate athlete_id values")
    reviewed = eligibility[
        ["player_id", "player_name", "espn_athlete_id", "review_status"]
    ].copy()
    reviewed["_espn_athlete_id"] = reviewed["espn_athlete_id"].map(_identity)
    if reviewed["player_id"].astype(str).duplicated().any():
        raise RosterAdapterError("eligibility contains duplicate player_id values")

    teams = raw_standings[["team_id", "team_abbreviation"]].copy()
    teams["_current_team_id"] = teams["team_id"].map(_identity)
    teams["_team_abbreviation"] = teams["team_abbreviation"].map(
        normalize_team_abbreviation
    )
    if teams["_current_team_id"].duplicated().any():
        raise RosterAdapterError("standings contains duplicate team_id values")

    joined = reviewed.merge(
        core[["_espn_athlete_id", "current_team_id", "active", "status_type"]],
        on="_espn_athlete_id",
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not joined["_merge"].eq("both").all():
        missing_players = joined.loc[joined["_merge"] != "both", "player_name"].tolist()
        raise RosterAdapterError(
            "reviewed ESPN identities missing from player core: " + ", ".join(missing_players)
        )
    joined["_current_team_id"] = joined["current_team_id"].map(_identity)
    joined = joined.merge(
        teams[["_current_team_id", "_team_abbreviation"]],
        on="_current_team_id",
        how="left",
        validate="many_to_one",
    )
    joined["active"] = joined["active"].map(_as_bool)
    joined["status_type"] = joined["status_type"].astype(str).str.strip().str.lower()
    missing_active_team = joined["active"] & joined["_team_abbreviation"].isna()
    if missing_active_team.any():
        names = joined.loc[missing_active_team, "player_name"].tolist()
        raise RosterAdapterError(
            "active roster players have no current team mapping: " + ", ".join(names)
        )

    roster = joined[
        ["player_id", "player_name", "_team_abbreviation", "active", "status_type"]
    ].rename(columns={"_team_abbreviation": "team_abbreviation"})
    roster["player_id"] = roster["player_id"].astype(str)
    roster["source_as_of"] = source_date.date().isoformat()
    return RosterAdapterResult(
        roster=roster,
        quality={
            "reviewed_players_matched": int(len(roster)),
            "active_players": int(roster["active"].sum()),
            "inactive_players": int((roster["status_type"] == "inactive").sum()),
            "free_agents": int((roster["status_type"] == "free-agent").sum()),
            "source_as_of": source_date.date().isoformat(),
        },
    )
