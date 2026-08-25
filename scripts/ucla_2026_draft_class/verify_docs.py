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
    sdv = ROOT / "data/raw/sportsdataverse/wnba_2026"
    frozen_poss = pd.read_parquet(sdv / "wnba_possessions_2026.parquet", columns=["game_id"])
    frozen_lineups = pd.read_parquet(sdv / "wnba_lineups_2026.parquet", columns=["game_id"])
    espn = pd.read_parquet(sdv / "espn_pbp_2026.parquet", columns=["game_id"])
    return {
        "frozen_poss_games": int(frozen_poss.game_id.nunique()),
        "frozen_lineup_games": int(frozen_lineups.game_id.nunique()),
        "espn_games": int(espn.game_id.nunique()),
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


# Lines that legitimately quote a superseded vintage, with the reason. Each must
# still appear verbatim -- a stale exemption is itself reported, so this list
# cannot silently start excusing something it was never meant to.
HISTORICAL_QUOTES = [
    ("DERIVED_POSSESSIONS.md", "| Derived layer, 277 games |",
     "four-vintage Betts+Austin table: the point is that the estimate moved"),
    ("EDA_FINDINGS_PBPSTATS_ONLY.md", "At 277 games this document said",
     "explicit correction against the previous vintage"),
    ("DERIVED_POSSESSIONS.md", "277 games as her decline continued",
     "retained earlier-vintage note; the preceding line labels it as such"),
]


def coverage_value_check(t: dict, text: dict[str, str]) -> list[str]:
    """Reject obsolete game counts, rather than merely finding one fresh one.

    `re.search` is satisfied by a single match, so a document can quote the
    current vintage once and keep four stale copies. This walks every
    "<n> games" occurrence instead. A value is fine if it is the current count
    or another source's real coverage (all derived, never hardcoded); a
    superseded value is fine only on a line that also names the current count,
    or on an explicitly listed historical line.
    """
    allowed = {t["games"], t["frozen_poss_games"], t["frozen_lineup_games"],
               t["espn_games"], t["team_games_validated"]}
    bad = []
    for f, body in text.items():
        for m in re.finditer(r"\b(\d{3})(?:,\d{3})? (?:team[- ])?games\b", body):
            val = int(m.group(1))
            if val in allowed:
                continue
            line_no = body[:m.start()].count("\n") + 1
            line = body.splitlines()[line_no - 1]
            if str(t["games"]) in line:
                continue                      # a side-by-side vintage comparison
            if any(fn == f and frag in line for fn, frag, _ in HISTORICAL_QUOTES):
                continue                      # explicitly allowed history
            bad.append(f"{f}:{line_no} quotes an obsolete coverage value "
                       f"({val} games); current is {t['games']}")
    for fn, frag, why in HISTORICAL_QUOTES:
        if frag not in text.get(fn, ""):
            bad.append(f"stale exemption: {fn} no longer contains {frag!r} ({why})")
    return bad


def row_count_check() -> list[str]:
    """Every row count quoted in the README's artifact table must be real.

    Hand-picked checks only catch the figures someone thought to list, and the
    per-export row counts grow on exactly the refreshes this script exists to
    police. So rather than enumerate them, parse the table and compare each
    claim against the file it names.
    """
    md = (DOCS / "README.md").read_text()
    claims = re.findall(r"^\|\s*`([^`]+\.(?:csv|parquet))`\s*\|\s*([\d,]+)\s*\|", md, re.M)
    if not claims:
        return ["README.md: no artifact table rows found to verify — has the table moved?"]
    bad = []
    for name, claimed in claims:
        path = DATA / name
        if not path.exists():
            bad.append(f"README.md names {name}, which does not exist in data/")
            continue
        actual = (len(pd.read_parquet(path)) if name.endswith(".parquet")
                  else len(pd.read_csv(path)))
        if int(claimed.replace(",", "")) != actual:
            bad.append(f"README.md says {name} has {claimed} rows; it has {actual:,}")
    return bad


# prose that describes the open Rice window as a fixed range. The window grows
# on every refresh, so a chart built to these words silently drops her latest
# games -- which is exactly what happened once already.
DASH = r"[-\u2013\u2014]"
CLOSED_WINDOW_PROSE = re.compile(
    # any fixed endpoint, not just the 6-10 / g32-36 wording that was wrong once:
    # a future refresh is just as likely to write "return 6-11" or "g32-37".
    rf"return\s*(?:games\s*)?6\s*{DASH}\s*\d+"
    rf"|\bg\s*3\d\s*{DASH}\s*3\d\b"
    rf"|\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    rf"\s+post-injury games",
    re.I)


def prose_check(text: dict[str, str]) -> list[str]:
    """No document may describe the open-ended return window as a closed range."""
    bad = []
    for f, body in text.items():
        for m in CLOSED_WINDOW_PROSE.finditer(body):
            line = body[:m.start()].count("\n") + 1
            bad.append(f"{f}:{line} describes the open return window as closed: {m.group(0)!r}")
    return bad


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
    failures += prose_check(text)
    failures += coverage_value_check(t, text)
    row_failures = row_count_check()
    failures += row_failures

    n_rows = len(re.findall(r"^\|\s*`[^`]+\.(?:csv|parquet)`\s*\|\s*[\d,]+\s*\|",
                            text["README.md"], re.M))

    print(f"data: {t['games']} games through {t['through']}, {t['players']} players, "
          f"{t['possessions']:,} possessions")
    if failures:
        print(f"\n{len(failures)} doc/data mismatch(es):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"all {len(checks(t)) + 6 + n_rows} doc/data consistency checks pass "
          f"({n_rows} of them per-export row counts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
