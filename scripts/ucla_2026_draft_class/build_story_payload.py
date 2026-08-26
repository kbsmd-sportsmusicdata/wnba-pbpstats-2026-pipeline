"""Emit the single JSON payload the editorial artifact reads.

Every figure in the story comes from here, so nothing in the HTML is hand-typed
and the page can be regenerated after any pipeline refresh. `verify_docs.py`
holds the documents to the same manifests this reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "analysis" / "ucla_2026_draft_class" / "data"
OUT = D / "story_payload.json"

SIX = ["Kiki Rice", "Lauren Betts", "Gabriela Jaquez",
       "Charlisse Leger-Walker", "Gianna Kneepkens", "Angela Dugalic"]


def rd(v, n=2):
    return None if pd.isna(v) else round(float(v), n)


def main() -> int:
    manifest = json.loads((D / "story_manifest.json").read_text())
    impact_man = json.loads((D / "impact_manifest.json").read_text())
    derived_man = json.loads((D / "derived_possessions_manifest.json").read_text())
    ext = json.loads((D / "external_rapm_check.json").read_text())

    prof = pd.read_csv(D / "story_ucla_six_season_profile.csv")
    long = pd.read_csv(D / "story_metric_percentiles_long.csv")
    impact = pd.read_csv(D / "story_ucla_six_impact.csv")
    onoff = pd.read_csv(D / "story_derived_onoff_full_season.csv")
    monthly = pd.read_csv(D / "story_monthly_development.csv")
    duos = pd.read_csv(D / "story_duo_splits_full_season.csv")
    rice_t = pd.read_csv(D / "story_rice_timeline.csv")
    rice_b = pd.read_csv(D / "story_rice_return_blocks_player.csv")
    rice_d = pd.read_csv(D / "story_rice_blocks_derived.csv")
    league = pd.read_csv(D / "story_league_pool_250min.csv")
    teams = pd.read_csv(D / "story_team_context.csv")

    wide = long.pivot(index="player", columns="metric", values="value")
    pct = long.pivot(index="player", columns="metric", values="league_pctile")

    players = []
    for name in SIX:
        i = impact[impact.player_name == name].iloc[0]
        o = onoff[onoff.player == name].iloc[0]
        p = prof[prof.player_name == name].iloc[0]
        w, q = wide.loc[name], pct.loc[name]
        players.append(dict(
            name=name, last=name.split()[-1], team=str(p.teams),
            minutes=rd(p.minutes, 0), mpg=rd(w.min_per_game, 1),
            gp=int(monthly[monthly.player == name].games.sum()),
            usage=rd(w.usage, 1), pts75=rd(w.pace_neutral_pts_75, 1),
            ts=rd(w.ts_pct, 3), sq=rd(w.shot_quality_avg, 3),
            making=rd(w.shot_making_over_sq, 3),
            ast75=rd(w.ast_75, 2), tov75=rd(w.tov_75, 2), foul75=rd(w.foul_75, 2),
            stocks75=rd(w.stocks_75, 2),
            rim_share=rd(w.rim_share, 3), three_share=rd(w.three_share, 3),
            pct=dict(mpg=rd(q.min_per_game, 0), pts75=rd(q.pace_neutral_pts_75, 0),
                     ts=rd(q.ts_pct, 0), sq=rd(q.shot_quality_avg, 0),
                     making=rd(q.shot_making_over_sq, 0), ast75=rd(q.ast_75, 0),
                     stocks75=rd(q.stocks_75, 0), rim_share=rd(q.rim_share, 0)),
            o_rapm=rd(i.o_rapm), d_rapm=rd(i.d_rapm), rapm=rd(i.rapm),
            waa=rd(i.waa), rapm_pctile=rd(i.rapm_pctile_200plus, 0),
            poss=rd(i.poss, 0),
            on_net=rd(o.on_net), off_net=rd(o.off_net), swing=rd(o.net_swing),
            on_poss=rd(o.on_poss, 0),
        ))

    scatter = [dict(x=rd(r.shot_quality_avg, 3), y=rd(r.shot_making_over_sq, 3))
               for r in league.itertuples()
               if not pd.isna(r.shot_quality_avg) and not pd.isna(r.shot_making_over_sq)]

    dg = []
    for pair, g in duos.groupby("pair", sort=False):
        tog = g[g.state.str.contains(r"\+", regex=True)]
        if not len(tog):
            continue
        t = tog.iloc[0]
        others = g[(~g.state.str.contains(r"\+", regex=True)) & (g.state != "none")]
        best = others.loc[others.net.idxmax()] if len(others) else None
        dg.append(dict(pair=str(pair), team=str(g.team.iloc[0]),
                       together=rd(t.net, 1), poss=rd(t.off_poss, 0),
                       best_other=None if best is None else str(best.state),
                       best_other_net=None if best is None else rd(best.net, 1)))

    rt = rice_t[(rice_t.tgn >= 27) & (rice_t.status == "played")]
    payload = dict(
        coverage=dict(games=manifest["games_in_spine"], through=manifest["games_through"],
                      league_pool=manifest["league_pool_size"],
                      rookie_pool=manifest["rookie_pool_size"],
                      possessions=derived_man["possessions"]),
        reliability=dict(
            r200=impact_man["split_half_reliability"]["200+_poss"]["full_season_reliability"],
            att_off=impact_man["attenuation_offense"],
            att_def=impact_man["attenuation_defense"],
            ext_matched=ext["matched"], ext_in_band=ext["raw_inside_reference_interval"],
            ext_se=ext["reference_median_se"], ext_span=ext["reference_span_in_se"]),
        players=players,
        league_scatter=scatter,
        league_swing=[rd(r, 1) for r in league.net_swing.dropna()],
        monthly=[dict(player=str(r.player), month=str(r.month)[-2:], mpg=rd(r.mpg, 1),
                      ts=rd(r.ts_pct, 3), pts75=rd(r.pts75, 1), foul75=rd(r.foul75, 2),
                      on_net=rd(r.on_net, 1), games=int(r.games))
                 for r in monthly.itertuples()],
        duos=dg,
        rice=dict(
            minutes=[dict(g=int(r.tgn), min=rd(r.minutes, 1)) for r in rt.itertuples()],
            blocks=[dict(block=str(r.block), games=int(r.games_played),
                         mpg=rd(r.min_per_game, 1), ts=rd(r.ts_pct, 3),
                         pts75=rd(r.pace_neutral_pts_75, 1),
                         rim_acc=rd(r.rim_accuracy, 2), tov75=rd(r.tov_75, 2))
                    for r in rice_b.itertuples()],
            onoff=[dict(block=str(r.block), on_net=rd(r.on_net, 1),
                        off_net=rd(r.off_net, 1), poss=rd(r.on_poss, 0))
                   for r in rice_d.itertuples()]),
        teams=[dict(team=str(r.team_abbreviation), net=rd(r.net, 1), rank=int(r.net_rank),
                    wins=int(r.wins), games=int(r.games), ucla=bool(r.has_ucla_rookie))
               for r in teams.itertuples()],
    )
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {OUT.name}: {OUT.stat().st_size/1024:.1f} KB, "
          f"{len(players)} players, {len(scatter)} league points, "
          f"{len(payload['monthly'])} monthly rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
