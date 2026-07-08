from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


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

TEAM_NAME_TO_ABBR = {
    "aces": "LVA",
    "atlanta dream": "ATL",
    "chicago sky": "CHI",
    "connecticut sun": "CON",
    "dallas wings": "DAL",
    "dream": "ATL",
    "fever": "IND",
    "fire": "PDX",
    "golden state valkyries": "GSV",
    "indiana fever": "IND",
    "las vegas aces": "LVA",
    "liberty": "NYL",
    "los angeles sparks": "LAS",
    "lynx": "MIN",
    "mercury": "PHX",
    "minnesota lynx": "MIN",
    "mystics": "WAS",
    "new york liberty": "NYL",
    "phoenix mercury": "PHX",
    "portland fire": "PDX",
    "seattle storm": "SEA",
    "sky": "CHI",
    "sparks": "LAS",
    "storm": "SEA",
    "sun": "CON",
    "valkyries": "GSV",
    "washington mystics": "WAS",
    "wings": "DAL",
}


def safe_divide(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    return np.where(denominator > 0, numerator / denominator, np.nan)


def _id_series(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for col in candidates:
        if col in df.columns:
            return df[col].astype(str)
    return pd.Series(dtype=str)


def _name_key(value) -> str:
    return " ".join(str(value).lower().split())


def _team_key(value) -> str:
    raw = str(value).strip().upper()
    return TEAM_ABBR_ALIASES.get(raw, raw)


def _team_key_from_row(row: pd.Series) -> str:
    for col in ["team_abbreviation", "team_abbrev", "abbreviation", "team_short_display_name"]:
        if col in row and pd.notna(row[col]):
            return _team_key(row[col])
    for col in ["team_display_name", "team_name", "name", "short_name"]:
        if col in row and pd.notna(row[col]):
            key = _name_key(row[col])
            if key in TEAM_NAME_TO_ABBR:
                return TEAM_NAME_TO_ABBR[key]
    return ""


def build_box_workload(player_box: pd.DataFrame) -> pd.DataFrame:
    columns = ["player_name_key", "team_key", "box_minutes", "box_games_played", "box_starts"]
    if player_box.empty or not {"athlete_display_name", "team_abbreviation", "minutes"}.issubset(player_box.columns):
        return pd.DataFrame(columns=columns)

    box = player_box.copy()
    if "did_not_play" in box.columns:
        box = box[box["did_not_play"] != True].copy()  # noqa: E712
    box["box_minutes_row"] = pd.to_numeric(box["minutes"], errors="coerce")
    box = box[
        box["box_minutes_row"].notna()
        & box["athlete_display_name"].notna()
        & box["team_abbreviation"].notna()
    ].copy()
    if box.empty:
        return pd.DataFrame(columns=columns)

    box["player_name_key"] = box["athlete_display_name"].map(_name_key)
    box["team_key"] = box["team_abbreviation"].map(_team_key)
    if "starter" in box.columns:
        box["box_start_row"] = box["starter"].fillna(False).astype(bool).astype(int)
    else:
        box["box_start_row"] = np.nan
    game_col = "game_id" if "game_id" in box.columns else None
    grouped = box.groupby(["player_name_key", "team_key"], dropna=False).agg(
        box_minutes=("box_minutes_row", "sum"),
        box_games_played=(game_col, "nunique") if game_col else ("box_minutes_row", "count"),
        box_starts=("box_start_row", "sum"),
    ).reset_index()
    grouped["box_minutes"] = grouped["box_minutes"].round(1)
    return grouped[columns]


def build_position_lookup(player_box: pd.DataFrame, player_season_stats: pd.DataFrame) -> Dict[str, str]:
    pieces = []
    if not player_box.empty and {"athlete_id", "athlete_position_abbreviation"}.issubset(player_box.columns):
        cols = ["athlete_id", "athlete_position_abbreviation"]
        if "athlete_display_name" in player_box.columns:
            cols.append("athlete_display_name")
        pieces.append(player_box[cols].rename(columns={"athlete_id": "player_id", "athlete_display_name": "player_name"}))
    if not player_season_stats.empty and {"athlete_id", "athlete_position_abbreviation"}.issubset(player_season_stats.columns):
        cols = ["athlete_id", "athlete_position_abbreviation"]
        if "athlete_display_name" in player_season_stats.columns:
            cols.append("athlete_display_name")
        pieces.append(player_season_stats[cols].rename(columns={"athlete_id": "player_id", "athlete_display_name": "player_name"}))
    if not pieces:
        return {}
    positions = pd.concat(pieces, ignore_index=True).dropna(subset=["player_id", "athlete_position_abbreviation"])
    positions["player_id"] = positions["player_id"].astype(str)
    positions["athlete_position_abbreviation"] = positions["athlete_position_abbreviation"].astype(str)
    lookup: Dict[str, str] = {}
    for _, row in positions.drop_duplicates("player_id").iterrows():
        lookup[f"id:{row['player_id']}"] = row["athlete_position_abbreviation"]
    if "player_name" in positions.columns:
        named = positions.dropna(subset=["player_name"]).copy()
        named["name_key"] = named["player_name"].map(_name_key)
        for _, row in named.drop_duplicates("name_key").iterrows():
            lookup[f"name:{row['name_key']}"] = row["athlete_position_abbreviation"]
    return lookup


def build_team_context(team_features: pd.DataFrame, standings: pd.DataFrame) -> pd.DataFrame:
    team = team_features.copy()
    if "entity_id_feature" in team.columns:
        team["team_id_key"] = team["entity_id_feature"].astype(str)
    elif "team_id" in team.columns:
        team["team_id_key"] = team["team_id"].astype(str)
    else:
        team["team_id_key"] = team["team_abbreviation"].astype(str)

    team["team_games_played"] = pd.to_numeric(team.get("games_played"), errors="coerce")
    team["team_off_rating"] = safe_divide(team.get("points", np.nan), team.get("off_poss", np.nan)) * 100
    team["team_def_rating"] = safe_divide(team.get("opponent_points", np.nan), team.get("def_poss", np.nan)) * 100
    team["team_net_rating"] = team["team_off_rating"] - team["team_def_rating"]
    team["team_key"] = team.apply(_team_key_from_row, axis=1)

    keep = ["team_id_key", "team_abbreviation", "team_key", "team_games_played", "team_off_rating", "team_def_rating", "team_net_rating"]
    team_context = team[[c for c in keep if c in team.columns]].copy()

    if not standings.empty:
        stand = standings.copy()
        if "team_id" in stand.columns:
            stand["team_id_key"] = stand["team_id"].astype(str)
        else:
            stand["team_id_key"] = stand.get("team_abbreviation", pd.Series(dtype=str)).astype(str)
        if "win_pct" not in stand.columns and {"wins", "losses"}.issubset(stand.columns):
            stand["win_pct"] = safe_divide(stand["wins"], pd.to_numeric(stand["wins"], errors="coerce") + pd.to_numeric(stand["losses"], errors="coerce"))
        stand["team_win_pct"] = pd.to_numeric(stand.get("win_pct"), errors="coerce")
        stand["team_key"] = stand.apply(_team_key_from_row, axis=1)
        stand_by_id = stand[["team_id_key", "team_win_pct"]].drop_duplicates("team_id_key")
        team_context = team_context.merge(stand_by_id, on="team_id_key", how="left")
        missing_win_pct = team_context["team_win_pct"].isna()
        if missing_win_pct.any() and "team_key" in team_context.columns:
            stand_by_key = stand[stand["team_key"].astype(bool)][["team_key", "team_win_pct"]].drop_duplicates("team_key")
            team_context = team_context.merge(stand_by_key, on="team_key", how="left", suffixes=("", "_by_team_key"))
            team_context["team_win_pct"] = team_context["team_win_pct"].fillna(team_context["team_win_pct_by_team_key"])
            team_context = team_context.drop(columns=["team_win_pct_by_team_key"])
    else:
        team_context["team_win_pct"] = np.nan

    return team_context


def build_candidate_pool(
    player_features: pd.DataFrame,
    team_context: pd.DataFrame,
    position_lookup: Dict[str, str],
    box_workload: pd.DataFrame,
    thresholds: Dict,
    *,
    as_of_date: str,
) -> pd.DataFrame:
    df = player_features.copy()
    df["player_id"] = df["entity_id_feature"].astype(str)
    df["player_name"] = df["entity_name_feature"].astype(str)
    df["player_name_key"] = df["player_name"].map(_name_key)
    df["team_id_key"] = df.get("team_id", df["team_abbreviation"]).astype(str)
    df["team_key"] = df["team_abbreviation"].map(_team_key)
    df["pbpstats_minutes"] = pd.to_numeric(df.get("minutes"), errors="coerce")
    df["pbpstats_games_played"] = pd.to_numeric(df.get("games_played"), errors="coerce")

    if box_workload is not None and not box_workload.empty:
        df = df.merge(box_workload, on=["player_name_key", "team_key"], how="left")
    else:
        df["box_minutes"] = np.nan
        df["box_games_played"] = np.nan
        df["box_starts"] = np.nan

    if "team_id_key" in team_context.columns:
        df = df.merge(
            team_context[["team_id_key", "team_games_played", "team_win_pct", "team_net_rating"]],
            on="team_id_key",
            how="left",
        )
    df["team_games_played"] = df["team_games_played"].fillna(df.groupby("team_abbreviation")["pbpstats_games_played"].transform("max"))
    df["games_played"] = pd.to_numeric(df["box_games_played"], errors="coerce")
    df["minutes"] = pd.to_numeric(df["box_minutes"], errors="coerce")
    df["box_starts"] = pd.to_numeric(df["box_starts"], errors="coerce")
    df["start_rate"] = safe_divide(df["box_starts"], df["box_games_played"])
    starter_threshold = float(thresholds.get("starter_role_start_rate_threshold", 0.50))
    df["starter_role_flag"] = df["start_rate"] >= starter_threshold
    df["availability_rate"] = safe_divide(df["box_games_played"], df["team_games_played"])
    df["mpg"] = safe_divide(df["box_minutes"], df["box_games_played"])
    df["eligibility_minutes_source"] = np.where(
        df["box_minutes"].notna() & df["box_games_played"].notna(),
        "sportsdataverse_player_box",
        "missing_sportsdataverse_player_box",
    )
    df["eligibility_minutes_source"] = "missing_sportsdataverse_player_box"
    df.loc[df["box_minutes"].notna() & df["box_games_played"].notna(), "eligibility_minutes_source"] = "sportsdataverse_player_box"
    
    df["position"] = df["player_id"].map(lambda value: position_lookup.get(f"id:{value}"))
    name_positions = df["player_name"].map(lambda value: position_lookup.get(f"name:{_name_key(value)}"))
    df["position"] = df["position"].fillna(name_positions).fillna("UNK")

    min_minutes = float(thresholds.get("min_minutes", 300))
    watchlist_min_minutes = float(thresholds.get("watchlist_min_minutes", 180))
    min_games = float(thresholds.get("min_games", 8))
    min_team_game_share = float(thresholds.get("min_team_game_share", 0.45))

    core = (
        (df["box_minutes"] >= min_minutes)
        & (df["box_games_played"] >= min_games)
        & (df["availability_rate"] >= min_team_game_share)
    )
    watchlist = (
        ~core
        & (df["box_minutes"] >= watchlist_min_minutes)
        & (df["box_games_played"] >= min_games)
    )

    df["eligible_flag"] = core
    df["candidate_tier"] = np.select(
        [core, watchlist],
        ["Core Candidate", "Watchlist"],
        default="Ineligible",
    )
    df["eligibility_reason"] = np.select(
        [core, watchlist],
        [
            "Meets minutes, games, and team-game share thresholds",
            "Meets watchlist workload but falls short of full eligibility",
        ],
        default="Below minimum All-Star board workload thresholds",
    )
    df["season"] = 2026
    df["as_of_date"] = as_of_date

    columns = [
        "season",
        "as_of_date",
        "player_id",
        "player_name",
        "team_id_key",
        "team_abbreviation",
        "position",
        "games_played",
        "team_games_played",
        "team_win_pct",
        "team_net_rating",
        "availability_rate",
        "minutes",
        "box_minutes",
        "box_games_played",
        "box_starts",
        "start_rate",
        "starter_role_flag",
        "pbpstats_minutes",
        "pbpstats_games_played",
        "eligibility_minutes_source",
        "mpg",
        "eligible_flag",
        "candidate_tier",
        "eligibility_reason",
    ]
    out = df[[c for c in columns if c in df.columns]].rename(columns={"team_id_key": "team_id"})
    return out.sort_values(["candidate_tier", "minutes"], ascending=[True, False]).reset_index(drop=True)
