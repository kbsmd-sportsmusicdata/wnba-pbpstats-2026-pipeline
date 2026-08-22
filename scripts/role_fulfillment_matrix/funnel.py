"""Ordered candidate gates with explicit exclusion reasons."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .data_sources import LoadedSources


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def build_candidate_funnel(
    sources: LoadedSources, metrics: pd.DataFrame, config: Dict[str, Any]
) -> pd.DataFrame:
    players = (
        sources.player_game.sort_values("game_date")
        .drop_duplicates("player_id", keep="last")
        [["player_id", "player_name", "team_abbreviation"]]
    )
    standings = sources.standings[["team_abbreviation", "current_rank"]]
    eligibility = sources.eligibility.rename(columns={
        "review_status": "eligibility_review_status",
        "player_name": "eligibility_player_name",
        "reviewed_by": "eligibility_reviewed_by",
        "reviewed_at": "eligibility_reviewed_at",
        "source_url": "eligibility_source_url",
    })
    assignments = sources.role_assignments.rename(columns={
        "review_status": "assignment_review_status",
        "player_name": "assignment_player_name",
        "reviewed_by": "assignment_reviewed_by",
        "reviewed_at": "assignment_reviewed_at",
    })
    frame = players.merge(standings, on="team_abbreviation", how="left")
    frame = frame.merge(eligibility, on="player_id", how="left")
    frame = frame.merge(assignments, on="player_id", how="left")
    metric_columns = [c for c in metrics.columns if c not in {"player_name", "team_abbreviation"}]
    frame = frame.merge(metrics[metric_columns], on="player_id", how="left")

    max_rank = float(config["contender"]["current_rank_max"])
    min_games = int(config["minimums"]["recent_games"])
    min_poss = float(config["minimums"]["recent_off_poss"])
    valid_roles = set(sources.role_definitions)

    reasons = []
    for row in frame.to_dict("records"):
        if pd.isna(row.get("current_rank")) or float(row["current_rank"]) > max_rank:
            reason = "non_contender_team"
        elif row.get("eligibility_review_status") != "reviewed":
            reason = "eligibility_not_reviewed"
        elif not _as_bool(row.get("eligible_flag")):
            reason = "not_age_experience_eligible"
        elif row.get("assignment_review_status") != "reviewed":
            reason = "role_assignment_not_reviewed"
        elif row.get("role_code") not in valid_roles:
            reason = "role_assignment_invalid"
        elif pd.isna(row.get("recent_games")) or float(row["recent_games"]) < min_games:
            reason = "insufficient_recent_sample"
        elif pd.isna(row.get("recent_off_poss")) or float(row["recent_off_poss"]) < min_poss:
            reason = "insufficient_recent_possessions"
        else:
            reason = ""
        reasons.append(reason)

    frame["exclusion_reason"] = reasons
    frame["funnel_status"] = frame["exclusion_reason"].map(lambda value: "included" if not value else "excluded")
    return frame.sort_values(["funnel_status", "current_rank", "player_name"], ascending=[False, True, True]).reset_index(drop=True)
