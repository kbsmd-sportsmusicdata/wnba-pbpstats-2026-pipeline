#!/usr/bin/env python3
"""Build WNBA 2026 possession-level impact metrics.

Estimates RAPM from every possession rather than from scoring events alone, and computes
bench and clutch net ratings from the same source. All three were previously unavailable
for want of validated possession/stint data.

The possession feed lags the rest of the pipeline, so every output carries a
`coverage_through` column stating the last game date it reflects.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from possession_impact.data_sources import (
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
from possession_impact.design import (
    attach_bench_counts,
    attach_home_flag,
    attach_score_state,
    build_design_matrix,
    derive_starters,
    player_index,
    possession_counts,
    prepare_possessions,
)
from possession_impact.net_ratings import (
    attach_player_labels,
    attach_team_labels,
    build_bench_net_rating,
    build_clutch_net_rating,
)
from possession_impact.rapm import build_rapm_table, cross_validate_alpha, fit_rapm


def output_paths(output_root: Path) -> Dict[str, Path]:
    processed = output_root / "data" / "processed"
    return {
        "rapm": processed / "rapm_player_2026.csv",
        "bench": processed / "bench_net_rating_2026.csv",
        "clutch": processed / "clutch_net_rating_2026.csv",
        "cv": processed / "rapm_alpha_cv_2026.csv",
        "manifest": processed / "run_manifest_2026.json",
    }


def _write(path: Path, df: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def coverage_window(possessions: pd.DataFrame, game_logs: pd.DataFrame) -> Dict[str, Any]:
    """Date the possession coverage.

    The possession feed carries game ids but no dates. The WNBA game logs share that id
    space, so they supply the window the outputs actually reflect.
    """
    window: Dict[str, Any] = {
        "coverage_games": int(possessions["game_id"].nunique()) if not possessions.empty else 0,
        "coverage_from": None,
        "coverage_through": None,
    }
    if possessions.empty or game_logs.empty or "game_date" not in game_logs.columns:
        return window

    covered = set(possessions["game_id"].astype(str))
    logs = game_logs[game_logs["game_id"].astype(str).isin(covered)]
    dates = pd.to_datetime(logs["game_date"], errors="coerce").dropna()
    if dates.empty:
        return window
    window["coverage_from"] = dates.min().date().isoformat()
    window["coverage_through"] = dates.max().date().isoformat()
    return window


def _stamp(table: pd.DataFrame, window: Dict[str, Any]) -> pd.DataFrame:
    """Put the coverage date on every row, so the lag travels with the file."""
    if table.empty:
        return table
    out = table.copy()
    out["coverage_through"] = window.get("coverage_through")
    return out


def compare_with_published_impact(rapm: pd.DataFrame, player_impact: pd.DataFrame) -> Dict[str, Any]:
    """Sanity-check against the pre-computed impact feed.

    Not a target to match: that feed's `rapm` column tracks DARKO filtered skill almost
    exactly, so it is a different estimator. A moderate positive correlation is reassuring;
    a negative or near-zero one would point at a bug here.
    """
    if rapm.empty or player_impact.empty or "rapm" not in player_impact.columns:
        return {"status": "unavailable"}

    left = rapm[["player_id", "rapm", "total_poss"]].copy()
    left["player_id"] = pd.to_numeric(left["player_id"], errors="coerce")
    right = player_impact[["player_id", "rapm"]].rename(columns={"rapm": "published_rapm"}).copy()
    right["player_id"] = pd.to_numeric(right["player_id"], errors="coerce")
    merged = left.merge(right, on="player_id", how="inner").dropna(subset=["rapm", "published_rapm"])
    if len(merged) < 3:
        return {"status": "insufficient_overlap", "players": int(len(merged))}

    reliable = merged[merged["total_poss"] >= 500]
    return {
        "status": "compared",
        "players": int(len(merged)),
        "correlation_all": round(float(merged["rapm"].corr(merged["published_rapm"])), 4),
        "correlation_reliable_only": round(float(reliable["rapm"].corr(reliable["published_rapm"])), 4)
        if len(reliable) >= 3
        else None,
        "note": "published rapm is DARKO-derived, so agreement is expected to be partial",
    }


def build_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    output_root = resolve_output_root(config)
    ensure_output_dirs(output_root)
    paths = output_paths(output_root)
    sources = load_sources(config)

    rapm_config = config.get("rapm", {})
    bench_config = config.get("bench", {})
    clutch_config = config.get("clutch", {})

    row_counts: Dict[str, int] = {}
    stats: Dict[str, Any] = {}

    possessions, counts = prepare_possessions(sources.possessions)
    stats["possession_counts"] = counts
    if possessions.empty:
        stats["status"] = "possessions_missing"
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

    window = coverage_window(possessions, sources.game_logs)
    stats["coverage"] = window

    possessions = attach_home_flag(possessions, sources.wnba_pbp)
    starters = derive_starters(possessions)
    possessions = attach_bench_counts(possessions, starters)
    possessions = attach_score_state(possessions)
    stats["home_flag_coverage"] = round(float(possessions["offense_is_home"].notna().mean()), 4)
    stats["bench_flag_coverage"] = round(float(possessions["offense_bench_on_court"].notna().mean()), 4)

    players = player_index(possessions)
    matrix, response, _ = build_design_matrix(possessions, players)
    alpha, cv_scores = cross_validate_alpha(
        matrix,
        response,
        possessions["game_id"].astype(str).to_numpy(),
        alpha_grid=rapm_config.get("alpha_grid", [1000, 4000, 16000]),
        folds=int(rapm_config.get("cv_folds", 5)),
        seed=int(rapm_config.get("random_seed", 20260812)),
    )
    raw_rapm, fit = fit_rapm(matrix, response, players, alpha=alpha)
    stats["rapm_fit"] = fit

    rapm = build_rapm_table(
        raw_rapm,
        possession_counts(possessions, players),
        min_possessions_reliable=int(rapm_config.get("min_possessions_reliable", 500)),
        min_possessions_reported=int(rapm_config.get("min_possessions_reported", 100)),
    )
    rapm = attach_player_labels(rapm, sources.player_features)
    stats["published_impact_comparison"] = compare_with_published_impact(rapm, sources.player_impact)

    bench = attach_team_labels(
        build_bench_net_rating(
            possessions, bench_heavy_threshold=int(bench_config.get("bench_heavy_threshold", 3))
        ),
        sources.team_features,
    )
    clutch = attach_team_labels(
        build_clutch_net_rating(
            possessions,
            max_seconds_remaining=float(clutch_config.get("max_seconds_remaining", 300)),
            min_period=int(clutch_config.get("min_period", 4)),
            max_score_margin=float(clutch_config.get("max_score_margin", 5)),
        ),
        sources.team_features,
    )

    row_counts["rapm_player_2026.csv"] = _write(paths["rapm"], _stamp(rapm, window))
    row_counts["bench_net_rating_2026.csv"] = _write(paths["bench"], _stamp(bench, window))
    row_counts["clutch_net_rating_2026.csv"] = _write(paths["clutch"], _stamp(clutch, window))
    row_counts["rapm_alpha_cv_2026.csv"] = _write(paths["cv"], cv_scores)

    stats["status"] = "ok"
    stats["players_reported"] = int(len(rapm))
    stats["players_reliable"] = int((rapm["sample_flag"] == "Reliable").sum()) if not rapm.empty else 0

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
    lines = ["## Possession Impact", ""]
    if not paths["manifest"].exists():
        lines.append("No manifest found.")
        return "\n".join(lines)

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    stats = manifest.get("analysis_stats", {})
    coverage = stats.get("coverage", {})
    fit = stats.get("rapm_fit", {})
    lines.extend(
        [
            f"- Generated at: `{manifest.get('generated_at_utc')}`",
            f"- **Coverage through: `{coverage.get('coverage_through')}`** "
            f"({coverage.get('coverage_games')} games from `{coverage.get('coverage_from')}`)",
            f"- Possessions used: `{stats.get('possession_counts', {}).get('usable_possessions')}`",
            f"- Ridge alpha (cross-validated): `{fit.get('alpha')}`",
            f"- Home-court advantage: `{round(fit.get('home_court_advantage', 0), 2)}` points per 100",
            f"- Players reported: `{stats.get('players_reported')}` "
            f"(`{stats.get('players_reliable')}` reliable)",
            "",
        ]
    )

    if paths["rapm"].exists():
        rapm = pd.read_csv(paths["rapm"])
        reliable = rapm[rapm["sample_flag"] == "Reliable"].head(10) if "sample_flag" in rapm.columns else rapm.head(10)
        if not reliable.empty:
            lines.extend(
                [
                    "### Top RAPM (reliable sample)",
                    "",
                    "| Player | Team | Poss | O-RAPM | D-RAPM | RAPM |",
                    "| --- | --- | ---: | ---: | ---: | ---: |",
                ]
            )
            for _, row in reliable.iterrows():
                lines.append(
                    f"| {row.get('player_name')} | {row.get('team_abbreviation')} | {int(row['total_poss'])} | "
                    f"{row['o_rapm']:+.2f} | {row['d_rapm']:+.2f} | {row['rapm']:+.2f} |"
                )
            lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WNBA 2026 possession-level impact metrics.")
    parser.add_argument("--config", required=True)
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
    build_outputs(config)
    summary = build_summary(resolve_output_root(config))
    print(summary)
    write_github_step_summary(summary)


if __name__ == "__main__":
    main()
