"""Deterministic cutoff and window policy for Role Fulfillment Matrix live reviews."""

from __future__ import annotations

from typing import Any, Dict, Mapping

import pandas as pd


def validate_locked_parity_windows(configured: Mapping[str, Any] | None) -> Dict[str, str]:
    """Normalize and validate the fixed windows paired with locked parity inputs."""
    required = ("baseline_start", "baseline_end", "recent_start", "recent_end")
    if not isinstance(configured, Mapping):
        raise ValueError("locked_parity_inputs requires explicit locked_parity_windows")
    missing = [key for key in required if not configured.get(key)]
    if missing:
        raise ValueError(
            "locked_parity_windows is missing required fields: " + ", ".join(missing)
        )
    windows = {
        key: pd.Timestamp(configured[key]).date().isoformat()
        for key in required
    }
    ordered = [pd.Timestamp(windows[key]) for key in required]
    if not (ordered[0] <= ordered[1] < ordered[2] <= ordered[3]):
        raise ValueError(
            "locked_parity_windows must be ordered baseline_start through recent_end"
        )
    return windows


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
