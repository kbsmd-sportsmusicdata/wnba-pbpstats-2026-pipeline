import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wnba_game_layer import (  # noqa: E402
    GameLayerError,
    build_player_game,
    build_team_game,
    games_by_id,
    normalize_column,
    to_minutes,
)


# One completed game between NYL (home) and CON (away), in the get-games spine shape.
_GAMES = [
    {
        "GameId": "1022600001", "Date": "2026-05-08",
        "HomeTeamId": "1611661313", "HomeTeamAbbreviation": "NYL", "HomePoints": 106, "HomePossessions": 87,
        "AwayTeamId": "1611661323", "AwayTeamAbbreviation": "CON", "AwayPoints": 75, "AwayPossessions": 88,
    },
]


class NormalizeTest(unittest.TestCase):
    def test_column_normalization(self):
        self.assertEqual(normalize_column("OffPoss"), "off_poss")
        self.assertEqual(normalize_column("TsPct"), "ts_pct")
        self.assertEqual(normalize_column("Offensive Fouls Drawn"), "offensive_fouls_drawn")
        self.assertEqual(normalize_column("2pt And 1 Free Throw Trips"), "2pt_and_1_free_throw_trips")

    def test_minutes_parsing(self):
        self.assertAlmostEqual(to_minutes("34:30"), 34.5)
        self.assertAlmostEqual(to_minutes("40:00"), 40.0)
        self.assertAlmostEqual(to_minutes("12"), 12.0)
        self.assertIsNone(to_minutes(""))
        self.assertIsNone(to_minutes(None))


class PlayerGameTest(unittest.TestCase):
    def setUp(self):
        self.games = games_by_id(_GAMES)

    def test_spine_join_and_zero_fill(self):
        # Two CON players: the first omits Blocks (pbpstats zero-omission), the second reports it,
        # so Blocks is in the batch's column union and the first player's value must fill to 0.
        rows = [
            {"GameId": "1022600001", "Date": "2026-05-08", "Team": "CON", "Opponent": "NYL",
             "Minutes": "33:00", "Points": 18, "Assists": 4,
             "PlayerId": "203833", "PlayerName": "Chelsea Gray", "TeamId": "1611661323", "TeamAbbreviation": "CON"},
            {"GameId": "1022600001", "Date": "2026-05-08", "Team": "CON", "Opponent": "NYL",
             "Minutes": "28:00", "Points": 12, "Blocks": 3,
             "PlayerId": "1610", "PlayerName": "Alyssa Thomas", "TeamId": "1611661323", "TeamAbbreviation": "CON"},
        ]
        pg = build_player_game(rows, self.games)
        row = pg[pg["player_id"] == "203833"].iloc[0]
        self.assertEqual(row["player_id"], "203833")
        self.assertEqual(row["team_id"], "1611661323")           # played-for team from the spine
        self.assertEqual(row["opponent_team_id"], "1611661313")
        self.assertFalse(row["is_home"])                          # CON was away
        self.assertEqual(row["team_points"], 75)
        self.assertEqual(row["opponent_points"], 106)
        self.assertEqual(row["margin"], -31)
        self.assertFalse(bool(row["win"]))
        self.assertAlmostEqual(row["minutes"], 33.0)
        self.assertEqual(row["points"], 18)
        # A metric never sent for this player is present and zero, not null.
        self.assertIn("blocks", pg.columns)
        self.assertEqual(row["blocks"], 0)

    def test_trade_safety_attributes_game_to_played_for_team(self):
        # Injected TeamId is the player's *current* team (NYL), but she played this game for CON.
        rows = [
            {"GameId": "1022600001", "Date": "2026-05-08", "Team": "CON", "Opponent": "NYL",
             "Minutes": "20:00", "Points": 5,
             "PlayerId": "999", "PlayerName": "Traded Player", "TeamId": "1611661313", "TeamAbbreviation": "NYL"},
        ]
        pg = build_player_game(rows, self.games)
        # Resolved to the team actually played for (CON), not the current-roster team.
        self.assertEqual(pg.iloc[0]["team_id"], "1611661323")
        self.assertEqual(pg.iloc[0]["opponent_team_id"], "1611661313")

    def test_row_absent_from_spine_fails_closed(self):
        rows = [{"GameId": "9999999999", "Date": "2026-05-08", "Team": "CON", "Opponent": "NYL",
                 "PlayerId": "1", "TeamId": "1611661323"}]
        with self.assertRaisesRegex(GameLayerError, "absent from the get-games spine"):
            build_player_game(rows, self.games)

    def test_row_matching_neither_side_fails_closed(self):
        rows = [{"GameId": "1022600001", "Date": "2026-05-08", "Team": "XXX", "Opponent": "NYL",
                 "PlayerId": "1", "TeamId": "0000000000"}]
        with self.assertRaisesRegex(GameLayerError, "matches neither side"):
            build_player_game(rows, self.games)


class TeamGameTest(unittest.TestCase):
    def test_reciprocal_rows_and_identity(self):
        games = games_by_id(_GAMES)
        # Team logs carry no "Team" field; the injected TeamId resolves the side.
        rows = [
            {"GameId": "1022600001", "Date": "2026-05-08", "Opponent": "CON", "Minutes": "200:00",
             "Points": 106, "TeamId": "1611661313", "TeamName": "NYL", "TeamAbbreviation": "NYL"},
            {"GameId": "1022600001", "Date": "2026-05-08", "Opponent": "NYL", "Minutes": "200:00",
             "Points": 75, "TeamId": "1611661323", "TeamName": "CON", "TeamAbbreviation": "CON"},
        ]
        tg = build_team_game(rows, games)
        self.assertEqual(len(tg), 2)
        self.assertEqual(tg["margin"].sum(), 0)                   # reciprocal
        nyl = tg[tg["team_id"] == "1611661313"].iloc[0]
        self.assertTrue(nyl["is_home"])
        self.assertTrue(bool(nyl["win"]))
        self.assertEqual(nyl["team_name"], "NYL")
        self.assertEqual(nyl["opponent_team_id"], "1611661323")


if __name__ == "__main__":
    unittest.main()
