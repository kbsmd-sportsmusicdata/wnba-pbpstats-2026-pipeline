import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from standings_playoff_forecast import render_markdown as rm  # noqa: E402


_ABBR = {1: "AAA", 2: "BBB", 3: "CCC"}


def _h2h():
    # AAA beat BBB 2-1; AAA and CCC have not met; BBB split with CCC 1-1.
    return pd.DataFrame(
        [
            {"team_id": 1, "opponent_id": 2, "games_played": 3, "wins": 2, "losses": 1},
            {"team_id": 2, "opponent_id": 1, "games_played": 3, "wins": 1, "losses": 2},
            {"team_id": 2, "opponent_id": 3, "games_played": 2, "wins": 1, "losses": 1},
            {"team_id": 3, "opponent_id": 2, "games_played": 2, "wins": 1, "losses": 1},
            {"team_id": 1, "opponent_id": 3, "games_played": 0, "wins": 0, "losses": 0},
            {"team_id": 3, "opponent_id": 1, "games_played": 0, "wins": 0, "losses": 0},
        ]
    )


class HeadToHeadTableTest(unittest.TestCase):
    def test_matrix_shape_and_ordering(self):
        lines = rm._head_to_head_table(_h2h(), [1, 2, 3], _ABBR)
        # Header + separator + one row per team.
        self.assertEqual(len(lines), 2 + 3)
        self.assertEqual(lines[0], "| Team | AAA | BBB | CCC |")

    def test_records_are_reciprocal_and_diagonal_is_dashed(self):
        lines = rm._head_to_head_table(_h2h(), [1, 2, 3], _ABBR)
        rows = {line.split(" | ")[0].strip("| ").strip(): line for line in lines[2:]}
        # AAA's row: self em-dash, 2-1 vs BBB, not-met en-dash vs CCC.
        self.assertIn("| AAA | — | 2-1 | – |", rows["AAA"])
        # BBB's row mirrors AAA: 1-2 back, self, 1-1 vs CCC.
        self.assertIn("| BBB | 1-2 | — | 1-1 |", rows["BBB"])

    def test_unmet_pairs_and_missing_rows_render_endash(self):
        # Drop the AAA/CCC rows entirely: still rendered as not-met, never a crash.
        frame = _h2h()
        frame = frame[~((frame["team_id"] == 1) & (frame["opponent_id"] == 3))]
        lines = rm._head_to_head_table(frame, [1, 2, 3], _ABBR)
        aaa = next(line for line in lines[2:] if line.startswith("| AAA "))
        self.assertIn("| AAA | — | 2-1 | – |", aaa)


if __name__ == "__main__":
    unittest.main()
