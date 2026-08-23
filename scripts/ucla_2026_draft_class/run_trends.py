import sys, warnings; from pathlib import Path
warnings.simplefilter("ignore")
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"scripts/ucla_2026_draft_class"))
from metrics import season_totals, derive
pd.set_option('display.width',300); pd.set_option('display.max_columns',300)

UCLA={1643427:'Lauren Betts',1643447:'Gabriela Jaquez',1643445:'Kiki Rice',
      1643455:'Angela Dugalic',1643429:'Gianna Kneepkens',1643449:'Charlisse Leger-Walker'}
pg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
pg["player_id"]=pg.player_id.astype(int); pg["game_date"]=pd.to_datetime(pg.game_date)
u=pg[pg.player_id.isin(UCLA)].copy().sort_values(["player_id","game_date"])
u["career_game"]=u.groupby("player_id").cumcount()+1
u["month"]=u.game_date.dt.to_period("M").astype(str)

print("### MONTHLY SPLITS (possession-weighted)")
for pid,nm in UCLA.items():
    s=u[u.player_id==pid]
    rows=[]
    for mo,g in s.groupby("month"):
        d=derive(season_totals(g)).iloc[0]
        rows.append(dict(month=mo,gp=int(d.games_played),mpg=d.min_per_game,usage=d.usage,
            pts75=d.pace_neutral_pts_75,ts=d.ts_pct,ast75=d.ast_75,tov75=d.tov_75,
            foul75=d.foul_75,three_share=d.three_share,net_on=d.net_on_court))
    print(f"\n-- {nm}"); print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n\n### FIRST HALF vs SECOND HALF of each player's own games")
rows=[]
for pid,nm in UCLA.items():
    s=u[u.player_id==pid]; n=len(s); h=n//2
    for lab,g in (("first",s.iloc[:h]),("second",s.iloc[h:])):
        d=derive(season_totals(g)).iloc[0]
        rows.append(dict(player=nm,half=lab,gp=int(d.games_played),mpg=round(d.min_per_game,1),
            usage=round(d.usage,1),pts75=round(d.pace_neutral_pts_75,1),ts=round(d.ts_pct,3),
            ast75=round(d.ast_75,2),tov75=round(d.tov_75,2),foul75=round(d.foul_75,2),
            three_share=round(d.three_share,3),rim_share=round(d.rim_share,3)))
h=pd.DataFrame(rows)
p=h.pivot(index="player",columns="half")
for m in ["mpg","usage","pts75","ts","ast75","tov75","foul75","three_share"]:
    p[(m,"delta")]=p[(m,"second")]-p[(m,"first")]
print(h.to_string(index=False))
print("\nDeltas (2nd half minus 1st half):")
print(p.loc[:,[(m,"delta") for m in ["mpg","usage","pts75","ts","ast75","tov75","foul75","three_share"]]].round(3).to_string())
u.to_csv(ROOT/"analysis/ucla_2026_draft_class/data/ucla_six_game_logs_enriched.csv",index=False)
