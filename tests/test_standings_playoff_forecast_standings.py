import sys
import unittest
from dataclasses import FrozenInstanceError, replace
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


def _eleven_game_series() -> pd.DataFrame:
    """A's ordered results are L-W-W-W-W-W-W-L-L-L-L."""

    rows = []
    alpha_results = [0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0]
    for game_number, alpha_win in enumerate(alpha_results, start=1):
        game_id = f"{game_number:02d}"
        alpha_home = game_number % 2 == 1
        alpha_points = 80 if alpha_win else 70
        bravo_points = 70 if alpha_win else 80
        rows.extend(
            [
                {"game_id": game_id, "game_date": "2026-06-10", "team_id": "A", "team_abbreviation": "AAA", "team_name": "Alpha", "franchise_id": "alpha", "opponent_id": "B", "opponent_franchise_id": "bravo", "home_away": "home" if alpha_home else "away", "win": alpha_win, "loss": 1 - alpha_win, "points_for": alpha_points, "points_against": bravo_points, "margin": alpha_points - bravo_points},
                {"game_id": game_id, "game_date": "2026-06-10", "team_id": "B", "team_abbreviation": "BBB", "team_name": "Bravo", "franchise_id": "bravo", "opponent_id": "A", "opponent_franchise_id": "alpha", "home_away": "away" if alpha_home else "home", "win": 1 - alpha_win, "loss": alpha_win, "points_for": bravo_points, "points_against": alpha_points, "margin": bravo_points - alpha_points},
            ]
        )
    return pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)


def _fifteen_team_cycle() -> pd.DataFrame:
    """One reciprocal cycle gives every configured team two completed games."""

    rows = []
    team_ids = [f"T{rank:02d}" for rank in range(1, 16)]
    for game_number, home_id in enumerate(team_ids, start=1):
        away_id = team_ids[game_number % len(team_ids)]
        home_rank = int(home_id[1:])
        away_rank = int(away_id[1:])
        home_win = int(home_rank < away_rank)
        home_points = 80 if home_win else 70
        away_points = 70 if home_win else 80
        for team_id, opponent_id, home_away, win, points_for, points_against in (
            (home_id, away_id, "home", home_win, home_points, away_points),
            (away_id, home_id, "away", 1 - home_win, away_points, home_points),
        ):
            rows.append(
                {
                    "game_id": f"cycle-{game_number:02d}",
                    "game_date": f"2026-06-{game_number:02d}",
                    "team_id": team_id,
                    "team_abbreviation": team_id,
                    "team_name": f"Team {team_id}",
                    "franchise_id": team_id.lower(),
                    "opponent_id": opponent_id,
                    "opponent_franchise_id": opponent_id.lower(),
                    "home_away": home_away,
                    "win": win,
                    "loss": 1 - win,
                    "points_for": points_for,
                    "points_against": points_against,
                    "margin": points_for - points_against,
                }
            )
    return pd.DataFrame(rows)


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

    def test_current_context_derives_records_games_back_streak_and_current_500_opponents(self) -> None:
        from standings_playoff_forecast import standings as standings_module
        from standings_playoff_forecast.config import load_season_config

        add_context = getattr(standings_module, "add_current_standings_context", None)
        self.assertIsNotNone(add_context)

        cfg = replace(load_season_config(2026), team_count=3, playoff_qualifiers=2)
        team_games = _team_games()
        home_teams = {"1": "A", "2": "B", "3": "C", "4": "A"}
        team_games["home_away"] = team_games.apply(
            lambda row: "home" if row["team_id"] == home_teams[row["game_id"]] else "away",
            axis=1,
        )
        standings = standings_module.build_current_standings(team_games, cfg)
        standings["current_rank"] = standings["team_id"].map({"B": 1, "C": 2, "A": 3})
        actual = add_context(standings, team_games, cfg).set_index("team_id")

        self.assertEqual(actual.loc["B", "games_back"], 0.0)
        self.assertEqual(actual.loc["A", "games_back"], 1.0)
        self.assertEqual(
            actual.loc[
                "A",
                [
                    "home_wins",
                    "home_losses",
                    "home_record",
                    "road_wins",
                    "road_losses",
                    "road_record",
                ],
            ].to_dict(),
            {
                "home_wins": 1,
                "home_losses": 1,
                "home_record": "1-1",
                "road_wins": 0,
                "road_losses": 1,
                "road_record": "0-1",
            },
        )
        self.assertEqual(
            actual.loc[
                "A",
                [
                    "last10_wins",
                    "last10_losses",
                    "last10_record",
                    "current_streak_type",
                    "current_streak_length",
                    "current_streak_label",
                ],
            ].to_dict(),
            {
                "last10_wins": 1,
                "last10_losses": 2,
                "last10_record": "1-2",
                "current_streak_type": "L",
                "current_streak_length": 2,
                "current_streak_label": "L2",
            },
        )
        self.assertEqual(
            actual.loc[
                "B",
                [
                    "record_vs_current_500_plus_wins",
                    "record_vs_current_500_plus_losses",
                    "record_vs_current_500_plus",
                    "record_vs_current_500_plus_pct",
                ],
            ].to_dict(),
            {
                "record_vs_current_500_plus_wins": 1,
                "record_vs_current_500_plus_losses": 0,
                "record_vs_current_500_plus": "1-0",
                "record_vs_current_500_plus_pct": 1.0,
            },
        )
        self.assertTrue(pd.isna(actual.loc["A", "conference_wins"]))
        self.assertTrue(pd.isna(actual.loc["A", "conference_losses"]))
        self.assertTrue(pd.isna(actual.loc["A", "conference_record"]))
        self.assertEqual(actual.loc["A", "playoff_cutline_flag"], "cutline_chase")

    def test_current_context_assigns_all_2026_cutline_bands_independent_of_input_index(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import (
            add_current_standings_context,
            build_current_standings,
        )

        cfg = load_season_config(2026)
        team_games = _fifteen_team_cycle()
        standings = build_current_standings(team_games, cfg)
        standings["current_rank"] = standings["team_id"].str[1:].astype(int)
        standings.loc[standings["team_id"].eq("T02"), ["games_played", "losses", "win_pct"]] = [
            1,
            0,
            1.0,
        ]
        standings.index = list(reversed(range(15)))

        actual = add_current_standings_context(standings, team_games, cfg).set_index(
            "team_id"
        )

        self.assertEqual(
            actual["playoff_cutline_flag"].to_dict(),
            {**{f"T{rank:02d}": "top4" for rank in range(1, 5)},
             **{f"T{rank:02d}": "playoff_field" for rank in range(5, 9)},
             **{f"T{rank:02d}": "cutline_chase" for rank in range(9, 11)},
             **{f"T{rank:02d}": "outside" for rank in range(11, 16)}},
        )
        self.assertEqual(actual.loc["T04", "playoff_cutline_flag"], "top4")
        self.assertEqual(actual.loc["T10", "playoff_cutline_flag"], "cutline_chase")
        self.assertEqual(actual.loc["T02", "games_back"], 0.5)
        self.assertTrue(pd.api.types.is_float_dtype(actual["games_back"].dtype))
        self.assertTrue(pd.api.types.is_integer_dtype(actual["home_wins"].dtype))
        self.assertTrue(pd.api.types.is_integer_dtype(actual["current_rank"].dtype))
        self.assertTrue(pd.api.types.is_string_dtype(actual["conference_record"].dtype))

    def test_current_context_requires_exact_configured_rank_permutation(self) -> None:
        """Catches zero, negative, gaps, and out-of-range ranks."""
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import (
            add_current_standings_context,
            build_current_standings,
        )

        cfg = replace(load_season_config(2026), team_count=3, playoff_qualifiers=2)
        team_games = _team_games()
        home_teams = {"1": "A", "2": "B", "3": "C", "4": "A"}
        team_games["home_away"] = team_games.apply(
            lambda row: "home" if row["team_id"] == home_teams[row["game_id"]] else "away",
            axis=1,
        )
        for ranks in ([1, 2, 0], [1, 2, -1], [1, 2, 4], [1, 3, 4]):
            with self.subTest(ranks=ranks):
                standings = build_current_standings(team_games, cfg)
                standings["current_rank"] = ranks
                with self.assertRaisesRegex(
                    ValueError, "complete permutation from 1 through 3"
                ):
                    add_current_standings_context(standings, team_games, cfg)

        partial = build_current_standings(team_games, cfg).iloc[:2].copy()
        partial["current_rank"] = [1, 2]
        with self.assertRaisesRegex(
            ValueError, "complete permutation from 1 through 3"
        ):
            add_current_standings_context(partial, team_games, cfg)

    def test_current_context_uses_stable_game_order_for_last10_and_nullable_zero_game_pct(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import (
            STANDINGS_COLUMNS,
            add_current_standings_context,
            build_current_standings,
        )

        cfg = replace(load_season_config(2026), team_count=2, playoff_qualifiers=1)
        team_games = _eleven_game_series()
        standings = build_current_standings(team_games, cfg)
        standings["current_rank"] = standings["team_id"].map({"A": 1, "B": 2})

        context = add_current_standings_context(standings, team_games, cfg)
        actual = context.set_index("team_id")

        self.assertEqual(list(context.columns), STANDINGS_COLUMNS)
        self.assertEqual(
            actual.loc[
                "A",
                [
                    "last10_wins",
                    "last10_losses",
                    "last10_record",
                    "current_streak_type",
                    "current_streak_length",
                    "current_streak_label",
                ],
            ].to_dict(),
            {
                "last10_wins": 6,
                "last10_losses": 4,
                "last10_record": "6-4",
                "current_streak_type": "L",
                "current_streak_length": 4,
                "current_streak_label": "L4",
            },
        )
        self.assertEqual(actual.loc["A", "record_vs_current_500_plus"], "0-0")
        self.assertEqual(actual.loc["A", "record_vs_current_500_plus_wins"], 0)
        self.assertEqual(actual.loc["A", "record_vs_current_500_plus_losses"], 0)
        self.assertTrue(pd.isna(actual.loc["A", "record_vs_current_500_plus_pct"]))

    def test_current_context_requires_rank_before_cutline_assignment(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import (
            add_current_standings_context,
            build_current_standings,
        )

        cfg = load_season_config(2026)
        team_games = _eleven_game_series()
        unranked = build_current_standings(team_games, cfg).drop(columns="current_rank")

        with self.assertRaisesRegex(
            ValueError, "standings is missing required columns: current_rank"
        ):
            add_current_standings_context(unranked, team_games, cfg)

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

    def test_current_standings_rejects_metadata_drift_instead_of_splitting_a_team_record(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import build_current_standings

        team_games = _team_games()
        team_games.loc[(team_games["game_id"] == "4") & (team_games["team_id"] == "A"), "team_name"] = "Alpha Renamed"

        with self.assertRaisesRegex(ValueError, "conflicting presentation metadata for team_id=A"):
            build_current_standings(team_games, load_season_config(2026))

    def test_head_to_head_rejects_metadata_drift_instead_of_splitting_a_pair_record(self) -> None:
        from standings_playoff_forecast.standings import build_head_to_head

        team_games = _team_games()
        team_games.loc[(team_games["game_id"] == "4") & (team_games["team_id"] == "A"), "opponent_franchise_id"] = "bravo_renamed"

        with self.assertRaisesRegex(ValueError, "conflicting presentation metadata for team_id=A, opponent_id=B"):
            build_head_to_head(team_games)


class ExternalStandingsQATest(unittest.TestCase):
    def _derived_standings(self) -> pd.DataFrame:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.standings import build_current_standings

        return build_current_standings(_team_games(), load_season_config(2026))

    def test_missing_external_snapshot_is_unavailable_and_result_is_frozen(self) -> None:
        from standings_playoff_forecast.standings import compare_external_standings

        result = compare_external_standings(self._derived_standings(), None)

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.compared_team_count, 0)
        self.assertEqual(result.mismatch_team_ids, ())
        self.assertIn("unavailable", result.message.lower())
        with self.assertRaises(FrozenInstanceError):
            result.status = "matched"

    def test_exact_long_form_records_are_matched(self) -> None:
        from standings_playoff_forecast.standings import compare_external_standings

        result = compare_external_standings(
            self._derived_standings(),
            _long_form_standings(alpha_wins=1, alpha_losses=2),
        )

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.compared_team_count, 3)
        self.assertEqual(result.mismatch_team_ids, ())

    def test_stale_long_form_records_are_nonblocking_mismatch(self) -> None:
        from standings_playoff_forecast.standings import compare_external_standings

        result = compare_external_standings(
            self._derived_standings(),
            _long_form_standings(alpha_wins=2, alpha_losses=1),
        )

        self.assertEqual(result.status, "mismatch")
        self.assertEqual(result.compared_team_count, 3)
        self.assertEqual(result.mismatch_team_ids, ("A",))
        self.assertIn("team_id=A", result.message)

    def test_wide_or_malformed_schema_is_unparseable_and_nonblocking(self) -> None:
        from standings_playoff_forecast.standings import compare_external_standings

        wide_external = pd.DataFrame(
            {
                "team_id": ["A", "B", "C"],
                "wins": [1, 1, 1],
                "losses": [2, 1, 1],
            }
        )
        result = compare_external_standings(self._derived_standings(), wide_external)

        self.assertEqual(result.status, "unparseable")
        self.assertEqual(result.compared_team_count, 0)
        self.assertEqual(result.mismatch_team_ids, ())
        self.assertIn("missing required columns", result.message)

    def test_missing_external_team_is_nonblocking_mismatch(self) -> None:
        from standings_playoff_forecast.standings import compare_external_standings

        external = _long_form_standings(
            alpha_wins=1,
            alpha_losses=2,
        ).loc[lambda rows: rows["team_id"].ne("C")]
        result = compare_external_standings(self._derived_standings(), external)

        self.assertEqual(result.status, "mismatch")
        self.assertEqual(result.compared_team_count, 2)
        self.assertEqual(result.mismatch_team_ids, ("C",))

    def test_derived_invariant_failure_still_raises_without_external_snapshot(self) -> None:
        from standings_playoff_forecast.standings import compare_external_standings

        invalid = self._derived_standings()
        invalid.loc[invalid["team_id"].eq("A"), "games_played"] = 999

        with self.assertRaisesRegex(
            ValueError,
            "derived standings violates games_played equals wins plus losses",
        ):
            compare_external_standings(invalid, None)


if __name__ == "__main__":
    unittest.main()
