"""Ridge-regularized adjusted plus-minus over possessions.

Each possession contributes one observation: points per 100, regressed on the ten players
on the floor. Ridge is what makes the estimate meaningful -- WNBA rotations are short, so
teammates appear together constantly and the unpenalized solution would be wildly
collinear. The penalty pulls every player toward the league average, and how hard it pulls
is chosen by cross-validation rather than assumed.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

#: Intercept and home-court columns are nuisance terms, not player effects, so they are
#: estimated without shrinkage.
UNPENALIZED_COLUMNS = 2


def solve_ridge(gram: np.ndarray, moment: np.ndarray, alpha: float) -> np.ndarray:
    """Solve (X'X + alpha*P) b = X'y, leaving the nuisance columns unpenalized.

    The nuisance columns carry no penalty, so the system is singular whenever one of them
    is degenerate -- which happens for real when the play-by-play is unavailable and the
    home-court column is constant. A least-squares fallback keeps the run alive and returns
    the minimum-norm solution instead of crashing on a missing optional source.
    """
    penalty = np.eye(gram.shape[0])
    penalty[:UNPENALIZED_COLUMNS, :UNPENALIZED_COLUMNS] = 0.0
    system = gram + alpha * penalty
    try:
        return np.linalg.solve(system, moment)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(system, moment, rcond=None)[0]


def game_folds(game_ids: Sequence, folds: int, seed: int) -> np.ndarray:
    """Assign folds by game so possessions from one game never straddle the split.

    Possessions within a game share lineups and context; splitting them at random would
    leak information into the held-out set and flatter every alpha equally.
    """
    games = pd.unique(pd.Series(game_ids))
    generator = np.random.default_rng(seed)
    assignment = {game: index % folds for index, game in enumerate(generator.permutation(games))}
    return pd.Series(game_ids).map(assignment).to_numpy()


def cross_validate_alpha(
    matrix: np.ndarray,
    response: np.ndarray,
    game_ids: Sequence,
    *,
    alpha_grid: Sequence[float],
    folds: int,
    seed: int,
) -> Tuple[float, pd.DataFrame]:
    """Pick the penalty that predicts held-out possessions best.

    The full cross-product is computed once and each fold's contribution subtracted from
    it, which is far cheaper than rebuilding it per fold.
    """
    fold_ids = game_folds(game_ids, folds, seed)
    gram_full = matrix.T @ matrix
    moment_full = matrix.T @ response

    rows: List[Dict[str, float]] = []
    for alpha in alpha_grid:
        squared_error = 0.0
        count = 0
        for fold in range(folds):
            held_out = fold_ids == fold
            if not held_out.any() or held_out.all():
                continue
            matrix_out = matrix[held_out]
            response_out = response[held_out]
            gram_train = gram_full - matrix_out.T @ matrix_out
            moment_train = moment_full - matrix_out.T @ response_out
            beta = solve_ridge(gram_train, moment_train, float(alpha))
            residual = response_out - matrix_out @ beta
            squared_error += float(residual @ residual)
            count += len(response_out)
        rows.append({"alpha": float(alpha), "cv_rmse": float(np.sqrt(squared_error / count)) if count else np.nan})

    scores = pd.DataFrame(rows)
    best = float(scores.loc[scores["cv_rmse"].idxmin(), "alpha"]) if not scores["cv_rmse"].isna().all() else float(alpha_grid[0])
    return best, scores


def fit_rapm(
    matrix: np.ndarray,
    response: np.ndarray,
    players: Sequence[int],
    *,
    alpha: float,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """Fit at the chosen penalty and split the coefficients into offence and defence."""
    gram = matrix.T @ matrix
    moment = matrix.T @ response
    beta = solve_ridge(gram, moment, alpha)

    player_count = len(players)
    offense = beta[UNPENALIZED_COLUMNS : UNPENALIZED_COLUMNS + player_count]
    defense = beta[UNPENALIZED_COLUMNS + player_count :]

    table = pd.DataFrame(
        {
            "player_id": list(players),
            "o_rapm": offense,
            "d_rapm": defense,
            "rapm": offense + defense,
        }
    )
    fit = {
        "alpha": float(alpha),
        "intercept": float(beta[0]),
        "home_court_advantage": float(beta[1]),
        "possessions": int(matrix.shape[0]),
        "parameters": int(matrix.shape[1]),
    }
    return table, fit


def build_rapm_table(
    rapm: pd.DataFrame,
    counts: pd.DataFrame,
    *,
    min_possessions_reliable: int,
    min_possessions_reported: int,
) -> pd.DataFrame:
    """Attach sample sizes, drop players too thin to report, and rank."""
    table = rapm.merge(counts, on="player_id", how="left")
    table = table[table["total_poss"].fillna(0) >= min_possessions_reported].copy()
    table["sample_flag"] = np.where(
        table["total_poss"] >= min_possessions_reliable, "Reliable", "Low sample"
    )
    for column in ("o_rapm", "d_rapm", "rapm"):
        table[column] = table[column].round(3)
    table = table.sort_values("rapm", ascending=False).reset_index(drop=True)
    table.insert(1, "rapm_rank", np.arange(1, len(table) + 1))
    return table
