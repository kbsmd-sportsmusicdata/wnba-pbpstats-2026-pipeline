# Team Identity Dashboard MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a coaching-first WNBA Team Identity Dashboard that compares two teams, contrasts last-five form with season identity, generates evidence-linked coaching priorities, falls back safely from validated lineup data to starter/bench splits, and exports as a portable single-file HTML dashboard plus print-ready coach brief.

**Architecture:** Extend the repository's existing staged Python analysis pattern. Python 3.11 loads SportsDataVerse, PBPStats, and Midseason Team Grades outputs; produces deterministic CSV/JSON datasets; evaluates configuration-backed coaching rules; and injects one nested payload into framework-free HTML. The browser only filters and formats precomputed results. Optional PBP and lineup measures degrade to explicit availability states rather than fabricated estimates.

**Tech Stack:** Python 3.11, pandas, NumPy, PyArrow, Python standard library, `unittest`, HTML5, CSS, vanilla JavaScript, GitHub Actions.

## Global Constraints

- Use `analysis/team_identity_dashboard/config/team_identity_config.json` as the runtime configuration entrypoint.
- Reuse `analysis/midseason_team_grades/data/processed/team_game_four_factors_2026.csv`; do not recalculate Four Factors with different formulas.
- Default comparison window is each team's five most recent eligible games versus its full-season baseline as of `as_of_date`.
- Python is the source of truth for metrics, percentiles, ranks, labels, coaching priorities, confidence, and availability.
- Core dashboard data must be embedded in one HTML file with no runtime network request.
- Use only dependencies already present in `requirements.txt`; do not add a frontend framework or templating package.
- Use `unittest`, matching the repository's current tests.
- Preserve four metric availability states exactly: `available`, `estimated`, `proxy`, `unavailable`.
- Use validated five-player lineup metrics only when validation passes; otherwise use a clearly labeled starter/bench split.
- Starter/bench outputs must never be described as five-player lineup performance.
- First-time visitors see the configured featured matchup; returning visitors resume their last selection through browser local storage.
- Generate latest validated outputs and immutable dated snapshots.
- Percentile bands are: Elite 90–100, Strong 75–89, Above average 60–74, Average 40–59, Below average 25–39, Poor 10–24, Critical weakness 0–9.
- Rank icons are: rank 1 `🥇`, rank 2 `🥈`, rank 3 `🥉`, second-worst `⬇️`, worst `⚠️`.
- Delta icons are `▲`, `▼`, and `→`; arrows represent raw movement while accompanying text interprets metric direction.
- Trigger icons are no icon for moderate, `🔥` for strong, and `🔥🔥` for extremely strong.
- A symbol is attached to one display owner only; never repeat the same signal on both a value and its evidence text.
- Do not use red/green as categorical encoding.
- Print exports must display the exact `as_of_date` and snapshot identifier.
- Every recommendation must expose rule ID, metrics, comparison window, evidence values, sample, confidence, and source section.

---

## File Map

### Create

```text
analysis/team_identity_dashboard/README.md
analysis/team_identity_dashboard/methodology.md
analysis/team_identity_dashboard/config/team_identity_config.json
analysis/team_identity_dashboard/config/metric_registry.json
analysis/team_identity_dashboard/config/coaching_rules.json
analysis/team_identity_dashboard/dashboard/team_identity_dashboard.template.html
scripts/build_team_identity_dashboard.py
scripts/team_identity/__init__.py
scripts/team_identity/loaders.py
scripts/team_identity/team_games.py
scripts/team_identity/rolling_form.py
scripts/team_identity/identity_metrics.py
scripts/team_identity/quarter_profiles.py
scripts/team_identity/game_phases.py
scripts/team_identity/lineup_splits.py
scripts/team_identity/coaching_rules.py
scripts/team_identity/presentation.py
scripts/team_identity/validation.py
scripts/team_identity/exports.py
tests/test_team_identity_dashboard.py
.github/workflows/team-identity-dashboard.yml
```

### Generated, not hand-edited

```text
analysis/team_identity_dashboard/data/processed/team_game_identity_2026.csv
analysis/team_identity_dashboard/data/processed/team_identity_summary_2026.csv
analysis/team_identity_dashboard/data/processed/team_recent_form_2026.csv
analysis/team_identity_dashboard/data/processed/team_quarter_profile_2026.csv
analysis/team_identity_dashboard/data/processed/team_game_phase_profile_2026.csv
analysis/team_identity_dashboard/data/processed/team_starter_bench_profile_2026.csv
analysis/team_identity_dashboard/data/processed/team_validated_lineup_profile_2026.csv
analysis/team_identity_dashboard/data/processed/matchup_identity_edges_2026.csv
analysis/team_identity_dashboard/data/processed/coaching_priorities_2026.csv
analysis/team_identity_dashboard/data/viz/team_identity_dashboard_2026.json
analysis/team_identity_dashboard/data/manifests/run_manifest_2026.json
analysis/team_identity_dashboard/data/snapshots/YYYY-MM-DD/**
analysis/team_identity_dashboard/dashboard/team_identity_dashboard.html
analysis/team_identity_dashboard/exports/coach_briefs/featured_matchup_coach_brief_2026.html
```

---

### Task 1: Configuration Contract, Package Skeleton, and Source Loader

**Files:**
- Create: `analysis/team_identity_dashboard/config/team_identity_config.json`
- Create: `analysis/team_identity_dashboard/config/metric_registry.json`
- Create: `analysis/team_identity_dashboard/config/coaching_rules.json`
- Create: `scripts/team_identity/__init__.py`
- Create: `scripts/team_identity/loaders.py`
- Create: `tests/test_team_identity_dashboard.py`

**Interfaces:**
- Produces: `DashboardConfig`, `LoadedIdentitySources`, `load_config_bundle(config_path: Path)`, `load_identity_sources(config: DashboardConfig)`, `resolve_output_paths(config: DashboardConfig)`.
- Consumes: Existing SportsDataVerse files, PBPStats feature files, and Midseason Team Grades processed outputs.

- [ ] **Step 1: Write loader tests for configuration, source manifests, and missing optional files**

```python
# tests/test_team_identity_dashboard.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from team_identity.loaders import load_config_bundle, load_identity_sources


class TeamIdentityDashboardTest(unittest.TestCase):
    def test_load_config_bundle_resolves_defaults_and_registry(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "metric_registry.json").write_text(
                json.dumps({"efg_pct": {"label": "eFG%", "direction": "higher_is_better"}}),
                encoding="utf-8",
            )
            (config_dir / "coaching_rules.json").write_text(json.dumps({"rules": []}), encoding="utf-8")
            config_path = config_dir / "team_identity_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "season": 2026,
                        "as_of_date": "2026-07-25",
                        "output_root": str(root / "output"),
                        "metric_registry": "metric_registry.json",
                        "coaching_rules": "coaching_rules.json",
                        "source_files": {},
                    }
                ),
                encoding="utf-8",
            )

            config = load_config_bundle(config_path)

            self.assertEqual(config.season, 2026)
            self.assertEqual(config.recent_window, 5)
            self.assertEqual(config.metric_registry["efg_pct"]["label"], "eFG%")
            self.assertEqual(config.coaching_rules, [])

    def test_optional_sources_load_as_empty_and_are_recorded(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            config_path = self._write_minimal_config(root)
            config = load_config_bundle(config_path)

            sources = load_identity_sources(config)

            self.assertTrue(sources.espn_pbp.empty)
            self.assertEqual(sources.source_manifest["espn_pbp"]["status"], "missing_optional")
```

Add `_write_minimal_config()` to the test class. It must write tiny `team_box_2026.parquet` and `player_box_2026.parquet` files because those sources are required.

- [ ] **Step 2: Run the loader tests and verify they fail**

Run:

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
```

Expected: import failure because `team_identity.loaders` does not exist.

- [ ] **Step 3: Create the configuration files with concrete MVP defaults**

`team_identity_config.json` must contain:

```json
{
  "season": 2026,
  "as_of_date": "latest",
  "recent_window": 5,
  "featured_team": "GSV",
  "featured_opponent": "MIN",
  "sportsdataverse_data_root": "data/raw/sportsdataverse/wnba_2026",
  "sportsdataverse_fallback_root": "2026_scout_report",
  "pbpstats_data_root": "data/pbpstats_wnba_2026",
  "midseason_team_grades_root": "analysis/midseason_team_grades",
  "output_root": "analysis/team_identity_dashboard",
  "metric_registry": "metric_registry.json",
  "coaching_rules": "coaching_rules.json",
  "minimum_games": {"strong": 10, "usable": 5},
  "lineups": {"minimum_possessions": 25, "minimum_games": 3},
  "source_files": {
    "player_box": "player_box_2026.parquet",
    "team_box": "team_box_2026.parquet",
    "standings": "standings_2026.parquet",
    "espn_pbp": "play_by_play_2026.parquet",
    "wnba_stats_pbp": "wnbastats_play_by_play_20260602.parquet"
  }
}
```

Seed `metric_registry.json` with the 12 fingerprint metrics and the KPI metrics. Every record must include `label`, `direction`, `format`, `group`, `minimum_games`, `stable_epsilon`, `wnba_source`, `wpba_fallback`, and `wpba_status`.

Seed `coaching_rules.json` with at least one rule in each category: `attack`, `limit`, `key`. Include `dedupe_group`, `phase`, `metrics`, `trigger`, `priority_weight`, `headline`, `evidence_template`, and `source_section`.

- [ ] **Step 4: Implement immutable configuration and source dataclasses**

```python
# scripts/team_identity/loaders.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DashboardConfig:
    season: int
    as_of_date: str
    recent_window: int
    featured_team: str
    featured_opponent: str
    output_root: Path
    sportsdataverse_data_root: Path
    sportsdataverse_fallback_root: Path
    pbpstats_data_root: Path
    midseason_team_grades_root: Path
    source_files: dict[str, str]
    minimum_games: dict[str, int]
    lineup_config: dict[str, int]
    metric_registry: dict[str, dict[str, Any]]
    coaching_rules: list[dict[str, Any]]
    config_path: Path
    config_hash: str


@dataclass
class LoadedIdentitySources:
    player_box: pd.DataFrame
    team_box: pd.DataFrame
    standings: pd.DataFrame
    espn_pbp: pd.DataFrame
    wnba_stats_pbp: pd.DataFrame
    player_features: pd.DataFrame
    team_features: pd.DataFrame
    four_factors: pd.DataFrame
    bench_team_game: pd.DataFrame
    clutch_team_game: pd.DataFrame
    rapm_player: pd.DataFrame
    source_manifest: dict[str, dict[str, Any]]
```

Implement `load_config_bundle()` so registry and rules paths resolve relative to the config file directory. Compute SHA-256 from stable JSON excluding filesystem-derived fields.

Implement `load_identity_sources()` with these rules:

- Missing `team_box` or `player_box`: raise `FileNotFoundError` with the exact expected primary and fallback paths.
- Missing standings, PBP, feature panels, Four Factors, bench, clutch, or RAPM: return an empty DataFrame and mark `missing_optional`.
- Add path, row count, column count, size, modified time, and latest game date to each manifest record.
- Coerce numeric box-score columns using `pd.to_numeric(errors="coerce")`.

- [ ] **Step 5: Run the loader tests and verify they pass**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
```

Expected: both loader tests pass.

- [ ] **Step 6: Commit the configuration and loader layer**

```bash
git add analysis/team_identity_dashboard/config scripts/team_identity tests/test_team_identity_dashboard.py
git commit -m "feat: add team identity configuration and loaders"
```

---

### Task 2: Canonical Team-Game Identity Table

**Files:**
- Create: `scripts/team_identity/team_games.py`
- Modify: `tests/test_team_identity_dashboard.py`

**Interfaces:**
- Consumes: `LoadedIdentitySources.team_box`, `LoadedIdentitySources.four_factors`, `DashboardConfig.as_of_date`.
- Produces: `build_team_game_identity(team_box: pd.DataFrame, four_factors: pd.DataFrame, as_of_date: str) -> pd.DataFrame`.

- [ ] **Step 1: Add tests for reciprocal opponents, Four Factors reuse, possession estimates, and date filtering**

```python
from team_identity.team_games import build_team_game_identity


def test_build_team_game_identity_reuses_four_factors_and_filters_as_of_date(self):
    team_box = pd.DataFrame([
        {"game_id": "g1", "game_date": "2026-07-20", "team_id": "1", "team_abbreviation": "ATL", "team_display_name": "Atlanta Dream", "team_home_away": "home", "team_score": 80, "opponent_team_id": "2", "opponent_team_abbreviation": "MIN", "opponent_team_score": 75, "field_goals_attempted": 70, "offensive_rebounds": 10, "turnovers": 12, "free_throws_attempted": 20},
        {"game_id": "g1", "game_date": "2026-07-20", "team_id": "2", "team_abbreviation": "MIN", "team_display_name": "Minnesota Lynx", "team_home_away": "away", "team_score": 75, "opponent_team_id": "1", "opponent_team_abbreviation": "ATL", "opponent_team_score": 80, "field_goals_attempted": 68, "offensive_rebounds": 8, "turnovers": 14, "free_throws_attempted": 18},
        {"game_id": "g2", "game_date": "2026-07-26", "team_id": "1", "team_abbreviation": "ATL", "team_display_name": "Atlanta Dream", "team_home_away": "home", "team_score": 90, "opponent_team_id": "3", "opponent_team_abbreviation": "NYL", "opponent_team_score": 88, "field_goals_attempted": 72, "offensive_rebounds": 9, "turnovers": 10, "free_throws_attempted": 22},
    ])
    four = pd.DataFrame([
        {"game_id": "g1", "team_abbreviation": "ATL", "off_efg_pct": 55.2, "off_tov_pct": 14.1, "off_orb_pct": 31.0, "off_fta_rate": 28.6, "def_efg_pct": 49.8, "def_tov_pct": 16.0, "def_orb_allowed_pct": 27.0, "def_fta_rate_allowed": 26.5},
        {"game_id": "g1", "team_abbreviation": "MIN", "off_efg_pct": 49.8, "off_tov_pct": 16.0, "off_orb_pct": 27.0, "off_fta_rate": 26.5, "def_efg_pct": 55.2, "def_tov_pct": 14.1, "def_orb_allowed_pct": 31.0, "def_fta_rate_allowed": 28.6},
    ])

    out = build_team_game_identity(team_box, four, "2026-07-25")

    self.assertEqual(len(out), 2)
    atl = out[out["team_abbreviation"] == "ATL"].iloc[0]
    self.assertEqual(atl["opponent_abbreviation"], "MIN")
    self.assertAlmostEqual(atl["efg_pct"], 55.2)
    self.assertEqual(atl["possessions_status"], "estimated")
    self.assertGreater(atl["off_rating"], 0)
```

- [ ] **Step 2: Run the new test and verify it fails**

```bash
python -m unittest tests.test_team_identity_dashboard.TeamIdentityDashboardTest.test_build_team_game_identity_reuses_four_factors_and_filters_as_of_date -v
```

Expected: import failure for `team_identity.team_games`.

- [ ] **Step 3: Implement team normalization, reciprocal validation, and possession estimates**

```python
# scripts/team_identity/team_games.py
from __future__ import annotations

import numpy as np
import pandas as pd

TEAM_ALIASES = {"GS": "GSV", "LA": "LAS", "LV": "LVA", "NY": "NYL", "PHO": "PHX", "POR": "PDX", "WSH": "WAS"}


def team_key(value: object) -> str:
    raw = str(value).strip().upper()
    return TEAM_ALIASES.get(raw, raw)


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    return pd.Series(np.where(den > 0, num / den, np.nan), index=num.index)


def build_team_game_identity(team_box: pd.DataFrame, four_factors: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    required = {"game_id", "game_date", "team_abbreviation", "opponent_team_abbreviation", "team_score", "opponent_team_score"}
    missing = sorted(required - set(team_box.columns))
    if missing:
        raise ValueError(f"team_box missing required columns: {missing}")

    df = team_box.copy()
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    if as_of_date != "latest":
        df = df[df["game_date"] <= pd.Timestamp(as_of_date)]
    df["team_abbreviation"] = df["team_abbreviation"].map(team_key)
    df["opponent_abbreviation"] = df["opponent_team_abbreviation"].map(team_key)
    df["home_away"] = df.get("team_home_away", df.get("home_away", ""))

    action_possessions = (
        pd.to_numeric(df.get("field_goals_attempted"), errors="coerce")
        - pd.to_numeric(df.get("offensive_rebounds"), errors="coerce")
        + pd.to_numeric(df.get("turnovers"), errors="coerce")
        + 0.44 * pd.to_numeric(df.get("free_throws_attempted"), errors="coerce")
    )
    df["team_possessions_est"] = action_possessions
    opponent = df[["game_id", "team_abbreviation", "team_possessions_est"]].rename(
        columns={"team_abbreviation": "opponent_abbreviation", "team_possessions_est": "opponent_possessions_est"}
    )
    df = df.merge(opponent, on=["game_id", "opponent_abbreviation"], how="left", validate="many_to_one")
    df["possessions"] = (df["team_possessions_est"] + df["opponent_possessions_est"]) / 2
    df["possessions_status"] = "estimated"
    df["off_rating"] = safe_divide(df["team_score"] * 100, df["possessions"])
    df["def_rating"] = safe_divide(df["opponent_team_score"] * 100, df["possessions"])
    df["net_rating"] = df["off_rating"] - df["def_rating"]
    df["pace"] = df["possessions"]

    if not four_factors.empty:
        factors = four_factors.copy()
        factors["team_abbreviation"] = factors["team_abbreviation"].map(team_key)
        df = df.merge(factors, on=["game_id", "team_abbreviation"], how="left", validate="one_to_one")

    rename = {
        "team_display_name": "team_name",
        "opponent_team_id": "opponent_id",
        "off_efg_pct": "efg_pct",
        "off_tov_pct": "tov_pct",
        "off_orb_pct": "oreb_pct",
        "off_fta_rate": "ft_rate",
    }
    df = df.rename(columns=rename)
    df["as_of_date"] = df["game_date"].max().date().isoformat() if as_of_date == "latest" else as_of_date
    return df.sort_values(["game_date", "game_id", "team_abbreviation"]).reset_index(drop=True)
```

Before returning, add a reciprocal check: every `(game_id, team_abbreviation, opponent_abbreviation)` must have the reverse row. Raise `ValueError` listing nonreciprocal game IDs.

- [ ] **Step 4: Run the canonical-table test and the full test file**

```bash
python -m unittest tests.test_team_identity_dashboard.TeamIdentityDashboardTest.test_build_team_game_identity_reuses_four_factors_and_filters_as_of_date -v
python -m unittest tests/test_team_identity_dashboard.py -v
```

Expected: pass.

- [ ] **Step 5: Commit the canonical table**

```bash
git add scripts/team_identity/team_games.py tests/test_team_identity_dashboard.py
git commit -m "feat: build canonical team game identity table"
```

---

### Task 3: Season Identity, League Percentiles, Ranks, and Rolling Form

**Files:**
- Create: `scripts/team_identity/identity_metrics.py`
- Create: `scripts/team_identity/rolling_form.py`
- Modify: `tests/test_team_identity_dashboard.py`

**Interfaces:**
- Consumes: canonical team-game table and metric registry.
- Produces: `build_team_identity_summary(team_games, registry)`, `build_team_recent_form(team_games, registry, recent_window)`.

- [ ] **Step 1: Add tests for direction-aware percentiles, top-three/bottom-two ranks, and team-specific last-five windows**

```python
from team_identity.identity_metrics import build_team_identity_summary
from team_identity.rolling_form import build_team_recent_form


def test_identity_summary_respects_lower_is_better_and_ties(self):
    rows = []
    for team, efg, tov in [("A", 60, 10), ("B", 55, 12), ("C", 50, 14), ("D", 45, 16)]:
        rows.append({"game_id": f"g-{team}", "game_date": "2026-07-20", "team_abbreviation": team, "efg_pct": efg, "tov_pct": tov})
    games = pd.DataFrame(rows)
    registry = {
        "efg_pct": {"label": "eFG%", "direction": "higher_is_better", "format": "percent", "minimum_games": 1, "stable_epsilon": 0.1},
        "tov_pct": {"label": "TOV%", "direction": "lower_is_better", "format": "percent", "minimum_games": 1, "stable_epsilon": 0.1},
    }

    out = build_team_identity_summary(games, registry)

    a_efg = out[(out.team_abbreviation == "A") & (out.metric_id == "efg_pct")].iloc[0]
    a_tov = out[(out.team_abbreviation == "A") & (out.metric_id == "tov_pct")].iloc[0]
    self.assertEqual(a_efg["league_rank"], 1)
    self.assertEqual(a_tov["league_rank"], 1)
    self.assertGreaterEqual(a_efg["league_percentile"], 90)


def test_recent_form_uses_each_teams_five_latest_games(self):
    games = pd.DataFrame([
        {"game_id": f"a{i}", "game_date": f"2026-07-{i:02d}", "team_abbreviation": "A", "efg_pct": 40 + i}
        for i in range(1, 8)
    ] + [
        {"game_id": f"b{i}", "game_date": f"2026-07-{i:02d}", "team_abbreviation": "B", "efg_pct": 50 + i}
        for i in range(1, 5)
    ])
    registry = {"efg_pct": {"label": "eFG%", "direction": "higher_is_better", "format": "percent", "minimum_games": 1, "stable_epsilon": 0.1}}

    out = build_team_recent_form(games, registry, 5)

    a = out[(out.team_abbreviation == "A") & (out.metric_id == "efg_pct")].iloc[0]
    b = out[(out.team_abbreviation == "B") & (out.metric_id == "efg_pct")].iloc[0]
    self.assertEqual(a["recent_games"], 5)
    self.assertEqual(b["recent_games"], 4)
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
```

Expected: missing module errors.

- [ ] **Step 3: Implement raw identity summaries**

```python
# scripts/team_identity/identity_metrics.py
from __future__ import annotations

import numpy as np
import pandas as pd


def _rank(values: pd.Series, direction: str) -> pd.Series:
    ascending = direction == "lower_is_better"
    return pd.to_numeric(values, errors="coerce").rank(ascending=ascending, method="min")


def _percentile(values: pd.Series, direction: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    oriented = -numeric if direction == "lower_is_better" else numeric
    return oriented.rank(pct=True, method="average") * 100


def build_team_identity_summary(team_games: pd.DataFrame, registry: dict[str, dict]) -> pd.DataFrame:
    records: list[dict] = []
    for metric_id, spec in registry.items():
        if metric_id not in team_games.columns:
            for team in sorted(team_games["team_abbreviation"].dropna().unique()):
                records.append({"team_abbreviation": team, "metric_id": metric_id, "availability": "unavailable"})
            continue
        grouped = team_games.groupby("team_abbreviation", dropna=False).agg(
            metric_value=(metric_id, "mean"), games=("game_id", "nunique")
        ).reset_index()
        grouped["league_rank"] = _rank(grouped["metric_value"], spec["direction"])
        grouped["league_percentile"] = _percentile(grouped["metric_value"], spec["direction"])
        grouped["league_size"] = grouped["team_abbreviation"].nunique()
        grouped["availability"] = np.where(
            grouped["games"] >= int(spec.get("minimum_games", 5)),
            spec.get("availability", "available"),
            "estimated",
        )
        grouped["metric_id"] = metric_id
        grouped["metric_label"] = spec["label"]
        records.extend(grouped.to_dict("records"))
    return pd.DataFrame(records)
```

- [ ] **Step 4: Implement team-specific rolling form and direction-aware interpretation**

```python
# scripts/team_identity/rolling_form.py
from __future__ import annotations

import numpy as np
import pandas as pd


def build_team_recent_form(team_games: pd.DataFrame, registry: dict[str, dict], recent_window: int = 5) -> pd.DataFrame:
    ordered = team_games.sort_values(["team_abbreviation", "game_date", "game_id"])
    recent = ordered.groupby("team_abbreviation", group_keys=False).tail(recent_window)
    records: list[dict] = []
    for metric_id, spec in registry.items():
        if metric_id not in ordered.columns:
            continue
        season = ordered.groupby("team_abbreviation")[metric_id].mean()
        recent_avg = recent.groupby("team_abbreviation")[metric_id].mean()
        recent_games = recent.groupby("team_abbreviation")["game_id"].nunique()
        for team in sorted(ordered["team_abbreviation"].dropna().unique()):
            season_value = season.get(team, np.nan)
            recent_value = recent_avg.get(team, np.nan)
            raw_delta = recent_value - season_value
            direction_multiplier = -1 if spec["direction"] == "lower_is_better" else 1
            improvement_delta = raw_delta * direction_multiplier
            epsilon = float(spec.get("stable_epsilon", 0))
            interpretation = "stable" if abs(raw_delta) <= epsilon else ("improving" if improvement_delta > 0 else "declining")
            records.append({
                "team_abbreviation": team,
                "metric_id": metric_id,
                "metric_label": spec["label"],
                "season_value": season_value,
                "recent_value": recent_value,
                "raw_delta": raw_delta,
                "improvement_delta": improvement_delta,
                "interpretation": interpretation,
                "recent_games": int(recent_games.get(team, 0)),
                "recent_window": recent_window,
            })
    return pd.DataFrame(records)
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
git add scripts/team_identity/identity_metrics.py scripts/team_identity/rolling_form.py tests/test_team_identity_dashboard.py
git commit -m "feat: add identity percentiles and rolling form"
```

---

### Task 4: Quarter Profiles and Coaching Phase Evidence

**Files:**
- Create: `scripts/team_identity/quarter_profiles.py`
- Create: `scripts/team_identity/game_phases.py`
- Modify: `tests/test_team_identity_dashboard.py`

**Interfaces:**
- Consumes: ESPN PBP, canonical team games, optional clutch output and PBPStats team features.
- Produces: `build_team_quarter_profile(espn_pbp, team_games)`, `build_game_phase_profile(team_games, quarter_profile, clutch_team_game, team_features)`.

- [ ] **Step 1: Add tests for quarter scoring, unavailable possession ratings, and phase statuses**

```python
from team_identity.quarter_profiles import build_team_quarter_profile
from team_identity.game_phases import build_game_phase_profile


def test_quarter_profile_sums_scoring_events_without_faking_possessions(self):
    pbp = pd.DataFrame([
        {"game_id": "g1", "game_date": "2026-07-20", "period_number": 1, "team_abbreviation": "ATL", "opponent_team_abbreviation": "MIN", "score_value": 2, "scoring_play": True},
        {"game_id": "g1", "game_date": "2026-07-20", "period_number": 1, "team_abbreviation": "MIN", "opponent_team_abbreviation": "ATL", "score_value": 3, "scoring_play": True},
        {"game_id": "g1", "game_date": "2026-07-20", "period_number": 2, "team_abbreviation": "ATL", "opponent_team_abbreviation": "MIN", "score_value": 3, "scoring_play": True},
    ])
    games = pd.DataFrame([
        {"game_id": "g1", "game_date": "2026-07-20", "team_abbreviation": "ATL", "opponent_abbreviation": "MIN"},
        {"game_id": "g1", "game_date": "2026-07-20", "team_abbreviation": "MIN", "opponent_abbreviation": "ATL"},
    ])

    out = build_team_quarter_profile(pbp, games)

    atl_q1 = out[(out.team_abbreviation == "ATL") & (out.quarter == 1)].iloc[0]
    self.assertEqual(atl_q1["points"], 2)
    self.assertEqual(atl_q1["opponent_points"], 3)
    self.assertTrue(pd.isna(atl_q1["net_rating"]))
    self.assertEqual(atl_q1["rating_status"], "unavailable")
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
```

- [ ] **Step 3: Implement period-column normalization and quarter scoring**

```python
# scripts/team_identity/quarter_profiles.py
from __future__ import annotations

import numpy as np
import pandas as pd


def _first_present(df: pd.DataFrame, candidates: list[str]) -> str | None:
    return next((column for column in candidates if column in df.columns), None)


def build_team_quarter_profile(espn_pbp: pd.DataFrame, team_games: pd.DataFrame) -> pd.DataFrame:
    columns = ["game_id", "game_date", "team_abbreviation", "opponent_abbreviation", "quarter", "points", "opponent_points", "scoring_margin", "possessions", "off_rating", "def_rating", "net_rating", "rating_status"]
    period_col = _first_present(espn_pbp, ["period_number", "period", "period_id"])
    team_col = _first_present(espn_pbp, ["team_abbreviation", "team_abbrev"])
    if espn_pbp.empty or period_col is None or team_col is None or "score_value" not in espn_pbp.columns:
        return pd.DataFrame(columns=columns)

    scoring = espn_pbp.copy()
    if "scoring_play" in scoring.columns:
        scoring = scoring[scoring["scoring_play"] == True]  # noqa: E712
    scoring["score_value"] = pd.to_numeric(scoring["score_value"], errors="coerce").fillna(0)
    scoring["quarter"] = pd.to_numeric(scoring[period_col], errors="coerce").astype("Int64")
    scoring["team_abbreviation"] = scoring[team_col].astype(str).str.upper()
    points = scoring.groupby(["game_id", "quarter", "team_abbreviation"], dropna=False)["score_value"].sum().reset_index(name="points")

    base = team_games[["game_id", "game_date", "team_abbreviation", "opponent_abbreviation"]].drop_duplicates()
    quarters = pd.DataFrame({"quarter": [1, 2, 3, 4]})
    base = base.merge(quarters, how="cross")
    base = base.merge(points, on=["game_id", "quarter", "team_abbreviation"], how="left")
    opponent_points = points.rename(columns={"team_abbreviation": "opponent_abbreviation", "points": "opponent_points"})
    base = base.merge(opponent_points, on=["game_id", "quarter", "opponent_abbreviation"], how="left")
    base[["points", "opponent_points"]] = base[["points", "opponent_points"]].fillna(0)
    base["scoring_margin"] = base["points"] - base["opponent_points"]

    possession_col = _first_present(scoring, ["possession_id", "offensive_possession_id"])
    if possession_col:
        possession_counts = scoring.groupby(["game_id", "quarter", "team_abbreviation"])[possession_col].nunique().reset_index(name="possessions")
        base = base.merge(possession_counts, on=["game_id", "quarter", "team_abbreviation"], how="left")
        base["off_rating"] = np.where(base["possessions"] > 0, 100 * base["points"] / base["possessions"], np.nan)
        base["def_rating"] = np.where(base["possessions"] > 0, 100 * base["opponent_points"] / base["possessions"], np.nan)
        base["net_rating"] = base["off_rating"] - base["def_rating"]
        base["rating_status"] = "available"
    else:
        base["possessions"] = np.nan
        base["off_rating"] = np.nan
        base["def_rating"] = np.nan
        base["net_rating"] = np.nan
        base["rating_status"] = "unavailable"
    return base[columns]
```

- [ ] **Step 4: Implement five coaching-phase rows with explicit evidence availability**

```python
# scripts/team_identity/game_phases.py
from __future__ import annotations

import pandas as pd

PHASES = ["opening_five", "transition", "half_court", "quarter_endings", "late_game"]


def build_game_phase_profile(
    team_games: pd.DataFrame,
    quarter_profile: pd.DataFrame,
    clutch_team_game: pd.DataFrame,
    team_features: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    teams = sorted(team_games["team_abbreviation"].dropna().unique())
    season = team_games.groupby("team_abbreviation", dropna=False).mean(numeric_only=True)
    q1 = quarter_profile[quarter_profile["quarter"] == 1].groupby("team_abbreviation").mean(numeric_only=True) if not quarter_profile.empty else pd.DataFrame()
    clutch = clutch_team_game.groupby("team_abbreviation").mean(numeric_only=True) if not clutch_team_game.empty else pd.DataFrame()

    for team in teams:
        rows.append({"team_abbreviation": team, "phase": "opening_five", "primary_metric": "q1_scoring_margin", "metric_value": q1.at[team, "scoring_margin"] if team in q1.index else None, "availability": "available" if team in q1.index else "unavailable"})
        rows.append({"team_abbreviation": team, "phase": "transition", "primary_metric": "pace", "metric_value": season.at[team, "pace"] if "pace" in season.columns else None, "availability": "proxy"})
        rows.append({"team_abbreviation": team, "phase": "half_court", "primary_metric": "efg_pct", "metric_value": season.at[team, "efg_pct"] if "efg_pct" in season.columns else None, "availability": "proxy"})
        rows.append({"team_abbreviation": team, "phase": "quarter_endings", "primary_metric": "quarter_scoring_margin", "metric_value": quarter_profile[quarter_profile["team_abbreviation"] == team]["scoring_margin"].mean() if not quarter_profile.empty else None, "availability": "estimated" if not quarter_profile.empty else "unavailable"})
        rows.append({"team_abbreviation": team, "phase": "late_game", "primary_metric": "clutch_point_diff", "metric_value": clutch.at[team, "clutch_point_diff"] if team in clutch.index else None, "availability": "available" if team in clutch.index else "unavailable"})
    return pd.DataFrame(rows)
```

Do not label transition or half-court proxy rows as possession-split efficiency. Their evidence text must name the proxy metrics used.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
git add scripts/team_identity/quarter_profiles.py scripts/team_identity/game_phases.py tests/test_team_identity_dashboard.py
git commit -m "feat: add quarter and coaching phase profiles"
```

---

### Task 5: Starter/Bench Baseline and Validated Lineup Adapter

**Files:**
- Create: `scripts/team_identity/lineup_splits.py`
- Modify: `tests/test_team_identity_dashboard.py`

**Interfaces:**
- Produces: `build_starter_bench_profile(player_box, team_box, recent_window) -> pd.DataFrame`, `build_validated_lineup_profile(wnba_stats_pbp, lineup_config) -> tuple[pd.DataFrame, str]`.

- [ ] **Step 1: Add tests for starter/bench reconciliation and lineup fallback**

```python
from team_identity.lineup_splits import build_starter_bench_profile, build_validated_lineup_profile


def test_starter_bench_profile_reconciles_points_and_minutes(self):
    player_box = pd.DataFrame([
        {"game_id": "g1", "game_date": "2026-07-20", "team_abbreviation": "ATL", "opponent_team_abbreviation": "MIN", "starter": True, "did_not_play": False, "minutes": 30, "points": 20, "field_goals_made": 8, "field_goals_attempted": 16, "three_point_field_goals_made": 2, "free_throws_attempted": 4, "rebounds": 5, "assists": 4, "turnovers": 2, "plus_minus": 8},
        {"game_id": "g1", "game_date": "2026-07-20", "team_abbreviation": "ATL", "opponent_team_abbreviation": "MIN", "starter": False, "did_not_play": False, "minutes": 10, "points": 10, "field_goals_made": 4, "field_goals_attempted": 8, "three_point_field_goals_made": 1, "free_throws_attempted": 2, "rebounds": 3, "assists": 2, "turnovers": 1, "plus_minus": 4},
    ])
    team_box = pd.DataFrame([{"game_id": "g1", "team_abbreviation": "ATL", "team_score": 30, "field_goals_attempted": 24, "free_throws_attempted": 6, "turnovers": 3, "rebounds": 8}])

    out = build_starter_bench_profile(player_box, team_box, 5)

    self.assertEqual(set(out["role_group"]), {"starters", "bench"})
    self.assertAlmostEqual(out["points_share"].sum(), 100.0)
    self.assertAlmostEqual(out["minutes_share"].sum(), 100.0)


def test_lineup_adapter_returns_fallback_when_possessions_are_missing(self):
    pbp = pd.DataFrame([{"game_id": "g1", "home_player1": "1", "home_player2": "2", "home_player3": "3", "home_player4": "4", "home_player5": "5", "away_player1": "6", "away_player2": "7", "away_player3": "8", "away_player4": "9", "away_player5": "10"}])

    out, status = build_validated_lineup_profile(pbp, {"minimum_possessions": 25, "minimum_games": 3})

    self.assertTrue(out.empty)
    self.assertEqual(status, "fallback_starter_bench_missing_possession_id")
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
```

- [ ] **Step 3: Implement group-level starter and bench outputs**

```python
# scripts/team_identity/lineup_splits.py
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_divide(num: pd.Series, den: pd.Series) -> pd.Series:
    return pd.Series(np.where(den > 0, num / den, np.nan), index=num.index)


def build_starter_bench_profile(player_box: pd.DataFrame, team_box: pd.DataFrame, recent_window: int = 5) -> pd.DataFrame:
    if player_box.empty or "starter" not in player_box.columns:
        return pd.DataFrame()
    played = player_box[player_box.get("did_not_play", False) != True].copy()  # noqa: E712
    played["role_group"] = np.where(played["starter"] == True, "starters", "bench")  # noqa: E712
    numeric = ["minutes", "points", "field_goals_made", "field_goals_attempted", "three_point_field_goals_made", "free_throws_attempted", "rebounds", "assists", "turnovers", "plus_minus"]
    for column in numeric:
        played[column] = pd.to_numeric(played.get(column), errors="coerce").fillna(0)
    played["offensive_actions"] = played["field_goals_attempted"] + 0.44 * played["free_throws_attempted"] + played["turnovers"]

    game = played.groupby(["game_id", "game_date", "team_abbreviation", "opponent_team_abbreviation", "role_group"], dropna=False).agg(
        minutes=("minutes", "sum"), points=("points", "sum"), fgm=("field_goals_made", "sum"), fga=("field_goals_attempted", "sum"), fg3m=("three_point_field_goals_made", "sum"), fta=("free_throws_attempted", "sum"), rebounds=("rebounds", "sum"), assists=("assists", "sum"), turnovers=("turnovers", "sum"), plus_minus=("plus_minus", "sum"), offensive_actions=("offensive_actions", "sum")
    ).reset_index()
    totals = game.groupby(["game_id", "team_abbreviation"], dropna=False).agg(team_minutes=("minutes", "sum"), team_points=("points", "sum"), team_actions=("offensive_actions", "sum")).reset_index()
    game = game.merge(totals, on=["game_id", "team_abbreviation"], how="left", validate="many_to_one")
    game["minutes_share"] = _safe_divide(game["minutes"] * 100, game["team_minutes"])
    game["points_share"] = _safe_divide(game["points"] * 100, game["team_points"])
    game["usage_action_share"] = _safe_divide(game["offensive_actions"] * 100, game["team_actions"])
    game["efg_pct"] = _safe_divide((game["fgm"] + 0.5 * game["fg3m"]) * 100, game["fga"])
    game["ts_pct"] = _safe_divide(game["points"] * 100, 2 * (game["fga"] + 0.44 * game["fta"]))
    game["ast_to"] = _safe_divide(game["assists"], game["turnovers"])

    ordered = game.sort_values(["team_abbreviation", "game_date", "game_id"])
    recent_game_ids = ordered[["team_abbreviation", "game_id", "game_date"]].drop_duplicates().groupby("team_abbreviation", group_keys=False).tail(recent_window)
    recent = ordered.merge(recent_game_ids[["team_abbreviation", "game_id"]], on=["team_abbreviation", "game_id"], how="inner")
    season_summary = ordered.groupby(["team_abbreviation", "role_group"], dropna=False).mean(numeric_only=True).add_prefix("season_").reset_index()
    recent_summary = recent.groupby(["team_abbreviation", "role_group"], dropna=False).mean(numeric_only=True).add_prefix("recent_").reset_index()
    return season_summary.merge(recent_summary, on=["team_abbreviation", "role_group"], how="left")
```

Keep `usage_action_share` named as a proxy; do not rename it `usage_rate`.

- [ ] **Step 4: Implement strict lineup validation and possession-based aggregation only when supported**

```python
def build_validated_lineup_profile(wnba_stats_pbp: pd.DataFrame, lineup_config: dict[str, int]) -> tuple[pd.DataFrame, str]:
    lineup_columns = [f"home_player{i}" for i in range(1, 6)] + [f"away_player{i}" for i in range(1, 6)]
    if wnba_stats_pbp.empty:
        return pd.DataFrame(), "fallback_starter_bench_missing_lineup_source"
    if not set(lineup_columns).issubset(wnba_stats_pbp.columns):
        return pd.DataFrame(), "fallback_starter_bench_missing_lineup_columns"
    if "possession_id" not in wnba_stats_pbp.columns:
        return pd.DataFrame(), "fallback_starter_bench_missing_possession_id"

    pbp = wnba_stats_pbp.dropna(subset=lineup_columns + ["possession_id"]).copy()
    valid_unique = pbp.apply(
        lambda row: len(set(str(row[column]) for column in lineup_columns[:5])) == 5
        and len(set(str(row[column]) for column in lineup_columns[5:])) == 5,
        axis=1,
    )
    pbp = pbp[valid_unique]
    if pbp.empty:
        return pd.DataFrame(), "fallback_starter_bench_invalid_five_player_rows"

    # Implementation must aggregate one row per unique lineup and possession,
    # then calculate points for, points against, possessions, offensive rating,
    # defensive rating, and net rating. Retain only lineups meeting both
    # minimum_possessions and minimum_games from lineup_config.
```

Complete the aggregation in the implementation, returning status `validated_lineup_possessions` when nonempty and `fallback_starter_bench_insufficient_lineup_sample` when all lineups fail thresholds.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
git add scripts/team_identity/lineup_splits.py tests/test_team_identity_dashboard.py
git commit -m "feat: add starter bench and validated lineup profiles"
```

---

### Task 6: Matchup Edges and Deterministic Coaching Rules

**Files:**
- Create: `scripts/team_identity/coaching_rules.py`
- Modify: `tests/test_team_identity_dashboard.py`
- Modify: `analysis/team_identity_dashboard/config/coaching_rules.json`

**Interfaces:**
- Produces: `build_matchup_edges(identity_summary, recent_form)`, `evaluate_coaching_rules(edges, quarter_profile, phase_profile, starter_bench, rules, minimum_games)`.

- [ ] **Step 1: Add tests for edge direction, category caps, minimum two-signal Keys, confidence, and deduplication**

```python
from team_identity.coaching_rules import build_matchup_edges, evaluate_coaching_rules


def test_rules_cap_categories_and_dedupe_related_actions(self):
    edges = pd.DataFrame([
        {"team_abbreviation": "ATL", "opponent_abbreviation": "MIN", "metric_id": "oreb_pct", "team_percentile": 90, "opponent_percentile": 30, "percentile_gap": 60, "team_recent_improvement": 3.5, "opponent_recent_improvement": -2.0, "team_games": 12, "opponent_games": 12},
        {"team_abbreviation": "ATL", "opponent_abbreviation": "MIN", "metric_id": "second_chance_points", "team_percentile": 88, "opponent_percentile": 35, "percentile_gap": 53, "team_recent_improvement": 4.0, "opponent_recent_improvement": -1.0, "team_games": 12, "opponent_games": 12},
        {"team_abbreviation": "ATL", "opponent_abbreviation": "MIN", "metric_id": "tov_pct", "team_percentile": 75, "opponent_percentile": 25, "percentile_gap": 50, "team_recent_improvement": 2.0, "opponent_recent_improvement": -2.0, "team_games": 12, "opponent_games": 12},
    ])
    rules = [
        {"rule_id": "attack_glass", "category": "attack", "dedupe_group": "offensive_rebounding", "metrics": ["oreb_pct"], "minimum_signals": 1, "trigger": {"moderate_gap": 20, "strong_gap": 35, "extreme_gap": 50}, "priority_weight": 1.0, "headline": "Crash the offensive glass", "source_section": "offensive_identity"},
        {"rule_id": "attack_second_chance", "category": "attack", "dedupe_group": "offensive_rebounding", "metrics": ["second_chance_points"], "minimum_signals": 1, "trigger": {"moderate_gap": 20, "strong_gap": 35, "extreme_gap": 50}, "priority_weight": 0.9, "headline": "Extend possessions", "source_section": "offensive_identity"},
        {"rule_id": "key_possession_battle", "category": "key", "dedupe_group": "possession_battle", "metrics": ["oreb_pct", "tov_pct"], "minimum_signals": 2, "trigger": {"moderate_gap": 20, "strong_gap": 35, "extreme_gap": 50}, "priority_weight": 1.1, "headline": "Win the possession battle", "source_section": "matchup_overview"},
    ]

    out = evaluate_coaching_rules(edges, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), rules, {"strong": 10, "usable": 5})

    attacks = out[out["category"] == "attack"]
    keys = out[out["category"] == "key"]
    self.assertEqual(len(attacks), 1)
    self.assertEqual(attacks.iloc[0]["rule_id"], "attack_glass")
    self.assertEqual(len(keys), 1)
    self.assertEqual(keys.iloc[0]["evidence_count"], 2)
    self.assertEqual(keys.iloc[0]["confidence"], "Strong")
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
```

- [ ] **Step 3: Implement matchup edge construction**

```python
# scripts/team_identity/coaching_rules.py
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd


def build_matchup_edges(identity_summary: pd.DataFrame, recent_form: pd.DataFrame) -> pd.DataFrame:
    identity = identity_summary.rename(columns={
        "team_abbreviation": "team_abbreviation",
        "league_percentile": "team_percentile",
        "metric_value": "team_value",
        "games": "team_games",
    })
    opponent = identity_summary.rename(columns={
        "team_abbreviation": "opponent_abbreviation",
        "league_percentile": "opponent_percentile",
        "metric_value": "opponent_value",
        "games": "opponent_games",
    })
    pairs = identity.merge(opponent, on="metric_id", suffixes=("", "_opponent"))
    pairs = pairs[pairs["team_abbreviation"] != pairs["opponent_abbreviation"]].copy()
    pairs["percentile_gap"] = pairs["team_percentile"] - pairs["opponent_percentile"]

    recent_team = recent_form[["team_abbreviation", "metric_id", "improvement_delta"]].rename(columns={"improvement_delta": "team_recent_improvement"})
    recent_opp = recent_form[["team_abbreviation", "metric_id", "improvement_delta"]].rename(columns={"team_abbreviation": "opponent_abbreviation", "improvement_delta": "opponent_recent_improvement"})
    return pairs.merge(recent_team, on=["team_abbreviation", "metric_id"], how="left").merge(recent_opp, on=["opponent_abbreviation", "metric_id"], how="left")
```

- [ ] **Step 4: Implement scoring, confidence, dedupe, and category caps**

Use these normalized components:

```python
def _component(value: float, strong_threshold: float) -> float:
    if pd.isna(value) or strong_threshold <= 0:
        return 0.0
    return float(min(abs(value) / strong_threshold, 1.0))


def _confidence(team_games: int, opponent_games: int, evidence_count: int, minimum_games: dict[str, int], has_proxy: bool) -> str:
    sample = min(team_games, opponent_games)
    if not has_proxy and sample >= minimum_games["strong"] and evidence_count >= 2:
        return "Strong"
    if sample >= minimum_games["usable"] and evidence_count >= 1:
        return "Usable"
    return "Monitor"
```

Calculate:

```text
priority_score = 100 × priority_weight × (
  0.40 × matchup_severity
+ 0.20 × recent_confirmation
+ 0.15 × stability
+ 0.15 × phase_concentration
+ 0.10 × sample_confidence
)
```

Requirements:

- A rule triggers only when `evidence_count >= minimum_signals`.
- Keep the highest score within each `(team, opponent, category, dedupe_group)`.
- Keep at most three rows per `(team, opponent, category)`.
- A Key requires at least two distinct metric IDs.
- If no rule triggers in a category, exports later display `No strong validated priority`; the rules function must not create a fake row.
- Store evidence as stable, sorted JSON using `json.dumps(..., sort_keys=True, ensure_ascii=False)`.

- [ ] **Step 5: Expand the JSON rule set and test all three categories**

Add rules for:

- Attack: offensive glass, rim pressure, pace/transition, extra pass, second unit.
- Limit: rim protection, three-point denial, defensive rebounding, ball security, foul avoidance.
- Keys: possession battle, first five minutes, live-ball turnovers, shot-quality target, Q3 stabilization.

Every rule must name a `dedupe_group` and `source_section`.

- [ ] **Step 6: Run tests and commit**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
git add scripts/team_identity/coaching_rules.py analysis/team_identity_dashboard/config/coaching_rules.json tests/test_team_identity_dashboard.py
git commit -m "feat: add deterministic coaching rules engine"
```

---

### Task 7: Presentation Contract for Labels, Medals, Arrows, and Fire Triggers

**Files:**
- Create: `scripts/team_identity/presentation.py`
- Modify: `tests/test_team_identity_dashboard.py`
- Modify: `analysis/team_identity_dashboard/config/metric_registry.json`

**Interfaces:**
- Produces: `percentile_label`, `rank_icon`, `delta_display`, `trigger_level`, `decorate_identity_summary`, `decorate_priorities`.

- [ ] **Step 1: Add exact boundary and symbol-ownership tests**

```python
from team_identity.presentation import percentile_label, rank_icon, delta_display, trigger_level, decorate_priorities


def test_percentile_labels_cover_exact_boundaries(self):
    expected = {100: "Elite", 90: "Elite", 89: "Strong", 75: "Strong", 74: "Above average", 60: "Above average", 59: "Average", 40: "Average", 39: "Below average", 25: "Below average", 24: "Poor", 10: "Poor", 9: "Critical weakness", 0: "Critical weakness"}
    for value, label in expected.items():
        self.assertEqual(percentile_label(value), label)


def test_rank_icons_include_top_three_and_bottom_two(self):
    self.assertEqual(rank_icon(1, 15), "🥇")
    self.assertEqual(rank_icon(2, 15), "🥈")
    self.assertEqual(rank_icon(3, 15), "🥉")
    self.assertEqual(rank_icon(14, 15), "⬇️")
    self.assertEqual(rank_icon(15, 15), "⚠️")
    self.assertEqual(rank_icon(8, 15), "")


def test_delta_arrow_is_raw_direction_but_text_is_metric_direction(self):
    display = delta_display(-2.1, "lower_is_better", 0.1, "pp")
    self.assertEqual(display["arrow"], "▼")
    self.assertEqual(display["interpretation"], "improving")


def test_strong_rule_places_fire_once(self):
    priorities = pd.DataFrame([{"headline": "Crash the glass", "trigger_level": "strong", "evidence_text": "Elite OREB%", "rank_icon": "🥈"}])
    decorated = decorate_priorities(priorities)
    row = decorated.iloc[0]
    self.assertEqual(row["headline_display"].count("🔥"), 1)
    self.assertEqual(row["evidence_display"].count("🔥"), 0)
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
```

- [ ] **Step 3: Implement the presentation helpers**

```python
# scripts/team_identity/presentation.py
from __future__ import annotations

import math
import pandas as pd


def percentile_label(percentile: float) -> str:
    if pd.isna(percentile):
        return "Unavailable"
    if percentile >= 90: return "Elite"
    if percentile >= 75: return "Strong"
    if percentile >= 60: return "Above average"
    if percentile >= 40: return "Average"
    if percentile >= 25: return "Below average"
    if percentile >= 10: return "Poor"
    return "Critical weakness"


def rank_icon(rank: float, league_size: int) -> str:
    if pd.isna(rank) or league_size <= 0:
        return ""
    rank = int(rank)
    if rank == 1: return "🥇"
    if rank == 2: return "🥈"
    if rank == 3: return "🥉"
    if league_size >= 4 and rank == league_size - 1: return "⬇️"
    if rank == league_size: return "⚠️"
    return ""


def delta_display(raw_delta: float, direction: str, stable_epsilon: float, unit: str) -> dict[str, str]:
    if pd.isna(raw_delta):
        return {"arrow": "", "signed_value": "Unavailable", "interpretation": "unavailable"}
    arrow = "→" if abs(raw_delta) <= stable_epsilon else ("▲" if raw_delta > 0 else "▼")
    improvement = raw_delta if direction == "higher_is_better" else -raw_delta
    interpretation = "stable" if arrow == "→" else ("improving" if improvement > 0 else "declining")
    return {"arrow": arrow, "signed_value": f"{raw_delta:+.1f} {unit}".strip(), "interpretation": interpretation}


def trigger_level(percentile_gap: float, thresholds: dict[str, float]) -> str:
    magnitude = abs(percentile_gap)
    if magnitude >= thresholds["extreme_gap"]: return "extreme"
    if magnitude >= thresholds["strong_gap"]: return "strong"
    if magnitude >= thresholds["moderate_gap"]: return "moderate"
    return "none"
```

`decorate_priorities()` must assign display ownership:

- Fire icon belongs to `headline_display` for strong/extreme rules.
- Rank icon belongs to `evidence_display` when available.
- Delta arrow belongs to `delta_display`.
- Do not duplicate any of these in tooltip text; tooltip text uses words such as `rank 2 of 15` and `strong trigger`.

- [ ] **Step 4: Add formatting metadata to the metric registry**

For every metric, add:

```json
{
  "unit": "pp",
  "decimals": 1,
  "tooltip_format": "{label}: {value}; {percentile}th percentile; rank {rank} of {league_size}",
  "symbol_owners": {
    "rank": "evidence",
    "delta": "delta",
    "trigger": "headline"
  }
}
```

Use correct units per metric: `per_100`, `percent`, `pp`, `possessions`, `seconds`, or `points`.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
git add scripts/team_identity/presentation.py analysis/team_identity_dashboard/config/metric_registry.json tests/test_team_identity_dashboard.py
git commit -m "feat: add team identity presentation contract"
```

---

### Task 8: Validation, Output Writing, Immutable Snapshots, and Browser Payload

**Files:**
- Create: `scripts/team_identity/validation.py`
- Create: `scripts/team_identity/exports.py`
- Modify: `tests/test_team_identity_dashboard.py`

**Interfaces:**
- Produces: `validate_team_games`, `validate_starter_bench`, `validate_outputs`, `build_dashboard_payload`, `write_processed_outputs`, `write_snapshot`, `write_manifest`.

- [ ] **Step 1: Add tests for reciprocal validation, starter/bench reconciliation, snapshot collisions, and stable JSON**

```python
from team_identity.exports import stable_json_dumps, write_snapshot
from team_identity.validation import validate_team_games


def test_snapshot_refuses_different_content_for_existing_date(self):
    with tempfile.TemporaryDirectory() as raw_tmp:
        root = Path(raw_tmp)
        first = {"as_of_date": "2026-07-25", "teams": ["ATL"]}
        second = {"as_of_date": "2026-07-25", "teams": ["MIN"]}
        write_snapshot(root, "2026-07-25", {"payload.json": stable_json_dumps(first)})
        with self.assertRaisesRegex(FileExistsError, "snapshot collision"):
            write_snapshot(root, "2026-07-25", {"payload.json": stable_json_dumps(second)})
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
```

- [ ] **Step 3: Implement validation reports**

```python
# scripts/team_identity/validation.py
from __future__ import annotations

import pandas as pd


def validate_team_games(team_games: pd.DataFrame) -> dict:
    duplicate_count = int(team_games.duplicated(["game_id", "team_abbreviation"]).sum())
    reciprocal = team_games.merge(
        team_games[["game_id", "team_abbreviation", "opponent_abbreviation"]].rename(columns={"team_abbreviation": "opponent_abbreviation", "opponent_abbreviation": "team_abbreviation"}),
        on=["game_id", "team_abbreviation", "opponent_abbreviation"],
        how="left",
        indicator=True,
    )
    nonreciprocal = sorted(reciprocal.loc[reciprocal["_merge"] != "both", "game_id"].astype(str).unique())
    return {
        "status": "pass" if duplicate_count == 0 and not nonreciprocal else "fail",
        "duplicate_team_game_rows": duplicate_count,
        "nonreciprocal_game_ids": nonreciprocal,
    }
```

Add `validate_starter_bench()` with tolerances:

- Points shares sum to `100 ± 0.1` when team points are positive.
- Minutes shares sum to `100 ± 0.1` when team minutes are positive.
- No role group outside `starters`, `bench`.

Add `validate_outputs()` that fails required outputs and warns for optional quarter, phase, and lineup outputs.

- [ ] **Step 4: Implement deterministic output and snapshot writers**

```python
# scripts/team_identity/exports.py
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


def stable_json_dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_snapshot(snapshot_root: Path, as_of_date: str, files: dict[str, str]) -> dict[str, str]:
    target = snapshot_root / as_of_date
    target.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for relative_name, content in files.items():
        path = target / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = _sha256(content)
        if path.exists() and _sha256(path.read_text(encoding="utf-8")) != digest:
            raise FileExistsError(f"snapshot collision for {path}")
        path.write_text(content, encoding="utf-8")
        hashes[relative_name] = digest
    return hashes
```

Implement `build_dashboard_payload()` with top-level keys:

```json
{
  "meta": {},
  "teams": [],
  "identity": [],
  "recent_form": [],
  "quarters": [],
  "phases": [],
  "starter_bench": [],
  "validated_lineups": [],
  "matchup_edges": [],
  "coaching_priorities": [],
  "metric_registry": {},
  "availability": {}
}
```

Use `DataFrame.where(pd.notna(df), None).to_dict("records")` before JSON serialization so JavaScript receives `null`, not `NaN`.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
git add scripts/team_identity/validation.py scripts/team_identity/exports.py tests/test_team_identity_dashboard.py
git commit -m "feat: add validation snapshots and dashboard payload"
```

---

### Task 9: Staged CLI Builder and End-to-End Fixture Build

**Files:**
- Create: `scripts/build_team_identity_dashboard.py`
- Modify: `tests/test_team_identity_dashboard.py`
- Create: `analysis/team_identity_dashboard/README.md`
- Create: `analysis/team_identity_dashboard/methodology.md`

**Interfaces:**
- Produces CLI stages `data`, `rules`, `dashboard`, `brief`, `all`.
- Orchestrates all functions from Tasks 1–8.

- [ ] **Step 1: Add an end-to-end CLI fixture test**

Use the existing Midseason Team Grades test pattern: write temporary parquet/CSV fixtures, invoke the script through `subprocess.run`, and assert exact output names.

```python
def test_cli_builds_all_required_outputs(self):
    with tempfile.TemporaryDirectory() as raw_tmp:
        root = Path(raw_tmp)
        config_path = self._write_full_fixture_bundle(root)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_team_identity_dashboard.py"), "--config", str(config_path), "--stage", "all"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        output_root = root / "analysis" / "team_identity_dashboard"
        expected = [
            output_root / "data/processed/team_game_identity_2026.csv",
            output_root / "data/processed/team_identity_summary_2026.csv",
            output_root / "data/processed/team_recent_form_2026.csv",
            output_root / "data/processed/team_starter_bench_profile_2026.csv",
            output_root / "data/processed/matchup_identity_edges_2026.csv",
            output_root / "data/processed/coaching_priorities_2026.csv",
            output_root / "data/viz/team_identity_dashboard_2026.json",
            output_root / "data/manifests/run_manifest_2026.json",
        ]
        for path in expected:
            self.assertTrue(path.exists(), msg=str(path))
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
python -m unittest tests.test_team_identity_dashboard.TeamIdentityDashboardTest.test_cli_builds_all_required_outputs -v
```

- [ ] **Step 3: Implement CLI path mapping and stages**

```python
# scripts/build_team_identity_dashboard.py
#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from team_identity.loaders import load_config_bundle, load_identity_sources, resolve_output_paths

STAGES = {"data", "rules", "dashboard", "brief", "all"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WNBA Team Identity Dashboard outputs.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--stage", choices=sorted(STAGES), default="all")
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--featured-team", default=None)
    parser.add_argument("--featured-opponent", default=None)
    return parser.parse_args()
```

Implement `build_outputs(config, stage) -> dict` with this exact dependency order:

1. Load sources.
2. Build and validate canonical team games.
3. Build identity summary and recent form.
4. Build quarter, phase, starter/bench, and validated-lineup outputs.
5. Build matchup edges for all ordered team pairs.
6. Evaluate and decorate coaching priorities.
7. Write processed outputs.
8. Build and write JSON payload.
9. Build dashboard and coach brief for `dashboard`, `brief`, or `all` stages.
10. Write manifest and immutable snapshot.

`--as-of-date latest` resolves to the latest eligible `game_date` after source loading. Store the resolved ISO date in all outputs and the manifest.

- [ ] **Step 4: Write README and methodology with runnable commands and formulas**

README command:

```bash
python scripts/build_team_identity_dashboard.py \
  --config analysis/team_identity_dashboard/config/team_identity_config.json \
  --stage all
```

Methodology must document:

- Possession estimate formula.
- Four Factors source reuse.
- Percentile direction and tie method.
- Last-five selection.
- Quarter rating availability.
- Transition and half-court proxies.
- Starter/bench action-share proxy.
- Lineup validation gates.
- Rules score weights.
- Confidence labels.
- Symbol ownership.

- [ ] **Step 5: Run the CLI test and full suite**

```bash
python -m unittest tests.test_team_identity_dashboard.TeamIdentityDashboardTest.test_cli_builds_all_required_outputs -v
python -m unittest tests/test_team_identity_dashboard.py -v
```

Expected: pass.

- [ ] **Step 6: Commit the orchestrator and documentation**

```bash
git add scripts/build_team_identity_dashboard.py analysis/team_identity_dashboard/README.md analysis/team_identity_dashboard/methodology.md tests/test_team_identity_dashboard.py
git commit -m "feat: add staged team identity build pipeline"
```

---

### Task 10: Single-File Dashboard UI

**Files:**
- Create: `analysis/team_identity_dashboard/dashboard/team_identity_dashboard.template.html`
- Modify: `scripts/team_identity/exports.py`
- Modify: `tests/test_team_identity_dashboard.py`

**Interfaces:**
- Produces: `render_dashboard_html(payload: dict, template_path: Path, output_path: Path) -> Path`.

- [ ] **Step 1: Add a rendering test for embedded data, navigation, controls, and accessibility hooks**

```python
from team_identity.exports import render_dashboard_html


def test_render_dashboard_html_is_single_file_and_accessible(self):
    with tempfile.TemporaryDirectory() as raw_tmp:
        root = Path(raw_tmp)
        template = root / "template.html"
        output = root / "dashboard.html"
        template.write_text("<html><body><script id='dashboard-data' type='application/json'>__DASHBOARD_DATA__</script><main id='app'></main></body></html>", encoding="utf-8")
        render_dashboard_html({"meta": {"as_of_date": "2026-07-25"}, "teams": []}, template, output)
        html = output.read_text(encoding="utf-8")
        self.assertNotIn("__DASHBOARD_DATA__", html)
        self.assertIn('"as_of_date": "2026-07-25"', html)
        self.assertNotIn("fetch(", html)
```

- [ ] **Step 2: Run the rendering test and verify it fails**

```bash
python -m unittest tests.test_team_identity_dashboard.TeamIdentityDashboardTest.test_render_dashboard_html_is_single_file_and_accessible -v
```

- [ ] **Step 3: Build the semantic HTML structure**

The template must include:

```html
<body>
  <a class="skip-link" href="#main-content">Skip to dashboard content</a>
  <div class="app-shell">
    <nav class="left-rail" aria-label="Dashboard sections">...</nav>
    <main id="main-content">
      <header id="matchup-header">...</header>
      <section id="kpi-ribbon" aria-labelledby="kpi-title">...</section>
      <section id="identity-fingerprints">...</section>
      <section id="recent-form">...</section>
      <section id="quarter-profile">...</section>
      <section id="game-phases">...</section>
      <section id="lineups">...</section>
    </main>
    <aside id="coaching-rail" aria-label="Coaching priorities">...</aside>
  </div>
  <script id="dashboard-data" type="application/json">__DASHBOARD_DATA__</script>
</body>
```

Global controls must be native labeled `<select>` elements for team, opponent, as-of date, and comparison window.

- [ ] **Step 4: Implement rendering functions in vanilla JavaScript**

Required functions:

```javascript
const STORAGE_KEY = "teamIdentityDashboard.matchup.v1";

function readPayload() {
  return JSON.parse(document.getElementById("dashboard-data").textContent);
}

function resolveInitialMatchup(payload) {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = { team: params.get("team"), opponent: params.get("opponent") };
  if (fromUrl.team && fromUrl.opponent) return fromUrl;
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  if (saved?.team && saved?.opponent) return saved;
  return { team: payload.meta.featured_team, opponent: payload.meta.featured_opponent };
}

function saveMatchup(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ team: state.team, opponent: state.opponent }));
}
```

Also implement:

- `renderKpis(state)`
- `renderFingerprint(group, state)`
- `renderRecentForm(state)`
- `renderQuarterHeatmap(state)`
- `renderPhaseMatrix(state)`
- `renderLineupPanel(state)`
- `renderCoachingRail(mode, state)`
- `focusEvidence(sourceSection, metricId)`

Metric rows and coaching cards must include `data-metric-id` and `data-source-section`. Clicking a coaching card scrolls to the supporting section and applies a temporary `.evidence-focus` class.

- [ ] **Step 5: Implement visual and responsive CSS**

Requirements:

- Desktop layout: `220px minmax(0, 1fr) 320px`.
- Tablet layout: left rail collapses to horizontal navigation; coaching rail moves below main content.
- Use CSS custom properties for dark navy surfaces, neutral text, blue/violet/gold/coral/teal accents.
- Use patterns, borders, labels, and icons so color is never the sole status indicator.
- Horizontal percentile bars include visible text labels.
- Heatmap cells include numeric text.
- Respect `prefers-reduced-motion`.
- Tooltips are focusable buttons or use `aria-describedby`; do not rely on hover-only content.

- [ ] **Step 6: Implement Python payload injection**

```python
def render_dashboard_html(payload: dict, template_path: Path, output_path: Path) -> Path:
    template = template_path.read_text(encoding="utf-8")
    if template.count("__DASHBOARD_DATA__") != 1:
        raise ValueError("dashboard template must contain exactly one __DASHBOARD_DATA__ marker")
    serialized = stable_json_dumps(payload).replace("</script>", "<\\/script>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template.replace("__DASHBOARD_DATA__", serialized), encoding="utf-8")
    return output_path
```

- [ ] **Step 7: Run tests and perform local structural checks**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
python scripts/build_team_identity_dashboard.py --config analysis/team_identity_dashboard/config/team_identity_config.json --stage dashboard
python - <<'PY'
from pathlib import Path
html = Path("analysis/team_identity_dashboard/dashboard/team_identity_dashboard.html").read_text(encoding="utf-8")
assert "__DASHBOARD_DATA__" not in html
assert "fetch(" not in html
assert 'id="coaching-rail"' in html
assert '@media print' in html
print("dashboard structural checks passed")
PY
```

- [ ] **Step 8: Commit the dashboard UI**

```bash
git add analysis/team_identity_dashboard/dashboard/team_identity_dashboard.template.html scripts/team_identity/exports.py tests/test_team_identity_dashboard.py
git commit -m "feat: add single file team identity dashboard"
```

---

### Task 11: Print Coach Brief

**Files:**
- Modify: `analysis/team_identity_dashboard/dashboard/team_identity_dashboard.template.html`
- Modify: `scripts/team_identity/exports.py`
- Modify: `tests/test_team_identity_dashboard.py`

**Interfaces:**
- Produces: `render_featured_coach_brief(payload, team, opponent, output_path) -> Path`.

- [ ] **Step 1: Add coach-brief rendering tests**

```python
from team_identity.exports import render_featured_coach_brief


def test_coach_brief_contains_snapshot_and_priority_sections(self):
    payload = {
        "meta": {"as_of_date": "2026-07-25", "snapshot_id": "2026-07-25", "featured_team": "ATL", "featured_opponent": "MIN"},
        "teams": [{"team_abbreviation": "ATL", "team_name": "Atlanta Dream"}, {"team_abbreviation": "MIN", "team_name": "Minnesota Lynx"}],
        "coaching_priorities": [
            {"team_abbreviation": "ATL", "opponent_abbreviation": "MIN", "category": "attack", "headline_display": "Crash the glass 🔥", "evidence_display": "Elite OREB% 🥈", "confidence": "Strong"}
        ],
        "identity": [], "recent_form": [], "quarters": [], "phases": [], "starter_bench": [], "validated_lineups": []
    }
    with tempfile.TemporaryDirectory() as raw_tmp:
        path = Path(raw_tmp) / "brief.html"
        render_featured_coach_brief(payload, "ATL", "MIN", path)
        html = path.read_text(encoding="utf-8")
        self.assertIn("As of July 25, 2026", html)
        self.assertIn("ATTACK", html)
        self.assertIn("Crash the glass", html)
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
python -m unittest tests.test_team_identity_dashboard.TeamIdentityDashboardTest.test_coach_brief_contains_snapshot_and_priority_sections -v
```

- [ ] **Step 3: Implement a dedicated static print renderer**

The generated brief must include, in order:

1. Matchup and snapshot header.
2. Eight KPI cells.
3. Offensive and defensive fingerprints.
4. Last-five change table.
5. Q1–Q4 profile.
6. Attack, Limit, and Keys columns.
7. Five game-phase rows.
8. Validated lineup or starter/bench summary.
9. Data-quality footnote.

Use escaped HTML for all text values. Implement a standard-library helper:

```python
from html import escape


def _html(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)
```

If a category has no recommendation, render `No strong validated priority`.

- [ ] **Step 4: Add print CSS to both dashboard and coach brief**

```css
@media print {
  @page { size: landscape; margin: 0.35in; }
  body { background: #fff; color: #111; }
  .left-rail, .global-controls, .interactive-only, .print-button { display: none !important; }
  .app-shell { display: block; }
  .card { break-inside: avoid; box-shadow: none; border: 1px solid #bbb; }
  a[href]::after { content: ""; }
}
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tests/test_team_identity_dashboard.py -v
git add analysis/team_identity_dashboard/dashboard/team_identity_dashboard.template.html scripts/team_identity/exports.py tests/test_team_identity_dashboard.py
git commit -m "feat: add print ready coaching brief"
```

---

### Task 12: GitHub Actions, Full Verification, and Generated-Output Policy

**Files:**
- Create: `.github/workflows/team-identity-dashboard.yml`
- Modify: `analysis/team_identity_dashboard/README.md`
- Modify: `.gitignore` only if the repository already ignores generated analysis outputs by pattern.

**Interfaces:**
- Produces a manually dispatched, test-gated build compatible with repository conventions.

- [ ] **Step 1: Create the workflow with manual inputs**

```yaml
name: Team Identity Dashboard

on:
  workflow_dispatch:
    inputs:
      as_of_date:
        description: "ISO date or latest"
        required: true
        type: string
        default: "latest"
      comparison_window:
        description: "Recent game count"
        required: true
        type: choice
        options: ["3", "5", "10"]
        default: "5"
      featured_team:
        description: "Featured team abbreviation"
        required: true
        type: string
        default: "GSV"
      featured_opponent:
        description: "Featured opponent abbreviation"
        required: true
        type: string
        default: "MIN"
      run_tests:
        description: "Run Team Identity Dashboard tests"
        required: true
        type: boolean
        default: true
      commit_outputs:
        description: "Commit generated dashboard outputs"
        required: true
        type: boolean
        default: false

jobs:
  team-identity-dashboard:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run tests
        if: ${{ inputs.run_tests }}
        run: python -m unittest tests/test_team_identity_dashboard.py -v
      - name: Build dashboard
        run: |
          python scripts/build_team_identity_dashboard.py \
            --config analysis/team_identity_dashboard/config/team_identity_config.json \
            --stage all \
            --as-of-date "${{ inputs.as_of_date }}" \
            --featured-team "${{ inputs.featured_team }}" \
            --featured-opponent "${{ inputs.featured_opponent }}"
      - name: Write build summary
        run: cat analysis/team_identity_dashboard/data/manifests/run_manifest_2026.json >> "$GITHUB_STEP_SUMMARY"
      - name: Commit generated outputs
        if: ${{ inputs.commit_outputs }}
        run: |
          git add analysis/team_identity_dashboard/data analysis/team_identity_dashboard/dashboard/team_identity_dashboard.html analysis/team_identity_dashboard/exports
          if git diff --cached --quiet; then
            echo "No Team Identity Dashboard output changes to commit"
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git commit -m "chore: refresh team identity dashboard"
          git push
```

The CLI must read `comparison_window` from config or a new `--recent-window` argument. Add that argument before committing the workflow so the selected input is actually passed and used.

- [ ] **Step 2: Run the complete verification suite locally**

```bash
python -m unittest tests/test_midseason_team_grades.py -v
python -m unittest tests/test_team_identity_dashboard.py -v
python scripts/build_midseason_team_grades.py \
  --config analysis/midseason_team_grades/config/midseason_team_grades_config.json \
  --stage all
python scripts/build_team_identity_dashboard.py \
  --config analysis/team_identity_dashboard/config/team_identity_config.json \
  --stage all \
  --as-of-date latest \
  --recent-window 5
```

Expected:

- Both test files pass.
- Existing Midseason Team Grades outputs still build.
- Team Identity Dashboard outputs build without traceback.
- Manifest `validation.status` is `pass` or `degraded_optional`.
- Dashboard HTML contains embedded JSON and no core-data fetch.
- Featured coach brief includes the resolved snapshot date.

- [ ] **Step 3: Validate output schemas and symbol rules with a one-off audit script**

```bash
python - <<'PY'
import json
from pathlib import Path
import pandas as pd

root = Path("analysis/team_identity_dashboard")
identity = pd.read_csv(root / "data/processed/team_identity_summary_2026.csv")
recent = pd.read_csv(root / "data/processed/team_recent_form_2026.csv")
priorities = pd.read_csv(root / "data/processed/coaching_priorities_2026.csv")
payload = json.loads((root / "data/viz/team_identity_dashboard_2026.json").read_text(encoding="utf-8"))

assert identity[["team_abbreviation", "metric_id"]].duplicated().sum() == 0
assert set(identity["availability"].dropna()) <= {"available", "estimated", "proxy", "unavailable"}
assert set(recent["interpretation"].dropna()) <= {"improving", "declining", "stable"}
assert priorities.groupby(["team_abbreviation", "opponent_abbreviation", "category"]).size().max() <= 3
for _, row in priorities.iterrows():
    assert str(row.get("headline_display", "")).count("🔥") <= 2
    assert "🔥" not in str(row.get("evidence_display", ""))
assert payload["meta"]["recent_window"] == 5
print("schema and symbol audit passed")
PY
```

- [ ] **Step 4: Update README with workflow and output policy**

Document:

- Workflow is manual-only for the first stable release.
- `commit_outputs=false` is the safe default.
- Snapshots are immutable.
- PNG export is deferred.
- In-dashboard rule editing is deferred.
- Validated lineup metrics may be absent; starter/bench remains the guaranteed baseline.

- [ ] **Step 5: Commit the workflow and final documentation**

```bash
git add .github/workflows/team-identity-dashboard.yml analysis/team_identity_dashboard/README.md
git commit -m "ci: add team identity dashboard workflow"
```

---

## Self-Review Results

### Spec coverage

- Coaching-first hierarchy: Tasks 10–11.
- Canonical team-game data: Task 2.
- Season and last-five comparison: Task 3.
- Quarter and game phases: Task 4.
- Validated lineup plus starter/bench fallback: Task 5.
- Deterministic Attack / Limit / Keys: Task 6.
- Percentile labels, medals, arrows, and fire icon: Task 7.
- Availability states, validation, manifests, snapshots: Task 8.
- Portable HTML and print brief: Tasks 10–11.
- Manual GitHub Actions workflow: Task 12.
- WPBA-compatible registry and fallbacks: Tasks 1 and 9 methodology.

### Placeholder scan

The implementation plan contains no `TBD`, `TODO`, `implement later`, or unspecified error-handling steps. The validated-lineup aggregation is intentionally specified as a strict possession-based interface with named output measures and statuses; it must not be replaced by scoring-event pseudo-possessions.

### Type and naming consistency

- `team_abbreviation`, `opponent_abbreviation`, `metric_id`, `league_percentile`, `league_rank`, `availability`, and `as_of_date` remain consistent across tasks.
- The rolling-form field is `improvement_delta`; rules rename it to team/opponent recent improvement.
- The lineup fallback statuses consistently begin with `fallback_starter_bench_`.
- Browser payload keys match the generated dataset names.

## Execution Handoff

Plan implementation should occur in an isolated worktree created at execution time.

Two execution options:

1. **Subagent-Driven — recommended:** dispatch a fresh implementation agent per task, run tests, and review each task before proceeding.
2. **Inline Execution:** execute tasks in this session in batches with review checkpoints.
