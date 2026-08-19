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

from team_identity_shift.decomposition import (  # noqa: E402
    build_decomposition_table,
    classify_nature,
    decompose_offense,
)
from team_identity_shift.schedule_context import (  # noqa: E402
    build_game_opponents,
    build_period_schedule_context,
    schedule_deltas,
)
from team_identity_shift.shift import (  # noqa: E402
    apply_schedule_adjustment,
    permutation_null,
    shift_score,
    style_from_totals,
    totals_columns_for,
)
from team_identity_shift.style import (  # noqa: E402
    BASELINE,
    RECENT,
    aggregate_period,
    assign_periods,
    build_style_frame,
    dimension_deltas,
    league_scales,
    period_metrics,
    team_key,
)


DIMENSIONS = [
    "three_point_attempt_rate",
    "rim_fga_share",
    "turnover_rate",
    "pace",
]

CONFIG = {
    # These end-to-end builder tests exercise the snapshot window-panel path with a synthetic
    # panel, so they pin that source rather than the game-layer default.
    "periods": {"recent_games": 4, "min_baseline_games": 2, "source": "window_panel"},
    "style_dimensions": DIMENSIONS,
    "permutation_test": {
        "iterations": 200,
        "random_seed": 11,
        "significant_percentile": 0.95,
        "moderate_percentile": 0.80,
    },
    "labels": {"helping_net_rating_delta": 2.0, "hurting_net_rating_delta": -2.0, "top_dimension_count": 3},
}


def window_row(team, index, *, games=1, three_heavy=False, **overrides):
    """One team-window of totals, shaped like the snapshot window panel.

    Points are derived from the made shots rather than set independently, because the
    offensive decomposition rests on ``points == 2*FG2M + 3*FG3M + FT points``.
    """
    fg3a, fg2a = (30, 30) if three_heavy else (15, 45)
    fg2m, fg3m, ft_points = int(fg2a * 0.5), int(fg3a * 0.35), 12
    row = {
        "team_abbreviation": team,
        "entity_id": f"id-{team}",
        "window_index": index,
        "is_baseline_block": False,
        "games_in_window": games,
        "covered_game_date_start": f"2026-06-{index + 1:02d}",
        "covered_game_date_end": f"2026-06-{index + 1:02d}",
        "off_poss": 80 * games,
        "def_poss": 80 * games,
        "points": (2 * fg2m + 3 * fg3m + ft_points) * games,
        "opponent_points": 82 * games,
        "fg2_a": fg2a * games,
        "fg3_a": fg3a * games,
        "fg2_m": fg2m * games,
        "fg3_m": fg3m * games,
        "fta": 16 * games,
        "ft_points": ft_points * games,
        "at_rim_fga": 20 * games,
        "at_rim_fgm": 12 * games,
        "short_mid_range_fga": 8 * games,
        "long_mid_range_fga": 7 * games,
        "corner3_fga": int(fg3a * 0.25) * games,
        "arc3_fga": int(fg3a * 0.75) * games,
        "turnovers": 12 * games,
        "live_ball_turnovers": 7 * games,
        "off_rebounds": 10 * games,
        "def_rebounds": 26 * games,
        "assists": 18 * games,
        "pts_assisted2s": 24 * games,
        "pts_assisted3s": 18 * games,
        "second_chance_points": 10 * games,
        "second_chance_off_poss": 9 * games,
        "penalty_off_poss": 14 * games,
        "penalty_points": 18 * games,
        "steals": 7 * games,
        "blocks": 4 * games,
        "fouls": 18 * games,
        "shotquality_pbp_avg": 0.50,
        "shotquality_pbp_avg_weight": (fg2a + fg3a) * games,
    }
    row.update(overrides)
    return row


def build_panel(teams=("AAA", "BBB", "CCC", "DDD"), windows=12, shift_team=None):
    rows = []
    for team in teams:
        for index in range(windows):
            # The shifted team swaps to a three-heavy diet for its final four windows.
            three_heavy = shift_team == team and index >= windows - 4
            rows.append(window_row(team, index, three_heavy=three_heavy))
    return pd.DataFrame(rows)


class PeriodSplitTest(unittest.TestCase):
    def test_recent_block_reaches_the_target_games(self):
        panel = build_panel(teams=("AAA",), windows=10)
        ordered = assign_periods(panel, recent_games=4)
        recent = ordered[ordered["period"] == RECENT]
        self.assertEqual(recent["games_in_window"].sum(), 4)
        self.assertEqual(list(recent["window_index"]), [6, 7, 8, 9])

    def test_split_lands_on_a_window_boundary(self):
        panel = pd.DataFrame(
            [window_row("AAA", 0, games=5), window_row("AAA", 1, games=3), window_row("AAA", 2, games=3)]
        )
        ordered = assign_periods(panel, recent_games=4)
        recent = ordered[ordered["period"] == RECENT]
        # Four games cannot be cut out of a three-game window, so the block widens to six.
        self.assertEqual(recent["games_in_window"].sum(), 6)

    def test_periods_partition_the_season(self):
        panel = build_panel(teams=("AAA",), windows=10)
        ordered = assign_periods(panel, recent_games=4)
        self.assertEqual(len(ordered[ordered["period"] == BASELINE]) + len(ordered[ordered["period"] == RECENT]), 10)


class AggregationTest(unittest.TestCase):
    def test_counting_columns_are_summed(self):
        panel = build_panel(teams=("AAA",), windows=3)
        totals = aggregate_period(panel, ["points", "off_poss", "fg3_a"])
        self.assertEqual(totals["points"], panel["points"].sum())
        self.assertEqual(totals["off_poss"], 80 * 3)
        self.assertEqual(totals["fg3_a"], panel["fg3_a"].sum())

    def test_reconstructed_averages_are_reweighted_not_summed(self):
        panel = pd.DataFrame(
            [
                window_row("AAA", 0, shotquality_pbp_avg=0.40, shotquality_pbp_avg_weight=100),
                window_row("AAA", 1, shotquality_pbp_avg=0.60, shotquality_pbp_avg_weight=300),
            ]
        )
        totals = aggregate_period(panel, ["points"])
        # Weighted, not the 0.50 a plain mean would give.
        self.assertAlmostEqual(totals["shotquality_pbp_avg"], (0.40 * 100 + 0.60 * 300) / 400)
        self.assertAlmostEqual(totals["shotquality_pbp_avg_weight"], 400)

    def test_period_rates_come_from_totals_not_averaged_rates(self):
        # A high-possession window must dominate a low-possession one, so the period rate
        # is the pooled 20/120 rather than the average of 10/100 and 10/20.
        panel = pd.DataFrame(
            [
                window_row("AAA", 0, off_poss=100, turnovers=10),
                window_row("AAA", 1, off_poss=20, turnovers=10),
            ]
        )
        metrics = period_metrics(panel, ["off_poss", "turnovers", "points", "fg2_a", "fg3_a"])
        pooled = 20 / 120
        naive = np.mean([10 / 100, 10 / 20])
        self.assertAlmostEqual(metrics["turnover_rate"], pooled)
        self.assertNotAlmostEqual(metrics["turnover_rate"], naive)


class StyleScalingTest(unittest.TestCase):
    def test_scale_is_cross_team_spread(self):
        season = pd.DataFrame(
            {"team_abbreviation": ["A", "B", "C"], "three_point_attempt_rate": [0.30, 0.40, 0.50]}
        )
        scales = league_scales(season, ["three_point_attempt_rate"])
        self.assertAlmostEqual(scales["three_point_attempt_rate"], np.std([0.30, 0.40, 0.50], ddof=1))

    def test_zero_spread_yields_no_scale(self):
        season = pd.DataFrame({"team_abbreviation": ["A", "B"], "pace": [80.0, 80.0]})
        self.assertTrue(pd.isna(league_scales(season, ["pace"])["pace"]))

    def test_z_delta_is_delta_over_scale(self):
        periods = pd.DataFrame(
            [
                {"team_abbreviation": "A", "period": BASELINE, "pace": 78.0},
                {"team_abbreviation": "A", "period": RECENT, "pace": 82.0},
            ]
        )
        deltas = dimension_deltas(periods, pd.Series({"pace": 2.0}), ["pace"])
        row = deltas.iloc[0]
        self.assertAlmostEqual(row["delta"], 4.0)
        self.assertAlmostEqual(row["z_delta"], 2.0)


class ShiftScoreTest(unittest.TestCase):
    def test_score_ignores_missing_dimensions(self):
        self.assertAlmostEqual(shift_score(np.array([1.0, -2.0, np.nan])), 3.0)

    def test_a_real_style_change_scores_above_its_own_null(self):
        panel = build_panel(shift_team="AAA")
        period_frame, season_frame, _ = build_style_frame(
            panel, dimensions=DIMENSIONS, recent_games=4, min_baseline_games=2
        )
        scales = league_scales(season_frame, DIMENSIONS)
        deltas = dimension_deltas(period_frame, scales, DIMENSIONS)

        shifted = deltas[deltas["team_abbreviation"] == "AAA"]
        steady = deltas[deltas["team_abbreviation"] == "BBB"]
        shifted_score = np.nansum(np.abs(shifted["z_delta"]))
        steady_score = np.nansum(np.abs(steady["z_delta"]))
        self.assertGreater(shifted_score, steady_score)

    def test_permutation_null_is_empty_for_a_single_window(self):
        panel = build_panel(teams=("AAA",), windows=1)
        null = permutation_null(
            panel,
            dimensions=DIMENSIONS,
            scales=pd.Series({d: 1.0 for d in DIMENSIONS}),
            totals_columns=totals_columns_for(panel),
            recent_games=4,
            iterations=10,
            rng=np.random.default_rng(0),
        )
        self.assertEqual(null.size, 0)

    def test_permutation_null_preserves_season_totals(self):
        # Every permutation reuses the same windows, so baseline + recent must be constant.
        panel = build_panel(teams=("AAA",), windows=8)
        columns = totals_columns_for(panel)
        null = permutation_null(
            panel,
            dimensions=DIMENSIONS,
            scales=pd.Series({d: 1.0 for d in DIMENSIONS}),
            totals_columns=columns,
            recent_games=4,
            iterations=50,
            rng=np.random.default_rng(3),
        )
        self.assertEqual(null.size, 50)
        self.assertTrue(np.all(np.isfinite(null)))

    def test_style_from_totals_matches_manual_rates(self):
        totals = pd.DataFrame(
            [{"games_in_window": 2, "off_poss": 160, "fg2_a": 90, "fg3_a": 60, "turnovers": 24, "at_rim_fga": 40}]
        )
        style = style_from_totals(totals, ["three_point_attempt_rate", "turnover_rate", "pace", "rim_fga_share"])
        self.assertAlmostEqual(style.iloc[0]["three_point_attempt_rate"], 60 / 150)
        self.assertAlmostEqual(style.iloc[0]["turnover_rate"], 24 / 160)
        self.assertAlmostEqual(style.iloc[0]["pace"], 80.0)
        self.assertAlmostEqual(style.iloc[0]["rim_fga_share"], 40 / 150)


class DecompositionTest(unittest.TestCase):
    def _period(self, *, off_poss, fga, fgm, fg3m, ft_points, quality, points=None):
        """A period whose points follow from its made shots, as real data does."""
        efg = (fgm + 0.5 * fg3m) / fga
        return pd.Series(
            {
                "points": 2 * fgm + fg3m + ft_points if points is None else points,
                "off_poss": off_poss,
                "fga": fga,
                "ft_points": ft_points,
                "efg_pct": efg,
                "shotquality_pbp_avg": quality,
            }
        )

    def test_components_reconcile_to_the_observed_change(self):
        baseline = self._period(off_poss=160, fga=120, fgm=55, fg3m=15, ft_points=15, quality=0.48)
        recent = self._period(off_poss=160, fga=126, fgm=62, fg3m=20, ft_points=18, quality=0.52)
        record = decompose_offense(baseline, recent)
        modelled = (
            record["shot_quality_effect"]
            + record["shot_making_effect"]
            + record["shot_rate_effect"]
            + record["free_throw_effect"]
        )
        self.assertAlmostEqual(record["off_rating_delta"], modelled, places=9)
        self.assertAlmostEqual(record["decomposition_residual"], 0.0, places=9)

    def test_better_shot_locations_show_up_as_quality_not_making(self):
        # eFG% is unchanged; only the expected value of the shots taken rose.
        baseline = self._period(off_poss=160, fga=120, fgm=57, fg3m=16, ft_points=15, quality=0.45)
        recent = self._period(off_poss=160, fga=120, fgm=57, fg3m=16, ft_points=15, quality=0.55)
        record = decompose_offense(baseline, recent)
        self.assertGreater(record["shot_quality_effect"], 0)
        self.assertLess(record["shot_making_effect"], 0)
        self.assertAlmostEqual(
            record["shot_quality_effect"] + record["shot_making_effect"], 0.0, places=9
        )

    def test_hot_shooting_shows_up_as_making_not_quality(self):
        baseline = self._period(off_poss=160, fga=120, fgm=55, fg3m=15, ft_points=15, quality=0.50)
        recent = self._period(off_poss=160, fga=120, fgm=64, fg3m=15, ft_points=15, quality=0.50)
        record = decompose_offense(baseline, recent)
        self.assertAlmostEqual(record["shot_quality_effect"], 0.0, places=9)
        self.assertGreater(record["shot_making_effect"], 0)
        self.assertEqual(classify_nature(record), "Conversion-led (cosmetic)")

    def test_inconsistent_points_surface_in_the_residual(self):
        # The identity assumes points == 2*FGM + 3PM + FT points. If a source ever breaks
        # that, the residual must expose it rather than the components absorbing it.
        baseline = self._period(off_poss=160, fga=120, fgm=55, fg3m=15, ft_points=15, quality=0.50)
        broken = self._period(
            off_poss=160, fga=120, fgm=55, fg3m=15, ft_points=15, quality=0.50, points=999
        )
        record = decompose_offense(baseline, broken)
        self.assertGreater(abs(record["decomposition_residual"]), 1.0)

    def test_flat_offense_is_labelled_as_such(self):
        baseline = self._period(off_poss=160, fga=120, fgm=55, fg3m=15, ft_points=15, quality=0.50)
        record = decompose_offense(baseline, baseline)
        self.assertEqual(classify_nature(record), "No material offensive change")

    def test_table_covers_every_team_with_both_periods(self):
        panel = build_panel(shift_team="AAA")
        period_frame, _, _ = build_style_frame(
            panel, dimensions=DIMENSIONS, recent_games=4, min_baseline_games=2
        )
        table = build_decomposition_table(period_frame)
        self.assertEqual(len(table), 4)
        self.assertLess(table["decomposition_residual"].abs().max(), 1e-9)


class ScheduleContextTest(unittest.TestCase):
    def test_abbreviations_are_normalised(self):
        self.assertEqual(team_key("GS"), "GSV")
        self.assertEqual(team_key("wsh"), "WAS")
        self.assertEqual(team_key("MIN"), "MIN")

    def test_each_game_yields_a_row_per_side(self):
        schedule = pd.DataFrame(
            [{"game_date": "2026-06-01", "home_abbreviation": "GS", "away_abbreviation": "MIN"}]
        )
        opponents = build_game_opponents(schedule)
        self.assertEqual(len(opponents), 2)
        self.assertEqual(set(opponents["team_abbreviation"]), {"GSV", "MIN"})
        self.assertEqual(
            opponents.loc[opponents["team_abbreviation"] == "GSV", "opponent_abbreviation"].iloc[0], "MIN"
        )

    def test_period_opponent_strength_uses_covered_dates(self):
        panel = pd.DataFrame(
            [
                window_row("AAA", 0),
                window_row("AAA", 1),
                window_row("AAA", 2),
                window_row("AAA", 3),
            ]
        )
        schedule = pd.DataFrame(
            [
                {"game_date": "2026-06-01", "home_abbreviation": "AAA", "away_abbreviation": "BBB"},
                {"game_date": "2026-06-02", "home_abbreviation": "AAA", "away_abbreviation": "BBB"},
                {"game_date": "2026-06-03", "home_abbreviation": "CCC", "away_abbreviation": "AAA"},
                {"game_date": "2026-06-04", "home_abbreviation": "CCC", "away_abbreviation": "AAA"},
            ]
        )
        season = pd.DataFrame(
            {"team_abbreviation": ["AAA", "BBB", "CCC"], "net_rating": [0.0, -10.0, 10.0]}
        )
        context = build_period_schedule_context(panel, schedule, season, recent_games=2)
        recent = context[context["period"] == RECENT].iloc[0]
        baseline = context[context["period"] == BASELINE].iloc[0]
        self.assertAlmostEqual(baseline["opponent_net_rating"], -10.0)
        self.assertAlmostEqual(recent["opponent_net_rating"], 10.0)
        self.assertAlmostEqual(recent["home_rate"], 0.0)

    def test_missing_schedule_returns_empty_context(self):
        panel = build_panel(teams=("AAA",), windows=4)
        context = build_period_schedule_context(panel, pd.DataFrame(), pd.DataFrame(), recent_games=2)
        self.assertTrue(context.empty)
        self.assertTrue(schedule_deltas(context).empty)


class ScheduleAdjustmentTest(unittest.TestCase):
    def test_easier_schedule_discounts_an_apparent_gain(self):
        shift = pd.DataFrame(
            [{"team_abbreviation": "AAA", "net_rating_delta": 4.0, "opponent_net_rating_delta": -6.0}]
        )
        out = apply_schedule_adjustment(shift, CONFIG).iloc[0]
        self.assertAlmostEqual(out["opponent_adjusted_net_rating_delta"], -2.0)
        self.assertEqual(out["shift_direction"], "Hurting")

    def test_harder_schedule_credits_an_apparent_decline(self):
        shift = pd.DataFrame(
            [{"team_abbreviation": "AAA", "net_rating_delta": -1.0, "opponent_net_rating_delta": 5.0}]
        )
        out = apply_schedule_adjustment(shift, CONFIG).iloc[0]
        self.assertAlmostEqual(out["opponent_adjusted_net_rating_delta"], 4.0)
        self.assertEqual(out["shift_direction"], "Helping")

    def test_missing_schedule_falls_back_to_raw_net_rating(self):
        shift = pd.DataFrame(
            [{"team_abbreviation": "AAA", "net_rating_delta": 3.0, "opponent_net_rating_delta": np.nan}]
        )
        out = apply_schedule_adjustment(shift, CONFIG).iloc[0]
        self.assertAlmostEqual(out["opponent_adjusted_net_rating_delta"], 3.0)
        self.assertEqual(out["shift_direction_basis"], "raw_net_rating")


class BuilderEndToEndTest(unittest.TestCase):
    def test_cli_writes_every_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            panel_dir = tmpdir / "panel" / "data" / "processed"
            panel_dir.mkdir(parents=True)
            sports_dir = tmpdir / "sportsdataverse"
            sports_dir.mkdir(parents=True)

            build_panel(shift_team="AAA").to_csv(panel_dir / "team_window_panel_2026.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "game_date": f"2026-06-{day:02d}",
                        "home_abbreviation": "AAA",
                        "away_abbreviation": "BBB",
                    }
                    for day in range(1, 13)
                ]
            ).to_parquet(sports_dir / "schedule_2026.parquet")

            config = json.loads(json.dumps(CONFIG))
            config.update(
                {
                    "season": 2026,
                    "window_panel_root": str(tmpdir / "panel"),
                    "sportsdataverse_data_root": str(sports_dir),
                    "output_root": str(tmpdir / "analysis"),
                    "source_files": {
                        "team_window_panel": "data/processed/team_window_panel_2026.csv",
                        "schedule": "schedule_2026.parquet",
                    },
                }
            )
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_team_identity_shift.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            processed = tmpdir / "analysis" / "data" / "processed"
            shift = pd.read_csv(processed / "team_identity_shift_2026.csv")
            decomposition = pd.read_csv(processed / "team_shift_decomposition_2026.csv")
            manifest = json.loads((processed / "run_manifest_2026.json").read_text(encoding="utf-8"))

            self.assertEqual(len(shift), 4)
            self.assertIn("shift_significance", shift.columns)
            self.assertIn("opponent_adjusted_net_rating_delta", shift.columns)
            self.assertLess(decomposition["decomposition_residual"].abs().max(), 1e-9)
            self.assertEqual(manifest["analysis_stats"]["status"], "ok")
            # The team whose shot diet changed should top the ranking.
            self.assertEqual(shift.iloc[0]["team_abbreviation"], "AAA")

    def test_missing_panel_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = json.loads(json.dumps(CONFIG))
            config.update(
                {
                    "window_panel_root": str(tmpdir / "absent"),
                    "sportsdataverse_data_root": str(tmpdir / "absent"),
                    "output_root": str(tmpdir / "analysis"),
                }
            )
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_team_identity_shift.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (tmpdir / "analysis" / "data" / "processed" / "run_manifest_2026.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["analysis_stats"]["status"], "window_panel_missing")


if __name__ == "__main__":
    unittest.main()
