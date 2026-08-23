"""Season-level metric derivation for the UCLA 2026 draft class EDA.

Everything is rebuilt from summed game-log counting stats so rate stats are
possession-weighted, not averages-of-averages.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

COUNT_COLS = [
    "minutes", "off_poss", "def_poss", "total_poss", "points", "fg2_m", "fg2_a",
    "fg3_m", "fg3_a", "ft_points", "fta", "at_rim_fgm", "at_rim_fga",
    "short_mid_range_fgm", "short_mid_range_fga", "long_mid_range_fgm",
    "long_mid_range_fga", "corner3_fgm", "corner3_fga", "arc3_fgm", "arc3_fga",
    "assists", "two_pt_assists", "three_pt_assists", "assist_points",
    "turnovers", "live_ball_turnovers", "dead_ball_turnovers",
    "bad_pass_turnovers", "lost_ball_turnovers", "off_rebounds", "def_rebounds",
    "rebounds", "self_oreb", "steals", "blocks", "blocked_at_rim", "fouls",
    "shooting_fouls", "offensive_fouls", "fouls_drawn", "charge_fouls_drawn",
    "two_pt_shooting_fouls_drawn", "three_pt_shooting_fouls_drawn",
    "pts_assisted2s", "pts_unassisted2s", "pts_assisted3s", "pts_unassisted3s",
    "pts_putbacks", "second_chance_points", "penalty_points", "first_chance_points",
    "fg2a_blocked", "fg3a_blocked", "plus_minus", "team_points", "opponent_points",
    "second_chance_off_poss", "penalty_off_poss", "recovered_blocks",
]

# opportunity-denominated rebound/shot-quality rates need possession weighting
WEIGHTED_RATE_COLS = {
    "off_fgrebound_pct": "off_poss",
    "def_fgrebound_pct": "def_poss",
    "off_at_rim_rebound_pct": "off_poss",
    "def_at_rim_rebound_pct": "def_poss",
    "def_three_pt_rebound_pct": "def_poss",
    "off_three_pt_rebound_pct": "off_poss",
    "self_oreb_pct": "off_poss",
    "shot_quality_avg": "fga_total",
    "on_off_rtg": "off_poss",
    "on_def_rtg": "def_poss",
    "usage": "off_poss",
    "avg2pt_shot_distance": "fg2_a",
    "avg3pt_shot_distance": "fg3_a",
}


def _safe(num, den):
    num = pd.to_numeric(num, errors="coerce")
    den = pd.to_numeric(den, errors="coerce")
    return np.where((den.notna()) & (den != 0), num / den, np.nan)


def season_totals(pg: pd.DataFrame, key=("player_id", "player_name")) -> pd.DataFrame:
    """Sum counting stats and possession-weight the rate stats."""
    df = pg.copy()
    df["fga_total"] = df["fg2_a"].fillna(0) + df["fg3_a"].fillna(0)
    present = [c for c in COUNT_COLS if c in df.columns]
    agg = df.groupby(list(key), as_index=False)[present + ["fga_total"]].sum(min_count=1)
    agg["games_played"] = df.groupby(list(key))["game_id"].nunique().values
    agg["team_wins"] = df.groupby(list(key))["win"].sum().values
    agg["teams"] = (
        df.groupby(list(key))["team_abbreviation"]
        .agg(lambda s: "/".join(sorted(set(s))))
        .values
    )

    for col, wcol in WEIGHTED_RATE_COLS.items():
        if col not in df.columns or wcol not in df.columns:
            continue
        w = df[wcol].fillna(0)
        v = pd.to_numeric(df[col], errors="coerce")
        ok = v.notna()
        tmp = pd.DataFrame({"k": list(zip(*[df[k] for k in key])), "wv": v.where(ok) * w.where(ok), "w": w.where(ok)})
        g = tmp.groupby("k").sum(min_count=1)
        vals = _safe(g["wv"], g["w"])
        agg[col] = pd.Series(vals, index=g.index).reindex(
            list(zip(*[agg[k] for k in key]))
        ).values
    return agg


def derive(agg: pd.DataFrame) -> pd.DataFrame:
    """Per-100-possession volume rates plus efficiency and profile shares."""
    d = agg.copy()
    op = d["off_poss"].replace(0, np.nan)
    dp = d["def_poss"].replace(0, np.nan)
    tp = (d["off_poss"] + d["def_poss"]).replace(0, np.nan)
    fga = d["fga_total"].replace(0, np.nan)
    mins = d["minutes"].replace(0, np.nan)

    d["min_per_game"] = d["minutes"] / d["games_played"]
    d["pts_per_game"] = d["points"] / d["games_played"]
    d["pace_neutral_pts_75"] = d["points"] / op * 75
    d["ast_75"] = d["assists"] / op * 75
    d["tov_75"] = d["turnovers"] / op * 75
    d["live_tov_75"] = d["live_ball_turnovers"] / op * 75
    d["oreb_75"] = d["off_rebounds"] / op * 75
    d["dreb_75"] = d["def_rebounds"] / dp * 75
    d["stl_75"] = d["steals"] / dp * 75
    d["blk_75"] = d["blocks"] / dp * 75
    d["stocks_75"] = d["stl_75"] + d["blk_75"]
    d["foul_75"] = d["fouls"] / dp * 75
    d["fouls_drawn_75"] = d["fouls_drawn"] / op * 75
    d["shot_75"] = d["fga_total"] / op * 75
    d["fta_75"] = d["fta"] / op * 75

    d["ts_pct"] = _safe(d["points"], 2 * (d["fga_total"] + 0.44 * d["fta"]))
    d["efg_pct"] = _safe(d["fg2_m"] + 1.5 * d["fg3_m"], fga)
    d["fg3_pct"] = _safe(d["fg3_m"], d["fg3_a"])
    d["fg2_pct"] = _safe(d["fg2_m"], d["fg2_a"])
    d["ftr"] = _safe(d["fta"], fga)
    d["ast_to_tov"] = _safe(d["assists"], d["turnovers"])
    d["ast_pts_created_75"] = d["assist_points"] / op * 75
    d["pts_plus_created_75"] = d["pace_neutral_pts_75"] + d["ast_pts_created_75"]

    # shot diet
    d["rim_share"] = _safe(d["at_rim_fga"], fga)
    d["short_mid_share"] = _safe(d["short_mid_range_fga"], fga)
    d["long_mid_share"] = _safe(d["long_mid_range_fga"], fga)
    d["mid_share"] = d["short_mid_share"] + d["long_mid_share"]
    d["three_share"] = _safe(d["fg3_a"], fga)
    d["corner3_share"] = _safe(d["corner3_fga"], fga)
    d["rim_and_three_share"] = d["rim_share"] + d["three_share"]
    d["rim_accuracy"] = _safe(d["at_rim_fgm"], d["at_rim_fga"])
    d["three_accuracy"] = _safe(d["fg3_m"], d["fg3_a"])
    d["blocked_rate"] = _safe(d["fg2a_blocked"] + d["fg3a_blocked"], fga)

    # self-creation vs. play-finishing
    made_pts_from_fg = (
        d["pts_assisted2s"] + d["pts_unassisted2s"] + d["pts_assisted3s"] + d["pts_unassisted3s"]
    ).replace(0, np.nan)
    d["unassisted_pts_share"] = _safe(d["pts_unassisted2s"] + d["pts_unassisted3s"], made_pts_from_fg)
    d["putback_pts_share"] = _safe(d["pts_putbacks"], made_pts_from_fg)
    d["second_chance_pts_share"] = _safe(d["second_chance_points"], d["points"])
    d["penalty_pts_share"] = _safe(d["penalty_points"], d["points"])

    # shot-making over expectation (pbpstats shot quality is an expected-eFG proxy)
    if "shot_quality_avg" in d.columns:
        d["shot_making_over_sq"] = d["efg_pct"] - d["shot_quality_avg"]

    # team-context / role share
    d["net_on_court"] = d["on_off_rtg"] - d["on_def_rtg"]
    d["pm_per_100"] = d["plus_minus"] / tp * 100
    return d


def add_percentiles(d: pd.DataFrame, cols, suffix="_pct_rank", pool_mask=None) -> pd.DataFrame:
    out = d.copy()
    base = out if pool_mask is None else out[pool_mask]
    for c in cols:
        if c not in out.columns:
            continue
        ranks = base[c].rank(pct=True)
        out[c + suffix] = ranks.reindex(out.index)
    return out
