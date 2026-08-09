"""Season-configured deterministic standings tiebreaks."""

from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Iterable

import pandas as pd

from .team_game_layer import normalize_id


@dataclass(frozen=True)
class TiebreakResult:
    """Ordered stable team IDs plus deterministic non-official fallback uses."""

    ordered_team_ids: tuple[str, ...]
    fallback_count: int = 0


CriterionScore = Fraction | int
Criterion = Callable[
    [tuple[str, ...], pd.DataFrame, pd.DataFrame],
    dict[str, CriterionScore],
]


def head_to_head_win_pct(
    team_ids: tuple[str, ...],
    final_team_state: pd.DataFrame,
    all_games: pd.DataFrame,
) -> dict[str, Fraction]:
    """Return each tied team's win percentage against the tied group."""

    del final_team_state
    tied = set(team_ids)
    group_games = all_games.loc[
        all_games["team_id"].isin(tied) & all_games["opponent_id"].isin(tied)
    ]
    scores: dict[str, Fraction] = {}
    for team_id in team_ids:
        team_games = group_games.loc[group_games["team_id"].eq(team_id)]
        scores[team_id] = Fraction(int(team_games["win"].sum()), len(team_games) or 1)
    return scores


def record_vs_final_500_plus(
    team_ids: tuple[str, ...],
    final_team_state: pd.DataFrame,
    all_games: pd.DataFrame,
) -> dict[str, Fraction]:
    """Return each tied team's record against teams finishing at least .500."""

    games_played = final_team_state["wins"] + final_team_state["losses"]
    final_500_plus = set(
        final_team_state.loc[
            games_played.gt(0)
            & final_team_state["wins"].mul(2).ge(games_played),
            "team_id",
        ]
    )
    qualifying_games = all_games.loc[all_games["opponent_id"].isin(final_500_plus)]
    scores: dict[str, Fraction] = {}
    for team_id in team_ids:
        team_games = qualifying_games.loc[qualifying_games["team_id"].eq(team_id)]
        scores[team_id] = Fraction(int(team_games["win"].sum()), len(team_games) or 1)
    return scores


def head_to_head_point_diff(
    team_ids: tuple[str, ...],
    final_team_state: pd.DataFrame,
    all_games: pd.DataFrame,
) -> dict[str, int]:
    """Return point differential within the tied group."""

    del final_team_state
    tied = set(team_ids)
    group_games = all_games.loc[
        all_games["team_id"].isin(tied) & all_games["opponent_id"].isin(tied)
    ]
    return {
        team_id: int(group_games.loc[group_games["team_id"].eq(team_id), "margin"].sum())
        for team_id in team_ids
    }


def overall_point_diff(
    team_ids: tuple[str, ...],
    final_team_state: pd.DataFrame,
    all_games: pd.DataFrame,
) -> dict[str, int]:
    """Return overall final point differential for each tied team."""

    del all_games
    point_differential = final_team_state.set_index("team_id")["point_differential"]
    return {team_id: int(point_differential.loc[team_id]) for team_id in team_ids}


CRITERIA = {
    "head_to_head_win_pct": head_to_head_win_pct,
    "record_vs_final_500_plus": record_vs_final_500_plus,
    "head_to_head_point_diff": head_to_head_point_diff,
    "overall_point_diff": overall_point_diff,
}


def _configured_criteria(cfg: object) -> tuple[Criterion, ...]:
    names = tuple(cfg.tiebreaks)
    unknown = sorted(set(names).difference(CRITERIA))
    if unknown:
        raise ValueError(f"unknown configured tiebreak criteria: {', '.join(unknown)}")
    if not names:
        raise ValueError("configured tiebreak criteria must not be empty")
    return tuple(CRITERIA[name] for name in names)


def _normalized_state(final_team_state: pd.DataFrame) -> pd.DataFrame:
    required = {"team_id", "wins", "losses"}
    missing = sorted(required.difference(final_team_state.columns))
    if missing:
        raise ValueError(
            f"final_team_state is missing required columns: {', '.join(missing)}"
        )

    normalized = final_team_state.copy()
    normalized["team_id"] = normalized["team_id"].map(normalize_id)
    if normalized["team_id"].isna().any():
        raise ValueError("final_team_state contains missing team_id")
    duplicate_ids = normalized.loc[
        normalized["team_id"].duplicated(keep=False), "team_id"
    ].drop_duplicates()
    if not duplicate_ids.empty:
        raise ValueError(
            "final_team_state contains duplicate normalized team_id: "
            + ", ".join(duplicate_ids)
        )
    for column in ("wins", "losses", "point_differential"):
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="raise")
    return normalized


def _normalized_games(all_games: pd.DataFrame) -> pd.DataFrame:
    required = {"game_id", "team_id", "opponent_id"}
    missing = sorted(required.difference(all_games.columns))
    if missing:
        raise ValueError(
            f"all_games is missing required columns: {', '.join(missing)}"
        )

    normalized = all_games.copy()
    for column in ("game_id", "team_id", "opponent_id"):
        normalized[column] = normalized[column].map(normalize_id)
    if normalized[["game_id", "team_id", "opponent_id"]].isna().any().any():
        raise ValueError("all_games contains missing game or team identifiers")

    duplicate_rows = normalized.duplicated(["game_id", "team_id"], keep=False)
    if duplicate_rows.any():
        duplicates = normalized.loc[duplicate_rows, ["game_id", "team_id"]]
        duplicate_text = ", ".join(
            f"{row.game_id}/{row.team_id}"
            for row in duplicates.drop_duplicates().itertuples(index=False)
        )
        raise ValueError(f"duplicate directional all-games rows: {duplicate_text}")
    return normalized


def _resolve_at_criterion(
    team_ids: tuple[str, ...],
    final_team_state: pd.DataFrame,
    all_games: pd.DataFrame,
    criteria: tuple[Criterion, ...],
    criterion_index: int,
    restart_after_elimination: bool,
) -> TiebreakResult:
    if len(team_ids) < 2:
        return TiebreakResult(team_ids)
    if criterion_index >= len(criteria):
        return TiebreakResult(tuple(sorted(team_ids)), fallback_count=1)

    scores = criteria[criterion_index](team_ids, final_team_state, all_games)
    score_groups: dict[object, list[str]] = {}
    for team_id in team_ids:
        score_groups.setdefault(scores[team_id], []).append(team_id)

    if len(score_groups) == 1:
        return _resolve_at_criterion(
            team_ids,
            final_team_state,
            all_games,
            criteria,
            criterion_index + 1,
            restart_after_elimination,
        )

    ordered: list[str] = []
    fallback_count = 0
    for score in sorted(score_groups, reverse=True):
        subgroup = tuple(score_groups[score])
        next_index = 0 if restart_after_elimination else criterion_index + 1
        resolved = _resolve_at_criterion(
            subgroup,
            final_team_state,
            all_games,
            criteria,
            next_index,
            restart_after_elimination,
        )
        ordered.extend(resolved.ordered_team_ids)
        fallback_count += resolved.fallback_count
    return TiebreakResult(tuple(ordered), fallback_count)


def resolve_tied_group(
    team_ids: Iterable[object],
    final_team_state: pd.DataFrame,
    all_games: pd.DataFrame,
    cfg: object,
) -> TiebreakResult:
    """Resolve teams that share the same final record."""

    criteria = _configured_criteria(cfg)
    state = _normalized_state(final_team_state)
    normalized_team_ids = tuple(normalize_id(team_id) for team_id in team_ids)
    normalized_games = _normalized_games(all_games)
    return _resolve_at_criterion(
        normalized_team_ids,
        state,
        normalized_games,
        criteria,
        0,
        cfg.multi_team_restart_after_elimination,
    )


def rank_teams(
    final_team_state: pd.DataFrame,
    all_games: pd.DataFrame,
    cfg: object,
) -> TiebreakResult:
    """Rank the supplied final team state by record, then configured criteria."""

    criteria = _configured_criteria(cfg)
    state = _normalized_state(final_team_state)
    record_groups: dict[Fraction, list[str]] = {}
    for row in state.itertuples(index=False):
        games_played = int(row.wins + row.losses)
        record = Fraction(int(row.wins), games_played or 1)
        record_groups.setdefault(record, []).append(row.team_id)

    ordered: list[str] = []
    fallback_count = 0
    normalized_games: pd.DataFrame | None = None
    for record in sorted(record_groups, reverse=True):
        team_ids = tuple(record_groups[record])
        if len(team_ids) == 1:
            ordered.extend(team_ids)
            continue
        if normalized_games is None:
            normalized_games = _normalized_games(all_games)
        resolved = _resolve_at_criterion(
            team_ids,
            state,
            normalized_games,
            criteria,
            0,
            cfg.multi_team_restart_after_elimination,
        )
        ordered.extend(resolved.ordered_team_ids)
        fallback_count += resolved.fallback_count
    return TiebreakResult(tuple(ordered), fallback_count)
