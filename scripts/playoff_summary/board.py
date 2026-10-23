"""Curated headline subset + Markdown leaderboard. Pure; no network, no filesystem.

The board is the one curated subset of the full union (efficiency, usage, shooting, pace) rendered
two ways: a compact CSV and a Markdown leaderboard like the hidden-value / team-identity boards.
Only players meeting the ``min_playoff_games`` flag appear in the ranked player board.
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd


# Curated player headline columns, in display order. Shooting rates use the component-derived
# versions (correct across unequal samples), not the per-game averages.
_PLAYER_COLUMNS = [
    ("player_name", "Player"),
    ("team_abbreviation", "Team"),
    ("games", "G"),
    ("minutes_per_game", "MPG"),
    ("points_per100", "PTS/100"),
    ("ts_pct_derived", "TS%"),
    ("usage", "USG%"),
    ("assists_per100", "AST/100"),
    ("rebounds_per100", "REB/100"),
    ("turnovers_per100", "TOV/100"),
    ("plus_minus_per_game", "+/- (g)"),
]
_TEAM_COLUMNS = [
    ("team_abbreviation", "Team"),
    ("games", "G"),
    ("record", "W-L"),
    ("pace", "Pace"),
    ("points_per100", "PTS/100"),
    ("opponent_points_per_game", "OPP PPG"),
    ("margin_per_game", "Margin/g"),
]


def _present(df: pd.DataFrame, pairs: List[tuple]) -> List[tuple]:
    return [(src, label) for src, label in pairs if src in df.columns]


def player_leaderboard(
    player_agg: pd.DataFrame, *, top_n: int = 15, sort_by: str = "points_per100", qualified_only: bool = True
) -> pd.DataFrame:
    """Curated, ranked player board. ``qualified_only`` keeps rows with ``meets_min_games``."""
    if player_agg.empty:
        return pd.DataFrame()
    df = player_agg
    if qualified_only and "meets_min_games" in df.columns:
        df = df[df["meets_min_games"]]
    pairs = _present(df, _PLAYER_COLUMNS)
    board = df[[src for src, _ in pairs]].rename(columns=dict(pairs))
    sort_label = dict(pairs).get(sort_by)
    if sort_label and sort_label in board.columns:
        board = board.sort_values(sort_label, ascending=False)
    return board.head(top_n).reset_index(drop=True)


def team_board(team_agg: pd.DataFrame) -> pd.DataFrame:
    """Curated team board, sorted by wins then scoring margin."""
    if team_agg.empty:
        return pd.DataFrame()
    df = team_agg.copy()
    if {"wins", "losses"}.issubset(df.columns):
        df["record"] = df["wins"].astype("Int64").astype(str) + "-" + df["losses"].astype("Int64").astype(str)
    pairs = _present(df, _TEAM_COLUMNS)
    pair_srcs = [src for src, _ in pairs]
    helper = [c for c in ("wins", "margin_per_game") if c in df.columns and c not in pair_srcs]
    board = df[pair_srcs + helper].copy()
    sort_cols = [c for c in ("wins", "margin_per_game") if c in board.columns]
    if sort_cols:
        board = board.sort_values(sort_cols, ascending=False)
    board = board[pair_srcs].rename(columns=dict(pairs))
    return board.reset_index(drop=True)


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if abs(value) < 1 else f"{value:.1f}"
    return str(value)


def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No qualifying rows._"
    header = "| " + " | ".join(df.columns) + " |"
    sep = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows = ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([header, sep, *rows])


def render_markdown(
    player_board: pd.DataFrame,
    team_board_df: pd.DataFrame,
    *,
    season: str,
    as_of: Optional[str],
    min_games: int,
    total_players: int,
    total_teams: int,
) -> str:
    """Render the playoff leaderboard Markdown summary."""
    coverage = f" · data through **{as_of}**" if as_of else ""
    return "\n".join(
        [
            f"# WNBA {season} Playoff Summary",
            "",
            f"Descriptive playoff splits (per 100 possessions){coverage}. "
            f"Player board is limited to the **{total_players}** players with at least "
            f"**{min_games}** playoff game(s); shooting rates are recomputed from summed makes and "
            f"attempts, not averaged per game.",
            "",
            "## Player leaderboard",
            "",
            _md_table(player_board),
            "",
            f"## Teams ({total_teams})",
            "",
            _md_table(team_board_df),
            "",
            "_Small playoff samples: treat these as descriptive, not predictive._",
            "",
        ]
    )
