from __future__ import annotations

import pandas as pd


def _reason(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def assign_archetypes(metric_panel: pd.DataFrame, value_board: pd.DataFrame) -> pd.DataFrame:
    df = metric_panel.merge(
        value_board[
            [
                "player_id",
                "allstar_value_score",
                "production_score",
                "efficiency_score",
                "creation_score",
                "impact_score",
                "availability_score",
            ]
        ],
        on="player_id",
        how="left",
    ).copy()

    rows = []
    for _, row in df.iterrows():
        usage = row.get("usage", 0) or 0
        assists = row.get("assists_per_75", 0) or 0
        stocks = row.get("stocks_per_75", 0) or 0
        rebounds = row.get("rebounds_per_75", 0) or 0
        rim_share = row.get("rim_fga_share", 0) or 0
        three_share = row.get("three_point_fga_share", 0) or 0
        shot_making = row.get("shot_making_over_shotquality_pbp", 0) or 0
        tier = row.get("candidate_tier", "")
        primary = "High-Leverage Connector"
        secondary = row.get("specialized_shooter_label", "No Clear Secondary")
        confidence = 0.62
        reasons = []

        if tier == "Watchlist":
            primary = "Rising Sample Watch"
            confidence = 0.60
            reasons.append("watchlist workload keeps the signal promising but not fully eligible")
        if usage >= 24 and assists >= 3:
            primary = "Primary Engine"
            confidence = 0.82
            reasons.append("high usage paired with strong playmaking volume")
        elif row.get("allstar_value_score", 0) >= 80 and stocks >= 1.3:
            primary = "Two-Way Star"
            confidence = 0.78
            reasons.append("top-board composite score with defensive event value")
        elif rim_share >= 0.50 and rebounds >= 5:
            primary = "Efficient Interior Anchor"
            confidence = 0.76
            reasons.append("paint-heavy shot diet with strong rebounding volume")
        elif shot_making >= 0.04 and three_share >= 0.25:
            primary = "Shot-Making Wing"
            confidence = 0.74
            reasons.append("positive shot-making delta with real perimeter volume")
        elif rim_share >= 0.45:
            primary = "Rim-Pressure Finisher"
            confidence = 0.70
            reasons.append("rim-heavy profile creates paint pressure")
        elif three_share >= 0.40:
            primary = "Spacing Guard/Wing"
            confidence = 0.70
            reasons.append("three-point volume is the clearest offensive value signal")
        elif stocks >= 1.5 or rebounds >= 6:
            primary = "Defense/Glass Value"
            confidence = 0.68
            reasons.append("defensive event or rebounding value leads the profile")

        if not reasons:
            reasons.append("balanced profile without a single dominant value signal")
        if secondary in ("", "nan", None):
            secondary = row.get("shot_diet_profile_label", "No Clear Secondary")

        rows.append(
            {
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "team_abbreviation": row["team_abbreviation"],
                "primary_archetype": primary,
                "secondary_archetype": secondary,
                "archetype_confidence": round(confidence, 2),
                "archetype_reasons": _reason(*reasons),
                "shooting_efficiency_category": row.get("shooting_efficiency_category"),
                "shotquality_pbp_profile_label": row.get("shotquality_pbp_profile_label"),
                "shot_diet_profile_label": row.get("shot_diet_profile_label"),
                "specialized_shooter_label": row.get("specialized_shooter_label"),
                "shot_diet_risk_label": row.get("shot_diet_risk_label"),
            }
        )

    return pd.DataFrame(rows)

