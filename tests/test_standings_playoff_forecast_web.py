"""Contract tests for the stat-pack and interactive dashboard renderers."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tests.test_standings_playoff_forecast_markdown import (  # noqa: E402
    _literal_bundle,
)


DASHBOARD_FILES = {
    "index.html",
    "assets/styles.css",
    "assets/app.js",
    "assets/charts.js",
    "data/forecast_payload.json",
}


class WebRendererTests(unittest.TestCase):
    def test_stat_pack_has_exact_path_zones_five_nuggets_and_escaped_source_text(self):
        from standings_playoff_forecast.render_stat_pack import render_stat_pack

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            insights_path = processed_root / "broadcast_insights.csv"
            insights = pd.read_csv(insights_path)
            insights.loc[0, "quick_read_snippet"] = "Literal <script>alert(1)</script> story."
            insights.to_csv(insights_path, index=False)

            output = render_stat_pack(processed_root, cfg=cfg)
            self.assertEqual(
                output,
                Path(cfg.output_root)
                / "deliverables/season=2031/latest/wnba_playoff_stat_pack_insert.html",
            )
            text = output.read_text(encoding="utf-8")
            for zone in (
                "Model &amp; cutline status",
                "Current playoff field",
                "Projected standings &amp; playoff probability",
                "Exact-rank probability",
                "Remaining schedule &amp; win impact",
                "Five broadcast nuggets",
                "Tiebreak watch",
                "Methodology &amp; source",
            ):
                self.assertIn(zone, text)
            self.assertEqual(text.count('class="nugget"'), 5)
            self.assertIn("73.1%", text)
            self.assertIn("Literal &lt;script&gt;alert(1)&lt;/script&gt; story.", text)
            self.assertNotIn("<script>alert(1)</script>", text)
            self.assertIn("@page { size: 17in 11in; margin: 0.25in; }", text)

    def test_stat_pack_is_deterministic_and_schema_failure_preserves_existing_output(self):
        from standings_playoff_forecast.render_stat_pack import render_stat_pack

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            output = render_stat_pack(processed_root, cfg=cfg)
            first = output.read_bytes()
            self.assertEqual(render_stat_pack(processed_root, cfg=cfg).read_bytes(), first)

            forecast_path = processed_root / "forecast_summary.csv"
            forecast = pd.read_csv(forecast_path).drop(columns=["playoff_probability"])
            forecast.to_csv(forecast_path, index=False)
            with self.assertRaisesRegex(ValueError, "playoff_probability"):
                render_stat_pack(processed_root, cfg=cfg)
            self.assertEqual(output.read_bytes(), first)
            self.assertFalse(list(output.parent.glob(f".{output.name}.*.tmp")))

    def test_dashboard_exact_inventory_payload_copy_sections_controls_and_fetch_contract(self):
        from standings_playoff_forecast.render_dashboard import render_dashboard

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            source_payload = (processed_root / "forecast_payload.json").read_bytes()
            output = render_dashboard(processed_root, cfg=cfg)
            dashboard_root = output.parent
            inventory = {
                path.relative_to(dashboard_root).as_posix()
                for path in dashboard_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(inventory, DASHBOARD_FILES)
            copied_payload = dashboard_root / "data/forecast_payload.json"
            self.assertEqual(copied_payload.read_bytes(), source_payload)
            self.assertEqual(
                hashlib.sha256(copied_payload.read_bytes()).hexdigest(),
                hashlib.sha256(source_payload).hexdigest(),
            )

            html = output.read_text(encoding="utf-8")
            for section_id in (
                "snapshot-kpis",
                "current-standings",
                "projected-standings",
                "rank-probability",
                "schedule-leverage",
                "team-detail",
                "historical-comparison",
                "broadcast-insights",
                "method-cutoff",
            ):
                self.assertIn(f'id="{section_id}"', html)
            for control in ("team-select", "race-view", "probability-view"):
                self.assertIn(f'id="{control}"', html)
            self.assertIn('data-team-count="2"', html)
            self.assertIn('data-playoff-qualifiers="1"', html)

            app = (dashboard_root / "assets/app.js").read_text(encoding="utf-8")
            self.assertIn(
                'fetch("./data/forecast_payload.json", { cache: "no-store" })',
                app,
            )
            self.assertIn("Forecast payload failed: ${response.status}", app)
            self.assertIn("popstate", app)
            self.assertIn("URLSearchParams", app)
            self.assertIn("pushState", app)
            self.assertIn("aria-live", html)
            self.assertNotIn("innerHTML", app)
            for forbidden in ("Math.random", "simulate", "Minnesota Lynx", "Las Vegas Aces"):
                self.assertNotIn(forbidden, app + html)

    def test_dashboard_responsive_accessible_and_explicit_empty_error_states(self):
        from standings_playoff_forecast.render_dashboard import render_dashboard

        with tempfile.TemporaryDirectory() as temporary:
            cfg, processed_root = _literal_bundle(Path(temporary), history_available=False)
            output = render_dashboard(processed_root, cfg=cfg)
            dashboard_root = output.parent
            html = output.read_text(encoding="utf-8")
            css = (dashboard_root / "assets/styles.css").read_text(encoding="utf-8")
            app = (dashboard_root / "assets/app.js").read_text(encoding="utf-8")
            charts = (dashboard_root / "assets/charts.js").read_text(encoding="utf-8")

            for width in (1024, 768, 390):
                self.assertIn(f"max-width: {width}px", css)
            self.assertIn("overflow-x: auto", css)
            self.assertIn("min-height: 44px", css)
            self.assertIn(":focus-visible", css)
            self.assertIn("prefers-reduced-motion", css)
            self.assertIn("Forecast unavailable", app)
            self.assertIn("No remaining games", app)
            self.assertIn("Historical context unavailable", app)
            self.assertIn("Conditional estimate unavailable", app)
            self.assertIn("createElement(\"table\")", charts)
            self.assertIn("<caption", html)

    def test_dashboard_publication_is_deterministic_and_atomic_on_validation_failure(self):
        from standings_playoff_forecast.render_dashboard import render_dashboard

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            output = render_dashboard(processed_root, cfg=cfg)
            dashboard_root = output.parent
            first = {
                path.relative_to(dashboard_root).as_posix(): path.read_bytes()
                for path in dashboard_root.rglob("*")
                if path.is_file()
            }
            render_dashboard(processed_root, cfg=cfg)
            second = {
                path.relative_to(dashboard_root).as_posix(): path.read_bytes()
                for path in dashboard_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first, second)

            with patch(
                "standings_playoff_forecast.render_dashboard._write_file",
                side_effect=OSError("injected staged-write failure"),
            ):
                with self.assertRaisesRegex(OSError, "staged-write failure"):
                    render_dashboard(processed_root, cfg=cfg)
            after_staged_failure = {
                path.relative_to(dashboard_root).as_posix(): path.read_bytes()
                for path in dashboard_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after_staged_failure, first)
            self.assertFalse(list(dashboard_root.parent.glob(".dashboard.*.tmp")))

            (processed_root / "forecast_payload.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "top-level keys"):
                render_dashboard(processed_root, cfg=cfg)
            after = {
                path.relative_to(dashboard_root).as_posix(): path.read_bytes()
                for path in dashboard_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, first)
            self.assertFalse(list(dashboard_root.parent.glob(".dashboard.*.tmp")))


if __name__ == "__main__":
    unittest.main()
