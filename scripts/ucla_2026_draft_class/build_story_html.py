"""Assemble the editorial artifact from its parts and the generated payload.

The page carries no hand-typed figures: every number is read at load time from
`story_payload.json`, which `build_story_payload.py` derives from the same
manifests `verify_docs.py` checks. After a pipeline refresh, run the payload
builder then this, and republish.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "analysis" / "ucla_2026_draft_class" / "story"
DATA = ROOT / "analysis" / "ucla_2026_draft_class" / "data"


def main() -> int:
    subprocess.run([sys.executable, str(Path(__file__).with_name("build_story_payload.py"))],
                   check=True)
    parts = [
        (SRC / "head.html").read_text(),
        (SRC / "body.html").read_text(),
        '\n<script type="application/json" id="payload">',
        (DATA / "story_payload.json").read_text(),
        "</script>\n<script>\n",
        (SRC / "app.js").read_text(),
        "</script>\n",
    ]
    out = SRC / "ucla-six.html"
    out.write_text("".join(parts))
    print(f"wrote {out.relative_to(ROOT)}  ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
