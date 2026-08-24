import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_role_fulfillment_live import build  # noqa: E402
from role_fulfillment_matrix.contracts import authorize_execution  # noqa: E402


LIVE_CONFIG = (
    ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.json"
)
LIVE_OUTPUT_APPROVAL = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "live_output_approval_manifest_2026.json"
)


class LiveEnablementConfigTest(unittest.TestCase):
    def test_live_config_records_manual_approval_and_disables_scheduling(self):
        config = json.loads(LIVE_CONFIG.read_text())

        self.assertEqual(config["mode"], "live")
        self.assertTrue(config["live_output_enabled"])
        self.assertEqual(
            config["end_to_end_review_status"],
            "approved_19_player_review",
        )
        self.assertEqual(config["execution_mode"], "manual_only")
        self.assertFalse(config["scheduling_enabled"])
        self.assertEqual(config["live_output_approved_by"], "Krystal Beasley")
        self.assertEqual(config["live_output_approved_at"], "2026-08-23")
        self.assertEqual(
            config["output_root"],
            "analysis/role_fulfillment_matrix/live",
        )
        authorize_execution(config)

        approval = json.loads(LIVE_OUTPUT_APPROVAL.read_text())
        self.assertEqual(approval["review_status"], "approved")
        self.assertEqual(approval["approved_by"], "Krystal Beasley")
        self.assertEqual(approval["approved_at"], "2026-08-23")
        self.assertEqual(approval["approved_result_counts"], {
            "live_scored": 11,
            "season_context_only": 5,
            "inactive_suppressed": 3,
        })
        self.assertEqual(approval["execution_mode"], "manual_only")
        self.assertFalse(approval["scheduling_enabled"])
        for item in approval["approved_dry_run_artifacts"]:
            path = ROOT / item["path"]
            self.assertEqual(item["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(approval["manual_live_run_status"], "completed")
        self.assertEqual(
            approval["manual_live_run"]["generated_at_utc"],
            "2026-08-23T23:37:49+00:00",
        )
        for item in approval["manual_live_run"]["artifacts"]:
            path = ROOT / item["path"]
            self.assertEqual(item["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_no_github_workflow_schedules_the_role_fulfillment_live_builder(self):
        workflows = ROOT / ".github" / "workflows"
        contents = "\n".join(
            path.read_text(errors="replace") for path in workflows.glob("*.y*ml")
        )
        self.assertNotIn("build_role_fulfillment_live.py", contents)


class ManualLiveOutputTest(unittest.TestCase):
    def test_manual_live_run_writes_isolated_enabled_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "live"
            manifest = build(output_root=output_root)
            scores = pd.read_csv(
                output_root / "data" / "processed" / "role_fulfillment_matrix_2026.csv"
            )
            evidence = json.loads(
                (
                    output_root
                    / "data"
                    / "processed"
                    / "role_fulfillment_evidence_2026.json"
                ).read_text()
            )
            html = (
                output_root
                / "deliverables"
                / "role_fulfillment_matrix"
                / "index.html"
            ).read_text()

        self.assertEqual(manifest["mode"], "live")
        self.assertEqual(manifest["live_scoring_status"], "live_enabled")
        self.assertEqual(manifest["live_scoring_blockers"], [])
        self.assertTrue(manifest["live_output_enabled"])
        self.assertEqual(manifest["execution_mode"], "manual_only")
        self.assertFalse(manifest["scheduling_enabled"])
        self.assertEqual(manifest["players_scored"], 11)
        self.assertEqual(
            scores["score_status"].value_counts().to_dict(),
            {
                "live_scored": 11,
                "season_context_only": 5,
                "inactive_suppressed": 3,
            },
        )
        self.assertEqual(
            {row["source_name"] for row in evidence},
            {
                "pbpstats_player_game_reviewed_adapter",
                "reviewed_player_role_assignments_2026",
            },
        )
        self.assertEqual(
            {row["safeguard"] for row in evidence},
            {
                "live_output; rates_recomputed_from_additive_counts",
                "live_output; reviewed_role_assignment",
            },
        )
        self.assertIn("Live output enabled", html)
        self.assertIn("Live scoring: <b>ENABLED</b>", html)
        self.assertNotIn("DRY RUN", html)


if __name__ == "__main__":
    unittest.main()
