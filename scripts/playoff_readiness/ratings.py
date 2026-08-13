"""How good is each team, and how sure are we?

Seed probabilities are only as good as the strength estimates behind them, so the rating
model is deliberately plain and deliberately checked. Each completed game contributes one
observation:

    margin = rating(home) - rating(away) + home_advantage + error

fitted by ridge-penalised weighted least squares. Three choices carry weight:

* **Margins, not results.** A win is one bit; a margin is the same bit plus a read on how
  close the game was. Blowouts are capped so a 40-point night cannot drag a rating.
* **Recency weighting.** Rosters and rotations move over a season. Older games count less,
  with a half-life set by config and chosen by backtest rather than taste.
* **Ratings carry uncertainty.** The simulation draws a full rating vector from the fit's
  posterior on every run, so a team with 27 games played is allowed to be less certain
  than the point estimate suggests. Simulating from the point estimate alone produces
  playoff odds that are far too confident, which is the standard way these models lie.

`backtest` exists because none of that is worth trusting on assertion. It refits on an
early slice of the season and scores the rest against two baselines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .schedule import LEAGUE_TEAMS


@dataclass
class RatingFit:
    teams: List[str]
    ratings: np.ndarray
    home_advantage: float
    residual_sd: float
    covariance: np.ndarray
    alpha: float
    games: int
    effective_games: float

    def rating_series(self) -> pd.Series:
        return pd.Series(self.ratings, index=self.teams, name="team_rating")

    def expected_margin(self, home: Sequence[str], away: Sequence[str], neutral: Optional[Sequence[bool]] = None) -> np.ndarray:
        lookup = {team: index for index, team in enumerate(self.teams)}
        home_index = np.array([lookup[team] for team in home])
        away_index = np.array([lookup[team] for team in away])
        if neutral is None:
            edge = np.full(len(home_index), self.home_advantage)
        else:
            edge = np.where(np.asarray(neutral, dtype=bool), 0.0, self.home_advantage)
        return self.ratings[home_index] - self.ratings[away_index] + edge


def design_matrix(
    home: Sequence[str],
    away: Sequence[str],
    neutral: Optional[Sequence[bool]] = None,
    *,
    teams: Sequence[str] = LEAGUE_TEAMS,
) -> np.ndarray:
    """One column per team plus a home-advantage column.

    Every row sums to zero across the team columns, so the ratings are identified only up
    to a common shift. The ridge penalty resolves that by selecting the minimum-norm
    solution, which is the sum-to-zero one -- ratings are therefore centred on the league
    by construction and read directly as points per game above average.
    """
    lookup = {team: index for index, team in enumerate(teams)}
    matrix = np.zeros((len(home), len(teams) + 1))
    for row, (home_team, away_team) in enumerate(zip(home, away)):
        matrix[row, lookup[home_team]] = 1.0
        matrix[row, lookup[away_team]] = -1.0
    if neutral is None:
        matrix[:, -1] = 1.0
    else:
        matrix[:, -1] = np.where(np.asarray(neutral), 0.0, 1.0)
    return matrix


def recency_weights(dates: pd.Series, *, half_life_days: float, reference: Optional[pd.Timestamp] = None) -> np.ndarray:
    """Exponential decay in calendar days. A non-positive half-life means no weighting."""
    if half_life_days is None or half_life_days <= 0:
        return np.ones(len(dates))
    dates = pd.to_datetime(dates)
    reference = reference if reference is not None else dates.max()
    age_days = (reference - dates).dt.total_seconds().to_numpy() / 86400.0
    return np.power(0.5, np.maximum(age_days, 0.0) / float(half_life_days))


def fit_ratings(
    played: pd.DataFrame,
    *,
    alpha: float,
    half_life_days: float,
    margin_cap: float,
    teams: Sequence[str] = LEAGUE_TEAMS,
) -> RatingFit:
    """Weighted ridge fit of team ratings and home advantage."""
    teams = list(teams)
    if played.empty:
        return RatingFit(
            teams=teams,
            ratings=np.zeros(len(teams)),
            home_advantage=0.0,
            residual_sd=float("nan"),
            covariance=np.zeros((len(teams) + 1, len(teams) + 1)),
            alpha=alpha,
            games=0,
            effective_games=0.0,
        )

    matrix = design_matrix(
        played["home_team"].tolist(), played["away_team"].tolist(), played["neutral_site"].tolist(), teams=teams
    )
    margin = (played["home_score"] - played["away_score"]).to_numpy(dtype=float)
    if margin_cap and margin_cap > 0:
        margin = np.clip(margin, -float(margin_cap), float(margin_cap))
    weights = recency_weights(played["game_date"], half_life_days=half_life_days)

    penalty = np.eye(matrix.shape[1])
    penalty[-1, -1] = 0.0  # home advantage is a league constant, not a shrinkable rating
    weighted = matrix * weights[:, None]
    gram = matrix.T @ weighted + alpha * penalty
    moment = weighted.T @ margin
    beta = np.linalg.solve(gram, moment)

    fitted = matrix @ beta
    residual = margin - fitted
    inverse = np.linalg.inv(gram)
    edf = float(np.trace(matrix @ inverse @ weighted.T))
    denominator = max(float(weights.sum()) - edf, 1.0)
    variance = float((weights * residual**2).sum() / denominator)
    # Sandwich form: the plain (X'WX + aP)^-1 understates spread once observations are
    # unequally weighted, and rating uncertainty is the whole point of computing it.
    covariance = variance * inverse @ (matrix.T @ (matrix * (weights**2)[:, None])) @ inverse

    return RatingFit(
        teams=teams,
        ratings=beta[:-1],
        home_advantage=float(beta[-1]),
        residual_sd=float(np.sqrt(variance)),
        covariance=covariance,
        alpha=float(alpha),
        games=int(len(played)),
        effective_games=round(float(weights.sum()), 2),
    )


def cross_validate_alpha(
    played: pd.DataFrame,
    *,
    alpha_grid: Sequence[float],
    half_life_days: float,
    margin_cap: float,
    folds: int,
    seed: int,
    teams: Sequence[str] = LEAGUE_TEAMS,
) -> Tuple[float, pd.DataFrame]:
    """Pick the penalty by held-out margin error rather than by preference."""
    grid = [float(value) for value in alpha_grid] or [1.0]
    if len(played) < folds * 2:
        return grid[len(grid) // 2], pd.DataFrame(columns=["alpha", "held_out_rmse", "folds"])

    rng = np.random.default_rng(seed)
    assignment = rng.integers(0, folds, size=len(played))
    rows: List[Dict[str, Any]] = []
    for alpha in grid:
        errors: List[float] = []
        for fold in range(folds):
            train = played[assignment != fold]
            test = played[assignment == fold]
            if train.empty or test.empty:
                continue
            fit = fit_ratings(train, alpha=alpha, half_life_days=half_life_days, margin_cap=margin_cap, teams=teams)
            predicted = fit.expected_margin(
                test["home_team"].tolist(), test["away_team"].tolist(), test["neutral_site"].tolist()
            )
            actual = (test["home_score"] - test["away_score"]).to_numpy(dtype=float)
            errors.append(float(np.mean((actual - predicted) ** 2)))
        if errors:
            rows.append({"alpha": alpha, "held_out_rmse": round(float(np.sqrt(np.mean(errors))), 4), "folds": len(errors)})

    table = pd.DataFrame(rows)
    if table.empty:
        return grid[len(grid) // 2], table
    best = float(table.loc[table["held_out_rmse"].idxmin(), "alpha"])
    return best, table.sort_values("alpha").reset_index(drop=True)


def sample_ratings(fit: RatingFit, draws: int, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray]:
    """Draw `draws` rating vectors and home advantages from the fit's posterior.

    Returns `(ratings[draws, teams], home_advantage[draws])`. The covariance is nearly
    singular along the common-shift direction the ridge pinned down, so the draw goes
    through an eigenvalue decomposition with negatives clipped rather than a Cholesky
    factorisation that would simply fail.
    """
    mean = np.concatenate([fit.ratings, [fit.home_advantage]])
    values, vectors = np.linalg.eigh(fit.covariance)
    root = vectors @ np.diag(np.sqrt(np.clip(values, 0.0, None)))
    noise = rng.standard_normal((draws, len(mean)))
    sampled = mean[None, :] + noise @ root.T
    return sampled[:, :-1], sampled[:, -1]


def win_probability(margin: np.ndarray, residual_sd: float) -> np.ndarray:
    """Probability the expected margin turns into a win, under a normal error."""
    from math import erf, sqrt

    if not np.isfinite(residual_sd) or residual_sd <= 0:
        return (np.asarray(margin) > 0).astype(float)
    z = np.asarray(margin, dtype=float) / (residual_sd * sqrt(2.0))
    return 0.5 * (1.0 + np.vectorize(erf)(z))


def backtest(
    played: pd.DataFrame,
    *,
    alpha: float,
    half_life_days: float,
    margin_cap: float,
    train_fraction: float = 0.7,
    teams: Sequence[str] = LEAGUE_TEAMS,
) -> Dict[str, Any]:
    """Score the model on games it has not seen, against two honest baselines.

    The split is chronological, which is the only split that matches how the model is
    actually used. Baselines are (a) home team always wins, and (b) the sign of the two
    teams' win-percentage gap turned into a probability by logistic regression on the
    training slice. A rating model that cannot beat those is not earning its complexity.
    """
    result: Dict[str, Any] = {"status": "insufficient_data"}
    if len(played) < 40:
        return result

    ordered = played.sort_values("game_date").reset_index(drop=True)
    cut = int(len(ordered) * train_fraction)
    train, test = ordered.iloc[:cut], ordered.iloc[cut:]
    if train.empty or test.empty:
        return result

    fit = fit_ratings(train, alpha=alpha, half_life_days=half_life_days, margin_cap=margin_cap, teams=teams)
    predicted_margin = fit.expected_margin(
        test["home_team"].tolist(), test["away_team"].tolist(), test["neutral_site"].tolist()
    )
    actual_margin = (test["home_score"] - test["away_score"]).to_numpy(dtype=float)
    home_won = (actual_margin > 0).astype(float)

    model_probability = win_probability(predicted_margin, fit.residual_sd)
    home_rate = float((train["home_score"] > train["away_score"]).mean())
    home_baseline = np.full(len(test), home_rate)
    record_baseline = _record_baseline(train, test, teams=teams)

    result = {
        "status": "scored",
        "train_games": int(len(train)),
        "test_games": int(len(test)),
        "train_through": train["game_date"].max().date().isoformat(),
        "model_log_loss": _log_loss(home_won, model_probability),
        "model_brier": _brier(home_won, model_probability),
        "model_margin_rmse": round(float(np.sqrt(np.mean((actual_margin - predicted_margin) ** 2))), 3),
        "home_field_baseline_log_loss": _log_loss(home_won, home_baseline),
        "home_field_baseline_brier": _brier(home_won, home_baseline),
        "record_baseline_log_loss": _log_loss(home_won, record_baseline),
        "record_baseline_brier": _brier(home_won, record_baseline),
        "model_accuracy": round(float(((model_probability > 0.5) == (home_won > 0.5)).mean()), 4),
    }
    result["beats_home_field_baseline"] = result["model_log_loss"] < result["home_field_baseline_log_loss"]
    result["beats_record_baseline"] = result["model_log_loss"] < result["record_baseline_log_loss"]
    return result


def _record_baseline(train: pd.DataFrame, test: pd.DataFrame, *, teams: Sequence[str]) -> np.ndarray:
    """Win probability from the win-percentage gap alone, calibrated on the training slice."""
    wins: Dict[str, float] = {team: 0.0 for team in teams}
    games: Dict[str, float] = {team: 0.0 for team in teams}
    for _, row in train.iterrows():
        home_win = row["home_score"] > row["away_score"]
        wins[row["home_team"]] += float(home_win)
        wins[row["away_team"]] += float(not home_win)
        games[row["home_team"]] += 1.0
        games[row["away_team"]] += 1.0
    pct = {team: (wins[team] + 1.0) / (games[team] + 2.0) for team in teams}

    gap_train = np.array([pct[row["home_team"]] - pct[row["away_team"]] for _, row in train.iterrows()])
    outcome_train = (train["home_score"] > train["away_score"]).to_numpy(dtype=float)
    slope, intercept = _logistic_fit(gap_train, outcome_train)

    gap_test = np.array([pct[row["home_team"]] - pct[row["away_team"]] for _, row in test.iterrows()])
    return 1.0 / (1.0 + np.exp(-(intercept + slope * gap_test)))


def _logistic_fit(x: np.ndarray, y: np.ndarray, *, iterations: int = 60) -> Tuple[float, float]:
    """Two-parameter logistic regression by Newton steps, with a tiny ridge for stability."""
    beta = np.zeros(2)
    matrix = np.column_stack([np.ones(len(x)), x])
    for _ in range(iterations):
        probability = 1.0 / (1.0 + np.exp(-(matrix @ beta)))
        gradient = matrix.T @ (y - probability) - 1e-6 * beta
        weight = np.clip(probability * (1.0 - probability), 1e-9, None)
        hessian = matrix.T @ (matrix * weight[:, None]) + 1e-6 * np.eye(2)
        step = np.linalg.solve(hessian, gradient)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return float(beta[1]), float(beta[0])


def _log_loss(actual: np.ndarray, probability: np.ndarray) -> float:
    clipped = np.clip(probability, 1e-9, 1 - 1e-9)
    return round(float(-np.mean(actual * np.log(clipped) + (1 - actual) * np.log(1 - clipped))), 4)


def _brier(actual: np.ndarray, probability: np.ndarray) -> float:
    return round(float(np.mean((probability - actual) ** 2)), 4)
