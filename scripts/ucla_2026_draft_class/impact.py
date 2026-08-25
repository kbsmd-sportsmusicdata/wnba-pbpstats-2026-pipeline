"""RAPM and WAR for the 2026 season, computed in-repo from the possession layer.

Why this exists
---------------
`wnba_player_impact_2026.parquet` is frozen at gp <= 29 (mid-July) while the
rest of the pipeline runs through the full season. Its RAPM is therefore a
first-two-thirds verdict, and several of its other columns are unusable
regardless of vintage: `adj_rapm` has a standard deviation of 4.66 against
`rapm`'s 0.85, `obpm`/`dbpm` are miscentred at -3.4 / +2.8, and
`darko_filtered_skill` correlates with `rapm` at exactly 1.000 -- it is a
duplicate column, not an independent estimate.

RAPM is the one impact metric that can be honestly rebuilt here, because the
derived possession layer provides exactly what it needs: every possession with
both five-player lineups and the points scored. That is the canonical RAPM
input, not a proxy for it.

BPM deliberately is not built. BPM is not a formula applied to a box score; it
is a regression of box-score rates onto long-run RAPM, and its published
coefficients come from 14+ NBA seasons. Fitting that regression on one WNBA
season gives a cross-validated R-squared of -0.09 -- worse than predicting the
mean -- so locally estimated coefficients would be noise, and transplanting the
NBA set onto a different scoring environment would be the proxy this layer
exists to avoid. See IMPACT_LAYER.md.

Method
------
Ridge regression over possessions. Each row carries +1 for the five offensive
players and +1 in a separate defensive block for the five defenders; the
response is points per 100 possessions. The penalty is chosen by 5-fold
cross-validation rather than assumed. Possession weights come from the
calibration in `derive_possessions.py`, so rates sit on the pbpstats scale.

WAR needs two things RAPM does not: a points-per-win rate and a replacement
level. The first is estimated from this season's own win%-to-margin
relationship rather than borrowed. The second is a convention, stated as a
parameter -- so wins above *average* (WAA), which needs no such choice, is
reported alongside it and is the safer number to quote.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ucla_2026_draft_class"))
sys.path.insert(0, str(ROOT / "scripts" / "possession_impact"))
import derive_possessions as dp  # noqa: E402
from rapm import game_folds  # noqa: E402  (this repo's existing convention)

OUT = ROOT / "analysis" / "ucla_2026_draft_class" / "data"
POSS = OUT / "derived_possessions_2026.parquet"

ALPHAS = (500, 1000, 2000, 4000, 8000, 16000, 32000)
# Replacement level in points per 100 possessions below league average. This is
# a convention, not a measurement: ridge shrinkage pulls low-possession players
# toward zero, so replacement level cannot be read off the RAPM of fringe
# players -- the estimates there are biased toward average precisely where you
# would want to measure it. -2.0 matches the standard definition used for
# NBA replacement level; WAA is reported alongside for anyone who would rather
# not adopt it.
REPLACEMENT_RAPM = -2.0
MIN_POSS_REPORT = 200


@dataclass
class FitResult:
    alpha: int
    cv_curve: dict
    n_players: int
    n_possessions: int


def design_matrix(poss: pd.DataFrame):
    """One row per possession: +1 for each offensive player, +1 for each defender."""
    players = sorted({p for lu in poss.off_lineup for p in lu}
                     | {p for lu in poss.def_lineup for p in lu})
    idx = {p: i for i, p in enumerate(players)}
    n = len(players)
    rows, cols = [], []
    for r, (off, deff) in enumerate(zip(poss.off_lineup, poss.def_lineup)):
        for p in off:
            rows.append(r); cols.append(idx[p])
        for p in deff:
            rows.append(r); cols.append(idx[p] + n)
    X = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)),
                          shape=(len(poss), 2 * n))
    y = poss.points.values / poss.poss_weight.values * 100
    w = poss.poss_weight.values
    return X, y, w, players


def fit_rapm(X, y, w, game_ids, alphas=ALPHAS, seed=0, folds=5):
    """Choose the ridge penalty by cross-validation, then fit on everything.

    Folds are assigned by game, not by row. Possessions within a game share
    lineups and game context, so splitting them at random leaks information
    into the held-out set and the curve stops describing out-of-game
    performance. `scripts/possession_impact/rapm.py` already established this
    convention in the repo, so its helper is reused rather than reimplemented.
    """
    assignment = game_folds(game_ids, folds, seed)
    curve = {}
    for a in alphas:
        errs = []
        for k in range(folds):
            tr = np.where(assignment != k)[0]
            te = np.where(assignment == k)[0]
            m = Ridge(alpha=a, solver="sparse_cg", max_iter=2000)
            m.fit(X[tr], y[tr], sample_weight=w[tr])
            errs.append(np.average((y[te] - m.predict(X[te])) ** 2, weights=w[te]))
        curve[a] = float(np.mean(errs))
    best = min(curve, key=curve.get)
    model = Ridge(alpha=best, solver="sparse_cg", max_iter=5000)
    model.fit(X, y, sample_weight=w)
    return model, best, curve


def coefficients(model, players, off_w: pd.Series | None = None,
                 def_w: pd.Series | None = None) -> pd.DataFrame:
    """Player coefficients, sign-aligned and centred.

    A defensive coefficient lowers opponent scoring, so its sign is flipped to
    make "higher is better" true on every column.

    Centring matters and is easy to miss. Ridge fixes only the *sum* of the
    offensive and defensive blocks against the intercept, not where the league
    average sits within each block, so the raw split leaves an arbitrary
    constant in both. Left alone it shifts every rating by the same amount and
    silently inflates (or deflates) every WAR. Each block is therefore centred
    to a possession-weighted mean of zero, which makes league-average impact
    exactly zero and league-wide wins-above-average sum to zero.

    Each block is centred against *its own* exposure. Weighting the defensive
    block by offensive possessions would leave a small residual, for the same
    reason a player's two possession counts cannot be used interchangeably
    anywhere else in this module.
    """
    n = len(players)
    df = pd.DataFrame({"espn_id": players, "o_rapm": model.coef_[:n],
                       "d_rapm": -model.coef_[n:]})
    for col, weights in (("o_rapm", off_w), ("d_rapm", def_w if def_w is not None else off_w)):
        if weights is None:
            continue
        w = df.espn_id.map(weights).fillna(0).values
        if w.sum() > 0:
            df[col] = df[col] - np.average(df[col], weights=w)
    df["rapm"] = df.o_rapm + df.d_rapm
    return df


def possession_counts(poss: pd.DataFrame, side: str = "off") -> pd.Series:
    """Calibrated possessions a player was on the floor for, per side.

    Offensive and defensive exposure are not identical -- substitutions land
    between possessions and periods end unevenly -- so each coefficient has to
    be charged against its own count rather than a single shared one.
    """
    col = f"{side}_lineup"
    ex = poss[[col, "poss_weight"]].explode(col)
    return ex.groupby(col).poss_weight.sum()


def split_half_reliability(poss: pd.DataFrame, alpha: int) -> dict:
    """Fit odd and even games separately and correlate. The honest error bar."""
    games = sorted(poss.pbp_game_id.unique())
    halves = []
    for sel in (games[0::2], games[1::2]):
        sub = poss[poss.pbp_game_id.isin(sel)]
        X, y, w, players = design_matrix(sub)
        m = Ridge(alpha=alpha, solver="sparse_cg", max_iter=5000)
        m.fit(X, y, sample_weight=w)
        halves.append(coefficients(m, players, possession_counts(sub, "off"),
                                   possession_counts(sub, "def"))
                      .set_index("espn_id").rapm)
    a, b = halves
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    counts = possession_counts(poss)
    joined["poss"] = counts.reindex(joined.index)
    out = {}
    for cut in (200, 500, 1000):
        s = joined[joined.poss >= cut]
        r = float(s.a.corr(s.b))
        out[f"{cut}+_poss"] = {
            "n": int(len(s)), "half_r": round(r, 3),
            # Spearman-Brown: reliability of the full-season estimate given the
            # correlation between two half-season estimates
            "full_season_reliability": round(2 * r / (1 + r), 3) if r > 0 else None,
        }
    return out


def points_per_win(tg: pd.DataFrame) -> dict:
    """Points of margin per marginal win, from this season's own results."""
    t = tg.groupby("team_abbreviation", as_index=False).agg(
        g=("game_id", "nunique"), w=("win", "sum"),
        pf=("points", "sum"), pa=("opponent_points", "sum"))
    t["win_pct"] = t.w / t.g
    t["mov"] = (t.pf - t.pa) / t.g
    slope, intercept = np.polyfit(t.mov, t.win_pct, 1)
    r2 = float(np.corrcoef(t.mov, t.win_pct)[0, 1] ** 2)
    # wins above .500 = G * slope * MOV; total point differential = G * MOV,
    # so points per marginal win is simply 1 / slope
    return {"points_per_win": float(1 / slope), "win_pct_on_mov_slope": float(slope),
            "intercept": float(intercept), "r2": r2, "teams": int(len(t))}


def add_wins(rapm: pd.DataFrame, ppw: float,
             replacement: float = REPLACEMENT_RAPM) -> pd.DataFrame:
    """Convert impact into wins.

    Two things this has to get right. It uses the calibrated columns, not the
    raw ridge ones -- the replacement convention is expressed in real points
    per 100, so applying it to shrunk coefficients would compare quantities on
    two different scales. And it charges each component against its own
    exposure: a player's offensive and defensive possession counts differ, so
    multiplying the combined coefficient by one shared count would assign the
    defensive rating the wrong workload.
    """
    d = rapm.copy()
    d["marginal_pts_vs_average"] = (d.o_rapm_scaled * d.off_poss
                                    + d.d_rapm_scaled * d.def_poss) / 100
    # replacement is a net rate, so it is charged against time on the floor,
    # taken as the mean of the two exposures
    exposure = (d.off_poss + d.def_poss) / 2
    d["marginal_pts_vs_replacement"] = (d.marginal_pts_vs_average
                                        - replacement * exposure / 100)
    d["waa"] = d.marginal_pts_vs_average / ppw
    d["war"] = d.marginal_pts_vs_replacement / ppw
    return d


def team_additivity_check(rapm: pd.DataFrame, poss: pd.DataFrame,
                          tg: pd.DataFrame, suffix: str = "") -> dict:
    """Does the additive model reproduce team ratings, and at what scale?

    RAPM assumes a lineup's rating is the sum of its five players, so aggregated
    over a season the coefficients should recover each team's offensive and
    defensive ratings relative to league average.

    Offence and defence are aggregated through their own lineups and their own
    possession counts. A team's offensive exposure is not its defensive
    exposure, so pushing the combined coefficient through `off_lineup` alone
    would measure something that is not the additive model's attenuation -- and
    every scaled coefficient and every WAR is divided by that number.

    Ridge shrinks, so the *ordering* is reproduced closely while the *spread* is
    compressed. Regressing predicted on actual recovers the compression, which
    is what `attenuation` reports, separately per side because the two need not
    shrink alike.
    """
    e = dp.load_pbp()
    tmap = pd.concat([
        e[["home_team_id", "home_abbr"]].rename(columns={"home_team_id": "tid", "home_abbr": "abbr"}),
        e[["away_team_id", "away_abbr"]].rename(columns={"away_team_id": "tid", "away_abbr": "abbr"}),
    ]).drop_duplicates()
    tmap["tid"] = tmap.tid.astype(int)
    id2abbr = dict(zip(tmap.tid, tmap.abbr))

    p = poss.copy()
    p["off_abbr_"] = p.off_team.map(id2abbr)
    p["def_abbr_"] = p.def_team.map(id2abbr)

    def side_pred(lineup_col, team_col, coef_col):
        # true team possession totals; the lineup explosion multiplies by five
        denom = p.groupby(team_col).poss_weight.sum()
        ex = p[[team_col, lineup_col, "poss_weight"]].explode(lineup_col)
        agg = ex.groupby([team_col, lineup_col]).poss_weight.sum().reset_index()
        agg = agg.merge(rapm[["espn_id", coef_col]], left_on=lineup_col,
                        right_on="espn_id", how="left").dropna(subset=[coef_col])
        return (agg.assign(c=agg[coef_col] * agg.poss_weight)
                   .groupby(team_col).c.sum() / denom)

    pred_o = side_pred("off_lineup", "off_abbr_", f"o_rapm{suffix}")
    pred_d = side_pred("def_lineup", "def_abbr_", f"d_rapm{suffix}")

    lg_o = tg.points.sum() / tg.off_poss.sum() * 100
    lg_d = tg.opponent_points.sum() / tg.def_poss.sum() * 100
    grp = tg.groupby("team_abbreviation")
    act_o = grp.apply(lambda x: x.points.sum() / x.off_poss.sum() * 100 - lg_o)
    # positive means good defence, matching the sign convention on d_rapm
    act_d = grp.apply(lambda x: -(x.opponent_points.sum() / x.def_poss.sum() * 100 - lg_d))

    out = {}
    for name, pred, act in (("offense", pred_o, act_o), ("defense", pred_d, act_d)):
        c = pd.concat([pred.rename("p"), act.rename("a")], axis=1).dropna()
        out[name] = {"r": round(float(c.p.corr(c.a)), 3),
                     "attenuation": round(float(np.polyfit(c.a, c.p, 1)[0]), 3)}
    net = pd.concat([(pred_o + pred_d).rename("p"), (act_o + act_d).rename("a")],
                    axis=1).dropna()
    out["net"] = {"teams": int(len(net)), "r": round(float(net.p.corr(net.a)), 3),
                  "mae": round(float((net.p - net.a).abs().mean()), 2),
                  "attenuation": round(float(np.polyfit(net.a, net.p, 1)[0]), 3)}
    return out


def main() -> None:
    poss = pd.read_parquet(POSS)
    poss = poss[poss.valid]
    tg = pd.read_parquet(dp.PBP_TEAM)

    X, y, w, players = design_matrix(poss)
    model, alpha, curve = fit_rapm(X, y, w, poss.pbp_game_id.values)
    off_counts = possession_counts(poss, "off")
    def_counts = possession_counts(poss, "def")
    rapm = coefficients(model, players, off_counts, def_counts)
    rapm["off_poss"] = rapm.espn_id.map(off_counts).fillna(0)
    rapm["def_poss"] = rapm.espn_id.map(def_counts).fillna(0)
    rapm["poss"] = rapm.off_poss

    xw = pd.read_csv(dp.CROSSWALK)
    xw["player_id"] = pd.to_numeric(xw.player_id, errors="coerce")
    xw = xw.dropna(subset=["espn_athlete_id"]).drop_duplicates("espn_athlete_id")
    rapm = rapm.merge(
        xw[["espn_athlete_id", "player_id", "pbpstats_player_name", "team_abbreviation"]]
        .rename(columns={"espn_athlete_id": "espn_id", "pbpstats_player_name": "player_name"}),
        on="espn_id", how="left")

    # calibrate each side to its own observed team scale before converting to
    # wins; offence and defence need not shrink by the same factor
    raw_fit = team_additivity_check(rapm, poss, tg)
    att_o = raw_fit["offense"]["attenuation"]
    att_d = raw_fit["defense"]["attenuation"]
    rapm["o_rapm_scaled"] = rapm.o_rapm / att_o
    rapm["d_rapm_scaled"] = rapm.d_rapm / att_d
    rapm["rapm_scaled"] = rapm.o_rapm_scaled + rapm.d_rapm_scaled

    ppw = points_per_win(tg)
    rapm = add_wins(rapm, ppw["points_per_win"])
    rapm = rapm.sort_values("rapm", ascending=False).reset_index(drop=True)

    reliability = split_half_reliability(poss, alpha)
    additivity = {"raw_ridge": raw_fit,
                  "calibrated": team_additivity_check(rapm, poss, tg, suffix="_scaled")}

    rapm.to_csv(OUT / "impact_rapm_war_2026.csv", index=False)
    ucla = ["Lauren Betts", "Gabriela Jaquez", "Kiki Rice", "Angela Dugalic",
            "Gianna Kneepkens", "Charlisse Leger-Walker"]
    six = rapm[rapm.player_name.isin(ucla)].copy()
    six["rapm_pctile_200plus"] = [
        round(float((rapm[rapm.poss >= MIN_POSS_REPORT].rapm < v).mean() * 100), 1)
        for v in six.rapm]
    six.to_csv(OUT / "story_ucla_six_impact.csv", index=False)

    # sensitivity of WAR to the replacement convention. Select by membership
    # rather than reindexing: two players in the possession layer have no
    # crosswalk entry, so the name column carries nulls.
    sens = {}
    for r in (-1.0, -1.5, -2.0, -2.5, -3.0):
        w_r = add_wins(rapm, ppw["points_per_win"], r)
        sens[f"{r:+.1f}"] = round(float(w_r.loc[w_r.player_name.isin(ucla), "war"].sum()), 2)

    manifest = {
        "built_from": "derived_possessions_2026.parquet",
        "games": int(poss.pbp_game_id.nunique()),
        "possessions": int(len(poss)),
        "players": int(len(players)),
        "players_without_crosswalk_name": int(rapm.player_name.isna().sum()),
        "ridge_alpha": int(alpha),
        "cv_curve_weighted_mse": {str(k): round(v, 2) for k, v in curve.items()},
        "rapm_poss_weighted_mean": round(
            float(np.average(rapm.rapm, weights=rapm.poss)), 4),
        "league_waa_total": round(float(rapm.waa.sum()), 2),
        "league_war_total": round(float(rapm.war.sum()), 2),
        "rapm_sd_raw": round(float(rapm.rapm.std()), 3),
        "rapm_sd_scaled": round(float(rapm.rapm_scaled.std()), 3),
        "attenuation_offense": att_o,
        "attenuation_defense": att_d,
        "split_half_reliability": reliability,
        "team_additivity": additivity,
        "points_per_win": {k: (round(v, 4) if isinstance(v, float) else v)
                           for k, v in ppw.items()},
        "replacement_rapm": REPLACEMENT_RAPM,
        # WAA sums to zero by construction, so league-total WAR is purely a
        # function of the replacement constant. Expressing it as the win rate an
        # all-replacement league would post makes the convention checkable:
        # anything far from the low-20s would mean the constant is wrong.
        "implied_replacement_win_pct": round(
            float((tg.win.sum() - rapm.war.sum()) / tg.game_id.nunique() / 2), 3),
        "ucla_six_total_war_by_replacement_level": sens,
        "bpm": "not built - see IMPACT_LAYER.md; box-score-to-RAPM regression "
               "cross-validates at R2 = -0.09 on a single season",
    }
    (OUT / "impact_manifest.json").write_text(json.dumps(manifest, indent=2))

    pd.set_option("display.width", 220)
    print(json.dumps(manifest, indent=2))
    print("\n### Top 12 by RAPM (1000+ possessions)")
    q = rapm[rapm.poss >= 1000]
    print(q.head(12)[["player_name", "team_abbreviation", "poss", "o_rapm",
                      "d_rapm", "rapm", "rapm_scaled", "waa",
                      "war"]].round(2).to_string(index=False))
    print("\n### UCLA six")
    print(six[["player_name", "team_abbreviation", "poss", "o_rapm", "d_rapm",
               "rapm", "rapm_scaled", "rapm_pctile_200plus", "waa",
               "war"]].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
