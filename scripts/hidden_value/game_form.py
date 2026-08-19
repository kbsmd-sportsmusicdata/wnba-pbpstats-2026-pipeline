"""Per-player trajectory built from the true per-game layer, not snapshot windows.

The window-panel trajectory (:mod:`hidden_value.trajectory`) infers "recent form" from deltas
between snapshots of cumulative season totals, so its resolution depends on how often totals were
captured. The shared game layer carries one row per player-game, so the same shrunk-slope,
recent-level and volatility signals can be measured over actual games instead. The output schema
is a drop-in match for :func:`hidden_value.trajectory.build_player_trajectories`, so the board and
role model consume it unchanged.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from .trajectory import shrink, weighted_slope


# Per-game derivations of the trajectory metrics that are not already a game-layer column.
# ts_pct and usage are per-game columns already; the rest are computed here from possessions.
def derive_game_metrics(player_game: pd.DataFrame) -> pd.DataFrame:
    """Add the trajectory metrics the game layer does not carry directly, per game."""
    out = player_game.copy()
    off_poss = pd.to_numeric(out.get("off_poss"), errors="coerce")
    points = pd.to_numeric(out.get("points"), errors="coerce")
    team_poss = pd.to_numeric(out.get("team_possessions"), errors="coerce")
    on_off = pd.to_numeric(out.get("on_off_rtg"), errors="coerce")
    on_def = pd.to_numeric(out.get("on_def_rtg"), errors="coerce")

    with np.errstate(divide="ignore", invalid="ignore"):
        out["points_per_75"] = np.where(off_poss > 0, points / off_poss * 75.0, np.nan)
        out["on_court_poss_share"] = np.where(team_poss > 0, off_poss / team_poss, np.nan)
    out["on_court_net_rating"] = on_off - on_def
    return out


def build_game_trajectories(
    player_game: pd.DataFrame,
    *,
    metrics: Sequence[str],
    recent_games: int,
    min_games: int,
    shrinkage_constant: float,
) -> pd.DataFrame:
    """One row per player: shrunk slope, recent level and volatility per metric over recent games.

    Games are ordered by date and weighted by the player's offensive possessions in each, so a
    short appearance moves the trend less than a full game -- mirroring the window-panel builder's
    possession weighting. Slopes are shrunk toward zero when few games support them.
    """
    columns = ["player_id", "windows_used", "recent_possessions"]
    if player_game is None or player_game.empty:
        return pd.DataFrame(columns=columns)

    frame = derive_game_metrics(player_game)
    frame = frame.sort_values(["player_id", "game_date", "game_id"])

    rows: List[Dict] = []
    for player, group in frame.groupby("player_id", sort=True):
        ordered = group.tail(recent_games)
        if len(ordered) < min_games:
            continue
        weights = pd.to_numeric(ordered.get("off_poss"), errors="coerce").fillna(0.0)

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
            valid = values.notna()
            record[f"{metric}_recent"] = (
                float(np.average(values[valid], weights=weights[valid]))
                if valid.any() and weights[valid].sum() > 0
                else np.nan
            )
            record[f"{metric}_volatility"] = float(values.std(ddof=1)) if valid.sum() > 1 else np.nan
        rows.append(record)

    return pd.DataFrame(rows, columns=columns + [
        f"{metric}_{suffix}" for metric in metrics for suffix in ("slope", "recent", "volatility")
    ])
