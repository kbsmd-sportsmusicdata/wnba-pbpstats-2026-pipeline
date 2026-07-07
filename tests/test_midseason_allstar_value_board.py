import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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
                    "team_id": "100",
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
                    "team_id": "100",
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
                    "team_id": "200",
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
                    "entity_id_feature": "100",
                    "entity_name_feature": "Atlanta Dream",
                    "team_id": "100",
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
                    "entity_id_feature": "200",
                    "entity_name_feature": "Minnesota Lynx",
                    "team_id": "200",
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

        player_box = pd.DataFrame(
            [
                {
                    "athlete_id": "1",
                    "athlete_display_name": "Alpha Star",
                    "athlete_position_abbreviation": "G",
                    "team_id": "100",
                    "team_abbreviation": "ATL",
                    "game_date": "2026-07-01",
                    "did_not_play": False,
                },
                {
                    "athlete_id": "2",
                    "athlete_display_name": "Beta Watch",
                    "athlete_position_abbreviation": "F",
                    "team_id": "100",
                    "team_abbreviation": "ATL",
                    "game_date": "2026-07-01",
                    "did_not_play": False,
                },
            ]
        )
        standings = pd.DataFrame(
            [
                {"team_id": "100", "team_name": "Dream", "wins": "12", "losses": "8", "win_pct": "0.600", "season": 2026},
                {"team_id": "200", "team_name": "Lynx", "wins": "15", "losses": "5", "win_pct": "0.750", "season": 2026},
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
            self.assertEqual(board.iloc[0]["player_name"], "Alpha Star")
            self.assertIn("allstar_value_score", board.columns)
            self.assertGreater(board.iloc[0]["allstar_value_score"], board.iloc[-1]["allstar_value_score"])

            pool = pd.read_csv(out_root / "data/processed/candidate_pool_2026.csv")
            tiers = dict(zip(pool["player_name"], pool["candidate_tier"]))
            self.assertEqual(tiers["Alpha Star"], "Core Candidate")
            self.assertEqual(tiers["Beta Watch"], "Watchlist")
            self.assertEqual(tiers["Gamma Reserve"], "Ineligible")

            archetypes = pd.read_csv(out_root / "data/processed/player_archetypes_2026.csv")
            self.assertIn("Primary Engine", set(archetypes["primary_archetype"]))


if __name__ == "__main__":
    unittest.main()
