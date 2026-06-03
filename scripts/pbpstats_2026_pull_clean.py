"""
pbpstats_2026_pull_clean.py

GitHub-ready WNBA 2026 PBPStats raw pull + clean script.

Purpose
-------
Pull 2026 WNBA PBPStats data, save raw files first, then clean/process them.

For an active season, totals rows change throughout the season. This script uses:
- raw_master/: append-only history of unique raw row states
- raw_latest/: overwritten current raw snapshot
- clean_master/: append-only history of unique clean row states
- clean_latest/: overwritten current clean snapshot

Run
---
python scripts/pbpstats_2026_pull_clean.py

Dependencies
------------
pip install pandas numpy requests
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests


# =============================================================================
# CONFIG
# =============================================================================

LEAGUE = "wnba"
SEASON = "2026"
SEASON_TYPE = "Regular Season"
BASE_URL = "https://api.pbpstats.com"

# Placeholder-friendly root. Codex can rename this later.
DATA_ROOT = Path(os.getenv("PBPSTATS_PIPELINE_DATA_ROOT", "data/pbpstats_wnba_2026"))

RAW_MASTER_DIR = DATA_ROOT / "raw_master" / SEASON
RAW_LATEST_DIR = DATA_ROOT / "raw_latest" / SEASON

CLEAN_MASTER_DIR = DATA_ROOT / "clean_master" / SEASON
CLEAN_LATEST_DIR = DATA_ROOT / "clean_latest" / SEASON

RUN_LOG_DIR = DATA_ROOT / "run_logs"

REQUEST_SLEEP_SECONDS = float(os.getenv("PBPSTATS_SLEEP_SECONDS", "0.35"))
MAX_RETRIES = int(os.getenv("PBPSTATS_MAX_RETRIES", "4"))
TIMEOUT_SECONDS = int(os.getenv("PBPSTATS_TIMEOUT_SECONDS", "30"))

DATASET_FILES = {
    "teams_directory": {
        "raw_master": RAW_MASTER_DIR / "wnba_teams_directory_raw_master.csv",
        "raw_latest_csv": RAW_LATEST_DIR / "wnba_teams_directory_raw_latest.csv",
        "raw_latest_json": RAW_LATEST_DIR / "wnba_teams_directory_raw_latest.json",
        "clean_master": CLEAN_MASTER_DIR / "wnba_teams_directory_clean_master.csv",
        "clean_latest_csv": CLEAN_LATEST_DIR / "wnba_teams_directory_clean_latest.csv",
        "clean_latest_json": CLEAN_LATEST_DIR / "wnba_teams_directory_clean_latest.json",
    },
    "players_directory": {
        "raw_master": RAW_MASTER_DIR / "wnba_players_directory_raw_master.csv",
        "raw_latest_csv": RAW_LATEST_DIR / "wnba_players_directory_raw_latest.csv",
        "raw_latest_json": RAW_LATEST_DIR / "wnba_players_directory_raw_latest.json",
        "clean_master": CLEAN_MASTER_DIR / "wnba_players_directory_clean_master.csv",
        "clean_latest_csv": CLEAN_LATEST_DIR / "wnba_players_directory_clean_latest.csv",
        "clean_latest_json": CLEAN_LATEST_DIR / "wnba_players_directory_clean_latest.json",
    },
    "player_totals": {
        "raw_master": RAW_MASTER_DIR / "player_totals_raw_master.csv",
        "raw_latest_csv": RAW_LATEST_DIR / "player_totals_raw_latest.csv",
        "raw_latest_json": RAW_LATEST_DIR / "player_totals_raw_latest.json",
        "clean_master": CLEAN_MASTER_DIR / "player_totals_clean_master.csv",
        "clean_latest_csv": CLEAN_LATEST_DIR / "player_totals_clean_latest.csv",
        "clean_latest_json": CLEAN_LATEST_DIR / "player_totals_clean_latest.json",
    },
    "team_totals": {
        "raw_master": RAW_MASTER_DIR / "team_totals_raw_master.csv",
        "raw_latest_csv": RAW_LATEST_DIR / "team_totals_raw_latest.csv",
        "raw_latest_json": RAW_LATEST_DIR / "team_totals_raw_latest.json",
        "clean_master": CLEAN_MASTER_DIR / "team_totals_clean_master.csv",
        "clean_latest_csv": CLEAN_LATEST_DIR / "team_totals_clean_latest.csv",
        "clean_latest_json": CLEAN_LATEST_DIR / "team_totals_clean_latest.json",
    },
}

VOLATILE_HASH_FIELDS = {
    "_run_id",
    "_fetched_at_utc",
    "_cleaned_at_utc",
    "_clean_run_id",
    "_feature_run_id",
    "_featured_at_utc",
    "_row_content_hash",
    "_row_state_hash",
    "run_id",
    "fetched_at_utc",
    "cleaned_at_utc",
    "clean_run_id",
    "feature_run_id",
    "featured_at_utc",
    "row_content_hash",
    "row_state_hash",
}


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


RUN_ID = os.getenv("PBPSTATS_RUN_ID", make_run_id())


def ensure_dirs() -> None:
    for path in [RAW_MASTER_DIR, RAW_LATEST_DIR, CLEAN_MASTER_DIR, CLEAN_LATEST_DIR, RUN_LOG_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def hash_obj(obj: Any) -> str:
    return hashlib.sha256(stable_json_dumps(obj).encode("utf-8")).hexdigest()


def nonvolatile_row_hash(row: Dict[str, Any]) -> str:
    """Hash row contents while excluding run/timestamp/hash metadata."""
    clean_row = {k: v for k, v in row.items() if k not in VOLATILE_HASH_FIELDS}
    return hash_obj(clean_row)


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def read_hashes_from_csv(path: Path, hash_col: str = "_row_content_hash") -> set:
    if not path.exists():
        return set()
    try:
        return set(pd.read_csv(path, usecols=[hash_col])[hash_col].astype(str))
    except Exception:
        existing = pd.read_csv(path)
        if hash_col not in existing.columns:
            return set()
        return set(existing[hash_col].astype(str))


def append_unique_csv(path: Path, df: pd.DataFrame, hash_col: str = "_row_content_hash") -> Tuple[int, int, int]:
    """Append only rows whose hash_col is not already present in path."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if df.empty:
        before = len(pd.read_csv(path)) if path.exists() else 0
        return before, 0, before

    if hash_col not in df.columns:
        raise ValueError(f"Missing hash column: {hash_col}")

    before_count = len(pd.read_csv(path)) if path.exists() else 0
    existing_hashes = read_hashes_from_csv(path, hash_col=hash_col)
    df_to_add = df[~df[hash_col].astype(str).isin(existing_hashes)].copy()
    added_count = len(df_to_add)

    if added_count > 0:
        df_to_add.to_csv(path, mode="a", header=not path.exists(), index=False)

    return before_count, added_count, before_count + added_count


def overwrite_latest(csv_path: Path, json_path: Path, df: pd.DataFrame, metadata: Dict[str, Any]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    save_json(
        json_path,
        {
            "metadata": {
                **metadata,
                "row_count": len(df),
                "last_saved_at_utc": utc_now_iso(),
                "run_id": RUN_ID,
            },
            "rows": df.to_dict(orient="records"),
        },
    )


# =============================================================================
# API HELPERS
# =============================================================================

def request_json(endpoint: str, params: Optional[Dict[str, Any]] = None, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    sess = session or requests.Session()
    url = f"{BASE_URL}{endpoint}"
    last_err: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = sess.get(url, params=params or {}, timeout=TIMEOUT_SECONDS)
            if response.status_code in {429, 500, 502, 503, 504}:
                wait = min(2 ** attempt, 30)
                print(f"[retry] {response.status_code} {endpoint} attempt={attempt}; sleep={wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except Exception as err:
            last_err = err
            wait = min(2 ** attempt, 30)
            print(f"[retry] error {endpoint} attempt={attempt}: {err}; sleep={wait}s")
            time.sleep(wait)

    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {endpoint} params={params}") from last_err


def extract_table_rows(response_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = response_json.get("multi_row_table_data", [])
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("Expected multi_row_table_data to be a list")
    return rows


def extract_single_row(response_json: Dict[str, Any]) -> Dict[str, Any]:
    single = response_json.get("single_row_table_data", {})
    if single is None:
        return {}
    return single if isinstance(single, dict) else {"value": single}


# =============================================================================
# RAW COLLECTION
# =============================================================================

def annotate_raw_rows(
    rows: List[Dict[str, Any]],
    *,
    dataset: str,
    endpoint: str,
    params: Dict[str, Any],
    season: Optional[str],
    season_type: Optional[str],
) -> pd.DataFrame:
    annotated = []
    fetched_at = utc_now_iso()

    for row in rows:
        new_row = dict(row)
        new_row["_dataset"] = dataset
        new_row["_league"] = LEAGUE
        new_row["_season"] = season
        new_row["_season_type"] = season_type
        new_row["_source_endpoint"] = endpoint
        new_row["_source_params_json"] = stable_json_dumps(params)
        new_row["_run_id"] = RUN_ID
        new_row["_fetched_at_utc"] = fetched_at
        new_row["_row_content_hash"] = nonvolatile_row_hash(new_row)
        annotated.append(new_row)

    return pd.DataFrame(annotated)


def fetch_teams_directory(session: requests.Session) -> pd.DataFrame:
    endpoint = f"/get-teams/{LEAGUE}"
    params: Dict[str, Any] = {}
    response_json = request_json(endpoint, params=params, session=session)
    rows = response_json.get("teams", [])

    if not isinstance(rows, list):
        raise ValueError("Expected get-teams response to contain a list under key 'teams'")

    df = annotate_raw_rows(rows, dataset="teams_directory", endpoint=endpoint, params=params, season=None, season_type=None)
    df["_source_response_keys"] = stable_json_dumps(list(response_json.keys()))
    return df


def fetch_players_directory(session: requests.Session) -> pd.DataFrame:
    endpoint = f"/get-all-players-for-league/{LEAGUE}"
    params: Dict[str, Any] = {}
    response_json = request_json(endpoint, params=params, session=session)
    players = response_json.get("players", {})

    if not isinstance(players, dict):
        raise ValueError("Expected players response to contain dict under key 'players'")

    rows = [{"PlayerId": str(player_id), "PlayerName": player_name} for player_id, player_name in players.items()]
    df = annotate_raw_rows(rows, dataset="players_directory", endpoint=endpoint, params=params, season=None, season_type=None)
    df["_source_response_keys"] = stable_json_dumps(list(response_json.keys()))
    return df


def fetch_totals(session: requests.Session, stats_type: str) -> pd.DataFrame:
    endpoint = f"/get-totals/{LEAGUE}"
    params = {"Season": SEASON, "SeasonType": SEASON_TYPE, "Type": stats_type}
    response_json = request_json(endpoint, params=params, session=session)
    rows = extract_table_rows(response_json)
    single_row = extract_single_row(response_json)
    dataset = f"{stats_type.lower()}_totals"

    df = annotate_raw_rows(rows, dataset=dataset, endpoint=endpoint, params=params, season=SEASON, season_type=SEASON_TYPE)
    df["_source_response_keys"] = stable_json_dumps(list(response_json.keys()))
    df["_single_row_table_data_json"] = stable_json_dumps(single_row)
    return df


def persist_raw_dataset(dataset: str, raw_df: pd.DataFrame) -> Dict[str, Any]:
    files = DATASET_FILES[dataset]
    before, added, after = append_unique_csv(files["raw_master"], raw_df)
    overwrite_latest(
        files["raw_latest_csv"],
        files["raw_latest_json"],
        raw_df,
        metadata={
            "dataset": dataset,
            "layer": "raw_latest",
            "season": SEASON,
            "season_type": SEASON_TYPE,
            "dedupe_strategy": "raw_master appends unique content hashes; raw_latest overwrites current API snapshot",
        },
    )
    print(f"[raw:{dataset}] API rows={len(raw_df)} | master before={before} | added={added} | after={after}")
    return {"dataset": dataset, "api_rows": len(raw_df), "master_before": before, "master_added": added, "master_after": after}


# =============================================================================
# CLEANING
# =============================================================================

def normalize_column_name(col: str) -> str:
    col = str(col).strip()
    col = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", col)
    col = re.sub(r"[^0-9a-zA-Z]+", "_", col)
    col = re.sub(r"_+", "_", col)
    return col.strip("_").lower()


def rename_shotquality_column(original_col: str) -> str:
    normalized = normalize_column_name(original_col)
    normalized = normalized.replace("shot_quality", "shotquality")
    normalized = normalized.replace("shotquality_pbp", "shotquality")

    if normalized == "shotquality":
        return "shotquality_pbp"
    if normalized.startswith("shotquality_"):
        return f"shotquality_pbp_{normalized.replace('shotquality_', '', 1)}"
    if normalized.endswith("_shotquality"):
        return f"shotquality_pbp_{normalized.replace('_shotquality', '')}"
    if "shotquality" in normalized:
        suffix = normalized.replace("shotquality", "").strip("_")
        return f"shotquality_pbp_{suffix}" if suffix else "shotquality_pbp"
    return normalized


def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    rename_map: Dict[str, str] = {}
    used: Dict[str, int] = {}

    for col in df.columns:
        norm = normalize_column_name(col)
        new_col = rename_shotquality_column(col) if ("shot_quality" in norm or "shotquality" in norm) else norm
        new_col = re.sub(r"_+", "_", new_col).strip("_")

        if new_col in used:
            used[new_col] += 1
            new_col = f"{new_col}_{used[new_col]}"
        else:
            used[new_col] = 0

        rename_map[col] = new_col

    return df.rename(columns=rename_map)


def coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    protected = ["id", "name", "team", "player", "league", "season", "dataset", "endpoint", "params", "hash", "run_id", "fetched_at", "source"]

    for col in df.columns:
        col_lower = col.lower()
        if any(p in col_lower for p in protected):
            continue
        if df[col].dtype == "object":
            cleaned = (
                df[col]
                .astype(str)
                .str.replace("%", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.strip()
                .replace({"nan": np.nan, "None": np.nan, "": np.nan})
            )
            numeric = pd.to_numeric(cleaned, errors="coerce")
            original_non_null = df[col].notna().sum()
            numeric_non_null = numeric.notna().sum()
            if original_non_null > 0 and numeric_non_null / original_non_null >= 0.80:
                df[col] = numeric
    return df


def first_existing_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def add_standard_ids(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    df = df.copy()

    if dataset in {"player_totals", "players_directory"}:
        id_col = first_existing_col(df, ["player_id", "playerid", "entity_id", "id"])
        name_col = first_existing_col(df, ["player_name", "playername", "name", "player", "entity_name"])
        if id_col:
            df["player_id_clean"] = df[id_col].astype(str)
        if name_col:
            df["player_name_clean"] = df[name_col].astype(str)

    if dataset in {"team_totals", "teams_directory"}:
        id_col = first_existing_col(df, ["team_id", "teamid", "entity_id", "id"])
        name_col = first_existing_col(df, ["team", "team_abbreviation", "team_name", "name", "text", "entity_name"])
        if id_col:
            df["team_id_clean"] = df[id_col].astype(str)
        if name_col:
            df["team_name_clean"] = df[name_col].astype(str)

    return df


def clean_raw_df(raw_df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    clean = raw_df.copy()
    clean = clean_column_names(clean)
    clean = coerce_numeric_columns(clean)
    clean = add_standard_ids(clean, dataset)
    clean["season"] = SEASON if dataset in {"player_totals", "team_totals"} else None
    clean["season_type"] = SEASON_TYPE if dataset in {"player_totals", "team_totals"} else None
    clean["league"] = LEAGUE
    clean["dataset_clean"] = dataset
    clean["_cleaned_at_utc"] = utc_now_iso()
    clean["_clean_run_id"] = RUN_ID
    clean["_row_content_hash"] = [nonvolatile_row_hash(row) for row in clean.to_dict(orient="records")]
    return clean


def persist_clean_dataset(dataset: str, clean_df: pd.DataFrame) -> Dict[str, Any]:
    files = DATASET_FILES[dataset]
    before, added, after = append_unique_csv(files["clean_master"], clean_df)
    overwrite_latest(
        files["clean_latest_csv"],
        files["clean_latest_json"],
        clean_df,
        metadata={
            "dataset": dataset,
            "layer": "clean_latest",
            "season": SEASON,
            "season_type": SEASON_TYPE,
            "dedupe_strategy": "clean_master appends unique content hashes; clean_latest overwrites current cleaned snapshot",
        },
    )
    print(f"[clean:{dataset}] rows={len(clean_df)} | master before={before} | added={added} | after={after}")
    return {"dataset": dataset, "clean_rows": len(clean_df), "master_before": before, "master_added": added, "master_after": after}


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    ensure_dirs()

    print("=" * 96)
    print("PBPStats WNBA 2026 Pull + Clean")
    print(f"run_id={RUN_ID}")
    print(f"data_root={DATA_ROOT}")
    print("=" * 96)

    run_summary = {"run_id": RUN_ID, "started_at_utc": utc_now_iso(), "season": SEASON, "season_type": SEASON_TYPE, "raw": [], "clean": []}

    with requests.Session() as session:
        fetch_plan = {
            "teams_directory": fetch_teams_directory,
            "players_directory": fetch_players_directory,
            "player_totals": lambda s: fetch_totals(s, "Player"),
            "team_totals": lambda s: fetch_totals(s, "Team"),
        }
        latest_raw: Dict[str, pd.DataFrame] = {}

        for dataset, fetch_fn in fetch_plan.items():
            raw_df = fetch_fn(session)
            latest_raw[dataset] = raw_df
            run_summary["raw"].append(persist_raw_dataset(dataset, raw_df))
            time.sleep(REQUEST_SLEEP_SECONDS)

        for dataset, raw_df in latest_raw.items():
            clean_df = clean_raw_df(raw_df, dataset)
            run_summary["clean"].append(persist_clean_dataset(dataset, clean_df))

    run_summary["finished_at_utc"] = utc_now_iso()
    log_path = RUN_LOG_DIR / f"pull_clean_{RUN_ID}.json"
    save_json(log_path, run_summary)

    print("=" * 96)
    print("DONE: Pull + Clean")
    print(f"Run log: {log_path}")
    print("=" * 96)


if __name__ == "__main__":
    main()
