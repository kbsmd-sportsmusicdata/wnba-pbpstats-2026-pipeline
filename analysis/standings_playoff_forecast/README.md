# WNBA Standings & Playoff Forecast

This season-parameterized project builds a reproducible WNBA standings and playoff forecast bundle. It preserves the existing upstream ingestion workflows and follows the repository's thin-builder, importable-package analysis pattern. One validated machine-readable bundle owns the standings, official tiebreak ordering, matchup probabilities, simulations, leverage, and deterministic broadcast insights used by every presentation surface.

## Source Hierarchy

The forecast has three mandatory inputs:

- The SportsDataverse schedule defines season scope, completed and remaining regular-season games, cutoff dates, participants, and home/away assignment.
- The SportsDataverse team box supplies reciprocal scores, results, and box-score metrics for each completed schedule game.
- `analysis/standings_playoff_forecast/config/team_history.csv` supplies mandatory franchise identity metadata.

Two sources are optional:

- PBPStats latest-snapshot team features may enrich predictive ratings when available. Their absence does not stop the forecast.
- An external standings snapshot may be compared with the derived standings for QA. It is never used to initialize the forecast or repair the canonical ledger.

The upstream refresh entry points remain `scripts/fetch_wnba_sportsdataverse_2026.py` and `.github/workflows/sportsdataverse-wnba-2026.yml` for SportsDataverse data, plus `scripts/pbpstats_2026_pull_clean.py`, `scripts/pbpstats_2026_features.py`, and `.github/workflows/pbpstats-wnba-2026.yml` for optional PBPStats enrichment.

## Canonical Current Standings

Current standings are reconstructed from the completed-game ledger rather than ingested as a derived table. This guarantees that standings, head-to-head state, point differential, recent form, schedule accounting, and Monte Carlo initialization share one auditable source of truth.

The schedule determines which games qualify and the team box must provide exactly two coherent directional rows for every completed game. The derived standings include GP/W/L, win percentage, points for and against, point differential, games back, home and road records, last 10, current streak, record versus current .500-or-better teams, current rank through the official tiebreak engine, and cutline category. Conference fields remain null until validated conference metadata is available.

External standings QA reports `matched`, `mismatch`, `unavailable`, or `unparseable`. Every external status is non-blocking because the external snapshot is validation evidence, not a forecast input.

## Validation Semantics

The forecast fails closed for:

- `missing mandatory schedule/team-box`;
- `schedule/team-box completed-game mismatch`;
- `non-reciprocal game rows`, including duplicate or incomplete directional rows;
- `wrong team universe`;
- `completed + remaining != configured season length`;
- `simulation invariant failure`; or
- `renderer artifact failure`.

The forecast continues with an explicit warning or QA status when:

- `external standings unavailable/mismatched` (a schema-incompatible snapshot reports `unparseable`); or
- `optional PBPStats unavailable`.

## Data and Output Roots

The reusable normalized team-game layer lives at `data/processed/wnba_team_game/season=<season>/team_game.parquet`. Forecast-specific machine-readable outputs live under `analysis/standings_playoff_forecast/data/processed/season=<season>/latest/`, while presentation artifacts live under `analysis/standings_playoff_forecast/deliverables/season=<season>/latest/`.

`--render all` writes the validated machine bundle and all four presentation deliverables:

1. Excel analysis workbook: `wnba_standings_playoff_forecast.xlsx`.
2. Broadcaster Markdown brief: `wnba_broadcast_forecast_brief.md`.
3. One-page broadcast stat-pack insert: `wnba_playoff_stat_pack_insert.html`.
4. Interactive playoff-race dashboard: `dashboard/index.html`.

The dashboard embeds the same validated JSON payload that is copied to `dashboard/data/forecast_payload.json`. Open the downloaded `dashboard/index.html` directly with a browser, including through `file://`; no local server is required. For hosted use, the app retains its JSON-fetch fallback.

## Season and Historical Scope

The CLI requires an explicit `--season` parameter. Season-specific competition rules and source paths are configured per verified season; unknown seasons fail closed. The initial target is 2026. Prior normalized partitions may provide descriptive context, optionally bounded by `--history-start`, but historical model training is out of scope for V1. `--skip-history` produces a valid empty history output and does not prevent the current-season forecast.

The cutoff defaults to the latest completed game in the qualified schedule, never the wall clock. The default seed is deterministically derived from the season and resolved cutoff. At the resolved cutoff, the canonical schedule/team-box ledger must validate before standings are derived or simulations begin; stale or inconsistent external standings only change the reported QA status.

## Run and Test

Build the 2026 forecast bundle and all presentation artifacts with a small local simulation count:

```bash
python scripts/build_standings_playoff_forecast.py \
  --season 2026 \
  --simulations 500 \
  --render all
```

Supported runtime options are `--cutoff YYYY-MM-DD`, `--simulations`, `--conditional-simulations`, `--random-seed`, `--history-start`, `--skip-history`, `--render {none,all}`, `--sportsdataverse-data-root`, `--pbpstats-data-root`, and `--output-root`. V1 derives conditional leverage from the retained main simulations, so a nonzero `--conditional-simulations` request fails rather than claiming a second run occurred. `--render none` writes only the validated machine-readable bundle; `--render all` additionally writes the four presentation deliverables above.

Refresh upstream sources, then build:

```bash
python scripts/fetch_wnba_sportsdataverse_2026.py
python scripts/pbpstats_2026_pull_clean.py
python scripts/pbpstats_2026_features.py
python scripts/build_standings_playoff_forecast.py \
  --season 2026 \
  --simulations 100000 \
  --render all
```

Run the forecast test suite:

```bash
python -m unittest discover -s tests -p "test_standings_playoff_forecast*.py"
```
