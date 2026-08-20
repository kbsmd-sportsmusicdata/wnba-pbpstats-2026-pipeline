#!/usr/bin/env python3
"""Build the WNBA 2026 Functional Depth Score.

Depth as a playoff variable: a team-level score from five components -- production distribution,
rotation trust and role redundancy (from the current per-game player layer), plus replacement
resilience and the performance floor (from the possession-impact bench net ratings). The two
possession-fed components carry an availability flag because that feed lags the game layer.

Outputs a headline table, the five sub-scores in long form, and the
``star dependency <-> distributed resilience`` roster strip.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from functional_depth.data_sources import (
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
from functional_depth.score import build_functional_depth, build_strip, components_long


def output_paths(output_root: Path) -> Dict[str, Path]:
    processed = output_root / "data" / "processed"
    return {
        "depth": processed / "functional_depth_2026.csv",
        "components": processed / "functional_depth_components_2026.csv",
        "strip": processed / "functional_depth_strip_2026.csv",
        "manifest": processed / "run_manifest_2026.json",
    }


def _write(path: Path, df: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def build_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    output_root = resolve_output_root(config)
    ensure_output_dirs(output_root)
    paths = output_paths(output_root)
    sources = load_sources(config)

    stats: Dict[str, Any] = {}
    row_counts: Dict[str, int] = {}

    depth = build_functional_depth(sources.player_game, sources.bench_net_rating, config)
    if depth.empty:
        stats["status"] = "player_game_missing"
    else:
        strip = build_strip(depth)
        components = components_long(depth)
        row_counts["functional_depth_2026.csv"] = _write(paths["depth"], depth)
        row_counts["functional_depth_components_2026.csv"] = _write(paths["components"], components)
        row_counts["functional_depth_strip_2026.csv"] = _write(paths["strip"], strip)
        stats.update(
            {
                "status": "ok",
                "teams_scored": int(len(depth)),
                "teams_with_possession_components": int(depth["possession_components_available"].sum()),
                "star_dependent": int((depth["depth_profile"] == "star_dependent").sum()),
                "distributed_resilience": int((depth["depth_profile"] == "distributed_resilience").sum()),
            }
        )

    manifest = {
        "run_id": utc_now_iso().replace(":", "").replace("-", ""),
        "generated_at_utc": utc_now_iso(),
        "season": config.get("season", 2026),
        "config_path": config.get("_config_path"),
        "config_hash": hash_config(config),
        "source_manifest": sources.source_manifest,
        "analysis_stats": stats,
        "outputs": row_counts,
    }
    paths["manifest"].write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    return manifest


def build_summary(output_root: Path) -> str:
    paths = output_paths(output_root)
    lines = ["## Functional Depth Score", ""]
    if not paths["manifest"].exists():
        lines.append("No manifest found.")
        return "\n".join(lines)

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    stats = manifest.get("analysis_stats", {})
    lines.extend(
        [
            f"- Generated at: `{manifest.get('generated_at_utc')}`",
            f"- Teams scored: `{stats.get('teams_scored')}` "
            f"(`{stats.get('teams_with_possession_components')}` with possession components)",
            "",
        ]
    )
    if paths["depth"].exists():
        depth = pd.read_csv(paths["depth"])
        if not depth.empty:
            lines.extend(
                [
                    "| Rank | Team | Depth | Profile | Top scorer share | Components |",
                    "| ---: | --- | ---: | --- | ---: | ---: |",
                ]
            )
            for _, row in depth.head(15).iterrows():
                share = row.get("top_scorer_share")
                share_text = f"{share:.0%}" if pd.notna(share) else "—"
                lines.append(
                    f"| {int(row['depth_rank'])} | {row['team_abbreviation']} | "
                    f"{row['functional_depth_score']:.1f} | {row.get('depth_profile', '')} | "
                    f"{share_text} | {int(row['components_used'])}/5 |"
                )
            lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the WNBA 2026 Functional Depth Score.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--game-layer-root", default=None)
    parser.add_argument("--possession-impact-root", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    config = apply_runtime_overrides(
        config,
        game_layer_root=args.game_layer_root,
        possession_impact_root=args.possession_impact_root,
        output_root=args.output_root,
    )
    build_outputs(config)
    summary = build_summary(resolve_output_root(config))
    print(summary)
    write_github_step_summary(summary)


if __name__ == "__main__":
    main()
