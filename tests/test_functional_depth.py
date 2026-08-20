import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from functional_depth.metrics import (  # noqa: E402
    aggregate_player_team,
    gini,
    league_skill_thresholds,
    production_distribution,
    role_redundancy,
    rotation_trust,
)
from functional_depth.score import build_functional_depth, build_strip, components_long  # noqa: E402


def _player_game(team, player, name, games, ppg, mpg, apg=2, bpg=0, spg=1, tpg=1):
    """games identical rows for one player: constant per-game production."""
    rows = []
    for g in range(games):
        rows.append(
            {
                "team_abbreviation": team, "player_id": player, "player_name": name,
                "game_id": f"{team}-{g}", "minutes": mpg,
                "points": ppg, "assists": apg, "off_poss": 60.0, "def_poss": 60.0,
                "blocks": bpg, "steals": spg, "fg3_m": tpg,
            }
        )
    return rows


def _star_team(team="AAA"):
    # One 30-ppg star + four ~8-ppg role players: concentrated.
    rows = _player_game(team, f"{team}1", "Star", 10, 30, 34, apg=6, tpg=3)
    for i in range(2, 6):
        rows += _player_game(team, f"{team}{i}", f"Role{i}", 10, 8, 22, apg=2, tpg=1)
    return rows


def _distributed_team(team="BBB"):
    # Five ~15-ppg players: even.
    rows = []
    for i in range(1, 6):
        rows += _player_game(team, f"{team}{i}", f"Bal{i}", 10, 15, 26, apg=4, bpg=1, tpg=2)
    return rows


class GiniTest(unittest.TestCase):
    def test_even_and_concentrated(self):
        self.assertAlmostEqual(gini([10, 10, 10, 10]), 0.0, places=6)
        self.assertGreater(gini([100, 1, 1, 1]), 0.6)
        self.assertTrue(np.isnan(gini([])))


class AggregateTest(unittest.TestCase):
    def test_min_games_filter_and_per75(self):
        pg = pd.DataFrame(_player_game("AAA", "A1", "Star", 8, 30, 34) + _player_game("AAA", "A2", "Cameo", 2, 4, 5))
        agg = aggregate_player_team(pg, min_games=5)
        self.assertEqual(set(agg["player_id"]), {"A1"})  # the 2-game cameo is dropped
        star = agg.iloc[0]
        self.assertAlmostEqual(star["scoring"], 30 / 60 * 75)  # points per 75 possessions


class ComponentTest(unittest.TestCase):
    def test_distribution_star_vs_balanced(self):
        star = aggregate_player_team(pd.DataFrame(_star_team()), min_games=5)
        balanced = aggregate_player_team(pd.DataFrame(_distributed_team()), min_games=5)
        star_gini = production_distribution(star, rotation_minutes=12)["creation_gini"]
        bal_gini = production_distribution(balanced, rotation_minutes=12)["creation_gini"]
        self.assertGreater(star_gini, bal_gini)  # the star team is more concentrated

    def test_rotation_trust_counts_meaningful_minutes(self):
        agg = aggregate_player_team(pd.DataFrame(_distributed_team()), min_games=5)
        trust = rotation_trust(agg, rotation_minutes=12)
        self.assertEqual(trust["rotation_size"], 5)

    def test_role_redundancy_uses_league_thresholds(self):
        both = pd.DataFrame(_star_team("AAA") + _distributed_team("BBB"))
        agg = aggregate_player_team(both, min_games=5)
        thresholds = league_skill_thresholds(agg, rotation_minutes=12)
        red = role_redundancy(agg[agg["team_abbreviation"] == "BBB"], thresholds, rotation_minutes=12)
        self.assertIn("role_redundancy", red)
        self.assertTrue(0.0 <= red["role_redundancy"] <= 1.0)


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.player_game = pd.DataFrame(_star_team("AAA") + _distributed_team("BBB"))
        self.bench = pd.DataFrame(
            [
                {"team_abbreviation": "AAA", "bench_dropoff": 6.0, "bench_heavy_net_rating": -8.0},
                {"team_abbreviation": "BBB", "bench_dropoff": -1.0, "bench_heavy_net_rating": 5.0},
            ]
        )
        self.config = {"depth": {"rotation_minutes": 12.0, "min_games": 5}}

    def test_distributed_team_scores_deeper(self):
        depth = build_functional_depth(self.player_game, self.bench, self.config)
        self.assertEqual(set(depth["team_abbreviation"]), {"AAA", "BBB"})
        bbb = depth[depth["team_abbreviation"] == "BBB"].iloc[0]
        aaa = depth[depth["team_abbreviation"] == "AAA"].iloc[0]
        self.assertGreater(bbb["functional_depth_score"], aaa["functional_depth_score"])
        self.assertEqual(bbb["depth_rank"], 1)
        self.assertTrue(bool(bbb["possession_components_available"]))

    def test_possession_components_missing_are_flagged_and_renormalized(self):
        depth = build_functional_depth(self.player_game, pd.DataFrame(), self.config)
        row = depth.iloc[0]
        self.assertFalse(bool(row["possession_components_available"]))
        self.assertEqual(int(row["components_used"]), 3)  # only the three game-layer components
        self.assertTrue(np.isfinite(row["functional_depth_score"]))  # renormalized, not NaN

    def test_strip_axis_orders_star_to_distributed(self):
        depth = build_functional_depth(self.player_game, self.bench, self.config)
        strip = build_strip(depth)
        # Sorted ascending on the axis: the star-dependent team comes first (most negative).
        self.assertEqual(strip.iloc[0]["team_abbreviation"], "AAA")
        self.assertLess(strip.iloc[0]["dependency_axis"], strip.iloc[-1]["dependency_axis"])

    def test_components_long_marks_possession_fed(self):
        depth = build_functional_depth(self.player_game, self.bench, self.config)
        long = components_long(depth)
        self.assertEqual(len(long), len(depth) * 5)
        poss = long[long["possession_fed"]]["component"].unique()
        self.assertEqual(set(poss), {"replacement_resilience", "performance_floor"})


if __name__ == "__main__":
    unittest.main()
