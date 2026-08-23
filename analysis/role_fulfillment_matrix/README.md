# Role Fulfillment Matrix — Fixture Vertical Slice

This directory is a standalone experiment for identifying young/emerging contributors on
contending teams and diagnosing role fit. It is intentionally separate from the standings and
playoff forecast dashboard.

## Current status

- **Prototype mode:** synthetic fixtures only.
- **Live scoring:** blocked.
- **Real eligibility data:** reviewed and approved for all 227 PBPStats players.
- **Real role assignments:** reviewed and approved for 36 roster-attached eligible players on
  top-six contenders; three confirmed free agents remain in eligibility history only.
- **Why scoring remains blocked:** reviewed live role formulas and thresholds are not yet approved.
- **Output interpretation:** all names, teams, and scores in the generated dashboard are synthetic.

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

## Reviewed role and sample safeguards

The reviewed registry is `config/player_role_assignments_2026.csv`. It stores one scored primary
role, an optional unscored secondary role, assignment confidence, and approval metadata. Roster
and sample status remain separate from role approval:

- free agents are excluded as `not_currently_rostered` without deleting eligibility history;
- inactive rostered players retain their role with `score_status = inactive_suppressed`;
- recent scoring requires at least three games and 100 offensive possessions in the approved
  recent window;
- a player with at least 500 season offensive possessions may remain visible with
  `score_status = season_context_only` when the recent gate fails;
- season-context fallback rows carry separate season, recent-game, and recent-possession flags and
  do not receive Fulfillment, Opportunity, or Stability scores.

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

## Promotion gate

Do not switch to live mode by changing the config string alone. Promotion requires:

1. a unique, source-cited eligibility row for every candidate;
2. a reviewed player-role assignment for every roster-attached candidate; **complete**;
3. coverage, duplicate, and unknown-role checks;
4. reviewed role formulas and thresholds; **remaining blocker**;
5. a shared-cutoff decision for lagging impact context;
6. fixture parity tests against a hand-calculated review set.

Until those are complete, `live_config.template.json` fails before any live table is read.
