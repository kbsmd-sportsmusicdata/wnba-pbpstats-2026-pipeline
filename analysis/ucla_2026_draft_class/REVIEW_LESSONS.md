# Review lessons: what Codex found, and why my own checks did not

A record of every automated review finding raised against this analysis module,
what each one actually was, why the checks I had written failed to catch it, and
what the fix was. Written while the reasoning is still recoverable — the *why it
was missed* half decays fastest, and it is the half worth keeping.

Scope: PRs #36, #37, #40, #44, #45, #46 (the UCLA 2026 draft-class module and the
derived possession / impact layers it depends on). Reviewer:
`chatgpt-codex-connector[bot]`, triggered on the draft→ready transition.

> **This file is deliberately outside `verify_docs.py`.** It quotes superseded
> vintages (`274 games`, `g32-36`, `return 6-11`) as evidence, so the coverage
> sweep and `CLOSED_WINDOW_PROSE` would reject it on sight. Note the mechanism,
> though: it is excluded because `main()` enumerates five filenames rather than
> globbing the directory — the same enumerate-don't-derive pattern criticised in
> §3. The exclusion happens to be right; it is not right *by design*. If that
> file list ever becomes a glob, this document needs an explicit exemption.

---

## 1. Scoreboard

| PR | Codex threads | Addressed | Open | Class of finding |
|---|:--:|:--:|:--:|---|
| #36 | 0 | – | – | – |
| #37 | 0 | – | – | – |
| #40 | 2 | 0 | **2** | replay correctness (P1), overclaimed interface |
| #44 | 4 | 4 | 0 | doc/data drift |
| #45 | 6 | 4 | **2** | checks narrower than their own docstring |
| #46 | 6 | 3 | **3** | modelling errors, doc/data drift |
| **Total** | **18** | **11** | **7** | |

Seven findings are still open. Every one of them arrived on a review that was
submitted *after* the PR had already merged — see §5. They are listed with
verification status in §6.

By class across all 18:

- **Doc/data drift** — 7. A document quotes a number the artifact no longer holds.
- **Check narrower than its docstring** — 5. A verifier that promises coverage it
  does not deliver.
- **Modelling error** — 4. Wrong exposure, leaked folds, missing control.
- **Replay correctness** — 1. State-machine ordering bug (P1).
- **Overclaimed interface** — 1. Documented compatibility the schema does not have.

---

## 2. Doc/data drift (7 findings)

The bulk of the volume, and the cheapest class to eliminate mechanically.

| # | Finding | Fix |
|---|---|---|
| #44-1 | Block key still promised `g32-36` (a closed five-game window) on a row that had grown to six games. Same stale label in four exports. | Renamed at source to `Return games 6+ (g32+)`; kept the window open-ended deliberately, since its instability is the point. |
| #44-2 | New 281-game coverage banner contradicted the document's own allowed-source section (274 games / 548 team-games) and source table (`202/274`) fourteen lines below it. | Updated inventory and denominators together. Auditing for the same shape found `METRIC_FRAMEWORK.md` carrying the entire stale inventory — outside the diff, so outside what Codex could see. |
| #44-3 | `DERIVED_POSSESSIONS.md` published 554-team-game / 185-and-58-player validation tables against a manifest recording 562 / 187 / 57. This is the *advertised validation report* for the artifact it disagreed with. | Tables regenerated from the manifest; pbp input counts (279 games / 15,466 subs → 283 / 15,854) were stale for the same reason. |
| #44-4 | Table row said 306 shared possessions; the paragraph immediately beneath it still said 289 of 1,032. | Prose now reads 306 of 1,088. Codex's independently recomputed 1,088 was correct. |
| #45-1 | README chart guidance still instructed builders to use "return 6–10" and chart ten post-injury games. Following it would silently drop a game. | Replaced the hardcoded list with a filter spec (`tgn >= 27 and status == "played"`); current values demoted to an "as of this vintage" illustration. |
| #46-5 | **Open.** Leaders table in `IMPACT_LAYER.md` predates the per-side calibration fix in the same PR. | — |
| #46-6 | **Open.** README simultaneously says impact is current *and* tells readers to omit all RAPM/BPM/WAR figures as frozen. | — |

**Why my checks missed these.** Two distinct reasons, and they are different bugs
in my thinking.

For #44-1 through #45-1: at the time these landed, `verify_docs.py` existed but
its checks were *targeted* — each one asserted that a specific expected string
appeared somewhere in a specific file. That design answers "is the fresh value
present?" It cannot answer "is a stale value also present?" A document that
quotes the game count in five places passes as soon as one of the five is right.
I had built a presence check and reasoned about it as if it were a consistency
check.

For #46-5 and #46-6: a sequencing failure, not a design one. I wrote
`IMPACT_LAYER.md` and the README section against the layer as it stood, then
Codex's round-one findings changed the calibration, then I regenerated the CSV
export and did not re-read the prose that quoted it. `verify_docs.py` currently
passes all 51 checks with both defects live, because no check reads the leaders
table and no check looks for two instructions that contradict each other. The
verifier is only as wide as the claims I remembered to enumerate — which is
exactly the criticism Codex made of it in #45-2, generalised one level up.

---

## 3. Checks narrower than their own docstring (5 findings)

The most instructive class, because every one of these is a check I wrote
*specifically to prevent* the thing it then failed to prevent.

| # | Finding | Fix |
|---|---|---|
| #45-2 | The README artifact-table row counts were never validated. README claimed 181 rows for `story_ucla_six_game_logs.csv` (actual 187) and 36 for `story_rice_timeline.csv` (actual 37) — and the verifier reported success. | Parse the README table and compare *every* claimed count to the file it names. All 16 exports covered; new rows covered automatically. Checks went 20 → 37. |
| #45-3 | `re.search` is satisfied by one match, so a document can carry one fresh quote and four stale ones. `METRIC_FRAMEWORK.md` named the game count in five places against three checked shapes. | Walk *every* `<n> games` occurrence and reject obsolete values. A value passes if it is the current count or another source's real coverage — all derived from files, never hardcoded. Superseded values pass only on a line that also names the current count, or on one of three listed historical lines, each with a stated reason. The exemption list is itself checked: a listed line that stops matching is reported. |
| #45-4 | `CLOSED_WINDOW_PROSE` promised to reject *any* closed range but only matched `6-10` / `g32-36`. A refresh writing `return 6-11` or `g32-37` would pass. | Generalised to any numeric endpoint and any `g3x-3x`. The game-count half was *re-broken in the same fix* and repaired only on the PR that added this file — see §9. |
| #45-5 | **Open.** The obsolete-value sweep only inspects values followed by the literal word `games`; player counts are never swept. | — |
| #45-6 | **Open.** The export-label check requires *both* halves to be closed (`re.search(r"g3\d-3\d", b) and "6" in b`), so `Return games 6-10 (g32+)` passes. | — |

**Why my checks missed these.** Three compounding habits.

*I wrote each check from the failure I had just fixed, so it inherited that
failure's exact shape.* `CLOSED_WINDOW_PROSE` knew `6-10` and `g32-36` because
those were the literal strings wrong on my screen at that moment. The docstring
above it said "no document may describe the open-ended return window as a closed
range" — a claim about a class. The regex encoded an instance. I wrote the
docstring describing what I *meant* and the pattern matching what I had *seen*,
and never re-read one against the other. #45-6 is the identical mistake surviving
into the export check, and it is still there.

*Enumerating passes for the wrong reason.* Every fix in this class replaced an
enumeration with a derivation — parse the table rather than list the files, walk
every occurrence rather than search for one. An enumerating check silently stops
covering things the moment the world grows; a deriving check cannot. This is the
single most portable lesson in the document.

*I never negative-tested the originals.* The rewrites in #45 were each negative-
tested — reintroduce the specific bug, confirm a non-zero exit naming it, restore
— and that discipline is what made them trustworthy. The checks they replaced had
never been run against a document that should fail. A check that has only ever
been observed passing is not evidence of anything. (One negative test in this
module did initially pass for the wrong reason: a `sed` substitution never matched
because the target cell was bolded, so "the check still fails" was really "the
file never changed." The harness now asserts the file actually changed before
trusting the result.)

---

## 4. Modelling errors (4 findings)

The class no document-consistency checker will ever find.

| # | Finding | Fix / status |
|---|---|---|
| #46-3 | WAA multiplied the combined `o_rapm + d_rapm` by offensive possessions alone, charging the defensive coefficient the wrong workload. | Measured the divergence before acting — offensive and defensive counts differ by a mean of 5.2 possessions, ~1.5% at the median. Now `o_rapm_scaled × off_poss + d_rapm_scaled × def_poss`, with the net replacement rate charged against the mean of the two. |
| #46-1 | Row-wise `KFold` put possessions from the same game in both training and validation. Not out-of-game performance, and biased toward an under-regularised alpha. **The repo had already solved this**: `scripts/possession_impact/rapm.py::game_folds`, whose docstring makes exactly this argument. | Imported the existing helper. Ran both first: the selected penalty is unchanged at 4000, and the two curves sit within ~5 weighted MSE at every alpha. No number moved; the leak was real anyway. |
| #46-2 | Total-RAPM attenuation was calibrated by applying `o_rapm + d_rapm` entirely through `off_lineup`, so the 0.64 slope was not the additive model's actual attenuation — and every scaled coefficient and every WAR divides by it. | Offence and defence now aggregated through their own lineups and possession counts and calibrated separately: offence r 0.995 / 0.647, defence r 0.993 / 0.654. Calibrated net additivity r 0.995, MAE 0.49. |
| #46-4 | **Open.** The design matrix holds only the two player blocks and an intercept — no home-court control. With unequal home exposure across a partial season, any home scoring effect is absorbed into player coefficients. **The repo had already solved this too**: `scripts/possession_impact/design.py` carries an unpenalised `offense_is_home` nuisance column. | — |

**Why my checks missed these.** This is the section worth re-reading before
building the next impact layer.

*Every sanity check I wrote was an aggregate invariant, and aggregate invariants
are blind to errors that cancel across units.* I checked that league WAA sums to
zero, that attenuation lands in a plausible range, that team additivity holds at
r ≈ 0.99. Those are real checks — they caught the two largest errors in this
layer before any review saw it (§5). But the exposure mismatch shifts each
player's workload by ~1.5% in whichever direction her off/def split leans, and
those directions are roughly symmetric across the league. Sum them and they
vanish. Fold leakage changes a cross-validation curve, not any invariant. A
missing home-court control redistributes a small effect across players who
happen to have played more home possessions — again, league-neutral by
construction. **All three survive every check I wrote, and would have survived
any number of additional checks of the same kind.** The corollary is a rule: at
least one check must operate at the grain the error would occur at — per player,
per possession, per fold — not at the grain the result is reported at.

*I re-read my own code and re-derived my own intent.* Reading `poss` used for
both terms, I reconstructed the reasoning that had put it there and it looked
deliberate. Codex read the same line with no prior belief about what it was
supposed to say and asked why a defensive coefficient was weighted by offensive
possessions. That is not a capability gap; it is a standpoint gap, and it is why
a second reader is worth more here than more of my own checks. Notably, fixing
#46-3 is what surfaced the *same* mistake one level up in `coefficients()`, which
had been centring both blocks against offensive possessions and leaving league
WAA at +0.018 instead of zero. One outside prompt cascaded into an error my own
invariant had been quietly tolerating.

*I did not search the repo before writing.* Two of the four findings in this
class are literally "this repository already contains the correct implementation."
`game_folds` and `offense_is_home` were both sitting in `scripts/possession_impact/`.
The cost is not duplicated code — it is that each of those existing pieces
encodes a correctness decision someone already made and I silently un-made. A
grep for the concept before implementing it would have caught both.

---

## 5. Replay correctness and overclaimed interface (2 findings, both open)

| # | Finding | Status |
|---|---|---|
| #40-1 **(P1)** | In `replay_game()`, a `Substitution` mutates `on[tid]` immediately, but the preceding possession has not yet been flushed — `flush()` fires only when the ball changes hands or the period ends, and it reads `on[off_team]` *at flush time*. Any substitution logged between a possession's last event and the opponent's next informative event is therefore attributed backwards into the completed possession. | **Open and confirmed.** Measured: **3,354 of 45,643 possessions (7.3%) carry a contaminated lineup** — 4.6% offensive, 4.8% defensive — covering **8.7% of all points**. Substitutions cluster at dead balls, which is precisely after made baskets and fouls, so this is common rather than incidental. It feeds every duo split and the RAPM design matrix. |
| #40-2 | `DERIVED_POSSESSIONS.md` calls the layer "a drop-in replacement for `wnba_possessions_2026.parquet` … so it can feed any analysis the frozen file used to." It emits `off_team`/`def_team` and list-valued `off_lineup`/`def_lineup`; `run_possessions.py` requires `count_as_possession`, `offense_team_id`, `defense_team_id`, and `off_player_1`…`def_player_5`. | **Open and confirmed.** Substituting the file raises missing-column errors immediately. |

**Why my checks missed #40-1.** The validation suite compared reconstructed
possessions against pbpstats at two levels: team-game possession and point totals
(the possession logic), and per-player on-court possession counts (the lineup
replay). Both passed at r ≈ 0.99 and both are genuinely insensitive to this bug.
Mis-dating a substitution by one possession does not change how many possessions
a team had or how many points it scored — the team totals are untouched by
construction. And at the player level, a swap of A→B moves one possession from A
to B; over a season substitutions run in both directions and the per-player net
error largely washes out, which is exactly why the correlation stayed high.

What breaks is **co-presence** — which four teammates were on the floor together
— and co-presence is the entire reason this layer exists. It is the one dimension
I never validated.

My first account of why was that co-presence had no external reference to check
against. That is false, and Codex said so on the PR that added this file: the
frozen `wnba_possessions_2026.parquet` carries all ten `off_player_*` /
`def_player_*` columns across 32,265 possessions and 202 games. Differing
possession conventions would need alignment, but for the two-thirds of the season
the two layers overlap, a direct external check on reconstructed lineup
combinations was available the whole time.

So the real reason is worse than "no ground truth existed," and worth naming
precisely. I had cast the frozen file exclusively as *the thing being replaced* —
stale, superseded, the motivation for the rebuild — and never once as *a thing to
validate against on the overlap*. Once a dataset is framed as the problem, it
stops being visible as a resource. Compounding that, the two checks I did write
compare scalar aggregates that a `groupby` produces directly; comparing lineups
means joining set-valued columns across two identifier namespaces, which is more
work. I validated the dimensions that were convenient to validate and then
constructed a justification for the gap that sounded principled.

Two checks were available and neither was written:

- **External, partial season.** Join reconstructed lineups to the frozen
  parquet's ten lineup columns over the 202-game overlap.
- **Internal, full season, no external data at all.** Snapshot the lineup at the
  possession's first event and assert it still matches at flush. This is exactly
  the instrumentation that produced the 7.3% figure above — perhaps twenty lines,
  and it needs nothing but the replay itself.

The second would have caught the bug on the day it was written.

**Why my checks missed #40-2.** No check reads a compatibility claim, and I never
tried the substitution the sentence advertises. The prose hedges accurately in
its first clause ("in shape — one row per possession, both five-player lineups,
points, and a calibration weight") and then overclaims in its second ("can feed
any analysis the frozen file used to"). I wrote the hedge and then wrote past it.

---

## 6. The process failure behind all seven open findings

Every unaddressed finding in this document sits on a Codex review that was
submitted **after** its PR had already merged:

| PR | Merged | Codex review | Gap |
|---|---|---|---|
| #40 | 04:55:57Z | 04:58:37Z | +2m 40s |
| #44 | 03:39:01Z | 03:41:58Z | +2m 57s |
| #45 | 04:31:42Z | 04:32:26Z (3rd review) | +44s |
| #46 | 05:02:18Z | 05:03:08Z (2nd review) | +50s |

Codex fires on the draft→ready transition and takes roughly two to three minutes.
I marked ready and merged inside that window every single time. On #44 I then
reported "no review comments" on the PR — which was true when I checked and false
three minutes later.

Compounding it: Codex posts findings as **reviews** (`get_reviews` /
`get_review_comments`), not as issue comments. For a stretch I was checking only
two of the four comment surfaces, so even reviews that had landed were invisible
to me.

Two fixes, both free:

1. **Do not merge until the review has landed** — or, if merging fast, re-check
   `get_review_comments` two to three minutes after the merge and open a
   follow-up for anything found. A merged PR is not a closed review.
2. **Check all four surfaces**: `get_reviews`, `get_review_comments`,
   `get_comments`, and issue comments. Codex uses the second.

---

## 7. What the existing checks *did* catch

For calibration, so the lesson is not "my checks were worthless." Two of the
largest errors in the impact layer were caught before any review saw the code,
both by aggregate invariants:

- **The 5× denominator.** Team-additivity calibration used the lineup-*exploded*
  possession total as its denominator, computing the mean player RAPM rather than
  the five-player sum. It reported attenuation 0.128 and a league-best WAR of
  24.65. The WAR figure was implausible on its face; the ratio turned out to be
  exactly 5.0.
- **The centring offset.** Ridge only constrains the sum of the offensive and
  defensive blocks against the intercept, leaving +0.25/100 in every rating and
  league WAA at +29.5 rather than 0.

Both violated an invariant *loudly*, which is what aggregate checks are good for:
they catch large errors and errors of the wrong order of magnitude. They caught
nothing in §4, because nothing in §4 is large.

---

## 8. Carry-forward checklist

Ordered by leverage, for this module and for sibling analysis modules.

**Process**
1. Wait for the automated review before merging; re-check after merging if you did not.
2. Check all four PR comment surfaces, not the two that are convenient.
3. Before implementing any modelling primitive, grep the repo for it first.

**Verifier design**
4. Derive, never enumerate — parse the table, walk every occurrence.
5. Reject obsolete values; do not merely confirm a fresh one is present somewhere.
6. Negative-test every check by reintroducing the bug it targets, and assert the
   file actually changed before trusting the result.
7. Re-read each docstring against its implementation: does the pattern cover the
   class the sentence promises, or only the instance you last saw?
8. Make exemption lists self-checking, so a stale exemption is itself reported.

**Modelling**
9. Every term gets its own exposure. Offensive coefficients take offensive
   possessions; defensive take defensive; net quantities take the mean.
10. Cross-validation folds go at the grain correlation lives at — by game, never
    by row.
11. Calibrate each side against its own aggregate, not a combined one through a
    single side's lineups.
12. Include the nuisance controls the design demands (home court), unpenalised.
13. Write at least one check at the *unit* grain — per player, per possession —
    because aggregate invariants cannot see errors that cancel.
14. Before concluding a dimension is unverifiable, check whether a superseded or
    partial-coverage dataset can still validate it over the overlap. A file you
    are replacing is still a reference for the range it does cover — being framed
    as the problem is what makes it invisible as a resource.
15. Failing that, check the dimension internally. Absence of an external
    reference is not absence of a testable property, and an internal invariant
    (snapshot at start, assert at end) often needs no reference at all.
16. Be suspicious when the dimensions you validated are exactly the ones that
    were convenient to validate. That correlation is usually the explanation,
    not a coincidence.

**Documentation**
17. Regenerate prose after the last code change, not before it.
18. When you hedge a claim, do not write past the hedge in the next clause.

---

## 9. Postscript: this document drew two findings of its own

Codex reviewed the PR that added this file and raised two P2s. Both were real,
and one of them is the document's own thesis landing on the document.

**The enumerate-don't-derive bug had recurred inside the fix that named it.**
The #45-4 repair generalised the *range* half of `CLOSED_WINDOW_PROSE` properly
— any numeric endpoint, any `g3x-3x` — and then wrote the *count* half as
`one|two|…|twelve`. §3 above described that as covering "any spelled or numeric
post-injury game count." It covered twelve of them. The return window grows every
refresh, so `thirteen post-injury games` was a scheduled failure, and the row
claiming the fix was the thing that would have kept anyone from looking. I wrote
a paragraph criticising enumeration and shipped an enumeration in the sentence
under it.

Now derived: any leading token before `post-injury games` is treated as a count
unless it appears in a short list of open determiners (`her`, `the`, `all`,
`several`, …). Negative-tested across eight cases — `thirteen`, `twenty-one`,
`13` and `eleven` rejected; `her`, `all`, `each of these` and `several` accepted
— each with an assertion that the file actually changed before the result was
trusted, per rule 6.

**The co-presence diagnosis in §5 was wrong**, and wrong in a self-serving
direction: I had written that the dimension went unchecked because no external
reference existed. One did, for two thirds of the season. §5 now records the
real reason, which is a worse one, and rules 14–16 replace the comfortable
lesson I had drawn from the false version.

The general shape is worth keeping. A retrospective is written by the same person
whose judgement produced the errors, using the same judgement, and it will
reproduce the same blind spots — including, evidently, in the act of describing
them. That is not an argument against writing one. It is an argument for sending
it through the same review as the code.
