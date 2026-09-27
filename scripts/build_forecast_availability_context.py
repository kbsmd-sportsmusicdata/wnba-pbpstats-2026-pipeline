#!/usr/bin/env python3
"""Build the forecast × availability context table.

A companion to the standings / playoff forecast: it joins the forecast's own output (playoff odds,
projected seed) to the current injury report on the shared ESPN ``team_id`` and flags which
contenders are depleted heading into the stretch. It reads the forecast's committed *output* rather
than any simulation internals, so it never touches the Monte Carlo, the broadcast-insight contract,
or the forecast's renderers.

Output: ``analysis/injuries/data/processed/forecast_availability_context_2026.csv`` + a manifest.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

from injuries.data_sources import (
    hash_config,
    load_config,
    path_from_config,
    stable_json_dumps,
    utc_now_iso,
    write_github_step_summary,
)
from injuries.forecast_context import build_forecast_availability_context
from injuries.report import attach_player_ids, build_current_report


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def _player_mpg(player_game: pd.DataFrame) -> pd.DataFrame:
    """Per-player minutes-per-game from the game layer, for minutes-weighting vacated rotation load."""
    if player_game is None or player_game.empty:
        return pd.DataFrame(columns=["player_id", "mpg"])
    frame = player_game.copy()
    frame["player_id"] = pd.to_numeric(frame.get("player_id"), errors="coerce")
    frame["minutes"] = pd.to_numeric(frame.get("minutes"), errors="coerce")
    frame = frame.dropna(subset=["player_id"])
    grouped = frame.groupby("player_id")["minutes"]
    total = grouped.sum()
    games = grouped.apply(lambda s: int(s.notna().sum()))
    mpg = np.where(games.values > 0, total.values / games.values, np.nan)
    return pd.DataFrame({"player_id": total.index.astype("Int64"), "mpg": mpg})


def build_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    output_root = path_from_config(config.get("output_root", "analysis/injuries"))
    processed = output_root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    context_path = processed / "forecast_availability_context_2026.csv"
    manifest_path = processed / "forecast_availability_context_manifest_2026.json"

    forecast = _read(path_from_config(config.get("forecast_summary_path", "")))
    injuries = _read(path_from_config(config.get("injuries_path", "data/raw/injuries/injuries_2026.parquet")))
    crosswalk = _read(
        path_from_config(
            config.get("crosswalk_path", "analysis/role_fulfillment_matrix/config/player_eligibility_2026.csv")
        )
    )
    player_game = _read(path_from_config(config.get("player_game_path", "")))

    stats: Dict[str, Any] = {}
    if forecast.empty:
        stats["status"] = "forecast_summary_missing"
        context = pd.DataFrame()
    elif injuries.empty:
        stats["status"] = "injuries_missing"
        context = pd.DataFrame()
    else:
        injury_current = attach_player_ids(build_current_report(injuries), crosswalk)
        context = build_forecast_availability_context(forecast, injury_current, _player_mpg(player_game))
        context.to_csv(context_path, index=False)
        flag_counts = context["availability_flag"].value_counts().to_dict()
        stats.update(
            {
                "status": "ok",
                "teams": int(len(context)),
                "depleted_contenders": int((context["availability_flag"] == "Depleted contender").sum()),
                "flag_counts": flag_counts,
                "output_rows": int(len(context)),
            }
        )

    manifest = {
        "generated_at_utc": utc_now_iso(),
        "season": config.get("season", 2026),
        "config_path": config.get("_config_path"),
        "config_hash": hash_config(config),
        "analysis_stats": stats,
        "output_path": str(context_path) if stats.get("status") == "ok" else None,
    }
    manifest_path.write_text(stable_json_dumps(manifest) + "\n", encoding="utf-8")
    return manifest


def build_summary(config: Dict[str, Any]) -> str:
    output_root = path_from_config(config.get("output_root", "analysis/injuries"))
    context_path = output_root / "data" / "processed" / "forecast_availability_context_2026.csv"
    lines = ["## Forecast × Availability Context", ""]
    if not context_path.exists():
        lines.append("No context table produced (forecast or injury feed missing).")
        return "\n".join(lines)

    context = pd.read_csv(context_path)
    depleted = context[context["availability_flag"].isin(("Depleted contender", "Key player lost for season"))]
    lines.append(
        f"- Teams: `{len(context)}`; contenders flagged depleted: "
        f"`{int((context['availability_flag'] == 'Depleted contender').sum())}`"
    )
    lines.append("")
    lines.extend(
        [
            "| Seed (proj) | Team | Playoff % | Out | OFS | Rotation MPG out | Flag | Key losses |",
            "| ---: | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for _, row in context.iterrows():
        playoff = pd.to_numeric(pd.Series([row.get("playoff_probability")]), errors="coerce").iloc[0]
        playoff_text = f"{100 * playoff:.0f}%" if pd.notna(playoff) else "—"
        seed = pd.to_numeric(pd.Series([row.get("expected_final_rank")]), errors="coerce").iloc[0]
        seed_text = f"{seed:.1f}" if pd.notna(seed) else "—"
        raw_names = row.get("out_for_season_names")
        names = "—" if pd.isna(raw_names) else (str(raw_names).strip() or "—")
        lines.append(
            f"| {seed_text} | {row.get('team_abbreviation')} | {playoff_text} | "
            f"{int(row.get('players_out', 0))} | {int(row.get('players_out_for_season', 0))} | "
            f"{row.get('rotation_minutes_out', 0):.0f} | {row.get('availability_flag')} | {names} |"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the forecast × availability context table.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--forecast-summary-path", default=None)
    parser.add_argument("--injuries-path", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    if args.forecast_summary_path:
        config["forecast_summary_path"] = args.forecast_summary_path
    if args.injuries_path:
        config["injuries_path"] = args.injuries_path
    if args.output_root:
        config["output_root"] = args.output_root
    build_outputs(config)
    summary = build_summary(config)
    print(summary)
    write_github_step_summary(summary)


if __name__ == "__main__":
    main()
