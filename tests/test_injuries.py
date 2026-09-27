import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from injuries.forecast_context import build_forecast_availability_context  # noqa: E402
from injuries.report import (  # noqa: E402
    attach_player_ids,
    build_current_report,
    build_team_availability,
    classify_absence_reason,
    latest_as_of,
    mentions_season_ending,
    normalize_availability_status,
    normalize_injuries,
    normalize_player_name,
)


def _raw_row(**overrides):
    row = {
        "as_of_date": "2026-09-26",
        "season": 2026,
        "team_id": 11,
        "team_display_name": "Phoenix Mercury",
        "injury_id": 1,
        "athlete_id": 1628276,
        "athlete_display_name": "Kelsey Plum",
        "athlete_position": "G",
        "status": "Out",
        "injury_date": "2026-08-31T14:46Z",
        "type_name": "INJURY_STATUS_OUT",
        "detail_type": "Lower Leg",
        "detail_side": "Left",
        "detail_return_date": "2027-05-01",
        "detail_fantasy_status": "OFS",
        "short_comment": "out for the year",
    }
    row.update(overrides)
    return row


class AvailabilityNormalizationTest(unittest.TestCase):
    def test_out_for_season_from_fantasy_status(self):
        self.assertEqual(normalize_availability_status("Out", "OFS"), "Out for season")

    def test_game_time_decision_is_day_to_day(self):
        self.assertEqual(normalize_availability_status("Out", "GTD"), "Day-to-day")

    def test_day_to_day_status(self):
        self.assertEqual(normalize_availability_status("Day-To-Day", ""), "Day-to-day")

    def test_plain_out(self):
        self.assertEqual(normalize_availability_status("Out", "OUT"), "Out")

    def test_unknown_status_defaults_to_out_not_dropped(self):
        # A player on the injury feed is never fully available; an unknown code must not vanish.
        self.assertEqual(normalize_availability_status("", ""), "Out")


class AbsenceClassificationTest(unittest.TestCase):
    def test_body_part_is_injury(self):
        self.assertEqual(classify_absence_reason("Knee"), "injury")

    def test_illness_and_concussion_are_injuries(self):
        self.assertEqual(classify_absence_reason("Illness"), "injury")
        self.assertEqual(classify_absence_reason("Concussion"), "injury")

    def test_housekeeping_is_non_injury(self):
        for reason in ("Not Injury Related", "Personal", "Coach's Decision", "Rest"):
            self.assertEqual(classify_absence_reason(reason), "non_injury")

    def test_blank_is_unspecified(self):
        self.assertEqual(classify_absence_reason(""), "unspecified")


class NameNormalizationTest(unittest.TestCase):
    def test_accents_and_punctuation_folded(self):
        self.assertEqual(normalize_player_name("A'ja Wilson"), "ajawilson")
        self.assertEqual(normalize_player_name("Luisa Geiselsöder"), "luisageiselsoder")


class SeasonEndingDetectionTest(unittest.TestCase):
    def test_phrases_matched_and_traps_rejected(self):
        self.assertTrue(mentions_season_ending("will be sidelined for the rest of the season"))
        self.assertTrue(mentions_season_ending("out for the 2026 WNBA season"))
        self.assertTrue(mentions_season_ending("suffered a season-ending injury"))
        # Single-game phrasings that merely contain "season"/"game" must not match.
        self.assertFalse(mentions_season_ending("out for the season finale Thursday"))
        self.assertFalse(mentions_season_ending("ruled out for the remainder of Thursday's game"))
        self.assertFalse(mentions_season_ending("out for Thursday's game against the Sky"))

    def test_out_status_upgraded_to_season_ending_by_comment(self):
        # ESPN left the status as OUT, but the comment confirms a season-ender (the NaLyssa case).
        raw = pd.DataFrame(
            [
                _raw_row(
                    athlete_id=99,
                    detail_fantasy_status="OUT",
                    detail_type="Leg",
                    short_comment="Smith will be sidelined for the rest of the season after a leg injury.",
                )
            ]
        )
        current = build_current_report(raw)
        row = current.iloc[0]
        self.assertEqual(row["availability_status"], "Out for season")
        self.assertTrue(row["is_out_for_season"])

    def test_placeholder_return_date_is_blanked(self):
        # ESPN's 2027-05-01 next-season placeholder is not a real ETA and must not be published.
        raw = pd.DataFrame(
            [
                _raw_row(athlete_id=1, detail_fantasy_status="OUT", detail_return_date="2027-05-01"),
                _raw_row(athlete_id=2, detail_fantasy_status="OUT", detail_return_date="2026-09-27"),
            ]
        )
        current = build_current_report(raw).set_index("athlete_id")
        self.assertEqual(current.loc[1, "expected_return_date"], "")  # placeholder blanked
        self.assertEqual(current.loc[2, "expected_return_date"], "2026-09-27")  # real in-season ETA kept

    def test_return_date_placeholder_does_not_trigger_season_ending(self):
        # A short-term OUT with the 2027-05-01 placeholder return date must stay "Out", not OFS.
        raw = pd.DataFrame(
            [
                _raw_row(
                    athlete_id=98,
                    detail_fantasy_status="OUT",
                    detail_type="Ankle",
                    detail_return_date="2027-05-01",
                    short_comment="Player (ankle) is out for Thursday's game against Golden State.",
                )
            ]
        )
        row = build_current_report(raw).iloc[0]
        self.assertEqual(row["availability_status"], "Out")
        self.assertFalse(row["is_out_for_season"])


class CurrentReportTest(unittest.TestCase):
    def test_latest_snapshot_and_one_row_per_player(self):
        raw = pd.DataFrame(
            [
                _raw_row(as_of_date="2026-09-25", detail_fantasy_status="OUT", detail_type="Ankle"),
                _raw_row(as_of_date="2026-09-26", detail_fantasy_status="OFS", detail_type="Lower Leg"),
                # A second active listing for the same athlete on the current date: the more
                # limiting status must win.
                _raw_row(
                    as_of_date="2026-09-26",
                    injury_id=2,
                    detail_fantasy_status="GTD",
                    detail_type="Illness",
                    injury_date="2026-09-20T00:00Z",
                ),
            ]
        )
        current = build_current_report(raw)
        self.assertEqual(latest_as_of(normalize_injuries(raw)), "2026-09-26")
        self.assertEqual(len(current), 1)
        row = current.iloc[0]
        self.assertEqual(row["availability_status"], "Out for season")
        self.assertTrue(row["is_out_for_season"])
        self.assertTrue(row["is_out"])
        self.assertEqual(row["team_abbreviation"], "PHX")

    def test_team_abbreviation_maps_expansion_teams(self):
        raw = pd.DataFrame(
            [
                _raw_row(athlete_id=1, team_id=129689, team_display_name="Golden State Valkyries"),
                _raw_row(athlete_id=2, team_id=132052, team_display_name="Portland Fire"),
                _raw_row(athlete_id=3, team_id=131935, team_display_name="Toronto Tempo"),
            ]
        )
        current = build_current_report(raw)
        self.assertEqual(
            set(current["team_abbreviation"]),
            {"GSV", "PDX", "TOR"},
        )

    def test_empty_input_yields_empty_frame(self):
        self.assertTrue(build_current_report(pd.DataFrame()).empty)


class PlayerIdResolutionTest(unittest.TestCase):
    def setUp(self):
        self.crosswalk = pd.DataFrame(
            {
                "player_id": ["1628276", "203400", "espn:9999"],
                "player_name": ["Kelsey Plum", "Skylar Diggins", "Source Only"],
                "espn_athlete_id": [3065570, 2529622, 9999],
            }
        )

    def test_exact_espn_id_match(self):
        report = build_current_report(pd.DataFrame([_raw_row(athlete_id=3065570)]))
        resolved = attach_player_ids(report, self.crosswalk)
        self.assertEqual(resolved.iloc[0]["player_id_match"], "espn_athlete_id")
        self.assertEqual(int(resolved.iloc[0]["pbpstats_player_id"]), 1628276)

    def test_name_fallback_when_id_absent(self):
        report = build_current_report(
            pd.DataFrame([_raw_row(athlete_id=111111, athlete_display_name="Skylar Diggins")])
        )
        resolved = attach_player_ids(report, self.crosswalk)
        self.assertEqual(resolved.iloc[0]["player_id_match"], "normalized_name")
        self.assertEqual(int(resolved.iloc[0]["pbpstats_player_id"]), 203400)

    def test_unmatched_player_kept_with_null_id(self):
        report = build_current_report(
            pd.DataFrame([_raw_row(athlete_id=222222, athlete_display_name="Unknown Rookie")])
        )
        resolved = attach_player_ids(report, self.crosswalk)
        self.assertEqual(resolved.iloc[0]["player_id_match"], "unmatched")
        self.assertTrue(pd.isna(resolved.iloc[0]["pbpstats_player_id"]))

    def test_missing_crosswalk_is_not_fatal(self):
        report = build_current_report(pd.DataFrame([_raw_row()]))
        resolved = attach_player_ids(report, pd.DataFrame())
        self.assertEqual(resolved.iloc[0]["player_id_match"], "unmatched")


class TeamAvailabilityTest(unittest.TestCase):
    def test_counts_and_names(self):
        raw = pd.DataFrame(
            [
                _raw_row(athlete_id=1, athlete_display_name="Star Out", detail_fantasy_status="OFS", detail_type="Knee"),
                _raw_row(athlete_id=2, athlete_display_name="Role Out", detail_fantasy_status="OUT", detail_type="Ankle"),
                _raw_row(
                    athlete_id=3,
                    athlete_display_name="Nat Team",
                    detail_fantasy_status="OUT",
                    detail_type="Not Injury Related",
                ),
                _raw_row(athlete_id=4, athlete_display_name="Maybe Plays", status="Day-To-Day", detail_fantasy_status="GTD"),
            ]
        )
        team = build_team_availability(build_current_report(raw))
        self.assertEqual(len(team), 1)
        row = team.iloc[0]
        self.assertEqual(row["team_abbreviation"], "PHX")
        self.assertEqual(row["players_listed"], 4)
        self.assertEqual(row["players_out"], 3)
        self.assertEqual(row["players_out_for_season"], 1)
        self.assertEqual(row["players_day_to_day"], 1)
        self.assertEqual(row["injury_absences"], 2)
        self.assertEqual(row["non_injury_absences"], 1)
        self.assertIn("Star Out", row["out_for_season_names"])


class ForecastAvailabilityContextTest(unittest.TestCase):
    def _forecast(self):
        return pd.DataFrame(
            {
                "season": [2026, 2026, 2026],
                "cutoff_date": ["2026-09-23"] * 3,
                "team_id": [11, 8, 3],  # PHX, MIN, DAL (ESPN ids)
                "team_abbreviation": ["PHX", "MIN", "DAL"],
                "current_rank": [10, 1, 7],
                "expected_final_rank": [10.2, 1.0, 7.0],
                "playoff_probability": [0.40, 1.0, 0.55],  # PHX & DAL in the race, MIN locked
                "top4_probability": [0.0, 1.0, 0.1],
            }
        )

    def _injury_current(self):
        raw = pd.DataFrame(
            [
                _raw_row(athlete_id=1, team_id=11, athlete_display_name="Star A", detail_fantasy_status="OFS", detail_type="Knee"),
                _raw_row(athlete_id=2, team_id=11, athlete_display_name="Star B", detail_fantasy_status="OFS", detail_type="Leg"),
                _raw_row(athlete_id=3, team_id=3, athlete_display_name="Wing C", detail_fantasy_status="OUT", detail_type="Ankle"),
            ]
        )
        current = build_current_report(raw)
        current["pbpstats_player_id"] = pd.array([1, 2, 3], dtype="Int64")
        current["player_id"] = ["1", "2", "3"]
        current["player_id_match"] = "espn_athlete_id"
        return current

    def test_join_and_flags(self):
        mpg = pd.DataFrame({"player_id": pd.array([1, 2, 3], dtype="Int64"), "mpg": [30.0, 20.0, 15.0]})
        context = build_forecast_availability_context(self._forecast(), self._injury_current(), mpg).set_index(
            "team_abbreviation"
        )
        # PHX: two season-ending injuries and in the playoff race -> depleted contender.
        self.assertEqual(context.loc["PHX", "players_out_for_season"], 2)
        self.assertAlmostEqual(context.loc["PHX", "rotation_minutes_out"], 50.0)
        self.assertEqual(context.loc["PHX", "availability_flag"], "Depleted contender")
        # MIN carries no injuries -> healthy.
        self.assertEqual(context.loc["MIN", "availability_flag"], "Healthy")
        # DAL has one short-term injury absence.
        self.assertEqual(context.loc["DAL", "players_out"], 1)

    def test_season_long_non_injury_counts_in_rotation_minutes(self):
        # A player out for the season for a non-injury reason (left the team) still frees the minutes.
        current = self._injury_current()
        current.loc[current["athlete_display_name"] == "Star A", "absence_category"] = "non_injury"
        mpg = pd.DataFrame({"player_id": pd.array([1, 2, 3], dtype="Int64"), "mpg": [30.0, 20.0, 15.0]})
        context = build_forecast_availability_context(self._forecast(), current, mpg).set_index("team_abbreviation")
        # PHX still counts both season-ending absences (50 mpg) despite one being non-injury.
        self.assertAlmostEqual(context.loc["PHX", "rotation_minutes_out"], 50.0)
        # injury_absences stays injury-only (Star B), so the count and the minutes differ by design.
        self.assertEqual(context.loc["PHX", "injury_absences"], 1)

    def test_missing_forecast_yields_empty(self):
        self.assertTrue(build_forecast_availability_context(pd.DataFrame(), self._injury_current()).empty)

    def test_missing_injuries_leaves_teams_healthy(self):
        context = build_forecast_availability_context(self._forecast(), pd.DataFrame())
        self.assertEqual(len(context), 3)
        self.assertTrue((context["availability_flag"] == "Healthy").all())


class InjuryReportStaleOutputTest(unittest.TestCase):
    def test_missing_feed_clears_stale_tables(self):
        import build_injury_report as builder

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            processed = output_root / "data" / "processed"
            processed.mkdir(parents=True)
            stale = processed / "injury_report_current_2026.csv"
            stale.write_text("athlete_display_name,availability_status\nX,Out\n", encoding="utf-8")
            (processed / "team_availability_2026.csv").write_text("team_abbreviation\nPHX\n", encoding="utf-8")
            (processed / "injury_report_history_2026.csv").write_text("as_of_date\n2026-09-26\n", encoding="utf-8")

            config = {
                "output_root": str(output_root),
                "injuries_path": str(output_root / "missing.parquet"),
                "crosswalk_path": str(output_root / "missing.csv"),
                "_config_path": str(output_root / "config.json"),
            }
            manifest = builder.build_outputs(config)
            self.assertEqual(manifest["analysis_stats"]["status"], "injuries_missing")
            self.assertFalse(stale.exists())
            self.assertFalse((processed / "team_availability_2026.csv").exists())
            self.assertFalse((processed / "injury_report_history_2026.csv").exists())


class ForecastContextStaleOutputTest(unittest.TestCase):
    def test_missing_input_clears_stale_table_and_summary(self):
        import build_forecast_availability_context as builder

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            processed = output_root / "data" / "processed"
            processed.mkdir(parents=True)
            stale = processed / "forecast_availability_context_2026.csv"
            stale.write_text("team_abbreviation,availability_flag\nPHX,Depleted\n", encoding="utf-8")

            config = {
                "output_root": str(output_root),
                "forecast_summary_path": str(output_root / "does_not_exist.csv"),
                "injuries_path": str(output_root / "also_missing.parquet"),
                "crosswalk_path": str(output_root / "missing_crosswalk.csv"),
                "player_game_path": str(output_root / "missing_game.parquet"),
                "_config_path": str(output_root / "config.json"),
            }
            manifest = builder.build_outputs(config)
            self.assertEqual(manifest["analysis_stats"]["status"], "forecast_summary_missing")
            # The stale table is removed so it cannot be presented or committed as freshly produced.
            self.assertFalse(stale.exists())
            summary = builder.build_summary(config)
            self.assertIn("No context table produced", summary)


class BuildScriptIntegrationTest(unittest.TestCase):
    def test_build_runs_against_committed_feed(self):
        injuries_path = ROOT / "data" / "raw" / "injuries" / "injuries_2026.parquet"
        if not injuries_path.exists():
            self.skipTest("committed injuries feed not present")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_injury_report.py"),
                    "--config",
                    str(ROOT / "analysis" / "injuries" / "config" / "injuries_config.json"),
                    "--output-root",
                    tmp,
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            current = pd.read_csv(Path(tmp) / "data" / "processed" / "injury_report_current_2026.csv")
            self.assertGreater(len(current), 0)
            self.assertIn("availability_status", current.columns)
            self.assertIn("pbpstats_player_id", current.columns)
            # The reviewed crosswalk should resolve the overwhelming majority of listed players.
            match_rate = (current["player_id_match"] != "unmatched").mean()
            self.assertGreater(match_rate, 0.8)


if __name__ == "__main__":
    unittest.main()
