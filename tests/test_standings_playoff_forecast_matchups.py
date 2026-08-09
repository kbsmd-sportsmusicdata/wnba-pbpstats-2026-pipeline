import sys
import unittest
from dataclasses import replace
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
