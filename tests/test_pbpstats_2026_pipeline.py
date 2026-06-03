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
                    {"player_id_clean": "7", "_row_content_hash": "hash-1"},
                    {"player_id_clean": "12", "_row_content_hash": "hash-2"},
                ]
            )
            before, added, after = PULL_CLEAN.append_unique_csv(path, initial)
            self.assertEqual((before, added, after), (0, 2, 2))

            rerun = pd.DataFrame(
                [
                    {"player_id_clean": "12", "_row_content_hash": "hash-2"},
                    {"player_id_clean": "15", "_row_content_hash": "hash-3"},
                ]
            )
            before, added, after = PULL_CLEAN.append_unique_csv(path, rerun)
            self.assertEqual((before, added, after), (2, 1, 3))

            written = pd.read_csv(path)
            self.assertEqual(len(written), 3)
            self.assertEqual(set(written["_row_content_hash"]), {"hash-1", "hash-2", "hash-3"})

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


class FeaturesHelpersTest(unittest.TestCase):
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
