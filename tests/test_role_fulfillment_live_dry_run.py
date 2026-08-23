import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from role_fulfillment_matrix.contracts import (  # noqa: E402
    LiveScoringBlocked,
    authorize_execution,
)
from role_fulfillment_matrix.data_sources import LoadedSources, load_sources  # noqa: E402
from role_fulfillment_matrix.funnel import build_candidate_funnel  # noqa: E402
from role_fulfillment_matrix.live_policy import (  # noqa: E402
    derive_analysis_windows,
    validate_locked_parity_windows,
)
from role_fulfillment_matrix.metrics import build_window_metrics  # noqa: E402
from role_fulfillment_matrix.pipeline import build_analysis  # noqa: E402
from role_fulfillment_matrix.roster_adapter import (  # noqa: E402
    RosterAdapterError,
    adapt_espn_roster,
)
from role_fulfillment_matrix.standings_adapter import (  # noqa: E402
    adapt_forecast_standings,
)


LIVE_CONFIG = (
    ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.template.json"
)


class LiveDryRunGovernanceTest(unittest.TestCase):
    def test_live_template_declares_cutoff_policy_and_keeps_output_disabled(self):
        config = json.loads(LIVE_CONFIG.read_text())
        self.assertEqual(config["mode"], "live_dry_run")
        self.assertEqual(
            config["window_policy"],
            {"recent_days": 14, "baseline_days": 14, "lag_days": 1},
        )
        self.assertNotIn("windows", config)
        self.assertEqual(
            config["locked_parity_windows"],
            {
                "baseline_start": "2026-07-24",
                "baseline_end": "2026-08-06",
                "recent_start": "2026-08-07",
                "recent_end": "2026-08-20",
            },
        )
        self.assertFalse(config["live_output_enabled"])

    def test_cutoff_policy_derives_non_overlapping_fourteen_day_windows(self):
        self.assertEqual(
            derive_analysis_windows(
                "2026-08-21",
                recent_days=14,
                baseline_days=14,
                lag_days=1,
            ),
            {
                "baseline_start": "2026-07-24",
                "baseline_end": "2026-08-06",
                "recent_start": "2026-08-07",
                "recent_end": "2026-08-20",
            },
        )

    def test_window_policy_rejects_nonpositive_lengths_and_negative_lag(self):
        for kwargs in (
            {"recent_days": 0, "baseline_days": 14, "lag_days": 1},
            {"recent_days": 14, "baseline_days": 0, "lag_days": 1},
            {"recent_days": 14, "baseline_days": 14, "lag_days": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                derive_analysis_windows("2026-08-21", **kwargs)

    def test_locked_parity_inputs_require_complete_ordered_fixed_windows(self):
        with self.assertRaisesRegex(ValueError, "requires explicit"):
            validate_locked_parity_windows(None)
        with self.assertRaisesRegex(ValueError, "missing required fields"):
            validate_locked_parity_windows({"recent_start": "2026-08-07"})
        with self.assertRaisesRegex(ValueError, "must be ordered"):
            validate_locked_parity_windows(
                {
                    "baseline_start": "2026-08-07",
                    "baseline_end": "2026-08-20",
                    "recent_start": "2026-07-24",
                    "recent_end": "2026-08-06",
                }
            )

    def test_approved_dry_run_is_allowed_but_live_publish_stays_blocked(self):
        config = json.loads(LIVE_CONFIG.read_text())
        config["mode"] = "live_dry_run"
        authorize_execution(config)

        publish = dict(config, mode="live", live_output_enabled=True)
        with self.assertRaises(LiveScoringBlocked):
            authorize_execution(publish)

    def test_dry_run_requires_approved_gates_and_disabled_output(self):
        base = json.loads(LIVE_CONFIG.read_text())
        base["mode"] = "live_dry_run"
        invalid = (
            dict(base, validation_status="pending_review"),
            dict(base, live_adapter_status="pending_review"),
            dict(base, live_output_enabled=True),
        )
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(LiveScoringBlocked):
                authorize_execution(config)


class LiveSourceAdapterTest(unittest.TestCase):
    def test_standings_adapter_normalizes_all_espn_pbpstats_team_code_differences(self):
        standings = pd.DataFrame(
            [
                {"team_id": 129689, "team_abbreviation": "GS", "current_rank": 1},
                {"team_id": 17, "team_abbreviation": "LV", "current_rank": 2},
                {"team_id": 9, "team_abbreviation": "NY", "current_rank": 3},
                {"team_id": 16, "team_abbreviation": "WSH", "current_rank": 4},
                {"team_id": 132052, "team_abbreviation": "POR", "current_rank": 5},
                {"team_id": 6, "team_abbreviation": "LA", "current_rank": 6},
                {"team_id": 20, "team_abbreviation": "ATL", "current_rank": 7},
            ]
        )
        result = adapt_forecast_standings(
            standings,
            {"cutoff_date": "2026-08-21"},
        )
        self.assertEqual(
            result.standings["team_abbreviation"].tolist(),
            ["GSV", "LVA", "NYL", "WAS", "PDX", "LAS", "ATL"],
        )
        self.assertEqual(set(result.standings["cutoff_date"]), {"2026-08-21"})
        self.assertEqual(result.quality["normalized_team_codes"], 6)

    def test_roster_adapter_uses_reviewed_identity_crosswalk_and_current_team(self):
        player_core = pd.DataFrame(
            [
                {
                    "athlete_id": "1001",
                    "full_name": "Current Player",
                    "current_team_id": "17",
                    "active": True,
                    "status_type": "active",
                },
                {
                    "athlete_id": "1002",
                    "full_name": "Inactive Player",
                    "current_team_id": "9",
                    "active": False,
                    "status_type": "inactive",
                },
            ]
        )
        eligibility = pd.DataFrame(
            [
                {
                    "player_id": "p1",
                    "player_name": "Current Player",
                    "espn_athlete_id": "1001",
                    "review_status": "reviewed",
                },
                {
                    "player_id": "p2",
                    "player_name": "Inactive Player",
                    "espn_athlete_id": "1002",
                    "review_status": "reviewed",
                },
            ]
        )
        raw_standings = pd.DataFrame(
            [
                {"team_id": 17, "team_abbreviation": "LV"},
                {"team_id": 9, "team_abbreviation": "NY"},
            ]
        )
        result = adapt_espn_roster(
            player_core,
            eligibility,
            raw_standings,
            source_as_of="2026-08-22",
            cutoff_date="2026-08-21",
        )
        roster = result.roster.set_index("player_id")
        self.assertEqual(roster.loc["p1", "team_abbreviation"], "LVA")
        self.assertTrue(roster.loc["p1", "active"])
        self.assertEqual(roster.loc["p2", "team_abbreviation"], "NYL")
        self.assertEqual(roster.loc["p2", "status_type"], "inactive")
        self.assertEqual(result.quality["reviewed_players_matched"], 2)

    def test_roster_adapter_rejects_a_snapshot_older_than_the_cutoff(self):
        player_core = pd.DataFrame(
            [{"athlete_id": "1001", "current_team_id": "17", "active": True, "status_type": "active"}]
        )
        eligibility = pd.DataFrame(
            [{"player_id": "p1", "player_name": "Player", "espn_athlete_id": "1001", "review_status": "reviewed"}]
        )
        standings = pd.DataFrame([{"team_id": 17, "team_abbreviation": "LV"}])
        with self.assertRaisesRegex(RosterAdapterError, "older than the standings cutoff"):
            adapt_espn_roster(
                player_core,
                eligibility,
                standings,
                source_as_of="2026-08-20",
                cutoff_date="2026-08-21",
            )

    def test_live_loader_wires_reviewed_sources_and_derives_effective_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            standings_path = root / "standings.csv"
            standings_manifest_path = root / "standings_manifest.json"
            player_path = root / "player.csv"
            team_path = root / "team.csv"
            ingest_manifest_path = root / "ingest_manifest.json"
            failures_path = root / "failures.json"
            player_core_path = root / "player_core.csv"
            eligibility_path = root / "eligibility.csv"
            assignments_path = root / "assignments.csv"

            pd.DataFrame(
                [{"team_id": 17, "team_abbreviation": "LV", "current_rank": 1}]
            ).to_csv(standings_path, index=False)
            standings_manifest_path.write_text(json.dumps({"cutoff_date": "2026-08-21"}))
            pd.DataFrame([self._raw_player_row()]).to_csv(player_path, index=False)
            pd.DataFrame(
                [{"Date": "2026-08-20", "GameId": "g1", "TeamAbbreviation": "LVA", "OffPoss": 80}]
            ).to_csv(team_path, index=False)
            ingest_manifest_path.write_text(
                json.dumps({"coverage_through": "2026-08-20", "players": {"failed_players": 0}})
            )
            failures_path.write_text("[]")
            pd.DataFrame(
                [{"athlete_id": "1001", "current_team_id": "17", "active": True, "status_type": "active"}]
            ).to_csv(player_core_path, index=False)
            pd.DataFrame([self._eligibility_row()]).to_csv(eligibility_path, index=False)
            pd.DataFrame([self._assignment_row()]).to_csv(assignments_path, index=False)

            config = self._live_config(
                standings_path=standings_path,
                standings_manifest_path=standings_manifest_path,
                player_path=player_path,
                team_path=team_path,
                ingest_manifest_path=ingest_manifest_path,
                failures_path=failures_path,
                player_core_path=player_core_path,
                eligibility_path=eligibility_path,
                assignments_path=assignments_path,
            )
            sources = load_sources(config)
            analysis = build_analysis(config)

        self.assertEqual(sources.effective_config["mode"], "live_dry_run")
        self.assertEqual(
            sources.effective_config["windows"],
            {
                "baseline_start": "2026-07-24",
                "baseline_end": "2026-08-06",
                "recent_start": "2026-08-07",
                "recent_end": "2026-08-20",
            },
        )
        self.assertEqual(sources.adapter_audit["status"], "review_ready")
        self.assertEqual(sources.source_manifest["player_game"]["status"], "reviewed_live_adapter")
        self.assertEqual(sources.roster_status.loc[0, "team_abbreviation"], "LVA")
        self.assertEqual(sources.standings.loc[0, "cutoff_date"], "2026-08-21")
        self.assertEqual(analysis.manifest["mode"], "live_dry_run")
        self.assertEqual(analysis.manifest["live_scoring_status"], "dry_run_only")
        self.assertEqual(
            analysis.manifest["live_scoring_blockers"],
            ["final reviewer approval and explicit live-output enablement"],
        )

    def test_locked_parity_uses_its_fixed_window_when_scoring_window_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            standings_path = root / "standings.csv"
            standings_manifest_path = root / "standings_manifest.json"
            player_path = root / "player.csv"
            team_path = root / "team.csv"
            ingest_manifest_path = root / "ingest_manifest.json"
            failures_path = root / "failures.json"
            player_core_path = root / "player_core.csv"
            eligibility_path = root / "eligibility.csv"
            assignments_path = root / "assignments.csv"
            parity_path = root / "locked_parity.csv"

            pd.DataFrame(
                [{"team_id": 17, "team_abbreviation": "LV", "current_rank": 1}]
            ).to_csv(standings_path, index=False)
            standings_manifest_path.write_text(json.dumps({"cutoff_date": "2026-08-23"}))
            fixed_row = self._raw_player_row()
            later_row = dict(fixed_row, Date="2026-08-22", GameId="g2", Points=30)
            pd.DataFrame([fixed_row, later_row]).to_csv(player_path, index=False)
            pd.DataFrame(
                [
                    {"Date": "2026-08-20", "GameId": "g1", "TeamAbbreviation": "LVA", "OffPoss": 80},
                    {"Date": "2026-08-22", "GameId": "g2", "TeamAbbreviation": "LVA", "OffPoss": 80},
                ]
            ).to_csv(team_path, index=False)
            ingest_manifest_path.write_text(
                json.dumps({"coverage_through": "2026-08-22", "players": {"failed_players": 0}})
            )
            failures_path.write_text("[]")
            pd.DataFrame(
                [{"athlete_id": "1001", "current_team_id": "17", "active": True, "status_type": "active"}]
            ).to_csv(player_core_path, index=False)
            pd.DataFrame([self._eligibility_row()]).to_csv(eligibility_path, index=False)
            pd.DataFrame([self._assignment_row()]).to_csv(assignments_path, index=False)
            pd.DataFrame(
                [
                    {
                        "player_id": "p1",
                        "player_name": "Player One",
                        "role_code": "lead_creator",
                        "assignment_confidence": 0.9,
                        "recent_games": 1,
                        "recent_off_poss": 40,
                        "recent_total_poss": 81,
                        "recent_fga": 8,
                        "recent_true_shooting_attempts": 8.88,
                        "recent_at_rim_fga": 3,
                        "recent_assists_per_75": 9.375,
                        "recent_true_shooting_pct": 12 / 17.76,
                        "recent_turnover_rate": 0.05,
                        "recent_three_point_fga_share": 0.375,
                        "recent_fta_rate": 0.25,
                        "recent_rim_fga_share": 0.375,
                        "recent_rim_fg_pct": 2 / 3,
                        "recent_rebounds_per_75_total_possessions": 300 / 81,
                        "recent_offensive_rebounds_per_75_off_poss": 1.875,
                    }
                ]
            ).to_csv(parity_path, index=False)

            config = self._live_config(
                standings_path=standings_path,
                standings_manifest_path=standings_manifest_path,
                player_path=player_path,
                team_path=team_path,
                ingest_manifest_path=ingest_manifest_path,
                failures_path=failures_path,
                player_core_path=player_core_path,
                eligibility_path=eligibility_path,
                assignments_path=assignments_path,
            )
            config["sources"]["locked_parity_inputs"] = str(parity_path)
            config["sources"]["roster_source_as_of"] = "2026-08-23"
            config["locked_parity_windows"] = {
                "baseline_start": "2026-07-24",
                "baseline_end": "2026-08-06",
                "recent_start": "2026-08-07",
                "recent_end": "2026-08-20",
            }
            sources = load_sources(config)

        self.assertEqual(sources.effective_config["windows"]["recent_end"], "2026-08-22")
        self.assertEqual(sources.adapter_audit["locked_parity_matches"], 1)
        self.assertEqual(
            sources.adapter_audit["locked_parity_windows"],
            config["locked_parity_windows"],
        )

    @staticmethod
    def _raw_player_row():
        return {
            "Date": "2026-08-20",
            "GameId": "g1",
            "Team": "LVA",
            "PlayerId": "p1",
            "PlayerName": "Player One",
            "Minutes": "20:00",
            "OffPoss": 40,
            "DefPoss": 41,
            "TotalPoss": 81,
            "Points": 12,
            "Assists": 5,
            "Turnovers": 2,
            "FG2M": 3,
            "FG2A": 5,
            "FG3M": 1,
            "FG3A": 3,
            "FTA": 2,
            "FtPoints": 2,
            "AtRimFGM": 2,
            "AtRimFGA": 3,
            "Rebounds": 4,
            "OffRebounds": 1,
        }

    @staticmethod
    def _eligibility_row():
        return {
            "player_id": "p1",
            "player_name": "Player One",
            "espn_athlete_id": "1001",
            "eligibility_type": "experience_le_3",
            "eligible_flag": True,
            "active": True,
            "status_type": "active",
            "review_status": "reviewed",
        }

    @staticmethod
    def _assignment_row():
        return {
            "player_id": "p1",
            "player_name": "Player One",
            "team_abbreviation": "LVA",
            "role_code": "lead_creator",
            "secondary_role_code": "",
            "assignment_confidence": 0.9,
            "review_status": "reviewed",
        }

    @staticmethod
    def _live_config(**paths):
        return {
            "season": 2026,
            "mode": "live_dry_run",
            "formula_version": "rfm-live-v1",
            "output_root": "unused",
            "sources": {
                "standings": str(paths["standings_path"]),
                "standings_manifest": str(paths["standings_manifest_path"]),
                "pbpstats_player_game": str(paths["player_path"]),
                "pbpstats_team_game": str(paths["team_path"]),
                "pbpstats_manifest": str(paths["ingest_manifest_path"]),
                "pbpstats_failures": str(paths["failures_path"]),
                "roster": str(paths["player_core_path"]),
                "roster_source_as_of": "2026-08-22",
                "eligibility": str(paths["eligibility_path"]),
                "role_assignments": str(paths["assignments_path"]),
                "role_definitions": str(
                    ROOT
                    / "analysis"
                    / "role_fulfillment_matrix"
                    / "config"
                    / "role_definitions_live_v1.json"
                ),
            },
            "window_policy": {"recent_days": 14, "baseline_days": 14, "lag_days": 1},
            "contender": {"current_rank_max": 6},
            "minimums": {
                "recent_games": 3,
                "recent_off_poss": 100,
                "season_off_poss_fallback": 500,
                "assignment_confidence_score": 0.5,
            },
            "opportunity": {
                "minutes_per_game": {"floor": 10, "target": 30, "weight": 0.3},
                "possession_share": {"floor": 0.2, "target": 0.7, "weight": 0.4},
                "possession_share_delta": {"floor": -0.1, "target": 0.2, "weight": 0.3},
            },
            "stability": {
                "recent_games_target": 6,
                "recent_off_poss_target": 300,
                "possession_share_sd_ceiling": 0.15,
                "weights": {"games": 0.2, "possessions": 0.3, "consistency": 0.3, "assignment_confidence": 0.2},
            },
            "validation_status": "approved_11_player_review",
            "live_adapter_status": "approved_review",
            "live_output_enabled": False,
        }


class CurrentTeamSafeguardTest(unittest.TestCase):
    def test_traded_player_appears_once_and_uses_current_team_games_only(self):
        sources, config = self._sources(assignment_team="LVA")
        metrics = build_window_metrics(sources.player_game, config)
        funnel = build_candidate_funnel(sources, metrics, config)
        player = funnel[funnel["player_id"] == "p1"]

        self.assertEqual(len(player), 1)
        self.assertEqual(player.iloc[0]["team_abbreviation"], "LVA")
        self.assertEqual(player.iloc[0]["recent_games"], 2)
        self.assertEqual(player.iloc[0]["recent_off_poss"], 120)

    def test_role_assignment_for_old_team_is_rejected_after_trade(self):
        sources, config = self._sources(assignment_team="ATL")
        metrics = build_window_metrics(sources.player_game, config)
        funnel = build_candidate_funnel(sources, metrics, config)
        player = funnel[funnel["player_id"] == "p1"].iloc[0]

        self.assertEqual(player["funnel_status"], "excluded")
        self.assertEqual(player["exclusion_reason"], "role_assignment_team_mismatch")

    @staticmethod
    def _sources(*, assignment_team):
        player_game = pd.DataFrame(
            [
                CurrentTeamSafeguardTest._canonical_game("old", "ATL", "2026-08-08", 40),
                CurrentTeamSafeguardTest._canonical_game("new1", "LVA", "2026-08-15", 60),
                CurrentTeamSafeguardTest._canonical_game("new2", "LVA", "2026-08-20", 60),
            ]
        )
        eligibility = pd.DataFrame(
            [
                {
                    "player_id": "p1",
                    "player_name": "Player One",
                    "eligibility_type": "experience_le_3",
                    "eligible_flag": True,
                    "active": True,
                    "status_type": "active",
                    "review_status": "reviewed",
                }
            ]
        )
        assignments = pd.DataFrame(
            [
                {
                    "player_id": "p1",
                    "player_name": "Player One",
                    "team_abbreviation": assignment_team,
                    "role_code": "lead_creator",
                    "assignment_confidence": 0.9,
                    "review_status": "reviewed",
                }
            ]
        )
        roles = json.loads(
            (
                ROOT
                / "analysis"
                / "role_fulfillment_matrix"
                / "config"
                / "role_definitions_live_v1.json"
            ).read_text()
        )
        config = {
            "contender": {"current_rank_max": 6},
            "minimums": {
                "recent_games": 1,
                "recent_off_poss": 50,
                "season_off_poss_fallback": 500,
            },
            "windows": {
                "baseline_start": "2026-07-24",
                "baseline_end": "2026-08-06",
                "recent_start": "2026-08-07",
                "recent_end": "2026-08-20",
            },
        }
        sources = LoadedSources(
            standings=pd.DataFrame(
                [{"team_abbreviation": "LVA", "current_rank": 1, "cutoff_date": "2026-08-21"}]
            ),
            player_game=player_game,
            eligibility=eligibility,
            role_assignments=assignments,
            role_definitions=roles,
            source_manifest={},
            roster_status=pd.DataFrame(
                [{"player_id": "p1", "player_name": "Player One", "team_abbreviation": "LVA", "active": True, "status_type": "active"}]
            ),
            adapter_audit={},
            effective_config=config,
        )
        return sources, config

    @staticmethod
    def _canonical_game(game_id, team, date, off_poss):
        return {
            "game_date": pd.Timestamp(date),
            "game_id": game_id,
            "player_id": "p1",
            "player_name": "Player One",
            "team_abbreviation": team,
            "minutes": 25,
            "off_poss": off_poss,
            "team_possessions": 80,
            "points": 12,
            "assists": 5,
            "turnovers": 2,
            "fga": 10,
            "fgm": 5,
            "fta": 2,
            "ftm": 2,
            "at_rim_fga": 3,
            "at_rim_fgm": 2,
            "def_poss": off_poss,
            "total_poss": 2 * off_poss,
            "fg3a": 4,
            "fg3m": 1,
            "rebounds": 4,
            "off_rebounds": 1,
        }


class LiveDryRunOutputTest(unittest.TestCase):
    def test_real_sources_build_an_isolated_nonpublishing_review_package(self):
        from build_role_fulfillment_live_dry_run import build

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "live_dry_run"
            manifest = build(output_root=output_root)
            report = (
                output_root / "role_fulfillment_matrix_live_dry_run_validation.md"
            ).read_text()
            bundle = output_root / "deliverables" / "role_fulfillment_matrix"
            html = (bundle / "index.html").read_text()
            payload = json.loads(
                (bundle / "data" / "role_fulfillment_payload.json").read_text()
            )

        self.assertEqual(manifest["mode"], "live_dry_run")
        self.assertEqual(manifest["live_scoring_status"], "dry_run_only")
        self.assertFalse(manifest["live_output_enabled"])
        self.assertEqual(manifest["adapter_audit"]["status"], "review_ready")
        self.assertEqual(manifest["adapter_audit"]["locked_parity_players"], 11)
        self.assertEqual(manifest["adapter_audit"]["locked_parity_matches"], 11)
        self.assertLessEqual(
            manifest["adapter_audit"]["locked_parity_max_abs_difference"],
            0.000001,
        )
        self.assertEqual(manifest["dry_run_gate_status"], "blocked")
        self.assertEqual(
            manifest["dry_run_gate_blockers"],
            ["current contender candidates without reviewed role assignments: 1"],
        )
        self.assertGreater(manifest["funnel_counts"]["players_considered"], 200)
        self.assertGreater(manifest["funnel_counts"]["candidates_included"], 0)
        self.assertIn("Review status: **pending reviewer approval**", report)
        self.assertIn("Live output remains disabled", report)
        self.assertIn("Chloe Bibby", report)
        self.assertIn("role assignment", report)
        self.assertIn("Locked 11-player parity: 11 of 11", report)
        self.assertIn("Zero-omitted cells filled:", report)
        self.assertIn("Live-data dry run", html)
        self.assertNotIn("Synthetic players and teams", html)
        self.assertNotIn(">FIXTURE<", html)
        self.assertEqual(payload["meta"]["mode"], "live_dry_run")
        self.assertTrue(
            all(row["analysis_mode"] == "live_dry_run" for row in payload["candidates"])
        )
        self.assertNotIn(
            "fixture_only",
            {row["score_status"] for row in payload["candidates"]},
        )


if __name__ == "__main__":
    unittest.main()
