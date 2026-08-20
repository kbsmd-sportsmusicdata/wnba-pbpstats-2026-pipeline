# WNBA Standings & Playoff Forecast

This season-parameterized project builds a reproducible WNBA standings and playoff forecast bundle. It preserves the existing upstream ingestion workflows and follows the repository's thin-builder, importable-package analysis pattern. One validated machine-readable bundle owns the standings, official tiebreak ordering, matchup probabilities, simulations, leverage, and deterministic broadcast insights used by every presentation surface.

## Source Hierarchy

The forecast has three mandatory inputs:

- The SportsDataverse schedule defines season scope, completed and remaining regular-season games, cutoff dates, participants, and home/away assignment.
- The SportsDataverse team box supplies reciprocal scores, results, and box-score metrics for each completed schedule game.
- `analysis/standings_playoff_forecast/config/team_history.csv` supplies mandatory franchise identity metadata.

Two sources are optional:

- PBPStats team features provide optional descriptive context only. They do not enter `predictive_net_rating`, matchup probabilities, or simulations, and their absence does not stop the forecast.
- An external standings snapshot may be compared with the derived standings for QA. It is never used to initialize the forecast or repair the canonical ledger.

The upstream refresh entry points remain `scripts/fetch_wnba_sportsdataverse_2026.py` and `.github/workflows/sportsdataverse-wnba-2026.yml` for SportsDataverse data, plus `scripts/pbpstats_2026_pull_clean.py`, `scripts/pbpstats_2026_features.py`, and `.github/workflows/pbpstats-wnba-2026.yml` for optional PBPStats context. An explicit `snapshot_as_of` is treated as stats coverage. When only `last_saved_at_utc` exists, the forecast labels it as a conservative cutoff-safety upper bound rather than an exact coverage date.

## Completed-Game Source: ESPN Live vs SportsDataverse

The forecast's cutoff is the date of the last completed game in the `schedule`/`team_box` inputs. Three feeds can supply those, chosen by the workflow's `source_feed` input:

- **`pbpstats` (default)** — `scripts/fetch_wnba_pbpstats_forecast_2026.py` supplies completed results, scores and per-game team box scores (`get-games` plus `get-game-logs` Team) and **overlays** them onto the SportsDataverse fixture list — the one part of that feed that does not lag, since fixtures do not change once published — writing into `data/raw/pbpstats_forecast/wnba_2026/`. Fresh and CI-native: the cutoff tracks the games actually played (mid-August rather than 2026-08-01). By default in CI it reads those results from the **committed game-log ingest** (`data/pbpstats_2026_player_game_logs/`, produced by `fetch_wnba_pbpstats_game_logs_2026.py` with per-entity retry) via `--from-game-logs`, so the forecast no longer makes 15 brittle live `get-game-logs` calls where a single team's transient 500 aborts the whole build; without that flag it fetches the same data live from `api.pbpstats.com`. Its completed-game freshness then tracks the last game-log ingest run (the daily PBPStats workflow).
- **`sportsdataverse`** — the republished ESPN data under `data/raw/sportsdataverse/wnba_2026/`. Reliable on GitHub runners but its release cadence runs a couple of weeks behind the season, which caps the cutoff in the past. Kept as a fallback.
- **`espn`** — `scripts/fetch_wnba_espn_2026.py` pulls directly from ESPN's site API. Fresh, but **ESPN returns HTTP 403 to GitHub-hosted Actions runners** (it blocks cloud egress IP ranges, and no header change gets around it), so `espn` only works from a machine ESPN will serve: a local checkout or self-hosted runner.

pbpstats ids are crosswalked to the SportsDataverse (ESPN) id space through `team_history`, and results are aligned to each SportsDataverse fixture by date and team pair, so the forecast's own schedule reconciliation — cup final, postponements and all — runs unchanged and simply sees a later completion boundary. Each fresh feed writes to its own data root and the build is pointed at it with `--sportsdataverse-data-root`, leaving the SportsDataverse files the other analyses depend on untouched. The fetch fails closed if a completed game is missing its team box scores or if the overlaid schedule does not reconcile to the configured games-per-team. When a non-SportsDataverse feed is chosen, the SportsDataverse `standings_2026.parquet` used for external QA is not present in that root, so external QA reports `unavailable` — it is validation evidence only and never a forecast input.

## Canonical Current Standings

Current standings are reconstructed from the completed-game ledger rather than ingested as a derived table. This guarantees that standings, head-to-head state, point differential, recent form, schedule accounting, and Monte Carlo initialization share one auditable source of truth.

The schedule determines which games qualify and the team box must provide exactly two coherent directional rows for every completed game. The derived standings include GP/W/L, win percentage, points for and against, point differential, games back, home and road records, last 10, current streak, record versus current .500-or-better teams, current rank through the official tiebreak engine, and cutline category. Conference fields remain null until validated conference metadata is available.

External standings QA reports `matched`, `mismatch`, `unavailable`, or `unparseable`. Every external status is non-blocking because the external snapshot is validation evidence, not a forecast input.

## Clinching Is Proved, Not Simulated

`clinched_playoffs`, `eliminated_from_playoffs`, and `status_note` are counting arguments over the games that remain, computed before the Monte Carlo runs and carried on both `current_standings.csv` and `forecast_summary.csv`.

- **Eliminated** when at least `playoff_qualifiers` other teams already hold more wins than this team could reach by winning out. Each of those teams finishes strictly ahead on wins, so no tiebreak can rescue it.
- **Clinched** when at most `playoff_qualifiers - 1` other teams could still reach this team's current win total. Every other team finishes strictly below it even if it loses out.
- **`in_contention`** otherwise.

A playoff probability of 1.0000 over a hundred thousand simulated seasons is a different claim from "cannot be caught", and the two are reported separately for that reason. Both tests ignore that remaining games are shared between teams, which makes them **conservative**: they confirm a clinch or an elimination no earlier than the league does, never earlier. A team can therefore sit at a simulated 0.0000 and still be alive on paper. Resolving the shared-schedule case exactly is the classic baseball elimination problem — a max-flow computation for first place, and NP-hard for a general top-`k` cut — so the conservative bound is what is published and what is claimed.

The two views are cross-checked every run: a team proved eliminated with a non-zero simulated probability, or proved clinched below one, fails the build rather than publishing a contradiction.

## Validation Semantics

The forecast fails closed for:

- `missing mandatory schedule/team-box`;
- `schedule/team-box completed-game mismatch`;
- `non-reciprocal game rows`, including duplicate or incomplete directional rows;
- `wrong team universe`;
- `completed + remaining != configured season length`;
- `simulation invariant failure`;
- `clinch proof contradicting the simulation`; or
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

The dashboard also carries a **Functional depth — descriptive context** panel (the star-dependency ↔ distributed-resilience strip from the [Functional Depth](../functional_depth/) analysis). It is embedded from `analysis/functional_depth/data/processed/functional_depth_strip_2026.csv` when present and is **descriptive only** — it never enters the validated payload, the standings, the matchup probabilities, or the simulation, and the dashboard renders normally (panel hidden) when the strip is absent.

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
