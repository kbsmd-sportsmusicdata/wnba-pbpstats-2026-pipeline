#!/usr/bin/env python3
"""Build the WNBA 2026 hidden-value watchlist.

Two questions, kept deliberately separate: which players are contributing more than their
role implies (underrated now), and which are improving fast enough to matter for September
(trending up). Both are scored against playoff-relevant skills rather than raw production.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

from hidden_value.board import build_board, build_component_long, fit_role_model
from hidden_value.data_sources import (
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
from hidden_value.features import (
    apply_eligibility,
    build_player_panel,
    build_playoff_fit,
    build_regression_upside,
    build_start_rate,
    percentile,
)
from hidden_value.game_form import build_game_trajectories
from hidden_value.trajectory import build_player_trajectories


def output_paths(output_root: Path) -> Dict[str, Path]:
    processed = output_root / "data" / "processed"
    return {
        "board": processed / "hidden_value_board_2026.csv",
        "trajectories": processed / "player_trajectory_2026.csv",
        "components": processed / "hidden_value_components_2026.csv",
        "manifest": processed / "run_manifest_2026.json",
    }


def _write(path: Path, df: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def _empty_manifest(config: Dict[str, Any], sources, stats: Dict[str, Any], path: Path) -> Dict[str, Any]:
    manifest = {
        "run_id": utc_now_iso().replace(":", "").replace("-", ""),
        "generated_at_utc": utc_now_iso(),
        "season": config.get("season", 2026),
        "config_path": config.get("_config_path"),
        "config_hash": hash_config(config),
        "source_manifest": sources.source_manifest,
        "analysis_stats": stats,
        "outputs": {},
    }
    path.write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    return manifest


def build_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    output_root = resolve_output_root(config)
    ensure_output_dirs(output_root)
    paths = output_paths(output_root)
    sources = load_sources(config)

    stats: Dict[str, Any] = {}
    if sources.player_features.empty:
        stats["status"] = "player_features_missing"
        return _empty_manifest(config, sources, stats, paths["manifest"])

    trajectory_config = config.get("trajectory", {})
    metrics = trajectory_config.get("metrics", [])
    shrinkage_constant = float(trajectory_config.get("shrinkage_constant", 6.0))
    # Prefer the true per-game layer for recent-form trajectory; fall back to the snapshot window
    # panel when the game layer is unavailable, so the board still builds.
    requested_source = trajectory_config.get("source", "game_layer")
    if requested_source == "game_layer" and not sources.player_game.empty:
        trajectories = build_game_trajectories(
            sources.player_game,
            metrics=metrics,
            recent_games=int(trajectory_config.get("recent_games", trajectory_config.get("recent_windows", 10))),
            min_games=int(trajectory_config.get("min_games", trajectory_config.get("min_windows", 4))),
            shrinkage_constant=shrinkage_constant,
        )
        trajectory_source = "game_layer"
    else:
        trajectories = build_player_trajectories(
            sources.player_window_panel,
            metrics=metrics,
            recent_windows=int(trajectory_config.get("recent_windows", 10)),
            min_windows=int(trajectory_config.get("min_windows", 4)),
            shrinkage_constant=shrinkage_constant,
        )
        trajectory_source = "window_panel" if requested_source == "game_layer" else requested_source
    stats["trajectory_source"] = trajectory_source
    start_rates = build_start_rate(sources.possessions)

    panel = build_player_panel(
        sources.player_features,
        sources.team_features,
        sources.rapm,
        start_rates,
        trajectories,
        sources.player_impact,
    )
    eligibility = config.get("eligibility", {})
    panel = apply_eligibility(
        panel,
        min_total_possessions=int(eligibility.get("min_total_possessions", 300)),
        min_games_played=int(eligibility.get("min_games_played", 8)),
        reliable_total_possessions=int(eligibility.get("reliable_total_possessions", 800)),
    )
    if panel.empty:
        stats["status"] = "no_eligible_players"
        return _empty_manifest(config, sources, stats, paths["manifest"])

    # RAPM is the better impact measure, but it covers fewer players and lags; on-court net
    # rating stands in where it is missing so the board is not silently narrowed.
    impact = pd.to_numeric(panel.get("rapm"), errors="coerce")
    fallback = pd.to_numeric(panel.get("on_court_net_rating"), errors="coerce")
    panel["impact_measure"] = impact.where(impact.notna(), fallback / 10.0)
    panel["impact_source"] = np.where(impact.notna(), "rapm", "on_court_net_rating")

    role_config = config.get("role_model", {})
    residual, role_diagnostics = fit_role_model(
        panel,
        impact_column="impact_measure",
        proxies=role_config.get("proxies", []),
        ridge_alpha=float(role_config.get("ridge_alpha", 1.0)),
    )
    panel["role_residual"] = residual
    stats["role_model"] = role_diagnostics

    regression_config = config.get("regression_upside", {})
    regression = build_regression_upside(
        panel,
        min_fga=int(regression_config.get("min_fga", 120)),
        free_throw_prior_weight=float(regression_config.get("free_throw_prior_weight", 0.5)),
    )
    for column in regression.columns:
        panel[column] = regression[column]

    panel["playoff_fit"] = build_playoff_fit(panel)

    # Trajectory blends production, efficiency and opportunity trends; the DARKO projection
    # is folded in where available as an independent forward-looking read.
    trend_parts = pd.DataFrame(
        {
            "production": percentile(panel.get("points_per_75_slope")),
            "efficiency": percentile(panel.get("ts_pct_slope")),
            "opportunity": percentile(panel.get("on_court_poss_share_slope")),
            "on_court": percentile(panel.get("on_court_net_rating_slope")),
            "projection": percentile(panel.get("darko_projected_rating")),
        }
    )
    panel["trajectory_raw"] = trend_parts.mean(axis=1, skipna=True)
    panel["volatility_raw"] = pd.to_numeric(panel.get("on_court_net_rating_volatility"), errors="coerce")

    board = build_board(panel, weights=config.get("weights", {}), labels=config.get("labels", {}))
    components = build_component_long(board)

    row_counts = {
        "hidden_value_board_2026.csv": _write(paths["board"], board),
        "player_trajectory_2026.csv": _write(paths["trajectories"], trajectories),
        "hidden_value_components_2026.csv": _write(paths["components"], components),
    }

    stats.update(
        {
            "status": "ok",
            "players_scored": int(len(board)),
            "players_reliable": int((board["sample_flag"] == "Reliable").sum()),
            "impact_from_rapm": int((board["impact_source"] == "rapm").sum()),
            "track_counts": board["board_track"].value_counts().to_dict(),
            "conviction_counts": board["conviction"].value_counts().to_dict(),
            "trajectory_players": int(len(trajectories)),
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
    lines = ["## Hidden Value Watchlist", ""]
    if not paths["manifest"].exists():
        lines.append("No manifest found.")
        return "\n".join(lines)

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    stats = manifest.get("analysis_stats", {})
    role = stats.get("role_model", {})
    lines.extend(
        [
            f"- Generated at: `{manifest.get('generated_at_utc')}`",
            f"- Players scored: `{stats.get('players_scored')}` (`{stats.get('players_reliable')}` reliable)",
            f"- Role model R²: `{role.get('r_squared')}` over `{role.get('players_fitted')}` players",
            f"- Tracks: `{stats.get('track_counts')}`",
            "",
        ]
    )

    if paths["board"].exists():
        board = pd.read_csv(paths["board"])
        for track in ("Underrated Now", "Recent Form"):
            subset = board[(board["board_track"] == track) & (board["sample_flag"] == "Reliable")].head(8)
            if subset.empty:
                continue
            lines.extend(
                [
                    f"### {track}",
                    "",
                    "| Player | Team | Score | Role resid | Trend | Fit | Conviction |",
                    "| --- | --- | ---: | ---: | ---: | ---: | --- |",
                ]
            )
            for _, row in subset.iterrows():
                lines.append(
                    f"| {row.get('player_name')} | {row.get('team_abbreviation')} | "
                    f"{row['hidden_value_score']:.1f} | {row['role_residual_score']:.0f} | "
                    f"{row['trajectory_score']:.0f} | {row['playoff_fit_score']:.0f} | {row['conviction']} |"
                )
            lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the WNBA 2026 hidden-value watchlist.")
    parser.add_argument("--config", required=True)
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
    build_outputs(config)
    summary = build_summary(resolve_output_root(config))
    print(summary)
    write_github_step_summary(summary)


if __name__ == "__main__":
    main()
