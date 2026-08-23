# Role Fulfillment Matrix Live Dry Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the approved `rfm-live-v1` formulas against real reviewed 2026 sources in an isolated, non-publishing dry-run pipeline.

**Architecture:** Add a third execution state, `live_dry_run`, beside fixture and blocked live publishing. A standings adapter establishes the cutoff and team-code crosswalk, the approved PBPStats adapter produces canonical player-game rows, and a roster adapter overlays current affiliation and activity without altering reviewed eligibility or role decisions. Outputs are written only under the live-review directory and retain an explicit final-approval blocker.

**Tech Stack:** Python 3, pandas, pyarrow, JSON configuration, `unittest`, Node test runner, standalone HTML/JavaScript.

**Spec:** `analysis/role_fulfillment_matrix/methodology.md`

## Global Constraints

- Do not integrate with or write into the standings/playoff forecast dashboard.
- Keep `live_output_enabled` false throughout this implementation.
- Use only reviewed eligibility and primary role assignments for scoring.
- Preserve zero-omitted-count, freshness, coverage, and parity safeguards.
- Write live dry-run outputs only below `analysis/role_fulfillment_matrix/data/review/live_dry_run/`.
- Keep true on/off and team impact evidence-only and excluded from headline scores.

---

### Task 1: Live Dry-Run Governance and Window Policy

**Files:**
- Create: `scripts/role_fulfillment_matrix/live_policy.py`
- Modify: `scripts/role_fulfillment_matrix/contracts.py`
- Modify: `analysis/role_fulfillment_matrix/config/live_config.template.json`
- Test: `tests/test_role_fulfillment_live_dry_run.py`

**Interfaces:**
- Produces: `derive_analysis_windows(cutoff_date, recent_days, baseline_days, lag_days) -> dict[str, str]`.
- Produces: `authorize_execution(config) -> None`, permitting fixture and approved dry-run states while continuing to reject live publishing.

- [ ] **Step 1: Write failing governance and literal date-boundary tests**

```python
def test_cutoff_policy_derives_non_overlapping_fourteen_day_windows():
    assert derive_analysis_windows("2026-08-21", 14, 14, 1) == {
        "baseline_start": "2026-07-24",
        "baseline_end": "2026-08-06",
        "recent_start": "2026-08-07",
        "recent_end": "2026-08-20",
    }

def test_approved_dry_run_is_allowed_but_live_publish_stays_blocked():
    authorize_execution(approved_dry_run_config)
    with self.assertRaises(LiveScoringBlocked):
        authorize_execution(dict(approved_dry_run_config, mode="live", live_output_enabled=True))
```

- [ ] **Step 2: Run the focused test and confirm missing policy behavior fails**
- [ ] **Step 3: Implement the minimum policy and governance checks**
- [ ] **Step 4: Run the focused test and confirm it passes**

### Task 2: Standings and Roster Adapters

**Files:**
- Create: `scripts/role_fulfillment_matrix/standings_adapter.py`
- Create: `scripts/role_fulfillment_matrix/roster_adapter.py`
- Test: `tests/test_role_fulfillment_live_dry_run.py`

**Interfaces:**
- Produces: `adapt_forecast_standings(standings, manifest) -> AdapterResult` with canonical `team_abbreviation`, `current_rank`, and `cutoff_date`.
- Produces: `adapt_espn_roster(player_core, eligibility, standings, source_as_of) -> AdapterResult` with canonical `player_id`, current team, `active`, and `status_type`.

- [ ] **Step 1: Write failing tests for all six ESPN-to-PBPStats abbreviation differences, cutoff propagation, reviewed identity coverage, and stale roster blocking**
- [ ] **Step 2: Run the focused tests and verify expected failures**
- [ ] **Step 3: Implement explicit abbreviation normalization, uniqueness checks, reviewed crosswalk joins, and source-date validation**
- [ ] **Step 4: Run the focused tests and confirm they pass**

### Task 3: Approved PBPStats Adapter Wiring

**Files:**
- Modify: `scripts/role_fulfillment_matrix/data_sources.py`
- Modify: `scripts/role_fulfillment_matrix/pipeline.py`
- Test: `tests/test_role_fulfillment_live_dry_run.py`

**Interfaces:**
- `load_sources(config) -> LoadedSources` returns canonical standings, player-game rows, reviewed eligibility and roles, canonical roster status, adapter audits, and the effective cutoff-derived configuration.

- [ ] **Step 1: Write a failing integration test that loads real-source-shaped temporary files and asserts dry-run mode, source provenance, adapter audit status, and derived windows**
- [ ] **Step 2: Run it and confirm non-fixture loading is still rejected**
- [ ] **Step 3: Add the dry-run loader branch using the approved raw PBPStats adapter and fail closed on any adapter blocker**
- [ ] **Step 4: Run the integration test and existing fixture tests**

### Task 4: Current-Team and Multi-Team Safeguards

**Files:**
- Modify: `scripts/role_fulfillment_matrix/funnel.py`
- Modify: `scripts/role_fulfillment_matrix/metrics.py`
- Modify: `scripts/role_fulfillment_matrix/pipeline.py`
- Test: `tests/test_role_fulfillment_live_dry_run.py`

**Interfaces:**
- Funnel identity is canonical roster `player_id + current team`.
- Window metrics remain at `player_id + team` grain and are joined on both keys.

- [ ] **Step 1: Write failing tests proving a traded player appears once, only current-team games feed scores, and an old-team role assignment is rejected**
- [ ] **Step 2: Run tests and verify duplicate/mixed-team behavior fails**
- [ ] **Step 3: Join current roster context and metrics on player plus team; add `role_assignment_team_mismatch` exclusion**
- [ ] **Step 4: Run focused and fixture regression tests**

### Task 5: Isolated Real-Data Outputs and Review Report

**Files:**
- Modify: `scripts/build_role_fulfillment_matrix.py`
- Modify: `scripts/role_fulfillment_matrix/outputs.py`
- Modify: `scripts/role_fulfillment_matrix/render_dashboard.py`
- Modify: `analysis/role_fulfillment_matrix/templates/index.html`
- Modify: `analysis/role_fulfillment_matrix/templates/assets/app.js`
- Create: `scripts/build_role_fulfillment_live_dry_run.py`
- Test: `tests/test_role_fulfillment_live_dry_run.py`
- Test: `tests/test_role_fulfillment_matrix_web.py`

**Interfaces:**
- `build_live_dry_run(config_path, output_root) -> dict` writes scores, funnel, evidence, manifest, dashboard, and `role_fulfillment_matrix_live_dry_run_validation.md` below the review root.

- [ ] **Step 1: Write failing tests for isolated paths, real-data labels, dry-run score status, provenance, and continued publish blocking**
- [ ] **Step 2: Run tests and confirm fixture-only output behavior fails them**
- [ ] **Step 3: Implement mode-aware scoring labels, status banner, manifest, and reviewer report**
- [ ] **Step 4: Run the dry-run builder against committed real sources and inspect its manifest**

### Task 6: Manual CI Gate and Documentation

**Files:**
- Modify: `.github/workflows/role-fulfillment-matrix.yml`
- Modify: `analysis/role_fulfillment_matrix/README.md`
- Modify: `analysis/role_fulfillment_matrix/methodology.md`
- Test: `tests/test_role_fulfillment_matrix_web.py`

**Interfaces:**
- Manual workflow runs fixture and live dry-run jobs, uploads separate artifacts, has read-only permissions, and contains no schedule, commit, or push step.

- [ ] **Step 1: Write a failing workflow test for the manual dry-run job and isolated artifact path**
- [ ] **Step 2: Run it and confirm the current fixture-only workflow fails**
- [ ] **Step 3: Add the dry-run job and document source, window, roster, trade, and final approval rules**
- [ ] **Step 4: Run workflow and documentation-adjacent tests**

### Task 7: Final Validation

**Files:**
- Verify all modified and generated files.

**Interfaces:**
- Produces a clean branch with live publishing still disabled and a reviewer-facing real-data package.

- [ ] **Step 1: Run all Role Fulfillment Matrix Python tests**
- [ ] **Step 2: Run client tests, syntax compilation, builds, and `git diff --check`**
- [ ] **Step 3: Inspect the dry-run manifest for source freshness, candidate coverage, output mode, blocker status, and fixture-label absence**
- [ ] **Step 4: Review the complete diff against every global constraint**
