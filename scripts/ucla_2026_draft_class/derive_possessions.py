"""Rebuild a full-season possession-and-lineup layer from ESPN play-by-play.

Why this exists
---------------
The sportsdataverse possessions parquet is frozen at 202 games while the rest
of the pipeline has moved on (277 as of 2026-08-22), so any lineup or duo
analysis built on it describes only the first two thirds of the season.

The pbpstats player game logs cannot fix that. They are player-game
aggregates carrying possession *counts* (`OffPoss`, `DefPoss`, `OnOffRtg`) —
they say how many possessions a player was on the floor for, never which four
teammates were out there with her. Co-presence is the missing dimension, and
no amount of aggregate arithmetic recovers it.

`espn_pbp_2026.parquet` does cover the full season and carries 15k+
substitution events naming both the entering and the exiting player. That is
enough to replay every game, hold a five-player lineup per side, and cut the
game into possessions.

Method
------
Event attribution was derived empirically rather than assumed (see
`docs/`-free note in the findings): every shot type, free throw and offensive
rebound is logged against the team with the ball; defensive rebounds against
the team gaining it; turnovers against the team losing it. Fouls, timeouts,
jump balls and kicked-ball violations are ambiguous and are skipped.

A possession runs until the ball changes hands or the period ends. Defining
it that way — rather than by enumerating terminating events — makes and-one
trips, missed free throws and offensive-rebound putbacks fall out correctly
without special cases.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SDV = ROOT / "data/raw/sportsdataverse/wnba_2026"
PBP_PLAYER = ROOT / "data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet"
PBP_TEAM = ROOT / "data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet"
CROSSWALK = ROOT / "analysis/role_fulfillment_matrix/data/review/player_identity_crosswalk_2026.csv"

TEAM_MAP = {"GS": "GSV", "LA": "LAS", "LV": "LVA", "NY": "NYL", "POR": "PDX", "WSH": "WAS"}
NON_LEAGUE = {"COOP", "SPO"}          # all-star exhibition squads

# events that say nothing reliable about who has the ball
SKIP_EXACT = {"Substitution", "Jumpball", "Kicked Ball", "Full Timeout", "Official Timeout",
              "Short Timeout", "Offensive Foul", "Delay of Game", "Ejection",
              "Defensive 3-Seconds", "Double Technical Foul"}
SKIP_CONTAINS = ("Foul",)             # every foul call; the paired Turnover row carries the change
KEEP_ANYWAY = ("Offensive Foul Turnover",)   # ...except the turnover itself
PERIOD_END = {"End Period", "End Game"}


def _norm(a: str) -> str:
    return TEAM_MAP.get(a, a)


def _informative(t: str) -> bool:
    if t in PERIOD_END or t in SKIP_EXACT:
        return False
    if any(k in t for k in KEEP_ANYWAY):
        return True
    return not any(k in t for k in SKIP_CONTAINS)


def load_pbp() -> pd.DataFrame:
    e = pd.read_parquet(SDV / "espn_pbp_2026.parquet")
    e["game_date"] = pd.to_datetime(e.game_date)
    e["home_abbr"] = e.home_team_abbrev.map(_norm)
    e["away_abbr"] = e.away_team_abbrev.map(_norm)
    e = e[~e.home_abbr.isin(NON_LEAGUE) & ~e.away_abbr.isin(NON_LEAGUE)]
    return e.sort_values(["game_id", "period_number", "game_play_number"]).reset_index(drop=True)


def game_crosswalk(e: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    """Match ESPN game ids to pbpstats game ids on date plus the unordered team pair."""
    eg = e.groupby("game_id", as_index=False).agg(
        date=("game_date", "first"), home=("home_abbr", "first"),
        away=("away_abbr", "first"), home_id=("home_team_id", "first"),
        away_id=("away_team_id", "first"))
    eg["key"] = (eg.date.dt.strftime("%Y-%m-%d") + "|"
                 + eg[["home", "away"]].min(axis=1) + "|" + eg[["home", "away"]].max(axis=1))
    t = tg.copy()
    t["game_date"] = pd.to_datetime(t.game_date)
    t["key"] = (t.game_date.dt.strftime("%Y-%m-%d") + "|"
                + t[["team_abbreviation", "opponent_team_abbreviation"]].min(axis=1) + "|"
                + t[["team_abbreviation", "opponent_team_abbreviation"]].max(axis=1))
    tk = t[["game_id", "key"]].drop_duplicates("key").rename(columns={"game_id": "pbp_game_id"})
    return eg.merge(tk, on="key", how="inner")


def player_crosswalk() -> dict[int, int]:
    """ESPN athlete_id -> pbpstats player_id, from the repo's existing crosswalk."""
    xw = pd.read_csv(CROSSWALK)
    # rows for players with no pbpstats game record carry a placeholder id
    # ("espn:4790263"), so coerce and drop rather than casting blind
    xw["player_id"] = pd.to_numeric(xw.player_id, errors="coerce")
    xw = xw.dropna(subset=["espn_athlete_id", "player_id"])
    return {int(a): int(p) for a, p in zip(xw.espn_athlete_id, xw.player_id)}


def starting_lineups() -> dict[tuple[str, int], set[int]]:
    r = pd.read_parquet(SDV / "game_rosters_2026.parquet")
    r = r[r.starter.fillna(False).astype(bool)]
    return {(str(g), int(t)): set(d.athlete_id.astype(int))
            for (g, t), d in r.groupby(["game_id", "team_id"])}


def replay_game(ev: pd.DataFrame, home_id: int, away_id: int,
                start: dict[int, set[int]]) -> list[dict]:
    """Replay one game into possessions, carrying both lineups on every row."""
    on = {home_id: set(start.get(home_id, set())), away_id: set(start.get(away_id, set()))}
    other = {home_id: away_id, away_id: home_id}
    rows: list[dict] = []
    off_team: int | None = None
    pts = 0
    period = int(ev.period_number.iloc[0])

    def flush():
        nonlocal pts, off_team
        if off_team is not None:
            rows.append(dict(period=period, off_team=off_team, def_team=other[off_team],
                             points=pts, valid=len(on[home_id]) == 5 and len(on[away_id]) == 5,
                             off_lineup=tuple(sorted(on[off_team])),
                             def_lineup=tuple(sorted(on[other[off_team]]))))
        pts = 0

    for row in ev.itertuples():
        t = row.type_text or ""
        if int(row.period_number) != period:
            flush()
            off_team, period = None, int(row.period_number)
        if t == "Substitution":
            tid = int(row.team_id) if not pd.isna(row.team_id) else None
            if tid in on and not pd.isna(row.athlete_id_1) and not pd.isna(row.athlete_id_2):
                on[tid].discard(int(row.athlete_id_2))
                on[tid].add(int(row.athlete_id_1))
            continue
        if t in PERIOD_END:
            flush()
            off_team = None
            continue
        if not _informative(t) or pd.isna(row.team_id):
            continue
        tid = int(row.team_id)
        if tid not in on:
            continue

        # a defensive rebound hands the ball to the rebounder; everything else
        # informative is logged against whoever already has it
        ball = tid
        if t == "Defensive Rebound":
            if off_team is None:
                off_team = other[tid]
            ball = tid

        if off_team is None:
            off_team = ball
        elif ball != off_team:
            flush()
            off_team = ball

        if row.scoring_play and tid == off_team:
            pts += int(row.score_value or 0)
    flush()
    return rows


def build(limit_games: int | None = None) -> pd.DataFrame:
    e = load_pbp()
    tg = pd.read_parquet(PBP_TEAM)
    xw = game_crosswalk(e, tg)
    starts = starting_lineups()
    keep = set(xw.game_id)
    if limit_games:
        keep = set(list(keep)[:limit_games])

    meta = xw.set_index("game_id")
    out = []
    for gid, ev in e[e.game_id.isin(keep)].groupby("game_id"):
        m = meta.loc[gid]
        h, a = int(m.home_id), int(m.away_id)
        start = {h: starts.get((str(gid), h), set()), a: starts.get((str(gid), a), set())}
        for rec in replay_game(ev, h, a, start):
            rec.update(game_id=gid, pbp_game_id=m.pbp_game_id, game_date=m.date)
            out.append(rec)
    return pd.DataFrame(out)


def validate(poss: pd.DataFrame) -> dict:
    """Score the reconstruction against the pbpstats game layer.

    Two checks. Team-game possessions and points test the possession logic.
    Player-game on-court possessions test the lineup replay — that one matters
    most, because co-presence is the whole reason this layer exists.
    """
    tg = pd.read_parquet(PBP_TEAM)
    pg = pd.read_parquet(PBP_PLAYER)
    pg["player_id"] = pg.player_id.astype(int)
    esp2pbp = {v: k for k, v in player_crosswalk().items()}   # pbpstats -> espn

    mine = poss.groupby(["pbp_game_id", "off_team"], as_index=False).agg(
        my_poss=("points", "size"), my_pts=("points", "sum"))
    # map espn team ids to pbpstats team abbreviations through the crosswalk rows
    e = load_pbp()
    tmap = pd.concat([
        e[["home_team_id", "home_abbr"]].rename(columns={"home_team_id": "tid", "home_abbr": "abbr"}),
        e[["away_team_id", "away_abbr"]].rename(columns={"away_team_id": "tid", "away_abbr": "abbr"}),
    ]).drop_duplicates()
    tmap["tid"] = tmap.tid.astype(int)
    mine = mine.merge(tmap, left_on="off_team", right_on="tid", how="left")

    ref = tg[["game_id", "team_abbreviation", "off_poss", "points"]].rename(
        columns={"game_id": "pbp_game_id", "team_abbreviation": "abbr"})
    cmp_ = mine.merge(ref, on=["pbp_game_id", "abbr"], how="inner")
    cmp_["poss_diff"] = cmp_.my_poss - cmp_.off_poss
    cmp_["pts_diff"] = cmp_.my_pts - cmp_.points

    # player-level on-court possessions
    rows = []
    for side, lin, tcol in (("off", "off_lineup", "off_team"), ("def", "def_lineup", "def_team")):
        ex = poss[["pbp_game_id", lin]].explode(lin).rename(columns={lin: "espn_id"})
        ex["side"] = side
        rows.append(ex)
    ex = pd.concat(rows)
    ex["espn_id"] = pd.to_numeric(ex.espn_id, errors="coerce")
    cnt = ex[ex.side == "off"].groupby(["pbp_game_id", "espn_id"], as_index=False).size().rename(
        columns={"size": "my_off_poss"})
    pgx = pg[["game_id", "player_id", "off_poss"]].rename(columns={"game_id": "pbp_game_id"})
    pgx["espn_id"] = pgx.player_id.map(esp2pbp)
    pcmp = pgx.dropna(subset=["espn_id"]).merge(cnt, on=["pbp_game_id", "espn_id"], how="inner")
    pcmp["diff"] = pcmp.my_off_poss - pcmp.off_poss
    pcmp["pct_err"] = pcmp["diff"] / pcmp.off_poss.replace(0, np.nan)

    return dict(
        team_games=len(cmp_),
        poss_corr=float(cmp_.my_poss.corr(cmp_.off_poss)),
        poss_mean_diff=float(cmp_.poss_diff.mean()),
        poss_mae=float(cmp_.poss_diff.abs().mean()),
        pts_exact_match_pct=float((cmp_.pts_diff == 0).mean() * 100),
        pts_mae=float(cmp_.pts_diff.abs().mean()),
        player_games=len(pcmp),
        player_poss_corr=float(pcmp.my_off_poss.corr(pcmp.off_poss)),
        player_poss_mean_pct_err=float(pcmp.pct_err.mean() * 100),
        player_poss_mae=float(pcmp["diff"].abs().mean()),
        _team_cmp=cmp_, _player_cmp=pcmp,
    )


def calibrate(poss: pd.DataFrame) -> pd.DataFrame:
    """Give every possession a weight so team-game totals match pbpstats exactly.

    Points are already reproduced exactly (100% of team-games), and the
    possession count runs about 1.5% high against pbpstats — a level bias from
    differing conventions on team rebounds and end-of-period heaves, not a
    lineup error. Weighting each possession by
    `pbpstats_off_poss / reconstructed_off_poss` for its team-game puts every
    rate on the pbpstats scale while leaving the lineup structure untouched.

    Differential metrics (on/off, duo net ratings) barely move — the bias
    mostly cancels — but calibrated levels can be quoted next to pbpstats
    numbers without a caveat about scale.
    """
    tg = pd.read_parquet(PBP_TEAM)
    e = load_pbp()
    tmap = pd.concat([
        e[["home_team_id", "home_abbr"]].rename(columns={"home_team_id": "tid", "home_abbr": "abbr"}),
        e[["away_team_id", "away_abbr"]].rename(columns={"away_team_id": "tid", "away_abbr": "abbr"}),
    ]).drop_duplicates()
    tmap["tid"] = tmap.tid.astype(int)

    mine = poss.groupby(["pbp_game_id", "off_team"], as_index=False).size().rename(
        columns={"size": "my_poss"})
    mine = mine.merge(tmap, left_on="off_team", right_on="tid", how="left")
    ref = tg[["game_id", "team_abbreviation", "off_poss"]].rename(
        columns={"game_id": "pbp_game_id", "team_abbreviation": "abbr"})
    f = mine.merge(ref, on=["pbp_game_id", "abbr"], how="left")
    f["poss_weight"] = (f.off_poss / f.my_poss).fillna(1.0)

    out = poss.merge(f[["pbp_game_id", "off_team", "poss_weight", "abbr"]],
                     on=["pbp_game_id", "off_team"], how="left")
    out["poss_weight"] = out.poss_weight.fillna(1.0)
    out = out.rename(columns={"abbr": "off_abbr"})
    return out


def lineup_splits(poss: pd.DataFrame, players: list[int], team_id: int,
                  labels: dict[int, str] | None = None) -> pd.DataFrame:
    """Team offence and defence split by which of `players` were on the floor.

    Works for any number of players; the state label lists whoever was out
    there, so a pair yields four rows and a trio eight.
    """
    labels = labels or {p: str(p) for p in players}
    o = poss[poss.off_team == team_id].copy()
    d = poss[poss.def_team == team_id].copy()

    def state(lineups):
        return ["+".join(labels[p] for p in players if p in set(l)) or "none" for l in lineups]

    o["state"] = state(o.off_lineup)
    d["state"] = state(d.def_lineup)
    og = o.groupby("state", as_index=False).agg(
        off_poss=("poss_weight", "sum"), pf=("points", "sum"), raw_off=("points", "size"))
    dg = d.groupby("state", as_index=False).agg(
        def_poss=("poss_weight", "sum"), pa=("points", "sum"), raw_def=("points", "size"))
    m = og.merge(dg, on="state", how="outer").fillna(0)
    m["ortg"] = m.pf / m.off_poss.replace(0, np.nan) * 100
    m["drtg"] = m.pa / m.def_poss.replace(0, np.nan) * 100
    m["net"] = m.ortg - m.drtg
    return m.sort_values("off_poss", ascending=False)
