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
    )


def _history_rows(season: int) -> list[dict]:
    # The 0.50 rows are deliberately different from the completed-season rows:
    # a progress benchmark must retain these values rather than use future data.
    rows = []
    final_records = {
        "A": [(1, 0, 10, 100), (2, 0, 30, 100)],
        "B": [(1, 0, -3, 100), (2, 0, 4, 100)],
        "C": [(1, 0, 2, 100), (1, 1, -12, 100)],
    }
    for team_id, games in final_records.items():
        previous_point_diff = 0
        for game_number, (wins, losses, point_diff, possessions) in enumerate(
            games, start=1
        ):
            rows.append(
                {
                    "season": season,
                    "game_id": f"{season}-{team_id}-{game_number}",
                    "team_id": team_id,
                    "season_game_number": game_number,
                    "season_progress_pct": game_number / 2,
                    "win": int(game_number == 1 or team_id in {"A", "B"}),
                    "loss": int(not (game_number == 1 or team_id in {"A", "B"})),
                    "wins_to_date": wins,
                    "losses_to_date": losses,
                    "win_pct_to_date": wins / game_number,
                    "point_diff_to_date": point_diff,
                    "margin": point_diff - previous_point_diff,
                    "points_for": 100 + point_diff - previous_point_diff,
                    "points_against": 100,
                    "possessions_est": possessions,
                    "net_rating_est": 999.0 if game_number == 2 else point_diff,
                }
            )
            previous_point_diff = point_diff
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
            2.0,
        )
        self.assertEqual(
            aggregate.loc[aggregate["metric"].eq("final_first_out_wins"), "value"].iloc[0],
            1.0,
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
        self.assertEqual(as_of_rows["as_of_net_rating"].tolist(), [10.0, -3.0, 2.0])
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


if __name__ == "__main__":
    unittest.main()
