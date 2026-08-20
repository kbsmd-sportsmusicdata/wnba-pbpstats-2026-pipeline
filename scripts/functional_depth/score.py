"""Compose the five components into a Functional Depth Score and the roster strip.

Each component is turned into a league-relative 0-100 sub-score (percentile across teams, signed so
that higher always means deeper), then blended by configured weights. The two possession-fed
components can be missing for a team because that feed lags; when they are, the weights are
renormalized over the components that are present and the team is flagged, rather than scored on a
silent zero.

The roster strip places each team on a single ``star dependency <-> distributed resilience`` axis,
drawn from the distribution family (how spread the production and minutes are, and whether skills
have backups), anchored by the top scorer's share of rotation points.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .metrics import (
    SKILLS,
    aggregate_player_team,
    league_skill_thresholds,
    performance_floor,
    production_distribution,
    replacement_resilience,
    role_redundancy,
    rotation_trust,
)


# Component -> (raw metric column, higher_raw_is_deeper). The sub-score is a signed percentile so a
# higher sub-score is always "deeper".
_COMPONENTS = {
    "production_distribution": ("creation_gini", False),
    "rotation_trust": ("minutes_entropy", True),
    "role_redundancy": ("role_redundancy", True),
    "replacement_resilience": ("bench_dropoff", False),
    "performance_floor": ("bench_heavy_net_rating", True),
}
_POSSESSION_COMPONENTS = ("replacement_resilience", "performance_floor")
_DEFAULT_WEIGHTS = {
    "production_distribution": 0.25,
    "rotation_trust": 0.15,
    "role_redundancy": 0.20,
    "replacement_resilience": 0.20,
    "performance_floor": 0.20,
}


def _team_metrics_row(team: str, players: pd.DataFrame, bench: pd.DataFrame, thresholds: Dict[str, float],
                      *, rotation_minutes: float) -> Dict[str, Any]:
    row: Dict[str, Any] = {"team_abbreviation": team}
    row.update(production_distribution(players, rotation_minutes=rotation_minutes))
    row.update(rotation_trust(players, rotation_minutes=rotation_minutes))
    row.update(role_redundancy(players, thresholds, rotation_minutes=rotation_minutes))
    bench_rows = bench[bench["team_abbreviation"] == team] if not bench.empty else bench
    bench_row = bench_rows.iloc[0] if len(bench_rows) else pd.Series(dtype="float64")
    row.update(replacement_resilience(bench_row))
    row.update(performance_floor(bench_row))
    row["possession_components_available"] = bool(len(bench_rows))
    return row


def _signed_percentile(series: pd.Series, higher_is_deeper: bool) -> pd.Series:
    """0-100 percentile across teams, oriented so higher is always deeper. NaN stays NaN."""
    return series.rank(pct=True, ascending=higher_is_deeper) * 100.0


def build_functional_depth(
    player_game: pd.DataFrame,
    bench_net_rating: pd.DataFrame,
    config: Dict[str, Any],
) -> pd.DataFrame:
    """One row per team: component metrics, 0-100 sub-scores, weighted composite, and rank."""
    depth_config = config.get("depth", {})
    rotation_minutes = float(depth_config.get("rotation_minutes", 12.0))
    min_games = int(depth_config.get("min_games", 5))
    weights = {**_DEFAULT_WEIGHTS, **depth_config.get("weights", {})}

    player_team = aggregate_player_team(player_game, min_games=min_games)
    if player_team.empty:
        return pd.DataFrame()
    thresholds = league_skill_thresholds(player_team, rotation_minutes=rotation_minutes)

    bench = bench_net_rating if bench_net_rating is not None else pd.DataFrame()
    rows: List[Dict[str, Any]] = [
        _team_metrics_row(team, group, bench, thresholds, rotation_minutes=rotation_minutes)
        for team, group in player_team.groupby("team_abbreviation", sort=True)
    ]
    frame = pd.DataFrame(rows)

    # Signed 0-100 sub-score per component.
    subscore_columns: List[str] = []
    for component, (raw_column, higher_is_deeper) in _COMPONENTS.items():
        subscore = f"{component}_subscore"
        frame[subscore] = _signed_percentile(pd.to_numeric(frame[raw_column], errors="coerce"), higher_is_deeper)
        subscore_columns.append(subscore)

    # Weighted composite, renormalizing over the components present for each team.
    def _composite(row: pd.Series) -> float:
        available = {c: weights[c] for c in _COMPONENTS if np.isfinite(row.get(f"{c}_subscore", np.nan))}
        total_weight = sum(available.values())
        if total_weight <= 0:
            return np.nan
        return float(sum(row[f"{c}_subscore"] * w for c, w in available.items()) / total_weight)

    frame["functional_depth_score"] = frame.apply(_composite, axis=1)
    frame["components_used"] = frame.apply(
        lambda r: int(sum(np.isfinite(r.get(f"{c}_subscore", np.nan)) for c in _COMPONENTS)), axis=1
    )

    # star dependency <-> distributed resilience: the distribution family, mapped to [-1, 1].
    distribution_family = ["production_distribution_subscore", "rotation_trust_subscore", "role_redundancy_subscore"]
    family_mean = frame[distribution_family].mean(axis=1, skipna=True)
    frame["dependency_axis"] = (family_mean - 50.0) / 50.0
    frame["depth_profile"] = np.where(
        frame["dependency_axis"] >= 0.15, "distributed_resilience",
        np.where(frame["dependency_axis"] <= -0.15, "star_dependent", "balanced"),
    )

    frame = frame.sort_values("functional_depth_score", ascending=False, na_position="last").reset_index(drop=True)
    frame.insert(1, "depth_rank", np.arange(1, len(frame) + 1))
    return frame


def build_strip(depth: pd.DataFrame) -> pd.DataFrame:
    """The one-axis roster strip: team, its position, the anchoring star share, and a label."""
    if depth.empty:
        return pd.DataFrame(columns=["team_abbreviation", "dependency_axis", "top_scorer_share", "depth_profile"])
    columns = ["team_abbreviation", "dependency_axis", "top_scorer_share", "depth_profile", "functional_depth_score"]
    strip = depth[[c for c in columns if c in depth.columns]].copy()
    return strip.sort_values("dependency_axis", ascending=True, na_position="last").reset_index(drop=True)


def components_long(depth: pd.DataFrame) -> pd.DataFrame:
    """Long team x component frame for plotting the five sub-scores."""
    if depth.empty:
        return pd.DataFrame(columns=["team_abbreviation", "component", "subscore", "possession_fed"])
    rows: List[Dict[str, Any]] = []
    for _, row in depth.iterrows():
        for component in _COMPONENTS:
            rows.append(
                {
                    "team_abbreviation": row["team_abbreviation"],
                    "component": component,
                    "subscore": row.get(f"{component}_subscore"),
                    "possession_fed": component in _POSSESSION_COMPONENTS,
                }
            )
    return pd.DataFrame(rows)
