import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
PULL_CLEAN = load_module("pbpstats_2026_pull_clean", ROOT / "scripts" / "pbpstats_2026_pull_clean.py")
FEATURES = load_module("pbpstats_2026_features", ROOT / "scripts" / "pbpstats_2026_features.py")


class PullCleanHelpersTest(unittest.TestCase):
    def test_raw_hash_uses_stable_business_row_only(self):
        row = {"PlayerId": "42", "PlayerName": "Example Player", "PTS": 12}

        hash_a = PULL_CLEAN.build_raw_row_hash(
            row,
            dataset="player_totals",
            season="2026",
            season_type="Regular Season",
        )
        hash_b = PULL_CLEAN.build_raw_row_hash(
            row,
            dataset="player_totals",
            season="2026",
            season_type="Regular Season",
        )

        self.assertEqual(hash_a, hash_b)

    def test_nonvolatile_row_hash_ignores_run_metadata(self):
        row_a = {
            "player_id_clean": "7",
            "shotquality_pbp": 0.55,
            "_run_id": "run-a",
            "_fetched_at_utc": "2026-06-02T00:00:00+00:00",
            "_row_content_hash": "ignore-me",
        }
        row_b = {
            "player_id_clean": "7",
            "shotquality_pbp": 0.55,
            "_run_id": "run-b",
            "_fetched_at_utc": "2026-06-03T00:00:00+00:00",
            "_row_content_hash": "different",
        }

        self.assertEqual(
            PULL_CLEAN.nonvolatile_row_hash(row_a),
            PULL_CLEAN.nonvolatile_row_hash(row_b),
        )

    def test_append_unique_csv_adds_only_new_hashes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "master.csv"
            initial = pd.DataFrame(
                [
                    {"player_id_clean": "7", "_row_content_hash": "a" * 64},
                    {"player_id_clean": "12", "_row_content_hash": "b" * 64},
                ]
            )
            before, added, after = PULL_CLEAN.append_unique_csv(path, initial)
            self.assertEqual((before, added, after), (0, 2, 2))

            rerun = pd.DataFrame(
                [
                    {"player_id_clean": "12", "_row_content_hash": "b" * 64},
                    {"player_id_clean": "15", "_row_content_hash": "c" * 64},
                ]
            )
            before, added, after = PULL_CLEAN.append_unique_csv(path, rerun)
            self.assertEqual((before, added, after), (2, 1, 3))

            written = pd.read_csv(path)
            self.assertEqual(len(written), 3)
            self.assertEqual(set(written["_row_content_hash"]), {"a" * 64, "b" * 64, "c" * 64})

    def test_append_unique_csv_preserves_hash_column_when_new_columns_are_reordered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "master.csv"
            initial = pd.DataFrame(
                [
                    {"team_id_clean": "A", "_fetched_at_utc": "t1", "_row_content_hash": "a" * 64},
                ]
            )
            initial.to_csv(path, index=False)

            rerun = pd.DataFrame(
                [
                    {"_row_content_hash": "b" * 64, "team_id_clean": "B", "_fetched_at_utc": "t2"},
                ],
                columns=["_row_content_hash", "team_id_clean", "_fetched_at_utc"],
            )

            before, added, after = PULL_CLEAN.append_unique_csv(path, rerun)

            self.assertEqual((before, added, after), (1, 1, 2))
            written = pd.read_csv(path)
            self.assertEqual(
                list(written["_row_content_hash"]),
                ["a" * 64, "b" * 64],
            )

    def test_append_unique_csv_drops_existing_rows_with_invalid_hash_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "master.csv"
            path.write_text(
                "team_id_clean,_row_content_hash\n"
                "A,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "B,2026-06-03T21:02:35+00:00\n",
                encoding="utf-8",
            )

            rerun = pd.DataFrame(
                [
                    {"team_id_clean": "B", "_row_content_hash": "b" * 64},
                ]
            )

            before, added, after = PULL_CLEAN.append_unique_csv(path, rerun)

            self.assertEqual((before, added, after), (1, 1, 2))
            written = pd.read_csv(path)
            self.assertEqual(
                list(written["_row_content_hash"]),
                ["a" * 64, "b" * 64],
            )

    def test_clean_column_names_normalizes_shotquality_columns(self):
        raw = pd.DataFrame(
            [
                {
                    "Shot Quality": 0.51,
                    "Expected ShotQuality EFG": 0.49,
                    "PlayerId": "42",
                }
            ]
        )

        cleaned = PULL_CLEAN.clean_column_names(raw)

        self.assertIn("shotquality_pbp", cleaned.columns)
        self.assertIn("shotquality_pbp_expected_efg", cleaned.columns)
        self.assertIn("player_id", cleaned.columns)

    def test_clean_raw_df_hash_is_stable_across_reruns(self):
        raw_a = pd.DataFrame(
            [
                {
                    "PlayerId": "42",
                    "PlayerName": "Example Player",
                    "Shot Quality": 0.51,
                    "_run_id": "run-a",
                    "_fetched_at_utc": "2026-06-02T00:00:00+00:00",
                    "_row_content_hash": "ignore-a",
                }
            ]
        )
        raw_b = pd.DataFrame(
            [
                {
                    "PlayerId": "42",
                    "PlayerName": "Example Player",
                    "Shot Quality": 0.51,
                    "_run_id": "run-b",
                    "_fetched_at_utc": "2026-06-03T00:00:00+00:00",
                    "_row_content_hash": "ignore-b",
                }
            ]
        )

        clean_a = PULL_CLEAN.clean_raw_df(raw_a, "player_totals")
        clean_b = PULL_CLEAN.clean_raw_df(raw_b, "player_totals")

        self.assertEqual(
            clean_a.loc[0, "_row_content_hash"],
            clean_b.loc[0, "_row_content_hash"],
        )

    def test_annotate_raw_rows_ignores_attached_metadata_in_hash(self):
        rows = [{"PlayerId": "42", "PlayerName": "Example Player", "PTS": 12}]

        df_a = PULL_CLEAN.annotate_raw_rows(
            rows,
            dataset="player_totals",
            endpoint="/get-totals/wnba",
            params={"Season": "2026", "Type": "Player"},
            season="2026",
            season_type="Regular Season",
        )
        df_b = PULL_CLEAN.annotate_raw_rows(
            rows,
            dataset="player_totals",
            endpoint="/get-totals/wnba",
            params={"Season": "2026", "Type": "Player"},
            season="2026",
            season_type="Regular Season",
        )

        df_a["_source_response_keys"] = '["multi_row_table_data"]'
        df_b["_source_response_keys"] = '["multi_row_table_data","single_row_table_data"]'
        df_a["_single_row_table_data_json"] = '{"Totals": 100}'
        df_b["_single_row_table_data_json"] = '{"Totals": 105}'

        self.assertEqual(
            df_a.loc[0, "_row_content_hash"],
            df_b.loc[0, "_row_content_hash"],
        )

    def test_clean_raw_df_ignores_single_row_totals_summary_in_hash(self):
        raw_a = pd.DataFrame(
            [
                {
                    "PlayerId": "42",
                    "PlayerName": "Example Player",
                    "FGA": 10,
                    "FGM": 5,
                    "PTS": 12,
                    "_single_row_table_data_json": '{"Totals": 100}',
                }
            ]
        )
        raw_b = pd.DataFrame(
            [
                {
                    "PlayerId": "42",
                    "PlayerName": "Example Player",
                    "FGA": 10,
                    "FGM": 5,
                    "PTS": 12,
                    "_single_row_table_data_json": '{"Totals": 105}',
                }
            ]
        )

        clean_a = PULL_CLEAN.clean_raw_df(raw_a, "player_totals")
        clean_b = PULL_CLEAN.clean_raw_df(raw_b, "player_totals")

        self.assertEqual(
            clean_a.loc[0, "_row_content_hash"],
            clean_b.loc[0, "_row_content_hash"],
        )

    def test_directory_raw_hash_is_stable_across_reruns(self):
        rows = [{"id": 1611661330, "text": "ATL"}]
        df_a = PULL_CLEAN.annotate_raw_rows(
            rows,
            dataset="teams_directory",
            endpoint="/get-teams/wnba",
            params={},
            season=None,
            season_type=None,
        )
        df_b = PULL_CLEAN.annotate_raw_rows(
            rows,
            dataset="teams_directory",
            endpoint="/get-teams/wnba",
            params={},
            season=None,
            season_type=None,
        )

        df_a["_source_response_keys"] = '["teams"]'
        df_b["_source_response_keys"] = '["teams","meta"]'

        self.assertEqual(
            df_a.loc[0, "_row_content_hash"],
            df_b.loc[0, "_row_content_hash"],
        )


class FeaturesHelpersTest(unittest.TestCase):
    def test_feature_append_unique_csv_handles_short_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "player_features_master.csv"
            path.write_text(
                "entity_id_feature,specialized_shooter_label,_feature_run_id,_featured_at_utc,_row_content_hash\n"
                "100,Valid Shooter,run-a,2026-06-03T21:02:36+00:00," + ("a" * 64) + "\n"
                "101,run-b,2026-06-03T21:03:17+00:00," + ("b" * 64) + "\n",
                encoding="utf-8",
            )

            rerun = pd.DataFrame(
                [
                    {
                        "entity_id_feature": "101",
                        "specialized_shooter_label": "Valid Shooter",
                        "_feature_run_id": "run-b",
                        "_featured_at_utc": "2026-06-03T21:03:17+00:00",
                        "_row_content_hash": "b" * 64,
                    }
                ]
            )

            before, added, after = FEATURES.append_unique_csv(path, rerun)

            self.assertEqual((before, added, after), (1, 1, 2))
            written = pd.read_csv(path)
            self.assertEqual(
                list(written["_row_content_hash"]),
                ["a" * 64, "b" * 64],
            )

    def test_feature_hash_ignores_feature_metadata(self):
        row_a = {
            "entity_id_feature": "ATL",
            "efg_pct_feature": 0.56,
            "_feature_run_id": "run-a",
            "_featured_at_utc": "2026-06-02T00:00:00+00:00",
        }
        row_b = {
            "entity_id_feature": "ATL",
            "efg_pct_feature": 0.56,
            "_feature_run_id": "run-b",
            "_featured_at_utc": "2026-06-03T00:00:00+00:00",
        }

        self.assertEqual(
            FEATURES.nonvolatile_row_hash(row_a),
            FEATURES.nonvolatile_row_hash(row_b),
        )

    def test_add_shotquality_pbp_features_creates_expected_columns(self):
        df = pd.DataFrame(
            [
                {
                    "efg_pct_feature": 0.58,
                    "shotquality_pbp_expected_efg": 0.53,
                }
            ]
        )

        result = FEATURES.add_shotquality_pbp_features(df)

        self.assertIn("shotquality_pbp_feature", result.columns)
        self.assertIn("shot_making_over_shotquality_pbp", result.columns)
        self.assertAlmostEqual(result.loc[0, "shotquality_pbp_feature"], 0.53)
        self.assertAlmostEqual(result.loc[0, "shot_making_over_shotquality_pbp"], 0.05)

    def test_load_latest_clean_does_not_create_duplicate_context_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "player_totals_clean_latest.csv"
            pd.DataFrame(
                [
                    {
                        "player_id_clean": "42",
                        "player_name_clean": "Example Player",
                        "season": "2026",
                        "season_type": "Regular Season",
                        "league": "wnba",
                        "shotquality_pbp_avg": 0.51,
                    }
                ]
            ).to_csv(path, index=False)

            loaded = FEATURES.load_latest_clean(path, "player")

            self.assertFalse(loaded.columns.duplicated().any())
            self.assertEqual(list(loaded.columns).count("season"), 1)
            self.assertEqual(list(loaded.columns).count("season_type"), 1)
            self.assertEqual(list(loaded.columns).count("league"), 1)

    def test_load_latest_clean_drops_prior_stage_hash_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "player_totals_clean_latest.csv"
            pd.DataFrame(
                [
                    {
                        "player_id_clean": "42",
                        "player_name_clean": "Example Player",
                        "row_content_hash": "legacy-hash",
                        "_row_content_hash": "current-hash",
                        "run_id": "legacy-run",
                        "_clean_run_id": "clean-run",
                    }
                ]
            ).to_csv(path, index=False)

            loaded = FEATURES.load_latest_clean(path, "player")

            self.assertNotIn("row_content_hash", loaded.columns)
            self.assertNotIn("_row_content_hash", loaded.columns)
            self.assertNotIn("run_id", loaded.columns)
            self.assertNotIn("_clean_run_id", loaded.columns)

    def test_feature_hash_ignores_clean_totals_summary_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path_a = Path(tmpdir) / "player_totals_clean_latest_a.csv"
            path_b = Path(tmpdir) / "player_totals_clean_latest_b.csv"

            base_row = {
                "player_id_clean": "42",
                "player_name_clean": "Example Player",
                "fga": 10,
                "fgm": 5,
                "pts": 12,
                "fta": 2,
                "fg3a": 3,
                "fg3m": 1,
                "at_rim_fga": 4,
                "at_rim_fgm": 3,
                "short_mid_range_fga": 2,
                "short_mid_range_fgm": 1,
                "long_mid_range_fga": 1,
                "long_mid_range_fgm": 0,
                "corner3_fga": 1,
                "corner3_fgm": 0,
                "arc3_fga": 2,
                "arc3_fgm": 1,
                "shotquality_pbp_avg": 0.52,
            }

            row_a = dict(base_row)
            row_a["single_row_table_data_json"] = '{"Totals": 100}'
            row_b = dict(base_row)
            row_b["single_row_table_data_json"] = '{"Totals": 105}'

            pd.DataFrame([row_a]).to_csv(path_a, index=False)
            pd.DataFrame([row_b]).to_csv(path_b, index=False)

            feature_a = FEATURES.add_features(FEATURES.load_latest_clean(path_a, "player"), "player")
            feature_b = FEATURES.add_features(FEATURES.load_latest_clean(path_b, "player"), "player")

            self.assertEqual(
                feature_a.loc[0, "_row_content_hash"],
                feature_b.loc[0, "_row_content_hash"],
            )


if __name__ == "__main__":
    unittest.main()
