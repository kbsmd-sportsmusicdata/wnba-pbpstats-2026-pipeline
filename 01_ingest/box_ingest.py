"""
box_ingest.py
WNBA Live Game Intel — Data Ingest Layer
Downloads team box, player box, and optional reference files
from sportsdataverse parquet endpoints.
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
import requests

# ── Config ────────────────────────────────────────────────────────────────────

SEASON = 2026
BASE_URL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"

# Parquet file endpoints — release tag names confirmed against:
# https://github.com/sportsdataverse/sportsdataverse-data/releases
ENDPOINTS = {
    # Core box scores — always downloaded
    "team_box": f"{BASE_URL}/wnba_team_box_{SEASON}/wnba_team_box_{SEASON}.parquet",
    "player_box": f"{BASE_URL}/wnba_player_box_{SEASON}/wnba_player_box_{SEASON}.parquet",

    # Reference files — optional, used for validation + game ID tracking
    "standings": f"{BASE_URL}/wnba_stats_standings/wnba_stats_standings.parquet",
    "rosters": f"{BASE_URL}/wnba_stats_game_rosters/wnba_stats_game_rosters.parquet",
    "schedule": f"{BASE_URL}/wnba_stats_schedules/wnba_stats_schedules.parquet",
}

OUTPUT_DIR = Path("data/raw")
LOG_DIR = Path("logs")

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
    ],
)
log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def download_parquet(name: str, url: str, out_dir: Path) -> pd.DataFrame | None:
    """Download a parquet file from URL, save locally, return DataFrame."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{name}_{SEASON}_raw.parquet"

    log.info(f"Downloading [{name}] from:\n  {url}")
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        log.error(f"HTTP error for [{name}]: {e}")
        return None
    except requests.exceptions.RequestException as e:
        log.error(f"Request failed for [{name}]: {e}")
        return None

    dest.write_bytes(response.content)
    log.info(f"Saved [{name}] → {dest} ({dest.stat().st_size / 1024:.1f} KB)")

    try:
        df = pd.read_parquet(dest)
        log.info(f"Loaded [{name}]: {df.shape[0]:,} rows × {df.shape[1]} cols")
        return df
    except Exception as e:
        log.error(f"Failed to read parquet [{name}]: {e}")
        return None


def validate_box_scores(team_df: pd.DataFrame, player_df: pd.DataFrame) -> None:
    """Basic sanity checks on box score files."""
    log.info("── Validation ──────────────────────────────────────")

    if team_df is not None:
        game_ids = team_df["game_id"].nunique() if "game_id" in team_df.columns else "unknown"
        team_ids = team_df["team_id"].nunique() if "team_id" in team_df.columns else "?"
        log.info(f"team_box  → {team_ids} teams, {game_ids} games")

    if player_df is not None:
        athletes = player_df["athlete_id"].nunique() if "athlete_id" in player_df.columns else "?"
        log.info(f"player_box → {athletes} unique athletes")

    if team_df is not None and player_df is not None:
        if "game_id" in team_df.columns and "game_id" in player_df.columns:
            team_games = set(team_df["game_id"].unique())
            player_games = set(player_df["game_id"].unique())
            mismatch = team_games.symmetric_difference(player_games)
            if mismatch:
                log.warning(f"game_id mismatch between team_box and player_box: {len(mismatch)} IDs differ")
            else:
                log.info("game_id alignment: team_box ↔ player_box ✓")

    log.info("────────────────────────────────────────────────────")


def cross_reference_schedule(schedule_df: pd.DataFrame, team_df: pd.DataFrame) -> None:
    """Cross-check game IDs in box scores against the schedule."""
    if schedule_df is None or team_df is None:
        return
    if "game_id" not in schedule_df.columns or "game_id" not in team_df.columns:
        return

    sched_ids = set(schedule_df["game_id"].unique())
    box_ids = set(team_df["game_id"].unique())
    missing_from_box = sched_ids - box_ids
    orphan_in_box = box_ids - sched_ids

    log.info(f"Schedule cross-reference: {len(sched_ids)} scheduled games, {len(box_ids)} in box scores")
    if missing_from_box:
        log.warning(f"  {len(missing_from_box)} scheduled games missing from box scores (may be future games)")
    if orphan_in_box:
        log.warning(f"  {len(orphan_in_box)} box score game_ids not found in schedule")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WNBA Live Game Intel — Box Score & Reference Ingest"
    )
    parser.add_argument(
        "--include-reference",
        action="store_true",
        default=False,
        help="Also download rosters, schedule, and standings reference files",
    )
    parser.add_argument(
        "--rosters",
        action="store_true",
        default=False,
        help="Download rosters only (subset of --include-reference)",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        default=False,
        help="Download schedule only (subset of --include-reference)",
    )
    parser.add_argument(
        "--standings",
        action="store_true",
        default=False,
        help="Download standings only (subset of --include-reference)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        default=False,
        help="Skip post-download validation checks",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(OUTPUT_DIR),
        help=f"Output directory for raw parquet files (default: {OUTPUT_DIR})",
    )

    args = parser.parse_args()
    out = Path(args.output_dir)

    log.info(f"{'='*60}")
    log.info(f"WNBA {SEASON} Box Score Ingest  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Output dir : {out}")
    log.info(f"{'='*60}")

    # ── Always: core box scores ───────────────────────────────────────────────
    team_df = download_parquet("team_box", ENDPOINTS["team_box"], out / "box_scores")
    player_df = download_parquet("player_box", ENDPOINTS["player_box"], out / "box_scores")

    if not args.skip_validation:
        validate_box_scores(team_df, player_df)

    # ── Optional: reference files ─────────────────────────────────────────────
    download_any_ref = args.include_reference or args.rosters or args.schedule or args.standings

    schedule_df = None

    if args.include_reference or args.rosters:
        download_parquet("rosters", ENDPOINTS["rosters"], out / "reference")

    if args.include_reference or args.schedule:
        schedule_df = download_parquet("schedule", ENDPOINTS["schedule"], out / "reference")

    if args.include_reference or args.standings:
        download_parquet("standings", ENDPOINTS["standings"], out / "reference")

    if not download_any_ref:
        log.info("Reference files skipped (pass --include-reference or individual flags to download)")

    # ── Cross-reference validation ────────────────────────────────────────────
    if schedule_df is not None and not args.skip_validation:
        cross_reference_schedule(schedule_df, team_df)

    log.info("Ingest complete.")


if __name__ == "__main__":
    main()
