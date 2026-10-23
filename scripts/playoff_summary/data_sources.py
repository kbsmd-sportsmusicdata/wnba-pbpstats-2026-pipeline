"""Input loading + path resolution for the playoff summary. The only filesystem-touching module.

Everything is optional: if the playoff game layer has not been produced yet (no playoff ingest),
the loaders return empty frames and the build skips cleanly -- the same fail-open contract as the
game-layer builder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

DEFAULTS: Dict[str, Any] = {
    "season": 2026,
    "game_layer_root": "data/processed",
    "game_logs_root": "data/pbpstats_2026_player_game_logs",
    "output_root": "analysis/playoff_summary",
    "min_playoff_games": 2,
    "board_top_n": 15,
    "movers_metric": "points_per100",
    "movers_top_n": 8,
}


def load_config(path: Optional[Path]) -> Dict[str, Any]:
    config = dict(DEFAULTS)
    if path and Path(path).exists():
        with Path(path).open(encoding="utf-8") as handle:
            config.update(json.load(handle))
    return config


def path_from_config(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def _slug(season_type: str) -> str:
    return "wnba_2026_" + season_type.strip().lower().replace(" ", "_")


def resolve_paths(config: Mapping[str, Any]) -> Dict[str, Path]:
    season = str(config.get("season", DEFAULTS["season"]))
    layer = path_from_config(config.get("game_layer_root", DEFAULTS["game_layer_root"]))
    logs = path_from_config(config.get("game_logs_root", DEFAULTS["game_logs_root"]))
    player_dir = layer / "wnba_pbpstats_player_game" / f"season={season}"
    team_dir = layer / "wnba_pbpstats_team_game" / f"season={season}"
    return {
        "playoff_player": player_dir / "playoffs" / "player_game.parquet",
        "playoff_team": team_dir / "playoffs" / "team_game.parquet",
        "rs_player": player_dir / "player_game.parquet",
        "rs_team": team_dir / "team_game.parquet",
        "playoff_games": logs / "playoffs" / f"games_{_slug('Playoffs')}.csv",
        "output_root": path_from_config(config.get("output_root", DEFAULTS["output_root"])),
    }


def read_parquet_optional(path: Path) -> pd.DataFrame:
    """Read a parquet, or an empty frame if it is absent (season type not ingested yet)."""
    if not Path(path).exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def read_games_spine(path: Path) -> List[dict]:
    """Read the playoff games dimension CSV as a list of row dicts (empty if absent)."""
    if not Path(path).exists():
        return []
    return pd.read_csv(path, dtype=str).to_dict("records")
