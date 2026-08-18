"""Pure transforms for the shared pbpstats game layer. No network, no filesystem."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd


class GameLayerError(RuntimeError):
    """Raised when game-log rows cannot be reconciled with the get-games spine."""


# Row fields consumed into the normalized spine block; not re-emitted under their raw names.
_PLAYER_IDENTITY = {"GameId", "Date", "Team", "Opponent", "PlayerId", "PlayerName", "TeamId", "TeamAbbreviation", "Minutes"}
_TEAM_IDENTITY = {"GameId", "Date", "Team", "Opponent", "TeamId", "TeamName", "TeamAbbreviation", "Minutes"}

# The normalized spine columns, in order, that lead every row.
_PLAYER_SPINE = [
    "season", "season_type", "game_id", "game_date",
    "player_id", "player_name", "team_id", "team_abbreviation",
    "opponent_team_id", "opponent_team_abbreviation", "is_home",
    "minutes", "team_points", "opponent_points", "margin", "win",
    "team_possessions", "opponent_possessions",
]
_TEAM_SPINE = [
    "season", "season_type", "game_id", "game_date",
    "team_id", "team_abbreviation", "team_name",
    "opponent_team_id", "opponent_team_abbreviation", "is_home",
    "minutes", "team_points", "opponent_points", "margin", "win",
    "team_possessions", "opponent_possessions",
]


def normalize_column(name: str) -> str:
    """CamelCase / spaced pbpstats column -> snake_case, mirroring the pull/clean convention."""
    text = str(name).strip()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_").lower()


def to_minutes(value: Any) -> Optional[float]:
    """``"MM:SS"`` (or a bare number) -> decimal minutes; blank/None -> None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            minutes = int(parts[0])
            seconds = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            return None
        return round(minutes + seconds / 60.0, 4)
    try:
        return round(float(text), 4)
    except ValueError:
        return None


def _norm_id(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def _to_number(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if text == "":
        return None
    try:
        number = float(text)
    except ValueError:
        return text  # genuine string metric, left as-is
    return int(number) if number.is_integer() else number


def games_by_id(games: Sequence[Mapping[str, Any]]) -> Dict[str, dict]:
    """Index the games-dimension rows (``get-games`` spine) by string game id."""
    indexed: Dict[str, dict] = {}
    for game in games:
        game_id = _norm_id(game.get("game_id") if "game_id" in game else game.get("GameId"))
        if game_id is None:
            continue
        indexed[game_id] = {
            "game_id": game_id,
            "date": str(game.get("date") or game.get("Date"))[:10],
            "home_team_id": _norm_id(game.get("home_team_id") or game.get("HomeTeamId")),
            "home_team_abbreviation": game.get("home_team_abbreviation") or game.get("HomeTeamAbbreviation"),
            "home_points": _to_number(game.get("home_points") if "home_points" in game else game.get("HomePoints")),
            "home_possessions": _to_number(game.get("home_possessions") if "home_possessions" in game else game.get("HomePossessions")),
            "away_team_id": _norm_id(game.get("away_team_id") or game.get("AwayTeamId")),
            "away_team_abbreviation": game.get("away_team_abbreviation") or game.get("AwayTeamAbbreviation"),
            "away_points": _to_number(game.get("away_points") if "away_points" in game else game.get("AwayPoints")),
            "away_possessions": _to_number(game.get("away_possessions") if "away_possessions" in game else game.get("AwayPossessions")),
        }
    return indexed


def _resolve_side(row: Mapping[str, Any], game: Mapping[str, Any]) -> Tuple[bool, str]:
    """Return ``(is_home, reason)`` for the row's played-for team against the spine game.

    Preference order: match the row's played-for abbreviation, then its team id. A row that
    matches neither side of its own game is a data fault and is surfaced, not guessed.
    """
    abbr = row.get("Team")
    if abbr and abbr == game["home_team_abbreviation"]:
        return True, "abbr"
    if abbr and abbr == game["away_team_abbreviation"]:
        return False, "abbr"
    team_id = _norm_id(row.get("TeamId"))
    if team_id and team_id == game["home_team_id"]:
        return True, "team_id"
    if team_id and team_id == game["away_team_id"]:
        return False, "team_id"
    raise GameLayerError(
        f"game-log row for game {game['game_id']} matches neither side "
        f"(row team {abbr!r}/{team_id!r}; game {game['home_team_abbreviation']}/{game['away_team_abbreviation']})"
    )


def _spine_fields(game: Mapping[str, Any], is_home: bool) -> Dict[str, Any]:
    if is_home:
        team_id, team_abbr = game["home_team_id"], game["home_team_abbreviation"]
        opp_id, opp_abbr = game["away_team_id"], game["away_team_abbreviation"]
        team_pts, opp_pts = game["home_points"], game["away_points"]
        team_poss, opp_poss = game["home_possessions"], game["away_possessions"]
    else:
        team_id, team_abbr = game["away_team_id"], game["away_team_abbreviation"]
        opp_id, opp_abbr = game["home_team_id"], game["home_team_abbreviation"]
        team_pts, opp_pts = game["away_points"], game["home_points"]
        team_poss, opp_poss = game["away_possessions"], game["home_possessions"]
    margin = (team_pts - opp_pts) if (team_pts is not None and opp_pts is not None) else None
    return {
        "game_id": game["game_id"],
        "game_date": game["date"],
        "game_team_id": team_id,
        "game_team_abbreviation": team_abbr,
        "opponent_team_id": opp_id,
        "opponent_team_abbreviation": opp_abbr,
        "is_home": is_home,
        "team_points": team_pts,
        "opponent_points": opp_pts,
        "margin": margin,
        "win": (None if margin is None else bool(margin > 0)),
        "team_possessions": team_poss,
        "opponent_possessions": opp_poss,
    }


def _metric_columns(rows: Sequence[Mapping[str, Any]], identity: set) -> List[str]:
    """Union of non-identity metric keys across rows, first-seen order, snake_cased (deduped)."""
    ordered: List[str] = []
    seen: set = set()
    for row in rows:
        for key in row.keys():
            if key in identity:
                continue
            norm = normalize_column(key)
            if norm and norm not in seen:
                seen.add(norm)
                ordered.append(norm)
    return ordered


def _build(
    rows: Sequence[Mapping[str, Any]],
    games: Mapping[str, Mapping[str, Any]],
    *,
    season: Any,
    season_type: str,
    identity: set,
    id_field: str,
    spine_columns: List[str],
    extra_identity: Dict[str, Tuple[str, str]],
) -> pd.DataFrame:
    """Shared assembly for player- and team-grain layers.

    ``extra_identity`` maps output column -> ``(raw_field, spine_or_row)`` for the grain-specific
    identity (player id/name, or team name) that rides alongside the common spine.
    """
    metric_cols = _metric_columns(rows, identity)
    records: List[dict] = []
    for row in rows:
        game_id = _norm_id(row.get("GameId"))
        game = games.get(game_id)
        if game is None:
            raise GameLayerError(f"game-log row references game {game_id!r} absent from the get-games spine")
        is_home, _ = _resolve_side(row, game)
        spine = _spine_fields(game, is_home)

        record: Dict[str, Any] = {"season": _to_number(season), "season_type": season_type}
        # Identity: the played-for team comes from the spine (trade-safe), names/ids from the row.
        record["game_id"] = spine["game_id"]
        record["game_date"] = spine["game_date"]
        for out_col, (raw_field, source) in extra_identity.items():
            record[out_col] = _norm_id(row.get(raw_field)) if out_col.endswith("_id") else row.get(raw_field)
        record["team_id"] = spine["game_team_id"]
        record["team_abbreviation"] = spine["game_team_abbreviation"]
        record["opponent_team_id"] = spine["opponent_team_id"]
        record["opponent_team_abbreviation"] = spine["opponent_team_abbreviation"]
        record["is_home"] = spine["is_home"]
        record["minutes"] = to_minutes(row.get("Minutes"))
        record["team_points"] = spine["team_points"]
        record["opponent_points"] = spine["opponent_points"]
        record["margin"] = spine["margin"]
        record["win"] = spine["win"]
        record["team_possessions"] = spine["team_possessions"]
        record["opponent_possessions"] = spine["opponent_possessions"]

        for raw_key, value in row.items():
            if raw_key in identity:
                continue
            record[normalize_column(raw_key)] = _to_number(value)
        records.append(record)

    columns = spine_columns + [c for c in metric_cols if c not in spine_columns]
    frame = pd.DataFrame(records)
    frame = frame.reindex(columns=columns)
    # pbpstats omits zero-valued stats: absent metric -> 0. Spine/identity columns are left as-is.
    metric_fill = {c: 0 for c in metric_cols if c in frame.columns}
    if metric_fill:
        frame = frame.fillna(value=metric_fill)
    sort_keys = [k for k in (id_field, "game_date", "game_id") if k in frame.columns]
    if sort_keys:
        frame = frame.sort_values(sort_keys).reset_index(drop=True)
    return frame


def build_player_game(
    log_rows: Sequence[Mapping[str, Any]],
    games: Mapping[str, Mapping[str, Any]],
    *,
    season: Any = 2026,
    season_type: str = "Regular Season",
) -> pd.DataFrame:
    """Normalized one-row-per-player-game table keyed on ``player_id + game_id``."""
    return _build(
        log_rows, games,
        season=season, season_type=season_type,
        identity=_PLAYER_IDENTITY, id_field="player_id", spine_columns=_PLAYER_SPINE,
        extra_identity={"player_id": ("PlayerId", "row"), "player_name": ("PlayerName", "row")},
    )


def build_team_game(
    log_rows: Sequence[Mapping[str, Any]],
    games: Mapping[str, Mapping[str, Any]],
    *,
    season: Any = 2026,
    season_type: str = "Regular Season",
) -> pd.DataFrame:
    """Normalized one-row-per-team-game table keyed on ``team_id + game_id``."""
    return _build(
        log_rows, games,
        season=season, season_type=season_type,
        identity=_TEAM_IDENTITY, id_field="team_id", spine_columns=_TEAM_SPINE,
        extra_identity={"team_name": ("TeamName", "row")},
    )
