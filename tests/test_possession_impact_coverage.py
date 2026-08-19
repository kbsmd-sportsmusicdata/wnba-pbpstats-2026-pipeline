import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_possession_impact import coverage_window  # noqa: E402


_POSSESSIONS = pd.DataFrame({"game_id": ["1", "1", "2", "3"]})  # covers games 1,2,3
_GAME_LAYER = pd.DataFrame(
    {"game_id": ["1", "2", "3", "4"], "game_date": ["2026-05-08", "2026-05-10", "2026-05-12", "2026-05-14"]}
)
_SDV_LOGS = pd.DataFrame({"game_id": ["1", "2", "3"], "game_date": ["2026-05-08", "2026-05-10", "2026-05-11"]})


class CoverageWindowTest(unittest.TestCase):
    def test_game_layer_is_preferred_and_dates_the_covered_games(self):
        window = coverage_window(_POSSESSIONS, _SDV_LOGS, _GAME_LAYER)
        self.assertEqual(window["coverage_date_source"], "game_layer")
        self.assertEqual(window["coverage_games"], 3)
        self.assertEqual(window["coverage_from"], "2026-05-08")
        self.assertEqual(window["coverage_through"], "2026-05-12")  # game 3, not the uncovered game 4

    def test_falls_back_to_sportsdataverse_logs_when_layer_absent(self):
        window = coverage_window(_POSSESSIONS, _SDV_LOGS, pd.DataFrame())
        self.assertEqual(window["coverage_date_source"], "sportsdataverse_game_logs")
        self.assertEqual(window["coverage_through"], "2026-05-11")

    def test_no_date_source_leaves_dates_none(self):
        window = coverage_window(_POSSESSIONS, pd.DataFrame(), pd.DataFrame())
        self.assertIsNone(window["coverage_through"])
        self.assertIsNone(window["coverage_date_source"])
        self.assertEqual(window["coverage_games"], 3)  # game count still comes from the possessions

    def test_empty_possessions(self):
        window = coverage_window(pd.DataFrame(columns=["game_id"]), _SDV_LOGS, _GAME_LAYER)
        self.assertEqual(window["coverage_games"], 0)
        self.assertIsNone(window["coverage_through"])


if __name__ == "__main__":
    unittest.main()
