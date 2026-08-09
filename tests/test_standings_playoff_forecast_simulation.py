import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _season_config(
    *,
    team_count: int = 2,
    games_per_team: int = 1,
    qualifiers: int = 1,
    simulations: int = 6,
    tiebreaks: tuple[str, ...] = ("overall_point_diff",),
):
    from standings_playoff_forecast.config import load_season_config

    return replace(
        load_season_config(2026),
        team_count=team_count,
        regular_season_games_per_team=games_per_team,
        playoff_qualifiers=qualifiers,
        simulation_count=simulations,
        tiebreaks=tiebreaks,
    )


def _remaining(*rows: tuple[object, object, object, float, float, float]) -> pd.DataFrame:
    records = []
    for game_id, home_id, away_id, expected_margin, sigma, home_probability in rows:
        records.append(
            {
                "game_id": game_id,
                "home_id": home_id,
                "away_id": away_id,
                "expected_home_margin": expected_margin,
                "margin_sigma": sigma,
                "home_win_probability": home_probability,
                "away_win_probability": 1.0 - home_probability,
            }
        )
    return pd.DataFrame(
        records,
        columns=[
            "game_id",
            "home_id",
            "away_id",
            "expected_home_margin",
            "margin_sigma",
            "home_win_probability",
            "away_win_probability",
        ],
    )


def _completed_game(
    game_id: object,
    winner_id: object,
    loser_id: object,
    margin: int = 10,
) -> list[dict[str, object]]:
    return [
        {
            "game_id": game_id,
            "team_id": winner_id,
            "opponent_id": loser_id,
            "win": 1,
            "loss": 0,
            "margin": margin,
        },
        {
            "game_id": game_id,
            "team_id": loser_id,
            "opponent_id": winner_id,
            "win": 0,
            "loss": 1,
            "margin": -margin,
        },
    ]


def _empty_completed() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["game_id", "team_id", "opponent_id", "win", "loss", "margin"]
    )


class SimulationMarginAndSeedTest(unittest.TestCase):
    def test_rounds_zero_draws_away_from_zero_by_draw_sign_and_repeats_seed(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        remaining = _remaining(("g1", "A", "B", 0.0, 0.1, 0.5))
        cfg = _season_config()

        first = simulate_season(_empty_completed(), remaining, cfg, seed=314)
        repeated = simulate_season(_empty_completed(), remaining, cfg, seed=314)

        # Hand-checked NumPy Generator draws round to zero with signs --++++; the
        # production rule must retain those signs as non-zero integer margins.
        self.assertEqual(
            first.simulated_home_margins[:, 0].tolist(),
            [-1, -1, 1, 1, 1, 1],
        )
        self.assertTrue(np.issubdtype(first.simulated_home_margins.dtype, np.integer))
        self.assertFalse(np.any(first.simulated_home_margins == 0))
        np.testing.assert_array_equal(
            first.simulated_home_margins, repeated.simulated_home_margins
        )
        np.testing.assert_array_equal(first.final_ranks, repeated.final_ranks)
        assert_frame_equal(first.forecast_summary, repeated.forecast_summary)
        assert_frame_equal(
            first.rank_probability_matrix, repeated.rank_probability_matrix
        )

    def test_different_seed_changes_draws_and_result_arrays_are_read_only(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        remaining = _remaining(("g1", "A", "B", 0.0, 5.0, 0.5))
        cfg = _season_config(simulations=20)

        first = simulate_season(_empty_completed(), remaining, cfg, seed=11)
        second = simulate_season(_empty_completed(), remaining, cfg, seed=12)

        self.assertFalse(
            np.array_equal(
                first.simulated_home_margins,
                second.simulated_home_margins,
            )
        )
        with self.assertRaises(ValueError):
            first.simulated_home_margins[0, 0] = 99
        with self.assertRaises(FrozenInstanceError):
            first.seed = 99


class OfficialTiebreakSimulationTest(unittest.TestCase):
    def test_builds_final_state_and_recomputes_final_500_membership_per_run(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        completed = pd.DataFrame(
            [
                *_completed_game("g1", "X", "A"),
                *_completed_game("g2", "A", "Z"),
                *_completed_game("g3", "B", "X"),
                *_completed_game("g4", "Z", "B"),
            ]
        )
        remaining = _remaining(
            ("g5", "X", "Z", 10.0, 0.01, 0.999),
            ("g6", "X", "Z", 10.0, 0.01, 0.999),
            ("g7", "A", "B", 10.0, 0.01, 0.999),
            ("g8", "B", "A", 10.0, 0.01, 0.999),
        )
        cfg = _season_config(
            team_count=4,
            games_per_team=4,
            qualifiers=2,
            simulations=1,
            tiebreaks=("record_vs_final_500_plus",),
        )

        result = simulate_season(completed, remaining, cfg, seed=5)

        self.assertEqual(result.team_ids, ("A", "B", "X", "Z"))
        self.assertEqual(result.final_wins.tolist(), [[2, 2, 3, 1]])
        self.assertEqual(result.final_losses.tolist(), [[2, 2, 1, 3]])
        self.assertEqual(
            result.final_point_differentials.tolist(),
            [[0, 0, 20, -20]],
        )
        # B's 2-1 record against final .500+ teams beats A's 1-2 record.
        # Using the pre-simulation .500 set would leave the pair tied instead.
        self.assertEqual(result.final_ranks.tolist(), [[3, 2, 1, 4]])
        self.assertEqual(result.fallback_count, 0)

    def test_aggregates_official_fallback_usage_from_every_run(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        completed = pd.DataFrame(
            [
                *_completed_game("g1", "A", "B", margin=5),
                *_completed_game("g2", "B", "A", margin=5),
            ]
        )
        cfg = _season_config(
            games_per_team=2,
            simulations=3,
            tiebreaks=(
                "head_to_head_win_pct",
                "record_vs_final_500_plus",
                "head_to_head_point_diff",
                "overall_point_diff",
            ),
        )

        result = simulate_season(completed, _remaining(), cfg, seed=99)

        self.assertEqual(result.final_ranks.tolist(), [[1, 2], [1, 2], [1, 2]])
        self.assertEqual(result.fallback_count, 3)


class ProbabilityAggregationTest(unittest.TestCase):
    def test_preserves_exact_ranks_and_derives_configured_probability_bands(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        result = simulate_season(
            _empty_completed(),
            _remaining(("g1", "A", "B", 0.0, 0.1, 0.5)),
            _season_config(),
            seed=314,
        )

        summary = result.forecast_summary.set_index("team_id")
        self.assertEqual(
            list(summary.columns),
            [
                "season",
                "projected_wins_mean",
                "projected_losses_mean",
                "wins_p10",
                "wins_p50",
                "wins_p90",
                "expected_final_rank",
                "playoff_probability",
                "top4_probability",
                "home_court_probability",
                "rank_1_probability",
                "rank_2_probability",
                "out_probability",
            ],
        )
        self.assertAlmostEqual(summary.loc["A", "projected_wins_mean"], 2 / 3)
        self.assertAlmostEqual(summary.loc["B", "projected_wins_mean"], 1 / 3)
        self.assertAlmostEqual(summary.loc["A", "expected_final_rank"], 4 / 3)
        self.assertAlmostEqual(summary.loc["B", "expected_final_rank"], 5 / 3)
        self.assertAlmostEqual(summary.loc["A", "rank_1_probability"], 2 / 3)
        self.assertAlmostEqual(summary.loc["A", "rank_2_probability"], 1 / 3)
        self.assertAlmostEqual(summary.loc["A", "playoff_probability"], 2 / 3)
        self.assertAlmostEqual(summary.loc["A", "top4_probability"], 2 / 3)
        self.assertAlmostEqual(summary.loc["A", "home_court_probability"], 2 / 3)
        self.assertAlmostEqual(summary.loc["A", "out_probability"], 1 / 3)
        self.assertEqual(
            summary.loc["A", ["wins_p10", "wins_p50", "wins_p90"]].tolist(),
            [0.0, 1.0, 1.0],
        )

        matrix = result.rank_probability_matrix
        self.assertEqual(
            list(matrix.columns),
            ["season", "team_id", "final_rank", "probability", "playoff_rank"],
        )
        self.assertEqual(len(matrix), 4)
        self.assertEqual(
            matrix[["team_id", "final_rank"]].values.tolist(),
            [["A", 1], ["A", 2], ["B", 1], ["B", 2]],
        )
        self.assertEqual(matrix.loc[matrix["final_rank"].eq(1), "playoff_rank"].tolist(), [1, 1])
        self.assertTrue(matrix.loc[matrix["final_rank"].eq(2), "playoff_rank"].isna().all())

        rank_wide = matrix.pivot(index="team_id", columns="final_rank", values="probability")
        np.testing.assert_allclose(rank_wide.sum(axis=1).to_numpy(), 1.0)
        np.testing.assert_allclose(rank_wide.sum(axis=0).to_numpy(), 1.0)
        self.assertAlmostEqual(summary["playoff_probability"].sum(), 1.0)
        self.assertTrue(matrix["probability"].between(0.0, 1.0).all())

    def test_probability_mass_validator_rejects_team_and_rank_mass_drift(self) -> None:
        from standings_playoff_forecast.simulation import _validate_probability_mass

        cfg = _season_config(simulations=10)
        summary = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "playoff_probability": [0.6, 0.4],
                "top4_probability": [0.6, 0.4],
                "home_court_probability": [0.6, 0.4],
                "out_probability": [0.5, 0.5],
                "rank_1_probability": [0.6, 0.4],
                "rank_2_probability": [0.5, 0.5],
            }
        )
        bad_team_mass = pd.DataFrame(
            {
                "team_id": ["A", "A", "B", "B"],
                "final_rank": [1, 2, 1, 2],
                "probability": [0.6, 0.5, 0.4, 0.5],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "each team's rank probabilities must sum to 1",
        ):
            _validate_probability_mass(summary, bad_team_mass, cfg)

        bad_rank_mass = bad_team_mass.copy()
        bad_rank_mass["probability"] = [0.7, 0.3, 0.4, 0.6]
        with self.assertRaisesRegex(
            ValueError,
            "each rank's league probability must sum to 1",
        ):
            _validate_probability_mass(summary, bad_rank_mass, cfg)

    def test_simulation_state_validator_rejects_broken_run_invariants(self) -> None:
        from standings_playoff_forecast.simulation import _validate_simulation_state

        cfg = _season_config(simulations=1)
        valid = {
            "final_wins": np.array([[1, 0]], dtype=np.int64),
            "final_losses": np.array([[0, 1]], dtype=np.int64),
            "final_point_differentials": np.array([[5, -5]], dtype=np.int64),
            "final_ranks": np.array([[1, 2]], dtype=np.int64),
            "simulated_home_margins": np.array([[5]], dtype=np.int64),
        }
        corruptions = (
            (
                "simulated_home_margins",
                np.array([[0]], dtype=np.int64),
                "simulated margins must be non-zero",
            ),
            (
                "final_losses",
                np.array([[1, 1]], dtype=np.int64),
                "every final team must reach 1 games",
            ),
            (
                "final_point_differentials",
                np.array([[5, -4]], dtype=np.int64),
                "league point differential must sum to zero in every run",
            ),
            (
                "final_ranks",
                np.array([[1, 1]], dtype=np.int64),
                "every run must assign each exact rank once",
            ),
        )
        for field, value, message in corruptions:
            with self.subTest(field=field):
                state = {**valid, field: value}
                with self.assertRaisesRegex(ValueError, message):
                    _validate_simulation_state(cfg=cfg, **state)

    def test_probability_validator_rejects_missing_cells_and_summary_drift(self) -> None:
        from standings_playoff_forecast.simulation import _validate_probability_mass

        cfg = _season_config(simulations=10)
        matrix = pd.DataFrame(
            {
                "team_id": ["A", "A", "B", "B"],
                "final_rank": [1, 2, 1, 2],
                "probability": [0.6, 0.4, 0.4, 0.6],
            }
        )
        summary = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "playoff_probability": [0.6, 0.4],
                "top4_probability": [0.6, 0.4],
                "home_court_probability": [0.6, 0.4],
                "out_probability": [0.4, 0.6],
                "rank_1_probability": [0.6, 0.4],
                "rank_2_probability": [0.4, 0.6],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "rank probability matrix must contain every team-rank cell exactly once",
        ):
            _validate_probability_mass(summary, matrix.iloc[:-1], cfg)

        drifted_summary = summary.copy()
        drifted_summary["playoff_probability"] = [0.5, 0.5]
        with self.assertRaisesRegex(
            ValueError,
            "summary probability bands must match the exact-rank matrix",
        ):
            _validate_probability_mass(drifted_summary, matrix, cfg)


class SimulationInputValidationTest(unittest.TestCase):
    def test_normalizes_stable_ids_before_building_the_team_universe(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        result = simulate_season(
            _empty_completed(),
            _remaining((1.0, 1.0, "2.0", 2.0, 1.0, 0.75)),
            _season_config(simulations=1),
            seed=4,
        )

        self.assertEqual(result.team_ids, ("1", "2"))
        self.assertEqual(result.remaining_game_ids, ("1",))
        self.assertEqual(
            result.rank_probability_matrix["team_id"].drop_duplicates().tolist(),
            ["1", "2"],
        )

    def test_rejects_missing_completed_and_remaining_contract_columns(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        remaining = _remaining(("g1", "A", "B", 2.0, 1.0, 0.75))
        with self.assertRaisesRegex(
            ValueError,
            "completed_games is missing required columns: margin",
        ):
            simulate_season(
                _empty_completed().drop(columns="margin"),
                remaining,
                _season_config(simulations=1),
                seed=1,
            )

        with self.assertRaisesRegex(
            ValueError,
            "scored_remaining is missing required columns: margin_sigma",
        ):
            simulate_season(
                _empty_completed(),
                remaining.drop(columns="margin_sigma"),
                _season_config(simulations=1),
                seed=1,
            )

    def test_rejects_missing_or_identical_game_participants(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        with self.assertRaisesRegex(
            ValueError,
            "scored_remaining contains missing game or team identifiers",
        ):
            simulate_season(
                _empty_completed(),
                _remaining(("g1", "A", None, 2.0, 1.0, 0.75)),
                _season_config(simulations=1),
                seed=1,
            )

        with self.assertRaisesRegex(
            ValueError,
            "scored_remaining contains a game with identical participants: g1",
        ):
            simulate_season(
                _empty_completed(),
                _remaining(("g1", "A", " A ", 2.0, 1.0, 0.75)),
                _season_config(simulations=1),
                seed=1,
            )

    def test_rejects_duplicate_or_overlapping_normalized_game_ids(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        duplicate_remaining = _remaining(
            (1.0, "A", "B", 2.0, 1.0, 0.75),
            ("1", "B", "A", -2.0, 1.0, 0.25),
        )
        with self.assertRaisesRegex(
            ValueError,
            "scored_remaining contains duplicate normalized game_id: 1",
        ):
            simulate_season(
                _empty_completed(),
                duplicate_remaining,
                _season_config(games_per_team=2, simulations=1),
                seed=1,
            )

        completed = pd.DataFrame(_completed_game("g1", "A", "B"))
        with self.assertRaisesRegex(
            ValueError,
            "completed and remaining games overlap: g1",
        ):
            simulate_season(
                completed,
                _remaining(("g1", "A", "B", 2.0, 1.0, 0.75)),
                _season_config(games_per_team=2, simulations=1),
                seed=1,
            )

    def test_rejects_nonreciprocal_completed_results(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        bad_margin = pd.DataFrame(_completed_game("g1", "A", "B"))
        bad_margin.loc[1, "margin"] = 10
        both_winners = pd.DataFrame(_completed_game("g1", "A", "B"))
        both_winners.loc[1, ["win", "loss"]] = [1, 0]
        fractional_margin = pd.DataFrame(_completed_game("g1", "A", "B"))
        fractional_margin["margin"] = [0.5, -0.5]

        for malformed in (bad_margin, both_winners, fractional_margin):
            with self.subTest(rows=malformed.to_dict("records")):
                with self.assertRaisesRegex(
                    ValueError,
                    "completed_games must contain reciprocal directional results: g1",
                ):
                    simulate_season(
                        malformed,
                        _remaining(),
                        _season_config(simulations=1),
                        seed=1,
                    )

    def test_rejects_nonfinite_matchup_probabilities_margins_and_sigmas(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        remaining = _remaining(("g1", "A", "B", 2.0, 1.0, 0.75))
        invalid_values = {
            "expected_home_margin": np.nan,
            "margin_sigma": np.inf,
            "home_win_probability": np.nan,
            "away_win_probability": -np.inf,
        }
        for column, value in invalid_values.items():
            with self.subTest(column=column):
                malformed = remaining.copy()
                malformed.loc[0, column] = value
                with self.assertRaisesRegex(
                    ValueError,
                    f"scored_remaining contains non-finite {column}: g1",
                ):
                    simulate_season(
                        _empty_completed(),
                        malformed,
                        _season_config(simulations=1),
                        seed=1,
                    )

    def test_rejects_nonpositive_sigma_and_invalid_probability_mass(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        remaining = _remaining(("g1", "A", "B", 2.0, 1.0, 0.75))
        invalid_cases = (
            ("margin_sigma", 0.0, "margin_sigma must be positive: g1"),
            (
                "home_win_probability",
                1.1,
                r"matchup probabilities must be within \[0, 1\]: g1",
            ),
            (
                "away_win_probability",
                0.5,
                "home and away matchup probabilities must sum to 1: g1",
            ),
        )
        for column, value, message in invalid_cases:
            with self.subTest(column=column):
                malformed = remaining.copy()
                malformed.loc[0, column] = value
                with self.assertRaisesRegex(ValueError, message):
                    simulate_season(
                        _empty_completed(),
                        malformed,
                        _season_config(simulations=1),
                        seed=1,
                    )

    def test_rejects_team_universe_and_completed_plus_remaining_count_mismatches(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        remaining = _remaining(("g1", "A", "B", 2.0, 1.0, 0.75))
        with self.assertRaisesRegex(
            ValueError,
            "simulation team universe has 2 teams; expected 3",
        ):
            simulate_season(
                _empty_completed(),
                remaining,
                _season_config(team_count=3, qualifiers=2, simulations=1),
                seed=1,
            )

        with self.assertRaisesRegex(
            ValueError,
            "completed plus remaining games do not equal 2 for every team: A=1, B=1",
        ):
            simulate_season(
                _empty_completed(),
                remaining,
                _season_config(games_per_team=2, simulations=1),
                seed=1,
            )

    def test_uses_configured_count_and_validates_runtime_controls(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        remaining = _remaining(("g1", "A", "B", 2.0, 1.0, 0.75))
        cfg = _season_config(simulations=3)

        configured = simulate_season(_empty_completed(), remaining, cfg, seed=1)
        overridden = simulate_season(
            _empty_completed(),
            remaining,
            cfg,
            simulation_count=2,
            seed=1,
        )

        self.assertEqual(configured.simulation_count, 3)
        self.assertEqual(overridden.simulation_count, 2)
        for invalid_count in (0, -1, 1.5, True):
            with self.subTest(simulation_count=invalid_count):
                with self.assertRaisesRegex(
                    ValueError,
                    "simulation_count must be a positive integer",
                ):
                    simulate_season(
                        _empty_completed(),
                        remaining,
                        cfg,
                        simulation_count=invalid_count,
                        seed=1,
                    )
        with self.assertRaisesRegex(ValueError, "seed must be an integer"):
            simulate_season(
                _empty_completed(),
                remaining,
                cfg,
                simulation_count=1,
                seed=1.5,
            )

    def test_rejects_invalid_competition_dimensions(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        cases = (
            (
                replace(_season_config(), team_count=0),
                "team_count must be positive",
            ),
            (
                replace(_season_config(), regular_season_games_per_team=0),
                "regular_season_games_per_team must be positive",
            ),
            (
                replace(_season_config(), playoff_qualifiers=0),
                "playoff_qualifiers must be between 1 and team_count",
            ),
            (
                replace(_season_config(), playoff_qualifiers=3),
                "playoff_qualifiers must be between 1 and team_count",
            ),
        )
        for cfg, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    simulate_season(
                        _empty_completed(),
                        _remaining(("g1", "A", "B", 2.0, 1.0, 0.75)),
                        cfg,
                        simulation_count=1,
                        seed=1,
                    )

    def test_rejects_simulated_margins_outside_supported_integer_range(self) -> None:
        from standings_playoff_forecast.simulation import simulate_season

        with self.assertRaisesRegex(
            ValueError,
            "simulated margin exceeds supported integer range",
        ):
            simulate_season(
                _empty_completed(),
                _remaining(("g1", "A", "B", 3_000_000_000.0, 0.01, 1.0)),
                _season_config(simulations=1),
                seed=1,
            )


if __name__ == "__main__":
    unittest.main()
