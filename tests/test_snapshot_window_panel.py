import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from snapshot_window_panel.derived import (  # noqa: E402
    attach_team_possession_share,
    build_player_window_metrics,
    build_team_window_metrics,
)
from snapshot_window_panel.panel import (  # noqa: E402
    apply_weighted_averages,
    build_window_frame,
    classify_additive_columns,
    detect_restatements,
    finalize_panel,
    is_additive_column,
    restatement_check_columns,
    screen_snapshot_integrity,
)


BASE_CONFIG = {
    "panel": {
        "timestamp_column": "_featured_at_utc",
        "games_played_column": "games_played",
        "entity_column": "entity_id",
        "min_games_in_window": 1,
        "emit_baseline_block": True,
    },
    "restatement_detection": {
        "ratio_threshold": 5.0,
        "entity_share_threshold": 0.5,
        "min_history_windows": 3,
        "max_out_of_envelope_share": 0.02,
    },
    "weighted_averages": {"team": [], "player": []},
}


def snapshot_rows(entity, team, stamps, **columns):
    """Build a cumulative snapshot archive for one entity."""
    rows = []
    for index, stamp in enumerate(stamps):
        row = {
            "entity_id": entity,
            "team_abbreviation": team,
            "name": f"Entity {entity}",
            "_featured_at_utc": stamp,
        }
        for column, values in columns.items():
            row[column] = values[index]
        rows.append(row)
    return rows


def build(config, master, level="team"):
    raw, additive, specs, quarantine = build_window_frame(pd.DataFrame(master), config=config, level=level)
    cleaned, qa = detect_restatements(
        raw,
        restatement_check_columns(raw, additive),
        ratio_threshold=config["restatement_detection"]["ratio_threshold"],
        entity_share_threshold=config["restatement_detection"]["entity_share_threshold"],
        min_history_windows=config["restatement_detection"]["min_history_windows"],
    )
    cleaned = apply_weighted_averages(cleaned, specs)
    panel = finalize_panel(cleaned, min_games_in_window=1, identifier_columns=["entity_id", "window_index"])
    return panel, qa, quarantine


class ColumnClassificationTest(unittest.TestCase):
    def test_counting_stats_are_additive(self):
        for column in ("points", "fg3_a", "off_poss", "turnovers", "at_rim_fgm", "games_played"):
            self.assertTrue(is_additive_column(column), column)

    def test_rates_labels_and_metadata_are_not_additive(self):
        for column in (
            "efg_pct",
            "ts_pct",
            "fg3_apct",
            "at_rim_frequency",
            "at_rim_accuracy",
            "rim_fga_share",
            "pace",
            "usage",
            "on_off_rtg",
            "shotquality_pbp_avg",
            "shot_making_over_shotquality_pbp",
            "efg_pct_feature",
            "ts_pct_feature_percentile",
            "shot_diet_profile_label",
            "sample_size_flag",
            "seconds_per_poss_off",
            "avg2pt_shot_distance",
            "entity_id",
            "team_abbreviation",
            "_row_content_hash",
        ):
            self.assertFalse(is_additive_column(column), column)

    def test_classify_skips_all_null_columns(self):
        df = pd.DataFrame({"points": [1, 2], "never_populated": [np.nan, np.nan], "efg_pct": [0.5, 0.5]})
        additive = classify_additive_columns(df)
        self.assertIn("points", additive)
        self.assertNotIn("never_populated", additive)
        self.assertNotIn("efg_pct", additive)


class WindowDifferencingTest(unittest.TestCase):
    def setUp(self):
        self.stamps = [
            "2026-06-02T15:00:00+00:00",
            "2026-06-04T15:00:00+00:00",
            "2026-06-06T15:00:00+00:00",
        ]
        self.master = snapshot_rows(
            "1610612737",
            "ATL",
            self.stamps,
            games_played=[5, 6, 7],
            points=[400, 480, 570],
            off_poss=[400, 480, 560],
        )

    def test_baseline_block_carries_the_pre_archive_games(self):
        panel, _, _ = build(BASE_CONFIG, self.master)
        baseline = panel[panel["is_baseline_block"]].iloc[0]
        self.assertEqual(baseline["games_in_window"], 5)
        self.assertEqual(baseline["points"], 400)
        self.assertEqual(baseline["window_index"], 0)

    def test_windows_are_consecutive_differences(self):
        panel, _, _ = build(BASE_CONFIG, self.master)
        body = panel[~panel["is_baseline_block"]].sort_values("window_index")
        self.assertEqual(list(body["points"]), [80, 90])
        self.assertEqual(list(body["games_in_window"]), [1, 1])
        self.assertEqual(list(body["off_poss"]), [80, 80])

    def test_window_totals_reconcile_to_the_season_total(self):
        panel, _, _ = build(BASE_CONFIG, self.master)
        self.assertEqual(panel["points"].sum(), 570)
        self.assertEqual(panel["games_in_window"].sum(), 7)

    def test_duplicate_timestamps_keep_the_later_row(self):
        master = list(self.master)
        master.append(
            {
                "entity_id": "1610612737",
                "team_abbreviation": "ATL",
                "name": "Entity",
                "_featured_at_utc": self.stamps[-1],
                "games_played": 7,
                "points": 999,
                "off_poss": 560,
            }
        )
        panel, _, _ = build(BASE_CONFIG, master)
        self.assertEqual(panel["points"].sum(), 999)

    def test_covered_game_dates_trail_the_snapshot_by_a_day(self):
        panel, _, _ = build(BASE_CONFIG, self.master)
        body = panel[~panel["is_baseline_block"]].sort_values("window_index").iloc[0]
        self.assertEqual(str(body["covered_game_date_start"]), "2026-06-02")
        self.assertEqual(str(body["covered_game_date_end"]), "2026-06-03")

    def test_team_change_is_flagged(self):
        master = snapshot_rows(
            "203825",
            "LAS",
            self.stamps,
            games_played=[5, 6, 7],
            points=[100, 120, 140],
            off_poss=[100, 120, 140],
        )
        master[2]["team_abbreviation"] = "PHX"
        panel, _, _ = build(BASE_CONFIG, master, level="player")
        flags = panel.sort_values("window_index")["team_changed_in_window"].tolist()
        self.assertEqual(flags, [False, False, True])


class RestatementDetectionTest(unittest.TestCase):
    def _many_entities(self, points_series, games_series, count=6, filler_columns=60):
        stamps = [f"2026-06-{day:02d}T15:00:00+00:00" for day in range(2, 2 + len(points_series))]
        master = []
        for index in range(count):
            # The archive carries ~250 additive columns, so one dirty column is a small
            # share of the whole and must reach column-level invalidation rather than
            # tripping the whole-snapshot quarantine. The filler reproduces that ratio.
            filler = {
                f"clean_stat_{n}": [10 * (step + 1) for step in range(len(points_series))]
                for n in range(filler_columns)
            }
            master.extend(
                snapshot_rows(
                    f"team{index}",
                    f"T{index}",
                    stamps,
                    games_played=games_series,
                    points=points_series,
                    off_poss=[80 * (step + 1) for step in range(len(points_series))],
                    **filler,
                )
            )
        return master

    def test_negative_delta_is_invalidated_and_reported(self):
        master = self._many_entities([100, 180, 150, 230, 310], [1, 2, 3, 4, 5])
        panel, qa, quarantine = build(BASE_CONFIG, master)
        self.assertTrue(quarantine.empty)
        issues = set(qa["issue"]) if not qa.empty else set()
        self.assertIn("negative_delta", issues)
        revised = panel[(panel["window_index"] == 2)]
        self.assertTrue(revised["points"].isna().all())
        # Only the offending column is dropped; the rest of the row survives.
        self.assertTrue(revised["games_in_window"].notna().all())

    def test_signed_columns_may_decrease_without_being_flagged(self):
        stamps = [f"2026-06-{day:02d}T15:00:00+00:00" for day in range(2, 8)]
        master = []
        for index in range(6):
            master.extend(
                snapshot_rows(
                    f"team{index}",
                    f"T{index}",
                    stamps,
                    games_played=[1, 2, 3, 4, 5, 6],
                    points=[80, 160, 240, 320, 400, 480],
                    off_poss=[80, 160, 240, 320, 400, 480],
                    plus_minus=[5, -3, 10, 2, -12, 4],
                )
            )
        panel, qa, _ = build(BASE_CONFIG, master)
        flagged = set(qa["column"]) if not qa.empty else set()
        self.assertNotIn("plus_minus", flagged)
        self.assertTrue(panel["plus_minus"].notna().all())

    def test_league_wide_scale_break_is_detected(self):
        # Every entity's seconds_played is re-based on the same snapshot, as the 2026 feed
        # did on 2026-08-07.
        stamps = [f"2026-06-{day:02d}T15:00:00+00:00" for day in range(2, 10)]
        master = []
        for index in range(6):
            seconds = [1200, 2400, 3600, 4800, 6000, 7200, 30000, 31200]
            master.extend(
                snapshot_rows(
                    f"team{index}",
                    f"T{index}",
                    stamps,
                    games_played=list(range(1, 9)),
                    points=[80 * n for n in range(1, 9)],
                    off_poss=[80 * n for n in range(1, 9)],
                    seconds_played=seconds,
                )
            )
        panel, qa, _ = build(BASE_CONFIG, master)
        breaks = qa[qa["issue"] == "league_wide_scale_break"]
        self.assertIn("seconds_played", set(breaks["column"]))
        self.assertTrue(panel[panel["window_index"] == 6]["seconds_played"].isna().all())
        # An unaffected column in the same window is untouched.
        self.assertTrue(panel[panel["window_index"] == 6]["points"].notna().all())

    def test_isolated_outlier_is_not_treated_as_a_restatement(self):
        # One entity has a huge game; the rest are normal. That is basketball, not a bug.
        stamps = [f"2026-06-{day:02d}T15:00:00+00:00" for day in range(2, 10)]
        master = []
        for index in range(6):
            points = [80 * n for n in range(1, 9)]
            if index == 0:
                points = [80, 160, 240, 320, 400, 480, 3000, 3080]
            master.extend(
                snapshot_rows(
                    f"team{index}",
                    f"T{index}",
                    stamps,
                    games_played=list(range(1, 9)),
                    points=points,
                    off_poss=[80 * n for n in range(1, 9)],
                )
            )
        panel, qa, _ = build(BASE_CONFIG, master)
        breaks = qa[qa["issue"] == "league_wide_scale_break"] if not qa.empty else pd.DataFrame()
        self.assertTrue(breaks.empty or "points" not in set(breaks["column"]))
        self.assertTrue(panel[panel["entity_id"] == "team0"]["points"].notna().all())


class SnapshotQuarantineTest(unittest.TestCase):
    def _archive_with_corrupt_snapshot(self):
        stamps = [f"2026-06-{day:02d}T15:00:00+00:00" for day in range(2, 8)]
        master = []
        for index in range(5):
            master.extend(
                snapshot_rows(
                    f"team{index}",
                    f"T{index}",
                    stamps,
                    games_played=[1, 2, 3, 4, 5, 6],
                    points=[80, 160, 240, 320, 400, 480],
                    off_poss=[80, 160, 240, 320, 400, 480],
                    first_chance_points=[70, 140, 210, 280, 350, 420],
                    penalty_points=[10, 20, 30, 40, 50, 60],
                )
            )
        frame = pd.DataFrame(master)
        # Simulate the column shift seen at 2026-06-03T18:58:03Z: two fields swap values
        # on a single snapshot for every entity.
        corrupt = frame["_featured_at_utc"] == stamps[2]
        frame.loc[corrupt, ["first_chance_points", "penalty_points"]] = frame.loc[
            corrupt, ["penalty_points", "first_chance_points"]
        ].values
        return frame, stamps

    def test_corrupt_snapshot_is_quarantined(self):
        frame, stamps = self._archive_with_corrupt_snapshot()
        additive = classify_additive_columns(frame)
        kept, report = screen_snapshot_integrity(
            frame.assign(_featured_at_utc=pd.to_datetime(frame["_featured_at_utc"], utc=True)),
            additive,
            entity_column="entity_id",
            timestamp_column="_featured_at_utc",
            max_out_of_envelope_share=0.02,
        )
        self.assertEqual(len(report), 1)
        self.assertEqual(str(report.iloc[0]["snapshot_utc"]), str(pd.Timestamp(stamps[2])))
        self.assertNotIn(pd.Timestamp(stamps[2]), set(kept["_featured_at_utc"]))

    def test_quarantine_bridges_windows_without_losing_games(self):
        frame, _ = self._archive_with_corrupt_snapshot()
        panel, _, quarantine = build(BASE_CONFIG, frame.to_dict("records"))
        self.assertEqual(len(quarantine), 1)
        per_entity = panel.groupby("entity_id")[["games_in_window", "points"]].sum()
        # No games are dropped: the window either side of the bad snapshot merges into one.
        self.assertTrue((per_entity["games_in_window"] == 6).all())
        self.assertTrue((per_entity["points"] == 480).all())

    def test_clean_archive_is_not_quarantined(self):
        stamps = [f"2026-06-{day:02d}T15:00:00+00:00" for day in range(2, 8)]
        master = []
        for index in range(5):
            master.extend(
                snapshot_rows(
                    f"team{index}",
                    f"T{index}",
                    stamps,
                    games_played=[1, 2, 3, 4, 5, 6],
                    points=[80, 160, 240, 320, 400, 480],
                    off_poss=[80, 160, 240, 320, 400, 480],
                )
            )
        _, _, quarantine = build(BASE_CONFIG, master)
        self.assertTrue(quarantine.empty)


class WeightedAverageTest(unittest.TestCase):
    def test_window_average_is_recovered_exactly(self):
        config = json.loads(json.dumps(BASE_CONFIG))
        config["weighted_averages"]["team"] = [{"column": "shotquality_pbp_avg", "weight": "fga"}]
        stamps = [
            "2026-06-02T15:00:00+00:00",
            "2026-06-04T15:00:00+00:00",
            "2026-06-06T15:00:00+00:00",
        ]
        # 100 shots at 0.50, then 50 shots at 0.60, then 50 shots at 0.40.
        cumulative_avg = [0.50, (100 * 0.50 + 50 * 0.60) / 150, (100 * 0.50 + 50 * 0.60 + 50 * 0.40) / 200]
        master = snapshot_rows(
            "1610612737",
            "ATL",
            stamps,
            games_played=[5, 6, 7],
            fg2_a=[60, 90, 120],
            fg3_a=[40, 60, 80],
            fg2_m=[30, 45, 60],
            fg3_m=[12, 18, 24],
            points=[200, 300, 400],
            off_poss=[200, 300, 400],
            shotquality_pbp_avg=cumulative_avg,
        )
        panel, _, _ = build(config, master)
        recovered = panel.sort_values("window_index")["shotquality_pbp_avg"].tolist()
        self.assertAlmostEqual(recovered[0], 0.50, places=9)
        self.assertAlmostEqual(recovered[1], 0.60, places=9)
        self.assertAlmostEqual(recovered[2], 0.40, places=9)

    def test_weight_column_is_reported(self):
        config = json.loads(json.dumps(BASE_CONFIG))
        config["weighted_averages"]["team"] = [{"column": "shotquality_pbp_avg", "weight": "fga"}]
        master = snapshot_rows(
            "1610612737",
            "ATL",
            ["2026-06-02T15:00:00+00:00", "2026-06-04T15:00:00+00:00"],
            games_played=[5, 6],
            fg2_a=[60, 90],
            fg3_a=[40, 60],
            fg2_m=[30, 45],
            fg3_m=[12, 18],
            points=[200, 300],
            off_poss=[200, 300],
            shotquality_pbp_avg=[0.50, 0.52],
        )
        panel, _, _ = build(config, master)
        body = panel[~panel["is_baseline_block"]].iloc[0]
        self.assertEqual(body["shotquality_pbp_avg_weight"], 50)


class DerivedMetricsTest(unittest.TestCase):
    def test_team_rates_use_window_totals(self):
        panel = pd.DataFrame(
            [
                {
                    "entity_id": "1",
                    "games_in_window": 1,
                    "points": 100,
                    "opponent_points": 90,
                    "off_poss": 80,
                    "def_poss": 80,
                    "fg2_a": 50,
                    "fg3_a": 30,
                    "fg2_m": 25,
                    "fg3_m": 12,
                    "fta": 20,
                    "turnovers": 12,
                    "assists": 25,
                    "at_rim_fga": 24,
                }
            ]
        )
        out = build_team_window_metrics(panel).iloc[0]
        self.assertAlmostEqual(out["off_rating"], 125.0)
        self.assertAlmostEqual(out["def_rating"], 112.5)
        self.assertAlmostEqual(out["net_rating"], 12.5)
        self.assertAlmostEqual(out["pace"], 80.0)
        self.assertAlmostEqual(out["efg_pct"], (37 + 0.5 * 12) / 80)
        self.assertAlmostEqual(out["ts_pct"], 100 / (2 * (80 + 0.44 * 20)))
        self.assertAlmostEqual(out["three_point_attempt_rate"], 30 / 80)
        self.assertAlmostEqual(out["rim_fga_share"], 24 / 80)
        self.assertAlmostEqual(out["turnover_rate"], 12 / 80)
        self.assertAlmostEqual(out["assist_rate"], 25 / 37)

    def test_player_rates_are_per_75_possessions(self):
        panel = pd.DataFrame(
            [
                {
                    "entity_id": "1",
                    "games_in_window": 1,
                    "points": 30,
                    "assists": 6,
                    "turnovers": 3,
                    "rebounds": 9,
                    "steals": 2,
                    "blocks": 1,
                    "fta": 8,
                    "off_poss": 75,
                    "def_poss": 75,
                    "total_poss": 150,
                    "fg2_a": 12,
                    "fg3_a": 8,
                    "fg2_m": 7,
                    "fg3_m": 3,
                    "on_off_rtg": 118.0,
                    "on_def_rtg": 104.0,
                }
            ]
        )
        out = build_player_window_metrics(panel).iloc[0]
        self.assertAlmostEqual(out["points_per_75"], 30 / 150 * 75)
        self.assertAlmostEqual(out["assists_per_75"], 6 / 150 * 75)
        self.assertAlmostEqual(out["stocks_per_75"], 3 / 150 * 75)
        self.assertAlmostEqual(out["assist_turnover_ratio"], 2.0)
        self.assertAlmostEqual(out["on_court_net_rating"], 14.0)

    def test_missing_denominator_yields_null_not_error(self):
        panel = pd.DataFrame([{"entity_id": "1", "games_in_window": 1, "points": 10, "off_poss": 0}])
        out = build_team_window_metrics(panel).iloc[0]
        self.assertTrue(pd.isna(out["off_rating"]))


class PossessionShareTest(unittest.TestCase):
    def _player(self, start, end, off_poss):
        return {
            "entity_id": "p1",
            "team_abbreviation": "ATL",
            "covered_game_date_start": start,
            "covered_game_date_end": end,
            "off_poss": off_poss,
            "is_baseline_block": False,
        }

    def _team(self, start, end, off_poss):
        return {
            "entity_id": "t1",
            "team_abbreviation": "ATL",
            "covered_game_date_start": start,
            "covered_game_date_end": end,
            "off_poss": off_poss,
            "is_baseline_block": False,
        }

    def test_player_window_spanning_two_team_windows_is_aggregated(self):
        players = pd.DataFrame([self._player("2026-06-02", "2026-06-05", 90)])
        teams = pd.DataFrame(
            [
                self._team("2026-06-02", "2026-06-03", 80),
                self._team("2026-06-04", "2026-06-05", 80),
            ]
        )
        out, stats = attach_team_possession_share(players, teams)
        self.assertEqual(out.iloc[0]["team_off_poss"], 160)
        self.assertAlmostEqual(out.iloc[0]["on_court_poss_share"], 90 / 160)
        self.assertEqual(stats["match_rate"], 1.0)

    def test_partial_coverage_is_left_null(self):
        players = pd.DataFrame([self._player("2026-06-02", "2026-06-05", 90)])
        teams = pd.DataFrame([self._team("2026-06-02", "2026-06-03", 80)])
        out, stats = attach_team_possession_share(players, teams)
        self.assertTrue(pd.isna(out.iloc[0]["team_off_poss"]))
        self.assertEqual(stats["match_rate"], 0.0)

    def test_other_teams_windows_are_not_borrowed(self):
        players = pd.DataFrame([self._player("2026-06-02", "2026-06-03", 90)])
        teams = pd.DataFrame([self._team("2026-06-02", "2026-06-03", 80)])
        teams.loc[0, "team_abbreviation"] = "MIN"
        out, _ = attach_team_possession_share(players, teams)
        self.assertTrue(pd.isna(out.iloc[0]["team_off_poss"]))


class BuilderEndToEndTest(unittest.TestCase):
    def test_cli_writes_panels_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            master_dir = tmpdir / "pbpstats" / "features_master" / "2026"
            master_dir.mkdir(parents=True)
            stamps = [f"2026-06-{day:02d}T15:00:00+00:00" for day in range(2, 8)]

            team_rows = []
            player_rows = []
            for index in range(3):
                team_rows.extend(
                    snapshot_rows(
                        f"team{index}",
                        f"T{index}",
                        stamps,
                        games_played=[1, 2, 3, 4, 5, 6],
                        points=[80 * n for n in range(1, 7)],
                        opponent_points=[78 * n for n in range(1, 7)],
                        off_poss=[80 * n for n in range(1, 7)],
                        def_poss=[80 * n for n in range(1, 7)],
                        fg2_a=[40 * n for n in range(1, 7)],
                        fg3_a=[25 * n for n in range(1, 7)],
                        fg2_m=[20 * n for n in range(1, 7)],
                        fg3_m=[9 * n for n in range(1, 7)],
                        fta=[15 * n for n in range(1, 7)],
                        turnovers=[12 * n for n in range(1, 7)],
                    )
                )
                player_rows.extend(
                    snapshot_rows(
                        f"player{index}",
                        f"T{index}",
                        stamps,
                        games_played=[1, 2, 3, 4, 5, 6],
                        points=[20 * n for n in range(1, 7)],
                        off_poss=[60 * n for n in range(1, 7)],
                        def_poss=[60 * n for n in range(1, 7)],
                        total_poss=[120 * n for n in range(1, 7)],
                        fg2_a=[8 * n for n in range(1, 7)],
                        fg3_a=[5 * n for n in range(1, 7)],
                        fg2_m=[4 * n for n in range(1, 7)],
                        fg3_m=[2 * n for n in range(1, 7)],
                        fta=[4 * n for n in range(1, 7)],
                        assists=[5 * n for n in range(1, 7)],
                        turnovers=[2 * n for n in range(1, 7)],
                    )
                )
            pd.DataFrame(team_rows).to_csv(master_dir / "team_totals_features_master.csv", index=False)
            pd.DataFrame(player_rows).to_csv(master_dir / "player_totals_features_master.csv", index=False)

            config = json.loads(json.dumps(BASE_CONFIG))
            config.update(
                {
                    "season": 2026,
                    "pbpstats_data_root": str(tmpdir / "pbpstats"),
                    "output_root": str(tmpdir / "analysis"),
                    "source_files": {
                        "team_master": "features_master/2026/team_totals_features_master.csv",
                        "player_master": "features_master/2026/player_totals_features_master.csv",
                    },
                }
            )
            config_path = tmpdir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_snapshot_window_panel.py"), "--config", str(config_path)],
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            processed = tmpdir / "analysis" / "data" / "processed"
            team_panel = pd.read_csv(processed / "team_window_panel_2026.csv")
            player_panel = pd.read_csv(processed / "player_window_panel_2026.csv")
            manifest = json.loads((processed / "run_manifest_2026.json").read_text(encoding="utf-8"))

            self.assertEqual(len(team_panel), 18)
            self.assertEqual(team_panel["games_in_window"].sum(), 18)
            self.assertIn("net_rating", team_panel.columns)
            self.assertIn("points_per_75", player_panel.columns)
            self.assertIn("on_court_poss_share", player_panel.columns)
            self.assertEqual(manifest["panel_stats"]["team"]["entities"], 3)
            self.assertEqual(manifest["outputs"]["team_window_panel_2026.csv"], 18)
            self.assertTrue((processed / "window_panel_qa_2026.csv").exists())

    def test_empty_source_produces_empty_panel_without_crashing(self):
        empty, additive, specs, quarantine = build_window_frame(pd.DataFrame(), config=BASE_CONFIG, level="team")
        self.assertTrue(empty.empty)
        self.assertEqual(additive, [])
        self.assertTrue(quarantine.empty)


if __name__ == "__main__":
    unittest.main()
