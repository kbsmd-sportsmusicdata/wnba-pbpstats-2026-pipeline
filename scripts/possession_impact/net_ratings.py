"""Bench and clutch net ratings computed from possessions rather than plus-minus.

Both were previously marked unavailable in the team-grades methodology for want of
validated possession/stint data. They are the same calculation applied to different slices
of the possession feed: points per 100 scored minus points per 100 allowed.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd


def _ratings(offense: pd.DataFrame, defense: pd.DataFrame, prefix: str) -> Dict[str, float]:
    """Offensive, defensive and net rating per 100 possessions for one slice."""
    off_poss, def_poss = len(offense), len(defense)
    off_rating = float(offense["points"].sum() / off_poss * 100) if off_poss else np.nan
    def_rating = float(defense["points"].sum() / def_poss * 100) if def_poss else np.nan
    return {
        f"{prefix}_off_poss": off_poss,
        f"{prefix}_def_poss": def_poss,
        f"{prefix}_off_rating": off_rating,
        f"{prefix}_def_rating": def_rating,
        f"{prefix}_net_rating": off_rating - def_rating if off_poss and def_poss else np.nan,
    }


def build_bench_net_rating(
    possessions: pd.DataFrame,
    *,
    bench_heavy_threshold: int,
) -> pd.DataFrame:
    """Net rating by how much of a team's bench is on the floor.

    Three slices per team: the starting five alone, any possession with at least one
    non-starter, and bench-heavy units. The drop-off between the first two is the number
    that matters for playoff rotations, where benches shorten.
    """
    columns = [
        "team_id",
        "starters_only_off_poss",
        "starters_only_def_poss",
        "starters_only_off_rating",
        "starters_only_def_rating",
        "starters_only_net_rating",
        "any_bench_off_poss",
        "any_bench_def_poss",
        "any_bench_off_rating",
        "any_bench_def_rating",
        "any_bench_net_rating",
        "bench_heavy_off_poss",
        "bench_heavy_def_poss",
        "bench_heavy_off_rating",
        "bench_heavy_def_rating",
        "bench_heavy_net_rating",
        "bench_dropoff",
    ]
    if possessions.empty or "offense_bench_on_court" not in possessions.columns:
        return pd.DataFrame(columns=columns)

    known = possessions[
        possessions["offense_bench_on_court"].notna() & possessions["defense_bench_on_court"].notna()
    ]
    rows: List[Dict[str, float]] = []
    for team in sorted(pd.unique(known["offense_team_id"])):
        offense = known[known["offense_team_id"] == team]
        defense = known[known["defense_team_id"] == team]
        record: Dict[str, float] = {"team_id": int(team)}
        record.update(
            _ratings(
                offense[offense["offense_bench_on_court"] == 0],
                defense[defense["defense_bench_on_court"] == 0],
                "starters_only",
            )
        )
        record.update(
            _ratings(
                offense[offense["offense_bench_on_court"] >= 1],
                defense[defense["defense_bench_on_court"] >= 1],
                "any_bench",
            )
        )
        record.update(
            _ratings(
                offense[offense["offense_bench_on_court"] >= bench_heavy_threshold],
                defense[defense["defense_bench_on_court"] >= bench_heavy_threshold],
                "bench_heavy",
            )
        )
        record["bench_dropoff"] = record["starters_only_net_rating"] - record["any_bench_net_rating"]
        rows.append(record)

    table = pd.DataFrame(rows)
    return table[[column for column in columns if column in table.columns]]


def build_clutch_net_rating(
    possessions: pd.DataFrame,
    *,
    max_seconds_remaining: float,
    min_period: int,
    max_score_margin: float,
) -> pd.DataFrame:
    """Net rating in close, late possessions.

    Clutch is defined on the possession itself: late enough, close enough at the moment it
    starts. Using the margin *before* the possession avoids scoring on it defining it as
    clutch.
    """
    columns = [
        "team_id",
        "clutch_off_poss",
        "clutch_def_poss",
        "clutch_off_rating",
        "clutch_def_rating",
        "clutch_net_rating",
        "clutch_games",
    ]
    required = {"period", "start_seconds_remaining", "offense_margin_before"}
    if possessions.empty or not required.issubset(possessions.columns):
        return pd.DataFrame(columns=columns)

    clutch = possessions[
        (pd.to_numeric(possessions["period"], errors="coerce") >= min_period)
        & (pd.to_numeric(possessions["start_seconds_remaining"], errors="coerce") <= max_seconds_remaining)
        & (pd.to_numeric(possessions["offense_margin_before"], errors="coerce").abs() <= max_score_margin)
    ]
    if clutch.empty:
        return pd.DataFrame(columns=columns)

    rows: List[Dict[str, float]] = []
    for team in sorted(set(clutch["offense_team_id"]) | set(clutch["defense_team_id"])):
        offense = clutch[clutch["offense_team_id"] == team]
        defense = clutch[clutch["defense_team_id"] == team]
        record: Dict[str, float] = {"team_id": int(team)}
        record.update(_ratings(offense, defense, "clutch"))
        record["clutch_games"] = int(pd.concat([offense["game_id"], defense["game_id"]]).nunique())
        rows.append(record)

    return pd.DataFrame(rows)[columns]


def attach_team_labels(table: pd.DataFrame, team_features: pd.DataFrame) -> pd.DataFrame:
    """Add readable team abbreviations, which the possession feed carries only as ids."""
    if table.empty or team_features.empty or "team_id" not in team_features.columns:
        return table
    labels = team_features[["team_id", "team_abbreviation"]].drop_duplicates("team_id")
    labels["team_id"] = pd.to_numeric(labels["team_id"], errors="coerce").astype("Int64")
    out = table.copy()
    out["team_id"] = pd.to_numeric(out["team_id"], errors="coerce").astype("Int64")
    out = out.merge(labels, on="team_id", how="left")
    return out[["team_id", "team_abbreviation"] + [c for c in out.columns if c not in {"team_id", "team_abbreviation"}]]


def attach_player_labels(table: pd.DataFrame, player_features: pd.DataFrame) -> pd.DataFrame:
    """Add player names and teams from the PBPStats features, which share the id space."""
    if table.empty or player_features.empty:
        return table
    labels = player_features[["entity_id", "name", "team_abbreviation"]].drop_duplicates("entity_id")
    labels = labels.rename(columns={"entity_id": "player_id", "name": "player_name"})
    labels["player_id"] = pd.to_numeric(labels["player_id"], errors="coerce").astype("Int64")
    out = table.copy()
    out["player_id"] = pd.to_numeric(out["player_id"], errors="coerce").astype("Int64")
    out = out.merge(labels, on="player_id", how="left")
    leading = ["player_id", "player_name", "team_abbreviation"]
    return out[leading + [c for c in out.columns if c not in leading]]
