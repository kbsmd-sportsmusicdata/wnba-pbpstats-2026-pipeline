import contextlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


@contextlib.contextmanager
def fake_urlopen(*args, **kwargs):
    """Stands in for urllib.request.urlopen so no test performs a real download."""

    class _Response:
        @staticmethod
        def read():
            return b"parquet-bytes"

    yield _Response()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
SPORTSDV = load_module("fetch_wnba_sportsdataverse_2026", ROOT / "scripts" / "fetch_wnba_sportsdataverse_2026.py")


class SportsDataverse2026DownloadTest(unittest.TestCase):
    def test_build_file_list_2026_only_returns_expected_files(self):
        file_map = SPORTSDV.build_2026_file_list()

        self.assertEqual(len(file_map), 15)
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
                "wnba_stats_standings_2026.parquet",
                "wnba_possessions_2026.parquet",
                "wnba_lineups_2026.parquet",
                "wnba_player_impact_2026.parquet",
            },
        )

    def test_possession_and_impact_sources_point_at_their_releases(self):
        file_map = SPORTSDV.build_2026_file_list()

        self.assertIn(
            "wnba_stats_possessions/wnba_possessions_2026.parquet",
            file_map["wnba_possessions_2026.parquet"]["url"],
        )
        self.assertIn(
            "wnba_stats_game_lineups/wnba_lineups_2026.parquet",
            file_map["wnba_lineups_2026.parquet"]["url"],
        )
        self.assertIn(
            "wnba_player_impact/wnba_player_impact_2026.parquet",
            file_map["wnba_player_impact_2026.parquet"]["url"],
        )

    def test_every_url_is_a_sportsdataverse_release_download(self):
        for filename, info in SPORTSDV.build_2026_file_list().items():
            self.assertTrue(info["url"].startswith(SPORTSDV.BASE_RELEASE_URL), filename)

    def test_both_pbp_sources_are_present(self):
        file_map = SPORTSDV.build_2026_file_list()

        self.assertEqual(file_map["wnba_pbp_2026.parquet"]["source"], "WNBA.com")
        self.assertEqual(file_map["espn_pbp_2026.parquet"]["source"], "ESPN")
        self.assertIn("wnba_stats_pbp", file_map["wnba_pbp_2026.parquet"]["url"])
        self.assertIn("espn_wnba_pbp", file_map["espn_pbp_2026.parquet"]["url"])

    def test_wide_wnba_stats_standings_is_downloaded_but_not_adapted_here(self):
        file_map = SPORTSDV.build_2026_file_list()

        source = file_map["wnba_stats_standings_2026.parquet"]
        self.assertEqual(source["source"], "WNBA.com")
        self.assertIn("wnba_stats_standings", source["url"])

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

            with patch.object(SPORTSDV.urllib.request, "urlopen", fake_urlopen), patch.object(
                SPORTSDV.pd, "read_parquet", return_value=sample_df
            ) as mock_read:
                manifest = SPORTSDV.download_all(
                    file_map=SPORTSDV.build_2026_file_list(),
                    data_root=data_root,
                    manifest_path=data_root / "run_logs" / "download_manifest_2026.json",
                )

            self.assertEqual(mock_read.call_count, 15)
            self.assertEqual(len(manifest["files"]), 15)
            self.assertTrue((data_root / "player_box_2026.parquet").exists())
            self.assertTrue((data_root / "espn_pbp_2026.parquet").exists())
            self.assertTrue((data_root / "wnba_stats_standings_2026.parquet").exists())

            manifest_path = data_root / "run_logs" / "download_manifest_2026.json"
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["season"], "2026")
            self.assertEqual(len(saved_manifest["files"]), 15)
            self.assertEqual(saved_manifest["failed_count"], 0)
            self.assertNotIn("run_id", saved_manifest)
            self.assertNotIn("generated_at_utc", saved_manifest)

    def test_manifest_is_stable_across_reruns_when_downloaded_data_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "downloads"
            manifest_path = data_root / "run_logs" / "download_manifest_2026.json"
            sample_df = pd.DataFrame([{"id": 1, "value": "ok"}])

            with patch.object(SPORTSDV.urllib.request, "urlopen", fake_urlopen), patch.object(
                SPORTSDV.pd, "read_parquet", return_value=sample_df
            ):
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


class DownloadResilienceTest(unittest.TestCase):
    """A scheduled pull must survive a flaky release CDN without losing good files."""

    def test_transient_failure_is_retried_then_succeeds(self):
        sample_df = pd.DataFrame([{"id": 1}])
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("502 Bad Gateway")
            return sample_df

        with patch.object(SPORTSDV.pd, "read_parquet", side_effect=flaky), patch.object(
            SPORTSDV.urllib.request, "urlopen", fake_urlopen
        ), patch.object(SPORTSDV.time, "sleep"):
            out = SPORTSDV.download_parquet_nocache("https://example.test/x.parquet")

        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(out), 1)

    def test_exhausted_retries_raise(self):
        with patch.object(SPORTSDV.pd, "read_parquet", side_effect=OSError("502")), patch.object(
            SPORTSDV.urllib.request, "urlopen", fake_urlopen
        ), patch.object(SPORTSDV.time, "sleep"):
            with self.assertRaises(RuntimeError):
                SPORTSDV.download_parquet_nocache("https://example.test/x.parquet", attempts=2)

    def test_one_bad_file_does_not_lose_the_others(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "downloads"
            sample_df = pd.DataFrame([{"id": 1}])

            file_map = {
                "good_2026.parquet": {"url": "https://example.test/good", "size_note": "-", "source": "T"},
                "bad_2026.parquet": {"url": "https://example.test/bad", "size_note": "-", "source": "T"},
            }

            def fake_download(url, **kwargs):
                if url.endswith("bad"):
                    raise RuntimeError("release unavailable")
                return sample_df

            with patch.object(SPORTSDV, "download_parquet_nocache", side_effect=fake_download):
                manifest = SPORTSDV.download_all(
                    file_map=file_map,
                    data_root=data_root,
                    manifest_path=data_root / "run_logs" / "m.json",
                )

            self.assertEqual(manifest["failed_count"], 1)
            self.assertEqual(manifest["failed_files"], ["bad_2026.parquet"])
            self.assertTrue((data_root / "good_2026.parquet").exists())
            self.assertFalse((data_root / "bad_2026.parquet").exists())
            failed = [f for f in manifest["files"] if not f.get("success")][0]
            self.assertIn("release unavailable", failed["error"])


if __name__ == "__main__":
    unittest.main()
