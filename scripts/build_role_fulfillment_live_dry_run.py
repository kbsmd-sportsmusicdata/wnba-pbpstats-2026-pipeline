#!/usr/bin/env python3
"""Build the isolated real-data Role Fulfillment Matrix dry-run review package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from role_fulfillment_matrix.data_sources import load_config
from role_fulfillment_matrix.outputs import build_outputs


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.template.json"
)


def _render_report(manifest: Dict[str, Any], funnel: pd.DataFrame) -> str:
    counts = manifest["funnel_counts"]
    audit = manifest["adapter_audit"]
    zero_filled = manifest["source_manifest"]["player_game"]["quality"][
        "zero_filled_cells"
    ]
    lines = [
        "# Role Fulfillment Matrix — Live Dry-Run Validation",
        "",
        "Review status: **pending reviewer approval**",
        "",
        "Live output remains disabled. This package exercises the approved real-data path only.",
        "",
        "## Run boundary",
        "",
        f"- Analysis mode: `{manifest['mode']}`",
        f"- Formula version: `{manifest['formula_version']}`",
        f"- Analysis cutoff: {manifest['analysis_cutoff_date']}",
        f"- Baseline window: {manifest['windows']['baseline_start']} through {manifest['windows']['baseline_end']}",
        f"- Recent window: {manifest['windows']['recent_start']} through {manifest['windows']['recent_end']}",
        f"- Players considered: {counts['players_considered']}",
        f"- Candidates included: {counts['candidates_included']}",
        f"- Players with all three scores: {manifest['players_scored']}",
        f"- End-to-end gate status: `{manifest['dry_run_gate_status']}`",
        "",
        "## Source gate",
        "",
        f"- PBPStats adapter status: `{audit['status']}`",
        f"- Reviewed assignment coverage: {audit['candidate_coverage']['matched']} of {audit['candidate_coverage']['expected']}",
        f"- Locked 11-player parity: {audit['locked_parity_matches']} of {audit['locked_parity_players']}",
        f"- Maximum parity difference: {audit['locked_parity_max_abs_difference']:.9f}",
        "- Locked parity window: "
        f"{audit['locked_parity_windows']['recent_start']} through "
        f"{audit['locked_parity_windows']['recent_end']}",
        f"- Zero-omitted cells filled: {sum(int(value) for value in zero_filled.values())} across allowlisted additive fields",
        f"- Reviewed-player refresh failures: {len(audit['candidate_refresh_failures'])}",
        f"- Global refresh failures: {audit['global_refresh_failures']}",
    ]
    if audit["warnings"]:
        lines.extend(["", "Warnings:"] + [f"- {item}" for item in audit["warnings"]])
    missing_eligibility = funnel[
        funnel["exclusion_reason"] == "eligibility_not_reviewed"
    ]
    missing_roles = funnel[
        funnel["exclusion_reason"] == "role_assignment_not_reviewed"
    ]
    deferred_inactive_roles = funnel[
        funnel["exclusion_reason"] == "inactive_role_review_deferred"
    ]
    assignment_mismatches = funnel[
        funnel["exclusion_reason"] == "role_assignment_team_mismatch"
    ]
    if (
        not missing_eligibility.empty
        or not missing_roles.empty
        or not assignment_mismatches.empty
    ):
        lines.extend(["", "## Current-candidate review blockers", ""])
        for row in missing_eligibility.to_dict("records"):
            lines.append(
                f"- {row['player_name']} ({row['team_abbreviation']}): reviewed eligibility row required."
            )
        for row in missing_roles.to_dict("records"):
            lines.append(
                f"- {row['player_name']} ({row['team_abbreviation']}): reviewed primary role assignment required."
            )
        for row in assignment_mismatches.to_dict("records"):
            lines.append(
                f"- {row['player_name']} ({row['team_abbreviation']}): reviewed role assignment belongs to another team."
            )
    if not deferred_inactive_roles.empty:
        lines.extend(["", "## Deferred inactive role reviews", ""])
        for row in deferred_inactive_roles.to_dict("records"):
            lines.append(
                f"- {row['player_name']} ({row['team_abbreviation']}): role assignment deferred while inactive; reactivation restores the review blocker."
            )
    lines.extend(
        [
            "",
            "## Remaining gate",
            "",
            "- Review candidate affiliation, sample status, scores, and evidence provenance.",
            "- Approval of this report is required before any explicit live-output enablement.",
            "- No schedule, commit, forecast-dashboard integration, or publishing occurs here.",
            "",
        ]
    )
    return "\n".join(lines)


def build(
    *,
    config_path: Path = DEFAULT_CONFIG,
    output_root: Path | None = None,
) -> Dict[str, Any]:
    config = load_config(config_path)
    if output_root is not None:
        config["output_root"] = str(output_root)
    manifest = build_outputs(config)
    review_root = Path(config["output_root"])
    if not review_root.is_absolute():
        review_root = ROOT / review_root
    review_root.mkdir(parents=True, exist_ok=True)
    funnel = pd.read_csv(
        review_root / "data" / "processed" / "candidate_funnel_2026.csv",
        dtype={"player_id": str},
    )
    report_path = review_root / "role_fulfillment_matrix_live_dry_run_validation.md"
    report_path.write_text(_render_report(manifest, funnel), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build(config_path=args.config, output_root=args.output_root)
    print(
        json.dumps(
            {
                "status": "live_dry_run_built",
                "mode": manifest["mode"],
                "players_scored": manifest["players_scored"],
                "live_scoring_status": manifest["live_scoring_status"],
                "live_output_enabled": manifest["live_output_enabled"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
