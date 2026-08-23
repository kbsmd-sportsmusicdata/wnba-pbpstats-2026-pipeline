import sys, warnings; from pathlib import Path
warnings.simplefilter("ignore")
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parents[2]
pd.set_option('display.width',300)

UCLA={1643427:('Lauren Betts','WAS'),1643447:('Gabriela Jaquez','CHI'),1643445:('Kiki Rice','TOR'),
      1643455:('Angela Dugalic','WAS'),1643429:('Gianna Kneepkens','CON'),1643449:('Charlisse Leger-Walker','CON')}
po=pd.read_parquet(ROOT/"data/raw/sportsdataverse/wnba_2026/wnba_possessions_2026.parquet")
po=po[po.count_as_possession]
offc=[f"off_player_{i}" for i in range(1,6)]; defc=[f"def_player_{i}" for i in range(1,6)]
for c in offc+defc: po[c]=pd.to_numeric(po[c],errors="coerce")
print("possession sample: %d poss across %d games (May 8 - mid Jul)"%(len(po),po.game_id.nunique()))

def split(pid, team_id):
    on_o = po[(po.offense_team_id==team_id) & (po[offc].eq(pid).any(axis=1))]
    off_o= po[(po.offense_team_id==team_id) & (~po[offc].eq(pid).any(axis=1))]
    on_d = po[(po.defense_team_id==team_id) & (po[defc].eq(pid).any(axis=1))]
    off_d= po[(po.defense_team_id==team_id) & (~po[defc].eq(pid).any(axis=1))]
    def o(d):
        n=len(d)
        return dict(poss=n, ppp=d.points.sum()/n if n else np.nan,
                    fg3a_rate=d.fg3a.sum()/n if n else np.nan,
                    fg2a_rate=d.fg2a.sum()/n if n else np.nan,
                    fta_rate=d.fta.sum()/n if n else np.nan,
                    tov_rate=d.tov.sum()/n if n else np.nan,
                    oreb_rate=d.oreb.sum()/n if n else np.nan,
                    fg2_pct=d.fg2m.sum()/max(d.fg2a.sum(),1),
                    fg3_pct=d.fg3m.sum()/max(d.fg3a.sum(),1),
                    sec_chance=d.is_second_chance.mean() if n else np.nan)
    return o(on_o),o(off_o),o(on_d),o(off_d)

tid={'WAS':None,'CHI':None,'TOR':None,'CON':None}
pg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
for tm in tid: tid[tm]=int(pg.loc[pg.team_abbreviation==tm,'team_id'].astype(int).mode().iloc[0])

rows=[]
for pid,(nm,tm) in UCLA.items():
    oo,ofo,od,ofd = split(pid, tid[tm])
    rows.append(dict(player=nm, side="OFF (own team w/ player)", **oo))
    rows.append(dict(player=nm, side="OFF (own team w/o player)", **ofo))
    rows.append(dict(player=nm, side="DEF (opp vs player on)", **od))
    rows.append(dict(player=nm, side="DEF (opp vs player off)", **ofd))
r=pd.DataFrame(rows)
print("\n### POSSESSION-LEVEL ON/OFF SPLITS (partial season: through mid-July)")
for nm in [v[0] for v in UCLA.values()]:
    print(f"\n-- {nm}")
    print(r[r.player==nm].drop(columns="player").round(3).to_string(index=False))
r.to_csv(ROOT/"analysis/ucla_2026_draft_class/data/possession_on_off_splits.csv",index=False)
