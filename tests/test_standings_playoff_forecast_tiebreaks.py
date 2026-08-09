import sys
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _season_config(*criteria: str, restart: bool = True):
    from standings_playoff_forecast.config import load_season_config

    return replace(
        load_season_config(2026),
        tiebreaks=criteria,
        multi_team_restart_after_elimination=restart,
    )


def _final_state(*rows: tuple[object, int, int, int]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["team_id", "wins", "losses", "point_differential"],
    )


def _game(
    game_id: str,
    winner_id: object,
    loser_id: object,
    winner_points: int = 80,
    loser_points: int = 70,
) -> list[dict[str, object]]:
    margin = winner_points - loser_points
    return [
        {
            "game_id": game_id,
            "team_id": winner_id,
            "opponent_id": loser_id,
            "win": 1,
            "loss": 0,
            "points_for": winner_points,
            "points_against": loser_points,
            "margin": margin,
        },
        {
            "game_id": game_id,
            "team_id": loser_id,
            "opponent_id": winner_id,
            "win": 0,
            "loss": 1,
            "points_for": loser_points,
            "points_against": winner_points,
            "margin": -margin,
        },
    ]


class TiebreakCriteriaTest(unittest.TestCase):
    def test_head_to_head_win_percentage_uses_each_directional_team_row_once(self) -> None:
        from standings_playoff_forecast.tiebreaks import resolve_tied_group

        final_state = _final_state(("A", 10, 10, 0), ("B", 10, 10, 0))
        all_games = pd.DataFrame(_game("1", "B", "A"))

        result = resolve_tied_group(
            ["A", "B"],
            final_state,
            all_games,
            _season_config("head_to_head_win_pct"),
        )

        self.assertEqual(result.ordered_team_ids, ("B", "A"))
        self.assertEqual(result.fallback_count, 0)

    def test_record_vs_final_500_plus_recomputes_qualifiers_from_final_state(self) -> None:
        from standings_playoff_forecast.tiebreaks import resolve_tied_group

        final_state = _final_state(
            ("A", 10, 10, 0),
            ("B", 10, 10, 0),
            ("X", 12, 8, 0),
            ("Z", 8, 12, 0),
        )
        all_games = pd.DataFrame(
            [
                *_game("1", "A", "X"),
                *_game("2", "Z", "A"),
                *_game("3", "X", "B"),
                *_game("4", "B", "Z"),
            ]
        )

        result = resolve_tied_group(
            ["B", "A"],
            final_state,
            all_games,
            _season_config("record_vs_final_500_plus"),
        )

        self.assertEqual(result.ordered_team_ids, ("A", "B"))
        self.assertEqual(result.fallback_count, 0)

    def test_head_to_head_point_differential_sums_only_tied_team_games(self) -> None:
        from standings_playoff_forecast.tiebreaks import resolve_tied_group

        final_state = _final_state(("A", 10, 10, 0), ("B", 10, 10, 0))
        all_games = pd.DataFrame(
            [
                *_game("1", "A", "B", 90, 70),
                *_game("2", "B", "A", 81, 80),
            ]
        )

        result = resolve_tied_group(
            ["B", "A"],
            final_state,
            all_games,
            _season_config("head_to_head_point_diff"),
        )

        self.assertEqual(result.ordered_team_ids, ("A", "B"))
        self.assertEqual(result.fallback_count, 0)

    def test_overall_point_differential_uses_supplied_final_team_state(self) -> None:
        from standings_playoff_forecast.tiebreaks import resolve_tied_group

        final_state = _final_state(("A", 10, 10, 5), ("B", 10, 10, 20))
        all_games = pd.DataFrame(columns=["game_id", "team_id", "opponent_id", "win", "margin"])

        result = resolve_tied_group(
            ["A", "B"],
            final_state,
            all_games,
            _season_config("overall_point_diff"),
        )

        self.assertEqual(result.ordered_team_ids, ("B", "A"))
        self.assertEqual(result.fallback_count, 0)


class MultiTeamRestartTest(unittest.TestCase):
    def test_reduced_multi_team_tie_restarts_at_head_to_head_win_percentage(self) -> None:
        from standings_playoff_forecast.tiebreaks import resolve_tied_group

        final_state = _final_state(
            ("A", 20, 20, 0),
            ("B", 20, 20, 0),
            ("C", 20, 20, 0),
        )
        all_games = pd.DataFrame(
            [
                # B wins the reduced B/C series 2-1, but C owns its point differential.
                *_game("1", "B", "C", 81, 80),
                *_game("2", "B", "C", 76, 75),
                *_game("3", "C", "B", 90, 70),
                # Across the original group: A is 3-1; B and C are both 2-3.
                *_game("4", "A", "B"),
                *_game("5", "A", "B"),
                *_game("6", "A", "C"),
                *_game("7", "C", "A"),
            ]
        )
        criteria = ("head_to_head_win_pct", "head_to_head_point_diff")

        restarted = resolve_tied_group(
            ["A", "C", "B"],
            final_state,
            all_games,
            _season_config(*criteria, restart=True),
        )
        not_restarted = resolve_tied_group(
            ["A", "C", "B"],
            final_state,
            all_games,
            _season_config(*criteria, restart=False),
        )

        self.assertEqual(restarted.ordered_team_ids, ("A", "B", "C"))
        self.assertEqual(not_restarted.ordered_team_ids, ("A", "C", "B"))
        self.assertEqual(restarted.fallback_count, 0)


class DeterministicFallbackTest(unittest.TestCase):
    def test_exhausted_official_criteria_sort_normalized_ids_and_count_one_use(self) -> None:
        from standings_playoff_forecast.tiebreaks import resolve_tied_group

        final_state = _final_state((2.0, 20, 20, 0), ("10.0", 20, 20, 0))
        all_games = pd.DataFrame(
            columns=["game_id", "team_id", "opponent_id", "win", "margin"]
        )

        result = resolve_tied_group(
            [2.0, "10.0"],
            final_state,
            all_games,
            _season_config(
                "head_to_head_win_pct",
                "record_vs_final_500_plus",
                "head_to_head_point_diff",
                "overall_point_diff",
            ),
        )

        self.assertEqual(result.ordered_team_ids, ("10", "2"))
        self.assertEqual(result.fallback_count, 1)

    def test_rank_teams_applies_tiebreaks_only_within_equal_final_records(self) -> None:
        from standings_playoff_forecast.tiebreaks import rank_teams

        final_state = _final_state(
            ("D", 15, 25, 1000),
            ("C", 20, 20, 100),
            ("B", 20, 20, 100),
            ("A", 25, 15, -100),
        )
        all_games = pd.DataFrame(
            columns=["game_id", "team_id", "opponent_id", "win", "margin"]
        )

        result = rank_teams(
            final_state,
            all_games,
            _season_config("overall_point_diff"),
        )

        self.assertEqual(result.ordered_team_ids, ("A", "B", "C", "D"))
        self.assertEqual(result.fallback_count, 1)


class TiebreakConfigurationTest(unittest.TestCase):
    def test_unknown_configured_criterion_fails_even_when_no_record_is_tied(self) -> None:
        from standings_playoff_forecast.tiebreaks import rank_teams

        final_state = _final_state(("A", 25, 15, 10))
        all_games = pd.DataFrame(
            columns=["game_id", "team_id", "opponent_id", "win", "margin"]
        )

        with self.assertRaisesRegex(
            ValueError, "unknown configured tiebreak criteria: coin_flip"
        ):
            rank_teams(
                final_state,
                all_games,
                _season_config("coin_flip"),
            )

    def test_duplicate_directional_game_rows_are_rejected_before_scoring(self) -> None:
        from standings_playoff_forecast.tiebreaks import resolve_tied_group

        final_state = _final_state(("A", 10, 10, 0), ("B", 10, 10, 0))
        rows = _game("1", "B", "A")
        all_games = pd.DataFrame([*rows, dict(rows[1])])

        with self.assertRaisesRegex(
            ValueError, "duplicate directional all-games rows: 1/A"
        ):
            resolve_tied_group(
                ["A", "B"],
                final_state,
                all_games,
                _season_config("head_to_head_win_pct"),
            )

    def test_normalized_final_team_ids_must_remain_unique(self) -> None:
        from standings_playoff_forecast.tiebreaks import rank_teams

        final_state = _final_state((2, 20, 20, 0), ("2.0", 20, 20, 0))
        all_games = pd.DataFrame(
            columns=["game_id", "team_id", "opponent_id", "win", "margin"]
        )

        with self.assertRaisesRegex(
            ValueError, "final_team_state contains duplicate normalized team_id: 2"
        ):
            rank_teams(
                final_state,
                all_games,
                _season_config("overall_point_diff"),
            )


if __name__ == "__main__":
    unittest.main()
