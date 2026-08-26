#!/usr/bin/env python3
"""Build a review-only RFM roster refresh package from ESPN team pages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from role_fulfillment_matrix.roster_refresh import (  # noqa: E402
    build_roster_refresh_candidate,
    parse_espn_roster_page,
    write_roster_refresh_package,
)


TEAM_ABBREVIATIONS = (
    "atl",
    "chi",
    "con",
    "dal",
    "gs",
    "ind",
    "lv",
    "la",
    "min",
    "ny",
    "phx",
    "por",
    "sea",
    "tor",
    "wsh",
)


def roster_url(abbreviation: str) -> str:
    return f"https://www.espn.com/wnba/team/roster/_/name/{abbreviation}"


def _download_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8")


def _page_inputs(values: list[str]) -> list[tuple[str, Path]]:
    parsed = []
    for value in values:
        if "=" not in value:
            raise ValueError("--page must use abbreviation=/path/to/page.html")
        abbreviation, raw_path = value.split("=", 1)
        abbreviation = abbreviation.strip().lower()
        if abbreviation not in TEAM_ABBREVIATIONS:
            raise ValueError(f"unsupported WNBA team abbreviation: {abbreviation}")
        parsed.append((abbreviation, Path(raw_path)))
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--addendum", type=Path, action="append", default=[])
    parser.add_argument(
        "--page",
        action="append",
        default=[],
        help="Use downloaded HTML as abbreviation=/path/to/page.html; repeat per team.",
    )
    parser.add_argument("--source-as-of", required=True)
    parser.add_argument("--cutoff-date", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    if args.page:
        inputs = _page_inputs(args.page)
        pages = [
            parse_espn_roster_page(
                path.read_text(encoding="utf-8"),
                source_url=roster_url(abbreviation),
            )
            for abbreviation, path in inputs
        ]
    else:
        pages = [
            parse_espn_roster_page(
                _download_page(roster_url(abbreviation)),
                source_url=roster_url(abbreviation),
            )
            for abbreviation in TEAM_ABBREVIATIONS
        ]

    base = pd.read_csv(args.base, dtype=str, keep_default_na=False)
    addenda = [
        pd.read_csv(path, dtype=str, keep_default_na=False) for path in args.addendum
    ]
    package = build_roster_refresh_candidate(
        base,
        addenda,
        pages,
        source_as_of=args.source_as_of,
        cutoff_date=args.cutoff_date,
    )
    outputs = write_roster_refresh_package(
        package,
        pages,
        args.output_directory,
        snapshot_date=args.source_as_of,
    )
    print(f"Review package written to {args.output_directory}")
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
