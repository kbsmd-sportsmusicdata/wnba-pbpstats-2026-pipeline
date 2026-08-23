"""Everything in EDA_FINDINGS_PBPSTATS_ONLY.md, from the pbpstats layer alone.

Sources, and nothing else:
  data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet  (274 games)
  data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet      (274 games)

The one exception is cohort identification: pbpstats carries no college or
draft metadata, so the six players and the rookie pool are selected via
player_core_2026.csv. That file contributes membership only — every number
below is computed from the two parquets.
"""
from __future__ import annotations

import json, sys, warnings
from itertools import combinations
from pathlib import Path

warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ucla_2026_draft_class"))
from metrics import season_totals, derive   # noqa: E402
from onoff import build_on_off              # noqa: E402
from build_datasets import load_cohorts     # noqa: E402

OUT = ROOT / "analysis" / "ucla_2026_draft_class" / "data"
UCLA = {1643427: "Lauren Betts", 1643447: "Gabriela Jaquez", 1643445: "Kiki Rice",
        1643455: "Angela Dugalic", 1643429: "Gianna Kneepkens", 1643449: "Charlisse Leger-Walker"}
RICE = 1643445


def load():
    pg = pd.read_parquet(ROOT / "data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
    pg["player_id"] = pg.player_id.astype(int)
    pg["game_date"] = pd.to_datetime(pg.game_date)
    tg = pd.read_parquet(ROOT / "data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet")
    tg["game_date"] = pd.to_datetime(tg.game_date)
    return pg, tg


def team_defense(tg: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Each team's season defensive rating and its distance from league average."""
    lg = tg.opponent_points.sum() / tg.def_poss.sum() * 100
    d = tg.groupby(["team_id", "team_abbreviation"], as_index=False).apply(
        lambda x: pd.Series({"drtg": x.opponent_points.sum() / x.def_poss.sum() * 100})
    )
    d["def_strength"] = d.drtg - lg          # negative = tougher than average
    return d, lg


def rice_blocks(pg: pd.DataFrame, tg: pd.DataFrame) -> dict:
    """Rice's season split into pre-injury, absence, and two five-game return windows."""
    tor = tg[tg.team_abbreviation == "TOR"].sort_values("game_date").reset_index(drop=True)
    tor["tgn"] = np.arange(1, len(tor) + 1)
    r = pg[pg.player_id == RICE].merge(tor[["game_id", "tgn"]], on="game_id")

    labels = ["Pre-injury (g1-10)", "Return games 1-5 (g27-31)", "Return games 6-10 (g32-36)"]
    r["block"] = np.select([r.tgn <= 10, r.tgn.between(27, 31)], labels[:2], labels[2])
    tor["block"] = np.select(
        [tor.tgn <= 10, tor.tgn.between(11, 26), tor.tgn.between(27, 31)],
        ["Pre-injury (g1-10)", "Rice OUT (g11-26)", "Return games 1-5 (g27-31)"],
        "Return games 6-10 (g32-36)")

    player = pd.DataFrame([
        dict(block=b, **{k: v for k, v in derive(season_totals(g)).iloc[0].items()
                         if k in ("games_played", "min_per_game", "off_poss", "usage",
                                  "pace_neutral_pts_75", "ts_pct", "efg_pct", "shot_quality_avg",
                                  "shot_making_over_sq", "ast_75", "tov_75", "foul_75", "fta_75",
                                  "rim_share", "rim_accuracy", "three_share", "net_on_court")})
        for b, g in r.groupby("block")]).set_index("block").loc[labels]

    team = tor.groupby("block", as_index=False).agg(
        games=("game_id", "nunique"), wins=("win", "sum"), pf=("points", "sum"),
        pa=("opponent_points", "sum"), op=("off_poss", "sum"), dp=("def_poss", "sum"))
    team["ortg"] = team.pf / team.op * 100
    team["drtg"] = team.pa / team.dp * 100
    team["net"] = team.ortg - team.drtg

    # per-block on/off, same exact arithmetic as the season-long version
    swings = []
    for b in labels:
        s = r[r.block == b].merge(
            tg[["game_id", "team_id", "off_poss", "def_poss", "points", "opponent_points"]],
            on=["game_id", "team_id"], suffixes=("", "_t"))
        on_f, on_a = (s.on_off_rtg / 100 * s.off_poss).sum(), (s.on_def_rtg / 100 * s.def_poss).sum()
        off_op, off_dp = s.off_poss_t.sum() - s.off_poss.sum(), s.def_poss_t.sum() - s.def_poss.sum()
        on = on_f / s.off_poss.sum() * 100 - on_a / s.def_poss.sum() * 100
        off = (s.points_t.sum() - on_f) / off_op * 100 - (s.opponent_points_t.sum() - on_a) / off_dp * 100
        swings.append(dict(block=b, on_net=on, off_net=off, net_swing=on - off,
                           on_off_poss=int(s.off_poss.sum())))

    tor["rest_days"] = tor.game_date.diff().dt.days
    timeline = tor[["tgn", "game_date", "opponent_team_abbreviation", "win", "rest_days"]].merge(
        tor[["game_id", "tgn"]], on="tgn").merge(
        r[["game_id", "minutes", "off_poss", "points", "usage", "assists", "turnovers",
           "fouls", "plus_minus"]], on="game_id", how="left")
    timeline["status"] = np.where(timeline.minutes.isna(), "OUT", "played")
    return dict(player=player, team=team, swings=pd.DataFrame(swings), timeline=timeline)


def teammate_minute_correlations(pg: pd.DataFrame, tg: pd.DataFrame, min_minutes=250):
    """Do two teammates' per-game minutes trade off?

    A strongly negative correlation with a stable combined total is the
    pbpstats-only signature of one rotation slot being split between two
    players. Some negative correlation is mechanical (team minutes are fixed),
    so every pair is scored against the distribution of all rotation pairs.
    """
    rows = []
    for tm, gt in tg.groupby("team_abbreviation"):
        gids = gt[["game_id"]]
        tp = pg[pg.team_abbreviation == tm]
        rot = tp.groupby("player_id").minutes.sum()
        rot = rot[rot >= min_minutes].index.tolist()
        for a, b in combinations(rot, 2):
            A = tp[tp.player_id == a][["game_id", "minutes"]].rename(columns={"minutes": "a"})
            B = tp[tp.player_id == b][["game_id", "minutes"]].rename(columns={"minutes": "b"})
            m = gids.merge(A, on="game_id", how="left").merge(B, on="game_id", how="left").fillna(0)
            if m.a.std() == 0 or m.b.std() == 0:
                continue
            both = m[(m.a > 0) & (m.b > 0)]
            rows.append(dict(team=tm, player_a=a, player_b=b, r=m.a.corr(m.b),
                             games_both=len(both),
                             combined_mpg=(both.a + both.b).mean(),
                             combined_sd=(both.a + both.b).std()))
    df = pd.DataFrame(rows)
    df["r_pctile"] = df.r.rank(pct=True) * 100
    names = pg[["player_id", "player_name"]].drop_duplicates().set_index("player_id").player_name
    df["name_a"] = df.player_a.map(names)
    df["name_b"] = df.player_b.map(names)
    return df


def main() -> None:
    pg, tg = load()
    bio = load_cohorts()
    bio["player_id"] = pd.to_numeric(bio.player_id, errors="coerce")

    agg = derive(season_totals(pg)).merge(
        bio[["player_id", "position_abbreviation", "experience_years", "draft_year",
             "draft_selection", "college_id"]], on="player_id", how="left"
    ).merge(build_on_off(pg, tg).drop(columns=["player_name"]), on="player_id", how="left")
    agg["is_rookie"] = agg.experience_years.eq(0)
    agg["is_ucla"] = agg.draft_year.eq(2026) & agg.college_id.eq(26.0)

    tmd, lg_drtg = team_defense(tg)
    u = pg[pg.player_id.isin(UCLA)].merge(
        tmd[["team_id", "def_strength"]].rename(
            columns={"team_id": "opponent_team_id", "def_strength": "opp_def_strength"}),
        on="opponent_team_id", how="left")
    u["fga"] = u.fg2_a.fillna(0) + u.fg3_a.fillna(0)
    sched = []
    for nm, g in u.groupby("player_name"):
        s = np.average(g.opp_def_strength, weights=g.off_poss)
        pts75 = g.points.sum() / g.off_poss.sum() * 75
        sched.append(dict(player=nm, off_poss=int(g.off_poss.sum()), sched_def_strength=s,
                          pts75_raw=pts75, pts75_opp_adj=pts75 * (1 - s / lg_drtg),
                          ts_raw=g.points.sum() / (2 * (g.fga.sum() + 0.44 * g.fta.sum()))))
    sched = pd.DataFrame(sched)

    rb = rice_blocks(pg, tg)
    corr = teammate_minute_correlations(pg, tg)

    rb["timeline"].to_csv(OUT / "story_rice_timeline.csv", index=False)
    rb["player"].reset_index().to_csv(OUT / "story_rice_return_blocks_player.csv", index=False)
    rb["team"].to_csv(OUT / "story_rice_return_blocks_team.csv", index=False)
    rb["swings"].to_csv(OUT / "story_rice_return_blocks_onoff.csv", index=False)
    sched.to_csv(OUT / "story_opponent_adjusted_scoring.csv", index=False)
    tmd.to_csv(OUT / "story_team_defense_strength.csv", index=False)
    corr.to_csv(OUT / "story_teammate_minute_correlations.csv", index=False)

    print("=== RICE: minutes by block ===")
    print(rb["timeline"][rb["timeline"].status == "played"]
          .assign(block=lambda d: np.select(
              [d.tgn <= 10, d.tgn.between(27, 31)],
              ["pre-injury", "return 1-5"], "return 6-10"))
          .groupby("block").minutes.agg(["count", "mean", "min", "max", "std"]).round(1).to_string())
    print("\n=== RICE: rates by block ===");  print(rb["player"].round(3).to_string())
    print("\n=== TORONTO: team net by block ===")
    print(rb["team"].set_index("block")[["games", "wins", "ortg", "drtg", "net"]].round(2).to_string())
    print("\n=== RICE: on/off by block ===");  print(rb["swings"].round(2).to_string(index=False))
    print(f"\n=== Opponent adjustment (league DRtg {lg_drtg:.2f}) ===")
    print(sched.round(3).to_string(index=False))
    print("\n=== Teammate minute-correlation baseline ===")
    print(corr.r.describe(percentiles=[.05, .25, .5, .75, .95]).round(3).to_string())

    (OUT / "pbpstats_only_manifest.json").write_text(json.dumps(dict(
        sources=["player_game.parquet", "team_game.parquet"],
        cohort_membership_only="player_core_2026.csv",
        games=int(pg.game_id.nunique()), through=str(pg.game_date.max().date()),
        league_drtg=round(lg_drtg, 3),
        teammate_pairs_scored=int(len(corr)),
    ), indent=2))


if __name__ == "__main__":
    main()
