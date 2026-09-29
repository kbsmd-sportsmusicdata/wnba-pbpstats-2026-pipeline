"""Shared WNBA 2026 injury / availability report.

Normalizes the raw ESPN injury feed into a current-availability view that every downstream
analysis can join against, and bridges ESPN ``athlete_id`` to the pbpstats ``player_id`` the rest
of the pipeline runs on.
"""

from .report import (
    ESPN_TEAM_ID_TO_ABBREVIATION,
    TEAM_ABBREVIATION_BY_DISPLAY,
    attach_player_ids,
    build_current_report,
    build_team_availability,
    classify_absence_reason,
    frees_rotation_minutes,
    latest_as_of,
    mentions_season_ending,
    normalize_availability_status,
    normalize_injuries,
    normalize_player_name,
)

__all__ = [
    "ESPN_TEAM_ID_TO_ABBREVIATION",
    "TEAM_ABBREVIATION_BY_DISPLAY",
    "attach_player_ids",
    "build_current_report",
    "build_team_availability",
    "classify_absence_reason",
    "frees_rotation_minutes",
    "latest_as_of",
    "mentions_season_ending",
    "normalize_availability_status",
    "normalize_injuries",
    "normalize_player_name",
]
