#!/usr/bin/env python3
"""Build the standalone fixture-only Role Fulfillment Matrix prototype."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from role_fulfillment_matrix.data_sources import load_config
from role_fulfillment_matrix.outputs import build_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="analysis/role_fulfillment_matrix/config/fixture_config.json",
        help="Fixture config path. Live mode is intentionally blocked.",
    )
    parser.add_argument("--output-root", default=None, help="Optional isolated output root.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    if args.output_root:
        config["output_root"] = args.output_root
    manifest = build_outputs(config)
    print(json.dumps({
        "status": "fixture_prototype_built",
        "mode": manifest["mode"],
        "players_scored": manifest["players_scored"],
        "live_scoring_status": manifest["live_scoring_status"],
    }, indent=2))


if __name__ == "__main__":
    main()
