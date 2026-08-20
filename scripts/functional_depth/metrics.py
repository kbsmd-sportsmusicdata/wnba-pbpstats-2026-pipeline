"""The five Functional Depth components, each a team-level measurement.

Depth is measured as *how a team's production is distributed and how it holds up when starters
sit*, not as bench points. Three components come from the current per-game player layer
(production distribution, rotation trust, role redundancy); two come from the possession-impact
bench net ratings (replacement resilience, performance floor) and carry an availability flag
because that feed lags.

Every function here is pure; the builder wires them together.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import pandas as pd


# Skills a playoff rotation needs more than one source of. Each maps to a per-75-possession rate
# built from the game layer; a "provider" is a rotation player at or above the league rotation
# median for that skill.
SKILLS = ("scoring", "playmaking", "perimeter_shooting", "rim_protection", "ball_pressure")


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def aggregate_player_team(player_game: pd.DataFrame, *, min_games: int) -> pd.DataFrame:
    """Season-to-date per-player, per-team totals and the per-75 rates the skills are built from.

    A player is kept only once they clear ``min_games`` for a team, which drops call-ups and
    garbage-time cameos that would otherwise distort a team's distribution.
    """
    if player_game is None or player_game.empty:
        return pd.DataFrame()

    frame = player_game.copy()
    for column in ("minutes", "points", "assists", "off_poss", "def_poss", "blocks", "steals", "fg3_m"):
        frame[column] = _num(frame, column)

    grouped = frame.groupby(["team_abbreviation", "player_id"], sort=False)
    agg = grouped.agg(
        player_name=("player_name", "first"),
        games=("game_id", "nunique"),
        minutes=("minutes", "sum"),
        points=("points", "sum"),
        assists=("assists", "sum"),
        off_poss=("off_poss", "sum"),
        def_poss=("def_poss", "sum"),
        blocks=("blocks", "sum"),
        steals=("steals", "sum"),
        threes_made=("fg3_m", "sum"),
    ).reset_index()

    agg = agg[agg["games"] >= int(min_games)].copy()
    agg["minutes_per_game"] = agg["minutes"] / agg["games"].where(agg["games"] > 0, np.nan)

    off = agg["off_poss"].where(agg["off_poss"] > 0, np.nan)
    dff = agg["def_poss"].where(agg["def_poss"] > 0, np.nan)
    agg["scoring"] = agg["points"] / off * 75
    agg["playmaking"] = agg["assists"] / off * 75
    agg["perimeter_shooting"] = agg["threes_made"] / off * 75
    agg["rim_protection"] = agg["blocks"] / dff * 75
    agg["ball_pressure"] = agg["steals"] / dff * 75
    return agg.reset_index(drop=True)


def gini(values: Sequence[float]) -> float:
    """Gini concentration of non-negative values in [0, 1]; 0 = perfectly even, 1 = all in one."""
    array = np.sort(np.asarray([v for v in values if v is not None and np.isfinite(v) and v >= 0], dtype=float))
    n = array.size
    if n == 0 or array.sum() == 0:
        return np.nan
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * array) - (n + 1) * array.sum()) / (n * array.sum()))


def _rotation(team_players: pd.DataFrame, *, rotation_minutes: float) -> pd.DataFrame:
    return team_players[team_players["minutes_per_game"] >= rotation_minutes].copy()


def production_distribution(team_players: pd.DataFrame, *, rotation_minutes: float) -> Dict[str, float]:
    """How concentrated scoring and creation are across the rotation (lower Gini = more distributed)."""
    rotation = _rotation(team_players, rotation_minutes=rotation_minutes)
    creation = _num(rotation, "points") + 2.0 * _num(rotation, "assists")  # a point-equivalent of created offense
    return {
        "scoring_gini": gini(_num(rotation, "points").tolist()),
        "creation_gini": gini(creation.tolist()),
        "top_scorer_share": (
            float(_num(rotation, "points").max() / _num(rotation, "points").sum())
            if _num(rotation, "points").sum() > 0
            else np.nan
        ),
    }


def rotation_trust(team_players: pd.DataFrame, *, rotation_minutes: float) -> Dict[str, float]:
    """How many players earn meaningful minutes, and how evenly those minutes are spread."""
    rotation = _rotation(team_players, rotation_minutes=rotation_minutes)
    minutes = _num(rotation, "minutes")
    total = minutes.sum()
    if total > 0:
        shares = (minutes / total).to_numpy()
        shares = shares[shares > 0]
        entropy = float(-(shares * np.log(shares)).sum())
        max_entropy = float(np.log(len(shares))) if len(shares) > 1 else np.nan
        normalized = entropy / max_entropy if max_entropy and max_entropy > 0 else np.nan
    else:
        normalized = np.nan
    return {
        "rotation_size": int(len(rotation)),
        "minutes_entropy": float(normalized) if normalized is not None else np.nan,
    }


def role_redundancy(
    team_players: pd.DataFrame,
    league_thresholds: Dict[str, float],
    *,
    rotation_minutes: float,
    skills: Sequence[str] = SKILLS,
) -> Dict[str, float]:
    """Fraction of required skills for which the team has at least two above-median providers."""
    rotation = _rotation(team_players, rotation_minutes=rotation_minutes)
    providers: Dict[str, int] = {}
    redundant = 0
    for skill in skills:
        threshold = league_thresholds.get(skill, np.nan)
        count = int((_num(rotation, skill) >= threshold).sum()) if np.isfinite(threshold) else 0
        providers[f"{skill}_providers"] = count
        if count >= 2:
            redundant += 1
    return {"role_redundancy": redundant / len(skills), **providers}


def league_skill_thresholds(
    player_team: pd.DataFrame, *, rotation_minutes: float, skills: Sequence[str] = SKILLS
) -> Dict[str, float]:
    """The league rotation median for each skill -- the bar a 'provider' must clear."""
    rotation = player_team[player_team["minutes_per_game"] >= rotation_minutes]
    return {skill: float(pd.to_numeric(rotation.get(skill), errors="coerce").median()) for skill in skills}


def replacement_resilience(bench_row: pd.Series) -> Dict[str, float]:
    """How far net rating falls once any non-starter is on the floor (smaller drop = more resilient)."""
    dropoff = pd.to_numeric(bench_row.get("bench_dropoff"), errors="coerce")
    return {"bench_dropoff": float(dropoff) if pd.notna(dropoff) else np.nan}


def performance_floor(bench_row: pd.Series) -> Dict[str, float]:
    """Net rating of the deepest-bench units -- how badly the weakest rotation segment hurts."""
    floor = pd.to_numeric(bench_row.get("bench_heavy_net_rating"), errors="coerce")
    return {"bench_heavy_net_rating": float(floor) if pd.notna(floor) else np.nan}
