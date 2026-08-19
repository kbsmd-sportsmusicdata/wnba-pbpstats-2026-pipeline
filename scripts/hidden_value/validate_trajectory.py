"""Held-out validation of the per-game trajectory signal.

Reproduces the test the methodology uses to justify the trajectory component's 0.05 weight,
now on the true per-game layer: for each player, hold out the last ``holdout`` games, fit the
shrunk possession-weighted slope over the ``k`` games before them, and ask whether that slope
improves a prediction of the *held-out level* over simply knowing the player's current level.

The question is predictive validity, not measurement resolution -- a sharper trend that still
predicts regression does not earn more weight. Predicting the held-out level (not a before/after
difference) avoids the mechanical regression-to-the-mean trap.
"""

from __future__ import annotations

from typing import List, Sequence

import numpy as np
import pandas as pd

try:  # imported as a package module (tests, build)
    from .game_form import derive_game_metrics
    from .trajectory import shrink, weighted_slope
except ImportError:  # run as a standalone script
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from hidden_value.game_form import derive_game_metrics
    from hidden_value.trajectory import shrink, weighted_slope


TRAJECTORY_METRICS = ["points_per_75", "ts_pct", "usage", "on_court_poss_share", "on_court_net_rating"]


def _ols_r2(y: np.ndarray, features: np.ndarray) -> tuple:
    """R^2 and coefficients of an intercept OLS of ``y`` on ``features`` (columns)."""
    design = np.column_stack([np.ones(len(features)), features])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    predicted = design @ beta
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return r2, beta


def validate_trajectory(
    player_game: pd.DataFrame,
    *,
    metrics: Sequence[str] = TRAJECTORY_METRICS,
    k: int = 10,
    holdout: int = 5,
    shrinkage_constant: float = 6.0,
    min_prior: int = 3,
    min_players: int = 20,
) -> pd.DataFrame:
    """Return, per metric, the incremental R^2 of the shrunk slope over current level.

    A positive incremental R^2 with a *positive* slope coefficient means the trend adds
    correctly-signed predictive value; a negative coefficient means the trend predicts mean
    reversion, i.e. ranking on it would select players about to regress.
    """
    frame = derive_game_metrics(player_game).sort_values(["player_id", "game_date", "game_id"])
    results: List[dict] = []
    for metric in metrics:
        rows: List[tuple] = []
        for _, group in frame.groupby("player_id", sort=True):
            values = pd.to_numeric(group[metric], errors="coerce").to_numpy()
            weights = pd.to_numeric(group["off_poss"], errors="coerce").fillna(0.0).to_numpy()
            if len(group) < k + holdout:
                continue
            prior_v, prior_w = values[-(k + holdout):-holdout], weights[-(k + holdout):-holdout]
            held_v, held_w = values[-holdout:], weights[-holdout:]
            prior_mask = ~np.isnan(prior_v) & (prior_w > 0)
            held_mask = ~np.isnan(held_v) & (held_w > 0)
            if prior_mask.sum() < min_prior or held_mask.sum() == 0:
                continue
            level = float(np.average(prior_v[prior_mask], weights=prior_w[prior_mask]))
            slope = shrink(weighted_slope(prior_v, prior_w), int(prior_mask.sum()), shrinkage_constant)
            if not np.isfinite(slope):
                continue
            held_level = float(np.average(held_v[held_mask], weights=held_w[held_mask]))
            rows.append((held_level, level, slope))

        record = {"metric": metric, "players": len(rows)}
        if len(rows) < min_players:
            record.update({"incremental_r2": np.nan, "slope_coef": np.nan, "sign": "insufficient"})
            results.append(record)
            continue
        table = pd.DataFrame(rows, columns=["held", "level", "slope"])
        y = table["held"].to_numpy()
        r2_level, _ = _ols_r2(y, table[["level"]].to_numpy())
        r2_both, beta_both = _ols_r2(y, table[["level", "slope"]].to_numpy())
        slope_coef = float(beta_both[2])
        record.update(
            {
                "incremental_r2": round(r2_both - r2_level, 4),
                "slope_coef": round(slope_coef, 3),
                "sign": "positive" if slope_coef > 0 else "negative",
            }
        )
        results.append(record)
    return pd.DataFrame(results)


def main(argv: Sequence[str] | None = None) -> None:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Held-out validation of the per-game trajectory signal.")
    parser.add_argument(
        "--player-game",
        default="data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet",
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--holdout", type=int, default=5)
    args = parser.parse_args(argv)

    path = Path(args.player_game)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    report = validate_trajectory(pd.read_parquet(path), k=args.k, holdout=args.holdout)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
