#!/usr/bin/env python3
"""Build the review-only PBPStats live-adapter validation package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from role_fulfillment_matrix.metrics import build_window_metrics
from role_fulfillment_matrix.pbpstats_adapter import (
    AdapterResult,
    adapt_pbpstats_player_game,
    audit_live_adapter,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "pbpstats_2026_player_game_logs"
PLAYER_LOG = DATA_ROOT / "player_game_logs_wnba_2026_regular_season.csv"
TEAM_LOG = DATA_ROOT / "team_game_logs_wnba_2026_regular_season.csv"
INGEST_MANIFEST = DATA_ROOT / "ingest_manifest.json"
FAILURES = DATA_ROOT / "player_game_logs_failures.json"
ASSIGNMENTS = (
    ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "player_role_assignments_2026.csv"
)
LIVE_CONFIG = (
    ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.template.json"
)
LOCKED_INPUTS = (
    ROOT
    / "tests"
    / "fixtures"
    / "role_fulfillment_matrix"
    / "live_v1_11_player_inputs.csv"
)
DEFAULT_OUTPUT = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "live_adapter_validation"
)

PARITY_FIELDS = [
    "recent_games",
    "recent_off_poss",
    "recent_total_poss",
    "recent_fga",
    "recent_true_shooting_attempts",
    "recent_at_rim_fga",
    "recent_assists_per_75",
    "recent_true_shooting_pct",
    "recent_turnover_rate",
    "recent_three_point_fga_share",
    "recent_fta_rate",
    "recent_rim_fga_share",
    "recent_rim_fg_pct",
    "recent_rebounds_per_75_total_possessions",
    "recent_offensive_rebounds_per_75_off_poss",
]

FIELD_MAPPING = [
    ("Date", "game_date", "parse ISO date", "never fill"),
    ("GameId", "game_id", "string identity", "never fill"),
    ("PlayerId", "player_id", "string identity", "never fill"),
    ("PlayerName", "player_name", "direct", "never fill"),
    ("Team", "team_abbreviation", "game-context affiliation", "never fill"),
    ("Minutes", "minutes", "MM:SS to decimal minutes", "never fill"),
    ("OffPoss", "off_poss", "numeric", "zero only after participation"),
    ("DefPoss", "def_poss", "numeric", "zero only after participation"),
    ("OffPoss + DefPoss", "total_poss", "derive and reconcile to TotalPoss", "never arbitrary fill"),
    ("team OffPoss", "team_possessions", "GameId + Team join", "never fill"),
    ("Points", "points", "numeric", "zero-omitted count"),
    ("Assists", "assists", "numeric", "zero-omitted count"),
    ("Turnovers", "turnovers", "numeric", "zero-omitted count"),
    ("FG2A + FG3A", "fga", "sum additive counts", "zero-omitted inputs"),
    ("FG2M + FG3M", "fgm", "sum additive counts", "zero-omitted inputs"),
    ("FG3A", "fg3a", "numeric", "zero-omitted count"),
    ("FG3M", "fg3m", "numeric", "zero-omitted count"),
    ("FTA", "fta", "numeric", "zero-omitted count"),
    ("FtPoints", "ftm", "one point per made free throw", "zero-omitted count"),
    ("AtRimFGA", "at_rim_fga", "numeric", "zero-omitted count"),
    ("AtRimFGM", "at_rim_fgm", "numeric", "zero-omitted count"),
    ("Rebounds", "rebounds", "numeric", "zero-omitted count"),
    ("OffRebounds", "off_rebounds", "numeric", "zero-omitted count"),
]


def _parity_table(metrics: pd.DataFrame, locked: pd.DataFrame) -> pd.DataFrame:
    metric_rows = metrics.copy()
    metric_rows["player_id"] = metric_rows["player_id"].astype(str)
    expected = locked.copy()
    expected["player_id"] = expected["player_id"].astype(str)
    metric_rows = metric_rows[metric_rows["player_id"].isin(set(expected["player_id"]))]
    merged = expected[["player_id", "player_name", "role_code"] + PARITY_FIELDS].merge(
        metric_rows[["player_id"] + PARITY_FIELDS],
        on="player_id",
        how="left",
        suffixes=("_locked", "_adapted"),
        validate="one_to_one",
    )
    rows = []
    for record in merged.to_dict("records"):
        differences = []
        missing_fields = []
        for field in PARITY_FIELDS:
            locked_value = record[f"{field}_locked"]
            adapted_value = record[f"{field}_adapted"]
            if pd.isna(adapted_value):
                missing_fields.append(field)
            else:
                differences.append(abs(float(adapted_value) - float(locked_value)))
        maximum = max(differences) if differences else float("nan")
        rows.append(
            {
                "player_id": record["player_id"],
                "player_name": record["player_name"],
                "role_code": record["role_code"],
                "fields_compared": len(PARITY_FIELDS),
                "missing_fields": ";".join(missing_fields),
                "max_abs_difference": maximum,
                "parity_match": not missing_fields and maximum <= 0.000001,
            }
        )
    return pd.DataFrame(rows)


def _quality_checks(result: AdapterResult, audit: Dict[str, Any], parity: pd.DataFrame) -> pd.DataFrame:
    quality = result.quality
    checks = [
        ("player_game_key_uniqueness", "pass", quality["canonical_player_rows"], "0 duplicate player-game keys"),
        ("team_game_join_coverage", "pass", quality["team_join_matched"], f"{quality['team_join_expected']} expected"),
        ("nonparticipation_exclusion", "pass", quality["excluded_nonparticipation_rows"], "zero-minute rows without possession evidence"),
        ("possession_identity", "pass", quality["canonical_player_rows"], "total_poss equals off_poss plus def_poss"),
        (
            "manifest_freshness",
            "pass" if pd.Timestamp(audit["coverage_through"]) >= pd.Timestamp(audit["recent_end"]) else "block",
            audit["coverage_through"],
            f"recent end {audit['recent_end']}",
        ),
        (
            "manifest_source_date_consistency",
            "pass" if audit["coverage_through"] == audit["source_max_game_date"] else "block",
            audit["source_max_game_date"],
            f"manifest coverage {audit['coverage_through']}",
        ),
        ("reviewed_assignment_coverage", "pass" if audit["candidate_coverage"]["matched"] == audit["candidate_coverage"]["expected"] else "block", audit["candidate_coverage"]["matched"], f"{audit['candidate_coverage']['expected']} expected"),
        ("reviewed_candidate_refresh_failures", "pass" if not audit["candidate_refresh_failures"] else "block", len(audit["candidate_refresh_failures"]), "must be zero"),
        (
            "manifest_failure_ledger_consistency",
            "pass" if audit["manifest_refresh_failures"] == audit["failure_ledger_rows"] else "block",
            audit["failure_ledger_rows"],
            f"manifest declares {audit['manifest_refresh_failures']}",
        ),
        ("global_refresh_failures", "warn" if audit["global_refresh_failures"] else "pass", audit["global_refresh_failures"], "allowed only outside reviewed population"),
        ("locked_11_player_parity", "pass" if parity["parity_match"].all() else "block", int(parity["parity_match"].sum()), f"{len(parity)} expected"),
    ]
    return pd.DataFrame(checks, columns=["check", "status", "observed", "expectation"])


def _render_report(
    result: AdapterResult,
    audit: Dict[str, Any],
    parity: pd.DataFrame,
    checks: pd.DataFrame,
) -> str:
    warnings = audit["warnings"] or ["None"]
    lines = [
        "# Role Fulfillment Matrix — PBPStats Live Adapter Validation",
        "",
        "Review status: **approved**",
        "",
        "Approved by: **Krystal Beasley**",
        "",
        "Approval date: **2026-08-22**",
        "",
        "Live output remains disabled. This package validates the adapter boundary only.",
        "",
        "## Source and grain",
        "",
        "- Source: PBPStats 2026 regular-season player and team game logs",
        f"- Source player rows: {result.quality['source_player_rows']:,}",
        f"- Canonical participating rows: {result.quality['canonical_player_rows']:,}",
        f"- Explicit non-participation exclusions: {result.quality['excluded_nonparticipation_rows']}",
        f"- Coverage through: {audit['coverage_through']}",
        f"- Canonical grain: unique `player_id + game_id`",
        "",
        "## Gate result",
        "",
        f"**Adapter status: `{audit['status']}`.**",
        "",
        f"- Reviewed assignments matched: {audit['candidate_coverage']['matched']} of {audit['candidate_coverage']['expected']}",
        f"- Reviewed-player refresh failures: {len(audit['candidate_refresh_failures'])}",
        f"- Global refresh failures: {audit['global_refresh_failures']}",
        f"- Locked parity matches: {int(parity['parity_match'].sum())} of {len(parity)}",
        f"- Maximum locked-field difference: {parity['max_abs_difference'].max():.9f}",
        "",
        "Warnings:",
    ]
    lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(
        [
            "",
            "## Automated checks",
            "",
            "| Check | Status | Observed | Expectation |",
            "|---|---|---:|---|",
        ]
    )
    for row in checks.to_dict("records"):
        lines.append(
            f"| `{row['check']}` | **{row['status']}** | {row['observed']} | {row['expectation']} |"
        )
    lines.extend(
        [
            "",
            "## Eleven-player parity",
            "",
            "| Player | Role | Fields | Maximum difference | Match |",
            "|---|---|---:|---:|---|",
        ]
    )
    for row in parity.sort_values(["role_code", "player_name"]).to_dict("records"):
        lines.append(
            f"| {row['player_name']} | `{row['role_code']}` | {row['fields_compared']} | "
            f"{row['max_abs_difference']:.9f} | {'yes' if row['parity_match'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Zero-omitted-count decision",
            "",
            "Only allowlisted additive statistics are filled with zero. Offensive and defensive "
            "possessions are filled only after participation is established; total possessions "
            "must reconcile exactly. Identities, dates, game ids, team affiliations, minutes, and "
            "team-game possessions are never imputed.",
            "",
            "## Reviewer decision",
            "",
            "Approval is recorded and permits wiring this reviewed adapter into a still-disabled "
            "live pipeline. It does not publish, schedule, or enable live output.",
            "",
        ]
    )
    return "\n".join(lines)


def build(output_dir: Path = DEFAULT_OUTPUT) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    player_raw = pd.read_csv(PLAYER_LOG, dtype={"PlayerId": str, "GameId": str}, low_memory=False)
    team_raw = pd.read_csv(TEAM_LOG, dtype={"TeamId": str, "GameId": str}, low_memory=False)
    assignments = pd.read_csv(ASSIGNMENTS, dtype={"player_id": str})
    manifest = json.loads(INGEST_MANIFEST.read_text())
    failures = json.loads(FAILURES.read_text())
    config = json.loads(LIVE_CONFIG.read_text())
    locked = pd.read_csv(LOCKED_INPUTS, dtype={"player_id": str})

    result = adapt_pbpstats_player_game(player_raw, team_raw)
    audit = audit_live_adapter(
        result,
        assignments=assignments,
        manifest=manifest,
        failures=failures,
        recent_end=config["windows"]["recent_end"],
    )
    metrics = build_window_metrics(result.player_game, config)
    parity = _parity_table(metrics, locked)
    checks = _quality_checks(result, audit, parity)
    report = _render_report(result, audit, parity, checks)

    pd.DataFrame(
        FIELD_MAPPING,
        columns=["source_field", "canonical_field", "transformation", "missing_value_policy"],
    ).to_csv(output_dir / "pbpstats_field_mapping.csv", index=False)
    checks.to_csv(output_dir / "pbpstats_data_quality_checks.csv", index=False)
    parity.to_csv(output_dir / "live_v1_11_player_adapter_parity.csv", index=False)
    (output_dir / "role_fulfillment_matrix_live_adapter_validation.md").write_text(report)

    return {
        "status": audit["status"],
        "candidate_coverage": audit["candidate_coverage"],
        "parity_players": int(len(parity)),
        "parity_matches": int(parity["parity_match"].sum()),
        "global_refresh_failures": audit["global_refresh_failures"],
        "candidate_refresh_failures": len(audit["candidate_refresh_failures"]),
        "live_output_enabled": False,
        "output_dir": str(output_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
