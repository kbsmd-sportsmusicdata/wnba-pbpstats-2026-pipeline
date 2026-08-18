"""Arithmetic clinching and elimination, deliberately kept out of the simulation.

A playoff probability of 1.0000 over a hundred thousand runs is not the claim "cannot be
caught", and conflating the two is how a forecast ends up eliminating a team that is still
alive. These flags are counting arguments over the games that remain, and they hold
whatever the simulation happens to draw:

* **Eliminated** when at least ``playoff_qualifiers`` other teams already have more wins
  than this team could reach by winning out. Every one of those teams finishes strictly
  ahead on wins, so no tiebreak can rescue it.
* **Clinched** when at most ``playoff_qualifiers - 1`` other teams could still reach this
  team's *current* win total. Every other team finishes strictly below it even if it loses
  out, so no tiebreak can cost it the seed.

Both tests ignore the fact that remaining games are shared between teams -- a game between
two rivals must produce a winner, which the exact formulation exploits. That makes these
**conservative**: they confirm a clinch or an elimination no earlier than the league does,
and never earlier. Exactly resolving the shared-schedule case is the classic baseball
elimination problem, which is a max-flow computation for first place and NP-hard for a
general top-``k`` cut, so the conservative bound is what is published and what is claimed.

``verify_against_simulation`` closes the loop the other way: arithmetic certainty and the
simulation must never disagree. A team proved eliminated with a non-zero playoff
probability, or proved clinched with a probability below one, means one of the two is
wrong, and the build stops rather than publish both.
"""

import math

import pandas as pd

from .contracts import SeasonConfig
from .team_game_layer import normalize_id


CLINCH_COLUMNS = (
    "clinched_playoffs",
    "eliminated_from_playoffs",
    "status_note",
)

STATUS_CLINCHED = "clinched_playoffs"
STATUS_ELIMINATED = "eliminated_from_playoffs"
STATUS_IN_CONTENTION = "in_contention"

_SCHEDULE_COUNT_COLUMNS = {"team_id", "remaining_games"}
_STANDINGS_COLUMNS = {"team_id", "wins"}


def _validated_wins(standings: pd.DataFrame, cfg: SeasonConfig) -> pd.Series:
    """Wins as clean non-negative integers, indexed by normalized team id."""

    missing = sorted(_STANDINGS_COLUMNS.difference(standings.columns))
    if missing:
        raise ValueError(
            "current standings is missing required columns: " + ", ".join(missing)
        )
    frame = standings.loc[:, ["team_id", "wins"]].copy()
    frame["team_id"] = frame["team_id"].map(normalize_id)
    if frame["team_id"].isna().any() or frame["team_id"].eq("").any():
        raise ValueError("current standings has an invalid team universe")
    if frame["team_id"].duplicated().any():
        raise ValueError("current standings has an invalid team universe")
    if len(frame) != cfg.team_count:
        raise ValueError(
            "current standings team universe failed: "
            f"expected {cfg.team_count} teams; observed {len(frame)}"
        )
    # Booleans are numeric to pandas and would silently pass the range checks below.
    if frame["wins"].map(pd.api.types.is_bool).any():
        raise ValueError("current standings has invalid wins")
    wins = pd.to_numeric(frame["wins"], errors="coerce")
    invalid = (
        wins.isna()
        | ~wins.map(math.isfinite)
        | wins.lt(0)
        | wins.gt(cfg.regular_season_games_per_team)
        | wins.mod(1).ne(0)
    )
    if invalid.any():
        raise ValueError("current standings has invalid wins")
    return pd.Series(wins.astype(int).to_numpy(), index=frame["team_id"], name="wins")


def _validated_remaining(
    season_schedule_counts: pd.DataFrame, team_ids: pd.Index, cfg: SeasonConfig
) -> pd.Series:
    """Remaining games per team, from the frame the schedule validator already checked."""

    missing = sorted(_SCHEDULE_COUNT_COLUMNS.difference(season_schedule_counts.columns))
    if missing:
        raise ValueError(
            "season schedule counts is missing required columns: " + ", ".join(missing)
        )
    frame = season_schedule_counts.loc[:, ["team_id", "remaining_games"]].copy()
    frame["team_id"] = frame["team_id"].map(normalize_id)
    if frame["team_id"].duplicated().any():
        raise ValueError("season schedule counts has a duplicate team universe")
    remaining = pd.to_numeric(frame["remaining_games"], errors="coerce")
    invalid = (
        remaining.isna()
        | ~remaining.map(math.isfinite)
        | remaining.lt(0)
        | remaining.gt(cfg.regular_season_games_per_team)
        | remaining.mod(1).ne(0)
    )
    if invalid.any():
        raise ValueError("season schedule counts has invalid remaining_games")
    series = pd.Series(remaining.astype(int).to_numpy(), index=frame["team_id"])
    unknown = sorted(set(series.index).difference(team_ids))
    if unknown:
        raise ValueError(
            "season schedule counts has unknown team IDs: " + ", ".join(unknown)
        )
    # A team can legitimately be absent once it has no games left to play.
    return series.reindex(team_ids).fillna(0).astype(int)


def attach_clinch_status(
    standings: pd.DataFrame,
    season_schedule_counts: pd.DataFrame,
    cfg: SeasonConfig,
) -> pd.DataFrame:
    """Return ``standings`` with the three status columns filled in.

    The columns are appended rather than folded into ``STANDINGS_COLUMNS`` so the output
    layer picks them up through the path it already has for extra standings columns, and
    they travel into ``forecast_summary`` from there.
    """

    result = standings.copy()
    wins = _validated_wins(result, cfg)
    remaining = _validated_remaining(season_schedule_counts, wins.index, cfg)
    qualifiers = int(cfg.playoff_qualifiers)
    if qualifiers < 1 or qualifiers > cfg.team_count:
        raise ValueError(
            "playoff_qualifiers must fall between 1 and the configured team count"
        )

    max_possible = wins + remaining
    clinched: dict[str, bool] = {}
    eliminated: dict[str, bool] = {}
    for team_id in wins.index:
        others = wins.index.drop(team_id)
        # Teams whose current wins already exceed this team's best case finish ahead of
        # it no matter what either side does from here.
        guaranteed_ahead = int((wins[others] > max_possible[team_id]).sum())
        # Teams that could still reach this team's worst case, and so could pass it.
        could_pass = int((max_possible[others] >= wins[team_id]).sum())
        eliminated[team_id] = guaranteed_ahead >= qualifiers
        clinched[team_id] = could_pass <= qualifiers - 1

    keys = result["team_id"].map(normalize_id)
    result["clinched_playoffs"] = keys.map(clinched).astype(bool)
    result["eliminated_from_playoffs"] = keys.map(eliminated).astype(bool)
    contradictory = result["clinched_playoffs"] & result["eliminated_from_playoffs"]
    if contradictory.any():
        # Unreachable given the two tests above; asserted because publishing a team as
        # both clinched and eliminated would be worse than failing the build.
        raise ValueError("a team cannot be both clinched and eliminated")
    result["status_note"] = STATUS_IN_CONTENTION
    result.loc[result["clinched_playoffs"], "status_note"] = STATUS_CLINCHED
    result.loc[result["eliminated_from_playoffs"], "status_note"] = STATUS_ELIMINATED
    return result


def verify_against_simulation(
    standings: pd.DataFrame, forecast_summary: pd.DataFrame
) -> None:
    """Fail closed when the proof and the simulation disagree.

    Both read the same schedule, so the two are checkable against each other in one
    direction only. A proved elimination forces a zero probability and a proved clinch
    forces a one; the converse does not hold, because the bound is conservative and a team
    can sit at 0.0000 over the sampled seasons while still being alive on paper. Only the
    contradictions are errors.
    """

    # This is a consistency check between two computed things, so it has nothing to say
    # when either side is absent. A forecast summary genuinely missing its probabilities
    # is rejected by `_validate_probability_outputs`, which requires both columns before
    # anything is written -- so skipping here loses no safety and keeps the check usable
    # by callers that assemble a partial summary.
    if not {"team_id", "playoff_probability"}.issubset(forecast_summary.columns):
        return
    if not set(CLINCH_COLUMNS).issubset(standings.columns):
        return

    probability = pd.Series(
        pd.to_numeric(forecast_summary["playoff_probability"], errors="coerce").to_numpy(),
        index=forecast_summary["team_id"].map(normalize_id),
    )
    keys = standings["team_id"].map(normalize_id)
    aligned = keys.map(probability)

    impossible = standings["eliminated_from_playoffs"] & aligned.gt(0.0)
    if impossible.any():
        teams = ", ".join(sorted(keys[impossible].astype(str)))
        raise ValueError(
            "teams proved eliminated hold a non-zero simulated playoff probability: "
            f"{teams}"
        )
    certain = standings["clinched_playoffs"] & aligned.lt(1.0)
    if certain.any():
        teams = ", ".join(sorted(keys[certain].astype(str)))
        raise ValueError(
            "teams proved clinched hold a simulated playoff probability below one: "
            f"{teams}"
        )
