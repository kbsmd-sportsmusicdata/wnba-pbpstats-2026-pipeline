# Role Fulfillment Matrix — Eligibility Coverage Review

Review status: **approved by Krystal Beasley on 2026-08-24**

Eligibility coverage status: **approved, promoted, and regression verified**

## Approved decision

Both newly visible PBPStats identities are approved under the existing `experience_years <= 3`
eligibility rule. Both players are listed as rookies by the WNBA and therefore calculate to zero
years of experience and `eligible_flag = true`. The Michelle Onyiah / Ugonne Onyiah alias match is
explicitly approved.

| Player | PBPStats ID | ESPN ID | Team | WNBA experience | Calculated result | Identity review |
|---|---:|---:|---|---|---|---|
| Michelle Onyiah | 1642803 | 4433744 | IND | Rookie | Eligible | Manual alias: ESPN uses Ugonne Onyiah; WNBA and PBPStats use Michelle Onyiah. |
| Morgan Maly | 1642835 | 4599199 | CHI | Rookie | Eligible | Exact normalized name match. |

## Source evidence

- Michelle Onyiah: WNBA profile `https://www.wnba.com/player/1642803` lists Indiana,
  Forward-Center, birthdate March 12, 2002, and Rookie experience. ESPN identity `4433744` is the
  same California player under the name Ugonne Onyiah.
- Morgan Maly: WNBA profile `https://www.wnba.com/player/1642835` lists Chicago, Forward,
  birthdate January 25, 2002, and Rookie experience. ESPN identity `4599199` is an exact name match.
- The committed source snapshot preserves these reviewed facts and URLs; the manifest pins the
  source, eligibility addendum, and player-core addendum hashes.

## Safeguards

- The original 229-row source evidence remains immutable; the reviewed table now contains 231 rows.
- Both promoted rows have `review_status = reviewed`, `reviewed_by = Krystal Beasley`, and
  `reviewed_at = 2026-08-24`.
- Eligibility is calculated only from the approved threshold: `0 <= 3`.
- Live scoring remains blocked because Michelle Onyiah is now a contender candidate without a
  reviewed primary role assignment.

## Completed promotion

1. Both rows are marked reviewed by Krystal Beasley on 2026-08-24.
2. The eligibility rows are promoted into the 231-row reviewed table and identity crosswalk.
3. The reviewed player-core addendum is configured alongside the immutable base snapshot.
4. The eligibility approval manifest records the new row counts and immutable hashes.
5. Eligibility, PBPStats coverage, and roster-adapter checks pass. The dry-run correctly identifies
   Michelle Onyiah's primary role assignment as the next review gate and prevents a manual live run
   from writing output until it is resolved.
