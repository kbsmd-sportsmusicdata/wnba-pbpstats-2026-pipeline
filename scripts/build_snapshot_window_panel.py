#!/usr/bin/env python3
"""Build the PBPStats snapshot window panel for WNBA 2026.

The PBPStats feeds publish season-to-date totals only. This builder differences the daily
snapshot archive in ``features_master`` so that team and player history becomes a panel of
game windows, which is what trend, identity-shift and trajectory analysis need.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from snapshot_window_panel.data_sources import (
    apply_runtime_overrides,
    ensure_output_dirs,
    hash_config,
    load_config,
    load_sources,
    resolve_output_root,
    stable_json_dumps,
    utc_now_iso,
    write_github_step_summary,
)
from snapshot_window_panel.derived import (
    attach_team_possession_share,
    build_player_window_metrics,
    build_team_window_metrics,
)
from snapshot_window_panel.panel import (
    apply_weighted_averages,
    build_window_frame,
    detect_restatements,
    finalize_panel,
    restatement_check_columns,
)


STAGES = {"team", "player", "all"}

TEAM_IDENTIFIERS = [
    "entity_id",
    "team_abbreviation",
    "name",
    "window_index",
    "is_baseline_block",
    "window_start_utc",
    "window_end_utc",
    "snapshot_span_days",
    "covered_game_date_start",
    "covered_game_date_end",
    "games_in_window",
    "cumulative_games_played",
]

PLAYER_IDENTIFIERS = [
    "entity_id",
    "name",
    "team_abbreviation",
    "team_changed_in_window",
    "window_index",
    "is_baseline_block",
    "window_start_utc",
    "window_end_utc",
    "snapshot_span_days",
    "covered_game_date_start",
    "covered_game_date_end",
    "games_in_window",
    "cumulative_games_played",
]


def output_paths(output_root: Path) -> Dict[str, Path]:
    processed = output_root / "data" / "processed"
    return {
        "team_panel": processed / "team_window_panel_2026.csv",
        "player_panel": processed / "player_window_panel_2026.csv",
        "qa": processed / "window_panel_qa_2026.csv",
        "manifest": processed / "run_manifest_2026.json",
    }


def _write(path: Path, df: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def _read_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def build_level_panel(
    master: pd.DataFrame,
    *,
    config: Dict[str, Any],
    level: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Difference one master archive into a finished, QA'd window panel."""
    panel_config = config.get("panel", {})
    detection = config.get("restatement_detection", {})

    raw, additive_columns, specs, quarantine = build_window_frame(master, config=config, level=level)
    stats: Dict[str, Any] = {
        "additive_columns_differenced": len(additive_columns),
        "weighted_averages_reconstructed": [spec["column"] for spec in specs],
        "snapshots_quarantined": int(len(quarantine)),
        "quarantined_snapshots": [str(s) for s in quarantine.get("snapshot_utc", [])],
    }
    if raw.empty:
        stats["status"] = "no_windows_built"
        return pd.DataFrame(), pd.DataFrame(), stats

    cleaned, qa = detect_restatements(
        raw,
        restatement_check_columns(raw, additive_columns),
        ratio_threshold=float(detection.get("ratio_threshold", 5.0)),
        entity_share_threshold=float(detection.get("entity_share_threshold", 0.5)),
        min_history_windows=int(detection.get("min_history_windows", 3)),
    )
    cleaned = apply_weighted_averages(cleaned, specs)

    identifiers = TEAM_IDENTIFIERS if level == "team" else PLAYER_IDENTIFIERS
    finished = finalize_panel(
        cleaned,
        min_games_in_window=int(panel_config.get("min_games_in_window", 1)),
        identifier_columns=identifiers,
    )
    finished = build_team_window_metrics(finished) if level == "team" else build_player_window_metrics(finished)

    if not quarantine.empty:
        quarantine_rows = pd.DataFrame(
            [
                {
                    "column": "*all columns*",
                    "issue": "snapshot_quarantined",
                    "windows_invalidated": 0,
                    "entities_affected": int(row["entities_screened"]),
                    "first_window_end_utc": row["snapshot_utc"],
                    "last_window_end_utc": row["snapshot_utc"],
                    "detail": (
                        f"{row['out_of_envelope_share']:.4f} of {row['columns_screened']} additive columns "
                        "broke the cumulative monotone envelope; the snapshot was dropped and adjacent "
                        "windows bridge across it."
                    ),
                }
                for _, row in quarantine.iterrows()
            ]
        )
        qa = pd.concat([qa, quarantine_rows], ignore_index=True) if not qa.empty else quarantine_rows

    if not qa.empty:
        qa.insert(0, "level", level)
    stats.update(
        {
            "status": "ok",
            "entities": int(finished["entity_id"].nunique()) if not finished.empty else 0,
            "windows": int(len(finished)),
            "games_covered": float(pd.to_numeric(finished.get("games_in_window"), errors="coerce").sum()),
            "first_window_end_utc": str(finished["window_end_utc"].min()) if not finished.empty else None,
            "last_window_end_utc": str(finished["window_end_utc"].max()) if not finished.empty else None,
        }
    )
    return finished, qa, stats


def build_outputs(config: Dict[str, Any], stage: str) -> Dict[str, Any]:
    output_root = resolve_output_root(config)
    ensure_output_dirs(output_root)
    paths = output_paths(output_root)
    sources = load_sources(config)

    previous_manifest: Dict[str, Any] = {}
    if paths["manifest"].exists():
        previous_manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    row_counts: Dict[str, int] = dict(previous_manifest.get("outputs", {}))
    panel_stats: Dict[str, Any] = dict(previous_manifest.get("panel_stats", {}))

    qa_frames: List[pd.DataFrame] = []
    team_panel = pd.DataFrame()

    if stage in {"team", "all"}:
        team_panel, team_qa, team_stats = build_level_panel(sources.team_master, config=config, level="team")
        panel_stats["team"] = team_stats
        row_counts["team_window_panel_2026.csv"] = _write(paths["team_panel"], team_panel)
        qa_frames.append(team_qa)

    if stage in {"player", "all"}:
        player_panel, player_qa, player_stats = build_level_panel(
            sources.player_master, config=config, level="player"
        )
        if team_panel.empty:
            team_panel = _read_optional(paths["team_panel"])
        player_panel, share_stats = attach_team_possession_share(player_panel, team_panel)
        player_stats["team_possession_share_match_rate"] = share_stats["match_rate"]
        panel_stats["player"] = player_stats
        row_counts["player_window_panel_2026.csv"] = _write(paths["player_panel"], player_panel)
        qa_frames.append(player_qa)

    qa_frames = [frame for frame in qa_frames if not frame.empty]
    if stage == "all" or not paths["qa"].exists():
        qa = pd.concat(qa_frames, ignore_index=True) if qa_frames else pd.DataFrame(
            columns=[
                "level",
                "column",
                "issue",
                "windows_invalidated",
                "entities_affected",
                "first_window_end_utc",
                "last_window_end_utc",
                "detail",
            ]
        )
        row_counts["window_panel_qa_2026.csv"] = _write(paths["qa"], qa)
    elif qa_frames:
        existing = _read_optional(paths["qa"])
        level = "team" if stage == "team" else "player"
        existing = existing[existing.get("level", pd.Series(dtype=str)) != level] if not existing.empty else existing
        combined = pd.concat([existing] + qa_frames, ignore_index=True)
        row_counts["window_panel_qa_2026.csv"] = _write(paths["qa"], combined)

    manifest = {
        "run_id": utc_now_iso().replace(":", "").replace("-", ""),
        "generated_at_utc": utc_now_iso(),
        "season": config.get("season", 2026),
        "config_path": config.get("_config_path"),
        "config_hash": hash_config(config),
        "stage": stage,
        "source_manifest": sources.source_manifest,
        "panel_stats": panel_stats,
        "outputs": row_counts,
    }
    paths["manifest"].write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    return manifest


def build_summary(output_root: Path) -> str:
    paths = output_paths(output_root)
    lines = ["## Snapshot Window Panel", ""]
    if not paths["manifest"].exists():
        lines.append("No manifest found.")
        return "\n".join(lines)

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    lines.extend(
        [
            f"- Generated at: `{manifest.get('generated_at_utc')}`",
            f"- Stage: `{manifest.get('stage')}`",
            "",
            "### Panel Coverage",
            "",
            "| Level | Entities | Windows | Games covered | Latest window |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for level, stats in manifest.get("panel_stats", {}).items():
        lines.append(
            f"| {level} | {stats.get('entities', 0)} | {stats.get('windows', 0)} | "
            f"{stats.get('games_covered', 0):.0f} | {stats.get('last_window_end_utc')} |"
        )
    lines.append("")

    qa = _read_optional(paths["qa"])
    if not qa.empty:
        lines.extend(
            [
                "### Restatements Detected",
                "",
                "| Level | Column | Issue | Windows invalidated |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for _, row in qa.head(20).iterrows():
            lines.append(
                f"| {row['level']} | {row['column']} | {row['issue']} | {row['windows_invalidated']} |"
            )
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the WNBA 2026 PBPStats snapshot window panel.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--stage", choices=sorted(STAGES), default="all")
    parser.add_argument("--pbpstats-data-root", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    config = apply_runtime_overrides(
        config,
        pbpstats_data_root=args.pbpstats_data_root,
        output_root=args.output_root,
    )
    build_outputs(config, args.stage)
    summary = build_summary(resolve_output_root(config))
    print(summary)
    write_github_step_summary(summary)


if __name__ == "__main__":
    main()
