import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hidden_value.board import build_board, fit_role_model, standardize  # noqa: E402
from hidden_value.features import (  # noqa: E402
    apply_eligibility,
    build_playoff_fit,
    build_regression_upside,
    build_start_rate,
    percentile,
)
from hidden_value.trajectory import (  # noqa: E402
    build_player_trajectories,
    shrink,
    weighted_slope,
)


class TrajectoryMathTest(unittest.TestCase):
    def test_slope_recovers_a_clean_trend(self):
        self.assertAlmostEqual(weighted_slope([1.0, 2.0, 3.0, 4.0], [1, 1, 1, 1]), 1.0)

    def test_flat_series_has_zero_slope(self):
        self.assertAlmostEqual(weighted_slope([5.0, 5.0, 5.0], [1, 1, 1]), 0.0)

    def test_heavier_windows_pull_the_slope(self):
        # A perfectly linear series fits identically under any weights, so the series has
        # to bend for weighting to matter.
        light = weighted_slope([0.0, 0.0, 10.0], [1, 1, 1])
        heavy = weighted_slope([0.0, 0.0, 10.0], [1, 1, 100])
        self.assertNotAlmostEqual(light, heavy)

    def test_too_few_points_gives_no_slope(self):
        self.assertTrue(np.isnan(weighted_slope([1.0], [1])))

    def test_shrinkage_pulls_small_samples_toward_zero(self):
        self.assertLess(abs(shrink(1.0, 2, 6.0)), abs(shrink(1.0, 20, 6.0)))
        self.assertAlmostEqual(shrink(1.0, 6, 6.0), 0.5)

    def test_trajectory_frame_skips_players_below_the_window_floor(self):
        rows = []
        for player, windows in (("a", 6), ("b", 2)):
            for index in range(windows):
                rows.append(
                    {
                        "entity_id": player,
                        "window_index": index,
                        "is_baseline_block": False,
                        "total_poss_for_rates": 100,
                        "points_per_75": 10 + index,
                    }
                )
        out = build_player_trajectories(
            pd.DataFrame(rows), metrics=["points_per_75"], recent_windows=10, min_windows=4, shrinkage_constant=6.0
        )
        self.assertEqual(list(out["player_id"]), ["a"])
        self.assertGreater(out.iloc[0]["points_per_75_slope"], 0)

    def test_baseline_block_is_excluded(self):
        rows = [
            {"entity_id": "a", "window_index": 0, "is_baseline_block": True, "total_poss_for_rates": 900, "points_per_75": 99},
        ] + [
            {"entity_id": "a", "window_index": i, "is_baseline_block": False, "total_poss_for_rates": 100, "points_per_75": 10}
            for i in range(1, 6)
        ]
        out = build_player_trajectories(
            pd.DataFrame(rows), metrics=["points_per_75"], recent_windows=10, min_windows=4, shrinkage_constant=6.0
        )
        self.assertEqual(out.iloc[0]["windows_used"], 5)
        self.assertAlmostEqual(out.iloc[0]["points_per_75_recent"], 10.0)


class StartRateTest(unittest.TestCase):
    def _possessions(self):
        rows = []
        for game in ("g1", "g2"):
            rows.append(
                {
                    "game_id": game,
                    "period": 1,
                    "possession_number": 1,
                    **{f"off_player_{i}": i for i in range(1, 6)},
                    **{f"def_player_{i}": 5 + i for i in range(1, 6)},
                }
            )
            rows.append(
                {
                    "game_id": game,
                    "period": 2,
                    "possession_number": 2,
                    **{f"off_player_{i}": i for i in range(1, 5)},
                    "off_player_5": 11,
                    **{f"def_player_{i}": 5 + i for i in range(1, 6)},
                }
            )
        return pd.DataFrame(rows)

    def test_starters_have_a_full_start_rate(self):
        out = build_start_rate(self._possessions()).set_index("player_id")
        self.assertEqual(out.loc[1, "start_rate"], 1.0)
        self.assertEqual(out.loc[1, "games_started"], 2)

    def test_a_substitute_appears_without_starting(self):
        out = build_start_rate(self._possessions()).set_index("player_id")
        self.assertEqual(out.loc[11, "games_started"], 0)
        self.assertEqual(out.loc[11, "games_appeared"], 2)
        self.assertEqual(out.loc[11, "start_rate"], 0.0)

    def test_empty_input_returns_empty_frame(self):
        self.assertTrue(build_start_rate(pd.DataFrame()).empty)


class RoleModelTest(unittest.TestCase):
    def test_residual_is_orthogonal_to_the_proxies(self):
        rng = np.random.default_rng(4)
        minutes = rng.normal(size=120)
        panel = pd.DataFrame(
            {
                "minutes": minutes,
                "usage": rng.normal(size=120),
                "impact_measure": 2.0 * minutes + rng.normal(scale=0.2, size=120),
            }
        )
        residual, diagnostics = fit_role_model(
            panel, impact_column="impact_measure", proxies=["minutes", "usage"], ridge_alpha=0.001
        )
        self.assertGreater(diagnostics["r_squared"], 0.9)
        # Whatever role explained has been removed.
        self.assertLess(abs(float(np.corrcoef(residual, panel["minutes"])[0, 1])), 0.1)

    def test_missing_proxies_are_reported_not_silently_dropped(self):
        panel = pd.DataFrame({"minutes": [1.0, 2, 3, 4, 5], "impact_measure": [1.0, 2, 3, 4, 5]})
        _, diagnostics = fit_role_model(
            panel, impact_column="impact_measure", proxies=["minutes", "not_a_column"], ridge_alpha=1.0
        )
        self.assertEqual(diagnostics["proxies_used"], ["minutes"])
        self.assertEqual(diagnostics["proxies_dropped"], ["not_a_column"])

    def test_constant_proxy_is_dropped(self):
        panel = pd.DataFrame(
            {"minutes": [1.0, 2, 3, 4, 5], "flat": [7.0] * 5, "impact_measure": [1.0, 2, 3, 4, 5]}
        )
        _, diagnostics = fit_role_model(
            panel, impact_column="impact_measure", proxies=["minutes", "flat"], ridge_alpha=1.0
        )
        self.assertEqual(diagnostics["proxies_dropped"], ["flat"])

    def test_insufficient_data_is_reported(self):
        panel = pd.DataFrame({"minutes": [1.0, 2.0], "impact_measure": [1.0, np.nan]})
        residual, diagnostics = fit_role_model(
            panel, impact_column="impact_measure", proxies=["minutes"], ridge_alpha=1.0
        )
        self.assertEqual(diagnostics["status"], "insufficient_data")
        self.assertTrue(residual.isna().all())

    def test_standardize_skips_unusable_columns(self):
        frame = pd.DataFrame({"good": [1.0, 2, 3, 4], "flat": [1.0] * 4, "sparse": [1.0, np.nan, np.nan, np.nan]})
        design, used = standardize(frame, ["good", "flat", "sparse", "absent"])
        self.assertEqual(used, ["good"])
        self.assertEqual(design.shape, (4, 1))


class RegressionUpsideTest(unittest.TestCase):
    def test_missing_good_looks_reads_as_upside(self):
        panel = pd.DataFrame(
            {
                "shot_making_residual": [-0.08, 0.08],
                "fga": [300, 300],
                "ft_pct": [np.nan, np.nan],
                "fg3_pct": [np.nan, np.nan],
                "fg3_a": [0, 0],
            }
        )
        out = build_regression_upside(panel, min_fga=120, free_throw_prior_weight=0.5)
        self.assertGreater(out.iloc[0]["regression_upside_raw"], out.iloc[1]["regression_upside_raw"])

    def test_low_volume_shooters_are_not_scored_on_shot_making(self):
        panel = pd.DataFrame(
            {"shot_making_residual": [-0.5], "fga": [10], "ft_pct": [np.nan], "fg3_pct": [np.nan], "fg3_a": [0]}
        )
        out = build_regression_upside(panel, min_fga=120, free_throw_prior_weight=0.5)
        self.assertEqual(out.iloc[0]["regression_upside_raw"], 0.0)

    def test_free_throw_touch_flags_three_point_room(self):
        panel = pd.DataFrame(
            {
                "shot_making_residual": [0.0, 0.0],
                "fga": [300, 300],
                "ft_pct": [0.90, 0.60],
                "fg3_pct": [0.28, 0.28],
                "fg3_a": [100, 100],
            }
        )
        out = build_regression_upside(panel, min_fga=120, free_throw_prior_weight=0.5)
        self.assertGreater(out.iloc[0]["three_point_prior_gap"], out.iloc[1]["three_point_prior_gap"])


class PlayoffFitTest(unittest.TestCase):
    def test_self_creators_score_above_assisted_finishers(self):
        panel = pd.DataFrame(
            {
                "assisted2s_pct": [0.20, 0.90],
                "at_rim_pct_assisted": [0.20, 0.90],
                "fta_rate": [0.40, 0.10],
                "corner3_share_of_3pa": [0.40, 0.10],
                "rim_and_three_share": [0.80, 0.40],
                "live_ball_turnover_pct": [0.05, 0.20],
                "on_court_poss_share_recent": [0.70, 0.30],
            }
        )
        fit = build_playoff_fit(panel)
        self.assertGreater(fit.iloc[0], fit.iloc[1])

    def test_empty_panel_returns_empty(self):
        self.assertTrue(build_playoff_fit(pd.DataFrame()).empty)


class BoardTest(unittest.TestCase):
    def _panel(self, n=40):
        rng = np.random.default_rng(9)
        return pd.DataFrame(
            {
                "player_id": range(n),
                "player_name": [f"P{i}" for i in range(n)],
                "team_abbreviation": ["AAA"] * n,
                "role_residual": rng.normal(size=n),
                "trajectory_raw": rng.normal(size=n),
                "regression_upside_score": rng.uniform(0, 100, n),
                "playoff_fit": rng.uniform(0, 100, n),
                "volatility_raw": rng.uniform(0, 10, n),
                "sample_flag": ["Reliable"] * n,
                "on_court_poss_share_slope": rng.normal(size=n),
            }
        )

    def test_track_label_does_not_promise_a_forecast(self):
        # The trend is descriptive here; "Trending Up" would overclaim.
        board = build_board(self._panel(), weights={"role_residual": 0.5, "trajectory": 0.5}, labels={})
        self.assertNotIn("Trending Up", set(board["board_track"]))
        self.assertIn("Recent Form", set(board["board_track"]))

    def test_board_ranks_and_labels(self):
        board = build_board(self._panel(), weights={"role_residual": 1.0}, labels={})
        self.assertEqual(board.iloc[0]["hidden_value_rank"], 1)
        self.assertTrue(board["hidden_value_score"].is_monotonic_decreasing)
        self.assertEqual(set(board["board_track"]) - {"Underrated Now", "Recent Form"}, set())

    def test_every_player_lands_on_exactly_one_track(self):
        board = build_board(self._panel(), weights={"role_residual": 0.5, "trajectory": 0.5}, labels={})
        self.assertEqual(len(board), 40)
        self.assertEqual(board["board_track"].isna().sum(), 0)

    def test_low_sample_players_are_downgraded(self):
        panel = self._panel()
        panel["sample_flag"] = ["Low sample"] * len(panel)
        board = build_board(panel, weights={"role_residual": 1.0}, labels={})
        self.assertNotIn("Strong", set(board["conviction"]))

    def test_volatility_penalty_favours_the_steadier_player(self):
        panel = pd.DataFrame(
            {
                "player_id": [1, 2],
                "player_name": ["steady", "wild"],
                "role_residual": [1.0, 1.0],
                "trajectory_raw": [1.0, 1.0],
                "regression_upside_score": [50.0, 50.0],
                "playoff_fit": [50.0, 50.0],
                "volatility_raw": [1.0, 50.0],
                "sample_flag": ["Reliable", "Reliable"],
            }
        )
        board = build_board(panel, weights={"role_residual": 0.5, "volatility_penalty": 0.5}, labels={})
        self.assertEqual(board.iloc[0]["player_name"], "steady")

    def test_notes_explain_the_ranking(self):
        board = build_board(self._panel(), weights={"role_residual": 1.0}, labels={})
        self.assertTrue(board["watchlist_note"].str.len().gt(0).all())


class EligibilityTest(unittest.TestCase):
    def test_thin_players_are_dropped_and_marginal_ones_flagged(self):
        panel = pd.DataFrame(
            {
                "player_id": [1, 2, 3],
                "total_poss": [1200, 400, 50],
                "games_played": [20, 20, 20],
            }
        )
        out = apply_eligibility(panel, min_total_possessions=300, min_games_played=8, reliable_total_possessions=800)
        self.assertEqual(list(out["player_id"]), [1, 2])
        self.assertEqual(list(out["sample_flag"]), ["Reliable", "Low sample"])

    def test_games_floor_is_applied(self):
        panel = pd.DataFrame({"player_id": [1], "total_poss": [5000], "games_played": [3]})
        out = apply_eligibility(panel, min_total_possessions=300, min_games_played=8, reliable_total_possessions=800)
        self.assertTrue(out.empty)


class PercentileTest(unittest.TestCase):
    def test_direction_is_respected(self):
        series = pd.Series([1.0, 2.0, 3.0])
        self.assertGreater(percentile(series).iloc[2], percentile(series).iloc[0])
        self.assertLess(percentile(series, higher_is_better=False).iloc[2], percentile(series, higher_is_better=False).iloc[0])


class BuilderEndToEndTest(unittest.TestCase):
    def test_cli_writes_board_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pbp = tmpdir / "pbpstats" / "features_latest" / "2026"
            pbp.mkdir(parents=True)
            sports = tmpdir / "sportsdataverse"
            sports.mkdir(parents=True)
            panel_dir = tmpdir / "panel" / "data" / "processed"
            panel_dir.mkdir(parents=True)
            impact_dir = tmpdir / "impact" / "data" / "processed"
            impact_dir.mkdir(parents=True)

            rng = np.random.default_rng(1)
            n = 30
            pd.DataFrame(
                {
                    "entity_id": range(1, n + 1),
                    "name": [f"P{i}" for i in range(1, n + 1)],
                    "team_abbreviation": ["AAA", "BBB"] * (n // 2),
                    "minutes": rng.uniform(200, 900, n),
                    "games_played": rng.integers(10, 30, n),
                    "usage": rng.uniform(10, 30, n),
                    "total_poss": rng.uniform(500, 3000, n),
                    "on_off_rtg": rng.uniform(95, 120, n),
                    "on_def_rtg": rng.uniform(95, 120, n),
                    "efg_pct_feature": rng.uniform(0.4, 0.6, n),
                    "ts_pct_feature": rng.uniform(0.45, 0.65, n),
                    "shotquality_pbp_feature": rng.uniform(0.45, 0.55, n),
                    "shot_making_over_shotquality_pbp": rng.uniform(-0.1, 0.1, n),
                    "fg2_a": rng.uniform(100, 300, n),
                    "fg3_a": rng.uniform(50, 200, n),
                    "fg3_pct": rng.uniform(0.25, 0.42, n),
                    "ft_points": rng.uniform(30, 150, n),
                    "fta": rng.uniform(40, 180, n),
                    "fta_rate_feature": rng.uniform(0.1, 0.4, n),
                    "at_rim_pct_assisted": rng.uniform(0.2, 0.9, n),
                    "assisted2s_pct": rng.uniform(0.2, 0.9, n),
                    "corner3_fga": rng.uniform(5, 60, n),
                    "live_ball_turnover_pct": rng.uniform(0.02, 0.2, n),
                    "rim_and_three_fga_share": rng.uniform(0.4, 0.9, n),
                }
            ).to_csv(pbp / "player_totals_features_latest.csv", index=False)
            pd.DataFrame(
                {
                    "team_abbreviation": ["AAA", "BBB"],
                    "points": [2000, 1900],
                    "off_poss": [1900, 1900],
                    "opponent_points": [1900, 2000],
                    "def_poss": [1900, 1900],
                }
            ).to_csv(pbp / "team_totals_features_latest.csv", index=False)

            rows = []
            for player in range(1, n + 1):
                for window in range(8):
                    rows.append(
                        {
                            "entity_id": player,
                            "window_index": window,
                            "is_baseline_block": False,
                            "total_poss_for_rates": 120,
                            "points_per_75": 10 + window * 0.1 * (player % 3),
                            "ts_pct": 0.5,
                            "usage": 20,
                            "on_court_poss_share": 0.5,
                            "on_court_net_rating": rng.normal(0, 5),
                        }
                    )
            pd.DataFrame(rows).to_csv(panel_dir / "player_window_panel_2026.csv", index=False)
            pd.DataFrame(
                {
                    "player_id": range(1, n + 1),
                    "o_rapm": rng.normal(0, 1, n),
                    "d_rapm": rng.normal(0, 1, n),
                    "rapm": rng.normal(0, 1, n),
                    "total_poss": rng.uniform(500, 3000, n),
                }
            ).to_csv(impact_dir / "rapm_player_2026.csv", index=False)

            poss_rows = []
            for game in range(4):
                for number in range(4):
                    poss_rows.append(
                        {
                            "game_id": f"g{game}",
                            "period": 1 if number == 0 else 2,
                            "possession_number": number + 1,
                            **{f"off_player_{i}": i for i in range(1, 6)},
                            **{f"def_player_{i}": 5 + i for i in range(1, 6)},
                        }
                    )
            pd.DataFrame(poss_rows).to_parquet(sports / "wnba_possessions_2026.parquet")
            pd.DataFrame(
                {"player_id": range(1, n + 1), "darko_projected_rating": rng.normal(0, 1, n)}
            ).to_parquet(sports / "wnba_player_impact_2026.parquet")

            config = {
                "season": 2026,
                "pbpstats_data_root": str(tmpdir / "pbpstats"),
                "sportsdataverse_data_root": str(sports),
                "window_panel_root": str(tmpdir / "panel"),
                "possession_impact_root": str(tmpdir / "impact"),
                "output_root": str(tmpdir / "analysis"),
                "eligibility": {"min_total_possessions": 300, "min_games_played": 8, "reliable_total_possessions": 800},
                "trajectory": {
                    "recent_windows": 10,
                    "min_windows": 4,
                    "shrinkage_constant": 6.0,
                    "metrics": ["points_per_75", "ts_pct", "usage", "on_court_poss_share", "on_court_net_rating"],
                },
                "role_model": {"proxies": ["minutes", "usage", "start_rate", "team_net_rating"], "ridge_alpha": 1.0},
                "regression_upside": {"min_fga": 120, "free_throw_prior_weight": 0.5},
                "weights": {
                    "role_residual": 0.35,
                    "trajectory": 0.25,
                    "regression_upside": 0.20,
                    "playoff_fit": 0.20,
                    "volatility_penalty": 0.10,
                },
                "labels": {"strong_percentile": 0.85, "moderate_percentile": 0.70},
            }
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_hidden_value.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            processed = tmpdir / "analysis" / "data" / "processed"
            board = pd.read_csv(processed / "hidden_value_board_2026.csv")
            manifest = json.loads((processed / "run_manifest_2026.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["analysis_stats"]["status"], "ok")
            self.assertGreater(len(board), 0)
            for column in ("hidden_value_score", "board_track", "conviction", "watchlist_note", "role_residual_score"):
                self.assertIn(column, board.columns)
            self.assertIn("proxies_dropped", manifest["analysis_stats"]["role_model"])

    def test_missing_features_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = {
                "pbpstats_data_root": str(tmpdir / "absent"),
                "sportsdataverse_data_root": str(tmpdir / "absent"),
                "window_panel_root": str(tmpdir / "absent"),
                "possession_impact_root": str(tmpdir / "absent"),
                "output_root": str(tmpdir / "analysis"),
            }
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_hidden_value.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (tmpdir / "analysis" / "data" / "processed" / "run_manifest_2026.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["analysis_stats"]["status"], "player_features_missing")


if __name__ == "__main__":
    unittest.main()
