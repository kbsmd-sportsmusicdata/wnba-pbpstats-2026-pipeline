import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _cfg():
    from standings_playoff_forecast.config import load_season_config

    return replace(
        load_season_config(2026),
        team_count=6,
        playoff_qualifiers=5,
        regular_season_games_per_team=2,
        simulation_count=4,
        tiebreaks=("head_to_head_win_pct", "overall_point_diff"),
    )


def _simulation_result(*, all_home_wins: bool = False):
    from standings_playoff_forecast.simulation import SimulationResult

    team_ids = ("A", "B", "C", "D", "E", "F")
    ranks = np.array(
        [
            [1, 6, 2, 3, 4, 5],
            [6, 1, 2, 3, 4, 5],
            [3, 5, 1, 2, 4, 6],
            [5, 3, 1, 2, 4, 6],
        ],
        dtype=np.int32,
    )
    margins = np.array(
        [[1, 1], [-1, 1], [1, 1], [-1, -1]], dtype=np.int32
    )
    if all_home_wins:
        margins[:, 0] = 1
    summary = pd.DataFrame(
        {
            "team_id": team_ids,
            "season": 2026,
            "expected_final_rank": ranks.mean(axis=0),
            "playoff_probability": (ranks <= 5).mean(axis=0),
            "top4_probability": (ranks <= 4).mean(axis=0),
            "rank_1_probability": (ranks == 1).mean(axis=0),
        }
    )
    matrix = pd.DataFrame(
        [
            {
                "season": 2026,
                "team_id": team_id,
                "final_rank": rank,
                "probability": float((ranks[:, team_index] == rank).mean()),
                "playoff_rank": rank if rank <= 5 else pd.NA,
            }
            for team_index, team_id in enumerate(team_ids)
            for rank in range(1, 7)
        ]
    )
    shape = (4, 6)
    return SimulationResult(
        forecast_summary=summary,
        rank_probability_matrix=matrix,
        fallback_count=0,
        simulation_count=4,
        seed=7,
        team_ids=team_ids,
        remaining_game_ids=("g1", "g2"),
        final_wins=np.zeros(shape, dtype=np.int32),
        final_losses=np.zeros(shape, dtype=np.int32),
        final_point_differentials=np.zeros(shape, dtype=np.int64),
        final_ranks=ranks,
        simulated_home_margins=margins,
    )


def _remaining() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": "2026-09-01",
                "home_id": "A",
                "away_id": "B",
                "home_win_probability": 0.5,
                "away_win_probability": 0.5,
            },
            {
                "game_id": "g2",
                "game_date": "2026-09-02",
                "home_id": "C",
                "away_id": "A",
                "home_win_probability": 0.75,
                "away_win_probability": 0.25,
            },
        ]
    )


def _standings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "team_id": ["A", "B", "C", "D", "E", "F"],
            "team_name": ["Alpha", "Beta", "Charlie", "Delta", "Echo", "Foxtrot"],
            "current_rank": [5, 6, 4, 3, 2, 1],
            "wins": [10, 10, 12, 11, 13, 14],
            "losses": [10, 10, 8, 9, 7, 6],
            "point_differential": [0, -1, 20, 10, 25, 30],
        }
    )


def _forecast_summary() -> pd.DataFrame:
    result = _simulation_result().forecast_summary.copy()
    result["rank_1_probability"] = [0.4, 0.4, 0.1, 0.05, 0.03, 0.02]
    return result


def _strength() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "team_id": ["A", "B", "C", "D", "E", "F"],
            "recent_net_rating": [1.0, -2.0, 3.0, 0.0, 8.0, 8.0],
        }
    )


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "context_level": "aggregate",
                "metric": "same_progress_playoff_rate",
                "season": pd.NA,
                "season_count": 4,
                "seed_band": pd.NA,
                "qualifier_rank": 5,
                "team_id": pd.NA,
                "target_progress_pct": 0.75,
                "as_of_progress_pct": pd.NA,
                "as_of_net_rating": pd.NA,
                "final_rank": pd.NA,
                "value": 0.625,
                "sample_size": 24,
                "availability_status": "available",
            }
        ]
    )


class GameLeverageTest(unittest.TestCase):
    def test_conditions_on_stored_game_branches_with_home_oriented_signed_swings(self) -> None:
        """Catches selecting the wrong game column or reversing conditional signs."""
        from standings_playoff_forecast.leverage import calculate_game_leverage

        result = calculate_game_leverage(
            _remaining(), _simulation_result(), _standings(), _cfg()
        ).set_index("game_id")

        g1 = result.loc["g1"]
        self.assertEqual((g1["home_win_branch_n"], g1["home_loss_branch_n"]), (2, 2))
        self.assertTrue(g1["conditional_estimate_available"])
        self.assertAlmostEqual(g1["home_playoff_probability_swing"], 0.5)
        self.assertAlmostEqual(g1["away_playoff_probability_swing"], -0.5)
        self.assertAlmostEqual(g1["home_top4_probability_swing"], 1.0)
        self.assertAlmostEqual(g1["away_top4_probability_swing"], -1.0)
        self.assertAlmostEqual(g1["home_expected_rank_swing"], 3.5)
        self.assertAlmostEqual(g1["away_expected_rank_swing"], -3.5)
        self.assertTrue(g1["direct_h2h_tiebreak_flag"])
        self.assertTrue(g1["cutline_matchup_flag"])
        self.assertFalse(g1["top4_matchup_flag"])
        self.assertTrue(result.loc["g2", "top4_matchup_flag"])
        self.assertEqual(result["leverage_score"].tolist(), [100.0, 0.0])
        self.assertEqual(result["leverage_label"].tolist(), ["Critical", "Low"])

    def test_zero_sample_branch_is_explicitly_unavailable(self) -> None:
        """Catches fabricated conditional probabilities for an empty branch."""
        from standings_playoff_forecast.leverage import calculate_game_leverage

        result = calculate_game_leverage(
            _remaining(), _simulation_result(all_home_wins=True), _standings(), _cfg()
        )

        g1 = result.loc[result["game_id"].eq("g1")].iloc[0]
        self.assertEqual((g1["home_win_branch_n"], g1["home_loss_branch_n"]), (4, 0))
        self.assertFalse(g1["conditional_estimate_available"])
        self.assertTrue(pd.isna(g1["home_playoff_probability_if_home_loss"]))
        self.assertTrue(pd.isna(g1["home_playoff_probability_swing"]))

    def test_game_order_must_match_the_owned_simulation_columns(self) -> None:
        """Catches positional conditioning after the scored schedule is reordered."""
        from standings_playoff_forecast.leverage import calculate_game_leverage

        with self.assertRaisesRegex(ValueError, "remaining game order"):
            calculate_game_leverage(
                _remaining().iloc[::-1].reset_index(drop=True),
                _simulation_result(),
                _standings(),
                _cfg(),
            )


class BroadcastInsightsTest(unittest.TestCase):
    def _leverage(self) -> pd.DataFrame:
        from standings_playoff_forecast.leverage import calculate_game_leverage

        return calculate_game_leverage(
            _remaining(), _simulation_result(), _standings(), _cfg()
        )

    def test_emits_exact_priority_categories_and_traceable_actionable_fields(self) -> None:
        """Catches omitted/duplicate stories and non-deterministic tied leaders."""
        from standings_playoff_forecast.broadcast_insights import (
            INSIGHT_COLUMNS,
            build_broadcast_insights,
        )

        insights = build_broadcast_insights(
            _forecast_summary(),
            _standings(),
            _strength(),
            _remaining(),
            self._leverage(),
            _cfg(),
            historical_context=_history(),
        )

        self.assertEqual(insights.columns.tolist(), INSIGHT_COLUMNS)
        self.assertEqual(insights["priority"].tolist(), list(range(1, 11)))
        self.assertEqual(
            insights["category"].tolist(),
            [
                "leader_race",
                "playoff_cutline",
                "top4_race",
                "tiebreak_watch",
                "remaining_sos",
                "most_likely_riser",
                "most_vulnerable_seed",
                "recent_form",
                "high_leverage_game",
                "historical_context",
            ],
        )
        self.assertEqual(insights.loc[0, "team_or_race"], "A")
        self.assertEqual(insights.loc[7, "team_or_race"], "E")
        for column in INSIGHT_COLUMNS[1:]:
            self.assertTrue(insights[column].map(lambda value: isinstance(value, str) and bool(value)).all())
        self.assertIn("forecast_summary.rank_1_probability", insights.loc[0, "source_fields"])
        self.assertIn("historical_context.value", insights.loc[9, "source_fields"])
        self.assertIn("halftime", insights.loc[8, "halftime_checkpoint"].lower())
        self.assertIn("fourth quarter", insights.loc[8, "fourth_quarter_checkpoint"].lower())

    def test_missing_history_replaces_only_last_story_with_distinct_schedule_watch(self) -> None:
        """Catches shrinking the list or emitting unsupported historical prose."""
        from standings_playoff_forecast.broadcast_insights import build_broadcast_insights

        insights = build_broadcast_insights(
            _forecast_summary(),
            _standings(),
            _strength(),
            _remaining(),
            self._leverage(),
            _cfg(),
            historical_context=pd.DataFrame(),
        )

        self.assertEqual(len(insights), 10)
        self.assertEqual(insights.loc[9, "category"], "schedule_watch")
        self.assertNotIn("historical_context", insights["category"].tolist())
        self.assertIn("g2", insights.loc[9, "data_point"])
        self.assertNotEqual(insights.loc[8, "data_point"], insights.loc[9, "data_point"])

    def test_no_remaining_games_keeps_a_defined_ten_story_fallback(self) -> None:
        """Catches a completed schedule collapsing the broadcaster card."""
        from standings_playoff_forecast.broadcast_insights import build_broadcast_insights
        from standings_playoff_forecast.leverage import LEVERAGE_COLUMNS

        empty_remaining = _remaining().iloc[0:0].copy()
        insights = build_broadcast_insights(
            _forecast_summary(),
            _standings(),
            _strength(),
            empty_remaining,
            pd.DataFrame(columns=LEVERAGE_COLUMNS),
            _cfg(),
            historical_context=None,
        )

        self.assertEqual(len(insights), 10)
        self.assertEqual(insights.loc[8, "category"], "high_leverage_game")
        self.assertEqual(insights.loc[9, "category"], "schedule_watch")
        self.assertIn("No remaining games", insights.loc[8, "data_point"])

    def test_rejects_forecast_probabilities_outside_unit_interval(self) -> None:
        """Catches broadcaster prose built from invalid forecast mass."""
        from standings_playoff_forecast.broadcast_insights import build_broadcast_insights

        forecast = _forecast_summary()
        forecast.loc[0, "playoff_probability"] = 1.1
        with self.assertRaisesRegex(ValueError, "probabilities"):
            build_broadcast_insights(
                forecast,
                _standings(),
                _strength(),
                _remaining(),
                self._leverage(),
                _cfg(),
            )


if __name__ == "__main__":
    unittest.main()
