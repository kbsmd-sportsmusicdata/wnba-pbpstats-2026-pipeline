import sys, warnings; from pathlib import Path
warnings.simplefilter("ignore")
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"scripts/ucla_2026_draft_class"))
pd.set_option('display.width',300)

UCLA={1643427:('Lauren Betts','WAS'),1643447:('Gabriela Jaquez','CHI'),1643445:('Kiki Rice','TOR'),
      1643455:('Angela Dugalic','WAS'),1643429:('Gianna Kneepkens','CON'),1643449:('Charlisse Leger-Walker','CON')}
pg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
pg["player_id"]=pg.player_id.astype(int); pg["game_date"]=pd.to_datetime(pg.game_date)
tg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet")
tg["game_date"]=pd.to_datetime(tg.game_date)

print("### 1. TEAM MINUTES / POSSESSION SHARE ABSORBED BY EACH UCLA ROOKIE")
rows=[]
for pid,(nm,tm) in UCLA.items():
    t=tg[tg.team_abbreviation==tm]
    p=pg[pg.player_id==pid]
    rows.append(dict(player=nm,team=tm,team_games=t.game_id.nunique(),played=p.game_id.nunique(),
        avail_pct=100*p.game_id.nunique()/t.game_id.nunique(),
        min_share=100*p.minutes.sum()/(t.minutes.sum()),
        off_poss_share=100*p.off_poss.sum()/t.off_poss.sum(),
        team_pts_share=100*p.points.sum()/t.points.sum(),
        team_ast_share=100*p.assists.sum()/t.assists.sum(),
        team_reb_share=100*p.rebounds.sum()/t.rebounds.sum()))
print(pd.DataFrame(rows).round(1).to_string(index=False))

print("\n### 2. TORONTO WITH / WITHOUT KIKI RICE (16-game contiguous absence, games 11-26)")
tor=tg[tg.team_abbreviation=="TOR"].sort_values("game_date").reset_index(drop=True)
tor["gn"]=np.arange(1,len(tor)+1)
played=set(pg[(pg.player_id==1643445)].game_id)
tor["rice"]=np.where(tor.game_id.isin(played),"with","without")
tor["block"]=np.select([tor.gn<=10,tor.gn.between(11,26)],["A: g1-10 (Rice in)","B: g11-26 (Rice out)"],"C: g27-36 (Rice back)")
for key in ["rice","block"]:
    o=tor.groupby(key).agg(g=("game_id","nunique"),w=("win","sum"),pf=("points","sum"),pa=("opponent_points","sum"),
                           op=("off_poss","sum"),dp=("def_poss","sum")).reset_index()
    o["ortg"]=o.pf/o.op*100; o["drtg"]=o.pa/o.dp*100; o["net"]=o.ortg-o.drtg; o["win_pct"]=o.w/o.g
    print(o.round(2).to_string(index=False)); print()

print("### 3. TEAMMATE PAIRS — team net rating by availability state (game granularity)")
def pair(tm,a,b,na,nb):
    t=tg[tg.team_abbreviation==tm].copy()
    pa_=set(pg[pg.player_id==a].game_id); pb_=set(pg[pg.player_id==b].game_id)
    t["state"]=np.select([t.game_id.isin(pa_)&t.game_id.isin(pb_),t.game_id.isin(pa_),t.game_id.isin(pb_)],
                         ["both",f"{na} only",f"{nb} only"],default="neither")
    o=t.groupby("state").agg(g=("game_id","nunique"),w=("win","sum"),pf=("points","sum"),pa=("opponent_points","sum"),
                             op=("off_poss","sum"),dp=("def_poss","sum")).reset_index()
    o["ortg"]=o.pf/o.op*100; o["drtg"]=o.pa/o.dp*100; o["net"]=o.ortg-o.drtg
    print(f"-- {tm}: {na} + {nb}"); print(o.round(2).to_string(index=False)); print()
pair("WAS",1643427,1643455,"Betts","Dugalic")
pair("CON",1643429,1643449,"Kneepkens","Leger-Walker")

print("### 4. IMPACT METRICS (sportsdataverse; season-to-date through ~mid-July, gp<=29)")
imp=pd.read_parquet(ROOT/"data/raw/sportsdataverse/wnba_2026/wnba_player_impact_2026.parquet")
c=["player_name","team_abbreviation","gp","min","o_rapm","d_rapm","rapm","ospm","dspm","spm","obpm","dbpm","bpm","war","darko_filtered_skill"]
sub=imp[imp.player_id.isin(UCLA)][c]
print(sub.round(2).to_string(index=False))
rook_ids=[k for k in imp.player_id]
print("\nleague percentile of rapm / bpm / war among players with 200+ min:")
q=imp[imp["min"]>=200].copy()
for m in ["rapm","bpm","war","spm"]:
    q[m+"_p"]=q[m].rank(pct=True)*100
print(q[q.player_id.isin(UCLA)][["player_name","min","rapm","rapm_p","bpm","bpm_p","war","war_p","spm","spm_p"]].round(1).to_string(index=False))
