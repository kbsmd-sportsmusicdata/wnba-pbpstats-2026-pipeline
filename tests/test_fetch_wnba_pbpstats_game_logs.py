import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_wnba_pbpstats_game_logs_2026 as gl  # noqa: E402


# Two teams, four players, three completed games -- the smallest shape that exercises the
# home/away spine, the identity injection, and the incremental checkpoint. Ids mirror the real
# pbpstats id spaces (team 1611661xxx, player short ids).
_GAMES = {
    "results": [
        {"GameId": "1022600001", "Date": "2026-05-08", "HomeTeamId": "1611661313", "AwayTeamId": "1611661323",
         "HomePoints": 106, "AwayPoints": 75, "HomePossessions": 87, "AwayPossessions": 88,
         "HomeTeamAbbreviation": "NYL", "AwayTeamAbbreviation": "CON"},
        {"GameId": "1022600002", "Date": "2026-05-10", "HomeTeamId": "1611661323", "AwayTeamId": "1611661313",
         "HomePoints": 80, "AwayPoints": 90, "HomePossessions": 84, "AwayPossessions": 85,
         "HomeTeamAbbreviation": "CON", "AwayTeamAbbreviation": "NYL"},
    ],
}
_NEW_GAME = {"GameId": "1022600003", "Date": "2026-05-12", "HomeTeamId": "1611661313", "AwayTeamId": "1611661323",
             "HomePoints": 95, "AwayPoints": 88, "HomePossessions": 83, "AwayPossessions": 83,
             "HomeTeamAbbreviation": "NYL", "AwayTeamAbbreviation": "CON"}

_TOTALS_PLAYER = {
    "single_row_table_data": {},
    "multi_row_table_data": [
        {"EntityId": "1627668", "Name": "Breanna Stewart", "TeamId": "1611661313", "TeamAbbreviation": "NYL", "GamesPlayed": 2},
        {"EntityId": "3", "Name": "Sabrina Ionescu", "TeamId": "1611661313", "TeamAbbreviation": "NYL", "GamesPlayed": 2},
        {"EntityId": "1610", "Name": "Alyssa Thomas", "TeamId": "1611661323", "TeamAbbreviation": "CON", "GamesPlayed": 2},
        {"EntityId": "203833", "Name": "Chelsea Gray", "TeamId": "1611661323", "TeamAbbreviation": "CON", "GamesPlayed": 2},
    ],
}
_TOTALS_TEAM = {
    "single_row_table_data": {},
    "multi_row_table_data": [
        {"EntityId": "1611661313", "TeamId": "1611661313", "Name": "NYL", "TeamAbbreviation": "NYL", "GamesPlayed": 2},
        {"EntityId": "1611661323", "TeamId": "1611661323", "Name": "CON", "TeamAbbreviation": "CON", "GamesPlayed": 2},
    ],
}


def _player_log(player_team, opponent, games):
    """One per-game row per game the player's team played, with a stat or two present."""
    rows = []
    for g in games:
        if player_team not in (g["HomeTeamId"], g["AwayTeamId"]):
            continue
        is_home = g["HomeTeamId"] == player_team
        rows.append({
            "GameId": g["GameId"], "Date": g["Date"],
            "Team": g["HomeTeamAbbreviation"] if is_home else g["AwayTeamAbbreviation"],
            "Opponent": g["AwayTeamAbbreviation"] if is_home else g["HomeTeamAbbreviation"],
            "Points": 18, "Assists": 5,
        })
    return {"single_row_table_data": {}, "multi_row_table_data": rows}


_PLAYER_TEAM = {"1627668": "1611661313", "3": "1611661313", "1610": "1611661323", "203833": "1611661323"}


def _make_fetcher(games_payload, *, fail_players=frozenset()):
    def fetcher(endpoint, params=None):
        params = params or {}
        if endpoint.endswith("/get-games/wnba"):
            return games_payload
        if endpoint.endswith("/get-totals/wnba"):
            return _TOTALS_PLAYER if params.get("Type") == "Player" else _TOTALS_TEAM
        if "/get-game-logs/" in endpoint:
            eid, etype = str(params["EntityId"]), params["EntityType"]
            if etype == "Player":
                if eid in fail_players:
                    raise gl.PBPStatsGameLogError("500 Server Error: Internal Server Error")
                return _player_log(_PLAYER_TEAM[eid], None, games_payload["results"])
            return _player_log(eid, None, games_payload["results"])  # team: rows for its own games
        raise AssertionError(f"unexpected endpoint {endpoint}")

    return fetcher


class LookupTest(unittest.TestCase):
    def test_player_lookup_columns_and_ids(self):
        lookup = gl.build_player_lookup(_TOTALS_PLAYER)
        self.assertEqual(list(lookup.columns), ["player_id", "player_name", "team_id", "team_abbreviation", "games_played"])
        self.assertEqual(len(lookup), 4)
        stewart = lookup[lookup["player_id"] == "1627668"].iloc[0]
        self.assertEqual(stewart["team_abbreviation"], "NYL")
        self.assertEqual(int(stewart["games_played"]), 2)

    def test_duplicate_player_ids_fail_closed(self):
        payload = {"multi_row_table_data": [
            {"EntityId": "5", "Name": "A"}, {"EntityId": "5", "Name": "B"},
        ]}
        with self.assertRaisesRegex(gl.PBPStatsGameLogError, "duplicate player ids"):
            gl.build_player_lookup(payload)

    def test_games_dimension_is_the_keyed_spine(self):
        dim = gl.build_games_dimension(_GAMES)
        self.assertEqual(len(dim), 2)
        self.assertEqual(dim["game_id"].tolist(), ["1022600001", "1022600002"])
        first = dim.iloc[0]
        self.assertEqual(first["home_team_abbreviation"], "NYL")
        self.assertEqual(int(first["home_points"]), 106)

    def test_games_dimension_rejects_duplicate_game_ids(self):
        payload = {"results": [
            dict(_GAMES["results"][0]),
            dict(_GAMES["results"][0], Date="2026-05-09"),
        ]}
        with self.assertRaisesRegex(gl.PBPStatsGameLogError, "duplicate game ids"):
            gl.build_games_dimension(payload)


class AnnotateTest(unittest.TestCase):
    def test_identity_is_injected_at_the_end_of_each_row(self):
        identity = {"PlayerId": "203833", "PlayerName": "Chelsea Gray", "TeamId": "1611661323", "TeamAbbreviation": "CON"}
        rows = gl.annotate_log_rows(_player_log("1611661323", None, _GAMES["results"]), identity, gl.PLAYER_IDENTITY_FIELDS)
        self.assertEqual(len(rows), 2)
        self.assertEqual(list(rows[0].keys())[-4:], list(gl.PLAYER_IDENTITY_FIELDS))
        self.assertEqual(rows[0]["PlayerId"], "203833")
        # The row's own Team/Opponent (game context) survive alongside the injected current team.
        self.assertEqual(rows[0]["Team"], "CON")
        self.assertEqual(rows[0]["TeamAbbreviation"], "CON")


class MergeTest(unittest.TestCase):
    def test_dedupe_keeps_last_row_per_key(self):
        rows = [
            {"PlayerId": "1", "GameId": "g1", "Points": 10},
            {"PlayerId": "1", "GameId": "g1", "Points": 12},  # revised, supersedes
            {"PlayerId": "1", "GameId": "g2", "Points": 8},
        ]
        deduped = gl.dedupe_rows(rows, ("PlayerId", "GameId"))
        self.assertEqual(len(deduped), 2)
        g1 = next(r for r in deduped if r["GameId"] == "g1")
        self.assertEqual(g1["Points"], 12)

    def test_merge_replaces_only_the_refreshed_entitys_rows(self):
        existing = [
            {"PlayerId": "1", "GameId": "g1", "Points": 10},
            {"PlayerId": "2", "GameId": "g1", "Points": 20},
        ]
        refreshed = {"1": [{"PlayerId": "1", "GameId": "g1", "Points": 11}, {"PlayerId": "1", "GameId": "g2", "Points": 9}]}
        merged = gl.merge_entity_rows(existing, refreshed, entity_field="PlayerId")
        # Player 2 untouched; player 1 fully replaced with two fresh rows.
        self.assertEqual(sorted(r["PlayerId"] for r in merged), ["1", "1", "2"])
        p1 = {r["GameId"]: r["Points"] for r in merged if r["PlayerId"] == "1"}
        self.assertEqual(p1, {"g1": 11, "g2": 9})


class AffectedTest(unittest.TestCase):
    def test_first_build_marks_every_entity_affected(self):
        lookup = gl.build_player_lookup(_TOTALS_PLAYER)
        affected = gl.identify_affected_entities(
            lookup=lookup, id_column="player_id", existing_rows=[], entity_field="PlayerId",
            entities_in_new_games=set(), prior_failures=set(),
        )
        self.assertEqual(len(affected), 4)

    def test_incremental_targets_only_new_game_teams_and_failures(self):
        lookup = gl.build_player_lookup(_TOTALS_PLAYER)
        # Two NYL players already have complete rows; nothing new, nothing failed -> nobody refetched.
        existing = [
            {"PlayerId": "1627668", "GameId": "1022600001", "Points": 1}, {"PlayerId": "1627668", "GameId": "1022600002", "Points": 1},
            {"PlayerId": "3", "GameId": "1022600001", "Points": 1}, {"PlayerId": "3", "GameId": "1022600002", "Points": 1},
            {"PlayerId": "1610", "GameId": "1022600001", "Points": 1}, {"PlayerId": "1610", "GameId": "1022600002", "Points": 1},
            {"PlayerId": "203833", "GameId": "1022600001", "Points": 1}, {"PlayerId": "203833", "GameId": "1022600002", "Points": 1},
        ]
        quiet = gl.identify_affected_entities(
            lookup=lookup, id_column="player_id", existing_rows=existing, entity_field="PlayerId",
            entities_in_new_games=set(), prior_failures=set(),
        )
        self.assertEqual(quiet, [])
        # A failure is always retried; a player flagged by a new-game team is refetched.
        targeted = gl.identify_affected_entities(
            lookup=lookup, id_column="player_id", existing_rows=existing, entity_field="PlayerId",
            entities_in_new_games={"3"}, prior_failures={"203833"},
        )
        self.assertEqual(targeted, ["203833", "3"])


class BuildIntegrationTest(unittest.TestCase):
    def test_first_build_then_incremental_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "logs"

            # First build: one player fails transiently and is recorded, not fatal.
            first = gl.build("2026", "Regular Season", root, fetcher=_make_fetcher(_GAMES, fail_players={"203833"}), sleep_seconds=0)
            players = first["players"]
            self.assertTrue(players["is_first_build"])
            self.assertEqual(players["affected_players"], 4)
            self.assertEqual(players["refreshed_players"], 3)
            self.assertEqual(players["failed_players"], 1)
            self.assertEqual(players["combined_players"], 3)
            self.assertEqual(first["teams"]["combined_teams"], 2)

            failures = json.loads((root / "player_game_logs_failures.json").read_text())
            self.assertEqual([f["player_id"] for f in failures], ["203833"])
            # Raw per-entity responses and the combined pair are on disk.
            self.assertTrue((root / "raw" / "player_1627668_game_logs.json").exists())
            self.assertTrue((root / "player_game_logs_wnba_2026_regular_season.csv").exists())
            combined = json.loads((root / "player_game_logs_wnba_2026_regular_season.json").read_text())
            keys = {(r["PlayerId"], r["GameId"]) for r in combined}
            self.assertEqual(len(keys), len(combined))  # PlayerId + GameId is unique

            # Incremental run: a new game appears and the prior failure now succeeds.
            games_v2 = {"results": _GAMES["results"] + [_NEW_GAME]}
            second = gl.build("2026", "Regular Season", root, fetcher=_make_fetcher(games_v2), sleep_seconds=0)
            p2 = second["players"]
            self.assertFalse(p2["is_first_build"])
            self.assertEqual(p2["new_game_ids"], 1)
            self.assertEqual(p2["failed_players"], 0)
            self.assertEqual(p2["combined_players"], 4)  # Chelsea Gray recovered
            self.assertEqual(p2["combined_game_ids"], 3)
            self.assertEqual(json.loads((root / "player_game_logs_failures.json").read_text()), [])
            combined2 = json.loads((root / "player_game_logs_wnba_2026_regular_season.json").read_text())
            self.assertTrue(any(r["PlayerId"] == "203833" for r in combined2))
            keys2 = {(r["PlayerId"], r["GameId"]) for r in combined2}
            self.assertEqual(len(keys2), len(combined2))


if __name__ == "__main__":
    unittest.main()
