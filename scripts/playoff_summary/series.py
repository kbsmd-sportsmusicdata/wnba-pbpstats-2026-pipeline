"""Pure series-rollup transforms. No network, no filesystem.

Groups the playoff games spine into series (one row per unordered team pair) and rolls up games
played, each side's wins and points, pace, and the game-id list. Works mid-series: it reflects the
games played so far, so a best-of-N series in progress shows its partial state.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

import pandas as pd


def _norm_id(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def series_rollups(games: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """One row per playoff series (unordered team pair), from the games-dimension rows.

    Accepts the snake_case games spine (``game_id``, ``home_team_id``, ``home_points`` ...). The two
    teams are ordered deterministically by id (``team_a`` < ``team_b``) so the pairing is stable.
    """
    buckets: dict = {}
    for game in games:
        home = _norm_id(game.get("home_team_id") or game.get("HomeTeamId"))
        away = _norm_id(game.get("away_team_id") or game.get("AwayTeamId"))
        if home is None or away is None:
            continue
        home_abbr = game.get("home_team_abbreviation") or game.get("HomeTeamAbbreviation")
        away_abbr = game.get("away_team_abbreviation") or game.get("AwayTeamAbbreviation")
        hp = _num(game.get("home_points") if "home_points" in game else game.get("HomePoints"))
        ap = _num(game.get("away_points") if "away_points" in game else game.get("AwayPoints"))
        hposs = _num(game.get("home_possessions") if "home_possessions" in game else game.get("HomePossessions"))
        aposs = _num(game.get("away_possessions") if "away_possessions" in game else game.get("AwayPossessions"))
        gid = _norm_id(game.get("game_id") or game.get("GameId"))

        # Order the pair by id so (A,B) and (B,A) collapse to one series.
        if home <= away:
            a_id, a_abbr, a_pts, a_poss = home, home_abbr, hp, hposs
            b_id, b_abbr, b_pts, b_poss = away, away_abbr, ap, aposs
        else:
            a_id, a_abbr, a_pts, a_poss = away, away_abbr, ap, aposs
            b_id, b_abbr, b_pts, b_poss = home, home_abbr, hp, hposs

        s = buckets.setdefault(
            (a_id, b_id),
            {
                "team_a_id": a_id, "team_a_abbreviation": a_abbr,
                "team_b_id": b_id, "team_b_abbreviation": b_abbr,
                "games_played": 0, "team_a_wins": 0, "team_b_wins": 0,
                "team_a_points_total": 0.0, "team_b_points_total": 0.0,
                "possessions_total": 0.0, "possessions_games": 0, "game_ids": [],
            },
        )
        s["team_a_abbreviation"] = s["team_a_abbreviation"] or a_abbr
        s["team_b_abbreviation"] = s["team_b_abbreviation"] or b_abbr
        s["games_played"] += 1
        if gid is not None:
            s["game_ids"].append(gid)
        if a_pts is not None:
            s["team_a_points_total"] += a_pts
        if b_pts is not None:
            s["team_b_points_total"] += b_pts
        if a_pts is not None and b_pts is not None:
            if a_pts > b_pts:
                s["team_a_wins"] += 1
            elif b_pts > a_pts:
                s["team_b_wins"] += 1
        if a_poss is not None and b_poss is not None:
            s["possessions_total"] += (a_poss + b_poss) / 2.0
            s["possessions_games"] += 1

    records: List[dict] = []
    for s in buckets.values():
        gp = s["games_played"]
        avg_poss = (s["possessions_total"] / s["possessions_games"]) if s["possessions_games"] else None
        if s["team_a_wins"] > s["team_b_wins"]:
            leader = s["team_a_abbreviation"]
        elif s["team_b_wins"] > s["team_a_wins"]:
            leader = s["team_b_abbreviation"]
        else:
            leader = None
        records.append(
            {
                "team_a_id": s["team_a_id"], "team_a_abbreviation": s["team_a_abbreviation"],
                "team_b_id": s["team_b_id"], "team_b_abbreviation": s["team_b_abbreviation"],
                "games_played": gp,
                "team_a_wins": s["team_a_wins"], "team_b_wins": s["team_b_wins"],
                "series_leader": leader,
                "team_a_points_total": s["team_a_points_total"], "team_b_points_total": s["team_b_points_total"],
                "team_a_margin_total": s["team_a_points_total"] - s["team_b_points_total"],
                "avg_possessions": avg_poss,
                "game_ids": ";".join(s["game_ids"]),
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    return frame.sort_values(["team_a_id", "team_b_id"]).reset_index(drop=True)
