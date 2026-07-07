from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd


def export_viz_tables(value_board: pd.DataFrame, metric_panel: pd.DataFrame, archetypes: pd.DataFrame, viz_dir: Path) -> Dict[str, int]:
    viz_dir.mkdir(parents=True, exist_ok=True)

    rankings_cols = [
        "overall_rank",
        "player_id",
        "player_name",
        "team_abbreviation",
        "position",
        "candidate_tier",
        "allstar_value_score",
        "score_band",
        "production_score",
        "efficiency_score",
        "creation_score",
        "impact_score",
    ]
    rankings = value_board[[c for c in rankings_cols if c in value_board.columns]].copy()
    rankings.to_csv(viz_dir / "board_rankings_viz_2026.csv", index=False)

    component_cols = [
        "production_score",
        "efficiency_score",
        "creation_score",
        "impact_score",
        "availability_score",
        "team_context_score",
    ]
    components = value_board.melt(
        id_vars=["player_id", "player_name", "team_abbreviation", "overall_rank"],
        value_vars=[c for c in component_cols if c in value_board.columns],
        var_name="component",
        value_name="score",
    )
    components["component"] = components["component"].str.replace("_score", "", regex=False)
    components.to_csv(viz_dir / "score_components_viz_2026.csv", index=False)

    scatter = metric_panel.merge(
        archetypes[["player_id", "primary_archetype"]],
        on="player_id",
        how="left",
    ).merge(
        value_board[["player_id", "overall_rank", "allstar_value_score"]],
        on="player_id",
        how="left",
    )
    scatter = scatter.rename(
        columns={
            "usage": "x_metric_usage",
            "ts_pct_feature": "y_metric_ts_pct",
        }
    )
    scatter_cols = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "primary_archetype",
        "overall_rank",
        "allstar_value_score",
        "x_metric_usage",
        "y_metric_ts_pct",
        "shot_making_over_shotquality_pbp",
    ]
    scatter[[c for c in scatter_cols if c in scatter.columns]].to_csv(viz_dir / "archetype_scatter_viz_2026.csv", index=False)

    team_rep = value_board.groupby("team_abbreviation", dropna=False).agg(
        candidates=("player_id", "count"),
        top_score=("allstar_value_score", "max"),
        avg_score=("allstar_value_score", "mean"),
    ).reset_index()
    team_rep.to_csv(viz_dir / "team_representation_viz_2026.csv", index=False)

    social = value_board.head(20).merge(
        archetypes[["player_id", "primary_archetype"]],
        on="player_id",
        how="left",
    )
    social["display_line"] = social.apply(
        lambda row: f"#{int(row['overall_rank'])} {row['player_name']} ({row['team_abbreviation']}) - {row['allstar_value_score']:.1f}",
        axis=1,
    )
    social["proof_point"] = social.apply(
        lambda row: f"{row['primary_archetype']} | production {row['production_score']:.1f}, impact {row['impact_score']:.1f}",
        axis=1,
    )
    social_cols = ["overall_rank", "player_id", "player_name", "team_abbreviation", "display_line", "proof_point"]
    social[[c for c in social_cols if c in social.columns]].to_csv(viz_dir / "social_card_players_2026.csv", index=False)

    return {
        "board_rankings_viz_2026.csv": len(rankings),
        "score_components_viz_2026.csv": len(components),
        "archetype_scatter_viz_2026.csv": len(scatter),
        "team_representation_viz_2026.csv": len(team_rep),
        "social_card_players_2026.csv": len(social),
    }


def export_editorial_assets(value_board: pd.DataFrame, archetypes: pd.DataFrame, editorial_dir: Path, *, as_of_date: str) -> Dict[str, int]:
    editorial_dir.mkdir(parents=True, exist_ok=True)
    top = value_board.head(10).merge(
        archetypes[["player_id", "primary_archetype", "archetype_reasons"]],
        on="player_id",
        how="left",
    )

    manifest_lines = [
        "# WNBA Midseason All-Star Value Board Asset Manifest",
        "",
        f"Data through: {as_of_date}",
        "",
        "## Recommended Assets",
        "",
        "- Board rankings table: `data/viz/board_rankings_viz_2026.csv`",
        "- Score component long table: `data/viz/score_components_viz_2026.csv`",
        "- Archetype scatter source: `data/viz/archetype_scatter_viz_2026.csv`",
        "- Team representation source: `data/viz/team_representation_viz_2026.csv`",
        "- Social card copy: `data/viz/social_card_players_2026.csv`",
        "",
        "## Top Board Rows",
        "",
        "| Rank | Player | Team | Score | Archetype |",
        "| ---: | --- | --- | ---: | --- |",
    ]
    for _, row in top.iterrows():
        manifest_lines.append(
            f"| {int(row['overall_rank'])} | {row['player_name']} | {row['team_abbreviation']} | {row['allstar_value_score']:.1f} | {row['primary_archetype']} |"
        )
    (editorial_dir / "substack_asset_manifest_2026.md").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    draft_lines = [
        "# WNBA Midseason All-Star Value Board",
        "",
        f"_Data through {as_of_date}. This is a value-first editorial board, not an official ballot prediction._",
        "",
        "## The Board",
        "",
    ]
    for _, row in top.head(5).iterrows():
        draft_lines.extend(
            [
                f"### {int(row['overall_rank'])}. {row['player_name']}, {row['team_abbreviation']}",
                "",
                f"All-Star Value Score: **{row['allstar_value_score']:.1f}**. Archetype: **{row['primary_archetype']}**.",
                "",
                f"Why the model likes this case: {row['board_note']} {row['archetype_reasons']}.",
                "",
            ]
        )
    draft_lines.extend(
        [
            "## Chart Checklist",
            "",
            "- Ranked top-20 board",
            "- Component score bars for top candidates",
            "- Archetype scatter using usage and true shooting",
            "- Team representation view",
        ]
    )
    (editorial_dir / "substack_draft_2026.md").write_text("\n".join(draft_lines) + "\n", encoding="utf-8")

    return {
        "substack_asset_manifest_2026.md": len(manifest_lines),
        "substack_draft_2026.md": len(draft_lines),
    }

