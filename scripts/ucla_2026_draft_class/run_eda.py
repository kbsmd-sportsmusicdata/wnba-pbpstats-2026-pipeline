from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ucla_2026_draft_class"))
from metrics import season_totals, derive
from build_datasets import load_cohorts

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 200)

pg = pd.read_parquet(ROOT/"data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
pg["player_id"] = pg["player_id"].astype(int)
pg["game_date"] = pd.to_datetime(pg["game_date"])
bio = load_cohorts()
bio["player_id"] = pd.to_numeric(bio["player_id"], errors="coerce")

agg = derive(season_totals(pg))
agg = agg.merge(
    bio[["player_id","display_name","position_abbreviation","experience_years","draft_year",
         "draft_selection","draft_round","college_id","age","display_height","athlete_id"]],
    on="player_id", how="left")
agg["is_rookie"] = agg["experience_years"].eq(0)
agg["is_ucla"] = agg["draft_year"].eq(2026) & agg["college_id"].eq(26.0)
agg.to_csv(ROOT/"analysis/ucla_2026_draft_class/data/season_agg_all_players.csv", index=False)

print("players:", len(agg), "| rookies:", int(agg.is_rookie.sum()), "| UCLA:", int(agg.is_ucla.sum()))
print("rookies w/ >=200 min:", int(((agg.is_rookie)&(agg.minutes>=200)).sum()))
cols = ["player_name","teams","position_abbreviation","draft_selection","games_played","min_per_game",
        "minutes","off_poss","usage","pts_per_game","pace_neutral_pts_75","ts_pct","efg_pct",
        "shot_quality_avg","shot_making_over_sq","ast_75","tov_75","oreb_75","dreb_75","stl_75","blk_75",
        "foul_75","net_on_court","pm_per_100"]
print(agg[agg.is_ucla][cols].sort_values("draft_selection").round(3).to_string(index=False))
