"""Identity shift scoring and its permutation null.

A raw before/after difference always looks like something. With roughly two dozen windows
per team, most of it is week-to-week noise. Every observed shift is therefore compared
against the distribution of shifts the same team's own games produce when their order is
scrambled, which controls for both a team's volatility and its sample size.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from snapshot_window_panel.derived import build_team_window_metrics

from .style import BASELINE, RECENT


def style_from_totals(totals: pd.DataFrame, dimensions: Sequence[str]) -> pd.DataFrame:
    """Compute style dimensions from summed window totals.

    Deliberately routed through the same metric builder the panel uses, so period-level
    and window-level definitions cannot drift apart.
    """
    metrics = build_team_window_metrics(totals)
    return metrics[[dimension for dimension in dimensions if dimension in metrics.columns]]


def shift_score(z_deltas: np.ndarray) -> np.ndarray:
    """Total league-scaled movement across dimensions (L1), ignoring missing dimensions."""
    return np.nansum(np.abs(z_deltas), axis=-1)


def _totals_matrix(windows: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    return windows[list(columns)].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=float)


def _recent_mask(games: np.ndarray, recent_games: float) -> np.ndarray:
    """Mark the trailing windows that together reach the recent-games target."""
    games_from_end = np.cumsum(games[::-1])[::-1]
    return (games_from_end - games) < recent_games


def permutation_null(
    windows: pd.DataFrame,
    *,
    dimensions: Sequence[str],
    scales: pd.Series,
    totals_columns: Sequence[str],
    recent_games: float,
    iterations: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Shift scores produced by scrambling the order of one team's windows.

    Each window keeps its own totals; only their position in the season changes. A shift
    that survives this is one the schedule order cannot explain.
    """
    ordered = windows.sort_values("window_index")
    matrix = _totals_matrix(ordered, totals_columns)
    games = pd.to_numeric(ordered["games_in_window"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    window_count = len(ordered)
    if window_count < 2:
        return np.array([])

    permutations = np.argsort(rng.random((iterations, window_count)), axis=1)
    permuted_games = games[permutations]

    games_from_end = np.cumsum(permuted_games[:, ::-1], axis=1)[:, ::-1]
    masks = (games_from_end - permuted_games) < recent_games

    permuted_matrix = matrix[permutations]
    recent_sums = np.einsum("bn,bnk->bk", masks.astype(float), permuted_matrix)
    total_sums = matrix.sum(axis=0)
    baseline_sums = total_sums[None, :] - recent_sums

    recent_style = style_from_totals(pd.DataFrame(recent_sums, columns=list(totals_columns)), dimensions)
    baseline_style = style_from_totals(pd.DataFrame(baseline_sums, columns=list(totals_columns)), dimensions)

    scale_values = np.array([scales.get(dimension, np.nan) for dimension in recent_style.columns], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        z_deltas = (recent_style.to_numpy() - baseline_style.to_numpy()) / scale_values[None, :]
    return shift_score(z_deltas)


def build_shift_table(
    panel: pd.DataFrame,
    deltas: pd.DataFrame,
    period_frame: pd.DataFrame,
    *,
    dimensions: Sequence[str],
    scales: pd.Series,
    totals_columns: Sequence[str],
    config: Dict,
) -> pd.DataFrame:
    """One row per team: how far its style moved, and whether that beats its own noise."""
    permutation_config = config.get("permutation_test", {})
    iterations = int(permutation_config.get("iterations", 4000))
    significant_at = float(permutation_config.get("significant_percentile", 0.95))
    moderate_at = float(permutation_config.get("moderate_percentile", 0.80))
    recent_games = float(config.get("periods", {}).get("recent_games", 10))
    label_config = config.get("labels", {})
    top_count = int(label_config.get("top_dimension_count", 3))
    helping_at = float(label_config.get("helping_net_rating_delta", 2.0))
    hurting_at = float(label_config.get("hurting_net_rating_delta", -2.0))

    rng = np.random.default_rng(int(permutation_config.get("random_seed", 20260812)))
    baseline_periods = period_frame[period_frame["period"] == BASELINE].set_index("team_abbreviation")
    recent_periods = period_frame[period_frame["period"] == RECENT].set_index("team_abbreviation")

    rows: List[Dict] = []
    for team, team_deltas in deltas.groupby("team_abbreviation", sort=True):
        if team not in baseline_periods.index or team not in recent_periods.index:
            continue
        z_values = pd.to_numeric(team_deltas["z_delta"], errors="coerce").to_numpy()
        observed = float(np.nansum(np.abs(z_values)))
        euclidean = float(np.sqrt(np.nansum(z_values**2)))

        null_scores = permutation_null(
            panel[panel["team_abbreviation"] == team],
            dimensions=dimensions,
            scales=scales,
            totals_columns=totals_columns,
            recent_games=recent_games,
            iterations=iterations,
            rng=rng,
        )
        if null_scores.size:
            percentile = float((null_scores < observed).mean())
            p_value = float((null_scores >= observed).mean())
            null_median = float(np.median(null_scores))
        else:
            percentile = np.nan
            p_value = np.nan
            null_median = np.nan

        if pd.isna(percentile):
            significance = "Not evaluated"
        elif percentile >= significant_at:
            significance = "Significant"
        elif percentile >= moderate_at:
            significance = "Moderate"
        else:
            significance = "Within noise"

        baseline_net = pd.to_numeric(baseline_periods.loc[team, "net_rating"], errors="coerce")
        recent_net = pd.to_numeric(recent_periods.loc[team, "net_rating"], errors="coerce")
        net_delta = recent_net - baseline_net
        if pd.isna(net_delta):
            direction = "Unknown"
        elif net_delta >= helping_at:
            direction = "Helping"
        elif net_delta <= hurting_at:
            direction = "Hurting"
        else:
            direction = "Neutral"

        ranked = team_deltas.reindex(
            pd.to_numeric(team_deltas["z_delta"], errors="coerce").abs().sort_values(ascending=False).index
        ).head(top_count)
        moves = ", ".join(
            f"{row['dimension']} {'+' if row['z_delta'] >= 0 else ''}{row['z_delta']:.2f}"
            for _, row in ranked.iterrows()
            if pd.notna(row["z_delta"])
        )

        rows.append(
            {
                "team_abbreviation": team,
                "identity_shift_l1": observed,
                "identity_shift_euclidean": euclidean,
                "null_median_l1": null_median,
                "shift_vs_null_ratio": float(observed / null_median) if null_median else np.nan,
                "permutation_percentile": percentile,
                "permutation_p_value": p_value,
                "shift_significance": significance,
                "baseline_games": float(baseline_periods.loc[team, "games"]),
                "recent_games": float(recent_periods.loc[team, "games"]),
                "baseline_net_rating": baseline_net,
                "recent_net_rating": recent_net,
                "net_rating_delta": net_delta,
                "baseline_off_rating": pd.to_numeric(baseline_periods.loc[team, "off_rating"], errors="coerce"),
                "recent_off_rating": pd.to_numeric(recent_periods.loc[team, "off_rating"], errors="coerce"),
                "baseline_def_rating": pd.to_numeric(baseline_periods.loc[team, "def_rating"], errors="coerce"),
                "recent_def_rating": pd.to_numeric(recent_periods.loc[team, "def_rating"], errors="coerce"),
                "shift_direction": direction,
                "top_dimension_moves": moves,
            }
        )

    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table = table.sort_values("identity_shift_l1", ascending=False).reset_index(drop=True)
    table.insert(1, "shift_rank", np.arange(1, len(table) + 1))
    return table


def apply_schedule_adjustment(shift: pd.DataFrame, config: Dict) -> pd.DataFrame:
    """Re-express the change in net rating against a constant strength of schedule.

    Net rating measured against weaker opponents is inflated by roughly the amount those
    opponents are weaker. If a team's recent opponents average ``d`` points per 100 worse
    than its earlier ones, the observed change overstates the real one by ``-d``, so the
    adjusted change is ``observed + d``.

    This matters: several 2026 teams swing from improving to declining once it is applied,
    so the direction label is taken from the adjusted figure wherever schedule data exists.
    """
    if shift.empty or "opponent_net_rating_delta" not in shift.columns:
        if not shift.empty:
            shift = shift.copy()
            shift["opponent_adjusted_net_rating_delta"] = shift.get("net_rating_delta")
        return shift

    label_config = config.get("labels", {})
    helping_at = float(label_config.get("helping_net_rating_delta", 2.0))
    hurting_at = float(label_config.get("hurting_net_rating_delta", -2.0))

    out = shift.copy()
    raw = pd.to_numeric(out["net_rating_delta"], errors="coerce")
    opponent = pd.to_numeric(out["opponent_net_rating_delta"], errors="coerce")
    adjusted = raw + opponent
    out["opponent_adjusted_net_rating_delta"] = adjusted.where(opponent.notna(), raw)

    basis = out["opponent_adjusted_net_rating_delta"]
    out["shift_direction"] = np.select(
        [basis.isna(), basis >= helping_at, basis <= hurting_at],
        ["Unknown", "Helping", "Hurting"],
        default="Neutral",
    )
    out["shift_direction_basis"] = np.where(
        opponent.notna(), "opponent_adjusted", "raw_net_rating"
    )
    return out


def totals_columns_for(panel: pd.DataFrame) -> List[str]:
    """Raw columns the style dimensions are built from, plus the games denominator."""
    required = [
        "games_in_window",
        "off_poss",
        "def_poss",
        "points",
        "opponent_points",
        "fg2_a",
        "fg3_a",
        "fg2_m",
        "fg3_m",
        "fta",
        "ft_points",
        "at_rim_fga",
        "at_rim_fgm",
        "short_mid_range_fga",
        "long_mid_range_fga",
        "corner3_fga",
        "arc3_fga",
        "turnovers",
        "live_ball_turnovers",
        "off_rebounds",
        "def_rebounds",
        "assists",
        "pts_assisted2s",
        "pts_assisted3s",
        "second_chance_points",
        "second_chance_off_poss",
        "penalty_off_poss",
        "penalty_points",
        "steals",
        "blocks",
        "fouls",
    ]
    return [column for column in required if column in panel.columns]
