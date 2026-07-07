#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

from midseason_allstar_value_board.archetypes import assign_archetypes
from midseason_allstar_value_board.candidate_pool import build_box_workload, build_candidate_pool, build_position_lookup, build_team_context
from midseason_allstar_value_board.data_sources import (
    apply_runtime_overrides,
    ensure_output_dirs,
    hash_config,
    load_config,
    load_sources,
    resolve_output_root,
    stable_json_dumps,
    utc_now_iso,
    write_github_step_summary,
)
from midseason_allstar_value_board.editorial import export_editorial_assets, export_viz_tables
from midseason_allstar_value_board.scoring import build_metric_panel, build_value_board


STAGES = {"processed", "viz", "editorial", "all"}


def output_paths(output_root: Path) -> Dict[str, Path]:
    return {
        "candidate_pool": output_root / "data" / "processed" / "candidate_pool_2026.csv",
        "metric_panel": output_root / "data" / "processed" / "player_metric_panel_2026.csv",
        "value_board": output_root / "data" / "processed" / "allstar_value_board_2026.csv",
        "archetypes": output_root / "data" / "processed" / "player_archetypes_2026.csv",
        "manifest": output_root / "data" / "processed" / "run_manifest_2026.json",
    }


def build_processed(config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict]:
    output_root = resolve_output_root(config)
    dirs = ensure_output_dirs(output_root)
    sources = load_sources(config)
    thresholds = config.get("thresholds", {})
    as_of_date = str(config.get("as_of_date", "2026-midseason"))

    team_context = build_team_context(sources.team_features, sources.standings)
    position_lookup = build_position_lookup(sources.player_box, sources.player_season_stats)
    box_workload = build_box_workload(sources.player_box)
    candidate_pool = build_candidate_pool(
        sources.player_features,
        team_context,
        position_lookup,
        box_workload,
        thresholds,
        as_of_date=as_of_date,
    )
    metric_panel = build_metric_panel(sources.player_features, candidate_pool, team_context)
    value_board = build_value_board(metric_panel, config.get("weights", {}))
    archetypes = assign_archetypes(metric_panel, value_board)

    paths = output_paths(output_root)
    candidate_pool.to_csv(paths["candidate_pool"], index=False)
    metric_panel.to_csv(paths["metric_panel"], index=False)
    value_board.to_csv(paths["value_board"], index=False)
    archetypes.to_csv(paths["archetypes"], index=False)

    manifest = {
        "run_id": utc_now_iso().replace(":", "").replace("-", ""),
        "generated_at_utc": utc_now_iso(),
        "season": config.get("season", 2026),
        "as_of_date": as_of_date,
        "config_path": config.get("_config_path"),
        "config_hash": hash_config(config),
        "source_manifest": sources.source_manifest,
        "outputs": {
            "candidate_pool_2026.csv": len(candidate_pool),
            "player_metric_panel_2026.csv": len(metric_panel),
            "allstar_value_board_2026.csv": len(value_board),
            "player_archetypes_2026.csv": len(archetypes),
        },
    }
    paths["manifest"].write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    return candidate_pool, metric_panel, value_board, archetypes, manifest


def load_processed(output_root: Path) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = output_paths(output_root)
    missing = [str(path) for key, path in paths.items() if key != "manifest" and not path.exists()]
    if missing:
        raise FileNotFoundError(f"Processed outputs are required for this stage. Missing: {missing}")
    metric_panel = pd.read_csv(paths["metric_panel"])
    value_board = pd.read_csv(paths["value_board"])
    archetypes = pd.read_csv(paths["archetypes"])
    return metric_panel, value_board, archetypes


def build_viz(config: Dict) -> Dict[str, int]:
    output_root = resolve_output_root(config)
    dirs = ensure_output_dirs(output_root)
    metric_panel, value_board, archetypes = load_processed(output_root)
    return export_viz_tables(value_board, metric_panel, archetypes, dirs["viz"])


def build_editorial(config: Dict) -> Dict[str, int]:
    output_root = resolve_output_root(config)
    dirs = ensure_output_dirs(output_root)
    _, value_board, archetypes = load_processed(output_root)
    return export_editorial_assets(
        value_board,
        archetypes,
        dirs["editorial"],
        as_of_date=str(config.get("as_of_date", "2026-midseason")),
    )


def build_summary(output_root: Path) -> str:
    paths = output_paths(output_root)
    lines = ["## Midseason All-Star Value Board", ""]
    if paths["manifest"].exists():
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        lines.extend(
            [
                f"- Generated at: `{manifest.get('generated_at_utc')}`",
                f"- As of date: `{manifest.get('as_of_date')}`",
                "",
                "### Output Row Counts",
                "",
                "| Output | Rows |",
                "| --- | ---: |",
            ]
        )
        for name, rows in manifest.get("outputs", {}).items():
            lines.append(f"| {name} | {rows} |")
        lines.append("")
    if paths["value_board"].exists():
        board = pd.read_csv(paths["value_board"]).head(10)
        lines.extend(["### Top 10 Board", "", "| Rank | Player | Team | Score |", "| ---: | --- | --- | ---: |"])
        for _, row in board.iterrows():
            lines.append(
                f"| {int(row['overall_rank'])} | {row['player_name']} | {row['team_abbreviation']} | {row['allstar_value_score']:.1f} |"
            )
        lines.append("")
    return "\n".join(lines)


def run(config: Dict, stage: str) -> None:
    output_root = resolve_output_root(config)
    if stage in ("processed", "all"):
        build_processed(config)
    if stage in ("viz", "all"):
        build_viz(config)
    if stage in ("editorial", "all"):
        build_editorial(config)

    summary = build_summary(output_root)
    print(summary)
    write_github_step_summary(summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WNBA Midseason All-Star Value Board outputs.")
    parser.add_argument("--config", required=True, help="Path to All-Star Value Board JSON config.")
    parser.add_argument("--stage", choices=sorted(STAGES), default="all")
    parser.add_argument("--pbpstats-data-root", default=None)
    parser.add_argument("--sportsdataverse-data-root", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    config = apply_runtime_overrides(
        config,
        pbpstats_data_root=args.pbpstats_data_root,
        sportsdataverse_data_root=args.sportsdataverse_data_root,
        output_root=args.output_root,
    )
    run(config, args.stage)


if __name__ == "__main__":
    main()
