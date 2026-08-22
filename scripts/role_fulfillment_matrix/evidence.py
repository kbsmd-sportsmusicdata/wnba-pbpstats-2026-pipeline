"""Long-form evidence records for score transparency."""

from __future__ import annotations

from typing import Any, Dict, Iterable


def build_evidence_rows(
    row: Dict[str, Any],
    families: Dict[str, Iterable[Dict[str, Any]]],
    config: Dict[str, Any],
) -> list[Dict[str, Any]]:
    windows = config["windows"]
    denominators = {
        "off_poss": row.get("recent_off_poss"),
        "true_shooting_attempts": row.get("recent_true_shooting_attempts"),
        "turnovers": row.get("recent_turnovers"),
        "fga": row.get("recent_fga"),
        "at_rim_fga": row.get("recent_at_rim_fga"),
        "team_possessions": row.get("recent_team_possessions"),
        "recent_games": row.get("recent_games"),
    }
    stability_denominators = {
        "games": config["stability"]["recent_games_target"],
        "possessions": config["stability"]["recent_off_poss_target"],
        "consistency": row.get("recent_games"),
        "assignment_confidence": 1.0,
    }
    records = []
    for family, metrics in families.items():
        for metric in metrics:
            code = metric["code"]
            denominator_name = metric.get("denominator")
            if not denominator_name:
                if code in {"minutes_per_game", "games", "consistency", "assignment_confidence"}:
                    denominator_name = "recent_games"
                else:
                    denominator_name = "team_possessions"
            denominator = denominators.get(denominator_name, row.get("recent_games"))
            metadata = {
                "source_name": "synthetic_fixture_player_game",
                "window_scope": "recent",
                "window_start": windows["recent_start"],
                "window_end": windows["recent_end"],
                "baseline_denominator": None,
                "recent_denominator": denominator,
                "safeguard": "fixture_only; rates_recomputed_from_additive_counts",
            }
            if family == "stability":
                denominator = stability_denominators[code]
                metadata["recent_denominator"] = denominator
            if code == "possession_share_delta":
                metadata.update({
                    "window_scope": "baseline_to_recent",
                    "window_start": windows["baseline_start"],
                    "baseline_denominator": row.get("baseline_team_possessions"),
                    "recent_denominator": row.get("recent_team_possessions"),
                })
            elif code == "assignment_confidence":
                reviewed_at = row.get("assignment_reviewed_at")
                metadata.update({
                    "source_name": "synthetic_fixture_role_assignments",
                    "window_scope": "assignment_review",
                    "window_start": reviewed_at,
                    "window_end": reviewed_at,
                    "baseline_denominator": None,
                    "recent_denominator": None,
                    "safeguard": "fixture_only; reviewed_role_assignment",
                })
            records.append({
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "role_code": row["role_code"],
                "score_family": family,
                "metric_code": code,
                "metric_value": metric.get("value"),
                "component_score": metric.get("component_score"),
                "denominator": denominator,
                **metadata,
            })
    return records
