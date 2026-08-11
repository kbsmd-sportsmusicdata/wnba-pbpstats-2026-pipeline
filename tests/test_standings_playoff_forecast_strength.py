import sys
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _team_games() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "team_id": "A",
                "team_abbreviation": "ALP",
                "team_name": "Alpha",
                "franchise_id": "alpha",
                "game_id": "1",
                "game_date": "2026-06-01",
                "win": 1,
                "net_rating_est": 10.0,
                "efg_pct": 0.50,
                "opp_efg_pct": 0.40,
                "tov_pct": 0.10,
                "opp_tov_pct": 0.20,
                "oreb_pct": 0.30,
                "opp_oreb_pct": 0.20,
                "ftr": 0.25,
                "opp_ftr": 0.20,
            },
            {
                "team_id": "A",
                "team_abbreviation": "ALP",
                "team_name": "Alpha",
                "franchise_id": "alpha",
                "game_id": "2",
                "game_date": "2026-06-03",
                "win": 1,
                "net_rating_est": 20.0,
                "efg_pct": 0.60,
                "opp_efg_pct": 0.50,
                "tov_pct": 0.10,
                "opp_tov_pct": 0.20,
                "oreb_pct": 0.30,
                "opp_oreb_pct": 0.20,
                "ftr": 0.25,
                "opp_ftr": 0.20,
            },
            {
                "team_id": "A",
                "team_abbreviation": "ALP",
                "team_name": "Alpha",
                "franchise_id": "alpha",
                "game_id": "3",
                "game_date": "2026-06-05",
                "win": 0,
                "net_rating_est": -30.0,
                "efg_pct": 0.30,
                "opp_efg_pct": 0.60,
                "tov_pct": 0.30,
                "opp_tov_pct": 0.10,
                "oreb_pct": 0.10,
                "opp_oreb_pct": 0.30,
                "ftr": 0.10,
                "opp_ftr": 0.30,
            },
            {
                "team_id": "B",
                "team_abbreviation": "BRV",
                "team_name": "Bravo",
                "franchise_id": "bravo",
                "game_id": "1",
                "game_date": "2026-06-01",
                "win": 0,
                "net_rating_est": -10.0,
                "efg_pct": 0.40,
                "opp_efg_pct": 0.50,
                "tov_pct": 0.20,
                "opp_tov_pct": 0.10,
                "oreb_pct": 0.20,
                "opp_oreb_pct": 0.30,
                "ftr": 0.20,
                "opp_ftr": 0.25,
            },
            {
                "team_id": "B",
                "team_abbreviation": "BRV",
                "team_name": "Bravo",
                "franchise_id": "bravo",
                "game_id": "2",
                "game_date": "2026-06-03",
                "win": 0,
                "net_rating_est": -20.0,
                "efg_pct": 0.50,
                "opp_efg_pct": 0.60,
                "tov_pct": 0.20,
                "opp_tov_pct": 0.10,
                "oreb_pct": 0.20,
                "opp_oreb_pct": 0.30,
                "ftr": 0.20,
                "opp_ftr": 0.25,
            },
            {
                "team_id": "B",
                "team_abbreviation": "BRV",
                "team_name": "Bravo",
                "franchise_id": "bravo",
                "game_id": "3",
                "game_date": "2026-06-05",
                "win": 1,
                "net_rating_est": 30.0,
                "efg_pct": 0.60,
                "opp_efg_pct": 0.30,
                "tov_pct": 0.10,
                "opp_tov_pct": 0.30,
                "oreb_pct": 0.30,
                "opp_oreb_pct": 0.10,
                "ftr": 0.30,
                "opp_ftr": 0.10,
            },
        ]
    )


class TeamStrengthTest(unittest.TestCase):
    def test_aggregates_only_games_at_or_before_cutoff_with_positive_is_good_factors(self) -> None:
        from standings_playoff_forecast.config import load_model_config, load_season_config
        from standings_playoff_forecast.team_strength import build_team_strength

        cfg = replace(load_season_config(2026), recent_window_games=1)
        result = build_team_strength(
            _team_games(), None, cfg, load_model_config(), cutoff="2026-06-03"
        ).set_index("team_id")

        alpha = result.loc["A"]
        self.assertEqual(alpha["season_games_played"], 2)
        self.assertEqual(alpha["recent_games_played"], 1)
        self.assertAlmostEqual(alpha["season_win_pct"], 1.0)
        self.assertAlmostEqual(alpha["season_net_rating"], 15.0)
        self.assertAlmostEqual(alpha["recent_net_rating"], 20.0)
        self.assertAlmostEqual(alpha["efg_diff"], 0.10)
        self.assertAlmostEqual(alpha["tov_diff"], 0.10)
        self.assertAlmostEqual(alpha["oreb_diff"], 0.10)
        self.assertAlmostEqual(alpha["ftr_diff"], 0.05)
        self.assertAlmostEqual(alpha["predictive_net_rating"], 16.5)
        self.assertAlmostEqual(alpha["composite_strength"], 1.0)

    def test_composite_strength_is_zero_when_every_in_season_factor_has_zero_variance(self) -> None:
        from standings_playoff_forecast.config import load_model_config, load_season_config
        from standings_playoff_forecast.team_strength import build_team_strength

        games = _team_games().loc[lambda rows: rows["game_date"] <= "2026-06-03"].copy()
        for column in (
            "win",
            "net_rating_est",
            "efg_pct",
            "opp_efg_pct",
            "tov_pct",
            "opp_tov_pct",
            "oreb_pct",
            "opp_oreb_pct",
            "ftr",
            "opp_ftr",
        ):
            games[column] = 1.0

        result = build_team_strength(
            games,
            None,
            replace(load_season_config(2026), recent_window_games=1),
            load_model_config(),
            cutoff="2026-06-03",
        )

        self.assertTrue(result["composite_strength"].notna().all())
        self.assertTrue(result["composite_strength"].eq(0.0).all())

    def test_attaches_pbpstats_context_only_with_explicit_snapshot_as_of_metadata(self) -> None:
        from standings_playoff_forecast.config import load_model_config, load_season_config
        from standings_playoff_forecast.team_strength import build_team_strength

        pbp = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "games_played": [2, 2],
                "plus_minus": [30, -30],
                "_featured_at_utc": ["2026-06-04T12:00:00Z"] * 2,
            }
        )
        pbp.attrs["pbpstats_snapshot_as_of"] = "2026-06-03T21:05:00+00:00"
        result = build_team_strength(
            _team_games(),
            pbp,
            replace(load_season_config(2026), recent_window_games=1),
            load_model_config(),
            cutoff="2026-06-03",
        ).set_index("team_id")

        alpha = result.loc["A"]
        self.assertTrue(alpha["pbpstats_snapshot_available"])
        self.assertEqual(alpha["pbpstats_snapshot_as_of"], "2026-06-03")
        self.assertTrue(alpha["pbpstats_snapshot_safe_for_cutoff"])
        self.assertEqual(alpha["pbpstats_games_played"], 2)
        self.assertEqual(alpha["pbpstats_plus_minus"], 30)

    def test_historical_cutoff_leaves_newer_pbpstats_snapshot_context_null(self) -> None:
        from standings_playoff_forecast.config import load_model_config, load_season_config
        from standings_playoff_forecast.team_strength import build_team_strength

        pbp = pd.DataFrame(
            {"team_id": ["A", "B"], "games_played": [2, 2], "plus_minus": [30, -30]}
        )
        pbp.attrs["snapshot_as_of"] = "2026-06-03"
        result = build_team_strength(
            _team_games(),
            pbp,
            replace(load_season_config(2026), recent_window_games=1),
            load_model_config(),
            cutoff="2026-06-01",
        ).set_index("team_id")

        alpha = result.loc["A"]
        self.assertTrue(alpha["pbpstats_snapshot_available"])
        self.assertEqual(alpha["pbpstats_snapshot_as_of"], "2026-06-03")
        self.assertFalse(alpha["pbpstats_snapshot_safe_for_cutoff"])
        self.assertTrue(pd.isna(alpha["pbpstats_games_played"]))
        self.assertTrue(pd.isna(alpha["pbpstats_plus_minus"]))

    def test_accepts_a_verified_snapshot_metadata_envelope(self) -> None:
        from standings_playoff_forecast.config import load_model_config, load_season_config
        from standings_playoff_forecast.team_strength import build_team_strength

        pbp = pd.DataFrame({"team_id": ["A", "B"], "plus_minus": [30, -30]})
        pbp.attrs["pbpstats_snapshot_metadata"] = {"as_of": "2026-06-03"}
        result = build_team_strength(
            _team_games(),
            pbp,
            replace(load_season_config(2026), recent_window_games=1),
            load_model_config(),
            cutoff="2026-06-03",
        ).set_index("team_id")

        self.assertEqual(result.loc["A", "pbpstats_snapshot_as_of"], "2026-06-03")
        self.assertTrue(result.loc["A", "pbpstats_snapshot_safe_for_cutoff"])
        self.assertEqual(result.loc["A", "pbpstats_plus_minus"], 30)

    def test_missing_pbpstats_snapshot_is_non_fatal_and_leaves_context_null(self) -> None:
        from standings_playoff_forecast.config import load_model_config, load_season_config
        from standings_playoff_forecast.team_strength import build_team_strength

        result = build_team_strength(
            _team_games(),
            None,
            replace(load_season_config(2026), recent_window_games=1),
            load_model_config(),
            cutoff="2026-06-03",
        ).set_index("team_id")

        alpha = result.loc["A"]
        self.assertFalse(alpha["pbpstats_snapshot_available"])
        self.assertTrue(pd.isna(alpha["pbpstats_snapshot_as_of"]))
        self.assertFalse(alpha["pbpstats_snapshot_safe_for_cutoff"])
        self.assertTrue(pd.isna(alpha["pbpstats_games_played"]))

    def test_pbpstats_context_uses_the_stable_franchise_crosswalk_for_different_id_systems(self) -> None:
        from standings_playoff_forecast.config import load_model_config, load_season_config
        from standings_playoff_forecast.team_strength import build_team_strength

        games = _team_games().loc[lambda rows: rows["team_id"] == "A"].copy()
        games["team_id"] = "17"
        games["franchise_id"] = "las_vegas_aces"
        pbp = pd.DataFrame(
            {"team_id": ["1611661319"], "games_played": [2], "plus_minus": [30]}
        )
        pbp.attrs["snapshot_as_of"] = "2026-06-03"
        result = build_team_strength(
            games,
            pbp,
            replace(load_season_config(2026), recent_window_games=1),
            load_model_config(),
            cutoff="2026-06-03",
        ).set_index("team_id")

        self.assertEqual(result.loc["17", "pbpstats_plus_minus"], 30)

    def test_feature_generation_timestamp_is_not_treated_as_snapshot_as_of_date(self) -> None:
        from standings_playoff_forecast.config import load_model_config, load_season_config
        from standings_playoff_forecast.team_strength import build_team_strength

        pbp = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "plus_minus": [30, -30],
                "_featured_at_utc": ["2026-06-03T12:00:00Z"] * 2,
            }
        )
        result = build_team_strength(
            _team_games(),
            pbp,
            replace(load_season_config(2026), recent_window_games=1),
            load_model_config(),
            cutoff="2026-06-03",
        ).set_index("team_id")

        alpha = result.loc["A"]
        self.assertTrue(alpha["pbpstats_snapshot_available"])
        self.assertTrue(pd.isna(alpha["pbpstats_snapshot_as_of"]))
        self.assertFalse(alpha["pbpstats_snapshot_safe_for_cutoff"])
        self.assertTrue(pd.isna(alpha["pbpstats_plus_minus"]))


if __name__ == "__main__":
    unittest.main()
