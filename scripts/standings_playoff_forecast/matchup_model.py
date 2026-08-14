"""Pace-scaled remaining-game margin and win-probability model."""

import math
from statistics import NormalDist, stdev

import pandas as pd

from .contracts import ForecastModelConfig


_EMPTY_LEAGUE_NEUTRAL_PACE = 100.0


def _fallback_sigma(model_cfg: ForecastModelConfig) -> float:
    return (model_cfg.minimum_sigma + model_cfg.maximum_sigma) / 2


def _side_context(context: pd.DataFrame, side: str) -> pd.DataFrame:
    return context.rename(
        columns={
            "team_id": f"{side}_id",
            "predictive_net_rating": f"{side}_predictive_net_rating",
            "pace_est": f"{side}_pace",
        }
    )


def _add_model_frame(
    games: pd.DataFrame, model_cfg: ForecastModelConfig
) -> pd.DataFrame:
    framed = games.copy()
    framed["avg_pace"] = (framed["home_pace"] + framed["away_pace"]) / 2
    framed["base_margin"] = (
        framed["home_predictive_net_rating"]
        - framed["away_predictive_net_rating"]
    ) * framed["avg_pace"] / 100
    framed["rest_diff"] = (
        pd.to_numeric(framed["home_rest_days"], errors="coerce")
        - pd.to_numeric(framed["away_rest_days"], errors="coerce")
    ).fillna(0).clip(
        lower=-model_cfg.max_rest_day_adjustment,
        upper=model_cfg.max_rest_day_adjustment,
    )
    framed["expected_home_margin"] = (
        framed["base_margin"]
        + model_cfg.home_court_points
        + framed["rest_diff"] * model_cfg.rest_day_points
        - model_cfg.back_to_back_penalty_points
        * framed["home_b2b"].astype(bool).astype(int)
        + model_cfg.back_to_back_penalty_points
        * framed["away_b2b"].astype(bool).astype(int)
    )
    return framed


def _validate_reciprocal_team_games(team_games: pd.DataFrame) -> None:
    for game_id, game_rows in team_games.groupby("game_id", dropna=False):
        home_rows = game_rows.loc[game_rows["is_home"].astype(bool)]
        away_rows = game_rows.loc[~game_rows["is_home"].astype(bool)]
        if len(game_rows) != 2 or len(home_rows) != 1 or len(away_rows) != 1:
            raise ValueError(
                "completed team_games must contain reciprocal directional rows: "
                f"{game_id}"
            )
        home = home_rows.iloc[0]
        away = away_rows.iloc[0]
        if (
            home["team_id"] != away["opponent_id"]
            or home["opponent_id"] != away["team_id"]
        ):
            raise ValueError(
                "completed team_games must contain reciprocal directional rows: "
                f"{game_id}"
            )


def _estimate_sigma(
    team_games: pd.DataFrame,
    context: pd.DataFrame,
    model_cfg: ForecastModelConfig,
) -> float:
    home_games = team_games.loc[team_games["is_home"].astype(bool)].rename(
        columns={
            "team_id": "home_id",
            "opponent_id": "away_id",
            "margin": "actual_home_margin",
            "rest_days": "home_rest_days",
            "back_to_back": "home_b2b",
        }
    )
    away_rest = team_games.loc[
        ~team_games["is_home"].astype(bool),
        ["game_id", "team_id", "rest_days", "back_to_back"],
    ].rename(
        columns={
            "team_id": "away_id",
            "rest_days": "away_rest_days",
            "back_to_back": "away_b2b",
        }
    )
    completed = home_games.merge(
        away_rest, on=["game_id", "away_id"], how="inner", validate="one_to_one"
    )
    completed = completed.merge(
        _side_context(context, "home"),
        on="home_id",
        how="left",
        validate="many_to_one",
    ).merge(
        _side_context(context, "away"),
        on="away_id",
        how="left",
        validate="many_to_one",
    )
    completed_context = (
        "home_predictive_net_rating",
        "away_predictive_net_rating",
        "home_pace",
        "away_pace",
    )
    context_is_finite = pd.DataFrame(
        {
            column: pd.to_numeric(completed[column], errors="coerce").map(
                math.isfinite
            )
            for column in completed_context
        }
    ).all(axis=1)
    if not context_is_finite.all():
        invalid_games = ", ".join(
            completed.loc[~context_is_finite, "game_id"].astype(str)
        )
        raise ValueError(
            "completed games have missing strength or pace context: "
            f"{invalid_games}"
        )
    completed = _add_model_frame(completed, model_cfg)
    residuals = pd.to_numeric(
        completed["actual_home_margin"], errors="coerce"
    ) - completed["expected_home_margin"]
    finite_residuals = [float(value) for value in residuals if math.isfinite(value)]
    if len(finite_residuals) < 2:
        return _fallback_sigma(model_cfg)
    estimate = stdev(finite_residuals)
    if not math.isfinite(estimate):
        return _fallback_sigma(model_cfg)
    return min(max(estimate, model_cfg.minimum_sigma), model_cfg.maximum_sigma)


def score_matchups(
    remaining: pd.DataFrame,
    strength: pd.DataFrame,
    team_games: pd.DataFrame,
    model_cfg: ForecastModelConfig,
) -> pd.DataFrame:
    """Score remaining games using current strength and completed-game pace."""

    _validate_reciprocal_team_games(team_games)
    rating_columns = ["team_id", "predictive_net_rating"]
    if "season_games_played" in strength.columns:
        rating_columns.append("season_games_played")
    ratings = strength[rating_columns].copy()
    pace = (
        team_games.assign(
            pace_est=pd.to_numeric(team_games["pace_est"], errors="coerce")
        )
        .groupby("team_id", as_index=False)["pace_est"]
        .mean()
    )
    context = ratings.merge(pace, on="team_id", how="left", validate="one_to_one")
    if "season_games_played" in context.columns:
        zero_game_team = pd.to_numeric(
            context["season_games_played"], errors="coerce"
        ).eq(0)
        observed_pace = pd.to_numeric(pace["pace_est"], errors="coerce")
        observed_pace = observed_pace.loc[observed_pace.map(math.isfinite)]
        neutral_pace = (
            float(observed_pace.mean())
            if not observed_pace.empty
            else _EMPTY_LEAGUE_NEUTRAL_PACE
        )
        context.loc[zero_game_team & context["pace_est"].isna(), "pace_est"] = (
            neutral_pace
        )
    result = remaining.copy().merge(
        _side_context(context, "home"),
        on="home_id",
        how="left",
        validate="many_to_one",
    ).merge(
        _side_context(context, "away"),
        on="away_id",
        how="left",
        validate="many_to_one",
    )
    required_context = (
        "home_predictive_net_rating",
        "away_predictive_net_rating",
        "home_pace",
        "away_pace",
    )
    context_is_finite = pd.DataFrame(
        {
            column: pd.to_numeric(result[column], errors="coerce").map(math.isfinite)
            for column in required_context
        }
    ).all(axis=1)
    if not context_is_finite.all():
        invalid_games = ", ".join(result.loc[~context_is_finite, "game_id"].astype(str))
        raise ValueError(
            f"remaining games have missing strength or pace context: {invalid_games}"
        )
    result = _add_model_frame(result, model_cfg)
    margin_sigma = _estimate_sigma(team_games, context, model_cfg)
    standard_normal = NormalDist()
    result["margin_sigma"] = margin_sigma
    result["home_win_probability"] = result["expected_home_margin"].map(
        lambda margin: standard_normal.cdf(float(margin) / margin_sigma)
    )
    result["away_win_probability"] = 1.0 - result["home_win_probability"]
    result["model_version"] = model_cfg.model_version
    return result
