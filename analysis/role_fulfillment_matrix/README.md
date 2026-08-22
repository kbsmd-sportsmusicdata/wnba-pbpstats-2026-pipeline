# Role Fulfillment Matrix — Fixture Vertical Slice

This directory is a standalone experiment for identifying young/emerging contributors on
contending teams and diagnosing role fit. It is intentionally separate from the standings and
playoff forecast dashboard.

## Current status

- **Prototype mode:** synthetic fixtures only.
- **Live scoring:** blocked.
- **Why blocked:** the GitHub repository does not yet contain a reviewed age/experience eligibility
  table or reviewed player-role assignments.
- **Output interpretation:** all names, teams, and scores in the generated dashboard are synthetic.

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
2. a reviewed player-role assignment for every candidate;
3. coverage, duplicate, and unknown-role checks;
4. reviewed role formulas and thresholds;
5. a shared-cutoff decision for lagging impact context;
6. fixture parity tests against a hand-calculated review set.

Until those are complete, `live_config.template.json` fails before any live table is read.
