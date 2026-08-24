#!/usr/bin/env python3
"""Run the explicitly approved Role Fulfillment Matrix live build manually."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from role_fulfillment_matrix.data_sources import load_config, resolve_path
from role_fulfillment_matrix.outputs import build_outputs


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    ROOT / "analysis" / "role_fulfillment_matrix" / "config" / "live_config.json"
)


def build(
    *,
    config_path: Path = DEFAULT_CONFIG,
    runs_root: Path | None = None,
    run_id: str | None = None,
) -> Dict[str, Any]:
    config = load_config(config_path)
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{6}Z", run_id):
        raise ValueError("manual live run id must use YYYY-MM-DDTHHMMSSZ")
    base_root = resolve_path(runs_root or config["output_root"])
    output_root = base_root / "runs" / run_id
    if output_root.exists():
        raise FileExistsError(f"manual live run already exists: {output_root}")
    config["output_root"] = str(output_root)
    config["manual_run_id"] = run_id
    return build_outputs(config)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--runs-root", type=Path, default=None)
    parser.add_argument("--run-id", type=str, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build(
        config_path=args.config,
        runs_root=args.runs_root,
        run_id=args.run_id,
    )
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
                "manual_run_id": manifest["manual_run_id"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
