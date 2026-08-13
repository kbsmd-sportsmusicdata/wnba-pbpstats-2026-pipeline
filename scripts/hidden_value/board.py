"""The role-adjusted residual and the composite watchlist.

"Underrated" only means something relative to a baseline. Here the baseline is what a
player's *situation* predicts: minutes, usage, starts, share of team possessions, and team
quality. Fit impact against those, and the residual is the part of a player's contribution
their situation does not explain -- which is precisely the part a coaching staff or a
reader has not priced in.

The scoring weights lean on signals measured at a player's current *level* rather than on
the direction they have been moving. Held-out testing showed a rising trend predicts
slightly *worse* subsequent production once level is controlled for, so extrapolating it
would rank players on mean reversion pointed the wrong way. See the methodology.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from .features import percentile


def standardize(frame: pd.DataFrame, columns: Sequence[str]) -> Tuple[np.ndarray, List[str]]:
    """Z-score the usable proxies, filling gaps with the column mean."""
    used: List[str] = []
    pieces: List[np.ndarray] = []
    for column in columns:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().sum() < 3:
            continue
        deviation = values.std(ddof=0)
        if not np.isfinite(deviation) or deviation == 0:
            continue
        pieces.append(((values - values.mean()) / deviation).fillna(0.0).to_numpy())
        used.append(column)
    if not pieces:
        return np.empty((len(frame), 0)), []
    return np.column_stack(pieces), used


def fit_role_model(
    panel: pd.DataFrame,
    *,
    impact_column: str,
    proxies: Sequence[str],
    ridge_alpha: float,
) -> Tuple[pd.Series, Dict]:
    """Residual of impact after what role predicts.

    A mild ridge penalty is used because the proxies are strongly collinear -- minutes,
    starts and possession share all measure "how much the coach plays them" -- and an
    unpenalized fit would split that shared signal arbitrarily between them.

    Team strength belongs in the baseline alongside role. Over half a season a shrunk RAPM
    still carries a good deal of the team around a player: measured impact correlates far
    more strongly with team net rating than with any measure of a player's own role. Left
    in, the board simply lists the best teams' rotations. Regressing it out is what makes
    the residual mean "better than their situation explains" -- which is the profile worth
    finding.
    """
    impact = pd.to_numeric(panel.get(impact_column), errors="coerce")
    design, used = standardize(panel, proxies)
    # A proxy named in config that is missing or constant used to vanish without a word,
    # which is how two of five silently dropped out of the first build.
    dropped = [column for column in proxies if column not in used]
    diagnostics: Dict = {
        "impact_column": impact_column,
        "proxies_used": used,
        "proxies_dropped": dropped,
        "ridge_alpha": ridge_alpha,
    }

    trainable = impact.notna().to_numpy()
    if not used or trainable.sum() < len(used) + 2:
        diagnostics["status"] = "insufficient_data"
        return pd.Series(np.nan, index=panel.index), diagnostics

    matrix = np.column_stack([np.ones(len(panel)), design])
    train_x, train_y = matrix[trainable], impact.to_numpy()[trainable]
    penalty = np.eye(matrix.shape[1])
    penalty[0, 0] = 0.0  # never shrink the intercept
    beta = np.linalg.lstsq(train_x.T @ train_x + ridge_alpha * penalty, train_x.T @ train_y, rcond=None)[0]

    predicted = matrix @ beta
    residual = impact - predicted

    explained = float(np.corrcoef(train_y, predicted[trainable])[0, 1] ** 2) if trainable.sum() > 2 else np.nan
    diagnostics.update(
        {
            "status": "fitted",
            "players_fitted": int(trainable.sum()),
            "r_squared": round(explained, 4) if np.isfinite(explained) else None,
            "coefficients": {name: round(float(value), 4) for name, value in zip(used, beta[1:])},
        }
    )
    return residual, diagnostics


def build_board(
    panel: pd.DataFrame,
    *,
    weights: Dict[str, float],
    labels: Dict,
) -> pd.DataFrame:
    """Score, rank and split the watchlist into its two tracks."""
    if panel.empty:
        return panel

    board = panel.copy()
    board["role_residual_score"] = percentile(board.get("role_residual"))
    board["trajectory_score"] = percentile(board.get("trajectory_raw"))
    board["playoff_fit_score"] = percentile(board.get("playoff_fit"))
    board["volatility_score"] = percentile(board.get("volatility_raw"), higher_is_better=False)

    components = {
        "role_residual": board["role_residual_score"],
        "trajectory": board["trajectory_score"],
        "regression_upside": board.get("regression_upside_score"),
        "playoff_fit": board["playoff_fit_score"],
    }
    total = 0.0
    weighted = pd.Series(0.0, index=board.index)
    for name, series in components.items():
        weight = float(weights.get(name, 0.0))
        if weight <= 0 or series is None:
            continue
        weighted += pd.to_numeric(series, errors="coerce").fillna(50.0) * weight
        total += weight

    penalty_weight = float(weights.get("volatility_penalty", 0.0))
    if penalty_weight > 0:
        weighted += board["volatility_score"].fillna(50.0) * penalty_weight
        total += penalty_weight

    board["hidden_value_score"] = weighted / total if total else np.nan

    # Two tracks rather than one blended ranking, naming whichever signal carries a
    # player's case. "Recent Form" is deliberately descriptive: held-out testing on this
    # season showed the trend does not forecast what comes next, so the label must not
    # imply that it does.
    residual_rank = board["role_residual_score"].rank(ascending=False)
    trajectory_rank = board["trajectory_score"].rank(ascending=False)
    board["board_track"] = np.where(
        residual_rank <= trajectory_rank, "Underrated Now", "Recent Form"
    )

    strong = float(labels.get("strong_percentile", 0.85))
    moderate = float(labels.get("moderate_percentile", 0.70))
    score_percentile = board["hidden_value_score"].rank(pct=True)
    board["conviction"] = np.select(
        [score_percentile >= strong, score_percentile >= moderate],
        ["Strong", "Moderate"],
        default="Monitor",
    )
    # A low-sample player can top the board on noise; say so rather than hide it.
    board.loc[board.get("sample_flag").eq("Low sample"), "conviction"] = board.loc[
        board.get("sample_flag").eq("Low sample"), "conviction"
    ].map({"Strong": "Moderate", "Moderate": "Monitor", "Monitor": "Monitor"})

    board["watchlist_note"] = board.apply(_note, axis=1)
    board = board.sort_values("hidden_value_score", ascending=False).reset_index(drop=True)
    board.insert(1, "hidden_value_rank", np.arange(1, len(board) + 1))
    return board


def _note(row: pd.Series) -> str:
    """A one-line reason, so the ranking is readable without the component columns."""
    reasons: List[str] = []
    if pd.notna(row.get("role_residual_score")) and row["role_residual_score"] >= 75:
        reasons.append("out-produces their role")
    if pd.notna(row.get("trajectory_score")) and row["trajectory_score"] >= 75:
        reasons.append("recent form rising (descriptive, not a forecast)")
    if pd.notna(row.get("regression_upside_score")) and row["regression_upside_score"] >= 75:
        reasons.append("shot quality ahead of results")
    if pd.notna(row.get("playoff_fit_score")) and row["playoff_fit_score"] >= 75:
        reasons.append("skills scale to playoff basketball")
    if pd.notna(row.get("on_court_poss_share_slope")) and row["on_court_poss_share_slope"] > 0:
        # The one trend that does persist, though it predicts opportunity, not production.
        reasons.append("role expanding")
    if not reasons:
        reasons.append("balanced profile, no single standout signal")
    return f"{row.get('board_track')}: " + ", ".join(reasons)


def build_component_long(board: pd.DataFrame) -> pd.DataFrame:
    """Long-format component scores, ready to plot."""
    score_columns = [
        "role_residual_score",
        "trajectory_score",
        "regression_upside_score",
        "playoff_fit_score",
        "volatility_score",
    ]
    present = [column for column in score_columns if column in board.columns]
    if board.empty or not present:
        return pd.DataFrame(columns=["player_id", "player_name", "component", "score"])
    return board.melt(
        id_vars=[c for c in ["player_id", "player_name", "team_abbreviation", "hidden_value_rank"] if c in board.columns],
        value_vars=present,
        var_name="component",
        value_name="score",
    ).sort_values(["hidden_value_rank", "component"]).reset_index(drop=True)
