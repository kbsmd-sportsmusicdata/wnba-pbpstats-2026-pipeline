from __future__ import annotations

from pathlib import Path
from typing import Dict

from .data_sources import stable_json_dumps


def export_eda_bundle(output_root: Path, row_counts: Dict[str, int]) -> Dict[str, int]:
    eda_dir = output_root / "data" / "eda"
    eda_dir.mkdir(parents=True, exist_ok=True)
    datasets = {
        "team_game_four_factors_2026.csv": {
            "grain": "one row per team-game",
            "keys": ["game_id", "team_abbreviation"],
            "recommended_questions": ["Which four-factor edges explain each team's grade?", "Which defenses suppress opponent eFG and free throws?"],
        },
        "bench_player_game_2026.csv": {
            "grain": "one row per bench player-game",
            "keys": ["game_id", "player_id", "team_abbreviation"],
            "recommended_questions": ["Which reserves combine efficiency and real minutes?", "Which bench players swing matchups by opponent?"],
        },
        "bench_team_game_2026.csv": {
            "grain": "one row per team-game bench unit",
            "keys": ["game_id", "team_abbreviation"],
            "recommended_questions": ["Which teams rely most on bench scoring?", "Which benches are gaining or losing trust over time?"],
        },
        "bench_team_summary_2026.csv": {
            "grain": "one row per team",
            "keys": ["team_abbreviation"],
            "recommended_questions": ["Which teams have the deepest second units?", "Which bench profiles are efficient versus volume-only?"],
        },
        "clutch_team_game_2026.csv": {
            "grain": "one row per team-game clutch window",
            "keys": ["game_id", "team_abbreviation"],
            "recommended_questions": ["Which teams create late-game scoring separation?", "Where does clutch sample size limit conclusions?"],
        },
        "player_midseason_impact_2026.csv": {
            "grain": "one row per player",
            "keys": ["player_id", "team_abbreviation"],
            "recommended_questions": ["How does All-Star value map to team grades?", "Which non-headliners still shape team outcomes?"],
        },
        "player_fit_profiles_2026.csv": {
            "grain": "one row per player",
            "keys": ["player_id", "team_abbreviation"],
            "recommended_questions": ["Which player skill profiles complement team needs?", "Where do spacing, rim pressure, and usage overlap?"],
        },
        "rapm_player_2026.csv": {
            "grain": "one row per player when lineup validation passes",
            "keys": ["player_id"],
            "recommended_questions": ["Which RAPM-style signals agree or disagree with box-score value?", "Which estimates are sample-size fragile?"],
        },
    }
    manifest = {
        "purpose": "EDA-ready dataset manifest for WNBA midseason team grades.",
        "datasets": datasets,
        "row_counts": row_counts,
        "agent_usage_note": "Use Codex chat for narrative EDA first; this repo provides deterministic datasets, not an LLM agent runner.",
    }
    (eda_dir / "eda_manifest_2026.json").write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    prompt = [
        "# Midseason Team Grades EDA Prompt",
        "",
        "Analyze the generated datasets across team four factors, bench depth, clutch context, player impact, All-Star value, and fit profiles.",
        "Prioritize cross-dataset signals, opponent/date context, and places where sample size limits the claim.",
        "Do not treat RAPM-style outputs as official RAPM; use the manifest status and diagnostics.",
    ]
    (eda_dir / "eda_prompt_2026.md").write_text("\n".join(prompt) + "\n", encoding="utf-8")
    return {"eda_manifest_2026.json": 1, "eda_prompt_2026.md": len(prompt)}
