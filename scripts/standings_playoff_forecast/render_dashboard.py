"""Publish a static interactive dashboard over the validated forecast payload."""

from __future__ import annotations

import html
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from .render_markdown import _load_inputs


DASHBOARD_DIRECTORY = "dashboard"
TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "analysis"
    / "standings_playoff_forecast"
    / "templates"
)


def _render_index(template: str, *, cfg: object) -> str:
    replacements = {
        "SEASON": html.escape(str(int(cfg.season)), quote=True),
        "TEAM_COUNT": html.escape(str(int(cfg.team_count)), quote=True),
        "PLAYOFF_QUALIFIERS": html.escape(
            str(int(cfg.playoff_qualifiers)), quote=True
        ),
        "TOP_BOUNDARY": html.escape(
            str(min(4, int(cfg.playoff_qualifiers))), quote=True
        ),
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    if "{{" in rendered:
        raise ValueError("dashboard template contains unresolved placeholders")
    return rendered


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _publish_directory(staged: Path, final: Path) -> None:
    backup = final.parent / f".{final.name}.{uuid.uuid4().hex}.bak"
    had_previous = final.exists()
    try:
        if had_previous:
            os.replace(final, backup)
        os.replace(staged, final)
    except BaseException:
        if backup.exists() and not final.exists():
            os.replace(backup, final)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def render_dashboard(processed_root: str | Path, *, cfg: object) -> Path:
    """Atomically publish the static dashboard and byte-identical payload copy."""

    root = Path(processed_root).expanduser().resolve()
    _frames, _manifest, _payload = _load_inputs(root, cfg)
    payload_bytes = (root / "forecast_payload.json").read_bytes()
    template = (TEMPLATE_ROOT / "dashboard_index.html").read_text(encoding="utf-8")
    index = _render_index(template, cfg=cfg).encode("utf-8")
    assets = {
        "assets/styles.css": (TEMPLATE_ROOT / "dashboard_styles.css").read_bytes(),
        "assets/app.js": (TEMPLATE_ROOT / "dashboard_app.js").read_bytes(),
        "assets/charts.js": (TEMPLATE_ROOT / "dashboard_charts.js").read_bytes(),
        "data/forecast_payload.json": payload_bytes,
        "index.html": index,
    }

    output_root = Path(cfg.output_root).expanduser()
    if not output_root.is_absolute():
        raise ValueError("configured output_root must be absolute before rendering")
    latest = output_root / "deliverables" / f"season={cfg.season}" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".dashboard.", suffix=".tmp", dir=latest))
    final = latest / DASHBOARD_DIRECTORY
    try:
        for relative, content in assets.items():
            _write_file(staged / relative, content)
        _publish_directory(staged, final)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return final / "index.html"


__all__ = ["DASHBOARD_DIRECTORY", "render_dashboard"]
