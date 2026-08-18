# PBPStats WNBA 2026 Pipeline

This repo uses a lightweight two-step Python pipeline for current-season WNBA PBPStats data. It is intentionally limited to CSV/JSON outputs plus run logs.

## Run Order

Run the scripts in this order:

```bash
python scripts/pbpstats_2026_pull_clean.py
python scripts/pbpstats_2026_features.py
```

The features step depends on the clean latest files from the pull/clean step.

## Data Root

The pipeline reads `PBPSTATS_PIPELINE_DATA_ROOT` when set. The default is:

```text
data/pbpstats_wnba_2026
```

## Folder Contract

The pipeline keeps current-state outputs separate from append-only history:

```text
data/pbpstats_wnba_2026/
  raw_master/2026/
  raw_latest/2026/
  clean_master/2026/
  clean_latest/2026/
  features_master/2026/
  features_latest/2026/
    leaderboards/
  run_logs/
```

- `*_latest` files are overwritten on every run and are the correct inputs for downstream notebooks and dashboards.
- `*_master` files are append-only and keep only unique row states based on content hashes.
- `run_logs/` stores one JSON summary per script run.

## Stable Current-State Outputs

Downstream consumers should read these files:

```text
data/pbpstats_wnba_2026/clean_latest/2026/player_totals_clean_latest.csv
data/pbpstats_wnba_2026/clean_latest/2026/team_totals_clean_latest.csv
data/pbpstats_wnba_2026/features_latest/2026/player_totals_features_latest.csv
data/pbpstats_wnba_2026/features_latest/2026/team_totals_features_latest.csv
data/pbpstats_wnba_2026/features_latest/2026/leaderboards/*.csv
```

## Safeguards

- Row hashes intentionally ignore volatile metadata such as run IDs and timestamps.
- Re-running without upstream data changes should not append duplicate rows to any master CSV.
- Shot quality fields are normalized into the `shotquality_pbp` naming family.

## Player and Team Game Logs

`scripts/fetch_wnba_pbpstats_game_logs_2026.py` ingests per-game logs for every player and team, producing one combined player-game table for downstream analysis plus the individual raw API responses behind it.

```bash
python scripts/fetch_wnba_pbpstats_game_logs_2026.py
```

The fan-out is: `get-totals` (Player) enumerates the season's players → `get-game-logs` (Player) is called once per player → the per-game rows are combined, with the player identity the rows omit (`PlayerId`, `PlayerName`, `TeamId`, `TeamAbbreviation`) injected from the totals lookup. Team logs are ingested the same way from `get-totals`/`get-game-logs` (Team). `get-games` is the authoritative game dimension / schedule-result spine; logs join to it by `GameId`.

### Data Root and Folder Contract

The script reads `PBPSTATS_GAME_LOGS_DATA_ROOT` when set (default `data/pbpstats_2026_player_game_logs`):

```text
data/pbpstats_2026_player_game_logs/
  get_games_wnba_2026_regular_season.json        # raw get-games response (the spine)
  games_wnba_2026_regular_season.csv             # game dimension derived from get-games
  get_totals_player_wnba_2026_regular_season.json
  get_totals_team_wnba_2026_regular_season.json
  player_lookup_wnba_2026.csv                    # player_id, player_name, team_id, team_abbreviation, games_played
  team_lookup_wnba_2026.csv
  player_game_logs_wnba_2026_regular_season.csv  # combined player-game table (column union)
  player_game_logs_wnba_2026_regular_season.json # combined, ragged (preserves pbpstats zero-omission)
  team_game_logs_wnba_2026_regular_season.csv
  team_game_logs_wnba_2026_regular_season.json
  player_game_logs_failures.json                 # entities that failed transiently, retried next run
  team_game_logs_failures.json
  ingest_manifest.json
  raw/
    player_<ID>_game_logs.json                   # one raw response per player
    team_<ID>_game_logs.json
```

The combined player log's primary key is **`PlayerId` + `GameId`**; the combined JSON is what the playoff project consumes. Because pbpstats omits zero-valued stats, an absent column in a row means zero — the JSON stays ragged to preserve that, while the CSV is the column union with blanks for the same absences.

### Historical Build vs Incremental Refresh

The first run is a full historical build (every player, every game log). Subsequent runs are incremental: **`GameId` is the freshness checkpoint**, not `GamesPlayed`, because the feeds refresh at different times and a game can appear in `get-games` before `get-totals` counts it. A run re-fetches only the entities a newly-appeared game touches, plus any entity whose stored row count no longer matches its `GamesPlayed` and anything that failed transiently before, then replaces those entities' rows and appends onto the existing baseline. A transient `5xx` on one entity is recorded in the failures file and retried automatically on the next run rather than sinking the whole build.

### Tests

```bash
python -m unittest tests.test_fetch_wnba_pbpstats_game_logs
```

## Shared Normalized Game Layer

`scripts/build_wnba_game_layer_2026.py` turns the combined game logs into analysis-ready per-game tables that every downstream analysis reads instead of re-deriving game grain from season totals:

```bash
python scripts/build_wnba_game_layer_2026.py
```

```text
data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet   # one row per player-game
data/processed/wnba_pbpstats_team_game/season=2026/team_game.parquet       # one row per team-game
data/processed/wnba_pbpstats_player_game/season=2026/game_layer_manifest.json
```

Each row is snake_cased, has its zero-omitted stats filled to 0 (pbpstats semantics), and is joined to the `get-games` spine for `game_date`, `is_home`, `opponent_team_id`, `team_points`/`opponent_points`, `margin`, `win`, and possessions. Player-game rows are keyed **`player_id + game_id`**; team-game rows are keyed **`team_id + game_id`**. The per-game team is derived from the spine by matching the played-for abbreviation, so a mid-season trade attributes each game to the team actually played for rather than the player's current team. The transforms live in the importable `wnba_game_layer` package and fail closed on a row absent from the spine or matching neither side of its game.

These two paths are distinct from the forecast's own `data/processed/wnba_team_game/` layer (that one is SportsDataverse-derived, in ESPN id space); the pbpstats layer is richer (full advanced metric set) and in pbpstats id space.

```bash
python -m unittest tests.test_wnba_game_layer
```

## GitHub Actions

The workflow at `.github/workflows/pbpstats-wnba-2026.yml` supports:

- `workflow_dispatch` for manual runs
- a daily in-season schedule during May through October

The workflow runs the pull/clean, features, and game-log ingest steps, then stages and commits only generated CSV/JSON files under `data/pbpstats_wnba_2026/` and `data/pbpstats_2026_player_game_logs/`.
