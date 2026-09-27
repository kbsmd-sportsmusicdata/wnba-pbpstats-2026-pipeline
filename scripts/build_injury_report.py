#!/usr/bin/env python3
"""Build the WNBA 2026 injury / availability report.

Turns the raw ESPN injury feed into three analysis-ready tables:

* ``injury_report_current_2026.csv`` -- one row per player for the most recent snapshot, with a
  normalized availability status and the resolved pbpstats ``player_id``;
* ``team_availability_2026.csv`` -- the current team-level rollup of who is unavailable and why;
* ``injury_report_history_2026.csv`` -- every snapshot in the feed, normalized, for trend work.

The tables are the shared availability layer the hidden-value board, functional depth and the
playoff forecast read. Nothing here is a hard dependency: with the feed missing the run writes an
empty-status manifest instead of failing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from injuries.data_sources import (
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
from injuries.report import (
    attach_player_ids,
    build_current_report,
    build_team_availability,
    latest_as_of,
    normalize_injuries,
)


def output_paths(output_root: Path) -> Dict[str, Path]:
    processed = output_root / "data" / "processed"
    return {
        "current": processed / "injury_report_current_2026.csv",
        "team": processed / "team_availability_2026.csv",
        "history": processed / "injury_report_history_2026.csv",
        "manifest": processed / "run_manifest_2026.json",
    }


def _write(path: Path, df: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def build_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    output_root = resolve_output_root(config)
    ensure_output_dirs(output_root)
    paths = output_paths(output_root)
    sources = load_sources(config)

    stats: Dict[str, Any] = {}
    row_counts: Dict[str, int] = {}

    if sources.injuries.empty:
        stats["status"] = "injuries_missing"
    else:
        history = normalize_injuries(sources.injuries)
        current = build_current_report(sources.injuries, as_of=config.get("as_of"))
        current = attach_player_ids(current, sources.crosswalk)
        team = build_team_availability(current)

        row_counts = {
            "injury_report_current_2026.csv": _write(paths["current"], current),
            "team_availability_2026.csv": _write(paths["team"], team),
            "injury_report_history_2026.csv": _write(paths["history"], history),
        }
        matched = int((current["player_id_match"] != "unmatched").sum()) if not current.empty else 0
        stats.update(
            {
                "status": "ok",
                "as_of_date": latest_as_of(current),
                "players_current": int(len(current)),
                "player_id_matched": matched,
                "player_id_match_rate": round(matched / len(current), 4) if len(current) else None,
                "players_out": int(current["is_out"].sum()) if not current.empty else 0,
                "players_out_for_season": int(current["is_out_for_season"].sum()) if not current.empty else 0,
                "players_day_to_day": int(current["is_day_to_day"].sum()) if not current.empty else 0,
                "teams_affected": int(team["team_abbreviation"].nunique()) if not team.empty else 0,
                "snapshots": int(history["as_of_date"].nunique()) if not history.empty else 0,
            }
        )

    manifest = {
        "run_id": utc_now_iso().replace(":", "").replace("-", ""),
        "generated_at_utc": utc_now_iso(),
        "season": config.get("season", 2026),
        "config_path": config.get("_config_path"),
        "config_hash": hash_config(config),
        "source_manifest": sources.source_manifest,
        "analysis_stats": stats,
        "outputs": row_counts,
    }
    paths["manifest"].write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    return manifest


def build_summary(output_root: Path) -> str:
    paths = output_paths(output_root)
    lines = ["## Injury / Availability Report", ""]
    if not paths["manifest"].exists():
        lines.append("No manifest found.")
        return "\n".join(lines)

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    stats = manifest.get("analysis_stats", {})
    if stats.get("status") != "ok":
        lines.append(f"- Status: `{stats.get('status')}`")
        return "\n".join(lines)

    lines.extend(
        [
            f"- Generated at: `{manifest.get('generated_at_utc')}`",
            f"- As of: `{stats.get('as_of_date')}`",
            f"- Players listed: `{stats.get('players_current')}` "
            f"(`{stats.get('players_out')}` out, `{stats.get('players_out_for_season')}` out for season, "
            f"`{stats.get('players_day_to_day')}` day-to-day)",
            f"- pbpstats id match rate: `{stats.get('player_id_match_rate')}`",
            "",
        ]
    )
    if paths["team"].exists():
        team = pd.read_csv(paths["team"])
        team = team.sort_values(["players_out_for_season", "players_out"], ascending=False)
        if not team.empty:
            lines.extend(
                [
                    "| Team | Out | Out for season | Day-to-day | Out (names) |",
                    "| --- | ---: | ---: | ---: | --- |",
                ]
            )
            for _, row in team.head(15).iterrows():
                names = str(row.get("players_out_names") or "").strip() or "—"
                lines.append(
                    f"| {row['team_abbreviation']} | {int(row['players_out'])} | "
                    f"{int(row['players_out_for_season'])} | {int(row['players_day_to_day'])} | {names} |"
                )
            lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the WNBA 2026 injury / availability report.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--injuries-path", default=None)
    parser.add_argument("--crosswalk-path", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    config = apply_runtime_overrides(
        config,
        injuries_path=args.injuries_path,
        crosswalk_path=args.crosswalk_path,
        output_root=args.output_root,
    )
    build_outputs(config)
    summary = build_summary(resolve_output_root(config))
    print(summary)
    write_github_step_summary(summary)


if __name__ == "__main__":
    main()
