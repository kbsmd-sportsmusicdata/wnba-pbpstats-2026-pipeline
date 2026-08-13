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

from playoff_readiness.ratings import (  # noqa: E402
    backtest,
    design_matrix,
    fit_ratings,
    recency_weights,
    sample_ratings,
    win_probability,
)
from playoff_readiness.readiness import (  # noqa: E402
    _shrink_clutch,
    result_metrics,
    rotation_metrics,
    style_metrics,
)
from playoff_readiness.schedule import (  # noqa: E402
    LEAGUE_TEAMS,
    current_standings,
    head_to_head,
    long_results,
    reconcile_schedule,
    team_key,
)
from playoff_readiness.simulate import (  # noqa: E402
    clinch_flags,
    game_leverage,
    magic_numbers,
    rank_teams,
    season_state,
    series_win_probability,
    simulate_remaining,
    summarize,
)


def game(
    game_id,
    date,
    home,
    away,
    home_score=None,
    away_score=None,
    status="STATUS_FINAL",
    completed=True,
    game_type="STD",
):
    return {
        "game_id": game_id,
        "game_date": date,
        "home_abbreviation": home,
        "away_abbreviation": away,
        "home_score": home_score if home_score is not None else 0,
        "away_score": away_score if away_score is not None else 0,
        "status_type_completed": completed,
        "status_type_name": status,
        "type_abbreviation": game_type,
        "neutral_site": False,
    }


def round_robin(teams, *, rounds=2, start_day=1, scores=None):
    """A complete double round-robin, so every team plays the same number of games."""
    rows = []
    day = start_day
    for repeat in range(rounds):
        for i, home in enumerate(teams):
            for away in teams[i + 1 :]:
                first, second = (home, away) if repeat == 0 else (away, home)
                points = scores(first, second) if scores else (80, 70)
                rows.append(
                    game(f"g{len(rows)}", f"2026-05-{day:02d}", first, second, points[0], points[1])
                )
        day += 1
    return rows


class ScheduleReconciliationTest(unittest.TestCase):
    def test_a_balanced_season_splits_into_played_and_remaining(self):
        teams = list(LEAGUE_TEAMS)
        rows = round_robin(teams)
        # One more full round, unplayed: every team gains exactly fourteen fixtures.
        upcoming = [
            game(f"u{index}", "2026-09-01", home, away, status="STATUS_SCHEDULED", completed=False)
            for index, (home, away) in enumerate(zip(teams, teams[1:] + teams[:1]))
        ]
        played, remaining, diagnostics = reconcile_schedule(pd.DataFrame(rows + upcoming))
        self.assertTrue(diagnostics["reconciled"], diagnostics["teams_off_expected"])
        self.assertEqual(len(played), len(rows))
        self.assertEqual(len(remaining), len(upcoming))
        self.assertEqual(diagnostics["expected_games_per_team"], 30)
        self.assertEqual(diagnostics["played_through"], "2026-05-02")
        self.assertEqual(diagnostics["season_ends"], "2026-09-01")

    def test_an_unbalanced_schedule_is_reported_as_unreconciled(self):
        rows = round_robin(list(LEAGUE_TEAMS))
        rows.append(game("extra", "2026-06-01", "MIN", "NYL", 90, 80))
        _, _, diagnostics = reconcile_schedule(pd.DataFrame(rows))
        self.assertFalse(diagnostics["reconciled"])
        self.assertEqual(diagnostics["teams_off_expected"], ["MIN", "NYL"])

    def test_commissioners_cup_final_is_excluded(self):
        rows = round_robin(list(LEAGUE_TEAMS))
        rows.append(game("cup", "2026-06-30", "NYL", "LVA", 93, 85, game_type="CC"))
        played, _, diagnostics = reconcile_schedule(pd.DataFrame(rows))
        self.assertEqual(len(played), len(rows) - 1)
        self.assertTrue(diagnostics["reconciled"])
        self.assertIn(("CC", 1), [tuple(entry) for entry in diagnostics["dropped_non_counting_games"]])

    def test_all_star_teams_are_dropped(self):
        rows = round_robin(list(LEAGUE_TEAMS))
        rows.append(game("as", "2026-07-25", "SPO", "COOP", 129, 122, game_type="ALLSTAR"))
        _, _, diagnostics = reconcile_schedule(pd.DataFrame(rows))
        self.assertEqual(diagnostics["dropped_non_league_rows"], 1)
        self.assertTrue(diagnostics["reconciled"])

    def test_postponed_shell_is_dropped_once_the_makeup_has_been_played(self):
        rows = round_robin(list(LEAGUE_TEAMS))
        rows.append(game("shell", "2026-07-16", "DAL", "NYL", status="STATUS_POSTPONED", completed=False))
        played, remaining, diagnostics = reconcile_schedule(pd.DataFrame(rows))
        self.assertEqual(diagnostics["postponed_rows"], 1)
        self.assertEqual(diagnostics["postponed_restored_as_unplayed"], [])
        self.assertTrue(diagnostics["reconciled"])
        self.assertNotIn("shell", set(played["game_id"]) | set(remaining["game_id"]))

    def test_postponed_game_awaiting_a_makeup_is_restored_as_unplayed(self):
        # Drop one real DAL-NYL meeting so the pair is a game short, which is exactly the
        # state a genuinely un-made-up postponement leaves behind.
        rows = [
            row
            for row in round_robin(list(LEAGUE_TEAMS))
            if {row["home_abbreviation"], row["away_abbreviation"]} != {"DAL", "NYL"}
            or row["game_date"] != "2026-05-01"
        ]
        rows.append(game("shell", "2026-07-16", "DAL", "NYL", status="STATUS_POSTPONED", completed=False))
        _, remaining, diagnostics = reconcile_schedule(pd.DataFrame(rows))
        self.assertEqual(diagnostics["postponed_restored_as_unplayed"], ["shell"])
        self.assertIn("shell", set(remaining["game_id"]))
        self.assertTrue(diagnostics["reconciled"])

    def test_standings_come_from_the_game_log(self):
        rows = round_robin(list(LEAGUE_TEAMS), scores=lambda h, a: (90, 80) if h == "MIN" else (80, 90))
        played, remaining, _ = reconcile_schedule(pd.DataFrame(rows))
        standings = current_standings(long_results(played), remaining)
        minnesota = standings.set_index("team_abbreviation").loc["MIN"]
        # MIN wins at home and loses on the road, so it splits its schedule evenly.
        self.assertEqual(int(minnesota["games_played"]), 28)
        self.assertEqual(int(minnesota["wins"]) + int(minnesota["losses"]), 28)

    def test_team_key_maps_both_abbreviation_spaces(self):
        self.assertEqual(team_key("GS"), "GSV")
        self.assertEqual(team_key("GSV"), "GSV")
        self.assertEqual(team_key("WSH"), "WAS")


class RatingModelTest(unittest.TestCase):
    def _noiseless_season(self, ratings, home_advantage=3.0):
        rows = []
        teams = list(ratings)
        for i, home in enumerate(teams):
            for away in teams:
                if home == away:
                    continue
                margin = ratings[home] - ratings[away] + home_advantage
                rows.append(game(f"g{len(rows)}", f"2026-05-{1 + i:02d}", home, away, 80 + margin, 80))
        played, _, _ = reconcile_schedule(pd.DataFrame(rows))
        return played

    def test_noiseless_margins_recover_ratings_and_home_advantage(self):
        truth = {team: value for team, value in zip(LEAGUE_TEAMS, np.linspace(-7, 7, len(LEAGUE_TEAMS)))}
        played = self._noiseless_season(truth, home_advantage=3.0)
        fit = fit_ratings(played, alpha=1e-6, half_life_days=0, margin_cap=0)
        estimated = fit.rating_series()
        for team, value in truth.items():
            self.assertAlmostEqual(estimated[team], value, places=4)
        self.assertAlmostEqual(fit.home_advantage, 3.0, places=4)

    def test_ratings_are_centred_on_the_league(self):
        truth = {team: float(index) for index, team in enumerate(LEAGUE_TEAMS)}
        fit = fit_ratings(self._noiseless_season(truth), alpha=1.0, half_life_days=0, margin_cap=0)
        self.assertAlmostEqual(float(fit.ratings.sum()), 0.0, places=6)

    def test_the_margin_cap_limits_a_blowout(self):
        rows = round_robin(list(LEAGUE_TEAMS))
        rows[0] = game(rows[0]["game_id"], rows[0]["game_date"], rows[0]["home_abbreviation"], rows[0]["away_abbreviation"], 180, 70)
        played, _, _ = reconcile_schedule(pd.DataFrame(rows))
        capped = fit_ratings(played, alpha=1.0, half_life_days=0, margin_cap=20)
        uncapped = fit_ratings(played, alpha=1.0, half_life_days=0, margin_cap=0)
        blown_out = rows[0]["home_abbreviation"]
        self.assertLess(
            capped.rating_series()[blown_out],
            uncapped.rating_series()[blown_out],
        )

    def test_recency_weights_decay_by_half_life(self):
        dates = pd.Series(pd.to_datetime(["2026-05-01", "2026-06-01", "2026-07-01"]))
        weights = recency_weights(dates, half_life_days=30.0, reference=pd.Timestamp("2026-07-01"))
        self.assertAlmostEqual(weights[-1], 1.0, places=6)
        self.assertAlmostEqual(weights[-2], 0.5, places=1)
        self.assertLess(weights[0], weights[1])

    def test_zero_half_life_means_no_weighting(self):
        dates = pd.Series(pd.to_datetime(["2026-05-01", "2026-07-01"]))
        self.assertTrue(np.allclose(recency_weights(dates, half_life_days=0), 1.0))

    def test_design_matrix_rows_sum_to_zero_across_teams(self):
        matrix = design_matrix(["MIN", "ATL"], ["NYL", "CHI"], teams=LEAGUE_TEAMS)
        self.assertTrue(np.allclose(matrix[:, :-1].sum(axis=1), 0.0))
        self.assertTrue(np.allclose(matrix[:, -1], 1.0))

    def test_posterior_draws_are_centred_and_spread(self):
        truth = {team: float(index) for index, team in enumerate(LEAGUE_TEAMS)}
        rows = round_robin(list(LEAGUE_TEAMS), scores=lambda h, a: (80 + truth[h] - truth[a], 80))
        played, _, _ = reconcile_schedule(pd.DataFrame(rows))
        fit = fit_ratings(played, alpha=1.0, half_life_days=0, margin_cap=0)
        ratings, home = sample_ratings(fit, 4000, np.random.default_rng(7))
        self.assertEqual(ratings.shape, (4000, len(LEAGUE_TEAMS)))
        self.assertTrue(np.allclose(ratings.mean(axis=0), fit.ratings, atol=0.5))
        self.assertEqual(len(home), 4000)

    def test_win_probability_is_monotone_and_centred(self):
        probabilities = win_probability(np.array([-10.0, 0.0, 10.0]), 10.0)
        self.assertAlmostEqual(probabilities[1], 0.5, places=6)
        self.assertLess(probabilities[0], probabilities[1])
        self.assertLess(probabilities[1], probabilities[2])

    def test_backtest_reports_both_baselines(self):
        rng = np.random.default_rng(11)
        truth = {team: float(index) - 7 for index, team in enumerate(LEAGUE_TEAMS)}
        rows = []
        for repeat in range(4):
            for i, home in enumerate(LEAGUE_TEAMS):
                for away in LEAGUE_TEAMS[i + 1 :]:
                    margin = truth[home] - truth[away] + 3.0 + rng.normal(0, 8)
                    rows.append(game(f"g{len(rows)}", f"2026-05-{1 + repeat:02d}", home, away, 80 + margin, 80))
        played, _, _ = reconcile_schedule(pd.DataFrame(rows))
        report = backtest(played, alpha=2.0, half_life_days=0, margin_cap=20)
        self.assertEqual(report["status"], "scored")
        # With a real strength signal present, the model must beat "the home team wins".
        self.assertTrue(report["beats_home_field_baseline"])
        self.assertIn("record_baseline_log_loss", report)


class TiebreakTest(unittest.TestCase):
    def _blank(self, wins):
        count = len(wins)
        return {
            "wins": np.array([wins], dtype=float),
            "head_to_head": np.zeros((1, count, count)),
            "conference_wins": np.zeros((1, count)),
            "conference_games": np.zeros((1, count)),
            "point_differential": np.zeros((1, count)),
            "jitter": np.zeros((1, count)),
        }

    def test_wins_decide_when_nothing_is_tied(self):
        state = self._blank([10, 8, 6])
        seeds = rank_teams(**state)
        self.assertEqual(list(seeds[0]), [1, 2, 3])

    def test_head_to_head_breaks_a_two_team_tie(self):
        state = self._blank([10, 10, 6])
        state["head_to_head"][0, 1, 0] = 2.0  # team 1 swept team 0
        seeds = rank_teams(**state)
        self.assertEqual(seeds[0][1], 1)
        self.assertEqual(seeds[0][0], 2)

    def test_conference_record_breaks_a_tie_when_head_to_head_is_level(self):
        state = self._blank([10, 10, 6])
        state["head_to_head"][0, 0, 1] = 1.0
        state["head_to_head"][0, 1, 0] = 1.0
        state["conference_games"][0] = [10, 10, 10]
        state["conference_wins"][0] = [4, 8, 1]
        seeds = rank_teams(**state)
        self.assertEqual(seeds[0][1], 1)

    def test_point_differential_is_the_last_real_rung(self):
        state = self._blank([10, 10, 6])
        state["head_to_head"][0, 0, 1] = 1.0
        state["head_to_head"][0, 1, 0] = 1.0
        state["conference_games"][0] = [10, 10, 10]
        state["conference_wins"][0] = [5, 5, 1]
        state["point_differential"][0] = [10.0, 90.0, 0.0]
        seeds = rank_teams(**state)
        self.assertEqual(seeds[0][1], 1)

    def test_head_to_head_only_counts_games_against_the_tied_teams(self):
        # Team 2 beat team 0 four times but is not tied with anyone, so those wins must
        # not decide the tie between teams 0 and 1.
        state = self._blank([10, 10, 4])
        state["head_to_head"][0, 2, 0] = 4.0
        state["head_to_head"][0, 0, 1] = 3.0
        seeds = rank_teams(**state)
        self.assertEqual(seeds[0][0], 1)

    def test_seeds_are_a_permutation(self):
        rng = np.random.default_rng(3)
        count = len(LEAGUE_TEAMS)
        state = {
            "wins": rng.integers(0, 44, (50, count)).astype(float),
            "head_to_head": rng.integers(0, 3, (50, count, count)).astype(float),
            "conference_wins": rng.integers(0, 16, (50, count)).astype(float),
            "conference_games": np.full((50, count), 16.0),
            "point_differential": rng.normal(0, 50, (50, count)),
            "jitter": rng.random((50, count)),
        }
        seeds = rank_teams(**state)
        for row in seeds:
            self.assertEqual(sorted(row), list(range(1, count + 1)))


class SeriesTest(unittest.TestCase):
    def test_a_coin_flip_series_is_a_coin_flip(self):
        probability = series_win_probability(np.full((1, 3), 0.5))
        self.assertAlmostEqual(float(probability[0]), 0.5, places=9)

    def test_certain_wins_take_the_series(self):
        self.assertAlmostEqual(float(series_win_probability(np.full((1, 5), 1.0))[0]), 1.0, places=9)
        self.assertAlmostEqual(float(series_win_probability(np.full((1, 7), 0.0))[0]), 0.0, places=9)

    def test_best_of_three_matches_the_closed_form(self):
        p = np.array([[0.7, 0.4, 0.6]])
        expected = 0.7 * 0.4 + 0.7 * 0.6 * 0.6 + 0.3 * 0.4 * 0.6
        self.assertAlmostEqual(float(series_win_probability(p)[0]), expected, places=9)

    def test_longer_series_favour_the_better_team(self):
        short = float(series_win_probability(np.full((1, 3), 0.6))[0])
        long = float(series_win_probability(np.full((1, 7), 0.6))[0])
        self.assertGreater(long, short)


class SimulationTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(5)
        truth = {team: float(index) - 7 for index, team in enumerate(LEAGUE_TEAMS)}
        rows = []
        for repeat in range(2):
            for i, home in enumerate(LEAGUE_TEAMS):
                for away in LEAGUE_TEAMS[i + 1 :]:
                    margin = truth[home] - truth[away] + 2.0 + rng.normal(0, 10)
                    rows.append(game(f"p{len(rows)}", f"2026-05-{1 + repeat:02d}", home, away, 80 + margin, 80))
        upcoming = [
            game(f"u{index}", "2026-09-01", home, away, status="STATUS_SCHEDULED", completed=False)
            for index, (home, away) in enumerate(zip(LEAGUE_TEAMS, LEAGUE_TEAMS[1:] + LEAGUE_TEAMS[:1]))
        ]
        self.played, self.remaining, _ = reconcile_schedule(pd.DataFrame(rows + upcoming))
        self.results = long_results(self.played)
        self.standings = current_standings(self.results, self.remaining)
        self.fit = fit_ratings(self.played, alpha=2.0, half_life_days=0, margin_cap=20)
        self.simulation = simulate_remaining(
            self.results, self.remaining, self.fit, simulations=2000, seed=99
        )

    def test_eight_teams_make_the_playoffs_in_every_run(self):
        self.assertTrue(np.all(self.simulation.made_playoffs().sum(axis=1) == 8))

    def test_exactly_one_champion_per_run(self):
        self.assertTrue(np.all((self.simulation.finish == 4).sum(axis=1) == 1))

    def test_probabilities_sum_to_the_field_and_the_trophy(self):
        odds = summarize(self.simulation, self.standings)
        self.assertAlmostEqual(float(odds["p_playoffs"].sum()), 8.0, places=2)
        self.assertAlmostEqual(float(odds["p_title"].sum()), 1.0, places=2)

    def test_every_team_gains_exactly_its_remaining_games(self):
        state = season_state(self.results)
        played_wins = state["wins"]
        extra = self.simulation.wins - played_wins[None, :]
        remaining_counts = np.array(
            [
                int((self.remaining["home_team"] == team).sum() + (self.remaining["away_team"] == team).sum())
                for team in self.simulation.teams
            ]
        )
        self.assertTrue(np.all(extra >= 0))
        self.assertTrue(np.all(extra <= remaining_counts[None, :]))

    def test_leverage_covers_both_sides_of_every_game(self):
        leverage = game_leverage(self.simulation)
        self.assertEqual(len(leverage), 2 * len(self.remaining))
        self.assertEqual(set(leverage["is_home"]), {True, False})

    def test_winning_never_hurts_a_team_and_sometimes_matters(self):
        leverage = game_leverage(self.simulation)
        signed = leverage["playoff_leverage"].dropna()
        # Winning a game cannot lower a team's own playoff odds; the small tolerance is
        # Monte Carlo noise, not a modelled effect.
        self.assertGreater(float(signed.min()), -0.02)
        self.assertGreater(float(signed.max()), 0.05)

    def test_head_to_head_state_matches_the_game_log(self):
        state = season_state(self.results)
        matrix = head_to_head(self.results)
        self.assertTrue(np.allclose(state["head_to_head"], matrix.loc[list(LEAGUE_TEAMS), list(LEAGUE_TEAMS)].to_numpy()))


class ClinchTest(unittest.TestCase):
    def _standings(self, records):
        rows = []
        for index, (team, wins, remaining) in enumerate(records):
            rows.append(
                {
                    "team_abbreviation": team,
                    "current_seed": index + 1,
                    "wins": wins,
                    "losses": 44 - remaining - wins,
                    "games_remaining": remaining,
                    "max_possible_wins": wins + remaining,
                    "point_differential": 0,
                }
            )
        return pd.DataFrame(rows)

    def test_a_team_nobody_can_reach_has_clinched(self):
        records = [("AAA", 40, 0)] + [(f"T{i}", 5, 4) for i in range(14)]
        flags = clinch_flags(self._standings(records)).set_index("team_abbreviation")
        self.assertTrue(flags.loc["AAA", "clinched_playoffs"])
        self.assertFalse(flags.loc["AAA", "eliminated"])

    def test_a_team_that_cannot_catch_eight_others_is_eliminated(self):
        records = [(f"T{i}", 30, 0) for i in range(8)] + [(f"B{i}", 2, 1) for i in range(7)]
        flags = clinch_flags(self._standings(records)).set_index("team_abbreviation")
        self.assertTrue(flags.loc["B0", "eliminated"])
        self.assertFalse(flags.loc["T0", "eliminated"])

    def test_nothing_is_clinched_when_everything_is_still_open(self):
        records = [(f"T{i}", 10, 20) for i in range(15)]
        flags = clinch_flags(self._standings(records))
        self.assertFalse(flags["clinched_playoffs"].any())
        self.assertFalse(flags["eliminated"].any())

    def test_magic_number_counts_against_the_first_team_out(self):
        records = [(f"T{i}", 30 - i, 5) for i in range(15)]
        numbers = magic_numbers(self._standings(records)).set_index("team_abbreviation")
        self.assertEqual(numbers.loc["T0", "reference_team"], "T8")
        # T8 can reach 27 wins; T0 has 30 and has already clinched against it.
        self.assertEqual(int(numbers.loc["T0", "magic_number"]), 0)
        self.assertTrue(pd.isna(numbers.loc["T0", "tragic_number"]))


class ReadinessMetricTest(unittest.TestCase):
    def test_quality_gap_is_residual_not_schedule(self):
        """The naive version is negative for all fifteen teams; this one is not."""
        rng = np.random.default_rng(13)
        truth = {team: float(index) - 7 for index, team in enumerate(LEAGUE_TEAMS)}
        rows = []
        for repeat in range(2):
            for i, home in enumerate(LEAGUE_TEAMS):
                for away in LEAGUE_TEAMS[i + 1 :]:
                    margin = truth[home] - truth[away] + 2.0 + rng.normal(0, 9)
                    rows.append(game(f"g{len(rows)}", f"2026-05-{1 + repeat:02d}", home, away, 80 + margin, 80))
        played, _, _ = reconcile_schedule(pd.DataFrame(rows))
        results = long_results(played)
        fit = fit_ratings(played, alpha=2.0, half_life_days=0, margin_cap=20)
        ratings = fit.rating_series()
        expected = pd.Series(
            results["team"].map(ratings).to_numpy()
            - results["opponent"].map(ratings).to_numpy()
            + np.where(results["is_home"], fit.home_advantage, -fit.home_advantage),
            index=results.index,
        )
        field = list(LEAGUE_TEAMS[-8:])
        metrics = result_metrics(results, field, expected_margin=expected)
        gaps = metrics["quality_gap"].dropna()
        self.assertGreater(len(gaps), 10)
        self.assertTrue((gaps > 0).any() and (gaps < 0).any())
        self.assertLess(abs(float(gaps.mean())), 2.0)

    def test_style_split_separates_set_from_early_possessions(self):
        rows = []
        for index in range(40):
            is_set = index % 2 == 0
            rows.append(
                {
                    "game_id": "g1",
                    "offense_team_id": 10,
                    "defense_team_id": 20,
                    "possession_start_type": "OffMadeShot" if is_set else "OffLiveBallTurnover",
                    "points": 2 if is_set else 0,
                    "count_as_possession": True,
                }
            )
        logs = pd.DataFrame(
            [
                {"team_id": 10, "team_abbreviation": "MIN", "game_id": "g1", "game_date": "2026-07-01"},
                {"team_id": 20, "team_abbreviation": "NYL", "game_id": "g1", "game_date": "2026-07-01"},
            ]
        )
        style = style_metrics(pd.DataFrame(rows), logs).set_index("team_abbreviation")
        self.assertAlmostEqual(style.loc["MIN", "set_off_rating"], 200.0, places=6)
        self.assertAlmostEqual(style.loc["MIN", "early_off_rating"], 0.0, places=6)
        self.assertAlmostEqual(style.loc["MIN", "set_possession_share"], 0.5, places=6)
        # The same possessions are the defence's, seen from the other side.
        self.assertAlmostEqual(style.loc["NYL", "set_def_rating"], 200.0, places=6)

    def test_uncounted_possessions_are_ignored(self):
        rows = [
            {"game_id": "g1", "offense_team_id": 10, "defense_team_id": 20, "possession_start_type": "OffMadeShot", "points": 2, "count_as_possession": True},
            {"game_id": "g1", "offense_team_id": 10, "defense_team_id": 20, "possession_start_type": "OffMadeShot", "points": 99, "count_as_possession": False},
        ]
        logs = pd.DataFrame([{"team_id": 10, "team_abbreviation": "MIN"}, {"team_id": 20, "team_abbreviation": "NYL"}])
        style = style_metrics(pd.DataFrame(rows), logs).set_index("team_abbreviation")
        self.assertAlmostEqual(style.loc["MIN", "set_off_rating"], 200.0, places=6)

    def test_clutch_is_shrunk_toward_zero_by_sample(self):
        board = pd.DataFrame(
            {
                "clutch_net_rating": [40.0, 40.0],
                "clutch_off_poss": [50, 5000],
                "clutch_def_poss": [50, 5000],
            }
        )
        shrunk = _shrink_clutch(board)["clutch_net_rating_shrunk"]
        self.assertLess(shrunk[0], 15.0)
        self.assertGreater(shrunk[1], 35.0)
        self.assertLess(shrunk[0], shrunk[1])

    def test_rotation_concentration_reads_the_recent_window(self):
        rows = []
        for game_index in range(12):
            # The first two games use an eleven-player rotation; the last ten use seven.
            players = range(1, 12) if game_index < 2 else range(1, 8)
            for player in players:
                rows.append(
                    {
                        "game_id": f"g{game_index}",
                        "game_date": f"2026-07-{game_index + 1:02d}",
                        "team_abbreviation": "MIN",
                        "athlete_id": player,
                        "minutes": 200 / len(list(players)),
                    }
                )
        rotation = rotation_metrics(pd.DataFrame(rows), recent_games=10).set_index("team_abbreviation")
        self.assertAlmostEqual(rotation.loc["MIN", "rotation_concentration"], 1.0, places=6)
        self.assertEqual(int(rotation.loc["MIN", "rotation_games"]), 10)

    def test_missing_optional_inputs_return_empty_frames_with_columns(self):
        self.assertIn("set_net_rating", style_metrics(pd.DataFrame(), pd.DataFrame()).columns)
        self.assertIn("rotation_concentration", rotation_metrics(pd.DataFrame()).columns)


class BuilderEndToEndTest(unittest.TestCase):
    def test_cli_writes_every_output_with_coverage_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            sports = tmpdir / "sportsdataverse"
            sports.mkdir(parents=True)

            rng = np.random.default_rng(17)
            truth = {team: float(index) - 7 for index, team in enumerate(LEAGUE_TEAMS)}
            rows = []
            for repeat in range(2):
                for i, home in enumerate(LEAGUE_TEAMS):
                    for away in LEAGUE_TEAMS[i + 1 :]:
                        margin = truth[home] - truth[away] + 2.0 + rng.normal(0, 10)
                        rows.append(
                            game(f"p{len(rows)}", f"2026-05-{1 + repeat:02d}", home, away, 80 + margin, 80)
                        )
            rows.extend(
                game(f"u{index}", "2026-09-01", home, away, status="STATUS_SCHEDULED", completed=False)
                for index, (home, away) in enumerate(zip(LEAGUE_TEAMS, LEAGUE_TEAMS[1:] + LEAGUE_TEAMS[:1]))
            )
            pd.DataFrame(rows).to_parquet(sports / "schedule_2026.parquet")

            possessions, logs, boxes = [], [], []
            for index, team in enumerate(LEAGUE_TEAMS):
                logs.append(
                    {
                        "team_id": 100 + index,
                        "team_abbreviation": team,
                        "game_id": f"s{index}",
                        "game_date": "2026-05-02",
                    }
                )
                for possession in range(20):
                    possessions.append(
                        {
                            "game_id": f"s{index}",
                            "offense_team_id": 100 + index,
                            "defense_team_id": 100 + ((index + 1) % len(LEAGUE_TEAMS)),
                            "possession_start_type": "OffMadeShot" if possession % 2 else "OffMissedShot",
                            "points": 2,
                            "count_as_possession": True,
                        }
                    )
                for player in range(9):
                    boxes.append(
                        {
                            "game_id": f"s{index}",
                            "game_date": "2026-05-02",
                            "team_abbreviation": team,
                            "athlete_id": index * 100 + player,
                            "minutes": 25.0 if player < 7 else 10.0,
                        }
                    )
            pd.DataFrame(possessions).to_parquet(sports / "wnba_possessions_2026.parquet")
            pd.DataFrame(logs).to_parquet(sports / "player_game_logs_2026.parquet")
            pd.DataFrame(boxes).to_parquet(sports / "player_box_2026.parquet")

            config = {
                "season": 2026,
                "sportsdataverse_data_root": str(sports),
                "possession_impact_root": str(tmpdir / "absent"),
                "team_identity_shift_root": str(tmpdir / "absent"),
                "output_root": str(tmpdir / "analysis"),
                "ratings": {"alpha_grid": [1, 4], "cv_folds": 3, "random_seed": 1, "half_life_days": 0, "margin_cap": 20},
                "simulation": {"simulations": 500, "random_seed": 2},
                "playoffs": {"playoff_teams": 8},
                "readiness": {"top_seed_threshold": 0.25, "contention_floor": 0.005, "recent_games": 10},
            }
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_playoff_readiness.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            processed = tmpdir / "analysis" / "data" / "processed"
            odds = pd.read_csv(processed / "playoff_odds_2026.csv")
            readiness = pd.read_csv(processed / "playoff_readiness_2026.csv")
            seeds = pd.read_csv(processed / "playoff_seed_probabilities_2026.csv")
            leverage = pd.read_csv(processed / "remaining_game_leverage_2026.csv")
            manifest = json.loads((processed / "run_manifest_2026.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["analysis_stats"]["status"], "ok")
            self.assertTrue(manifest["analysis_stats"]["schedule"]["reconciled"])
            self.assertAlmostEqual(manifest["analysis_stats"]["simulation"]["playoff_probability_sum"], 8.0, places=1)
            self.assertAlmostEqual(manifest["analysis_stats"]["simulation"]["title_probability_sum"], 1.0, places=2)
            self.assertEqual(len(odds), len(LEAGUE_TEAMS))
            self.assertEqual(len(seeds), len(LEAGUE_TEAMS) ** 2)
            self.assertEqual(len(leverage), 2 * len(LEAGUE_TEAMS))
            # Both clocks travel with the file, because they are different clocks.
            self.assertIn("results_coverage_through", readiness.columns)
            self.assertIn("possession_coverage_through", readiness.columns)
            self.assertEqual(set(odds["coverage_through"]), {"2026-05-02"})
            # The possession-impact build did not run, and the board still exists.
            self.assertNotIn("bench_dropoff", readiness.columns)
            self.assertIn("set_net_rating", readiness.columns)

    def test_an_unreconciled_schedule_stops_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            sports = tmpdir / "sportsdataverse"
            sports.mkdir(parents=True)
            rows = round_robin(list(LEAGUE_TEAMS))
            rows.append(game("extra", "2026-06-01", "MIN", "NYL", 90, 80))
            pd.DataFrame(rows).to_parquet(sports / "schedule_2026.parquet")

            config = {
                "sportsdataverse_data_root": str(sports),
                "possession_impact_root": str(tmpdir / "absent"),
                "team_identity_shift_root": str(tmpdir / "absent"),
                "output_root": str(tmpdir / "analysis"),
                "simulation": {"simulations": 100, "random_seed": 1},
            }
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_playoff_readiness.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not reconcile", result.stderr)


if __name__ == "__main__":
    unittest.main()
