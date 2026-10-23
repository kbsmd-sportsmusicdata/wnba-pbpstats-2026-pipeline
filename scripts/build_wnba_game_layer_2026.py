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

# Season types mirror the game-log ingest. ``Both`` builds Regular Season then Playoffs; Regular
# Season keeps the historical flat output layout while other types nest under a subdirectory, the
# same split the ingest uses for its own files (see ``_logs_dir`` / ``_output_dir``).
REGULAR_SEASON = "Regular Season"
PLAYOFFS = "Playoffs"
BOTH = "Both"
SEASON_TYPE_CHOICES = (REGULAR_SEASON, PLAYOFFS, BOTH)
DEFAULT_SEASON_TYPE = REGULAR_SEASON

DEFAULT_LOGS_ROOT = "data/pbpstats_2026_player_game_logs"
DEFAULT_OUTPUT_ROOT = "data/processed"


def _slug(season_type: str) -> str:
    return "wnba_2026_" + season_type.strip().lower().replace(" ", "_")


def resolve_season_types(selection: str) -> List[str]:
    """Expand a ``--season-type`` selection into the concrete season types to build."""
    if selection == BOTH:
        return [REGULAR_SEASON, PLAYOFFS]
    return [selection]


def _subdir(season_type: str) -> str:
    """Subdirectory name for a non-Regular-Season type ("" for Regular Season)."""
    if season_type.strip().lower() == REGULAR_SEASON.lower():
        return ""
    return season_type.strip().lower().replace(" ", "_")


def _logs_dir(logs_root: Path, season_type: str) -> Path:
    """Where the ingest wrote this season type's combined logs (Playoffs nests in a subdir)."""
    sub = _subdir(season_type)
    return logs_root / sub if sub else logs_root


def _output_dir(output_root: Path, dataset: str, season: str, season_type: str) -> Path:
    """Parquet output dir: Regular Season stays at ``<dataset>/season=<season>`` (consumed there),
    other season types nest one level deeper so they never overwrite it."""
    base = output_root / dataset / f"season={season}"
    sub = _subdir(season_type)
    return base / sub if sub else base


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
) -> Optional[Dict[str, Any]]:
    """Build the player- and team-game parquet for one season type.

    Returns the manifest, or ``None`` when this season type has not been ingested yet (no combined
    logs on disk) -- so a ``Both`` build quietly skips Playoffs before any playoff ingest has run
    instead of failing.
    """
    logs_dir = _logs_dir(logs_root, season_type)
    player_log = logs_dir / f"player_game_logs_{_slug(season_type)}.json"
    team_log = logs_dir / f"team_game_logs_{_slug(season_type)}.json"
    if not player_log.exists() or not team_log.exists():
        return None

    games = games_by_id(_load_games(logs_dir, season_type))
    if not games:
        raise SystemExit(f"no games found in the {season_type} spine; run the game-log ingest first")

    player_rows = _read_json(player_log)
    team_rows = _read_json(team_log)

    player_game = build_player_game(player_rows, games, season=season, season_type=season_type)
    team_game = build_team_game(team_rows, games, season=season, season_type=season_type)

    player_dir = _output_dir(output_root, "wnba_pbpstats_player_game", season, season_type)
    team_dir = _output_dir(output_root, "wnba_pbpstats_team_game", season, season_type)
    player_path = player_dir / "player_game.parquet"
    team_path = team_dir / "team_game.parquet"
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
    manifest_path = player_dir / "game_layer_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the shared WNBA 2026 pbpstats game layer.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument(
        "--season-type",
        default=DEFAULT_SEASON_TYPE,
        choices=SEASON_TYPE_CHOICES,
        help="Season type(s) to build. 'Both' builds Regular Season then Playoffs.",
    )
    parser.add_argument("--logs-root", default=DEFAULT_LOGS_ROOT)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else Path(__file__).resolve().parents[1] / path


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    logs_root, output_root = _resolve(args.logs_root), _resolve(args.output_root)
    for season_type in resolve_season_types(args.season_type):
        manifest = build(args.season, season_type, logs_root, output_root)
        if manifest is None:
            print(f"game layer {args.season} {season_type}: no ingested game logs found; skipped")
            continue
        pg, tg = manifest["player_game"], manifest["team_game"]
        print(
            f"game layer {args.season} {season_type}: {pg['rows']} player-game rows "
            f"({pg['players']} players, {pg['columns']} cols) -> {pg['path']}\n"
            f"             {tg['rows']} team-game rows "
            f"({tg['teams']} teams, {tg['columns']} cols) -> {tg['path']}"
        )


if __name__ == "__main__":
    main()
