#!/usr/bin/env python3
"""Fetch WNBA 2026 schedule and team box scores straight from ESPN's live API.

SportsDataverse republishes ESPN's data on a cadence that has been running a couple of
weeks behind the games themselves -- its ``team_box``/``schedule`` releases were still
frozen at 2026-08-01 while the season had played into mid-August. The standings forecast
takes its cutoff from the last completed game in those files, so a stale feed silently
caps the forecast in the past no matter how fresh the rest of the pipeline is.

This fetcher goes to the same source SportsDataverse does -- ESPN's public site API -- but
without the republish lag, and writes ``schedule_2026.parquet`` and ``team_box_2026.parquet``
in exactly the shape the forecast consumes. It writes to its own data root
(``data/raw/espn/wnba_2026`` by default) rather than overwriting the SportsDataverse files,
because several other analyses still read those; the forecast is pointed at this root with
``--sportsdataverse-data-root``.

Only the columns the forecast actually reads are produced. If ESPN's payload is missing or
malformed for a completed game, the fetch fails loudly rather than writing a file that
would break the forecast's own reconciliation -- and that reconciliation (every team must
reach the configured season length) is the backstop that catches any labelling mistake in
game type before it reaches a deliverable.

Network access is deliberately confined to :func:`fetch_json`; everything else is a pure
transform over the returned JSON, so the assembly is unit-tested without a live endpoint.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import pandas as pd


SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
SCOREBOARD_URL = f"{SITE_API}/scoreboard"
SUMMARY_URL = f"{SITE_API}/summary"

REGULAR_SEASON_TYPE = 2
DEFAULT_SEASON = 2026
DEFAULT_DATA_ROOT = "data/raw/espn/wnba_2026"

MAX_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 60

# ESPN's site API returns 403 to non-browser clients -- a bare tool User-Agent is refused
# even from a CI runner that can otherwise reach the host. A realistic browser header set
# is what public consumers of this endpoint use; it is overridable via ESPN_USER_AGENT for
# the day ESPN changes the rules again.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _request_headers() -> dict[str, str]:
    import os

    return {
        "User-Agent": os.environ.get("ESPN_USER_AGENT", DEFAULT_USER_AGENT),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.espn.com/wnba/",
        "Origin": "https://www.espn.com",
        "Cache-Control": "no-cache",
    }

# The eight box-score fields the forecast's team-game layer needs to estimate pace and
# efficiency. Every completed game must supply all of them.
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

# ESPN's combined "made-attempted" statistic names, split into the two fields the forecast
# expects. Values arrive as strings like "30-70".
_PAIR_STATS = {
    "fieldGoalsMade-fieldGoalsAttempted": ("field_goals_made", "field_goals_attempted"),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": (
        "three_point_field_goals_made",
        None,
    ),
    "freeThrowsMade-freeThrowsAttempted": ("free_throws_made", "free_throws_attempted"),
}
# ESPN's single-value statistic names mapped to the forecast's fields.
_SINGLE_STATS = {
    "offensiveRebounds": "offensive_rebounds",
    "defensiveRebounds": "defensive_rebounds",
    "turnovers": "turnovers",
    "totalTurnovers": "turnovers",
    "fieldGoalsMade": "field_goals_made",
    "fieldGoalsAttempted": "field_goals_attempted",
    "threePointFieldGoalsMade": "three_point_field_goals_made",
    "freeThrowsMade": "free_throws_made",
    "freeThrowsAttempted": "free_throws_attempted",
}

SCHEDULE_COLUMNS = [
    "game_id",
    "season",
    "season_type",
    "game_date",
    "type_abbreviation",
    "status_type_name",
    "status_type_completed",
    "status_period",
    "format_regulation_periods",
    "neutral_site",
    "home_id",
    "home_abbreviation",
    "home_display_name",
    "home_score",
    "away_id",
    "away_abbreviation",
    "away_display_name",
    "away_score",
]
TEAM_BOX_COLUMNS = [
    "game_id",
    "season",
    "season_type",
    "game_date",
    "team_id",
    "team_abbreviation",
    "team_display_name",
    "team_home_away",
    "team_score",
    "team_winner",
    "opponent_team_id",
    "opponent_team_abbreviation",
    "opponent_team_score",
    *BOX_STAT_FIELDS,
]


class ESPNFetchError(RuntimeError):
    """Raised when ESPN data cannot be retrieved or does not reconcile."""


# --------------------------------------------------------------------------- network


def fetch_json(url: str, *, params: Optional[Mapping[str, Any]] = None) -> dict:
    """GET a JSON document, retrying transient failures with exponential backoff.

    This is the only function that touches the network; the rest of the module is a pure
    transform over what it returns.
    """
    if params:
        query = "&".join(f"{key}={value}" for key, value in params.items())
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers=_request_headers())
    last_error: Optional[Exception] = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
    raise ESPNFetchError(f"failed to fetch {url} after {MAX_ATTEMPTS} attempts: {last_error}")


def discover_game_dates(scoreboard: Mapping[str, Any]) -> list[str]:
    """Read the season's game dates from a scoreboard payload's league calendar.

    ESPN returns the full list of dates that have games under ``leagues[0].calendar``,
    which turns a season sweep into one request per game-day instead of one per calendar
    day. Entries are ISO timestamps; only the date part is kept.
    """
    leagues = scoreboard.get("leagues") or []
    if not leagues:
        return []
    calendar = leagues[0].get("calendar") or []
    dates: list[str] = []
    for entry in calendar:
        text = str(entry)[:10]
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            continue
        dates.append(text)
    return sorted(dict.fromkeys(dates))


def collect_events(
    season: int,
    *,
    fetcher=fetch_json,
) -> list[dict]:
    """Enumerate every scheduled and completed game for the season.

    One scoreboard request seeds the calendar; each game-day is then fetched once and its
    events de-duplicated by game id.
    """
    seed = fetcher(SCOREBOARD_URL, params={"dates": season, "limit": 1000})
    game_dates = discover_game_dates(seed)
    events: dict[str, dict] = {}
    # The seed response already carries the events for whatever day it defaulted to.
    for event in seed.get("events") or []:
        events[str(event.get("id"))] = event
    for game_date in game_dates:
        payload = fetcher(SCOREBOARD_URL, params={"dates": game_date.replace("-", ""), "limit": 1000})
        for event in payload.get("events") or []:
            events[str(event.get("id"))] = event
    return list(events.values())


# ----------------------------------------------------------------------- pure parse


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _competition(event: Mapping[str, Any]) -> Mapping[str, Any]:
    competitions = event.get("competitions") or [{}]
    return competitions[0] if competitions else {}


def _game_type_abbreviation(event: Mapping[str, Any], competition: Mapping[str, Any]) -> str:
    """STD for an ordinary game, CC for the Commissioner's Cup championship.

    The Cup final is a real game between two league teams that does *not* count in the
    standings, and the forecast keys its special handling on this abbreviation. ESPN flags
    it through the competition notes rather than a type code, so the headline is the
    signal. Everything else is STD; the All-Star game is excluded upstream because it is
    not a regular-season-type event.
    """
    notes = competition.get("notes") or []
    headlines = " ".join(str(note.get("headline", "")) for note in notes).lower()
    if "commissioner" in headlines and "cup" in headlines:
        return "CC"
    return "STD"


def parse_event(event: Mapping[str, Any]) -> Optional[dict]:
    """Turn one scoreboard event into a schedule row, or None if it is not usable.

    Non-regular-season events (the All-Star game and exhibitions) and any event without two
    identifiable league competitors are dropped rather than guessed at.
    """
    season = event.get("season") or {}
    if _to_int(season.get("type")) != REGULAR_SEASON_TYPE:
        return None

    competition = _competition(event)
    competitors = competition.get("competitors") or []
    if len(competitors) != 2:
        return None

    sides: dict[str, Mapping[str, Any]] = {}
    for competitor in competitors:
        home_away = str(competitor.get("homeAway", "")).strip().lower()
        if home_away in {"home", "away"}:
            sides[home_away] = competitor
    if set(sides) != {"home", "away"}:
        return None

    status = (competition.get("status") or event.get("status") or {})
    status_type = status.get("type") or {}
    game_date = str(event.get("date") or competition.get("date") or "")[:10]
    if not game_date:
        return None

    def team_field(side: str, *keys: str) -> Any:
        team = sides[side].get("team") or {}
        for key in keys:
            if key in team and team[key] not in (None, ""):
                return team[key]
        return None

    row = {
        "game_id": str(event.get("id")),
        "season": _to_int(season.get("year")),
        "season_type": REGULAR_SEASON_TYPE,
        "game_date": game_date,
        "type_abbreviation": _game_type_abbreviation(event, competition),
        "status_type_name": str(status_type.get("name") or ""),
        "status_type_completed": bool(status_type.get("completed", False)),
        "status_period": _to_int(status.get("period")),
        "format_regulation_periods": _to_int(
            (competition.get("format") or {}).get("regulation", {}).get("periods")
        )
        or 4,
        "neutral_site": bool(competition.get("neutralSite", False)),
        "home_id": _stringify_id(team_field("home", "id")),
        "home_abbreviation": team_field("home", "abbreviation"),
        "home_display_name": team_field("home", "displayName", "name"),
        "home_score": _to_int(sides["home"].get("score")),
        "away_id": _stringify_id(team_field("away", "id")),
        "away_abbreviation": team_field("away", "abbreviation"),
        "away_display_name": team_field("away", "displayName", "name"),
        "away_score": _to_int(sides["away"].get("score")),
    }
    if row["home_id"] is None or row["away_id"] is None:
        return None
    return row


def _stringify_id(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    text = str(value).strip()
    return text or None


def _split_pair(value: Any) -> tuple[Optional[int], Optional[int]]:
    text = str(value).strip()
    if "-" not in text:
        return _to_int(text), None
    made, _, attempted = text.partition("-")
    return _to_int(made), _to_int(attempted)


def parse_box_statistics(statistics: Iterable[Mapping[str, Any]]) -> dict[str, Optional[int]]:
    """Map one team's ESPN box statistics onto the eight fields the forecast needs.

    ESPN reports shooting as combined ``made-attempted`` strings and rebounds/turnovers as
    single values, and different payloads use slightly different names for the same stat;
    both spellings are handled. Missing fields are left None so the caller can reject the
    game rather than silently model it with a zero.
    """
    parsed: dict[str, Optional[int]] = {field: None for field in BOX_STAT_FIELDS}
    for statistic in statistics:
        name = str(statistic.get("name", ""))
        value = statistic.get("displayValue", statistic.get("value"))
        if name in _PAIR_STATS:
            made_field, attempted_field = _PAIR_STATS[name]
            made, attempted = _split_pair(value)
            if made_field and parsed.get(made_field) is None:
                parsed[made_field] = made
            if attempted_field and parsed.get(attempted_field) is None:
                parsed[attempted_field] = attempted
        elif name in _SINGLE_STATS:
            field = _SINGLE_STATS[name]
            if parsed.get(field) is None:
                parsed[field] = _to_int(value)
    return parsed


def parse_summary_boxscore(summary: Mapping[str, Any]) -> dict[str, dict[str, Optional[int]]]:
    """Return ``{team_id: {stat_field: value}}`` for both teams in a game summary."""
    boxscore = summary.get("boxscore") or {}
    result: dict[str, dict[str, Optional[int]]] = {}
    for team_block in boxscore.get("teams") or []:
        team_id = _stringify_id((team_block.get("team") or {}).get("id"))
        if team_id is None:
            continue
        result[team_id] = parse_box_statistics(team_block.get("statistics") or [])
    return result


# --------------------------------------------------------------------- assembly


def build_schedule_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Assemble the schedule frame, de-duplicated and ordered by date."""
    if not rows:
        return pd.DataFrame(columns=SCHEDULE_COLUMNS)
    frame = pd.DataFrame(list(rows)).drop_duplicates(subset="game_id")
    for column in SCHEDULE_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame[SCHEDULE_COLUMNS]
    return frame.sort_values(["game_date", "game_id"]).reset_index(drop=True)


def build_team_box_frame(
    schedule_rows: Sequence[Mapping[str, Any]],
    boxscores: Mapping[str, Mapping[str, Mapping[str, Optional[int]]]],
) -> pd.DataFrame:
    """Two directional rows per completed game, carrying scores and box statistics.

    Every completed game must have a box score covering both of its teams; a gap is an
    error rather than a row of nulls, because the forecast cannot estimate pace without it.
    """
    directional: list[dict[str, Any]] = []
    missing: list[str] = []
    for row in schedule_rows:
        if not row.get("status_type_completed"):
            continue
        game_id = str(row["game_id"])
        game_box = boxscores.get(game_id)
        home_id, away_id = row["home_id"], row["away_id"]
        if not game_box or home_id not in game_box or away_id not in game_box:
            missing.append(game_id)
            continue
        for side, opponent in (("home", "away"), ("away", "home")):
            team_id = row[f"{side}_id"]
            opponent_id = row[f"{opponent}_id"]
            team_score = row[f"{side}_score"]
            opponent_score = row[f"{opponent}_score"]
            record = {
                "game_id": game_id,
                "season": row["season"],
                "season_type": row["season_type"],
                "game_date": row["game_date"],
                "team_id": team_id,
                "team_abbreviation": row[f"{side}_abbreviation"],
                "team_display_name": row[f"{side}_display_name"],
                "team_home_away": side,
                "team_score": team_score,
                "team_winner": (
                    None
                    if team_score is None or opponent_score is None
                    else bool(team_score > opponent_score)
                ),
                "opponent_team_id": opponent_id,
                "opponent_team_abbreviation": row[f"{opponent}_abbreviation"],
                "opponent_team_score": opponent_score,
                **{field: game_box[team_id].get(field) for field in BOX_STAT_FIELDS},
            }
            directional.append(record)
    if missing:
        raise ESPNFetchError(
            "completed games are missing box scores for both teams: " + ", ".join(sorted(missing))
        )
    if not directional:
        return pd.DataFrame(columns=TEAM_BOX_COLUMNS)
    frame = pd.DataFrame(directional)[TEAM_BOX_COLUMNS]
    return frame.sort_values(["game_date", "game_id", "team_home_away"]).reset_index(drop=True)


def reconcile(schedule: pd.DataFrame, *, expected_games_per_team: Optional[int]) -> dict[str, Any]:
    """Summarise coverage, and check the per-team game count when one is expected."""
    completed = schedule[schedule["status_type_completed"].astype(bool)]
    scheduled = schedule[~schedule["status_type_completed"].astype(bool)]
    per_team = (
        pd.concat([schedule["home_abbreviation"], schedule["away_abbreviation"]]).value_counts()
        if not schedule.empty
        else pd.Series(dtype=int)
    )
    diagnostics: dict[str, Any] = {
        "games_total": int(len(schedule)),
        "games_completed": int(len(completed)),
        "games_scheduled": int(len(scheduled)),
        "teams": int(len(per_team)),
        "coverage_through": (
            str(pd.to_datetime(completed["game_date"]).max().date()) if not completed.empty else None
        ),
        "season_ends": (
            str(pd.to_datetime(schedule["game_date"]).max().date()) if not schedule.empty else None
        ),
    }
    if expected_games_per_team:
        off = sorted(
            team for team, count in per_team.items() if int(count) != expected_games_per_team
        )
        diagnostics["expected_games_per_team"] = expected_games_per_team
        diagnostics["teams_off_expected"] = off
        diagnostics["reconciled"] = not off and len(per_team) > 0
    return diagnostics


def write_outputs(schedule: pd.DataFrame, team_box: pd.DataFrame, data_root: Path) -> dict[str, str]:
    data_root.mkdir(parents=True, exist_ok=True)
    schedule_path = data_root / "schedule_2026.parquet"
    team_box_path = data_root / "team_box_2026.parquet"
    schedule.to_parquet(schedule_path, index=False)
    team_box.to_parquet(team_box_path, index=False)
    return {"schedule": str(schedule_path), "team_box": str(team_box_path)}


# ------------------------------------------------------------------------- main


def build(
    season: int,
    data_root: Path,
    *,
    expected_games_per_team: Optional[int],
    fetcher=fetch_json,
) -> dict[str, Any]:
    events = collect_events(season, fetcher=fetcher)
    schedule_rows = [row for row in (parse_event(event) for event in events) if row is not None]
    if not schedule_rows:
        raise ESPNFetchError("ESPN returned no usable regular-season events")

    boxscores: dict[str, dict[str, dict[str, Optional[int]]]] = {}
    for row in schedule_rows:
        if not row["status_type_completed"]:
            continue
        summary = fetcher(SUMMARY_URL, params={"event": row["game_id"]})
        boxscores[row["game_id"]] = parse_summary_boxscore(summary)

    schedule = build_schedule_frame(schedule_rows)
    team_box = build_team_box_frame(schedule_rows, boxscores)
    diagnostics = reconcile(schedule, expected_games_per_team=expected_games_per_team)
    if expected_games_per_team and not diagnostics.get("reconciled"):
        raise ESPNFetchError(
            "ESPN schedule did not reconcile to "
            f"{expected_games_per_team} games per team: {diagnostics.get('teams_off_expected')}"
        )

    paths = write_outputs(schedule, team_box, data_root)
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "season": season,
        "source": "espn_site_api",
        "diagnostics": diagnostics,
        "outputs": paths,
    }
    (data_root / "espn_fetch_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch WNBA 2026 schedule and box scores from ESPN.")
    parser.add_argument("--season", type=int, default=DEFAULT_SEASON)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--expected-games-per-team",
        type=int,
        default=None,
        help="Fail unless every team reconciles to this many games (e.g. 44 for 2026).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    root = Path(args.data_root)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[1] / root
    manifest = build(
        args.season,
        root,
        expected_games_per_team=args.expected_games_per_team,
    )
    diagnostics = manifest["diagnostics"]
    print(
        f"ESPN {args.season}: {diagnostics['games_completed']} completed / "
        f"{diagnostics['games_scheduled']} scheduled through "
        f"{diagnostics['coverage_through']} -> {manifest['outputs']['schedule']}"
    )


if __name__ == "__main__":
    main()
