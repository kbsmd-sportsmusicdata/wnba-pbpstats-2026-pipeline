import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class StandingsPlayoffForecastConfigTest(unittest.TestCase):
    def test_forecast_package_imports_from_scripts_root(self) -> None:
        import standings_playoff_forecast

        self.assertIsNotNone(standings_playoff_forecast)


if __name__ == "__main__":
    unittest.main()
