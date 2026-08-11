import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class StandingsPlayoffForecastConfigTest(unittest.TestCase):
    def _season_payloads(self):
        import standings_playoff_forecast.config as config_module

        return (
            config_module._load_json(config_module.CONFIG_ROOT / "seasons" / "default.json"),
            config_module._load_json(config_module.CONFIG_ROOT / "seasons" / "2026.json"),
        )

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

    def test_rejects_non_mapping_optional_validation_files(self) -> None:
        import standings_playoff_forecast.config as config_module

        default, season = self._season_payloads()
        season = deepcopy(season)
        season["optional_validation_files"] = ["standings_2026.parquet"]
        with patch.object(config_module, "_load_json", side_effect=[default, season]):
            with self.assertRaisesRegex(
                ValueError, "optional_validation_files must be a mapping"
            ):
                config_module.load_season_config(2026)

    def test_rejects_non_string_optional_validation_key_or_value(self) -> None:
        import standings_playoff_forecast.config as config_module

        default, base_season = self._season_payloads()
        for optional_files in ({1: "standings.parquet"}, {"standings": 1}):
            with self.subTest(optional_files=optional_files):
                season = deepcopy(base_season)
                season["optional_validation_files"] = optional_files
                with patch.object(
                    config_module, "_load_json", side_effect=[default, season]
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "optional_validation_files must map strings to strings",
                    ):
                        config_module.load_season_config(2026)

    def test_rejects_source_and_optional_validation_name_collision(self) -> None:
        import standings_playoff_forecast.config as config_module

        default, season = self._season_payloads()
        season = deepcopy(season)
        season["optional_validation_files"] = {"schedule": "other.parquet"}
        with patch.object(config_module, "_load_json", side_effect=[default, season]):
            with self.assertRaisesRegex(
                ValueError, "optional_validation_files must not overlap source_files"
            ):
                config_module.load_season_config(2026)

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
