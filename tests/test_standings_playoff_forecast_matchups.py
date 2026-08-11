import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _season_cfg(*, games_per_team: int = 3):
    from standings_playoff_forecast.config import load_season_config

    return replace(
        load_season_config(2026),
        team_count=2,
        regular_season_games_per_team=games_per_team,
    )


def _schedule_row(
    game_id: object,
    game_date: str,
    *,
    completed: bool,
    season: int = 2026,
    season_type: int = 2,
    event_type: str = "STD",
    status_name: str | None = None,
    home_id: object = "A",
    away_id: object = "B",
) -> dict[str, object]:
    return {
        "game_id": game_id,
        "game_date": game_date,
        "season": season,
        "season_type": season_type,
        "type_abbreviation": event_type,
        "status_type_completed": completed,
        "status_type_name": status_name
        or ("STATUS_FINAL" if completed else "STATUS_SCHEDULED"),
        "home_id": home_id,
        "away_id": away_id,
        "home_abbreviation": "ALP",
        "home_display_name": "Alpha",
        "away_abbreviation": "BRV",
        "away_display_name": "Bravo",
    }


def _completed_team_games(home_margins: list[float]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, home_margin in enumerate(home_margins, start=1):
        for team_id, opponent_id, is_home, margin in (
            ("A", "B", True, home_margin),
            ("B", "A", False, -home_margin),
        ):
            rows.append(
                {
                    "game_id": f"played-{index}",
                    "team_id": team_id,
                    "opponent_id": opponent_id,
                    "is_home": is_home,
                    "margin": margin,
                    "pace_est": 100.0,
                    "rest_days": 2,
                    "back_to_back": False,
                }
            )
    return pd.DataFrame(rows)


class RemainingScheduleTest(unittest.TestCase):
    def test_selects_configured_regular_season_and_carries_rest_from_last_completed_game(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row("1", "2026-06-01", completed=True),
                _schedule_row("2", "2026-06-03", completed=False),
                _schedule_row("3", "2026-06-04", completed=False),
                _schedule_row(
                    "all-star",
                    "2026-06-02",
                    completed=False,
                    event_type="ALLSTAR",
                ),
                _schedule_row(
                    "postseason",
                    "2026-06-05",
                    completed=False,
                    season_type=3,
                ),
                _schedule_row(
                    "other-season",
                    "2030-06-05",
                    completed=False,
                    season=2030,
                ),
            ]
        )

        result = build_remaining_schedule(schedule, "2026-06-01", _season_cfg())

        self.assertEqual(result["game_id"].tolist(), ["2", "3"])
        self.assertEqual(result["home_rest_days"].tolist(), [1, 0])
        self.assertEqual(result["away_rest_days"].tolist(), [1, 0])
        self.assertEqual(result["home_b2b"].tolist(), [False, True])
        self.assertEqual(result["away_b2b"].tolist(), [False, True])

    def test_excludes_a_postponed_event_when_its_makeup_game_is_scheduled(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row("1", "2026-06-01", completed=True),
                _schedule_row(
                    "postponed",
                    "2026-06-03",
                    completed=False,
                    status_name="STATUS_POSTPONED",
                ),
                _schedule_row("makeup", "2026-06-05", completed=False),
            ]
        )

        result = build_remaining_schedule(
            schedule, "2026-06-01", _season_cfg(games_per_team=2)
        )

        self.assertEqual(result["game_id"].tolist(), ["makeup"])
        self.assertEqual(result["home_rest_days"].tolist(), [3])

    def test_keeps_a_commissioners_cup_game_that_fills_both_team_schedules(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row("1", "2026-06-01", completed=True),
                _schedule_row(
                    "cup",
                    "2026-06-04",
                    completed=False,
                    event_type="CC",
                ),
            ]
        )

        result = build_remaining_schedule(
            schedule, "2026-06-01", _season_cfg(games_per_team=2)
        )

        self.assertEqual(result["game_id"].tolist(), ["cup"])
        self.assertEqual(result["home_rest_days"].tolist(), [2])

    def test_excludes_a_cup_final_that_would_exceed_configured_team_totals(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row("1", "2026-06-01", completed=True),
                _schedule_row("2", "2026-06-04", completed=False),
                _schedule_row(
                    "extra-cup",
                    "2026-06-05",
                    completed=False,
                    event_type="CC",
                ),
            ]
        )

        result = build_remaining_schedule(
            schedule, "2026-06-01", _season_cfg(games_per_team=2)
        )

        self.assertEqual(result["game_id"].tolist(), ["2"])

    def test_fails_closed_when_completed_and_remaining_games_do_not_reconcile(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row("1", "2026-06-01", completed=True),
                _schedule_row("2", "2026-06-04", completed=False),
            ]
        )

        with self.assertRaisesRegex(ValueError, "schedule reconciliation failed"):
            build_remaining_schedule(schedule, "2026-06-01", _season_cfg())

    def test_normalizes_schedule_game_and_participant_ids(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row(
                    1.0,
                    "2026-06-01",
                    completed=True,
                    home_id=10.0,
                    away_id=20.0,
                ),
                _schedule_row(
                    2.0,
                    "2026-06-04",
                    completed=False,
                    home_id=20.0,
                    away_id=10.0,
                ),
            ]
        )

        result = build_remaining_schedule(
            schedule, "2026-06-01", _season_cfg(games_per_team=2)
        )

        self.assertEqual(result.loc[0, "game_id"], "2")
        self.assertEqual(result.loc[0, "home_id"], "20")
        self.assertEqual(result.loc[0, "away_id"], "10")

    def test_rejects_null_or_identical_home_and_away_participants(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        invalid_schedules = (
            pd.DataFrame(
                [
                    _schedule_row(
                        "1", "2026-06-01", completed=True, away_id=None
                    )
                ]
            ),
            pd.DataFrame(
                [
                    _schedule_row(
                        "1", "2026-06-01", completed=True, away_id="A"
                    )
                ]
            ),
        )
        for schedule in invalid_schedules:
            with self.subTest(schedule=schedule):
                with self.assertRaisesRegex(
                    ValueError, "invalid home/away participants"
                ):
                    build_remaining_schedule(
                        schedule,
                        "2026-06-01",
                        _season_cfg(games_per_team=1),
                    )

    def test_only_completed_games_at_or_before_cutoff_leave_the_remaining_set(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row("1", "2026-05-30", completed=True),
                _schedule_row("unresolved", "2026-05-31", completed=False),
                _schedule_row("later-final", "2026-06-04", completed=True),
            ]
        )

        result = build_remaining_schedule(schedule, "2026-06-01", _season_cfg())

        self.assertEqual(result["game_id"].tolist(), ["unresolved", "later-final"])

    def test_rejects_duplicate_normalized_schedule_game_ids(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row(1, "2026-06-01", completed=True),
                _schedule_row(1.0, "2026-06-04", completed=False),
            ]
        )

        with self.assertRaisesRegex(ValueError, "duplicate game_id"):
            build_remaining_schedule(
                schedule, "2026-06-01", _season_cfg(games_per_team=2)
            )

    def test_rejects_blank_normalized_schedule_participant_ids(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [
                _schedule_row(
                    "1", "2026-06-01", completed=True, away_id="   "
                )
            ]
        )

        with self.assertRaisesRegex(ValueError, "invalid home/away participants"):
            build_remaining_schedule(
                schedule, "2026-06-01", _season_cfg(games_per_team=1)
            )

    def test_rejects_null_normalized_schedule_game_id(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )

        schedule = pd.DataFrame(
            [_schedule_row(None, "2026-06-01", completed=True)]
        )

        with self.assertRaisesRegex(ValueError, "invalid game_id"):
            build_remaining_schedule(
                schedule, "2026-06-01", _season_cfg(games_per_team=1)
            )


class SeasonScheduleCountValidationTest(unittest.TestCase):
    def test_returns_stable_per_team_full_season_reconciliation(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            validate_season_schedule_counts,
        )

        current_standings = pd.DataFrame(
            {
                "team_id": ["B", "A"],
                "games_played": [43, 43],
            }
        )
        remaining_schedule = pd.DataFrame(
            [
                {"game_id": "future-1", "home_id": "A", "away_id": "B"},
            ]
        )

        result = validate_season_schedule_counts(
            current_standings,
            remaining_schedule,
            _season_cfg(games_per_team=44),
        )

        self.assertEqual(
            result.to_dict("records"),
            [
                {
                    "team_id": "A",
                    "completed_gp": 43,
                    "remaining_games": 1,
                    "configured_games": 44,
                    "total_games": 44,
                    "status": "validated",
                },
                {
                    "team_id": "B",
                    "completed_gp": 43,
                    "remaining_games": 1,
                    "configured_games": 44,
                    "total_games": 44,
                    "status": "validated",
                },
            ],
        )

    def test_rejects_missing_or_duplicate_schedule_games(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            validate_season_schedule_counts,
        )

        current_standings = pd.DataFrame(
            {"team_id": ["A", "B"], "games_played": [1, 1]}
        )
        with self.subTest("missing"):
            with self.assertRaisesRegex(ValueError, "season schedule count mismatch"):
                validate_season_schedule_counts(
                    current_standings,
                    pd.DataFrame(
                        [{"game_id": "future-1", "home_id": "A", "away_id": "B"}]
                    ),
                    _season_cfg(games_per_team=3),
                )
        with self.subTest("duplicate"):
            with self.assertRaisesRegex(ValueError, "duplicate game_id"):
                validate_season_schedule_counts(
                    current_standings,
                    pd.DataFrame(
                        [
                            {"game_id": "future-1", "home_id": "A", "away_id": "B"},
                            {"game_id": "future-1", "home_id": "B", "away_id": "A"},
                        ]
                    ),
                    _season_cfg(games_per_team=3),
                )

    def test_rejects_invalid_team_universe_and_completed_game_counts(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            validate_season_schedule_counts,
        )

        valid_remaining = pd.DataFrame(
            [{"game_id": "future-1", "home_id": "A", "away_id": "B"}]
        )
        with self.subTest("missing team"):
            with self.assertRaisesRegex(ValueError, "team universe"):
                validate_season_schedule_counts(
                    pd.DataFrame({"team_id": ["A"], "games_played": [1]}),
                    valid_remaining,
                    _season_cfg(games_per_team=2),
                )
        with self.subTest("unknown remaining team"):
            with self.assertRaisesRegex(ValueError, "unknown team IDs"):
                validate_season_schedule_counts(
                    pd.DataFrame(
                        {"team_id": ["A", "B"], "games_played": [1, 1]}
                    ),
                    pd.DataFrame(
                        [{"game_id": "future-1", "home_id": "A", "away_id": "C"}]
                    ),
                    _season_cfg(games_per_team=2),
                )
        with self.subTest("invalid completed games"):
            with self.assertRaisesRegex(ValueError, "invalid completed games_played"):
                validate_season_schedule_counts(
                    pd.DataFrame(
                        {"team_id": ["A", "B"], "games_played": [1.5, 1]}
                    ),
                    valid_remaining,
                    _season_cfg(games_per_team=2),
                )

    def test_rejects_boolean_games_played_before_numeric_coercion(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            validate_season_schedule_counts,
        )

        remaining = pd.DataFrame(
            [{"game_id": "future-1", "home_id": "A", "away_id": "B"}]
        )
        for value in (True, np.bool_(True)):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(
                    ValueError, "invalid completed games_played"
                ):
                    validate_season_schedule_counts(
                        pd.DataFrame(
                            {"team_id": ["A", "B"], "games_played": [value, 1]}
                        ),
                        remaining,
                        _season_cfg(games_per_team=2),
                    )

    def test_rejects_nonfinite_negative_and_out_of_range_completed_games(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            validate_season_schedule_counts,
        )

        remaining = pd.DataFrame(
            [{"game_id": "future-1", "home_id": "A", "away_id": "B"}]
        )
        for value in (float("nan"), float("inf"), float("-inf"), -1, 3):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError, "invalid completed games_played"
                ):
                    validate_season_schedule_counts(
                        pd.DataFrame(
                            {"team_id": ["A", "B"], "games_played": [value, 1]}
                        ),
                        remaining,
                        _season_cfg(games_per_team=2),
                    )

    def test_rejects_normalized_and_literal_duplicate_standings_team_ids(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            validate_season_schedule_counts,
        )

        remaining = pd.DataFrame(
            [{"game_id": "future-1", "home_id": "A", "away_id": "B"}]
        )
        for team_ids in (("1.0", "1"), ("A", "A")):
            with self.subTest(team_ids=team_ids):
                with self.assertRaisesRegex(ValueError, "invalid team universe"):
                    validate_season_schedule_counts(
                        pd.DataFrame(
                            {"team_id": team_ids, "games_played": [1, 1]}
                        ),
                        remaining,
                        _season_cfg(games_per_team=2),
                    )

    def test_accepts_empty_remaining_schedule_when_each_team_is_complete(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            validate_season_schedule_counts,
        )

        result = validate_season_schedule_counts(
            pd.DataFrame({"team_id": ["B", "A"], "games_played": [2, 2]}),
            pd.DataFrame(columns=["game_id", "home_id", "away_id"]),
            _season_cfg(games_per_team=2),
        )

        self.assertEqual(
            result.to_dict("records"),
            [
                {
                    "team_id": "A",
                    "completed_gp": 2,
                    "remaining_games": 0,
                    "configured_games": 2,
                    "total_games": 2,
                    "status": "validated",
                },
                {
                    "team_id": "B",
                    "completed_gp": 2,
                    "remaining_games": 0,
                    "configured_games": 2,
                    "total_games": 2,
                    "status": "validated",
                },
            ],
        )

    def test_rejects_same_team_remaining_game(self) -> None:
        from standings_playoff_forecast.remaining_schedule import (
            validate_season_schedule_counts,
        )

        with self.assertRaisesRegex(ValueError, "same-team participants"):
            validate_season_schedule_counts(
                pd.DataFrame({"team_id": ["A", "B"], "games_played": [1, 1]}),
                pd.DataFrame(
                    [{"game_id": "future-1", "home_id": "A", "away_id": "A"}]
                ),
                _season_cfg(games_per_team=2),
            )


class MatchupModelTest(unittest.TestCase):
    def test_scores_exact_pace_scaled_strength_and_context_formula(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.matchup_model import score_matchups

        remaining = pd.DataFrame(
            [
                {
                    "game_id": "future",
                    "game_date": "2026-06-10",
                    "home_id": "A",
                    "away_id": "B",
                    "home_rest_days": 3,
                    "away_rest_days": 0,
                    "home_b2b": False,
                    "away_b2b": True,
                }
            ]
        )
        strength = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "predictive_net_rating": [10.0, -5.0],
            }
        )
        team_games = pd.DataFrame(
            [
                {
                    "game_id": "played",
                    "team_id": "A",
                    "opponent_id": "B",
                    "is_home": True,
                    "margin": 5.0,
                    "pace_est": 75.0,
                    "rest_days": pd.NA,
                    "back_to_back": False,
                },
                {
                    "game_id": "played",
                    "team_id": "B",
                    "opponent_id": "A",
                    "is_home": False,
                    "margin": -5.0,
                    "pace_est": 75.0,
                    "rest_days": pd.NA,
                    "back_to_back": False,
                },
            ]
        )

        result = score_matchups(
            remaining, strength, team_games, load_model_config()
        ).iloc[0]

        self.assertAlmostEqual(result["avg_pace"], 75.0)
        self.assertAlmostEqual(result["base_margin"], 11.25)
        self.assertEqual(result["rest_diff"], 2)
        self.assertAlmostEqual(result["expected_home_margin"], 14.2)
        self.assertAlmostEqual(result["margin_sigma"], 13.0)
        self.assertAlmostEqual(result["home_win_probability"], 0.8626510598048461)
        self.assertAlmostEqual(result["away_win_probability"], 0.1373489401951539)
        self.assertAlmostEqual(
            result["home_win_probability"] + result["away_win_probability"],
            1.0,
        )

    def test_estimates_sigma_from_completed_game_residuals_in_the_same_model_frame(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.matchup_model import score_matchups

        remaining = pd.DataFrame(
            [
                {
                    "game_id": "future",
                    "game_date": "2026-06-10",
                    "home_id": "A",
                    "away_id": "B",
                    "home_rest_days": 2,
                    "away_rest_days": 2,
                    "home_b2b": False,
                    "away_b2b": False,
                }
            ]
        )
        strength = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "predictive_net_rating": [5.0, -5.0],
            }
        )

        result = score_matchups(
            remaining,
            strength,
            _completed_team_games([1.5, 21.5]),
            load_model_config(),
        ).iloc[0]

        self.assertAlmostEqual(result["margin_sigma"], 14.142135623730951)

    def test_clamps_residual_sigma_to_configured_bounds(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.matchup_model import score_matchups

        remaining = pd.DataFrame(
            [
                {
                    "game_id": "future",
                    "game_date": "2026-06-10",
                    "home_id": "A",
                    "away_id": "B",
                    "home_rest_days": 2,
                    "away_rest_days": 2,
                    "home_b2b": False,
                    "away_b2b": False,
                }
            ]
        )
        strength = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "predictive_net_rating": [5.0, -5.0],
            }
        )
        for margins, expected_sigma in (
            ([10.5, 12.5], 8.0),
            ([-8.5, 31.5], 18.0),
        ):
            with self.subTest(margins=margins):
                result = score_matchups(
                    remaining,
                    strength,
                    _completed_team_games(margins),
                    load_model_config(),
                ).iloc[0]

                self.assertAlmostEqual(result["margin_sigma"], expected_sigma)

    def test_uses_midpoint_sigma_fallback_for_non_finite_residual_sample(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.matchup_model import score_matchups

        remaining = pd.DataFrame(
            [
                {
                    "game_id": "future",
                    "game_date": "2026-06-10",
                    "home_id": "A",
                    "away_id": "B",
                    "home_rest_days": 2,
                    "away_rest_days": 2,
                    "home_b2b": False,
                    "away_b2b": False,
                }
            ]
        )
        strength = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "predictive_net_rating": [5.0, -5.0],
            }
        )

        result = score_matchups(
            remaining,
            strength,
            _completed_team_games([float("nan"), float("nan")]),
            load_model_config(),
        ).iloc[0]

        self.assertEqual(result["margin_sigma"], 13.0)
        self.assertTrue(0.0 <= result["home_win_probability"] <= 1.0)
        self.assertTrue(0.0 <= result["away_win_probability"] <= 1.0)

    def test_fails_closed_when_a_remaining_team_has_no_strength(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.matchup_model import score_matchups

        remaining = pd.DataFrame(
            [
                {
                    "game_id": "future",
                    "game_date": "2026-06-10",
                    "home_id": "A",
                    "away_id": "B",
                    "home_rest_days": 2,
                    "away_rest_days": 2,
                    "home_b2b": False,
                    "away_b2b": False,
                }
            ]
        )
        strength = pd.DataFrame(
            {"team_id": ["A"], "predictive_net_rating": [5.0]}
        )

        with self.assertRaisesRegex(ValueError, "missing strength or pace"):
            score_matchups(
                remaining,
                strength,
                _completed_team_games([1.5]),
                load_model_config(),
            )

    def test_missing_first_game_rest_is_neutral_and_probabilities_remain_finite(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.matchup_model import score_matchups

        remaining = pd.DataFrame(
            [
                {
                    "game_id": "future",
                    "game_date": "2026-05-01",
                    "home_id": "A",
                    "away_id": "B",
                    "home_rest_days": pd.NA,
                    "away_rest_days": pd.NA,
                    "home_b2b": False,
                    "away_b2b": False,
                }
            ]
        )
        strength = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "predictive_net_rating": [10.0, -5.0],
            }
        )

        result = score_matchups(
            remaining,
            strength,
            _completed_team_games([5.0]),
            load_model_config(),
        ).iloc[0]

        self.assertEqual(result["rest_diff"], 0)
        self.assertAlmostEqual(result["expected_home_margin"], 16.5)
        self.assertTrue(0.0 <= result["home_win_probability"] <= 1.0)
        self.assertTrue(0.0 <= result["away_win_probability"] <= 1.0)

    def test_residual_estimation_rejects_a_missing_reciprocal_away_row(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.matchup_model import score_matchups

        remaining = pd.DataFrame(
            [
                {
                    "game_id": "future",
                    "game_date": "2026-06-10",
                    "home_id": "A",
                    "away_id": "B",
                    "home_rest_days": 2,
                    "away_rest_days": 2,
                    "home_b2b": False,
                    "away_b2b": False,
                }
            ]
        )
        strength = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "predictive_net_rating": [5.0, -5.0],
            }
        )
        games = _completed_team_games([1.5, 21.5])
        games = games.loc[
            ~(
                games["game_id"].eq("played-2")
                & games["is_home"].eq(False)
            )
        ]

        with self.assertRaisesRegex(ValueError, "reciprocal directional rows"):
            score_matchups(remaining, strength, games, load_model_config())

    def test_residual_estimation_rejects_missing_completed_game_context(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.matchup_model import score_matchups

        remaining = pd.DataFrame(
            [
                {
                    "game_id": "future",
                    "game_date": "2026-06-10",
                    "home_id": "A",
                    "away_id": "B",
                    "home_rest_days": 2,
                    "away_rest_days": 2,
                    "home_b2b": False,
                    "away_b2b": False,
                }
            ]
        )
        strength = pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "predictive_net_rating": [5.0, -5.0],
            }
        )
        known = _completed_team_games([1.5])
        missing = _completed_team_games([5.0]).replace(
            {"A": "C", "B": "D", "played-1": "missing-context"}
        )

        with self.assertRaisesRegex(
            ValueError, "completed games have missing strength or pace"
        ):
            score_matchups(
                remaining,
                strength,
                pd.concat([known, missing], ignore_index=True),
                load_model_config(),
            )

    def test_canonical_team_games_exclude_extra_cup_before_pace_and_sigma(self) -> None:
        from standings_playoff_forecast.config import load_model_config
        from standings_playoff_forecast.data_sources import ForecastSources
        from standings_playoff_forecast.matchup_model import score_matchups
        from standings_playoff_forecast.remaining_schedule import (
            build_remaining_schedule,
        )
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        schedule = pd.DataFrame(
            [
                {
                    **_schedule_row("std-1", "2026-06-01", completed=True),
                    "home_score": 91.5,
                    "away_score": 100.0,
                    "format_regulation_periods": 4,
                    "status_period": 4,
                },
                {
                    **_schedule_row("std-2", "2026-06-03", completed=True),
                    "home_score": 111.5,
                    "away_score": 100.0,
                    "format_regulation_periods": 4,
                    "status_period": 4,
                },
                {
                    **_schedule_row("future", "2026-06-05", completed=False),
                    "home_score": pd.NA,
                    "away_score": pd.NA,
                    "format_regulation_periods": 4,
                    "status_period": 0,
                },
                {
                    **_schedule_row(
                        "extra-cup",
                        "2026-06-04",
                        completed=True,
                        event_type="CC",
                    ),
                    "home_score": 200.0,
                    "away_score": 50.0,
                    "format_regulation_periods": 4,
                    "status_period": 4,
                },
            ]
        )
        box_rows: list[dict[str, object]] = []
        for game_id, pace, home_score, away_score in (
            ("std-1", 100.0, 91.5, 100.0),
            ("std-2", 80.0, 111.5, 100.0),
            ("extra-cup", 20.0, 200.0, 50.0),
        ):
            for team_id in ("A", "B"):
                is_home = team_id == "A"
                team_score = home_score if is_home else away_score
                opponent_score = away_score if is_home else home_score
                box_rows.append(
                    {
                        "game_id": game_id,
                        "team_id": team_id,
                        "opponent_team_id": "B" if is_home else "A",
                        "team_home_away": "home" if is_home else "away",
                        "team_score": team_score,
                        "opponent_team_score": opponent_score,
                        "team_winner": team_score > opponent_score,
                        "field_goals_made": pace / 2,
                        "field_goals_attempted": pace,
                        "three_point_field_goals_made": 0,
                        "free_throws_made": 0,
                        "free_throws_attempted": 0,
                        "offensive_rebounds": 0,
                        "defensive_rebounds": pace / 4,
                        "turnovers": 0,
                    }
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            cfg = replace(
                _season_cfg(games_per_team=3),
                normalized_team_game_root=str(temp_root / "processed"),
            )
            sources = ForecastSources(
                schedule=schedule,
                team_box=pd.DataFrame(box_rows),
                team_history=pd.DataFrame(
                    {
                        "season": [2026, 2026],
                        "sportsdataverse_team_id": ["A", "B"],
                        "franchise_id": ["alpha", "bravo"],
                    }
                ),
                pbp_team_features=None,
                external_standings=None,
                schedule_path=temp_root / "schedule.parquet",
                team_box_path=temp_root / "team_box.parquet",
                team_history_path=temp_root / "team_history.csv",
                pbp_team_features_path=None,
                external_standings_path=None,
            )
            team_games = build_team_game_layer(sources, cfg, cutoff="2026-06-04")
            remaining = build_remaining_schedule(schedule, "2026-06-04", cfg)
            scored = score_matchups(
                remaining,
                pd.DataFrame(
                    {
                        "team_id": ["A", "B"],
                        "predictive_net_rating": [0.0, 0.0],
                    }
                ),
                team_games,
                load_model_config(),
            ).iloc[0]

        self.assertEqual(set(team_games["game_id"]), {"std-1", "std-2"})
        self.assertNotIn("extra-cup", set(team_games["game_id"]))
        self.assertAlmostEqual(scored["home_pace"], 90.0)
        self.assertAlmostEqual(scored["away_pace"], 90.0)
        self.assertAlmostEqual(scored["margin_sigma"], 14.142135623730951)


if __name__ == "__main__":
    unittest.main()
