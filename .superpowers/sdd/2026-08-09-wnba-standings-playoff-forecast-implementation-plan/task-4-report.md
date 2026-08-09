# Task 4 — Standings and Head-to-Head Report

## Implementation

- Added `scripts/standings_playoff_forecast/standings.py`.
- `build_current_standings(team_games, cfg)` aggregates every normalized directional `game_id` / `team_id` row exactly once into unranked GP, W, L, win percentage, PF, PA, and point differential.
- `build_head_to_head(team_games)` groups by ordered team/opponent pairs, retaining reciprocal rows such as A-vs-B and B-vs-A as separate records.
- `reconcile_standings(...)` validates standings accounting at every cutoff. At or after the latest completed-game cutoff it pivots SportsDataverse's long-form `stat_name` / `value` rows and requires exact team-level GP/W/L agreement. At earlier historical cutoffs it validates only derived GP = W + L and point differential = PF - PA, so a newer source snapshot cannot leak forward results.
- Duplicate directional game/team rows fail closed rather than being silently double-counted. Tie ordering and forecast-model behavior are intentionally out of scope.

## Reconciliation Semantics

SportsDataverse stores standings one statistic per row. This implementation consumes `stat_name` values `wins` and `losses`, normalizes source team IDs, and derives source GP as W + L. A caller supplies the cutoff and latest completed-game date explicitly. Equal or later dates perform source reconciliation; only earlier dates perform internal invariant validation.

## Files Changed

- `scripts/standings_playoff_forecast/standings.py`
- `tests/test_standings_playoff_forecast_standings.py`
- This report

## TDD Evidence

RED was observed before production code existed:

```text
ModuleNotFoundError: No module named 'standings_playoff_forecast.standings'
Ran 5 tests ... FAILED (errors=5)
```

The test fixture is hand checked: four games yield A 3 GP / 1-2 / 244 PF / 241 PA / +3; B 3 GP / 2-1 / 226 PF / 231 PA / -5; C 2 GP / 1-1 / 162 PF / 160 PA / +2. It also asserts directional A-vs-B (1-1, 159-151, +8) separately from B-vs-A (1-1, 151-159, -8).

GREEN:

```text
/private/tmp/wnba_forecast_venv/bin/python -m unittest tests/test_standings_playoff_forecast_standings.py
Ran 5 tests ... OK
```

## Verification and Self-Review

- Focused standings suite: 5 tests passed.
- Full suite: 52 tests passed.
- `git diff --check`: passed.
- Reviewed aggregation keys, empty-table contracts, long-form source parsing, ID normalization, exact GP/W/L comparison, and the historical no-future-snapshot branch.

## Data-Freshness Concern

The checked-in current schedule produces 436 directional rows through 2026-08-01, but its `standings_2026.parquet` reports only 1–2 games per team. A live latest-cutoff reconciliation therefore correctly fails for all teams until the SportsDataverse standings snapshot is refreshed. This is not a long-form schema ambiguity: `wins` and `losses` are present and unambiguous. It is a stale-source issue; no implementation relaxation was made.

## Fix Round 1 — Review Findings

### Fixes

- Changed reconciliation semantics so only `cutoff < latest_completed_game_date` is historical. An equal or later cutoff now requires exact source GP/W/L reconciliation, including off days after the last completed game.
- Changed standings aggregation to group by `team_id` only and head-to-head aggregation to group by ordered `team_id` / `opponent_id` only.
- Presentation metadata is now attached after aggregation. Conflicting name, abbreviation, or franchise metadata for a stable team or ordered pair fails clearly instead of producing partial duplicate records.

### TDD Evidence

Added the following focused regression tests before changing production code:

- `test_later_than_latest_cutoff_rejects_stale_source_record`
- `test_current_standings_rejects_metadata_drift_instead_of_splitting_a_team_record`
- `test_head_to_head_rejects_metadata_drift_instead_of_splitting_a_pair_record`

RED command:

```text
/private/tmp/wnba_forecast_venv/bin/python -m unittest tests/test_standings_playoff_forecast_standings.py
Ran 8 tests ... FAILED (failures=3)
```

The failures were the expected absent `ValueError` cases: a 2026-06-05 cutoff after a 2026-06-04 latest game accepted a stale source record, and team/pair metadata drift did not fail instead of creating split partial records.

GREEN command:

```text
/private/tmp/wnba_forecast_venv/bin/python -m unittest tests/test_standings_playoff_forecast_standings.py
Ran 8 tests ... OK
```

Full-suite command:

```text
/private/tmp/wnba_forecast_venv/bin/python -m unittest discover -s tests -p 'test_*.py'
Ran 55 tests ... OK
```

### Files Changed

- `scripts/standings_playoff_forecast/standings.py`
- `tests/test_standings_playoff_forecast_standings.py`
- This report

### Final Review

- `git diff --check` passed.
- The new later-cutoff test would fail if reconciliation reverted to equality-only behavior.
- The metadata-drift tests would fail if mutable metadata returned to aggregation keys or conflicting attachments were silently accepted.
