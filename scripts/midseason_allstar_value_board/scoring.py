from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from .candidate_pool import safe_divide


def percentile_score(series: pd.Series | None, *, higher_is_better: bool = True) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    values = pd.to_numeric(series, errors="coerce")
    if not higher_is_better:
        values = -values
    if values.notna().sum() <= 1:
        return pd.Series(np.where(values.notna(), 100.0, np.nan), index=series.index)
    return values.rank(pct=True, method="average") * 100


def mean_available(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    existing = [c for c in cols if c in df.columns]
    if not existing:
        return pd.Series(np.nan, index=df.index)
    return df[existing].mean(axis=1, skipna=True)


def build_metric_panel(player_features: pd.DataFrame, candidate_pool: pd.DataFrame, team_context: pd.DataFrame) -> pd.DataFrame:
    df = player_features.copy()
    df["player_id"] = df["entity_id_feature"].astype(str)
    df["player_name"] = df["entity_name_feature"].astype(str)
    df["team_id"] = df.get("team_id", df["team_abbreviation"]).astype(str)
    df["pbpstats_minutes"] = pd.to_numeric(df.get("minutes"), errors="coerce")
    df["pbpstats_games_played"] = pd.to_numeric(df.get("games_played"), errors="coerce")
    df = df.drop(columns=[c for c in ["minutes", "games_played"] if c in df.columns])
    df["total_poss_for_rates"] = pd.to_numeric(df.get("total_poss"), errors="coerce")
    df["total_poss_for_rates"] = df["total_poss_for_rates"].fillna(pd.to_numeric(df.get("off_poss"), errors="coerce") + pd.to_numeric(df.get("def_poss"), errors="coerce"))

    for col in ["points", "rebounds", "assists", "turnovers", "steals", "blocks"]:
        df[f"{col}_per_75"] = safe_divide(df.get(col, np.nan), df["total_poss_for_rates"]) * 75
    df["stocks_per_75"] = df["steals_per_75"].fillna(0) + df["blocks_per_75"].fillna(0)
    df["assist_turnover_ratio"] = safe_divide(df.get("assists", np.nan), df.get("turnovers", np.nan))
    df["on_court_net_rating"] = pd.to_numeric(df.get("on_off_rtg"), errors="coerce") - pd.to_numeric(df.get("on_def_rtg"), errors="coerce")

    pool_cols = [
        "player_id",
        "position",
        "team_games_played",
        "availability_rate",
        "games_played",
        "minutes",
        "box_minutes",
        "box_games_played",
        "eligibility_minutes_source",
        "candidate_tier",
        "eligible_flag",
        "eligibility_reason",
    ]
    df = df.merge(candidate_pool[[c for c in pool_cols if c in candidate_pool.columns]], on="player_id", how="left")

    if "team_id_key" in team_context.columns:
        team_context = team_context.rename(columns={"team_id_key": "team_id"})
    team_cols = ["team_id", "team_win_pct", "team_net_rating"]
    df = df.merge(team_context[[c for c in team_cols if c in team_context.columns]].drop_duplicates("team_id"), on="team_id", how="left")
    df["team_relative_net_rating"] = df["on_court_net_rating"] - df["team_net_rating"]

    keep = [
        "player_id",
        "player_name",
        "team_id",
        "team_abbreviation",
        "position",
        "games_played",
        "team_games_played",
        "availability_rate",
        "minutes",
        "box_minutes",
        "box_games_played",
        "pbpstats_minutes",
        "pbpstats_games_played",
        "eligibility_minutes_source",
        "candidate_tier",
        "eligible_flag",
        "points_per_75",
        "rebounds_per_75",
        "assists_per_75",
        "stocks_per_75",
        "turnovers_per_75",
        "assist_turnover_ratio",
        "usage",
        "ts_pct_feature",
        "efg_pct_feature",
        "shotquality_pbp_feature",
        "shot_making_over_shotquality_pbp",
        "fta_rate_feature",
        "on_court_net_rating",
        "team_relative_net_rating",
        "team_win_pct",
        "team_net_rating",
        "sample_size_flag",
        "shooting_efficiency_category",
        "shotquality_pbp_profile_label",
        "shot_diet_profile_label",
        "specialized_shooter_label",
        "shot_diet_risk_label",
        "rim_fga_share",
        "three_point_fga_share",
        "midrange_fga_share",
    ]
    return df[[c for c in keep if c in df.columns]].copy()


def build_value_board(metric_panel: pd.DataFrame, weights: Dict[str, float]) -> pd.DataFrame:
    df = metric_panel.copy()
    df["production_score"] = mean_available(
        pd.DataFrame(
            {
                "points": percentile_score(df.get("points_per_75")),
                "rebounds": percentile_score(df.get("rebounds_per_75")),
                "assists": percentile_score(df.get("assists_per_75")),
                "stocks": percentile_score(df.get("stocks_per_75")),
                "turnover_discipline": percentile_score(df.get("turnovers_per_75"), higher_is_better=False),
            }
        ),
        ["points", "rebounds", "assists", "stocks", "turnover_discipline"],
    )
    df["efficiency_score"] = mean_available(
        pd.DataFrame(
            {
                "ts": percentile_score(df.get("ts_pct_feature")),
                "efg": percentile_score(df.get("efg_pct_feature")),
                "shot_making": percentile_score(df.get("shot_making_over_shotquality_pbp")),
                "shot_quality": percentile_score(df.get("shotquality_pbp_feature")),
                "fta_rate": percentile_score(df.get("fta_rate_feature")),
            }
        ),
        ["ts", "efg", "shot_making", "shot_quality", "fta_rate"],
    )
    df["creation_score"] = mean_available(
        pd.DataFrame(
            {
                "usage": percentile_score(df.get("usage")),
                "assists": percentile_score(df.get("assists_per_75")),
                "assist_turnover": percentile_score(df.get("assist_turnover_ratio")),
                "turnover_discipline": percentile_score(df.get("turnovers_per_75"), higher_is_better=False),
            }
        ),
        ["usage", "assists", "assist_turnover", "turnover_discipline"],
    )
    df["impact_score"] = mean_available(
        pd.DataFrame(
            {
                "on_court": percentile_score(df.get("on_court_net_rating")),
                "relative": percentile_score(df.get("team_relative_net_rating")),
                "stocks": percentile_score(df.get("stocks_per_75")),
            }
        ),
        ["on_court", "relative", "stocks"],
    )
    df["availability_score"] = mean_available(
        pd.DataFrame(
            {
                "minutes": percentile_score(df.get("minutes")),
                "games": percentile_score(df.get("games_played")),
                "availability": percentile_score(df.get("availability_rate")),
            }
        ),
        ["minutes", "games", "availability"],
    )
    df["team_context_score"] = mean_available(
        pd.DataFrame(
            {
                "win_pct": percentile_score(df.get("team_win_pct")),
                "net": percentile_score(df.get("team_net_rating")),
            }
        ),
        ["win_pct", "net"],
    )

    default_weights = {
        "production": 0.25,
        "efficiency": 0.20,
        "creation": 0.15,
        "impact": 0.20,
        "availability": 0.10,
        "team_context": 0.10,
    }
    default_weights.update(weights or {})
    total_weight = sum(default_weights.values()) or 1
    components = ["production", "efficiency", "creation", "impact", "availability", "team_context"]
    weighted_sum = pd.Series(0.0, index=df.index)
    sum_weights = pd.Series(0.0, index=df.index)
    for comp in components:
        score_col = f"{comp}_score"
        weight = default_weights[comp]
        weighted_sum += df[score_col].fillna(0) * weight
        sum_weights += df[score_col].notna() * weight
    df["allstar_value_score"] = safe_divide(weighted_sum, sum_weights)

    if "eligible_flag" in df.columns:
        df = df[df["eligible_flag"].fillna(False).astype(bool)].copy()

    df = df.sort_values("allstar_value_score", ascending=False).reset_index(drop=True)
    df["overall_rank"] = np.arange(1, len(df) + 1)
    df["team_rank"] = df.groupby("team_abbreviation")["allstar_value_score"].rank(ascending=False, method="first").astype(int)
    df["score_band"] = pd.cut(
        df["allstar_value_score"],
        bins=[-np.inf, 45, 60, 75, 90, np.inf],
        labels=["Deep Watch", "Rotation Value", "All-Star Case", "Strong All-Star Case", "Board Headliner"],
    ).astype(str)
    df["board_note"] = df.apply(
        lambda row: f"{row['score_band']}: {row['candidate_tier']} with {row['production_score']:.1f} production and {row['impact_score']:.1f} impact scores.",
        axis=1,
    )
    return df
