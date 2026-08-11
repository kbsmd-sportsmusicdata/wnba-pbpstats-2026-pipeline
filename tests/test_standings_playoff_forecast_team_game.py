import json
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
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
        "team_history_path": source_root / "team_history.csv",
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
                "opponent_team_id": 19.0,
                "team_home_away": "home",
                "team_score": 80,
                "opponent_team_score": 70,
                "team_winner": True,
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
                "opponent_team_id": 17.0,
                "team_home_away": "away",
                "team_score": 70,
                "opponent_team_score": 80,
                "team_winner": False,
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
    pd.DataFrame(
        {
            "season": [2026, 2026],
            "sportsdataverse_team_id": [17, 19],
            "franchise_id": ["las_vegas_aces", "chicago_sky"],
        }
    ).to_csv(paths["team_history_path"], index=False)
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
    home_rows = later_box["team_home_away"].eq("home")
    later_box.loc[home_rows, ["team_score", "opponent_team_score", "team_winner"]] = [
        home_score,
        away_score,
        home_score > away_score,
    ]
    later_box.loc[~home_rows, ["team_score", "opponent_team_score", "team_winner"]] = [
        away_score,
        home_score,
        away_score > home_score,
    ]
    pd.concat([team_box, later_box], ignore_index=True).to_parquet(paths["team_box_path"])


def _completed_schedule(*, completed: bool = True) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_id": "501",
                "season": 2026,
                "season_type": 2,
                "game_date": "2026-06-01",
                "status_type_completed": completed,
                "status_type_name": "STATUS_FINAL" if completed else "STATUS_SCHEDULED",
                "type_abbreviation": "STD",
                "home_id": "17",
                "away_id": "19",
            }
        ]
    )


def _reciprocal_team_games() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_id": "501",
                "game_date": "2026-06-01",
                "team_id": "17",
                "opponent_id": "19",
                "home_away": "home",
                "is_home": True,
                "win": 1,
                "loss": 0,
                "points_for": 80,
                "points_against": 70,
                "margin": 10,
            },
            {
                "game_id": "501",
                "game_date": "2026-06-01",
                "team_id": "19",
                "opponent_id": "17",
                "home_away": "away",
                "is_home": False,
                "win": 0,
                "loss": 1,
                "points_for": 70,
                "points_against": 80,
                "margin": -10,
            },
        ]
    )


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

            with self.assertWarnsRegex(
                RuntimeWarning, "Optional external standings are unavailable"
            ):
                sources = load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                )

        self.assertEqual(sources.schedule["game_id"].tolist(), ["101"])
        self.assertEqual(sources.team_box["game_id"].tolist(), ["101"])
        self.assertIsNone(sources.external_standings)
        self.assertIsNone(sources.external_standings_path)
        self.assertEqual(
            getattr(sources, "external_standings_load_status", None), "unavailable"
        )
        self.assertIsNone(sources.pbp_team_features)

    def test_invalid_external_standings_warns_and_returns_none(self) -> None:
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
            paths["external_standings_path"].write_text("not parquet", encoding="utf-8")

            with self.assertWarnsRegex(
                RuntimeWarning, "Optional external standings could not be read"
            ):
                sources = load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                )

        self.assertIsNone(sources.external_standings)
        self.assertEqual(
            sources.external_standings_path,
            paths["external_standings_path"],
        )
        self.assertEqual(
            getattr(sources, "external_standings_load_status", None), "unparseable"
        )

    def test_optional_pbpstats_sidecar_distinguishes_snapshot_from_save_upper_bound(self) -> None:
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
                getattr(sources, "external_standings_load_status", None), "loaded"
            )
            self.assertEqual(
                sources.pbp_team_features.attrs["pbpstats_snapshot_metadata"],
                {
                    "cutoff_safety_upper_bound": "2026-06-03T21:05:00+00:00",
                    "provenance_kind": "last_saved_at_utc_upper_bound",
                    "run_id": "20260603T210500Z",
                    "sidecar": str(features_path.with_suffix(".json")),
                },
            )

            features_path.with_suffix(".json").write_text(
                '{"metadata":{"snapshot_as_of":"2026-06-02T23:00:00+00:00",'
                '"last_saved_at_utc":"2026-06-03T21:05:00+00:00",'
                '"run_id":"20260603T210500Z","row_count":1},"rows":[]}',
                encoding="utf-8",
            )
            explicit = load_forecast_sources(
                cfg,
                **paths,
                pbp_team_features_path=features_path,
            )
            assert explicit.pbp_team_features is not None
            self.assertEqual(
                explicit.pbp_team_features.attrs["pbpstats_snapshot_metadata"],
                {
                    "snapshot_as_of": "2026-06-02T23:00:00+00:00",
                    "provenance_kind": "snapshot_as_of",
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


class CompletedGameLedgerValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cfg = _fixture_config(Path(self.temporary.name))

    def validate(self, schedule: pd.DataFrame, team_games: pd.DataFrame):
        from standings_playoff_forecast.team_game_layer import (
            validate_completed_game_ledger,
        )

        return validate_completed_game_ledger(
            schedule, team_games, self.cfg, cutoff="2026-06-01"
        )

    def test_valid_two_row_reciprocal_game_returns_frozen_result(self) -> None:
        result = self.validate(_completed_schedule(), _reciprocal_team_games())

        self.assertEqual(result.completed_game_count, 1)
        self.assertEqual(result.directional_row_count, 2)
        self.assertEqual(result.game_ids, ("501",))
        with self.assertRaises(FrozenInstanceError):
            result.completed_game_count = 2

    def test_valid_reciprocal_rows_do_not_require_unique_caller_index(self) -> None:
        rows = _reciprocal_team_games()
        rows.index = [0, 0]

        result = self.validate(_completed_schedule(), rows)

        self.assertEqual(result.directional_row_count, 2)

    def test_missing_reciprocal_row_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "completed game must have exactly two directional rows: 501"
        ):
            self.validate(_completed_schedule(), _reciprocal_team_games().iloc[:1])

    def test_mismatched_points_for_and_against_fails_closed(self) -> None:
        malformed = _reciprocal_team_games()
        malformed.loc[1, "points_against"] = 81

        with self.assertRaisesRegex(ValueError, "reciprocal points_for/points_against"):
            self.validate(_completed_schedule(), malformed)

    def test_mismatched_margins_fail_closed(self) -> None:
        malformed = _reciprocal_team_games()
        malformed.loc[1, "margin"] = -9

        with self.assertRaisesRegex(ValueError, "opposite nonzero margins"):
            self.validate(_completed_schedule(), malformed)

    def test_duplicate_directional_row_fails_closed(self) -> None:
        rows = _reciprocal_team_games()
        malformed = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)

        with self.assertRaisesRegex(
            ValueError, "duplicate directional team-game rows: 501/17"
        ):
            self.validate(_completed_schedule(), malformed)

    def test_uncompleted_schedule_game_is_excluded_from_expected_ledger(self) -> None:
        empty = _reciprocal_team_games().iloc[:0]
        result = self.validate(_completed_schedule(completed=False), empty)

        self.assertEqual(result.completed_game_count, 0)
        self.assertEqual(result.directional_row_count, 0)
        self.assertEqual(result.game_ids, ())

    def test_false_completion_tokens_never_enter_the_ledger(self) -> None:
        empty = _reciprocal_team_games().iloc[:0]
        for token in (False, 0, 0.0, "0", "false", "False", " FALSE "):
            with self.subTest(token=token):
                schedule = _completed_schedule()
                schedule["status_type_completed"] = schedule[
                    "status_type_completed"
                ].astype(object)
                schedule.loc[0, "status_type_completed"] = token

                result = self.validate(schedule, empty)

                self.assertEqual(result.game_ids, ())

    def test_true_completion_tokens_enter_the_ledger(self) -> None:
        for token in (True, 1, 1.0, "1", "true", "TRUE", " true "):
            with self.subTest(token=token):
                schedule = _completed_schedule()
                schedule["status_type_completed"] = schedule[
                    "status_type_completed"
                ].astype(object)
                schedule.loc[0, "status_type_completed"] = token

                result = self.validate(schedule, _reciprocal_team_games())

                self.assertEqual(result.game_ids, ("501",))

    def test_unknown_completion_tokens_fail_closed(self) -> None:
        for token in (2, -1, "complete", "", None):
            with self.subTest(token=token):
                schedule = _completed_schedule()
                schedule["status_type_completed"] = schedule[
                    "status_type_completed"
                ].astype(object)
                schedule.loc[0, "status_type_completed"] = token

                with self.assertRaisesRegex(
                    ValueError, "invalid status_type_completed values"
                ):
                    self.validate(schedule, _reciprocal_team_games())

    def test_ledger_game_ids_must_exactly_match_completed_schedule_ids(self) -> None:
        malformed = _reciprocal_team_games().assign(game_id="other")

        with self.assertRaisesRegex(
            ValueError, "completed game-id parity failed.*missing=501.*unexpected=other"
        ):
            self.validate(_completed_schedule(), malformed)

    def test_directional_participants_must_match_schedule_home_and_away(self) -> None:
        malformed = _reciprocal_team_games()
        malformed.loc[0, ["team_id", "opponent_id"]] = ["19", "17"]
        malformed.loc[1, ["team_id", "opponent_id"]] = ["17", "19"]

        with self.assertRaisesRegex(
            ValueError, "directional participants do not match schedule: 501"
        ):
            self.validate(_completed_schedule(), malformed)

    def test_directional_home_away_must_match_schedule(self) -> None:
        malformed = _reciprocal_team_games()
        malformed[["home_away", "is_home"]] = [["away", False], ["home", True]]

        with self.assertRaisesRegex(
            ValueError, "directional participants do not match schedule: 501"
        ):
            self.validate(_completed_schedule(), malformed)

    def test_is_home_must_agree_with_home_away(self) -> None:
        malformed = _reciprocal_team_games()
        malformed.loc[0, "is_home"] = False

        with self.assertRaisesRegex(
            ValueError, "directional participants do not match schedule: 501"
        ):
            self.validate(_completed_schedule(), malformed)

    def test_directional_game_date_must_match_schedule(self) -> None:
        malformed = _reciprocal_team_games()
        malformed.loc[1, "game_date"] = "2026-06-02"

        with self.assertRaisesRegex(
            ValueError, "directional game_date does not match schedule: 501"
        ):
            self.validate(_completed_schedule(), malformed)

    def test_reciprocal_rows_must_have_one_winner_and_one_loser(self) -> None:
        malformed = _reciprocal_team_games()
        malformed.loc[1, ["win", "loss"]] = [1, 0]

        with self.assertRaisesRegex(ValueError, "one winner and one loser: 501"):
            self.validate(_completed_schedule(), malformed)

    def test_swapped_wins_and_losses_must_match_score_sign(self) -> None:
        malformed = _reciprocal_team_games()
        malformed[["win", "loss"]] = [[0, 1], [1, 0]]

        with self.assertRaisesRegex(
            ValueError, "completed game result does not match score margin: 501"
        ):
            self.validate(_completed_schedule(), malformed)

    def test_scores_must_be_numeric(self) -> None:
        malformed = _reciprocal_team_games()
        malformed["points_for"] = malformed["points_for"].astype(object)
        malformed.loc[0, "points_for"] = "not-a-score"

        with self.assertRaisesRegex(ValueError, "numeric scores: 501"):
            self.validate(_completed_schedule(), malformed)

    def test_margins_must_be_numeric_and_finite(self) -> None:
        for value in ("not-a-margin", float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                malformed = _reciprocal_team_games()
                malformed["margin"] = malformed["margin"].astype(object)
                malformed.loc[0, "margin"] = value

                with self.assertRaisesRegex(ValueError, "numeric margins: 501"):
                    self.validate(_completed_schedule(), malformed)


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

    def test_completed_game_results_come_from_team_box_not_schedule_scores(self) -> None:
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            schedule = pd.read_parquet(paths["schedule_path"])
            schedule.loc[0, ["home_score", "away_score"]] = [10, 120]
            schedule.to_parquet(paths["schedule_path"])
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        home = team_games.loc[team_games["is_home"]].iloc[0]
        away = team_games.loc[~team_games["is_home"]].iloc[0]
        self.assertEqual(
            home[["win", "loss", "points_for", "points_against", "margin"]].tolist(),
            [1, 0, 80, 70, 10],
        )
        self.assertEqual(
            away[["win", "loss", "points_for", "points_against", "margin"]].tolist(),
            [0, 1, 70, 80, -10],
        )

    def test_completed_game_build_does_not_depend_on_external_standings(self) -> None:
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            paths["external_standings_path"].unlink()
            with self.assertWarnsRegex(RuntimeWarning, "unavailable"):
                sources = load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                )
            team_games = build_team_game_layer(sources, cfg)

        self.assertEqual(len(team_games), 2)

    def test_false_string_completion_is_excluded_by_builder(self) -> None:
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            schedule = pd.read_parquet(paths["schedule_path"])
            schedule["status_type_completed"] = "False"
            schedule.to_parquet(paths["schedule_path"])
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        self.assertTrue(team_games.empty)

    def test_boolean_team_box_scores_fail_before_numeric_coercion(self) -> None:
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            team_box = pd.read_parquet(paths["team_box_path"])
            team_box["team_score"] = [True, False]
            team_box["opponent_team_score"] = [False, True]
            team_box.to_parquet(paths["team_box_path"])
            sources = load_forecast_sources(
                cfg,
                **paths,
                pbp_team_features_path=source_root / "not-present.csv",
            )

            with self.assertRaisesRegex(
                ValueError, "team_box scores must not be boolean"
            ):
                build_team_game_layer(sources, cfg)

    def test_active_team_history_universe_must_match_qualified_schedule(self) -> None:
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            history_path = source_root / "team_history.csv"
            pd.DataFrame(
                {
                    "season": [2026, 2026],
                    "sportsdataverse_team_id": [17, 20],
                    "franchise_id": ["las_vegas_aces", "atlanta_dream"],
                }
            ).to_csv(history_path, index=False)
            sources = load_forecast_sources(
                cfg,
                **paths,
                pbp_team_features_path=source_root / "not-present.csv",
            )

            with self.assertRaisesRegex(
                ValueError,
                "active team-history universe does not match qualified schedule.*schedule_only=19.*history_only=20",
            ):
                build_team_game_layer(sources, cfg)

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

    def test_active_franchise_ids_are_trimmed_and_must_not_be_blank(self) -> None:
        """Catches whitespace-only identities and unnormalized stable IDs."""
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            history = pd.read_csv(paths["team_history_path"])
            history.loc[0, "franchise_id"] = "  las_vegas_aces  "
            history.to_csv(paths["team_history_path"], index=False)
            result = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )
            self.assertEqual(
                result.loc[result["team_id"].eq("17"), "franchise_id"].iloc[0],
                "las_vegas_aces",
            )

            for invalid in ("   ", None):
                with self.subTest(invalid=invalid):
                    history.loc[0, "franchise_id"] = invalid
                    history.to_csv(paths["team_history_path"], index=False)
                    with self.assertRaisesRegex(
                        ValueError, "invalid active rows for season 2026"
                    ):
                        build_team_game_layer(
                            load_forecast_sources(
                                cfg,
                                **paths,
                                pbp_team_features_path=source_root / "not-present.csv",
                            ),
                            cfg,
                        )

    def test_active_season_rejects_duplicate_franchise_id(self) -> None:
        """Catches two active teams mapping to one canonical franchise."""
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            history = pd.read_csv(paths["team_history_path"])
            history["franchise_id"] = "same_franchise"
            history.to_csv(paths["team_history_path"], index=False)

            with self.assertRaisesRegex(
                ValueError, "duplicate active franchise mappings.*same_franchise"
            ):
                build_team_game_layer(
                    load_forecast_sources(
                        cfg,
                        **paths,
                        pbp_team_features_path=source_root / "not-present.csv",
                    ),
                    cfg,
                )

    def test_franchise_id_may_be_reused_across_seasons(self) -> None:
        """Protects historical continuity without weakening active-season uniqueness."""
        from standings_playoff_forecast.data_sources import load_forecast_sources
        from standings_playoff_forecast.team_game_layer import build_team_game_layer

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            cfg = _fixture_config(source_root)
            paths = _write_source_fixture(source_root)
            history = pd.read_csv(paths["team_history_path"])
            prior = history.assign(
                season=2025,
                sportsdataverse_team_id=[117, 119],
            )
            pd.concat([prior, history], ignore_index=True).to_csv(
                paths["team_history_path"], index=False
            )

            result = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
                    pbp_team_features_path=source_root / "not-present.csv",
                ),
                cfg,
            )

        self.assertEqual(set(result["franchise_id"]), {"las_vegas_aces", "chicago_sky"})

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
            team_box = pd.read_parquet(paths["team_box_path"])
            team_box[
                [
                    "game_id",
                    "team_id",
                    "opponent_team_id",
                    "team_home_away",
                    "team_score",
                    "opponent_team_score",
                    "team_winner",
                ]
            ].to_parquet(paths["team_box_path"])
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
                "field_goals_made",
                "field_goals_attempted",
                "three_point_field_goals_made",
                "free_throws_made",
                "free_throws_attempted",
                "offensive_rebounds",
                "defensive_rebounds",
                "turnovers",
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
            paths["team_history_path"] = history_path
            build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
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
            paths["team_history_path"] = history_path
            team_games = build_team_game_layer(
                load_forecast_sources(
                    cfg,
                    **paths,
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
