"""Deterministic cutoff and window policy for Role Fulfillment Matrix live reviews."""

from __future__ import annotations

from typing import Dict

import pandas as pd


def derive_analysis_windows(
    cutoff_date: str,
    *,
    recent_days: int,
    baseline_days: int,
    lag_days: int,
) -> Dict[str, str]:
    """Return adjacent baseline/recent windows ending before the analysis cutoff."""
    if recent_days <= 0 or baseline_days <= 0:
        raise ValueError("recent_days and baseline_days must be positive")
    if lag_days < 0:
        raise ValueError("lag_days must be nonnegative")
    cutoff = pd.to_datetime(cutoff_date, errors="coerce")
    if pd.isna(cutoff):
        raise ValueError(f"invalid cutoff_date: {cutoff_date}")

    recent_end = cutoff.normalize() - pd.Timedelta(days=lag_days)
    recent_start = recent_end - pd.Timedelta(days=recent_days - 1)
    baseline_end = recent_start - pd.Timedelta(days=1)
    baseline_start = baseline_end - pd.Timedelta(days=baseline_days - 1)
    return {
        "baseline_start": baseline_start.date().isoformat(),
        "baseline_end": baseline_end.date().isoformat(),
        "recent_start": recent_start.date().isoformat(),
        "recent_end": recent_end.date().isoformat(),
    }
