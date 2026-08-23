import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from role_fulfillment_matrix.data_sources import load_config  # noqa: E402
from role_fulfillment_matrix.outputs import build_outputs  # noqa: E402


FIXTURE_CONFIG = ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "fixture_config.json"


class StandaloneBundleTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.output_root = Path(self.tempdir.name) / "role_fulfillment_matrix"
        config = load_config(FIXTURE_CONFIG)
        config["output_root"] = str(self.output_root)
        self.manifest = build_outputs(config)
        self.bundle = self.output_root / "deliverables" / "role_fulfillment_matrix"

    def test_build_writes_only_the_declared_standalone_bundle(self):
        files = {
            path.relative_to(self.output_root).as_posix()
            for path in self.output_root.rglob("*") if path.is_file()
        }
        self.assertEqual(files, {
            "data/processed/candidate_funnel_2026.csv",
            "data/processed/role_fulfillment_matrix_2026.csv",
            "data/processed/role_fulfillment_evidence_2026.json",
            "data/processed/run_manifest_2026.json",
            "deliverables/role_fulfillment_matrix/index.html",
            "deliverables/role_fulfillment_matrix/assets/app.js",
            "deliverables/role_fulfillment_matrix/assets/score_display.js",
            "deliverables/role_fulfillment_matrix/assets/styles.css",
            "deliverables/role_fulfillment_matrix/data/role_fulfillment_payload.json",
        })

    def test_html_exposes_funnel_matrix_cards_and_evidence_dialog(self):
        html = (self.bundle / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="fixture-banner"', 'id="funnel-summary"', 'id="score-cards"',
            'id="role-matrix"', 'id="candidate-table"', 'id="evidence-dialog"',
            'id="rfm-data"',
        ):
            self.assertIn(marker, html)
        self.assertIn("Fixture-only prototype", html)
        self.assertNotIn("standings_playoff_forecast", html)

    def test_payload_is_embedded_for_file_viewing_and_written_for_audit(self):
        html = (self.bundle / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("__RFM_PAYLOAD__", html)
        payload = json.loads((self.bundle / "data" / "role_fulfillment_payload.json").read_text())
        self.assertEqual(payload["meta"]["mode"], "fixture")
        self.assertEqual(payload["meta"]["live_scoring_status"], "blocked")
        self.assertEqual(len(payload["candidates"]), 2)
        self.assertGreater(len(payload["evidence"]), 0)

    def test_client_uses_safe_text_rendering_and_accessible_dialog(self):
        app = (self.bundle / "assets" / "app.js").read_text(encoding="utf-8")
        html = (self.bundle / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", app)
        self.assertIn("textContent", app)
        self.assertIn("showModal", app)
        self.assertIn('aria-labelledby="evidence-title"', html)
        self.assertIn('aria-label="Role Fulfillment Matrix"', html)

    def test_manifest_reports_output_rows_and_fixture_governance(self):
        manifest = json.loads(
            (self.output_root / "data" / "processed" / "run_manifest_2026.json").read_text()
        )
        self.assertEqual(manifest["mode"], "fixture")
        self.assertEqual(manifest["live_scoring_status"], "blocked")
        self.assertEqual(manifest["output_rows"]["role_fulfillment_matrix_2026.csv"], 2)
        self.assertEqual(self.manifest["formula_version"], "rfm-fixture-v1")
        self.assertEqual(
            manifest["config_path"],
            "analysis/role_fulfillment_matrix/config/fixture_config.json",
        )
        source_paths = [
            record["path"] for record in manifest["source_manifest"].values()
        ]
        self.assertTrue(all(not Path(path).is_absolute() for path in source_paths))

    def test_workflow_is_manual_fixture_and_live_dry_run_only_and_cannot_commit(self):
        workflow = (ROOT / ".github" / "workflows" / "role-fulfillment-matrix.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("git commit", workflow)
        self.assertNotIn("git push", workflow)
        self.assertIn("fixture_config.json", workflow)
        self.assertIn("live-dry-run-review:", workflow)
        self.assertIn("build_role_fulfillment_live_dry_run.py", workflow)
        self.assertIn("analysis/role_fulfillment_matrix/data/review/live_dry_run", workflow)
        self.assertIn("upload-artifact@v4", workflow)


if __name__ == "__main__":
    unittest.main()
