import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _team_games() -> pd.DataFrame:
    """Hand-checked fixtures: each completed game has reciprocal team rows."""

    return pd.DataFrame(
        [
            # 2026-06-01: A defeats B, 80-70.
            {"game_id": "1", "game_date": "2026-06-01", "team_id": "A", "team_abbreviation": "AAA", "team_name": "Alpha", "franchise_id": "alpha", "opponent_id": "B", "opponent_franchise_id": "bravo", "win": 1, "loss": 0, "points_for": 80, "points_against": 70, "margin": 10},
            {"game_id": "1", "game_date": "2026-06-01", "team_id": "B", "team_abbreviation": "BBB", "team_name": "Bravo", "franchise_id": "bravo", "opponent_id": "A", "opponent_franchise_id": "alpha", "win": 0, "loss": 1, "points_for": 70, "points_against": 80, "margin": -10},
            # 2026-06-02: B defeats C, 75-72.
            {"game_id": "2", "game_date": "2026-06-02", "team_id": "B", "team_abbreviation": "BBB", "team_name": "Bravo", "franchise_id": "bravo", "opponent_id": "C", "opponent_franchise_id": "charlie", "win": 1, "loss": 0, "points_for": 75, "points_against": 72, "margin": 3},
            {"game_id": "2", "game_date": "2026-06-02", "team_id": "C", "team_abbreviation": "CCC", "team_name": "Charlie", "franchise_id": "charlie", "opponent_id": "B", "opponent_franchise_id": "bravo", "win": 0, "loss": 1, "points_for": 72, "points_against": 75, "margin": -3},
            # 2026-06-03: C defeats A, 90-85.
            {"game_id": "3", "game_date": "2026-06-03", "team_id": "C", "team_abbreviation": "CCC", "team_name": "Charlie", "franchise_id": "charlie", "opponent_id": "A", "opponent_franchise_id": "alpha", "win": 1, "loss": 0, "points_for": 90, "points_against": 85, "margin": 5},
            {"game_id": "3", "game_date": "2026-06-03", "team_id": "A", "team_abbreviation": "AAA", "team_name": "Alpha", "franchise_id": "alpha", "opponent_id": "C", "opponent_franchise_id": "charlie", "win": 0, "loss": 1, "points_for": 85, "points_against": 90, "margin": -5},
            # 2026-06-04: B defeats A, 81-79.
            {"game_id": "4", "game_date": "2026-06-04", "team_id": "B", "team_abbreviation": "BBB", "team_name": "Bravo", "franchise_id": "bravo", "opponent_id": "A", "opponent_franchise_id": "alpha", "win": 1, "loss": 0, "points_for": 81, "points_against": 79, "margin": 2},
            {"game_id": "4", "game_date": "2026-06-04", "team_id": "A", "team_abbreviation": "AAA", "team_name": "Alpha", "franchise_id": "alpha", "opponent_id": "B", "opponent_franchise_id": "bravo", "win": 0, "loss": 1, "points_for": 79, "points_against": 81, "margin": -2},
        ]
    )


def _long_form_standings(*, alpha_wins: int, alpha_losses: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"team_id": "A", "stat_name": "wins", "value": alpha_wins},
            {"team_id": "A", "stat_name": "losses", "value": alpha_losses},
            {"team_id": "B", "stat_name": "wins", "value": 2},
            {"team_id": "B", "stat_name": "losses", "value": 1},
            {"team_id": "C", "stat_name": "wins", "value": 1},
            {"team_id": "C", "stat_name": "losses", "value": 1},
        ]
    )


class StandingsAggregationTest(unittest.TestCase):
    def test_build_current_standings_aggregates_each_directional_team_game_once(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import build_current_standings

        standings = build_current_standings(_team_games(), load_season_config(2026))
        actual = standings.set_index("team_id").loc[
            ["A", "B", "C"], ["games_played", "wins", "losses", "points_for", "points_against", "point_differential"]
        ].to_dict("index")

        self.assertEqual(
            actual,
            {
                "A": {"games_played": 3, "wins": 1, "losses": 2, "points_for": 244, "points_against": 241, "point_differential": 3},
                "B": {"games_played": 3, "wins": 2, "losses": 1, "points_for": 226, "points_against": 231, "point_differential": -5},
                "C": {"games_played": 2, "wins": 1, "losses": 1, "points_for": 162, "points_against": 160, "point_differential": 2},
            },
        )

    def test_build_head_to_head_keeps_reciprocal_directional_records_separate(self) -> None:
        from standings_playoff_forecast.standings import build_head_to_head

        head_to_head = build_head_to_head(_team_games()).set_index(["team_id", "opponent_id"])

        self.assertEqual(
            head_to_head.loc[("A", "B"), ["games_played", "wins", "losses", "points_for", "points_against", "point_differential"]].to_dict(),
            {"games_played": 2, "wins": 1, "losses": 1, "points_for": 159, "points_against": 151, "point_differential": 8},
        )
        self.assertEqual(
            head_to_head.loc[("B", "A"), ["games_played", "wins", "losses", "points_for", "points_against", "point_differential"]].to_dict(),
            {"games_played": 2, "wins": 1, "losses": 1, "points_for": 151, "points_against": 159, "point_differential": -8},
        )


class StandingsReconciliationTest(unittest.TestCase):
    def test_latest_cutoff_reconciles_derived_record_against_long_form_source(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import build_current_standings, reconcile_standings

        derived = build_current_standings(_team_games(), load_season_config(2026))
        result = reconcile_standings(
            derived,
            _long_form_standings(alpha_wins=1, alpha_losses=2),
            cutoff="2026-06-04",
            latest_completed_game_date="2026-06-04",
        )

        self.assertEqual(result, "source_snapshot_reconciled")

    def test_latest_cutoff_rejects_source_record_mismatch(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import build_current_standings, reconcile_standings

        derived = build_current_standings(_team_games(), load_season_config(2026))

        with self.assertRaisesRegex(ValueError, "source standings mismatch.*team_id=A"):
            reconcile_standings(
                derived,
                _long_form_standings(alpha_wins=2, alpha_losses=1),
                cutoff="2026-06-04",
                latest_completed_game_date="2026-06-04",
            )

    def test_historical_cutoff_validates_internal_invariants_without_future_source_comparison(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import build_current_standings, reconcile_standings

        derived = build_current_standings(
            _team_games().loc[lambda rows: rows["game_date"] <= "2026-06-02"],
            load_season_config(2026),
        )
        result = reconcile_standings(
            derived,
            _long_form_standings(alpha_wins=1, alpha_losses=2),
            cutoff="2026-06-02",
            latest_completed_game_date="2026-06-04",
        )

        self.assertEqual(result, "historical_cutoff_invariants_validated")


if __name__ == "__main__":
    unittest.main()
