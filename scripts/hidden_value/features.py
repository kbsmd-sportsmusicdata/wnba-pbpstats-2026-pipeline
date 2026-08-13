"""Assemble the player panel the hidden-value board scores.

Four families of signal, each answering a different question:

* **Role** -- how much is this player *asked* to do? Minutes, usage, starts, share of team
  possessions. These are the reputation proxies the residual is taken against.
* **Impact** -- how much do they actually help? RAPM where it exists, on-court net rating
  otherwise.
* **Regression** -- is their current output likely to move? Shot quality against shot
  making, with free-throw shooting as a prior on three-point talent.
* **Playoff fit** -- do their skills survive a shorter rotation and a slower half-court
  game?
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def safe_divide(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(pd.notna(denominator) & (denominator != 0), numerator / denominator, np.nan)


def percentile(series: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    """Rank a column to 0-100, so signals on different scales can be combined."""
    values = pd.to_numeric(series, errors="coerce")
    if not higher_is_better:
        values = -values
    if values.notna().sum() <= 1:
        return pd.Series(np.where(values.notna(), 50.0, np.nan), index=series.index)
    return values.rank(pct=True) * 100


def build_start_rate(possessions: pd.DataFrame) -> pd.DataFrame:
    """Games started over games appeared, derived from the possession feed.

    The box scores carry a starter flag but use ESPN athlete ids, a different id space from
    everything else here. Opening-possession lineups keep the whole module on one key.
    """
    columns = ["player_id", "games_started", "games_appeared", "start_rate"]
    offense = [f"off_player_{i}" for i in range(1, 6)]
    defense = [f"def_player_{i}" for i in range(1, 6)]
    if possessions.empty or not set(offense + defense).issubset(possessions.columns):
        return pd.DataFrame(columns=columns)

    frame = possessions.dropna(subset=offense + defense).copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)

    appeared: Dict[int, set] = {}
    started: Dict[int, set] = {}
    opening = (
        frame[frame["period"] == 1]
        .sort_values(["game_id", "possession_number"])
        .groupby("game_id", sort=False)
        .head(1)
    )
    for row in frame.itertuples(index=False):
        game = str(getattr(row, "game_id"))
        for column in offense + defense:
            appeared.setdefault(int(getattr(row, column)), set()).add(game)
    for row in opening.itertuples(index=False):
        game = str(getattr(row, "game_id"))
        for column in offense + defense:
            started.setdefault(int(getattr(row, column)), set()).add(game)

    rows = [
        {
            "player_id": player,
            "games_started": len(started.get(player, set())),
            "games_appeared": len(games),
            "start_rate": len(started.get(player, set())) / len(games) if games else np.nan,
        }
        for player, games in appeared.items()
    ]
    return pd.DataFrame(rows).sort_values("player_id").reset_index(drop=True)


def build_player_panel(
    player_features: pd.DataFrame,
    team_features: pd.DataFrame,
    rapm: pd.DataFrame,
    start_rates: pd.DataFrame,
    trajectories: pd.DataFrame,
    player_impact: pd.DataFrame,
) -> pd.DataFrame:
    """One row per player carrying every signal the board scores."""
    if player_features.empty:
        return pd.DataFrame()

    frame = player_features.copy()
    panel = pd.DataFrame({"player_id": pd.to_numeric(frame["entity_id"], errors="coerce").astype("Int64")})
    panel["player_name"] = frame.get("name")
    panel["team_abbreviation"] = frame.get("team_abbreviation")
    panel["position"] = frame.get("position")

    # --- role -------------------------------------------------------------------------
    panel["minutes"] = _numeric(frame, "minutes")
    panel["games_played"] = _numeric(frame, "games_played")
    panel["usage"] = _numeric(frame, "usage")
    total_poss = _numeric(frame, "total_poss")
    panel["total_poss"] = total_poss.where(total_poss.notna(), _numeric(frame, "off_poss") + _numeric(frame, "def_poss"))

    # --- impact -----------------------------------------------------------------------
    panel["on_court_net_rating"] = _numeric(frame, "on_off_rtg") - _numeric(frame, "on_def_rtg")

    # --- shooting and regression signals ----------------------------------------------
    panel["efg_pct"] = _numeric(frame, "efg_pct_feature")
    panel["ts_pct"] = _numeric(frame, "ts_pct_feature")
    panel["shot_quality"] = _numeric(frame, "shotquality_pbp_feature")
    panel["shot_making_residual"] = _numeric(frame, "shot_making_over_shotquality_pbp")
    panel["fga"] = _numeric(frame, "fg2_a") + _numeric(frame, "fg3_a")
    panel["fg3_a"] = _numeric(frame, "fg3_a")
    panel["fg3_pct"] = _numeric(frame, "fg3_pct")
    panel["ft_pct"] = pd.Series(safe_divide(_numeric(frame, "ft_points"), _numeric(frame, "fta")), index=frame.index)
    panel["fta_rate"] = _numeric(frame, "fta_rate_feature")

    # --- playoff fit ------------------------------------------------------------------
    panel["at_rim_pct_assisted"] = _numeric(frame, "at_rim_pct_assisted")
    panel["assisted2s_pct"] = _numeric(frame, "assisted2s_pct")
    panel["corner3_share_of_3pa"] = pd.Series(
        safe_divide(_numeric(frame, "corner3_fga"), _numeric(frame, "fg3_a")), index=frame.index
    )
    panel["live_ball_turnover_pct"] = _numeric(frame, "live_ball_turnover_pct")
    panel["rim_and_three_share"] = _numeric(frame, "rim_and_three_fga_share")

    panel = panel.dropna(subset=["player_id"]).reset_index(drop=True)

    # --- joins ------------------------------------------------------------------------
    if not rapm.empty:
        side = rapm[["player_id", "o_rapm", "d_rapm", "rapm", "total_poss"]].copy()
        side = side.rename(columns={"total_poss": "rapm_poss"})
        side["player_id"] = pd.to_numeric(side["player_id"], errors="coerce").astype("Int64")
        panel = panel.merge(side, on="player_id", how="left")

    if not start_rates.empty:
        side = start_rates.copy()
        side["player_id"] = pd.to_numeric(side["player_id"], errors="coerce").astype("Int64")
        panel = panel.merge(side, on="player_id", how="left")

    if not trajectories.empty:
        side = trajectories.copy()
        side["player_id"] = pd.to_numeric(side["player_id"], errors="coerce").astype("Int64")
        panel = panel.merge(side, on="player_id", how="left")

    if not player_impact.empty and "darko_projected_rating" in player_impact.columns:
        side = player_impact[["player_id", "darko_projected_rating"]].copy()
        side["player_id"] = pd.to_numeric(side["player_id"], errors="coerce").astype("Int64")
        panel = panel.merge(side.drop_duplicates("player_id"), on="player_id", how="left")

    if not team_features.empty and {"team_abbreviation", "points", "off_poss"}.issubset(team_features.columns):
        teams = team_features.copy()
        teams["team_net_rating"] = (
            _numeric(teams, "points") / _numeric(teams, "off_poss")
            - _numeric(teams, "opponent_points") / _numeric(teams, "def_poss")
        ) * 100
        panel = panel.merge(
            teams[["team_abbreviation", "team_net_rating"]].drop_duplicates("team_abbreviation"),
            on="team_abbreviation",
            how="left",
        )

    return panel


def apply_eligibility(panel: pd.DataFrame, *, min_total_possessions: int, min_games_played: int,
                      reliable_total_possessions: int) -> pd.DataFrame:
    """Drop players too thin to say anything about, and flag the merely thin."""
    if panel.empty:
        return panel
    out = panel.copy()
    possessions = pd.to_numeric(out["total_poss"], errors="coerce").fillna(0)
    games = pd.to_numeric(out["games_played"], errors="coerce").fillna(0)
    out = out[(possessions >= min_total_possessions) & (games >= min_games_played)].copy()
    out["sample_flag"] = np.where(
        pd.to_numeric(out["total_poss"], errors="coerce") >= reliable_total_possessions,
        "Reliable",
        "Low sample",
    )
    return out.reset_index(drop=True)


def build_playoff_fit(panel: pd.DataFrame) -> pd.Series:
    """Score the skills that hold up in a shorter, slower playoff rotation.

    Self-creation is weighted most heavily: playoff defences take away the easy, assisted
    looks first, so a player who needs the offence to create for them loses the most.
    """
    if panel.empty:
        return pd.Series(dtype=float)

    parts = pd.DataFrame(
        {
            # Lower assisted share means more self-creation.
            "self_creation": percentile(panel.get("assisted2s_pct"), higher_is_better=False),
            "rim_independence": percentile(panel.get("at_rim_pct_assisted"), higher_is_better=False),
            "foul_drawing": percentile(panel.get("fta_rate")),
            "corner_reliability": percentile(panel.get("corner3_share_of_3pa")),
            "shot_diet": percentile(panel.get("rim_and_three_share")),
            "ball_security": percentile(panel.get("live_ball_turnover_pct"), higher_is_better=False),
            # A player who will not be in the rotation is not actionable, however good.
            "rotation_security": percentile(panel.get("on_court_poss_share_recent")),
        }
    )
    weights = {
        "self_creation": 0.25,
        "rim_independence": 0.10,
        "foul_drawing": 0.15,
        "corner_reliability": 0.10,
        "shot_diet": 0.10,
        "ball_security": 0.10,
        "rotation_security": 0.20,
    }
    weighted = sum(parts[name].fillna(50.0) * weight for name, weight in weights.items())
    return weighted / sum(weights.values())


def build_regression_upside(panel: pd.DataFrame, *, min_fga: int, free_throw_prior_weight: float) -> pd.DataFrame:
    """Flag players whose current shooting is likely to move, and which way.

    The core signal is shot making against shot quality: a player generating good looks and
    missing them is a buy, one converting mediocre looks at a high rate is a sell. Free
    throw percentage acts as a prior on three-point talent, because it is a cleaner read on
    touch and stabilises far sooner than three-point percentage.
    """
    columns = ["shot_making_residual", "regression_upside_raw", "regression_upside_score", "three_point_prior_gap"]
    if panel.empty:
        return pd.DataFrame(columns=columns)

    out = pd.DataFrame(index=panel.index)
    residual = pd.to_numeric(panel.get("shot_making_residual"), errors="coerce")
    fga = pd.to_numeric(panel.get("fga"), errors="coerce")

    # A negative residual is upside: the looks are there, the shots are not falling yet.
    upside = -residual
    upside = upside.where(fga >= min_fga)

    ft_pct = pd.to_numeric(panel.get("ft_pct"), errors="coerce")
    fg3_pct = pd.to_numeric(panel.get("fg3_pct"), errors="coerce")
    fg3a = pd.to_numeric(panel.get("fg3_a"), errors="coerce")
    # Free-throw shooters converting threes below what their touch implies have room.
    prior_gap = (ft_pct - 0.40) - (fg3_pct - 0.33)
    prior_gap = prior_gap.where((fg3a >= 40) & ft_pct.notna() & fg3_pct.notna())

    out["shot_making_residual"] = residual
    out["three_point_prior_gap"] = prior_gap
    out["regression_upside_raw"] = upside.fillna(0.0) + free_throw_prior_weight * prior_gap.fillna(0.0)
    out["regression_upside_score"] = percentile(out["regression_upside_raw"])
    return out
