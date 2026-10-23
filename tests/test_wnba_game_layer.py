import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_wnba_game_layer_2026 as glayer  # noqa: E402
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


def _write_season_logs(logs_dir: Path, slug: str, season_type: str) -> None:
    """Lay down the combined logs + games spine the build script reads, for one season type."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "game_id": "1022600001", "date": "2026-05-08",
        "home_team_id": "1611661313", "home_team_abbreviation": "NYL", "home_points": 106, "home_possessions": 87,
        "away_team_id": "1611661323", "away_team_abbreviation": "CON", "away_points": 75, "away_possessions": 88,
        "season_type": season_type,
    }]).to_csv(logs_dir / f"games_{slug}.csv", index=False)
    player_rows = [
        {"GameId": "1022600001", "Date": "2026-05-08", "Team": "CON", "Opponent": "NYL",
         "Minutes": "33:00", "Points": 18, "PlayerId": "203833", "PlayerName": "Chelsea Gray",
         "TeamId": "1611661323", "TeamAbbreviation": "CON", "SeasonType": season_type},
    ]
    team_rows = [
        {"GameId": "1022600001", "Date": "2026-05-08", "Opponent": "CON", "Minutes": "200:00",
         "Points": 106, "TeamId": "1611661313", "TeamName": "NYL", "TeamAbbreviation": "NYL", "SeasonType": season_type},
        {"GameId": "1022600001", "Date": "2026-05-08", "Opponent": "NYL", "Minutes": "200:00",
         "Points": 75, "TeamId": "1611661323", "TeamName": "CON", "TeamAbbreviation": "CON", "SeasonType": season_type},
    ]
    (logs_dir / f"player_game_logs_{slug}.json").write_text(json.dumps(player_rows), encoding="utf-8")
    (logs_dir / f"team_game_logs_{slug}.json").write_text(json.dumps(team_rows), encoding="utf-8")


class BuildScriptTest(unittest.TestCase):
    def test_season_type_helpers(self):
        self.assertEqual(glayer.resolve_season_types("Both"), ["Regular Season", "Playoffs"])
        self.assertEqual(glayer.resolve_season_types("Playoffs"), ["Playoffs"])
        logs = Path("/logs")
        self.assertEqual(glayer._logs_dir(logs, "Regular Season"), logs)
        self.assertEqual(glayer._logs_dir(logs, "Playoffs"), logs / "playoffs")
        out = Path("/out")
        self.assertEqual(
            glayer._output_dir(out, "wnba_pbpstats_player_game", "2026", "Regular Season"),
            out / "wnba_pbpstats_player_game" / "season=2026",
        )
        self.assertEqual(
            glayer._output_dir(out, "wnba_pbpstats_player_game", "2026", "Playoffs"),
            out / "wnba_pbpstats_player_game" / "season=2026" / "playoffs",
        )

    def test_build_skips_when_season_type_not_ingested(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(glayer.build("2026", "Playoffs", Path(tmp) / "logs", Path(tmp) / "out"))

    def test_regular_season_and_playoffs_build_to_isolated_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_root, out = Path(tmp) / "logs", Path(tmp) / "out"
            _write_season_logs(logs_root, "wnba_2026_regular_season", "Regular Season")
            _write_season_logs(logs_root / "playoffs", "wnba_2026_playoffs", "Playoffs")

            self.assertIsNotNone(glayer.build("2026", "Regular Season", logs_root, out))
            self.assertIsNotNone(glayer.build("2026", "Playoffs", logs_root, out))

            rs_player = out / "wnba_pbpstats_player_game" / "season=2026" / "player_game.parquet"
            po_player = out / "wnba_pbpstats_player_game" / "season=2026" / "playoffs" / "player_game.parquet"
            self.assertTrue(rs_player.exists())
            self.assertTrue(po_player.exists())

            rs_df = pd.read_parquet(rs_player)
            po_df = pd.read_parquet(po_player)
            # Exactly one season_type column, correctly labeled; the SeasonType row field is
            # consumed as identity, not re-emitted as a stray metric column.
            self.assertEqual(list(rs_df.columns).count("season_type"), 1)
            self.assertNotIn("SeasonType", rs_df.columns)
            self.assertEqual(set(rs_df["season_type"]), {"Regular Season"})
            # Regular Season parquet is intact after the Playoffs build (not clobbered).
            self.assertEqual(set(rs_df["season_type"]), {"Regular Season"})
            self.assertEqual(set(po_df["season_type"]), {"Playoffs"})


if __name__ == "__main__":
    unittest.main()
