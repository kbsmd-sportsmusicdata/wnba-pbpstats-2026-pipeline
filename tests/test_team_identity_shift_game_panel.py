import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity_shift.game_panel import build_game_team_panel  # noqa: E402
from team_identity_shift.style import build_style_frame, dimension_deltas, league_scales  # noqa: E402


_STYLE_DIMENSIONS = ["three_point_attempt_rate", "pace", "turnover_rate", "ft_attempt_rate"]


def _team_game_rows(n_teams=4, n_games=12):
    """A minimal team-game layer: counting stats, opponent points, shot quality, per game."""
    rows = []
    for t in range(n_teams):
        abbr = chr(ord("A") + t) * 3
        for g in range(n_games):
            rows.append(
                {
                    "team_id": str(1611661300 + t),
                    "team_abbreviation": abbr,
                    "game_id": f"{t}-{g}",
                    "game_date": f"2026-05-{g + 1:02d}",
                    "off_poss": 80.0, "def_poss": 80.0, "points": 82 + g, "opponent_points": 80,
                    "fg2_a": 40.0, "fg2_m": 20.0, "fg3_a": 22.0 + g, "fg3_m": 8.0, "fta": 16.0, "ft_points": 12.0,
                    "at_rim_fga": 24.0, "at_rim_fgm": 14.0, "short_mid_range_fga": 8.0, "long_mid_range_fga": 6.0,
                    "corner3_fga": 6.0, "arc3_fga": 16.0, "turnovers": 13.0, "live_ball_turnovers": 8.0,
                    "off_rebounds": 9.0, "def_rebounds": 28.0, "assists": 18.0,
                    "pts_assisted2s": 20.0, "pts_assisted3s": 15.0,
                    "second_chance_points": 10.0, "second_chance_off_poss": 8.0,
                    "penalty_off_poss": 12.0, "penalty_points": 14.0, "steals": 7.0, "blocks": 4.0, "fouls": 18.0,
                    "shot_quality_avg": 0.52,
                }
            )
    return pd.DataFrame(rows)


class GamePanelTest(unittest.TestCase):
    def test_one_window_per_game_with_panel_schema(self):
        panel = build_game_team_panel(_team_game_rows(n_teams=2, n_games=5))
        self.assertEqual(len(panel), 10)  # 2 teams x 5 games
        self.assertTrue((panel["games_in_window"] == 1).all())
        # window_index counts games within a team, starting at 1.
        aaa = panel[panel["team_abbreviation"] == "AAA"].sort_values("window_index")
        self.assertEqual(aaa["window_index"].tolist(), [1, 2, 3, 4, 5])
        # Covered dates collapse to the single game's date.
        self.assertTrue((aaa["covered_game_date_start"] == aaa["covered_game_date_end"]).all())

    def test_shot_quality_is_renamed_and_weighted(self):
        panel = build_game_team_panel(_team_game_rows(n_teams=1, n_games=3))
        self.assertIn("shotquality_pbp_avg", panel.columns)
        self.assertIn("shotquality_pbp_avg_weight", panel.columns)
        # Weight is field-goal attempts (fg2_a + fg3_a) for that game.
        row = panel.iloc[0]
        self.assertAlmostEqual(row["shotquality_pbp_avg_weight"], row["fg2_a"] + row["fg3_a"])

    def test_empty_input_returns_empty(self):
        self.assertTrue(build_game_team_panel(pd.DataFrame()).empty)

    def test_panel_drives_the_style_frame_unchanged(self):
        # The per-game panel is a drop-in for the existing style machinery.
        panel = build_game_team_panel(_team_game_rows(n_teams=4, n_games=12))
        period_frame, season_frame, skipped = build_style_frame(
            panel, dimensions=_STYLE_DIMENSIONS, recent_games=5, min_baseline_games=4
        )
        self.assertEqual(skipped, [])
        self.assertEqual(len(season_frame), 4)
        self.assertEqual(len(period_frame), 8)  # 4 teams x (baseline, recent)
        scales = league_scales(season_frame, _STYLE_DIMENSIONS)
        deltas = dimension_deltas(period_frame, scales, _STYLE_DIMENSIONS)
        self.assertFalse(deltas.empty)
        # Pace is recomputed from possessions/games, not summed.
        self.assertTrue((season_frame["pace"] > 0).all())


if __name__ == "__main__":
    unittest.main()
