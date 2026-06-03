"""
pbpstats_2026_features.py

GitHub-ready WNBA 2026 feature engineering script.

Purpose
-------
Reads latest cleaned 2026 PBPStats totals and produces:
- player feature panel
- team feature panel
- dashboard-ready leaderboard/summary tables

Because 2026 is a single active season, this script does NOT calculate YoY deltas.
It keeps features that make sense for one season:
- efficiency metrics
- shot-zone shares
- shotquality_pbp features
- shot-making over shotquality_pbp
- percentiles
- shooting labels
- shot diet/risk labels
- leaderboard tables

Run
---
python scripts/pbpstats_2026_features.py

Dependencies
------------
pip install pandas numpy
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# =============================================================================
# CONFIG
# =============================================================================

LEAGUE = "wnba"
SEASON = "2026"
SEASON_TYPE = "Regular Season"

DATA_ROOT = Path(os.getenv("PBPSTATS_PIPELINE_DATA_ROOT", "data/pbpstats_wnba_2026"))

CLEAN_LATEST_DIR = DATA_ROOT / "clean_latest" / SEASON

FEATURES_MASTER_DIR = DATA_ROOT / "features_master" / SEASON
FEATURES_LATEST_DIR = DATA_ROOT / "features_latest" / SEASON
LEADERBOARD_LATEST_DIR = FEATURES_LATEST_DIR / "leaderboards"
RUN_LOG_DIR = DATA_ROOT / "run_logs"

RUN_ID = os.getenv("PBPSTATS_RUN_ID", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

PLAYER_CLEAN_LATEST = CLEAN_LATEST_DIR / "player_totals_clean_latest.csv"
TEAM_CLEAN_LATEST = CLEAN_LATEST_DIR / "team_totals_clean_latest.csv"

PLAYER_FEATURES_MASTER = FEATURES_MASTER_DIR / "player_totals_features_master.csv"
TEAM_FEATURES_MASTER = FEATURES_MASTER_DIR / "team_totals_features_master.csv"

PLAYER_FEATURES_LATEST = FEATURES_LATEST_DIR / "player_totals_features_latest.csv"
TEAM_FEATURES_LATEST = FEATURES_LATEST_DIR / "team_totals_features_latest.csv"

PLAYER_FEATURES_LATEST_JSON = FEATURES_LATEST_DIR / "player_totals_features_latest.json"
TEAM_FEATURES_LATEST_JSON = FEATURES_LATEST_DIR / "team_totals_features_latest.json"

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
    "_source_endpoint",
    "_source_params_json",
    "_source_response_keys",
    "_single_row_table_data_json",
    "source_endpoint",
    "source_params_json",
    "source_response_keys",
    "single_row_table_data_json",
}

INHERITED_METADATA_COLUMNS = {
    "_run_id",
    "_fetched_at_utc",
    "_cleaned_at_utc",
    "_clean_run_id",
    "_row_content_hash",
    "_row_state_hash",
    "run_id",
    "fetched_at_utc",
    "cleaned_at_utc",
    "clean_run_id",
    "row_content_hash",
    "row_state_hash",
    "_source_endpoint",
    "_source_params_json",
    "_source_response_keys",
    "_single_row_table_data_json",
    "source_endpoint",
    "source_params_json",
    "source_response_keys",
    "single_row_table_data_json",
}

FEATURE_HASH_EXCLUDED_FIELDS = VOLATILE_HASH_FIELDS | {
    "feature_level",
    "season",
    "season_type",
    "league",
}


# =============================================================================
# HELPERS
# =============================================================================

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dirs() -> None:
    for path in [FEATURES_MASTER_DIR, FEATURES_LATEST_DIR, LEADERBOARD_LATEST_DIR, RUN_LOG_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def stable_json_dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def hash_obj(obj) -> str:
    return hashlib.sha256(stable_json_dumps(obj).encode("utf-8")).hexdigest()


def normalize_hash_value(value):
    if isinstance(value, dict):
        return {str(k): normalize_hash_value(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [normalize_hash_value(v) for v in value]
    if isinstance(value, (np.integer, np.int64)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if pd.isna(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def normalized_hash_record(row: Dict) -> Dict:
    return {str(k): normalize_hash_value(v) for k, v in sorted(row.items(), key=lambda item: str(item[0]))}


def build_row_hash(*, context: Dict, row: Dict) -> str:
    return hash_obj({"context": normalized_hash_record(context), "row": normalized_hash_record(row)})


def build_feature_row_hash(row: Dict, *, level: str, season: str = SEASON, season_type: str = SEASON_TYPE, league: str = LEAGUE) -> str:
    business_row = {k: v for k, v in row.items() if k not in FEATURE_HASH_EXCLUDED_FIELDS}
    context = {
        "feature_level": level,
        "league": league,
        "season": season,
        "season_type": season_type,
    }
    return build_row_hash(context=context, row=business_row)


def nonvolatile_row_hash(row: Dict) -> str:
    return build_row_hash(context={}, row={k: v for k, v in row.items() if k not in VOLATILE_HASH_FIELDS})


def save_json(path: Path, payload: Dict) -> None:
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
        df = pd.read_csv(path)
        return set(df[hash_col].astype(str)) if hash_col in df.columns else set()


def is_valid_hash(value) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value)))


def filter_valid_hash_rows(df: pd.DataFrame, hash_col: str = "_row_content_hash") -> pd.DataFrame:
    if df.empty or hash_col not in df.columns:
        return df.iloc[0:0].copy() if hash_col not in df.columns else df.copy()
    mask = df[hash_col].astype(str).apply(is_valid_hash)
    return df.loc[mask].copy()


def align_columns(existing: pd.DataFrame, new_rows: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    ordered_cols = list(existing.columns)
    for col in new_rows.columns:
        if col not in ordered_cols:
            ordered_cols.append(col)
    existing_aligned = existing.reindex(columns=ordered_cols)
    new_aligned = new_rows.reindex(columns=ordered_cols)
    return existing_aligned, new_aligned


def append_unique_csv(path: Path, df: pd.DataFrame, hash_col: str = "_row_content_hash") -> Tuple[int, int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)

    if df.empty:
        before = len(filter_valid_hash_rows(pd.read_csv(path), hash_col=hash_col)) if path.exists() else 0
        return before, 0, before

    if hash_col not in df.columns:
        raise ValueError(f"Missing hash column: {hash_col}")

    valid_new = filter_valid_hash_rows(df, hash_col=hash_col)
    if path.exists():
        existing = pd.read_csv(path)
        existing = filter_valid_hash_rows(existing, hash_col=hash_col)
    else:
        existing = pd.DataFrame(columns=valid_new.columns)

    before_count = len(existing)
    existing, valid_new = align_columns(existing, valid_new)
    existing_hashes = set(existing[hash_col].astype(str)) if hash_col in existing.columns else set()
    df_to_add = valid_new[~valid_new[hash_col].astype(str).isin(existing_hashes)].copy()
    added_count = len(df_to_add)

    combined = pd.concat([existing, df_to_add], ignore_index=True)
    combined.to_csv(path, index=False)

    return before_count, added_count, before_count + added_count


def overwrite_csv_json(csv_path: Path, json_path: Path, df: pd.DataFrame, metadata: Dict) -> None:
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


def clean_duplicate_underscores(text: str) -> str:
    text = str(text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [clean_duplicate_underscores(c) for c in df.columns]
    return df


def first_existing_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def safe_divide(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce").replace(0, np.nan)
    return numerator / denominator


def infer_rate_scale(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    med = s.dropna().median()
    if pd.isna(med):
        return s
    if med > 1 and med <= 100:
        return s / 100
    return s


def to_numeric_if_possible(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    protected = ["id", "name", "team", "player", "league", "season", "season_type", "label", "category", "source", "hash", "run_id", "fetched", "cleaned"]

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


def pct_rank(df: pd.DataFrame, col: str, out_col: str) -> pd.DataFrame:
    df = df.copy()
    df[out_col] = df[col].rank(pct=True, method="average") if col in df.columns else np.nan
    return df


# =============================================================================
# LOADERS
# =============================================================================

def load_latest_clean(path: Path, level: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing clean latest file: {path}")

    df = pd.read_csv(path)
    df = clean_columns(df)
    df = df.loc[:, ~df.columns.isin(INHERITED_METADATA_COLUMNS)].copy()
    df = to_numeric_if_possible(df)
    df["season"] = SEASON
    df["season_type"] = SEASON_TYPE
    df["league"] = LEAGUE
    df["feature_level"] = level

    if level == "player":
        id_col = first_existing_col(df, ["player_id_clean", "player_id", "playerid", "entity_id", "id"])
        name_col = first_existing_col(df, ["player_name_clean", "player_name", "playername", "name", "player", "entity_name"])
    else:
        id_col = first_existing_col(df, ["team_id_clean", "team_id", "teamid", "entity_id", "id"])
        name_col = first_existing_col(df, ["team_name_clean", "team_name", "team", "team_abbreviation", "name", "text"])

    df["entity_id_feature"] = df[id_col].astype(str) if id_col else np.nan
    df["entity_name_feature"] = df[name_col].astype(str) if name_col else np.nan

    print(f"[loaded:{level}] {path} | rows={len(df)} | cols={len(df.columns)}")
    return df


# =============================================================================
# SHOT DIET FEATURES
# =============================================================================

ZONE_ATTEMPT_CANDIDATES: Dict[str, List[str]] = {
    "rim": ["at_rim_fga", "rim_fga", "restricted_area_fga", "ra_fga"],
    "short_mid": ["short_mid_range_fga", "short_mid_fga", "paint_non_ra_fga"],
    "long_mid": ["long_mid_range_fga", "long_mid_fga", "mid_range_fga", "midrange_fga"],
    "corner3": ["corner3_fga", "corner_3_fga", "corner_three_fga"],
    "above_break3": ["arc3_fga", "arc_3_fga", "above_break_3_fga", "above_break_three_fga"],
}

ZONE_MADE_CANDIDATES: Dict[str, List[str]] = {
    "rim": ["at_rim_fgm", "rim_fgm", "restricted_area_fgm", "ra_fgm"],
    "short_mid": ["short_mid_range_fgm", "short_mid_fgm", "paint_non_ra_fgm"],
    "long_mid": ["long_mid_range_fgm", "long_mid_fgm", "mid_range_fgm", "midrange_fgm"],
    "corner3": ["corner3_fgm", "corner_3_fgm", "corner_three_fgm"],
    "above_break3": ["arc3_fgm", "arc_3_fgm", "above_break_3_fgm", "above_break_three_fgm"],
}


def detect_zone_columns(df: pd.DataFrame) -> Dict[str, Dict[str, Optional[str]]]:
    detected = {}
    for zone in ZONE_ATTEMPT_CANDIDATES:
        detected[zone] = {
            "attempt_col": first_existing_col(df, ZONE_ATTEMPT_CANDIDATES[zone]),
            "made_col": first_existing_col(df, ZONE_MADE_CANDIDATES[zone]),
        }
    print("[shot zone detection]")
    for zone, cols in detected.items():
        print(f"  {zone}: attempts={cols['attempt_col']} | makes={cols['made_col']}")
    return detected


def add_shot_diet_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    detected = detect_zone_columns(df)
    fga_col = first_existing_col(df, ["fga", "fg_a", "field_goal_attempts", "field_goals_attempted"])
    attempt_cols = [info["attempt_col"] for info in detected.values() if info["attempt_col"] is not None]

    df["detected_zone_fga_total"] = df[attempt_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1) if attempt_cols else np.nan
    total_attempts = pd.to_numeric(df[fga_col], errors="coerce") if fga_col else pd.to_numeric(df["detected_zone_fga_total"], errors="coerce")

    for zone, info in detected.items():
        attempt_col = info["attempt_col"]
        made_col = info["made_col"]
        share_col = f"{zone}_fga_share"
        efg_col = f"{zone}_efg_pct"

        df[share_col] = safe_divide(df[attempt_col], total_attempts) if attempt_col else np.nan

        if attempt_col and made_col:
            multiplier = 1.5 if zone in {"corner3", "above_break3"} else 1.0
            df[efg_col] = safe_divide(multiplier * pd.to_numeric(df[made_col], errors="coerce"), pd.to_numeric(df[attempt_col], errors="coerce"))
        else:
            df[efg_col] = np.nan

    df["midrange_fga_share"] = df[["short_mid_fga_share", "long_mid_fga_share"]].sum(axis=1, skipna=False)
    df["three_point_fga_share"] = df[["corner3_fga_share", "above_break3_fga_share"]].sum(axis=1, skipna=False)
    df["rim_and_three_fga_share"] = df[["rim_fga_share", "three_point_fga_share"]].sum(axis=1, skipna=False)
    df["paint_pressure_fga_share"] = df[["rim_fga_share", "short_mid_fga_share"]].sum(axis=1, skipna=False)

    share_cols = ["rim_fga_share", "short_mid_fga_share", "long_mid_fga_share", "corner3_fga_share", "above_break3_fga_share"]
    share_matrix = df[share_cols]
    df["shot_zone_concentration_score"] = (share_matrix ** 2).sum(axis=1, skipna=True)

    def entropy_score(row):
        vals = pd.to_numeric(row, errors="coerce").dropna()
        vals = vals[vals > 0]
        if len(vals) <= 1:
            return 0.0 if len(vals) == 1 else np.nan
        entropy = -np.sum(vals * np.log(vals))
        max_entropy = np.log(len(share_cols))
        return entropy / max_entropy if max_entropy > 0 else np.nan

    df["shot_diet_diversity_score"] = share_matrix.apply(entropy_score, axis=1)
    return df


# =============================================================================
# CORE FEATURES
# =============================================================================

def add_core_efficiency_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pts_col = first_existing_col(df, ["pts", "points"])
    fga_col = first_existing_col(df, ["fga", "fg_a", "field_goal_attempts"])
    fgm_col = first_existing_col(df, ["fgm", "fg_m", "field_goals_made"])
    fg3a_col = first_existing_col(df, ["fg3a", "fg3_a", "three_point_attempts", "three_pointers_attempted"])
    fg3m_col = first_existing_col(df, ["fg3m", "fg3_m", "three_pointers_made"])
    fta_col = first_existing_col(df, ["fta", "ft_a", "free_throw_attempts"])

    if fga_col:
        fga_series = pd.to_numeric(df[fga_col], errors="coerce")
        df["fga_feature_source"] = fga_col
    else:
        fga_series = pd.to_numeric(df["detected_zone_fga_total"], errors="coerce")
        df["fga_feature_source"] = "detected_zone_fga_total"

    efg_existing = first_existing_col(df, ["efg_pct_calc", "efg_pct", "e_fg_pct", "efg"])
    ts_existing = first_existing_col(df, ["ts_pct_calc", "ts_pct", "true_shooting_pct", "ts"])

    if efg_existing:
        df["efg_pct_feature"] = infer_rate_scale(df[efg_existing])
    elif fgm_col and fg3m_col:
        df["efg_pct_feature"] = safe_divide(pd.to_numeric(df[fgm_col], errors="coerce") + 0.5 * pd.to_numeric(df[fg3m_col], errors="coerce"), fga_series)
    else:
        df["efg_pct_feature"] = np.nan

    if ts_existing:
        df["ts_pct_feature"] = infer_rate_scale(df[ts_existing])
    elif pts_col and fta_col:
        df["ts_pct_feature"] = safe_divide(pd.to_numeric(df[pts_col], errors="coerce"), 2 * (fga_series + 0.44 * pd.to_numeric(df[fta_col], errors="coerce")))
    else:
        df["ts_pct_feature"] = np.nan

    df["points_per_fga_feature"] = safe_divide(df[pts_col], fga_series) if pts_col else np.nan
    df["fta_rate_feature"] = safe_divide(df[fta_col], fga_series) if fta_col else np.nan
    df["three_point_attempt_rate_feature"] = safe_divide(df[fg3a_col], fga_series) if fg3a_col else np.nan
    return df


def add_shotquality_pbp_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    shotquality_cols = [c for c in df.columns if c == "shotquality_pbp" or c.startswith("shotquality_pbp_")]
    excluded = {"has_shotquality_pbp_fields", "shotquality_pbp_field_count", "shotquality_pbp_source_column"}
    shotquality_cols = [c for c in shotquality_cols if c not in excluded and "field_count" not in c and not c.startswith("has_") and "source_column" not in c]

    print(f"[shotquality_pbp columns] {shotquality_cols if shotquality_cols else 'None found'}")

    preferred = ["shotquality_pbp", "shotquality_pbp_avg", "shotquality_pbp_efg", "shotquality_pbp_expected_efg", "shotquality_pbp_expected_e_fg"]
    primary = next((c for c in preferred if c in shotquality_cols), None)

    if primary is None:
        for col in shotquality_cols:
            if pd.to_numeric(df[col], errors="coerce").notna().sum() > 0:
                primary = col
                break

    if primary:
        df["shotquality_pbp_feature"] = infer_rate_scale(df[primary])
        df["shotquality_pbp_source_column"] = primary
    else:
        df["shotquality_pbp_feature"] = np.nan
        df["shotquality_pbp_source_column"] = None

    df["shot_making_over_shotquality_pbp"] = df["efg_pct_feature"] - df["shotquality_pbp_feature"]
    return df


def add_sample_flags(df: pd.DataFrame, level: str) -> pd.DataFrame:
    df = df.copy()
    if level == "team":
        df["sample_size_flag"] = "Strong"
        return df

    fga = pd.to_numeric(df.get("detected_zone_fga_total"), errors="coerce")
    df["sample_size_flag"] = np.select([fga >= 250, fga >= 100, fga > 0], ["Strong", "Usable", "Low"], default="Unknown")
    return df


# =============================================================================
# LABELS
# =============================================================================

def label_efficiency_percentile(pct: float) -> str:
    if pd.isna(pct):
        return "Unknown"
    if pct >= 0.90:
        return "Elite Efficiency"
    if pct >= 0.75:
        return "Strong Efficiency"
    if pct >= 0.40:
        return "Average Efficiency"
    if pct >= 0.15:
        return "Low Efficiency"
    return "Efficiency Concern"


def add_percentiles_and_labels(df: pd.DataFrame, level: str) -> pd.DataFrame:
    df = df.copy()
    percentile_cols = [
        "efg_pct_feature", "ts_pct_feature", "points_per_fga_feature", "fta_rate_feature", "three_point_attempt_rate_feature",
        "shotquality_pbp_feature", "shot_making_over_shotquality_pbp", "rim_fga_share", "midrange_fga_share",
        "three_point_fga_share", "rim_and_three_fga_share", "paint_pressure_fga_share", "shot_zone_concentration_score",
        "shot_diet_diversity_score", "corner3_fga_share", "above_break3_fga_share", "corner3_efg_pct", "above_break3_efg_pct",
        "rim_efg_pct", "long_mid_efg_pct", "short_mid_efg_pct",
    ]
    for col in percentile_cols:
        if col in df.columns:
            df = pct_rank(df, col, f"{col}_percentile")

    df["shooting_efficiency_category"] = df["efg_pct_feature_percentile"].apply(label_efficiency_percentile)
    df["ts_efficiency_category"] = df["ts_pct_feature_percentile"].apply(label_efficiency_percentile)

    def shot_quality_label(row):
        sq = row.get("shotquality_pbp_feature_percentile", np.nan)
        over = row.get("shot_making_over_shotquality_pbp", np.nan)
        if pd.isna(sq):
            return "Unknown Shot Quality"
        if sq >= 0.80 and pd.notna(over) and over >= 0.02:
            return "High-Quality Shots + Strong Making"
        if sq >= 0.80:
            return "High-Quality Shot Profile"
        if sq <= 0.25 and pd.notna(over) and over >= 0.04:
            return "Tough-Shot Maker"
        if sq <= 0.25:
            return "Tough Shot Profile"
        return "Average Shot Quality Profile"

    df["shotquality_pbp_profile_label"] = df.apply(shot_quality_label, axis=1)

    def shot_diet_label(row):
        rim3 = row.get("rim_and_three_fga_share", np.nan)
        mid = row.get("midrange_fga_share", np.nan)
        three = row.get("three_point_fga_share", np.nan)
        rim = row.get("rim_fga_share", np.nan)
        diversity = row.get("shot_diet_diversity_score", np.nan)
        concentration = row.get("shot_zone_concentration_score", np.nan)
        if pd.isna(rim3):
            return "Unavailable Shot Diet"
        if rim3 >= 0.68 and mid <= 0.30:
            return "Modern Shot Diet"
        if three >= 0.45:
            return "Perimeter-Leaning"
        if rim >= 0.35:
            return "Paint-Oriented"
        if mid >= 0.45:
            return "Midrange-Heavy"
        if diversity >= 0.88:
            return "Diversified Shot Profile"
        if concentration >= 0.45:
            return "Specialized Shot Profile"
        return "Balanced Shot Diet"

    df["shot_diet_profile_label"] = df.apply(shot_diet_label, axis=1)

    def shooter_specialty(row):
        sample = row.get("sample_size_flag", "Unknown")
        low_sample = level == "player" and sample in {"Low", "Unknown"}
        corner_vol = row.get("corner3_fga_share_percentile", np.nan)
        corner_eff = row.get("corner3_efg_pct_percentile", np.nan)
        above_vol = row.get("above_break3_fga_share_percentile", np.nan)
        above_eff = row.get("above_break3_efg_pct_percentile", np.nan)
        three_vol = row.get("three_point_fga_share_percentile", np.nan)
        efg_pctile = row.get("efg_pct_feature_percentile", np.nan)
        rim_vol = row.get("rim_fga_share_percentile", np.nan)
        rim_eff = row.get("rim_efg_pct_percentile", np.nan)
        mid_vol = row.get("midrange_fga_share_percentile", np.nan)
        diversity = row.get("shot_diet_diversity_score", np.nan)

        if low_sample and pd.notna(efg_pctile) and efg_pctile >= 0.75:
            return "Low-Volume Efficient Shooter"
        if pd.notna(corner_vol) and pd.notna(corner_eff) and corner_vol >= 0.75 and corner_eff >= 0.60:
            return "Corner Spacer"
        if pd.notna(above_vol) and pd.notna(above_eff) and above_vol >= 0.75 and above_eff >= 0.60:
            return "Above-Break Spacer"
        if pd.notna(three_vol) and pd.notna(efg_pctile) and three_vol >= 0.75 and efg_pctile >= 0.60:
            return "Perimeter Volume Threat"
        if pd.notna(rim_vol) and pd.notna(rim_eff) and rim_vol >= 0.75 and rim_eff >= 0.60:
            return "Rim Pressure Finisher"
        if pd.notna(mid_vol) and mid_vol >= 0.75 and pd.notna(efg_pctile) and efg_pctile >= 0.50:
            return "Midrange Specialist"
        if pd.notna(diversity) and diversity >= 0.88 and pd.notna(efg_pctile) and efg_pctile >= 0.50:
            return "Balanced Three-Level Scorer"
        if pd.notna(three_vol) and pd.notna(efg_pctile) and three_vol >= 0.75 and efg_pctile <= 0.35:
            return "High-Volume Low-Efficiency Shooter"
        return "No Clear Shooting Specialty"

    df["specialized_shooter_label"] = df.apply(shooter_specialty, axis=1)

    def risk_label(row):
        mid_pctile = row.get("midrange_fga_share_percentile", np.nan)
        efg_pctile = row.get("efg_pct_feature_percentile", np.nan)
        rim3 = row.get("rim_and_three_fga_share", np.nan)
        three = row.get("three_point_fga_share", np.nan)
        rim = row.get("rim_fga_share", np.nan)
        fta_rate = row.get("fta_rate_feature", np.nan)
        concentration = row.get("shot_zone_concentration_score", np.nan)

        if pd.notna(rim3) and rim3 >= 0.65 and (pd.isna(mid_pctile) or mid_pctile < 0.75):
            return "Clean Shot Profile"
        if pd.notna(mid_pctile) and mid_pctile >= 0.75 and (pd.isna(efg_pctile) or efg_pctile < 0.75):
            return "Midrange-Heavy Risk"
        if pd.notna(rim) and pd.notna(fta_rate) and rim < 0.20 and fta_rate < 0.20:
            return "Low Pressure Profile"
        if pd.notna(three) and three < 0.20:
            return "Spacing-Limited Profile"
        if pd.notna(three) and three >= 0.45:
            return "High Variance Profile"
        if pd.notna(concentration) and concentration >= 0.45:
            return "Specialist-Dependent"
        return "Balanced / Low Risk"

    df["shot_diet_risk_label"] = df.apply(risk_label, axis=1)
    return df


def add_feature_hashes(df: pd.DataFrame, level: str) -> pd.DataFrame:
    df = df.copy()
    df["_feature_run_id"] = RUN_ID
    df["_featured_at_utc"] = utc_now_iso()
    df["_row_content_hash"] = [build_feature_row_hash(row, level=level) for row in df.to_dict(orient="records")]
    return df


# =============================================================================
# FEATURE PIPELINE
# =============================================================================

def add_features(df: pd.DataFrame, level: str) -> pd.DataFrame:
    df = df.copy()
    df = clean_columns(df)
    df = to_numeric_if_possible(df)
    print("=" * 96)
    print(f"ADDING 2026 FEATURES: {level.upper()}")
    print("=" * 96)
    df = add_shot_diet_features(df)
    df = add_core_efficiency_features(df)
    df = add_shotquality_pbp_features(df)
    df = add_sample_flags(df, level)
    df = add_percentiles_and_labels(df, level)
    df = add_feature_hashes(df, level)
    return df


def persist_features(level: str, df: pd.DataFrame) -> Dict:
    if level == "player":
        master_path = PLAYER_FEATURES_MASTER
        latest_csv = PLAYER_FEATURES_LATEST
        latest_json = PLAYER_FEATURES_LATEST_JSON
    else:
        master_path = TEAM_FEATURES_MASTER
        latest_csv = TEAM_FEATURES_LATEST
        latest_json = TEAM_FEATURES_LATEST_JSON

    before, added, after = append_unique_csv(master_path, df)
    overwrite_csv_json(
        latest_csv,
        latest_json,
        df,
        metadata={
            "dataset": f"{level}_features",
            "layer": "features_latest",
            "season": SEASON,
            "season_type": SEASON_TYPE,
            "dedupe_strategy": "features_master appends unique content hashes; features_latest overwrites current feature snapshot",
        },
    )
    print(f"[features:{level}] rows={len(df)} | master before={before} | added={added} | after={after}")
    return {"level": level, "rows": len(df), "master_before": before, "master_added": added, "master_after": after}


# =============================================================================
# LEADERBOARDS
# =============================================================================

def top_table(df: pd.DataFrame, sort_col: str, out_name: str, n: int = 25, ascending: bool = False, min_fga: Optional[int] = None) -> pd.DataFrame:
    table = df.copy()
    if min_fga is not None and "detected_zone_fga_total" in table.columns:
        table = table[pd.to_numeric(table["detected_zone_fga_total"], errors="coerce") >= min_fga]
    if sort_col not in table.columns:
        print(f"[skip leaderboard] missing sort_col={sort_col} for {out_name}")
        return pd.DataFrame()
    table = table.sort_values(sort_col, ascending=ascending).head(n)
    keep_cols = [
        "season", "entity_id_feature", "entity_name_feature", "sample_size_flag", "detected_zone_fga_total",
        "efg_pct_feature", "ts_pct_feature", "points_per_fga_feature", "shotquality_pbp_feature",
        "shot_making_over_shotquality_pbp", "rim_fga_share", "midrange_fga_share", "three_point_fga_share",
        "rim_and_three_fga_share", "shot_diet_diversity_score", "shot_zone_concentration_score",
        "shooting_efficiency_category", "shotquality_pbp_profile_label", "shot_diet_profile_label",
        "specialized_shooter_label", "shot_diet_risk_label",
    ]
    keep_cols = [c for c in keep_cols if c in table.columns]
    table = table[keep_cols].copy()
    table["leaderboard_name"] = out_name
    table["leaderboard_sort_col"] = sort_col
    table["leaderboard_generated_at_utc"] = utc_now_iso()
    table["run_id"] = RUN_ID
    return table


def save_leaderboard(df: pd.DataFrame, filename: str) -> None:
    path = LEADERBOARD_LATEST_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"[leaderboard] {path} | rows={len(df)}")


def build_player_leaderboards(player_df: pd.DataFrame) -> Dict[str, int]:
    outputs: Dict[str, pd.DataFrame] = {
        "player_shotquality_leaders.csv": top_table(player_df, "shotquality_pbp_feature", "player_shotquality_leaders", n=30, min_fga=75),
        "player_shot_making_over_shotquality_leaders.csv": top_table(player_df, "shot_making_over_shotquality_pbp", "player_shot_making_over_shotquality_leaders", n=30, min_fga=75),
        "player_efficiency_leaders.csv": top_table(player_df, "efg_pct_feature", "player_efficiency_leaders", n=30, min_fga=75),
        "player_rim_and_three_leaders.csv": top_table(player_df, "rim_and_three_fga_share", "player_rim_and_three_leaders", n=30, min_fga=75),
        "player_rim_pressure_leaders.csv": top_table(player_df, "rim_fga_share", "player_rim_pressure_leaders", n=30, min_fga=75),
        "player_three_point_volume_leaders.csv": top_table(player_df, "three_point_fga_share", "player_three_point_volume_leaders", n=30, min_fga=75),
        "player_midrange_heavy_profiles.csv": top_table(player_df, "midrange_fga_share", "player_midrange_heavy_profiles", n=30, min_fga=75),
    }

    specialty = player_df.copy()
    if "specialized_shooter_label" in specialty.columns:
        specialty = specialty[specialty["specialized_shooter_label"].notna() & (specialty["specialized_shooter_label"] != "No Clear Shooting Specialty")].copy()
    else:
        specialty = pd.DataFrame()

    outputs["player_specialized_shooter_summary.csv"] = specialty[[
        c for c in ["season", "entity_id_feature", "entity_name_feature", "sample_size_flag", "detected_zone_fga_total", "specialized_shooter_label", "efg_pct_feature", "ts_pct_feature", "shotquality_pbp_feature", "rim_fga_share", "midrange_fga_share", "three_point_fga_share", "rim_and_three_fga_share"] if c in specialty.columns
    ]].copy() if not specialty.empty else pd.DataFrame()

    low_sample = player_df.copy()
    if "sample_size_flag" in low_sample.columns and "efg_pct_feature_percentile" in low_sample.columns:
        low_sample = low_sample[(low_sample["sample_size_flag"] == "Low") & (low_sample["efg_pct_feature_percentile"] >= 0.75)].copy()
    else:
        low_sample = pd.DataFrame()

    outputs["player_low_sample_efficiency_watchlist.csv"] = low_sample[[
        c for c in ["season", "entity_id_feature", "entity_name_feature", "sample_size_flag", "detected_zone_fga_total", "efg_pct_feature", "ts_pct_feature", "shotquality_pbp_feature", "shot_making_over_shotquality_pbp", "specialized_shooter_label", "shot_diet_profile_label"] if c in low_sample.columns
    ]].copy() if not low_sample.empty else pd.DataFrame()

    counts = {}
    for filename, table in outputs.items():
        save_leaderboard(table, filename)
        counts[filename] = len(table)
    return counts


def build_team_leaderboards(team_df: pd.DataFrame) -> Dict[str, int]:
    outputs: Dict[str, pd.DataFrame] = {
        "team_shotquality_leaders.csv": top_table(team_df, "shotquality_pbp_feature", "team_shotquality_leaders", n=20),
        "team_efficiency_leaders.csv": top_table(team_df, "efg_pct_feature", "team_efficiency_leaders", n=20),
        "team_modern_shot_diet_leaders.csv": top_table(team_df, "rim_and_three_fga_share", "team_modern_shot_diet_leaders", n=20),
        "team_three_point_volume_leaders.csv": top_table(team_df, "three_point_fga_share", "team_three_point_volume_leaders", n=20),
    }
    style_cols = [c for c in ["season", "entity_id_feature", "entity_name_feature", "efg_pct_feature", "ts_pct_feature", "points_per_fga_feature", "shotquality_pbp_feature", "shot_making_over_shotquality_pbp", "rim_fga_share", "midrange_fga_share", "three_point_fga_share", "rim_and_three_fga_share", "shot_diet_profile_label", "shot_diet_risk_label", "shooting_efficiency_category"] if c in team_df.columns]
    outputs["team_style_summary.csv"] = team_df[style_cols].copy()
    counts = {}
    for filename, table in outputs.items():
        save_leaderboard(table, filename)
        counts[filename] = len(table)
    return counts


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    ensure_dirs()
    print("=" * 96)
    print("PBPStats WNBA 2026 Feature Panels + Leaderboards")
    print(f"run_id={RUN_ID}")
    print(f"data_root={DATA_ROOT}")
    print("=" * 96)

    player_clean = load_latest_clean(PLAYER_CLEAN_LATEST, "player")
    team_clean = load_latest_clean(TEAM_CLEAN_LATEST, "team")

    player_features = add_features(player_clean, "player")
    team_features = add_features(team_clean, "team")

    feature_results = [persist_features("player", player_features), persist_features("team", team_features)]
    player_leaderboard_counts = build_player_leaderboards(player_features)
    team_leaderboard_counts = build_team_leaderboards(team_features)

    run_summary = {
        "run_id": RUN_ID,
        "season": SEASON,
        "season_type": SEASON_TYPE,
        "generated_at_utc": utc_now_iso(),
        "feature_results": feature_results,
        "player_leaderboards": player_leaderboard_counts,
        "team_leaderboards": team_leaderboard_counts,
    }
    log_path = RUN_LOG_DIR / f"features_{RUN_ID}.json"
    save_json(log_path, run_summary)

    print("=" * 96)
    print("DONE: Features + Leaderboards")
    print(f"Run log: {log_path}")
    print("=" * 96)


if __name__ == "__main__":
    main()
