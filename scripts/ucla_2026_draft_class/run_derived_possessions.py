"""Full-season lineup analysis for the UCLA six, on the derived possession layer."""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
warnings.simplefilter("ignore")
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ucla_2026_draft_class"))
import derive_possessions as dp   # noqa: E402

OUT = ROOT / "analysis" / "ucla_2026_draft_class" / "data"
pd.set_option("display.width", 260)

UCLA = {"Lauren Betts": "WAS", "Gabriela Jaquez": "CHI", "Kiki Rice": "TOR",
        "Angela Dugalic": "WAS", "Gianna Kneepkens": "CON", "Charlisse Leger-Walker": "CON"}
DUOS = [("WAS", ["Lauren Betts", "Shakira Austin"]),
        ("WAS", ["Lauren Betts", "Kiki Iriafen"]),
        ("WAS", ["Lauren Betts", "Angela Dugalic"]),
        ("CON", ["Charlisse Leger-Walker", "Gianna Kneepkens"]),
        ("TOR", ["Kiki Rice", "Julie Allemand"]),
        ("CHI", ["Gabriela Jaquez", "Natasha Cloud"])]


def main() -> None:
    poss = dp.calibrate(dp.build())
    poss.to_parquet(OUT / "derived_possessions_2026.parquet", index=False)
    v = dp.validate(poss)
    report = {k: v[k] for k in v if not k.startswith("_")}
    print("VALIDATION:", json.dumps(report, indent=2))

    core = pd.read_csv(ROOT / "analysis/role_fulfillment_matrix/data/live_inputs/player_core_2026.csv")
    eid = dict(zip(core.display_name, core.athlete_id))
    e = dp.load_pbp()
    tid = {r.home_abbr: int(r.home_team_id)
           for _, r in e[["home_team_id", "home_abbr"]].drop_duplicates().iterrows()}

    # 1 — duo splits
    frames = []
    for team, names in DUOS:
        ids = [int(eid[n]) for n in names]
        lab = {int(eid[n]): n.split()[-1] for n in names}
        t = dp.lineup_splits(poss, ids, tid[team], lab)
        t.insert(0, "pair", " + ".join(n.split()[-1] for n in names))
        t.insert(0, "team", team)
        frames.append(t)
        print(f"\n-- {team}: {t.pair.iloc[0]}")
        print(t[t.off_poss >= 40][["state", "off_poss", "def_poss", "ortg", "drtg", "net"]]
              .round(1).to_string(index=False))
    duos = pd.concat(frames)
    duos.to_csv(OUT / "story_duo_splits_full_season.csv", index=False)

    # 2 — possession-level on/off for each of the six, full season
    rows = []
    for name, team in UCLA.items():
        p = int(eid[name])
        t = dp.lineup_splits(poss, [p], tid[team], {p: "on"})
        on = t[t.state == "on"].iloc[0]
        off = t[t.state == "none"].iloc[0]
        rows.append(dict(player=name, team=team,
                         on_poss=on.off_poss, on_ortg=on.ortg, on_drtg=on.drtg, on_net=on.net,
                         off_poss=off.off_poss, off_ortg=off.ortg, off_drtg=off.drtg,
                         off_net=off.net, net_swing=on.net - off.net))
    onoff = pd.DataFrame(rows).sort_values("net_swing", ascending=False)
    onoff.to_csv(OUT / "story_derived_onoff_full_season.csv", index=False)
    print("\n### Possession-level on/off, full season (derived)")
    print(onoff.round(2).to_string(index=False))

    # 3 — Rice's return windows on the derived layer
    tg = pd.read_parquet(dp.PBP_TEAM)
    tg["game_date"] = pd.to_datetime(tg.game_date)
    tor = tg[tg.team_abbreviation == "TOR"].sort_values("game_date").reset_index(drop=True)
    tor["tgn"] = np.arange(1, len(tor) + 1)
    gmap = dict(zip(tor.game_id, tor.tgn))
    rp = poss[poss.pbp_game_id.isin(gmap)].copy()
    rp["tgn"] = rp.pbp_game_id.map(gmap)
    rp["block"] = np.select(
        [rp.tgn <= 10, rp.tgn.between(11, 26), rp.tgn.between(27, 31)],
        ["Pre-injury (g1-10)", "Rice OUT (g11-26)", "Return games 1-5 (g27-31)"], "Return games 6+ (g32+)")
    rid = int(eid["Kiki Rice"])
    out = []
    for b, g in rp.groupby("block"):
        t = dp.lineup_splits(g, [rid], tid["TOR"], {rid: "on"})
        on = t[t.state == "on"]
        off = t[t.state == "none"]
        out.append(dict(block=b,
                        on_poss=float(on.off_poss.iloc[0]) if len(on) else 0.0,
                        on_net=float(on.net.iloc[0]) if len(on) else np.nan,
                        off_net=float(off.net.iloc[0]) if len(off) else np.nan))
    rice = pd.DataFrame(out)
    rice["net_swing"] = rice.on_net - rice.off_net
    rice.to_csv(OUT / "story_rice_blocks_derived.csv", index=False)
    print("\n### Kiki Rice on/off by block, derived possession layer")
    print(rice.round(2).to_string(index=False))

    # 4 - how far can this layer be trusted?
    from onoff import build_on_off
    pg = pd.read_parquet(dp.PBP_PLAYER); pg["player_id"] = pg.player_id.astype(int)
    exact = build_on_off(pg, tg)
    esp2pbp = {v: k for k, v in dp.player_crosswalk().items()}
    tgames = tg.groupby("team_abbreviation").game_id.nunique().to_dict()
    rows = []
    for abbr, team in tid.items():
        for pid, g in pg[pg.team_abbreviation == abbr].groupby("player_id"):
            eid_ = esp2pbp.get(int(pid))
            if eid_ is None or g.off_poss.sum() < 150:
                continue
            t = dp.lineup_splits(poss, [int(eid_)], team, {int(eid_): "on"})
            on, off = t[t.state == "on"], t[t.state == "none"]
            if not len(on) or not len(off):
                continue
            rows.append(dict(player_id=pid, poss=float(on.off_poss.iloc[0]),
                             availability=g.game_id.nunique() / tgames[abbr],
                             derived_swing=float(on.net.iloc[0] - off.net.iloc[0])))
    nz = pd.DataFrame(rows).merge(exact[["player_id", "net_swing"]], on="player_id")
    nz["err"] = nz.derived_swing - nz.net_swing
    nz.to_csv(OUT / "derived_vs_exact_onoff.csv", index=False)
    ever = nz[nz.availability >= 0.95]
    noise = dict(
        all_players=dict(n=len(nz), corr=float(nz.derived_swing.corr(nz.net_swing)),
                         mae=float(nz.err.abs().mean())),
        ever_present=dict(n=len(ever), corr=float(ever.derived_swing.corr(ever.net_swing)),
                          mae=float(ever.err.abs().mean()), sd=float(ever.err.std())),
        note=("The all-players gap is mostly a definition difference, not error: pbpstats "
              "on/off is computed only within games a player appeared in, while the derived "
              "layer's off-court pool also contains games she missed. Restricting to players "
              "who appeared in 95%+ of team games isolates true reconstruction noise."),
    )
    print("\n### Derived vs pbpstats-exact on/off")
    print(json.dumps(noise, indent=2))

    # 5 - same-window replication against the frozen parquet
    stale = pd.read_parquet(dp.SDV / "wnba_possessions_2026.parquet")
    window = poss[poss.pbp_game_id.astype(str).isin(set(stale.game_id.astype(str)))]
    ids = [int(eid["Lauren Betts"]), int(eid["Shakira Austin"])]
    rep = dp.lineup_splits(window, ids, tid["WAS"], {ids[0]: "Betts", ids[1]: "Austin"})
    rep.to_csv(OUT / "derived_stale_window_replication.csv", index=False)
    print(f"\n### Replication on the frozen parquet's {window.pbp_game_id.nunique()} games")
    print(rep[["state", "off_poss", "ortg", "drtg", "net"]].round(1).to_string(index=False))

    (OUT / "derived_possessions_manifest.json").write_text(json.dumps(dict(
        noise=noise,
        source="espn_pbp_2026.parquet replayed into possessions + lineups",
        games=int(poss.pbp_game_id.nunique()),
        possessions=int(len(poss)),
        through=str(pd.to_datetime(poss.game_date).max().date()),
        validation=report,
        replaces="wnba_possessions_2026.parquet (frozen at 202 games)",
    ), indent=2, default=float))


if __name__ == "__main__":
    main()
