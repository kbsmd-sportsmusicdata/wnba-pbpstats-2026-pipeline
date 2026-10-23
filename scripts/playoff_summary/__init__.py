"""WNBA 2026 playoff summary: descriptive playoff splits, RS-vs-playoff deltas, series rollups.

A deliberately descriptive companion to the inferential regular-season tools: it reports what
happened in the playoffs (per 100 possessions) and how it differs from the regular season, with
sample size on every row, rather than fitting models a handful of playoff games cannot support.
"""

from .aggregate import (
    aggregate_entity,
    comparable_metric_columns,
    is_rate,
    rs_vs_playoff_deltas,
)
from .board import (
    defense_rebounding_leaderboard,
    delta_movers,
    player_leaderboard,
    render_markdown,
    render_movers_markdown,
    team_board,
)
from .series import series_rollups

__all__ = [
    "aggregate_entity",
    "comparable_metric_columns",
    "is_rate",
    "rs_vs_playoff_deltas",
    "player_leaderboard",
    "defense_rebounding_leaderboard",
    "delta_movers",
    "team_board",
    "render_markdown",
    "render_movers_markdown",
    "series_rollups",
]
