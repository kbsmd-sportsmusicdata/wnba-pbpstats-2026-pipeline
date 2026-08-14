"""
fetch_wnba_sportsdataverse_2026.py

Non-interactive 2026 WNBA parquet downloader for SportsDataverse GitHub releases.
This script is intended for local runs and GitHub Actions.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict
import urllib.request

import pandas as pd

SEASON = "2026"
BASE_RELEASE_URL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
DATA_ROOT = Path(os.getenv("SPORTSDATAVERSE_WNBA_2026_DATA_ROOT", "data/raw/sportsdataverse/wnba_2026"))
RUN_LOG_PATH = DATA_ROOT / "run_logs" / "download_manifest_2026.json"
MAX_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0


def espn(tag: str, filename: str) -> str:
    return f"{BASE_RELEASE_URL}/{tag}/{filename}"


def wnba(tag: str, filename: str) -> str:
    return f"{BASE_RELEASE_URL}/{tag}/{filename}"


def build_2026_file_list() -> Dict[str, Dict[str, str]]:
    year = SEASON
    return {
        f"player_box_{year}.parquet": {
            "url": espn("espn_wnba_player_boxscores", f"player_box_{year}.parquet"),
            "size_note": "~50-170 KB",
            "source": "ESPN",
        },
        f"team_box_{year}.parquet": {
            "url": espn("espn_wnba_team_boxscores", f"team_box_{year}.parquet"),
            "size_note": "~32-54 KB",
            "source": "ESPN",
        },
        f"player_game_logs_{year}.parquet": {
            "url": wnba("wnba_stats_player_game_logs", f"player_game_logs_{year}.parquet"),
            "size_note": "~22-126 KB",
            "source": "WNBA.com",
        },
        f"player_season_stats_{year}.parquet": {
            "url": espn("espn_wnba_player_season_stats", f"player_season_stats_{year}.parquet"),
            "size_note": "~57-61 KB",
            "source": "ESPN",
        },
        f"team_season_stats_{year}.parquet": {
            "url": espn("espn_wnba_team_season_stats", f"team_season_stats_{year}.parquet"),
            "size_note": "~16-18 KB",
            "source": "ESPN",
        },
        # ESPN WNBA Standings
        f"standings_{year}.parquet": {
            "url": espn("espn_wnba_standings", f"standings_{year}.parquet"),
            "size_note": "~15-16 KB",
            "source": "ESPN",
        },
        # WNBA.com Stats Standings
        f"wnba_stats_standings_{year}.parquet": {
            "url": wnba("wnba_stats_standings", f"standings_{year}.parquet"),
            "size_note": "~35 KB",
            "source": "WNBA.com",
        },
        f"shots_{year}.parquet": {
            "url": espn("espn_wnba_shots", f"shots_{year}.parquet"),
            "size_note": "~58-463 KB",
            "source": "ESPN",
        },
        f"game_rosters_{year}.parquet": {
            "url": espn("espn_wnba_game_rosters", f"game_rosters_{year}.parquet"),
            "size_note": "~32-70 KB",
            "source": "ESPN",
        },
        f"wnba_pbp_{year}.parquet": {
            "url": wnba("wnba_stats_pbp", f"play_by_play_{year}.parquet"),
            "size_note": "~367 KB",
            "source": "WNBA.com",
        },
        f"espn_pbp_{year}.parquet": {
            "url": espn("espn_wnba_pbp", f"play_by_play_{year}.parquet"),
            "size_note": "~633 KB",
            "source": "ESPN",
        },
        f"schedule_{year}.parquet": {
            "url": espn("espn_wnba_schedules", f"wnba_schedule_{year}.parquet"),
            "size_note": "~91-97 KB",
            "source": "ESPN",
        },
        # Possession-level lineups: the validated stint data that real RAPM, bench net
        # rating and possession-based clutch ratings all require.
        f"wnba_possessions_{year}.parquet": {
            "url": wnba("wnba_stats_possessions", f"wnba_possessions_{year}.parquet"),
            "size_note": "~384 KB",
            "source": "WNBA.com",
        },
        f"wnba_lineups_{year}.parquet": {
            "url": wnba("wnba_stats_game_lineups", f"wnba_lineups_{year}.parquet"),
            "size_note": "~129 KB",
            "source": "WNBA.com",
        },
        # Pre-computed impact metrics (RAPM, SPM, BPM, WAR, DARKO projections).
        f"wnba_player_impact_{year}.parquet": {
            "url": wnba("wnba_player_impact", f"wnba_player_impact_{year}.parquet"),
            "size_note": "~42 KB",
            "source": "SportsDataverse",
        },
    }


def ensure_dirs(data_root: Path, manifest_path: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(stable_json_dumps(payload), encoding="utf-8")
    tmp_path.replace(path)


def download_parquet_nocache(url: str, *, attempts: int = MAX_ATTEMPTS) -> pd.DataFrame:
    """Fetches a parquet file directly using HTTP headers to bypass CDN/client caching.

    The release CDN returns transient 5xx responses often enough to break an unattended
    run, so failures are retried with exponential backoff before giving up.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req) as response:
                content = response.read()
            return pd.read_parquet(io.BytesIO(content))
        except Exception as error:  # noqa: BLE001 - retried below, re-raised when exhausted
            last_error = error
            if attempt < attempts - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
    raise RuntimeError(f"failed to download {url} after {attempts} attempts: {last_error}")


def download_one(filename: str, file_info: Dict[str, str], data_root: Path) -> Dict[str, Any]:
    """Downloads one file, recording failure rather than aborting the whole run.

    A scheduled pull of fifteen files should not lose the fourteen that succeeded because
    one release was briefly unavailable. The run still fails loudly: `main` exits non-zero
    when any file is missing.
    """
    record: Dict[str, Any] = {
        "filename": filename,
        "source": file_info["source"],
        "url": file_info["url"],
        "size_note": file_info["size_note"],
    }
    output_path = data_root / filename
    try:
        df = download_parquet_nocache(file_info["url"])
    except Exception as error:  # noqa: BLE001 - surfaced through the manifest and exit code
        record.update({"success": False, "error": str(error)})
        return record

    df.to_parquet(output_path, index=False)
    record.update(
        {
            "success": True,
            "row_count": int(len(df)),
            "column_count": int(df.shape[1]),
            "sha256": sha256_file(output_path),
        }
    )
    return record


def download_all(
    *,
    file_map: Dict[str, Dict[str, str]] | None = None,
    data_root: Path = DATA_ROOT,
    manifest_path: Path = RUN_LOG_PATH,
) -> Dict[str, Any]:
    ensure_dirs(data_root, manifest_path)
    resolved_files = file_map or build_2026_file_list()
    results = []
    for filename in sorted(resolved_files):
        file_info = resolved_files[filename]
        results.append(download_one(filename, file_info, data_root))

    failures = [record["filename"] for record in results if not record.get("success")]
    manifest = {
        "season": SEASON,
        "output_dir": str(data_root),
        "file_count": len(results),
        "failed_count": len(failures),
        "failed_files": sorted(failures),
        "files": results,
    }
    # No run timestamp: the manifest must be byte-identical when nothing changed, so the
    # scheduled workflow commits only on real data changes instead of on every run.
    save_json(manifest_path, manifest)
    return manifest


def main() -> None:
    manifest = download_all()
    downloaded = manifest["file_count"] - manifest["failed_count"]
    print(f"Downloaded {downloaded}/{manifest['file_count']} SportsDataverse WNBA {SEASON} parquet files to {DATA_ROOT}")
    if manifest["failed_count"]:
        for filename in manifest["failed_files"]:
            print(f"  FAILED: {filename}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
