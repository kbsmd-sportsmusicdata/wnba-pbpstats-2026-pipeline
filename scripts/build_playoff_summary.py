#!/usr/bin/env python3
"""Build the WNBA 2026 playoff summary.

Descriptive playoff splits per player and team (per 100 possessions), regular-season-vs-playoff
rate deltas, and series rollups, plus a curated Markdown leaderboard. Sample size rides on every
row and nothing is dropped; thin rows are flagged via ``meets_min_games``.

This reads the playoff game layer produced by ``build_wnba_game_layer_2026.py --season-type
Playoffs``. If that layer is absent (no playoff ingest yet), the build skips cleanly.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playoff_summary.aggregate import aggregate_entity, rs_vs_playoff_deltas
from playoff_summary.board import player_leaderboard, render_markdown, team_board
from playoff_summary.data_sources import (
    load_config,
    read_games_spine,
    read_parquet_optional,
    resolve_paths,
)
from playoff_summary.series import series_rollups


def _write_table(base: Path, frame: pd.DataFrame) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(base.with_suffix(".csv"), index=False)
    frame.to_json(base.with_suffix(".json"), orient="records", indent=2)


def _coverage_through(df: pd.DataFrame) -> Optional[str]:
    if df.empty or "game_date" not in df.columns:
        return None
    dates = df["game_date"].dropna()
    return str(dates.max()) if not dates.empty else None


def build(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    paths = resolve_paths(config)
    min_games = int(config.get("min_playoff_games", 2))
    top_n = int(config.get("board_top_n", 15))
    season = str(config.get("season", 2026))

    playoff_player = read_parquet_optional(paths["playoff_player"])
    playoff_team = read_parquet_optional(paths["playoff_team"])
    if playoff_player.empty and playoff_team.empty:
        return None  # no playoff layer yet -> nothing to summarize

    out_root = paths["output_root"]
    coverage = _coverage_through(playoff_player) or _coverage_through(playoff_team)

    player_agg = aggregate_entity(
        playoff_player, id_col="player_id", name_cols=["player_name", "team_abbreviation", "team_id"], min_games=min_games
    )
    team_agg = aggregate_entity(
        playoff_team, id_col="team_id", name_cols=["team_name", "team_abbreviation"], min_games=min_games
    )
    _write_table(out_root / "player_playoff_splits", player_agg)
    _write_table(out_root / "team_playoff_splits", team_agg)

    # RS-vs-playoff deltas (only for entities present in both samples).
    rs_player = read_parquet_optional(paths["rs_player"])
    rs_team = read_parquet_optional(paths["rs_team"])
    player_delta = team_delta = pd.DataFrame()
    if not rs_player.empty:
        rs_player_agg = aggregate_entity(
            rs_player, id_col="player_id", name_cols=["player_name", "team_abbreviation", "team_id"], min_games=min_games
        )
        player_delta = rs_vs_playoff_deltas(
            rs_player_agg, player_agg, id_col="player_id", name_cols=["player_name", "team_abbreviation"]
        )
        _write_table(out_root / "player_rs_vs_playoff_delta", player_delta)
    if not rs_team.empty:
        rs_team_agg = aggregate_entity(
            rs_team, id_col="team_id", name_cols=["team_name", "team_abbreviation"], min_games=min_games
        )
        team_delta = rs_vs_playoff_deltas(
            rs_team_agg, team_agg, id_col="team_id", name_cols=["team_name", "team_abbreviation"]
        )
        _write_table(out_root / "team_rs_vs_playoff_delta", team_delta)

    # Series rollups from the playoff games spine.
    series = series_rollups(read_games_spine(paths["playoff_games"]))
    if not series.empty:
        _write_table(out_root / "series_rollups", series)

    # Curated board + Markdown leaderboard.
    board_players = player_leaderboard(player_agg, top_n=top_n)
    board_teams = team_board(team_agg)
    markdown = render_markdown(
        board_players, board_teams,
        season=season, as_of=coverage, min_games=min_games,
        total_players=int(len(board_players)), total_teams=int(len(team_agg)),
    )
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "playoff_leaderboard.md").write_text(markdown, encoding="utf-8")

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "season": season,
        "coverage_through": coverage,
        "min_playoff_games": min_games,
        "players": int(len(player_agg)),
        "qualified_players": int(player_agg["meets_min_games"].sum()) if "meets_min_games" in player_agg else 0,
        "teams": int(len(team_agg)),
        "series": int(len(series)),
        "player_delta_rows": int(len(player_delta)),
        "team_delta_rows": int(len(team_delta)),
        "inputs": {k: str(v) for k, v in paths.items() if k != "output_root"},
    }
    (out_root / "playoff_summary_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the WNBA 2026 playoff summary.")
    parser.add_argument("--config", default="analysis/playoff_summary/config/playoff_summary_config.json")
    parser.add_argument("--output-root", default=None, help="Override the config output root.")
    parser.add_argument("--min-playoff-games", type=int, default=None, help="Override the thin-sample threshold.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    config_path = Path(args.config)
    config = load_config(config_path if config_path.is_absolute() else Path(__file__).resolve().parent.parent / config_path)
    if args.output_root is not None:
        config["output_root"] = args.output_root
    if args.min_playoff_games is not None:
        config["min_playoff_games"] = args.min_playoff_games

    manifest = build(config)
    if manifest is None:
        print("playoff summary: no playoff game layer found; skipped (ingest Playoffs/Both first)")
        return
    print(
        f"playoff summary {manifest['season']}: {manifest['players']} players "
        f"({manifest['qualified_players']} qualified @ {manifest['min_playoff_games']}+ games), "
        f"{manifest['teams']} teams, {manifest['series']} series, "
        f"{manifest['player_delta_rows']} RS-vs-playoff player deltas, through {manifest['coverage_through']}"
    )


if __name__ == "__main__":
    main()
