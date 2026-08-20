import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from standings_playoff_forecast import render_dashboard as rd  # noqa: E402


_CFG = SimpleNamespace(season=2026, team_count=15, playoff_qualifiers=8)
_TEMPLATE = (
    '<html data-season="{{SEASON}}" data-team-count="{{TEAM_COUNT}}" '
    'data-playoff-qualifiers="{{PLAYOFF_QUALIFIERS}}" data-top-boundary="{{TOP_BOUNDARY}}">'
    '<script id="forecast-payload" type="application/json">{{EMBEDDED_PAYLOAD}}</script>'
    '<script id="functional-depth-strip" type="application/json">{{EMBEDDED_DEPTH_STRIP}}</script>'
    "</html>"
)


class DepthPanelRenderTest(unittest.TestCase):
    def test_depth_strip_is_embedded_and_marker_resolved(self):
        rendered = rd._render_index(
            _TEMPLATE, cfg=_CFG, payload_bytes=b"{}", depth_strip_bytes=b'[{"team_abbreviation":"LVA"}]'
        )
        self.assertNotIn("{{EMBEDDED_DEPTH_STRIP}}", rendered)
        self.assertNotIn("{{EMBEDDED_PAYLOAD}}", rendered)
        self.assertIn("LVA", rendered)
        # The embedded JSON is escaped for safe inclusion in a script element.
        self.assertNotIn("<script>", rendered.replace('<script id', ''))

    def test_missing_depth_marker_fails_closed(self):
        template = _TEMPLATE.replace(
            '<script id="functional-depth-strip" type="application/json">{{EMBEDDED_DEPTH_STRIP}}</script>', ""
        )
        with self.assertRaisesRegex(ValueError, "depth-strip marker"):
            rd._render_index(template, cfg=_CFG, payload_bytes=b"{}", depth_strip_bytes=b"[]")


class LoadDepthStripTest(unittest.TestCase):
    def test_present_strip_is_loaded_as_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "strip.csv"
            pd.DataFrame(
                [{"team_abbreviation": "LVA", "dependency_axis": -0.5, "top_scorer_share": 0.28,
                  "depth_profile": "star_dependent", "functional_depth_score": 41.3}]
            ).to_csv(path, index=False)
            cfg = SimpleNamespace(functional_depth_strip=str(path))
            data = rd._load_depth_strip(cfg)
        self.assertIn(b"LVA", data)
        self.assertIn(b"star_dependent", data)

    def test_absent_strip_is_empty_not_an_error(self):
        cfg = SimpleNamespace(functional_depth_strip=str(Path("does/not/exist.csv")))
        self.assertEqual(rd._load_depth_strip(cfg), b"[]")


if __name__ == "__main__":
    unittest.main()
