import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from midseason_allstar_value_board.integrity import check_csv_integrity  # noqa: E402


class MidseasonAllStarValueBoardTest(unittest.TestCase):
    def _write_fixture_sources(self, tmpdir: Path) -> Path:
        pbp_root = tmpdir / "pbpstats"
        sportsdv_root = tmpdir / "sportsdataverse"
        out_root = tmpdir / "analysis" / "midseason_allstar_value_board"
        (pbp_root / "features_latest" / "2026").mkdir(parents=True)
        sportsdv_root.mkdir(parents=True)

        players = pd.DataFrame(
            [
                {
                    "entity_id_feature": "1",
                    "entity_name_feature": "Alpha Star",
                    "team_id": "pbp-atl",
                    "team_abbreviation": "ATL",
                    "games_played": 12,
                    "minutes": 360,
                    "off_poss": 720,
                    "def_poss": 700,
                    "total_poss": 1420,
                    "points": 250,
                    "rebounds": 90,
                    "assists": 80,
                    "turnovers": 30,
                    "steals": 18,
                    "blocks": 12,
                    "fouls_drawn": 70,
                    "usage": 27.5,
                    "efg_pct_feature": 0.58,
                    "ts_pct_feature": 0.62,
                    "shotquality_pbp_feature": 0.55,
                    "shot_making_over_shotquality_pbp": 0.07,
                    "on_off_rtg": 114.0,
                    "on_def_rtg": 101.0,
                    "fta_rate_feature": 0.42,
                    "rim_fga_share": 0.38,
                    "three_point_fga_share": 0.34,
                    "midrange_fga_share": 0.28,
                    "sample_size_flag": "Strong",
                    "shooting_efficiency_category": "Elite Efficiency",
                    "shotquality_pbp_profile_label": "High-Quality Shot Profile",
                    "shot_diet_profile_label": "Diversified Shot Profile",
                    "specialized_shooter_label": "Balanced Three-Level Scorer",
                    "shot_diet_risk_label": "Balanced / Low Risk",
                },
                {
                    "entity_id_feature": "2",
                    "entity_name_feature": "Beta Watch",
                    "team_id": "pbp-atl",
                    "team_abbreviation": "ATL",
                    "games_played": 9,
                    "minutes": 220,
                    "off_poss": 420,
                    "def_poss": 410,
                    "total_poss": 830,
                    "points": 125,
                    "rebounds": 75,
                    "assists": 20,
                    "turnovers": 18,
                    "steals": 7,
                    "blocks": 16,
                    "fouls_drawn": 38,
                    "usage": 19.0,
                    "efg_pct_feature": 0.54,
                    "ts_pct_feature": 0.57,
                    "shotquality_pbp_feature": 0.52,
                    "shot_making_over_shotquality_pbp": 0.02,
                    "on_off_rtg": 106.0,
                    "on_def_rtg": 104.0,
                    "fta_rate_feature": 0.35,
                    "rim_fga_share": 0.62,
                    "three_point_fga_share": 0.02,
                    "midrange_fga_share": 0.36,
                    "sample_size_flag": "Usable",
                    "shooting_efficiency_category": "Strong Efficiency",
                    "shotquality_pbp_profile_label": "Average Shot Quality Profile",
                    "shot_diet_profile_label": "Paint-Oriented",
                    "specialized_shooter_label": "Rim Pressure Finisher",
                    "shot_diet_risk_label": "Spacing-Limited Profile",
                },
                {
                    "entity_id_feature": "3",
                    "entity_name_feature": "Gamma Reserve",
                    "team_id": "pbp-min",
                    "team_abbreviation": "MIN",
                    "games_played": 6,
                    "minutes": 120,
                    "off_poss": 220,
                    "def_poss": 230,
                    "total_poss": 450,
                    "points": 50,
                    "rebounds": 20,
                    "assists": 10,
                    "turnovers": 12,
                    "steals": 3,
                    "blocks": 1,
                    "fouls_drawn": 8,
                    "usage": 12.0,
                    "efg_pct_feature": 0.45,
                    "ts_pct_feature": 0.48,
                    "shotquality_pbp_feature": 0.47,
                    "shot_making_over_shotquality_pbp": -0.02,
                    "on_off_rtg": 95.0,
                    "on_def_rtg": 108.0,
                    "fta_rate_feature": 0.12,
                    "rim_fga_share": 0.20,
                    "three_point_fga_share": 0.55,
                    "midrange_fga_share": 0.25,
                    "sample_size_flag": "Low",
                    "shooting_efficiency_category": "Efficiency Concern",
                    "shotquality_pbp_profile_label": "Tough Shot Profile",
                    "shot_diet_profile_label": "Perimeter-Leaning",
                    "specialized_shooter_label": "Above-Break Spacer",
                    "shot_diet_risk_label": "High Variance",
                },
            ]
        )
        teams = pd.DataFrame(
            [
                {
                    "entity_id_feature": "pbp-atl",
                    "entity_name_feature": "Atlanta Dream",
                    "team_id": "pbp-atl",
                    "team_abbreviation": "ATL",
                    "games_played": 20,
                    "points": 1700,
                    "opponent_points": 1600,
                    "off_poss": 1650,
                    "def_poss": 1640,
                    "efg_pct_feature": 0.53,
                    "ts_pct_feature": 0.57,
                    "shotquality_pbp_feature": 0.52,
                },
                {
                    "entity_id_feature": "pbp-min",
                    "entity_name_feature": "Minnesota Lynx",
                    "team_id": "pbp-min",
                    "team_abbreviation": "MIN",
                    "games_played": 20,
                    "points": 1800,
                    "opponent_points": 1500,
                    "off_poss": 1660,
                    "def_poss": 1650,
                    "efg_pct_feature": 0.55,
                    "ts_pct_feature": 0.59,
                    "shotquality_pbp_feature": 0.54,
                },
            ]
        )
        players.to_csv(pbp_root / "features_latest" / "2026" / "player_totals_features_latest.csv", index=False)
        teams.to_csv(pbp_root / "features_latest" / "2026" / "team_totals_features_latest.csv", index=False)

        player_box_rows = []
        for player_id, name, position, games, minutes, starts in [
            ("1", "Alpha Star", "G", 12, 30, 10),
            ("2", "Beta Watch", "F", 9, 36, 4),
            ("3", "Gamma Reserve", "G", 6, 20, 1),
        ]:
            for game_num in range(games):
                player_box_rows.append(
                    {
                        "game_id": f"{player_id}-{game_num}",
                        "athlete_id": player_id,
                        "athlete_display_name": name,
                        "athlete_position_abbreviation": position,
                        "team_id": "100" if name != "Gamma Reserve" else "200",
                        "team_abbreviation": "ATL" if name != "Gamma Reserve" else "MIN",
                        "game_date": f"2026-07-{game_num + 1:02d}",
                        "minutes": minutes,
                        "starter": game_num < starts,
                        "did_not_play": False,
                    }
                )
        player_box_rows.append(
            {
                "game_id": "2-dnp-starter",
                "athlete_id": "2",
                "athlete_display_name": "Beta Watch",
                "athlete_position_abbreviation": "F",
                "team_id": "100",
                "team_abbreviation": "ATL",
                "game_date": "2026-07-15",
                "minutes": None,
                "starter": True,
                "did_not_play": True,
            }
        )
        player_box = pd.DataFrame(player_box_rows)
        standings = pd.DataFrame(
            [
                {
                    "team_id": "100",
                    "team_abbreviation": "ATL",
                    "team_name": "Dream",
                    "wins": "12",
                    "losses": "8",
                    "win_pct": "0.600",
                    "season": 2026,
                },
                {
                    "team_id": "200",
                    "team_abbreviation": "MIN",
                    "team_name": "Lynx",
                    "wins": "15",
                    "losses": "5",
                    "win_pct": "0.750",
                    "season": 2026,
                },
            ]
        )
        season_stats = pd.DataFrame(
            [
                {"athlete_id": "1", "athlete_display_name": "Alpha Star", "athlete_position_abbreviation": "G"},
                {"athlete_id": "2", "athlete_display_name": "Beta Watch", "athlete_position_abbreviation": "F"},
                {"athlete_id": "3", "athlete_display_name": "Gamma Reserve", "athlete_position_abbreviation": "G"},
            ]
        )
        logs = pd.DataFrame(
            [
                {"player_id": "1", "player_name": "Alpha Star", "game_date": "2026-07-02", "pts": "20", "ast": "5", "tov": "2"},
                {"player_id": "2", "player_name": "Beta Watch", "game_date": "2026-07-02", "pts": "12", "ast": "1", "tov": "1"},
            ]
        )
        team_box = pd.DataFrame(
            [{"team_id": "100", "team_abbreviation": "ATL", "game_date": "2026-07-02"}]
        )
        team_season_stats = pd.DataFrame(
            [{"team_id": "100", "team_name": "Dream", "gp": 20}, {"team_id": "200", "team_name": "Lynx", "gp": 20}]
        )
        player_box.to_parquet(sportsdv_root / "player_box_2026.parquet", index=False)
        logs.to_parquet(sportsdv_root / "player_game_logs_2026.parquet", index=False)
        season_stats.to_parquet(sportsdv_root / "player_season_stats_2026.parquet", index=False)
        team_box.to_parquet(sportsdv_root / "team_box_2026.parquet", index=False)
        standings.to_parquet(sportsdv_root / "standings_2026.parquet", index=False)
        team_season_stats.to_parquet(sportsdv_root / "team_season_stats_2026.parquet", index=False)

        config = {
            "season": 2026,
            "as_of_date": "2026-07-03",
            "pbpstats_data_root": str(pbp_root),
            "sportsdataverse_data_root": str(sportsdv_root),
            "sportsdataverse_fallback_root": str(sportsdv_root),
            "output_root": str(out_root),
            "thresholds": {
                "min_minutes": 300,
                "watchlist_min_minutes": 180,
                "min_games": 8,
                "min_team_game_share": 0.45,
                "starter_role_start_rate_threshold": 0.50,
            },
            "weights": {
                "production": 0.25,
                "efficiency": 0.20,
                "creation": 0.15,
                "impact": 0.20,
                "availability": 0.10,
                "team_context": 0.10,
            },
        }
        config_path = tmpdir / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return config_path

    def test_cli_stage_all_writes_required_outputs(self):
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            tmpdir = Path(raw_tmpdir)
            config_path = self._write_fixture_sources(tmpdir)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_midseason_allstar_value_board.py"),
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
            out_root = tmpdir / "analysis" / "midseason_allstar_value_board"
            required = [
                "data/processed/candidate_pool_2026.csv",
                "data/processed/player_metric_panel_2026.csv",
                "data/processed/allstar_value_board_2026.csv",
                "data/processed/player_archetypes_2026.csv",
                "data/processed/run_manifest_2026.json",
                "data/viz/board_rankings_viz_2026.csv",
                "data/viz/score_components_viz_2026.csv",
                "data/viz/archetype_scatter_viz_2026.csv",
                "data/viz/team_representation_viz_2026.csv",
                "data/viz/social_card_players_2026.csv",
                "editorial/substack_asset_manifest_2026.md",
                "editorial/substack_draft_2026.md",
            ]
            for relative in required:
                self.assertTrue((out_root / relative).exists(), relative)

            board = pd.read_csv(out_root / "data/processed/allstar_value_board_2026.csv")
            self.assertEqual(list(board["player_name"]), ["Alpha Star", "Beta Watch"])
            self.assertTrue(board["eligible_flag"].all())
            self.assertIn("allstar_value_score", board.columns)

            pool = pd.read_csv(out_root / "data/processed/candidate_pool_2026.csv")
            self.assertEqual(len(pool), 3)
            tiers = dict(zip(pool["player_name"], pool["candidate_tier"]))
            self.assertEqual(tiers["Alpha Star"], "Core Candidate")
            self.assertEqual(tiers["Beta Watch"], "Core Candidate")
            self.assertEqual(tiers["Gamma Reserve"], "Ineligible")
            beta = pool[pool["player_name"] == "Beta Watch"].iloc[0]
            self.assertEqual(beta["box_games_played"], 9)
            self.assertEqual(beta["box_minutes"], 324)
            self.assertEqual(beta["box_starts"], 4)
            self.assertAlmostEqual(beta["start_rate"], 4 / 9)
            self.assertFalse(beta["starter_role_flag"])
            self.assertEqual(beta["pbpstats_minutes"], 220)
            self.assertEqual(beta["eligibility_minutes_source"], "sportsdataverse_player_box")
            alpha = pool[pool["player_name"] == "Alpha Star"].iloc[0]
            self.assertEqual(alpha["box_starts"], 10)
            self.assertAlmostEqual(alpha["start_rate"], 10 / 12)
            self.assertTrue(alpha["starter_role_flag"])
            self.assertEqual(alpha["team_win_pct"], 0.6)

            metric_panel = pd.read_csv(out_root / "data/processed/player_metric_panel_2026.csv")
            self.assertEqual(len(metric_panel), 3)
            self.assertIn("box_minutes", metric_panel.columns)
            self.assertIn("box_starts", metric_panel.columns)
            self.assertIn("start_rate", metric_panel.columns)
            self.assertIn("starter_role_flag", metric_panel.columns)
            self.assertIn("pbpstats_minutes", metric_panel.columns)
            self.assertEqual(metric_panel.loc[metric_panel["player_name"] == "Alpha Star", "team_win_pct"].iloc[0], 0.6)

            social = pd.read_csv(out_root / "data/viz/social_card_players_2026.csv")
            self.assertEqual(list(social["player_name"]), ["Alpha Star", "Beta Watch"])

            rankings = pd.read_csv(out_root / "data/viz/board_rankings_viz_2026.csv")
            self.assertIn("box_starts", rankings.columns)
            self.assertIn("start_rate", rankings.columns)
            self.assertIn("starter_role_flag", rankings.columns)

            archetypes = pd.read_csv(out_root / "data/processed/player_archetypes_2026.csv")
            self.assertIn("Primary Engine", set(archetypes["primary_archetype"]))


if __name__ == "__main__":
    unittest.main()


class CsvIntegrityTest(unittest.TestCase):
    """Guards the failure that left the 2026 board corrupt and unnoticed for three weeks.

    Four committed artifacts each held two different exports concatenated, second header
    row and all. The builders cannot cause this -- they overwrite -- so the damage arrived
    from outside the pipeline and no code path was going to notice it.
    """

    KEY_COLUMNS = {
        "allstar_value_board_2026.csv": ["player_id"],
        "candidate_pool_2026.csv": ["player_id"],
        "player_metric_panel_2026.csv": ["player_id"],
        "player_archetypes_2026.csv": ["player_id"],
        "rapm_player_2026.csv": ["player_id"],
        "team_identity_shift_2026.csv": ["team_abbreviation"],
        "team_grade_panel_2026.csv": ["team_abbreviation"],
        "bench_net_rating_2026.csv": ["team_id"],
        "clutch_net_rating_2026.csv": ["team_id"],
    }

    def test_no_committed_analysis_csv_is_structurally_corrupt(self):
        problems = {}
        for path in sorted((ROOT / "analysis").rglob("*.csv")):
            record = check_csv_integrity(path, key_columns=self.KEY_COLUMNS.get(path.name))
            if not record["ok"]:
                problems[str(path.relative_to(ROOT))] = record["problems"]
        self.assertEqual(problems, {}, f"corrupt committed artifacts: {problems}")

    def test_concatenated_exports_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doubled.csv"
            path.write_text(
                "player_id,score\n1,10\n2,20\nplayer_id,score\n3,30\n",
                encoding="utf-8",
            )
            record = check_csv_integrity(path)
            self.assertFalse(record["ok"])
            self.assertEqual(record["repeated_header_lines"], [3])

    def test_ragged_widths_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ragged.csv"
            path.write_text("a,b,c\n1,2,3\n4,5\n", encoding="utf-8")
            record = check_csv_integrity(path)
            self.assertFalse(record["ok"])
            self.assertIn("inconsistent row widths [2, 3]", record["problems"])

    def test_duplicate_keys_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dupes.csv"
            path.write_text("player_id,score\n1,10\n1,20\n", encoding="utf-8")
            record = check_csv_integrity(path, key_columns=["player_id"])
            self.assertFalse(record["ok"])
            self.assertEqual(record["duplicate_keys"], [("1",)])

    def test_a_clean_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.csv"
            path.write_text("player_id,score\n1,10\n2,20\n", encoding="utf-8")
            record = check_csv_integrity(path, key_columns=["player_id"])
            self.assertTrue(record["ok"], record["problems"])
            self.assertEqual(record["rows"], 2)

    def test_missing_file_is_reported_not_raised(self):
        record = check_csv_integrity(Path("/nonexistent/nope.csv"))
        self.assertFalse(record["ok"])
        self.assertEqual(record["problems"], ["missing"])
