#!/usr/bin/env python3
"""Promote an explicitly approved RFM roster refresh package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from role_fulfillment_matrix.roster_refresh import (  # noqa: E402
    promote_roster_refresh_candidate,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _path_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _approval_report(manifest: dict, reviewed_changes: pd.DataFrame) -> str:
    lines = [
        "# Role Fulfillment Matrix — Base Roster Refresh Approval",
        "",
        "Review status: **approved**",
        "",
        f"Approved by: **{manifest['approved_by']}**",
        f"Approval date: **{manifest['approved_at']}**",
        f"Roster source as of: **{manifest['source_as_of']}**",
        f"Standings cutoff: **{manifest['standings_cutoff']}**",
        "",
        "## Promoted result",
        "",
        f"- Player-core rows: {manifest['quality']['player_core_rows']}",
        f"- Active players: {manifest['quality']['active_players']}",
        f"- Inactive rostered players: {manifest['quality']['inactive_players']}",
        f"- Free agents: {manifest['quality']['free_agents']}",
        f"- New reviewed eligibility rows: {manifest['quality']['new_eligibility_rows']}",
        f"- Reviewed eligibility rows: {manifest['quality']['eligibility_rows']}",
        f"- Identity crosswalk rows: {manifest['quality']['crosswalk_rows']}",
        "",
        "## Approved material changes",
        "",
        "| Change | Player | ESPN ID | Prior | Promoted | Review |",
        "|---|---|---:|---|---|---|",
    ]
    for row in reviewed_changes.itertuples(index=False):
        lines.append(
            f"| {row.change_type} | {row.player_name} | {row.athlete_id} | "
            f"{row.old_value or '—'} | {row.new_value or '—'} | {row.review_status} |"
        )
    lines.extend(
        [
            "",
            "## Safeguards",
            "",
            "- The pending review package remains unchanged.",
            "- The prior two-row player-core addendum remains historical evidence but is no longer "
            "a contributing live roster input.",
            "- Scheduling remains disabled; this approval does not authorize a manual live run.",
            "- Freshness, eligibility coverage, role coverage, and PBPStats adapter gates must be "
            "rerun after promotion.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-directory", type=Path, required=True)
    parser.add_argument("--base-output", type=Path, required=True)
    parser.add_argument("--eligibility", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--standings", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--source-as-of", required=True)
    parser.add_argument("--cutoff-date", required=True)
    args = parser.parse_args()

    snapshot_date = args.source_as_of
    pending_core_path = (
        args.review_directory / f"player_core_{snapshot_date}.pending.csv"
    )
    pending_changes_path = (
        args.review_directory / f"roster_refresh_changes_{snapshot_date}.csv"
    )
    source_snapshot_path = (
        args.review_directory / f"espn_roster_pages_{snapshot_date}.json"
    )
    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    inputs = {
        "pending_player_core": pd.read_csv(
            pending_core_path, dtype=str, keep_default_na=False
        ),
        "pending_changes": pd.read_csv(
            pending_changes_path, dtype=str, keep_default_na=False
        ),
        "eligibility": pd.read_csv(args.eligibility, dtype=str, keep_default_na=False),
        "crosswalk": pd.read_csv(args.crosswalk, dtype=str, keep_default_na=False),
        "standings": pd.read_csv(args.standings, dtype=str, keep_default_na=False),
    }
    promotion_kwargs = {
        "departure_decisions": decisions["departure_decisions"],
        "source_path": _path_label(args.base_output),
        "source_as_of": args.source_as_of,
        "cutoff_date": args.cutoff_date,
        "reviewed_by": decisions["reviewed_by"],
        "reviewed_at": decisions["reviewed_at"],
    }
    preliminary = promote_roster_refresh_candidate(
        inputs["pending_player_core"],
        inputs["pending_changes"],
        inputs["eligibility"],
        inputs["crosswalk"],
        inputs["standings"],
        source_sha256="0" * 64,
        **promotion_kwargs,
    )
    base_bytes = preliminary.player_core.to_csv(index=False).encode("utf-8")
    base_sha256 = _sha256_bytes(base_bytes)
    promoted = promote_roster_refresh_candidate(
        inputs["pending_player_core"],
        inputs["pending_changes"],
        inputs["eligibility"],
        inputs["crosswalk"],
        inputs["standings"],
        source_sha256=base_sha256,
        **promotion_kwargs,
    )

    args.base_output.parent.mkdir(parents=True, exist_ok=True)
    args.base_output.write_bytes(base_bytes)
    promoted.eligibility.to_csv(args.eligibility, index=False)
    promoted.crosswalk.to_csv(args.crosswalk, index=False)
    reviewed_changes_path = (
        args.review_directory
        / f"roster_refresh_changes_{snapshot_date}.reviewed.csv"
    )
    promoted.changes.to_csv(reviewed_changes_path, index=False)

    promotion_manifest_path = (
        args.review_directory
        / f"roster_refresh_promotion_manifest_{snapshot_date}.json"
    )
    approval_report_path = (
        args.review_directory / f"roster_refresh_approval_{snapshot_date}.md"
    )
    manifest = {
        "season": 2026,
        "review_status": "approved",
        "promotion_ready": True,
        "approved_by": decisions["reviewed_by"],
        "approved_at": decisions["reviewed_at"],
        "source_as_of": args.source_as_of,
        "standings_cutoff": args.cutoff_date,
        "quality": promoted.quality,
        "departure_decisions": decisions["departure_decisions"],
        "pending_evidence": {
            "player_core": {
                "path": _path_label(pending_core_path),
                "sha256": _sha256_file(pending_core_path),
            },
            "changes": {
                "path": _path_label(pending_changes_path),
                "sha256": _sha256_file(pending_changes_path),
            },
            "source_snapshot": {
                "path": _path_label(source_snapshot_path),
                "sha256": _sha256_file(source_snapshot_path),
            },
        },
        "promoted_outputs": {
            "player_core": {
                "path": _path_label(args.base_output),
                "sha256": _sha256_file(args.base_output),
            },
            "eligibility": {
                "path": _path_label(args.eligibility),
                "sha256": _sha256_file(args.eligibility),
            },
            "crosswalk": {
                "path": _path_label(args.crosswalk),
                "sha256": _sha256_file(args.crosswalk),
            },
            "reviewed_changes": {
                "path": _path_label(reviewed_changes_path),
                "sha256": _sha256_file(reviewed_changes_path),
            },
        },
        "retired_live_addendum": (
            "analysis/role_fulfillment_matrix/data/review/"
            "player_core_coverage_addendum_2026-08-24.csv"
        ),
        "execution_mode": "manual_only",
        "scheduling_enabled": False,
        "manual_live_run_authorized": False,
    }
    approval_report_path.write_text(
        _approval_report(manifest, promoted.changes), encoding="utf-8"
    )
    manifest["promoted_outputs"]["approval_report"] = {
        "path": _path_label(approval_report_path),
        "sha256": _sha256_file(approval_report_path),
    }
    promotion_manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Promotion package written to {args.review_directory}")
    print(f"player_core_sha256: {base_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
