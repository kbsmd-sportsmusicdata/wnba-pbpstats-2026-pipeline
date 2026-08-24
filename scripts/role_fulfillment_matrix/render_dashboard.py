"""Render a static, directly-openable RFM dashboard bundle."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict


def render_dashboard(payload: Dict[str, Any], template_root: Path, bundle_root: Path) -> None:
    (bundle_root / "assets").mkdir(parents=True, exist_ok=True)
    (bundle_root / "data").mkdir(parents=True, exist_ok=True)

    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    # Keep embedded JSON inert even if future reviewed names contain markup-like text.
    embedded = serialized.replace("<", "\\u003c")
    html = (template_root / "index.html").read_text(encoding="utf-8")
    if "__RFM_PAYLOAD__" not in html:
        raise ValueError("dashboard template is missing __RFM_PAYLOAD__ marker")
    mode = payload["meta"]["mode"]
    fixture = mode == "fixture"
    live = mode == "live"
    replacements = {
        "__RFM_PAYLOAD__": embedded,
        "__RFM_META_DESCRIPTION__": (
            "Fixture-only Role Fulfillment Matrix experiment"
            if fixture
            else (
                "Live Role Fulfillment Matrix"
                if live
                else "Live-data Role Fulfillment Matrix dry-run review"
            )
        ),
        "__RFM_PAGE_TITLE__": (
            "Role Fulfillment Matrix · Fixture Prototype"
            if fixture
            else (
                "Role Fulfillment Matrix · Live"
                if live
                else "Role Fulfillment Matrix · Live Dry Run"
            )
        ),
        "__RFM_STATUS_TITLE__": (
            "Fixture-only prototype"
            if fixture
            else ("Live output enabled" if live else "Live-data dry run")
        ),
        "__RFM_STATUS_DETAIL__": (
            "Synthetic players and teams. Live scoring is blocked pending reviewed gates."
            if fixture
            else (
                "Reviewed real sources and formulas. Manual execution is enabled; scheduling remains disabled."
                if live
                else "Reviewed real sources and formulas. Publishing remains disabled pending final approval."
            )
        ),
        "__RFM_LIVE_STATUS__": (
            "BLOCKED" if fixture else ("ENABLED" if live else "DRY RUN ONLY")
        ),
    }
    for marker, value in replacements.items():
        html = html.replace(marker, value)

    _atomic_text(bundle_root / "index.html", html)
    _atomic_text(bundle_root / "data" / "role_fulfillment_payload.json", serialized + "\n")
    shutil.copyfile(template_root / "assets" / "app.js", bundle_root / "assets" / "app.js")
    shutil.copyfile(
        template_root / "assets" / "score_display.js",
        bundle_root / "assets" / "score_display.js",
    )
    shutil.copyfile(template_root / "assets" / "styles.css", bundle_root / "assets" / "styles.css")


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)
