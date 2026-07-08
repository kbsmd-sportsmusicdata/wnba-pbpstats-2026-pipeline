#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

import pandas as pd

from midseason_team_grades.data_sources import (
    apply_runtime_overrides,
    ensure_output_dirs,
    hash_config,
    load_config,
    load_sources,
    resolve_output_root,
    stable_json_dumps,
    utc_now_iso,
)
from midseason_team_grades.eda import export_eda_bundle
from midseason_team_grades.metrics import (
    build_bench_player_game,
    build_bench_team_game,
    build_bench_team_summary,
    build_clutch_team_game,
    build_player_fit_profiles,
    build_player_midseason_impact,
    build_rapm_player,
    build_team_game_four_factors,
    build_team_grade_panel,
)


STAGES = {"core", "bench", "clutch", "rapm", "eda", "all"}


def output_paths(output_root: Path) -> Dict[str, Path]:
    processed = output_root / "data" / "processed"
    return {
        "four_factors": processed / "team_game_four_factors_2026.csv",
        "team_grade_panel": processed / "team_grade_panel_2026.csv",
        "bench_player_game": processed / "bench_player_game_2026.csv",
        "bench_team_game": processed / "bench_team_game_2026.csv",
        "bench_team_summary": processed / "bench_team_summary_2026.csv",
        "clutch_team_game": processed / "clutch_team_game_2026.csv",
        "player_midseason_impact": processed / "player_midseason_impact_2026.csv",
        "player_fit_profiles": processed / "player_fit_profiles_2026.csv",
        "rapm_player": processed / "rapm_player_2026.csv",
        "manifest": processed / "run_manifest_2026.json",
    }


def _write(path: Path, df: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def _read_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def build_outputs(config: Dict, stage: str) -> Dict:
    output_root = resolve_output_root(config)
    ensure_output_dirs(output_root)
    paths = output_paths(output_root)
    sources = load_sources(config)
    previous_manifest = {}
    if paths["manifest"].exists():
        previous_manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    row_counts: Dict[str, int] = dict(previous_manifest.get("outputs", {}))
    metric_status = {
        "vorp_status": "unavailable_exact_formula_required",
        "bench_net_rating_status": "not_calculated_requires_validated_possession_stints",
        "rapm_status": "not_requested",
    }
    metric_status.update(previous_manifest.get("metric_status", {}))

    if stage in {"core", "all"}:
        four = build_team_game_four_factors(sources.team_box)
        impact = build_player_midseason_impact(sources.allstar_board, sources.player_features)
        fit = build_player_fit_profiles(sources.player_features, sources.allstar_board)
        row_counts["team_game_four_factors_2026.csv"] = _write(paths["four_factors"], four)
        row_counts["player_midseason_impact_2026.csv"] = _write(paths["player_midseason_impact"], impact)
        row_counts["player_fit_profiles_2026.csv"] = _write(paths["player_fit_profiles"], fit)

    if stage in {"bench", "all"}:
        bench_players = build_bench_player_game(sources.player_box)
        bench_game = build_bench_team_game(sources.player_box, sources.team_box)
        bench_summary = build_bench_team_summary(bench_game)
        row_counts["bench_player_game_2026.csv"] = _write(paths["bench_player_game"], bench_players)
        row_counts["bench_team_game_2026.csv"] = _write(paths["bench_team_game"], bench_game)
        row_counts["bench_team_summary_2026.csv"] = _write(paths["bench_team_summary"], bench_summary)

    if stage in {"clutch", "all"}:
        clutch = build_clutch_team_game(sources.espn_pbp)
        row_counts["clutch_team_game_2026.csv"] = _write(paths["clutch_team_game"], clutch)

    if stage in {"rapm", "all"}:
        rapm, rapm_status = build_rapm_player(sources.wnba_stats_pbp, config)
        metric_status["rapm_status"] = rapm_status
        row_counts["rapm_player_2026.csv"] = _write(paths["rapm_player"], rapm)

    four = _read_optional(paths["four_factors"])
    bench_summary = _read_optional(paths["bench_team_summary"])
    team_grade = build_team_grade_panel(four, bench_summary, sources.team_features, sources.standings)
    row_counts["team_grade_panel_2026.csv"] = _write(paths["team_grade_panel"], team_grade)

    if stage in {"eda", "all"}:
        eda_counts = export_eda_bundle(output_root, row_counts)
        row_counts.update(eda_counts)

    manifest = {
        "run_id": utc_now_iso().replace(":", "").replace("-", ""),
        "generated_at_utc": utc_now_iso(),
        "season": config.get("season", 2026),
        "as_of_date": str(config.get("as_of_date", "2026-midseason")),
        "config_path": config.get("_config_path"),
        "config_hash": hash_config(config),
        "source_manifest": sources.source_manifest,
        "metric_status": metric_status,
        "outputs": row_counts,
    }
    paths["manifest"].write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    return manifest


def build_summary(output_root: Path) -> str:
    paths = output_paths(output_root)
    lines = ["## Midseason Team Grades", ""]
    if paths["manifest"].exists():
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        lines.extend(
            [
                f"- Generated at: `{manifest.get('generated_at_utc')}`",
                f"- As of date: `{manifest.get('as_of_date')}`",
                f"- VORP status: `{manifest.get('metric_status', {}).get('vorp_status')}`",
                f"- RAPM status: `{manifest.get('metric_status', {}).get('rapm_status')}`",
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
    if paths["team_grade_panel"].exists():
        panel = pd.read_csv(paths["team_grade_panel"]).head(10)
        if not panel.empty and {"team_grade_rank", "team_abbreviation", "team_grade_score"}.issubset(panel.columns):
            lines.extend(["### Top Team Grades", "", "| Rank | Team | Score |", "| ---: | --- | ---: |"])
            for _, row in panel.iterrows():
                lines.append(f"| {int(row['team_grade_rank'])} | {row['team_abbreviation']} | {row['team_grade_score']:.1f} |")
            lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WNBA midseason team grades datasets.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--stage", choices=sorted(STAGES), default="all")
    parser.add_argument("--sportsdataverse-data-root", default=None)
    parser.add_argument("--pbpstats-data-root", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    config = apply_runtime_overrides(
        config,
        sportsdataverse_data_root=args.sportsdataverse_data_root,
        pbpstats_data_root=args.pbpstats_data_root,
        output_root=args.output_root,
    )
    build_outputs(config, args.stage)
    print(build_summary(resolve_output_root(config)))


if __name__ == "__main__":
    main()
