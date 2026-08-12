"""Structural integrity checks for generated CSV artifacts.

The 2026 All-Star board sat corrupted in the repository for three weeks: four files each
held two different exports concatenated together, complete with a second header row
partway down. Nothing detected it, because every consumer read the file happily and simply
got nonsense -- band labels parsed as scores, one player appearing twice with different
schemas.

The builders themselves cannot cause this; they write with `to_csv`, which overwrites. The
damage came from outside the pipeline. These checks therefore exist to catch a malformed
artifact however it arrived, at generation time and again in CI.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


def check_csv_integrity(path: Path, *, key_columns: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Report structural problems in a CSV artifact.

    Looks for the concatenation signature -- a header repeated mid-file, or rows of more
    than one width -- and optionally for duplicate keys.
    """
    record: Dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        record["ok"] = False
        record["problems"] = ["missing"]
        return record

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        record.update({"ok": False, "problems": ["empty"], "rows": 0})
        return record

    header = rows[0]
    body = rows[1:]
    widths = sorted({len(row) for row in rows})
    repeated_header_lines = [index for index, row in enumerate(body, start=1) if row[:2] == header[:2]]

    problems = []
    if len(widths) > 1:
        problems.append(f"inconsistent row widths {widths}")
    if repeated_header_lines:
        problems.append(f"header repeated at line(s) {repeated_header_lines[:5]}")

    duplicate_keys: list = []
    if key_columns:
        missing = [column for column in key_columns if column not in header]
        if missing:
            problems.append(f"missing key column(s) {missing}")
        else:
            positions = [header.index(column) for column in key_columns]
            seen, duplicates = set(), set()
            for row in body:
                if len(row) != len(header):
                    continue
                key = tuple(row[position] for position in positions)
                (duplicates if key in seen else seen).add(key)
            duplicate_keys = sorted(duplicates)
            if duplicate_keys:
                problems.append(f"{len(duplicate_keys)} duplicate key(s) on {list(key_columns)}")

    record.update(
        {
            "rows": len(body),
            "columns": len(header),
            "row_widths": widths,
            "repeated_header_lines": repeated_header_lines,
            "duplicate_keys": duplicate_keys[:10],
            "problems": problems,
            "ok": not problems,
        }
    )
    return record


def check_outputs(paths: Dict[str, Path], key_columns: Dict[str, Sequence[str]]) -> Dict[str, Dict[str, Any]]:
    """Run the integrity check across a builder's CSV outputs."""
    report: Dict[str, Dict[str, Any]] = {}
    for name, path in paths.items():
        if Path(path).suffix.lower() != ".csv":
            continue
        report[Path(path).name] = check_csv_integrity(Path(path), key_columns=key_columns.get(name))
    return report


def failed_outputs(report: Dict[str, Dict[str, Any]]) -> Dict[str, list]:
    """The subset of a report that failed, as filename -> problems."""
    return {name: record["problems"] for name, record in report.items() if not record.get("ok")}
