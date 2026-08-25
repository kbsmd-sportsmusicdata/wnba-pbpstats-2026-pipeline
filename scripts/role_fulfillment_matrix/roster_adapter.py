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
    """Build the current ESPN roster universe and annotate eligibility coverage."""
    core_required = {
        "athlete_id",
        "full_name",
        "current_team_id",
        "position_name",
        "position_abbreviation",
        "active",
        "status_type",
    }
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

    cutoff = pd.to_datetime(cutoff_date, errors="coerce")
    if pd.isna(cutoff):
        raise RosterAdapterError("roster source_as_of and cutoff_date must be valid dates")
    if not eligibility["review_status"].eq("reviewed").all():
        raise RosterAdapterError("eligibility contains rows that are not reviewed")

    core = player_core.copy()
    if "_roster_source_as_of" in core.columns:
        source_dates = pd.to_datetime(core["_roster_source_as_of"], errors="coerce")
        if source_dates.isna().any():
            raise RosterAdapterError(
                "each contributing roster input must have a valid source_as_of date"
            )
        core["_roster_source_as_of"] = source_dates.dt.normalize()
        oldest_source_date = source_dates.min().normalize()
        newest_source_date = source_dates.max().normalize()
        if oldest_source_date < cutoff.normalize():
            raise RosterAdapterError(
                "oldest contributing roster snapshot is older than the standings cutoff"
            )
    else:
        source_date = pd.to_datetime(source_as_of, errors="coerce")
        if pd.isna(source_date):
            raise RosterAdapterError(
                "roster source_as_of and cutoff_date must be valid dates"
            )
        source_date = source_date.normalize()
        if source_date < cutoff.normalize():
            raise RosterAdapterError("roster snapshot is older than the standings cutoff")
        core["_roster_source_as_of"] = source_date
        oldest_source_date = source_date
        newest_source_date = source_date
    missing_position = (
        core["position_name"].isna()
        | core["position_name"].astype(str).str.strip().eq("")
        | core["position_abbreviation"].isna()
        | core["position_abbreviation"].astype(str).str.strip().eq("")
    )
    if missing_position.any():
        names = core.loc[missing_position, "full_name"].astype(str).tolist()
        raise RosterAdapterError("player core missing position context: " + ", ".join(names))
    core["position_name"] = core["position_name"].astype(str).str.strip()
    core["position_abbreviation"] = (
        core["position_abbreviation"].astype(str).str.strip().str.upper()
    )
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

    missing_reviewed = reviewed.loc[
        ~reviewed["_espn_athlete_id"].isin(set(core["_espn_athlete_id"])),
        "player_name",
    ].tolist()
    if missing_reviewed:
        raise RosterAdapterError(
            "reviewed ESPN identities missing from player core: "
            + ", ".join(missing_reviewed)
        )

    joined = core[
        [
            "_espn_athlete_id",
            "full_name",
            "current_team_id",
            "position_name",
            "position_abbreviation",
            "active",
            "status_type",
            "_roster_source_as_of",
        ]
    ].merge(
        reviewed,
        on="_espn_athlete_id",
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    eligibility_missing = joined["_merge"].eq("left_only")
    joined["eligibility_coverage_status"] = "reviewed"
    joined.loc[eligibility_missing, "eligibility_coverage_status"] = "missing"
    joined.loc[eligibility_missing, "player_id"] = (
        "espn:" + joined.loc[eligibility_missing, "_espn_athlete_id"]
    )
    joined.loc[eligibility_missing, "player_name"] = joined.loc[
        eligibility_missing, "full_name"
    ]
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
        [
            "player_id",
            "player_name",
            "_team_abbreviation",
            "position_name",
            "position_abbreviation",
            "active",
            "status_type",
            "eligibility_coverage_status",
        ]
    ].rename(columns={"_team_abbreviation": "team_abbreviation"})
    roster["player_id"] = roster["player_id"].astype(str)
    roster["source_as_of"] = joined["_roster_source_as_of"].dt.strftime("%Y-%m-%d")
    return RosterAdapterResult(
        roster=roster,
        quality={
            "current_core_players": int(len(roster)),
            "reviewed_players_matched": int((~eligibility_missing).sum()),
            "eligibility_players_unmatched": int(eligibility_missing.sum()),
            "unmatched_eligibility_players": sorted(
                joined.loc[eligibility_missing, "player_name"].tolist()
            ),
            "active_players": int(roster["active"].sum()),
            "inactive_players": int((roster["status_type"] == "inactive").sum()),
            "free_agents": int((roster["status_type"] == "free-agent").sum()),
            "source_as_of": oldest_source_date.date().isoformat(),
            "oldest_source_as_of": oldest_source_date.date().isoformat(),
            "newest_source_as_of": newest_source_date.date().isoformat(),
            "source_snapshot_count": int(
                joined["_roster_source_as_of"].nunique()
            ),
        },
    )
