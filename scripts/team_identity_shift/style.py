"""Period aggregation and the team style vector.

A team's identity is expressed as a vector of possession-normalized playing-style rates.
Period rates are always recomputed from summed window totals rather than averaged across
windows, so a 60-possession window does not carry the same weight as a 90-possession one.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from snapshot_window_panel.derived import build_team_window_metrics
from snapshot_window_panel.panel import (
    NEGATIVE_TOLERANCE,
    classify_additive_columns,
    safe_divide,
)


#: SportsDataverse/ESPN abbreviations mapped onto the PBPStats set used by the panel.
TEAM_ABBR_ALIASES = {
    "GS": "GSV",
    "GSV": "GSV",
    "LA": "LAS",
    "LAS": "LAS",
    "LV": "LVA",
    "LVA": "LVA",
    "NY": "NYL",
    "NYL": "NYL",
    "PHO": "PHX",
    "PHX": "PHX",
    "POR": "PDX",
    "PDX": "PDX",
    "WSH": "WAS",
    "WAS": "WAS",
}

BASELINE = "baseline"
RECENT = "recent"


def team_key(value) -> str:
    raw = str(value).strip().upper()
    return TEAM_ABBR_ALIASES.get(raw, raw)


def weighted_average_columns(panel: pd.DataFrame) -> Dict[str, str]:
    """Map each reconstructed average column to the weight column shipped beside it."""
    return {
        column[: -len("_weight")]: column
        for column in panel.columns
        if column.endswith("_weight") and column[: -len("_weight")] in panel.columns
    }


def aggregate_period(windows: pd.DataFrame, additive_columns: Sequence[str]) -> pd.Series:
    """Collapse a set of windows into one row of totals plus weight-averaged rates.

    Counting columns are summed. Reconstructed averages cannot be summed, so they are
    re-averaged against the weight column the panel emits for each one.
    """
    totals = windows[list(additive_columns)].apply(pd.to_numeric, errors="coerce").sum(min_count=1)

    for column, weight_column in weighted_average_columns(windows).items():
        values = pd.to_numeric(windows[column], errors="coerce")
        weights = pd.to_numeric(windows[weight_column], errors="coerce")
        usable = values.notna() & weights.notna() & (weights > 0)
        totals[column] = (
            float((values[usable] * weights[usable]).sum() / weights[usable].sum())
            if usable.any()
            else np.nan
        )
        totals[weight_column] = float(weights[usable].sum()) if usable.any() else np.nan

    return totals


def period_metrics(windows: pd.DataFrame, additive_columns: Sequence[str]) -> pd.Series:
    """Aggregate a period and recompute every rate from its totals."""
    totals = aggregate_period(windows, additive_columns)
    frame = pd.DataFrame([totals])
    frame["games_in_window"] = pd.to_numeric(windows["games_in_window"], errors="coerce").sum()
    return build_team_window_metrics(frame).iloc[0]


def assign_periods(windows: pd.DataFrame, *, recent_games: int) -> pd.DataFrame:
    """Split a team's windows into a recent block and everything before it.

    Windows are walked backwards accumulating games until the recent-games target is met,
    so the split lands on a window boundary rather than cutting one in half.
    """
    ordered = windows.sort_values("window_index").copy()
    games = pd.to_numeric(ordered["games_in_window"], errors="coerce").fillna(0)
    games_from_end = games[::-1].cumsum()[::-1]
    # A window joins the recent block when the games at or after it have not yet met the
    # target, which keeps the block at the smallest size that reaches recent_games.
    ordered["period"] = np.where(games_from_end - games < recent_games, RECENT, BASELINE)
    return ordered


def build_style_frame(
    panel: pd.DataFrame,
    *,
    dimensions: Sequence[str],
    recent_games: int,
    min_baseline_games: int,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Compute per-period style vectors and season style vectors for every team.

    Returns the long per-period frame, the season frame used for league scaling, and the
    list of teams that lacked enough baseline games to evaluate.
    """
    additive = [
        column
        for column in classify_additive_columns(panel)
        if column not in {"window_index", "cumulative_games_played", "snapshot_span_days"}
    ]

    period_rows: List[Dict] = []
    season_rows: List[Dict] = []
    skipped: List[str] = []

    for team, group in panel.groupby("team_abbreviation", sort=True):
        ordered = assign_periods(group, recent_games=recent_games)
        baseline = ordered[ordered["period"] == BASELINE]
        recent = ordered[ordered["period"] == RECENT]
        baseline_games = pd.to_numeric(baseline["games_in_window"], errors="coerce").sum()
        if baseline.empty or baseline_games < min_baseline_games:
            skipped.append(team)
            continue

        season = period_metrics(ordered, additive)
        season_rows.append({"team_abbreviation": team, **{d: season.get(d) for d in dimensions},
                            "games": float(pd.to_numeric(ordered["games_in_window"], errors="coerce").sum()),
                            "net_rating": season.get("net_rating"),
                            "off_rating": season.get("off_rating"),
                            "def_rating": season.get("def_rating")})

        for label, block in ((BASELINE, baseline), (RECENT, recent)):
            metrics = period_metrics(block, additive)
            # The whole metric row is carried, not just the style dimensions: the offensive
            # decomposition needs the underlying totals (FGA, free-throw points, shot
            # quality) recomputed on the same period aggregation.
            period_rows.append(
                {
                    **metrics.to_dict(),
                    "team_abbreviation": team,
                    "period": label,
                    "games": float(pd.to_numeric(block["games_in_window"], errors="coerce").sum()),
                    "first_game_date": block["covered_game_date_start"].min(),
                    "last_game_date": block["covered_game_date_end"].max(),
                }
            )

    return pd.DataFrame(period_rows), pd.DataFrame(season_rows), skipped


def league_scales(season_frame: pd.DataFrame, dimensions: Sequence[str]) -> pd.Series:
    """Scale each dimension by how much teams differ from each other across the season.

    Using cross-team spread rather than game-to-game spread makes a shift of 1.0 mean
    "moved by one league standard deviation of team-to-team difference" -- the natural
    unit for a question about identity.
    """
    scales = {}
    for dimension in dimensions:
        values = pd.to_numeric(season_frame.get(dimension), errors="coerce").dropna()
        deviation = float(values.std(ddof=1)) if len(values) > 1 else np.nan
        scales[dimension] = deviation if deviation and deviation > NEGATIVE_TOLERANCE else np.nan
    return pd.Series(scales)


def dimension_deltas(
    period_frame: pd.DataFrame,
    scales: pd.Series,
    dimensions: Sequence[str],
) -> pd.DataFrame:
    """Long frame of per-dimension movement, in raw and league-scaled units."""
    baseline = period_frame[period_frame["period"] == BASELINE].set_index("team_abbreviation")
    recent = period_frame[period_frame["period"] == RECENT].set_index("team_abbreviation")

    rows = []
    for team in baseline.index:
        if team not in recent.index:
            continue
        for dimension in dimensions:
            base_value = pd.to_numeric(baseline.loc[team, dimension], errors="coerce")
            recent_value = pd.to_numeric(recent.loc[team, dimension], errors="coerce")
            delta = recent_value - base_value
            scale = scales.get(dimension, np.nan)
            rows.append(
                {
                    "team_abbreviation": team,
                    "dimension": dimension,
                    "baseline_value": base_value,
                    "recent_value": recent_value,
                    "delta": delta,
                    "league_scale": scale,
                    "z_delta": float(safe_divide(delta, scale)) if pd.notna(scale) else np.nan,
                }
            )
    return pd.DataFrame(rows)
