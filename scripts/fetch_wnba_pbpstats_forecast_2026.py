#!/usr/bin/env python3
"""Fresh WNBA 2026 completed-game results from the pbpstats API, for the forecast.

The standings forecast dates its cutoff from the last completed game in its schedule and
team-box inputs. SportsDataverse republishes those on a lag that ran the cutoff weeks
behind the games actually played, and ESPN's own API refuses GitHub-hosted runners with a
403. The pbpstats API (``api.pbpstats.com``) is the source this repo already pulls
successfully from CI every day, and its ``get-games`` feed carries completed results far
fresher than SportsDataverse has republished.

The strategy is an **overlay**, not a rebuild:

* The SportsDataverse ``schedule_2026.parquet`` fixture list is the one part of that feed
  that is *not* stale -- fixtures do not change once published, only the results lag. The
  forecast already reconciles it to the configured games-per-team, cup final and all. So it
  stays the schedule spine.
* pbpstats ``get-games`` (completed results, scores, possessions, fresh) is laid over that
  spine: a fixture that pbpstats reports complete is marked complete and given its score.
* Team box scores are assembled from pbpstats ``get-game-logs`` (Team) -- one call per team
  -- carrying the four-factor inputs the forecast's team-game layer needs, keyed to the
  same fixtures.

Everything is emitted in the exact shape the forecast consumes, keyed in SportsDataverse's
team- and game-id space (pbpstats ids are crosswalked through ``team_history``), and written
to its own data root so the forecast is pointed at it with ``--sportsdataverse-data-root``
while the untouched SportsDataverse files keep serving the other analyses.

Network access is confined to :func:`request_json`; the transforms are pure and are tested
against real recorded API responses.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import pandas as pd


BASE_URL = "https://api.pbpstats.com"
LEAGUE = "wnba"
DEFAULT_SEASON = "2026"
DEFAULT_SEASON_TYPE = "Regular Season"
DEFAULT_DATA_ROOT = "data/raw/pbpstats_forecast/wnba_2026"
SPORTSDATAVERSE_SCHEDULE = "data/raw/sportsdataverse/wnba_2026/schedule_2026.parquet"
TEAM_HISTORY = "analysis/standings_playoff_forecast/config/team_history.csv"

MAX_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 60

# The eight four-factor fields the forecast's team-game layer needs, and how each is built
# from a pbpstats team game-log row. FtPoints is free-throw *points*, which equals makes at
# one point apiece, so it stands in for free throws made.
BOX_STAT_FIELDS = (
    "field_goals_made",
    "field_goals_attempted",
    "three_point_field_goals_made",
    "free_throws_made",
    "free_throws_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "turnovers",
)

SCHEDULE_COMPLETION_COLUMNS = ("status_type_completed", "status_type_name", "home_score", "away_score")

TEAM_BOX_COLUMNS = [
    "game_id",
    "season",
    "season_type",
    "game_date",
    "team_id",
    "team_abbreviation",
    "team_home_away",
    "team_score",
    "team_winner",
    "opponent_team_id",
    "opponent_team_abbreviation",
    "opponent_team_score",
    *BOX_STAT_FIELDS,
]


class PBPStatsFetchError(RuntimeError):
    """Raised when pbpstats data cannot be retrieved or does not reconcile."""


# --------------------------------------------------------------------------- network


def request_json(endpoint: str, params: Optional[Mapping[str, Any]] = None) -> dict:
    """GET a pbpstats JSON document, retrying transient failures with backoff.

    The only function that touches the network. Uses ``requests`` to match the rest of the
    repo's pbpstats tooling.
    """
    import requests

    url = f"{BASE_URL}{endpoint}"
    last_error: Optional[Exception] = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.get(url, params=dict(params or {}), timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise PBPStatsFetchError(f"retryable status {response.status_code}")
            response.raise_for_status()
            return response.json()
        except Exception as error:  # noqa: BLE001 - deliberately broad; retried below
            last_error = error
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
    raise PBPStatsFetchError(f"failed to fetch {endpoint} after {MAX_ATTEMPTS} attempts: {last_error}")


def fetch_games(season: str, season_type: str, fetcher: Callable = request_json) -> List[dict]:
    payload = fetcher(f"/get-games/{LEAGUE}", {"Season": season, "SeasonType": season_type})
    return list(payload.get("results") or [])


def fetch_team_game_log(team_id: str, season: str, season_type: str, fetcher: Callable = request_json) -> List[dict]:
    payload = fetcher(
        f"/get-game-logs/{LEAGUE}",
        {"Season": season, "SeasonType": season_type, "EntityId": team_id, "EntityType": "Team"},
    )
    return list(payload.get("multi_row_table_data") or [])


# ----------------------------------------------------------------------- pure parse


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _norm_id(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def team_crosswalk(team_history: pd.DataFrame, season: int = 2026) -> Dict[str, str]:
    """Map pbpstats team id to SportsDataverse (ESPN) team id from ``team_history``.

    Both id spaces are columns of the same authoritative crosswalk, so this is a lookup,
    not a heuristic. A season whose crosswalk is missing a team is fatal rather than a
    silent drop, because a dropped team breaks the schedule reconciliation downstream.
    """
    required = {"season", "pbpstats_team_id", "sportsdataverse_team_id"}
    missing = sorted(required.difference(team_history.columns))
    if missing:
        raise PBPStatsFetchError("team_history is missing required columns: " + ", ".join(missing))
    active = team_history[pd.to_numeric(team_history["season"], errors="coerce") == season]
    mapping = {
        _norm_id(row.pbpstats_team_id): _norm_id(row.sportsdataverse_team_id)
        for row in active.itertuples()
    }
    if None in mapping or any(value is None for value in mapping.values()):
        raise PBPStatsFetchError("team_history has blank team ids for the requested season")
    return mapping


def _game_key(date: str, team_a: str, team_b: str) -> tuple:
    """A source-independent match key: game date plus the unordered team pair."""
    return (str(date)[:10], frozenset((team_a, team_b)))


def index_games(games: Sequence[Mapping[str, Any]], crosswalk: Mapping[str, str]) -> Dict[tuple, dict]:
    """Index completed pbpstats games by ``(date, {home, away})`` in ESPN-id space.

    Raises if a game references a team absent from the crosswalk, or if two games share a
    key -- either would corrupt the overlay silently.
    """
    indexed: Dict[tuple, dict] = {}
    for game in games:
        home_pbp = _norm_id(game.get("HomeTeamId"))
        away_pbp = _norm_id(game.get("AwayTeamId"))
        if home_pbp not in crosswalk or away_pbp not in crosswalk:
            raise PBPStatsFetchError(f"get-games references a team outside the crosswalk: {home_pbp}/{away_pbp}")
        home = crosswalk[home_pbp]
        away = crosswalk[away_pbp]
        record = {
            "game_id": _norm_id(game.get("GameId")),
            "date": str(game.get("Date"))[:10],
            "home_id": home,
            "away_id": away,
            "home_points": _to_int(game.get("HomePoints")),
            "away_points": _to_int(game.get("AwayPoints")),
            "scores_by_team": {home: _to_int(game.get("HomePoints")), away: _to_int(game.get("AwayPoints"))},
        }
        key = _game_key(record["date"], home, away)
        if key in indexed:
            raise PBPStatsFetchError(f"get-games has duplicate games for {record['date']} {home} vs {away}")
        indexed[key] = record
    return indexed


def overlay_schedule(schedule: pd.DataFrame, games_by_key: Mapping[tuple, Mapping[str, Any]]) -> tuple:
    """Mark SDV fixtures complete and fill their scores from pbpstats, aligned by team id.

    SportsDataverse's home/away designation (venue-based) is kept; pbpstats scores are
    assigned to whichever side each team plays, so a disagreement over orientation between
    the two feeds cannot flip a result. Returns the overlaid schedule and the map from each
    matched fixture's game id to the pbpstats record, which the team box build reuses.
    """
    result = schedule.copy()
    dates = pd.to_datetime(result["game_date"].astype(str), errors="coerce").dt.strftime("%Y-%m-%d")
    home_ids = result["home_id"].map(_norm_id)
    away_ids = result["away_id"].map(_norm_id)

    completed_flags = result["status_type_completed"].tolist()
    status_names = result["status_type_name"].astype("object").tolist()
    home_scores = result["home_score"].astype("object").tolist()
    away_scores = result["away_score"].astype("object").tolist()

    matched: Dict[str, dict] = {}
    for position in range(len(result)):
        home, away = home_ids.iloc[position], away_ids.iloc[position]
        game = games_by_key.get(_game_key(dates.iloc[position], home, away))
        if game is None:
            continue
        home_scores[position] = game["scores_by_team"].get(home)
        away_scores[position] = game["scores_by_team"].get(away)
        completed_flags[position] = True
        status_names[position] = "STATUS_FINAL"
        matched[_norm_id(result.iloc[position]["game_id"])] = game

    result["status_type_completed"] = completed_flags
    result["status_type_name"] = status_names
    result["home_score"] = home_scores
    result["away_score"] = away_scores
    return result, matched


def parse_team_game_log_stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Optional[int]]]:
    """Map a team's game-log rows to ``{pbpstats_game_id: four-factor fields}``."""
    parsed: Dict[str, Dict[str, Optional[int]]] = {}
    for row in rows:
        game_id = _norm_id(row.get("GameId"))
        if game_id is None:
            continue
        fg2m, fg3m = _to_int(row.get("FG2M")), _to_int(row.get("FG3M"))
        fg2a, fg3a = _to_int(row.get("FG2A")), _to_int(row.get("FG3A"))
        parsed[game_id] = {
            "field_goals_made": _sum(fg2m, fg3m),
            "field_goals_attempted": _sum(fg2a, fg3a),
            "three_point_field_goals_made": fg3m,
            "free_throws_made": _to_int(row.get("FtPoints")),
            "free_throws_attempted": _to_int(row.get("FTA")),
            "offensive_rebounds": _to_int(row.get("OffRebounds")),
            "defensive_rebounds": _to_int(row.get("DefRebounds")),
            "turnovers": _to_int(row.get("Turnovers")),
        }
    return parsed


def _sum(*values: Optional[int]) -> Optional[int]:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


# --------------------------------------------------------------------- assembly


def build_team_box(
    schedule: pd.DataFrame,
    matched_games: Mapping[str, Mapping[str, Any]],
    team_logs: Mapping[str, Mapping[str, Mapping[str, Optional[int]]]],
    *,
    abbreviations: Mapping[str, str],
) -> pd.DataFrame:
    """Two directional rows per completed game, with four factors from the team logs.

    ``team_logs`` is keyed by ESPN team id, then pbpstats game id. A completed game whose
    box score is missing for either team is an error, not a null row -- the forecast cannot
    estimate pace without it.
    """
    rows: List[dict] = []
    missing: List[str] = []
    completed = schedule[schedule["status_type_completed"].map(_is_true)]
    for fixture in completed.itertuples(index=False):
        game_id = _norm_id(fixture.game_id)
        game = matched_games.get(game_id)
        if game is None:
            continue
        pbp_game_id = game["game_id"]
        home, away = game["home_id"], game["away_id"]
        sides = {
            home: {"home_away": "home", "opponent": away},
            away: {"home_away": "away", "opponent": home},
        }
        if any(team not in team_logs or pbp_game_id not in team_logs[team] for team in sides):
            missing.append(game_id)
            continue
        for team_id, meta in sides.items():
            opponent = meta["opponent"]
            team_score = game["scores_by_team"].get(team_id)
            opponent_score = game["scores_by_team"].get(opponent)
            rows.append(
                {
                    "game_id": game_id,
                    "season": _to_int(fixture.season),
                    "season_type": _to_int(fixture.season_type),
                    "game_date": game["date"],
                    "team_id": team_id,
                    "team_abbreviation": abbreviations.get(team_id),
                    "team_home_away": meta["home_away"],
                    "team_score": team_score,
                    "team_winner": (
                        None
                        if team_score is None or opponent_score is None
                        else bool(team_score > opponent_score)
                    ),
                    "opponent_team_id": opponent,
                    "opponent_team_abbreviation": abbreviations.get(opponent),
                    "opponent_team_score": opponent_score,
                    **{field: team_logs[team_id][pbp_game_id].get(field) for field in BOX_STAT_FIELDS},
                }
            )
    if missing:
        raise PBPStatsFetchError(
            "completed games are missing team game-log box scores: " + ", ".join(sorted(set(missing)))
        )
    if not rows:
        return pd.DataFrame(columns=TEAM_BOX_COLUMNS)
    frame = pd.DataFrame(rows)[TEAM_BOX_COLUMNS]
    return frame.sort_values(["game_date", "game_id", "team_home_away"]).reset_index(drop=True)


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1"}


def abbreviations_from_games(games: Sequence[Mapping[str, Any]], crosswalk: Mapping[str, str]) -> Dict[str, str]:
    """ESPN team id to the pbpstats abbreviation, read off the games feed."""
    mapping: Dict[str, str] = {}
    for game in games:
        for id_key, abbr_key in (("HomeTeamId", "HomeTeamAbbreviation"), ("AwayTeamId", "AwayTeamAbbreviation")):
            pbp = _norm_id(game.get(id_key))
            if pbp in crosswalk and game.get(abbr_key):
                mapping[crosswalk[pbp]] = str(game.get(abbr_key))
    return mapping


def reconcile(schedule: pd.DataFrame, *, expected_games_per_team: Optional[int]) -> Dict[str, Any]:
    completed = schedule[schedule["status_type_completed"].map(_is_true)]
    dates = pd.to_datetime(completed["game_date"].astype(str), errors="coerce").dropna()
    diagnostics: Dict[str, Any] = {
        "games_total": int(len(schedule)),
        "games_completed": int(len(completed)),
        "coverage_through": str(dates.max().date()) if not dates.empty else None,
    }
    if expected_games_per_team:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.team_game_layer import qualify_regular_season_schedule

        try:
            qualified = qualify_regular_season_schedule(schedule, load_season_config(2026))
            diagnostics["reconciled"] = True
            diagnostics["qualified_games"] = int(len(qualified))
        except Exception as error:  # noqa: BLE001 - surface the reconciliation reason
            diagnostics["reconciled"] = False
            diagnostics["reason"] = str(error)
    return diagnostics


def write_outputs(schedule: pd.DataFrame, team_box: pd.DataFrame, data_root: Path) -> Dict[str, str]:
    data_root.mkdir(parents=True, exist_ok=True)
    schedule_path = data_root / "schedule_2026.parquet"
    team_box_path = data_root / "team_box_2026.parquet"
    schedule.to_parquet(schedule_path, index=False)
    team_box.to_parquet(team_box_path, index=False)
    return {"schedule": str(schedule_path), "team_box": str(team_box_path)}


# ------------------------------------------------------------------------- main


def build(
    season: str,
    season_type: str,
    data_root: Path,
    *,
    sportsdataverse_schedule: Path,
    team_history_path: Path,
    expected_games_per_team: Optional[int],
    fetcher: Callable = request_json,
) -> Dict[str, Any]:
    schedule = pd.read_parquet(sportsdataverse_schedule)
    crosswalk = team_crosswalk(pd.read_csv(team_history_path), season=int(season))

    games = fetch_games(season, season_type, fetcher=fetcher)
    if not games:
        raise PBPStatsFetchError("get-games returned no completed games")
    games_by_key = index_games(games, crosswalk)
    abbreviations = abbreviations_from_games(games, crosswalk)

    overlaid, matched_games = overlay_schedule(schedule, games_by_key)

    team_logs: Dict[str, Dict[str, Dict[str, Optional[int]]]] = {}
    for pbp_team_id, espn_team_id in crosswalk.items():
        rows = fetch_team_game_log(pbp_team_id, season, season_type, fetcher=fetcher)
        team_logs[espn_team_id] = parse_team_game_log_stats(rows)

    team_box = build_team_box(overlaid, matched_games, team_logs, abbreviations=abbreviations)
    diagnostics = reconcile(overlaid, expected_games_per_team=expected_games_per_team)
    if expected_games_per_team and not diagnostics.get("reconciled"):
        raise PBPStatsFetchError(
            f"pbpstats overlay did not reconcile: {diagnostics.get('reason')}"
        )

    paths = write_outputs(overlaid, team_box, data_root)
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "season": season,
        "season_type": season_type,
        "source": "pbpstats_api_get_games_over_sportsdataverse_fixtures",
        "diagnostics": diagnostics,
        "matched_games": len(matched_games),
        "outputs": paths,
    }
    (data_root / "pbpstats_forecast_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch WNBA 2026 completed games from pbpstats for the forecast.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--season-type", default=DEFAULT_SEASON_TYPE)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--sportsdataverse-schedule", default=SPORTSDATAVERSE_SCHEDULE)
    parser.add_argument("--team-history", default=TEAM_HISTORY)
    parser.add_argument("--expected-games-per-team", type=int, default=None)
    return parser.parse_args(argv)


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else Path(__file__).resolve().parents[1] / path


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    manifest = build(
        args.season,
        args.season_type,
        _resolve(args.data_root),
        sportsdataverse_schedule=_resolve(args.sportsdataverse_schedule),
        team_history_path=_resolve(args.team_history),
        expected_games_per_team=args.expected_games_per_team,
    )
    diagnostics = manifest["diagnostics"]
    print(
        f"pbpstats {args.season}: {diagnostics['games_completed']} completed games through "
        f"{diagnostics['coverage_through']} -> {manifest['outputs']['schedule']}"
    )


if __name__ == "__main__":
    main()
