"""Rolling-window / form helpers over the shared game layer.

Every analysis that wants "recent form", "last 10", trend, consistency, or home/away and
opponent-quality splits reads the per-game layer and calls these instead of re-deriving windows
from snapshot deltas of season totals. All transforms are pure pandas and leakage-safe: rolling
values as of a game include that game and earlier ones only, in game-date order.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


def _ordered(df: pd.DataFrame, entity_col: str, sort_col: str) -> pd.DataFrame:
    return df.sort_values([entity_col, sort_col, "game_id"]).reset_index(drop=True)


def add_rolling(
    df: pd.DataFrame,
    *,
    entity_col: str,
    metrics: Sequence[str],
    window: int,
    sort_col: str = "game_date",
    min_periods: int = 1,
) -> pd.DataFrame:
    """Add ``{metric}_r{window}`` trailing means (as of each game, current game included).

    Leakage-safe: rows are ordered by ``sort_col`` then ``game_id`` within each entity, and the
    rolling mean uses only the current and earlier games in that order.
    """
    out = _ordered(df, entity_col, sort_col)
    present = [m for m in metrics if m in out.columns]
    for metric in present:
        out[f"{metric}_r{window}"] = (
            out.groupby(entity_col)[metric]
            .transform(lambda s: s.rolling(window=window, min_periods=min_periods).mean())
        )
    return out


def latest_form(
    df: pd.DataFrame,
    *,
    entity_col: str,
    metrics: Sequence[str],
    windows: Sequence[int] = (5, 10),
    sort_col: str = "game_date",
) -> pd.DataFrame:
    """One row per entity: recent-window means, season mean, and recent-vs-season deltas.

    For each metric and window ``n``: ``{metric}_last{n}`` (mean of the most recent ``n`` games),
    ``{metric}_season`` (full-season mean), and ``{metric}_delta_last{n}`` (recent minus season).
    """
    out = _ordered(df, entity_col, sort_col)
    present = [m for m in metrics if m in out.columns]
    records = []
    for entity, group in out.groupby(entity_col, sort=False):
        record: Dict[str, object] = {entity_col: entity, "games_played": int(len(group))}
        for metric in present:
            series = group[metric].dropna()
            season_mean = float(series.mean()) if not series.empty else np.nan
            record[f"{metric}_season"] = season_mean
            for n in windows:
                recent = series.tail(n)
                recent_mean = float(recent.mean()) if not recent.empty else np.nan
                record[f"{metric}_last{n}"] = recent_mean
                record[f"{metric}_delta_last{n}"] = (
                    recent_mean - season_mean
                    if not (np.isnan(recent_mean) or np.isnan(season_mean))
                    else np.nan
                )
        records.append(record)
    return pd.DataFrame(records)


def trend_slope(
    df: pd.DataFrame,
    *,
    entity_col: str,
    metrics: Sequence[str],
    sort_col: str = "game_date",
    min_games: int = 3,
) -> pd.DataFrame:
    """Per-entity least-squares slope of each metric against game index (a trajectory rate).

    Slope is per game. Entities with fewer than ``min_games`` valid points get NaN rather than an
    unstable fit.
    """
    out = _ordered(df, entity_col, sort_col)
    present = [m for m in metrics if m in out.columns]
    records = []
    for entity, group in out.groupby(entity_col, sort=False):
        record: Dict[str, object] = {entity_col: entity}
        for metric in present:
            series = group[metric].reset_index(drop=True).dropna()
            if len(series) >= min_games:
                x = np.arange(len(series), dtype=float)
                record[f"{metric}_slope"] = float(np.polyfit(x, series.to_numpy(dtype=float), 1)[0])
            else:
                record[f"{metric}_slope"] = np.nan
        records.append(record)
    return pd.DataFrame(records)


def consistency(
    df: pd.DataFrame,
    *,
    entity_col: str,
    metrics: Sequence[str],
    min_games: int = 3,
) -> pd.DataFrame:
    """Per-entity game-to-game volatility: standard deviation and coefficient of variation."""
    present = [m for m in metrics if m in df.columns]
    records = []
    for entity, group in df.groupby(entity_col, sort=False):
        record: Dict[str, object] = {entity_col: entity}
        for metric in present:
            series = group[metric].dropna()
            if len(series) >= min_games:
                std = float(series.std(ddof=1))
                mean = float(series.mean())
                record[f"{metric}_std"] = std
                record[f"{metric}_cv"] = (std / abs(mean)) if mean not in (0, 0.0) else np.nan
            else:
                record[f"{metric}_std"] = np.nan
                record[f"{metric}_cv"] = np.nan
        records.append(record)
    return pd.DataFrame(records)


def split_means(
    df: pd.DataFrame,
    *,
    entity_col: str,
    metrics: Sequence[str],
    by: str,
) -> pd.DataFrame:
    """Long-form per-entity means of each metric within each value of a grouping column.

    E.g. ``by="is_home"`` for home/away splits, or ``by="opponent_tier"`` after
    :func:`attach_opponent_strength`. Returns columns ``[entity_col, by, "games", metric...]``.
    """
    present = [m for m in metrics if m in df.columns]
    grouped = (
        df.groupby([entity_col, by], dropna=False)
        .agg(games=(entity_col, "size"), **{m: (m, "mean") for m in present})
        .reset_index()
    )
    return grouped


def attach_opponent_strength(
    df: pd.DataFrame,
    team_strength: Mapping[str, float],
    *,
    opponent_col: str = "opponent_team_id",
    threshold: float = 0.5,
) -> pd.DataFrame:
    """Add ``opponent_win_pct`` and a two-level ``opponent_tier`` (``at_or_above``/``below``).

    ``team_strength`` maps team id -> a strength value (e.g. season win pct). Opponents absent
    from the map get NaN strength and a null tier, so an incomplete map never mislabels a split.
    """
    out = df.copy()
    strength = {str(k): float(v) for k, v in team_strength.items()}
    win_pct = out[opponent_col].map(lambda v: strength.get(str(v), np.nan))
    out["opponent_win_pct"] = win_pct

    def _tier(value: float) -> Optional[str]:
        if pd.isna(value):
            return None
        return "at_or_above" if value >= threshold else "below"

    out["opponent_tier"] = win_pct.map(_tier)
    return out
