"""Core engine that turns cumulative snapshot archives into a game-window panel.

The PBPStats master files hold one row per entity per daily pull, and every row is a
season-to-date cumulative total. Differencing consecutive snapshots for a single entity
recovers what happened *between* those snapshots, which restores a time dimension the
season-total feeds do not otherwise expose.

Three classes of column need different treatment:

* Additive counting columns (points, possessions, attempts) diff directly.
* Ratio columns (eFG%, shot quality, on/off ratings) cannot be differenced. Where a
  cumulative average is paired with a cumulative weight, the window average is recovered
  as ``(avg_t * w_t - avg_{t-1} * w_{t-1}) / (w_t - w_{t-1})``.
* Everything else (labels, percentiles, identifiers) is carried or dropped.

Upstream restatements are a fact of life with a live feed: on 2026-08-07 the WNBA 2026
archive re-stated ``seconds_played`` league-wide by roughly 3.4x and cleared a backlog of
negative values. Rather than hard-coding that date, the engine detects both negative
diffs and league-wide scale breaks, and invalidates only the affected column/window pairs.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd


NEGATIVE_TOLERANCE = 1e-6

#: Columns matching any of these patterns are rates, labels or derived features rather
#: than additive counting stats, so they are never differenced.
NON_ADDITIVE_PATTERNS: Tuple[str, ...] = (
    r"_pct$",
    r"_pct_",
    r"_apct$",
    r"_apct_",
    r"_frequency$",
    r"_accuracy$",
    r"_share$",
    r"_score$",
    r"_percentile$",
    r"_label$",
    r"_category$",
    r"_flag$",
    r"_source$",
    r"_feature$",
    r"_rate$",
    r"_afrequency$",
    r"^avg",
    r"^pace$",
    r"^usage$",
    r"^on_off_rtg$",
    r"^on_def_rtg$",
    r"^shotquality",
    r"^shot_making",
    r"^seconds_per_poss",
    r"^seconds_excluding_orebs_per_poss",
)

#: Identifier and provenance columns that are carried through or ignored.
METADATA_COLUMNS = frozenset(
    {
        "entity_id",
        "team_id",
        "name",
        "short_name",
        "row_id",
        "team_abbreviation",
        "dataset",
        "league",
        "season",
        "season_type",
        "dataset_clean",
        "feature_level",
        "team_id_clean",
        "team_name_clean",
        "player_id_clean",
        "player_name_clean",
        "entity_id_feature",
        "entity_name_feature",
        "source_endpoint",
        "source_params_json",
        "run_id",
        "fetched_at_utc",
        "row_content_hash",
        "source_response_keys",
        "single_row_table_data_json",
    }
)

#: Additive columns that are signed and therefore legitimately decrease between snapshots.
#: They are differenced like any other counting stat but are exempt from the monotonicity
#: checks, which would otherwise read every losing stretch as a source restatement.
SIGNED_ADDITIVE_COLUMNS = frozenset({"plus_minus"})

#: Weight columns that are computed from additive components rather than read directly.
WEIGHT_BUILDERS: Dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "fga": lambda df: _numeric(df, "fg2_a") + _numeric(df, "fg3_a"),
    "missed_fga": lambda df: (_numeric(df, "fg2_a") + _numeric(df, "fg3_a"))
    - (_numeric(df, "fg2_m") + _numeric(df, "fg3_m")),
}


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def safe_divide(numerator, denominator) -> np.ndarray:
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(pd.notna(denominator) & (denominator != 0), numerator / denominator, np.nan)


def display_column_name(column: str) -> str:
    """Render an internal weighted-average helper column under its source column name."""
    if column.startswith("__wavg_num__"):
        return f"{column[len('__wavg_num__'):]} (weighted-average numerator)"
    if column.startswith("__wavg_den__"):
        return f"{column[len('__wavg_den__'):]} (weighted-average weight)"
    return column


def restatement_check_columns(panel: pd.DataFrame, additive_columns: Sequence[str]) -> List[str]:
    """Columns to screen for restatements: the additive stats plus the reconstruction inputs."""
    helpers = [c for c in panel.columns if c.startswith("__wavg_")]
    return [c for c in additive_columns if c in panel.columns] + helpers


def is_additive_column(column: str) -> bool:
    """Return True when a column is an additive counting stat safe to difference."""
    if column in METADATA_COLUMNS or column.startswith("_"):
        return False
    return not any(re.search(pattern, column) for pattern in NON_ADDITIVE_PATTERNS)


def classify_additive_columns(df: pd.DataFrame) -> List[str]:
    """Select the numeric, additive columns of a cumulative snapshot frame."""
    additive: List[str] = []
    for column in df.columns:
        if not is_additive_column(column):
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        if values.notna().any():
            additive.append(column)
    return additive


def build_weight_series(df: pd.DataFrame, weight: str) -> pd.Series:
    """Resolve a weight reference to a cumulative series, computing it when needed."""
    if weight in WEIGHT_BUILDERS:
        return WEIGHT_BUILDERS[weight](df)
    return _numeric(df, weight)


def _prepare_master(
    master: pd.DataFrame,
    *,
    entity_column: str,
    timestamp_column: str,
) -> pd.DataFrame:
    df = master.copy()
    df[timestamp_column] = pd.to_datetime(df[timestamp_column], errors="coerce", utc=True)
    df = df.dropna(subset=[timestamp_column, entity_column])
    df[entity_column] = df[entity_column].astype(str)
    df = df.sort_values([entity_column, timestamp_column])
    # A re-run of the feature builder can emit two rows for the same entity and instant.
    # The later row supersedes the earlier one.
    return df.drop_duplicates(subset=[entity_column, timestamp_column], keep="last")


def screen_snapshot_integrity(
    df: pd.DataFrame,
    additive_columns: Sequence[str],
    *,
    entity_column: str,
    timestamp_column: str,
    max_out_of_envelope_share: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Quarantine whole snapshots that the source published in a corrupt state.

    A cumulative total must sit between its neighbours in time. When a large share of
    additive columns break that envelope on the same snapshot for most entities, the pull
    itself is damaged rather than any single stat -- the WNBA 2026 archive has one such
    snapshot (2026-06-03T18:58:03Z) where a column shift moved values into adjacent fields.

    Column-level invalidation is the wrong remedy there: a shifted row can leave a field
    holding a plausible-looking number that belongs to a different stat. The whole snapshot
    is dropped instead, and the surrounding windows simply bridge across it, so no games
    are lost.

    Snapshots are removed one at a time, worst first, because a corrupt snapshot also sits
    inside its neighbours' envelopes and drags them out of range. Re-screening after each
    removal lets those neighbours clear once the real offender is gone.
    """
    monotone_columns = [
        c for c in additive_columns if c in df.columns and c not in SIGNED_ADDITIVE_COLUMNS
    ]
    if df.empty or not monotone_columns:
        return df, pd.DataFrame()

    working = df
    events: List[Dict[str, Any]] = []
    max_rounds = max(1, working[timestamp_column].nunique() // 4)

    for _ in range(max_rounds):
        scores = _envelope_scores(
            working,
            monotone_columns,
            entity_column=entity_column,
            timestamp_column=timestamp_column,
        )
        if scores.empty:
            break
        worst = scores.iloc[0]
        if worst["out_of_envelope_share"] <= max_out_of_envelope_share:
            break
        events.append(dict(worst))
        working = working[working[timestamp_column] != worst["snapshot_utc"]].copy()

    return working, pd.DataFrame(events)


def _envelope_scores(
    df: pd.DataFrame,
    monotone_columns: Sequence[str],
    *,
    entity_column: str,
    timestamp_column: str,
) -> pd.DataFrame:
    """Score each snapshot by the share of cumulative columns that break monotonicity."""
    shares: Dict[Any, List[float]] = {}
    for _, group in df.groupby(entity_column, sort=False):
        if len(group) < 3:
            continue
        values = group[list(monotone_columns)].apply(pd.to_numeric, errors="coerce").reset_index(drop=True)
        previous, following = values.shift(1), values.shift(-1)
        lower = np.minimum(previous, following)
        upper = np.maximum(previous, following)
        out_of_envelope = (
            ((values < lower - NEGATIVE_TOLERANCE) | (values > upper + NEGATIVE_TOLERANCE))
            & previous.notna()
            & following.notna()
        )
        for position, stamp in enumerate(group[timestamp_column].reset_index(drop=True)):
            shares.setdefault(stamp, []).append(float(out_of_envelope.iloc[position].mean()))

    if not shares:
        return pd.DataFrame()

    return pd.DataFrame(
        [
            {
                "snapshot_utc": stamp,
                "out_of_envelope_share": round(float(np.mean(values)), 6),
                "entities_screened": len(values),
                "columns_screened": len(monotone_columns),
            }
            for stamp, values in shares.items()
        ]
    ).sort_values("out_of_envelope_share", ascending=False).reset_index(drop=True)


def _entity_windows(
    group: pd.DataFrame,
    *,
    entity_column: str,
    timestamp_column: str,
    games_column: str,
    additive_columns: Sequence[str],
    weighted_average_specs: Sequence[Dict[str, Any]],
    emit_baseline_block: bool,
) -> pd.DataFrame:
    values = group[list(additive_columns)].apply(pd.to_numeric, errors="coerce")

    # Numerator/weight pairs let a cumulative average be re-expressed as an additive
    # quantity, which can then be differenced like any other counting stat.
    extras: Dict[str, pd.Series] = {}
    for spec in weighted_average_specs:
        column = spec["column"]
        if column not in group.columns:
            continue
        weights = build_weight_series(group, spec["weight"])
        extras[f"__wavg_num__{column}"] = pd.to_numeric(group[column], errors="coerce") * weights
        extras[f"__wavg_den__{column}"] = weights
    if extras:
        values = pd.concat([values, pd.DataFrame(extras, index=group.index)], axis=1)

    deltas = values.diff()
    if emit_baseline_block:
        # The first snapshot is itself a completed block of games (everything played
        # before the archive started), so it is emitted as window 0 rather than dropped.
        deltas.iloc[0] = values.iloc[0]
    else:
        deltas = deltas.iloc[1:]

    panel = deltas.reset_index(drop=True)
    stamps = group[timestamp_column].reset_index(drop=True)
    panel.insert(0, "entity_id", group[entity_column].iloc[0])
    panel["window_index"] = np.arange(len(panel)) + (0 if emit_baseline_block else 1)
    panel["is_baseline_block"] = False
    if emit_baseline_block:
        panel.loc[0, "is_baseline_block"] = True

    start_stamps = stamps.shift(1)
    if emit_baseline_block:
        panel["window_start_utc"] = start_stamps.values
        panel["window_end_utc"] = stamps.values
    else:
        panel["window_start_utc"] = start_stamps.iloc[1:].reset_index(drop=True).values
        panel["window_end_utc"] = stamps.iloc[1:].reset_index(drop=True).values

    panel["snapshot_span_days"] = (
        pd.to_datetime(panel["window_end_utc"], utc=True) - pd.to_datetime(panel["window_start_utc"], utc=True)
    ).dt.total_seconds() / 86400.0

    cumulative_games = pd.to_numeric(group[games_column], errors="coerce").reset_index(drop=True)
    if not emit_baseline_block:
        cumulative_games = cumulative_games.iloc[1:].reset_index(drop=True)
    panel["cumulative_games_played"] = cumulative_games.values
    panel["games_in_window"] = pd.to_numeric(panel.get(games_column), errors="coerce")

    for carry in ("name", "team_abbreviation", "team_id"):
        if carry in group.columns:
            series = group[carry].reset_index(drop=True)
            if not emit_baseline_block:
                series = series.iloc[1:].reset_index(drop=True)
            panel[carry] = series.values

    if "team_abbreviation" in group.columns:
        teams = group["team_abbreviation"].reset_index(drop=True)
        changed = teams.ne(teams.shift(1))
        changed.iloc[0] = False
        if not emit_baseline_block:
            changed = changed.iloc[1:].reset_index(drop=True)
        panel["team_changed_in_window"] = changed.values

    return panel


def build_window_frame(
    master: pd.DataFrame,
    *,
    config: Dict[str, Any],
    level: str,
) -> Tuple[pd.DataFrame, List[str], List[Dict[str, Any]], pd.DataFrame]:
    """Difference a cumulative snapshot archive into one row per entity per game window.

    Returns the raw window frame, the list of additive columns that were differenced, the
    weighted-average specs that were applied, and the quarantined-snapshot report.
    """
    panel_config = config.get("panel", {})
    detection = config.get("restatement_detection", {})
    entity_column = panel_config.get("entity_column", "entity_id")
    timestamp_column = panel_config.get("timestamp_column", "_featured_at_utc")
    games_column = panel_config.get("games_played_column", "games_played")
    emit_baseline_block = bool(panel_config.get("emit_baseline_block", True))
    specs = list(config.get("weighted_averages", {}).get(level, []))
    empty_report = pd.DataFrame()

    if master.empty or entity_column not in master.columns or timestamp_column not in master.columns:
        return pd.DataFrame(), [], specs, empty_report

    df = _prepare_master(master, entity_column=entity_column, timestamp_column=timestamp_column)
    if df.empty:
        return pd.DataFrame(), [], specs, empty_report

    additive_columns = classify_additive_columns(df)
    if games_column not in additive_columns:
        additive_columns.append(games_column)

    df, quarantine_report = screen_snapshot_integrity(
        df,
        additive_columns,
        entity_column=entity_column,
        timestamp_column=timestamp_column,
        max_out_of_envelope_share=float(detection.get("max_out_of_envelope_share", 0.02)),
    )
    if df.empty:
        return pd.DataFrame(), additive_columns, specs, quarantine_report

    frames = [
        _entity_windows(
            group,
            entity_column=entity_column,
            timestamp_column=timestamp_column,
            games_column=games_column,
            additive_columns=additive_columns,
            weighted_average_specs=specs,
            emit_baseline_block=emit_baseline_block,
        )
        for _, group in df.groupby(entity_column, sort=True)
    ]
    if not frames:
        return pd.DataFrame(), additive_columns, specs, quarantine_report

    panel = pd.concat(frames, ignore_index=True)
    return panel, additive_columns, specs, quarantine_report


def detect_restatements(
    panel: pd.DataFrame,
    additive_columns: Sequence[str],
    *,
    ratio_threshold: float,
    entity_share_threshold: float,
    min_history_windows: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Invalidate window values that a source restatement made meaningless.

    Two failure modes are handled:

    * A negative delta means the feed revised a cumulative total downward, so the window
      value for that entity and column is not a real observation.
    * A league-wide scale break (the same column jumping by an implausible multiple for a
      large share of entities on the same snapshot) means the feed re-based the column.

    Only the affected column/window pairs are set to NaN; every other column in the same
    row remains usable.
    """
    if panel.empty:
        return panel, pd.DataFrame()

    cleaned = panel.copy()
    events: List[Dict[str, Any]] = []
    body_mask = ~cleaned["is_baseline_block"].astype(bool)
    games = pd.to_numeric(cleaned["games_in_window"], errors="coerce")

    for column in additive_columns:
        if column not in cleaned.columns or column in SIGNED_ADDITIVE_COLUMNS:
            continue
        values = pd.to_numeric(cleaned[column], errors="coerce")

        negative_mask = body_mask & (values < -NEGATIVE_TOLERANCE)
        if negative_mask.any():
            events.append(
                {
                    "column": display_column_name(column),
                    "issue": "negative_delta",
                    "windows_invalidated": int(negative_mask.sum()),
                    "entities_affected": int(cleaned.loc[negative_mask, "entity_id"].nunique()),
                    "first_window_end_utc": cleaned.loc[negative_mask, "window_end_utc"].min(),
                    "last_window_end_utc": cleaned.loc[negative_mask, "window_end_utc"].max(),
                    "detail": "Cumulative total was revised downward by the source.",
                }
            )

        per_game = pd.Series(safe_divide(values, games), index=cleaned.index)
        eligible = body_mask & per_game.notna()
        scale_break_mask = pd.Series(False, index=cleaned.index)
        if eligible.sum() >= min_history_windows:
            entities = cleaned["entity_id"].where(eligible)
            medians = per_game.where(eligible).groupby(entities).transform("median")
            counts = per_game.where(eligible).groupby(entities).transform("count")
            outlier = (
                eligible
                & (counts >= min_history_windows)
                & medians.abs().gt(0)
                & per_game.abs().gt(ratio_threshold * medians.abs())
            )
            if outlier.any():
                # A restatement hits the whole league at once; a single hot game does not.
                share = outlier.where(eligible).groupby(cleaned["window_end_utc"].where(eligible)).transform("mean")
                scale_break_mask = eligible & outlier & share.ge(entity_share_threshold)

        if scale_break_mask.any():
            boundaries = sorted(cleaned.loc[scale_break_mask, "window_end_utc"].astype(str).unique())
            # The re-based value contaminates the whole snapshot, not just the outliers.
            boundary_mask = body_mask & cleaned["window_end_utc"].astype(str).isin(boundaries)
            scale_break_mask = boundary_mask
            events.append(
                {
                    "column": display_column_name(column),
                    "issue": "league_wide_scale_break",
                    "windows_invalidated": int(boundary_mask.sum()),
                    "entities_affected": int(cleaned.loc[boundary_mask, "entity_id"].nunique()),
                    "first_window_end_utc": min(boundaries),
                    "last_window_end_utc": max(boundaries),
                    "detail": (
                        "Column was re-based by the source at "
                        f"{', '.join(boundaries)}; window deltas across that boundary are not comparable."
                    ),
                }
            )

        invalid = negative_mask | scale_break_mask
        if invalid.any():
            cleaned.loc[invalid, column] = np.nan

    qa = pd.DataFrame(events)
    if not qa.empty:
        qa = qa.sort_values(["issue", "windows_invalidated"], ascending=[True, False]).reset_index(drop=True)
    return cleaned, qa


def apply_weighted_averages(panel: pd.DataFrame, specs: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """Recover per-window averages from the differenced numerator/weight pairs."""
    if panel.empty:
        return panel

    df = panel.copy()
    for spec in specs:
        column = spec["column"]
        numerator = f"__wavg_num__{column}"
        denominator = f"__wavg_den__{column}"
        if numerator not in df.columns or denominator not in df.columns:
            continue
        df[column] = safe_divide(df[numerator], df[denominator])
        df[f"{column}_weight"] = pd.to_numeric(df[denominator], errors="coerce")

    return df.drop(columns=[c for c in df.columns if c.startswith("__wavg_")])


def add_covered_game_dates(panel: pd.DataFrame) -> pd.DataFrame:
    """Label each window with the inclusive range of game dates it contains.

    The daily pull runs mid-morning UTC, so a snapshot stamped on date D reflects games
    played through D-1 in the league's local calendar. A window running from snapshot S to
    snapshot E therefore covers game dates ``[S_date, E_date)``. Validated against ESPN box
    scores: all 297 single-game windows in the 2026 archive match on team and opponent
    points under this attribution.
    """
    if panel.empty:
        return panel

    df = panel.copy()
    start = pd.to_datetime(df["window_start_utc"], errors="coerce", utc=True)
    end = pd.to_datetime(df["window_end_utc"], errors="coerce", utc=True)
    df["covered_game_date_start"] = start.dt.date
    df["covered_game_date_end"] = (end - pd.Timedelta(days=1)).dt.date
    return df


def finalize_panel(
    panel: pd.DataFrame,
    *,
    min_games_in_window: int,
    identifier_columns: Sequence[str],
) -> pd.DataFrame:
    """Drop empty windows and order columns for readability."""
    if panel.empty:
        return panel

    df = add_covered_game_dates(panel)
    games = pd.to_numeric(df["games_in_window"], errors="coerce")
    df = df[games.fillna(0) >= min_games_in_window].copy()
    df = df.sort_values(["entity_id", "window_index"]).reset_index(drop=True)

    leading = [c for c in identifier_columns if c in df.columns]
    remaining = [c for c in df.columns if c not in leading]
    return df[leading + remaining]
