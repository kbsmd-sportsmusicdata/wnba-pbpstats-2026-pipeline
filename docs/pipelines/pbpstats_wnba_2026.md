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

## GitHub Actions

The workflow at `.github/workflows/pbpstats-wnba-2026.yml` supports:

- `workflow_dispatch` for manual runs
- a daily in-season schedule during May through October

The workflow stages and commits only generated CSV/JSON files under `data/pbpstats_wnba_2026/`.
