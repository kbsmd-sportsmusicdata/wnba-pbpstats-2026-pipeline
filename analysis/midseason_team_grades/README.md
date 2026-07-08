# Midseason Team Grades

Builds WNBA 2026 midseason team-analysis datasets for offense/defense four factors, bench depth, clutch context, player impact, fit profiles, and RAPM-style diagnostics.

This module is designed as an analysis-ready source bundle for Codex/EDA review. It generates deterministic CSV/JSON outputs; it does not check an LLM EDA agent into the repo.

## Run

```bash
python scripts/build_midseason_team_grades.py \
  --config analysis/midseason_team_grades/config/midseason_team_grades_config.json \
  --stage all
```

Supported stages:

- `core`
- `bench`
- `clutch`
- `rapm`
- `eda`
- `all`

## Outputs

Processed outputs:

```text
analysis/midseason_team_grades/data/processed/team_game_four_factors_2026.csv
analysis/midseason_team_grades/data/processed/team_grade_panel_2026.csv
analysis/midseason_team_grades/data/processed/bench_player_game_2026.csv
analysis/midseason_team_grades/data/processed/bench_team_game_2026.csv
analysis/midseason_team_grades/data/processed/bench_team_summary_2026.csv
analysis/midseason_team_grades/data/processed/clutch_team_game_2026.csv
analysis/midseason_team_grades/data/processed/player_midseason_impact_2026.csv
analysis/midseason_team_grades/data/processed/player_fit_profiles_2026.csv
analysis/midseason_team_grades/data/processed/rapm_player_2026.csv
analysis/midseason_team_grades/data/processed/run_manifest_2026.json
```

EDA bundle:

```text
analysis/midseason_team_grades/data/eda/eda_manifest_2026.json
analysis/midseason_team_grades/data/eda/eda_prompt_2026.md
```

## Metric Notes

- VORP is not calculated unless an exact WNBA-compatible formula or source is supplied.
- Bench net rating is marked unavailable until validated possession stints are available.
- RAPM output is RAPM-style ridge regression on lineup scoring events when lineup data passes validation; it is not official league RAPM.
