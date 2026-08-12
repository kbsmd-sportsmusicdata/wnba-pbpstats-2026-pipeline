import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from midseason_team_grades.data_sources import load_config, load_sources  # noqa: E402
from midseason_team_grades.metrics import (  # noqa: E402
    build_player_fit_profiles,
    build_rapm_player,
    dedupe_allstar_board,
    filter_pbp_to_league_teams,
    filter_to_league_teams,
)


class MidseasonTeamGradesTest(unittest.TestCase):
    def _write_fixture_sources(self, tmpdir: Path) -> Path:
        source_root = tmpdir / "sportsdataverse"
        pbp_root = tmpdir / "pbpstats"
        allstar_root = tmpdir / "allstar"
        out_root = tmpdir / "analysis" / "midseason_team_grades"
        source_root.mkdir(parents=True)
        (pbp_root / "features_latest" / "2026").mkdir(parents=True)
        (allstar_root / "data" / "processed").mkdir(parents=True)

        player_box = pd.DataFrame(
            [
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "athlete_id": "1",
                    "athlete_display_name": "Alpha Starter",
                    "team_abbreviation": "ATL",
                    "opponent_team_abbreviation": "MIN",
                    "home_away": "home",
                    "minutes": 30,
                    "starter": True,
                    "did_not_play": False,
                    "points": 20,
                    "field_goals_made": 8,
                    "field_goals_attempted": 16,
                    "three_point_field_goals_made": 2,
                    "free_throws_attempted": 2,
                    "rebounds": 5,
                    "assists": 4,
                    "turnovers": 2,
                    "plus_minus": "+10",
                },
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "athlete_id": "2",
                    "athlete_display_name": "Beta Bench",
                    "team_abbreviation": "ATL",
                    "opponent_team_abbreviation": "MIN",
                    "home_away": "home",
                    "minutes": 10,
                    "starter": False,
                    "did_not_play": False,
                    "points": 12,
                    "field_goals_made": 5,
                    "field_goals_attempted": 8,
                    "three_point_field_goals_made": 1,
                    "free_throws_attempted": 2,
                    "rebounds": 3,
                    "assists": 2,
                    "turnovers": 1,
                    "plus_minus": "+5",
                },
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "athlete_id": "3",
                    "athlete_display_name": "DNP Bench",
                    "team_abbreviation": "ATL",
                    "opponent_team_abbreviation": "MIN",
                    "home_away": "home",
                    "minutes": None,
                    "starter": False,
                    "did_not_play": True,
                    "points": 0,
                    "field_goals_made": 0,
                    "field_goals_attempted": 0,
                    "three_point_field_goals_made": 0,
                    "free_throws_attempted": 0,
                    "rebounds": 0,
                    "assists": 0,
                    "turnovers": 0,
                    "plus_minus": "0",
                },
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "athlete_id": "4",
                    "athlete_display_name": "Gamma Starter",
                    "team_abbreviation": "MIN",
                    "opponent_team_abbreviation": "ATL",
                    "home_away": "away",
                    "minutes": 30,
                    "starter": True,
                    "did_not_play": False,
                    "points": 18,
                    "field_goals_made": 7,
                    "field_goals_attempted": 14,
                    "three_point_field_goals_made": 1,
                    "free_throws_attempted": 3,
                    "rebounds": 7,
                    "assists": 3,
                    "turnovers": 3,
                    "plus_minus": "-10",
                },
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "athlete_id": "5",
                    "athlete_display_name": "Delta Bench",
                    "team_abbreviation": "MIN",
                    "opponent_team_abbreviation": "ATL",
                    "home_away": "away",
                    "minutes": 10,
                    "starter": False,
                    "did_not_play": False,
                    "points": 6,
                    "field_goals_made": 2,
                    "field_goals_attempted": 5,
                    "three_point_field_goals_made": 0,
                    "free_throws_attempted": 2,
                    "rebounds": 2,
                    "assists": 1,
                    "turnovers": 1,
                    "plus_minus": "-5",
                },
            ]
        )
        team_box = pd.DataFrame(
            [
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "team_id": "100.0",
                    "team_abbreviation": "ATL",
                    "team_display_name": "Atlanta Dream",
                    "team_home_away": "home",
                    "team_score": 70,
                    "team_winner": True,
                    "field_goals_made": 28,
                    "field_goals_attempted": 60,
                    "three_point_field_goals_made": 8,
                    "free_throws_attempted": 16,
                    "offensive_rebounds": 10,
                    "defensive_rebounds": 25,
                    "turnovers": 12,
                    "opponent_team_id": "200",
                    "opponent_team_abbreviation": "MIN",
                    "opponent_team_score": 60,
                },
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "team_id": "200.0",
                    "team_abbreviation": "MIN",
                    "team_display_name": "Minnesota Lynx",
                    "team_home_away": "away",
                    "team_score": 60,
                    "team_winner": False,
                    "field_goals_made": 24,
                    "field_goals_attempted": 58,
                    "three_point_field_goals_made": 6,
                    "free_throws_attempted": 12,
                    "offensive_rebounds": 8,
                    "defensive_rebounds": 22,
                    "turnovers": 14,
                    "opponent_team_id": "100",
                    "opponent_team_abbreviation": "ATL",
                    "opponent_team_score": 70,
                },
            ]
        )
        espn_pbp = pd.DataFrame(
            [
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "home_team_id": "100",
                    "home_team_abbrev": "ATL",
                    "away_team_id": "200",
                    "away_team_abbrev": "MIN",
                    "team_id": "100",
                    "home_score": 66,
                    "away_score": 60,
                    "start_game_seconds_remaining": 250,
                    "score_value": 2,
                    "scoring_play": True,
                },
                {
                    "game_id": "g1",
                    "game_date": "2026-07-01",
                    "home_team_id": "100",
                    "home_team_abbrev": "ATL",
                    "away_team_id": "200",
                    "away_team_abbrev": "MIN",
                    "team_id": "200",
                    "home_score": 66,
                    "away_score": 63,
                    "start_game_seconds_remaining": 220,
                    "score_value": 3,
                    "scoring_play": True,
                },
            ]
        )
        wnba_pbp = pd.DataFrame(
            [
                {
                    "game_id": "g1",
                    "event_num": 1,
                    "score_value": 2,
                    "player1_team_abbreviation": "ATL",
                    "home_player1": "1",
                    "home_player2": "2",
                    "home_player3": "9",
                    "home_player4": "10",
                    "home_player5": "11",
                    "away_player1": "4",
                    "away_player2": "5",
                    "away_player3": "12",
                    "away_player4": "13",
                    "away_player5": "14",
                    "garbage_time": 0,
                }
            ]
        )
        player_features = pd.DataFrame(
            [
                {
                    "entity_id_feature": "1",
                    "entity_name_feature": "Alpha Starter",
                    "team_abbreviation": "ATL",
                    "usage": 24,
                    "ts_pct_feature": 0.58,
                    "rim_fga_share": 0.30,
                    "three_point_fga_share": 0.35,
                    "shot_diet_profile_label": "Balanced Shot Diet",
                },
                {
                    "entity_id_feature": "2",
                    "entity_name_feature": "Beta Bench",
                    "team_abbreviation": "ATL",
                    "usage": 18,
                    "ts_pct_feature": 0.62,
                    "rim_fga_share": 0.40,
                    "three_point_fga_share": 0.30,
                    "shot_diet_profile_label": "Modern Shot Diet",
                },
            ]
        )
        team_features = pd.DataFrame(
            [
                {"entity_id_feature": "100", "team_abbreviation": "ATL", "games_played": 1, "points": 70, "opponent_points": 60, "off_poss": 70, "def_poss": 70},
                {"entity_id_feature": "200", "team_abbreviation": "MIN", "games_played": 1, "points": 60, "opponent_points": 70, "off_poss": 70, "def_poss": 70},
            ]
        )
        standings = pd.DataFrame(
            [
                {"team_id": "100", "team_abbreviation": "ATL", "win_pct": "1.000"},
                {"team_id": "200", "team_abbreviation": "MIN", "win_pct": "0.000"},
            ]
        )
        allstar_board = pd.DataFrame(
            [
                {"player_id": "1", "player_name": "Alpha Starter", "team_abbreviation": "ATL", "allstar_value_score": 70, "starter_role_flag": True},
                {"player_id": "2", "player_name": "Beta Bench", "team_abbreviation": "ATL", "allstar_value_score": 55, "starter_role_flag": False},
            ]
        )

        player_box.to_parquet(source_root / "player_box_2026.parquet", index=False)
        team_box.to_parquet(source_root / "team_box_2026.parquet", index=False)
        espn_pbp.to_parquet(source_root / "play_by_play_2026.parquet", index=False)
        wnba_pbp.to_parquet(source_root / "wnbastats_play_by_play_20260602.parquet", index=False)
        standings.to_parquet(source_root / "standings_2026.parquet", index=False)
        player_features.to_csv(pbp_root / "features_latest" / "2026" / "player_totals_features_latest.csv", index=False)
        team_features.to_csv(pbp_root / "features_latest" / "2026" / "team_totals_features_latest.csv", index=False)
        allstar_board.to_csv(allstar_root / "data" / "processed" / "allstar_value_board_2026.csv", index=False)

        config = {
            "season": 2026,
            "as_of_date": "2026-07-01",
            "sportsdataverse_data_root": str(source_root),
            "sportsdataverse_fallback_root": str(source_root),
            "pbpstats_data_root": str(pbp_root),
            "allstar_value_board_root": str(allstar_root),
            "output_root": str(out_root),
            "rapm": {"min_scoring_events": 2, "ridge_alpha": 10.0},
            "source_files": {
                "player_box": "player_box_2026.parquet",
                "team_box": "team_box_2026.parquet",
                "standings": "standings_2026.parquet",
                "espn_pbp": "play_by_play_2026.parquet",
                "wnba_stats_pbp": "wnbastats_play_by_play_20260602.parquet",
            },
        }
        config_path = tmpdir / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return config_path

    def test_cli_writes_analysis_ready_team_grade_outputs(self):
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            tmpdir = Path(raw_tmpdir)
            config_path = self._write_fixture_sources(tmpdir)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_midseason_team_grades.py"),
                    "--config",
                    str(config_path),
                    "--stage",
                    "all",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            out_root = tmpdir / "analysis" / "midseason_team_grades"
            processed = out_root / "data" / "processed"
            expected = [
                "team_game_four_factors_2026.csv",
                "team_grade_panel_2026.csv",
                "bench_player_game_2026.csv",
                "bench_team_game_2026.csv",
                "bench_team_summary_2026.csv",
                "clutch_team_game_2026.csv",
                "player_midseason_impact_2026.csv",
                "player_fit_profiles_2026.csv",
                "rapm_player_2026.csv",
                "run_manifest_2026.json",
            ]
            for name in expected:
                self.assertTrue((processed / name).exists(), name)
            self.assertTrue((out_root / "data" / "eda" / "eda_manifest_2026.json").exists())

            four = pd.read_csv(processed / "team_game_four_factors_2026.csv")
            atl = four[four["team_abbreviation"] == "ATL"].iloc[0]
            self.assertEqual(atl["opponent_team_abbreviation"], "MIN")
            self.assertAlmostEqual(atl["off_efg_pct"], 53.3, places=1)
            self.assertAlmostEqual(atl["def_efg_pct"], 46.6, places=1)

            bench_players = pd.read_csv(processed / "bench_player_game_2026.csv")
            self.assertEqual(set(bench_players["player_name"]), {"Beta Bench", "Delta Bench"})
            self.assertNotIn("DNP Bench", set(bench_players["player_name"]))

            bench_game = pd.read_csv(processed / "bench_team_game_2026.csv")
            atl_bench = bench_game[bench_game["team_abbreviation"] == "ATL"].iloc[0]
            self.assertEqual(atl_bench["bench_points"], 12)
            self.assertAlmostEqual(atl_bench["bench_points_share"], 17.1, places=1)
            self.assertAlmostEqual(atl_bench["bench_minutes_share"], 25.0, places=1)

            clutch = pd.read_csv(processed / "clutch_team_game_2026.csv")
            self.assertEqual(set(clutch["team_abbreviation"]), {"ATL", "MIN"})
            self.assertEqual(clutch.loc[clutch["team_abbreviation"] == "ATL", "clutch_points"].iloc[0], 2)

            manifest = json.loads((processed / "run_manifest_2026.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["metric_status"]["vorp_status"], "unavailable_exact_formula_required")
            self.assertEqual(manifest["metric_status"]["rapm_status"], "skipped_insufficient_scoring_events")

    def test_clutch_stage_does_not_rewrite_team_grade_panel(self):
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            tmpdir = Path(raw_tmpdir)
            config_path = self._write_fixture_sources(tmpdir)

            all_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_midseason_team_grades.py"),
                    "--config",
                    str(config_path),
                    "--stage",
                    "all",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(all_result.returncode, 0, msg=all_result.stderr)

            panel_path = tmpdir / "analysis" / "midseason_team_grades" / "data" / "processed" / "team_grade_panel_2026.csv"
            sentinel = "team_abbreviation,team_grade_score\nKEEP,99\n"
            panel_path.write_text(sentinel, encoding="utf-8")

            clutch_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_midseason_team_grades.py"),
                    "--config",
                    str(config_path),
                    "--stage",
                    "clutch",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(clutch_result.returncode, 0, msg=clutch_result.stderr)
            self.assertEqual(panel_path.read_text(encoding="utf-8"), sentinel)

    def test_rapm_handles_missing_garbage_time_column(self):
        pbp = pd.DataFrame(
            [
                {
                    "score_value": 2,
                    "player1_team_abbreviation": "ATL",
                    "team_home": "ATL",
                    "home_player1": "1",
                    "home_player2": "2",
                    "home_player3": "3",
                    "home_player4": "4",
                    "home_player5": "5",
                    "away_player1": "6",
                    "away_player2": "7",
                    "away_player3": "8",
                    "away_player4": "9",
                    "away_player5": "10",
                },
                {
                    "score_value": 3,
                    "player1_team_abbreviation": "ATL",
                    "team_home": "ATL",
                    "home_player1": "1",
                    "home_player2": "2",
                    "home_player3": "3",
                    "home_player4": "4",
                    "home_player5": "5",
                    "away_player1": "6",
                    "away_player2": "7",
                    "away_player3": "8",
                    "away_player4": "9",
                    "away_player5": "10",
                },
            ]
        )

        rapm, status = build_rapm_player(pbp, {"rapm": {"min_scoring_events": 1, "ridge_alpha": 10.0}})

        self.assertEqual(status, "rapm_style_scoring_event_ridge")
        self.assertFalse(rapm.empty)


class SourceResolutionTest(unittest.TestCase):
    """Guards the failure mode where a mistyped filename silently yields empty outputs."""

    CONFIG_PATH = ROOT / "analysis" / "midseason_team_grades" / "config" / "midseason_team_grades_config.json"

    def test_every_configured_source_file_resolves(self):
        config = load_config(self.CONFIG_PATH)
        sources = load_sources(config)
        unresolved = {
            name: record.get("requested_filename")
            for name, record in sources.source_manifest.items()
            if record.get("status") == "unresolved"
        }
        self.assertEqual(unresolved, {}, f"configured sources did not resolve: {unresolved}")

    def test_pbp_sources_carry_the_columns_their_builders_need(self):
        config = load_config(self.CONFIG_PATH)
        sources = load_sources(config)
        # Clutch needs these; if the espn_pbp filename regresses, clutch goes empty again.
        self.assertTrue(
            {"game_id", "home_team_id", "away_team_id", "home_team_abbrev", "away_team_abbrev", "team_id", "score_value"}
            .issubset(sources.espn_pbp.columns)
        )
        self.assertFalse(sources.wnba_stats_pbp.empty)

    def test_unresolved_source_is_flagged_with_the_requested_name(self):
        config = load_config(self.CONFIG_PATH)
        config = dict(config)
        config["source_files"] = dict(config["source_files"], espn_pbp="does_not_exist_2026.parquet")
        sources = load_sources(config)
        record = sources.source_manifest["espn_pbp"]
        self.assertEqual(record["status"], "unresolved")
        self.assertEqual(record["requested_filename"], "does_not_exist_2026.parquet")
        self.assertEqual(record["rows"], 0)


class ExhibitionFilterTest(unittest.TestCase):
    STANDINGS = pd.DataFrame({"team_abbreviation": ["ATL", "MIN", "GS", "NY"]})

    def test_all_star_sides_and_their_game_are_dropped(self):
        box = pd.DataFrame(
            [
                {"game_id": "g1", "team_abbreviation": "ATL", "opponent_team_abbreviation": "MIN"},
                {"game_id": "g1", "team_abbreviation": "MIN", "opponent_team_abbreviation": "ATL"},
                {"game_id": "allstar", "team_abbreviation": "SPO", "opponent_team_abbreviation": "COOP"},
                {"game_id": "allstar", "team_abbreviation": "COOP", "opponent_team_abbreviation": "SPO"},
            ]
        )
        out = filter_to_league_teams(box, self.STANDINGS)
        self.assertEqual(set(out["game_id"]), {"g1"})
        self.assertEqual(len(out), 2)

    def test_aliased_abbreviations_survive_the_filter(self):
        # Standings say "GS", the box says "GSV"; both normalise to the same franchise.
        box = pd.DataFrame(
            [{"game_id": "g1", "team_abbreviation": "GSV", "opponent_team_abbreviation": "NY"}]
        )
        self.assertEqual(len(filter_to_league_teams(box, self.STANDINGS)), 1)

    def test_filter_is_a_no_op_without_standings(self):
        box = pd.DataFrame([{"game_id": "g1", "team_abbreviation": "SPO", "opponent_team_abbreviation": "COOP"}])
        self.assertEqual(len(filter_to_league_teams(box, pd.DataFrame())), 1)

    def test_pbp_exhibition_rows_are_dropped(self):
        pbp = pd.DataFrame(
            [
                {"home_team_abbrev": "ATL", "away_team_abbrev": "MIN", "score_value": 2},
                {"home_team_abbrev": "SPO", "away_team_abbrev": "COOP", "score_value": 3},
            ]
        )
        out = filter_pbp_to_league_teams(pbp, self.STANDINGS)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["home_team_abbrev"], "ATL")


class DamagedBoardTest(unittest.TestCase):
    """The committed 2026 board carries an embedded header row and shifted duplicates."""

    BOARD = pd.DataFrame(
        [
            {"player_id": 1627668, "allstar_value_score": "68.55"},
            {"player_id": 1627668, "allstar_value_score": "All-Star Case"},
            {"player_id": 1627673, "allstar_value_score": "70.63"},
            {"player_id": "player_id", "allstar_value_score": "score_band"},
        ]
    )

    def test_non_numeric_and_duplicate_rows_are_dropped(self):
        out = dedupe_allstar_board(self.BOARD)
        self.assertEqual(len(out), 2)
        self.assertEqual(set(out["player_id"]), {"1627668", "1627673"})
        self.assertAlmostEqual(out.iloc[0]["allstar_value_score"], 68.55)

    def test_fit_profile_merge_does_not_multiply_rows(self):
        features = pd.DataFrame(
            [
                {"entity_id_feature": "1627668", "entity_name_feature": "A", "usage": 25.0},
                {"entity_id_feature": "1627673", "entity_name_feature": "B", "usage": 18.0},
            ]
        )
        out = build_player_fit_profiles(features, self.BOARD)
        self.assertEqual(len(out), 2)
        self.assertEqual(out["allstar_value_score"].notna().sum(), 2)

    def test_mixed_id_types_merge_instead_of_raising(self):
        # Integer ids on the board, string ids on the features side.
        features = pd.DataFrame([{"entity_id_feature": "1627668", "entity_name_feature": "A", "usage": 25.0}])
        out = build_player_fit_profiles(features, self.BOARD)
        self.assertAlmostEqual(out.iloc[0]["allstar_value_score"], 68.55)


if __name__ == "__main__":
    unittest.main()
