# Team Identity Shift

Which WNBA teams have actually changed how they play this season, whether the change is
helping, and whether the reason will hold up.

Built on the [snapshot window panel](../snapshot_window_panel/), which supplies the time
dimension the PBPStats season totals lack.

## Outputs

`data/processed/`

| File | Grain | What it is |
|---|---|---|
| `team_identity_shift_2026.csv` | team | Headline table: shift size, significance, direction, nature |
| `team_shift_decomposition_2026.csv` | team | Offensive change split into design / conversion / possession / free throws |
| `team_shift_dimension_deltas_2026.csv` | team × dimension | Long format, ready to plot |
| `team_style_periods_2026.csv` | team × period | Baseline and recent style vectors with full metrics |
| `run_manifest_2026.json` | run | Source manifest, config hash, league scales, calibration stats |

## Running

```bash
python scripts/build_team_identity_shift.py \
  --config analysis/team_identity_shift/config/team_identity_shift_config.json
```

Options: `--window-panel-root`, `--sportsdataverse-data-root`, `--output-root`. CI
equivalent is the **Team Identity Shift** workflow. Rebuild the window panel first — this
analysis is only as current as the panel underneath it.

## Reading the Headline Table

| Column | Meaning |
|---|---|
| `identity_shift_l1` | Total movement, in league standard deviations of team-to-team difference |
| `shift_vs_null_ratio` | Observed ÷ what reshuffling this team's own season produces. Below 1.0 means unusually *stable* |
| `shift_significance` | Significant (≥95th pct of its own null) / Moderate (≥80th) / Within noise |
| `net_rating_delta` | Raw change in net rating |
| `opponent_adjusted_net_rating_delta` | The same change against a constant strength of schedule |
| `shift_direction` | Helping / Neutral / Hurting, from the **adjusted** figure |
| `shift_nature` | Design-led (structural), Conversion-led (cosmetic), or Possession-led |
| `top_dimension_moves` | The three largest scaled moves, with direction |

### The two columns that carry the story

**`shift_significance` says whether anything happened.** A team can post a big raw delta
and still be within noise — that means its own season, reshuffled, produces moves that
large all the time.

**`shift_nature` says whether it will last.** Design-led changes come from the shots a team
chooses to take and tend to persist. Conversion-led changes come from the same shots
falling at a different rate and tend to regress. A team whose improvement is entirely
conversion-led is a hot month, not a new team.

Read them together, and always against `opponent_adjusted_net_rating_delta` rather than the
raw one — the adjustment flips several 2026 teams between improving and declining.

## Caveats Worth Carrying Into Writing

- A shift being significant does not make it deliberate; injuries and rotation changes
  produce identity shifts too. Pair with the player panel to see whether personnel moved.
- `shift_nature` is offense-only. PBPStats team totals do not carry opponent shot location,
  so defensive change is reported as a rating delta without decomposition.
- Opponent strength uses the opponent's season net rating and ignores rest, travel and
  injuries.
- Every style dimension is weighted equally in the score. That is a choice, not a finding.

Full method, calibration evidence and limitations: [`methodology.md`](methodology.md).
