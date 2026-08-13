#!/usr/bin/env python3
"""Build WNBA 2026 playoff odds and playoff-readiness metrics.

Two questions, one build. Who gets in and where they seed comes from a Monte Carlo over
the unplayed schedule; whether what a team does well will survive a playoff series comes
from a metric set split into a contender lens and a bubble lens.

The rating model behind the simulation is backtested on held-out games every run, and the
result is written into the manifest. If it ever stops beating the record-only baseline,
that will be visible in the output rather than assumed away.

Inputs age at different rates. The schedule and game results are the freshest thing in the
repo; the possession feed that supplies the half-court split lags it by a fortnight. Both
coverage dates are published rather than blended into a single claim about currency.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from playoff_readiness.data_sources import (
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
from playoff_readiness.ratings import backtest, cross_validate_alpha, fit_ratings
from playoff_readiness.readiness import build_readiness, possession_coverage
from playoff_readiness.schedule import (
    conference_map,
    current_standings,
    long_results,
    reconcile_schedule,
)
from playoff_readiness.simulate import (
    game_leverage,
    magic_numbers,
    seed_distribution,
    simulate_remaining,
    summarize,
)


class ScheduleReconciliationError(RuntimeError):
    """Raised when the schedule does not describe a season every team can play."""


def output_paths(output_root: Path) -> Dict[str, Path]:
    processed = output_root / "data" / "processed"
    return {
        "odds": processed / "playoff_odds_2026.csv",
        "seeds": processed / "playoff_seed_probabilities_2026.csv",
        "readiness": processed / "playoff_readiness_2026.csv",
        "leverage": processed / "remaining_game_leverage_2026.csv",
        "ratings": processed / "team_ratings_2026.csv",
        "manifest": processed / "run_manifest_2026.json",
    }


def _write(path: Path, frame: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return len(frame)


def build_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    output_root = resolve_output_root(config)
    ensure_output_dirs(output_root)
    paths = output_paths(output_root)
    sources = load_sources(config)

    played, remaining, schedule_diagnostics = reconcile_schedule(sources.schedule)
    if not schedule_diagnostics.get("reconciled"):
        # Simulating a season where the games do not add up produces odds that look
        # perfectly reasonable and are wrong, so this is fatal rather than a warning.
        raise ScheduleReconciliationError(
            "schedule does not reconcile to an equal number of games per team: "
            f"{schedule_diagnostics.get('teams_off_expected')}"
        )

    conferences = conference_map(sources.standings)
    results = long_results(played)
    standings = current_standings(results, remaining, conferences=conferences)

    rating_config = config.get("ratings", {})
    half_life = float(rating_config.get("half_life_days", 0))
    margin_cap = float(rating_config.get("margin_cap", 20))
    alpha, alpha_table = cross_validate_alpha(
        played,
        alpha_grid=rating_config.get("alpha_grid", [0.5, 1, 2, 4, 8, 16, 32, 64]),
        half_life_days=half_life,
        margin_cap=margin_cap,
        folds=int(rating_config.get("cv_folds", 5)),
        seed=int(rating_config.get("random_seed", 20260813)),
    )
    fit = fit_ratings(played, alpha=alpha, half_life_days=half_life, margin_cap=margin_cap)
    validation = backtest(
        played,
        alpha=alpha,
        half_life_days=half_life,
        margin_cap=margin_cap,
        train_fraction=float(rating_config.get("backtest_train_fraction", 0.7)),
    )

    simulation_config = config.get("simulation", {})
    playoff_config = config.get("playoffs", {})
    simulation = simulate_remaining(
        results,
        remaining,
        fit,
        simulations=int(simulation_config.get("simulations", 20000)),
        seed=int(simulation_config.get("random_seed", 20260813)),
        conferences=conferences,
        series_formats=playoff_config.get("series_formats"),
    )

    odds = summarize(simulation, standings)
    odds = odds.merge(magic_numbers(standings), on="team_abbreviation", how="left")
    odds["coverage_through"] = schedule_diagnostics.get("played_through")
    seeds = seed_distribution(simulation)
    leverage = game_leverage(simulation)

    readiness_config = config.get("readiness", {})
    readiness = build_readiness(
        odds,
        standings,
        results,
        remaining,
        leverage,
        ratings=fit.rating_series(),
        home_advantage=fit.home_advantage,
        possessions=sources.possessions,
        game_logs=sources.game_logs,
        player_box=sources.player_box,
        bench=sources.bench,
        clutch=sources.clutch,
        identity=sources.identity,
        playoff_field_threshold=float(readiness_config.get("playoff_field_threshold", 0.5)),
        top_seed_threshold=float(readiness_config.get("top_seed_threshold", 0.25)),
        contention_floor=float(readiness_config.get("contention_floor", 0.005)),
        recent_games=int(readiness_config.get("recent_games", 10)),
    )
    possession_through = possession_coverage(sources.possessions, sources.game_logs)
    readiness["results_coverage_through"] = schedule_diagnostics.get("played_through")
    readiness["possession_coverage_through"] = possession_through

    ratings_table = pd.DataFrame(
        {
            "team_abbreviation": fit.teams,
            "team_rating": fit.ratings.round(3),
            "conference": [conferences.get(team) for team in fit.teams],
        }
    ).sort_values("team_rating", ascending=False)
    ratings_table["rating_rank"] = range(1, len(ratings_table) + 1)
    ratings_table["home_advantage"] = round(fit.home_advantage, 3)
    ratings_table["residual_sd"] = round(fit.residual_sd, 3)
    ratings_table["coverage_through"] = schedule_diagnostics.get("played_through")

    row_counts = {
        "playoff_odds_2026.csv": _write(paths["odds"], odds),
        "playoff_seed_probabilities_2026.csv": _write(paths["seeds"], seeds),
        "playoff_readiness_2026.csv": _write(paths["readiness"], readiness),
        "remaining_game_leverage_2026.csv": _write(paths["leverage"], leverage),
        "team_ratings_2026.csv": _write(paths["ratings"], ratings_table),
    }

    stats = {
        "status": "ok",
        "schedule": schedule_diagnostics,
        "rating_model": {
            "alpha": fit.alpha,
            "alpha_grid_search": alpha_table.to_dict("records"),
            "half_life_days": half_life,
            "margin_cap": margin_cap,
            "home_advantage_points": round(fit.home_advantage, 3),
            "residual_sd_points": round(fit.residual_sd, 3),
            "games_fitted": fit.games,
        },
        "model_validation": validation,
        "simulation": {
            "simulations": simulation.simulations,
            "random_seed": int(simulation_config.get("random_seed", 20260813)),
            "series_formats": playoff_config.get("series_formats"),
            # Both are identities the simulation must satisfy: eight teams make the
            # playoffs and exactly one wins the title, every run.
            "playoff_probability_sum": round(float(odds["p_playoffs"].sum()), 4),
            "title_probability_sum": round(float(odds["p_title"].sum()), 4),
        },
        "coverage": {
            "results_through": schedule_diagnostics.get("played_through"),
            "possessions_through": possession_through,
            "season_ends": schedule_diagnostics.get("season_ends"),
        },
        "readiness": {
            "lens_counts": readiness["readiness_lens"].value_counts().to_dict() if not readiness.empty else {},
            "status_counts": odds["status"].value_counts().to_dict(),
            "clinched": odds.loc[odds["clinched_playoffs"], "team_abbreviation"].tolist(),
            "eliminated": odds.loc[odds["eliminated"], "team_abbreviation"].tolist(),
        },
    }

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
    lines = ["## Playoff Readiness", ""]
    if not paths["manifest"].exists():
        lines.append("No manifest found.")
        return "\n".join(lines)

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    stats = manifest.get("analysis_stats", {})
    model = stats.get("rating_model", {})
    validation = stats.get("model_validation", {})
    coverage = stats.get("coverage", {})
    schedule = stats.get("schedule", {})
    lines.extend(
        [
            f"- Generated at: `{manifest.get('generated_at_utc')}`",
            f"- Games played / remaining: `{schedule.get('games_played')}` / `{schedule.get('games_remaining')}`",
            f"- Results through `{coverage.get('results_through')}`, possessions through `{coverage.get('possessions_through')}`",
            f"- Rating model: alpha `{model.get('alpha')}`, home advantage `{model.get('home_advantage_points')}` pts, "
            f"residual SD `{model.get('residual_sd_points')}` pts",
            f"- Held-out log loss `{validation.get('model_log_loss')}` vs record baseline "
            f"`{validation.get('record_baseline_log_loss')}`",
            "",
        ]
    )

    if paths["odds"].exists():
        odds = pd.read_csv(paths["odds"])
        lines.extend(
            [
                "### Odds",
                "",
                "| Team | Record | Proj W | P(playoffs) | P(top 4) | P(title) | Status |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for _, row in odds.iterrows():
            lines.append(
                f"| {row['team_abbreviation']} | {row['wins']:.0f}-{row['losses']:.0f} | "
                f"{row['projected_wins']:.1f} | {row['p_playoffs']:.3f} | {row['p_top_four']:.3f} | "
                f"{row['p_title']:.3f} | {row['status']} |"
            )
        lines.append("")

    if paths["readiness"].exists():
        readiness = pd.read_csv(paths["readiness"])
        for lens in ("Top seed", "Bubble", "Out of contention"):
            subset = readiness[readiness["readiness_lens"] == lens]
            if subset.empty:
                continue
            lines.extend([f"### {lens} lens", "", "| Team | Index | Half-court net | Quality gap | Note |", "| --- | ---: | ---: | ---: | --- |"])
            for _, row in subset.iterrows():
                lines.append(
                    f"| {row['team_abbreviation']} | {row.get('readiness_index')} | "
                    f"{row.get('set_net_rating')} | {row.get('quality_gap')} | {row.get('readiness_notes')} |"
                )
            lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WNBA 2026 playoff odds and readiness metrics.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--sportsdataverse-data-root", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--simulations", type=int, default=None, help="Override the configured simulation count.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(args.config))
    config = apply_runtime_overrides(
        config,
        sportsdataverse_data_root=args.sportsdataverse_data_root,
        output_root=args.output_root,
        simulations=args.simulations,
    )
    build_outputs(config)
    summary = build_summary(resolve_output_root(config))
    print(summary)
    write_github_step_summary(summary)


if __name__ == "__main__":
    main()
