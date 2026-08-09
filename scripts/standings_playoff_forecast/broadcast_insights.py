"""Deterministic, source-traceable broadcaster stories from forecast outputs."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import numpy as np
import pandas as pd

from .team_game_layer import normalize_id


INSIGHT_COLUMNS = [
    "priority",
    "category",
    "team_or_race",
    "data_point",
    "quick_read_snippet",
    "pregame_trigger",
    "halftime_checkpoint",
    "fourth_quarter_checkpoint",
    "why_it_matters",
    "source_fields",
]

DEFAULT_CATEGORIES = [
    "leader_race",
    "playoff_cutline",
    "top4_race",
    "tiebreak_watch",
    "remaining_sos",
    "most_likely_riser",
    "most_vulnerable_seed",
    "recent_form",
    "high_leverage_game",
    "historical_context",
]

_FORECAST_REQUIRED = {
    "team_id",
    "expected_final_rank",
    "playoff_probability",
    "top4_probability",
    "rank_1_probability",
}
_STANDINGS_REQUIRED = {"team_id", "current_rank", "wins", "losses"}
_STRENGTH_REQUIRED = {"team_id", "recent_net_rating"}
_REMAINING_REQUIRED = {
    "game_id",
    "home_id",
    "away_id",
    "home_win_probability",
    "away_win_probability",
}
_LEVERAGE_REQUIRED = {
    "game_id",
    "home_id",
    "away_id",
    "leverage_score",
    "leverage_label",
    "direct_h2h_tiebreak_flag",
    "cutline_matchup_flag",
    "top4_matchup_flag",
}
_HISTORY_REQUIRED = {
    "context_level",
    "metric",
    "season_count",
    "value",
    "sample_size",
    "availability_status",
}


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def _normalize(frame: pd.DataFrame, id_columns: Iterable[str], name: str) -> pd.DataFrame:
    result = frame.copy()
    columns = tuple(id_columns)
    for column in columns:
        result[column] = result[column].map(normalize_id)
    if result[list(columns)].isna().any().any() or result[list(columns)].eq("").any().any():
        raise ValueError(f"{name} contains missing or blank normalized identifiers")
    return result


def _numeric(frame: pd.DataFrame, columns: Iterable[str], name: str) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if not np.isfinite(result[list(columns)].to_numpy(dtype=float)).all():
        raise ValueError(f"{name} contains non-finite numeric values")
    return result


def _validate_inputs(
    forecast_summary: pd.DataFrame,
    current_standings: pd.DataFrame,
    team_strength: pd.DataFrame,
    scored_remaining: pd.DataFrame,
    game_leverage: pd.DataFrame,
    cfg: object,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    _require_columns(forecast_summary, _FORECAST_REQUIRED, "forecast_summary")
    _require_columns(current_standings, _STANDINGS_REQUIRED, "current_standings")
    _require_columns(team_strength, _STRENGTH_REQUIRED, "team_strength")
    _require_columns(scored_remaining, _REMAINING_REQUIRED, "scored_remaining")
    _require_columns(game_leverage, _LEVERAGE_REQUIRED, "game_leverage")
    forecast = _normalize(forecast_summary, ("team_id",), "forecast_summary")
    standings = _normalize(current_standings, ("team_id",), "current_standings")
    strength = _normalize(team_strength, ("team_id",), "team_strength")
    remaining = _normalize(
        scored_remaining, ("game_id", "home_id", "away_id"), "scored_remaining"
    )
    leverage = _normalize(game_leverage, ("game_id", "home_id", "away_id"), "game_leverage")
    for name, frame, key in (
        ("forecast_summary", forecast, "team_id"),
        ("current_standings", standings, "team_id"),
        ("team_strength", strength, "team_id"),
        ("scored_remaining", remaining, "game_id"),
        ("game_leverage", leverage, "game_id"),
    ):
        if frame[key].duplicated().any():
            raise ValueError(f"{name} contains duplicate normalized {key}")
    if not 1 <= cfg.playoff_qualifiers < cfg.team_count:
        raise ValueError("playoff_qualifiers must be below team_count")
    team_sets = [set(frame["team_id"]) for frame in (forecast, standings, strength)]
    if any(len(values) != cfg.team_count for values in team_sets) or not all(
        values == team_sets[0] for values in team_sets[1:]
    ):
        raise ValueError("forecast, standings, and strength team IDs must match configured teams")
    participants = set(remaining["home_id"]) | set(remaining["away_id"])
    if not participants.issubset(team_sets[0]) or remaining["home_id"].eq(remaining["away_id"]).any():
        raise ValueError("scored_remaining contains invalid participants")
    if tuple(leverage["game_id"]) != tuple(remaining["game_id"]):
        raise ValueError("game_leverage game order must match scored_remaining")
    if tuple(leverage[["home_id", "away_id"]].itertuples(index=False, name=None)) != tuple(
        remaining[["home_id", "away_id"]].itertuples(index=False, name=None)
    ):
        raise ValueError("game_leverage participants must match scored_remaining")

    forecast = _numeric(
        forecast,
        ("expected_final_rank", "playoff_probability", "top4_probability", "rank_1_probability"),
        "forecast_summary",
    )
    probability_columns = ["playoff_probability", "top4_probability", "rank_1_probability"]
    if not forecast[probability_columns].ge(0).all().all() or not forecast[probability_columns].le(1).all().all():
        raise ValueError("forecast_summary probabilities must be within [0, 1]")
    if not forecast["expected_final_rank"].between(1, cfg.team_count).all():
        raise ValueError("forecast_summary expected ranks must be valid")
    standings = _numeric(standings, ("current_rank", "wins", "losses"), "current_standings")
    if (
        standings["current_rank"].mod(1).ne(0).any()
        or set(standings["current_rank"].astype(int)) != set(range(1, cfg.team_count + 1))
        or standings[["wins", "losses"]].lt(0).any().any()
    ):
        raise ValueError("current_standings has invalid ranks or records")
    standings["current_rank"] = standings["current_rank"].astype(int)
    strength = _numeric(strength, ("recent_net_rating",), "team_strength")
    remaining = _numeric(
        remaining, ("home_win_probability", "away_win_probability"), "scored_remaining"
    )
    if (
        not remaining[["home_win_probability", "away_win_probability"]].ge(0).all().all()
        or not remaining[["home_win_probability", "away_win_probability"]].le(1).all().all()
        or not np.allclose(
            remaining["home_win_probability"] + remaining["away_win_probability"],
            1.0,
            rtol=0.0,
            atol=1e-12,
        )
    ):
        raise ValueError("scored_remaining probabilities must be complementary within [0, 1]")
    leverage = _numeric(leverage, ("leverage_score",), "game_leverage")
    if not leverage["leverage_score"].between(0, 100).all():
        raise ValueError("game_leverage scores must be within [0, 100]")
    if not leverage["leverage_label"].isin(("Critical", "High", "Moderate", "Low")).all():
        raise ValueError("game_leverage contains an invalid label")
    expected_labels = leverage["leverage_score"].map(_leverage_label)
    if not leverage["leverage_label"].eq(expected_labels).all():
        raise ValueError("game_leverage score-label threshold mismatch")
    flag_columns = (
        "direct_h2h_tiebreak_flag",
        "cutline_matchup_flag",
        "top4_matchup_flag",
    )
    strict_boolean = leverage[list(flag_columns)].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not strict_boolean.all().all():
        raise ValueError("game_leverage flags must contain strict boolean values")
    return forecast, standings, strength, remaining, leverage


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _leverage_label(score: float) -> str:
    if score >= 85:
        return "Critical"
    if score >= 65:
        return "High"
    if score >= 35:
        return "Moderate"
    return "Low"


def _story(
    *,
    category: str,
    team_or_race: str,
    data_point: str,
    quick_read: str,
    focus: str,
    why: str,
    sources: str,
) -> dict[str, object]:
    return {
        "category": category,
        "team_or_race": team_or_race,
        "data_point": data_point,
        "quick_read_snippet": quick_read,
        "pregame_trigger": f"Pregame: frame {focus} before tip.",
        "halftime_checkpoint": f"At halftime, note which side of {focus} the game state supports.",
        "fourth_quarter_checkpoint": f"Entering the fourth quarter, revisit {focus} if the result is still in play.",
        "why_it_matters": why,
        "source_fields": sources,
    }


def _stable_extreme(frame: pd.DataFrame, value: str, *, largest: bool = True) -> pd.Series:
    return frame.sort_values(
        [value, "team_id"], ascending=[not largest, True], kind="stable"
    ).iloc[0]


def _game_extreme(frame: pd.DataFrame, *, largest: bool) -> pd.Series | None:
    if frame.empty:
        return None
    return frame.sort_values(
        ["leverage_score", "game_id"], ascending=[not largest, True], kind="stable"
    ).iloc[0]


def _available_history(historical_context: pd.DataFrame | None) -> pd.Series | None:
    if historical_context is None or historical_context.empty:
        return None
    _require_columns(historical_context, _HISTORY_REQUIRED, "historical_context")
    available = historical_context.loc[
        historical_context["availability_status"].eq("available")
        & historical_context["context_level"].eq("aggregate")
    ].copy()
    if available.empty:
        return None
    available = _numeric(available, ("season_count", "value", "sample_size"), "historical_context")
    preferred = {
        "same_progress_playoff_rate": 0,
        "final_qualifier_wins": 1,
        "final_cutline_gap_wins": 2,
    }
    available["metric_priority"] = available["metric"].map(preferred).fillna(99)
    return available.sort_values(["metric_priority", "metric"], kind="stable").iloc[0]


def build_broadcast_insights(
    forecast_summary: pd.DataFrame,
    current_standings: pd.DataFrame,
    team_strength: pd.DataFrame,
    scored_remaining: pd.DataFrame,
    game_leverage: pd.DataFrame,
    cfg: object,
    *,
    historical_context: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build exactly ten deterministic stories without calling or prompting an LLM."""

    forecast, standings, strength, remaining, leverage = _validate_inputs(
        forecast_summary,
        current_standings,
        team_strength,
        scored_remaining,
        game_leverage,
        cfg,
    )
    joined = standings.merge(forecast, on="team_id", validate="one_to_one")
    stories: list[dict[str, object]] = []

    leader = _stable_extreme(forecast, "rank_1_probability")
    stories.append(
        _story(
            category="leader_race",
            team_or_race=leader.team_id,
            data_point=f"{leader.team_id} rank-1 probability: {_pct(leader.rank_1_probability)}",
            quick_read=f"{leader.team_id} owns the strongest simulated path to the top seed.",
            focus=f"{leader.team_id}'s top-seed path",
            why="The top seed sets the headline for the remaining regular-season race.",
            sources="forecast_summary.team_id, forecast_summary.rank_1_probability",
        )
    )

    qualifier = standings.loc[standings["current_rank"].eq(cfg.playoff_qualifiers)].iloc[0]
    first_out = standings.loc[standings["current_rank"].eq(cfg.playoff_qualifiers + 1)].iloc[0]
    q_forecast = forecast.set_index("team_id")
    cutline_name = f"{qualifier.team_id} / {first_out.team_id}"
    stories.append(
        _story(
            category="playoff_cutline",
            team_or_race=cutline_name,
            data_point=(
                f"Rank {cfg.playoff_qualifiers} {qualifier.team_id}: "
                f"{_pct(q_forecast.loc[qualifier.team_id, 'playoff_probability'])}; "
                f"rank {cfg.playoff_qualifiers + 1} {first_out.team_id}: "
                f"{_pct(q_forecast.loc[first_out.team_id, 'playoff_probability'])}"
            ),
            quick_read=f"{qualifier.team_id} and {first_out.team_id} define the current playoff cutline.",
            focus=f"the {cutline_name} cutline split",
            why="One team is currently in the configured playoff field and the other is first out.",
            sources="current_standings.current_rank, forecast_summary.playoff_probability, config.playoff_qualifiers",
        )
    )

    top4_limit = min(4, cfg.playoff_qualifiers)
    top4_in = standings.loc[standings["current_rank"].eq(top4_limit)].iloc[0]
    top4_out = standings.loc[standings["current_rank"].eq(top4_limit + 1)].iloc[0]
    top4_name = f"{top4_in.team_id} / {top4_out.team_id}"
    stories.append(
        _story(
            category="top4_race",
            team_or_race=top4_name,
            data_point=(
                f"Rank {top4_limit} {top4_in.team_id}: "
                f"{_pct(q_forecast.loc[top4_in.team_id, 'top4_probability'])}; "
                f"rank {top4_limit + 1} {top4_out.team_id}: "
                f"{_pct(q_forecast.loc[top4_out.team_id, 'top4_probability'])}"
            ),
            quick_read=f"{top4_name} is the current top-four boundary.",
            focus=f"the {top4_name} top-four boundary",
            why="A top-four finish carries the forecast's home-court significance.",
            sources="current_standings.current_rank, forecast_summary.top4_probability, config.playoff_qualifiers",
        )
    )

    direct = leverage.loc[leverage["direct_h2h_tiebreak_flag"].astype(bool)]
    tiebreak_game = _game_extreme(direct, largest=True)
    if tiebreak_game is not None:
        tiebreak_data = f"{tiebreak_game.game_id}: {tiebreak_game.home_id} vs {tiebreak_game.away_id}"
        tiebreak_name = f"{tiebreak_game.home_id} / {tiebreak_game.away_id}"
        tiebreak_sources = "game_leverage.game_id, game_leverage.home_id, game_leverage.away_id, game_leverage.direct_h2h_tiebreak_flag"
    else:
        pairs = []
        records = standings.sort_values("team_id", kind="stable")
        for left_index in range(len(records)):
            for right_index in range(left_index + 1, len(records)):
                left = records.iloc[left_index]
                right = records.iloc[right_index]
                left_gp = left.wins + left.losses
                right_gp = right.wins + right.losses
                left_pct = left.wins / left_gp if left_gp else 0.0
                right_pct = right.wins / right_gp if right_gp else 0.0
                pairs.append((abs(left_pct - right_pct), left.team_id, right.team_id))
        _, left_id, right_id = min(pairs)
        tiebreak_name = f"{left_id} / {right_id}"
        tiebreak_data = f"Closest current records: {left_id} and {right_id}"
        tiebreak_sources = "current_standings.team_id, current_standings.wins, current_standings.losses"
    stories.append(
        _story(
            category="tiebreak_watch",
            team_or_race=tiebreak_name,
            data_point=tiebreak_data,
            quick_read=f"Keep {tiebreak_name} on the tiebreak board.",
            focus=f"the {tiebreak_name} tiebreak implication",
            why="The configured standings rules use direct results before deterministic fallback when records tie.",
            sources=tiebreak_sources + ", config.tiebreaks",
        )
    )

    opponents: dict[str, list[str]] = defaultdict(list)
    for game in remaining.itertuples(index=False):
        opponents[game.home_id].append(game.away_id)
        opponents[game.away_id].append(game.home_id)
    playoff_by_team = forecast.set_index("team_id")["playoff_probability"]
    sos_rows = [
        {"team_id": team_id, "opponent_playoff_probability_mean": float(np.mean([playoff_by_team.loc[opponent] for opponent in opponent_ids]))}
        for team_id, opponent_ids in opponents.items()
    ]
    if sos_rows:
        sos = _stable_extreme(pd.DataFrame(sos_rows), "opponent_playoff_probability_mean")
        sos_data = f"{sos.team_id} average remaining-opponent playoff probability: {_pct(sos.opponent_playoff_probability_mean)}"
        sos_name = sos.team_id
        sos_quick = f"{sos.team_id} has the strongest remaining-opponent forecast profile."
    else:
        sos_data = "No remaining games; remaining-opponent sample size is 0."
        sos_name = "League schedule"
        sos_quick = "The configured remaining schedule is complete."
    stories.append(
        _story(
            category="remaining_sos",
            team_or_race=sos_name,
            data_point=sos_data,
            quick_read=sos_quick,
            focus="the remaining opponent profile",
            why="Opponent playoff probability gives a transparent schedule-strength lens without changing the forecast.",
            sources="scored_remaining.home_id, scored_remaining.away_id, forecast_summary.playoff_probability",
        )
    )

    joined["projected_rise"] = joined["current_rank"] - joined["expected_final_rank"]
    riser = _stable_extreme(joined, "projected_rise")
    stories.append(
        _story(
            category="most_likely_riser",
            team_or_race=riser.team_id,
            data_point=f"{riser.team_id} projected rank movement: {riser.projected_rise:+.2f}",
            quick_read=f"{riser.team_id} has the largest current-rank to expected-rank rise.",
            focus=f"{riser.team_id}'s upward seed path",
            why="The comparison identifies the largest forecast rise without rerunning the model.",
            sources="current_standings.current_rank, forecast_summary.expected_final_rank",
        )
    )

    playoff_seeds = joined.loc[joined["current_rank"].le(cfg.playoff_qualifiers)].copy()
    playoff_seeds["projected_drop"] = playoff_seeds["expected_final_rank"] - playoff_seeds["current_rank"]
    vulnerable = _stable_extreme(playoff_seeds, "projected_drop")
    stories.append(
        _story(
            category="most_vulnerable_seed",
            team_or_race=vulnerable.team_id,
            data_point=f"{vulnerable.team_id} projected rank movement: {vulnerable.projected_drop:+.2f}",
            quick_read=f"{vulnerable.team_id} has the largest projected drop among current playoff seeds.",
            focus=f"{vulnerable.team_id}'s seed defense",
            why="The current seed is more favorable than its simulation-average final rank.",
            sources="current_standings.current_rank, forecast_summary.expected_final_rank, config.playoff_qualifiers",
        )
    )

    recent = _stable_extreme(strength, "recent_net_rating")
    stories.append(
        _story(
            category="recent_form",
            team_or_race=recent.team_id,
            data_point=f"{recent.team_id} recent Net Rating: {recent.recent_net_rating:+.2f}",
            quick_read=f"{recent.team_id} has the best supplied recent-form rating.",
            focus=f"whether {recent.team_id}'s recent form carries into this game",
            why="Recent Net Rating is the cutoff-safe form indicator supplied by the strength layer.",
            sources="team_strength.team_id, team_strength.recent_net_rating",
        )
    )

    high_game = _game_extreme(leverage, largest=True)
    if high_game is None:
        high_name = "League schedule"
        high_data = "No remaining games; high-leverage game sample size is 0."
        high_quick = "There is no remaining game to rank for leverage."
    else:
        high_name = f"{high_game.home_id} / {high_game.away_id}"
        high_data = f"{high_game.game_id}: leverage {high_game.leverage_score:.1f} ({high_game.leverage_label})"
        high_quick = f"{high_game.game_id} is the highest normalized leverage game."
    stories.append(
        _story(
            category="high_leverage_game",
            team_or_race=high_name,
            data_point=high_data,
            quick_read=high_quick,
            focus="the highest supplied game-leverage implication",
            why="The score combines conditional playoff, top-four, rank, and configured boundary stakes.",
            sources="game_leverage.game_id, game_leverage.leverage_score, game_leverage.leverage_label",
        )
    )

    history = _available_history(historical_context)
    if history is not None:
        history_data = f"{history.metric}: {history.value:.3f} across {int(history.season_count)} seasons (n={int(history.sample_size)})"
        stories.append(
            _story(
                category="historical_context",
                team_or_race="Historical benchmark",
                data_point=history_data,
                quick_read="The available prior-season aggregate supplies descriptive context only.",
                focus=f"the {history.metric} historical benchmark",
                why="The benchmark contextualizes the current race without entering the simulation.",
                sources="historical_context.metric, historical_context.value, historical_context.season_count, historical_context.sample_size, historical_context.availability_status",
            )
        )
    else:
        if high_game is None:
            schedule_name = "League schedule"
            schedule_data = "No remaining games; the configured schedule is complete."
            schedule_quick = "Use the completed-schedule state instead of unavailable history."
            schedule_sources = "scored_remaining.game_id"
        elif len(leverage) == 1:
            schedule_name = "League schedule"
            schedule_data = (
                "Remaining schedule contains 1 game; no distinct second matchup "
                "is available."
            )
            schedule_quick = (
                "The sole remaining matchup already owns the high-leverage slot; "
                "this story reports schedule concentration."
            )
            schedule_sources = "scored_remaining.game_id"
        else:
            schedule_game = _game_extreme(
                leverage.loc[leverage["game_id"].ne(high_game.game_id)],
                largest=False,
            )
            schedule_name = f"{schedule_game.home_id} / {schedule_game.away_id}"
            schedule_data = f"{schedule_game.game_id}: {schedule_game.home_id} vs {schedule_game.away_id}, leverage {schedule_game.leverage_score:.1f}"
            schedule_quick = f"{schedule_game.game_id} is a second, distinct schedule watch after the top leverage game."
            schedule_sources = "game_leverage.game_id, game_leverage.home_id, game_leverage.away_id, game_leverage.leverage_score"
        stories.append(
            _story(
                category="schedule_watch",
                team_or_race=schedule_name,
                data_point=schedule_data,
                quick_read=schedule_quick,
                focus="the secondary schedule or tiebreak angle",
                why="Unavailable historical context is replaced with a supplied current-schedule story.",
                sources=schedule_sources,
            )
        )

    if len(stories) != 10:
        raise RuntimeError("broadcast insight selector must emit exactly ten stories")
    for priority, story in enumerate(stories, start=1):
        story["priority"] = priority
    result = pd.DataFrame(stories).reindex(columns=INSIGHT_COLUMNS)
    if result["priority"].duplicated().any() or result[INSIGHT_COLUMNS[1:]].isna().any().any():
        raise RuntimeError("broadcast insight output violated its stable contract")
    return result
