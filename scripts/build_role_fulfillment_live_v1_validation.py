#!/usr/bin/env python3
"""Build the reviewer package for rfm-live-v1 without enabling live output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from role_fulfillment_matrix.validation import (
    build_hand_validation,
    build_sensitivity_summary,
    render_validation_report,
    threshold_sensitivity,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "data"
    / "review"
    / "live_v1_validation"
)
INPUTS = (
    ROOT
    / "tests"
    / "fixtures"
    / "role_fulfillment_matrix"
    / "live_v1_11_player_inputs.csv"
)
EXPECTED = INPUTS.with_name("live_v1_11_player_expected.csv")
ROLES = (
    ROOT
    / "analysis"
    / "role_fulfillment_matrix"
    / "config"
    / "role_definitions_live_v1.json"
)


def build(output_dir: Path = DEFAULT_OUTPUT) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    players = pd.read_csv(INPUTS, dtype={"player_id": str})
    expected = pd.read_csv(EXPECTED)
    roles = json.loads(ROLES.read_text())

    hand = build_hand_validation(players, expected, roles)
    sensitivity = build_sensitivity_summary(
        threshold_sensitivity(players, roles, shift_fraction=0.10)
    )
    report = render_validation_report(hand, sensitivity)

    hand.to_csv(output_dir / "hand_calculated_11_player_validation.csv", index=False)
    sensitivity.to_csv(output_dir / "threshold_sensitivity_11_player.csv", index=False)
    (output_dir / "role_fulfillment_matrix_live_v1_validation.md").write_text(report)

    return {
        "formula_version": "rfm-live-v1",
        "players_validated": int(len(hand)),
        "hand_calculation_matches": int(hand["calculation_match"].sum()),
        "maximum_sensitivity_delta": float(sensitivity["max_abs_delta"].max()),
        "band_changes": int(sensitivity["band_changed"].sum()),
        "review_status": "pending_reviewer_approval",
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
