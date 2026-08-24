#!/usr/bin/env python3
"""Run the explicitly approved Role Fulfillment Matrix live build manually."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from role_fulfillment_matrix.data_sources import load_config
from role_fulfillment_matrix.outputs import build_outputs


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.json"
)


def build(
    *,
    config_path: Path = DEFAULT_CONFIG,
    output_root: Path | None = None,
) -> Dict[str, Any]:
    config = load_config(config_path)
    if output_root is not None:
        config["output_root"] = str(output_root)
    return build_outputs(config)


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
                "status": "live_build_complete",
                "mode": manifest["mode"],
                "players_scored": manifest["players_scored"],
                "live_scoring_status": manifest["live_scoring_status"],
                "live_output_enabled": manifest["live_output_enabled"],
                "execution_mode": manifest["execution_mode"],
                "scheduling_enabled": manifest["scheduling_enabled"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
