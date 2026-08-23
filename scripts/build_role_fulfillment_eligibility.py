#!/usr/bin/env python3
"""Build the pending-review Role Fulfillment Matrix eligibility package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from role_fulfillment_matrix.eligibility import (
    build_eligibility_package,
    sha256_file,
    write_eligibility_package,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-core", required=True, help="ESPN player-core CSV snapshot.")
    parser.add_argument("--player-game", required=True, help="PBPStats player-game parquet or CSV.")
    parser.add_argument("--cutoff-date", required=True, help="Inclusive analysis cutoff, YYYY-MM-DD.")
    parser.add_argument("--source-as-of", required=True, help="Player-core source date, YYYY-MM-DD.")
    parser.add_argument(
        "--experience-max",
        type=int,
        default=3,
        help="Maximum ESPN experience_years value that remains eligible.",
    )
    parser.add_argument(
        "--output-dir",
        default="analysis/role_fulfillment_matrix/data/review",
        help="Isolated directory for pending eligibility, crosswalk, and manifest outputs.",
    )
    return parser.parse_args()


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"source does not exist: {path}")
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def main() -> None:
    args = parse_args()
    player_core_path = Path(args.player_core)
    player_game_path = Path(args.player_game)
    package = build_eligibility_package(
        read_table(player_core_path),
        read_table(player_game_path),
        cutoff_date=args.cutoff_date,
        source_as_of=args.source_as_of,
        source_path=str(player_core_path),
        source_sha256=sha256_file(player_core_path),
        experience_max=args.experience_max,
    )
    outputs = write_eligibility_package(package, Path(args.output_dir))
    print(json.dumps({
        "status": "pending_review_package_built",
        "eligibility_rows": int(len(package.eligibility)),
        "crosswalk_rows": int(len(package.crosswalk)),
        "eligible_players": package.manifest["eligible_players"],
        "coverage_pct": package.manifest["coverage_pct"],
        "review_status": package.manifest["review_status"],
        "live_scoring_status": package.manifest["live_scoring_status"],
        "outputs": outputs,
    }, indent=2))


if __name__ == "__main__":
    main()
