import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _fixture_config(
    source_root: Path, *, season: int = 2026, games_per_team: int = 1
):
    from standings_playoff_forecast.config import load_season_config

    return replace(
        load_season_config(2026),
        season=season,
        team_count=2,
        regular_season_games_per_team=games_per_team,
        normalized_team_game_root=str(source_root / "processed"),
    )


def _write_source_fixture(source_root: Path) -> dict[str, Path]:
    paths = {
        "schedule_path": source_root / "schedule.parquet",
        "team_box_path": source_root / "team_box.parquet",
        "external_standings_path": source_root / "standings.parquet",
    }
    pd.DataFrame(
        [
            {
                "game_id": 501.0,
                "season": 2026,
                "season_type": 2,
                "game_date": "2026-06-01",
                "status_type_completed": True,
                "status_type_name": "STATUS_FINAL",
                "type_abbreviation": "STD",
                "format_regulation_periods": 4,
                "status_period": 4,
                "home_id": 17.0,
                "home_abbreviation": "LV",
                "home_display_name": "Las Vegas Aces",
                "home_score": 80,
                "away_id": "19",
                "away_abbreviation": "CHI",
                "away_display_name": "Chicago Sky",
                "away_score": 70,
            }
        ]
    ).to_parquet(paths["schedule_path"])
    pd.DataFrame(
        [
            {
                "game_id": 501.0,
                "team_id": 17.0,
                "field_goals_made": 30,
                "field_goals_attempted": 60,
                "three_point_field_goals_made": 8,
                "free_throws_made": 12,
                "free_throws_attempted": 15,
                "offensive_rebounds": 10,
                "defensive_rebounds": 25,
                "turnovers": 12,
            },
            {
                "game_id": 501.0,
                "team_id": 19.0,
                "field_goals_made": 26,
                "field_goals_attempted": 65,
                "three_point_field_goals_made": 6,
                "free_throws_made": 12,
                "free_throws_attempted": 14,
                "offensive_rebounds": 8,
                "defensive_rebounds": 22,
                "turnovers": 15,
            },
        ]
    ).to_parquet(paths["team_box_path"])
    pd.DataFrame(
        {
            "team_id": [17.0, 19.0],
            "team_abbreviation": ["LV", "CHI"],
            "team_display_name": ["Las Vegas Aces", "Chicago Sky"],
        }
    ).to_parquet(paths["external_standings_path"])
    return paths


def _append_game(
    paths: dict[str, Path],
    *,
    game_id: float,
    game_date: str,
    home_score: int,
    away_score: int,
) -> None:
    schedule = pd.read_parquet(paths["schedule_path"])
    later_game = schedule.iloc[0].copy()
    later_game["game_id"] = game_id
    later_game["game_date"] = game_date
    later_game["home_score"] = home_score
    later_game["away_score"] = away_score
    pd.concat([schedule, later_game.to_frame().T], ignore_index=True).to_parquet(
        paths["schedule_path"]
    )
    team_box = pd.read_parquet(paths["team_box_path"])
    later_box = team_box.loc[team_box["game_id"] == 501.0].copy()
    later_box["game_id"] = game_id
    pd.concat([team_box, later_box], ignore_index=True).to_parquet(paths["team_box_path"])


class ForecastSourceLoaderTest(unittest.TestCase):
    def test_missing_schedule_or_team_box_raises(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources

        cfg = load_season_config(2026)
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            for missing_name in ("schedule", "team_box"):
                with self.subTest(missing_name=missing_name):
                    case_root = source_root / missing_name
                    case_root.mkdir()
                    paths = {
                        "schedule_path": case_root / "schedule.parquet",
                        "team_box_path": case_root / "team_box.parquet",
                        "external_standings_path": case_root / "standings.parquet",
                    }
                    for source_name, path in paths.items():
                        if source_name.removesuffix("_path") != missing_name:
                            pd.DataFrame({"id": [1]}).to_parquet(path)
                    with self.assertRaisesRegex(
                        FileNotFoundError, f"missing mandatory {missing_name} source"
                    ):
                        load_forecast_sources(
                            cfg,
                            **paths,
                            pbp_team_features_path=case_root / "optional.csv",
                        )

    def test_loads_mandatory_tables_when_external_standings_are_missing(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources

        cfg = load_season_config(2026)
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            paths = {
                "schedule_path": source_root / "schedule.parquet",
                "team_box_path": source_root / "team_box.parquet",
                "external_standings_path": source_root / "standings.parquet",
            }
            pd.DataFrame({"game_id": ["101"]}).to_parquet(paths["schedule_path"])
            pd.DataFrame({"game_id": ["101"]}).to_parquet(paths["team_box_path"])

            sources = load_forecast_sources(
                cfg,
                **paths,
                pbp_team_features_path=source_root / "not-present.csv",
            )

        self.assertEqual(sources.schedule["game_id"].tolist(), ["101"])
        self.assertEqual(sources.team_box["game_id"].tolist(), ["101"])
        self.assertIsNone(sources.external_standings)
        self.assertIsNone(sources.external_standings_path)
        self.assertIsNone(sources.pbp_team_features)

    def test_optional_pbpstats_csv_restores_snapshot_as_of_from_json_sidecar(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources

        cfg = load_season_config(2026)
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            paths = {
                "schedule_path": source_root / "schedule.parquet",
                "team_box_path": source_root / "team_box.parquet",
                "external_standings_path": source_root / "standings.parquet",
            }
            pd.DataFrame({"game_id": ["101"]}).to_parquet(paths["schedule_path"])
            pd.DataFrame({"game_id": ["101"]}).to_parquet(paths["team_box_path"])
            pd.DataFrame({"team_id": ["1"]}).to_parquet(paths["external_standings_path"])
            features_path = source_root / "team_totals_features_latest.csv"
            pd.DataFrame(
                {
                    "team_id": ["1"],
                    "plus_minus": [5],
                    "_feature_run_id": ["20260603T210500Z"],
                }
            ).to_csv(features_path, index=False)
            features_path.with_suffix(".json").write_text(
                '{"metadata":{"last_saved_at_utc":"2026-06-03T21:05:00+00:00",'
                '"run_id":"20260603T210500Z","row_count":1},"rows":[]}',
                encoding="utf-8",
            )

            sources = load_forecast_sources(
                cfg,
                **paths,
                pbp_team_features_path=features_path,
            )

        assert sources.pbp_team_features is not None
        self.assertEqual(
            sources.pbp_team_features.attrs["pbpstats_snapshot_metadata"],
            {
                "as_of": "2026-06-03T21:05:00+00:00",
                "run_id": "20260603T210500Z",
                "sidecar": str(features_path.with_suffix(".json")),
            },
        )

    def test_mismatched_pbpstats_sidecar_is_not_trusted_as_cutoff_evidence(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources

        cfg = load_season_config(2026)
        mismatch_metadata = (
            {"row_count": 2, "run_id": "20260603T210500Z"},
            {"row_count": 1, "run_id": "different-run"},
        )
        for metadata in mismatch_metadata:
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as temp_dir:
                source_root = Path(temp_dir)
                paths = {
                    "schedule_path": source_root / "schedule.parquet",
                    "team_box_path": source_root / "team_box.parquet",
                    "external_standings_path": source_root / "standings.parquet",
                }
                pd.DataFrame({"game_id": ["101"]}).to_parquet(paths["schedule_path"])
                pd.DataFrame({"game_id": ["101"]}).to_parquet(paths["team_box_path"])
                pd.DataFrame({"team_id": ["1"]}).to_parquet(paths["external_standings_path"])
                features_path = source_root / "team_totals_features_latest.csv"
                pd.DataFrame(
                    {
                        "team_id": ["1"],
                        "_feature_run_id": ["20260603T210500Z"],
                    }
                ).to_csv(features_path, index=False)
                sidecar = {
                    "metadata": {
                        "last_saved_at_utc": "2026-06-03T21:05:00+00:00",
                        **metadata,
                    },
                    "rows": [],
                }
                features_path.with_suffix(".json").write_text(
                    json.dumps(sidecar), encoding="utf-8"
                )

                sources = load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=features_path,
                )

            assert sources.pbp_team_features is not None
            self.assertNotIn(
                "pbpstats_snapshot_metadata", sources.pbp_team_features.attrs
            )


class TeamGameLayerTest(unittest.TestCase):
    def test_normalize_id_unifies_numeric_and_string_source_ids(self) -> None:
        from standings_playoff_forecast.team_game_layer import normalize_id

        self.assertEqual(normalize_id(17), "17")
        self.assertEqual(normalize_id(17.0), "17")
        self.assertEqual(normalize_id(" 17.0 "), "17")
        self.assertIsNone(normalize_id(None))
        self.assertIsNone(normalize_id(pd.NA))

    def test_completed_game_emits_two_reciprocal_directional_rows(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            sources = load_forecast_sources(
                cfg,
                **paths,
                pbp_team_features_path=Path(temp_dir) / "not-present.csv",
            )
            team_games = build_team_game_layer(sources, cfg)

        self.assertEqual(len(team_games), 2)
        home = team_games.loc[team_games["team_id"] == "17"].iloc[0]
        away = team_games.loc[team_games["team_id"] == "19"].iloc[0]
        self.assertEqual(home["opponent_id"], "19")
        self.assertEqual(away["opponent_id"], "17")
        self.assertEqual(home["margin"], 10)
        self.assertEqual(away["margin"], -10)
        self.assertEqual(home["game_date"], pd.Timestamp("2026-06-01"))
        self.assertEqual(away["game_date"], pd.Timestamp("2026-06-01"))

    def test_no_completed_games_writes_an_empty_contract_table(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            schedule = pd.read_parquet(paths["schedule_path"])
            schedule["status_type_completed"] = False
            schedule.to_parquet(paths["schedule_path"])
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )
            output_path = (
                source_root / "processed" / "season=2026" / "team_game.parquet"
            )

            self.assertTrue(output_path.is_file())

        self.assertTrue(team_games.empty)
        self.assertEqual(len(team_games.columns), 50)

    def test_team_history_maps_stable_franchise_ids_after_string_normalization(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        las_vegas = team_games.loc[team_games["team_id"] == "17"].iloc[0]
        chicago = team_games.loc[team_games["team_id"] == "19"].iloc[0]
        self.assertEqual(las_vegas["franchise_id"], "las_vegas_aces")
        self.assertEqual(las_vegas["opponent_franchise_id"], "chicago_sky")
        self.assertEqual(chicago["franchise_id"], "chicago_sky")
        self.assertEqual(chicago["opponent_franchise_id"], "las_vegas_aces")

    def test_missing_season_franchise_mapping_fails_with_team_ids(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            history_path = source_root / "team_history.csv"
            pd.DataFrame(
                {
                    "season": [2026],
                    "sportsdataverse_team_id": [17],
                    "franchise_id": ["las_vegas_aces"],
                }
            ).to_csv(history_path, index=False)
            sources = load_forecast_sources(
                cfg,
                **paths,
                team_history_path=history_path,
                pbp_team_features_path=source_root / "not-present.csv",
            )

            with self.assertRaisesRegex(
                ValueError, "missing franchise mappings for season 2026: 19"
            ):
                build_team_game_layer(sources, cfg)

    def test_post_cutoff_mutation_cannot_change_as_of_team_games(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root, games_per_team=2)
            paths = _write_source_fixture(source_root)
            _append_game(
                paths,
                game_id=502.0,
                game_date="2026-06-10",
                home_score=75,
                away_score=76,
            )
            before = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
                cutoff="2026-06-05",
            )

            mutated_schedule = pd.read_parquet(paths["schedule_path"])
            mutated_schedule.loc[
                mutated_schedule["game_id"] == 502.0, ["home_score", "away_score"]
            ] = [140, 40]
            mutated_schedule.to_parquet(paths["schedule_path"])
            mutated_box = pd.read_parquet(paths["team_box_path"])
            mutated_box.loc[
                mutated_box["game_id"] == 502.0, "field_goals_made"
            ] = 55
            mutated_box.to_parquet(paths["team_box_path"])
            after = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
                cutoff="2026-06-05",
            )

        self.assertEqual(len(before), 2)
        pd.testing.assert_frame_equal(before, after)

    def test_cumulative_record_uses_team_games_in_chronological_order(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root, games_per_team=2)
            paths = _write_source_fixture(source_root)
            _append_game(
                paths,
                game_id=502.0,
                game_date="2026-06-02",
                home_score=75,
                away_score=76,
            )
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        las_vegas = team_games.loc[team_games["team_id"] == "17"]
        self.assertEqual(las_vegas["season_game_number"].tolist(), [1, 2])
        self.assertEqual(las_vegas["wins_to_date"].tolist(), [1, 1])
        self.assertEqual(las_vegas["losses_to_date"].tolist(), [0, 1])
        self.assertEqual(las_vegas["win_pct_to_date"].tolist(), [1.0, 0.5])
        self.assertEqual(las_vegas["point_diff_to_date"].tolist(), [10, 9])
        self.assertEqual(las_vegas["season_progress_pct"].tolist(), [0.5, 1.0])

    def test_consecutive_game_dates_mark_a_back_to_back(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root, games_per_team=2)
            paths = _write_source_fixture(source_root)
            _append_game(
                paths,
                game_id=502.0,
                game_date="2026-06-02",
                home_score=75,
                away_score=76,
            )
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        las_vegas = team_games.loc[team_games["team_id"] == "17"]
        self.assertTrue(pd.isna(las_vegas["rest_days"].iloc[0]))
        self.assertEqual(las_vegas["rest_days"].iloc[1], 0)
        self.assertEqual(las_vegas["back_to_back"].tolist(), [False, True])

    def test_game_box_scores_produce_hand_checked_advanced_metrics(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        las_vegas = team_games.loc[team_games["team_id"] == "17"].iloc[0]
        self.assertAlmostEqual(las_vegas["possessions_est"], 73.38)
        self.assertAlmostEqual(las_vegas["pace_est"], 73.38)
        self.assertAlmostEqual(las_vegas["efg_pct"], 34 / 60)
        self.assertAlmostEqual(las_vegas["opp_efg_pct"], 29 / 65)
        self.assertAlmostEqual(las_vegas["tov_pct"], 12 / 73.38)
        self.assertAlmostEqual(las_vegas["opp_tov_pct"], 15 / 73.38)
        self.assertAlmostEqual(las_vegas["oreb_pct"], 10 / 32)
        self.assertAlmostEqual(las_vegas["opp_oreb_pct"], 8 / 33)
        self.assertAlmostEqual(las_vegas["ftr"], 15 / 60)
        self.assertAlmostEqual(las_vegas["opp_ftr"], 14 / 65)
        self.assertAlmostEqual(las_vegas["ortg_est"], 8000 / 73.38)
        self.assertAlmostEqual(las_vegas["drtg_est"], 7000 / 73.38)
        self.assertAlmostEqual(las_vegas["net_rating_est"], 1000 / 73.38)

    def test_overtime_pace_is_normalized_to_a_forty_minute_game(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            schedule = pd.read_parquet(paths["schedule_path"])
            schedule["status_period"] = 5
            schedule.to_parquet(paths["schedule_path"])
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        las_vegas = team_games.loc[team_games["team_id"] == "17"].iloc[0]
        self.assertAlmostEqual(las_vegas["possessions_est"], 73.38)
        self.assertAlmostEqual(las_vegas["pace_est"], 73.38 * 40 / 45)

    def test_missing_box_metrics_remain_nullable_without_dropping_game(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            pd.DataFrame(
                {"game_id": [501.0, 501.0], "team_id": [17.0, 19.0]}
            ).to_parquet(paths["team_box_path"])
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        self.assertEqual(len(team_games), 2)
        advanced = [
            "possessions_est",
            "pace_est",
            "ortg_est",
            "drtg_est",
            "net_rating_est",
            "efg_pct",
            "opp_efg_pct",
            "tov_pct",
            "opp_tov_pct",
            "oreb_pct",
            "opp_oreb_pct",
            "ftr",
            "opp_ftr",
        ]
        self.assertTrue(team_games[advanced].isna().all().all())

    def test_zero_metric_denominators_return_null_instead_of_infinity(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            team_box = pd.read_parquet(paths["team_box_path"])
            metric_columns = [
                column
                for column in team_box.columns
                if column not in {"game_id", "team_id"}
            ]
            team_box[metric_columns] = 0
            team_box.to_parquet(paths["team_box_path"])
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        ratio_columns = [
            "ortg_est",
            "drtg_est",
            "net_rating_est",
            "efg_pct",
            "opp_efg_pct",
            "tov_pct",
            "opp_tov_pct",
            "oreb_pct",
            "opp_oreb_pct",
            "ftr",
            "opp_ftr",
        ]
        self.assertTrue(team_games[ratio_columns].isna().all().all())

    def test_writer_uses_the_configured_season_partition(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root, season=2030)
            paths = _write_source_fixture(source_root)
            schedule = pd.read_parquet(paths["schedule_path"])
            schedule["season"] = 2030
            schedule.to_parquet(paths["schedule_path"])
            history_path = source_root / "team_history.csv"
            pd.DataFrame(
                {
                    "season": [2030, 2030],
                    "sportsdataverse_team_id": [17, 19],
                    "franchise_id": ["las_vegas_aces", "chicago_sky"],
                }
            ).to_csv(history_path, index=False)
            build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    team_history_path=history_path,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )
            output_path = (
                source_root / "processed" / "season=2030" / "team_game.parquet"
            )

            self.assertTrue(output_path.is_file())
            written = pd.read_parquet(output_path)

        self.assertEqual(written["season"].tolist(), [2030, 2030])
        self.assertEqual(set(written["team_id"]), {"17", "19"})

    def test_multi_season_schedule_only_emits_the_configured_season(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root, season=2030)
            paths = _write_source_fixture(source_root)
            _append_game(
                paths,
                game_id=502.0,
                game_date="2030-06-01",
                home_score=75,
                away_score=76,
            )
            schedule = pd.read_parquet(paths["schedule_path"])
            schedule.loc[schedule["game_id"] == 502.0, "season"] = 2030
            schedule.to_parquet(paths["schedule_path"])
            history_path = source_root / "team_history.csv"
            pd.DataFrame(
                {
                    "season": [2030, 2030],
                    "sportsdataverse_team_id": [17, 19],
                    "franchise_id": ["las_vegas_aces", "chicago_sky"],
                }
            ).to_csv(history_path, index=False)
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    team_history_path=history_path,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        self.assertEqual(team_games["game_id"].tolist(), ["502", "502"])
        self.assertEqual(team_games["season"].tolist(), [2030, 2030])

    def test_regular_season_filter_keeps_std_and_cc_but_excludes_postseason(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root, games_per_team=2)
            paths = _write_source_fixture(source_root)
            _append_game(
                paths,
                game_id=502.0,
                game_date="2026-06-02",
                home_score=75,
                away_score=76,
            )
            _append_game(
                paths,
                game_id=503.0,
                game_date="2026-09-20",
                home_score=81,
                away_score=79,
            )
            _append_game(
                paths,
                game_id=504.0,
                game_date="2026-07-20",
                home_score=120,
                away_score=119,
            )
            schedule = pd.read_parquet(paths["schedule_path"])
            schedule.loc[
                schedule["game_id"] == 502.0, "type_abbreviation"
            ] = "CC"
            schedule.loc[
                schedule["game_id"] == 503.0, "season_type"
            ] = 3
            schedule.loc[
                schedule["game_id"] == 504.0, "type_abbreviation"
            ] = "ALLSTAR"
            schedule.to_parquet(paths["schedule_path"])
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        self.assertEqual(set(team_games["game_id"]), {"501", "502"})
        self.assertEqual(
            team_games.groupby("game_id").size().to_dict(), {"501": 2, "502": 2}
        )

    def test_full_std_schedule_excludes_an_extra_completed_cup_final(self) -> None:
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root, games_per_team=2)
            paths = _write_source_fixture(source_root)
            _append_game(
                paths,
                game_id=502.0,
                game_date="2026-06-02",
                home_score=75,
                away_score=76,
            )
            _append_game(
                paths,
                game_id=503.0,
                game_date="2026-06-03",
                home_score=81,
                away_score=79,
            )
            schedule = pd.read_parquet(paths["schedule_path"])
            schedule.loc[
                schedule["game_id"] == 503.0, "type_abbreviation"
            ] = "CC"
            schedule.to_parquet(paths["schedule_path"])

            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        self.assertEqual(set(team_games["game_id"]), {"501", "502"})
        self.assertEqual(len(team_games), 4)

    def test_output_contract_does_not_smear_optional_season_totals_across_games(self) -> None:
        from standings_playoff_forecast.config import load_season_config
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        expected_columns = [
            "season",
            "season_type",
            "game_id",
            "game_date",
            "season_game_number",
            "season_progress_pct",
            "team_id",
            "franchise_id",
            "team_abbreviation",
            "team_name",
            "opponent_id",
            "opponent_franchise_id",
            "opponent_abbreviation",
            "opponent_name",
            "home_away",
            "is_home",
            "win",
            "loss",
            "points_for",
            "points_against",
            "margin",
            "field_goals_made",
            "field_goals_attempted",
            "three_point_field_goals_made",
            "free_throws_made",
            "free_throws_attempted",
            "offensive_rebounds",
            "defensive_rebounds",
            "turnovers",
            "possessions_est",
            "pace_est",
            "ortg_est",
            "drtg_est",
            "net_rating_est",
            "efg_pct",
            "opp_efg_pct",
            "tov_pct",
            "opp_tov_pct",
            "oreb_pct",
            "opp_oreb_pct",
            "ftr",
            "opp_ftr",
            "rest_days",
            "back_to_back",
            "wins_to_date",
            "losses_to_date",
            "win_pct_to_date",
            "point_diff_to_date",
            "source_game_completed",
            "source_team_box_path",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            pbp_path = source_root / "team_totals_features_latest.csv"
            pd.DataFrame(
                {"team_id": [1611661319], "latest_season_net_rating": [99.0]}
            ).to_csv(pbp_path, index=False)
            sources = load_forecast_sources(
                cfg, **paths, pbp_team_features_path=pbp_path
            )
            team_games = build_team_game_layer(sources, cfg)

        self.assertIn("latest_season_net_rating", sources.pbp_team_features.columns)
        self.assertEqual(team_games.columns.tolist(), expected_columns)


if __name__ == "__main__":
    unittest.main()
