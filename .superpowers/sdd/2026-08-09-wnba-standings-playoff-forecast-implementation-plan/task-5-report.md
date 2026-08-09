# Task 5 — Official WNBA Tiebreak Engine Report

## Implementation

- Added `scripts/standings_playoff_forecast/tiebreaks.py` with the required `rank_teams(final_team_state, all_games, cfg)` and `resolve_tied_group(team_ids, final_team_state, all_games, cfg)` entry points.
- The `CRITERIA` registry maps the four configured names verbatim to criterion functions. The engine consumes `cfg.tiebreaks` in its configured order; unknown names fail before ranking, even when no record is tied.
- `rank_teams` first groups teams by exact final win percentage using `Fraction(wins, wins + losses)`. Official criteria can only reorder teams inside one equal-record group.
- Directional all-games rows are normalized and uniquely keyed by `game_id` / `team_id`. Reciprocal rows remain separate team perspectives; duplicate directional rows fail instead of being double-counted.

## Criterion Semantics

1. `head_to_head_win_pct`: win percentage from each tied team's directional rows whose opponent is also in the current tied group.
2. `record_vs_final_500_plus`: recomputes the `.500+` opponent set from the supplied final state's wins and losses, then evaluates each tied team's directional record against that set.
3. `head_to_head_point_diff`: sums directional margins only in games between members of the current tied group.
4. `overall_point_diff`: reads the supplied final state's overall point differential.

Fractions are used for record comparisons so equality does not depend on floating-point rounding.

## Restart Algorithm

The resolver evaluates one criterion and partitions the current group by score, highest first. If the whole group remains tied, it advances to the next configured criterion. If at least one team is separated, every still-tied subgroup is resolved recursively. With `cfg.multi_team_restart_after_elimination` enabled, that recursive call restarts at criterion 1; otherwise it continues at the next criterion.

The hand-checked restart fixture makes the semantic difference observable. Across A/B/C, A is 3-1 while B and C are both 2-3. In the reduced B/C group, B wins the series 2-1, but C has the better series point differential because its one win is by 20 and B's two wins are by one each. Restart therefore yields `A, B, C`; continuing without restart yields `A, C, B`.

## Result and Fallback Contract

Both public entry points return the immutable:

```python
TiebreakResult(
    ordered_team_ids: tuple[str, ...],
    fallback_count: int,
)
```

If a tied subgroup survives every configured official criterion, only normalized stable `team_id` sorts that subgroup. This is explicitly a deterministic non-official fallback. `fallback_count` increments once per unresolved subgroup and is summed through recursive subgroups and final-record groups, so Task 8 can aggregate it and Task 11 can record it without re-running or inferring tiebreak behavior.

## Files Changed

- `scripts/standings_playoff_forecast/tiebreaks.py`
- `tests/test_standings_playoff_forecast_tiebreaks.py`
- `.superpowers/sdd/2026-08-09-wnba-standings-playoff-forecast-implementation-plan/task-5-report.md`

## TDD RED/GREEN Evidence

All test runs used `/private/tmp/wnba_forecast_venv/bin/python`. That interpreter does not contain `pytest`, so the repository's `unittest`-compatible suite was used; no alternate Python was substituted.

- Criterion 1 RED: input order `A, B` remained unchanged instead of the hand-checked H2H result `B, A`. GREEN: the focused criterion test passed after directional per-team H2H scoring was implemented.
- Criterion 2 RED: input order `B, A` remained unchanged instead of `A, B`; A was 1-0 against final `.500+` opponent X while B was 0-1, and results against final sub-.500 Z were excluded. GREEN: the criterion test passed after `.500+` eligibility was recomputed from final W/L.
- Criterion 3 RED: input order `B, A` remained unchanged instead of `A, B`; the 1-1 series margins were A +20/-1 and B +1/-20. GREEN: the criterion test passed after tied-group margins were summed.
- Criterion 4 RED: input order `A, B` remained unchanged instead of `B, A` for final point differentials +5 and +20. GREEN: the criterion test passed after final-state point differential scoring was added.
- Multi-team restart RED: the engine returned `A, C, B`, the no-restart outcome, rather than `A, B, C`. GREEN: the recursive restart implementation passed both restart-enabled and restart-disabled assertions on the same fixture.
- Fallback RED: the exhausted group preserved normalized input order `2, 10` with count zero instead of stable normalized-ID order `10, 2` with count one. GREEN: the deterministic fallback and explicit counter passed.
- Final-record ordering RED: `rank_teams` preserved input `D, C, B, A` rather than record-first `A, B, C, D`. GREEN: exact win-percentage grouping plus within-group resolution passed.
- Fail-closed RED cases also covered unknown configured criteria, duplicate directional game rows, and normalized final-team ID collisions before their production guards were added.

Focused GREEN command:

```text
/private/tmp/wnba_forecast_venv/bin/python -m unittest tests.test_standings_playoff_forecast_tiebreaks -v
Ran 10 tests ... OK
```

Full-suite command:

```text
/private/tmp/wnba_forecast_venv/bin/python -m unittest discover -s tests -v
Ran 65 tests ... OK
```

Additional gates:

```text
PYTHONPYCACHEPREFIX=/private/tmp/wnba_forecast_pycache /private/tmp/wnba_forecast_venv/bin/python -m py_compile scripts/standings_playoff_forecast/tiebreaks.py tests/test_standings_playoff_forecast_tiebreaks.py
git diff --check
```

Both exited successfully.

## Self-Review

- Confirmed the registry contains exactly the four season-configurable criteria and no hardcoded 2026 sequence.
- Confirmed primary record grouping occurs before every official criterion.
- Confirmed `.500+` membership derives from the supplied final state, not current standings or a cached pre-simulation set.
- Confirmed reciprocal rows contribute once to each team's record and normalized duplicate `game_id` / `team_id` rows fail closed.
- Confirmed restart happens only after a criterion separates the current group; an all-tied group advances rather than looping.
- Confirmed fallback is reached only after all official criteria, is labeled non-official, sorts normalized IDs, and counts uses explicitly.
- Confirmed no simulation, modeling, or presentation code was added.

## Concerns

- The required temporary virtualenv lacks `pytest`; verification used Python's standard `unittest` runner with that same interpreter.
- The engine deliberately treats a fallback use as one unresolved subgroup, not one team. The contract exposes this directly for downstream manifest aggregation.
