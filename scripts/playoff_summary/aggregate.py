"""Pure aggregation transforms for the playoff summary. No network, no filesystem.

Turns the per-game playoff (and regular-season) game layer into per-entity descriptive splits:
counting stats summed and expressed **per 100 possessions**, rate stats possession-weighted, the
headline shooting rates recomputed from summed components (never averaged across games), and a
regular-season-vs-playoff delta table. Sample size rides on every row and nothing is dropped.
"""

from __future__ import annotations

from typing import List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


# Identity / game-context columns: never aggregated as stats.
_META = {
    "season", "season_type", "game_id", "game_date",
    "player_id", "player_name", "team_id", "team_name", "team_abbreviation",
    "opponent_team_id", "opponent_team_abbreviation", "is_home",
}
# Handled explicitly (not via the generic counting path).
_EXPLICIT = {"minutes", "win", "off_poss", "def_poss", "total_poss"}
# Game-context totals that are summable but whose per-100 is meaningless: keep total + per-game.
_CONTEXT = {"team_points", "opponent_points", "margin", "team_possessions", "opponent_possessions", "plus_minus"}

# Tokens that mark a column as an already-computed rate/ratio (so it is possession-weighted, not
# summed). Matched against the underscore-split column name, e.g. ``ts_pct`` -> {"ts","pct"}.
_RATE_TOKENS = {"pct", "apct", "accuracy", "frequency", "rtg", "distance"}
_RATE_EXACT = {"usage", "pace"}


def is_rate(col: str) -> bool:
    """True when the column is an already-computed rate/ratio (averaged, never summed)."""
    if col in _RATE_EXACT:
        return True
    if col.startswith("seconds"):  # seconds_per_poss_*, seconds_excluding_orebs_per_poss_*
        return True
    if "shot_quality_avg" in col:
        return True
    return any(token in _RATE_TOKENS for token in col.split("_"))


def _numeric(frame: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    return frame[list(cols)].apply(pd.to_numeric, errors="coerce")


def _classify(columns: Sequence[str]) -> dict:
    counting, rate, context = [], [], []
    for col in columns:
        if col in _META or col in _EXPLICIT:
            continue
        if col in _CONTEXT:
            context.append(col)
        elif is_rate(col):
            rate.append(col)
        else:
            counting.append(col)
    return {"counting": counting, "rate": rate, "context": context}


def _derived_shooting_rates(totals: pd.DataFrame) -> pd.DataFrame:
    """Recompute headline shooting rates from summed components (not averaged per-game).

    Averaging per-game percentages weights a 3-shot night the same as a 20-shot night, so the
    board's shooting rates are rebuilt from the summed makes/attempts instead.
    """
    out = pd.DataFrame(index=totals.index)

    def col(name: str) -> pd.Series:
        return pd.to_numeric(totals[name], errors="coerce") if name in totals else pd.Series(0.0, index=totals.index)

    fgm = col("fg2_m_total") + col("fg3_m_total")
    fga = col("fg2_a_total") + col("fg3_a_total")
    fta = col("fta_total")
    pts = col("points_total")
    fg3m, fg3a = col("fg3_m_total"), col("fg3_a_total")

    with np.errstate(divide="ignore", invalid="ignore"):
        ts_denom = 2.0 * (fga + 0.44 * fta)
        out["ts_pct_derived"] = np.where(ts_denom > 0, pts / ts_denom, np.nan)
        out["efg_pct_derived"] = np.where(fga > 0, (fgm + 0.5 * fg3m) / fga, np.nan)
        out["fg_pct_derived"] = np.where(fga > 0, fgm / fga, np.nan)
        out["fg3_pct_derived"] = np.where(fg3a > 0, fg3m / fg3a, np.nan)
    return out


def aggregate_entity(
    df: pd.DataFrame, *, id_col: str, name_cols: Sequence[str], min_games: int
) -> pd.DataFrame:
    """One row per entity (player or team): summed counting stats as per-100, weighted rates.

    Output columns: identity (+ the entity's most recent team in the sample), ``games``/``wins``/
    ``losses``/``meets_min_games``, minutes and possession totals, ``<c>_total`` and ``<c>_per100``
    for every counting stat, each rate column as a possession-weighted mean, ``<c>_total`` and
    ``<c>_per_game`` for game-context columns, and the derived headline shooting rates.
    """
    if df.empty:
        return pd.DataFrame()

    key = df[id_col]
    groups = df.groupby(id_col, sort=True)
    kinds = _classify(df.columns)
    games = groups.size().rename("games")
    total_poss_sum = (
        _numeric(df, ["total_poss"]).assign(**{id_col: key}).groupby(id_col)["total_poss"].sum()
        if "total_poss" in df.columns else pd.Series(0.0, index=games.index)
    )
    # Per-100 counting rates are per 100 **offensive** possessions. pbpstats ``total_poss`` is
    # offensive + defensive, so using it as the denominator would halve every rate (PTS/100 ~52
    # instead of ~105). Rate columns are still weighted by total on-court possessions.
    off_poss_sum = (
        _numeric(df, ["off_poss"]).assign(**{id_col: key}).groupby(id_col)["off_poss"].sum()
        if "off_poss" in df.columns else total_poss_sum
    )
    per100_denom = off_poss_sum.replace(0, np.nan)
    weight_denom = total_poss_sum.replace(0, np.nan)

    # Assemble every block as a frame indexed by entity id, then concat once (no fragmentation).
    blocks: List[pd.DataFrame] = []

    # Identity: the entity's most recent row in the sample (trade-safe team attribution).
    last = df.sort_values("game_date").groupby(id_col).tail(1).set_index(id_col)
    ident_cols = [c for c in ("season", "season_type", *name_cols) if c in last.columns]
    blocks.append(last[ident_cols])

    scalars = pd.DataFrame(index=games.index)
    scalars["games"] = games
    if "win" in df.columns:
        wins = df.assign(_w=df["win"].fillna(False).astype(bool)).groupby(id_col)["_w"].sum()
        scalars["wins"] = wins.astype(int)
        scalars["losses"] = (games - wins).astype(int)
    scalars["meets_min_games"] = games >= int(min_games)
    if "minutes" in df.columns:
        minutes = _numeric(df, ["minutes"]).assign(**{id_col: key}).groupby(id_col)["minutes"].sum()
        scalars["minutes_total"] = minutes
        scalars["minutes_per_game"] = minutes / games
    blocks.append(scalars)

    poss_present = [c for c in ("off_poss", "def_poss", "total_poss") if c in df.columns]
    if poss_present:
        poss_sums = _numeric(df, poss_present).assign(**{id_col: key}).groupby(id_col).sum()
        blocks.append(poss_sums.add_suffix("_total"))

    # Counting stats: sum -> total + per-100 (on summed total possessions).
    if kinds["counting"]:
        csum = _numeric(df, kinds["counting"]).assign(**{id_col: key}).groupby(id_col).sum()
        blocks.append(csum.add_suffix("_total"))
        blocks.append((csum.div(per100_denom, axis=0) * 100.0).add_suffix("_per100"))

    # Game-context: total + per-game (per-100 would be meaningless here).
    if kinds["context"]:
        xsum = _numeric(df, kinds["context"]).assign(**{id_col: key}).groupby(id_col).sum()
        blocks.append(xsum.add_suffix("_total"))
        blocks.append(xsum.div(games, axis=0).add_suffix("_per_game"))

    # Rate stats: possession-weighted mean across games.
    if kinds["rate"]:
        weighted = _numeric(df, kinds["rate"]).mul(pd.to_numeric(df["total_poss"], errors="coerce"), axis=0)
        wsum = weighted.assign(**{id_col: key}).groupby(id_col).sum()
        blocks.append(wsum.div(weight_denom, axis=0))

    out = pd.concat(blocks, axis=1)
    out = pd.concat([out, _derived_shooting_rates(out)], axis=1)
    out.index.name = id_col
    return out.reset_index().sort_values(id_col).reset_index(drop=True)


def comparable_metric_columns(agg: pd.DataFrame) -> List[str]:
    """Columns that compare across differently-sized samples: per-100 rates, rate means, derived
    shooting rates, and per-game context -- never raw ``_total`` volumes."""
    cols = []
    for col in agg.columns:
        if col.endswith("_per100") or col.endswith("_per_game") or col.endswith("_derived"):
            cols.append(col)
        elif col not in _META and col not in {"games", "wins", "losses", "meets_min_games"} and is_rate(col):
            cols.append(col)
    return cols


def rs_vs_playoff_deltas(
    rs_agg: pd.DataFrame, po_agg: pd.DataFrame, *, id_col: str, name_cols: Sequence[str]
) -> pd.DataFrame:
    """Players/teams present in both samples: regular-season rate, playoff rate, and the delta.

    Only comparable (per-100 / rate / per-game) columns are differenced -- raw volume totals are
    not comparable across a 40-game season and a short playoff run. ``rs_games``/``playoff_games``
    and the playoff ``meets_min_games`` flag ride on every row so the sample is always visible.
    """
    if rs_agg.empty or po_agg.empty:
        return pd.DataFrame()

    metrics = [c for c in comparable_metric_columns(po_agg) if c in rs_agg.columns]
    rs = rs_agg.set_index(id_col)
    po = po_agg.set_index(id_col)
    common = [eid for eid in po.index if eid in rs.index]

    records = []
    for eid in common:
        rec = {id_col: eid}
        for nc in name_cols:
            if nc in po.columns:
                rec[nc] = po.loc[eid, nc]
        rec["rs_games"] = int(rs.loc[eid, "games"])
        rec["playoff_games"] = int(po.loc[eid, "games"])
        rec["meets_min_games"] = bool(po.loc[eid, "meets_min_games"])
        for col in metrics:
            rs_val, po_val = rs.loc[eid, col], po.loc[eid, col]
            rec[f"{col}_rs"] = rs_val
            rec[f"{col}_playoff"] = po_val
            if pd.notna(rs_val) and pd.notna(po_val):
                rec[f"{col}_delta"] = po_val - rs_val
            else:
                rec[f"{col}_delta"] = np.nan
        records.append(rec)
    return pd.DataFrame(records).sort_values(id_col).reset_index(drop=True)
