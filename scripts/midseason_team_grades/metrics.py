from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd


TEAM_ABBR_ALIASES = {
    "GS": "GSV",
    "GSV": "GSV",
    "LA": "LAS",
    "LAS": "LAS",
    "LV": "LVA",
    "LVA": "LVA",
    "NY": "NYL",
    "NYL": "NYL",
    "PHO": "PHX",
    "PHX": "PHX",
    "POR": "PDX",
    "PDX": "PDX",
    "WSH": "WAS",
    "WAS": "WAS",
}


def safe_divide(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    return np.where(denominator > 0, numerator / denominator, np.nan)


def team_key(value) -> str:
    raw = str(value).strip().upper()
    return TEAM_ABBR_ALIASES.get(raw, raw)


def id_key(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def percentile_rank(series: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if not higher_is_better:
        values = -values
    if values.notna().sum() <= 1:
        return pd.Series(np.where(values.notna(), 100.0, np.nan), index=series.index)
    return values.rank(pct=True, method="average") * 100


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def league_team_keys(standings: pd.DataFrame) -> set[str]:
    """The franchise abbreviations that count as league teams, taken from the standings."""
    if standings.empty or "team_abbreviation" not in standings.columns:
        return set()
    return {team_key(value) for value in standings["team_abbreviation"].dropna().unique()}


def filter_to_league_teams(box: pd.DataFrame, standings: pd.DataFrame) -> pd.DataFrame:
    """Drop exhibition games played by non-franchise sides.

    The 2026 All-Star Game is tagged as regular season in the ESPN feed, so it cannot be
    filtered on ``season_type``; TEAM SPOON and TEAM COOP would otherwise be graded as
    league teams. The standings are used as the authoritative franchise list rather than a
    hard-coded set, so this keeps working as the league expands.
    """
    valid = league_team_keys(standings)
    if box.empty or not valid or "team_abbreviation" not in box.columns:
        return box

    df = box.copy()
    team_keys = df["team_abbreviation"].map(team_key)
    keep = team_keys.isin(valid)
    if "opponent_team_abbreviation" in df.columns:
        keep &= df["opponent_team_abbreviation"].map(team_key).isin(valid)
    if "game_id" in df.columns:
        # Both sides of an exhibition go, not just the non-franchise one.
        excluded_games = set(df.loc[~keep, "game_id"])
        keep &= ~df["game_id"].isin(excluded_games)
    return df[keep].copy()


def filter_pbp_to_league_teams(pbp: pd.DataFrame, standings: pd.DataFrame) -> pd.DataFrame:
    """Drop exhibition games from a play-by-play feed, which names its teams per game."""
    valid = league_team_keys(standings)
    required = {"home_team_abbrev", "away_team_abbrev"}
    if pbp.empty or not valid or not required.issubset(pbp.columns):
        return pbp
    keep = pbp["home_team_abbrev"].map(team_key).isin(valid) & pbp["away_team_abbrev"].map(team_key).isin(valid)
    return pbp[keep].copy()


def dedupe_allstar_board(allstar_board: pd.DataFrame) -> pd.DataFrame:
    """One numeric-scored row per player.

    Guards the join against a damaged board file: the committed 2026 artifact carries an
    embedded header row and column-shifted duplicates, which would otherwise multiply rows
    through the left merge.
    """
    if allstar_board.empty or "player_id" not in allstar_board.columns:
        return allstar_board

    df = allstar_board.copy()
    if "allstar_value_score" in df.columns:
        df["allstar_value_score"] = pd.to_numeric(df["allstar_value_score"], errors="coerce")
        df = df[df["allstar_value_score"].notna()]
    df["player_id"] = df["player_id"].map(id_key)
    return df[df["player_id"].astype(bool)].drop_duplicates(subset=["player_id"], keep="first")


def build_team_game_four_factors(team_box: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "game_id",
        "game_date",
        "team_id",
        "team_abbreviation",
        "opponent_team_id",
        "opponent_team_abbreviation",
        "home_away",
        "team_score",
        "opponent_team_score",
        "team_winner",
        "off_efg_pct",
        "off_tov_pct",
        "off_orb_pct",
        "off_fta_rate",
        "def_efg_pct",
        "def_tov_pct",
        "def_orb_allowed_pct",
        "def_fta_rate_allowed",
        "net_points",
    ]
    required = {"game_id", "team_abbreviation", "opponent_team_abbreviation", "field_goals_attempted"}
    if team_box.empty or not required.issubset(team_box.columns):
        return _empty(columns)

    df = team_box.copy()
    df["team_abbreviation"] = df["team_abbreviation"].map(team_key)
    df["opponent_team_abbreviation"] = df["opponent_team_abbreviation"].map(team_key)
    df["home_away"] = df.get("team_home_away", df.get("home_away", "")).astype(str)
    fga = pd.to_numeric(df["field_goals_attempted"], errors="coerce")
    fgm = pd.to_numeric(df.get("field_goals_made"), errors="coerce")
    fg3m = pd.to_numeric(df.get("three_point_field_goals_made"), errors="coerce")
    fta = pd.to_numeric(df.get("free_throws_attempted"), errors="coerce")
    tov = pd.to_numeric(df.get("turnovers"), errors="coerce")
    df["off_efg_pct"] = safe_divide(fgm + 0.5 * fg3m, fga) * 100
    df["off_tov_pct"] = safe_divide(tov, fga + 0.44 * fta + tov) * 100
    df["off_fta_rate"] = safe_divide(fta, fga) * 100

    opp_reb = df[["game_id", "team_abbreviation", "defensive_rebounds"]].rename(
        columns={"team_abbreviation": "opponent_team_abbreviation", "defensive_rebounds": "opponent_defensive_rebounds"}
    )
    df = df.merge(opp_reb, on=["game_id", "opponent_team_abbreviation"], how="left")
    df["off_orb_pct"] = safe_divide(df.get("offensive_rebounds"), df["offensive_rebounds"] + df["opponent_defensive_rebounds"]) * 100

    opp_metrics = df[
        [
            "game_id",
            "team_abbreviation",
            "off_efg_pct",
            "off_tov_pct",
            "off_orb_pct",
            "off_fta_rate",
        ]
    ].rename(
        columns={
            "team_abbreviation": "opponent_team_abbreviation",
            "off_efg_pct": "def_efg_pct",
            "off_tov_pct": "def_tov_pct",
            "off_orb_pct": "def_orb_allowed_pct",
            "off_fta_rate": "def_fta_rate_allowed",
        }
    )
    df = df.merge(opp_metrics, on=["game_id", "opponent_team_abbreviation"], how="left")
    df["net_points"] = pd.to_numeric(df.get("team_score"), errors="coerce") - pd.to_numeric(df.get("opponent_team_score"), errors="coerce")
    df = df.rename(columns={"team_home_away": "home_away"})
    for col in ["off_efg_pct", "off_tov_pct", "off_orb_pct", "off_fta_rate", "def_efg_pct", "def_tov_pct", "def_orb_allowed_pct", "def_fta_rate_allowed"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(1)
    return df[[c for c in columns if c in df.columns]].copy()


def build_bench_player_game(player_box: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "game_id",
        "game_date",
        "player_id",
        "player_name",
        "team_abbreviation",
        "opponent_team_abbreviation",
        "home_away",
        "minutes",
        "points",
        "rebounds",
        "assists",
        "turnovers",
        "field_goals_made",
        "field_goals_attempted",
        "three_point_field_goals_made",
        "free_throws_attempted",
        "plus_minus",
        "bench_ts_pct",
        "bench_efg_pct",
    ]
    if player_box.empty or "starter" not in player_box.columns:
        return _empty(columns)
    played = player_box[player_box.get("did_not_play", False) != True].copy()  # noqa: E712
    bench = played[played["starter"] == False].copy()  # noqa: E712
    if bench.empty:
        return _empty(columns)
    bench["team_abbreviation"] = bench["team_abbreviation"].map(team_key)
    bench["opponent_team_abbreviation"] = bench["opponent_team_abbreviation"].map(team_key)
    fga = pd.to_numeric(bench.get("field_goals_attempted"), errors="coerce")
    fgm = pd.to_numeric(bench.get("field_goals_made"), errors="coerce")
    fg3m = pd.to_numeric(bench.get("three_point_field_goals_made"), errors="coerce")
    fta = pd.to_numeric(bench.get("free_throws_attempted"), errors="coerce")
    pts = pd.to_numeric(bench.get("points"), errors="coerce")
    bench["bench_ts_pct"] = safe_divide(pts, 2 * (fga + 0.44 * fta)) * 100
    bench["bench_efg_pct"] = safe_divide(fgm + 0.5 * fg3m, fga) * 100
    bench = bench.rename(columns={"athlete_id": "player_id", "athlete_display_name": "player_name"})
    return bench[[c for c in columns if c in bench.columns]].copy()


def build_bench_team_game(player_box: pd.DataFrame, team_box: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "game_id",
        "game_date",
        "team_abbreviation",
        "opponent_team_abbreviation",
        "home_away",
        "team_score",
        "bench_points",
        "bench_points_share",
        "bench_minutes",
        "team_minutes",
        "bench_minutes_share",
        "bench_rebounds",
        "bench_assists",
        "bench_turnovers",
        "bench_ts_pct",
        "bench_efg_pct",
        "bench_ast_to",
        "bench_plus_minus",
        "bench_net_rating",
    ]
    bench_players = build_bench_player_game(player_box)
    if bench_players.empty:
        return _empty(columns)
    played = player_box[player_box.get("did_not_play", False) != True].copy()  # noqa: E712
    played["team_abbreviation"] = played["team_abbreviation"].map(team_key)
    team_minutes = played.groupby(["game_id", "team_abbreviation"], dropna=False)["minutes"].sum().reset_index(name="team_minutes")
    grouped = bench_players.groupby(["game_id", "game_date", "team_abbreviation", "opponent_team_abbreviation", "home_away"], dropna=False).agg(
        bench_points=("points", "sum"),
        bench_minutes=("minutes", "sum"),
        bench_rebounds=("rebounds", "sum"),
        bench_assists=("assists", "sum"),
        bench_turnovers=("turnovers", "sum"),
        bench_fgm=("field_goals_made", "sum"),
        bench_fga=("field_goals_attempted", "sum"),
        bench_fg3m=("three_point_field_goals_made", "sum"),
        bench_fta=("free_throws_attempted", "sum"),
        bench_plus_minus=("plus_minus", "sum"),
    ).reset_index()
    grouped = grouped.merge(team_minutes, on=["game_id", "team_abbreviation"], how="left")
    if not team_box.empty:
        team_context = team_box.copy()
        team_context["team_abbreviation"] = team_context["team_abbreviation"].map(team_key)
        team_context = team_context.rename(columns={"team_home_away": "home_away"})
        grouped = grouped.merge(
            team_context[["game_id", "team_abbreviation", "team_score"]],
            on=["game_id", "team_abbreviation"],
            how="left",
        )
    grouped["bench_points_share"] = safe_divide(grouped["bench_points"], grouped.get("team_score")) * 100
    grouped["bench_minutes_share"] = safe_divide(grouped["bench_minutes"], grouped["team_minutes"]) * 100
    grouped["bench_ts_pct"] = safe_divide(grouped["bench_points"], 2 * (grouped["bench_fga"] + 0.44 * grouped["bench_fta"])) * 100
    grouped["bench_efg_pct"] = safe_divide(grouped["bench_fgm"] + 0.5 * grouped["bench_fg3m"], grouped["bench_fga"]) * 100
    grouped["bench_ast_to"] = safe_divide(grouped["bench_assists"], grouped["bench_turnovers"])
    grouped["bench_net_rating"] = np.nan
    for col in ["bench_points_share", "bench_minutes_share", "bench_ts_pct", "bench_efg_pct", "bench_ast_to"]:
        grouped[col] = pd.to_numeric(grouped[col], errors="coerce").round(1)
    return grouped[[c for c in columns if c in grouped.columns]].copy()


def build_bench_team_summary(bench_team_game: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "team_abbreviation",
        "bench_games",
        "bench_points_per_game",
        "bench_minutes_per_game",
        "bench_points_share",
        "bench_minutes_share",
        "bench_ts_pct",
        "bench_efg_pct",
        "bench_ast_to",
        "last3_bench_points_per_game",
        "bench_trend_label",
        "bench_depth_rank",
    ]
    if bench_team_game.empty:
        return _empty(columns)
    summary = bench_team_game.groupby("team_abbreviation", dropna=False).agg(
        bench_games=("game_id", "nunique"),
        bench_points_per_game=("bench_points", "mean"),
        bench_minutes_per_game=("bench_minutes", "mean"),
        bench_points_share=("bench_points_share", "mean"),
        bench_minutes_share=("bench_minutes_share", "mean"),
        bench_ts_pct=("bench_ts_pct", "mean"),
        bench_efg_pct=("bench_efg_pct", "mean"),
        bench_ast_to=("bench_ast_to", "mean"),
    ).reset_index()
    last3 = bench_team_game.sort_values(["team_abbreviation", "game_date"]).groupby("team_abbreviation").tail(3)
    last3 = last3.groupby("team_abbreviation")["bench_points"].mean().reset_index(name="last3_bench_points_per_game")
    summary = summary.merge(last3, on="team_abbreviation", how="left")
    summary["bench_trend_label"] = np.select(
        [
            summary["last3_bench_points_per_game"] >= summary["bench_points_per_game"] * 1.10,
            summary["last3_bench_points_per_game"] <= summary["bench_points_per_game"] * 0.90,
        ],
        ["surging", "slipping"],
        default="steady",
    )
    summary["bench_depth_rank"] = summary["bench_points_per_game"].rank(ascending=False, method="min").astype(int)
    numeric_cols = [c for c in columns if c not in {"team_abbreviation", "bench_trend_label", "bench_depth_rank"}]
    summary[numeric_cols] = summary[numeric_cols].round(1)
    return summary[columns].copy()


def build_clutch_team_game(espn_pbp: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "game_id",
        "game_date",
        "team_abbreviation",
        "opponent_team_abbreviation",
        "home_away",
        "clutch_points",
        "clutch_opp_points",
        "clutch_point_diff",
        "clutch_possessions",
        "clutch_net_rating",
    ]
    required = {"game_id", "home_team_id", "away_team_id", "home_team_abbrev", "away_team_abbrev", "team_id", "score_value"}
    if espn_pbp.empty or not required.issubset(espn_pbp.columns):
        return _empty(columns)
    pbp = espn_pbp.copy()
    pbp["home_team_abbrev"] = pbp["home_team_abbrev"].map(team_key)
    pbp["away_team_abbrev"] = pbp["away_team_abbrev"].map(team_key)
    pbp["score_margin"] = pd.to_numeric(pbp.get("home_score"), errors="coerce") - pd.to_numeric(pbp.get("away_score"), errors="coerce")
    clutch = pbp[
        (pd.to_numeric(pbp.get("start_game_seconds_remaining"), errors="coerce") <= 300)
        & (pbp["score_margin"].abs() <= 6)
        & (pbp.get("scoring_play", True) == True)  # noqa: E712
        & (pd.to_numeric(pbp.get("score_value"), errors="coerce") > 0)
    ].copy()
    clutch["score_value"] = pd.to_numeric(clutch["score_value"], errors="coerce").fillna(0)
    clutch["team_id_key"] = clutch["team_id"].map(id_key)
    clutch_points = (
        clutch.groupby(["game_id", "team_id_key"], dropna=False)["score_value"]
        .sum()
        .to_dict()
    )
    games = pbp.drop_duplicates("game_id")[
        ["game_id", "game_date", "home_team_id", "home_team_abbrev", "away_team_id", "away_team_abbrev"]
    ]
    rows = []
    for _, game in games.iterrows():
        for side in ["home", "away"]:
            team_id = id_key(game[f"{side}_team_id"])
            team = game[f"{side}_team_abbrev"]
            opp = game["away_team_abbrev"] if side == "home" else game["home_team_abbrev"]
            pts = clutch_points.get((game["game_id"], team_id), 0)
            opp_id = id_key(game["away_team_id"] if side == "home" else game["home_team_id"])
            opp_pts = clutch_points.get((game["game_id"], opp_id), 0)
            rows.append(
                {
                    "game_id": game["game_id"],
                    "game_date": game["game_date"],
                    "team_abbreviation": team,
                    "opponent_team_abbreviation": opp,
                    "home_away": side,
                    "clutch_points": int(pts),
                    "clutch_opp_points": int(opp_pts),
                    "clutch_point_diff": int(pts - opp_pts),
                    "clutch_possessions": np.nan,
                    "clutch_net_rating": np.nan,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def build_player_midseason_impact(allstar_board: pd.DataFrame, player_features: pd.DataFrame) -> pd.DataFrame:
    if allstar_board.empty and player_features.empty:
        return _empty(["player_id", "player_name", "team_abbreviation"])
    if allstar_board.empty:
        impact = player_features.copy().rename(columns={"entity_id_feature": "player_id", "entity_name_feature": "player_name"})
    else:
        impact = dedupe_allstar_board(allstar_board)
    keep = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "overall_rank",
        "allstar_value_score",
        "production_score",
        "efficiency_score",
        "creation_score",
        "impact_score",
        "availability_score",
        "team_context_score",
        "starter_role_flag",
        "start_rate",
    ]
    return impact[[c for c in keep if c in impact.columns]].copy()


def build_player_fit_profiles(player_features: pd.DataFrame, allstar_board: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "usage",
        "ts_pct_feature",
        "rim_fga_share",
        "three_point_fga_share",
        "shot_diet_profile_label",
        "fit_profile_tags",
    ]
    if player_features.empty:
        return _empty(columns)
    df = player_features.copy().rename(columns={"entity_id_feature": "player_id", "entity_name_feature": "player_name"})
    if not allstar_board.empty and {"player_id", "allstar_value_score"}.issubset(allstar_board.columns):
        # The two sources type player_id differently (integer ids on the board, string ids
        # on the features side), which makes the merge raise rather than silently miss.
        board = dedupe_allstar_board(allstar_board)[["player_id", "allstar_value_score"]]
        df["player_id"] = df["player_id"].map(id_key)
        df = df.merge(board, on="player_id", how="left")

    def tags(row) -> str:
        out = []
        if pd.to_numeric(row.get("usage"), errors="coerce") >= 24:
            out.append("high-usage")
        if pd.to_numeric(row.get("three_point_fga_share"), errors="coerce") >= 0.35:
            out.append("spacing")
        if pd.to_numeric(row.get("rim_fga_share"), errors="coerce") >= 0.35:
            out.append("rim-pressure")
        if pd.to_numeric(row.get("ts_pct_feature"), errors="coerce") >= 0.58:
            out.append("efficient")
        return ", ".join(out) if out else "context-dependent"

    df["fit_profile_tags"] = df.apply(tags, axis=1)
    keep = [c for c in columns + ["allstar_value_score"] if c in df.columns]
    return df[keep].copy()


def build_team_grade_panel(
    four_factors: pd.DataFrame,
    bench_summary: pd.DataFrame,
    team_features: pd.DataFrame,
    standings: pd.DataFrame,
) -> pd.DataFrame:
    if four_factors.empty and bench_summary.empty:
        return _empty(["team_abbreviation"])
    if four_factors.empty:
        panel = bench_summary[["team_abbreviation"]].copy()
    else:
        panel = four_factors.groupby("team_abbreviation", dropna=False).agg(
            games=("game_id", "nunique"),
            net_points_per_game=("net_points", "mean"),
            off_efg_pct=("off_efg_pct", "mean"),
            off_tov_pct=("off_tov_pct", "mean"),
            off_orb_pct=("off_orb_pct", "mean"),
            off_fta_rate=("off_fta_rate", "mean"),
            def_efg_pct=("def_efg_pct", "mean"),
            def_tov_pct=("def_tov_pct", "mean"),
            def_orb_allowed_pct=("def_orb_allowed_pct", "mean"),
            def_fta_rate_allowed=("def_fta_rate_allowed", "mean"),
        ).reset_index()
    if not bench_summary.empty:
        panel = panel.merge(bench_summary, on="team_abbreviation", how="left")
    if not standings.empty:
        stand = standings.copy()
        if "team_abbreviation" in stand.columns:
            stand["team_abbreviation"] = stand["team_abbreviation"].map(team_key)
            stand["team_win_pct"] = pd.to_numeric(stand.get("win_pct"), errors="coerce")
            panel = panel.merge(stand[["team_abbreviation", "team_win_pct"]].drop_duplicates("team_abbreviation"), on="team_abbreviation", how="left")
    panel["offense_score"] = (
        percentile_rank(panel.get("off_efg_pct", pd.Series(index=panel.index)))
        + percentile_rank(panel.get("off_tov_pct", pd.Series(index=panel.index)), higher_is_better=False)
        + percentile_rank(panel.get("off_orb_pct", pd.Series(index=panel.index)))
        + percentile_rank(panel.get("off_fta_rate", pd.Series(index=panel.index)))
    ) / 4
    panel["defense_score"] = (
        percentile_rank(panel.get("def_efg_pct", pd.Series(index=panel.index)), higher_is_better=False)
        + percentile_rank(panel.get("def_orb_allowed_pct", pd.Series(index=panel.index)), higher_is_better=False)
        + percentile_rank(panel.get("def_fta_rate_allowed", pd.Series(index=panel.index)), higher_is_better=False)
        + percentile_rank(panel.get("def_tov_pct", pd.Series(index=panel.index)))
    ) / 4
    panel["bench_score"] = (
        percentile_rank(panel.get("bench_points_per_game", pd.Series(index=panel.index)))
        + percentile_rank(panel.get("bench_minutes_share", pd.Series(index=panel.index)))
        + percentile_rank(panel.get("bench_ts_pct", pd.Series(index=panel.index)))
    ) / 3
    panel["team_grade_score"] = panel[["offense_score", "defense_score", "bench_score"]].mean(axis=1, skipna=True)
    panel["team_grade_rank"] = panel["team_grade_score"].rank(ascending=False, method="min").astype(int)
    return panel.sort_values("team_grade_rank").reset_index(drop=True)


def build_rapm_player(wnba_stats_pbp: pd.DataFrame, config: Dict) -> Tuple[pd.DataFrame, str]:
    columns = ["player_id", "rapm_style_points_per_100_events", "rapm_events", "rapm_model_status"]
    if wnba_stats_pbp.empty:
        return _empty(columns), "skipped_missing_lineup_source"
    needed = {"player1_team_abbreviation", "home_player1", "home_player2", "home_player3", "home_player4", "home_player5", "away_player1", "away_player2", "away_player3", "away_player4", "away_player5"}
    if not needed.issubset(wnba_stats_pbp.columns):
        return _empty(columns), "skipped_missing_lineup_columns"
    pbp = wnba_stats_pbp.copy()
    pbp["rapm_event_points"] = pd.to_numeric(pbp.get("score_value"), errors="coerce")
    if pbp["rapm_event_points"].notna().sum() == 0 and "shot_value" in pbp.columns:
        made = pbp.get("shot_result", pd.Series("", index=pbp.index)).astype(str).str.lower().eq("made")
        pbp["rapm_event_points"] = np.where(made, pd.to_numeric(pbp["shot_value"], errors="coerce"), np.nan)
    if "garbage_time" in pbp.columns:
        garbage_time = pd.to_numeric(pbp["garbage_time"], errors="coerce").fillna(0)
    else:
        garbage_time = pd.Series(0, index=pbp.index)
    rows = pbp[(pbp["rapm_event_points"] > 0) & (garbage_time != 1)].copy()
    lineup_cols = [f"home_player{i}" for i in range(1, 6)] + [f"away_player{i}" for i in range(1, 6)]
    rows = rows.dropna(subset=lineup_cols)
    min_events = int(config.get("rapm", {}).get("min_scoring_events", 100))
    if len(rows) < min_events:
        return _empty(columns), "skipped_insufficient_scoring_events"
    player_ids = sorted({str(value) for col in lineup_cols for value in rows[col].dropna().astype(str)})
    player_index = {player_id: idx for idx, player_id in enumerate(player_ids)}
    x = np.zeros((len(rows), len(player_ids)))
    y = np.zeros(len(rows))
    for row_num, (_, row) in enumerate(rows.iterrows()):
        for col in [f"home_player{i}" for i in range(1, 6)]:
            x[row_num, player_index[str(row[col])]] = 1
        for col in [f"away_player{i}" for i in range(1, 6)]:
            x[row_num, player_index[str(row[col])]] = -1
        scoring_team = team_key(row.get("player1_team_abbreviation"))
        home_team = team_key(row.get("team_home", row.get("home_team_abbreviation", "")))
        sign = 1 if scoring_team == home_team else -1
        if not home_team:
            sign = 1
        y[row_num] = sign * float(row["rapm_event_points"])
    alpha = float(config.get("rapm", {}).get("ridge_alpha", 10.0))
    beta = np.linalg.solve(x.T @ x + alpha * np.eye(x.shape[1]), x.T @ y)
    out = pd.DataFrame(
        {
            "player_id": player_ids,
            "rapm_style_points_per_100_events": beta * 100,
            "rapm_events": len(rows),
            "rapm_model_status": "rapm_style_scoring_event_ridge",
        }
    )
    out["rapm_style_points_per_100_events"] = out["rapm_style_points_per_100_events"].round(3)
    return out.sort_values("rapm_style_points_per_100_events", ascending=False).reset_index(drop=True), "rapm_style_scoring_event_ridge"
