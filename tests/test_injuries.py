import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from injuries.report import (  # noqa: E402
    attach_player_ids,
    build_current_report,
    build_team_availability,
    classify_absence_reason,
    latest_as_of,
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
