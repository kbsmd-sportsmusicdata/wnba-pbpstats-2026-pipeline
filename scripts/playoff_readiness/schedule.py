"""Turning the ESPN schedule into a season that adds up.

Everything downstream -- ratings, simulations, seeds -- rests on two frames: the games
that have been played, and the games that have not. Getting those exactly right matters
more than any modelling choice, because a single phantom game hands a team a 45th result
and shifts its odds.

Three things in the raw feed need handling, and none of them announce themselves:

* the All-Star game, which involves teams that do not exist,
* the Commissioner's Cup championship, which is played by two real teams and does *not*
  count in the standings,
* postponement shells, which stay in the feed after the makeup game has been played under
  a new game id.

`reconcile_schedule` deals with all three and then checks its own work: every team must
finish with the same number of counting games, or the build stops.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# The pipeline's canonical abbreviations are the WNBA Stats ones; ESPN uses its own for
# six franchises. Same map as the rest of the repo.
TEAM_ABBR_ALIASES = {
    "GS": "GSV",
    "GSV": "GSV",
    "LA": "LAS",
    "LAS": "LAS",
    "LV": "LVA",
    "LVA": "LVA",
    "NY": "NYL",
    "NYL": "NYL",
    "PHO": "PHX",
    "PHX": "PHX",
    "POR": "PDX",
    "PDX": "PDX",
    "WSH": "WAS",
    "WAS": "WAS",
}

# Structural, not a statistic, so it is safe to hold as a constant -- but the standings
# feed overrides it when present, which is what `conference_map` is for.
WNBA_CONFERENCES = {
    "ATL": "East",
    "CHI": "East",
    "CON": "East",
    "IND": "East",
    "NYL": "East",
    "TOR": "East",
    "WAS": "East",
    "DAL": "West",
    "GSV": "West",
    "LAS": "West",
    "LVA": "West",
    "MIN": "West",
    "PDX": "West",
    "PHX": "West",
    "SEA": "West",
}

LEAGUE_TEAMS = tuple(sorted(WNBA_CONFERENCES))

# ESPN marks the Commissioner's Cup final `CC` and the All-Star game `ALLSTAR`. Cup *group*
# games are ordinary `STD` games and do count, which is why the flag rather than the
# `notes_type == "event"` marker is the right filter.
NON_COUNTING_GAME_TYPES = frozenset({"CC", "ALLSTAR"})


def team_key(value: Any) -> str:
    """Canonical abbreviation, or the input upper-cased if it is not a league team."""
    raw = str(value).strip().upper()
    return TEAM_ABBR_ALIASES.get(raw, raw)


def conference_map(standings: Optional[pd.DataFrame] = None) -> Dict[str, str]:
    """Conference per team, preferring the feed and falling back to the constant."""
    mapping = dict(WNBA_CONFERENCES)
    if standings is None or standings.empty:
        return mapping
    columns = {"team_id", "conference"}
    if not columns.issubset(standings.columns):
        return mapping
    for _, row in standings.iterrows():
        abbreviation = _abbreviation_from_standings(row)
        conference = str(row.get("conference", "")).strip().title()
        if abbreviation in mapping and conference in {"East", "West"}:
            mapping[abbreviation] = conference
    return mapping


def _abbreviation_from_standings(row: pd.Series) -> str:
    for column in ("team_abbreviation", "team_slug", "team_name"):
        value = row.get(column)
        if isinstance(value, str) and value.strip():
            candidate = team_key(value)
            if candidate in WNBA_CONFERENCES:
                return candidate
    return ""


def normalize_schedule(schedule: pd.DataFrame) -> pd.DataFrame:
    """One row per scheduled game with canonical team keys and a real date column."""
    required = {"game_id", "home_abbreviation", "away_abbreviation"}
    if schedule.empty or not required.issubset(schedule.columns):
        return pd.DataFrame(
            columns=[
                "game_id",
                "game_date",
                "home_team",
                "away_team",
                "home_score",
                "away_score",
                "completed",
                "status",
                "game_type",
                "neutral_site",
            ]
        )

    frame = pd.DataFrame(
        {
            "game_id": schedule["game_id"].astype(str),
            "game_date": pd.to_datetime(schedule.get("game_date").astype(str), errors="coerce"),
            "home_team": schedule["home_abbreviation"].map(team_key),
            "away_team": schedule["away_abbreviation"].map(team_key),
            "home_score": pd.to_numeric(schedule.get("home_score"), errors="coerce"),
            "away_score": pd.to_numeric(schedule.get("away_score"), errors="coerce"),
            "completed": schedule.get("status_type_completed").fillna(False).astype(bool),
            "status": schedule.get("status_type_name").astype(str),
            "game_type": schedule.get("type_abbreviation").astype(str).str.strip().str.upper(),
            "neutral_site": schedule.get("neutral_site").fillna(False).astype(bool),
        }
    )
    return frame.drop_duplicates(subset="game_id").reset_index(drop=True)


def reconcile_schedule(schedule: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Split the season into played and unplayed games, and prove the split adds up.

    Returns `(played, remaining, diagnostics)`. `diagnostics["reconciled"]` is False when
    the counting games do not come out level across the league; the caller is expected to
    treat that as fatal rather than simulate a season that does not exist.
    """
    frame = normalize_schedule(schedule)
    diagnostics: Dict[str, Any] = {"schedule_rows": int(len(frame))}
    if frame.empty:
        diagnostics.update({"reconciled": False, "reason": "empty_schedule"})
        return frame, frame, diagnostics

    league = frame["home_team"].isin(LEAGUE_TEAMS) & frame["away_team"].isin(LEAGUE_TEAMS)
    diagnostics["dropped_non_league_rows"] = int((~league).sum())
    frame = frame[league]

    counting = ~frame["game_type"].isin(NON_COUNTING_GAME_TYPES)
    diagnostics["dropped_non_counting_games"] = sorted(
        frame.loc[~counting, "game_type"].value_counts().to_dict().items()
    )
    frame = frame[counting]

    postponed = frame["status"].eq("STATUS_POSTPONED")
    kept = frame[~postponed]
    played = kept[kept["completed"] & kept[["home_score", "away_score"]].notna().all(axis=1)]
    remaining = kept[~kept.index.isin(played.index)]

    # A postponed shell is normally superseded by a makeup game carrying a fresh id, in
    # which case dropping it is right. If it has *not* been made up, the two teams come up
    # a game short -- so restore it as unplayed rather than quietly losing a fixture.
    restored: List[str] = []
    if postponed.any():
        counts = _games_per_team(played, remaining)
        expected = _expected_games(counts)
        for _, row in frame[postponed].iterrows():
            short = {row["home_team"], row["away_team"]}
            if all(counts.get(team, 0) < expected for team in short):
                remaining = pd.concat([remaining, row.to_frame().T], ignore_index=False)
                counts = _games_per_team(played, remaining)
                restored.append(str(row["game_id"]))
    diagnostics["postponed_rows"] = int(postponed.sum())
    diagnostics["postponed_restored_as_unplayed"] = restored

    counts = _games_per_team(played, remaining)
    expected = _expected_games(counts)
    diagnostics.update(
        {
            "games_played": int(len(played)),
            "games_remaining": int(len(remaining)),
            "games_per_team": {team: int(counts.get(team, 0)) for team in LEAGUE_TEAMS},
            "expected_games_per_team": int(expected),
            "teams_off_expected": sorted(
                team for team in LEAGUE_TEAMS if int(counts.get(team, 0)) != expected
            ),
        }
    )
    diagnostics["reconciled"] = not diagnostics["teams_off_expected"]
    diagnostics["played_through"] = (
        played["game_date"].max().date().isoformat() if not played.empty else None
    )
    diagnostics["season_ends"] = (
        remaining["game_date"].max().date().isoformat() if not remaining.empty else None
    )

    order = ["game_id", "game_date", "home_team", "away_team", "home_score", "away_score", "neutral_site"]
    return (
        played.sort_values("game_date")[order].reset_index(drop=True),
        remaining.sort_values("game_date")[order].reset_index(drop=True),
        diagnostics,
    )


def _games_per_team(played: pd.DataFrame, remaining: pd.DataFrame) -> Dict[str, int]:
    stacked = pd.concat(
        [played[["home_team", "away_team"]], remaining[["home_team", "away_team"]]],
        ignore_index=True,
    )
    if stacked.empty:
        return {}
    return pd.concat([stacked["home_team"], stacked["away_team"]]).value_counts().to_dict()


def _expected_games(counts: Dict[str, int]) -> int:
    """The season length the schedule itself implies -- the modal team total."""
    if not counts:
        return 0
    values = pd.Series(list(counts.values()))
    return int(values.mode().iloc[0])


def long_results(played: pd.DataFrame) -> pd.DataFrame:
    """Two rows per completed game, from each team's point of view."""
    if played.empty:
        return pd.DataFrame(
            columns=["game_id", "game_date", "team", "opponent", "is_home", "points", "opponent_points", "won", "margin"]
        )
    home = pd.DataFrame(
        {
            "game_id": played["game_id"],
            "game_date": played["game_date"],
            "team": played["home_team"],
            "opponent": played["away_team"],
            "is_home": ~played["neutral_site"].astype(bool),
            "points": played["home_score"],
            "opponent_points": played["away_score"],
        }
    )
    away = pd.DataFrame(
        {
            "game_id": played["game_id"],
            "game_date": played["game_date"],
            "team": played["away_team"],
            "opponent": played["home_team"],
            "is_home": False,
            "points": played["away_score"],
            "opponent_points": played["home_score"],
        }
    )
    results = pd.concat([home, away], ignore_index=True)
    results["margin"] = results["points"] - results["opponent_points"]
    results["won"] = results["margin"] > 0
    return results.sort_values(["game_date", "game_id"]).reset_index(drop=True)


def head_to_head(results: pd.DataFrame, teams: Optional[List[str]] = None) -> pd.DataFrame:
    """Wins by row team over column team, over games played so far."""
    index = list(teams or LEAGUE_TEAMS)
    matrix = pd.DataFrame(0, index=index, columns=index, dtype=int)
    if results.empty:
        return matrix
    wins = results[results["won"]].groupby(["team", "opponent"]).size()
    for (team, opponent), count in wins.items():
        if team in matrix.index and opponent in matrix.columns:
            matrix.loc[team, opponent] = int(count)
    return matrix


def current_standings(
    results: pd.DataFrame,
    remaining: pd.DataFrame,
    *,
    conferences: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Records, point differential and games left, straight from the reconciled schedule.

    Derived rather than read from the standings feed on purpose: the WNBA Stats standings
    file in this repo trails the schedule by roughly a fortnight, and a forecast that
    disagrees with its own game log is not worth publishing.
    """
    conferences = conferences or WNBA_CONFERENCES
    teams = list(LEAGUE_TEAMS)
    remaining_counts = (
        pd.concat([remaining["home_team"], remaining["away_team"]]).value_counts()
        if not remaining.empty
        else pd.Series(dtype=int)
    )

    rows: List[Dict[str, Any]] = []
    for team in teams:
        played = results[results["team"] == team] if not results.empty else results
        wins = int(played["won"].sum()) if not played.empty else 0
        games = int(len(played))
        rows.append(
            {
                "team_abbreviation": team,
                "conference": conferences.get(team, ""),
                "games_played": games,
                "wins": wins,
                "losses": games - wins,
                "win_pct": round(wins / games, 4) if games else np.nan,
                "points_for": int(played["points"].sum()) if games else 0,
                "points_against": int(played["opponent_points"].sum()) if games else 0,
                "point_differential": int(played["margin"].sum()) if games else 0,
                "net_points_per_game": round(float(played["margin"].mean()), 3) if games else np.nan,
                "home_wins": int(played.loc[played["is_home"], "won"].sum()) if games else 0,
                "home_games": int(played["is_home"].sum()) if games else 0,
                "games_remaining": int(remaining_counts.get(team, 0)),
                "home_games_remaining": int((remaining["home_team"] == team).sum()) if not remaining.empty else 0,
            }
        )

    standings = pd.DataFrame(rows)
    standings["max_possible_wins"] = standings["wins"] + standings["games_remaining"]
    standings = standings.sort_values(["win_pct", "point_differential"], ascending=False).reset_index(drop=True)
    standings.insert(1, "current_seed", np.arange(1, len(standings) + 1))
    return standings
