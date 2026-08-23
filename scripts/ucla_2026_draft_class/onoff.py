"""Full-season on/off splits derived from the pbpstats game layer.

pbpstats gives each player their team's offensive/defensive rating *while they
are on the floor* (`on_off_rtg` / `on_def_rtg`) plus the on-court possession
counts. Team totals come from the team-game layer, so the off-court side is
exact arithmetic rather than an estimate:

    on_court_pts  = on_off_rtg / 100 * off_poss
    off_court_pts = team_points - on_court_pts
    off_court_poss = team_off_poss - off_poss

Verified against the game layer: summing on-court points across a team's
players and dividing by five reproduces the team's game total exactly.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def build_on_off(pg: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    p = pg.copy()
    t = tg[["game_id", "team_id", "off_poss", "def_poss", "points", "opponent_points"]].rename(
        columns={
            "off_poss": "team_off_poss",
            "def_poss": "team_def_poss",
            "points": "team_pts_for",
            "opponent_points": "team_pts_against",
        }
    )
    p = p.merge(t, on=["game_id", "team_id"], how="left", validate="many_to_one")

    p["on_pts_for"] = p["on_off_rtg"] / 100 * p["off_poss"]
    p["on_pts_against"] = p["on_def_rtg"] / 100 * p["def_poss"]
    p["off_court_off_poss"] = p["team_off_poss"] - p["off_poss"]
    p["off_court_def_poss"] = p["team_def_poss"] - p["def_poss"]
    p["off_court_pts_for"] = p["team_pts_for"] - p["on_pts_for"]
    p["off_court_pts_against"] = p["team_pts_against"] - p["on_pts_against"]

    cols = [
        "off_poss", "def_poss", "on_pts_for", "on_pts_against",
        "off_court_off_poss", "off_court_def_poss",
        "off_court_pts_for", "off_court_pts_against",
    ]
    s = p.groupby(["player_id", "player_name"], as_index=False)[cols].sum(min_count=1)

    s["on_ortg"] = s["on_pts_for"] / s["off_poss"] * 100
    s["on_drtg"] = s["on_pts_against"] / s["def_poss"] * 100
    s["on_net"] = s["on_ortg"] - s["on_drtg"]
    s["off_ortg"] = s["off_court_pts_for"] / s["off_court_off_poss"] * 100
    s["off_drtg"] = s["off_court_pts_against"] / s["off_court_def_poss"] * 100
    s["off_net"] = s["off_ortg"] - s["off_drtg"]
    s["ortg_swing"] = s["on_ortg"] - s["off_ortg"]
    s["drtg_swing"] = s["on_drtg"] - s["off_drtg"]  # negative = better defense on court
    s["net_swing"] = s["on_net"] - s["off_net"]
    s["on_poss_share"] = s["off_poss"] / (s["off_poss"] + s["off_court_off_poss"])
    return s


def with_without_pair(pg: pd.DataFrame, tg: pd.DataFrame, a: int, b: int) -> pd.DataFrame:
    """Team net rating in the three states of a two-player pair, by game.

    Possession-level co-presence is not available for the whole season, so this
    operates at game granularity: it compares team performance in games where
    both played, exactly one played, and neither played.
    """
    sub = pg[pg.player_id.isin([a, b])][["game_id", "team_id", "player_id", "minutes"]]
    wide = sub.pivot_table(index=["game_id", "team_id"], columns="player_id",
                           values="minutes", aggfunc="sum").reset_index()
    for pid in (a, b):
        if pid not in wide.columns:
            wide[pid] = np.nan
    team_id = pg.loc[pg.player_id == a, "team_id"].mode().iloc[0]
    games = tg[tg.team_id == team_id][["game_id", "off_poss", "def_poss", "points", "opponent_points", "win"]]
    games = games.merge(wide[["game_id", a, b]], on="game_id", how="left")
    games["state"] = np.select(
        [games[a].notna() & games[b].notna(), games[a].notna(), games[b].notna()],
        ["both", "a_only", "b_only"], default="neither",
    )
    out = games.groupby("state", as_index=False).agg(
        games=("game_id", "nunique"), w=("win", "sum"),
        pf=("points", "sum"), pa=("opponent_points", "sum"),
        op=("off_poss", "sum"), dp=("def_poss", "sum"),
    )
    out["ortg"] = out.pf / out.op * 100
    out["drtg"] = out.pa / out.dp * 100
    out["net"] = out.ortg - out.drtg
    return out
