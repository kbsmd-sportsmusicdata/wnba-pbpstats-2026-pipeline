import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_playoff_summary as bps  # noqa: E402
from playoff_summary import (  # noqa: E402
    aggregate_entity,
    is_rate,
    player_leaderboard,
    render_markdown,
    rs_vs_playoff_deltas,
    series_rollups,
    team_board,
)


def _player_rows():
    """Player P1 with two playoff games (clean numbers), P2 with one game."""
    base = {"season": 2026, "season_type": "Playoffs", "is_home": True,
            "opponent_team_id": "1611661323", "opponent_team_abbreviation": "CON"}
    return pd.DataFrame([
        {**base, "game_id": "g1", "game_date": "2026-09-14", "player_id": "p1", "player_name": "Star One",
         "team_id": "1611661313", "team_abbreviation": "NYL", "win": True, "minutes": 30.0,
         "team_points": 100, "opponent_points": 90, "margin": 10, "plus_minus": 8,
         "team_possessions": 95, "opponent_possessions": 95, "off_poss": 25, "def_poss": 25, "total_poss": 50,
         "points": 20, "assists": 5, "rebounds": 8, "turnovers": 2,
         "fg2_m": 8, "fg2_a": 10, "fg3_m": 1, "fg3_a": 3, "fta": 4, "ts_pct": 0.60, "usage": 30.0},
        {**base, "game_id": "g2", "game_date": "2026-09-16", "player_id": "p1", "player_name": "Star One",
         "team_id": "1611661313", "team_abbreviation": "NYL", "win": False, "minutes": 34.0,
         "team_points": 88, "opponent_points": 93, "margin": -5, "plus_minus": -3,
         "team_possessions": 98, "opponent_possessions": 98, "off_poss": 52, "def_poss": 48, "total_poss": 100,
         "points": 30, "assists": 7, "rebounds": 10, "turnovers": 4,
         "fg2_m": 10, "fg2_a": 16, "fg3_m": 2, "fg3_a": 5, "fta": 6, "ts_pct": 0.50, "usage": 28.0},
        {**base, "game_id": "g1", "game_date": "2026-09-14", "player_id": "p2", "player_name": "Role Two",
         "team_id": "1611661323", "team_abbreviation": "CON", "win": False, "minutes": 18.0,
         "team_points": 90, "opponent_points": 100, "margin": -10, "plus_minus": -6,
         "team_possessions": 95, "opponent_possessions": 95, "off_poss": 20, "def_poss": 20, "total_poss": 40,
         "points": 10, "assists": 2, "rebounds": 4, "turnovers": 1,
         "fg2_m": 4, "fg2_a": 7, "fg3_m": 0, "fg3_a": 2, "fta": 2, "ts_pct": 0.48, "usage": 18.0},
    ])


class ClassifyTest(unittest.TestCase):
    def test_is_rate(self):
        for rate in ("ts_pct", "efg_pct", "usage", "pace", "at_rim_accuracy", "arc3_frequency",
                     "on_off_rtg", "fg3_apct", "at_rim_pct_assisted", "fg2_apct_blocked",
                     "avg3pt_shot_distance", "shot_quality_avg", "seconds_per_poss_off"):
            self.assertTrue(is_rate(rate), rate)
        for counting in ("points", "assists", "rebounds", "fg3_m", "fg3_a", "three_pt_assists",
                         "turnovers", "fta", "period3_fouls3_minutes"):
            self.assertFalse(is_rate(counting), counting)


class AggregateTest(unittest.TestCase):
    def setUp(self):
        self.agg = aggregate_entity(
            _player_rows(), id_col="player_id",
            name_cols=["player_name", "team_abbreviation", "team_id"], min_games=2,
        )

    def _p1(self):
        return self.agg[self.agg["player_id"] == "p1"].iloc[0]

    def test_counts_and_flag(self):
        p1 = self._p1()
        self.assertEqual(int(p1["games"]), 2)
        self.assertEqual(int(p1["wins"]), 1)
        self.assertEqual(int(p1["losses"]), 1)
        self.assertTrue(bool(p1["meets_min_games"]))
        p2 = self.agg[self.agg["player_id"] == "p2"].iloc[0]
        self.assertFalse(bool(p2["meets_min_games"]))  # only one game, min is 2
        self.assertEqual(p1["team_abbreviation"], "NYL")

    def test_counting_per100(self):
        p1 = self._p1()
        self.assertEqual(p1["points_total"], 50)
        self.assertAlmostEqual(p1["points_per100"], 50 / 150 * 100)   # 33.33...
        self.assertAlmostEqual(p1["assists_per100"], 12 / 150 * 100)  # 8.0
        self.assertEqual(p1["total_poss_total"], 150)

    def test_rate_is_possession_weighted(self):
        p1 = self._p1()
        self.assertAlmostEqual(p1["usage"], (30.0 * 50 + 28.0 * 100) / 150)  # 28.6667

    def test_derived_shooting_rates_from_sums(self):
        p1 = self._p1()
        # pts=50, fga=34, fta=10 -> TS = 50 / (2*(34+0.44*10)) = 50/76.8
        self.assertAlmostEqual(p1["ts_pct_derived"], 50 / 76.8)
        # fgm=21, fg3m=3, fga=34 -> eFG = (21+1.5)/34
        self.assertAlmostEqual(p1["efg_pct_derived"], 22.5 / 34)

    def test_context_per_game(self):
        p1 = self._p1()
        self.assertEqual(p1["margin_total"], 5)
        self.assertAlmostEqual(p1["margin_per_game"], 2.5)


class DeltaTest(unittest.TestCase):
    def test_rs_vs_playoff_delta_for_common_entities(self):
        playoff = aggregate_entity(_player_rows(), id_col="player_id",
                                   name_cols=["player_name", "team_abbreviation", "team_id"], min_games=2)
        rs_rows = _player_rows().copy()
        rs_rows["season_type"] = "Regular Season"
        rs_rows["points"] = rs_rows["points"] - 5  # RS scoring a touch lower
        rs = aggregate_entity(rs_rows, id_col="player_id",
                              name_cols=["player_name", "team_abbreviation", "team_id"], min_games=2)
        delta = rs_vs_playoff_deltas(rs, playoff, id_col="player_id",
                                     name_cols=["player_name", "team_abbreviation"])
        p1 = delta[delta["player_id"] == "p1"].iloc[0]
        self.assertEqual(int(p1["rs_games"]), 2)
        self.assertEqual(int(p1["playoff_games"]), 2)
        self.assertAlmostEqual(p1["points_per100_delta"], p1["points_per100_playoff"] - p1["points_per100_rs"])
        self.assertGreater(p1["points_per100_delta"], 0)  # playoffs scored more here
        self.assertNotIn("points_total_delta", delta.columns)  # raw volumes are never differenced


class SeriesTest(unittest.TestCase):
    def test_series_rollup_groups_unordered_pairs(self):
        games = [
            {"game_id": "g1", "home_team_id": "1611661313", "home_team_abbreviation": "NYL", "home_points": "100",
             "home_possessions": "95", "away_team_id": "1611661323", "away_team_abbreviation": "CON",
             "away_points": "90", "away_possessions": "95"},
            # reversed home/away, same pairing -> one series
            {"game_id": "g2", "home_team_id": "1611661323", "home_team_abbreviation": "CON", "home_points": "80",
             "home_possessions": "92", "away_team_id": "1611661313", "away_team_abbreviation": "NYL",
             "away_points": "95", "away_possessions": "92"},
        ]
        s = series_rollups(games)
        self.assertEqual(len(s), 1)
        row = s.iloc[0]
        self.assertEqual(int(row["games_played"]), 2)
        # NYL won both (100>90, 95>80); ids sort so team_a is the smaller id (1611661313 = NYL)
        self.assertEqual(row["team_a_abbreviation"], "NYL")
        self.assertEqual(int(row["team_a_wins"]), 2)
        self.assertEqual(int(row["team_b_wins"]), 0)
        self.assertEqual(row["series_leader"], "NYL")
        self.assertEqual(row["game_ids"], "g1;g2")


class BoardTest(unittest.TestCase):
    def test_leaderboard_filters_to_qualified_and_renders(self):
        agg = aggregate_entity(_player_rows(), id_col="player_id",
                               name_cols=["player_name", "team_abbreviation", "team_id"], min_games=2)
        board = player_leaderboard(agg, top_n=15)
        self.assertIn("PTS/100", board.columns)
        self.assertEqual(list(board["Player"]), ["Star One"])  # p2 filtered (1 game < 2)
        md = render_markdown(board, team_board(pd.DataFrame()), season="2026", as_of="2026-09-16",
                             min_games=2, total_players=len(board), total_teams=0)
        self.assertIn("Playoff Summary", md)
        self.assertIn("Star One", md)


def _team_rows():
    base = {"season": 2026, "season_type": "Playoffs"}
    return pd.DataFrame([
        {**base, "game_id": "g1", "game_date": "2026-09-14", "team_id": "1611661313", "team_name": "Liberty",
         "team_abbreviation": "NYL", "opponent_team_id": "1611661323", "opponent_team_abbreviation": "CON",
         "is_home": True, "win": True, "minutes": 200.0, "team_points": 100, "opponent_points": 90, "margin": 10,
         "team_possessions": 95, "opponent_possessions": 95, "off_poss": 95, "def_poss": 95, "total_poss": 190,
         "points": 100, "pace": 95.0},
        {**base, "game_id": "g1", "game_date": "2026-09-14", "team_id": "1611661323", "team_name": "Sun",
         "team_abbreviation": "CON", "opponent_team_id": "1611661313", "opponent_team_abbreviation": "NYL",
         "is_home": False, "win": False, "minutes": 200.0, "team_points": 90, "opponent_points": 100, "margin": -10,
         "team_possessions": 95, "opponent_possessions": 95, "off_poss": 95, "def_poss": 95, "total_poss": 190,
         "points": 90, "pace": 95.0},
    ])


class BuildEndToEndTest(unittest.TestCase):
    def _layout(self, tmp: Path, *, with_playoffs: bool):
        layer = tmp / "processed"
        logs = tmp / "logs"
        pdir = layer / "wnba_pbpstats_player_game" / "season=2026"
        tdir = layer / "wnba_pbpstats_team_game" / "season=2026"
        (pdir / "playoffs").mkdir(parents=True, exist_ok=True)
        (tdir / "playoffs").mkdir(parents=True, exist_ok=True)
        # Regular-season layers always present.
        rs_players = _player_rows().assign(season_type="Regular Season")
        rs_players.to_parquet(pdir / "player_game.parquet", index=False)
        _team_rows().assign(season_type="Regular Season").to_parquet(tdir / "team_game.parquet", index=False)
        if with_playoffs:
            _player_rows().to_parquet(pdir / "playoffs" / "player_game.parquet", index=False)
            _team_rows().to_parquet(tdir / "playoffs" / "team_game.parquet", index=False)
            (logs / "playoffs").mkdir(parents=True, exist_ok=True)
            pd.DataFrame([{
                "game_id": "g1", "date": "2026-09-14", "home_team_id": "1611661313",
                "home_team_abbreviation": "NYL", "home_points": 100, "home_possessions": 95,
                "away_team_id": "1611661323", "away_team_abbreviation": "CON", "away_points": 90,
                "away_possessions": 95, "season_type": "Playoffs",
            }]).to_csv(logs / "playoffs" / "games_wnba_2026_playoffs.csv", index=False)
        return {
            "season": 2026, "game_layer_root": str(layer), "game_logs_root": str(logs),
            "output_root": str(tmp / "out"), "min_playoff_games": 2, "board_top_n": 15,
        }

    def test_skips_when_no_playoff_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._layout(Path(tmp), with_playoffs=False)
            self.assertIsNone(bps.build(config))

    def test_full_build_writes_outputs_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._layout(Path(tmp), with_playoffs=True)
            manifest = bps.build(config)
            self.assertIsNotNone(manifest)
            out = Path(config["output_root"])
            for name in ("player_playoff_splits.csv", "player_playoff_splits.json",
                         "team_playoff_splits.csv", "player_rs_vs_playoff_delta.csv",
                         "series_rollups.csv", "playoff_leaderboard.md",
                         "playoff_summary_manifest.json"):
                self.assertTrue((out / name).exists(), name)
            self.assertEqual(manifest["players"], 2)
            self.assertEqual(manifest["qualified_players"], 1)  # only p1 has 2 games
            self.assertEqual(manifest["teams"], 2)
            self.assertEqual(manifest["series"], 1)
            saved = json.loads((out / "playoff_summary_manifest.json").read_text())
            self.assertEqual(saved["coverage_through"], "2026-09-16")


if __name__ == "__main__":
    unittest.main()
