import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hidden_value.validate_trajectory import TRAJECTORY_METRICS, validate_trajectory  # noqa: E402


def _synthetic_reverting_panel(n_players=40, n_games=18, seed=0):
    """Players whose production trend mean-reverts: the prior slope anticorrelates with what comes next.

    Built so the held-out test must recover a *negative* production slope coefficient, i.e. a rising
    trend predicting a lower held-out level -- the pattern the real data shows.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(n_players):
        base = rng.uniform(14, 26)
        # A player-specific trend that reverses in the holdout window.
        trend = rng.uniform(-1.5, 1.5)
        for g in range(n_games):
            phase = 1.0 if g < n_games - 5 else -1.0  # last 5 games swing the other way
            points = base + phase * trend * g + rng.normal(0, 1.0)
            rows.append(
                {
                    "player_id": str(1000 + p),
                    "game_id": f"{p}-{g}",
                    "game_date": f"2026-05-{g + 1:02d}",
                    "points": max(points, 0.0),
                    "off_poss": 70.0,
                    "team_possessions": 90.0,
                    "ts_pct": 0.55,
                    "usage": 24.0,
                    "on_off_rtg": 108.0,
                    "on_def_rtg": 100.0,
                }
            )
    return pd.DataFrame(rows)


class ValidateTrajectoryTest(unittest.TestCase):
    def test_report_shape_and_metrics(self):
        report = validate_trajectory(_synthetic_reverting_panel(), k=8, holdout=5, min_players=10)
        self.assertEqual(list(report["metric"]), list(TRAJECTORY_METRICS))
        self.assertIn("incremental_r2", report.columns)
        self.assertIn("slope_coef", report.columns)
        self.assertTrue((report["players"] > 0).all())

    def test_mean_reverting_production_yields_negative_slope_coefficient(self):
        report = validate_trajectory(_synthetic_reverting_panel(), k=8, holdout=5, min_players=10)
        production = report[report["metric"] == "points_per_75"].iloc[0]
        # The prior trend anticorrelates with the held-out level -> negative coefficient.
        self.assertEqual(production["sign"], "negative")

    def test_insufficient_sample_is_flagged_not_fabricated(self):
        tiny = _synthetic_reverting_panel(n_players=3, n_games=18)
        report = validate_trajectory(tiny, k=8, holdout=5, min_players=20)
        self.assertTrue((report["sign"] == "insufficient").all())
        self.assertTrue(report["incremental_r2"].isna().all())


if __name__ == "__main__":
    unittest.main()
