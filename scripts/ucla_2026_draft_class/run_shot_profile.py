import sys, warnings; from pathlib import Path
warnings.simplefilter("ignore")
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"scripts/ucla_2026_draft_class"))
from metrics import season_totals, derive
from build_datasets import load_cohorts
pd.set_option('display.width',320)

UCLA=[1643427,1643447,1643445,1643455,1643429,1643449]
pg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
pg["player_id"]=pg.player_id.astype(int)
bio=load_cohorts(); bio["player_id"]=pd.to_numeric(bio.player_id,errors="coerce")
agg=derive(season_totals(pg)).merge(bio[["player_id","display_name","position_abbreviation","experience_years","draft_year","college_id"]],on="player_id",how="left")
agg["is_ucla"]=agg.player_id.isin(UCLA)
agg["is_rookie"]=agg.experience_years.eq(0)

print("### SHOT DIET & FINISHING")
cols=["player_name","shot_75","rim_share","short_mid_share","long_mid_share","three_share","corner3_share",
      "rim_accuracy","three_accuracy","ftr","blocked_rate","shot_quality_avg","efg_pct","shot_making_over_sq",
      "unassisted_pts_share","putback_pts_share"]
print(agg[agg.is_ucla][cols].round(3).to_string(index=False))
print("\nPositional baselines (250+ min, possession-weighted medians):")
q=agg[(agg.minutes>=250)]
print(q.groupby("position_abbreviation")[cols[1:]].median().round(3).to_string())
print("\nLeague median (250+ min):"); print(q[cols[1:]].median().round(3).to_string())

print("\n\n### GAME-LEVEL VOLATILITY & OUTLIERS (UCLA six)")
u=pg[pg.player_id.isin(UCLA)].copy()
u["fga"]=u.fg2_a.fillna(0)+u.fg3_a.fillna(0)
u["gsc"]=(u.points+0.7*u.off_rebounds+0.3*u.def_rebounds+0.7*u.assists+u.steals+0.7*u.blocks
          -0.7*u.fga-0.4*(u.fta-u.ft_points.div(1).fillna(0)*0)-u.turnovers-0.4*u.fouls)
g=u.groupby("player_name").agg(gp=("game_id","nunique"),mpg=("minutes","mean"),
    pts_mean=("points","mean"),pts_sd=("points","std"),pts_max=("points","max"),
    min_sd=("minutes","std"),pm_mean=("plus_minus","mean"),pm_sd=("plus_minus","std")).reset_index()
g["pts_cv"]=g.pts_sd/g.pts_mean; g["min_cv"]=g.min_sd/g.mpg
print(g.round(2).to_string(index=False))

print("\nTop-3 games by points, each player:")
for nm,s in u.groupby("player_name"):
    t=s.nlargest(3,"points")[["game_date","opponent_team_abbreviation","minutes","points","fg2_m","fg2_a","fg3_m","fg3_a","rebounds","assists","turnovers","plus_minus"]]
    print(f"\n-- {nm}"); print(t.round(1).to_string(index=False))

print("\n\n### DOUBLE-DIGIT GAME RATE & SCORELESS RATE")
u["dd_pts"]=u.points>=10; u["scoreless"]=u.points==0; u["dbl_dbl"]=((u.points>=10).astype(int)+(u.rebounds>=10).astype(int)+(u.assists>=10).astype(int))>=2
print(u.groupby("player_name").agg(gp=("game_id","nunique"),pct_10plus=("dd_pts","mean"),
    pct_scoreless=("scoreless","mean"),double_doubles=("dbl_dbl","sum")).round(3).to_string())
