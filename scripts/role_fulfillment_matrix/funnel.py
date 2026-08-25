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
    players = sources.roster_status[
        [
            "player_id",
            "player_name",
            "team_abbreviation",
            "position_name",
            "position_abbreviation",
            "active",
            "status_type",
        ]
    ].copy()
    if players["player_id"].duplicated().any():
        raise ValueError("roster status contains duplicate player ids")
    standings = sources.standings[["team_abbreviation", "current_rank"]]
    eligibility = sources.eligibility.rename(columns={
        "review_status": "eligibility_review_status",
        "player_name": "eligibility_player_name",
        "team_abbreviation": "eligibility_team_abbreviation",
        "position_name": "eligibility_snapshot_position_name",
        "position_abbreviation": "eligibility_snapshot_position_abbreviation",
        "active": "eligibility_snapshot_active",
        "status_type": "eligibility_snapshot_status_type",
        "reviewed_by": "eligibility_reviewed_by",
        "reviewed_at": "eligibility_reviewed_at",
        "source_url": "eligibility_source_url",
    })
    assignments = sources.role_assignments.rename(columns={
        "review_status": "assignment_review_status",
        "player_name": "assignment_player_name",
        "team_abbreviation": "assignment_team_abbreviation",
        "reviewed_by": "assignment_reviewed_by",
        "reviewed_at": "assignment_reviewed_at",
    })
    frame = players.merge(standings, on="team_abbreviation", how="left")
    frame = frame.merge(eligibility, on="player_id", how="left")
    frame = frame.merge(assignments, on="player_id", how="left")
    metric_columns = [c for c in metrics.columns if c != "player_name"]
    frame = frame.merge(
        metrics[metric_columns],
        on=["player_id", "team_abbreviation"],
        how="left",
        validate="one_to_one",
    )

    max_rank = float(config["contender"]["current_rank_max"])
    min_games = int(config["minimums"]["recent_games"])
    min_poss = float(config["minimums"]["recent_off_poss"])
    season_fallback_poss = float(config["minimums"]["season_off_poss_fallback"])
    valid_roles = set(sources.role_definitions)

    recent_games = pd.to_numeric(frame.get("recent_games"), errors="coerce").fillna(0)
    recent_poss = pd.to_numeric(frame.get("recent_off_poss"), errors="coerce").fillna(0)
    season_poss = pd.to_numeric(frame.get("season_off_poss"), errors="coerce").fillna(0)
    status_type = frame["status_type"].astype("string").str.strip().str.lower()
    active = frame["active"].map(_as_bool)

    frame["recent_games_met"] = recent_games.ge(min_games)
    frame["recent_possessions_met"] = recent_poss.ge(min_poss)
    frame["insufficient_recent_games"] = ~frame["recent_games_met"]
    frame["insufficient_recent_possessions"] = ~frame["recent_possessions_met"]
    frame["season_possessions_met"] = season_poss.ge(season_fallback_poss)
    frame["recent_sample_met"] = (
        frame["recent_games_met"] & frame["recent_possessions_met"]
    )
    frame["inactive_rostered"] = status_type.eq("inactive")
    frame["currently_rostered"] = ~status_type.eq("free-agent")
    frame["score_eligible"] = active & frame["recent_sample_met"]
    frame["sample_status"] = "insufficient_recent_sample"
    frame.loc[
        frame["recent_games_met"] & ~frame["recent_possessions_met"],
        "sample_status",
    ] = "insufficient_recent_possessions"
    frame.loc[
        frame["season_possessions_met"] & ~frame["recent_sample_met"],
        "sample_status",
    ] = "season_volume_met_recent_sample_insufficient"
    frame.loc[frame["recent_sample_met"], "sample_status"] = "recent_sample_met"

    reasons = []
    for row in frame.to_dict("records"):
        if pd.isna(row.get("current_rank")) or float(row["current_rank"]) > max_rank:
            reason = "non_contender_team"
        elif row.get("eligibility_review_status") != "reviewed":
            reason = "eligibility_not_reviewed"
        elif not _as_bool(row.get("eligible_flag")):
            reason = "not_age_experience_eligible"
        elif str(row.get("status_type", "")).strip().lower() == "free-agent":
            reason = "not_currently_rostered"
        elif (
            _as_bool(row.get("inactive_rostered"))
            and row.get("assignment_review_status") != "reviewed"
        ):
            reason = "inactive_role_review_deferred"
        elif row.get("assignment_review_status") != "reviewed":
            reason = "role_assignment_not_reviewed"
        elif (
            pd.notna(row.get("assignment_team_abbreviation"))
            and str(row.get("assignment_team_abbreviation")).strip()
            and row.get("assignment_team_abbreviation") != row.get("team_abbreviation")
        ):
            reason = "role_assignment_team_mismatch"
        elif row.get("role_code") not in valid_roles:
            reason = "role_assignment_invalid"
        elif _as_bool(row.get("inactive_rostered")):
            reason = ""
        elif _as_bool(row.get("recent_sample_met")):
            reason = ""
        elif _as_bool(row.get("season_possessions_met")):
            reason = ""
        elif not _as_bool(row.get("recent_games_met")):
            reason = "insufficient_recent_sample"
        elif not _as_bool(row.get("recent_possessions_met")):
            reason = "insufficient_recent_possessions"
        else:
            reason = ""
        reasons.append(reason)

    frame["exclusion_reason"] = reasons
    frame["funnel_status"] = frame["exclusion_reason"].map(lambda value: "included" if not value else "excluded")
    return frame.sort_values(["funnel_status", "current_rank", "player_name"], ascending=[False, True, True]).reset_index(drop=True)
