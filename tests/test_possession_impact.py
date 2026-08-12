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

from possession_impact.design import (  # noqa: E402
    attach_bench_counts,
    attach_home_flag,
    attach_score_state,
    build_design_matrix,
    derive_starters,
    player_index,
    possession_counts,
    prepare_possessions,
)
from possession_impact.net_ratings import (  # noqa: E402
    build_bench_net_rating,
    build_clutch_net_rating,
)
from possession_impact.rapm import (  # noqa: E402
    build_rapm_table,
    cross_validate_alpha,
    fit_rapm,
    game_folds,
    solve_ridge,
)


def possession(
    game_id="g1",
    period=1,
    number=1,
    offense_team=10,
    defense_team=20,
    offense=(1, 2, 3, 4, 5),
    defense=(6, 7, 8, 9, 10),
    points=2,
    counted=True,
    seconds=500.0,
):
    row = {
        "game_id": game_id,
        "period": period,
        "possession_number": number,
        "offense_team_id": offense_team,
        "defense_team_id": defense_team,
        "points": points,
        "count_as_possession": counted,
        "start_seconds_remaining": seconds,
    }
    for index, player in enumerate(offense, start=1):
        row[f"off_player_{index}"] = player
    for index, player in enumerate(defense, start=1):
        row[f"def_player_{index}"] = player
    return row


class PreparePossessionsTest(unittest.TestCase):
    def test_uncounted_and_incomplete_rows_are_dropped(self):
        rows = [
            possession(number=1),
            possession(number=2, counted=False),
            possession(number=3, offense=(1, 2, 3, 4, None)),
        ]
        out, counts = prepare_possessions(pd.DataFrame(rows))
        self.assertEqual(len(out), 1)
        self.assertEqual(counts["dropped_not_counted"], 1)
        self.assertEqual(counts["dropped_incomplete_lineup"], 1)
        self.assertEqual(counts["usable_possessions"], 1)

    def test_lineups_become_integers(self):
        out, _ = prepare_possessions(pd.DataFrame([possession()]))
        self.assertEqual(out["off_player_1"].dtype, np.dtype("int64"))

    def test_players_are_sorted_and_unique(self):
        rows = [possession(offense=(5, 4, 3, 2, 1), defense=(9, 8, 7, 6, 10))]
        out, _ = prepare_possessions(pd.DataFrame(rows))
        self.assertEqual(player_index(out), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])


class HomeFlagTest(unittest.TestCase):
    def test_home_flag_comes_from_play_by_play_location(self):
        poss, _ = prepare_possessions(pd.DataFrame([possession(offense_team=10, defense_team=20)]))
        pbp = pd.DataFrame(
            [
                {"game_id": "g1", "team_id": 10, "location": "h"},
                {"game_id": "g1", "team_id": 20, "location": "v"},
            ]
        )
        out = attach_home_flag(poss, pbp)
        self.assertEqual(out.iloc[0]["offense_is_home"], 1.0)

    def test_away_offense_is_flagged_zero(self):
        poss, _ = prepare_possessions(pd.DataFrame([possession(offense_team=20, defense_team=10)]))
        pbp = pd.DataFrame(
            [
                {"game_id": "g1", "team_id": 10, "location": "h"},
                {"game_id": "g1", "team_id": 20, "location": "v"},
            ]
        )
        self.assertEqual(attach_home_flag(poss, pbp).iloc[0]["offense_is_home"], 0.0)

    def test_missing_play_by_play_leaves_the_flag_null(self):
        poss, _ = prepare_possessions(pd.DataFrame([possession()]))
        self.assertTrue(pd.isna(attach_home_flag(poss, pd.DataFrame()).iloc[0]["offense_is_home"]))


class StartersAndBenchTest(unittest.TestCase):
    def _frame(self):
        rows = [
            possession(number=1, period=1, offense=(1, 2, 3, 4, 5), defense=(6, 7, 8, 9, 10)),
            possession(number=2, period=1, offense_team=20, defense_team=10, offense=(6, 7, 8, 9, 10), defense=(1, 2, 3, 4, 5)),
            # Two substitutes come in for the home side.
            possession(number=3, period=2, offense=(1, 2, 3, 11, 12), defense=(6, 7, 8, 9, 10)),
        ]
        out, _ = prepare_possessions(pd.DataFrame(rows))
        return out

    def test_starters_are_the_opening_possession_lineups(self):
        starters = derive_starters(self._frame())
        self.assertEqual(starters[("g1", 10)], frozenset({1, 2, 3, 4, 5}))
        self.assertEqual(starters[("g1", 20)], frozenset({6, 7, 8, 9, 10}))

    def test_bench_counts_reflect_substitutions(self):
        frame = self._frame()
        out = attach_bench_counts(frame, derive_starters(frame))
        self.assertEqual(list(out["offense_bench_on_court"]), [0.0, 0.0, 2.0])
        self.assertEqual(list(out["defense_bench_on_court"]), [0.0, 0.0, 0.0])

    def test_unknown_game_leaves_bench_counts_null(self):
        frame = self._frame()
        out = attach_bench_counts(frame, {})
        self.assertTrue(out["offense_bench_on_court"].isna().all())


class ScoreStateTest(unittest.TestCase):
    def test_running_score_is_lagged_by_one_possession(self):
        rows = [
            possession(number=1, offense_team=10, defense_team=20, points=2),
            possession(number=2, offense_team=20, defense_team=10, points=3),
            possession(number=3, offense_team=10, defense_team=20, points=2),
        ]
        frame, _ = prepare_possessions(pd.DataFrame(rows))
        out = attach_score_state(frame)
        # Before possession 3 the score is 2-3 in favour of the away side.
        third = out.iloc[2]
        self.assertEqual(third["offense_score_before"], 2)
        self.assertEqual(third["defense_score_before"], 3)
        self.assertEqual(third["offense_margin_before"], -1)

    def test_first_possession_starts_level(self):
        frame, _ = prepare_possessions(pd.DataFrame([possession(points=2)]))
        out = attach_score_state(frame)
        self.assertEqual(out.iloc[0]["offense_margin_before"], 0)

    def test_games_do_not_bleed_into_each_other(self):
        rows = [
            possession(game_id="g1", number=1, points=3),
            possession(game_id="g2", number=1, points=2),
        ]
        frame, _ = prepare_possessions(pd.DataFrame(rows))
        out = attach_score_state(frame)
        self.assertTrue((out["offense_score_before"] == 0).all())


class DesignMatrixTest(unittest.TestCase):
    def test_layout_signs_and_response_scaling(self):
        frame, _ = prepare_possessions(pd.DataFrame([possession(points=2)]))
        frame = attach_home_flag(frame, pd.DataFrame([{"game_id": "g1", "team_id": 10, "location": "h"}]))
        players = player_index(frame)
        matrix, response, names = build_design_matrix(frame, players)

        self.assertEqual(matrix.shape, (1, 2 + 2 * len(players)))
        self.assertEqual(matrix[0, 0], 1.0)
        self.assertEqual(matrix[0, 1], 1.0)
        self.assertEqual(response[0], 200.0)
        # Five offensive slots at +1, five defensive at -1.
        self.assertEqual(matrix[0, 2:].sum(), 0.0)
        self.assertEqual((matrix[0, 2:] == 1.0).sum(), 5)
        self.assertEqual((matrix[0, 2:] == -1.0).sum(), 5)
        self.assertEqual(names[0], "intercept")
        self.assertEqual(names[1], "home")

    def test_possession_counts_split_offense_and_defense(self):
        rows = [possession(number=1), possession(number=2, offense=(6, 7, 8, 9, 10), defense=(1, 2, 3, 4, 5))]
        frame, _ = prepare_possessions(pd.DataFrame(rows))
        counts = possession_counts(frame, player_index(frame)).set_index("player_id")
        self.assertEqual(counts.loc[1, "off_poss"], 1)
        self.assertEqual(counts.loc[1, "def_poss"], 1)
        self.assertEqual(counts.loc[1, "total_poss"], 2)


class RidgeTest(unittest.TestCase):
    def test_nuisance_columns_are_not_shrunk(self):
        matrix = np.array([[1.0, 0.0, 1.0], [1.0, 1.0, -1.0], [1.0, 0.0, 1.0], [1.0, 1.0, -1.0]])
        response = np.array([10.0, 20.0, 10.0, 20.0])
        gram, moment = matrix.T @ matrix, matrix.T @ response
        heavy = solve_ridge(gram, moment, alpha=1e6)
        # The player term is crushed toward zero; intercept and home survive to fit the data.
        self.assertAlmostEqual(heavy[2], 0.0, places=4)
        self.assertGreater(abs(heavy[0]), 1.0)

    def test_zero_alpha_reproduces_least_squares(self):
        rng = np.random.default_rng(0)
        matrix = np.column_stack([np.ones(50), rng.normal(size=50), rng.normal(size=50)])
        response = matrix @ np.array([5.0, 2.0, -1.0])
        beta = solve_ridge(matrix.T @ matrix, matrix.T @ response, alpha=0.0)
        np.testing.assert_allclose(beta, [5.0, 2.0, -1.0], atol=1e-8)

    def test_degenerate_home_column_does_not_crash(self):
        # No play-by-play means a constant home column, which is unpenalized and therefore
        # singular. The solver must fall back rather than abort the run.
        matrix = np.column_stack([np.ones(6), np.zeros(6), np.array([1.0, -1, 1, -1, 1, -1])])
        response = np.array([10.0, 20, 10, 20, 10, 20])
        beta = solve_ridge(matrix.T @ matrix, matrix.T @ response, alpha=10.0)
        self.assertTrue(np.all(np.isfinite(beta)))

    def test_folds_never_split_a_game(self):
        games = ["a", "a", "b", "b", "c", "c", "d", "d"]
        folds = game_folds(games, folds=2, seed=1)
        assignment = pd.DataFrame({"game": games, "fold": folds})
        self.assertTrue((assignment.groupby("game")["fold"].nunique() == 1).all())

    def test_cross_validation_returns_a_grid_alpha(self):
        rng = np.random.default_rng(3)
        matrix = np.column_stack([np.ones(200), rng.integers(0, 2, 200), rng.normal(size=(200, 4))])
        response = matrix @ np.array([100.0, 2.0, 1.0, -1.0, 0.5, 0.0]) + rng.normal(size=200)
        grid = [1.0, 10.0, 100.0]
        alpha, scores = cross_validate_alpha(
            matrix, response, ["g%d" % (i // 10) for i in range(200)], alpha_grid=grid, folds=3, seed=5
        )
        self.assertIn(alpha, grid)
        self.assertEqual(len(scores), 3)
        self.assertTrue(scores["cv_rmse"].notna().all())


class RapmBehaviourTest(unittest.TestCase):
    """A player who genuinely helps should come out on top of a synthetic league."""

    def _synthetic(self, star=1, edge=0.4, games=60, seed=11):
        rng = np.random.default_rng(seed)
        roster_a, roster_b = list(range(1, 9)), list(range(9, 17))
        rows = []
        for game in range(games):
            for number in range(60):
                offense_is_a = number % 2 == 0
                attackers = rng.choice(roster_a if offense_is_a else roster_b, 5, replace=False)
                defenders = rng.choice(roster_b if offense_is_a else roster_a, 5, replace=False)
                base = 1.0 + (edge if star in set(attackers) else 0.0)
                points = 2 if rng.random() < base / 2 else 0
                rows.append(
                    possession(
                        game_id=f"g{game}",
                        number=number + 1,
                        offense_team=10 if offense_is_a else 20,
                        defense_team=20 if offense_is_a else 10,
                        offense=tuple(int(x) for x in attackers),
                        defense=tuple(int(x) for x in defenders),
                        points=points,
                    )
                )
        frame, _ = prepare_possessions(pd.DataFrame(rows))
        return frame

    def test_the_planted_star_ranks_first_on_offense(self):
        frame = self._synthetic()
        players = player_index(frame)
        matrix, response, _ = build_design_matrix(frame, players)
        table, fit = fit_rapm(matrix, response, players, alpha=100.0)
        self.assertEqual(int(table.sort_values("o_rapm", ascending=False).iloc[0]["player_id"]), 1)
        self.assertEqual(fit["possessions"], len(frame))

    def test_table_flags_low_samples_and_drops_the_thinnest(self):
        table = pd.DataFrame({"player_id": [1, 2, 3], "o_rapm": [1.0, 0.0, -1.0], "d_rapm": [0.5, 0.0, -0.5], "rapm": [1.5, 0.0, -1.5]})
        counts = pd.DataFrame({"player_id": [1, 2, 3], "off_poss": [400, 60, 20], "def_poss": [400, 60, 20], "total_poss": [800, 120, 40]})
        out = build_rapm_table(table, counts, min_possessions_reliable=500, min_possessions_reported=100)
        self.assertEqual(list(out["player_id"]), [1, 2])
        self.assertEqual(list(out["sample_flag"]), ["Reliable", "Low sample"])
        self.assertEqual(list(out["rapm_rank"]), [1, 2])


class NetRatingTest(unittest.TestCase):
    def test_bench_slices_use_the_right_possessions(self):
        rows = [
            # Starters-only possession for team 10: scores 2.
            possession(number=1, offense_team=10, defense_team=20, points=2),
            # Team 10 with two bench players on: scores 0.
            possession(number=2, period=2, offense_team=10, defense_team=20, offense=(1, 2, 3, 11, 12), points=0),
        ]
        frame, _ = prepare_possessions(pd.DataFrame(rows))
        frame = attach_bench_counts(frame, derive_starters(frame))
        bench = build_bench_net_rating(frame, bench_heavy_threshold=2).set_index("team_id")
        self.assertEqual(bench.loc[10, "starters_only_off_rating"], 200.0)
        self.assertEqual(bench.loc[10, "any_bench_off_rating"], 0.0)
        self.assertEqual(bench.loc[10, "bench_heavy_off_rating"], 0.0)

    def test_clutch_uses_the_margin_before_the_possession(self):
        rows = [
            # Late, close: qualifies. Scoring on it must not disqualify it.
            possession(number=1, period=4, seconds=100.0, offense_team=10, defense_team=20, points=3),
            # Late but a blowout by then: excluded.
            possession(number=2, period=4, seconds=90.0, offense_team=10, defense_team=20, points=2),
            # Early: excluded.
            possession(number=3, period=1, seconds=100.0, offense_team=10, defense_team=20, points=2),
        ]
        frame, _ = prepare_possessions(pd.DataFrame(rows))
        frame = attach_score_state(frame)
        clutch = build_clutch_net_rating(frame, max_seconds_remaining=300, min_period=4, max_score_margin=2)
        team = clutch.set_index("team_id").loc[10]
        self.assertEqual(team["clutch_off_poss"], 1)
        self.assertEqual(team["clutch_off_rating"], 300.0)

    def test_empty_input_returns_empty_frames_with_columns(self):
        self.assertTrue(build_bench_net_rating(pd.DataFrame(), bench_heavy_threshold=3).empty)
        self.assertIn(
            "clutch_net_rating",
            build_clutch_net_rating(pd.DataFrame(), max_seconds_remaining=300, min_period=4, max_score_margin=5).columns,
        )


class BuilderEndToEndTest(unittest.TestCase):
    def test_cli_writes_outputs_stamped_with_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            sports = tmpdir / "sportsdataverse"
            sports.mkdir(parents=True)
            pbp_root = tmpdir / "pbpstats" / "features_latest" / "2026"
            pbp_root.mkdir(parents=True)

            rng = np.random.default_rng(2)
            rows, logs, pbp = [], [], []
            for game in range(12):
                pbp.extend(
                    [
                        {"game_id": f"g{game}", "team_id": 10, "location": "h"},
                        {"game_id": f"g{game}", "team_id": 20, "location": "v"},
                    ]
                )
                logs.append({"game_id": f"g{game}", "game_date": f"2026-06-{game + 1:02d}"})
                for number in range(40):
                    offense_is_a = number % 2 == 0
                    attackers = rng.choice(list(range(1, 9)) if offense_is_a else list(range(9, 17)), 5, replace=False)
                    defenders = rng.choice(list(range(9, 17)) if offense_is_a else list(range(1, 9)), 5, replace=False)
                    rows.append(
                        possession(
                            game_id=f"g{game}",
                            period=1 + number // 10,
                            number=number + 1,
                            offense_team=10 if offense_is_a else 20,
                            defense_team=20 if offense_is_a else 10,
                            offense=tuple(int(x) for x in attackers),
                            defense=tuple(int(x) for x in defenders),
                            points=int(rng.choice([0, 2, 3])),
                            seconds=float(600 - number * 10),
                        )
                    )
            pd.DataFrame(rows).to_parquet(sports / "wnba_possessions_2026.parquet")
            pd.DataFrame(pbp).to_parquet(sports / "wnba_pbp_2026.parquet")
            pd.DataFrame(logs).to_parquet(sports / "player_game_logs_2026.parquet")
            pd.DataFrame([{"player_id": 1, "rapm": 0.5}]).to_parquet(sports / "wnba_player_impact_2026.parquet")
            pd.DataFrame(
                [{"entity_id": i, "name": f"P{i}", "team_abbreviation": "AAA"} for i in range(1, 17)]
            ).to_csv(pbp_root / "player_totals_features_latest.csv", index=False)
            pd.DataFrame([{"team_id": 10, "team_abbreviation": "AAA"}, {"team_id": 20, "team_abbreviation": "BBB"}]).to_csv(
                pbp_root / "team_totals_features_latest.csv", index=False
            )

            config = {
                "season": 2026,
                "sportsdataverse_data_root": str(sports),
                "pbpstats_data_root": str(tmpdir / "pbpstats"),
                "output_root": str(tmpdir / "analysis"),
                "rapm": {"alpha_grid": [100, 1000], "cv_folds": 3, "random_seed": 1, "min_possessions_reliable": 200, "min_possessions_reported": 50},
                "bench": {"bench_heavy_threshold": 3},
                "clutch": {"max_seconds_remaining": 300, "min_period": 4, "max_score_margin": 5},
            }
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_possession_impact.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            processed = tmpdir / "analysis" / "data" / "processed"
            rapm = pd.read_csv(processed / "rapm_player_2026.csv")
            bench = pd.read_csv(processed / "bench_net_rating_2026.csv")
            manifest = json.loads((processed / "run_manifest_2026.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["analysis_stats"]["status"], "ok")
            self.assertEqual(manifest["analysis_stats"]["coverage"]["coverage_through"], "2026-06-12")
            # The lag travels with every file, not just the manifest.
            self.assertEqual(set(rapm["coverage_through"]), {"2026-06-12"})
            self.assertEqual(set(bench["coverage_through"]), {"2026-06-12"})
            self.assertIn("player_name", rapm.columns)
            self.assertIn("team_abbreviation", bench.columns)

    def test_missing_possessions_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = {
                "sportsdataverse_data_root": str(tmpdir / "absent"),
                "pbpstats_data_root": str(tmpdir / "absent"),
                "output_root": str(tmpdir / "analysis"),
            }
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_possession_impact.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (tmpdir / "analysis" / "data" / "processed" / "run_manifest_2026.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["analysis_stats"]["status"], "possessions_missing")


if __name__ == "__main__":
    unittest.main()
