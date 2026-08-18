import sys
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from standings_playoff_forecast.clinching import (  # noqa: E402
    CLINCH_COLUMNS,
    STATUS_CLINCHED,
    STATUS_ELIMINATED,
    STATUS_IN_CONTENTION,
    attach_clinch_status,
    verify_against_simulation,
)
from standings_playoff_forecast.config import load_season_config  # noqa: E402


def _config(*, team_count: int, qualifiers: int, games_per_team: int = 44):
    return replace(
        load_season_config(2026),
        team_count=team_count,
        playoff_qualifiers=qualifiers,
        regular_season_games_per_team=games_per_team,
    )


def _standings(records):
    """``records`` is an iterable of ``(team_id, wins)``."""
    return pd.DataFrame(
        [
            {"team_id": team_id, "wins": wins, "current_rank": index + 1}
            for index, (team_id, wins) in enumerate(records)
        ]
    )


def _counts(records):
    """``records`` is an iterable of ``(team_id, remaining_games)``."""
    return pd.DataFrame(
        [{"team_id": team_id, "remaining_games": remaining} for team_id, remaining in records]
    )


class ClinchStatusTest(unittest.TestCase):
    def test_nothing_is_settled_while_everything_is_open(self):
        cfg = _config(team_count=15, qualifiers=8)
        standings = _standings((f"T{index}", 10) for index in range(15))
        counts = _counts((f"T{index}", 20) for index in range(15))
        result = attach_clinch_status(standings, counts, cfg)
        self.assertFalse(result["clinched_playoffs"].any())
        self.assertFalse(result["eliminated_from_playoffs"].any())
        self.assertEqual(set(result["status_note"]), {STATUS_IN_CONTENTION})

    def test_a_team_nobody_can_reach_has_clinched(self):
        cfg = _config(team_count=15, qualifiers=8)
        standings = _standings([("AAA", 40)] + [(f"T{index}", 5) for index in range(14)])
        counts = _counts([("AAA", 0)] + [(f"T{index}", 4) for index in range(14)])
        result = attach_clinch_status(standings, counts, cfg).set_index("team_id")
        self.assertTrue(result.loc["AAA", "clinched_playoffs"])
        self.assertFalse(result.loc["AAA", "eliminated_from_playoffs"])
        self.assertEqual(result.loc["AAA", "status_note"], STATUS_CLINCHED)

    def test_a_team_that_cannot_catch_eight_others_is_eliminated(self):
        cfg = _config(team_count=15, qualifiers=8)
        standings = _standings(
            [(f"T{index}", 30) for index in range(8)] + [(f"B{index}", 2) for index in range(7)]
        )
        counts = _counts(
            [(f"T{index}", 0) for index in range(8)] + [(f"B{index}", 1) for index in range(7)]
        )
        result = attach_clinch_status(standings, counts, cfg).set_index("team_id")
        self.assertTrue(result.loc["B0", "eliminated_from_playoffs"])
        self.assertEqual(result.loc["B0", "status_note"], STATUS_ELIMINATED)
        self.assertFalse(result.loc["T0", "eliminated_from_playoffs"])

    def test_elimination_turns_on_exactly_at_the_qualifier_count(self):
        """Seven teams guaranteed ahead is survivable; the eighth ends it."""
        cfg = _config(team_count=15, qualifiers=8)
        for ahead, expected in ((7, False), (8, True)):
            with self.subTest(guaranteed_ahead=ahead):
                # The target can reach 10; `ahead` teams already have 11.
                records = [("TARGET", 5)]
                records += [(f"A{index}", 11) for index in range(ahead)]
                records += [(f"C{index}", 0) for index in range(14 - ahead)]
                standings = _standings(records)
                counts = _counts(
                    [("TARGET", 5)]
                    + [(f"A{index}", 0) for index in range(ahead)]
                    + [(f"C{index}", 0) for index in range(14 - ahead)]
                )
                result = attach_clinch_status(standings, counts, cfg).set_index("team_id")
                self.assertEqual(bool(result.loc["TARGET", "eliminated_from_playoffs"]), expected)

    def test_clinching_turns_on_exactly_below_the_qualifier_count(self):
        """Eight live rivals is not enough; seven is."""
        cfg = _config(team_count=15, qualifiers=8)
        for rivals, expected in ((8, False), (7, True)):
            with self.subTest(rivals=rivals):
                # The target sits on 20; `rivals` teams can still reach it, the rest cannot.
                records = [("TARGET", 20)]
                records += [(f"R{index}", 18) for index in range(rivals)]
                records += [(f"D{index}", 1) for index in range(14 - rivals)]
                standings = _standings(records)
                counts = _counts(
                    [("TARGET", 0)]
                    + [(f"R{index}", 5) for index in range(rivals)]
                    + [(f"D{index}", 0) for index in range(14 - rivals)]
                )
                result = attach_clinch_status(standings, counts, cfg).set_index("team_id")
                self.assertEqual(bool(result.loc["TARGET", "clinched_playoffs"]), expected)

    def test_a_rival_that_can_only_tie_still_counts_against_a_clinch(self):
        """A tie can fall either way, so reaching the total is enough to threaten."""
        cfg = _config(team_count=3, qualifiers=1)
        standings = _standings([("TARGET", 10), ("TIE", 8), ("LOW", 0)])
        counts = _counts([("TARGET", 0), ("TIE", 2), ("LOW", 0)])
        result = attach_clinch_status(standings, counts, cfg).set_index("team_id")
        self.assertFalse(result.loc["TARGET", "clinched_playoffs"])

        # One win fewer available and the rival can no longer reach the mark.
        result = attach_clinch_status(
            standings, _counts([("TARGET", 0), ("TIE", 1), ("LOW", 0)]), cfg
        ).set_index("team_id")
        self.assertTrue(result.loc["TARGET", "clinched_playoffs"])

    def test_a_team_that_can_still_draw_level_is_not_eliminated(self):
        """The mirror of the clinch case: reaching a rival's total keeps a team alive.

        TARGET tops out on exactly the rival's win total, so the two would finish tied and
        a tiebreak could fall either way. Treating "can only tie" as "finishes behind"
        would eliminate a team that is still playing for it.
        """
        cfg = _config(team_count=3, qualifiers=1)
        standings = _standings([("RIVAL", 10), ("TARGET", 5), ("LOW", 0)])
        counts = _counts([("RIVAL", 0), ("TARGET", 5), ("LOW", 0)])
        result = attach_clinch_status(standings, counts, cfg).set_index("team_id")
        self.assertFalse(result.loc["TARGET", "eliminated_from_playoffs"])
        # RIVAL cannot clinch either, for the same reason from the other side.
        self.assertFalse(result.loc["RIVAL", "clinched_playoffs"])

        # One win fewer available and TARGET can no longer draw level.
        result = attach_clinch_status(
            standings, _counts([("RIVAL", 0), ("TARGET", 4), ("LOW", 0)]), cfg
        ).set_index("team_id")
        self.assertTrue(result.loc["TARGET", "eliminated_from_playoffs"])
        self.assertTrue(result.loc["RIVAL", "clinched_playoffs"])

    def test_a_finished_season_settles_every_team(self):
        cfg = _config(team_count=15, qualifiers=8, games_per_team=44)
        standings = _standings((f"T{index}", 40 - index * 2) for index in range(15))
        counts = _counts((f"T{index}", 0) for index in range(15))
        result = attach_clinch_status(standings, counts, cfg)
        self.assertEqual(int(result["clinched_playoffs"].sum()), 8)
        self.assertEqual(int(result["eliminated_from_playoffs"].sum()), 7)
        self.assertNotIn(STATUS_IN_CONTENTION, set(result["status_note"]))

    def test_a_team_absent_from_the_schedule_counts_has_no_games_left(self):
        cfg = _config(team_count=3, qualifiers=1)
        standings = _standings([("TARGET", 10), ("GONE", 8), ("LOW", 0)])
        # "GONE" has finished its season, so the validator emitted no row for it.
        result = attach_clinch_status(
            standings, _counts([("TARGET", 0), ("LOW", 0)]), cfg
        ).set_index("team_id")
        self.assertTrue(result.loc["TARGET", "clinched_playoffs"])
        self.assertTrue(result.loc["GONE", "eliminated_from_playoffs"])

    def test_status_note_never_contradicts_its_flag(self):
        """The markdown renderer rejects proof language without proof; honour that."""
        cfg = _config(team_count=15, qualifiers=8)
        standings = _standings((f"T{index}", 40 - index * 2) for index in range(15))
        result = attach_clinch_status(standings, _counts((f"T{index}", 0) for index in range(15)), cfg)
        for _, row in result.iterrows():
            note = str(row["status_note"]).lower()
            self.assertNotEqual(note, "not_evaluated")
            if row["clinched_playoffs"]:
                self.assertNotIn("eliminat", note)
            if row["eliminated_from_playoffs"]:
                self.assertNotIn("clinch", note)
            if not row["clinched_playoffs"] and not row["eliminated_from_playoffs"]:
                self.assertNotIn("clinch", note)
                self.assertNotIn("eliminat", note)

    def test_existing_columns_and_row_order_are_preserved(self):
        cfg = _config(team_count=3, qualifiers=1)
        standings = _standings([("B", 10), ("A", 8), ("C", 0)])
        result = attach_clinch_status(standings, _counts([("B", 0), ("A", 0), ("C", 0)]), cfg)
        self.assertEqual(result["team_id"].tolist(), ["B", "A", "C"])
        self.assertEqual(result["current_rank"].tolist(), [1, 2, 3])
        self.assertEqual(
            list(result.columns)[: len(standings.columns)], list(standings.columns)
        )


class ClinchInputValidationTest(unittest.TestCase):
    def setUp(self):
        self.cfg = _config(team_count=3, qualifiers=1)
        self.counts = _counts([("A", 1), ("B", 1), ("C", 1)])

    def test_missing_columns_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            attach_clinch_status(pd.DataFrame({"team_id": ["A"]}), self.counts, self.cfg)
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            attach_clinch_status(
                _standings([("A", 1), ("B", 1), ("C", 1)]),
                pd.DataFrame({"team_id": ["A"]}),
                self.cfg,
            )

    def test_wrong_team_count_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "team universe failed"):
            attach_clinch_status(_standings([("A", 1), ("B", 1)]), self.counts, self.cfg)

    def test_duplicate_team_ids_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid team universe"):
            attach_clinch_status(
                _standings([("A", 1), ("A", 2), ("C", 1)]), self.counts, self.cfg
            )

    def test_invalid_wins_fail_closed(self):
        cases = {
            "boolean": [True, False, False],
            "negative": [-1, 1, 1],
            "fractional": [1.5, 1, 1],
            "beyond the season": [99, 1, 1],
            "missing": [None, 1, 1],
        }
        for label, wins in cases.items():
            with self.subTest(case=label):
                standings = pd.DataFrame({"team_id": ["A", "B", "C"], "wins": wins})
                with self.assertRaisesRegex(ValueError, "invalid wins"):
                    attach_clinch_status(standings, self.counts, self.cfg)

    def test_invalid_remaining_games_fail_closed(self):
        standings = _standings([("A", 1), ("B", 1), ("C", 1)])
        for label, remaining in {"negative": [-1, 1, 1], "fractional": [0.5, 1, 1]}.items():
            with self.subTest(case=label):
                counts = pd.DataFrame({"team_id": ["A", "B", "C"], "remaining_games": remaining})
                with self.assertRaisesRegex(ValueError, "invalid remaining_games"):
                    attach_clinch_status(standings, counts, self.cfg)

    def test_unknown_team_in_schedule_counts_fails_closed(self):
        standings = _standings([("A", 1), ("B", 1), ("C", 1)])
        counts = _counts([("A", 1), ("B", 1), ("C", 1), ("Z", 1)])
        with self.assertRaisesRegex(ValueError, "unknown team IDs"):
            attach_clinch_status(standings, counts, self.cfg)

    def test_impossible_qualifier_count_fails_closed(self):
        standings = _standings([("A", 1), ("B", 1), ("C", 1)])
        for qualifiers in (0, 4):
            with self.subTest(qualifiers=qualifiers):
                cfg = _config(team_count=3, qualifiers=qualifiers)
                with self.assertRaisesRegex(ValueError, "playoff_qualifiers must fall"):
                    attach_clinch_status(standings, self.counts, cfg)


class SimulationAgreementTest(unittest.TestCase):
    def _standings_with_flags(self, rows):
        return pd.DataFrame(
            [
                {
                    "team_id": team_id,
                    "clinched_playoffs": clinched,
                    "eliminated_from_playoffs": eliminated,
                    "status_note": STATUS_IN_CONTENTION,
                }
                for team_id, clinched, eliminated in rows
            ]
        )

    def _summary(self, probabilities):
        return pd.DataFrame(
            [
                {"team_id": team_id, "playoff_probability": probability}
                for team_id, probability in probabilities
            ]
        )

    def test_consistent_proofs_and_probabilities_pass(self):
        standings = self._standings_with_flags(
            [("A", True, False), ("B", False, False), ("C", False, True)]
        )
        summary = self._summary([("A", 1.0), ("B", 0.4), ("C", 0.0)])
        verify_against_simulation(standings, summary)

    def test_an_eliminated_team_with_a_live_probability_stops_the_build(self):
        standings = self._standings_with_flags([("A", False, True), ("B", False, False)])
        summary = self._summary([("A", 0.01), ("B", 0.99)])
        with self.assertRaisesRegex(ValueError, "proved eliminated"):
            verify_against_simulation(standings, summary)

    def test_a_clinched_team_below_certainty_stops_the_build(self):
        standings = self._standings_with_flags([("A", True, False), ("B", False, False)])
        summary = self._summary([("A", 0.9999), ("B", 0.0001)])
        with self.assertRaisesRegex(ValueError, "proved clinched"):
            verify_against_simulation(standings, summary)

    def test_a_zero_probability_without_a_proof_is_allowed(self):
        """The bound is conservative, so simulated 0.0000 need not mean eliminated."""
        standings = self._standings_with_flags([("A", False, False), ("B", False, False)])
        summary = self._summary([("A", 0.0), ("B", 1.0)])
        verify_against_simulation(standings, summary)

    def test_a_summary_without_probabilities_is_skipped(self):
        """Nothing to contradict; `_validate_probability_outputs` rejects it later."""
        standings = self._standings_with_flags([("A", False, True)])
        verify_against_simulation(standings, pd.DataFrame({"team_id": ["A"]}))

    def test_standings_without_proofs_are_skipped(self):
        verify_against_simulation(
            pd.DataFrame({"team_id": ["A"]}), self._summary([("A", 0.5)])
        )


class RendererContractTest(unittest.TestCase):
    """The notes are read by the renderers, so pin the round trip rather than assume it.

    `render_markdown` rejects proof language on a row that carries no proof and treats
    `not_evaluated` as "nothing to say", so a note that disagrees with its flag is not a
    cosmetic problem -- it stops the brief from building.
    """

    def _labels(self):
        from standings_playoff_forecast.render_markdown import _status

        cfg = _config(team_count=15, qualifiers=8)
        standings = _standings((f"T{index}", 40 - index * 2) for index in range(15))
        counts = _counts((f"T{index}", 0) for index in range(15))
        settled = attach_clinch_status(standings, counts, cfg)

        open_cfg = _config(team_count=15, qualifiers=8)
        open_standings = _standings((f"T{index}", 10) for index in range(15))
        open_counts = _counts((f"T{index}", 20) for index in range(15))
        contested = attach_clinch_status(open_standings, open_counts, open_cfg)
        return _status, settled, contested

    def test_each_status_renders_the_intended_label(self):
        _status, settled, contested = self._labels()
        clinched = settled[settled["clinched_playoffs"]].iloc[0]
        eliminated = settled[settled["eliminated_from_playoffs"]].iloc[0]
        self.assertEqual(_status(clinched), "Mathematically clinched")
        self.assertEqual(_status(eliminated), "Mathematically eliminated")
        self.assertEqual(_status(contested.iloc[0]), "In contention")

    def test_the_renderer_validator_accepts_every_status_this_module_emits(self):
        from standings_playoff_forecast.render_markdown import _validate_status_proof

        _status, settled, contested = self._labels()
        for label, frame in (("settled", settled), ("contested", contested)):
            with self.subTest(case=label):
                forecast = frame.loc[
                    :, ["team_id", *CLINCH_COLUMNS]
                ].copy()
                _validate_status_proof(forecast)


if __name__ == "__main__":
    unittest.main()
