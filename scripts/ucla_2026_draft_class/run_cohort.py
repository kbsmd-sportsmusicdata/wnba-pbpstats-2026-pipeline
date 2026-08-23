import sys; from pathlib import Path
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"scripts/ucla_2026_draft_class"))
from metrics import season_totals, derive
from build_datasets import load_cohorts
from onoff import build_on_off
pd.set_option('display.width',300); pd.set_option('display.max_columns',300)

pg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
pg["player_id"]=pg.player_id.astype(int); pg["game_date"]=pd.to_datetime(pg.game_date)
tg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet")
bio=load_cohorts(); bio["player_id"]=pd.to_numeric(bio.player_id,errors="coerce")

agg=derive(season_totals(pg)).merge(
    bio[["player_id","display_name","position_abbreviation","experience_years","draft_year",
         "draft_selection","draft_round","college_id","age"]],on="player_id",how="left")
agg=agg.merge(build_on_off(pg,tg).drop(columns=["player_name"]),on="player_id",how="left",suffixes=("","_oo"))
agg["is_rookie"]=agg.experience_years.eq(0)
agg["is_ucla"]=agg.draft_year.eq(2026)&agg.college_id.eq(26.0)
agg["is_d26"]=agg.draft_year.eq(2026)

MET=["min_per_game","minutes","usage","pace_neutral_pts_75","ts_pct","efg_pct","shot_quality_avg",
     "shot_making_over_sq","ast_75","tov_75","ast_to_tov","ast_pts_created_75","pts_plus_created_75",
     "oreb_75","dreb_75","stl_75","blk_75","stocks_75","foul_75","fta_75","ftr","shot_75",
     "rim_share","mid_share","three_share","corner3_share","rim_accuracy","three_accuracy",
     "off_fgrebound_pct","def_fgrebound_pct","unassisted_pts_share","blocked_rate",
     "on_net","net_swing","ortg_swing","drtg_swing","pm_per_100","on_poss_share"]

# two reference pools: qualified league (>=250 min) and qualified rookies (>=150 min)
lg=agg[agg.minutes>=250].copy()
rk=agg[(agg.is_rookie)&(agg.minutes>=150)].copy()
for c in MET:
    agg[c+"__lg_pctile"]=agg[c].where(agg.minutes>=250).rank(pct=True)*100
    agg[c+"__rk_pctile"]=agg[c].where((agg.is_rookie)&(agg.minutes>=150)).rank(pct=True)*100
print("league pool n=%d | rookie pool n=%d"%(len(lg),len(rk)))
agg.to_csv(ROOT/"analysis/ucla_2026_draft_class/data/season_metrics_with_percentiles.csv",index=False)

U=agg[agg.is_ucla].sort_values("draft_selection")
show=["player_name","teams","draft_selection","games_played","min_per_game","usage","pace_neutral_pts_75",
      "ts_pct","shot_making_over_sq","ast_75","tov_75","ast_to_tov","stocks_75","foul_75","net_swing"]
print("\n### UCLA SIX — raw"); print(U[show].round(2).to_string(index=False))
print("\n### UCLA SIX — rookie-pool percentiles (of %d rookies w/ 150+ min)"%len(rk))
pc=[c+"__rk_pctile" for c in ["min_per_game","usage","pace_neutral_pts_75","ts_pct","shot_making_over_sq",
    "ast_75","tov_75","stocks_75","foul_75","off_fgrebound_pct","def_fgrebound_pct","three_share","rim_share","net_swing"]]
t=U[["player_name"]+pc].copy(); t.columns=["player"]+[c.replace("__rk_pctile","") for c in pc]
print(t.round(0).to_string(index=False))
print("\n### UCLA SIX — league-pool percentiles (of %d players w/ 250+ min)"%len(lg))
pc2=[c.replace("__rk_pctile","__lg_pctile") for c in pc]
t2=U[["player_name"]+pc2].copy(); t2.columns=["player"]+[c.replace("__lg_pctile","") for c in pc2]
print(t2.round(0).to_string(index=False))
