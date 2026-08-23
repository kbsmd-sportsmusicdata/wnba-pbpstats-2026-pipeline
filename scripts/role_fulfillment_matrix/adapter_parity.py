"""Locked metric parity checks shared by adapter review and live dry runs."""

from __future__ import annotations

import pandas as pd


PARITY_FIELDS = [
    "recent_games",
    "recent_off_poss",
    "recent_total_poss",
    "recent_fga",
    "recent_true_shooting_attempts",
    "recent_at_rim_fga",
    "recent_assists_per_75",
    "recent_true_shooting_pct",
    "recent_turnover_rate",
    "recent_three_point_fga_share",
    "recent_fta_rate",
    "recent_rim_fga_share",
    "recent_rim_fg_pct",
    "recent_rebounds_per_75_total_possessions",
    "recent_offensive_rebounds_per_75_off_poss",
]


def build_adapter_parity(metrics: pd.DataFrame, locked: pd.DataFrame) -> pd.DataFrame:
    """Compare canonical window metrics with independently locked player values."""
    metric_rows = metrics.copy()
    metric_rows["player_id"] = metric_rows["player_id"].astype(str)
    expected = locked.copy()
    expected["player_id"] = expected["player_id"].astype(str)
    metric_rows = metric_rows[metric_rows["player_id"].isin(set(expected["player_id"]))]
    merged = expected[["player_id", "player_name", "role_code"] + PARITY_FIELDS].merge(
        metric_rows[["player_id"] + PARITY_FIELDS],
        on="player_id",
        how="left",
        suffixes=("_locked", "_adapted"),
        validate="one_to_one",
    )
    rows = []
    for record in merged.to_dict("records"):
        differences = []
        missing_fields = []
        for field in PARITY_FIELDS:
            locked_value = record[f"{field}_locked"]
            adapted_value = record[f"{field}_adapted"]
            if pd.isna(adapted_value):
                missing_fields.append(field)
            else:
                differences.append(abs(float(adapted_value) - float(locked_value)))
        maximum = max(differences) if differences else float("nan")
        rows.append(
            {
                "player_id": record["player_id"],
                "player_name": record["player_name"],
                "role_code": record["role_code"],
                "fields_compared": len(PARITY_FIELDS),
                "missing_fields": ";".join(missing_fields),
                "max_abs_difference": maximum,
                "parity_match": not missing_fields and maximum <= 0.000001,
            }
        )
    return pd.DataFrame(rows)
