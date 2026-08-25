"""Fail if the findings documents disagree with the data they describe.

Coverage numbers (game counts, row counts, pool sizes, validation samples) are
quoted in prose across four markdown files and go stale every time the pipeline
refreshes. That drift has now been caught twice by hand and once in review, so
this makes it mechanical: every figure below is read out of the regenerated
manifests and grepped for in the docs.

Run after any rebuild:  python3 scripts/ucla_2026_draft_class/verify_docs.py
Exits non-zero and lists the mismatches if anything is stale.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "analysis" / "ucla_2026_draft_class"
DATA = DOCS / "data"


def load_truth() -> dict:
    pg = pd.read_parquet(ROOT / "data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet")
    tg = pd.read_parquet(ROOT / "data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet")
    story = json.loads((DATA / "story_manifest.json").read_text())
    derived = json.loads((DATA / "derived_possessions_manifest.json").read_text())
    noise = derived["noise"]
    return {
        "games": int(pg.game_id.nunique()),
        "players": int(pg.player_id.nunique()),
        "team_rows": int(tg.shape[0]),
        "through": str(pd.to_datetime(pg.game_date).max().date()),
        "possessions": int(derived["possessions"]),
        "team_games_validated": int(derived["validation"]["team_games"]),
        "league_pool": int(story["league_pool_size"]),
        "rookie_pool": int(story["rookie_pool_size"]),
        "rookie_population": int(story["rookie_population"]),
        "noise_all_n": int(noise["all_players"]["n"]),
        "noise_ever_n": int(noise["ever_present"]["n"]),
    }


def checks(t: dict) -> list[tuple[str, str, str]]:
    """(file, regex that must match, human description)."""
    g, p, r = t["games"], t["possessions"], t["team_rows"]
    return [
        ("EDA_FINDINGS_PBPSTATS_ONLY.md", rf"\b{g} games\b", f"{g}-game coverage"),
        ("EDA_FINDINGS_PBPSTATS_ONLY.md", rf"{g} games, {t['players']} players", "player-game shape"),
        ("EDA_FINDINGS_PBPSTATS_ONLY.md", rf"{g} games, {r} rows", "team-game shape"),
        ("EDA_FINDINGS_PBPSTATS_ONLY.md", rf"202/{g} games", "frozen-possessions ratio"),
        ("EDA_FINDINGS_PBPSTATS_ONLY.md", re.escape(t["through"]), "coverage date"),
        ("DERIVED_POSSESSIONS.md", rf"{t['team_games_validated']} team-games", "validated team-games"),
        ("DERIVED_POSSESSIONS.md", rf"{p:,} possessions", "possession count"),
        ("DERIVED_POSSESSIONS.md", rf"\|\s*{t['noise_all_n']}\s*\|", "all-players noise sample"),
        ("DERIVED_POSSESSIONS.md", rf"\|\s*{t['noise_ever_n']}\s*\|", "ever-present noise sample"),
        ("METRIC_FRAMEWORK.md", rf"{g} team games", "framework coverage"),
        # the framework table bolds the game count, so match across the markup
        ("METRIC_FRAMEWORK.md", rf"{g} games.{{0,20}}{t['players']} players", "framework player-game shape"),
        ("METRIC_FRAMEWORK.md", rf"202 of {g} games", "framework frozen ratio"),
        ("METRIC_FRAMEWORK.md", rf"{t['league_pool']} players with 250\+ minutes", "league pool"),
        ("METRIC_FRAMEWORK.md", rf"{t['rookie_pool']} rookies", "rookie pool"),
        ("README.md", rf"{g} games, through", "readme coverage"),
        ("README.md", rf"\|\s*{p:,}\s*\|", "readme possession count"),
    ]


def label_check() -> list[str]:
    """The Rice return window is open-ended; no export may imply a closed range."""
    bad = []
    for f in ("story_rice_return_blocks_player", "story_rice_return_blocks_team",
              "story_rice_return_blocks_onoff", "story_rice_blocks_derived"):
        path = DATA / f"{f}.csv"
        if not path.exists():
            continue
        blocks = set(pd.read_csv(path).block)
        closed = {b for b in blocks if re.search(r"g3\d-3\d", b) and "6" in b}
        if closed:
            bad.append(f"{f}.csv still uses a closed label for the open window: {sorted(closed)}")
    return bad


def main() -> int:
    t = load_truth()
    text = {f: (DOCS / f).read_text() for f in
            ("EDA_FINDINGS_PBPSTATS_ONLY.md", "DERIVED_POSSESSIONS.md",
             "METRIC_FRAMEWORK.md", "README.md")}
    failures = [f"{f}: missing {desc} (expected /{pat}/)"
                for f, pat, desc in checks(t) if not re.search(pat, text[f])]
    failures += label_check()

    print(f"data: {t['games']} games through {t['through']}, {t['players']} players, "
          f"{t['possessions']:,} possessions")
    if failures:
        print(f"\n{len(failures)} doc/data mismatch(es):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"all {len(checks(t)) + 4} doc/data consistency checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
