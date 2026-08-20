import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_wnba_pbpstats_forecast_2026 as pbp  # noqa: E402


# Four teams, pbpstats id -> ESPN id, mirroring the team_history crosswalk shape.
_TEAMS = [
    {"pbp": "1611661301", "espn": "1", "abbr": "AAA"},
    {"pbp": "1611661302", "espn": "2", "abbr": "BBB"},
    {"pbp": "1611661303", "espn": "3", "abbr": "CCC"},
    {"pbp": "1611661304", "espn": "4", "abbr": "DDD"},
]
_STATS = {"FG2M": 28, "FG2A": 55, "FG3M": 8, "FG3A": 22, "FtPoints": 14, "FTA": 18, "OffRebounds": 9, "DefRebounds": 28, "Turnovers": 13}


def _team_history(path: Path):
    pd.DataFrame(
        [
            {
                "season": 2026,
                "franchise_id": f"f_{t['espn']}",
                "sportsdataverse_team_id": int(t["espn"]),
                "sportsdataverse_team_abbreviation": t["abbr"],
                "sportsdataverse_team_name": t["abbr"],
                "pbpstats_team_id": int(t["pbp"]),
                "pbpstats_team_abbreviation": t["abbr"],
            }
            for t in _TEAMS
        ]
    ).to_csv(path, index=False)


def _sdv_schedule(path: Path):
    """A double round-robin plus one unplayed round: six fixtures per team."""
    rows = []
    gid = 0
    day = 1
    espn = {t["pbp"]: t["espn"] for t in _TEAMS}
    abbr = {t["pbp"]: t["abbr"] for t in _TEAMS}

    def fixture(home, away, date, completed):
        nonlocal gid
        gid += 1
        rows.append(
            {
                "game_id": f"40180{gid:04d}",
                "game_date": date,
                "season": 2026,
                "season_type": 2,
                "type_abbreviation": "STD",
                "status_type_name": "STATUS_FINAL" if completed else "STATUS_SCHEDULED",
                "status_type_completed": completed,
                "status_period": 4,
                "format_regulation_periods": 4,
                "neutral_site": False,
                "home_id": int(espn[home]),
                "home_abbreviation": abbr[home],
                "home_display_name": abbr[home],
                "home_score": 0,
                "away_id": int(espn[away]),
                "away_abbreviation": abbr[away],
                "away_display_name": abbr[away],
                "away_score": 0,
            }
        )

    teams = [t["pbp"] for t in _TEAMS]
    # Two completed round-robins (all fixtures marked scheduled in SDV, since its results lag),
    # then one more round left genuinely unplayed.
    for repeat in range(2):
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                home, away = (teams[i], teams[j]) if repeat % 2 == 0 else (teams[j], teams[i])
                fixture(home, away, f"2026-05-{day:02d}", completed=False)
                day += 1
    pd.DataFrame(rows).to_parquet(path, index=False)
    return rows


def _get_games_payload():
    """pbpstats get-games covering the first two rounds (completed), fresher than SDV."""
    results = []
    gid = 0
    day = 1
    teams = [t["pbp"] for t in _TEAMS]
    abbr = {t["pbp"]: t["abbr"] for t in _TEAMS}
    for repeat in range(1):  # only the first round is complete
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                home, away = (teams[i], teams[j]) if repeat % 2 == 0 else (teams[j], teams[i])
                gid += 1
                hs, as_ = (88, 80) if repeat == 0 else (79, 90)
                results.append(
                    {
                        "GameId": f"10226{gid:05d}",
                        "Date": f"2026-05-{day:02d}",
                        "HomeTeamId": home,
                        "AwayTeamId": away,
                        "HomePoints": hs,
                        "AwayPoints": as_,
                        "HomePossessions": 82,
                        "AwayPossessions": 82,
                        "HomeTeamAbbreviation": abbr[home],
                        "AwayTeamAbbreviation": abbr[away],
                    }
                )
                day += 1
    return {"results": results}


def _team_log_payload(pbp_team_id, games):
    """Synthetic per-game four-factor rows for one team, keyed to get-games GameIds."""
    abbr = {t["pbp"]: t["abbr"] for t in _TEAMS}
    rows = []
    for g in games["results"]:
        if pbp_team_id not in (g["HomeTeamId"], g["AwayTeamId"]):
            continue
        opponent = g["AwayTeamId"] if pbp_team_id == g["HomeTeamId"] else g["HomeTeamId"]
        rows.append({"GameId": g["GameId"], "Date": g["Date"], "Opponent": abbr[opponent], "Minutes": "40:00", **_STATS})
    return {"multi_row_table_data": rows}


def _fake_fetcher(games):
    def fetcher(endpoint, params=None):
        params = params or {}
        if endpoint.startswith("/get-games/"):
            return games
        if endpoint.startswith("/get-game-logs/"):
            return _team_log_payload(str(params["EntityId"]), games)
        raise AssertionError(f"unexpected endpoint {endpoint}")

    return fetcher


class CrosswalkTest(unittest.TestCase):
    def test_maps_pbpstats_ids_to_espn_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "team_history.csv"
            _team_history(path)
            crosswalk = pbp.team_crosswalk(pd.read_csv(path), season=2026)
        self.assertEqual(crosswalk["1611661301"], "1")
        self.assertEqual(len(crosswalk), 4)

    def test_missing_columns_fail_closed(self):
        with self.assertRaisesRegex(pbp.PBPStatsFetchError, "missing required columns"):
            pbp.team_crosswalk(pd.DataFrame({"season": [2026]}))


class ParseTest(unittest.TestCase):
    def test_four_factor_mapping_matches_a_real_game_log_row(self):
        """Pinned against a real Connecticut game-log row from the pbpstats API."""
        real_row = {
            "GameId": "1022600001",
            "FG2M": 28, "FG2A": 61, "FG3M": 4, "FG3A": 22,
            "FtPoints": 7, "FTA": 15, "OffRebounds": 18, "DefRebounds": 22, "Turnovers": 17,
        }
        parsed = pbp.parse_team_game_log_stats([real_row])["1022600001"]
        self.assertEqual(parsed["field_goals_made"], 32)  # FG2M + FG3M
        self.assertEqual(parsed["field_goals_attempted"], 83)  # FG2A + FG3A
        self.assertEqual(parsed["three_point_field_goals_made"], 4)
        self.assertEqual(parsed["free_throws_made"], 7)  # FtPoints
        self.assertEqual(parsed["free_throws_attempted"], 15)
        self.assertEqual(parsed["offensive_rebounds"], 18)
        self.assertEqual(parsed["defensive_rebounds"], 22)
        self.assertEqual(parsed["turnovers"], 17)

    def test_index_games_rejects_teams_outside_the_crosswalk(self):
        games = [{"GameId": "1", "Date": "2026-05-01", "HomeTeamId": "999", "AwayTeamId": "1611661302",
                  "HomePoints": 80, "AwayPoints": 70}]
        with self.assertRaisesRegex(pbp.PBPStatsFetchError, "outside the crosswalk"):
            pbp.index_games(games, {"1611661302": "2"})

    def test_index_games_rejects_duplicates(self):
        game = {"GameId": "1", "Date": "2026-05-01", "HomeTeamId": "1611661301", "AwayTeamId": "1611661302",
                "HomePoints": 80, "AwayPoints": 70}
        with self.assertRaisesRegex(pbp.PBPStatsFetchError, "duplicate"):
            pbp.index_games([game, dict(game, GameId="2")], {"1611661301": "1", "1611661302": "2"})


class OverlayTest(unittest.TestCase):
    def test_overlay_marks_matched_fixtures_complete_and_aligns_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched_path = Path(tmp) / "schedule.parquet"
            _sdv_schedule(sched_path)
            schedule = pd.read_parquet(sched_path)
            crosswalk = {t["pbp"]: t["espn"] for t in _TEAMS}
            games = _get_games_payload()
            overlaid, matched = pbp.overlay_schedule(schedule, pbp.index_games(games["results"], crosswalk))

        completed = overlaid[overlaid["status_type_completed"].map(pbp._is_true)]
        self.assertEqual(len(completed), 6)  # one completed round
        self.assertEqual(len(matched), 6)
        # A completed fixture carries real scores, not the placeholder zeros.
        self.assertTrue((completed["home_score"] + completed["away_score"] > 0).all())

    def test_pbpstats_is_the_completion_authority_over_native_sdv_finals(self):
        """An SDV fixture marked final natively but absent from pbpstats is reset to not-complete.

        This is the regression for the forecast's completed-game ledger parity failure: a refreshed
        SportsDataverse schedule reported games final ahead of the (committed) pbpstats feed, and
        inheriting those flags left completed games with no pbpstats box.
        """
        with tempfile.TemporaryDirectory() as tmp:
            sched_path = Path(tmp) / "schedule.parquet"
            _sdv_schedule(sched_path)
            schedule = pd.read_parquet(sched_path)
            # SportsDataverse marks a fixture pbpstats does NOT cover as already final, with a score.
            schedule.loc[schedule.index[-1], ["status_type_completed", "status_type_name", "home_score", "away_score"]] = [
                True,
                "STATUS_FINAL",
                77,
                70,
            ]
            crosswalk = {t["pbp"]: t["espn"] for t in _TEAMS}
            games = _get_games_payload()  # covers only the first round; not that last fixture
            overlaid, matched = pbp.overlay_schedule(schedule, pbp.index_games(games["results"], crosswalk))

        completed = overlaid[overlaid["status_type_completed"].map(pbp._is_true)]
        # Only the six pbpstats-covered games are completed; the native SDV final is reset.
        self.assertEqual(len(completed), 6)
        self.assertEqual(set(completed["game_id"]), set(matched))
        # Every completed game is one pbpstats matched (so it will have a box score).
        self.assertTrue(all(pbp._norm_id(gid) in matched for gid in completed["game_id"]))


class GameLogsFetcherTest(unittest.TestCase):
    """The committed-data fetcher must serve the same shapes as the live API, keyed per team."""

    def _write_committed(self, root: Path):
        import json as _json

        games = _get_games_payload()
        root.mkdir(parents=True, exist_ok=True)
        (root / "get_games_wnba_2026_regular_season.json").write_text(_json.dumps(games), encoding="utf-8")
        # Team logs: one flat list across all teams, each row tagged with its pbpstats TeamId,
        # exactly as the game-log ingest commits them.
        rows = []
        for team in _TEAMS:
            for g in games["results"]:
                if team["pbp"] in (g["HomeTeamId"], g["AwayTeamId"]):
                    rows.append({"GameId": g["GameId"], "Date": g["Date"], "TeamId": team["pbp"], **_STATS})
        (root / "team_game_logs_wnba_2026_regular_season.json").write_text(_json.dumps(rows), encoding="utf-8")
        return games

    def test_serves_games_and_per_team_logs_from_committed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game_logs"
            games = self._write_committed(root)
            fetcher = pbp.game_logs_fetcher(root, "Regular Season")

            served_games = fetcher("/get-games/wnba", {"Season": "2026", "SeasonType": "Regular Season"})
            self.assertEqual(len(served_games["results"]), len(games["results"]))

            team = _TEAMS[0]["pbp"]
            log = fetcher("/get-game-logs/wnba", {"EntityId": team, "EntityType": "Team"})
            self.assertTrue(log["multi_row_table_data"])
            self.assertTrue(all(str(r["TeamId"]) == team for r in log["multi_row_table_data"]))

    def test_missing_committed_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(pbp.PBPStatsFetchError, "committed game-log file is missing"):
                pbp.game_logs_fetcher(Path(tmp), "Regular Season")

    def test_build_through_committed_fetcher_reconciles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "team_history.csv"
            schedule = root / "sdv_schedule.parquet"
            _team_history(history)
            _sdv_schedule(schedule)
            self._write_committed(root / "game_logs")

            manifest = pbp.build(
                "2026", "Regular Season", root / "out",
                sportsdataverse_schedule=schedule,
                team_history_path=history,
                expected_games_per_team=None,
                fetcher=pbp.game_logs_fetcher(root / "game_logs", "Regular Season"),
            )
            self.assertEqual(manifest["diagnostics"]["games_completed"], 6)
            self.assertEqual(manifest["matched_games"], 6)


class BuildIntegrationTest(unittest.TestCase):
    def test_build_output_drops_into_the_forecast_stages(self):
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.standings import build_current_standings
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "team_history.csv"
            schedule = root / "sdv_schedule.parquet"
            _team_history(history)
            _sdv_schedule(schedule)
            games = _get_games_payload()

            data_root = root / "pbpstats"
            manifest = pbp.build(
                "2026",
                "Regular Season",
                data_root,
                sportsdataverse_schedule=schedule,
                team_history_path=history,
                expected_games_per_team=None,
                fetcher=_fake_fetcher(games),
            )
            self.assertEqual(manifest["diagnostics"]["games_completed"], 6)
            self.assertEqual(manifest["diagnostics"]["coverage_through"], "2026-05-06")

            cfg = replace(
                load_season_config(2026),
                team_count=4,
                regular_season_games_per_team=6,
                playoff_qualifiers=2,
                sportsdataverse_data_root=str(data_root),
            )
            sources = load_forecast_sources(
                cfg,
                schedule_path=data_root / "schedule_2026.parquet",
                team_box_path=data_root / "team_box_2026.parquet",
                team_history_path=history,
                external_standings_path=data_root / "absent.parquet",
                pbp_team_features_path=data_root / "absent.csv",
            )
            team_games = build_team_game_layer(sources, cfg, cutoff=None)
            self.assertEqual(len(team_games), 12)  # 6 completed games x 2 rows
            self.assertTrue(team_games["pace_est"].notna().all())
            self.assertTrue(team_games["net_rating_est"].notna().all())

            standings = build_current_standings(team_games, cfg)
            self.assertEqual(len(standings), 4)
            self.assertEqual(int(standings["games_played"].sum()), 12)


if __name__ == "__main__":
    unittest.main()
