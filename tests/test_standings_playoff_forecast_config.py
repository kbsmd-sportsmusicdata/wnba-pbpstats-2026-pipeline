import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class StandingsPlayoffForecastConfigTest(unittest.TestCase):
    def test_forecast_package_imports_from_scripts_root(self) -> None:
        import standings_playoff_forecast

        self.assertIsNotNone(standings_playoff_forecast)

    def test_loads_verified_2026_competition_rules(self) -> None:
        from standings_playoff_forecast.config import load_season_config

        cfg = load_season_config(2026)

        self.assertEqual(cfg.team_count, 15)
        self.assertEqual(cfg.regular_season_games_per_team, 44)
        self.assertEqual(cfg.playoff_qualifiers, 8)

    def test_2026_standings_is_optional_validation_source(self) -> None:
        from standings_playoff_forecast.config import load_season_config

        cfg = load_season_config(2026)

        self.assertIn("schedule", cfg.source_files)
        self.assertIn("team_box", cfg.source_files)
        self.assertNotIn("standings", cfg.source_files)
        self.assertEqual(
            cfg.optional_validation_files["standings"],
            "standings_2026.parquet",
        )

    def test_rejects_unknown_season_without_a_verified_config(self) -> None:
        from standings_playoff_forecast.config import load_season_config

        with self.assertRaises(FileNotFoundError):
            load_season_config(2099)

    def test_loads_model_settings_used_by_the_forecast(self) -> None:
        from standings_playoff_forecast.config import load_model_config

        cfg = load_model_config()

        self.assertEqual(cfg.model_version, "v1_heuristic_margin")
        self.assertEqual(cfg.season_net_rating_weight, 0.7)
        self.assertEqual(cfg.recent_net_rating_weight, 0.3)
        self.assertEqual(cfg.home_court_points, 1.5)
        self.assertEqual(cfg.minimum_sigma, 8.0)
        self.assertEqual(cfg.maximum_sigma, 18.0)


if __name__ == "__main__":
    unittest.main()
