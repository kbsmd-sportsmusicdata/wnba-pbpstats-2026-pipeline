import sys
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_wnba_espn_2026 as espn  # noqa: E402


# --------------------------------------------------------------------- fixtures


def _event(
    game_id,
    date,
    home,
    away,
    *,
    home_score=None,
    away_score=None,
    completed=True,
    season_type=2,
    note=None,
    competitors="both",
):
    """One scoreboard event in ESPN's shape."""
    def competitor(team, home_away, score):
        return {
            "homeAway": home_away,
            "score": None if score is None else str(score),
            "team": {"id": team["id"], "abbreviation": team["abbr"], "displayName": team["name"]},
        }

    entries = []
    if competitors in ("both", "home_only"):
        entries.append(competitor(home, "home", home_score))
    if competitors in ("both", "away_only"):
        entries.append(competitor(away, "away", away_score))
    competition = {
        "date": f"{date}T23:00Z",
        "neutralSite": False,
        "status": {
            "period": 4,
            "type": {
                "name": "STATUS_FINAL" if completed else "STATUS_SCHEDULED",
                "completed": completed,
                "state": "post" if completed else "pre",
            },
        },
        "competitors": entries,
    }
    if note is not None:
        competition["notes"] = [{"headline": note}]
    return {
        "id": str(game_id),
        "date": f"{date}T23:00Z",
        "season": {"year": 2026, "type": season_type},
        "competitions": [competition],
    }


def _summary(home, away, home_stats, away_stats):
    def block(team, stats):
        return {
            "team": {"id": team["id"]},
            "statistics": [
                {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": f"{stats['fgm']}-{stats['fga']}"},
                {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "displayValue": f"{stats['fg3m']}-{stats['fg3a']}"},
                {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": f"{stats['ftm']}-{stats['fta']}"},
                {"name": "offensiveRebounds", "displayValue": str(stats["oreb"])},
                {"name": "defensiveRebounds", "displayValue": str(stats["dreb"])},
                {"name": "turnovers", "displayValue": str(stats["tov"])},
            ],
        }

    return {"boxscore": {"teams": [block(home, home_stats), block(away, away_stats)]}}


_TEAMS = [
    {"id": "1", "abbr": "TA", "name": "Team A"},
    {"id": "2", "abbr": "TB", "name": "Team B"},
    {"id": "3", "abbr": "TC", "name": "Team C"},
    {"id": "4", "abbr": "TD", "name": "Team D"},
]
_STATS = {"fgm": 30, "fga": 70, "fg3m": 7, "fg3a": 20, "ftm": 15, "fta": 18, "oreb": 9, "dreb": 28, "tov": 13}


def _synthetic_season():
    """A double round-robin over four teams: every team plays exactly six games."""
    events, summaries = [], {}
    day = 1
    game_number = 0
    for repeat in range(2):
        for i in range(len(_TEAMS)):
            for j in range(i + 1, len(_TEAMS)):
                home, away = (_TEAMS[i], _TEAMS[j]) if repeat == 0 else (_TEAMS[j], _TEAMS[i])
                game_id = 401800000 + game_number
                # Home wins the first meeting, away wins the second, so records spread out.
                home_score, away_score = (88, 80) if repeat == 0 else (79, 90)
                events.append(
                    _event(game_id, f"2026-05-{day:02d}", home, away, home_score=home_score, away_score=away_score)
                )
                summaries[str(game_id)] = _summary(home, away, _STATS, _STATS)
                game_number += 1
                day += 1
    return events, summaries


def _fake_fetcher(events, summaries):
    """Serve ESPN's scoreboard-by-date and summary-by-event from in-memory fixtures."""
    by_date = {}
    for event in events:
        date_key = event["date"][:10].replace("-", "")
        by_date.setdefault(date_key, []).append(event)
    calendar = sorted({event["date"][:10] for event in events})

    def fetcher(url, *, params=None):
        params = params or {}
        if url == espn.SUMMARY_URL:
            return summaries[str(params["event"])]
        # scoreboard
        dates = str(params.get("dates", ""))
        if dates == "2026":  # the seed request
            return {"leagues": [{"calendar": calendar}], "events": []}
        return {"events": by_date.get(dates, [])}

    return fetcher


# --------------------------------------------------------------------- unit tests


class ParseEventTest(unittest.TestCase):
    def test_regular_season_game_becomes_a_schedule_row(self):
        row = espn.parse_event(
            _event(401800001, "2026-08-11", _TEAMS[0], _TEAMS[1], home_score=84, away_score=78)
        )
        self.assertEqual(row["game_id"], "401800001")
        self.assertEqual(row["season_type"], 2)
        self.assertEqual(row["type_abbreviation"], "STD")
        self.assertTrue(row["status_type_completed"])
        self.assertEqual(row["game_date"], "2026-08-11")
        self.assertEqual((row["home_id"], row["home_abbreviation"]), ("1", "TA"))
        self.assertEqual((row["away_id"], row["away_score"]), ("2", 78))

    def test_all_star_and_exhibition_events_are_dropped(self):
        self.assertIsNone(
            espn.parse_event(_event(1, "2026-07-19", _TEAMS[0], _TEAMS[1], season_type=3))
        )

    def test_commissioners_cup_final_is_flagged_cc(self):
        row = espn.parse_event(
            _event(
                2,
                "2026-06-30",
                _TEAMS[0],
                _TEAMS[1],
                home_score=93,
                away_score=85,
                note="WNBA Commissioner's Cup Championship",
            )
        )
        self.assertEqual(row["type_abbreviation"], "CC")

    def test_event_missing_a_competitor_is_dropped(self):
        self.assertIsNone(
            espn.parse_event(_event(3, "2026-08-11", _TEAMS[0], _TEAMS[1], competitors="home_only"))
        )

    def test_a_scheduled_game_keeps_null_scores_and_incomplete_flag(self):
        row = espn.parse_event(
            _event(4, "2026-09-20", _TEAMS[0], _TEAMS[1], completed=False)
        )
        self.assertFalse(row["status_type_completed"])
        self.assertIsNone(row["home_score"])
        self.assertEqual(row["status_type_name"], "STATUS_SCHEDULED")


class ParseBoxStatisticsTest(unittest.TestCase):
    def test_combined_and_single_statistics_map_to_the_eight_fields(self):
        parsed = espn.parse_box_statistics(
            [
                {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "30-70"},
                {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "displayValue": "8-22"},
                {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "14-18"},
                {"name": "offensiveRebounds", "displayValue": "10"},
                {"name": "defensiveRebounds", "displayValue": "27"},
                {"name": "turnovers", "displayValue": "12"},
            ]
        )
        self.assertEqual(parsed["field_goals_made"], 30)
        self.assertEqual(parsed["field_goals_attempted"], 70)
        self.assertEqual(parsed["three_point_field_goals_made"], 8)
        self.assertEqual(parsed["free_throws_made"], 14)
        self.assertEqual(parsed["free_throws_attempted"], 18)
        self.assertEqual(parsed["offensive_rebounds"], 10)
        self.assertEqual(parsed["defensive_rebounds"], 27)
        self.assertEqual(parsed["turnovers"], 12)

    def test_alternate_single_value_names_and_missing_fields(self):
        parsed = espn.parse_box_statistics(
            [
                {"name": "fieldGoalsMade", "displayValue": "31"},
                {"name": "fieldGoalsAttempted", "displayValue": "69"},
                {"name": "totalTurnovers", "displayValue": "15"},
            ]
        )
        self.assertEqual(parsed["field_goals_made"], 31)
        self.assertEqual(parsed["field_goals_attempted"], 69)
        self.assertEqual(parsed["turnovers"], 15)
        # Fields ESPN did not send stay None so the caller can reject the game.
        self.assertIsNone(parsed["offensive_rebounds"])


class BuildFrameTest(unittest.TestCase):
    def test_team_box_has_two_directional_rows_with_a_winner_flag(self):
        rows = [espn.parse_event(_event(5, "2026-08-11", _TEAMS[0], _TEAMS[1], home_score=90, away_score=80))]
        boxscores = {"5": {"1": dict.fromkeys(espn.BOX_STAT_FIELDS, 10), "2": dict.fromkeys(espn.BOX_STAT_FIELDS, 10)}}
        frame = espn.build_team_box_frame(rows, boxscores)
        self.assertEqual(len(frame), 2)
        home = frame[frame["team_home_away"].eq("home")].iloc[0]
        away = frame[frame["team_home_away"].eq("away")].iloc[0]
        self.assertTrue(bool(home["team_winner"]))
        self.assertFalse(bool(away["team_winner"]))
        self.assertEqual(home["opponent_team_id"], "2")
        self.assertEqual(list(frame.columns), espn.TEAM_BOX_COLUMNS)

    def test_completed_game_without_a_box_score_is_an_error(self):
        rows = [espn.parse_event(_event(6, "2026-08-11", _TEAMS[0], _TEAMS[1], home_score=90, away_score=80))]
        with self.assertRaisesRegex(espn.ESPNFetchError, "missing box scores"):
            espn.build_team_box_frame(rows, {})

    def test_scheduled_games_do_not_appear_in_the_team_box(self):
        rows = [espn.parse_event(_event(7, "2026-09-20", _TEAMS[0], _TEAMS[1], completed=False))]
        self.assertTrue(espn.build_team_box_frame(rows, {}).empty)

    def test_reconcile_flags_an_unbalanced_schedule(self):
        events, _ = _synthetic_season()
        schedule = espn.build_schedule_frame([espn.parse_event(e) for e in events])
        self.assertTrue(espn.reconcile(schedule, expected_games_per_team=6)["reconciled"])
        self.assertFalse(espn.reconcile(schedule, expected_games_per_team=7)["reconciled"])


class RequestHeaderTest(unittest.TestCase):
    def test_headers_present_a_browser_user_agent(self):
        """ESPN's site API 403s a bare tool User-Agent, so this must stay browser-like."""
        headers = espn._request_headers()
        self.assertIn("Mozilla/5.0", headers["User-Agent"])
        self.assertIn("espn.com", headers["Referer"])

    def test_user_agent_is_overridable(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"ESPN_USER_AGENT": "custom/1.0"}):
            self.assertEqual(espn._request_headers()["User-Agent"], "custom/1.0")


class DiscoverDatesTest(unittest.TestCase):
    def test_dates_come_from_the_league_calendar(self):
        payload = {"leagues": [{"calendar": ["2026-05-02T00:00Z", "2026-05-01T00:00Z", "bogus"]}]}
        self.assertEqual(espn.discover_game_dates(payload), ["2026-05-01", "2026-05-02"])


# ------------------------------------------------------------------ integration


class BuildAndForecastIntegrationTest(unittest.TestCase):
    """The real proof: ESPN output flows through the forecast's own loaders."""

    def _team_history(self, path: Path):
        pd.DataFrame(
            [
                {
                    "season": 2026,
                    "franchise_id": f"franchise_{team['id']}",
                    "sportsdataverse_team_id": int(team["id"]),
                    "sportsdataverse_team_abbreviation": team["abbr"],
                    "sportsdataverse_team_name": team["name"],
                    "pbpstats_team_id": 1000 + int(team["id"]),
                    "pbpstats_team_abbreviation": team["abbr"],
                }
                for team in _TEAMS
            ]
        ).to_csv(path, index=False)

    def test_espn_output_is_a_drop_in_for_the_forecast_stages(self):
        import tempfile

        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.standings import build_current_standings
        from standings_playoff_forecast.team_game_layer import build_team_game_layer
        from standings_playoff_forecast.tiebreaks import rank_teams

        events, summaries = _synthetic_season()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "espn"
            manifest = espn.build(
                2026, root, expected_games_per_team=6, fetcher=_fake_fetcher(events, summaries)
            )
            self.assertTrue(manifest["diagnostics"]["reconciled"])
            self.assertEqual(manifest["diagnostics"]["games_completed"], 12)

            history_path = Path(tmp) / "team_history.csv"
            self._team_history(history_path)

            cfg = replace(
                load_season_config(2026),
                team_count=4,
                regular_season_games_per_team=6,
                playoff_qualifiers=2,
                sportsdataverse_data_root=str(root),
            )
            sources = load_forecast_sources(
                cfg,
                schedule_path=root / "schedule_2026.parquet",
                team_box_path=root / "team_box_2026.parquet",
                team_history_path=history_path,
                external_standings_path=root / "does_not_exist.parquet",
                pbp_team_features_path=root / "does_not_exist.csv",
            )

            # The two stages that read schedule and team_box most directly.
            team_games = build_team_game_layer(sources, cfg, cutoff=None)
            self.assertEqual(len(team_games), 24)  # 12 games x 2 directional rows
            self.assertTrue(team_games["pace_est"].notna().all())
            self.assertTrue(team_games["net_rating_est"].notna().all())

            standings = build_current_standings(team_games, cfg)
            ranked = rank_teams(
                standings.rename(columns={"point_differential": "point_differential"}),
                team_games,
                cfg,
            )
            self.assertEqual(len(standings), 4)
            self.assertEqual(len(ranked.ordered_team_ids), 4)
            # Every team played its six games; the ledger reconciles.
            self.assertEqual(int(standings["games_played"].sum()), 24)


if __name__ == "__main__":
    unittest.main()
