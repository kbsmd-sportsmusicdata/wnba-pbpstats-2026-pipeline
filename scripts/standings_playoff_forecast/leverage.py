"""Conditional playoff leverage from an owned :class:`SimulationResult`.

All swings use a home-oriented branch contract. Probability swings are
``P(outcome | home win) - P(outcome | home loss)``. Expected-rank swings are
``E(rank | home loss) - E(rank | home win)``, so positive values are favorable
to the home side and negative values are favorable to the away side.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .team_game_layer import normalize_id


LEVERAGE_COLUMNS = [
    "game_id",
    "game_date",
    "home_id",
    "away_id",
    "home_win_branch_n",
    "home_loss_branch_n",
    "conditional_estimate_available",
    "home_playoff_probability_if_home_win",
    "home_playoff_probability_if_home_loss",
    "home_playoff_probability_swing",
    "away_playoff_probability_if_home_win",
    "away_playoff_probability_if_home_loss",
    "away_playoff_probability_swing",
    "home_top4_probability_if_home_win",
    "home_top4_probability_if_home_loss",
    "home_top4_probability_swing",
    "away_top4_probability_if_home_win",
    "away_top4_probability_if_home_loss",
    "away_top4_probability_swing",
    "home_expected_rank_if_home_win",
    "home_expected_rank_if_home_loss",
    "home_expected_rank_swing",
    "away_expected_rank_if_home_win",
    "away_expected_rank_if_home_loss",
    "away_expected_rank_swing",
    "direct_h2h_tiebreak_flag",
    "cutline_matchup_flag",
    "top4_matchup_flag",
    "raw_leverage",
    "leverage_score",
    "leverage_label",
]

_REMAINING_REQUIRED = {
    "game_id",
    "home_id",
    "away_id",
    "home_win_probability",
    "away_win_probability",
}
_STANDINGS_REQUIRED = {
    "team_id",
    "current_rank",
    "wins",
    "losses",
}
_SUMMARY_REQUIRED = {
    "team_id",
    "playoff_probability",
    "top4_probability",
    "expected_final_rank",
}


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def _normalized_ids(frame: pd.DataFrame, columns: tuple[str, ...], name: str) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = result[column].map(normalize_id)
    if result[list(columns)].isna().any().any() or result[list(columns)].eq("").any().any():
        raise ValueError(f"{name} contains missing or blank normalized identifiers")
    return result


def _validate_probability_columns(frame: pd.DataFrame, columns: list[str], name: str) -> None:
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(numeric.to_numpy(dtype=float)).all()
        or not numeric.ge(0).all().all()
        or not numeric.le(1).all().all()
    ):
        raise ValueError(f"{name} probabilities must be finite and within [0, 1]")


def _validate_inputs(
    scored_remaining: pd.DataFrame,
    simulation_result: object,
    current_standings: pd.DataFrame,
    cfg: object,
) -> tuple[pd.DataFrame, pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    _require_columns(scored_remaining, _REMAINING_REQUIRED, "scored_remaining")
    _require_columns(current_standings, _STANDINGS_REQUIRED, "current_standings")
    _require_columns(simulation_result.forecast_summary, _SUMMARY_REQUIRED, "forecast_summary")
    remaining = _normalized_ids(
        scored_remaining, ("game_id", "home_id", "away_id"), "scored_remaining"
    )
    standings = _normalized_ids(current_standings, ("team_id",), "current_standings")
    summary = _normalized_ids(simulation_result.forecast_summary, ("team_id",), "forecast_summary")
    if remaining["game_id"].duplicated().any():
        raise ValueError("scored_remaining contains duplicate normalized game_id")
    if standings["team_id"].duplicated().any():
        raise ValueError("current_standings contains duplicate normalized team_id")
    if summary["team_id"].duplicated().any():
        raise ValueError("forecast_summary contains duplicate normalized team_id")
    if remaining["home_id"].eq(remaining["away_id"]).any():
        raise ValueError("scored_remaining contains identical participants")
    _validate_probability_columns(
        remaining, ["home_win_probability", "away_win_probability"], "matchup"
    )
    complements = remaining[["home_win_probability", "away_win_probability"]].sum(axis=1)
    if not np.allclose(complements, 1.0, rtol=0.0, atol=1e-12):
        raise ValueError("home and away matchup probabilities must sum to 1")
    _validate_probability_columns(
        summary, ["playoff_probability", "top4_probability"], "forecast_summary"
    )
    expected_rank = pd.to_numeric(summary["expected_final_rank"], errors="coerce")
    if (
        not np.isfinite(expected_rank.to_numpy(dtype=float)).all()
        or not expected_rank.between(1, cfg.team_count).all()
    ):
        raise ValueError("forecast_summary expected ranks must be finite and valid")

    team_ids = tuple(normalize_id(value) for value in simulation_result.team_ids)
    game_ids = tuple(normalize_id(value) for value in simulation_result.remaining_game_ids)
    if (
        any(value is None or value == "" for value in team_ids)
        or len(team_ids) != cfg.team_count
        or len(set(team_ids)) != len(team_ids)
    ):
        raise ValueError("SimulationResult team_ids must be unique configured team IDs")
    if any(value is None or value == "" for value in game_ids) or len(set(game_ids)) != len(game_ids):
        raise ValueError("SimulationResult remaining_game_ids must be unique valid IDs")
    if tuple(remaining["game_id"]) != game_ids:
        raise ValueError("scored_remaining remaining game order must match SimulationResult")
    if tuple(summary["team_id"]) != team_ids:
        raise ValueError("forecast_summary team order must match SimulationResult")
    if set(standings["team_id"]) != set(team_ids):
        raise ValueError("current_standings team IDs must match SimulationResult")
    participant_ids = set(remaining["home_id"]) | set(remaining["away_id"])
    if not participant_ids.issubset(team_ids):
        raise ValueError("scored_remaining contains a team absent from SimulationResult")

    count = simulation_result.simulation_count
    if isinstance(count, bool) or not isinstance(count, (int, np.integer)) or count <= 0:
        raise ValueError("SimulationResult simulation_count must be a positive integer")
    ranks = np.asarray(simulation_result.final_ranks)
    margins = np.asarray(simulation_result.simulated_home_margins)
    if ranks.shape != (count, len(team_ids)):
        raise ValueError("SimulationResult final_ranks shape is inconsistent")
    if margins.shape != (count, len(game_ids)):
        raise ValueError("SimulationResult simulated_home_margins shape is inconsistent")
    if not np.issubdtype(ranks.dtype, np.integer) or not np.issubdtype(margins.dtype, np.integer):
        raise ValueError("SimulationResult ranks and margins must be integer arrays")
    if np.any(margins == 0):
        raise ValueError("SimulationResult simulated margins must be non-zero")
    expected_ranks = np.arange(1, cfg.team_count + 1)
    if not np.all(np.sort(ranks, axis=1) == expected_ranks):
        raise ValueError("SimulationResult must assign every configured rank in each run")

    ranks_numeric = pd.to_numeric(standings["current_rank"], errors="coerce")
    if (
        ranks_numeric.isna().any()
        or not np.isfinite(ranks_numeric.to_numpy(dtype=float)).all()
        or ranks_numeric.mod(1).ne(0).any()
        or set(ranks_numeric.astype(int)) != set(range(1, cfg.team_count + 1))
    ):
        raise ValueError("current_standings must assign every current_rank exactly once")
    standings["current_rank"] = ranks_numeric.astype(int)
    for column in ("wins", "losses"):
        values = pd.to_numeric(standings[column], errors="coerce")
        if not np.isfinite(values.to_numpy(dtype=float)).all() or values.lt(0).any():
            raise ValueError(f"current_standings contains invalid {column}")
        standings[column] = values
    return remaining, standings, team_ids, game_ids


def _conditional_rate(ranks: np.ndarray, mask: np.ndarray, limit: int) -> float:
    return float((ranks[mask] <= limit).mean())


def _label(score: float) -> str:
    if score >= 85:
        return "Critical"
    if score >= 65:
        return "High"
    if score >= 35:
        return "Moderate"
    return "Low"


def calculate_game_leverage(
    scored_remaining: pd.DataFrame,
    simulation_result: object,
    current_standings: pd.DataFrame,
    cfg: object,
) -> pd.DataFrame:
    """Return one conditional-leverage row for each stored remaining game.

    Raw leverage is transparent and home/away symmetric: 100 times the largest
    affected-team playoff swing, plus 60 times the largest top-four swing, plus
    four times the largest expected-rank swing, plus 15/10/10 points for direct
    H2H, playoff-cutline, and top-four-cutline flags. Min-max scaling is applied
    across games; a zero-variance set receives deterministic score zero.
    """

    remaining, standings, team_ids, game_ids = _validate_inputs(
        scored_remaining, simulation_result, current_standings, cfg
    )
    if not game_ids:
        return pd.DataFrame(columns=LEVERAGE_COLUMNS)

    team_index = {team_id: index for index, team_id in enumerate(team_ids)}
    standing_by_team = standings.set_index("team_id")
    final_ranks = np.asarray(simulation_result.final_ranks)
    margins = np.asarray(simulation_result.simulated_home_margins)
    playoff_limit = int(cfg.playoff_qualifiers)
    if not 1 <= playoff_limit < cfg.team_count:
        raise ValueError("playoff_qualifiers must be below team_count")
    top4_limit = min(4, playoff_limit)
    h2h_configured = any(name.startswith("head_to_head") for name in cfg.tiebreaks)
    rows: list[dict[str, object]] = []

    for game_index, game in enumerate(remaining.itertuples(index=False)):
        home_win = margins[:, game_index] > 0
        home_loss = ~home_win
        win_n = int(home_win.sum())
        loss_n = int(home_loss.sum())
        available = win_n > 0 and loss_n > 0
        home_ranks = final_ranks[:, team_index[game.home_id]]
        away_ranks = final_ranks[:, team_index[game.away_id]]
        values: dict[str, float] = {}
        if available:
            for side, ranks in (("home", home_ranks), ("away", away_ranks)):
                playoff_win = _conditional_rate(ranks, home_win, playoff_limit)
                playoff_loss = _conditional_rate(ranks, home_loss, playoff_limit)
                top4_win = _conditional_rate(ranks, home_win, top4_limit)
                top4_loss = _conditional_rate(ranks, home_loss, top4_limit)
                rank_win = float(ranks[home_win].mean())
                rank_loss = float(ranks[home_loss].mean())
                values.update(
                    {
                        f"{side}_playoff_probability_if_home_win": playoff_win,
                        f"{side}_playoff_probability_if_home_loss": playoff_loss,
                        f"{side}_playoff_probability_swing": playoff_win - playoff_loss,
                        f"{side}_top4_probability_if_home_win": top4_win,
                        f"{side}_top4_probability_if_home_loss": top4_loss,
                        f"{side}_top4_probability_swing": top4_win - top4_loss,
                        f"{side}_expected_rank_if_home_win": rank_win,
                        f"{side}_expected_rank_if_home_loss": rank_loss,
                        f"{side}_expected_rank_swing": rank_loss - rank_win,
                    }
                )
        else:
            for side in ("home", "away"):
                for metric in (
                    "playoff_probability_if_home_win",
                    "playoff_probability_if_home_loss",
                    "playoff_probability_swing",
                    "top4_probability_if_home_win",
                    "top4_probability_if_home_loss",
                    "top4_probability_swing",
                    "expected_rank_if_home_win",
                    "expected_rank_if_home_loss",
                    "expected_rank_swing",
                ):
                    values[f"{side}_{metric}"] = np.nan

        home_standing = standing_by_team.loc[game.home_id]
        away_standing = standing_by_team.loc[game.away_id]
        rank_pair = {int(home_standing.current_rank), int(away_standing.current_rank)}
        direct_h2h = bool(
            h2h_configured
            and home_standing.wins == away_standing.wins
            and home_standing.losses == away_standing.losses
        )
        cutline = rank_pair == {playoff_limit, playoff_limit + 1}
        top4 = top4_limit < cfg.team_count and rank_pair == {top4_limit, top4_limit + 1}
        conditional_raw = 0.0
        if available:
            conditional_raw = (
                100
                * max(
                    abs(values["home_playoff_probability_swing"]),
                    abs(values["away_playoff_probability_swing"]),
                )
                + 60
                * max(
                    abs(values["home_top4_probability_swing"]),
                    abs(values["away_top4_probability_swing"]),
                )
                + 4
                * max(
                    abs(values["home_expected_rank_swing"]),
                    abs(values["away_expected_rank_swing"]),
                )
            )
        rows.append(
            {
                "game_id": game.game_id,
                "game_date": getattr(game, "game_date", pd.NA),
                "home_id": game.home_id,
                "away_id": game.away_id,
                "home_win_branch_n": win_n,
                "home_loss_branch_n": loss_n,
                "conditional_estimate_available": available,
                **values,
                "direct_h2h_tiebreak_flag": direct_h2h,
                "cutline_matchup_flag": cutline,
                "top4_matchup_flag": top4,
                "raw_leverage": conditional_raw + 15 * direct_h2h + 10 * cutline + 10 * top4,
            }
        )

    result = pd.DataFrame(rows)
    raw_min = float(result["raw_leverage"].min())
    raw_max = float(result["raw_leverage"].max())
    if raw_max == raw_min:
        result["leverage_score"] = 0.0
    else:
        result["leverage_score"] = 100 * (result["raw_leverage"] - raw_min) / (raw_max - raw_min)
    result["leverage_label"] = result["leverage_score"].map(_label)
    return result.reindex(columns=LEVERAGE_COLUMNS)
