import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hidden_value.game_form import build_game_trajectories, derive_game_metrics  # noqa: E402
from hidden_value.trajectory import build_player_trajectories  # noqa: E402


_METRICS = ["points_per_75", "ts_pct", "usage", "on_court_poss_share", "on_court_net_rating"]


def _player_games(n=8, points_start=10, points_step=2):
    """One player, n games with a clean upward points trend and steady possessions."""
    return pd.DataFrame(
        {
            "player_id": ["1627668"] * n,
            "game_id": [f"g{i}" for i in range(n)],
            "game_date": pd.date_range("2026-05-01", periods=n, freq="2D").astype(str),
            "points": [points_start + points_step * i for i in range(n)],
            "off_poss": [75.0] * n,
            "team_possessions": [90.0] * n,
            "ts_pct": [0.55] * n,
            "usage": [25.0] * n,
            "on_off_rtg": [110.0] * n,
            "on_def_rtg": [100.0] * n,
        }
    )


class DeriveTest(unittest.TestCase):
    def test_derived_per_game_metrics(self):
        derived = derive_game_metrics(_player_games(n=1, points_start=30))
        row = derived.iloc[0]
        self.assertAlmostEqual(row["points_per_75"], 30 / 75 * 75)          # 30
        self.assertAlmostEqual(row["on_court_poss_share"], 75 / 90)
        self.assertAlmostEqual(row["on_court_net_rating"], 10.0)            # 110 - 100

    def test_zero_possession_game_is_nan_not_inf(self):
        games = _player_games(n=1)
        games.loc[0, "off_poss"] = 0
        derived = derive_game_metrics(games)
        self.assertTrue(np.isnan(derived.iloc[0]["points_per_75"]))


class TrajectoryTest(unittest.TestCase):
    def test_schema_is_a_drop_in_match_for_window_panel_builder(self):
        traj = build_game_trajectories(_player_games(), metrics=_METRICS, recent_games=10, min_games=5, shrinkage_constant=6.0)
        # Same columns the board consumes, produced by the window-panel builder too.
        expected = ["player_id", "windows_used", "recent_possessions"] + [
            f"{m}_{s}" for m in _METRICS for s in ("slope", "recent", "volatility")
        ]
        self.assertEqual(list(traj.columns), expected)

    def test_upward_points_trend_gives_positive_shrunk_slope(self):
        traj = build_game_trajectories(_player_games(points_step=2), metrics=_METRICS, recent_games=10, min_games=5, shrinkage_constant=6.0).iloc[0]
        self.assertGreater(traj["points_per_75_slope"], 0)
        self.assertAlmostEqual(traj["points_per_75_recent"], np.average([10 + 2 * i for i in range(8)]))
        # Flat metric -> zero slope, zero volatility.
        self.assertAlmostEqual(traj["ts_pct_slope"], 0.0)
        self.assertAlmostEqual(traj["ts_pct_volatility"], 0.0)
        self.assertEqual(traj["windows_used"], 8)

    def test_players_below_min_games_are_dropped(self):
        traj = build_game_trajectories(_player_games(n=3), metrics=_METRICS, recent_games=10, min_games=5, shrinkage_constant=6.0)
        self.assertTrue(traj.empty)

    def test_empty_input_returns_schema_only(self):
        traj = build_game_trajectories(pd.DataFrame(), metrics=_METRICS, recent_games=10, min_games=5, shrinkage_constant=6.0)
        self.assertTrue(traj.empty)
        self.assertEqual(list(traj.columns), ["player_id", "windows_used", "recent_possessions"])

    def test_shrinkage_pulls_short_series_toward_zero(self):
        # Same trend, fewer games -> smaller |slope| after shrinkage.
        long = build_game_trajectories(_player_games(n=12), metrics=_METRICS, recent_games=12, min_games=5, shrinkage_constant=6.0).iloc[0]
        short = build_game_trajectories(_player_games(n=6), metrics=_METRICS, recent_games=12, min_games=5, shrinkage_constant=6.0).iloc[0]
        self.assertGreater(abs(long["points_per_75_slope"]), abs(short["points_per_75_slope"]))


if __name__ == "__main__":
    unittest.main()
