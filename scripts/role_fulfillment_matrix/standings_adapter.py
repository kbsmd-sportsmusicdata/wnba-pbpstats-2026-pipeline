"""Adapter from forecast standings output to the RFM team contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

import pandas as pd


ESPN_TO_PBPSTATS_TEAM = {
    "GS": "GSV",
    "LV": "LVA",
    "NY": "NYL",
    "WSH": "WAS",
    "POR": "PDX",
    "LA": "LAS",
}


class StandingsAdapterError(ValueError):
    """Raised when forecast standings cannot support contender selection."""


@dataclass
class StandingsAdapterResult:
    standings: pd.DataFrame
    quality: Dict[str, Any]


def normalize_team_abbreviation(value: Any) -> str:
    code = str(value).strip().upper()
    return ESPN_TO_PBPSTATS_TEAM.get(code, code)


def adapt_forecast_standings(
    standings: pd.DataFrame,
    manifest: Mapping[str, Any],
) -> StandingsAdapterResult:
    """Carry the forecast cutoff and normalize team codes without using dashboard code."""
    required = {"team_id", "team_abbreviation", "current_rank"}
    missing = sorted(required - set(standings.columns))
    if missing:
        raise StandingsAdapterError(
            "forecast standings missing required columns: " + ", ".join(missing)
        )
    cutoff = pd.to_datetime(manifest.get("cutoff_date"), errors="coerce")
    if pd.isna(cutoff):
        raise StandingsAdapterError("forecast manifest has an invalid cutoff_date")

    canonical = standings[["team_id", "team_abbreviation", "current_rank"]].copy()
    original_codes = canonical["team_abbreviation"].astype(str).str.strip().str.upper()
    canonical["team_abbreviation"] = original_codes.map(normalize_team_abbreviation)
    canonical["current_rank"] = pd.to_numeric(canonical["current_rank"], errors="coerce")
    if canonical["current_rank"].isna().any():
        raise StandingsAdapterError("forecast standings contains invalid current_rank values")
    if canonical["team_abbreviation"].duplicated().any():
        raise StandingsAdapterError("normalized forecast standings contains duplicate teams")
    canonical["cutoff_date"] = cutoff.date().isoformat()
    return StandingsAdapterResult(
        standings=canonical,
        quality={
            "teams": int(len(canonical)),
            "cutoff_date": cutoff.date().isoformat(),
            "normalized_team_codes": int(
                (original_codes != canonical["team_abbreviation"]).sum()
            ),
        },
    )
