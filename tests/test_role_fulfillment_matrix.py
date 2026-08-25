import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from role_fulfillment_matrix.contracts import ContractError, LiveScoringBlocked  # noqa: E402
from role_fulfillment_matrix.data_sources import load_config, load_sources  # noqa: E402
from role_fulfillment_matrix.pipeline import build_analysis  # noqa: E402


FIXTURE_CONFIG = ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "fixture_config.json"
LIVE_CONFIG = ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.template.json"
REVIEWED_ASSIGNMENTS = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "config"
    / "player_role_assignments_2026.csv"
)
ROLE_ASSIGNMENT_MANIFEST = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "role_assignment_approval_manifest_2026.json"
)


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

    def test_unapproved_live_publish_mode_fails_closed_before_loading_player_data(self):
        config = load_config(LIVE_CONFIG)
        config["mode"] = "live"
        config["live_output_enabled"] = True
        with self.assertRaises(LiveScoringBlocked) as raised:
            load_sources(config)
        message = str(raised.exception)
        self.assertIn("approved formula, adapter, and 19-player reviews", message)
        self.assertIn("execution_mode=manual_only", message)
        self.assertIn("scheduling_enabled=false", message)

    def test_reviewed_assignment_registry_covers_rostered_pool_only(self):
        self.assertTrue(REVIEWED_ASSIGNMENTS.exists(), "reviewed assignment registry is missing")
        assignments = pd.read_csv(REVIEWED_ASSIGNMENTS, dtype={"player_id": "string"})
        allowed_roles = {
            "lead_creator",
            "secondary_creator_connector",
            "perimeter_scorer_spacer",
            "downhill_pressure_wing",
            "interior_hub_rebounder",
            "interior_finisher_rim_runner",
        }

        self.assertEqual(len(assignments), 38)
        self.assertEqual(assignments["player_id"].nunique(), 38)
        self.assertEqual(set(assignments["review_status"]), {"reviewed"})
        self.assertTrue(set(assignments["role_code"]).issubset(allowed_roles))
        self.assertTrue(
            set(assignments["secondary_role_code"].dropna()).issubset(allowed_roles)
        )
        self.assertTrue(
            {"Alex Fowler", "Julie Vanloo", "Ndjakalenga Mwenentanda"}.isdisjoint(
                assignments["player_name"]
            )
        )
        chloe = assignments.set_index("player_name").loc["Chloe Bibby"]
        self.assertEqual(chloe["team_abbreviation"], "MIN")
        self.assertEqual(chloe["role_code"], "perimeter_scorer_spacer")
        self.assertEqual(chloe["secondary_role_code"], "secondary_creator_connector")
        self.assertAlmostEqual(chloe["assignment_confidence"], 0.70)
        self.assertEqual(chloe["reviewed_at"], "2026-08-23")
        michelle = assignments.set_index("player_name").loc["Michelle Onyiah"]
        self.assertEqual(michelle["team_abbreviation"], "IND")
        self.assertEqual(michelle["role_code"], "interior_finisher_rim_runner")
        self.assertEqual(michelle["secondary_role_code"], "interior_hub_rebounder")
        self.assertAlmostEqual(michelle["assignment_confidence"], 0.60)
        self.assertEqual(michelle["reviewed_at"], "2026-08-25")

        manifest = json.loads(ROLE_ASSIGNMENT_MANIFEST.read_text())
        self.assertEqual(manifest["reviewed_assignment_rows"], 38)
        self.assertEqual(manifest["reviewed_team_counts"]["MIN"], 9)
        self.assertEqual(manifest["reviewed_team_counts"]["IND"], 6)
        self.assertEqual(
            manifest["reviewed_primary_role_counts"]["perimeter_scorer_spacer"],
            12,
        )
        self.assertEqual(
            manifest["reviewed_primary_role_counts"]["interior_finisher_rim_runner"],
            7,
        )
        self.assertEqual(manifest["last_updated_at"], "2026-08-25")
        self.assertEqual(manifest["live_scoring_status"], "enabled_manual_only")
        self.assertEqual(manifest["remaining_blockers"], [])
        self.assertEqual(
            manifest["assignment_policy"]["inactive_without_role"],
            "deferred_until_active",
        )
        janiah_review = next(
            row
            for row in manifest["supplemental_reviews"]
            if row["player_name"] == "Janiah Barker"
        )
        self.assertEqual(janiah_review["decision"], "defer_role_while_inactive")
        self.assertEqual(
            janiah_review["reactivation_policy"],
            "reviewed_primary_role_required",
        )
        michelle_review = next(
            row
            for row in manifest["supplemental_reviews"]
            if row["player_name"] == "Michelle Onyiah"
        )
        self.assertEqual(
            michelle_review,
            {
                "reviewed_at": "2026-08-25",
                "reviewed_by": "Krystal Beasley",
                "player_name": "Michelle Onyiah",
                "primary_role": "interior_finisher_rim_runner",
                "secondary_role": "interior_hub_rebounder",
                "assignment_confidence": 0.60,
                "live_score_safeguard": "insufficient_recent_sample",
            },
        )
        self.assertEqual(
            manifest["reviewed_output"]["sha256"],
            hashlib.sha256(REVIEWED_ASSIGNMENTS.read_bytes()).hexdigest(),
        )

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

    def test_window_context_distinguishes_team_schedule_from_player_games(self):
        score = self.result.scores.set_index("player_id").loc["FX-001"]

        self.assertEqual(score["recent_team_games"], 3)
        self.assertEqual(score["recent_games"], 3)
        self.assertEqual(score["baseline_team_games"], 3)
        self.assertEqual(score["season_team_games"], 6)

    def _build_with_eligibility_status(self, player_id, *, active, status_type):
        config = load_config(FIXTURE_CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            eligibility = pd.read_csv(config["sources"]["eligibility"])
            eligibility["active"] = True
            eligibility["status_type"] = "active"
            eligibility.loc[eligibility["player_id"] == player_id, "active"] = active
            eligibility.loc[
                eligibility["player_id"] == player_id, "status_type"
            ] = status_type
            path = Path(tmp) / "eligibility.csv"
            eligibility.to_csv(path, index=False)
            config["sources"] = dict(config["sources"])
            config["sources"]["eligibility"] = str(path)
            return build_analysis(config)

    def test_free_agent_is_excluded_before_role_and_sample_gates(self):
        result = self._build_with_eligibility_status(
            "FX-001", active=False, status_type="free-agent"
        )
        player = result.funnel.set_index("player_id").loc["FX-001"]

        self.assertEqual(player["funnel_status"], "excluded")
        self.assertEqual(player["exclusion_reason"], "not_currently_rostered")

    def test_inactive_rostered_player_keeps_role_but_has_no_score(self):
        result = self._build_with_eligibility_status(
            "FX-001", active=False, status_type="inactive"
        )
        player = result.funnel.set_index("player_id").loc["FX-001"]

        self.assertEqual(player["funnel_status"], "included")
        self.assertIn("score_eligible", result.funnel.columns)
        self.assertFalse(player["score_eligible"])
        score = result.scores.set_index("player_id").loc["FX-001"]
        self.assertEqual(score["score_status"], "inactive_suppressed")
        self.assertTrue(pd.isna(score["fulfillment_score"]))

    def test_inactive_player_without_role_is_deferred_until_reactivated(self):
        config = load_config(FIXTURE_CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            assignments = pd.read_csv(config["sources"]["role_assignments"])
            assignments = assignments[assignments["player_id"] != "FX-001"]
            assignment_path = Path(tmp) / "assignments.csv"
            assignments.to_csv(assignment_path, index=False)

            eligibility = pd.read_csv(config["sources"]["eligibility"])
            eligibility.loc[eligibility["player_id"] == "FX-001", "active"] = False
            eligibility.loc[
                eligibility["player_id"] == "FX-001", "status_type"
            ] = "inactive"
            eligibility_path = Path(tmp) / "eligibility.csv"
            eligibility.to_csv(eligibility_path, index=False)

            config["sources"] = dict(
                config["sources"],
                role_assignments=str(assignment_path),
                eligibility=str(eligibility_path),
            )
            deferred = build_analysis(config).funnel.set_index("player_id").loc["FX-001"]

            eligibility.loc[eligibility["player_id"] == "FX-001", "active"] = True
            eligibility.loc[
                eligibility["player_id"] == "FX-001", "status_type"
            ] = "active"
            eligibility.to_csv(eligibility_path, index=False)
            reactivated = build_analysis(config).funnel.set_index("player_id").loc["FX-001"]

        self.assertEqual(deferred["exclusion_reason"], "inactive_role_review_deferred")
        self.assertEqual(deferred["funnel_status"], "excluded")
        self.assertEqual(reactivated["exclusion_reason"], "role_assignment_not_reviewed")

    def test_live_mode_blocks_a_reviewed_assignment_with_an_invalid_role(self):
        sources = deepcopy(self.result.sources)
        sources.effective_config = dict(sources.effective_config, mode="live")
        sources.eligibility["review_status"] = "reviewed"
        sources.role_assignments.loc[
            sources.role_assignments["player_id"] == "FX-001", "role_code"
        ] = "removed_role"

        with patch("role_fulfillment_matrix.pipeline.load_sources", return_value=sources):
            with self.assertRaisesRegex(
                LiveScoringBlocked,
                "invalid reviewed role assignments: 1",
            ):
                build_analysis(sources.effective_config)

    def test_500_season_possessions_keep_role_visible_without_recent_score(self):
        config = load_config(FIXTURE_CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            player_game = pd.read_csv(config["sources"]["player_game"])
            baseline = (
                (player_game["player_id"] == "FX-005")
                & (player_game["game_date"] < "2026-08-18")
            )
            player_game.loc[baseline, "off_poss"] = 235
            player_game.loc[baseline, "team_possessions"] = 240
            path = Path(tmp) / "player_game.csv"
            player_game.to_csv(path, index=False)
            config["sources"] = dict(config["sources"])
            config["sources"]["player_game"] = str(path)
            config["minimums"] = dict(config["minimums"])
            config["minimums"]["season_off_poss_fallback"] = 500

            result = build_analysis(config)

        player = result.funnel.set_index("player_id").loc["FX-005"]
        self.assertTrue(
            {
                "season_off_poss",
                "season_possessions_met",
                "recent_games_met",
                "recent_possessions_met",
                "sample_status",
                "score_eligible",
            }.issubset(result.funnel.columns)
        )
        self.assertEqual(player["season_off_poss"], 500)
        self.assertTrue(player["season_possessions_met"])
        self.assertFalse(player["recent_games_met"])
        self.assertFalse(player["recent_possessions_met"])
        self.assertEqual(
            player["sample_status"],
            "season_volume_met_recent_sample_insufficient",
        )
        self.assertEqual(player["funnel_status"], "included")
        self.assertFalse(player["score_eligible"])
        self.assertIn("FX-005", set(result.scores["player_id"]))
        score = result.scores.set_index("player_id").loc["FX-005"]
        self.assertEqual(score["score_status"], "season_context_only")
        self.assertTrue(pd.isna(score["fulfillment_score"]))

    def test_empty_baseline_window_flows_to_unavailable_scores(self):
        config = load_config(FIXTURE_CONFIG)
        config["windows"] = dict(config["windows"])
        config["windows"]["baseline_start"] = "2025-01-01"
        config["windows"]["baseline_end"] = "2025-01-31"

        result = build_analysis(config)

        self.assertEqual(set(result.scores["player_id"]), {"FX-001", "FX-002"})
        self.assertTrue((result.scores["score_status"] == "unavailable").all())
        self.assertTrue(result.scores["baseline_possession_share"].isna().all())
        self.assertEqual(result.manifest["funnel_counts"]["candidates_included"], 2)
        self.assertEqual(result.manifest["players_scored"], 0)

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
            "window_start", "window_end", "window_scope", "source_name", "safeguard"
        }.issubset(evidence))
        self.assertEqual(set(evidence["source_name"]), {
            "synthetic_fixture_player_game",
            "synthetic_fixture_role_assignments",
        })

    def test_stability_evidence_preserves_raw_observations(self):
        stability = self.result.evidence[
            (self.result.evidence["player_id"] == "FX-001")
            & (self.result.evidence["score_family"] == "stability")
        ].set_index("metric_code")

        self.assertEqual(stability.loc["games", "metric_value"], 3.0)
        self.assertEqual(stability.loc["possessions", "metric_value"], 120.0)
        self.assertAlmostEqual(
            stability.loc["consistency", "metric_value"],
            0.2041241452319315,
            places=12,
        )
        self.assertEqual(stability.loc["assignment_confidence", "metric_value"], 0.9)
        self.assertEqual(stability.loc["games", "component_score"], 100.0)

    def test_evidence_provenance_matches_each_metric_source_and_window(self):
        evidence = self.result.evidence[
            self.result.evidence["player_id"] == "FX-001"
        ].set_index("metric_code")

        delta = evidence.loc["possession_share_delta"]
        self.assertEqual(delta["source_name"], "synthetic_fixture_player_game")
        self.assertEqual(delta["window_scope"], "baseline_to_recent")
        self.assertEqual(delta["window_start"], "2026-08-01")
        self.assertEqual(delta["window_end"], "2026-08-20")
        self.assertEqual(delta["baseline_denominator"], 240.0)
        self.assertEqual(delta["recent_denominator"], 240.0)

        assignment = evidence.loc["assignment_confidence"]
        self.assertEqual(assignment["source_name"], "synthetic_fixture_role_assignments")
        self.assertEqual(assignment["window_scope"], "assignment_review")
        self.assertEqual(assignment["window_start"], "2026-08-20")
        self.assertEqual(assignment["window_end"], "2026-08-20")

    def test_manifest_declares_live_scoring_block(self):
        manifest = self.result.manifest
        self.assertEqual(manifest["mode"], "fixture")
        self.assertEqual(manifest["live_scoring_status"], "blocked")
        self.assertEqual(manifest["players_scored"], 2)
        self.assertEqual(manifest["formula_version"], "rfm-fixture-v1")
        self.assertNotIn("overall_score", json.dumps(manifest))


if __name__ == "__main__":
    unittest.main()
