import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _season_config(season: int) -> SimpleNamespace:
    return SimpleNamespace(
        season=season,
        team_count=3,
        regular_season_games_per_team=2,
        playoff_qualifiers=2,
        tiebreaks=("head_to_head_win_pct", "overall_point_diff"),
        multi_team_restart_after_elimination=True,
    )


def _history_rows(season: int) -> list[dict]:
    return _complete_directional_rows(
        season,
        [("AB", "A", "B", 110, 100), ("BC", "B", "C", 107, 100), ("AC", "A", "C", 120, 100)],
    )


def _complete_directional_rows(
    season: int,
    games: list[tuple[str, str, str, int, int]],
    *,
    games_per_team: int = 2,
) -> list[dict]:
    """Build real reciprocal rows with hand-derived cumulative fields."""
    teams = sorted({team for _, home, away, _, _ in games for team in (home, away)})
    state = {team: {"games": 0, "wins": 0, "losses": 0, "point_diff": 0} for team in teams}
    rows = []
    for game_id, home, away, home_points, away_points in games:
        for team, opponent, points_for, points_against in (
            (home, away, home_points, away_points),
            (away, home, away_points, home_points),
        ):
            margin = points_for - points_against
            team_state = state[team]
            team_state["games"] += 1
            team_state["wins"] += int(margin > 0)
            team_state["losses"] += int(margin < 0)
            team_state["point_diff"] += margin
            rows.append(
                {
                    "season": season,
                    "game_id": f"{season}-{game_id}",
                    "team_id": team,
                    "opponent_id": opponent,
                    "season_game_number": team_state["games"],
                    "season_progress_pct": team_state["games"] / games_per_team,
                    "win": int(margin > 0),
                    "loss": int(margin < 0),
                    "wins_to_date": team_state["wins"],
                    "losses_to_date": team_state["losses"],
                    "win_pct_to_date": team_state["wins"] / team_state["games"],
                    "point_diff_to_date": team_state["point_diff"],
                    "margin": margin,
                    "points_for": points_for,
                    "points_against": points_against,
                    "possessions_est": 100,
                    "net_rating_est": 999.0 if team_state["games"] == 2 else margin,
                }
            )
    return rows


def _write_partition(root: Path, season: int) -> None:
    output = root / f"season={season}"
    output.mkdir(parents=True)
    pd.DataFrame(_history_rows(season)).to_parquet(output / "team_game.parquet", index=False)


class HistoricalContextTest(unittest.TestCase):
    def test_discovery_returns_only_prior_numeric_partitions_in_year_order(self) -> None:
        from standings_playoff_forecast.historical_context import discover_history

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("season=2025", "season=2023", "season=2026", "season=2030", "season=oops"):
                (root / name).mkdir()
            (root / "not-a-season").mkdir()

            discovered = discover_history(root, 2026)

        self.assertEqual([path.name for path in discovered], ["season=2023", "season=2025"])

    def test_missing_history_returns_empty_frame_with_stable_contract(self) -> None:
        from standings_playoff_forecast.historical_context import (
            HISTORICAL_CONTEXT_COLUMNS,
            build_historical_context,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            context = build_historical_context(
                Path(temp_dir), 2026, target_progress_pct=0.5
            )

        self.assertTrue(context.empty)
        self.assertEqual(context.columns.tolist(), HISTORICAL_CONTEXT_COLUMNS)

    def test_builds_generalized_cutline_seed_band_and_progress_benchmarks(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2024)
            _write_partition(root, 2025)
            context = build_historical_context(
                root,
                2026,
                target_progress_pct=0.5,
                season_config_loader=_season_config,
            )

        aggregate = context.loc[context["context_level"].eq("aggregate")]
        self.assertEqual(
            aggregate.loc[aggregate["metric"].eq("final_qualifier_wins"), "value"].iloc[0],
            1.0,
        )
        self.assertEqual(
            aggregate.loc[aggregate["metric"].eq("final_first_out_wins"), "value"].iloc[0],
            0.0,
        )
        self.assertEqual(
            aggregate.loc[aggregate["metric"].eq("final_cutline_gap_wins"), "value"].iloc[0],
            1.0,
        )
        self.assertEqual(
            aggregate.loc[aggregate["metric"].eq("same_progress_playoff_rate"), "value"].iloc[0],
            2 / 3,
        )
        self.assertEqual(
            aggregate.loc[aggregate["metric"].eq("same_progress_average_final_rank"), "value"].iloc[0],
            2.0,
        )
        seed_bands = set(
            context.loc[context["metric"].eq("final_seed_band_net_rating"), "seed_band"]
        )
        self.assertEqual(seed_bands, {"top_seed", "playoff_field", "outside_playoff"})
        top_seed_rating = context.loc[
            context["metric"].eq("final_seed_band_net_rating")
            & context["seed_band"].eq("top_seed"),
            "value",
        ].iloc[0]
        self.assertEqual(top_seed_rating, 15.0)

    def test_progress_rows_are_as_of_only_before_final_outcomes_are_joined(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            context = build_historical_context(
                root,
                2026,
                target_progress_pct=0.75,
                season_config_loader=_season_config,
            )

        as_of_rows = context.loc[context["metric"].eq("same_progress_team_outcome")]
        self.assertEqual(as_of_rows["as_of_progress_pct"].tolist(), [0.5, 0.5, 0.5])
        self.assertEqual(as_of_rows["as_of_net_rating"].tolist(), [10.0, -10.0, -7.0])
        self.assertEqual(as_of_rows["final_rank"].tolist(), [1.0, 2.0, 3.0])

    def test_unknown_historical_rules_are_reported_unavailable_not_guessed(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)

            def unavailable(_season: int):
                raise FileNotFoundError("no verified rules")

            context = build_historical_context(
                root, 2026, target_progress_pct=0.5, season_config_loader=unavailable
            )

        self.assertEqual(context["availability_status"].tolist(), ["season_config_unavailable"])
        self.assertEqual(context["season"].tolist(), [2025])

    def test_duplicate_team_game_rows_fail_closed(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            path = root / "season=2025" / "team_game.parquet"
            rows = pd.read_parquet(path)
            pd.concat([rows, rows.iloc[[0]]], ignore_index=True).to_parquet(path, index=False)

            with self.assertRaisesRegex(ValueError, "duplicate season-team-game"):
                build_historical_context(
                    root, 2026, target_progress_pct=0.5, season_config_loader=_season_config
                )

    def test_nonfinite_progress_fails_closed(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            path = root / "season=2025" / "team_game.parquet"
            rows = pd.read_parquet(path)
            rows.loc[0, "season_progress_pct"] = float("inf")
            rows.to_parquet(path, index=False)

            with self.assertRaisesRegex(ValueError, "non-finite season_progress_pct"):
                build_historical_context(
                    root, 2026, target_progress_pct=0.5, season_config_loader=_season_config
                )

    def test_tied_cutline_uses_configured_head_to_head_rank_for_seed_bands(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        games = [
            ("CA", "C", "A", 80, 79), ("CB", "C", "B", 80, 79),
            ("CD", "C", "D", 80, 79), ("CE", "C", "E", 80, 79),
            ("AD", "A", "D", 130, 70), ("DB", "D", "B", 81, 80),
            ("ED", "E", "D", 81, 80), ("BA", "B", "A", 81, 80),
            ("AE", "A", "E", 81, 80), ("BE", "B", "E", 81, 80),
        ]
        config = SimpleNamespace(
            season=2025, team_count=5, regular_season_games_per_team=4,
            playoff_qualifiers=2,
            tiebreaks=("head_to_head_win_pct", "overall_point_diff"),
            multi_team_restart_after_elimination=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "season=2025"
            output.mkdir()
            pd.DataFrame(_complete_directional_rows(2025, games, games_per_team=4)).to_parquet(
                output / "team_game.parquet", index=False
            )
            context = build_historical_context(
                root, 2026, target_progress_pct=1.0, season_config_loader=lambda _: config
            )

        final_bands = context.loc[context["metric"].eq("final_seed_band_net_rating")]
        self.assertEqual(final_bands.loc[final_bands["team_id"].eq("B"), "seed_band"].iloc[0], "playoff_field")
        self.assertEqual(final_bands.loc[final_bands["team_id"].eq("A"), "seed_band"].iloc[0], "outside_playoff")

    def test_exhausted_tiebreak_fallback_is_labeled_and_counted(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        config = SimpleNamespace(
            season=2025, team_count=2, regular_season_games_per_team=2,
            playoff_qualifiers=1, tiebreaks=("head_to_head_win_pct", "overall_point_diff"),
            multi_team_restart_after_elimination=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "season=2025"
            output.mkdir()
            pd.DataFrame(_complete_directional_rows(2025, [
                ("AB1", "A", "B", 80, 70), ("BA2", "B", "A", 80, 70),
            ])).to_parquet(output / "team_game.parquet", index=False)
            context = build_historical_context(
                root, 2026, target_progress_pct=1.0, season_config_loader=lambda _: config
            )

        fallback = context.loc[context["metric"].eq("final_tiebreak_fallback_count")]
        self.assertEqual(fallback["value"].tolist(), [1.0, 1.0])

    def test_as_of_net_rating_accumulates_all_games_before_target_progress(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            context = build_historical_context(
                root, 2026, target_progress_pct=1.0, season_config_loader=_season_config
            )

        as_of_rows = context.loc[context["metric"].eq("same_progress_team_outcome")]
        self.assertEqual(as_of_rows["as_of_net_rating"].tolist(), [15.0, -1.5, -13.5])

    def test_game_number_gap_is_reported_as_incomplete_outcome(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            path = root / "season=2025" / "team_game.parquet"
            rows = pd.read_parquet(path)
            rows.loc[(rows["team_id"].eq("B")) & (rows["season_game_number"].eq(1)), "season_game_number"] = 2
            rows.to_parquet(path, index=False)
            context = build_historical_context(
                root, 2026, target_progress_pct=1.0, season_config_loader=_season_config
            )

        self.assertEqual(context["availability_status"].tolist(), ["incomplete_season_outcomes"])

    def test_non_binary_win_loss_row_fails_closed(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            path = root / "season=2025" / "team_game.parquet"
            rows = pd.read_parquet(path)
            rows.loc[0, "loss"] = 1
            rows.to_parquet(path, index=False)
            with self.assertRaisesRegex(ValueError, "win/loss invariant"):
                build_historical_context(
                    root, 2026, target_progress_pct=1.0, season_config_loader=_season_config
                )

    def test_wrong_season_config_is_reported_unavailable(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            wrong_config = _season_config(2024)
            context = build_historical_context(
                root, 2026, target_progress_pct=1.0, season_config_loader=lambda _: wrong_config
            )

        self.assertEqual(context["availability_status"].tolist(), ["season_config_unavailable"])

    def test_extra_directional_game_reusing_number_is_reported_incomplete(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            path = root / "season=2025" / "team_game.parquet"
            rows = pd.read_parquet(path)
            extra = pd.DataFrame(
                [
                    {
                        **rows.loc[rows["team_id"].eq("B")].iloc[0].to_dict(),
                        "game_id": "2025-extra-BC", "team_id": "B", "opponent_id": "C",
                        "season_game_number": 1, "win": 1, "loss": 0, "margin": 5,
                    },
                    {
                        **rows.loc[rows["team_id"].eq("C")].iloc[0].to_dict(),
                        "game_id": "2025-extra-BC", "team_id": "C", "opponent_id": "B",
                        "season_game_number": 1, "win": 0, "loss": 1, "margin": -5,
                    },
                ]
            )
            pd.concat([rows, extra], ignore_index=True).to_parquet(path, index=False)
            context = build_historical_context(
                root, 2026, target_progress_pct=1.0, season_config_loader=_season_config
            )

        self.assertEqual(context["availability_status"].tolist(), ["incomplete_season_outcomes"])

    def test_reciprocal_rows_cannot_both_be_winners(self) -> None:
        from standings_playoff_forecast.historical_context import build_historical_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_partition(root, 2025)
            path = root / "season=2025" / "team_game.parquet"
            rows = pd.read_parquet(path)
            rows.loc[rows["game_id"].eq("2025-AB") & rows["team_id"].eq("B"), ["win", "loss"]] = (1, 0)
            rows.to_parquet(path, index=False)
            with self.assertRaisesRegex(ValueError, "reciprocal game accounting"):
                build_historical_context(
                    root, 2026, target_progress_pct=1.0, season_config_loader=_season_config
                )


if __name__ == "__main__":
    unittest.main()
