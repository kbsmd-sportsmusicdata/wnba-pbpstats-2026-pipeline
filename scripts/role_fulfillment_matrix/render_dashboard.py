"""Render the static, directly-openable fixture dashboard bundle."""

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
    html = html.replace("__RFM_PAYLOAD__", embedded)

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
