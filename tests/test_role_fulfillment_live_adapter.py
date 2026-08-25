import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from role_fulfillment_matrix.pbpstats_adapter import (  # noqa: E402
    AdapterContractError,
    adapt_pbpstats_player_game,
    audit_live_adapter,
)
from role_fulfillment_matrix.metrics import aggregate_window  # noqa: E402


def player_rows():
    return pd.DataFrame(
        [
            {
                "Date": "2026-08-19", "GameId": "g1", "Team": "AAA",
                "PlayerId": "p1", "PlayerName": "Player One", "Minutes": "10:30",
                "OffPoss": 20, "DefPoss": 21, "TotalPoss": 41,
                "Points": 5, "Assists": None, "Turnovers": 1,
                "FG2M": 1, "FG2A": 2, "FG3M": 1, "FG3A": 2,
                "FTA": None, "FtPoints": None, "AtRimFGM": None, "AtRimFGA": None,
                "Rebounds": 2, "OffRebounds": None,
            },
            {
                "Date": "2026-08-20", "GameId": "g2", "Team": "AAA",
                "PlayerId": "p1", "PlayerName": "Player One", "Minutes": "00:23",
                "OffPoss": None, "DefPoss": 1, "TotalPoss": 1,
                "Points": None, "Assists": None, "Turnovers": None,
                "FG2M": None, "FG2A": None, "FG3M": None, "FG3A": None,
                "FTA": None, "FtPoints": None, "AtRimFGM": None, "AtRimFGA": None,
                "Rebounds": None, "OffRebounds": None,
            },
            {
                "Date": "2026-08-20", "GameId": "g2", "Team": "AAA",
                "PlayerId": "p2", "PlayerName": "Player Two", "Minutes": "00:00",
                "OffPoss": None, "DefPoss": None, "TotalPoss": None,
                "Points": None, "Assists": None, "Turnovers": None,
                "FG2M": None, "FG2A": None, "FG3M": None, "FG3A": None,
                "FTA": None, "FtPoints": None, "AtRimFGM": None, "AtRimFGA": None,
                "Rebounds": None, "OffRebounds": None,
            },
        ]
    )


def team_rows():
    return pd.DataFrame(
        [
            {"Date": "2026-08-19", "GameId": "g1", "TeamAbbreviation": "AAA", "OffPoss": 80},
            {"Date": "2026-08-20", "GameId": "g2", "TeamAbbreviation": "AAA", "OffPoss": 75},
        ]
    )


class PBPStatsAdapterTest(unittest.TestCase):
    def test_zero_omitted_counts_are_filled_only_after_participation_is_proved(self):
        result = adapt_pbpstats_player_game(player_rows(), team_rows())
        adapted = result.player_game.sort_values("game_id").reset_index(drop=True)
        self.assertEqual(len(adapted), 2)
        self.assertEqual(result.quality["excluded_nonparticipation_rows"], 1)
        first = adapted.iloc[0]
        self.assertAlmostEqual(first["minutes"], 10.5)
        self.assertEqual(first["assists"], 0)
        self.assertEqual(first["fta"], 0)
        self.assertEqual(first["fgm"], 2)
        self.assertEqual(first["fga"], 4)
        second = adapted.iloc[1]
        self.assertEqual(second["off_poss"], 0)
        self.assertEqual(second["def_poss"], 1)
        self.assertEqual(second["total_poss"], 1)
        self.assertEqual(second["team_possessions"], 75)

    def test_duplicate_player_game_keys_fail_closed(self):
        players = pd.concat([player_rows(), player_rows().iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(AdapterContractError, "duplicate PlayerId and GameId"):
            adapt_pbpstats_player_game(players, team_rows())

    def test_missing_team_game_join_fails_closed(self):
        with self.assertRaisesRegex(AdapterContractError, "team-game possession join"):
            adapt_pbpstats_player_game(player_rows(), team_rows().iloc[[0]])

    def test_team_game_date_mismatch_fails_closed(self):
        teams = team_rows()
        teams.loc[teams["GameId"] == "g1", "Date"] = "2026-08-18"
        with self.assertRaisesRegex(AdapterContractError, "team-game date"):
            adapt_pbpstats_player_game(player_rows(), teams)

    def test_unrelated_refresh_failure_is_warning_but_candidate_failure_blocks(self):
        result = adapt_pbpstats_player_game(player_rows(), team_rows())
        assignments = pd.DataFrame([{"player_id": "p1", "player_name": "Player One"}])
        manifest = {"coverage_through": "2026-08-20", "players": {"failed_players": 1}}
        unrelated = audit_live_adapter(
            result,
            assignments=assignments,
            manifest=manifest,
            failures=[{"player_id": "p9", "name": "Other Player"}],
            recent_end="2026-08-20",
        )
        self.assertEqual(unrelated["status"], "review_ready")
        self.assertEqual(unrelated["candidate_coverage"], {"matched": 1, "expected": 1})
        self.assertTrue(any("unrelated" in warning for warning in unrelated["warnings"]))

        candidate_failure = audit_live_adapter(
            result,
            assignments=assignments,
            manifest=manifest,
            failures=[{"player_id": "p1", "name": "Player One"}],
            recent_end="2026-08-20",
        )
        self.assertEqual(candidate_failure["status"], "blocked")
        self.assertTrue(any("reviewed-role player refresh failures" in item for item in candidate_failure["blockers"]))

    def test_stale_or_internally_inconsistent_coverage_blocks(self):
        result = adapt_pbpstats_player_game(player_rows(), team_rows())
        assignments = pd.DataFrame([{"player_id": "p1", "player_name": "Player One"}])
        audit = audit_live_adapter(
            result,
            assignments=assignments,
            manifest={"coverage_through": "2026-08-19", "players": {"failed_players": 0}},
            failures=[],
            recent_end="2026-08-20",
        )
        self.assertEqual(audit["status"], "blocked")
        self.assertTrue(any("recent window" in item for item in audit["blockers"]))
        self.assertTrue(any("maximum player-game date" in item for item in audit["blockers"]))

    def test_manifest_failure_count_must_match_failure_ledger(self):
        result = adapt_pbpstats_player_game(player_rows(), team_rows())
        audit = audit_live_adapter(
            result,
            assignments=pd.DataFrame([{"player_id": "p1", "player_name": "Player One"}]),
            manifest={"coverage_through": "2026-08-20", "players": {"failed_players": 2}},
            failures=[{"player_id": "p9", "name": "Other Player"}],
            recent_end="2026-08-20",
        )
        self.assertEqual(audit["status"], "blocked")
        self.assertTrue(any("failure count" in item for item in audit["blockers"]))

    def test_canonical_counts_derive_the_live_v1_role_metrics(self):
        adapted = adapt_pbpstats_player_game(player_rows(), team_rows()).player_game
        metrics = aggregate_window(adapted, "recent").set_index("player_id").loc["p1"]
        self.assertAlmostEqual(metrics["recent_three_point_fga_share"], 0.5)
        self.assertAlmostEqual(metrics["recent_fta_rate"], 0.0)
        self.assertAlmostEqual(metrics["recent_rebounds_per_75_total_possessions"], 75 * 2 / 42)
        self.assertAlmostEqual(metrics["recent_offensive_rebounds_per_75_off_poss"], 0.0)

    def test_real_adapter_builder_writes_review_package_and_keeps_live_disabled(self):
        from build_role_fulfillment_live_adapter_validation import build

        with tempfile.TemporaryDirectory() as tmp:
            manifest = build(Path(tmp))
            quality = pd.read_csv(Path(tmp) / "pbpstats_data_quality_checks.csv")
            report = (Path(tmp) / "role_fulfillment_matrix_live_adapter_validation.md").read_text()
            output_names = {path.name for path in Path(tmp).iterdir()}
        self.assertEqual(manifest["status"], "review_ready")
        self.assertEqual(manifest["candidate_coverage"], {"matched": 38, "expected": 38})
        self.assertEqual(manifest["parity_players"], 11)
        self.assertEqual(manifest["parity_matches"], 11)
        self.assertEqual(
            manifest["locked_parity_windows"]["recent_end"],
            "2026-08-20",
        )
        self.assertFalse(manifest["live_output_enabled"])
        self.assertIn("Review status: **approved**", report)
        self.assertIn("Approved by: **Krystal Beasley**", report)
        self.assertIn("Approval date: **2026-08-22**", report)
        self.assertIn("manifest_failure_ledger_consistency", set(quality["check"]))
        self.assertEqual(
            quality.set_index("check").loc["manifest_failure_ledger_consistency", "status"],
            "pass",
        )
        self.assertEqual(
            output_names,
            {
                "pbpstats_field_mapping.csv",
                "pbpstats_data_quality_checks.csv",
                "live_v1_11_player_adapter_parity.csv",
                "role_fulfillment_matrix_live_adapter_validation.md",
            },
        )


if __name__ == "__main__":
    unittest.main()
