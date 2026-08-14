"""Per-player trend over the snapshot window panel.

The question is whether a player is getting better *now*, close enough to the playoffs to
matter. A raw slope over ten windows is mostly noise, so every slope here is shrunk toward
zero in proportion to how little data supports it: a player with four windows keeps far
less of their apparent trend than one with twelve.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import pandas as pd


def weighted_slope(values: Sequence[float], weights: Sequence[float]) -> float:
    """Least-squares slope of `values` against their order, weighted by sample size.

    Windows carry different numbers of possessions, so a 40-possession appearance should
    not move the trend as much as a 90-possession one.
    """
    y = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    usable = np.isfinite(y) & np.isfinite(w) & (w > 0)
    if usable.sum() < 2:
        return np.nan

    y, w = y[usable], w[usable]
    x = np.arange(len(y), dtype=float)
    mean_x = np.average(x, weights=w)
    mean_y = np.average(y, weights=w)
    variance = np.sum(w * (x - mean_x) ** 2)
    if variance <= 0:
        return np.nan
    return float(np.sum(w * (x - mean_x) * (y - mean_y)) / variance)


def shrink(slope: float, observations: int, constant: float) -> float:
    """Pull a slope toward zero when few windows support it."""
    if not np.isfinite(slope) or observations <= 0:
        return np.nan
    return float(slope * observations / (observations + constant))


def build_player_trajectories(
    panel: pd.DataFrame,
    *,
    metrics: Sequence[str],
    recent_windows: int,
    min_windows: int,
    shrinkage_constant: float,
) -> pd.DataFrame:
    """One row per player: shrunk slope and recent level for each tracked metric."""
    columns = ["player_id", "windows_used", "recent_possessions"]
    if panel.empty:
        return pd.DataFrame(columns=columns)

    body = panel[~panel["is_baseline_block"].astype(bool)] if "is_baseline_block" in panel.columns else panel
    rows: List[Dict] = []
    for player, group in body.groupby("entity_id", sort=True):
        ordered = group.sort_values("window_index").tail(recent_windows)
        if len(ordered) < min_windows:
            continue

        weights = pd.to_numeric(ordered.get("total_poss_for_rates"), errors="coerce")
        if weights.isna().all():
            weights = pd.to_numeric(ordered.get("off_poss"), errors="coerce")
        weights = weights.fillna(0.0)

        record: Dict = {
            "player_id": player,
            "windows_used": int(len(ordered)),
            "recent_possessions": float(weights.sum()),
        }
        for metric in metrics:
            if metric not in ordered.columns:
                continue
            values = pd.to_numeric(ordered[metric], errors="coerce")
            slope = weighted_slope(values.to_numpy(), weights.to_numpy())
            record[f"{metric}_slope"] = shrink(slope, len(ordered), shrinkage_constant)
            record[f"{metric}_recent"] = (
                float(np.average(values.dropna(), weights=weights[values.notna()]))
                if values.notna().any() and weights[values.notna()].sum() > 0
                else np.nan
            )
            record[f"{metric}_volatility"] = float(values.std(ddof=1)) if values.notna().sum() > 1 else np.nan
        rows.append(record)

    return pd.DataFrame(rows)


def role_expansion(trajectories: pd.DataFrame) -> pd.Series:
    """Rising share of team possessions played -- the leading indicator of a bigger role.

    Production follows opportunity, so a climbing on-court share tends to precede a
    climbing box score rather than the other way round.
    """
    if trajectories.empty or "on_court_poss_share_slope" not in trajectories.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(trajectories["on_court_poss_share_slope"], errors="coerce")
