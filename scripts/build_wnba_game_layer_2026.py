#!/usr/bin/env python3
"""Build the shared normalized WNBA 2026 pbpstats game layer.

Reads the combined pbpstats game logs (produced by ``fetch_wnba_pbpstats_game_logs_2026.py``)
and the ``get-games`` spine, and writes analysis-ready per-game tables that every downstream
analysis can read instead of re-deriving game grain from season totals:

* ``data/processed/wnba_pbpstats_player_game/season=<season>/player_game.parquet``
* ``data/processed/wnba_pbpstats_team_game/season=<season>/team_game.parquet``

The transforms live in :mod:`wnba_game_layer`; this script is a thin reader/writer.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wnba_game_layer import build_player_game, build_team_game, games_by_id  # noqa: E402


DEFAULT_SEASON = "2026"
DEFAULT_SEASON_TYPE = "Regular Season"
DEFAULT_LOGS_ROOT = "data/pbpstats_2026_player_game_logs"
DEFAULT_OUTPUT_ROOT = "data/processed"


def _slug(season_type: str) -> str:
    return "wnba_2026_" + season_type.strip().lower().replace(" ", "_")


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_games(logs_root: Path, season_type: str) -> List[dict]:
    csv_path = logs_root / f"games_{_slug(season_type)}.csv"
    if csv_path.exists():
        frame = pd.read_csv(csv_path, dtype=str)
        return frame.to_dict("records")
    json_path = logs_root / f"get_games_{_slug(season_type)}.json"
    payload = _read_json(json_path)
    return list(payload.get("results") or [])


def build(
    season: str,
    season_type: str,
    logs_root: Path,
    output_root: Path,
) -> Dict[str, Any]:
    games = games_by_id(_load_games(logs_root, season_type))
    if not games:
        raise SystemExit("no games found in the spine; run the game-log ingest first")

    player_rows = _read_json(logs_root / f"player_game_logs_{_slug(season_type)}.json")
    team_rows = _read_json(logs_root / f"team_game_logs_{_slug(season_type)}.json")

    player_game = build_player_game(player_rows, games, season=season, season_type=season_type)
    team_game = build_team_game(team_rows, games, season=season, season_type=season_type)

    player_path = output_root / "wnba_pbpstats_player_game" / f"season={season}" / "player_game.parquet"
    team_path = output_root / "wnba_pbpstats_team_game" / f"season={season}" / "team_game.parquet"
    for path, frame in ((player_path, player_game), (team_path, team_game)):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "season": season,
        "season_type": season_type,
        "games_in_spine": len(games),
        "player_game": {
            "rows": int(len(player_game)),
            "players": int(player_game["player_id"].nunique()) if not player_game.empty else 0,
            "games": int(player_game["game_id"].nunique()) if not player_game.empty else 0,
            "columns": int(len(player_game.columns)),
            "path": str(player_path),
        },
        "team_game": {
            "rows": int(len(team_game)),
            "teams": int(team_game["team_id"].nunique()) if not team_game.empty else 0,
            "games": int(team_game["game_id"].nunique()) if not team_game.empty else 0,
            "columns": int(len(team_game.columns)),
            "path": str(team_path),
        },
    }
    manifest_path = output_root / "wnba_pbpstats_player_game" / f"season={season}" / "game_layer_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the shared WNBA 2026 pbpstats game layer.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--season-type", default=DEFAULT_SEASON_TYPE)
    parser.add_argument("--logs-root", default=DEFAULT_LOGS_ROOT)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else Path(__file__).resolve().parents[1] / path


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    manifest = build(
        args.season, args.season_type,
        _resolve(args.logs_root), _resolve(args.output_root),
    )
    pg, tg = manifest["player_game"], manifest["team_game"]
    print(
        f"game layer {args.season}: {pg['rows']} player-game rows "
        f"({pg['players']} players, {pg['columns']} cols) -> {pg['path']}\n"
        f"             {tg['rows']} team-game rows "
        f"({tg['teams']} teams, {tg['columns']} cols) -> {tg['path']}"
    )


if __name__ == "__main__":
    main()
