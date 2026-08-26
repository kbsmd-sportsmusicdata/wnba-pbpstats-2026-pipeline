import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

APPROVED_ELIGIBILITY = (
    ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "player_eligibility_2026.csv"
)
APPROVAL_MANIFEST = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "eligibility_approval_manifest_2026.json"
)
ELIGIBILITY_ADDENDUM = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "eligibility_addendum_2026-08-23.csv"
)
PENDING_COVERAGE_ADDENDUM = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "eligibility_coverage_addendum_2026-08-24.pending.csv"
)
PENDING_COVERAGE_MANIFEST = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "eligibility_coverage_addendum_manifest_2026-08-24.json"
)
PENDING_PLAYER_CORE_ADDENDUM = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "player_core_coverage_addendum_2026-08-24.pending.csv"
)
APPROVED_COVERAGE_ADDENDUM = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "eligibility_coverage_addendum_2026-08-24.csv"
)
APPROVED_PLAYER_CORE_ADDENDUM = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "player_core_coverage_addendum_2026-08-24.csv"
)
PENDING_ELIGIBILITY = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "player_eligibility_2026.pending.csv"
)
CROSSWALK = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "player_identity_crosswalk_2026.csv"
)
BUILD_MANIFEST = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "eligibility_build_manifest_2026.json"
)


def eligibility_api():
    try:
        from role_fulfillment_matrix.eligibility import (
            EligibilityBuildError,
            build_eligibility_package,
            write_eligibility_package,
        )
    except ImportError as exc:
        raise AssertionError("eligibility builder is not implemented") from exc
    return EligibilityBuildError, build_eligibility_package, write_eligibility_package


def player_core_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "season": 2026,
            "athlete_id": "101",
            "slug": "rookie-player",
            "full_name": "Rookie Player",
            "date_of_birth": "2003-09-20T07:00Z",
            "experience_years": 0,
            "active": True,
            "status_type": "active",
        },
        {
            "season": 2026,
            "athlete_id": "102",
            "slug": "third-year-player",
            "full_name": "Third-Year Player",
            "date_of_birth": "2000-01-15T08:00Z",
            "experience_years": 3,
            "active": True,
            "status_type": "active",
        },
        {
            "season": 2026,
            "athlete_id": "103",
            "slug": "fourth-year-player",
            "full_name": "Fourth Year Player",
            "date_of_birth": "1999-12-31T08:00Z",
            "experience_years": 4,
            "active": True,
            "status_type": "active",
        },
        {
            "season": 2026,
            "athlete_id": "104",
            "slug": "source-only-player",
            "full_name": "Source Only Player",
            "date_of_birth": "2002-02-02T08:00Z",
            "experience_years": 2,
            "active": False,
            "status_type": "free-agent",
        },
    ])


def player_game_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "game_date": "2026-08-01",
            "game_id": "G1",
            "player_id": "P-1",
            "player_name": "Rookie Player",
            "team_abbreviation": "AAA",
        },
        {
            "game_date": "2026-08-19",
            "game_id": "G2",
            "player_id": "P-1",
            "player_name": "Rookie Player",
            "team_abbreviation": "BBB",
        },
        {
            "game_date": "2026-08-18",
            "game_id": "G3",
            "player_id": "P-2",
            "player_name": "Third Year Player",
            "team_abbreviation": "CCC",
        },
        {
            "game_date": "2026-08-20",
            "game_id": "G4",
            "player_id": "P-3",
            "player_name": "Fourth-Year Player",
            "team_abbreviation": "DDD",
        },
    ])


class EligibilityBuilderTest(unittest.TestCase):
    def test_builds_pending_rows_with_hand_checked_threshold_and_latest_team(self):
        _, build, _ = eligibility_api()

        package = build(
            player_core_frame(),
            player_game_frame(),
            cutoff_date="2026-08-20",
            source_as_of="2026-08-22",
            source_path="analysis/role_fulfillment_matrix/data/live_inputs/player_core_2026.csv",
            source_sha256="a" * 64,
            player_game_path="data/processed/player_game.parquet",
            player_game_sha256="b" * 64,
        )

        eligibility = package.eligibility.set_index("player_id")
        self.assertEqual(list(eligibility.index), ["P-3", "P-1", "P-2"])
        self.assertEqual(eligibility.loc["P-1", "team_abbreviation"], "BBB")
        self.assertEqual(eligibility.loc["P-1", "age_on_cutoff"], 22)
        self.assertEqual(eligibility.loc["P-2", "age_on_cutoff"], 26)
        self.assertEqual(eligibility.loc["P-3", "age_on_cutoff"], 26)
        self.assertTrue(eligibility.loc["P-1", "eligible_flag"])
        self.assertTrue(eligibility.loc["P-2", "eligible_flag"])
        self.assertFalse(eligibility.loc["P-3", "eligible_flag"])
        self.assertEqual(set(eligibility["eligibility_type"]), {"experience_le_3"})
        self.assertEqual(set(eligibility["review_status"]), {"pending"})
        self.assertTrue(eligibility["reviewed_by"].isna().all())
        self.assertTrue(eligibility["reviewed_at"].isna().all())
        self.assertEqual(
            eligibility.loc["P-2", "source_url"],
            "https://www.espn.com/wnba/player/bio/_/id/102/third-year-player",
        )

        crosswalk = package.crosswalk
        self.assertEqual(len(crosswalk), 4)
        self.assertEqual(crosswalk["match_status"].value_counts().to_dict(), {
            "matched": 3,
            "source_only": 1,
        })
        source_only = crosswalk[crosswalk["match_status"] == "source_only"].iloc[0]
        self.assertEqual(source_only["espn_player_name"], "Source Only Player")
        self.assertEqual(source_only["exclusion_reason"], "no_pbpstats_game_record")

        self.assertEqual(package.manifest["pbpstats_players"], 3)
        self.assertEqual(package.manifest["matched_players"], 3)
        self.assertEqual(package.manifest["coverage_pct"], 100.0)
        self.assertEqual(package.manifest["eligible_players"], 2)
        self.assertEqual(package.manifest["review_status"], "pending")
        self.assertEqual(package.manifest["live_scoring_status"], "blocked")
        self.assertEqual(package.manifest["sources"]["player_game"], {
            "path": "data/processed/player_game.parquet",
            "sha256": "b" * 64,
            "rows": 4,
            "rows_on_or_before_cutoff": 4,
        })

    def test_rejects_duplicate_normalized_source_names(self):
        error, build, _ = eligibility_api()
        core = player_core_frame()
        duplicate = core.iloc[[0]].copy()
        duplicate["athlete_id"] = "999"
        duplicate["full_name"] = "Rookie-Player"

        with self.assertRaisesRegex(error, "duplicate normalized player names.*rookieplayer"):
            build(
                pd.concat([core, duplicate], ignore_index=True),
                player_game_frame(),
                cutoff_date="2026-08-20",
                source_as_of="2026-08-22",
                source_path="player_core.csv",
                source_sha256="a" * 64,
                player_game_path="player_game.parquet",
                player_game_sha256="b" * 64,
            )

    def test_rejects_incomplete_pbpstats_coverage(self):
        error, build, _ = eligibility_api()
        games = pd.concat([
            player_game_frame(),
            pd.DataFrame([{
                "game_date": "2026-08-20",
                "game_id": "G5",
                "player_id": "P-4",
                "player_name": "Missing Source Player",
                "team_abbreviation": "EEE",
            }]),
        ], ignore_index=True)

        with self.assertRaisesRegex(error, "missing player-core matches.*Missing Source Player"):
            build(
                player_core_frame(),
                games,
                cutoff_date="2026-08-20",
                source_as_of="2026-08-22",
                source_path="player_core.csv",
                source_sha256="a" * 64,
                player_game_path="player_game.parquet",
                player_game_sha256="b" * 64,
            )

    def test_rejects_missing_or_invalid_experience(self):
        error, build, _ = eligibility_api()
        core = player_core_frame()
        core.loc[core["athlete_id"] == "102", "experience_years"] = None

        with self.assertRaisesRegex(error, "experience_years contains missing or invalid values"):
            build(
                core,
                player_game_frame(),
                cutoff_date="2026-08-20",
                source_as_of="2026-08-22",
                source_path="player_core.csv",
                source_sha256="a" * 64,
                player_game_path="player_game.parquet",
                player_game_sha256="b" * 64,
            )

    def test_writes_separate_outputs_with_source_and_output_hashes(self):
        _, build, write = eligibility_api()
        package = build(
            player_core_frame(),
            player_game_frame(),
            cutoff_date="2026-08-20",
            source_as_of="2026-08-22",
            source_path="player_core.csv",
            source_sha256="a" * 64,
            player_game_path="player_game.parquet",
            player_game_sha256="b" * 64,
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = write(package, Path(tmp))
            eligibility_path = Path(result["eligibility_path"])
            crosswalk_path = Path(result["crosswalk_path"])
            manifest_path = Path(result["manifest_path"])

            self.assertTrue(eligibility_path.exists())
            self.assertTrue(crosswalk_path.exists())
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["outputs"]["eligibility"]["sha256"],
                hashlib.sha256(eligibility_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                manifest["outputs"]["crosswalk"]["sha256"],
                hashlib.sha256(crosswalk_path.read_bytes()).hexdigest(),
            )

    def test_refuses_to_overwrite_directory_with_approved_review_evidence(self):
        error, build, write = eligibility_api()
        package = build(
            player_core_frame(),
            player_game_frame(),
            cutoff_date="2026-08-20",
            source_as_of="2026-08-22",
            source_path="player_core.csv",
            source_sha256="a" * 64,
            player_game_path="player_game.parquet",
            player_game_sha256="b" * 64,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            pending_path = output_dir / "player_eligibility_2026.pending.csv"
            pending_path.write_text("approved evidence\n", encoding="utf-8")
            (output_dir / "eligibility_approval_manifest_2026.json").write_text(
                '{"review_status":"reviewed"}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                error,
                "approved review evidence.*fresh output directory",
            ):
                write(package, output_dir)

            self.assertEqual(
                pending_path.read_text(encoding="utf-8"),
                "approved evidence\n",
            )

    def test_cli_builds_review_package_from_configurable_paths(self):
        script = ROOT / "scripts" / "build_role_fulfillment_eligibility.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            core_path = tmp_path / "player_core.csv"
            game_path = tmp_path / "player_game.parquet"
            output_dir = tmp_path / "review"
            player_core_frame().to_csv(core_path, index=False)
            player_game_frame().to_parquet(game_path, index=False)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--player-core",
                    str(core_path),
                    "--player-game",
                    str(game_path),
                    "--cutoff-date",
                    "2026-08-20",
                    "--source-as-of",
                    "2026-08-22",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["status"], "pending_review_package_built")
            self.assertEqual(summary["eligibility_rows"], 3)
            self.assertEqual(summary["eligible_players"], 2)
            self.assertEqual(summary["coverage_pct"], 100.0)
            self.assertEqual(summary["live_scoring_status"], "blocked")
            self.assertTrue((output_dir / "player_eligibility_2026.pending.csv").exists())


class ApprovedEligibilityArtifactTest(unittest.TestCase):
    def test_new_pbpstats_identities_have_a_complete_pending_review_addendum(self):
        self.assertTrue(PENDING_COVERAGE_ADDENDUM.exists())
        self.assertTrue(PENDING_COVERAGE_MANIFEST.exists())
        self.assertTrue(PENDING_PLAYER_CORE_ADDENDUM.exists())

        addendum = pd.read_csv(PENDING_COVERAGE_ADDENDUM, dtype={"player_id": str})
        self.assertEqual(len(addendum), 2)
        self.assertEqual(addendum["player_id"].nunique(), 2)
        self.assertEqual(addendum["espn_athlete_id"].nunique(), 2)
        self.assertEqual(
            set(addendum["player_name"]),
            {"Michelle Onyiah", "Morgan Maly"},
        )
        by_name = addendum.set_index("player_name")
        self.assertEqual(by_name.loc["Michelle Onyiah", "player_id"], "1642803")
        self.assertEqual(by_name.loc["Michelle Onyiah", "espn_athlete_id"], 4433744)
        self.assertEqual(by_name.loc["Michelle Onyiah", "team_abbreviation"], "IND")
        self.assertEqual(by_name.loc["Michelle Onyiah", "date_of_birth"], "2002-03-12")
        self.assertEqual(by_name.loc["Morgan Maly", "player_id"], "1642835")
        self.assertEqual(by_name.loc["Morgan Maly", "espn_athlete_id"], 4599199)
        self.assertEqual(by_name.loc["Morgan Maly", "team_abbreviation"], "CHI")
        self.assertEqual(by_name.loc["Morgan Maly", "date_of_birth"], "2002-01-25")
        self.assertTrue((addendum["experience_years"] == 0).all())
        self.assertTrue(addendum["eligible_flag"].all())
        self.assertEqual(set(addendum["review_status"]), {"pending"})
        self.assertTrue(addendum["reviewed_by"].isna().all())
        self.assertTrue(addendum["reviewed_at"].isna().all())
        self.assertEqual(set(addendum["source_system"]), {"WNBA"})

        player_core = pd.read_csv(PENDING_PLAYER_CORE_ADDENDUM)
        self.assertEqual(len(player_core), 2)
        self.assertEqual(player_core["athlete_id"].nunique(), 2)
        self.assertEqual(set(player_core["athlete_id"]), {4433744, 4599199})
        self.assertEqual(set(player_core["full_name"]), {"Michelle Onyiah", "Morgan Maly"})
        self.assertEqual(set(player_core["experience_years"]), {0})
        self.assertTrue(player_core["active"].all())
        self.assertEqual(set(player_core["status_type"]), {"developmental"})
        self.assertFalse(
            player_core[["current_team_id", "position_name", "position_abbreviation"]]
            .isna()
            .any()
            .any()
        )

        manifest = json.loads(PENDING_COVERAGE_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["review_status"], "reviewed")
        self.assertEqual(manifest["approved_by"], "Krystal Beasley")
        self.assertEqual(manifest["approved_at"], "2026-08-24")
        self.assertEqual(manifest["rows"], 2)
        self.assertEqual(manifest["pbpstats_player_ids"], ["1642803", "1642835"])
        self.assertEqual(manifest["eligible_players"], 2)
        self.assertEqual(manifest["projected_approved_rows"], 231)
        self.assertEqual(manifest["live_scoring_status"], "eligibility_coverage_approved")
        self.assertEqual(
            manifest["output"]["sha256"],
            hashlib.sha256(PENDING_COVERAGE_ADDENDUM.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["player_core_output"]["sha256"],
            hashlib.sha256(PENDING_PLAYER_CORE_ADDENDUM.read_bytes()).hexdigest(),
        )

    def test_approved_coverage_addendum_is_promoted_without_mutating_pending_evidence(self):
        self.assertTrue(APPROVED_COVERAGE_ADDENDUM.exists())
        self.assertTrue(APPROVED_PLAYER_CORE_ADDENDUM.exists())

        pending = pd.read_csv(PENDING_COVERAGE_ADDENDUM, dtype={"player_id": str})
        approved = pd.read_csv(APPROVED_COVERAGE_ADDENDUM, dtype={"player_id": str})
        review_fields = ["review_status", "reviewed_by", "reviewed_at"]
        pd.testing.assert_frame_equal(
            pending.drop(columns=review_fields),
            approved.drop(columns=review_fields),
            check_dtype=False,
        )
        self.assertEqual(set(approved["review_status"]), {"reviewed"})
        self.assertEqual(set(approved["reviewed_by"]), {"Krystal Beasley"})
        self.assertEqual(set(approved["reviewed_at"]), {"2026-08-24"})

        approved_core = pd.read_csv(APPROVED_PLAYER_CORE_ADDENDUM)
        pending_core = pd.read_csv(PENDING_PLAYER_CORE_ADDENDUM)
        pd.testing.assert_frame_equal(pending_core, approved_core, check_dtype=False)

    def test_approved_table_preserves_rule_and_records_human_review(self):
        self.assertTrue(APPROVED_ELIGIBILITY.exists(), "approved eligibility table is missing")
        eligibility = pd.read_csv(APPROVED_ELIGIBILITY)

        self.assertEqual(len(eligibility), 234)
        self.assertEqual(eligibility["player_id"].nunique(), 234)
        self.assertEqual(eligibility["espn_athlete_id"].nunique(), 234)
        self.assertTrue((eligibility["eligible_flag"] == (eligibility["experience_years"] <= 3)).all())
        self.assertEqual(set(eligibility["review_status"]), {"reviewed"})
        self.assertEqual(set(eligibility["reviewed_by"]), {"Krystal Beasley"})
        self.assertEqual(
            set(eligibility["reviewed_at"]),
            {"2026-08-22", "2026-08-23", "2026-08-24", "2026-08-25"},
        )

        refreshed = eligibility.set_index("player_name").loc[
            ["Elizabeth Balogun", "Christyn Williams", "Elena Buenavida"]
        ]
        self.assertEqual(set(refreshed["review_status"]), {"reviewed"})
        self.assertEqual(set(refreshed["reviewed_by"]), {"Krystal Beasley"})
        self.assertEqual(set(refreshed["reviewed_at"]), {"2026-08-25"})
        self.assertTrue(refreshed["eligible_flag"].all())
        self.assertEqual(
            set(refreshed["identity_match_method"]),
            {"espn_roster_identity_no_pbpstats_record"},
        )

        pending = pd.read_csv(PENDING_ELIGIBILITY)
        review_fields = ["review_status", "reviewed_by", "reviewed_at"]
        pending_ids = set(pending["player_id"].astype(str))
        original_approved = eligibility[
            eligibility["player_id"].astype(str).isin(pending_ids)
        ].drop(columns=review_fields).reset_index(drop=True)
        pending_without_review = pending.drop(columns=review_fields)
        original_approved["player_id"] = original_approved["player_id"].astype(str)
        pending_without_review["player_id"] = pending_without_review["player_id"].astype(str)
        pd.testing.assert_frame_equal(
            pending_without_review,
            original_approved,
            check_dtype=False,
        )

        addendum = pd.read_csv(ELIGIBILITY_ADDENDUM)
        self.assertEqual(
            set(addendum["player_name"]),
            {"Janiah Barker", "Iliana Rupert"},
        )
        addendum = addendum.set_index("player_name")
        self.assertEqual(addendum.loc["Janiah Barker", "player_id"], "espn:4565501")
        self.assertEqual(addendum.loc["Janiah Barker", "experience_years"], 0)
        self.assertTrue(bool(addendum.loc["Janiah Barker", "eligible_flag"]))
        self.assertEqual(addendum.loc["Janiah Barker", "status_type"], "inactive")
        self.assertEqual(addendum.loc["Iliana Rupert", "player_id"], "espn:4790263")
        self.assertEqual(addendum.loc["Iliana Rupert", "experience_years"], 4)
        self.assertFalse(bool(addendum.loc["Iliana Rupert", "eligible_flag"]))

        crosswalk = pd.read_csv(CROSSWALK)
        covered_ids = set(crosswalk.loc[crosswalk["player_id"].notna(), "player_id"])
        self.assertEqual(set(eligibility["player_id"]), covered_ids)

    def test_approval_manifest_hashes_promoted_table_and_records_manual_live_enablement(self):
        self.assertTrue(APPROVAL_MANIFEST.exists(), "eligibility approval manifest is missing")
        manifest = json.loads(APPROVAL_MANIFEST.read_text(encoding="utf-8"))

        self.assertEqual(manifest["review_status"], "reviewed")
        self.assertEqual(manifest["approved_by"], "Krystal Beasley")
        self.assertEqual(manifest["approved_at"], "2026-08-22")
        self.assertEqual(manifest["last_updated_at"], "2026-08-25")
        self.assertEqual(manifest["approved_rows"], 234)
        self.assertEqual(manifest["eligible_players"], 126)
        self.assertEqual(manifest["ineligible_players"], 108)
        self.assertEqual(manifest["live_eligibility_status"], "approved")
        self.assertEqual(manifest["live_scoring_status"], "enabled_manual_only")
        self.assertEqual(manifest["remaining_blockers"], [])
        self.assertEqual(
            manifest["approved_output"]["sha256"],
            hashlib.sha256(APPROVED_ELIGIBILITY.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["pending_input"]["sha256"],
            hashlib.sha256(PENDING_ELIGIBILITY.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["crosswalk"]["sha256"],
            hashlib.sha256(CROSSWALK.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["build_manifest"]["sha256"],
            hashlib.sha256(BUILD_MANIFEST.read_bytes()).hexdigest(),
        )
        self.assertEqual(len(manifest["supplemental_reviews"]), 3)
        supplement = manifest["supplemental_reviews"][0]
        self.assertEqual(supplement["reviewed_at"], "2026-08-23")
        self.assertEqual(supplement["rows"], 2)
        self.assertEqual(
            supplement["sha256"],
            hashlib.sha256(ELIGIBILITY_ADDENDUM.read_bytes()).hexdigest(),
        )
        coverage_supplement = manifest["supplemental_reviews"][1]
        self.assertEqual(coverage_supplement["reviewed_at"], "2026-08-24")
        self.assertEqual(coverage_supplement["rows"], 2)
        self.assertEqual(
            coverage_supplement["sha256"],
            hashlib.sha256(APPROVED_COVERAGE_ADDENDUM.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            coverage_supplement["player_core_sha256"],
            hashlib.sha256(APPROVED_PLAYER_CORE_ADDENDUM.read_bytes()).hexdigest(),
        )
        refresh_supplement = manifest["supplemental_reviews"][2]
        self.assertEqual(refresh_supplement["reviewed_at"], "2026-08-25")
        self.assertEqual(refresh_supplement["rows"], 3)
        self.assertEqual(refresh_supplement["identity_scope"], "new ESPN roster-only identities")

    def test_dry_run_config_references_approved_eligibility_without_enabling_output(self):
        live_config_path = (
            ROOT
            / "analysis"
            / "role_fulfillment_matrix"
            / "config"
            / "live_config.template.json"
        )
        config = json.loads(live_config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config["sources"]["eligibility"],
            "analysis/role_fulfillment_matrix/config/player_eligibility_2026.csv",
        )
        self.assertEqual(config["mode"], "live_dry_run")
        self.assertFalse(config["live_output_enabled"])


if __name__ == "__main__":
    unittest.main()
