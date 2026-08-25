# Role Fulfillment Matrix — Standalone Vertical Slice

This directory is a standalone experiment for identifying young/emerging contributors on
contending teams and diagnosing role fit. It is intentionally separate from the standings and
playoff forecast dashboard.

## Current status

- **Fixture mode:** retained for deterministic regression tests.
- **Live-data mode:** approved sources support both the isolated `live_dry_run` review path and
  the standalone manual `live` path.
- **Live output:** enabled for manual execution only; scheduling remains disabled.
- **Real eligibility data:** reviewed and approved for all 227 current PBPStats players plus two
  ESPN roster-only identities. Roster-only rows use reviewed `espn:<athlete_id>` placeholders;
  a later PBPStats appearance fails closed pending a reviewed identity crosswalk.
- **Real role assignments:** reviewed and approved for 38 roster-attached eligible players on
  top-six contenders; three confirmed free agents remain in eligibility history only.
- **Live formula status:** the six-role `rfm-live-v1` formulas and thresholds are approved.
- **Formula validation status:** the 11-player hand-calculation and threshold-sensitivity gate is
  approved.
- **Live adapter status:** the PBPStats adapter validation package was approved on 2026-08-22.
- **Current gate:** the first manual live run completed on 2026-08-23 and was accepted as the
  immutable baseline on 2026-08-24. Michelle Onyiah's role assignment was approved on August 25;
  before another live execution, the August 22 base roster must be refreshed to at least the current
  standings cutoff. Scheduling remains disabled and requires a separate design and approval gate.
- **Output interpretation:** the fixture dashboard remains synthetic; the dry-run dashboard uses
  reviewed real sources and is labeled `DRY RUN`, while the manual live dashboard is labeled
  `LIVE`.

## Eligibility review package

The review-stage package uses the committed ESPN player-core snapshot and the PBPStats player-game
layer through August 20, 2026. It applies the approved rule `experience_years <= 3`, but deliberately
sets every generated review row to `review_status = pending`. The reviewed promotion is stored
separately at `config/player_eligibility_2026.csv` with its own approval manifest.

```bash
python3 scripts/build_role_fulfillment_eligibility.py \
  --player-core analysis/role_fulfillment_matrix/data/live_inputs/player_core_2026.csv \
  --player-game data/processed/wnba_pbpstats_player_game/season=2026/player_game.parquet \
  --cutoff-date 2026-08-20 \
  --source-as-of 2026-08-22 \
  --output-dir analysis/role_fulfillment_matrix/data/review/runs/2026-08-23T000000Z
```

The builder refuses to write into a directory containing
`eligibility_approval_manifest_2026.json`. Use a fresh run directory for rebuilds so the approved
pending table, crosswalk, and build manifest remain immutable.

Review outputs:

- `player_eligibility_2026.pending.csv`: 227 pending eligibility decisions;
- `player_identity_crosswalk_2026.csv`: 227 matched identities plus five source-only records;
- `eligibility_build_manifest_2026.json`: rule, cutoff, source hash, coverage, and output hashes;
- `eligibility_approval_manifest_2026.json`: reviewer, approval date, and promoted-table hash;
- `eligibility_addendum_2026-08-23.csv`: reviewed Janiah Barker and Iliana Rupert roster-only rows;
- `eligibility_coverage_addendum_2026-08-24.csv`: reviewed Michelle Onyiah and Morgan Maly rows;
- `player_core_coverage_addendum_2026-08-24.csv`: reviewed roster context for those two identities;
- `README.md`: reviewer checklist and promotion boundary.

## Build

From the repository root:

```bash
python3 -m unittest tests/test_role_fulfillment_matrix.py tests/test_role_fulfillment_matrix_web.py
node --test tests/test_role_fulfillment_matrix_client.js
python3 scripts/build_role_fulfillment_matrix.py
```

Open:

```text
analysis/role_fulfillment_matrix/deliverables/role_fulfillment_matrix/index.html
```

The page embeds its payload, so it works when opened directly without a local web server.

Build the isolated real-data review package without publishing:

```bash
python3 scripts/build_role_fulfillment_live_dry_run.py
```

Dry-run outputs are confined to `data/review/live_dry_run/`. They include the funnel, score table,
evidence, run manifest, standalone dashboard, and
`role_fulfillment_matrix_live_dry_run_validation.md`.

Run the explicitly approved live build manually:

```bash
python3 scripts/build_role_fulfillment_live.py
```

The approved first run remains immutable at `analysis/role_fulfillment_matrix/live/`. Every later
manual invocation writes to a unique
`analysis/role_fulfillment_matrix/live/runs/<UTC-run-id>/` directory and refuses to overwrite an
existing run. The approved configuration requires `execution_mode = manual_only` and
`scheduling_enabled = false`; no GitHub workflow invokes the live builder.

The base roster and each reviewed addendum retain separate `source_as_of` dates. The adapter stamps
those dates onto the rows they contributed and compares the oldest contributing snapshot with the
standings cutoff. A newer addendum therefore cannot make an unchanged base roster appear current.

## Reviewed role and sample safeguards

The reviewed registry is `config/player_role_assignments_2026.csv`. It stores one scored primary
role, an optional unscored secondary role, assignment confidence, and approval metadata. Roster
and sample status remain separate from role approval:

- free agents are excluded as `not_currently_rostered` without deleting eligibility history;
- inactive rostered players retain their role with `score_status = inactive_suppressed`;
- inactive rostered players without a reviewed role are excluded as
  `inactive_role_review_deferred`; reactivation automatically restores the role-review blocker;
- recent scoring requires at least three games and 100 offensive possessions in the approved
  recent window;
- a player with at least 500 season offensive possessions may remain visible with
  `score_status = season_context_only` when the recent gate fails;
- season-context fallback rows carry separate season, recent-game, and recent-possession flags and
  do not receive Fulfillment, Opportunity, or Stability scores.
- assignment confidence below `0.50` suppresses all scores;
- role-specific denominator failure suppresses Fulfillment only while preserving valid Opportunity
  and Stability evidence.

## rfm-live-v1 validation gate

The approved six-role registry is `config/role_definitions_live_v1.json`. Its locked August 7–20
review cohort and independent expected calculations live under
`tests/fixtures/role_fulfillment_matrix/`.

Generate the review package without enabling live output:

```bash
python3 scripts/build_role_fulfillment_live_v1_validation.py
```

Outputs are confined to `data/review/live_v1_validation/`:

- `hand_calculated_11_player_validation.csv`;
- `threshold_sensitivity_11_player.csv`;
- `role_fulfillment_matrix_live_v1_validation.md`.

The current package matches all 11 locked calculations. A 10% threshold-band shift produces a
maximum 10-point change; two players cross one adjacent descriptive band. These bands are review
aids, not categorical player labels.

## PBPStats live-adapter review gate

The review-only adapter is `scripts/role_fulfillment_matrix/pbpstats_adapter.py`. It normalizes the
raw PBPStats player and team game logs to the canonical player-game contract while preserving the
live execution block.

Generate its review package:

```bash
python3 scripts/build_role_fulfillment_live_adapter_validation.py
```

Outputs are confined to `data/review/live_adapter_validation/`:

- `pbpstats_field_mapping.csv`;
- `pbpstats_data_quality_checks.csv`;
- `live_v1_11_player_adapter_parity.csv`;
- `role_fulfillment_matrix_live_adapter_validation.md`.

Only allowlisted additive counts use zero-omitted filling. Identity, dates, game ids, affiliation,
minutes, and team-game possessions are never imputed. Offensive or defensive possessions may be
filled with zero only after participation is established, and total possessions must reconcile.
The locked 11-player parity fixture remains tied to its explicit August 7-20 validation window;
the cutoff-derived recent window advances independently for dry-run scoring. Both windows are
recorded in the run manifest so a routine data refresh cannot be mistaken for an adapter change.
Every live dry run requires both the locked parity input file and its explicit fixed windows before
any live source is read.
The package was approved by Krystal Beasley on 2026-08-22; that approval authorizes the wiring
gate only and leaves live output disabled.

## Outputs

```text
analysis/role_fulfillment_matrix/
├── config/                     # fixture config, blocked live template, roles, review templates
├── data/processed/             # funnel, scores, evidence, run manifest
├── deliverables/
│   └── role_fulfillment_matrix # standalone static bundle
├── templates/                  # source HTML, CSS, and JavaScript
├── methodology.md              # formulas, fields, safeguards, and promotion gates
└── README.md
```

The dashboard answers three different questions without collapsing them into an overall score:

- **Fulfillment:** Is the player performing the behaviors, efficiency, and mistake control required
  by the reviewed role?
- **Opportunity:** Is the player receiving enough access to demonstrate that role, and is the access
  changing versus baseline?
- **Stability:** How much confidence should we place in the observation based on sample, opportunity
  consistency, and assignment confidence?

## Final promotion gate

Do not switch to live mode by changing the config string alone. Promotion requires:

1. a unique, source-cited eligibility row for every candidate;
2. a reviewed player-role assignment for every roster-attached candidate; **complete**;
3. coverage, duplicate, and unknown-role checks;
4. reviewed role formulas and thresholds; **complete as `rfm-live-v1`**;
5. a shared-cutoff decision for lagging impact context;
6. reviewer approval of the generated 11-player hand-calculation and sensitivity package;
   **complete**;
7. reviewer approval of the live-source adapter freshness, zero-omission, coverage, and parity
   package; **complete**;
8. deliberate adapter wiring with live output still disabled; **complete as `live_dry_run`**;
9. reviewer approval of the end-to-end dry-run package; **complete**;
10. explicit `live_output_enabled = true` change and one manual production run; **complete on
    2026-08-23**.

Scheduling remains disabled and requires a separate future decision after review of the manual run.
