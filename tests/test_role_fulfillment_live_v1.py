import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from role_fulfillment_matrix.contracts import (  # noqa: E402
    authorize_execution,
    validate_role_definitions,
)
from role_fulfillment_matrix.scoring import fulfillment  # noqa: E402
from role_fulfillment_matrix.pipeline import build_analysis  # noqa: E402
from role_fulfillment_matrix.data_sources import load_config  # noqa: E402
from role_fulfillment_matrix.validation import (  # noqa: E402
    build_hand_validation,
    build_sensitivity_summary,
    render_validation_report,
    threshold_sensitivity,
)


ROLE_PATH = ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "role_definitions_live_v1.json"
LIVE_CONFIG = ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.template.json"
FIXTURE_CONFIG = ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "fixture_config.json"
INPUTS = ROOT / "tests" / "fixtures" / "role_fulfillment_matrix" / "live_v1_11_player_inputs.csv"
EXPECTED = ROOT / "tests" / "fixtures" / "role_fulfillment_matrix" / "live_v1_11_player_expected.csv"


class LiveV1FormulaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roles = json.loads(ROLE_PATH.read_text())
        cls.inputs = pd.read_csv(INPUTS, dtype={"player_id": str})
        cls.expected = pd.read_csv(EXPECTED)

    def test_registry_contains_the_reviewed_six_role_taxonomy(self):
        self.assertEqual(
            set(self.roles),
            {
                "lead_creator",
                "secondary_creator_connector",
                "perimeter_scorer_spacer",
                "downhill_pressure_wing",
                "interior_finisher_rim_runner",
                "interior_hub_rebounder",
            },
        )
        validate_role_definitions(self.roles)

    def test_production_scores_match_the_locked_hand_calculations(self):
        expected = self.expected.set_index("player_name")
        for row in self.inputs.to_dict("records"):
            score, detail = fulfillment(pd.Series(row), self.roles[row["role_code"]])
            with self.subTest(player=row["player_name"]):
                self.assertAlmostEqual(score, expected.loc[row["player_name"], "expected_fulfillment_score"], places=5)
                component_columns = [f"component_{index}" for index in range(1, len(detail) + 1)]
                for item, column in zip(detail, component_columns):
                    self.assertAlmostEqual(item["component_score"], expected.loc[row["player_name"], column], places=5)

    def test_role_denominator_failure_suppresses_fulfillment(self):
        row = self.inputs[self.inputs["player_name"] == "Madina Okot"].iloc[0].copy()
        row["recent_at_rim_fga"] = 7
        score, detail = fulfillment(row, self.roles[row["role_code"]])
        rim_accuracy = next(item for item in detail if item["code"] == "rim_fg_pct")
        self.assertTrue(pd.isna(score))
        self.assertFalse(rim_accuracy["denominator_met"])
        self.assertEqual(rim_accuracy["minimum_denominator"], 8)

    def test_missing_role_denominator_suppresses_instead_of_raising(self):
        row = self.inputs[self.inputs["player_name"] == "Madina Okot"].iloc[0].copy()
        row["recent_at_rim_fga"] = pd.NA
        score, detail = fulfillment(row, self.roles[row["role_code"]])
        rim_accuracy = next(item for item in detail if item["code"] == "rim_fg_pct")
        self.assertTrue(pd.isna(score))
        self.assertFalse(rim_accuracy["denominator_met"])

    def test_sensitivity_keeps_base_case_equal_to_hand_calculations(self):
        sensitivity = threshold_sensitivity(self.inputs, self.roles, shift_fraction=0.10)
        self.assertEqual(len(sensitivity), 33)
        base = sensitivity[sensitivity["scenario"] == "base"].set_index("player_name")
        expected = self.expected.set_index("player_name")
        for player_name in expected.index:
            with self.subTest(player=player_name):
                self.assertAlmostEqual(
                    base.loc[player_name, "fulfillment_score"],
                    expected.loc[player_name, "expected_fulfillment_score"],
                    places=5,
                )

    def test_validation_report_carries_results_and_keeps_review_pending(self):
        hand = build_hand_validation(self.inputs, self.expected, self.roles)
        sensitivity = build_sensitivity_summary(
            threshold_sensitivity(self.inputs, self.roles, shift_fraction=0.10)
        )
        report = render_validation_report(hand, sensitivity)
        self.assertEqual(len(hand), 11)
        self.assertTrue(hand["calculation_match"].all())
        self.assertLessEqual(sensitivity["max_abs_delta"].max(), 10.000001)
        self.assertIn("11 of 11 production scores match", report)
        self.assertIn("Review status: **pending reviewer approval**", report)
        self.assertIn("Live output remains disabled", report)

    def test_validation_builder_writes_the_three_review_artifacts(self):
        from build_role_fulfillment_live_v1_validation import build

        with tempfile.TemporaryDirectory() as tmp:
            manifest = build(Path(tmp))
            output_names = {path.name for path in Path(tmp).iterdir()}
        self.assertEqual(manifest["hand_calculation_matches"], 11)
        self.assertEqual(manifest["players_validated"], 11)
        self.assertEqual(
            output_names,
            {
                "hand_calculated_11_player_validation.csv",
                "threshold_sensitivity_11_player.csv",
                "role_fulfillment_matrix_live_v1_validation.md",
            },
        )

    def test_live_config_names_v1_and_authorizes_only_the_dry_run(self):
        raw = json.loads(LIVE_CONFIG.read_text())
        self.assertEqual(raw["formula_version"], "rfm-live-v1")
        self.assertEqual(raw["mode"], "live_dry_run")
        self.assertEqual(raw["window_policy"]["recent_days"], 14)
        self.assertEqual(raw["window_policy"]["baseline_days"], 14)
        self.assertEqual(raw["validation_status"], "approved_11_player_review")
        self.assertEqual(raw["live_adapter_status"], "approved_review")
        self.assertFalse(raw["live_output_enabled"])
        authorize_execution(raw)

    def test_fixture_manifest_reports_the_current_validation_blocker(self):
        result = build_analysis(load_config(FIXTURE_CONFIG))
        self.assertEqual(
            result.manifest["live_scoring_blockers"],
            ["deliberate live adapter wiring and end-to-end dry run"],
        )

    def test_assignment_confidence_below_half_suppresses_all_scores(self):
        config = load_config(FIXTURE_CONFIG)
        config["minimums"] = dict(config["minimums"], assignment_confidence_score=0.50)
        assignments = pd.read_csv(ROOT / config["sources"]["role_assignments"])
        assignments.loc[assignments["player_id"] == "FX-001", "assignment_confidence"] = 0.49
        with tempfile.TemporaryDirectory() as tmp:
            assignment_path = Path(tmp) / "assignments.csv"
            assignments.to_csv(assignment_path, index=False)
            config["sources"] = dict(config["sources"], role_assignments=str(assignment_path))
            result = build_analysis(config)
        player = result.scores.set_index("player_id").loc["FX-001"]
        self.assertEqual(player["score_status"], "assignment_confidence_insufficient")
        self.assertTrue(pd.isna(player["fulfillment_score"]))
        self.assertTrue(pd.isna(player["opportunity_score"]))
        self.assertTrue(pd.isna(player["stability_score"]))

    def test_role_denominator_failure_preserves_opportunity_and_stability(self):
        config = load_config(FIXTURE_CONFIG)
        roles = json.loads((ROOT / config["sources"]["role_definitions"]).read_text())
        roles["rim_finisher"]["metrics"][1]["minimum_denominator"] = 8
        with tempfile.TemporaryDirectory() as tmp:
            role_path = Path(tmp) / "roles.json"
            role_path.write_text(json.dumps(roles))
            config["sources"] = dict(config["sources"], role_definitions=str(role_path))
            result = build_analysis(config)
        player = result.scores.set_index("player_id").loc["FX-002"]
        self.assertEqual(player["score_status"], "insufficient_role_evidence")
        self.assertTrue(pd.isna(player["fulfillment_score"]))
        self.assertTrue(pd.notna(player["opportunity_score"]))
        self.assertTrue(pd.notna(player["stability_score"]))


if __name__ == "__main__":
    unittest.main()
