"""Integration coverage for the repo-native standings forecast orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_standings_playoff_forecast as builder
from standings_playoff_forecast.contracts import ForecastModelConfig, SeasonConfig
from standings_playoff_forecast.historical_context import HISTORICAL_CONTEXT_COLUMNS
from standings_playoff_forecast.outputs import CSV_FILENAMES, PAYLOAD_KEYS


def season_config(root: Path) -> SeasonConfig:
    return SeasonConfig(
        season=2026,
        league="WNBA",
        season_type="Regular Season",
        simulation_count=100_000,
        recent_window_games=10,
        historical_context_enabled=True,
        historical_context_min_prior_seasons=1,
        team_count=2,
        regular_season_games_per_team=2,
        playoff_qualifiers=1,
        seeding_scope="league",
        tiebreaks=("head_to_head_win_pct",),
        multi_team_restart_after_elimination=True,
        sportsdataverse_data_root=str(root / "sdv"),
        pbpstats_data_root=str(root / "pbp"),
        source_files=MappingProxyType(
            {
                "schedule": "schedule.parquet",
                "team_box": "team_box.parquet",
                "standings": "standings.parquet",
                "pbp_team_features": "features.csv",
            }
        ),
        output_root=str(root / "output"),
        normalized_team_game_root=str(root / "normalized"),
    )


def model_config() -> ForecastModelConfig:
    return ForecastModelConfig(
        model_version="test-model",
        season_net_rating_weight=0.7,
        recent_net_rating_weight=0.3,
        home_court_points=1.5,
        rest_day_points=0.35,
        max_rest_day_adjustment=2,
        back_to_back_penalty_points=0.75,
        minimum_sigma=8.0,
        maximum_sigma=18.0,
        explanatory_strength=MappingProxyType({"season_net_rating": 1.0}),
        pbpstats_enrichment_enabled=True,
        pbpstats_enrichment_required=False,
    )


def options(**overrides: object) -> argparse.Namespace:
    values = {
        "season": 2026,
        "cutoff": None,
        "simulations": 25,
        "conditional_simulations": 0,
        "random_seed": None,
        "history_start": None,
        "skip_history": False,
        "render": "none",
        "sportsdataverse_data_root": None,
        "pbpstats_data_root": None,
        "output_root": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def literal_sources(root: Path) -> SimpleNamespace:
    schedule = pd.DataFrame(
        {
            "season": [2026, 2026],
            "season_type": [2, 2],
            "type_abbreviation": ["STD", "STD"],
            "game_id": ["g1", "g2"],
            "game_date": pd.to_datetime(["2026-06-01", "2026-06-08"]),
            "home_id": ["A", "B"],
            "away_id": ["B", "A"],
            "home_abbreviation": ["AAA", "BBB"],
            "away_abbreviation": ["BBB", "AAA"],
            "home_display_name": ["Alpha", "Beta"],
            "away_display_name": ["Beta", "Alpha"],
            "home_score": [80.0, pd.NA],
            "away_score": [70.0, pd.NA],
            "status_type_completed": [True, False],
            "status_type_name": ["STATUS_FINAL", "STATUS_SCHEDULED"],
            "format_regulation_periods": [4, 4],
            "status_period": [4, 0],
        }
    )
    team_box = pd.DataFrame(
        {
            "game_id": ["g1", "g1"],
            "team_id": ["A", "B"],
            "field_goals_made": [30, 27],
            "field_goals_attempted": [70, 68],
            "three_point_field_goals_made": [8, 7],
            "free_throws_made": [12, 9],
            "free_throws_attempted": [14, 11],
            "offensive_rebounds": [10, 8],
            "defensive_rebounds": [25, 24],
            "turnovers": [12, 13],
        }
    )
    standings = pd.DataFrame(
        {
            "team_id": ["A", "A", "B", "B"],
            "stat_name": ["wins", "losses", "wins", "losses"],
            "value": [1, 0, 0, 1],
        }
    )
    team_history = pd.DataFrame(
        {
            "season": [2026, 2026],
            "sportsdataverse_team_id": ["A", "B"],
            "franchise_id": ["alpha", "beta"],
        }
    )
    source_root = root / "sources"
    source_root.mkdir(parents=True)
    schedule_path = source_root / "schedule.parquet"
    team_box_path = source_root / "team_box.parquet"
    standings_path = source_root / "standings.parquet"
    team_history_path = source_root / "team_history.csv"
    schedule.to_parquet(schedule_path, index=False)
    team_box.to_parquet(team_box_path, index=False)
    standings.to_parquet(standings_path, index=False)
    team_history.to_csv(team_history_path, index=False)
    return SimpleNamespace(
        schedule=schedule,
        team_box=team_box,
        standings=standings,
        team_history=team_history,
        pbp_team_features=None,
        schedule_path=schedule_path,
        team_box_path=team_box_path,
        standings_path=standings_path,
        team_history_path=team_history_path,
        pbp_team_features_path=None,
    )


class OrchestratorIntegrationTests(unittest.TestCase):
    def test_literal_two_team_pipeline_runs_real_stages_from_alternate_cwd(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository_root = root / "repository"
            alternate_cwd = root / "elsewhere"
            config_root = repository_root / "analysis" / "standings_playoff_forecast" / "config"
            (config_root / "seasons").mkdir(parents=True)
            alternate_cwd.mkdir()
            (config_root / "seasons" / "default.json").write_text(
                '{"fixture": "default"}\n', encoding="utf-8"
            )
            (config_root / "seasons" / "2026.json").write_text(
                '{"fixture": "season"}\n', encoding="utf-8"
            )
            (config_root / "forecast_model.json").write_text(
                '{"fixture": "model"}\n', encoding="utf-8"
            )
            cfg = season_config(repository_root)
            cfg = SeasonConfig(
                **{
                    **cfg.__dict__,
                    "output_root": "analysis/literal_forecast",
                    "normalized_team_game_root": str(repository_root / "normalized"),
                }
            )
            sources = literal_sources(root)
            original_cwd = Path.cwd()
            try:
                os.chdir(alternate_cwd)
                with (
                    patch.object(builder, "REPOSITORY_ROOT", repository_root),
                    patch.object(builder, "CONFIG_ROOT", config_root),
                    patch.object(builder, "load_season_config", return_value=cfg),
                    patch.object(builder, "load_model_config", return_value=model_config()),
                    patch.object(builder, "load_forecast_sources", return_value=sources),
                ):
                    with warnings.catch_warnings(record=True):
                        result = builder.run_forecast(
                            options(simulations=20, skip_history=True)
                        )
            finally:
                os.chdir(original_cwd)

            expected = (
                repository_root
                / "analysis"
                / "literal_forecast"
                / "data"
                / "processed"
                / "season=2026"
                / "latest"
            )
            self.assertEqual(result.output_path, expected)
            self.assertTrue(expected.is_dir())
            self.assertEqual(
                sorted(path.name for path in expected.iterdir()),
                sorted([*CSV_FILENAMES.values(), "forecast_payload.json", "run_manifest.json"]),
            )
            payload = json.loads((expected / "forecast_payload.json").read_text())
            manifest = json.loads((expected / "run_manifest.json").read_text())
            self.assertEqual(set(payload), PAYLOAD_KEYS)
            self.assertEqual(payload["metadata"], manifest)
            self.assertEqual(manifest["simulation_count"], 20)
            self.assertEqual(manifest["conditional_simulation_count"], 0)
            self.assertEqual(
                {entry["name"] for entry in manifest["source_files"]},
                {
                    "schedule",
                    "season_config_default",
                    "standings",
                    "team_box",
                    "team_history",
                },
            )
            forecast = pd.read_csv(expected / "forecast_summary.csv")
            ranks = pd.read_csv(expected / "rank_probability_matrix.csv")
            self.assertEqual(len(forecast), 2)
            self.assertAlmostEqual(forecast["playoff_probability"].sum(), 1.0)
            self.assertTrue(
                ranks.groupby("team_id")["probability"].sum().sub(1.0).abs().lt(1e-12).all()
            )
            self.assertTrue(
                ranks.groupby("final_rank")["probability"].sum().sub(1.0).abs().lt(1e-12).all()
            )

    def test_parse_args_supports_runtime_overrides_and_rejects_invalid_numbers(self):
        args = builder.parse_args(
            [
                "--season",
                "2026",
                "--cutoff",
                "2026-08-08",
                "--simulations",
                "500",
                "--conditional-simulations",
                "0",
                "--random-seed",
                "17",
                "--history-start",
                "2022",
                "--skip-history",
                "--render",
                "none",
                "--sportsdataverse-data-root",
                "/tmp/sdv",
                "--pbpstats-data-root",
                "/tmp/pbp",
                "--output-root",
                "/tmp/output",
            ]
        )
        self.assertEqual(args.cutoff, "2026-08-08")
        self.assertEqual(args.simulations, 500)
        self.assertEqual(args.random_seed, 17)
        self.assertTrue(args.skip_history)
        self.assertEqual(args.output_root, "/tmp/output")
        for invalid in (
            ["--season", "2026", "--simulations", "0"],
            ["--season", "2026", "--random-seed", "-1"],
            ["--season", "2026", "--conditional-simulations", "-1"],
            ["--season", "2026", "--history-start", "0"],
            ["--season", "2026", "--cutoff", "08/08/2026"],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                builder.parse_args(invalid)

    def test_pipeline_resolves_cutoff_seed_ranks_and_writes_exact_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg = season_config(root)
            source_paths = {}
            for name in ("schedule", "team_box", "standings", "team_history"):
                path = root / f"{name}.source"
                path.write_text(name, encoding="utf-8")
                source_paths[name] = path
            schedule = pd.DataFrame(
                {
                    "game_id": ["old", "latest", "future"],
                    "game_date": pd.to_datetime(
                        ["2026-08-01", "2026-08-08", "2026-08-09"]
                    ),
                    "status_type_completed": [True, True, False],
                }
            )
            sources = SimpleNamespace(
                schedule=schedule,
                team_box=pd.DataFrame(),
                standings=pd.DataFrame(),
                team_history=pd.DataFrame(),
                pbp_team_features=None,
                schedule_path=source_paths["schedule"],
                team_box_path=source_paths["team_box"],
                standings_path=source_paths["standings"],
                team_history_path=source_paths["team_history"],
                pbp_team_features_path=None,
            )
            team_games = pd.DataFrame(
                {
                    "team_id": ["A", "B"],
                    "game_id": ["g", "g"],
                    "season_progress_pct": [0.5, 0.5],
                }
            )
            unranked = pd.DataFrame(
                {
                    "team_id": ["A", "B"],
                    "games_played": [1, 1],
                    "wins": [1, 0],
                    "losses": [0, 1],
                    "point_differential": [5, -5],
                }
            )
            ranked = SimpleNamespace(ordered_team_ids=("B", "A"))
            strength = pd.DataFrame(
                {
                    "team_id": ["A", "B"],
                    "pbpstats_snapshot_available": [False, False],
                    "pbpstats_snapshot_safe_for_cutoff": [False, False],
                }
            )
            remaining = pd.DataFrame({"game_id": ["future"]})
            scored = pd.DataFrame({"game_id": ["future"]})
            simulation = SimpleNamespace(forecast_summary=pd.DataFrame())
            leverage = pd.DataFrame({"game_id": ["future"]})
            insights = pd.DataFrame({"priority": range(1, 11)})
            history = pd.DataFrame(columns=HISTORICAL_CONTEXT_COLUMNS)
            stage_order: list[str] = []

            def stage(name: str, value: object) -> Mock:
                return Mock(side_effect=lambda *args, **kwargs: (stage_order.append(name), value)[1])

            output_root = root / "output" / "data" / "processed" / "season=2026" / "latest"

            def write_bundle(bundle, **kwargs):
                stage_order.append("outputs")
                output_root.mkdir(parents=True)
                for filename in (*CSV_FILENAMES.values(), "forecast_payload.json", "run_manifest.json"):
                    (output_root / filename).write_text("fixture\n", encoding="utf-8")
                self.assertEqual(bundle.current_standings["current_rank"].tolist(), [2, 1])
                self.assertEqual(kwargs["conditional_simulation_count"], 0)
                self.assertEqual(
                    set(kwargs["source_files"]),
                    {*source_paths, "season_config_default"},
                )
                return output_root

            with (
                patch.object(builder, "load_season_config", return_value=cfg),
                patch.object(builder, "load_model_config", return_value=model_config()),
                patch.object(builder, "load_forecast_sources", side_effect=stage("sources", sources)),
                patch.object(builder, "qualify_regular_season_schedule", return_value=schedule),
                patch.object(builder, "build_team_game_layer", side_effect=stage("team_game", team_games)),
                patch.object(builder, "build_current_standings", side_effect=stage("standings", unranked)),
                patch.object(builder, "build_head_to_head", return_value=pd.DataFrame()),
                patch.object(builder, "rank_teams", return_value=ranked) as rank_mock,
                patch.object(builder, "reconcile_standings", side_effect=stage("reconciliation", "source_snapshot_reconciled")),
                patch.object(builder, "build_team_strength", side_effect=stage("strength", strength)),
                patch.object(builder, "build_remaining_schedule", side_effect=stage("remaining", remaining)),
                patch.object(builder, "score_matchups", side_effect=stage("matchups", scored)),
                patch.object(builder, "simulate_season", side_effect=stage("simulation", simulation)) as simulate_mock,
                patch.object(builder, "build_historical_context", side_effect=stage("history", history)),
                patch.object(builder, "calculate_game_leverage", side_effect=stage("leverage", leverage)),
                patch.object(builder, "build_broadcast_insights", side_effect=stage("insights", insights)),
                patch.object(builder, "write_output_bundle", side_effect=write_bundle),
            ):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    result = builder.run_forecast(options())

            self.assertEqual(result.cutoff, pd.Timestamp("2026-08-08"))
            self.assertEqual(result.random_seed, 20260808)
            self.assertEqual(result.output_path, output_root)
            self.assertEqual(
                stage_order,
                [
                    "sources",
                    "team_game",
                    "standings",
                    "reconciliation",
                    "strength",
                    "remaining",
                    "matchups",
                    "simulation",
                    "history",
                    "leverage",
                    "insights",
                    "outputs",
                ],
            )
            rank_mock.assert_called_once()
            simulate_mock.assert_called_once_with(
                team_games, scored, cfg, simulation_count=25, seed=20260808
            )
            self.assertEqual(
                sorted(path.name for path in output_root.iterdir()),
                sorted([*CSV_FILENAMES.values(), "forecast_payload.json", "run_manifest.json"]),
            )
            self.assertTrue(any("PBPStats" in str(item.message) for item in caught))

    def test_overrides_use_frozen_config_skip_history_and_warn(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg = season_config(root)
            overridden = builder.apply_runtime_overrides(
                cfg,
                sportsdataverse_data_root="/runtime/sdv",
                pbpstats_data_root="/runtime/pbp",
                output_root="/runtime/output",
            )
            self.assertEqual(overridden.sportsdataverse_data_root, "/runtime/sdv")
            self.assertEqual(overridden.pbpstats_data_root, "/runtime/pbp")
            self.assertEqual(overridden.output_root, "/runtime/output")
            self.assertEqual(cfg.sportsdataverse_data_root, str(root / "sdv"))

        with patch.object(builder, "_run_pipeline") as pipeline:
            pipeline.return_value = SimpleNamespace()
            builder.run_forecast(options(skip_history=True))
            history = pipeline.call_args.kwargs["historical_context_override"]
            self.assertEqual(list(history.columns), HISTORICAL_CONTEXT_COLUMNS)
            self.assertTrue(history.empty)

    def test_history_start_excludes_earlier_seasons_from_aggregates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for season in (2022, 2023):
                (root / f"season={season}").mkdir()
            discovered = builder.discover_history(
                root, 2026, history_start=2023
            )
            self.assertEqual([path.name for path in discovered], ["season=2023"])

    def test_historical_provenance_includes_read_partition_and_season_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root = root / "config"
            (config_root / "seasons").mkdir(parents=True)
            default_path = config_root / "seasons" / "default.json"
            season_path = config_root / "seasons" / "2025.json"
            default_path.write_text("{}\n", encoding="utf-8")
            season_path.write_text("{}\n", encoding="utf-8")
            history_path = root / "season=2025" / "team_game.parquet"
            history_path.parent.mkdir()
            history_path.write_bytes(b"historical-fixture")
            context = pd.DataFrame(
                [
                    {
                        **{column: pd.NA for column in HISTORICAL_CONTEXT_COLUMNS},
                        "context_level": "season",
                        "metric": "fixture",
                        "season": 2025,
                        "season_count": 1,
                        "availability_status": "available",
                    }
                ]
            )
            context.attrs["historical_team_game_paths"] = [history_path]
            sources = SimpleNamespace(
                schedule_path=root / "schedule",
                team_box_path=root / "team_box",
                standings_path=root / "standings",
                team_history_path=root / "team_history",
                pbp_team_features_path=None,
            )
            for path in (
                sources.schedule_path,
                sources.team_box_path,
                sources.standings_path,
                sources.team_history_path,
            ):
                path.write_text("fixture", encoding="utf-8")
            with patch.object(builder, "CONFIG_ROOT", config_root):
                provenance = builder._source_files(sources, context)

            self.assertEqual(provenance["season_config_default"], default_path)
            self.assertEqual(provenance["historical_season_config_2025"], season_path)
            self.assertEqual(provenance["historical_team_game_2025"], history_path)

    def test_mixed_history_warns_once_and_preserves_context(self):
        available = {column: pd.NA for column in HISTORICAL_CONTEXT_COLUMNS}
        available.update(
            context_level="season",
            metric="fixture",
            season=2024,
            season_count=1,
            availability_status="available",
        )
        unavailable = {column: pd.NA for column in HISTORICAL_CONTEXT_COLUMNS}
        unavailable.update(
            context_level="availability",
            metric="historical_season_status",
            season=2025,
            season_count=0,
            availability_status="incomplete_season_outcomes",
        )
        context = pd.DataFrame([available, unavailable])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            builder._warn_for_history(context)

        history_warnings = [
            str(item.message) for item in caught if "Historical context" in str(item.message)
        ]
        self.assertEqual(len(history_warnings), 1)
        self.assertIn("partially unavailable", history_warnings[0])
        self.assertEqual(context["availability_status"].tolist(), ["available", "incomplete_season_outcomes"])

    def test_unsupported_conditional_run_and_stage_failures_propagate(self):
        with self.assertRaisesRegex(ValueError, "conditional simulations"):
            builder.run_forecast(options(conditional_simulations=5))
        with (
            patch.object(builder, "load_season_config", return_value=season_config(Path("/tmp"))),
            patch.object(builder, "load_model_config", return_value=model_config()),
            patch.object(builder, "load_forecast_sources", side_effect=FileNotFoundError("missing schedule")),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "missing schedule"):
                builder.run_forecast(options())

    def test_render_all_runs_all_four_renderers(self):
        cfg = season_config(Path("/tmp"))
        result = SimpleNamespace(
            output_path=Path("/tmp/output/data/processed/season=2026/latest"),
            stage_artifacts={"team_games": pd.DataFrame({"team_id": ["A"]})},
        )
        with (
            patch.object(builder, "load_season_config", return_value=cfg),
            patch.object(builder, "load_model_config", return_value=model_config()),
            patch.object(builder, "_run_pipeline", return_value=result),
            patch.object(builder, "render_excel", return_value=Path("/tmp/forecast.xlsx")) as excel,
            patch.object(builder, "render_markdown", return_value=Path("/tmp/brief.md")) as markdown,
            patch.object(builder, "render_stat_pack", return_value=Path("/tmp/stat-pack.html")) as stat_pack,
            patch.object(builder, "render_dashboard", return_value=Path("/tmp/dashboard/index.html")) as dashboard,
        ):
            self.assertIs(builder.run_forecast(options(render="all")), result)

        excel.assert_called_once_with(
            result.output_path,
            result.stage_artifacts["team_games"],
            cfg=cfg,
        )
        markdown.assert_called_once_with(result.output_path, cfg=cfg)
        stat_pack.assert_called_once_with(result.output_path, cfg=cfg)
        dashboard.assert_called_once_with(result.output_path, cfg=cfg)

    def test_render_none_never_invokes_any_renderer(self):
        cfg = season_config(Path("/tmp"))
        result = SimpleNamespace()
        with (
            patch.object(builder, "load_season_config", return_value=cfg),
            patch.object(builder, "load_model_config", return_value=model_config()),
            patch.object(builder, "_run_pipeline", return_value=result),
            patch.object(builder, "render_excel") as excel,
            patch.object(builder, "render_markdown") as markdown,
            patch.object(builder, "render_stat_pack") as stat_pack,
            patch.object(builder, "render_dashboard") as dashboard,
        ):
            self.assertIs(builder.run_forecast(options(render="none")), result)
        excel.assert_not_called()
        markdown.assert_not_called()
        stat_pack.assert_not_called()
        dashboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
