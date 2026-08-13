"""Whether a team is built for the games that come after the eighty-second day.

Odds say who will be there. This says something different: whether what a team does well
is the kind of thing that survives a playoff series. Two lenses, because the question is
genuinely different at the two ends of the table.

**Contenders** are asked whether their edge holds when the game slows down and the
rotation shortens: half-court efficiency separated from transition, results against the
teams they will actually face, how much they gain by shortening the bench, what happens in
the last five minutes, and how wide their game-to-game spread is.

**Bubble teams** are asked about the run-in: what is left on the schedule, where the
leverage sits, whether recent form is moving, and whether their style is the kind that
travels into a series if they get there.

There is deliberately **no fitted composite**. The playoffs have not happened, so there is
nothing to fit weights against, and inventing them would dress judgement up as evidence.
`readiness_index` is a plain equal-weight average of the tier's components, published as a
convenient ordering and labelled as one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .schedule import LEAGUE_TEAMS, team_key

# Possessions that begin after a made basket, a dead ball or a timeout start against a
# defence that is already set. The other two start types -- a defensive rebound or a live
# ball turnover -- are where transition lives. It is a proxy, not a tracking-derived
# transition flag, but it is the split the possession feed actually supports.
SET_DEFENCE_START_TYPES = frozenset({"OffMadeShot", "OffDeadball", "OffTimeout"})

CONTENDER_COMPONENTS = [
    ("set_net_rating", True),
    ("quality_gap", True),
    ("bench_dropoff", True),
    ("rotation_concentration", True),
    ("clutch_net_rating_shrunk", True),
    ("margin_sd", False),
]

BUBBLE_COMPONENTS = [
    ("p_playoffs", True),
    ("remaining_difficulty", False),
    ("remaining_home_share", True),
    ("form_delta", True),
    ("set_net_rating", True),
]

# Clutch net rating comes off 110 to 370 possessions a team. Left raw it swings by fifty
# points and would dominate an equal-weight average; shrunk toward zero in proportion to
# the sample it rests on, it says what it can support and no more.
CLUTCH_SHRINKAGE_POSSESSIONS = 250.0


def percentile(series: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if not higher_is_better:
        values = -values
    if values.notna().sum() <= 1:
        return pd.Series(np.where(values.notna(), 50.0, np.nan), index=series.index)
    return values.rank(pct=True, method="average") * 100


def result_metrics(
    results: pd.DataFrame,
    playoff_field: Sequence[str],
    *,
    expected_margin: Optional[pd.Series] = None,
    recent_games: int = 10,
) -> pd.DataFrame:
    """Quality of opposition, spread, and recent form -- all from the game log.

    `quality_gap` needs care. The obvious version -- margin against the playoff field minus
    overall margin -- is negative for all fifteen teams by construction, because the
    playoff field is the strong half of the league and every team does worse against it.
    It measures schedule, not quality.

    The version here is the residual one: **actual margin minus the margin the rating model
    expected**, over games against the playoff field only. Because a fitted team's
    residuals sum to roughly zero across its whole schedule, a positive value means a team
    saves its better performances for the games that resemble a playoff series -- the
    interaction an additive rating model cannot express, which is exactly the part worth
    reporting separately.
    """
    field = set(playoff_field)
    residual = None
    if expected_margin is not None and not results.empty:
        residual = results["margin"].to_numpy(dtype=float) - expected_margin.reindex(results.index).to_numpy(dtype=float)

    rows: List[Dict[str, Any]] = []
    for team in LEAGUE_TEAMS:
        mask = results["team"] == team if not results.empty else pd.Series(dtype=bool)
        played = results[mask]
        if played.empty:
            rows.append({"team_abbreviation": team})
            continue
        against_field_mask = played["opponent"].isin(field - {team})
        against_field = played[against_field_mask]
        against_rest = played[~against_field_mask]
        recent = played.sort_values("game_date").tail(recent_games)
        close = played[played["margin"].abs() <= 5]
        overall = float(played["margin"].mean())

        quality_gap = np.nan
        if residual is not None and against_field_mask.any():
            team_residual = pd.Series(residual[mask.to_numpy()], index=played.index)
            quality_gap = float(team_residual[against_field_mask].mean())

        rows.append(
            {
                "team_abbreviation": team,
                "margin_per_game": round(overall, 3),
                "margin_sd": round(float(played["margin"].std(ddof=1)), 3) if len(played) > 1 else np.nan,
                "games_vs_playoff_field": int(len(against_field)),
                "margin_vs_playoff_field": round(float(against_field["margin"].mean()), 3) if not against_field.empty else np.nan,
                "margin_vs_rest": round(float(against_rest["margin"].mean()), 3) if not against_rest.empty else np.nan,
                "quality_gap": round(quality_gap, 3) if np.isfinite(quality_gap) else np.nan,
                "recent_margin_per_game": round(float(recent["margin"].mean()), 3),
                "form_delta": round(float(recent["margin"].mean()) - overall, 3),
                "close_games": int(len(close)),
                "close_game_win_pct": round(float(close["won"].mean()), 3) if not close.empty else np.nan,
                "home_margin": round(float(played.loc[played["is_home"], "margin"].mean()), 3) if played["is_home"].any() else np.nan,
                "road_margin": round(float(played.loc[~played["is_home"], "margin"].mean()), 3) if (~played["is_home"]).any() else np.nan,
            }
        )
    return pd.DataFrame(rows)


def style_metrics(possessions: pd.DataFrame, game_logs: pd.DataFrame) -> pd.DataFrame:
    """Half-court efficiency separated from early offence, from possession start types.

    Playoff basketball is slower and more set. A team whose edge sits in early offence is
    relying on the part of the game a series takes away first, and the gap between the two
    splits is the single most useful style read available from this feed.
    """
    columns = [
        "team_abbreviation",
        "set_off_rating",
        "set_def_rating",
        "set_net_rating",
        "early_off_rating",
        "early_def_rating",
        "early_net_rating",
        "set_possession_share",
        "transition_reliance",
        "possession_games",
    ]
    if possessions.empty or "possession_start_type" not in possessions.columns:
        return pd.DataFrame(columns=columns)

    labels = team_labels(game_logs)
    frame = possessions
    if "count_as_possession" in frame.columns:
        frame = frame[frame["count_as_possession"].astype(bool)]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    frame = frame.assign(is_set=frame["possession_start_type"].isin(SET_DEFENCE_START_TYPES))
    offense = _split_ratings(frame, "offense_team_id")
    defense = _split_ratings(frame, "defense_team_id")
    games = frame.groupby("offense_team_id")["game_id"].nunique()

    table = pd.DataFrame(
        {
            "set_off_rating": offense["set_rating"],
            "early_off_rating": offense["early_rating"],
            "set_def_rating": defense["set_rating"],
            "early_def_rating": defense["early_rating"],
            "set_possession_share": offense["set_share"],
            "possession_games": games,
        }
    )
    table["set_net_rating"] = (table["set_off_rating"] - table["set_def_rating"]).round(2)
    table["early_net_rating"] = (table["early_off_rating"] - table["early_def_rating"]).round(2)
    # How much of a team's edge comes from the part of the game a series suppresses.
    table["transition_reliance"] = (table["early_net_rating"] - table["set_net_rating"]).round(2)
    table = table.round(2).reset_index().rename(columns={"index": "team_id", "offense_team_id": "team_id"})
    table["team_abbreviation"] = table["team_id"].map(labels)
    return table.dropna(subset=["team_abbreviation"])[columns].reset_index(drop=True)


def _split_ratings(frame: pd.DataFrame, side: str) -> pd.DataFrame:
    grouped = frame.groupby([side, "is_set"]).agg(possessions=("points", "size"), points=("points", "sum"))
    grouped["rating"] = 100.0 * grouped["points"] / grouped["possessions"]
    rating = grouped["rating"].unstack("is_set")
    possessions = grouped["possessions"].unstack("is_set").fillna(0.0)
    return pd.DataFrame(
        {
            "set_rating": rating.get(True),
            "early_rating": rating.get(False),
            "set_share": possessions.get(True, 0.0) / possessions.sum(axis=1).replace(0, np.nan),
        }
    )


def rotation_metrics(player_box: pd.DataFrame, *, recent_games: int = 10, core: int = 7) -> pd.DataFrame:
    """How short a team's rotation already is, from the recent box scores.

    Playoff rotations compress toward eight players. A team already distributing minutes
    that way is closer to the shape it will play in a series; a team spreading them over
    eleven has a change still to make. Measured over the last `recent_games` because a
    rotation in August is not the rotation from May.

    This is the unconfounded half of the rotation picture. `bench_dropoff` is the other
    half -- how much better the starters are -- and it carries a real caveat: starters-only
    possessions cluster at the openings of periods, when the opposing starters are also on
    the floor, so the split is partly a statement about who a unit faced. Neither metric
    settles the question alone, which is why both are reported.
    """
    columns = ["team_abbreviation", "rotation_concentration", "rotation_players", "rotation_games"]
    if player_box.empty or not {"team_abbreviation", "minutes", "game_id"}.issubset(player_box.columns):
        return pd.DataFrame(columns=columns)

    frame = player_box.copy()
    frame["team_abbreviation"] = frame["team_abbreviation"].map(team_key)
    frame = frame[frame["team_abbreviation"].isin(LEAGUE_TEAMS)]
    frame["minutes"] = pd.to_numeric(frame["minutes"], errors="coerce")
    frame = frame.dropna(subset=["minutes"])
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame["game_date"] = pd.to_datetime(frame.get("game_date").astype(str), errors="coerce")

    player_column = "athlete_id" if "athlete_id" in frame.columns else "athlete_display_name"
    rows: List[Dict[str, Any]] = []
    for team, games in frame.groupby("team_abbreviation"):
        recent_ids = (
            games.groupby("game_id")["game_date"].max().sort_values().tail(recent_games).index
        )
        window = games[games["game_id"].isin(recent_ids)]
        minutes = window.groupby(player_column)["minutes"].sum().sort_values(ascending=False)
        played = len(recent_ids)
        if minutes.sum() <= 0 or played == 0:
            continue
        rows.append(
            {
                "team_abbreviation": team,
                "rotation_concentration": round(float(minutes.head(core).sum() / minutes.sum()), 4),
                "rotation_players": int((minutes / played >= 10).sum()),
                "rotation_games": played,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def team_labels(game_logs: pd.DataFrame) -> Dict[Any, str]:
    """team_id to canonical abbreviation, from the feed that carries both."""
    if game_logs.empty or not {"team_id", "team_abbreviation"}.issubset(game_logs.columns):
        return {}
    pairs = game_logs[["team_id", "team_abbreviation"]].drop_duplicates()
    return {row["team_id"]: team_key(row["team_abbreviation"]) for _, row in pairs.iterrows()}


def possession_coverage(possessions: pd.DataFrame, game_logs: pd.DataFrame) -> Optional[str]:
    """Last game date the possession feed reflects. It lags, so the lag is published."""
    if possessions.empty or game_logs.empty or "game_date" not in game_logs.columns:
        return None
    covered = set(possessions["game_id"].astype(str))
    dates = pd.to_datetime(
        game_logs.loc[game_logs["game_id"].astype(str).isin(covered), "game_date"], errors="coerce"
    ).dropna()
    return dates.max().date().isoformat() if not dates.empty else None


def remaining_schedule_metrics(
    remaining: pd.DataFrame,
    ratings: pd.Series,
    *,
    home_advantage: float,
    playoff_field: Sequence[str],
) -> pd.DataFrame:
    """What is left: who, where, and how compressed.

    `remaining_opponent_rating` is the plain average opponent strength. The adjusted
    version nets out home advantage, which is the number that actually predicts the run-in
    -- a hard schedule mostly at home is not a hard schedule.
    """
    columns = [
        "team_abbreviation",
        "games_remaining",
        "remaining_home_games",
        "remaining_home_share",
        "remaining_opponent_rating",
        "remaining_difficulty",
        "remaining_vs_playoff_field",
        "remaining_back_to_backs",
    ]
    if remaining.empty:
        return pd.DataFrame(columns=columns)

    field = set(playoff_field)
    rows: List[Dict[str, Any]] = []
    for team in LEAGUE_TEAMS:
        home = remaining[remaining["home_team"] == team]
        away = remaining[remaining["away_team"] == team]
        opponents = pd.concat([home["away_team"], away["home_team"]])
        if opponents.empty:
            rows.append({"team_abbreviation": team, "games_remaining": 0})
            continue
        opponent_rating = opponents.map(ratings).astype(float)
        # Difficulty is the expected margin the team concedes: opponent strength less the
        # home edge where they hold it.
        difficulty = pd.concat(
            [
                home["away_team"].map(ratings).astype(float) - home_advantage,
                away["home_team"].map(ratings).astype(float) + home_advantage,
            ]
        )
        dates = pd.concat([home["game_date"], away["game_date"]]).sort_values()
        gaps = dates.diff().dt.days
        rows.append(
            {
                "team_abbreviation": team,
                "games_remaining": int(len(opponents)),
                "remaining_home_games": int(len(home)),
                "remaining_home_share": round(float(len(home) / len(opponents)), 3),
                "remaining_opponent_rating": round(float(opponent_rating.mean()), 3),
                "remaining_difficulty": round(float(difficulty.mean()), 3),
                "remaining_vs_playoff_field": int(opponents.isin(field - {team}).sum()),
                "remaining_back_to_backs": int((gaps == 1).sum()),
            }
        )
    return pd.DataFrame(rows)


def leverage_totals(leverage: pd.DataFrame) -> pd.DataFrame:
    """How much of a team's season is still genuinely undecided."""
    columns = ["team_abbreviation", "total_playoff_leverage", "total_seeding_leverage", "peak_game_leverage"]
    if leverage.empty:
        return pd.DataFrame(columns=columns)
    grouped = leverage.groupby("team_abbreviation").agg(
        total_playoff_leverage=("playoff_leverage", lambda s: float(np.nansum(np.abs(s)))),
        total_seeding_leverage=("top_four_leverage", lambda s: float(np.nansum(np.abs(s)))),
        peak_game_leverage=("playoff_leverage", lambda s: float(np.nanmax(np.abs(s))) if s.notna().any() else np.nan),
    )
    return grouped.round(4).reset_index()


def build_readiness(
    odds: pd.DataFrame,
    standings: pd.DataFrame,
    results: pd.DataFrame,
    remaining: pd.DataFrame,
    leverage: pd.DataFrame,
    *,
    ratings: pd.Series,
    home_advantage: float,
    possessions: pd.DataFrame,
    game_logs: pd.DataFrame,
    player_box: Optional[pd.DataFrame] = None,
    bench: Optional[pd.DataFrame] = None,
    clutch: Optional[pd.DataFrame] = None,
    identity: Optional[pd.DataFrame] = None,
    playoff_field_threshold: float = 0.5,
    top_seed_threshold: float = 0.25,
    contention_floor: float = 0.005,
    recent_games: int = 10,
) -> pd.DataFrame:
    """Assemble the readiness board: odds, style, schedule and the lens ordering."""
    if odds.empty:
        return pd.DataFrame()

    field = odds.loc[odds["p_playoffs"] >= playoff_field_threshold, "team_abbreviation"].tolist()
    expected = _expected_margins(results, ratings, home_advantage)

    board = odds.merge(
        result_metrics(results, field, expected_margin=expected, recent_games=recent_games),
        on="team_abbreviation",
        how="left",
    )
    board = board.merge(style_metrics(possessions, game_logs), on="team_abbreviation", how="left")
    board = board.merge(
        remaining_schedule_metrics(remaining, ratings, home_advantage=home_advantage, playoff_field=field),
        on="team_abbreviation",
        how="left",
        suffixes=("", "_schedule"),
    )
    board = board.merge(leverage_totals(leverage), on="team_abbreviation", how="left")
    if player_box is not None and not player_box.empty:
        board = board.merge(
            rotation_metrics(player_box, recent_games=recent_games), on="team_abbreviation", how="left"
        )
    board["team_rating"] = board["team_abbreviation"].map(ratings).round(3)

    board = _merge_optional(
        board,
        bench,
        ["team_abbreviation", "starters_only_net_rating", "any_bench_net_rating", "bench_dropoff"],
    )
    board = _merge_optional(
        board,
        clutch,
        ["team_abbreviation", "clutch_net_rating", "clutch_games", "clutch_off_poss", "clutch_def_poss"],
    )
    board = _merge_optional(
        board,
        identity,
        ["team_abbreviation", "shift_direction", "shift_significance", "opponent_adjusted_net_rating_delta"],
    )
    board = _shrink_clutch(board)

    # `bench_dropoff` from the possession-impact build is already
    # `starters_only_net_rating - any_bench_net_rating`, which is exactly the rotation
    # compression measure this lens wants: how much a team gains when a playoff series
    # lets it shorten. It is used directly rather than recomputed under a second name.
    board["readiness_lens"] = np.select(
        [
            board["p_top_four"] >= top_seed_threshold,
            board["p_playoffs"] >= contention_floor,
        ],
        ["Top seed", "Bubble"],
        default="Out of contention",
    )
    board["readiness_index"] = np.nan
    for lens, components in (("Top seed", CONTENDER_COMPONENTS), ("Bubble", BUBBLE_COMPONENTS)):
        mask = board["readiness_lens"] == lens
        if not mask.any():
            continue
        subset = board.loc[mask]
        scores = []
        for column, higher_is_better in components:
            if column not in subset.columns:
                continue
            scored = percentile(subset[column], higher_is_better=higher_is_better)
            board.loc[mask, f"{column}_score"] = scored.round(1)
            scores.append(scored)
        if scores:
            board.loc[mask, "readiness_index"] = (
                pd.concat(scores, axis=1).mean(axis=1, skipna=True).round(1)
            )

    board["readiness_notes"] = board.apply(_notes, axis=1)
    lens_order = pd.Categorical(board["readiness_lens"], categories=["Top seed", "Bubble", "Out of contention"], ordered=True)
    board = board.assign(_lens_order=lens_order).sort_values(
        ["_lens_order", "readiness_index"], ascending=[True, False]
    )
    return board.drop(columns="_lens_order").reset_index(drop=True)


def _expected_margins(results: pd.DataFrame, ratings: pd.Series, home_advantage: float) -> Optional[pd.Series]:
    """The margin the rating model expected in each played game, from each team's side."""
    if results.empty or ratings.empty:
        return None
    team = results["team"].map(ratings).astype(float)
    opponent = results["opponent"].map(ratings).astype(float)
    edge = np.where(results["is_home"].to_numpy(dtype=bool), home_advantage, -home_advantage)
    return pd.Series(team.to_numpy() - opponent.to_numpy() + edge, index=results.index)


def _shrink_clutch(board: pd.DataFrame) -> pd.DataFrame:
    """Pull clutch net rating toward zero in proportion to the possessions behind it."""
    if "clutch_net_rating" not in board.columns:
        return board
    rating = pd.to_numeric(board["clutch_net_rating"], errors="coerce")
    possessions = pd.Series(0.0, index=board.index)
    for column in ("clutch_off_poss", "clutch_def_poss"):
        if column in board.columns:
            possessions = possessions + pd.to_numeric(board[column], errors="coerce").fillna(0.0)
    board["clutch_possessions"] = possessions.astype(int)
    board["clutch_net_rating_shrunk"] = (
        rating * possessions / (possessions + CLUTCH_SHRINKAGE_POSSESSIONS)
    ).round(2)
    return board


def _merge_optional(board: pd.DataFrame, extra: Optional[pd.DataFrame], columns: Sequence[str]) -> pd.DataFrame:
    """Merge a dependency's output when it exists, and carry on when it does not.

    The possession-derived inputs come from a feed that lags and a build that may not have
    run; a readiness board missing its clutch column is worth far more than no board.
    """
    if extra is None or extra.empty:
        return board
    available = [column for column in columns if column in extra.columns]
    if "team_abbreviation" not in available:
        return board
    trimmed = extra[available].copy()
    trimmed["team_abbreviation"] = trimmed["team_abbreviation"].map(team_key)
    return board.merge(trimmed.drop_duplicates("team_abbreviation"), on="team_abbreviation", how="left")


def _notes(row: pd.Series) -> str:
    """A readable line naming the specific strength and the specific risk.

    Phrased so it stays true at both ends of the table: a bottom team is described as
    transition-dependent rather than as having a transition "edge" it does not have.
    """
    notes: List[str] = []
    transition = row.get("transition_reliance")
    if pd.notna(transition):
        if transition >= 4:
            notes.append(f"transition-dependent, half-court net {transition:.0f} pts worse than early offence")
        elif transition <= -4:
            notes.append("half-court game is the stronger half, which is what travels")
    gap = row.get("quality_gap")
    if pd.notna(gap):
        if gap >= 1.5:
            notes.append("beats the rating model against the playoff field")
        elif gap <= -1.5:
            notes.append("falls short of the model against the playoff field")
    dropoff = row.get("bench_dropoff")
    depth = row.get("rotation_players")
    if pd.notna(dropoff) and pd.notna(depth):
        if dropoff >= 8 and depth >= 9:
            notes.append(f"deep rotation ({depth:.0f} players) with a big starter gap, so shortening is an upgrade available")
        elif dropoff <= -3:
            notes.append("bench units have outscored the starters, so shortening is no obvious gain")
    elif pd.notna(dropoff) and dropoff >= 8:
        notes.append("large gap between starter and bench units")
    spread = row.get("margin_sd")
    if pd.notna(spread) and spread >= 15:
        notes.append("wide game-to-game spread")
    clutch = row.get("clutch_net_rating_shrunk")
    if pd.notna(clutch) and abs(clutch) >= 10:
        notes.append(f"clutch net {clutch:+.0f} on a thin sample")
    if row.get("readiness_lens") in {"Bubble", "Out of contention"}:
        difficulty = row.get("remaining_difficulty")
        if pd.notna(difficulty) and difficulty >= 1.0:
            notes.append("hardest part of the schedule still to come")
        elif pd.notna(difficulty) and difficulty <= -1.0:
            notes.append("soft run-in")
        form = row.get("form_delta")
        if pd.notna(form) and form >= 3:
            notes.append("recent form rising (descriptive, not a forecast)")
    if not notes:
        notes.append("no single standout signal either way")
    return f"{row.get('readiness_lens')}: " + "; ".join(notes)
