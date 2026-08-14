#!/usr/bin/env python3
"""Build the WNBA 2026 team identity shift analysis.

Answers two questions for every team: has the way it plays actually changed since earlier
in the season, and did the change help or hurt. Built on the snapshot window panel, which
supplies the time dimension the PBPStats season totals lack.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from team_identity_shift.data_sources import (
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
from team_identity_shift.decomposition import build_decomposition_table
from team_identity_shift.schedule_context import build_period_schedule_context, schedule_deltas
from team_identity_shift.shift import apply_schedule_adjustment, build_shift_table, totals_columns_for
from team_identity_shift.style import build_style_frame, dimension_deltas, league_scales


def output_paths(output_root: Path) -> Dict[str, Path]:
    processed = output_root / "data" / "processed"
    return {
        "periods": processed / "team_style_periods_2026.csv",
        "deltas": processed / "team_shift_dimension_deltas_2026.csv",
        "shift": processed / "team_identity_shift_2026.csv",
        "decomposition": processed / "team_shift_decomposition_2026.csv",
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

    panel = sources.team_window_panel
    dimensions = list(config.get("style_dimensions", []))
    periods_config = config.get("periods", {})
    recent_games = int(periods_config.get("recent_games", 10))
    min_baseline_games = int(periods_config.get("min_baseline_games", 8))

    row_counts: Dict[str, int] = {}
    stats: Dict[str, Any] = {"recent_games_target": recent_games, "style_dimensions": len(dimensions)}

    if panel.empty:
        stats["status"] = "window_panel_missing"
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

    period_frame, season_frame, skipped = build_style_frame(
        panel,
        dimensions=dimensions,
        recent_games=recent_games,
        min_baseline_games=min_baseline_games,
    )
    scales = league_scales(season_frame, dimensions)
    deltas = dimension_deltas(period_frame, scales, dimensions)

    shift = build_shift_table(
        panel,
        deltas,
        period_frame,
        dimensions=dimensions,
        scales=scales,
        totals_columns=totals_columns_for(panel),
        config=config,
    )
    decomposition = build_decomposition_table(period_frame)

    context = build_period_schedule_context(panel, sources.schedule, season_frame, recent_games=recent_games)
    context_deltas = schedule_deltas(context)
    if not shift.empty and not context_deltas.empty:
        shift = shift.merge(context_deltas, on="team_abbreviation", how="left")
    shift = apply_schedule_adjustment(shift, config)
    if not shift.empty and not decomposition.empty:
        shift = shift.merge(
            decomposition[["team_abbreviation", "shift_nature", "shot_quality_effect", "shot_making_effect"]],
            on="team_abbreviation",
            how="left",
        )

    row_counts["team_style_periods_2026.csv"] = _write(paths["periods"], period_frame)
    row_counts["team_shift_dimension_deltas_2026.csv"] = _write(paths["deltas"], deltas)
    row_counts["team_identity_shift_2026.csv"] = _write(paths["shift"], shift)
    row_counts["team_shift_decomposition_2026.csv"] = _write(paths["decomposition"], decomposition)

    stats.update(
        {
            "status": "ok",
            "teams_evaluated": int(shift["team_abbreviation"].nunique()) if not shift.empty else 0,
            "teams_skipped_insufficient_baseline": skipped,
            "significant_shifts": int((shift["shift_significance"] == "Significant").sum())
            if not shift.empty
            else 0,
            "moderate_shifts": int((shift["shift_significance"] == "Moderate").sum()) if not shift.empty else 0,
            "permutation_iterations": int(config.get("permutation_test", {}).get("iterations", 4000)),
            "max_decomposition_residual": float(decomposition["decomposition_residual"].abs().max())
            if not decomposition.empty
            else None,
            "schedule_context_teams": int(context_deltas["team_abbreviation"].nunique())
            if not context_deltas.empty
            else 0,
            "league_scales": {k: (float(v) if pd.notna(v) else None) for k, v in scales.items()},
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
    lines = ["## Team Identity Shift", ""]
    if not paths["manifest"].exists():
        lines.append("No manifest found.")
        return "\n".join(lines)

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    stats = manifest.get("analysis_stats", {})
    lines.extend(
        [
            f"- Generated at: `{manifest.get('generated_at_utc')}`",
            f"- Teams evaluated: `{stats.get('teams_evaluated')}`",
            f"- Recent period: last `{stats.get('recent_games_target')}` games",
            f"- Significant shifts: `{stats.get('significant_shifts')}` | Moderate: `{stats.get('moderate_shifts')}`",
            "",
        ]
    )

    if paths["shift"].exists():
        shift = pd.read_csv(paths["shift"])
        if not shift.empty:
            lines.extend(
                [
                    "### Largest Identity Shifts",
                    "",
                    "| Rank | Team | Shift (L1) | vs noise | Significance | Net Δ | Adj. net Δ | Direction | Nature |",
                    "| ---: | --- | ---: | ---: | --- | ---: | ---: | --- | --- |",
                ]
            )
            for _, row in shift.head(10).iterrows():
                lines.append(
                    f"| {int(row['shift_rank'])} | {row['team_abbreviation']} | {row['identity_shift_l1']:.2f} | "
                    f"{row.get('shift_vs_null_ratio', float('nan')):.2f}x | {row['shift_significance']} | "
                    f"{row['net_rating_delta']:+.1f} | {row.get('opponent_adjusted_net_rating_delta', float('nan')):+.1f} | "
                    f"{row['shift_direction']} | {row.get('shift_nature', '')} |"
                )
            lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the WNBA 2026 team identity shift analysis.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--window-panel-root", default=None)
    parser.add_argument("--sportsdataverse-data-root", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    config = apply_runtime_overrides(
        config,
        window_panel_root=args.window_panel_root,
        sportsdataverse_data_root=args.sportsdataverse_data_root,
        output_root=args.output_root,
    )
    build_outputs(config)
    summary = build_summary(resolve_output_root(config))
    print(summary)
    write_github_step_summary(summary)


if __name__ == "__main__":
    main()
