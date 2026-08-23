import sys, warnings; from pathlib import Path
warnings.simplefilter("ignore")
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"scripts/ucla_2026_draft_class"))
from metrics import season_totals, derive
from build_datasets import load_cohorts
from onoff import build_on_off
pd.set_option('display.width',320)

pg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
pg["player_id"]=pg.player_id.astype(int)
tg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet")
bio=load_cohorts(); bio["player_id"]=pd.to_numeric(bio.player_id,errors="coerce")
agg=derive(season_totals(pg)).merge(
    bio[["player_id","display_name","position_abbreviation","experience_years","draft_year","draft_selection","college_id"]],
    on="player_id",how="left").merge(build_on_off(pg,tg).drop(columns=["player_name"]),on="player_id",how="left")
agg["is_rookie"]=agg.experience_years.eq(0)
agg["UCLA"]=np.where(agg.draft_year.eq(2026)&agg.college_id.eq(26.0),"UCLA","")

r=agg[agg.is_rookie].copy()
print("### 2026 ROOKIE CLASS LEADERBOARD (all rookies with any minutes, n=%d)"%len(r))
c=["player_name","UCLA","teams","draft_selection","games_played","minutes","min_per_game","usage",
   "pace_neutral_pts_75","ts_pct","ast_75","tov_75","stocks_75","net_swing","on_poss_share"]
print(r.nlargest(25,"minutes")[c].round(2).to_string(index=False))

print("\n### UCLA SHARE OF THE 2026 ROOKIE CLASS")
u=r[r.UCLA=="UCLA"]
tot=dict(players=len(r),minutes=r.minutes.sum(),points=r.points.sum(),assists=r.assists.sum(),
         rebounds=r.rebounds.sum(),off_poss=r.off_poss_x.sum(),stl=r.steals.sum(),blk=r.blocks.sum())
uu =dict(players=len(u),minutes=u.minutes.sum(),points=u.points.sum(),assists=u.assists.sum(),
         rebounds=u.rebounds.sum(),off_poss=u.off_poss_x.sum(),stl=u.steals.sum(),blk=u.blocks.sum())
print(pd.DataFrame([tot,uu,{k:round(100*uu[k]/tot[k],1) for k in tot}],index=["rookie class","UCLA six","UCLA %"]).round(1).to_string())

print("\n### RANK WITHIN ROOKIE CLASS (1 = best; among rookies with 150+ min, n=%d)"%int(((r.minutes>=150)).sum()))
q=r[r.minutes>=150].copy()
higher=["minutes","min_per_game","usage","pace_neutral_pts_75","ts_pct","shot_making_over_sq","ast_75",
        "ast_to_tov","stocks_75","oreb_75","dreb_75","off_fgrebound_pct","def_fgrebound_pct","fta_75",
        "net_swing","on_poss_share","rim_accuracy","three_accuracy"]
lower=["tov_75","foul_75","blocked_rate"]
out={}
for m in higher: out[m]=q[m].rank(ascending=False,method="min")
for m in lower:  out[m]=q[m].rank(ascending=True,method="min")
R=pd.DataFrame(out,index=q.index); R.insert(0,"player",q.player_name)
print(R[R.player.isin(u.player_name)].set_index("player").T.astype("Int64").to_string())

print("\n### PRODUCTION vs DRAFT SLOT (2026 draftees who played)")
d=agg[agg.draft_year.eq(2026)&agg.minutes.gt(0)].copy()
d["min_rank"]=d.minutes.rank(ascending=False,method="min")
d["slot_vs_usage_rank"]=d.min_rank-d.draft_selection.rank(method="min")
print(d.nlargest(30,"minutes")[["player_name","UCLA","teams","draft_selection","minutes","min_rank","slot_vs_usage_rank","ts_pct","net_swing"]].round(2).to_string(index=False))
r.to_csv(ROOT/"analysis/ucla_2026_draft_class/data/rookie_class_2026_metrics.csv",index=False)
