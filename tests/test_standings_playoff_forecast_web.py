"""Contract tests for the stat-pack and interactive dashboard renderers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
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


class _QuietHttpHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        return


def _find_playwright_node_modules() -> Path:
    candidates = [
        Path(entry).expanduser()
        for entry in os.environ.get("NODE_PATH", "").split(os.pathsep)
        if entry
    ]
    candidates.extend(
        (
            ROOT / "node_modules",
            Path.home()
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules",
        )
    )
    candidates.extend(sorted((Path.home() / ".npm/_npx").glob("*/node_modules")))
    for candidate in candidates:
        if (candidate / "playwright-core").is_dir():
            return candidate
    raise unittest.SkipTest(
        "playwright-core is unavailable in NODE_PATH, the workspace, or bundled runtimes"
    )


def _run_dashboard_dom_contract(root: Path) -> str:
    node_modules = _find_playwright_node_modules()

    dashboard_root = root / "dashboard"
    index_path = dashboard_root / "index.html"
    index = index_path.read_text(encoding="utf-8")
    instrumentation = """<script>
window.__historyCalls = {push: 0, replace: 0};
const originalPushState = history.pushState.bind(history);
const originalReplaceState = history.replaceState.bind(history);
history.pushState = (...args) => { window.__historyCalls.push += 1; return originalPushState(...args); };
history.replaceState = (...args) => { window.__historyCalls.replace += 1; return originalReplaceState(...args); };
</script>"""
    index_path.write_text(
        index.replace(
            '<script src="./assets/charts.js" defer></script>',
            instrumentation + '\n  <script src="./assets/charts.js" defer></script>',
        ),
        encoding="utf-8",
    )
    error_root = root / "dashboard-error"
    shutil.copytree(dashboard_root, error_root)
    (error_root / "data/forecast_payload.json").unlink()

    runner = root / "dashboard_dom_runner.html"
    runner.write_text(
        """<!doctype html><meta charset="utf-8"><pre id="result">RUNNING</pre><iframe id="frame"></iframe>
<script>
const result = document.getElementById("result");
const frame = document.getElementById("frame");
const waitFor = async (predicate, label) => {
  const deadline = Date.now() + 4000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`Timed out: ${label}`);
};
const change = (control, value) => {
  control.value = value;
  control.checked = true;
  control.dispatchEvent(new Event("change", {bubbles: true}));
};
const assert = (condition, message) => { if (!condition) throw new Error(message); };
(async () => {
  frame.src = "dashboard/index.html";
  await waitFor(() => frame.contentDocument?.getElementById("app-status")?.textContent.includes("teams shown"), "dashboard start");
  const win = frame.contentWindow;
  let doc = frame.contentDocument;
  assert(win.__historyCalls.replace === 1, "initial render must replace URL state");
  change(doc.getElementById("team-select"), "B");
  change(doc.querySelector('input[name="probability"][value="rank"]'), "rank");
  assert(win.__historyCalls.push === 2, "team and probability changes must push URL state");
  assert(win.location.search.includes("team=B") && win.location.search.includes("probability=rank"), "team/probability URL state missing");
  const projected = doc.getElementById("projected-table").textContent;
  assert(projected.includes("Modal final rank") && projected.includes("Rank 1 · 50.0%") && projected.includes("Rank 2 · 73.1%"), `exact-rank supplied modal evidence missing: ${projected}`);
  change(doc.querySelector('input[name="race"][value="top4"]'), "top4");
  assert(win.__historyCalls.push === 3, "race change must push URL state");
  assert(doc.getElementById("team-select").options.length === 1, "top4 race must filter visible teams");
  win.history.back();
  await waitFor(() => win.location.search.includes("team=B") && win.location.search.includes("race=all") && doc.getElementById("team-select").value === "B", "popstate restoration");
  assert(doc.querySelector('input[name="probability"][value="rank"]').checked, "probability control not restored");
  assert(doc.querySelector('input[name="race"][value="all"]').checked, "race control not restored");

  frame.src = "dashboard-error/index.html";
  await waitFor(() => frame.contentDocument?.getElementById("error-state")?.textContent.includes("Forecast unavailable"), "payload error");
  doc = frame.contentDocument;
  assert(doc.getElementById("error-state").hidden === false, "payload error must be visible");
  assert(doc.getElementById("main-content").classList.contains("has-error"), "payload error class missing");
  assert(doc.getElementById("app-status").textContent === "Forecast payload could not be loaded.", "payload error live status missing");
  result.textContent = "PASS";
})().catch((error) => { result.textContent = `FAIL: ${error.stack || error.message}`; });
</script>""",
        encoding="utf-8",
    )
    browser_runner = root / "run_dashboard_dom.cjs"
    browser_runner.write_text(
        """const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({channel: "chrome", headless: true});
  try {
    const page = await browser.newPage();
    await page.goto(process.argv[2]);
    await page.waitForFunction(() => document.getElementById("result").textContent !== "RUNNING", null, {timeout: 10000});
    console.log(await page.locator("#result").textContent());
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
""",
        encoding="utf-8",
    )

    handler = partial(_QuietHttpHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/{runner.name}"
        completed = subprocess.run(
            [
                "node",
                str(browser_runner),
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "NODE_PATH": str(node_modules)},
        )
        return completed.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _measure_stat_pack_top_band(root: Path, filename: str) -> dict:
    node_modules = _find_playwright_node_modules()

    runner = root / "measure_stat_pack.cjs"
    runner.write_text(
        """const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({channel: "chrome", headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1920, height: 1200}});
    await page.goto(process.argv[2]);
    const geometry = await page.evaluate(() => {
      const masthead = document.querySelector(".masthead");
      const measure = (element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
      });
      return {masthead: measure(masthead), children: [...masthead.children].map(measure)};
    });
    console.log(JSON.stringify(geometry));
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
""",
        encoding="utf-8",
    )
    handler = partial(_QuietHttpHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/{filename}"
        completed = subprocess.run(
            ["node", str(runner), url],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "NODE_PATH": str(node_modules)},
        )
        return json.loads(completed.stdout)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class WebRendererTests(unittest.TestCase):
    def test_browser_runtime_discovery_honors_portable_node_path_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            node_modules = Path(temporary) / "node_modules"
            (node_modules / "playwright-core").mkdir(parents=True)
            finder = globals().get("_find_playwright_node_modules", lambda: None)
            with patch.dict(os.environ, {"NODE_PATH": str(node_modules)}):
                self.assertEqual(finder(), node_modules)

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

    def test_stat_pack_top_status_uses_compact_manifest_count_and_exact_pbp_value(self):
        from standings_playoff_forecast.render_stat_pack import render_stat_pack

        with tempfile.TemporaryDirectory() as temporary:
            cfg, processed_root = _literal_bundle(Path(temporary))
            output = render_stat_pack(processed_root, cfg=cfg)
            text = output.read_text(encoding="utf-8")
            top_status = text[text.index('<header class="masthead">') : text.index("</header>")]
            methodology = text[text.index('<section class="zone methodology"') :]

            self.assertIn("Source status", top_status)
            self.assertIn("1 validated file", top_status)
            self.assertNotIn("source.bin", top_status)
            self.assertIn("source.bin", methodology)
            self.assertIn("PBPStats", top_status)
            self.assertIn("safe_for_cutoff", top_status)

    def test_stat_pack_six_source_manifest_has_compact_top_status_without_clipping(self):
        from standings_playoff_forecast.render_stat_pack import render_stat_pack

        source_names = (
            "schedule_2026_regular_season_snapshot.csv",
            "standings_2026_official_snapshot.csv",
            "team_box_scores_2026_complete.parquet",
            "pbpstats_team_features_2026_latest.csv",
            "net_ratings_manual_20260809.csv",
            "rosters_2026_verified_snapshot.csv",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            manifest_path = processed_root / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_files"] = [
                {
                    "name": f"source_{index}",
                    "path": f"/validated/2026/{name}",
                    "sha256": f"{index:064x}",
                    "size_bytes": index * 1000,
                }
                for index, name in enumerate(source_names, start=1)
            ]
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            payload_path = processed_root / "forecast_payload.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            payload["metadata"] = manifest
            payload_path.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            output = render_stat_pack(processed_root, cfg=cfg)
            text = output.read_text(encoding="utf-8")
            top_status = text[text.index('<header class="masthead">') : text.index("</header>")]
            methodology = text[text.index('<section class="zone methodology"') :]
            geometry = _measure_stat_pack_top_band(output.parent, output.name)
            self.assertLessEqual(
                geometry["masthead"]["scrollHeight"],
                geometry["masthead"]["clientHeight"],
            )
            for child in geometry["children"]:
                self.assertLessEqual(child["scrollHeight"], child["clientHeight"])
                self.assertLessEqual(child["scrollWidth"], child["clientWidth"])

            self.assertIn("6 validated files", top_status)
            self.assertIn("safe_for_cutoff", top_status)
            for source_name in source_names:
                self.assertNotIn(source_name, top_status)
                self.assertIn(source_name, methodology)

    def test_stat_pack_publication_failure_preserves_prior_bytes_and_cleans_temp(self):
        from standings_playoff_forecast import render_stat_pack as stat_pack_module

        with tempfile.TemporaryDirectory() as temporary:
            cfg, processed_root = _literal_bundle(Path(temporary))
            output = stat_pack_module.render_stat_pack(processed_root, cfg=cfg)
            prior = output.read_bytes()

            with patch.object(
                stat_pack_module,
                "_replace_file",
                create=True,
                side_effect=OSError("injected publication failure"),
            ):
                with self.assertRaisesRegex(OSError, "publication failure"):
                    stat_pack_module.render_stat_pack(processed_root, cfg=cfg)

            self.assertEqual(output.read_bytes(), prior)
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

    def test_dashboard_radio_label_has_visible_keyboard_focus_style(self):
        from standings_playoff_forecast.render_dashboard import render_dashboard

        with tempfile.TemporaryDirectory() as temporary:
            cfg, processed_root = _literal_bundle(Path(temporary))
            output = render_dashboard(processed_root, cfg=cfg)
            css = (output.parent / "assets/styles.css").read_text(encoding="utf-8")

            self.assertIn(
                "fieldset label:has(input:focus-visible)",
                css,
            )

    def test_dashboard_dom_controls_url_rank_evidence_and_payload_error(self):
        from standings_playoff_forecast.render_dashboard import render_dashboard

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            rank_path = processed_root / "rank_probability_matrix.csv"
            rank_matrix = pd.read_csv(rank_path)
            rank_matrix.loc[rank_matrix["team_id"].eq("A"), "probability"] = 0.5
            rank_matrix.to_csv(rank_path, index=False)
            payload_path = processed_root / "forecast_payload.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            for row in payload["rank_probability_matrix"]:
                if row["team_id"] == "A":
                    row["probability"] = 0.5
            payload_path.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            output = render_dashboard(processed_root, cfg=cfg)
            dom_root = root / "dom-contract"
            dom_root.mkdir()
            shutil.copytree(output.parent, dom_root / "dashboard")
            dumped_dom = _run_dashboard_dom_contract(dom_root)
            self.assertEqual(dumped_dom.strip(), "PASS")

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
