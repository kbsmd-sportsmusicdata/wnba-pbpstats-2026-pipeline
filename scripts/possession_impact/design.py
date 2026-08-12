"""Turning the raw possession feed into modelling inputs.

Everything here works inside the WNBA Stats id space. The possession feed, the WNBA
play-by-play and the PBPStats entity ids all agree, so no cross-source key mapping is
needed; the ESPN box scores use a different id space and are deliberately not used.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Sequence, Tuple

import numpy as np
import pandas as pd


OFFENSE_COLUMNS = [f"off_player_{i}" for i in range(1, 6)]
DEFENSE_COLUMNS = [f"def_player_{i}" for i in range(1, 6)]
LINEUP_COLUMNS = OFFENSE_COLUMNS + DEFENSE_COLUMNS


def prepare_possessions(possessions: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Keep possessions that can actually carry a lineup-based estimate.

    Two exclusions: rows the feed does not count as a possession, and rows where any of the
    ten on-court slots is missing. Roughly 3.7% of the 2026 feed goes for those reasons.
    """
    counts = {"raw_rows": int(len(possessions))}
    if possessions.empty:
        return possessions, counts

    df = possessions.copy()
    counted = df["count_as_possession"].astype(bool) if "count_as_possession" in df.columns else pd.Series(True, index=df.index)
    complete = df[LINEUP_COLUMNS].notna().all(axis=1)
    counts["dropped_not_counted"] = int((~counted).sum())
    counts["dropped_incomplete_lineup"] = int((counted & ~complete).sum())

    df = df[counted & complete].copy()
    for column in LINEUP_COLUMNS:
        df[column] = df[column].astype("int64")
    df = df.sort_values(["game_id", "period", "possession_number"]).reset_index(drop=True)
    counts["usable_possessions"] = int(len(df))
    counts["games"] = int(df["game_id"].nunique())
    return df, counts


def player_index(possessions: pd.DataFrame) -> List[int]:
    """Every player who appears on the floor, in a stable order."""
    if possessions.empty:
        return []
    values = pd.unique(possessions[LINEUP_COLUMNS].to_numpy().ravel())
    return sorted(int(value) for value in values)


def attach_home_flag(possessions: pd.DataFrame, wnba_pbp: pd.DataFrame) -> pd.DataFrame:
    """Mark whether the offense is the home team, from the play-by-play location field.

    The play-by-play is used rather than the lineup feed because it covers every game in
    the possession file, and rather than the ESPN schedule because it shares the same game
    and team ids.
    """
    df = possessions.copy()
    df["offense_is_home"] = np.nan
    required = {"game_id", "team_id", "location"}
    if wnba_pbp.empty or not required.issubset(wnba_pbp.columns):
        return df

    sides = wnba_pbp[["game_id", "team_id", "location"]].dropna()
    sides = sides[sides["location"].astype(str).str.lower().isin(["h", "v"])]
    sides = sides[pd.to_numeric(sides["team_id"], errors="coerce").fillna(0) > 0]
    sides["game_key"] = sides["game_id"].astype(str)
    sides["team_id"] = pd.to_numeric(sides["team_id"], errors="coerce").astype("int64")
    sides["is_home"] = sides["location"].astype(str).str.lower().eq("h")
    lookup = sides.drop_duplicates(["game_key", "team_id"]).set_index(["game_key", "team_id"])["is_home"]

    keys = list(zip(df["game_id"].astype(str), df["offense_team_id"].astype("int64")))
    df["offense_is_home"] = pd.Series(lookup.reindex(keys).to_numpy(), index=df.index).astype("float64")
    return df


def derive_starters(possessions: pd.DataFrame) -> Dict[Tuple[str, int], FrozenSet[int]]:
    """The five on the floor for each team at the opening possession of each game.

    Taken from the possession feed itself so the module needs one source rather than two.
    Cross-checked against the separate game-lineups feed: the two agree on all 195 games
    where both are available.
    """
    if possessions.empty:
        return {}

    opening = (
        possessions[possessions["period"] == 1]
        .sort_values(["game_id", "possession_number"])
        .groupby("game_id", sort=False)
        .head(1)
    )
    starters: Dict[Tuple[str, int], FrozenSet[int]] = {}
    for row in opening.itertuples(index=False):
        game = str(getattr(row, "game_id"))
        starters[(game, int(getattr(row, "offense_team_id")))] = frozenset(
            int(getattr(row, column)) for column in OFFENSE_COLUMNS
        )
        starters[(game, int(getattr(row, "defense_team_id")))] = frozenset(
            int(getattr(row, column)) for column in DEFENSE_COLUMNS
        )
    return starters


def attach_bench_counts(
    possessions: pd.DataFrame,
    starters: Dict[Tuple[str, int], FrozenSet[int]],
) -> pd.DataFrame:
    """Count non-starters on the floor for each side of every possession."""
    df = possessions.copy()
    if df.empty:
        df["offense_bench_on_court"] = pd.Series(dtype="float64")
        df["defense_bench_on_court"] = pd.Series(dtype="float64")
        return df

    games = df["game_id"].astype(str).to_numpy()
    for side, team_column, columns in (
        ("offense", "offense_team_id", OFFENSE_COLUMNS),
        ("defense", "defense_team_id", DEFENSE_COLUMNS),
    ):
        teams = df[team_column].astype("int64").to_numpy()
        lineups = df[columns].to_numpy()
        counts = np.full(len(df), np.nan)
        for position in range(len(df)):
            starting_five = starters.get((games[position], int(teams[position])))
            if starting_five is None:
                continue
            counts[position] = sum(1 for player in lineups[position] if int(player) not in starting_five)
        df[f"{side}_bench_on_court"] = counts
    return df


def attach_score_state(possessions: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct the score before each possession, and the offense's margin.

    The feed carries points per possession but no running score, so both teams' totals are
    accumulated in possession order and lagged by one.
    """
    df = possessions.copy()
    if df.empty:
        for column in ("offense_score_before", "defense_score_before", "offense_margin_before"):
            df[column] = pd.Series(dtype="float64")
        return df

    points = pd.to_numeric(df["points"], errors="coerce").fillna(0.0)
    game = df["game_id"].astype(str)
    offense = df["offense_team_id"].astype("int64")
    # One of the two teams is picked as the reference side per game; the other follows.
    reference = game.map(df.groupby(game)["offense_team_id"].min().astype("int64"))
    offense_is_reference = offense.eq(reference)

    reference_points = points.where(offense_is_reference, 0.0)
    other_points = points.where(~offense_is_reference, 0.0)
    reference_before = reference_points.groupby(game).cumsum() - reference_points
    other_before = other_points.groupby(game).cumsum() - other_points

    df["offense_score_before"] = np.where(offense_is_reference, reference_before, other_before)
    df["defense_score_before"] = np.where(offense_is_reference, other_before, reference_before)
    df["offense_margin_before"] = df["offense_score_before"] - df["defense_score_before"]
    return df


def build_design_matrix(
    possessions: pd.DataFrame,
    players: Sequence[int],
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Design matrix for offence/defence RAPM.

    Column layout is ``[intercept, home, offense_1..offense_P, defense_1..defense_P]``.
    Offensive slots take +1 and defensive slots -1, so a larger coefficient means "better"
    on both sides: it adds points when attacking and subtracts them when defending.

    The response is points per 100 possessions, so coefficients are already in the units
    the outputs report.
    """
    player_count = len(players)
    position_of = {player: index for index, player in enumerate(players)}
    rows = len(possessions)
    matrix = np.zeros((rows, 2 + 2 * player_count), dtype=np.float64)
    matrix[:, 0] = 1.0
    if "offense_is_home" in possessions.columns:
        matrix[:, 1] = pd.to_numeric(possessions["offense_is_home"], errors="coerce").fillna(0.5).to_numpy()

    row_index = np.arange(rows)
    for column in OFFENSE_COLUMNS:
        columns = possessions[column].map(position_of).to_numpy()
        matrix[row_index, 2 + columns] = 1.0
    for column in DEFENSE_COLUMNS:
        columns = possessions[column].map(position_of).to_numpy()
        matrix[row_index, 2 + player_count + columns] = -1.0

    response = pd.to_numeric(possessions["points"], errors="coerce").fillna(0.0).to_numpy() * 100.0
    names = ["intercept", "home"] + [f"off_{p}" for p in players] + [f"def_{p}" for p in players]
    return matrix, response, names


def possession_counts(possessions: pd.DataFrame, players: Sequence[int]) -> pd.DataFrame:
    """Offensive and defensive possessions played, per player."""
    offense = pd.Series(possessions[OFFENSE_COLUMNS].to_numpy().ravel()).value_counts()
    defense = pd.Series(possessions[DEFENSE_COLUMNS].to_numpy().ravel()).value_counts()
    return pd.DataFrame(
        {
            "player_id": list(players),
            "off_poss": [int(offense.get(player, 0)) for player in players],
            "def_poss": [int(defense.get(player, 0)) for player in players],
        }
    ).assign(total_poss=lambda frame: frame["off_poss"] + frame["def_poss"])
