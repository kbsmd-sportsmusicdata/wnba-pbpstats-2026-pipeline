# Task 9 — Optional Historical Context Report

## Status

Implemented descriptive historical context in
`scripts/standings_playoff_forecast/historical_context.py`.  It does not train
a model, modify simulation inputs, or make a current-season forecast depend on
prior partitions.

## Discovery contract

`discover_history(normalized_root, forecast_season)` returns existing directory
partitions named exactly `season=<numeric year>` where the year is strictly less
than the forecast season, ordered ascending by year.  Current, future,
malformed, and non-directory entries are ignored.  An absent root returns an
empty list.

`build_historical_context` reads `team_game.parquet` from those partitions.  No
discovered partitions yields an empty DataFrame with the stable schema below,
never an error.  A partition missing its parquet is reported as
`team_game_unavailable`.

Historical competition rules come from the injected/default per-season config
loader.  An unavailable or invalid historical config becomes an explicit
`season_config_unavailable` availability row and is excluded from all
aggregates; no historical playoff cutoff is inferred from 2026 rules.

## Output schema

The long-form `historical_context` DataFrame has these columns:

```text
context_level, metric, season, season_count, seed_band, qualifier_rank,
team_id, target_progress_pct, as_of_progress_pct, as_of_net_rating,
final_rank, value, sample_size, availability_status
```

It supplies per-season and cross-season aggregate rows for generalized final
qualifier/first-out wins and win percentages, wins and win-percentage cutline
gaps, plus raw final Net Rating observations by `top_seed`, `playoff_field`,
and `outside_playoff` bands.  The output also includes team-level historical
as-of outcomes and aggregate `same_progress_playoff_rate` and
`same_progress_average_final_rank` benchmarks.

The cutline uses `playoff_qualifiers` from each historical season config; it is
not hardcoded as 8/9.  Final standings are descriptive and deterministic:
final wins, losses, cumulative point differential, then team ID break ties.

## Progress matching and leakage boundary

For a requested `target_progress_pct`, each historical team contributes its
latest row whose `season_progress_pct <= target_progress_pct`; this is a
deterministic nearest/as-of match and cannot select a future row.  The module
calculates the frozen as-of Net Rating from only those rows' margin and
possessions.  It only then joins the frozen rows to full completed-season final
ranks and qualifier outcomes.

Final seed-band Net Ratings are possession-weighted from all completed games
in each historical season.  They are descriptive final outcomes, not
predictors.  Historical PBPStats snapshots are not read or joined.

Missing required columns, wrong partition season values, duplicate
`season/team_id/game_id` rows, invalid identifiers, non-finite/out-of-range
progress, invalid metrics, and non-positive possessions fail closed.  A season
that does not have every configured team completing every configured regular
season game is reported as `incomplete_season_outcomes` and excluded rather
than silently biasing benchmarks.

## TDD cycles

1. Added discovery, no-history, generalized benchmarks, as-of leakage,
   unavailable-config, and duplicate-row tests.  The focused suite first failed
   with `ModuleNotFoundError` for the new module; implementation made all six
   tests green.
2. Added a hand-derived possession-weighted final Net Rating expectation.  It
   failed RED at `504.5` (an invalid average of per-game ratings) versus the
   expected `15.0`; final Net Rating was changed to total margin divided by
   total possessions and the test went green.
3. Removed the non-finite progress guard, added its focused test, and observed
   RED because no `ValueError` was raised.  Restoring the guard made the
   seven-test focused suite green.

## Verification

```text
PYTHONPYCACHEPREFIX=/private/tmp/wnba_forecast_pycache \
  /private/tmp/wnba_forecast_venv/bin/python -m unittest \
  tests/test_standings_playoff_forecast_history.py
# Ran 7 tests — OK

PYTHONPYCACHEPREFIX=/private/tmp/wnba_forecast_pycache \
  /private/tmp/wnba_forecast_venv/bin/python -m unittest discover -s tests
# Ran 126 tests — OK

PYTHONPYCACHEPREFIX=/private/tmp/wnba_forecast_pycache \
  /private/tmp/wnba_forecast_venv/bin/python -m compileall -q \
  scripts/standings_playoff_forecast tests/test_standings_playoff_forecast_history.py
# exit 0

git diff --check
# exit 0
```

## Files

- `scripts/standings_playoff_forecast/historical_context.py`
- `tests/test_standings_playoff_forecast_history.py`
- `.superpowers/sdd/2026-08-09-wnba-standings-playoff-forecast-implementation-plan/task-9-report.md`

## Self-review

- No model fitting, simulation, current forecast invocation, or historical
  PBPStats enrichment was added.
- No prior-season config is guessed from 2026; missing config is explicit and
  unavailable.
- A current 2026 run with no prior partitions receives a valid empty result.
- The remaining design dependency is data availability: prior seasons need
  their own verified season configs and complete canonical partitions before
  they can contribute to benchmarks.
