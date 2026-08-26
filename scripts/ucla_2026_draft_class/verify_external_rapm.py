"""Score this repo's RAPM against an independently published 2026 RAPM.

Why this exists
---------------
Until now the impact layer had exactly one external reference — the frozen
sportsdataverse RAPM, itself stale at mid-July. `REVIEW_LESSONS.md` rules 15-17
say to look for a reference before concluding a dimension is unverifiable, and
this is that reference for the impact layer.

How to read the result
----------------------
Point-estimate correlation is the wrong headline here, for two reasons.

1. The reference covers only its own top 34 (24 rows survive), selected on the
   reference's own metric. That is range restriction on the dependent variable
   and it attenuates any correlation computed on the slice.
2. The reference publishes a standard error of ~2.25, and its entire top-24
   spans 2.6 points -- about 1.16 SE. By its own uncertainty the slice is not
   rank-resolvable, so disagreement in ordering is expected between two correct
   estimators.

The meaningful test is therefore coverage: how often our estimate falls inside
the reference's own published interval. Compare RAW ridge coefficients, not the
calibrated ones -- the reference is a shrunk estimate and ours are de-shrunk by
the attenuation factor, so calibrated values sit on a deliberately wider scale.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis" / "ucla_2026_draft_class" / "data"
REF = OUT / "reference" / "rapm_wnbanalytics_2026.csv"


def compare() -> dict:
    ref = pd.read_csv(REF)
    ours = pd.read_csv(OUT / "impact_rapm_war_2026.csv")
    j = ref.merge(ours, left_on="Player", right_on="player_name", how="left")
    unmatched = j[j.player_name.isna()].Player.tolist()
    j = j.dropna(subset=["player_name"])

    j["in_band_raw"] = (j.rapm >= j.LO) & (j.rapm <= j.HI)
    j["in_band_scaled"] = (j.rapm_scaled >= j.LO) & (j.rapm_scaled <= j.HI)
    lo, hi = j[j.GP < 20], j[j.GP >= 30]

    return dict(
        reference="independently published 2026 WNBA RAPM (top 34; 24 rows)",
        matched=int(len(j)), unmatched=unmatched,
        team_agreement=int((j.TEAM == j.team_abbreviation).sum()),
        reference_median_se=round(float(j.SE.median()), 2),
        reference_span_in_se=round(float((j.RAPM.max() - j.RAPM.min()) / j.SE.median()), 2),
        raw_inside_reference_interval=int(j.in_band_raw.sum()),
        scaled_inside_reference_interval=int(j.in_band_scaled.sum()),
        mean_signed_z=round(float(((j.rapm_scaled - j.RAPM) / j.SE).mean()), 2),
        pearson_raw=round(float(j.RAPM.corr(j.rapm)), 3),
        spearman_raw=round(float(j.RAPM.corr(j.rapm, method="spearman")), 3),
        pearson_defence=round(float(j.DEFRAPM.corr(j.d_rapm)), 3),
        mean_diff_gp_under_20=round(float((lo.rapm - lo.RAPM).mean()), 2),
        mean_diff_gp_30_plus=round(float((hi.rapm - hi.RAPM).mean()), 2),
        note="Coverage against the reference's own interval is the headline; "
             "correlation on a top-34 slice is range-restricted and its span is "
             "~1.16 SE, so the slice is not rank-resolvable by the reference's "
             "own error bars. The sub-20-game gap is real and unexplained: our "
             "ridge shrinks materially only below ~300 possessions, so shrinkage "
             "toward zero does not account for it, and the reference's method is "
             "not documented here.",
    )


def main() -> int:
    r = compare()
    (OUT / "external_rapm_check.json").write_text(json.dumps(r, indent=2))
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
