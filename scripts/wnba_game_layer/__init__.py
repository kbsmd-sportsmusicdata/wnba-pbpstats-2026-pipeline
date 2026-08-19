"""Shared normalized WNBA 2026 pbpstats game layer.

Turns the combined pbpstats game logs (one ragged row per player-game / team-game, with
zero-valued stats omitted) into analysis-ready tables: snake_case columns, zero-omitted stats
filled to 0, and each row joined to the ``get-games`` spine for game context (date, home/away,
opponent, points, margin, result, possessions). Player-game rows are keyed ``player_id + game_id``;
team-game rows are keyed ``team_id + game_id``.

The per-game *team* is derived from the spine by matching the row's played-for abbreviation, so a
mid-season trade attributes each game to the team actually played for rather than the player's
current team.
"""

from .normalize import (
    GameLayerError,
    build_player_game,
    build_team_game,
    games_by_id,
    normalize_column,
    to_minutes,
)
from .windows import (
    add_rolling,
    attach_opponent_strength,
    consistency,
    latest_form,
    split_means,
    trend_slope,
)

__all__ = [
    "GameLayerError",
    "build_player_game",
    "build_team_game",
    "games_by_id",
    "normalize_column",
    "to_minutes",
    "add_rolling",
    "attach_opponent_strength",
    "consistency",
    "latest_form",
    "split_means",
    "trend_slope",
]
