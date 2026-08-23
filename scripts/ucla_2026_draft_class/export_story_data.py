"""Emit the tidy, design-ready slices for the UCLA 2026 draft-class story.

Every file is small enough to inline into an HTML artifact. Percentiles are
computed against two explicit reference pools so the editorial layer never has
to re-derive context:
  * league pool  = 149 players with 250+ minutes
  * rookie pool  =  37 rookies with 150+ minutes
"""
from __future__ import annotations

import json, sys, warnings
from pathlib import Path

warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ucla_2026_draft_class"))
from metrics import season_totals, derive          # noqa: E402
from onoff import build_on_off                     # noqa: E402
from build_datasets import load_cohorts            # noqa: E402

OUT = ROOT / "analysis" / "ucla_2026_draft_class" / "data"
OUT.mkdir(parents=True, exist_ok=True)

UCLA = {
    1643427: "Lauren Betts", 1643447: "Gabriela Jaquez", 1643445: "Kiki Rice",
    1643455: "Angela Dugalic", 1643429: "Gianna Kneepkens", 1643449: "Charlisse Leger-Walker",
}
LEAGUE_MIN, ROOKIE_MIN = 250, 150

HEADLINE = [
    "min_per_game", "usage", "pace_neutral_pts_75", "ts_pct", "efg_pct", "shot_quality_avg",
    "shot_making_over_sq", "ast_75", "tov_75", "ast_to_tov", "ast_pts_created_75",
    "oreb_75", "dreb_75", "off_fgrebound_pct", "def_fgrebound_pct", "stl_75", "blk_75",
    "stocks_75", "foul_75", "fta_75", "ftr", "shot_75", "rim_share", "mid_share",
    "three_share", "rim_accuracy", "three_accuracy", "unassisted_pts_share",
    "blocked_rate", "on_net", "net_swing", "ortg_swing", "drtg_swing", "on_poss_share",
]
LOWER_IS_BETTER = {"tov_75", "foul_75", "blocked_rate", "drtg_swing", "mid_share"}


def main() -> None:
    pg = pd.read_parquet(ROOT / "data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
    pg["player_id"] = pg.player_id.astype(int)
    pg["game_date"] = pd.to_datetime(pg.game_date)
    tg = pd.read_parquet(ROOT / "data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet")
    tg["game_date"] = pd.to_datetime(tg.game_date)
    bio = load_cohorts()
    bio["player_id"] = pd.to_numeric(bio.player_id, errors="coerce")

    agg = derive(season_totals(pg)).merge(
        bio[["player_id", "display_name", "position_abbreviation", "experience_years",
             "draft_year", "draft_selection", "draft_round", "college_id", "age", "display_height"]],
        on="player_id", how="left",
    ).merge(build_on_off(pg, tg).drop(columns=["player_name"]), on="player_id", how="left")
    agg["is_rookie"] = agg.experience_years.eq(0)
    agg["is_ucla"] = agg.draft_year.eq(2026) & agg.college_id.eq(26.0)

    lg_mask, rk_mask = agg.minutes >= LEAGUE_MIN, agg.is_rookie & (agg.minutes >= ROOKIE_MIN)
    pct_cols = {}
    for c in HEADLINE:
        asc = c in LOWER_IS_BETTER
        pct_cols[f"{c}__lg_pctile"] = agg[c].where(lg_mask).rank(pct=True, ascending=not asc) * 100
        pct_cols[f"{c}__rk_pctile"] = agg[c].where(rk_mask).rank(pct=True, ascending=not asc) * 100
        pct_cols[f"{c}__rk_rank"] = agg[c].where(rk_mask).rank(method="min", ascending=asc)
    agg = pd.concat([agg, pd.DataFrame(pct_cols, index=agg.index)], axis=1)

    # 1 — the six, season profile
    six = agg[agg.is_ucla].sort_values("draft_selection")
    six.to_csv(OUT / "story_ucla_six_season_profile.csv", index=False)

    # 2 — long/tidy percentile frame, ready for radar & bar-chart binding
    tidy = []
    for _, r in six.iterrows():
        for c in HEADLINE:
            tidy.append(dict(player=r.player_name, metric=c, value=r[c],
                             league_pctile=r[f"{c}__lg_pctile"], rookie_pctile=r[f"{c}__rk_pctile"],
                             rookie_rank=r[f"{c}__rk_rank"],
                             lower_is_better=c in LOWER_IS_BETTER,
                             league_median=agg.loc[lg_mask, c].median(),
                             rookie_median=agg.loc[rk_mask, c].median()))
    pd.DataFrame(tidy).to_csv(OUT / "story_metric_percentiles_long.csv", index=False)

    # 3 — reference pools kept whole so the story can plot distributions
    agg[lg_mask].to_csv(OUT / "story_league_pool_250min.csv", index=False)
    agg[rk_mask].to_csv(OUT / "story_rookie_pool_150min.csv", index=False)

    # 4 — game logs, trimmed to the columns an editorial chart actually needs
    keep = ["game_date", "player_name", "team_abbreviation", "opponent_team_abbreviation",
            "is_home", "win", "minutes", "points", "fg2_m", "fg2_a", "fg3_m", "fg3_a", "fta",
            "ft_points", "at_rim_fgm", "at_rim_fga", "assists", "turnovers", "off_rebounds",
            "def_rebounds", "rebounds", "steals", "blocks", "fouls", "plus_minus", "usage",
            "ts_pct", "off_poss", "def_poss", "on_off_rtg", "on_def_rtg", "shot_quality_avg"]
    logs = pg[pg.player_id.isin(UCLA)][keep].sort_values(["player_name", "game_date"])
    logs["game_no"] = logs.groupby("player_name").cumcount() + 1
    logs.to_csv(OUT / "story_ucla_six_game_logs.csv", index=False)

    # 5 — monthly development arcs
    m = pg[pg.player_id.isin(UCLA)].copy()
    m["month"] = m.game_date.dt.to_period("M").astype(str)
    rows = []
    for (pid, mo), g in m.groupby(["player_id", "month"]):
        d = derive(season_totals(g)).iloc[0]
        rows.append(dict(player=UCLA[pid], month=mo, games=int(d.games_played),
                         mpg=d.min_per_game, usage=d.usage, pts75=d.pace_neutral_pts_75,
                         ts_pct=d.ts_pct, ast75=d.ast_75, tov75=d.tov_75, foul75=d.foul_75,
                         three_share=d.three_share, rim_share=d.rim_share,
                         on_net=d.net_on_court))
    pd.DataFrame(rows).to_csv(OUT / "story_monthly_development.csv", index=False)

    # 6 — team context for the four employers
    t = tg.groupby(["team_abbreviation", "team_name"], as_index=False).agg(
        games=("game_id", "nunique"), wins=("win", "sum"), pf=("points", "sum"),
        pa=("opponent_points", "sum"), op=("off_poss", "sum"), dp=("def_poss", "sum"))
    t["ortg"] = t.pf / t.op * 100
    t["drtg"] = t.pa / t.dp * 100
    t["net"] = t.ortg - t.drtg
    t["win_pct"] = t.wins / t.games
    t["net_rank"] = t.net.rank(ascending=False).astype(int)
    t["has_ucla_rookie"] = t.team_abbreviation.isin(["WAS", "CHI", "TOR", "CON"])
    t.to_csv(OUT / "story_team_context.csv", index=False)

    manifest = dict(
        season=2026, season_type="Regular Season",
        games_through=str(pg.game_date.max().date()),
        games_in_spine=int(pg.game_id.nunique()),
        league_pool_size=int(lg_mask.sum()), league_pool_min_minutes=LEAGUE_MIN,
        rookie_pool_size=int(rk_mask.sum()), rookie_pool_min_minutes=ROOKIE_MIN,
        rookie_population=int(agg.is_rookie.sum()),
        lower_is_better=sorted(LOWER_IS_BETTER),
        files=sorted(p.name for p in OUT.glob("story_*.csv")),
    )
    (OUT / "story_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
