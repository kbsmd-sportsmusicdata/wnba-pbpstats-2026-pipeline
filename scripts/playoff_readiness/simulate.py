"""Playing the rest of the season, many times over.

Every remaining game is simulated as a margin drawn around what the rating model expects,
the resulting records are seeded through the WNBA tiebreak ladder, and the bracket is
played out. Everything the module reports -- seed probabilities, per-game leverage, odds
of surviving round one -- comes out of the same set of simulated seasons, which is what
keeps them mutually consistent.

Two implementation notes worth knowing:

* **Ratings are redrawn per simulation**, not fixed at the point estimate. Uncertainty
  about how good a team *is* dominates uncertainty about any single game once a bubble
  race gets tight, and ignoring it is what makes naive models announce 96% when they mean
  something closer to 80%.
* **Seed leverage is conditional, not re-simulated.** Because each simulation records the
  outcome of every remaining game, the swing a single game creates is the difference
  between two conditional means within one simulation set. That is both exact for the set
  and roughly a hundred times cheaper than re-running the season twice per game.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .ratings import RatingFit, sample_ratings, win_probability
from .schedule import LEAGUE_TEAMS, WNBA_CONFERENCES

PLAYOFF_TEAMS = 8

# Higher seed hosts, in the WNBA's 2-2-1 style pattern per round. True means the higher
# seed is at home for that game. Overridable from config as the league adjusts formats.
DEFAULT_SERIES_FORMATS = {
    "first_round": [True, True, False],
    "semifinals": [True, True, False, False, True],
    "finals": [True, True, False, False, True, False, True],
}

ROUND_LABELS = {0: "missed_playoffs", 1: "lost_first_round", 2: "lost_semifinals", 3: "lost_finals", 4: "champion"}


@dataclass
class SimulationResult:
    teams: List[str]
    simulations: int
    wins: np.ndarray  # (sims, teams)
    point_differential: np.ndarray  # (sims, teams)
    seeds: np.ndarray  # (sims, teams), 1 = best record
    outcomes: np.ndarray  # (sims, remaining games), 1 when the home team won
    finish: np.ndarray  # (sims, teams), see ROUND_LABELS
    remaining: pd.DataFrame

    def made_playoffs(self) -> np.ndarray:
        return self.seeds <= PLAYOFF_TEAMS


def _team_index(teams: Sequence[str]) -> Dict[str, int]:
    return {team: index for index, team in enumerate(teams)}


def season_state(
    results: pd.DataFrame,
    *,
    teams: Sequence[str] = LEAGUE_TEAMS,
    conferences: Optional[Dict[str, str]] = None,
) -> Dict[str, np.ndarray]:
    """Wins, point differential, head-to-head and conference record as of today."""
    teams = list(teams)
    lookup = _team_index(teams)
    conferences = conferences or WNBA_CONFERENCES
    count = len(teams)

    state = {
        "wins": np.zeros(count),
        "point_differential": np.zeros(count),
        "head_to_head": np.zeros((count, count)),
        "conference_wins": np.zeros(count),
        "conference_games": np.zeros(count),
    }
    if results.empty:
        return state

    for _, row in results.iterrows():
        team = lookup.get(row["team"])
        opponent = lookup.get(row["opponent"])
        if team is None or opponent is None:
            continue
        won = bool(row["won"])
        state["wins"][team] += float(won)
        state["point_differential"][team] += float(row["margin"])
        if won:
            state["head_to_head"][team, opponent] += 1.0
        if conferences.get(row["team"]) == conferences.get(row["opponent"]):
            state["conference_games"][team] += 1.0
            state["conference_wins"][team] += float(won)
    return state


def rank_teams(
    wins: np.ndarray,
    head_to_head: np.ndarray,
    conference_wins: np.ndarray,
    conference_games: np.ndarray,
    point_differential: np.ndarray,
    jitter: np.ndarray,
) -> np.ndarray:
    """Seeds from the WNBA tiebreak ladder, vectorised across simulations.

    The league's published ladder is, in order: head-to-head record, winning percentage
    within one's own conference, then further splits against playoff-eligible teams, then
    point differential. This implements the first two rungs, skips the playoff-eligible
    splits -- they are circular to evaluate mid-simulation, since eligibility is what is
    being decided -- and falls through to point differential. A seeded random jitter
    settles anything still level, which is what a coin flip does in reality and keeps the
    result from depending on alphabetical order.

    Head-to-head is measured against exactly the teams a team is tied with, which matches
    the rule for two-team ties and is the natural reading for larger ones.
    """
    tied = wins[:, :, None] == wins[:, None, :]
    head_to_head_wins = (head_to_head * tied).sum(axis=2)
    head_to_head_games = ((head_to_head + head_to_head.transpose(0, 2, 1)) * tied).sum(axis=2)
    head_to_head_pct = np.where(head_to_head_games > 0, head_to_head_wins / np.maximum(head_to_head_games, 1e-9), 0.5)
    conference_pct = np.where(conference_games > 0, conference_wins / np.maximum(conference_games, 1e-9), 0.5)

    # lexsort takes the last key as the most significant and sorts ascending, so the
    # ordering below reads bottom-up: wins, then head-to-head, then conference, then
    # differential, then the coin flip.
    order = np.lexsort((jitter, point_differential, conference_pct, head_to_head_pct, wins), axis=-1)
    descending = order[:, ::-1]
    seeds = np.empty_like(descending)
    rows = np.arange(descending.shape[0])[:, None]
    seeds[rows, descending] = np.arange(1, descending.shape[1] + 1)[None, :]
    return seeds


def simulate_remaining(
    results: pd.DataFrame,
    remaining: pd.DataFrame,
    fit: RatingFit,
    *,
    simulations: int,
    seed: int,
    teams: Sequence[str] = LEAGUE_TEAMS,
    conferences: Optional[Dict[str, str]] = None,
    series_formats: Optional[Dict[str, List[bool]]] = None,
) -> SimulationResult:
    """Simulate every unplayed game, seed the league, and play the bracket."""
    teams = list(teams)
    conferences = conferences or WNBA_CONFERENCES
    lookup = _team_index(teams)
    count = len(teams)
    rng = np.random.default_rng(seed)

    # float32 throughout the (sims x teams x teams) head-to-head cube: every value is a
    # small integer count, and float64 would triple the peak footprint of the tiebreak
    # step for nothing.
    state = season_state(results, teams=teams, conferences=conferences)
    wins = np.tile(state["wins"], (simulations, 1)).astype(np.float32)
    differential = np.tile(state["point_differential"], (simulations, 1)).astype(np.float32)
    head_to_head = np.tile(state["head_to_head"], (simulations, 1, 1)).astype(np.float32)
    conference_wins = np.tile(state["conference_wins"], (simulations, 1)).astype(np.float32)
    conference_games = np.tile(state["conference_games"], (simulations, 1)).astype(np.float32)

    ratings, home_advantage = sample_ratings(fit, simulations, rng)
    residual_sd = fit.residual_sd if np.isfinite(fit.residual_sd) and fit.residual_sd > 0 else 1.0

    outcomes = np.zeros((simulations, len(remaining)), dtype=np.uint8)
    for position, (_, game) in enumerate(remaining.iterrows()):
        home = lookup[game["home_team"]]
        away = lookup[game["away_team"]]
        edge = 0.0 if bool(game.get("neutral_site", False)) else home_advantage
        margin = ratings[:, home] - ratings[:, away] + edge + rng.normal(0.0, residual_sd, simulations)
        home_won = margin > 0
        outcomes[:, position] = home_won

        wins[:, home] += home_won
        wins[:, away] += ~home_won
        differential[:, home] += margin
        differential[:, away] -= margin
        head_to_head[:, home, away] += home_won
        head_to_head[:, away, home] += ~home_won
        if conferences.get(game["home_team"]) == conferences.get(game["away_team"]):
            conference_games[:, home] += 1
            conference_games[:, away] += 1
            conference_wins[:, home] += home_won
            conference_wins[:, away] += ~home_won

    jitter = rng.random((simulations, count))
    seeds = rank_teams(wins, head_to_head, conference_wins, conference_games, differential, jitter)
    finish = simulate_bracket(
        seeds, ratings, home_advantage, residual_sd, rng, formats=series_formats or DEFAULT_SERIES_FORMATS
    )

    return SimulationResult(
        teams=teams,
        simulations=simulations,
        wins=wins,
        point_differential=differential,
        seeds=seeds,
        outcomes=outcomes,
        finish=finish,
        remaining=remaining.reset_index(drop=True),
    )


def series_win_probability(game_probabilities: np.ndarray) -> np.ndarray:
    """Probability the favoured side takes the series, given per-game win probabilities.

    `game_probabilities` is `(sims, games)` in scheduled order. A short dynamic program
    over the running score handles any odd series length, which matters because the WNBA
    has changed its round formats twice in five years.
    """
    length = game_probabilities.shape[1]
    needed = length // 2 + 1
    distribution: Dict[Tuple[int, int], np.ndarray] = {(0, 0): np.ones(game_probabilities.shape[0])}
    for game in range(length):
        nxt: Dict[Tuple[int, int], np.ndarray] = {}
        probability = game_probabilities[:, game]
        for (won, lost), mass in distribution.items():
            if won >= needed or lost >= needed:
                nxt[(won, lost)] = nxt.get((won, lost), 0.0) + mass
                continue
            nxt[(won + 1, lost)] = nxt.get((won + 1, lost), 0.0) + mass * probability
            nxt[(won, lost + 1)] = nxt.get((won, lost + 1), 0.0) + mass * (1.0 - probability)
        distribution = nxt
    return sum(mass for (won, _), mass in distribution.items() if won >= needed)


def _series_winner(
    higher: np.ndarray,
    lower: np.ndarray,
    ratings: np.ndarray,
    home_advantage: np.ndarray,
    residual_sd: float,
    pattern: Sequence[bool],
    rng: np.random.Generator,
) -> np.ndarray:
    """Simulate one round: returns the winning team index per simulation."""
    rows = np.arange(ratings.shape[0])
    gap = ratings[rows, higher] - ratings[rows, lower]
    probabilities = np.empty((ratings.shape[0], len(pattern)))
    for game, higher_at_home in enumerate(pattern):
        edge = home_advantage if higher_at_home else -home_advantage
        probabilities[:, game] = win_probability(gap + edge, residual_sd)
    higher_wins = rng.random(ratings.shape[0]) < series_win_probability(probabilities)
    return np.where(higher_wins, higher, lower)


def simulate_bracket(
    seeds: np.ndarray,
    ratings: np.ndarray,
    home_advantage: np.ndarray,
    residual_sd: float,
    rng: np.random.Generator,
    *,
    formats: Dict[str, List[bool]],
) -> np.ndarray:
    """Play the eight-team bracket and record how far each team got.

    Seeding is league-wide rather than by conference, which is how the WNBA has bracketed
    since 2016: 1v8, 2v7, 3v6, 4v5, and the higher surviving seed advances into the higher
    half of the draw.
    """
    simulations, count = seeds.shape
    finish = np.zeros((simulations, count), dtype=np.uint8)

    order = np.argsort(seeds, axis=1)  # order[:, k] is the team holding seed k+1
    bracket = order[:, :PLAYOFF_TEAMS]
    rows = np.arange(simulations)
    finish[rows[:, None], bracket] = 1

    first_round = formats.get("first_round", DEFAULT_SERIES_FORMATS["first_round"])
    semifinals = formats.get("semifinals", DEFAULT_SERIES_FORMATS["semifinals"])
    finals = formats.get("finals", DEFAULT_SERIES_FORMATS["finals"])

    quarter_winners = [
        _series_winner(bracket[:, high], bracket[:, low], ratings, home_advantage, residual_sd, first_round, rng)
        for high, low in ((0, 7), (3, 4), (1, 6), (2, 5))
    ]
    finish[rows, quarter_winners[0]] = 2
    finish[rows, quarter_winners[1]] = 2
    finish[rows, quarter_winners[2]] = 2
    finish[rows, quarter_winners[3]] = 2

    semi_pairs = ((0, 1), (2, 3))
    semi_winners = []
    for left, right in semi_pairs:
        first, second = quarter_winners[left], quarter_winners[right]
        higher = np.where(seeds[rows, first] <= seeds[rows, second], first, second)
        lower = np.where(seeds[rows, first] <= seeds[rows, second], second, first)
        semi_winners.append(
            _series_winner(higher, lower, ratings, home_advantage, residual_sd, semifinals, rng)
        )
    finish[rows, semi_winners[0]] = 3
    finish[rows, semi_winners[1]] = 3

    first, second = semi_winners
    higher = np.where(seeds[rows, first] <= seeds[rows, second], first, second)
    lower = np.where(seeds[rows, first] <= seeds[rows, second], second, first)
    champion = _series_winner(higher, lower, ratings, home_advantage, residual_sd, finals, rng)
    finish[rows, champion] = 4
    return finish


def clinch_flags(standings: pd.DataFrame, *, playoff_teams: int = PLAYOFF_TEAMS) -> pd.DataFrame:
    """Arithmetic clinching and elimination, kept separate from the simulation.

    A probability of 1.0000 over twenty thousand runs is not the same claim as "cannot be
    caught", and conflating the two is how a model ends up eliminating a team that is
    still alive. These are the certainties:

    * **Eliminated** when at least `playoff_teams` other teams already have more wins than
      this team could reach by winning out.
    * **Clinched** when at most `playoff_teams - 1` other teams could still reach this
      team's current win total.

    Both ignore the fact that remaining games are shared between teams, so they are
    conservative -- they will confirm a clinch a little later than the league does, never
    earlier.
    """
    if standings.empty:
        return pd.DataFrame(columns=["team_abbreviation", "clinched_playoffs", "eliminated"])

    rows: List[Dict[str, Any]] = []
    for _, team in standings.iterrows():
        others = standings[standings["team_abbreviation"] != team["team_abbreviation"]]
        guaranteed_ahead = int((others["wins"] > team["max_possible_wins"]).sum())
        could_pass = int((others["max_possible_wins"] >= team["wins"]).sum())
        rows.append(
            {
                "team_abbreviation": team["team_abbreviation"],
                "clinched_playoffs": bool(could_pass <= playoff_teams - 1),
                "eliminated": bool(guaranteed_ahead >= playoff_teams),
            }
        )
    return pd.DataFrame(rows)


def summarize(simulation: SimulationResult, standings: pd.DataFrame) -> pd.DataFrame:
    """Per-team odds: playoffs, each seed, and how far the bracket takes them."""
    teams = simulation.teams
    seeds = simulation.seeds
    rows: List[Dict[str, Any]] = []
    current = standings.set_index("team_abbreviation") if not standings.empty else pd.DataFrame()
    flags = clinch_flags(standings).set_index("team_abbreviation") if not standings.empty else pd.DataFrame()

    for index, team in enumerate(teams):
        team_seeds = seeds[:, index]
        finish = simulation.finish[:, index]
        record = {
            "team_abbreviation": team,
            "current_seed": int(current.loc[team, "current_seed"]) if team in current.index else None,
            "wins": int(current.loc[team, "wins"]) if team in current.index else None,
            "losses": int(current.loc[team, "losses"]) if team in current.index else None,
            "games_remaining": int(current.loc[team, "games_remaining"]) if team in current.index else None,
            "projected_wins": round(float(simulation.wins[:, index].mean()), 2),
            "projected_wins_p10": float(np.percentile(simulation.wins[:, index], 10)),
            "projected_wins_p90": float(np.percentile(simulation.wins[:, index], 90)),
            "projected_seed": round(float(team_seeds.mean()), 2),
            "p_playoffs": round(float((team_seeds <= PLAYOFF_TEAMS).mean()), 4),
            "p_top_four": round(float((team_seeds <= 4).mean()), 4),
            "p_top_two": round(float((team_seeds <= 2).mean()), 4),
            "p_top_seed": round(float((team_seeds == 1).mean()), 4),
            "p_advance_first_round": round(float((finish >= 2).mean()), 4),
            "p_reach_finals": round(float((finish >= 3).mean()), 4),
            "p_title": round(float((finish == 4).mean()), 4),
        }
        record["clinched_playoffs"] = bool(flags.loc[team, "clinched_playoffs"]) if team in flags.index else False
        record["eliminated"] = bool(flags.loc[team, "eliminated"]) if team in flags.index else False
        record["status"] = _status(record["p_playoffs"], record["clinched_playoffs"], record["eliminated"])
        rows.append(record)

    board = pd.DataFrame(rows).sort_values(["p_playoffs", "projected_wins"], ascending=False)
    return board.reset_index(drop=True)


def _status(probability: float, clinched: bool, eliminated: bool) -> str:
    """Arithmetic certainty first, then what the simulation says. The two are different
    claims and the label says which one it is."""
    if clinched:
        return "Clinched"
    if eliminated:
        return "Eliminated"
    if probability >= 0.99:
        return "Effectively in"
    if probability >= 0.85:
        return "Comfortable"
    if probability >= 0.35:
        return "Bubble"
    if probability >= 0.02:
        return "Long shot"
    return "Effectively out"


def seed_distribution(simulation: SimulationResult) -> pd.DataFrame:
    """Long-format probability of finishing in each seed, ready to plot."""
    rows: List[Dict[str, Any]] = []
    for index, team in enumerate(simulation.teams):
        counts = np.bincount(simulation.seeds[:, index], minlength=len(simulation.teams) + 1)
        for seed in range(1, len(simulation.teams) + 1):
            rows.append(
                {
                    "team_abbreviation": team,
                    "seed": seed,
                    "probability": round(float(counts[seed] / simulation.simulations), 5),
                }
            )
    return pd.DataFrame(rows)


def game_leverage(simulation: SimulationResult) -> pd.DataFrame:
    """How much each unplayed game moves each participant's odds.

    Leverage is `P(outcome | this team wins) - P(outcome | this team loses)`, both
    measured inside the same simulation set. It answers the question a broadcast actually
    asks -- which of tonight's games matters most -- and it is the cleanest way to rank
    the run-in for a team fighting for the last seed.
    """
    if simulation.remaining.empty:
        return pd.DataFrame(
            columns=["game_id", "game_date", "team_abbreviation", "opponent", "is_home", "playoff_leverage", "top_four_leverage"]
        )

    lookup = _team_index(simulation.teams)
    made = simulation.made_playoffs()
    top_four = simulation.seeds <= 4
    rows: List[Dict[str, Any]] = []

    for position, (_, game) in enumerate(simulation.remaining.iterrows()):
        home_won = simulation.outcomes[:, position].astype(bool)
        for team, opponent, is_home in (
            (game["home_team"], game["away_team"], True),
            (game["away_team"], game["home_team"], False),
        ):
            index = lookup[team]
            won = home_won if is_home else ~home_won
            if won.all() or (~won).all():
                playoff_leverage = top_four_leverage = np.nan
            else:
                playoff_leverage = float(made[won, index].mean() - made[~won, index].mean())
                top_four_leverage = float(top_four[won, index].mean() - top_four[~won, index].mean())
            rows.append(
                {
                    "game_id": game["game_id"],
                    "game_date": game["game_date"].date().isoformat() if pd.notna(game["game_date"]) else None,
                    "team_abbreviation": team,
                    "opponent": opponent,
                    "is_home": is_home,
                    "playoff_leverage": round(playoff_leverage, 4) if np.isfinite(playoff_leverage) else None,
                    "top_four_leverage": round(top_four_leverage, 4) if np.isfinite(top_four_leverage) else None,
                }
            )

    leverage = pd.DataFrame(rows)
    leverage["leverage_rank"] = leverage["playoff_leverage"].abs().rank(ascending=False, method="min")
    return leverage.sort_values(["game_date", "game_id"]).reset_index(drop=True)


def magic_numbers(standings: pd.DataFrame, *, playoff_teams: int = PLAYOFF_TEAMS) -> pd.DataFrame:
    """The classic magic and tragic numbers, against the team on the wrong side of the cut.

    Exact clinching across fifteen teams is a combinatorial problem that the simulation
    already answers probabilistically; these are the arithmetic version a reader can check
    by hand. The magic number is measured against the current ninth seed, so it says "this
    many combined wins and ninth-place losses settles it against *that* team", not against
    the whole field.
    """
    if standings.empty:
        return pd.DataFrame(columns=["team_abbreviation", "magic_number", "tragic_number", "reference_team"])

    ordered = standings.sort_values("current_seed").reset_index(drop=True)
    inside = ordered.iloc[: playoff_teams]
    outside = ordered.iloc[playoff_teams:]
    first_out = outside.iloc[0] if not outside.empty else None
    last_in = inside.iloc[-1] if not inside.empty else None

    rows: List[Dict[str, Any]] = []
    for _, team in ordered.iterrows():
        if last_in is None or first_out is None:
            rows.append({"team_abbreviation": team["team_abbreviation"], "magic_number": None, "tragic_number": None, "reference_team": None})
            continue
        inside_cut = team["current_seed"] <= playoff_teams
        reference = first_out if inside_cut else last_in
        if team["team_abbreviation"] == reference["team_abbreviation"]:
            reference = outside.iloc[1] if inside_cut and len(outside) > 1 else reference
        magic = int(reference["max_possible_wins"] - team["wins"] + 1)
        tragic = int(team["max_possible_wins"] - reference["wins"] + 1)
        rows.append(
            {
                "team_abbreviation": team["team_abbreviation"],
                "magic_number": max(magic, 0) if inside_cut else None,
                "tragic_number": max(tragic, 0) if not inside_cut else None,
                "reference_team": reference["team_abbreviation"],
            }
        )
    return pd.DataFrame(rows)
