#!/usr/bin/env python3
"""Historical + incremental WNBA 2026 player and team game-log ingest from pbpstats.

The playoff project wants one combined player-game table -- every player-game row already
carries ``Date``, ``GameId``, ``Team`` and ``Opponent`` alongside the possession, efficiency,
shot-profile and usage fields -- plus the individual raw API responses behind it. The pbpstats
API exposes this one entity at a time: ``get-totals`` (Player) enumerates the season's players,
and ``get-game-logs`` (Player) returns one player's per-game rows. This module fans those calls
out, injects the player identity that the per-game rows omit, and combines them.

``get-games`` is the authoritative game dimension / schedule-result spine; player and team logs
are joined to it by ``GameId``. The combined player log's primary key is ``PlayerId + GameId``.

The first run is a full historical build: every player, every game log. Subsequent runs are
incremental -- ``GameId`` is the freshness checkpoint, not ``GamesPlayed`` (the feeds refresh at
different times, so a game can appear in ``get-games`` before ``get-totals`` counts it). A run
re-fetches only the entities a new game touches, retries anything that failed transiently before,
and appends the new-or-changed rows onto the existing baseline. pbpstats omits zero-valued stats,
so an absent column in a row means zero; the combined JSON stays ragged to preserve that, while
the CSV is the column union with blanks for the same absences.

Network access is confined to :func:`request_json`; every transform is pure and is tested against
real recorded API responses.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import pandas as pd


BASE_URL = "https://api.pbpstats.com"
LEAGUE = "wnba"
DEFAULT_SEASON = "2026"
DEFAULT_SEASON_TYPE = "Regular Season"
DEFAULT_DATA_ROOT = os.getenv("PBPSTATS_GAME_LOGS_DATA_ROOT", "data/pbpstats_2026_player_game_logs")

MAX_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 60
REQUEST_SLEEP_SECONDS = 0.35

# Identity fields injected onto each per-game row. The pbpstats per-game log omits the entity's
# own id/name -- only the request knew which player it asked for -- so they are filled from the
# ``get-totals`` lookup. ``Team`` on the row is the team the entity played for in that game; the
# injected ``TeamAbbreviation`` is the entity's current team, so a mid-season trade keeps both.
PLAYER_IDENTITY_FIELDS = ("PlayerId", "PlayerName", "TeamId", "TeamAbbreviation")
TEAM_IDENTITY_FIELDS = ("TeamId", "TeamName", "TeamAbbreviation")

# Row fields that are identity/text, never zero-omitted stats, so they are never blank-fills.
LOG_KEY_FIELDS = ("GameId", "Date", "Team", "Opponent")


class PBPStatsGameLogError(RuntimeError):
    """Raised when game-log data cannot be retrieved or fails a structural invariant."""


# --------------------------------------------------------------------------- network


def request_json(endpoint: str, params: Optional[Mapping[str, Any]] = None) -> dict:
    """GET a pbpstats JSON document, retrying transient failures with backoff.

    The only function that touches the network. Uses ``requests`` to match the rest of the
    repo's pbpstats tooling. 429 and 5xx are treated as retryable; a persistent failure raises
    so the caller records it rather than silently dropping the entity.
    """
    import requests

    url = f"{BASE_URL}{endpoint}"
    last_error: Optional[Exception] = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.get(url, params=dict(params or {}), timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise PBPStatsGameLogError(f"retryable status {response.status_code}")
            response.raise_for_status()
            return response.json()
        except Exception as error:  # noqa: BLE001 - deliberately broad; retried below
            last_error = error
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
    raise PBPStatsGameLogError(f"failed to fetch {endpoint} after {MAX_ATTEMPTS} attempts: {last_error}")


def fetch_games(season: str, season_type: str, fetcher: Callable = request_json) -> dict:
    return fetcher(f"/get-games/{LEAGUE}", {"Season": season, "SeasonType": season_type})


def fetch_totals(season: str, season_type: str, entity_type: str, fetcher: Callable = request_json) -> dict:
    return fetcher(
        f"/get-totals/{LEAGUE}",
        {"Season": season, "SeasonType": season_type, "Type": entity_type},
    )


def fetch_entity_game_log(
    entity_id: str, entity_type: str, season: str, season_type: str, fetcher: Callable = request_json
) -> dict:
    return fetcher(
        f"/get-game-logs/{LEAGUE}",
        {"Season": season, "SeasonType": season_type, "EntityType": entity_type, "EntityId": entity_id},
    )


# ----------------------------------------------------------------------- pure helpers


def _norm_id(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _rows(response: Mapping[str, Any]) -> List[dict]:
    rows = response.get("multi_row_table_data")
    return list(rows) if isinstance(rows, list) else []


# ---------------------------------------------------------------------- pure transforms


def build_player_lookup(totals_player: Mapping[str, Any]) -> pd.DataFrame:
    """``get-totals`` (Player) -> the season's player directory used to fan out game-log calls."""
    records = []
    for row in _rows(totals_player):
        player_id = _norm_id(row.get("EntityId"))
        if player_id is None:
            continue
        records.append(
            {
                "player_id": player_id,
                "player_name": row.get("Name"),
                "team_id": _norm_id(row.get("TeamId")),
                "team_abbreviation": row.get("TeamAbbreviation"),
                "games_played": _to_int(row.get("GamesPlayed")),
            }
        )
    frame = pd.DataFrame(records, columns=["player_id", "player_name", "team_id", "team_abbreviation", "games_played"])
    if frame["player_id"].duplicated().any():
        dupes = sorted(frame.loc[frame["player_id"].duplicated(), "player_id"])
        raise PBPStatsGameLogError(f"get-totals Player has duplicate player ids: {dupes}")
    return frame.sort_values("player_id").reset_index(drop=True)


def build_team_lookup(totals_team: Mapping[str, Any]) -> pd.DataFrame:
    """``get-totals`` (Team) -> the season's team directory used to fan out team game-log calls."""
    records = []
    for row in _rows(totals_team):
        team_id = _norm_id(row.get("EntityId")) or _norm_id(row.get("TeamId"))
        if team_id is None:
            continue
        records.append(
            {
                "team_id": team_id,
                "team_abbreviation": row.get("TeamAbbreviation") or row.get("Name"),
                "team_name": row.get("Name"),
                "games_played": _to_int(row.get("GamesPlayed")),
            }
        )
    frame = pd.DataFrame(records, columns=["team_id", "team_abbreviation", "team_name", "games_played"])
    return frame.sort_values("team_id").reset_index(drop=True)


def build_games_dimension(get_games: Mapping[str, Any]) -> pd.DataFrame:
    """``get-games`` -> the authoritative game dimension / schedule-result spine, keyed by GameId."""
    records = []
    for game in get_games.get("results") or []:
        game_id = _norm_id(game.get("GameId"))
        if game_id is None:
            continue
        records.append(
            {
                "game_id": game_id,
                "date": str(game.get("Date"))[:10],
                "home_team_id": _norm_id(game.get("HomeTeamId")),
                "home_team_abbreviation": game.get("HomeTeamAbbreviation"),
                "home_points": _to_int(game.get("HomePoints")),
                "home_possessions": _to_int(game.get("HomePossessions")),
                "away_team_id": _norm_id(game.get("AwayTeamId")),
                "away_team_abbreviation": game.get("AwayTeamAbbreviation"),
                "away_points": _to_int(game.get("AwayPoints")),
                "away_possessions": _to_int(game.get("AwayPossessions")),
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    if frame["game_id"].duplicated().any():
        dupes = sorted(frame.loc[frame["game_id"].duplicated(), "game_id"])
        raise PBPStatsGameLogError(f"get-games has duplicate game ids: {dupes}")
    return frame.sort_values(["date", "game_id"]).reset_index(drop=True)


def game_ids_of(get_games: Mapping[str, Any]) -> Set[str]:
    return {gid for gid in (_norm_id(g.get("GameId")) for g in get_games.get("results") or []) if gid}


def teams_in_games(get_games: Mapping[str, Any], game_ids: Iterable[str]) -> Set[str]:
    """The set of pbpstats team ids that appear on either side of the named games."""
    wanted = set(game_ids)
    teams: Set[str] = set()
    for game in get_games.get("results") or []:
        if _norm_id(game.get("GameId")) in wanted:
            teams.update(filter(None, (_norm_id(game.get("HomeTeamId")), _norm_id(game.get("AwayTeamId")))))
    return teams


def annotate_log_rows(
    response: Mapping[str, Any], identity: Mapping[str, Any], identity_fields: Sequence[str]
) -> List[dict]:
    """Return one entity's per-game rows with the requested identity fields appended to each.

    Injected fields go on the end of each row (dict insertion order), matching the combined
    dataset's layout: the API's own columns first, identity last.
    """
    annotated: List[dict] = []
    for row in _rows(response):
        record = dict(row)
        for field in identity_fields:
            record[field] = identity.get(field)
        annotated.append(record)
    return annotated


def combined_columns(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    """Union of every row's keys in first-seen order (API columns first, injected identity last)."""
    ordered: List[str] = []
    seen: Set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def dedupe_rows(rows: Sequence[Mapping[str, Any]], key_fields: Sequence[str]) -> List[dict]:
    """Keep the last row for each key tuple; a later fetch supersedes an earlier one."""
    by_key: Dict[Tuple, dict] = {}
    for row in rows:
        by_key[tuple(_norm_id(row.get(field)) for field in key_fields)] = dict(row)
    return list(by_key.values())


def merge_entity_rows(
    existing: Sequence[Mapping[str, Any]],
    refreshed_by_entity: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    entity_field: str,
) -> List[dict]:
    """Replace every existing row for a refreshed entity with that entity's fresh rows; keep the rest.

    ``refreshed_by_entity`` maps entity id -> the full, freshly fetched row list for that entity, so
    dropping the entity's stale rows wholesale and substituting the new ones both adds new games and
    corrects any revised earlier ones.
    """
    refreshed_ids = set(refreshed_by_entity)
    kept = [dict(row) for row in existing if _norm_id(row.get(entity_field)) not in refreshed_ids]
    for rows in refreshed_by_entity.values():
        kept.extend(dict(row) for row in rows)
    return kept


def rows_present_by_entity(rows: Sequence[Mapping[str, Any]], entity_field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        entity = _norm_id(row.get(entity_field))
        if entity is not None:
            counts[entity] = counts.get(entity, 0) + 1
    return counts


def identify_affected_entities(
    *,
    lookup: pd.DataFrame,
    id_column: str,
    existing_rows: Sequence[Mapping[str, Any]],
    entity_field: str,
    entities_in_new_games: Set[str],
    prior_failures: Set[str],
) -> List[str]:
    """The entities to (re)fetch this run.

    ``GameId`` is the primary checkpoint: any entity a newly-appeared game touches is refreshed.
    On top of that, an entity is refreshed when it has never been seen, when its ``GamesPlayed``
    in the fresh ``get-totals`` no longer matches the rows already stored for it (a robustness
    backstop for revised feeds), or when it failed transiently on a previous run.
    """
    present = rows_present_by_entity(existing_rows, entity_field)
    affected: Set[str] = set()
    for row in lookup.itertuples(index=False):
        entity = _norm_id(getattr(row, id_column))
        if entity is None:
            continue
        games_played = _to_int(getattr(row, "games_played", None))
        if (
            entity not in present
            or entity in entities_in_new_games
            or entity in prior_failures
            or (games_played is not None and present.get(entity, 0) != games_played)
        ):
            affected.add(entity)
    # Retry a prior failure even if it has since dropped out of the lookup.
    affected.update(prior_failures)
    return sorted(affected)


# ----------------------------------------------------------------------------- io


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    tmp.replace(path)


def _write_combined(base: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write the combined dataset as ragged JSON (preserving zero-omission) and a union CSV."""
    _write_json(base.with_suffix(".json"), list(rows))
    frame = pd.DataFrame(list(rows), columns=combined_columns(rows)) if rows else pd.DataFrame()
    frame.to_csv(base.with_suffix(".csv"), index=False)


def _load_existing_combined(base: Path) -> List[dict]:
    payload = _read_json(base.with_suffix(".json"))
    return list(payload) if isinstance(payload, list) else []


def _load_prior_failures(path: Path, id_key: str) -> Set[str]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        return set()
    return {fid for fid in (_norm_id(item.get(id_key)) for item in payload if isinstance(item, dict)) if fid}


# ------------------------------------------------------------------------- fan-out


def _fan_out_entity_logs(
    *,
    affected: Sequence[str],
    entity_type: str,
    identity_by_id: Mapping[str, Mapping[str, Any]],
    identity_fields: Sequence[str],
    raw_prefix: str,
    raw_dir: Path,
    season: str,
    season_type: str,
    fetcher: Callable,
    sleep_seconds: float,
) -> Tuple[Dict[str, List[dict]], List[dict]]:
    """Fetch each affected entity's game log, save its raw response, and annotate its rows.

    Returns ``(refreshed_rows_by_id, failures)``. A transient failure is recorded, not raised, so
    one bad entity never sinks the run -- it is retried automatically next time.
    """
    refreshed: Dict[str, List[dict]] = {}
    failures: List[dict] = []
    for entity_id in affected:
        identity = identity_by_id.get(entity_id, {})
        try:
            response = fetch_entity_game_log(entity_id, entity_type, season, season_type, fetcher=fetcher)
        except Exception as error:  # noqa: BLE001 - recorded as a retryable failure
            failures.append(
                {
                    f"{entity_type.lower()}_id": entity_id,
                    "name": identity.get("PlayerName") or identity.get("TeamName"),
                    "error": str(error),
                }
            )
            continue
        _write_json(raw_dir / f"{raw_prefix}_{entity_id}_game_logs.json", response)
        refreshed[entity_id] = annotate_log_rows(response, identity, identity_fields)
        if sleep_seconds:
            time.sleep(sleep_seconds)
    return refreshed, failures


def _player_identity(lookup: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    return {
        _norm_id(row.player_id): {
            "PlayerId": _norm_id(row.player_id),
            "PlayerName": row.player_name,
            "TeamId": _norm_id(row.team_id),
            "TeamAbbreviation": row.team_abbreviation,
        }
        for row in lookup.itertuples(index=False)
    }


def _team_identity(lookup: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    return {
        _norm_id(row.team_id): {
            "TeamId": _norm_id(row.team_id),
            "TeamName": row.team_name,
            "TeamAbbreviation": row.team_abbreviation,
        }
        for row in lookup.itertuples(index=False)
    }


# ------------------------------------------------------------------------- orchestration


def build(
    season: str,
    season_type: str,
    data_root: Path,
    *,
    include_team_logs: bool = True,
    fetcher: Callable = request_json,
    sleep_seconds: float = REQUEST_SLEEP_SECONDS,
) -> Dict[str, Any]:
    """Run the full historical build or an incremental refresh into ``data_root``."""
    raw_dir = data_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. get-games: the authoritative spine. Save it raw and as the game dimension.
    get_games = fetch_games(season, season_type, fetcher=fetcher)
    _write_json(data_root / f"get_games_{_slug(season_type)}.json", get_games)
    games_dim = build_games_dimension(get_games)
    games_dim.to_csv(data_root / f"games_{_slug(season_type)}.csv", index=False)
    current_game_ids = game_ids_of(get_games)
    if not current_game_ids:
        raise PBPStatsGameLogError("get-games returned no games; refusing to rebuild an empty baseline")

    # 2. get-totals Player: the player directory + saved raw response.
    totals_player = fetch_totals(season, season_type, "Player", fetcher=fetcher)
    _write_json(data_root / f"get_totals_player_{_slug(season_type)}.json", totals_player)
    player_lookup = build_player_lookup(totals_player)
    player_lookup.to_csv(data_root / "player_lookup_wnba_2026.csv", index=False)

    result: Dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "season": season,
        "season_type": season_type,
        "games_total": int(len(games_dim)),
        "coverage_through": (str(games_dim["date"].max()) if not games_dim.empty else None),
        "players_total": int(len(player_lookup)),
    }

    result["players"] = _refresh_player_logs(
        data_root=data_root,
        raw_dir=raw_dir,
        player_lookup=player_lookup,
        get_games=get_games,
        current_game_ids=current_game_ids,
        season=season,
        season_type=season_type,
        fetcher=fetcher,
        sleep_seconds=sleep_seconds,
    )

    if include_team_logs:
        totals_team = fetch_totals(season, season_type, "Team", fetcher=fetcher)
        _write_json(data_root / f"get_totals_team_{_slug(season_type)}.json", totals_team)
        team_lookup = build_team_lookup(totals_team)
        team_lookup.to_csv(data_root / "team_lookup_wnba_2026.csv", index=False)
        result["teams_total"] = int(len(team_lookup))
        result["teams"] = _refresh_team_logs(
            data_root=data_root,
            raw_dir=raw_dir,
            team_lookup=team_lookup,
            get_games=get_games,
            current_game_ids=current_game_ids,
            season=season,
            season_type=season_type,
            fetcher=fetcher,
            sleep_seconds=sleep_seconds,
        )

    _write_json(data_root / "ingest_manifest.json", result)
    return result


def _refresh_player_logs(
    *,
    data_root: Path,
    raw_dir: Path,
    player_lookup: pd.DataFrame,
    get_games: Mapping[str, Any],
    current_game_ids: Set[str],
    season: str,
    season_type: str,
    fetcher: Callable,
    sleep_seconds: float,
) -> Dict[str, Any]:
    combined_base = data_root / f"player_game_logs_{_slug(season_type)}"
    failures_path = data_root / "player_game_logs_failures.json"

    existing_rows = _load_existing_combined(combined_base)
    existing_game_ids = {gid for gid in (_norm_id(r.get("GameId")) for r in existing_rows) if gid}
    new_game_ids = current_game_ids - existing_game_ids
    entities_in_new_games = teams_in_games(get_games, new_game_ids)
    prior_failures = _load_prior_failures(failures_path, "player_id")

    # A team appearing in a new game marks all its current players affected.
    players_on_active_teams = {
        _norm_id(row.player_id)
        for row in player_lookup.itertuples(index=False)
        if _norm_id(row.team_id) in entities_in_new_games
    }
    affected = identify_affected_entities(
        lookup=player_lookup,
        id_column="player_id",
        existing_rows=existing_rows,
        entity_field="PlayerId",
        entities_in_new_games=players_on_active_teams,
        prior_failures=prior_failures,
    )

    refreshed, failures = _fan_out_entity_logs(
        affected=affected,
        entity_type="Player",
        identity_by_id=_player_identity(player_lookup),
        identity_fields=PLAYER_IDENTITY_FIELDS,
        raw_prefix="player",
        raw_dir=raw_dir,
        season=season,
        season_type=season_type,
        fetcher=fetcher,
        sleep_seconds=sleep_seconds,
    )

    merged = merge_entity_rows(existing_rows, refreshed, entity_field="PlayerId")
    merged = dedupe_rows(merged, ("PlayerId", "GameId"))
    _write_combined(combined_base, merged)
    _write_json(failures_path, failures)

    return {
        "is_first_build": not existing_rows,
        "affected_players": len(affected),
        "refreshed_players": len(refreshed),
        "failed_players": len(failures),
        "new_game_ids": len(new_game_ids),
        "combined_rows": len(merged),
        "combined_players": len({_norm_id(r.get("PlayerId")) for r in merged}),
        "combined_game_ids": len({_norm_id(r.get("GameId")) for r in merged}),
    }


def _refresh_team_logs(
    *,
    data_root: Path,
    raw_dir: Path,
    team_lookup: pd.DataFrame,
    get_games: Mapping[str, Any],
    current_game_ids: Set[str],
    season: str,
    season_type: str,
    fetcher: Callable,
    sleep_seconds: float,
) -> Dict[str, Any]:
    combined_base = data_root / f"team_game_logs_{_slug(season_type)}"
    failures_path = data_root / "team_game_logs_failures.json"

    existing_rows = _load_existing_combined(combined_base)
    existing_game_ids = {gid for gid in (_norm_id(r.get("GameId")) for r in existing_rows) if gid}
    new_game_ids = current_game_ids - existing_game_ids
    entities_in_new_games = teams_in_games(get_games, new_game_ids)
    prior_failures = _load_prior_failures(failures_path, "team_id")

    affected = identify_affected_entities(
        lookup=team_lookup,
        id_column="team_id",
        existing_rows=existing_rows,
        entity_field="TeamId",
        entities_in_new_games=entities_in_new_games,
        prior_failures=prior_failures,
    )

    refreshed, failures = _fan_out_entity_logs(
        affected=affected,
        entity_type="Team",
        identity_by_id=_team_identity(team_lookup),
        identity_fields=TEAM_IDENTITY_FIELDS,
        raw_prefix="team",
        raw_dir=raw_dir,
        season=season,
        season_type=season_type,
        fetcher=fetcher,
        sleep_seconds=sleep_seconds,
    )

    merged = merge_entity_rows(existing_rows, refreshed, entity_field="TeamId")
    merged = dedupe_rows(merged, ("TeamId", "GameId"))
    _write_combined(combined_base, merged)
    _write_json(failures_path, failures)

    return {
        "is_first_build": not existing_rows,
        "affected_teams": len(affected),
        "refreshed_teams": len(refreshed),
        "failed_teams": len(failures),
        "new_game_ids": len(new_game_ids),
        "combined_rows": len(merged),
        "combined_teams": len({_norm_id(r.get("TeamId")) for r in merged}),
        "combined_game_ids": len({_norm_id(r.get("GameId")) for r in merged}),
    }


def _slug(season_type: str) -> str:
    return "wnba_2026_" + season_type.strip().lower().replace(" ", "_")


# ------------------------------------------------------------------------- cli


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest WNBA 2026 player and team game logs from pbpstats (historical + incremental)."
    )
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--season-type", default=DEFAULT_SEASON_TYPE)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--skip-team-logs", action="store_true", help="Ingest player logs only.")
    parser.add_argument(
        "--sleep-seconds", type=float, default=REQUEST_SLEEP_SECONDS, help="Politeness delay between calls."
    )
    return parser.parse_args(argv)


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else Path(__file__).resolve().parents[1] / path


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    result = build(
        args.season,
        args.season_type,
        _resolve(args.data_root),
        include_team_logs=not args.skip_team_logs,
        sleep_seconds=args.sleep_seconds,
    )
    players = result["players"]
    print(
        f"pbpstats {args.season} game logs: {players['combined_rows']} player-game rows "
        f"across {players['combined_players']} players and {players['combined_game_ids']} games "
        f"(refreshed {players['refreshed_players']}, failed {players['failed_players']}) "
        f"through {result['coverage_through']}"
    )
    if args.skip_team_logs:
        return
    teams = result["teams"]
    print(
        f"pbpstats {args.season} team logs: {teams['combined_rows']} team-game rows "
        f"across {teams['combined_teams']} teams (refreshed {teams['refreshed_teams']}, "
        f"failed {teams['failed_teams']})"
    )


if __name__ == "__main__":
    main()
