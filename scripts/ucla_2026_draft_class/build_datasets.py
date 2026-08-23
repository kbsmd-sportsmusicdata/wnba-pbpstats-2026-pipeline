"""Build filtered analysis datasets for the 2026 UCLA six-player draft class.

Outputs land in analysis/ucla_2026_draft_class/data/. Read-only against the
existing pbpstats + sportsdataverse layers; nothing here mutates the pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis" / "ucla_2026_draft_class" / "data"
OUT.mkdir(parents=True, exist_ok=True)

PBP_PLAYER_GAME = ROOT / "data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet"
PBP_TEAM_GAME = ROOT / "data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet"
TEAM_GAME_DERIVED = ROOT / "data/processed/wnba_team_game/season=2026/team_game.parquet"
PLAYER_FEATURES = ROOT / "data/pbpstats_wnba_2026/features_latest/2026/player_totals_features_latest.csv"
TEAM_FEATURES = ROOT / "data/pbpstats_wnba_2026/features_latest/2026/team_totals_features_latest.csv"
PLAYER_CORE = ROOT / "analysis/role_fulfillment_matrix/data/live_inputs/player_core_2026.csv"
CROSSWALK = ROOT / "analysis/role_fulfillment_matrix/data/review/player_identity_crosswalk_2026.csv"
SDV = ROOT / "data/raw/sportsdataverse/wnba_2026"

UCLA_COLLEGE_ID = 26.0
DRAFT_YEAR = 2026.0


def load_cohorts() -> pd.DataFrame:
    """Bio + draft metadata for every 2026 player, with pbpstats ids attached."""
    core = pd.read_csv(PLAYER_CORE)
    xw = pd.read_csv(CROSSWALK)
    # placeholder ids ("espn:4790263") mark players with no pbpstats game record
    xw["player_id"] = pd.to_numeric(xw.player_id, errors="coerce")
    bio = core.merge(
        xw[["espn_athlete_id", "player_id", "pbpstats_player_name", "team_abbreviation"]],
        left_on="athlete_id",
        right_on="espn_athlete_id",
        how="left",
    )
    bio["is_rookie"] = bio["experience_years"].eq(0)
    bio["is_2026_draftee"] = bio["draft_year"].eq(DRAFT_YEAR)
    bio["is_ucla_six"] = bio["is_2026_draftee"] & bio["college_id"].eq(UCLA_COLLEGE_ID)
    bio["pick_overall"] = bio["draft_selection"]
    return bio


def main() -> None:
    bio = load_cohorts()
    ucla = bio[bio.is_ucla_six].copy().sort_values("pick_overall")
    ucla_ids = ucla["player_id"].dropna().astype(int).tolist()
    rookie_ids = (
        bio.loc[bio.is_rookie, "player_id"].dropna().astype(int).tolist()
    )

    pg = pd.read_parquet(PBP_PLAYER_GAME)
    pg["player_id"] = pg["player_id"].astype(int)
    pg["game_date"] = pd.to_datetime(pg["game_date"])

    tg = pd.read_parquet(PBP_TEAM_GAME)
    tg["game_date"] = pd.to_datetime(tg["game_date"])
    tgd = pd.read_parquet(TEAM_GAME_DERIVED)

    feats = pd.read_csv(PLAYER_FEATURES)
    feats["entity_id"] = pd.to_numeric(feats["entity_id"], errors="coerce")

    impact = pd.read_parquet(SDV / "wnba_player_impact_2026.parquet")
    box = pd.read_parquet(SDV / "player_box_2026.parquet")

    # ---- starter / bench role from ESPN box (has the `starter` flag pbpstats lacks)
    starts = (
        box[box.athlete_id.isin(ucla.athlete_id.tolist())]
        .assign(started=lambda d: d["starter"].fillna(False).astype(bool))
        .groupby("athlete_id")
        .agg(
            box_games=("game_id", "nunique"),
            games_started=("started", "sum"),
            dnp=("did_not_play", lambda s: int(s.fillna(False).astype(bool).sum())),
        )
        .reset_index()
    )

    frames = {
        "ucla_six_roster": ucla[
            [
                "athlete_id", "player_id", "display_name", "position_abbreviation",
                "display_height", "weight", "age", "jersey", "current_team_id",
                "team_abbreviation", "draft_round", "draft_selection", "college_id",
            ]
        ].merge(starts, on="athlete_id", how="left"),
        "ucla_six_game_logs": pg[pg.player_id.isin(ucla_ids)].copy(),
        "rookie_game_logs": pg[pg.player_id.isin(rookie_ids)].copy(),
        "player_game_all": pg,
        "team_game_pbp": tg,
        "team_game_derived": tgd,
        "player_features_all": feats,
        "player_impact_all": impact,
        "bio_all": bio,
    }

    for name in ("ucla_six_roster", "ucla_six_game_logs"):
        frames[name].to_csv(OUT / f"{name}.csv", index=False)

    meta = {
        "generated_from": "2026 pbpstats player/team game layer + sportsdataverse 2026",
        "season": 2026,
        "season_type": "Regular Season",
        "games_in_spine": int(pg.game_id.nunique()),
        "last_game_date": str(pg.game_date.max().date()),
        "ucla_six": ucla[["display_name", "player_id", "team_abbreviation", "draft_selection"]]
        .to_dict("records"),
        "rookie_pool_size": len(rookie_ids),
    }
    (OUT / "build_manifest.json").write_text(json.dumps(meta, indent=2, default=str))
    print(json.dumps(meta, indent=2, default=str))


if __name__ == "__main__":
    main()
