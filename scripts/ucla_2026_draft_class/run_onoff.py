import sys; from pathlib import Path
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"scripts/ucla_2026_draft_class"))
from onoff import build_on_off
pd.set_option('display.width',260)
pg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
pg["player_id"]=pg.player_id.astype(int)
tg=pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet")
oo=build_on_off(pg,tg)
oo.to_csv(ROOT/"analysis/ucla_2026_draft_class/data/on_off_all_players.csv",index=False)
ucla={1643427:'Betts',1643447:'Jaquez',1643445:'Rice',1643455:'Dugalic',1643429:'Kneepkens',1643449:'Leger-Walker'}
c=['player_name','off_poss','on_ortg','on_drtg','on_net','off_ortg','off_drtg','off_net','ortg_swing','drtg_swing','net_swing','on_poss_share']
print(oo[oo.player_id.isin(ucla)][c].round(2).to_string(index=False))
print()
# league distribution of net_swing among 500+ poss players
pool=oo[oo.off_poss>=400]
print('league net_swing (>=400 off poss, n=%d): '%len(pool), pool.net_swing.describe().round(2).to_dict())
