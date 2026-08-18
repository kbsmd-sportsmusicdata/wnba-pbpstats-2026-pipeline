import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wnba_game_layer import (  # noqa: E402
    add_rolling,
    attach_opponent_strength,
    consistency,
    latest_form,
    split_means,
    trend_slope,
)


def _panel():
    """One player, five games with a clean upward points trend, plus home/away and opponents."""
    return pd.DataFrame(
        {
            "player_id": ["1"] * 5,
            "game_id": [f"g{i}" for i in range(1, 6)],
            "game_date": ["2026-05-01", "2026-05-03", "2026-05-05", "2026-05-07", "2026-05-09"],
            "is_home": [True, False, True, False, True],
            "opponent_team_id": ["10", "20", "10", "20", "30"],
            "points": [10, 12, 14, 16, 18],
        }
    )


class RollingTest(unittest.TestCase):
    def test_rolling_is_trailing_and_leakage_safe(self):
        out = add_rolling(_panel(), entity_col="player_id", metrics=["points"], window=3)
        # As-of each game, the r3 mean uses only that game and the two before it.
        self.assertEqual(out["points_r3"].tolist(), [10.0, 11.0, 12.0, 14.0, 16.0])


class FormTest(unittest.TestCase):
    def test_latest_form_windows_and_deltas(self):
        form = latest_form(_panel(), entity_col="player_id", metrics=["points"], windows=(3,)).iloc[0]
        self.assertEqual(form["games_played"], 5)
        self.assertEqual(form["points_season"], 14.0)          # mean(10..18)
        self.assertAlmostEqual(form["points_last3"], 16.0)     # mean(14,16,18)
        self.assertAlmostEqual(form["points_delta_last3"], 2.0)  # 16 - 14

    def test_trend_slope_matches_known_line(self):
        slope = trend_slope(_panel(), entity_col="player_id", metrics=["points"]).iloc[0]["points_slope"]
        self.assertAlmostEqual(slope, 2.0)  # +2 points per game

    def test_consistency_std_and_cv(self):
        cons = consistency(_panel(), entity_col="player_id", metrics=["points"]).iloc[0]
        self.assertAlmostEqual(cons["points_std"], float(pd.Series([10, 12, 14, 16, 18]).std(ddof=1)))
        self.assertGreater(cons["points_cv"], 0)

    def test_short_series_yields_nan(self):
        short = _panel().head(2)
        slope = trend_slope(short, entity_col="player_id", metrics=["points"], min_games=3).iloc[0]["points_slope"]
        self.assertTrue(np.isnan(slope))


class SplitTest(unittest.TestCase):
    def test_home_away_split_means(self):
        split = split_means(_panel(), entity_col="player_id", metrics=["points"], by="is_home")
        home = split[split["is_home"]].iloc[0]
        away = split[~split["is_home"]].iloc[0]
        self.assertAlmostEqual(home["points"], (10 + 14 + 18) / 3)
        self.assertAlmostEqual(away["points"], (12 + 16) / 2)
        self.assertEqual(int(home["games"]), 3)

    def test_opponent_strength_tiers(self):
        tiered = attach_opponent_strength(_panel(), {"10": 0.700, "20": 0.300}, threshold=0.5)
        # Opponent 10 is strong, 20 weak, 30 unknown -> null tier (never mislabeled).
        by_opp = tiered.set_index("game_id")
        self.assertEqual(by_opp.loc["g1", "opponent_tier"], "at_or_above")
        self.assertEqual(by_opp.loc["g2", "opponent_tier"], "below")
        self.assertTrue(pd.isna(by_opp.loc["g5", "opponent_tier"]))  # unknown opponent: never mislabeled
        self.assertTrue(np.isnan(by_opp.loc["g5", "opponent_win_pct"]))


class RealDataSmokeTest(unittest.TestCase):
    def test_helpers_run_on_the_built_player_layer(self):
        path = ROOT / "data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet"
        if not path.exists():
            self.skipTest("game layer not built")
        pg = pd.read_parquet(path)
        form = latest_form(pg, entity_col="player_id", metrics=["points", "usage"], windows=(5, 10))
        self.assertEqual(len(form), pg["player_id"].nunique())
        self.assertIn("points_delta_last5", form.columns)


if __name__ == "__main__":
    unittest.main()
