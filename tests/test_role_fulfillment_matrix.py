import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from role_fulfillment_matrix.contracts import ContractError, LiveScoringBlocked  # noqa: E402
from role_fulfillment_matrix.data_sources import load_config, load_sources  # noqa: E402
from role_fulfillment_matrix.pipeline import build_analysis  # noqa: E402


FIXTURE_CONFIG = ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "fixture_config.json"
LIVE_CONFIG = ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.template.json"


class DataContractTest(unittest.TestCase):
    def test_fixture_sources_are_explicit_and_reviewed(self):
        config = load_config(FIXTURE_CONFIG)
        sources = load_sources(config)

        self.assertEqual(config["mode"], "fixture")
        self.assertEqual(set(sources.source_manifest), {
            "standings", "player_game", "eligibility", "role_assignments", "role_definitions"
        })
        self.assertEqual(len(sources.player_game), 27)
        self.assertTrue(sources.eligibility["player_id"].str.startswith("FX-").all())

    def test_live_mode_fails_closed_before_loading_player_data(self):
        config = load_config(LIVE_CONFIG)
        with self.assertRaisesRegex(
            LiveScoringBlocked,
            "reviewed age/experience eligibility table.*reviewed player-role assignments",
        ):
            load_sources(config)

    def test_schema_errors_name_the_source_and_missing_fields(self):
        config = load_config(FIXTURE_CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "standings.csv"
            bad_path.write_text("team_abbreviation\nAAA\n", encoding="utf-8")
            config["sources"] = dict(config["sources"])
            config["sources"]["standings"] = str(bad_path)
            with self.assertRaisesRegex(ContractError, "standings.*current_rank"):
                load_sources(config)


class FunnelAndScoringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_analysis(load_config(FIXTURE_CONFIG))

    def test_candidate_funnel_has_stable_exclusion_reasons(self):
        funnel = self.result.funnel.set_index("player_id")
        self.assertEqual(funnel.loc["FX-001", "funnel_status"], "included")
        self.assertEqual(funnel.loc["FX-002", "funnel_status"], "included")
        self.assertEqual(funnel.loc["FX-003", "exclusion_reason"], "non_contender_team")
        self.assertEqual(funnel.loc["FX-004", "exclusion_reason"], "eligibility_not_reviewed")
        self.assertEqual(funnel.loc["FX-005", "exclusion_reason"], "insufficient_recent_sample")

    def test_rates_are_recomputed_from_summed_counts(self):
        scores = self.result.scores.set_index("player_id")
        creator = scores.loc["FX-001"]
        # Recent fixture totals: 10 assists over 120 offensive possessions.
        self.assertAlmostEqual(creator["recent_assists_per_75"], 6.25, places=6)
        self.assertAlmostEqual(creator["recent_assist_turnover_ratio"], 10 / 6, places=6)
        self.assertAlmostEqual(creator["recent_possession_share"], 120 / 240, places=6)

    def test_scores_remain_independent_and_expose_safeguards(self):
        scores = self.result.scores
        self.assertEqual(set(scores["player_id"]), {"FX-001", "FX-002"})
        self.assertTrue({"fulfillment_score", "opportunity_score", "stability_score"}.issubset(scores))
        self.assertNotIn("overall_score", scores.columns)
        self.assertNotIn("composite_score", scores.columns)
        self.assertTrue((scores["score_status"] == "fixture_only").all())
        self.assertTrue((scores["formula_version"] == "rfm-fixture-v1").all())
        self.assertTrue((scores["coverage_pct"] == 100.0).all())

    def test_stability_is_confidence_not_performance(self):
        scores = self.result.scores.set_index("player_id")
        stable_poor = scores.loc["FX-002"]
        self.assertGreater(stable_poor["stability_score"], stable_poor["fulfillment_score"])
        self.assertGreaterEqual(stable_poor["stability_score"], 75.0)

    def test_evidence_is_expandable_and_traceable(self):
        evidence = self.result.evidence
        self.assertFalse(evidence.empty)
        self.assertTrue({
            "player_id", "score_family", "metric_code", "metric_value", "denominator",
            "window_start", "window_end", "source_name", "safeguard"
        }.issubset(evidence))
        self.assertTrue((evidence["source_name"] == "synthetic_fixture_player_game").all())

    def test_manifest_declares_live_scoring_block(self):
        manifest = self.result.manifest
        self.assertEqual(manifest["mode"], "fixture")
        self.assertEqual(manifest["live_scoring_status"], "blocked")
        self.assertEqual(manifest["players_scored"], 2)
        self.assertEqual(manifest["formula_version"], "rfm-fixture-v1")
        self.assertNotIn("overall_score", json.dumps(manifest))


if __name__ == "__main__":
    unittest.main()
