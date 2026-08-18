import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


EXPECTED_FILES = {
    "current_standings.csv",
    "head_to_head.csv",
    "team_strength.csv",
    "remaining_schedule.csv",
    "matchup_probabilities.csv",
    "forecast_summary.csv",
    "rank_probability_matrix.csv",
    "playoff_leverage_games.csv",
    "historical_context.csv",
    "broadcast_insights.csv",
    "forecast_payload.json",
    "run_manifest.json",
}


def _inputs(root: Path):
    from standings_playoff_forecast.config import (
        load_model_config,
        load_season_config,
    )
    from standings_playoff_forecast.outputs import ForecastOutputBundle
    from standings_playoff_forecast.historical_context import HISTORICAL_CONTEXT_COLUMNS
    from standings_playoff_forecast.leverage import LEVERAGE_COLUMNS
    from standings_playoff_forecast.simulation import SimulationResult

    cfg = replace(
        load_season_config(2026),
        season=2031,
        team_count=2,
        regular_season_games_per_team=2,
        playoff_qualifiers=1,
        simulation_count=4,
        output_root=str(root / "forecast-root"),
    )
    model_cfg = replace(load_model_config(), model_version="literal_model")
    current = pd.DataFrame(
        [
            {
                "team_id": "A",
                "franchise_id": "alpha",
                "team_abbreviation": "ALP",
                "team_name": "Alpha",
                "current_rank": 1,
                "games_played": 1,
                "wins": 1,
                "losses": 0,
                "win_pct": 1.0,
                "points_for": 80,
                "points_against": 70,
                "point_differential": 10,
                "games_back": 0.0,
                "home_wins": 1,
                "home_losses": 0,
                "road_wins": 0,
                "road_losses": 0,
                "home_record": "1-0",
                "road_record": "0-0",
                "last10_wins": 1,
                "last10_losses": 0,
                "last10_record": "1-0",
                "current_streak_type": "W",
                "current_streak_length": 1,
                "current_streak_label": "W1",
                "conference_wins": 1,
                "conference_losses": 0,
                "conference_record": "1-0",
                "record_vs_current_500_plus_wins": 1,
                "record_vs_current_500_plus_losses": 0,
                "record_vs_current_500_plus": "1-0",
                "record_vs_current_500_plus_pct": 1.0,
                "playoff_cutline_flag": True,
            },
            {
                "team_id": "B",
                "franchise_id": "bravo",
                "team_abbreviation": "BRV",
                "team_name": "Bravo",
                "current_rank": 2,
                "games_played": 1,
                "wins": 0,
                "losses": 1,
                "win_pct": 0.0,
                "points_for": 70,
                "points_against": 80,
                "point_differential": -10,
                "games_back": 1.0,
                "home_wins": 0,
                "home_losses": 0,
                "road_wins": 0,
                "road_losses": 1,
                "home_record": "0-0",
                "road_record": "0-1",
                "last10_wins": 0,
                "last10_losses": 1,
                "last10_record": "0-1",
                "current_streak_type": "L",
                "current_streak_length": 1,
                "current_streak_label": "L1",
                "conference_wins": 0,
                "conference_losses": 1,
                "conference_record": "0-1",
                "record_vs_current_500_plus_wins": 0,
                "record_vs_current_500_plus_losses": 1,
                "record_vs_current_500_plus": "0-1",
                "record_vs_current_500_plus_pct": 0.0,
                "playoff_cutline_flag": False,
            },
        ]
    )
    head_to_head = pd.DataFrame(
        [
            {
                "team_id": "A",
                "franchise_id": "alpha",
                "opponent_id": "B",
                "opponent_franchise_id": "bravo",
                "games_played": 1,
                "wins": 1,
                "losses": 0,
                "win_pct": 1.0,
                "points_for": 80,
                "points_against": 70,
                "point_differential": 10,
            },
            {
                "team_id": "B",
                "franchise_id": "bravo",
                "opponent_id": "A",
                "opponent_franchise_id": "alpha",
                "games_played": 1,
                "wins": 0,
                "losses": 1,
                "win_pct": 0.0,
                "points_for": 70,
                "points_against": 80,
                "point_differential": -10,
            },
        ]
    )
    strength = pd.DataFrame(
        [
            {
                "team_id": "A",
                "season_games_played": 1,
                "season_win_pct": 1.0,
                "season_net_rating": 8.0,
                "recent_games_played": 1,
                "recent_net_rating": np.float64(8.0),
                "predictive_net_rating": 6.0,
                "composite_strength": 1.0,
                "efg_diff": 0.05,
                "tov_diff": 0.02,
                "oreb_diff": 0.01,
                "ftr_diff": 0.03,
                "pbpstats_snapshot_available": np.bool_(True),
                "pbpstats_snapshot_as_of": pd.Timestamp("2031-06-01"),
                "pbpstats_cutoff_safety_upper_bound": pd.NaT,
                "pbpstats_provenance_kind": "snapshot_as_of",
                "pbpstats_snapshot_safe_for_cutoff": np.bool_(True),
            },
            {
                "team_id": "B",
                "season_games_played": 1,
                "season_win_pct": 0.0,
                "season_net_rating": -8.0,
                "recent_games_played": 1,
                "recent_net_rating": -8.0,
                "predictive_net_rating": -6.0,
                "composite_strength": -1.0,
                "efg_diff": -0.05,
                "tov_diff": -0.02,
                "oreb_diff": -0.01,
                "ftr_diff": -0.03,
                "pbpstats_snapshot_available": True,
                "pbpstats_snapshot_as_of": pd.Timestamp("2031-06-01"),
                "pbpstats_cutoff_safety_upper_bound": pd.NaT,
                "pbpstats_provenance_kind": "snapshot_as_of",
                "pbpstats_snapshot_safe_for_cutoff": True,
            },
        ]
    )
    remaining = pd.DataFrame(
        [
            {
                "game_id": "g2",
                "game_date": pd.Timestamp("2031-06-03"),
                "home_id": "A",
                "away_id": "B",
                "home_rest_days": 2,
                "away_rest_days": 2,
                "home_b2b": False,
                "away_b2b": False,
            }
        ]
    )
    matchups = remaining.assign(
        home_win_probability=np.float64(0.75),
        away_win_probability=np.float64(0.25),
        expected_home_margin=np.float64(5.5),
        margin_sigma=np.float64(10.0),
        model_version="literal_model",
    )
    summary = pd.DataFrame(
        {
            "team_id": ["A", "B"],
            "season": [2031, 2031],
            "projected_wins_mean": [1.75, 0.25],
            "projected_losses_mean": [0.25, 1.75],
            "wins_p10": [1.0, 0.0],
            "wins_p50": [2.0, 0.0],
            "wins_p90": [2.0, 1.0],
            "expected_final_rank": [1.25, 1.75],
            "playoff_probability": [0.75, 0.25],
            "top4_probability": [0.75, 0.25],
            "home_court_probability": [0.75, 0.25],
            "rank_1_probability": [0.75, 0.25],
            "rank_2_probability": [0.25, 0.75],
            "out_probability": [0.25, 0.75],
        }
    )
    matrix = pd.DataFrame(
        [
            {"season": 2031, "team_id": "A", "final_rank": 1, "probability": 0.75, "playoff_rank": 1},
            {"season": 2031, "team_id": "A", "final_rank": 2, "probability": 0.25, "playoff_rank": pd.NA},
            {"season": 2031, "team_id": "B", "final_rank": 1, "probability": 0.25, "playoff_rank": 1},
            {"season": 2031, "team_id": "B", "final_rank": 2, "probability": 0.75, "playoff_rank": pd.NA},
        ]
    )
    simulation = SimulationResult(
        forecast_summary=summary,
        rank_probability_matrix=matrix,
        fallback_count=2,
        simulation_count=4,
        seed=31,
        team_ids=("A", "B"),
        remaining_game_ids=("g2",),
        final_wins=np.array([[2, 0], [2, 0], [2, 0], [1, 1]], dtype=np.int32),
        final_losses=np.array([[0, 2], [0, 2], [0, 2], [1, 1]], dtype=np.int32),
        final_point_differentials=np.zeros((4, 2), dtype=np.int64),
        final_ranks=np.array([[1, 2], [1, 2], [1, 2], [2, 1]], dtype=np.int32),
        simulated_home_margins=np.array([[1], [1], [1], [-1]], dtype=np.int32),
    )
    leverage_row = {column: pd.NA for column in LEVERAGE_COLUMNS}
    leverage_row.update(
        {
            "game_id": "g2",
            "game_date": pd.Timestamp("2031-06-03"),
            "home_id": "A",
            "away_id": "B",
            "home_win_branch_n": 3,
            "home_loss_branch_n": 1,
            "conditional_estimate_available": True,
            "direct_h2h_tiebreak_flag": False,
            "cutline_matchup_flag": True,
            "top4_matchup_flag": False,
            "raw_leverage": 50.0,
            "leverage_score": np.float64(88.0),
            "leverage_label": "Critical",
        }
    )
    leverage = pd.DataFrame([leverage_row], columns=LEVERAGE_COLUMNS)
    history_rows = [
        {
                "context_level": "season",
                "metric": "final_qualifier_wins",
                "season": np.int64(2029),
                "season_count": 1,
                "value": 22.0,
                "sample_size": 1,
                "availability_status": "available",
                "as_of_progress_pct": pd.NA,
        },
        {
                "context_level": "availability",
                "metric": "historical_season_status",
                "season": np.int64(2030),
                "season_count": 0,
                "value": pd.NA,
                "sample_size": 0,
                "availability_status": "incomplete_season_outcomes",
                "as_of_progress_pct": pd.NA,
        },
    ]
    history = pd.DataFrame(history_rows).reindex(columns=HISTORICAL_CONTEXT_COLUMNS)
    insights = pd.DataFrame(
        [
            {
                "priority": np.int64(1),
                "category": "leader_race",
                "team_or_race": "ALP",
                "data_point": "75%",
                "quick_read_snippet": "Alpha leads.",
                "pregame_trigger": "Before tip.",
                "halftime_checkpoint": "At half.",
                "fourth_quarter_checkpoint": "Late.",
                "why_it_matters": "Top seed.",
                "source_fields": "rank_1_probability",
            }
        ]
    )
    bundle = ForecastOutputBundle(
        current_standings=current,
        head_to_head=head_to_head,
        team_strength=strength,
        remaining_schedule=remaining,
        matchup_probabilities=matchups,
        simulation_result=simulation,
        playoff_leverage_games=leverage,
        historical_context=history,
        broadcast_insights=insights,
    )
    return cfg, model_cfg, bundle


def _validation_inputs(
    cfg, *, completed: bool = False, external_present: bool = False
):
    from standings_playoff_forecast.standings import ExternalStandingsQA
    from standings_playoff_forecast.team_game_layer import LedgerValidationResult

    completed_gp = 2 if completed else 1
    remaining_games = 0 if completed else 1
    return {
        "ledger_validation": LedgerValidationResult(
            completed_game_count=completed_gp,
            directional_row_count=completed_gp * 2,
            game_ids=tuple(f"g{index}" for index in range(1, completed_gp + 1)),
        ),
        "season_schedule_validation": pd.DataFrame(
            {
                "team_id": ["A", "B"],
                "completed_gp": [completed_gp, completed_gp],
                "remaining_games": [remaining_games, remaining_games],
                "configured_games": [cfg.regular_season_games_per_team] * 2,
                "total_games": [cfg.regular_season_games_per_team] * 2,
                "status": ["validated", "validated"],
            }
        ),
        "external_standings_qa": (
            ExternalStandingsQA(
                status="matched",
                compared_team_count=2,
                mismatch_team_ids=(),
                message="fixture records matched",
            )
            if external_present
            else ExternalStandingsQA(
                status="unavailable",
                compared_team_count=0,
                mismatch_team_ids=(),
                message="fixture external standings unavailable",
            )
        ),
    }


def _write_fixture_bundle(
    root: Path,
    cfg,
    model_cfg,
    bundle,
):
    from standings_playoff_forecast.outputs import write_output_bundle

    root.mkdir(parents=True, exist_ok=True)
    season_config = root / "season.json"
    model_config = root / "model.json"
    source = root / "source.bin"
    season_config.write_bytes(b"season")
    model_config.write_bytes(b"model")
    source.write_bytes(b"source")
    return write_output_bundle(
        bundle,
        cfg=cfg,
        model_cfg=model_cfg,
        cutoff="2031-06-01",
        season_config_path=season_config,
        model_config_path=model_config,
        source_files={"schedule": source},
        **_validation_inputs(cfg),
        repository_root=root,
    )


class OutputBundleTest(unittest.TestCase):
    def test_rejects_safe_pbpstats_rows_without_supported_provenance_evidence(self) -> None:
        """Catches a safe PBPStats status crossing the output boundary without evidence."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            invalid_strength = bundle.team_strength.drop(
                columns=[
                    "pbpstats_provenance_kind",
                    "pbpstats_cutoff_safety_upper_bound",
                ]
            )
            invalid_bundle = replace(bundle, team_strength=invalid_strength)
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")

            with self.assertRaisesRegex(ValueError, "missing required columns"):
                write_output_bundle(
                    invalid_bundle,
                    cfg=cfg,
                    model_cfg=model_cfg,
                    cutoff="2031-06-01",
                    season_config_path=season_config,
                    model_config_path=model_config,
                    source_files={"schedule": source},
                    **_validation_inputs(cfg),
                    repository_root=root,
                )

    def test_rejects_available_pbpstats_rows_without_kind_or_evidence(self) -> None:
        """Catches context availability claiming a source state that cannot be described."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            invalid_strength = bundle.team_strength.copy()
            invalid_strength["pbpstats_snapshot_safe_for_cutoff"] = False
            invalid_strength["pbpstats_provenance_kind"] = pd.NA
            invalid_strength["pbpstats_snapshot_as_of"] = pd.NaT
            invalid_strength["pbpstats_cutoff_safety_upper_bound"] = pd.NaT
            invalid_bundle = replace(bundle, team_strength=invalid_strength)
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")

            with self.assertRaisesRegex(ValueError, "PBPStats provenance"):
                write_output_bundle(
                    invalid_bundle,
                    cfg=cfg,
                    model_cfg=model_cfg,
                    cutoff="2031-06-01",
                    season_config_path=season_config,
                    model_config_path=model_config,
                    source_files={"schedule": source},
                    **_validation_inputs(cfg),
                    repository_root=root,
                )

    def test_manifest_status_names_last_saved_cutoff_safety_bound_honestly(self) -> None:
        """Catches conservative save-time evidence being called exact coverage."""
        from standings_playoff_forecast.metadata import (
            _pbpstats_enrichment_status,
            _pbpstats_provenance_kind,
        )

        cfg, model_cfg, _bundle = _inputs(Path("/tmp/pbp-provenance-test"))
        strength = pd.DataFrame(
            {
                "pbpstats_snapshot_available": [True, True],
                "pbpstats_snapshot_safe_for_cutoff": [True, True],
                "pbpstats_provenance_kind": [
                    "last_saved_at_utc_upper_bound",
                    "last_saved_at_utc_upper_bound",
                ],
            }
        )

        self.assertEqual(
            _pbpstats_enrichment_status(strength, model_cfg),
            "safe_for_cutoff_via_last_saved_upper_bound",
        )
        self.assertEqual(
            _pbpstats_provenance_kind(strength),
            "last_saved_at_utc_upper_bound",
        )

    def test_writes_complete_deterministic_bundle_with_joined_forecast_contract(self) -> None:
        """Catches missing files, hardcoded season paths, or recalculated probabilities."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            season_config = root / "season.json"
            model_config = root / "model.json"
            schedule_source = root / "schedule.parquet"
            external_source = root / "external-standings.parquet"
            season_config.write_bytes(b'{"season":2031}\n')
            model_config.write_bytes(b'{"model":"literal"}\n')
            schedule_source.write_bytes(b"literal-source-bytes\n")
            external_source.write_bytes(b"external-validation-bytes\n")

            output = write_output_bundle(
                bundle,
                cfg=cfg,
                model_cfg=model_cfg,
                cutoff="2031-06-01T19:30:00Z",
                season_config_path=season_config,
                model_config_path=model_config,
                source_files={
                    "schedule": schedule_source,
                    "external_standings": external_source,
                },
                conditional_simulation_count=0,
                **_validation_inputs(cfg, external_present=True),
                repository_root=root / "not-a-repository",
            )
            first_bytes = {path.name: path.read_bytes() for path in output.iterdir()}
            second = write_output_bundle(
                bundle,
                cfg=cfg,
                model_cfg=model_cfg,
                cutoff="2031-06-01T19:30:00Z",
                season_config_path=season_config,
                model_config_path=model_config,
                source_files={
                    "schedule": schedule_source,
                    "external_standings": external_source,
                },
                conditional_simulation_count=0,
                **_validation_inputs(cfg, external_present=True),
                repository_root=root / "not-a-repository",
            )

            self.assertEqual(output, root / "forecast-root" / "data" / "processed" / "season=2031" / "latest")
            self.assertEqual({path.name for path in output.iterdir()}, EXPECTED_FILES)
            self.assertEqual(first_bytes, {path.name: path.read_bytes() for path in second.iterdir()})

            forecast = pd.read_csv(output / "forecast_summary.csv")
            self.assertEqual(forecast["team_id"].tolist(), ["A", "B"])
            self.assertEqual(forecast["team_abbreviation"].tolist(), ["ALP", "BRV"])
            self.assertEqual(forecast["current_rank"].tolist(), [1, 2])
            self.assertEqual(forecast["remaining_games"].tolist(), [1, 1])
            self.assertEqual(forecast["remaining_sos_rank"].tolist(), [2, 1])
            self.assertEqual(forecast["most_leverage_game_id"].tolist(), ["g2", "g2"])
            self.assertEqual(forecast["status_note"].tolist(), ["not_evaluated", "not_evaluated"])
            self.assertTrue(forecast["clinched_playoffs"].isna().all())
            self.assertTrue(forecast["eliminated_from_playoffs"].isna().all())
            self.assertEqual(forecast["rank_1_probability"].tolist(), [0.75, 0.25])
            self.assertEqual(forecast["rank_2_probability"].tolist(), [0.25, 0.75])

            rank_matrix = pd.read_csv(output / "rank_probability_matrix.csv")
            self.assertEqual(rank_matrix["cutoff_date"].unique().tolist(), ["2031-06-01"])
            self.assertEqual(rank_matrix["team_abbreviation"].tolist(), ["ALP", "ALP", "BRV", "BRV"])

            from standings_playoff_forecast.standings import STANDINGS_COLUMNS

            standings_csv = pd.read_csv(output / "current_standings.csv")
            self.assertEqual(list(standings_csv.columns), STANDINGS_COLUMNS)
            self.assertEqual(standings_csv["home_record"].tolist(), ["1-0", "0-0"])
            self.assertEqual(standings_csv["current_streak_label"].tolist(), ["W1", "L1"])

            manifest = json.loads((output / "run_manifest.json").read_text())
            payload = json.loads((output / "forecast_payload.json").read_text())
            self.assertEqual(
                set(payload),
                {
                    "metadata",
                    "standings",
                    "forecast_summary",
                    "rank_probability_matrix",
                    "remaining_schedule",
                    "leverage_games",
                    "broadcast_insights",
                    "historical_context",
                },
            )
            self.assertEqual(payload["metadata"], manifest)
            self.assertEqual(manifest["season"], 2031)
            self.assertEqual(manifest["cutoff_date"], "2031-06-01")
            self.assertEqual(manifest["simulation_count"], 4)
            self.assertEqual(manifest["conditional_simulation_count"], 0)
            self.assertEqual(manifest["random_seed"], 31)
            self.assertEqual(manifest["model_version"], "literal_model")
            self.assertEqual(manifest["official_tiebreak_fallback_count"], 2)
            self.assertEqual(manifest["history_seasons_used"], [2029])
            self.assertEqual(manifest["pbpstats_enrichment_status"], "safe_for_cutoff")
            self.assertEqual(manifest["pbpstats_provenance_kind"], "snapshot_as_of")
            self.assertIsNone(manifest["git_sha"])
            self.assertEqual(manifest["git_sha_status"], "unavailable")
            self.assertEqual(
                manifest["source_of_truth"],
                {
                    "current_standings": "derived_from_schedule_and_team_box",
                    "schedule": "mandatory",
                    "team_box": "mandatory",
                    "external_standings": "optional_validation",
                },
            )
            self.assertEqual(manifest["ledger_validation"], {"status": "validated"})
            self.assertEqual(
                manifest["season_schedule_validation"],
                {"status": "validated", "configured_games_per_team": 2},
            )
            self.assertEqual(
                manifest["external_standings_qa"],
                {
                    "status": "matched",
                    "compared_team_count": 2,
                    "mismatch_team_ids": [],
                },
            )
            self.assertEqual(manifest["season_config_sha256"], hashlib.sha256(season_config.read_bytes()).hexdigest())
            self.assertEqual(manifest["model_config_sha256"], hashlib.sha256(model_config.read_bytes()).hexdigest())
            sources_by_name = {entry["name"]: entry for entry in manifest["source_files"]}
            self.assertEqual(set(sources_by_name), {"schedule", "external_standings"})
            self.assertEqual(sources_by_name["schedule"]["path"], str(schedule_source.resolve()))
            self.assertEqual(sources_by_name["schedule"]["size_bytes"], len(b"literal-source-bytes\n"))
            self.assertEqual(sources_by_name["schedule"]["sha256"], hashlib.sha256(b"literal-source-bytes\n").hexdigest())
            self.assertEqual(sources_by_name["external_standings"]["path"], str(external_source.resolve()))
            self.assertEqual(
                sources_by_name["external_standings"]["sha256"],
                hashlib.sha256(b"external-validation-bytes\n").hexdigest(),
            )
            self.assertEqual(payload["remaining_schedule"][0]["game_date"], "2031-06-03T00:00:00")
            self.assertIsNone(payload["historical_context"][0]["as_of_progress_pct"])
            payload_standings = {row["team_id"]: row for row in payload["standings"]}
            self.assertEqual(payload_standings["A"]["home_record"], "1-0")
            self.assertEqual(payload_standings["B"]["current_streak_label"], "L1")

    def test_rejects_untyped_or_internally_inconsistent_validation_evidence(self) -> None:
        """Catches a manifest trusting caller-supplied status mappings or corrupt results."""
        from standings_playoff_forecast.outputs import write_output_bundle
        from standings_playoff_forecast.standings import ExternalStandingsQA
        from standings_playoff_forecast.team_game_layer import LedgerValidationResult

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")
            common = {
                "cfg": cfg,
                "model_cfg": model_cfg,
                "cutoff": "2031-06-01",
                "season_config_path": season_config,
                "model_config_path": model_config,
                "source_files": {"schedule": source},
                "repository_root": root,
            }
            valid = _validation_inputs(cfg)
            bad_schedule = valid["season_schedule_validation"].copy()
            bad_schedule.loc[1, "status"] = "unchecked"
            cases = [
                (
                    "ledger_mapping",
                    {**valid, "ledger_validation": {"status": "validated"}},
                    TypeError,
                    "LedgerValidationResult",
                ),
                (
                    "ledger_counts",
                    {
                        **valid,
                        "ledger_validation": LedgerValidationResult(1, 1, ("g1",)),
                    },
                    ValueError,
                    "directional_row_count",
                ),
                (
                    "schedule_mapping",
                    {
                        **valid,
                        "season_schedule_validation": {"status": "validated"},
                    },
                    TypeError,
                    "DataFrame",
                ),
                (
                    "schedule_status",
                    {**valid, "season_schedule_validation": bad_schedule},
                    ValueError,
                    "status.*validated",
                ),
                (
                    "ledger_schedule_disagreement",
                    {
                        **valid,
                        "ledger_validation": LedgerValidationResult(
                            2, 4, ("g1", "g2")
                        ),
                    },
                    ValueError,
                    "completed games.*ledger",
                ),
                (
                    "external_mapping",
                    {
                        **valid,
                        "external_standings_qa": {"status": "matched"},
                    },
                    TypeError,
                    "ExternalStandingsQA",
                ),
                (
                    "external_status",
                    {
                        **valid,
                        "external_standings_qa": ExternalStandingsQA(
                            status="unchecked",
                            compared_team_count=2,
                            mismatch_team_ids=(),
                            message="fixture",
                        ),
                    },
                    ValueError,
                    "external standings QA status",
                ),
                (
                    "external_partial_match",
                    {
                        **valid,
                        "external_standings_qa": ExternalStandingsQA(
                            status="matched",
                            compared_team_count=1,
                            mismatch_team_ids=(),
                            message="fixture",
                        ),
                    },
                    ValueError,
                    "matched external standings QA.*configured team",
                ),
            ]
            for name, validation, error_type, message in cases:
                with self.subTest(case=name):
                    with self.assertRaisesRegex(error_type, message):
                        write_output_bundle(bundle, **common, **validation)

            output = (
                root
                / "forecast-root"
                / "data"
                / "processed"
                / "season=2031"
                / "latest"
            )
            self.assertFalse(output.exists())

    def test_rejects_schedule_evidence_that_disagrees_with_emitted_frames(self) -> None:
        """Catches forged same-sized team universes or per-team game counts."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            base_root = Path(tmp)
            cases = []

            cfg, model_cfg, bundle = _inputs(base_root / "universe")
            forged_universe = _validation_inputs(cfg)
            forged_universe["season_schedule_validation"].loc[1, "team_id"] = "C"
            cases.append(
                (
                    "team_universe",
                    cfg,
                    model_cfg,
                    bundle,
                    forged_universe,
                    "team universe.*current_standings",
                )
            )

            cfg, model_cfg, bundle = _inputs(base_root / "completed")
            forged_completed = _validation_inputs(cfg)
            bundle = replace(
                bundle,
                current_standings=bundle.current_standings.assign(
                    games_played=[0, 2]
                ),
            )
            cases.append(
                (
                    "completed_gp",
                    cfg,
                    model_cfg,
                    bundle,
                    forged_completed,
                    "completed_gp.*current_standings games_played",
                )
            )

            cfg, model_cfg, bundle = _inputs(base_root / "remaining")
            forged_remaining = _validation_inputs(cfg)
            counts = forged_remaining["season_schedule_validation"]
            counts["completed_gp"] = [2, 0]
            counts["remaining_games"] = [0, 2]
            bundle = replace(
                bundle,
                current_standings=bundle.current_standings.assign(
                    games_played=[2, 0]
                ),
            )
            cases.append(
                (
                    "remaining_games",
                    cfg,
                    model_cfg,
                    bundle,
                    forged_remaining,
                    "remaining_games.*remaining_schedule",
                )
            )

            for name, cfg, model_cfg, bundle, validation, message in cases:
                with self.subTest(case=name):
                    root = base_root / name
                    root.mkdir(parents=True, exist_ok=True)
                    season_config = root / "season.json"
                    model_config = root / "model.json"
                    source = root / "source.bin"
                    season_config.write_bytes(b"season")
                    model_config.write_bytes(b"model")
                    source.write_bytes(b"source")
                    with self.assertRaisesRegex(ValueError, message):
                        write_output_bundle(
                            bundle,
                            cfg=cfg,
                            model_cfg=model_cfg,
                            cutoff="2031-06-01",
                            season_config_path=season_config,
                            model_config_path=model_config,
                            source_files={"schedule": source},
                            **validation,
                            repository_root=root,
                        )
                    self.assertFalse(
                        (
                            Path(cfg.output_root)
                            / "data"
                            / "processed"
                            / "season=2031"
                            / "latest"
                        ).exists()
                    )

    def test_rejects_external_qa_and_source_provenance_contradictions(self) -> None:
        """Catches manifests whose QA status cannot be supported by source evidence."""
        from standings_playoff_forecast.outputs import write_output_bundle
        from standings_playoff_forecast.standings import ExternalStandingsQA

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            season_config = root / "season.json"
            model_config = root / "model.json"
            schedule_source = root / "schedule.bin"
            external_source = root / "external.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            schedule_source.write_bytes(b"schedule")
            external_source.write_bytes(b"external")
            common = {
                "cfg": cfg,
                "model_cfg": model_cfg,
                "cutoff": "2031-06-01",
                "season_config_path": season_config,
                "model_config_path": model_config,
                "repository_root": root,
            }
            validation = _validation_inputs(cfg)
            present_statuses = [
                ExternalStandingsQA("matched", 2, (), "matched fixture"),
                ExternalStandingsQA("mismatch", 1, ("A",), "mismatch fixture"),
                ExternalStandingsQA("unparseable", 0, (), "unparseable fixture"),
            ]
            for qa in present_statuses:
                with self.subTest(status=qa.status, external_source="missing"):
                    with self.assertRaisesRegex(
                        ValueError, "external standings QA.*requires.*source provenance"
                    ):
                        write_output_bundle(
                            bundle,
                            source_files={"schedule": schedule_source},
                            **common,
                            **{**validation, "external_standings_qa": qa},
                        )

            with self.assertRaisesRegex(
                ValueError, "unavailable external standings QA.*omit.*source provenance"
            ):
                write_output_bundle(
                    bundle,
                    source_files={
                        "schedule": schedule_source,
                        "external_standings": external_source,
                    },
                    **common,
                    **validation,
                )

    def test_preserves_supplied_mathematical_status_without_inferring_from_probability(self) -> None:
        """Catches discarding upstream proof or treating Monte Carlo 0/1 as proof."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            current = bundle.current_standings.assign(
                clinched_playoffs=[True, False],
                eliminated_from_playoffs=[False, True],
                status_note=["mathematically_clinched", "mathematically_eliminated"],
            )
            bundle = replace(bundle, current_standings=current)
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")

            output = write_output_bundle(
                bundle,
                cfg=cfg,
                model_cfg=model_cfg,
                cutoff="2031-06-01",
                season_config_path=season_config,
                model_config_path=model_config,
                source_files={"schedule": source},
                **_validation_inputs(cfg),
                repository_root=root,
            )

            payload = json.loads((output / "forecast_payload.json").read_text())
            statuses = {
                row["team_id"]: (
                    row["clinched_playoffs"],
                    row["eliminated_from_playoffs"],
                    row["status_note"],
                )
                for row in payload["forecast_summary"]
            }
            self.assertEqual(
                statuses,
                {
                    "A": (True, False, "mathematically_clinched"),
                    "B": (False, True, "mathematically_eliminated"),
                },
            )

    def test_serialization_failure_leaves_existing_bundle_and_no_temporary_siblings(self) -> None:
        """Catches writing final paths before every in-memory serialization succeeds."""
        from standings_playoff_forecast import outputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")
            kwargs = {
                "cfg": cfg,
                "model_cfg": model_cfg,
                "cutoff": "2031-06-01",
                "season_config_path": season_config,
                "model_config_path": model_config,
                "source_files": {"schedule": source},
                **_validation_inputs(cfg),
                "repository_root": root,
            }
            output = outputs.write_output_bundle(bundle, **kwargs)
            original = {path.name: path.read_bytes() for path in output.iterdir()}
            real_to_csv = pd.DataFrame.to_csv

            def fail_on_history(frame, *args, **kwargs):
                if "availability_status" in frame.columns:
                    raise RuntimeError("injected CSV serialization failure")
                return real_to_csv(frame, *args, **kwargs)

            with mock.patch.object(pd.DataFrame, "to_csv", new=fail_on_history):
                with self.assertRaisesRegex(RuntimeError, "injected CSV serialization failure"):
                    outputs.write_output_bundle(bundle, **kwargs)

            self.assertEqual(original, {path.name: path.read_bytes() for path in output.iterdir()})
            self.assertEqual(list(output.glob(".*.tmp")), [])

    def test_directory_publish_failure_keeps_previous_bundle_and_cleans_staging(self) -> None:
        """Catches exposing a mixed generation when the bundle swap fails."""
        from standings_playoff_forecast import outputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")
            kwargs = {
                "cfg": cfg,
                "model_cfg": model_cfg,
                "cutoff": "2031-06-01",
                "season_config_path": season_config,
                "model_config_path": model_config,
                "source_files": {"schedule": source},
                **_validation_inputs(cfg),
                "repository_root": root,
            }
            output = outputs.write_output_bundle(bundle, **kwargs)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            real_replace = os.replace

            def fail_bundle_publish(source_path, target_path):
                source = Path(source_path)
                target = Path(target_path)
                if (
                    target == output
                    and source.name.startswith(".latest.")
                    and source.name.endswith(".tmp")
                ):
                    raise OSError("injected directory publication failure")
                return real_replace(source_path, target_path)

            with mock.patch.object(
                outputs.os, "replace", side_effect=fail_bundle_publish
            ):
                with self.assertRaisesRegex(
                    OSError, "injected directory publication failure"
                ):
                    outputs.write_output_bundle(bundle, **kwargs)

            self.assertEqual(
                {path.name: path.read_bytes() for path in output.iterdir()}, before
            )
            self.assertEqual(list(output.parent.glob(".latest.*")), [])

    def test_rejects_inconsistent_game_keys_and_infinite_json_values_before_writing(self) -> None:
        """Catches cross-table drift and non-standard Infinity JSON tokens."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            bad_matchups = bundle.matchup_probabilities.assign(away_id="X")
            bad_history = bundle.historical_context.copy()
            bad_history.loc[0, "value"] = np.inf
            bundle = replace(
                bundle,
                matchup_probabilities=bad_matchups,
                historical_context=bad_history,
            )
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")

            with self.assertRaisesRegex(ValueError, "infinite value|outside current_standings"):
                write_output_bundle(
                    bundle,
                    cfg=cfg,
                    model_cfg=model_cfg,
                    cutoff="2031-06-01",
                    season_config_path=season_config,
                    model_config_path=model_config,
                    source_files={"schedule": source},
                    **_validation_inputs(cfg),
                    repository_root=root,
                )
            output = root / "forecast-root" / "data" / "processed" / "season=2031" / "latest"
            self.assertFalse(output.exists())

    def test_payload_validator_rejects_missing_or_extra_top_level_keys(self) -> None:
        """Catches silently publishing a renderer-incompatible payload shape."""
        from standings_playoff_forecast.outputs import validate_forecast_payload

        with self.assertRaisesRegex(ValueError, "missing: broadcast_insights"):
            validate_forecast_payload(
                {
                    "metadata": {},
                    "standings": [],
                    "forecast_summary": [],
                    "rank_probability_matrix": [],
                    "remaining_schedule": [],
                    "leverage_games": [],
                    "historical_context": [],
                    "unexpected": [],
                }
            )

    def test_rejects_incomplete_canonical_matchup_schema_before_writing(self) -> None:
        """Catches publishing a table that later renderers cannot consume."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            bundle = replace(
                bundle,
                matchup_probabilities=bundle.matchup_probabilities.drop(
                    columns="margin_sigma"
                ),
            )
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")

            with self.assertRaisesRegex(
                ValueError,
                "matchup_probabilities is missing required columns: margin_sigma",
            ):
                write_output_bundle(
                    bundle,
                    cfg=cfg,
                    model_cfg=model_cfg,
                    cutoff="2031-06-01",
                    season_config_path=season_config,
                    model_config_path=model_config,
                    source_files={"schedule": source},
                    **_validation_inputs(cfg),
                    repository_root=root,
                )

    def test_rejects_incomplete_canonical_schemas_for_every_serialized_stage(self) -> None:
        """Catches weak per-stage schema gates that merely check identifier columns."""
        from standings_playoff_forecast.outputs import write_output_bundle

        cases = [
            ("current_standings", "points_for"),
            ("head_to_head", "losses"),
            ("team_strength", "recent_games_played"),
            ("remaining_schedule", "home_rest_days"),
            ("playoff_leverage_games", "home_win_branch_n"),
            ("historical_context", "sample_size"),
            ("broadcast_insights", "source_fields"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for frame_name, missing_column in cases:
                with self.subTest(frame=frame_name, column=missing_column):
                    root = Path(tmp) / frame_name
                    root.mkdir()
                    cfg, model_cfg, bundle = _inputs(root)
                    incomplete = getattr(bundle, frame_name).drop(columns=missing_column)
                    bundle = replace(bundle, **{frame_name: incomplete})
                    season_config = root / "season.json"
                    model_config = root / "model.json"
                    source = root / "source.bin"
                    season_config.write_bytes(b"season")
                    model_config.write_bytes(b"model")
                    source.write_bytes(b"source")

                    with self.assertRaisesRegex(
                        ValueError,
                        f"{frame_name} is missing required columns:.*{missing_column}",
                    ):
                        write_output_bundle(
                            bundle,
                            cfg=cfg,
                            model_cfg=model_cfg,
                            cutoff="2031-06-01",
                            season_config_path=season_config,
                            model_config_path=model_config,
                            source_files={"schedule": source},
                            **_validation_inputs(cfg),
                            repository_root=root,
                        )

    def test_rejects_empty_or_invalid_source_provenance(self) -> None:
        """Catches manifests that name no evidence or accept a placeholder digest."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            season_config = root / "season.json"
            model_config = root / "model.json"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            common = {
                "cfg": cfg,
                "model_cfg": model_cfg,
                "cutoff": "2031-06-01",
                "season_config_path": season_config,
                "model_config_path": model_config,
                **_validation_inputs(cfg),
                "repository_root": root,
            }

            with self.assertRaisesRegex(ValueError, "source_files must not be empty"):
                write_output_bundle(bundle, source_files={}, **common)
            with self.assertRaisesRegex(ValueError, "valid SHA-256"):
                write_output_bundle(
                    bundle,
                    source_files={
                        "schedule": {
                            "path": root / "missing.parquet",
                            "size_bytes": 7,
                            "sha256": "not-a-digest",
                        }
                    },
                    **common,
                )

    def test_rejects_matchup_model_version_that_disagrees_with_manifest(self) -> None:
        """Catches internally inconsistent model provenance across bundle files."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            bundle = replace(
                bundle,
                matchup_probabilities=bundle.matchup_probabilities.assign(
                    model_version="different_model"
                ),
            )
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")

            with self.assertRaisesRegex(
                ValueError, "matchup model_version must match model config"
            ):
                write_output_bundle(
                    bundle,
                    cfg=cfg,
                    model_cfg=model_cfg,
                    cutoff="2031-06-01",
                    season_config_path=season_config,
                    model_config_path=model_config,
                    source_files={"schedule": source},
                    **_validation_inputs(cfg),
                    repository_root=root,
                )

    def test_writes_completed_season_with_empty_remaining_and_leverage_tables(self) -> None:
        """Catches treating an empty canonical schedule as a missing model version."""
        from standings_playoff_forecast.outputs import write_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            simulation = replace(
                bundle.simulation_result,
                remaining_game_ids=(),
                simulated_home_margins=np.empty((4, 0), dtype=np.int32),
            )
            bundle = replace(
                bundle,
                current_standings=bundle.current_standings.assign(
                    games_played=2,
                    wins=[2, 0],
                    losses=[0, 2],
                ),
                remaining_schedule=bundle.remaining_schedule.iloc[0:0],
                matchup_probabilities=bundle.matchup_probabilities.iloc[0:0],
                simulation_result=simulation,
                playoff_leverage_games=bundle.playoff_leverage_games.iloc[0:0],
            )
            season_config = root / "season.json"
            model_config = root / "model.json"
            source = root / "source.bin"
            season_config.write_bytes(b"season")
            model_config.write_bytes(b"model")
            source.write_bytes(b"source")

            output = write_output_bundle(
                bundle,
                cfg=cfg,
                model_cfg=model_cfg,
                cutoff="2031-06-01",
                season_config_path=season_config,
                model_config_path=model_config,
                source_files={"schedule": source},
                **_validation_inputs(cfg, completed=True),
                repository_root=root,
            )

            payload = json.loads((output / "forecast_payload.json").read_text())
            self.assertEqual(payload["remaining_schedule"], [])
            self.assertEqual(payload["leverage_games"], [])
            for row in payload["forecast_summary"]:
                self.assertEqual(row["remaining_games"], 0)
                self.assertIsNone(row["remaining_sos_rank"])
                self.assertIsNone(row["most_leverage_game_id"])

    def test_git_operating_system_failure_is_explicitly_unavailable(self) -> None:
        """Catches optional git provenance crashing an otherwise valid run."""
        from standings_playoff_forecast.metadata import _git_provenance

        with mock.patch(
            "standings_playoff_forecast.metadata.subprocess.run",
            side_effect=PermissionError("git execution denied"),
        ):
            self.assertEqual(
                _git_provenance(ROOT),
                (None, "unavailable"),
            )

    def test_rejects_forecast_aggregates_inconsistent_with_exact_rank_matrix(self) -> None:
        """Catches trusting drifted aggregate fields while exact rank cells remain valid."""
        aggregate_cases = {
            "playoff_probability": [0.60, 0.40],
            "top4_probability": [0.60, 0.40],
            "home_court_probability": [0.60, 0.40],
            "out_probability": [0.40, 0.60],
            "expected_final_rank": [1.40, 1.60],
        }
        with tempfile.TemporaryDirectory() as tmp:
            for column, bad_values in aggregate_cases.items():
                with self.subTest(column=column):
                    root = Path(tmp) / column
                    cfg, model_cfg, bundle = _inputs(root)
                    summary = bundle.simulation_result.forecast_summary.copy()
                    summary[column] = bad_values
                    simulation = replace(bundle.simulation_result, forecast_summary=summary)
                    bundle = replace(bundle, simulation_result=simulation)

                    with self.assertRaisesRegex(
                        ValueError,
                        f"{column}.*rank_probability_matrix",
                    ):
                        _write_fixture_bundle(root, cfg, model_cfg, bundle)

            tolerance_root = Path(tmp) / "within_tolerance"
            cfg, model_cfg, bundle = _inputs(tolerance_root)
            summary = bundle.simulation_result.forecast_summary.copy()
            supplied_probability = 0.7500000000005
            summary.loc[summary["team_id"].eq("A"), "playoff_probability"] = (
                supplied_probability
            )
            simulation = replace(bundle.simulation_result, forecast_summary=summary)
            bundle = replace(bundle, simulation_result=simulation)
            output = _write_fixture_bundle(tolerance_root, cfg, model_cfg, bundle)
            payload = json.loads((output / "forecast_payload.json").read_text())
            alpha = next(
                row for row in payload["forecast_summary"] if row["team_id"] == "A"
            )
            self.assertEqual(alpha["playoff_probability"], supplied_probability)

    def test_rejects_invalid_playoff_rank_semantics(self) -> None:
        """Catches qualifying ranks marked null or out ranks marked as playoff seeds."""
        matrix_cases = {
            "qualifying_rank_is_null": (0, pd.NA),
            "out_rank_is_populated": (1, 2),
            "out_rank_is_malformed": (1, "not-a-rank"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (row_index, bad_value) in matrix_cases.items():
                with self.subTest(case=name):
                    root = Path(tmp) / name
                    cfg, model_cfg, bundle = _inputs(root)
                    matrix = bundle.simulation_result.rank_probability_matrix.copy()
                    matrix.loc[row_index, "playoff_rank"] = bad_value
                    simulation = replace(
                        bundle.simulation_result,
                        rank_probability_matrix=matrix,
                    )
                    bundle = replace(bundle, simulation_result=simulation)

                    with self.assertRaisesRegex(
                        ValueError,
                        "playoff_rank.*qualifying final_rank",
                    ):
                        _write_fixture_bundle(root, cfg, model_cfg, bundle)

    def test_validates_shared_schedule_and_leverage_fields_against_matchups(self) -> None:
        """Catches same-key rows whose date, rest, or B2B context silently diverges."""
        matchup_changes = {
            "game_date": pd.Timestamp("2031-06-04"),
            "home_rest_days": 9,
            "away_rest_days": 8,
            "home_b2b": True,
            "away_b2b": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            for column, bad_value in matchup_changes.items():
                with self.subTest(frame="matchup_probabilities", column=column):
                    root = Path(tmp) / f"matchup_{column}"
                    cfg, model_cfg, bundle = _inputs(root)
                    matchups = bundle.matchup_probabilities.copy()
                    matchups[column] = bad_value
                    bundle = replace(bundle, matchup_probabilities=matchups)

                    with self.assertRaisesRegex(
                        ValueError,
                        f"{column}.*remaining_schedule",
                    ):
                        _write_fixture_bundle(root, cfg, model_cfg, bundle)

            root = Path(tmp) / "matchup_missing_home_rest_days"
            cfg, model_cfg, bundle = _inputs(root)
            matchups = bundle.matchup_probabilities.copy()
            matchups["home_rest_days"] = pd.NA
            bundle = replace(bundle, matchup_probabilities=matchups)
            with self.assertRaisesRegex(
                ValueError,
                "home_rest_days.*remaining_schedule",
            ):
                _write_fixture_bundle(root, cfg, model_cfg, bundle)

            root = Path(tmp) / "leverage_game_date"
            cfg, model_cfg, bundle = _inputs(root)
            leverage = bundle.playoff_leverage_games.copy()
            leverage["game_date"] = pd.Timestamp("2031-06-05")
            bundle = replace(bundle, playoff_leverage_games=leverage)
            with self.assertRaisesRegex(
                ValueError,
                "game_date.*matchup_probabilities",
            ):
                _write_fixture_bundle(root, cfg, model_cfg, bundle)

    def test_historical_context_bytes_are_stable_for_equivalent_row_order(self) -> None:
        """Catches leaking historical input order into canonical CSV or JSON bytes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, model_cfg, bundle = _inputs(root)
            output = _write_fixture_bundle(root, cfg, model_cfg, bundle)
            first_csv = (output / "historical_context.csv").read_bytes()
            first_payload = (output / "forecast_payload.json").read_bytes()

            reversed_history = bundle.historical_context.iloc[::-1].reset_index(drop=True)
            reversed_bundle = replace(bundle, historical_context=reversed_history)
            output = _write_fixture_bundle(root, cfg, model_cfg, reversed_bundle)

            self.assertEqual(
                (output / "historical_context.csv").read_bytes(),
                first_csv,
            )
            self.assertEqual(
                (output / "forecast_payload.json").read_bytes(),
                first_payload,
            )

    def test_unavailable_source_cannot_override_canonical_provenance_name(self) -> None:
        """Catches caller evidence replacing the manifest's configured source name."""
        from standings_playoff_forecast.metadata import _source_provenance

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.parquet"
            provenance = _source_provenance(
                {
                    "schedule": {
                        "path": missing,
                        "name": "spoofed-source",
                        "size_bytes": 7,
                        "sha256": "a" * 64,
                    }
                }
            )

            self.assertEqual(
                provenance,
                [
                    {
                        "name": "schedule",
                        "path": str(missing.resolve()),
                        "size_bytes": 7,
                        "sha256": "a" * 64,
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
