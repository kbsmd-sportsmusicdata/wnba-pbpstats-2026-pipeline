# Role Fulfillment Matrix Implementation Plan

> **For agentic workers:** Follow the repository's existing `unittest` conventions and execute
> each task test-first. Do not broaden this experiment into forecast integration.

**Goal:** Deliver a standalone, fixture-only Role Fulfillment Matrix vertical slice with a hard
live-scoring governance gate.

**Architecture:** A new sibling analysis package loads four explicit tables, applies a fail-closed
candidate funnel, recomputes recent/baseline metrics from additive counts, emits three independent
scores and evidence, and renders a self-contained static dashboard bundle.

**Tech Stack:** Python 3.11, pandas, standard-library `unittest`, static HTML/CSS/JavaScript, SVG.

**Spec:** `docs/superpowers/specs/2026-08-21-role-fulfillment-matrix-design.md`

## Global constraints

- Work only on `experiment/role-fulfillment-matrix` in the isolated worktree.
- Do not edit any `standings_playoff_forecast` path.
- Use synthetic fixture inputs only.
- A live config must fail before score calculation.
- Do not create an overall/composite score.
- Keep generated output visibly marked `fixture_only` and `live_scoring_status=blocked`.

### Task 1: Establish configuration and contract failures

**Files:**

- Create: `analysis/role_fulfillment_matrix/config/fixture_config.json`
- Create: `analysis/role_fulfillment_matrix/config/live_config.template.json`
- Create: `analysis/role_fulfillment_matrix/config/role_definitions.json`
- Create: `analysis/role_fulfillment_matrix/config/player_eligibility_2026.template.csv`
- Create: `analysis/role_fulfillment_matrix/config/player_role_assignments_2026.template.csv`
- Create: `tests/fixtures/role_fulfillment_matrix/*`
- Create: `tests/test_role_fulfillment_matrix.py`
- Create: `scripts/role_fulfillment_matrix/contracts.py`
- Create: `scripts/role_fulfillment_matrix/data_sources.py`

- [ ] Write tests for fixture loading, schema errors, unreviewed rows, and live-mode blocking.
- [ ] Run the tests and confirm they fail for missing implementation.
- [ ] Implement the smallest contracts and adapter that pass.
- [ ] Re-run the tests.

### Task 2: Build the candidate funnel and window metrics

**Files:**

- Modify: `tests/test_role_fulfillment_matrix.py`
- Create: `scripts/role_fulfillment_matrix/funnel.py`
- Create: `scripts/role_fulfillment_matrix/metrics.py`

- [ ] Add tests for contender, eligibility, assignment, sample, and denominator gates.
- [ ] Add a regression test proving rates are recomputed from summed counts.
- [ ] Confirm the new tests fail.
- [ ] Implement deterministic funnel rows, stable exclusion reasons, and recent/baseline windows.
- [ ] Re-run the tests.

### Task 3: Build independent scores and evidence

**Files:**

- Modify: `tests/test_role_fulfillment_matrix.py`
- Create: `scripts/role_fulfillment_matrix/scoring.py`
- Create: `scripts/role_fulfillment_matrix/evidence.py`

- [ ] Add tests for role-specific fulfillment, opportunity, stability, missing metrics, and no
  composite field.
- [ ] Add a test proving stable poor performance can have high Stability and low Fulfillment.
- [ ] Confirm the tests fail.
- [ ] Implement normalized role metrics, score metadata, and evidence records.
- [ ] Re-run the tests.

### Task 4: Build outputs and standalone dashboard

**Files:**

- Create: `tests/test_role_fulfillment_matrix_web.py`
- Create: `scripts/role_fulfillment_matrix/outputs.py`
- Create: `scripts/role_fulfillment_matrix/render_dashboard.py`
- Create: `scripts/build_role_fulfillment_matrix.py`
- Create: `analysis/role_fulfillment_matrix/templates/index.html`
- Create: `analysis/role_fulfillment_matrix/templates/assets/styles.css`
- Create: `analysis/role_fulfillment_matrix/templates/assets/app.js`

- [ ] Add output-manifest, exact-bundle, required-section, safe-payload, matrix, and evidence-dialog
  tests.
- [ ] Confirm the tests fail.
- [ ] Implement atomic processed outputs and a self-contained static bundle.
- [ ] Re-run both focused test modules.

### Task 5: Document and automate the fixture experiment

**Files:**

- Create: `analysis/role_fulfillment_matrix/README.md`
- Create: `analysis/role_fulfillment_matrix/methodology.md`
- Create: `.github/workflows/role-fulfillment-matrix.yml`

- [ ] Document the build command, output contract, governance block, and promotion prerequisites.
- [ ] Add a manual-only workflow that runs tests, builds fixtures, and uploads—but never commits—the
  artifact.
- [ ] Build the fixture artifact and inspect the manifest and bundle.

### Task 6: Verify isolation and branch quality

- [ ] Run the focused fixture-only suite.
- [ ] Run relevant existing sibling-analysis tests.
- [ ] Confirm the live config fails with the expected reviewed-table message.
- [ ] Confirm no forecast-dashboard path changed.
- [ ] Review the final diff for generated or unrelated files.
- [ ] Commit the completed experiment branch.
