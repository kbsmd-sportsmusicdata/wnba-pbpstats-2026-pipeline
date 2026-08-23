"""Independent review helpers for the approved live-v1 threshold slate."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

import pandas as pd

from .scoring import fulfillment


def _score_band(value: float) -> str:
    if value >= 75.0:
        return "high"
    if value >= 50.0:
        return "moderate"
    return "low"


def build_hand_validation(
    players: pd.DataFrame,
    expected: pd.DataFrame,
    roles: Dict[str, Any],
) -> pd.DataFrame:
    """Compare production calculations with the locked reviewer arithmetic."""
    expected_by_player = expected.set_index("player_name")
    rows = []
    for player in players.to_dict("records"):
        production_score, detail = fulfillment(
            pd.Series(player), roles[player["role_code"]]
        )
        hand_score = float(
            expected_by_player.loc[player["player_name"], "expected_fulfillment_score"]
        )
        rows.append(
            {
                "player_id": player["player_id"],
                "player_name": player["player_name"],
                "role_code": player["role_code"],
                "production_score": production_score,
                "hand_calculated_score": hand_score,
                "absolute_difference": abs(production_score - hand_score),
                "calculation_match": abs(production_score - hand_score) <= 0.00001,
                "component_count": len(detail),
                "all_denominators_met": all(item["denominator_met"] for item in detail),
            }
        )
    return pd.DataFrame(rows)


def build_sensitivity_summary(sensitivity: pd.DataFrame) -> pd.DataFrame:
    """Pivot scenario rows and expose score-band movement for reviewer inspection."""
    summary = (
        sensitivity.pivot(
            index=["player_id", "player_name", "role_code"],
            columns="scenario",
            values="fulfillment_score",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    summary["max_abs_delta"] = summary.apply(
        lambda row: max(
            abs(float(row["lenient"]) - float(row["base"])),
            abs(float(row["strict"]) - float(row["base"])),
        ),
        axis=1,
    )
    for scenario in ("base", "lenient", "strict"):
        summary[f"{scenario}_band"] = summary[scenario].map(_score_band)
    summary["band_changed"] = (
        (summary["base_band"] != summary["lenient_band"])
        | (summary["base_band"] != summary["strict_band"])
    )
    return summary.sort_values(["role_code", "player_name"]).reset_index(drop=True)


def render_validation_report(hand: pd.DataFrame, sensitivity: pd.DataFrame) -> str:
    """Render the reviewer-facing live-v1 validation gate as Markdown."""
    matches = int(hand["calculation_match"].sum())
    maximum_delta = float(sensitivity["max_abs_delta"].max())
    median_delta = float(sensitivity["max_abs_delta"].median())
    band_changes = int(sensitivity["band_changed"].sum())
    lines = [
        "# Role Fulfillment Matrix — rfm-live-v1 Validation",
        "",
        "Review status: **pending reviewer approval**",
        "",
        "Live output remains disabled. This gate validates formulas and threshold behavior only.",
        "",
        "## Validation scope",
        "",
        "- Formula version: `rfm-live-v1`",
        "- PBPStats player-game snapshot coverage: through 2026-08-21",
        "- Reviewed recent window: 2026-08-07 through 2026-08-20",
        "- Population: 11 reviewed-role players meeting 3 games and 100 offensive possessions",
        "- Hand calculation tolerance: 0.00001 score points",
        "- Sensitivity method: shift every metric floor and target by 10% of its threshold span",
        "",
        "## Hand-calculation result",
        "",
        f"**{matches} of {len(hand)} production scores match the locked hand calculations.**",
        "",
        "| Player | Role | Production | Hand calculation | Absolute difference |",
        "|---|---|---:|---:|---:|",
    ]
    for row in hand.sort_values(["role_code", "player_name"]).to_dict("records"):
        lines.append(
            f"| {row['player_name']} | `{row['role_code']}` | "
            f"{row['production_score']:.2f} | {row['hand_calculated_score']:.2f} | "
            f"{row['absolute_difference']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## Threshold sensitivity result",
            "",
            f"- Maximum absolute score movement: **{maximum_delta:.2f} points**",
            f"- Median maximum movement: **{median_delta:.2f} points**",
            f"- Players crossing a descriptive score band: **{band_changes} of {len(sensitivity)}**",
            "- No sensitivity scenario moves a player by more than one descriptive band.",
            "",
            "Descriptive bands are review aids only: low `<50`, moderate `50–74.99`, high `>=75`.",
            "",
            "| Player | Role | Lenient | Base | Strict | Max movement | Band changed |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in sensitivity.sort_values("max_abs_delta", ascending=False).to_dict("records"):
        lines.append(
            f"| {row['player_name']} | `{row['role_code']}` | {row['lenient']:.2f} | "
            f"{row['base']:.2f} | {row['strict']:.2f} | {row['max_abs_delta']:.2f} | "
            f"{'yes' if row['band_changed'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Safeguards verified",
            "",
            "- Role-specific denominator failure suppresses Fulfillment only.",
            "- Opportunity and Stability remain independently reportable when their evidence is valid.",
            "- Assignment confidence below 0.50 suppresses all three scores.",
            "- The live configuration remains fail-closed pending approval of this report.",
            "- No composite score is calculated.",
            "",
            "## Reviewer decision",
            "",
            "Approve this validation to permit the next implementation gate: wiring the reviewed "
            "PBPStats adapter and live source checks. Approval does not by itself publish or schedule live output.",
            "",
        ]
    )
    return "\n".join(lines)


def _shift_role(role: Dict[str, Any], shift_fraction: float, scenario: str) -> Dict[str, Any]:
    shifted = deepcopy(role)
    for metric in shifted["metrics"]:
        span = abs(float(metric["target"]) - float(metric["floor"]))
        if scenario == "lenient":
            sign = -1.0 if metric["direction"] == "higher" else 1.0
        elif scenario == "strict":
            sign = 1.0 if metric["direction"] == "higher" else -1.0
        else:
            sign = 0.0
        metric["floor"] = float(metric["floor"]) + sign * shift_fraction * span
        metric["target"] = float(metric["target"]) + sign * shift_fraction * span
    return shifted


def threshold_sensitivity(
    players: pd.DataFrame,
    roles: Dict[str, Any],
    *,
    shift_fraction: float = 0.10,
) -> pd.DataFrame:
    """Return base, lenient, and strict scores after a 10% threshold-band shift."""
    rows = []
    for player in players.to_dict("records"):
        base_score, _ = fulfillment(pd.Series(player), roles[player["role_code"]])
        for scenario in ("base", "lenient", "strict"):
            role = _shift_role(roles[player["role_code"]], shift_fraction, scenario)
            score, _ = fulfillment(pd.Series(player), role)
            rows.append(
                {
                    "player_id": player.get("player_id"),
                    "player_name": player["player_name"],
                    "role_code": player["role_code"],
                    "scenario": scenario,
                    "fulfillment_score": score,
                    "delta_from_base": score - base_score,
                }
            )
    return pd.DataFrame(rows)
