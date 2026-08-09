"""Monte Carlo season simulation and rank-probability aggregation."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .contracts import SeasonConfig
from .team_game_layer import normalize_id
from .tiebreaks import rank_teams


_COMPLETED_COLUMNS = {
    "game_id",
    "team_id",
    "opponent_id",
    "win",
    "loss",
    "margin",
}
_REMAINING_COLUMNS = {
    "game_id",
    "home_id",
    "away_id",
    "expected_home_margin",
    "margin_sigma",
    "home_win_probability",
    "away_win_probability",
}


@dataclass(frozen=True)
class SimulationResult:
    """Owned simulation outputs consumed by forecast post-processing."""

    forecast_summary: pd.DataFrame
    rank_probability_matrix: pd.DataFrame
    fallback_count: int
    simulation_count: int
    seed: int
    team_ids: tuple[str, ...]
    remaining_game_ids: tuple[str, ...]
    final_wins: np.ndarray
    final_losses: np.ndarray
    final_point_differentials: np.ndarray
    final_ranks: np.ndarray
    simulated_home_margins: np.ndarray


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def _validate_identifiers(
    frame: pd.DataFrame,
    *,
    name: str,
    participant_columns: tuple[str, str],
) -> None:
    identifier_columns = ("game_id", *participant_columns)
    if frame[list(identifier_columns)].isna().any().any():
        raise ValueError(f"{name} contains missing game or team identifiers")
    same_team = frame[participant_columns[0]].eq(frame[participant_columns[1]])
    if same_team.any():
        game_id = frame.loc[same_team, "game_id"].iloc[0]
        raise ValueError(
            f"{name} contains a game with identical participants: {game_id}"
        )


def _validate_game_ids(
    completed_games: pd.DataFrame,
    scored_remaining: pd.DataFrame,
) -> None:
    duplicate_remaining = scored_remaining.loc[
        scored_remaining["game_id"].duplicated(keep=False), "game_id"
    ].drop_duplicates()
    if not duplicate_remaining.empty:
        raise ValueError(
            "scored_remaining contains duplicate normalized game_id: "
            + ", ".join(duplicate_remaining)
        )

    duplicate_directional = completed_games.loc[
        completed_games.duplicated(["game_id", "team_id"], keep=False),
        ["game_id", "team_id"],
    ].drop_duplicates()
    if not duplicate_directional.empty:
        duplicate_text = ", ".join(
            f"{row.game_id}/{row.team_id}"
            for row in duplicate_directional.itertuples(index=False)
        )
        raise ValueError(
            "completed_games contains duplicate directional rows: " + duplicate_text
        )

    overlap = sorted(
        set(completed_games["game_id"]).intersection(scored_remaining["game_id"])
    )
    if overlap:
        raise ValueError("completed and remaining games overlap: " + ", ".join(overlap))


def _validate_completed_results(completed_games: pd.DataFrame) -> None:
    numeric_columns = ("win", "loss", "margin")
    numeric = completed_games[list(numeric_columns)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    finite = np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    for row_index, is_finite in zip(completed_games.index, finite):
        if not is_finite:
            game_id = completed_games.loc[row_index, "game_id"]
            raise ValueError(
                "completed_games must contain reciprocal directional results: "
                f"{game_id}"
            )
    completed_games[list(numeric_columns)] = numeric

    result_columns = [
        "game_id",
        "team_id",
        "opponent_id",
        "win",
        "loss",
        "margin",
    ]
    for game_id, game_rows in completed_games[result_columns].groupby(
        "game_id",
        sort=False,
    ):
        reciprocal = len(game_rows) == 2
        if reciprocal:
            first, second = tuple(game_rows.itertuples(index=False))
            reciprocal = (
                first.team_id == second.opponent_id
                and first.opponent_id == second.team_id
                and first.win in (0, 1)
                and second.win in (0, 1)
                and first.loss in (0, 1)
                and second.loss in (0, 1)
                and first.win + first.loss == 1
                and second.win + second.loss == 1
                and first.win + second.win == 1
                and first.loss + second.loss == 1
                and first.margin != 0
                and first.margin == np.rint(first.margin)
                and second.margin == np.rint(second.margin)
                and first.margin == -second.margin
                and (first.margin > 0) == bool(first.win)
                and (second.margin > 0) == bool(second.win)
            )
        if not reciprocal:
            raise ValueError(
                "completed_games must contain reciprocal directional results: "
                f"{game_id}"
            )


def _validate_matchup_values(scored_remaining: pd.DataFrame) -> None:
    numeric_columns = (
        "expected_home_margin",
        "margin_sigma",
        "home_win_probability",
        "away_win_probability",
    )
    for column in numeric_columns:
        values = pd.to_numeric(scored_remaining[column], errors="coerce")
        finite = np.isfinite(values.to_numpy(dtype=float))
        if not finite.all():
            game_ids = ", ".join(scored_remaining.loc[~finite, "game_id"])
            raise ValueError(
                f"scored_remaining contains non-finite {column}: {game_ids}"
            )
        scored_remaining[column] = values

    nonpositive_sigma = scored_remaining["margin_sigma"].le(0)
    if nonpositive_sigma.any():
        game_ids = ", ".join(
            scored_remaining.loc[nonpositive_sigma, "game_id"]
        )
        raise ValueError(f"margin_sigma must be positive: {game_ids}")

    probability_columns = ["home_win_probability", "away_win_probability"]
    probabilities = scored_remaining[probability_columns]
    out_of_bounds = ~probabilities.ge(0).all(axis=1) | ~probabilities.le(1).all(axis=1)
    if out_of_bounds.any():
        game_ids = ", ".join(scored_remaining.loc[out_of_bounds, "game_id"])
        raise ValueError(
            f"matchup probabilities must be within [0, 1]: {game_ids}"
        )

    complementary = np.isclose(
        probabilities.sum(axis=1).to_numpy(dtype=float),
        1.0,
        rtol=0.0,
        atol=1e-12,
    )
    if not complementary.all():
        game_ids = ", ".join(scored_remaining.loc[~complementary, "game_id"])
        raise ValueError(
            "home and away matchup probabilities must sum to 1: " + game_ids
        )


def _build_probability_outputs(
    *,
    team_ids: tuple[str, ...],
    final_wins: np.ndarray,
    final_losses: np.ndarray,
    final_ranks: np.ndarray,
    cfg: SeasonConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    team_count = len(team_ids)
    simulation_count = final_ranks.shape[0]
    rank_counts = np.zeros((team_count, team_count), dtype=np.int64)
    for team_index in range(team_count):
        rank_counts[team_index] = np.bincount(
            final_ranks[:, team_index],
            minlength=team_count + 1,
        )[1:]
    rank_probabilities = rank_counts / simulation_count
    playoff_limit = cfg.playoff_qualifiers
    top4_limit = min(4, playoff_limit)
    win_percentiles = np.percentile(final_wins, [10, 50, 90], axis=0)

    summary = pd.DataFrame(
        {
            "team_id": team_ids,
            "season": cfg.season,
            "projected_wins_mean": final_wins.mean(axis=0),
            "projected_losses_mean": final_losses.mean(axis=0),
            "wins_p10": win_percentiles[0],
            "wins_p50": win_percentiles[1],
            "wins_p90": win_percentiles[2],
            "expected_final_rank": final_ranks.mean(axis=0),
            "playoff_probability": rank_probabilities[:, :playoff_limit].sum(axis=1),
            "top4_probability": rank_probabilities[:, :top4_limit].sum(axis=1),
            "home_court_probability": rank_probabilities[:, :top4_limit].sum(axis=1),
        }
    )
    for final_rank in range(1, team_count + 1):
        summary[f"rank_{final_rank}_probability"] = rank_probabilities[
            :, final_rank - 1
        ]
    summary["out_probability"] = rank_probabilities[:, playoff_limit:].sum(axis=1)

    matrix = pd.DataFrame(
        {
            "season": np.repeat(cfg.season, team_count * team_count),
            "team_id": np.repeat(np.asarray(team_ids, dtype=object), team_count),
            "final_rank": np.tile(np.arange(1, team_count + 1), team_count),
            "probability": rank_probabilities.reshape(-1),
        }
    )
    matrix["playoff_rank"] = matrix["final_rank"].where(
        matrix["final_rank"].le(playoff_limit)
    ).astype("Int64")
    return summary, matrix


def _validate_probability_mass(
    forecast_summary: pd.DataFrame,
    rank_probability_matrix: pd.DataFrame,
    cfg: SeasonConfig,
) -> None:
    summary_team_ids = tuple(forecast_summary["team_id"])
    expected_cells = pd.MultiIndex.from_product(
        [summary_team_ids, range(1, cfg.team_count + 1)],
        names=["team_id", "final_rank"],
    )
    actual_cells = pd.MultiIndex.from_frame(
        rank_probability_matrix[["team_id", "final_rank"]]
    )
    if (
        len(summary_team_ids) != cfg.team_count
        or len(set(summary_team_ids)) != cfg.team_count
        or actual_cells.has_duplicates
        or len(actual_cells) != len(expected_cells)
        or not actual_cells.sort_values().equals(expected_cells.sort_values())
    ):
        raise ValueError(
            "rank probability matrix must contain every team-rank cell exactly once"
        )

    probabilities = pd.to_numeric(
        rank_probability_matrix["probability"],
        errors="coerce",
    )
    if (
        not np.isfinite(probabilities.to_numpy(dtype=float)).all()
        or not probabilities.between(0.0, 1.0).all()
    ):
        raise ValueError("rank probabilities must be finite and within [0, 1]")

    team_mass = rank_probability_matrix.assign(probability=probabilities).groupby(
        "team_id"
    )["probability"].sum()
    if not np.allclose(team_mass.to_numpy(), 1.0, rtol=0.0, atol=1e-12):
        raise ValueError("each team's rank probabilities must sum to 1")

    rank_mass = rank_probability_matrix.assign(probability=probabilities).groupby(
        "final_rank"
    )["probability"].sum()
    if not np.allclose(rank_mass.to_numpy(), 1.0, rtol=0.0, atol=1e-12):
        raise ValueError("each rank's league probability must sum to 1")

    probability_columns = [
        "playoff_probability",
        "top4_probability",
        "home_court_probability",
        "out_probability",
        *[
            f"rank_{final_rank}_probability"
            for final_rank in range(1, cfg.team_count + 1)
        ],
    ]
    summary_probabilities = forecast_summary[probability_columns].apply(
        pd.to_numeric,
        errors="coerce",
    )
    if (
        not np.isfinite(summary_probabilities.to_numpy(dtype=float)).all()
        or not summary_probabilities.ge(0.0).all().all()
        or not summary_probabilities.le(1.0).all().all()
    ):
        raise ValueError("summary probabilities must be finite and within [0, 1]")
    if not np.isclose(
        summary_probabilities["playoff_probability"].sum(),
        cfg.playoff_qualifiers,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError(
            "league playoff probability must sum to playoff_qualifiers"
        )

    pivot = rank_probability_matrix.assign(probability=probabilities).pivot(
        index="team_id",
        columns="final_rank",
        values="probability",
    ).reindex(summary_team_ids)
    exact_columns = [
        f"rank_{final_rank}_probability"
        for final_rank in range(1, cfg.team_count + 1)
    ]
    summary_by_team = forecast_summary.set_index("team_id").reindex(summary_team_ids)
    playoff_limit = cfg.playoff_qualifiers
    top4_limit = min(4, playoff_limit)
    expected_bands = np.column_stack(
        (
            pivot.loc[:, 1:playoff_limit].sum(axis=1),
            pivot.loc[:, 1:top4_limit].sum(axis=1),
            pivot.loc[:, 1:top4_limit].sum(axis=1),
            pivot.loc[:, playoff_limit + 1 : cfg.team_count].sum(axis=1),
        )
    )
    actual_bands = summary_by_team[
        [
            "playoff_probability",
            "top4_probability",
            "home_court_probability",
            "out_probability",
        ]
    ].to_numpy(dtype=float)
    if (
        not np.allclose(
            summary_by_team[exact_columns].to_numpy(dtype=float),
            pivot.to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-12,
        )
        or not np.allclose(
            actual_bands,
            expected_bands,
            rtol=0.0,
            atol=1e-12,
        )
    ):
        raise ValueError(
            "summary probability bands must match the exact-rank matrix"
        )


def _validate_simulation_state(
    *,
    final_wins: np.ndarray,
    final_losses: np.ndarray,
    final_point_differentials: np.ndarray,
    final_ranks: np.ndarray,
    simulated_home_margins: np.ndarray,
    cfg: SeasonConfig,
) -> None:
    if np.any(simulated_home_margins == 0):
        raise ValueError("simulated margins must be non-zero")
    if np.any(final_wins < 0) or np.any(final_losses < 0):
        raise ValueError("final wins and losses must be non-negative")
    games_played = final_wins + final_losses
    if not np.all(games_played == cfg.regular_season_games_per_team):
        raise ValueError(
            f"every final team must reach {cfg.regular_season_games_per_team} games"
        )
    if not np.all(final_point_differentials.sum(axis=1) == 0):
        raise ValueError(
            "league point differential must sum to zero in every run"
        )
    expected_ranks = np.arange(1, cfg.team_count + 1, dtype=np.int64)
    if not np.all(np.sort(final_ranks, axis=1) == expected_ranks):
        raise ValueError("every run must assign each exact rank once")


def simulate_season(
    completed_games: pd.DataFrame,
    scored_remaining: pd.DataFrame,
    cfg: SeasonConfig,
    *,
    simulation_count: int | None = None,
    seed: int = 0,
) -> SimulationResult:
    """Simulate remaining margins and aggregate final-rank probabilities."""

    count = cfg.simulation_count if simulation_count is None else simulation_count
    if (
        isinstance(count, bool)
        or not isinstance(count, (int, np.integer))
        or count <= 0
    ):
        raise ValueError("simulation_count must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise ValueError("seed must be an integer")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    if cfg.team_count <= 0:
        raise ValueError("team_count must be positive")
    if cfg.regular_season_games_per_team <= 0:
        raise ValueError("regular_season_games_per_team must be positive")
    if not 1 <= cfg.playoff_qualifiers <= cfg.team_count:
        raise ValueError("playoff_qualifiers must be between 1 and team_count")

    _require_columns(completed_games, _COMPLETED_COLUMNS, "completed_games")
    _require_columns(scored_remaining, _REMAINING_COLUMNS, "scored_remaining")
    completed_games = completed_games.copy()
    scored_remaining = scored_remaining.copy()
    for column in ("game_id", "team_id", "opponent_id"):
        completed_games[column] = completed_games[column].map(normalize_id)
    for column in ("game_id", "home_id", "away_id"):
        scored_remaining[column] = scored_remaining[column].map(normalize_id)
    _validate_identifiers(
        completed_games,
        name="completed_games",
        participant_columns=("team_id", "opponent_id"),
    )
    _validate_identifiers(
        scored_remaining,
        name="scored_remaining",
        participant_columns=("home_id", "away_id"),
    )
    _validate_game_ids(completed_games, scored_remaining)
    _validate_completed_results(completed_games)
    _validate_matchup_values(scored_remaining)

    team_ids = tuple(
        sorted(
            set(completed_games["team_id"])
            | set(completed_games["opponent_id"])
            | set(scored_remaining["home_id"])
            | set(scored_remaining["away_id"])
        )
    )
    if len(team_ids) != cfg.team_count:
        raise ValueError(
            f"simulation team universe has {len(team_ids)} teams; "
            f"expected {cfg.team_count}"
        )

    completed_counts = completed_games["team_id"].value_counts()
    remaining_counts = pd.concat(
        [scored_remaining["home_id"], scored_remaining["away_id"]],
        ignore_index=True,
    ).value_counts()
    total_counts = completed_counts.add(remaining_counts, fill_value=0).reindex(
        team_ids,
        fill_value=0,
    ).astype(int)
    count_mismatch = total_counts.ne(cfg.regular_season_games_per_team)
    if count_mismatch.any():
        count_text = ", ".join(
            f"{team_id}={total_counts.loc[team_id]}"
            for team_id in total_counts.index[count_mismatch]
        )
        raise ValueError(
            "completed plus remaining games do not equal "
            f"{cfg.regular_season_games_per_team} for every team: {count_text}"
        )

    game_ids = tuple(str(value) for value in scored_remaining["game_id"])
    rng = np.random.default_rng(seed)
    draws = rng.normal(
        loc=scored_remaining["expected_home_margin"].to_numpy(dtype=float),
        scale=scored_remaining["margin_sigma"].to_numpy(dtype=float),
        size=(count, len(game_ids)),
    )
    draw_nonnegative = draws >= 0
    np.rint(draws, out=draws)
    integer_bounds = np.iinfo(np.int32)
    if np.any(draws < integer_bounds.min) or np.any(draws > integer_bounds.max):
        raise ValueError("simulated margin exceeds supported integer range")
    simulated_home_margins = draws.astype(np.int32)
    rounded_zero = simulated_home_margins == 0
    simulated_home_margins[rounded_zero] = np.where(
        draw_nonnegative[rounded_zero],
        1,
        -1,
    )
    del draws, draw_nonnegative
    team_index = {team_id: index for index, team_id in enumerate(team_ids)}
    completed_wins = np.zeros(len(team_ids), dtype=np.int32)
    completed_losses = np.zeros(len(team_ids), dtype=np.int32)
    completed_point_differentials = np.zeros(len(team_ids), dtype=np.int64)
    for row in completed_games.itertuples(index=False):
        index = team_index[row.team_id]
        completed_wins[index] += int(row.win)
        completed_losses[index] += int(row.loss)
        completed_point_differentials[index] += int(row.margin)

    final_wins = np.broadcast_to(completed_wins, (count, len(team_ids))).copy()
    final_losses = np.broadcast_to(completed_losses, (count, len(team_ids))).copy()
    final_point_differentials = np.broadcast_to(
        completed_point_differentials,
        (count, len(team_ids)),
    ).copy()
    home_indices = np.array(
        [team_index[team_id] for team_id in scored_remaining["home_id"]],
        dtype=np.int64,
    )
    away_indices = np.array(
        [team_index[team_id] for team_id in scored_remaining["away_id"]],
        dtype=np.int64,
    )
    for game_index, (home_index, away_index) in enumerate(
        zip(home_indices, away_indices)
    ):
        home_margins = simulated_home_margins[:, game_index]
        home_wins = home_margins > 0
        final_wins[:, home_index] += home_wins
        final_losses[:, home_index] += ~home_wins
        final_wins[:, away_index] += ~home_wins
        final_losses[:, away_index] += home_wins
        final_point_differentials[:, home_index] += home_margins
        final_point_differentials[:, away_index] -= home_margins

    final_ranks = np.zeros((count, len(team_ids)), dtype=np.int32)
    completed_for_tiebreak = completed_games[
        ["game_id", "team_id", "opponent_id", "win", "loss", "margin"]
    ].copy()
    fallback_count = 0
    for simulation_index in range(count):
        margins = simulated_home_margins[simulation_index]
        home_wins = margins > 0
        simulated_games = pd.DataFrame(
            {
                "game_id": np.repeat(np.asarray(game_ids, dtype=object), 2),
                "team_id": np.column_stack(
                    (
                        scored_remaining["home_id"].to_numpy(),
                        scored_remaining["away_id"].to_numpy(),
                    )
                ).reshape(-1),
                "opponent_id": np.column_stack(
                    (
                        scored_remaining["away_id"].to_numpy(),
                        scored_remaining["home_id"].to_numpy(),
                    )
                ).reshape(-1),
                "win": np.column_stack((home_wins, ~home_wins)).reshape(-1).astype(int),
                "loss": np.column_stack((~home_wins, home_wins)).reshape(-1).astype(int),
                "margin": np.column_stack((margins, -margins)).reshape(-1),
            }
        )
        all_games = pd.concat(
            [completed_for_tiebreak, simulated_games],
            ignore_index=True,
        )
        final_state = pd.DataFrame(
            {
                "team_id": team_ids,
                "wins": final_wins[simulation_index],
                "losses": final_losses[simulation_index],
                "point_differential": final_point_differentials[simulation_index],
            }
        )
        ranking = rank_teams(final_state, all_games, cfg)
        fallback_count += ranking.fallback_count
        for final_rank, team_id in enumerate(ranking.ordered_team_ids, start=1):
            final_ranks[simulation_index, team_index[team_id]] = final_rank
    _validate_simulation_state(
        final_wins=final_wins,
        final_losses=final_losses,
        final_point_differentials=final_point_differentials,
        final_ranks=final_ranks,
        simulated_home_margins=simulated_home_margins,
        cfg=cfg,
    )

    arrays = (
        final_wins,
        final_losses,
        final_point_differentials,
        final_ranks,
        simulated_home_margins,
    )
    for array in arrays:
        array.setflags(write=False)

    forecast_summary, rank_probability_matrix = _build_probability_outputs(
        team_ids=team_ids,
        final_wins=final_wins,
        final_losses=final_losses,
        final_ranks=final_ranks,
        cfg=cfg,
    )
    _validate_probability_mass(forecast_summary, rank_probability_matrix, cfg)

    return SimulationResult(
        forecast_summary=forecast_summary,
        rank_probability_matrix=rank_probability_matrix,
        fallback_count=fallback_count,
        simulation_count=count,
        seed=seed,
        team_ids=team_ids,
        remaining_game_ids=game_ids,
        final_wins=final_wins,
        final_losses=final_losses,
        final_point_differentials=final_point_differentials,
        final_ranks=final_ranks,
        simulated_home_margins=simulated_home_margins,
    )
