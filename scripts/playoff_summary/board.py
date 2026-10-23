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
# Second curated player subset: defense & rebounding.
_DEFENSE_COLUMNS = [
    ("player_name", "Player"),
    ("team_abbreviation", "Team"),
    ("games", "G"),
    ("minutes_per_game", "MPG"),
    ("def_rebounds_per100", "DREB/100"),
    ("off_rebounds_per100", "OREB/100"),
    ("rebounds_per100", "REB/100"),
    ("def_fgrebound_pct", "DREB%"),
    ("off_fgrebound_pct", "OREB%"),
    ("steals_per100", "STL/100"),
    ("blocks_per100", "BLK/100"),
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


def defense_rebounding_leaderboard(
    player_agg: pd.DataFrame, *, top_n: int = 15, sort_by: str = "rebounds_per100", qualified_only: bool = True
) -> pd.DataFrame:
    """Curated defense & rebounding board (per-100 steals/blocks/rebounds + rebound rates)."""
    if player_agg.empty:
        return pd.DataFrame()
    df = player_agg
    if qualified_only and "meets_min_games" in df.columns:
        df = df[df["meets_min_games"]]
    pairs = _present(df, _DEFENSE_COLUMNS)
    board = df[[src for src, _ in pairs]].rename(columns=dict(pairs))
    sort_label = dict(pairs).get(sort_by)
    if sort_label and sort_label in board.columns:
        board = board.sort_values(sort_label, ascending=False)
    return board.head(top_n).reset_index(drop=True)


def delta_movers(
    player_delta: pd.DataFrame, *, metric: str = "points_per100", top_n: int = 8, qualified_only: bool = True
):
    """Biggest risers and fallers on one metric's RS->playoff delta.

    Returns ``(risers, fallers)`` display frames (Player/Team/PO G/RS/PO/Delta). Empty frames when
    the metric's delta columns are absent (e.g. no overlapping sample).
    """
    cols = [f"{metric}_rs", f"{metric}_playoff", f"{metric}_delta"]
    if player_delta.empty or not all(c in player_delta.columns for c in cols):
        return pd.DataFrame(), pd.DataFrame()
    df = player_delta
    if qualified_only and "meets_min_games" in df.columns:
        df = df[df["meets_min_games"]]
    df = df.dropna(subset=[f"{metric}_delta"])
    name_cols = [c for c in ("player_name", "team_abbreviation", "team_name", "playoff_games") if c in df.columns]
    rename = {"player_name": "Player", "team_abbreviation": "Team", "team_name": "Team",
              "playoff_games": "PO G", f"{metric}_rs": "RS", f"{metric}_playoff": "PO", f"{metric}_delta": "Δ"}

    def _view(sub: pd.DataFrame) -> pd.DataFrame:
        return sub[name_cols + cols].rename(columns=rename).reset_index(drop=True)

    risers = _view(df.sort_values(f"{metric}_delta", ascending=False).head(top_n))
    fallers = _view(df.sort_values(f"{metric}_delta", ascending=True).head(top_n))
    return risers, fallers


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
    defense_board: Optional[pd.DataFrame] = None,
) -> str:
    """Render the playoff leaderboard Markdown summary (scoring + optional defense/rebounding)."""
    coverage = f" · data through **{as_of}**" if as_of else ""
    lines = [
        f"# WNBA {season} Playoff Summary",
        "",
        f"Descriptive playoff splits (per 100 possessions){coverage}. "
        f"Player boards are limited to the **{total_players}** players with at least "
        f"**{min_games}** playoff game(s); shooting rates are recomputed from summed makes and "
        f"attempts, not averaged per game.",
        "",
        "## Scoring & efficiency",
        "",
        _md_table(player_board),
        "",
    ]
    if defense_board is not None:
        lines += ["## Defense & rebounding", "", _md_table(defense_board), ""]
    lines += [
        f"## Teams ({total_teams})",
        "",
        _md_table(team_board_df),
        "",
        "_Small playoff samples: treat these as descriptive, not predictive._",
        "",
    ]
    return "\n".join(lines)


def render_movers_markdown(
    risers: pd.DataFrame,
    fallers: pd.DataFrame,
    *,
    season: str,
    metric_label: str,
    as_of: Optional[str],
    min_games: int,
) -> str:
    """Render the RS->playoff risers & fallers board for one headline metric."""
    coverage = f" · data through **{as_of}**" if as_of else ""
    return "\n".join(
        [
            f"# WNBA {season} Playoffs — Risers & Fallers",
            "",
            f"Largest regular-season → playoff change in **{metric_label}**{coverage}. "
            f"Qualified players ({min_games}+ playoff games); Δ = playoff − regular season.",
            "",
            "## Biggest risers",
            "",
            _md_table(risers),
            "",
            "## Biggest fallers",
            "",
            _md_table(fallers),
            "",
            "_Small playoff samples: treat these as descriptive, not predictive._",
            "",
        ]
    )
