import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
SPORTSDV = load_module("fetch_wnba_sportsdataverse_2026", ROOT / "scripts" / "fetch_wnba_sportsdataverse_2026.py")


class SportsDataverse2026DownloadTest(unittest.TestCase):
    def test_build_file_list_2026_only_returns_11_expected_files(self):
        file_map = SPORTSDV.build_2026_file_list()

        self.assertEqual(len(file_map), 11)
        self.assertEqual(
            set(file_map.keys()),
            {
                "player_box_2026.parquet",
                "team_box_2026.parquet",
                "player_game_logs_2026.parquet",
                "player_season_stats_2026.parquet",
                "team_season_stats_2026.parquet",
                "standings_2026.parquet",
                "shots_2026.parquet",
                "game_rosters_2026.parquet",
                "wnba_pbp_2026.parquet",
                "espn_pbp_2026.parquet",
                "schedule_2026.parquet",
            },
        )

    def test_both_pbp_sources_are_present(self):
        file_map = SPORTSDV.build_2026_file_list()

        self.assertEqual(file_map["wnba_pbp_2026.parquet"]["source"], "WNBA.com")
        self.assertEqual(file_map["espn_pbp_2026.parquet"]["source"], "ESPN")
        self.assertIn("wnba_stats_pbp", file_map["wnba_pbp_2026.parquet"]["url"])
        self.assertIn("espn_wnba_pbp", file_map["espn_pbp_2026.parquet"]["url"])

    def test_default_output_paths_stay_inside_sportsdataverse_2026_tree(self):
        self.assertEqual(
            SPORTSDV.DATA_ROOT,
            Path("data/raw/sportsdataverse/wnba_2026"),
        )
        self.assertEqual(
            SPORTSDV.RUN_LOG_PATH,
            Path("data/raw/sportsdataverse/wnba_2026/run_logs/download_manifest_2026.json"),
        )

    def test_download_all_writes_parquet_files_and_stable_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "downloads"
            sample_df = pd.DataFrame([{"id": 1, "value": "ok"}])

            with patch.object(SPORTSDV.pd, "read_parquet", return_value=sample_df) as mock_read:
                manifest = SPORTSDV.download_all(
                    file_map=SPORTSDV.build_2026_file_list(),
                    data_root=data_root,
                    manifest_path=data_root / "run_logs" / "download_manifest_2026.json",
                )

            self.assertEqual(mock_read.call_count, 11)
            self.assertEqual(len(manifest["files"]), 11)
            self.assertTrue((data_root / "player_box_2026.parquet").exists())
            self.assertTrue((data_root / "espn_pbp_2026.parquet").exists())

            manifest_path = data_root / "run_logs" / "download_manifest_2026.json"
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["season"], "2026")
            self.assertEqual(len(saved_manifest["files"]), 11)
            self.assertNotIn("run_id", saved_manifest)
            self.assertNotIn("generated_at_utc", saved_manifest)

    def test_manifest_is_stable_across_reruns_when_downloaded_data_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "downloads"
            manifest_path = data_root / "run_logs" / "download_manifest_2026.json"
            sample_df = pd.DataFrame([{"id": 1, "value": "ok"}])

            with patch.object(SPORTSDV.pd, "read_parquet", return_value=sample_df):
                manifest_a = SPORTSDV.download_all(
                    file_map=SPORTSDV.build_2026_file_list(),
                    data_root=data_root,
                    manifest_path=manifest_path,
                )
                manifest_b = SPORTSDV.download_all(
                    file_map=SPORTSDV.build_2026_file_list(),
                    data_root=data_root,
                    manifest_path=manifest_path,
                )

            self.assertEqual(manifest_a, manifest_b)
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                manifest_a,
            )


if __name__ == "__main__":
    unittest.main()
