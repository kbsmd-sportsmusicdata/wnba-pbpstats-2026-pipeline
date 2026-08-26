import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def roster_refresh_api():
    try:
        from role_fulfillment_matrix.roster_refresh import (
            RosterRefreshError,
            build_roster_refresh_candidate,
            parse_espn_roster_page,
            promote_roster_refresh_candidate,
            write_roster_refresh_package,
        )
    except ImportError as exc:
        raise AssertionError("roster refresh support is not implemented") from exc
    return (
        RosterRefreshError,
        build_roster_refresh_candidate,
        parse_espn_roster_page,
        promote_roster_refresh_candidate,
        write_roster_refresh_package,
    )


def espn_page(team_id, team_name, athletes):
    payload = {
        "page": {
            "content": {
                "roster": {
                    "team": {"id": str(team_id), "displayName": team_name},
                    "athletes": athletes,
                }
            }
        }
    }
    return (
        "<!doctype html><html><head>"
        "<!-- ESPNFITT | build | request | hash | www.espn.com | "
        "Tue, 25 Aug 2026 23:20:02 GMT -->"
        "</head><body><script>window['__espnfitt__']="
        + json.dumps(payload)
        + ";</script></body></html>"
    )


def athlete(player_id, name, *, position="G", experience=1, birth_date="01/02/03"):
    first_name, last_name = name.split(" ", 1)
    slug = name.lower().replace(" ", "-")
    return {
        "shortName": f"{first_name[0]}. {last_name}",
        "name": name,
        "href": f"https://www.espn.com/wnba/player/_/id/{player_id}/{slug}",
        "uid": f"s:40~l:59~a:{player_id}",
        "guid": f"guid-{player_id}",
        "id": str(player_id),
        "height": "6' 1\"",
        "weight": "170 lbs",
        "age": 23,
        "position": position,
        "jersey": "9",
        "birthDate": birth_date,
        "headshot": f"https://example.test/{player_id}.png",
        "lastName": last_name,
        "experience": experience,
        "college": "Example University",
    }


def existing_player(
    player_id,
    name,
    team_id,
    *,
    active=True,
    status_type="active",
    position="G",
):
    first_name, last_name = name.split(" ", 1)
    return {
        "season": 2026,
        "athlete_id": str(player_id),
        "guid": f"old-guid-{player_id}",
        "uid": f"s:40~l:59~a:{player_id}",
        "slug": name.lower().replace(" ", "-"),
        "type": "basketball",
        "first_name": first_name,
        "last_name": last_name,
        "full_name": name,
        "display_name": name,
        "short_name": f"{first_name[0]}. {last_name}",
        "height": 73.0,
        "display_height": "6' 1\"",
        "weight": 170.0,
        "display_weight": "170 lbs",
        "age": 23,
        "date_of_birth": "2003-01-02T08:00Z",
        "birth_city": "",
        "birth_state": "",
        "birth_country": "USA",
        "jersey": "9",
        "position_id": "3",
        "position_name": {"G": "Guard", "F": "Forward", "C": "Center"}[position],
        "position_abbreviation": position,
        "position_display_name": {"G": "Guard", "F": "Forward", "C": "Center"}[position],
        "college_id": "",
        "current_team_id": str(team_id),
        "headshot_href": f"https://example.test/{player_id}.png",
        "experience_years": 1,
        "status_id": "1" if active else "2",
        "status_name": "Active" if active else "Inactive",
        "status_type": status_type,
        "draft_year": "",
        "draft_round": "",
        "draft_selection": "",
        "active": active,
    }


class EspnRosterPageParserTest(unittest.TestCase):
    def test_extracts_source_timestamp_team_and_complete_player_identity(self):
        _, _, parse, _, _ = roster_refresh_api()
        page = parse(
            espn_page("5", "Indiana Fever", [athlete("101", "New Player", position="C")]),
            source_url="https://www.espn.com/wnba/team/roster/_/name/ind",
        )

        self.assertEqual(page.team_id, "5")
        self.assertEqual(page.team_name, "Indiana Fever")
        self.assertEqual(page.generated_at_utc, "2026-08-25T23:20:02Z")
        self.assertEqual(page.source_url, "https://www.espn.com/wnba/team/roster/_/name/ind")
        self.assertEqual(page.players.iloc[0]["athlete_id"], "101")
        self.assertEqual(page.players.iloc[0]["position_abbreviation"], "C")
        self.assertEqual(page.players.iloc[0]["experience_years"], 1)

    def test_rejects_missing_or_duplicate_player_ids(self):
        error, _, parse, _, _ = roster_refresh_api()
        duplicate = athlete("101", "New Player")
        with self.assertRaisesRegex(error, "duplicate athlete IDs"):
            parse(
                espn_page("5", "Indiana Fever", [duplicate, duplicate]),
                source_url="https://www.espn.com/wnba/team/roster/_/name/ind",
            )


class RosterRefreshCandidateTest(unittest.TestCase):
    def test_overlays_current_membership_without_erasing_historical_identities(self):
        _, build, parse, _, _ = roster_refresh_api()
        base = pd.DataFrame(
            [
                existing_player("101", "Returning Player", "5", position="G"),
                existing_player("102", "Departed Player", "5", position="F"),
                existing_player(
                    "103",
                    "Prior Freeagent",
                    "6",
                    active=False,
                    status_type="free-agent",
                    position="G",
                ),
                existing_player(
                    "104",
                    "Activated Player",
                    "6",
                    active=False,
                    status_type="free-agent",
                    position="G",
                ),
            ]
        )
        addendum = pd.DataFrame(
            [
                {
                    "athlete_id": "105",
                    "slug": "addendum-player",
                    "full_name": "Addendum Player",
                    "date_of_birth": "2002-03-12",
                    "current_team_id": "5",
                    "position_name": "Forward-Center",
                    "position_abbreviation": "F-C",
                    "experience_years": 0,
                    "active": True,
                    "status_type": "developmental",
                }
            ]
        )
        pages = [
            parse(
                espn_page(
                    "5",
                    "Indiana Fever",
                    [
                        athlete("101", "Returning Player", position="C"),
                        athlete("105", "Addendum Player", position="C", experience=0),
                        athlete("106", "New Player", position="F", experience=0),
                    ],
                ),
                source_url="https://www.espn.com/wnba/team/roster/_/name/ind",
            ),
            parse(
                espn_page(
                    "131935",
                    "Toronto Tempo",
                    [athlete("104", "Activated Player", position="G")],
                ),
                source_url="https://www.espn.com/wnba/team/roster/_/name/tor",
            ),
        ]

        package = build(
            base,
            [addendum],
            pages,
            source_as_of="2026-08-25",
            cutoff_date="2026-08-23",
        )

        candidate = package.player_core.set_index("athlete_id")
        self.assertEqual(len(candidate), 6)
        self.assertIn("103", candidate.index)
        self.assertEqual(candidate.loc["103", "status_type"], "free-agent")
        self.assertFalse(candidate.loc["102", "active"])
        self.assertEqual(candidate.loc["102", "status_type"], "pending-roster-review")
        self.assertEqual(candidate.loc["104", "current_team_id"], "131935")
        self.assertTrue(candidate.loc["104", "active"])
        self.assertEqual(candidate.loc["101", "position_abbreviation"], "C")
        self.assertEqual(candidate.loc["105", "position_abbreviation"], "C")
        self.assertEqual(candidate.loc["106", "full_name"], "New Player")
        self.assertEqual(candidate.loc["106", "date_of_birth"], "2003-01-02T08:00Z")

        changes = package.changes.set_index(["change_type", "athlete_id"])
        for key in (
            ("removed_from_active_page", "102"),
            ("activated", "104"),
            ("team_changed", "104"),
            ("position_changed", "101"),
            ("position_changed", "105"),
            ("added_active", "106"),
        ):
            self.assertIn(key, changes.index)
        self.assertEqual(set(package.changes["review_status"]), {"pending"})
        self.assertFalse(package.manifest["promotion_ready"])
        self.assertEqual(package.manifest["candidate_rows"], 6)
        self.assertEqual(package.manifest["current_active_players"], 4)
        self.assertEqual(package.manifest["new_active_identities"], 1)
        self.assertEqual(package.manifest["removed_from_active_page"], 1)
        self.assertEqual(
            package.manifest["blockers"],
            [
                "new active identities require eligibility review",
                "players removed from the active roster page require status review",
                "all material roster changes require explicit approval before promotion",
            ],
        )

    def test_rejects_stale_or_cross_team_duplicate_snapshots(self):
        error, build, parse, _, _ = roster_refresh_api()
        base = pd.DataFrame([existing_player("101", "Returning Player", "5")])
        ind = parse(
            espn_page("5", "Indiana Fever", [athlete("101", "Returning Player")]),
            source_url="https://www.espn.com/wnba/team/roster/_/name/ind",
        )
        tor = parse(
            espn_page("131935", "Toronto Tempo", [athlete("101", "Returning Player")]),
            source_url="https://www.espn.com/wnba/team/roster/_/name/tor",
        )
        with self.assertRaisesRegex(error, "older than the standings cutoff"):
            build(base, [], [ind], source_as_of="2026-08-22", cutoff_date="2026-08-23")
        with self.assertRaisesRegex(error, "listed on multiple current roster pages"):
            build(base, [], [ind, tor], source_as_of="2026-08-25", cutoff_date="2026-08-23")

    def test_writes_candidate_change_ledger_snapshot_manifest_and_review_report(self):
        _, build, parse, _, write = roster_refresh_api()
        base = pd.DataFrame([existing_player("101", "Returning Player", "5")])
        page = parse(
            espn_page(
                "5",
                "Indiana Fever",
                [
                    athlete("101", "Returning Player"),
                    athlete("106", "New Player", position="F", experience=0),
                ],
            ),
            source_url="https://www.espn.com/wnba/team/roster/_/name/ind",
        )
        package = build(
            base,
            [],
            [page],
            source_as_of="2026-08-25",
            cutoff_date="2026-08-23",
        )

        with tempfile.TemporaryDirectory() as directory:
            outputs = write(package, [page], Path(directory), snapshot_date="2026-08-25")
            self.assertEqual(
                sorted(path.name for path in outputs.values()),
                [
                    "espn_roster_pages_2026-08-25.json",
                    "player_core_2026-08-25.pending.csv",
                    "roster_refresh_changes_2026-08-25.csv",
                    "roster_refresh_manifest_2026-08-25.json",
                    "roster_refresh_review_2026-08-25.md",
                ],
            )
            manifest = json.loads(outputs["manifest"].read_text())
            self.assertEqual(manifest["candidate_rows"], 2)
            self.assertEqual(len(manifest["artifacts"]["player_core_pending"]["sha256"]), 64)
            snapshot = json.loads(outputs["source_snapshot"].read_text())
            self.assertEqual(snapshot["teams"][0]["team_id"], "5")
            self.assertEqual(snapshot["teams"][0]["players"][1]["athlete_id"], "106")
            report = outputs["review_report"].read_text()
            self.assertIn("Review status: **pending**", report)
            self.assertIn("New Player", report)
            self.assertIn("new active identities require eligibility review", report)

    def test_promotion_resolves_departure_statuses_and_adds_reviewed_roster_only_eligibility(self):
        _, build, parse, promote, _ = roster_refresh_api()
        base = pd.DataFrame(
            [
                existing_player("101", "Returning Player", "5"),
                existing_player("102", "Injured Player", "5", position="F"),
                existing_player("103", "Waived Player", "11", position="F"),
            ]
        )
        page = parse(
            espn_page(
                "5",
                "Indiana Fever",
                [
                    athlete("101", "Returning Player"),
                    athlete("106", "New Player", position="F", experience=0),
                ],
            ),
            source_url="https://www.espn.com/wnba/team/roster/_/name/ind",
        )
        package = build(
            base,
            [],
            [page],
            source_as_of="2026-08-25",
            cutoff_date="2026-08-23",
        )
        eligibility = pd.DataFrame(
            [
                {
                    "player_id": "p101",
                    "player_name": "Returning Player",
                    "espn_athlete_id": "101",
                    "espn_player_name": "Returning Player",
                    "team_abbreviation": "IND",
                    "eligibility_type": "experience_le_3",
                    "date_of_birth": "2003-01-02T08:00Z",
                    "age_on_cutoff": 23,
                    "experience_years": 1,
                    "eligible_flag": True,
                    "active": True,
                    "status_type": "active",
                    "review_status": "reviewed",
                    "reviewed_by": "Reviewer",
                    "reviewed_at": "2026-08-22",
                    "source_system": "ESPN",
                    "source_url": "https://example.test/101",
                    "source_snapshot_path": "old.csv",
                    "source_snapshot_sha256": "a" * 64,
                    "source_as_of": "2026-08-22",
                    "identity_match_method": "normalized_full_name_exact",
                }
            ]
        )
        crosswalk = pd.DataFrame(
            [
                {
                    "normalized_name": "returningplayer",
                    "player_id": "p101",
                    "pbpstats_player_name": "Returning Player",
                    "team_abbreviation": "IND",
                    "latest_game_date": "2026-08-20",
                    "espn_athlete_id": "101",
                    "espn_player_name": "Returning Player",
                    "experience_years": 1,
                    "source_url": "https://example.test/101",
                    "match_status": "matched",
                    "match_method": "normalized_full_name_exact",
                    "exclusion_reason": "",
                }
            ]
        )
        standings = pd.DataFrame(
            [
                {"team_id": "5", "team_abbreviation": "IND"},
                {"team_id": "11", "team_abbreviation": "PHX"},
            ]
        )

        promoted = promote(
            package.player_core,
            package.changes,
            eligibility,
            crosswalk,
            standings,
            departure_decisions={
                "102": {
                    "status_type": "inactive",
                    "active": False,
                    "current_team_id": "5",
                    "source_url": "https://example.test/injury",
                },
                "103": {
                    "status_type": "free-agent",
                    "active": False,
                    "current_team_id": "",
                    "source_url": "https://example.test/buyout",
                },
            },
            source_path="analysis/role_fulfillment_matrix/data/live_inputs/player_core_2026.csv",
            source_sha256="b" * 64,
            source_as_of="2026-08-25",
            cutoff_date="2026-08-23",
            reviewed_by="Krystal Beasley",
            reviewed_at="2026-08-25",
        )

        core = promoted.player_core.set_index("athlete_id")
        self.assertEqual(core.loc["102", "status_type"], "inactive")
        self.assertEqual(core.loc["102", "current_team_id"], "5")
        self.assertEqual(core.loc["103", "status_type"], "free-agent")
        self.assertEqual(core.loc["103", "current_team_id"], "")
        self.assertFalse(core["status_type"].eq("pending-roster-review").any())

        added = promoted.eligibility.set_index("player_id").loc["espn:106"]
        self.assertEqual(added["player_name"], "New Player")
        self.assertEqual(added["team_abbreviation"], "IND")
        self.assertEqual(added["experience_years"], 0)
        self.assertTrue(added["eligible_flag"])
        self.assertEqual(added["review_status"], "reviewed")
        self.assertEqual(added["source_snapshot_sha256"], "b" * 64)
        crosswalk_added = promoted.crosswalk.set_index("player_id").loc["espn:106"]
        self.assertEqual(crosswalk_added["match_status"], "source_only")
        self.assertEqual(crosswalk_added["exclusion_reason"], "no_pbpstats_game_record")
        self.assertEqual(set(promoted.changes["review_status"]), {"reviewed"})
        self.assertEqual(promoted.quality["new_eligibility_rows"], 1)
        self.assertEqual(promoted.quality["unresolved_departures"], 0)


class RosterRefreshCommandTest(unittest.TestCase):
    def test_builds_review_package_from_explicit_downloaded_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            base_path = work / "base.csv"
            page_path = work / "ind.html"
            output_path = work / "review"
            pd.DataFrame([existing_player("101", "Returning Player", "5")]).to_csv(
                base_path, index=False
            )
            page_path.write_text(
                espn_page("5", "Indiana Fever", [athlete("101", "Returning Player")])
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_rfm_roster_refresh.py"),
                    "--base",
                    str(base_path),
                    "--page",
                    f"ind={page_path}",
                    "--source-as-of",
                    "2026-08-25",
                    "--cutoff-date",
                    "2026-08-23",
                    "--output-directory",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_path / "roster_refresh_manifest_2026-08-25.json").read_text()
            )
            self.assertEqual(manifest["team_pages"], 1)
            self.assertEqual(manifest["current_active_players"], 1)
            self.assertIn("review package written", result.stdout.lower())

    def test_promotes_an_approved_package_without_mutating_pending_evidence(self):
        _, build, parse, _, write = roster_refresh_api()
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            review = work / "review"
            page = parse(
                espn_page(
                    "5",
                    "Indiana Fever",
                    [athlete("106", "New Player", position="F", experience=0)],
                ),
                source_url="https://www.espn.com/wnba/team/roster/_/name/ind",
            )
            package = build(
                pd.DataFrame([existing_player("102", "Injured Player", "5")]),
                [],
                [page],
                source_as_of="2026-08-25",
                cutoff_date="2026-08-23",
            )
            outputs = write(package, [page], review, snapshot_date="2026-08-25")
            pending_hash = outputs["player_core_pending"].read_bytes()
            eligibility_path = work / "eligibility.csv"
            crosswalk_path = work / "crosswalk.csv"
            standings_path = work / "standings.csv"
            decisions_path = work / "decisions.json"
            base_output = work / "live" / "player_core.csv"
            pd.DataFrame(columns=[
                "player_id", "player_name", "espn_athlete_id", "espn_player_name",
                "team_abbreviation", "eligibility_type", "date_of_birth", "age_on_cutoff",
                "experience_years", "eligible_flag", "active", "status_type",
                "review_status", "reviewed_by", "reviewed_at", "source_system",
                "source_url", "source_snapshot_path", "source_snapshot_sha256",
                "source_as_of", "identity_match_method",
            ]).to_csv(eligibility_path, index=False)
            pd.DataFrame(columns=[
                "normalized_name", "player_id", "pbpstats_player_name", "team_abbreviation",
                "latest_game_date", "espn_athlete_id", "espn_player_name",
                "experience_years", "source_url", "match_status", "match_method",
                "exclusion_reason",
            ]).to_csv(crosswalk_path, index=False)
            pd.DataFrame([
                {"team_id": "5", "team_abbreviation": "IND"}
            ]).to_csv(standings_path, index=False)
            decisions_path.write_text(json.dumps({
                "reviewed_by": "Krystal Beasley",
                "reviewed_at": "2026-08-25",
                "departure_decisions": {
                    "102": {
                        "status_type": "inactive",
                        "active": False,
                        "current_team_id": "5",
                        "source_url": "https://example.test/injury",
                    }
                },
            }))

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "promote_rfm_roster_refresh.py"),
                    "--review-directory", str(review),
                    "--base-output", str(base_output),
                    "--eligibility", str(eligibility_path),
                    "--crosswalk", str(crosswalk_path),
                    "--standings", str(standings_path),
                    "--decisions", str(decisions_path),
                    "--source-as-of", "2026-08-25",
                    "--cutoff-date", "2026-08-23",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(outputs["player_core_pending"].read_bytes(), pending_hash)
            promoted = pd.read_csv(base_output, dtype=str, keep_default_na=False)
            self.assertEqual(
                promoted.set_index("athlete_id").loc["102", "status_type"],
                "inactive",
            )
            manifest = json.loads(
                (review / "roster_refresh_promotion_manifest_2026-08-25.json").read_text()
            )
            self.assertEqual(manifest["review_status"], "approved")
            self.assertTrue(manifest["promotion_ready"])
            self.assertEqual(manifest["quality"]["new_eligibility_rows"], 1)
            self.assertIn("promotion package written", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
