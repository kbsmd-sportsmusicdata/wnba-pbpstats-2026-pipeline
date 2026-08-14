"""Split a team's change in offensive rating into design, conversion and possession parts.

The question behind an identity shift is whether it helped. Offensive rating alone cannot
answer that, because a team can score more simply by making shots it was already taking.
This module separates the part of the change that came from *taking better shots* -- a
coaching decision that tends to persist -- from the part that came from *making the same
shots more often*, which is largely variance and tends to regress.

The identity used is exact:

    off_rating = 200 * (Q + M) * A + 100 * F

where ``Q`` is expected eFG% from shot location (PBPStats shot quality), ``M`` is the
shot-making residual (actual eFG% minus ``Q``), ``A`` is field-goal attempts per
possession, and ``F`` is free-throw points per possession. Each factor's contribution is
attributed with the symmetric two-factor rule ``d(XY) = mean(X)*dY + mean(Y)*dX``, which
reconciles to the total change exactly rather than leaving an interaction term stranded.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from snapshot_window_panel.panel import safe_divide

from .style import BASELINE, RECENT


def _factors(row: pd.Series) -> Dict[str, float]:
    fga = pd.to_numeric(row.get("fga"), errors="coerce")
    off_poss = pd.to_numeric(row.get("off_poss"), errors="coerce")
    points = pd.to_numeric(row.get("points"), errors="coerce")
    ft_points = pd.to_numeric(row.get("ft_points"), errors="coerce")
    efg = pd.to_numeric(row.get("efg_pct"), errors="coerce")
    quality = pd.to_numeric(row.get("shotquality_pbp_avg"), errors="coerce")

    return {
        "shot_quality": float(quality) if pd.notna(quality) else np.nan,
        "shot_making": float(efg - quality) if pd.notna(efg) and pd.notna(quality) else np.nan,
        "shot_rate": float(safe_divide(fga, off_poss)),
        "ft_points_rate": float(safe_divide(ft_points, off_poss)),
        "efg_pct": float(efg) if pd.notna(efg) else np.nan,
        "off_rating": float(safe_divide(points, off_poss) * 100),
    }


def decompose_offense(baseline: pd.Series, recent: pd.Series) -> Dict[str, float]:
    """Attribute the change in offensive rating to shot quality, shot making, shot rate and free throws."""
    start, end = _factors(baseline), _factors(recent)

    quality_mean = np.mean([start["shot_quality"], end["shot_quality"]])
    making_mean = np.mean([start["shot_making"], end["shot_making"]])
    rate_mean = np.mean([start["shot_rate"], end["shot_rate"]])

    delta_quality = end["shot_quality"] - start["shot_quality"]
    delta_making = end["shot_making"] - start["shot_making"]
    delta_rate = end["shot_rate"] - start["shot_rate"]
    delta_ft = end["ft_points_rate"] - start["ft_points_rate"]

    quality_effect = 200 * rate_mean * delta_quality
    making_effect = 200 * rate_mean * delta_making
    rate_effect = 200 * (quality_mean + making_mean) * delta_rate
    ft_effect = 100 * delta_ft

    observed = end["off_rating"] - start["off_rating"]
    modelled = quality_effect + making_effect + rate_effect + ft_effect

    return {
        "baseline_off_rating": start["off_rating"],
        "recent_off_rating": end["off_rating"],
        "off_rating_delta": observed,
        "baseline_shot_quality": start["shot_quality"],
        "recent_shot_quality": end["shot_quality"],
        "shot_quality_delta": delta_quality,
        "baseline_shot_making": start["shot_making"],
        "recent_shot_making": end["shot_making"],
        "shot_making_delta": delta_making,
        "baseline_shot_rate": start["shot_rate"],
        "recent_shot_rate": end["shot_rate"],
        "shot_rate_delta": delta_rate,
        "baseline_ft_points_rate": start["ft_points_rate"],
        "recent_ft_points_rate": end["ft_points_rate"],
        "ft_points_rate_delta": delta_ft,
        "shot_quality_effect": quality_effect,
        "shot_making_effect": making_effect,
        "shot_rate_effect": rate_effect,
        "free_throw_effect": ft_effect,
        "modelled_off_rating_delta": modelled,
        "decomposition_residual": observed - modelled,
    }


def classify_nature(record: Dict[str, float], *, minimum_effect: float = 1.0) -> str:
    """Name the dominant driver of the offensive change.

    Design-led changes come from the shots a team chooses to take and generally hold.
    Conversion-led changes come from making the same shots at a different rate and
    generally do not.
    """
    effects = {
        "Design-led (structural)": record.get("shot_quality_effect"),
        "Conversion-led (cosmetic)": record.get("shot_making_effect"),
        "Possession-led": (record.get("shot_rate_effect") or 0) + (record.get("free_throw_effect") or 0),
    }
    usable = {name: value for name, value in effects.items() if pd.notna(value)}
    if not usable:
        return "Unknown"

    dominant = max(usable, key=lambda name: abs(usable[name]))
    if abs(usable[dominant]) < minimum_effect:
        return "No material offensive change"
    return dominant


def build_decomposition_table(period_frame: pd.DataFrame) -> pd.DataFrame:
    """Per-team offensive decomposition between the baseline and recent periods."""
    baseline = period_frame[period_frame["period"] == BASELINE].set_index("team_abbreviation")
    recent = period_frame[period_frame["period"] == RECENT].set_index("team_abbreviation")

    rows: List[Dict] = []
    for team in baseline.index:
        if team not in recent.index:
            continue
        record = decompose_offense(baseline.loc[team], recent.loc[team])
        record["team_abbreviation"] = team
        record["shift_nature"] = classify_nature(record)
        baseline_def = pd.to_numeric(baseline.loc[team, "def_rating"], errors="coerce")
        recent_def = pd.to_numeric(recent.loc[team, "def_rating"], errors="coerce")
        record["def_rating_delta"] = recent_def - baseline_def
        record["net_rating_delta"] = record["off_rating_delta"] - record["def_rating_delta"]
        rows.append(record)

    table = pd.DataFrame(rows)
    if table.empty:
        return table
    leading = ["team_abbreviation", "shift_nature", "off_rating_delta", "def_rating_delta", "net_rating_delta"]
    return table[leading + [c for c in table.columns if c not in leading]].sort_values(
        "off_rating_delta", ascending=False
    ).reset_index(drop=True)
