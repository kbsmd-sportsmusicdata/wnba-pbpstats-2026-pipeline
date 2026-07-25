# Team Identity Dashboard MVP Design

**Status:** Approved design specification  
**Date:** 2026-07-25  
**Repository:** `kbsmd-sportsmusicdata/wnba-pbpstats-2026-pipeline`  
**Primary audience:** WNBA coaching staff  
**Delivery:** Single-file HTML/CSS/JavaScript dashboard with print-optimized HTML coach brief

## 1. Purpose

Build the first MVP of a broader Basketball Intelligence Suite inside the existing WNBA 2026 pipeline. The MVP is a coaching-first **Team Identity Dashboard** that compares a selected team and opponent, surfaces season identity and last-five changes, and converts validated matchup evidence into deterministic coaching priorities.

The dashboard must answer four questions quickly:

1. What does each team do well and poorly?
2. What has changed over the last five games?
3. Where are the most important matchup edges and vulnerabilities?
4. What should the coaching staff attack, limit, and emphasize by game phase?

The MVP establishes the shared rolling team-game, visualization, rules-engine, and export foundation that later modules will reuse:

- Scout Lab Player Watchlist
- Passing Chemistry Network
- Lineup Connectivity Score
- Quarter Passing Flow
- Development Pathway Graph

## 2. Product principles

### 2.1 Coaching-first hierarchy

The first screen must prioritize decisions over exploration:

1. Matchup header and global controls
2. Identity snapshot KPI ribbon
3. Offensive and defensive identity fingerprints
4. Recent-form delta heatmap
5. Quarter profile heatmap
6. Coaching action rail

Advanced definitions, formulas, source notes, and sample details remain available through tooltips, expandable evidence, or a methodology drawer.

### 2.2 One shared analytical truth

Python produces deterministic, visualization-ready data. JavaScript formats and filters that data but does not independently recalculate core metrics, percentiles, coaching priorities, or sample-quality decisions.

### 2.3 Evidence-linked recommendations

Every generated coaching recommendation must expose:

- Triggering metric or metrics
- Matchup gap or trend
- Comparison window
- Sample size and confidence
- Rule identifier
- Supporting display text

### 2.4 Honest fallbacks

Each metric has one of four availability states:

- `available`
- `estimated`
- `proxy`
- `unavailable`

Unavailable WNBA or WPBA measures must not be silently replaced by unrelated substitutes.

## 3. Approved MVP scope

### 3.1 Included

- Team-vs-opponent matchup workspace
- Latest validated data by default
- Reproducible dated snapshots
- Season baseline and last-five comparison
- Offensive and defensive identity fingerprints
- Recent-form delta heatmap
- Quarter profile heatmap
- Coaching-phase breakdown
- Rules-based Attack / Limit / Keys recommendations
- Toggle between Attack / Limit / Keys and Game Phases in the coaching rail
- Validated lineup metrics when available
- Starter/bench splits as the guaranteed lineup baseline
- Featured matchup for first-time visitors
- Browser-local persistence of the last selected matchup for returning visitors
- Print-optimized HTML coach brief
- WNBA implementation with documented WPBA fallbacks

### 3.2 Deferred

- PNG export
- In-dashboard threshold editing
- Analyst rules editor
- React or other frontend framework migration
- Player Watchlist implementation
- Passing and lineup network modules
- Public/fan-facing editorial mode
- Fully interactive five-player lineup explorer when stint validation is insufficient

## 4. Repository structure

Create the module using the repository's existing analysis-project pattern.

```text
analysis/team_identity_dashboard/
├── README.md
├── methodology.md
├── config/
│   ├── team_identity_config.json
│   ├── metric_registry.json
│   └── coaching_rules.json
├── data/
│   ├── processed/
│   ├── viz/
│   ├── manifests/
│   └── snapshots/
├── dashboard/
│   └── team_identity_dashboard.html
└── exports/
    └── coach_briefs/

scripts/
├── build_team_identity_dashboard.py
└── team_identity/
    ├── __init__.py
    ├── loaders.py
    ├── team_games.py
    ├── rolling_form.py
    ├── identity_metrics.py
    ├── quarter_profiles.py
    ├── game_phases.py
    ├── lineup_splits.py
    ├── coaching_rules.py
    ├── presentation.py
    ├── validation.py
    └── exports.py

tests/
└── test_team_identity_dashboard.py

.github/workflows/
└── team-identity-dashboard.yml
```

## 5. Source data and adapters

### 5.1 WNBA source adapter

Use the current repository sources and outputs where available:

- SportsDataVerse team box scores
- SportsDataVerse player box scores and player game logs
- ESPN/SportsDataVerse play-by-play
- PBPStats team totals and feature panels
- PBPStats player totals and feature panels
- Existing Midseason Team Grades outputs for Four Factors, bench analysis, clutch context, player impact, and validated RAPM-style signals

The module must reuse existing definitions rather than introduce competing Four Factors or shot-profile formulas.

### 5.2 WPBA adapter contract

The future WPBA adapter must support the same visualization-ready output contract using:

- Team game logs
- Team quarter logs
- Player game logs
- Starter indicators
- Estimated possessions
- Validated team and player totals

Every metric entry in `metric_registry.json` includes WNBA and WPBA source mappings plus a WPBA fallback status.

Example:

```json
{
  "tov_pct": {
    "label": "Turnover rate",
    "direction": "lower_is_better",
    "format": "percent",
    "group": "offensive_identity",
    "minimum_games": 5,
    "wnba_source": "team_game_four_factors_2026.csv:tov_pct",
    "wpba_fallback": "turnovers / estimated_possessions",
    "wpba_status": "estimated"
  }
}
```

## 6. Canonical data model

### 6.1 Canonical team-game table

Create `team_game_identity_2026.csv`, one row per team per game.

Required identifiers and context:

```text
game_id
game_date
season
team_id
team_abbreviation
team_name
opponent_id
opponent_abbreviation
opponent_name
home_away
result
team_score
opponent_score
as_of_date
```

Core measures:

```text
possessions
off_rating
def_rating
net_rating
pace
efg_pct
tov_pct
oreb_pct
ft_rate
rim_rate
three_rate
assisted_fg_pct
shot_quality
shot_making_over_expected
live_ball_tov_pct
points_in_paint
second_chance_points
bench_points
```

Quarter and phase measures are stored in purpose-specific outputs instead of widening the canonical table indefinitely.

### 6.2 Derived outputs

| Output | Grain | Purpose |
|---|---|---|
| `team_identity_summary_2026.csv` | team | Season identity, rank, percentile, label, availability |
| `team_recent_form_2026.csv` | team × metric | Last-five baseline, season baseline, raw delta, directional interpretation |
| `team_quarter_profile_2026.csv` | team × quarter | Q1–Q4 efficiency, margin, pace, turnovers, rebounding |
| `team_game_phase_profile_2026.csv` | team × phase | Opening, transition, half court, quarter endings, late game |
| `team_starter_bench_profile_2026.csv` | team × role group | Guaranteed starter/bench baseline |
| `team_validated_lineup_profile_2026.csv` | team × lineup | Optional validated five-player lineup data |
| `matchup_identity_edges_2026.csv` | selected team × opponent × metric | Advantages, vulnerabilities, matchup gaps |
| `coaching_priorities_2026.csv` | matchup × recommendation | Ranked deterministic coaching priorities |
| `team_identity_dashboard_2026.json` | build | Nested browser-ready payload |
| `run_manifest_2026.json` | build | Source versions, validation, row counts, snapshot metadata |

## 7. Data freshness and snapshots

### 7.1 Default behavior

The dashboard opens using the newest successful validated build.

### 7.2 Snapshot support

Every build records:

- `as_of_date`
- Build timestamp
- Git commit SHA when available
- Source file paths and hashes
- Source row counts
- Output row counts
- Validation status by dataset
- Rule and metric-registry versions

Save historical snapshots under:

```text
analysis/team_identity_dashboard/data/snapshots/YYYY-MM-DD/
```

Coach briefs must show the exact as-of date and must not silently update after export.

## 8. Dashboard information architecture

### 8.1 Persistent left navigation

- Matchup Overview
- Offensive Identity
- Defensive Identity
- Quarter Profile
- Recent Form
- Game Phases
- Lineups
- Coaching Notes

### 8.2 Global controls

One compact control bar controls the full workspace:

- Your Team
- Opponent
- As-of Date
- Comparison Window

Default comparison window:

> Last 5 games vs full-season baseline

### 8.3 Initial state

- First-time visitor: configured featured matchup
- Returning visitor: last selected teams restored from browser local storage
- Local storage must not override a URL-encoded matchup if deep linking is added later

### 8.4 Matchup Overview order

1. Team-vs-team header
2. Identity snapshot KPI ribbon
3. Offensive and defensive fingerprints
4. Recent-form delta heatmap
5. Quarter profile heatmap
6. Game-phase summary
7. Starter/bench or validated lineup summary
8. Recent games and evidence details

### 8.5 Right coaching rail

Default mode:

- Attack
- Limit
- Keys

Alternate mode:

- Game Phases

The toggle reorganizes one recommendation set. It does not create independent or contradictory recommendations.

## 9. Visual design

Use the selected third mockup direction:

- Dark, high-contrast interface
- Persistent left navigation
- Large team-vs-team header
- Compact global filters
- Central analytical workspace
- Right coaching-action rail
- Clear card hierarchy
- Colorblind-friendly neutral, blue, violet, gold, coral, and teal accents
- No red/green categorical encoding

### 9.1 KPI ribbon

Show key matchup measures such as:

- Offensive Rating
- Defensive Rating
- Net Rating
- Pace
- eFG%
- TOV%
- OREB%
- Free-throw rate

### 9.2 Identity fingerprints

Use aligned horizontal percentile bars.

Offensive identity, maximum six rows:

- Pace
- eFG%
- Rim pressure
- Three-point attempt rate
- Assisted scoring
- Offensive rebound rate

Defensive identity, maximum six rows:

- Opponent eFG%
- Turnover pressure
- Defensive rebound rate
- Rim suppression
- Three-point suppression
- Foul avoidance

Each row displays:

- Percentile bar
- Human-readable percentile label
- Exact metric value
- League rank icon when applicable
- One recent-form direction indicator

### 9.3 Recent-form deltas

Use a diverging heatmap rather than another set of bars.

Columns:

- Selected team last-five vs season
- Opponent last-five vs season
- Matchup implication

Cells show exact delta values. Color supports interpretation but never replaces text.

### 9.4 Quarter profile

Use a quarter heatmap with Q1–Q4 columns and paired team rows.

Selectable measures:

- Net rating or scoring margin
- Offensive efficiency
- Defensive efficiency
- Pace
- Turnover rate
- Rebound edge

### 9.5 Four Factors

Use compact head-to-head bullet or dumbbell comparisons in detailed tabs.

### 9.6 Game phases

Use a phase matrix with rows:

- Opening five minutes
- Transition
- Half court
- Quarter endings
- Late game

Columns:

- Edge
- Evidence
- Priority
- Confidence

Selecting a phase reveals supporting charts and recent-game evidence.

## 10. Coaching phase definitions

### 10.1 Opening five minutes

Use:

- Early pace
- First-quarter efficiency
- Turnover pressure
- Initial shot profile

### 10.2 Transition

Use:

- Pace and seconds per possession
- Live-ball turnovers
- Rim pressure
- Transition-defense proxies

### 10.3 Half court

Use:

- Shot quality and shot diet
- Assisted scoring
- Offensive rebounding
- Turnover and foul pressure

### 10.4 Quarter endings

Use final three minutes of Q1–Q3:

- Scoring margin
- Possession execution
- Fouls
- Turnovers

### 10.5 Late game

Use close-game fourth-quarter possessions:

- Clutch scoring
- Free-throw pressure
- Ball security
- Shot selection

Possession-based clutch ratings must remain unavailable unless possession validation passes.

## 11. Rules engine

### 11.1 Configuration

Rules are edited only through version-controlled JSON for the MVP.

Files:

- `coaching_rules.json`: triggers, weights, copy templates, suppression, category and phase mappings
- `metric_registry.json`: labels, direction, percentile bands, icons, formatting, samples and source mapping

### 11.2 Rule structure

```json
{
  "rule_id": "attack_turnover_pressure",
  "category": "attack",
  "phase": ["transition", "half_court"],
  "metric": "opponent_tov_pct",
  "comparison": "matchup_gap",
  "trigger": {
    "percentile_min": 0.70,
    "recent_delta_min_pp": 1.5
  },
  "minimum_games": 5,
  "priority_weight": 1.15,
  "headline": "Pressure their ball security",
  "template": "Opponent turnover rate has risen {recent_delta} over its season baseline.",
  "evidence_fields": ["opponent_tov_pct", "opponent_live_ball_tov_pct"],
  "suppression_rules": ["low_sample", "missing_live_ball_data"]
}
```

### 11.3 Evidence hierarchy

Evaluate evidence in this order:

1. Head-to-head matchup gap
2. Last-five change vs season
3. Season-long identity
4. Quarter or phase concentration
5. Sample quality and confidence

Recent changes modify season identity; they do not automatically replace it.

### 11.4 Default trigger bands

| Signal | Moderate | Strong |
|---|---:|---:|
| League percentile | ≥70th or ≤30th | ≥85th or ≤15th |
| Matchup percentile gap | ≥20 points | ≥35 points |
| Rate change, L5 vs season | ≥1.5 pp | ≥3.0 pp |
| Rating change, L5 vs season | ≥3 per 100 | ≥6 per 100 |
| Pace change | ≥2 possessions | ≥4 possessions |
| Quarter net-rating edge | ≥5 per 100 | ≥10 per 100 |
| Quarter scoring-margin edge | ≥2.0 points | ≥4.0 points |
| Possession-length change | ≥0.5 seconds | ≥1.0 second |

### 11.5 Selection

Score each candidate using:

```text
rule score =
  matchup severity
+ recent-form confirmation
+ phase concentration
+ strategic importance
- sample penalty
- redundancy penalty
```

Select at most:

- 3 Attack priorities
- 3 Limit priorities
- 3 Execution Keys

Execution Keys require:

- A tactical action
- A measurable target
- At least two supporting signals

Merge redundant rules before display.

### 11.6 Confidence

**Strong**

- At least ten relevant games
- Multiple supporting measures
- No major validation warning

**Usable**

- At least five relevant games
- One primary and one supporting measure
- No direct contradiction

**Monitor**

- Small sample, role change, proxy, or partial evidence

WPBA proxy-based evidence cannot receive Strong confidence until validated.

## 12. Presentation and icon contract

### 12.1 Percentile labels

| Percentile | Label |
|---:|---|
| 90–100 | Elite |
| 75–89 | Strong |
| 60–74 | Above average |
| 40–59 | Average |
| 25–39 | Below average |
| 10–24 | Poor |
| 0–9 | Critical weakness |

Callouts may use the label while the exact percentile remains in the tooltip or expanded evidence.

Example:

> Elite offensive rebounding 🥈

Tooltip:

> OREB% is 93rd percentile and ranks 2nd in the league.

### 12.2 League-rank icons

- Rank 1: 🥇
- Rank 2: 🥈
- Rank 3: 🥉
- Second-worst: ⬇️
- Worst: ⚠️

Rank icons are used only for direct league ranks or ranks derived from correctly directed percentiles.

### 12.3 Direction indicators

- `▲` increase
- `▼` decrease
- `→` stable

The arrow reflects raw movement. Accompanying text must interpret whether that movement is beneficial based on metric direction.

Examples:

- `▼ −2.1 pp — improving` for offensive turnover rate
- `▼ −3.4 pp — declining` for eFG%

### 12.4 Trigger-strength icon

- Moderate: no fire icon
- Strong: 🔥
- Extremely strong: 🔥🔥, used sparingly

### 12.5 One-symbol rule

A symbol may appear with the metric value or with the evidence/headline text, never both.

Allowed:

> Attack the glass 🔥  
> OREB% ranks 2nd in the league.

Allowed:

> Attack the glass  
> OREB% ranks 2nd in the league 🥈.

Not allowed:

> 🔥 Attack the glass 🥈  
> OREB% is 93rd percentile 🔥.

### 12.6 Card hierarchy

Each coaching card uses:

1. Tactical headline, optionally with 🔥
2. Evidence label or league-rank icon
3. Delta with `▲`, `▼`, or `→`
4. Tooltip with exact percentile, rank, raw values, sample and rule trigger

## 13. Lineup and starter/bench policy

### 13.1 Guaranteed baseline

Calculate starter/bench splits from player box-score or player-game rows using the starter indicator.

Include:

- Minutes share
- Points and scoring share
- eFG%
- TS%
- AST/TO
- Rebounding contribution
- Plus-minus
- Usage distribution
- Last-five vs season changes
- Selected-team vs opponent comparison

### 13.2 Validated lineup enhancement

Show five-player lineup or RAPM-style measures only when the source dataset passes configured validation.

Validation includes:

- Required player identifiers
- Exactly five players per valid lineup observation after normalization
- Minimum possession threshold
- Nonnegative and plausible possession counts
- Team and opponent linkage
- No material duplicate stint inflation

### 13.3 Display states

The dashboard labels the section as one of:

- `Validated lineup data`
- `Starter/bench split`
- `Unavailable — validation failed`

Starter/bench splits must never be described as five-player lineup performance.

## 14. Linked interactions and progressive disclosure

- Selecting a metric highlights the same metric across fingerprints, deltas, quarter evidence and coaching cards.
- Selecting a quarter filters supporting evidence to that quarter.
- Selecting a coaching card scrolls to and emphasizes its supporting visual.
- Selecting a phase reveals relevant detailed evidence.
- Metric definitions, formulas and sample sizes appear in tooltips or drawers.
- The primary page remains scannable without opening details.

## 15. Export behavior

### 15.1 MVP export

Provide a print-optimized HTML coach brief using the same data payload.

Include:

- Matchup header and as-of date
- KPI ribbon
- Offensive and defensive fingerprints
- Recent-form summary
- Quarter heatmap
- 3 Attack priorities
- 3 Limit priorities
- 3 Execution Keys
- Five game-phase notes
- Starter/bench or validated lineup summary
- Data-quality and sample footnote

### 15.2 Deferred export

Add PNG export only after the HTML print layout is stable and visually validated.

## 16. Single-file dashboard contract

The generated file must contain:

- Embedded CSS
- Embedded JavaScript
- Embedded JSON payload
- No framework dependency
- No runtime network requests for core data
- Print stylesheet
- Accessible keyboard controls
- Accessible tooltip alternatives
- Responsive desktop and tablet layouts

External fonts may be used only with safe fallbacks. The dashboard must remain functional when external font loading fails.

## 17. Validation and testing

### 17.1 Data tests

Verify:

- One team-game row per team per game
- Opponent linkage is reciprocal
- Four Factors match existing module definitions
- Percentiles respect metric direction
- League ranks are deterministic under ties
- Last-five windows use each team's five most recent eligible games as of the snapshot
- Quarter rows reconcile to game totals within documented tolerances
- Starter and bench minutes reconcile to team player minutes
- Snapshot outputs are immutable after creation

### 17.2 Rules tests

Verify:

- Moderate and strong thresholds
- Positive and negative metric direction
- Rank medal and bottom-two icon assignment
- Percentile label assignment
- Fire icon assignment
- One-symbol rule
- Redundancy suppression
- Low-sample suppression
- Attack, Limit and Key count caps
- Phase reorganization preserves recommendation identity

### 17.3 Frontend tests

Verify:

- Featured matchup loads on first visit
- Last matchup restores on return
- Team selectors update all panels
- Right-rail toggle preserves evidence
- Print mode excludes interactive-only controls
- Tooltips expose exact percentile and sample values
- Keyboard navigation works across tabs and controls
- Missing metrics display availability states rather than zeros

### 17.4 Build manifest validation

Fail the build when required inputs or core outputs are missing. Warn, but continue with a documented degraded state, when optional lineup or PBP-derived metrics are unavailable.

## 18. GitHub Actions workflow

Add a workflow with manual dispatch first. Scheduled execution can be added after the initial build is stable.

Inputs:

- `as_of_date`
- `comparison_window`
- `featured_team`
- `featured_opponent`
- `run_tests`
- `commit_outputs`

Stages:

1. Checkout
2. Python 3.11 setup
3. Dependency install
4. Unit tests
5. Processed data build
6. Visualization payload build
7. Single-file HTML build
8. Print coach-brief build
9. Manifest summary
10. Optional generated-output commit

## 19. Error handling

- Required source missing: fail with exact file and expected location
- Optional metric missing: set availability state and suppress dependent rules
- Invalid lineup data: fall back to starter/bench split
- Fewer than five team games: calculate available trend, label Monitor, and expose sample size
- Team selection without opponent: disable matchup recommendations while retaining self-scout identity
- Empty rule category: show `No strong validated priority` instead of manufacturing a recommendation
- Snapshot collision: refuse overwrite unless the existing snapshot content hash matches

## 20. Success criteria

The MVP is successful when:

1. A coach can select two teams and understand their matchup identity in under one minute.
2. Every recommendation can be traced to exact evidence.
3. Last-five changes are clearly separated from season identity.
4. The dashboard works as one portable HTML file.
5. The coach brief prints cleanly from the browser.
6. The build remains useful without validated five-player lineups by using clearly labeled starter/bench splits.
7. The same output contract can later accept WPBA data without redesigning the interface.
8. All icons, percentiles, labels, arrows and trigger markers follow one configuration-backed presentation contract.

## 21. Implementation sequence

The implementation plan should deliver testable software in this order:

1. Configuration and metric registry
2. Canonical team-game layer
3. Season identity and rolling last-five form
4. Quarter and phase profiles
5. Starter/bench baseline and validated lineup adapter
6. Matchup edge calculations
7. Rules engine and presentation formatting
8. Visualization-ready JSON contract
9. Single-file dashboard
10. Print coach brief
11. Workflow and end-to-end validation

The later Scout Lab and Network Analysis Lab modules are separate specifications and implementation plans. They may consume this MVP's canonical tables and shared registry but must not expand the first MVP scope.