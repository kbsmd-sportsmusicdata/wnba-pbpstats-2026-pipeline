"""Contract tests for the broadcaster Markdown forecast brief."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tests.test_standings_playoff_forecast_excel import (  # noqa: E402
    _literal_bundle as _excel_literal_bundle,
)


def _literal_bundle(root: Path, *, history_available: bool = True):
    """Task 13 fixture with a coherent Task 10 conditional-game row."""

    cfg, processed_root = _excel_literal_bundle(
        root, history_available=history_available
    )
    leverage_path = processed_root / "playoff_leverage_games.csv"
    leverage = pd.read_csv(leverage_path)
    if not leverage.empty:
        values = {
            "home_playoff_probability_if_home_win": 0.9,
            "home_playoff_probability_if_home_loss": 0.3,
            "home_playoff_probability_swing": 0.6,
            "away_playoff_probability_if_home_win": 0.1,
            "away_playoff_probability_if_home_loss": 0.7,
            "away_playoff_probability_swing": -0.6,
            "home_top4_probability_if_home_win": 0.9,
            "home_top4_probability_if_home_loss": 0.3,
            "home_top4_probability_swing": 0.6,
            "away_top4_probability_if_home_win": 0.1,
            "away_top4_probability_if_home_loss": 0.7,
            "away_top4_probability_swing": -0.6,
            "home_expected_rank_if_home_win": 1.1,
            "home_expected_rank_if_home_loss": 1.7,
            "home_expected_rank_swing": 0.6,
            "away_expected_rank_if_home_win": 1.9,
            "away_expected_rank_if_home_loss": 1.3,
            "away_expected_rank_swing": -0.6,
        }
        for column, value in values.items():
            leverage.loc[:, column] = value
        leverage.to_csv(leverage_path, index=False)
    return cfg, processed_root


SECTIONS = (
    "Data cutoff and source status",
    "Current playoff picture",
    "Main findings",
    "Top-4 / home-court race",
    "Playoff cutline",
    "High-leverage games",
    "Useful broadcast checkpoints",
    "Tiebreak watch",
    "Historical context",
    "Method / caveats",
)

CONDITIONAL_VALUE_COLUMNS_FOR_TEST = (
    "home_playoff_probability_if_home_win",
    "home_playoff_probability_if_home_loss",
    "home_playoff_probability_swing",
    "away_playoff_probability_if_home_win",
    "away_playoff_probability_if_home_loss",
    "away_playoff_probability_swing",
    "home_top4_probability_if_home_win",
    "home_top4_probability_if_home_loss",
    "home_top4_probability_swing",
    "away_top4_probability_if_home_win",
    "away_top4_probability_if_home_loss",
    "away_top4_probability_swing",
    "home_expected_rank_if_home_win",
    "home_expected_rank_if_home_loss",
    "home_expected_rank_swing",
    "away_expected_rank_if_home_win",
    "away_expected_rank_if_home_loss",
    "away_expected_rank_swing",
)


def _render(root: Path, *, history_available: bool = True):
    from standings_playoff_forecast.render_markdown import render_markdown

    cfg, processed_root = _literal_bundle(root, history_available=history_available)
    return cfg, processed_root, render_markdown(processed_root, cfg=cfg)


class MarkdownRendererTests(unittest.TestCase):
    def test_exact_sections_all_insights_checkpoints_and_supplied_probability(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg, processed_root, brief_path = _render(Path(temporary))
            self.assertEqual(
                brief_path,
                Path(cfg.output_root)
                / "deliverables"
                / "season=2031"
                / "latest"
                / "wnba_broadcast_forecast_brief.md",
            )
            text = brief_path.read_text(encoding="utf-8")
            positions = []
            for section in SECTIONS:
                heading = f"## {section}"
                self.assertEqual(text.count(heading), 1)
                positions.append(text.index(heading))
            self.assertEqual(positions, sorted(positions))

            snippet_positions = []
            for priority in range(1, 11):
                snippet = f"Literal story {priority}."
                self.assertEqual(text.count(snippet), 1)
                snippet_positions.append(text.index(snippet))
            self.assertEqual(snippet_positions, sorted(snippet_positions))
            for label in ("Pregame", "Halftime", "Entering Q4", "Postgame"):
                self.assertIn(f"- **{label}:**", text)

            # 73.1%, rather than the original fixture's 75%, proves this is a
            # presentation of the validated CSV and not a second calculation.
            self.assertIn("73.1%", text)
            self.assertIn("Status not evaluated", text)
            self.assertIn("4 simulations", text)
            self.assertIn("seed 31", text)
            self.assertIn("literal_model", text)
            self.assertIn("safe_for_cutoff", text)
            self.assertIn("2029", text)
            self.assertIn("2 stable-ID fallback events", text)
            self.assertIn("source.bin", text)
            self.assertIn("Stable normalized team ID", text)
            self.assertIn("not an official", text)
            self.assertIn("simulation estimates", text)

            manifest = json.loads((processed_root / "run_manifest.json").read_text())
            self.assertEqual(manifest["official_tiebreak_fallback_count"], 2)

    def test_escapes_table_cells_and_is_byte_deterministic(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            insights_path = processed_root / "broadcast_insights.csv"
            insights = pd.read_csv(insights_path)
            insights.loc[0, "data_point"] = "danger | split\n# injected"
            insights.loc[0, "why_it_matters"] = "control\x01value"
            insights.to_csv(insights_path, index=False)

            first_path = render_markdown(processed_root, cfg=cfg)
            first = first_path.read_bytes()
            second_path = render_markdown(processed_root, cfg=cfg)
            self.assertEqual(first_path, second_path)
            self.assertEqual(first, second_path.read_bytes())
            text = first.decode("utf-8")
            self.assertIn(r"danger \| split<br># injected", text)
            self.assertNotIn("\n# injected", text)
            self.assertNotIn("\x01", text)
            self.assertEqual(list(first_path.parent.glob(f".{first_path.name}.*.tmp")), [])

    def test_history_available_partial_and_unavailable_are_explicit(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            available_text = render_markdown(processed_root, cfg=cfg).read_text()
            self.assertIn("History status: **partial**", available_text)
            self.assertIn("final_qualifier_wins", available_text)
            self.assertIn("incomplete_season_outcomes", available_text)

            history_path = processed_root / "historical_context.csv"
            history = pd.read_csv(history_path)
            available = history.loc[history["availability_status"].eq("available")]
            available.to_csv(history_path, index=False)
            fully_available_text = render_markdown(processed_root, cfg=cfg).read_text()
            self.assertIn("History status: **available**", fully_available_text)

            unavailable = history.loc[history["availability_status"].ne("available")]
            unavailable.to_csv(history_path, index=False)
            unavailable_text = render_markdown(processed_root, cfg=cfg).read_text()
            self.assertIn("History status: **unavailable**", unavailable_text)
            self.assertIn("No historical benchmark is available", unavailable_text)

    def test_completed_schedule_is_explicit(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            for filename in (
                "remaining_schedule.csv",
                "matchup_probabilities.csv",
                "playoff_leverage_games.csv",
            ):
                path = processed_root / filename
                pd.read_csv(path).iloc[0:0].to_csv(path, index=False)
            text = render_markdown(processed_root, cfg=cfg).read_text()
            self.assertIn("No remaining games are present in the validated bundle.", text)
            self.assertIn("No key games remain; checkpoints are not applicable.", text)

    def test_leverage_order_uses_score_then_stable_game_id(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)

            remaining_path = processed_root / "remaining_schedule.csv"
            remaining = pd.read_csv(remaining_path)
            extra_remaining = []
            for game_id, date in (("g10", "2031-06-04"), ("g1", "2031-06-05")):
                row = remaining.iloc[0].copy()
                row["game_id"] = game_id
                row["game_date"] = date
                extra_remaining.append(row)
            pd.concat([remaining, pd.DataFrame(extra_remaining)], ignore_index=True).to_csv(
                remaining_path, index=False
            )

            matchups_path = processed_root / "matchup_probabilities.csv"
            matchups = pd.read_csv(matchups_path)
            extra_matchups = []
            for game_id, date in (("g10", "2031-06-04"), ("g1", "2031-06-05")):
                row = matchups.iloc[0].copy()
                row["game_id"] = game_id
                row["game_date"] = date
                extra_matchups.append(row)
            pd.concat([matchups, pd.DataFrame(extra_matchups)], ignore_index=True).to_csv(
                matchups_path, index=False
            )

            leverage_path = processed_root / "playoff_leverage_games.csv"
            leverage = pd.read_csv(leverage_path)
            leverage.loc[0, "leverage_score"] = 40.0
            extra_leverage = []
            for game_id, date in (("g10", "2031-06-04"), ("g1", "2031-06-05")):
                row = leverage.iloc[0].copy()
                row["game_id"] = game_id
                row["game_date"] = date
                row["leverage_score"] = 88.0
                extra_leverage.append(row)
            pd.concat([leverage, pd.DataFrame(extra_leverage)], ignore_index=True).to_csv(
                leverage_path, index=False
            )

            text = render_markdown(processed_root, cfg=cfg).read_text()
            table_start = text.index("## High-leverage games")
            checkpoint_start = text.index("## Useful broadcast checkpoints")
            table = text[table_start:checkpoint_start]
            self.assertLess(table.index("2031-06-05"), table.index("2031-06-04"))
            self.assertLess(table.index("2031-06-04"), table.index("2031-06-03"))

    def test_every_rendered_key_game_gets_each_checkpoint_label_once(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            game_specs = [
                (f"extra-{index}", f"2031-06-{3 + index:02d}")
                for index in range(1, 6)
            ]
            for filename in (
                "remaining_schedule.csv",
                "matchup_probabilities.csv",
                "playoff_leverage_games.csv",
            ):
                path = processed_root / filename
                frame = pd.read_csv(path)
                rows = []
                for game_id, game_date in game_specs:
                    row = frame.iloc[0].copy()
                    row["game_id"] = game_id
                    row["game_date"] = game_date
                    rows.append(row)
                pd.concat([frame, pd.DataFrame(rows)], ignore_index=True).to_csv(
                    path, index=False
                )

            text = render_markdown(processed_root, cfg=cfg).read_text()
            checkpoints = text[
                text.index("## Useful broadcast checkpoints") : text.index(
                    "## Tiebreak watch"
                )
            ]
            for label in ("Pregame", "Halftime", "Entering Q4", "Postgame"):
                self.assertEqual(checkpoints.count(f"- **{label}:**"), 6)

    def test_status_requires_strict_nullable_boolean_proof(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, clinched, eliminated, note, message in (
                ("malformed", "yes", False, "not_evaluated", "nullable Boolean"),
                ("contradictory", True, True, "not_evaluated", "both be true"),
                ("wrong_note", True, False, "mathematically_eliminated", "status_note"),
            ):
                with self.subTest(name=name):
                    cfg, processed_root = _literal_bundle(root / name)
                    path = processed_root / "forecast_summary.csv"
                    forecast = pd.read_csv(path)
                    forecast["clinched_playoffs"] = forecast[
                        "clinched_playoffs"
                    ].astype(object)
                    forecast["eliminated_from_playoffs"] = forecast[
                        "eliminated_from_playoffs"
                    ].astype(object)
                    forecast.loc[0, "clinched_playoffs"] = clinched
                    forecast.loc[0, "eliminated_from_playoffs"] = eliminated
                    forecast.loc[0, "status_note"] = note
                    forecast.to_csv(path, index=False)
                    with self.assertRaisesRegex(ValueError, message):
                        render_markdown(processed_root, cfg=cfg)

            cfg, processed_root = _literal_bundle(root / "note_only")
            path = processed_root / "forecast_summary.csv"
            forecast = pd.read_csv(path)
            forecast.loc[0, ["clinched_playoffs", "eliminated_from_playoffs"]] = pd.NA
            forecast.loc[0, "status_note"] = "mathematically_clinched"
            forecast.loc[1, "status_note"] = "review_pending"
            forecast.to_csv(path, index=False)
            text = render_markdown(processed_root, cfg=cfg).read_text()
            picture = text[
                text.index("## Current playoff picture") : text.index(
                    "## Main findings"
                )
            ]
            self.assertNotIn("Mathematically clinched", picture)
            self.assertIn("Status not evaluated", picture)
            self.assertIn("Review pending", picture)

            cfg, processed_root = _literal_bundle(root / "proved")
            path = processed_root / "forecast_summary.csv"
            forecast = pd.read_csv(path)
            for column in ("clinched_playoffs", "eliminated_from_playoffs"):
                forecast[column] = forecast[column].astype(object)
            forecast.loc[0, ["clinched_playoffs", "eliminated_from_playoffs"]] = [
                True,
                False,
            ]
            forecast.loc[0, "status_note"] = "mathematically_clinched"
            forecast.loc[1, ["clinched_playoffs", "eliminated_from_playoffs"]] = [
                False,
                True,
            ]
            forecast.loc[1, "status_note"] = "mathematically_eliminated"
            forecast.to_csv(path, index=False)
            text = render_markdown(processed_root, cfg=cfg).read_text()
            picture = text[
                text.index("## Current playoff picture") : text.index(
                    "## Main findings"
                )
            ]
            self.assertEqual(picture.count("Mathematically clinched"), 1)
            self.assertEqual(picture.count("Mathematically eliminated"), 1)

    def test_conditional_state_and_flags_fail_closed(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                (
                    "malformed_available",
                    "conditional_estimate_available",
                    "maybe",
                    "Boolean",
                ),
                ("malformed_flag", "direct_h2h_tiebreak_flag", 1, "Boolean"),
                ("zero_branch", "home_loss_branch_n", 0, "both branches"),
                (
                    "missing_conditional",
                    "home_playoff_probability_if_home_win",
                    pd.NA,
                    "conditional values",
                ),
                (
                    "incoherent_swing",
                    "home_playoff_probability_swing",
                    0.1,
                    "conditional swing",
                ),
            )
            for name, column, value, message in cases:
                with self.subTest(name=name):
                    cfg, processed_root = _literal_bundle(root / name)
                    path = processed_root / "playoff_leverage_games.csv"
                    leverage = pd.read_csv(path)
                    leverage[column] = leverage[column].astype(object)
                    leverage.loc[0, column] = value
                    if name == "zero_branch":
                        leverage.loc[0, "home_win_branch_n"] = 4
                    leverage.to_csv(path, index=False)
                    with self.assertRaisesRegex(ValueError, message):
                        render_markdown(processed_root, cfg=cfg)

            cfg, processed_root = _literal_bundle(root / "unavailable_populated")
            path = processed_root / "playoff_leverage_games.csv"
            leverage = pd.read_csv(path)
            leverage.loc[0, "conditional_estimate_available"] = False
            leverage.loc[0, "home_loss_branch_n"] = 0
            leverage.loc[0, "home_win_branch_n"] = 4
            leverage.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "unavailable.*null"):
                render_markdown(processed_root, cfg=cfg)

            cfg, processed_root = _literal_bundle(root / "unavailable_malformed")
            path = processed_root / "playoff_leverage_games.csv"
            leverage = pd.read_csv(path)
            leverage.loc[0, "conditional_estimate_available"] = False
            leverage.loc[0, "home_win_branch_n"] = 4
            leverage.loc[0, "home_loss_branch_n"] = 0
            leverage.loc[0, list(CONDITIONAL_VALUE_COLUMNS_FOR_TEST)] = pd.NA
            malformed_column = "home_playoff_probability_if_home_win"
            leverage[malformed_column] = leverage[malformed_column].astype(object)
            leverage.loc[0, malformed_column] = "garbage"
            leverage.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "unavailable.*null"):
                render_markdown(processed_root, cfg=cfg)

            cfg, processed_root = _literal_bundle(root / "unavailable_valid")
            path = processed_root / "playoff_leverage_games.csv"
            leverage = pd.read_csv(path)
            leverage.loc[0, "conditional_estimate_available"] = False
            leverage.loc[0, "home_win_branch_n"] = 4
            leverage.loc[0, "home_loss_branch_n"] = 0
            leverage.loc[0, list(CONDITIONAL_VALUE_COLUMNS_FOR_TEST)] = pd.NA
            leverage.to_csv(path, index=False)
            text = render_markdown(processed_root, cfg=cfg).read_text()
            self.assertIn("| unavailable |", text)
            self.assertIn("Supplied home playoff swing: Unavailable", text)

    def test_fallback_count_is_labeled_as_events_not_simulations(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            cfg, _processed_root, brief_path = _render(Path(temporary))
            self.assertEqual(cfg.season, 2031)
            text = brief_path.read_text()
            self.assertIn("2 stable-ID fallback events", text)
            self.assertIn("unresolved tied subgroups across simulation rankings", text)
            self.assertNotIn("simulations required stable-ID", text)

    def test_schema_failure_preserves_existing_brief_and_cleans_temporary_file(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg, processed_root = _literal_bundle(root)
            brief_path = render_markdown(processed_root, cfg=cfg)
            original = brief_path.read_bytes()
            forecast_path = processed_root / "forecast_summary.csv"
            pd.read_csv(forecast_path).drop(columns=["playoff_probability"]).to_csv(
                forecast_path, index=False
            )

            with self.assertRaisesRegex(
                ValueError, "forecast_summary.*playoff_probability"
            ):
                render_markdown(processed_root, cfg=cfg)
            self.assertEqual(brief_path.read_bytes(), original)
            self.assertEqual(list(brief_path.parent.glob(f".{brief_path.name}.*.tmp")), [])

    def test_rejects_bad_priorities_probability_and_game_relationships(self):
        from standings_playoff_forecast.render_markdown import render_markdown

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                ("priorities", "broadcast_insights.csv", "priority", 11, "priorities"),
                (
                    "probability",
                    "forecast_summary.csv",
                    "playoff_probability",
                    1.1,
                    "probabilities",
                ),
                (
                    "missing_probability",
                    "forecast_summary.csv",
                    "playoff_probability",
                    pd.NA,
                    "probabilities",
                ),
                (
                    "participants",
                    "playoff_leverage_games.csv",
                    "home_id",
                    "outside",
                    "participants",
                ),
            )
            for name, filename, column, value, message in cases:
                with self.subTest(name=name):
                    case_root = root / name
                    cfg, processed_root = _literal_bundle(case_root)
                    path = processed_root / filename
                    frame = pd.read_csv(path)
                    frame.loc[0, column] = value
                    frame.to_csv(path, index=False)
                    with self.assertRaisesRegex(ValueError, message):
                        render_markdown(processed_root, cfg=cfg)


if __name__ == "__main__":
    unittest.main()
