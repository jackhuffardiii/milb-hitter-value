"""B25 (S26, S27, S30, C22): pitchers on the site. Runs after b9 (hitter site) and b24 (combined board).

leaderboard.json: hitter rows from b9 plus pitcher rows, one combined rank by expected surplus (board_2026), role H / P / 2W.
Hitter cards get the combined rank. Pitcher cards (players/{id}.json, kind "pitcher"): stat lines, the rate chain (raw, park
neutral, MLE, regressed), the projected mERA ladder (display only, C15), role and P(SP) (display only, S24), arsenal by pitch
type (display only, S27), IL flag (S26), P(MLB), ETA, WAR, surplus, drivers. method.json gains a "pitchers" block.
"""
import json

import numpy as np
import pandas as pd

from . import b22_pitch_models as b22
from .b5_features import MEXICAN_LEAGUE
from .b9_site import LEVEL_ORDER, SEASON, SITE, dump, m, r, teams
from .common import DATA

LV = {l: i for i, l in enumerate(LEVEL_ORDER)}
COMPS = ["K", "BB", "HR", "GB", "XB"]


def raw_rates(d):
    bip = d.BF - d.SO - d.BB - d.HBP - d.HR
    return {"K": d.SO / d.BF, "BB": (d.BB - d.IBB.fillna(0)) / d.BF, "HR": d.HR / d.BF, "GB": d.GO / (d.GO + d.AO),
            "XB": (d["2B"] + 2 * d["3B"]) / bip}


def org_lookup(ms, ids, tm):
    cur = ms[(ms.season == SEASON) & ms.player_id.isin(ids)].assign(lv=lambda d: d.level.map(LV))
    top = cur.sort_values(["player_id", "lv", "BF"], ascending=[True, True, False]).drop_duplicates("player_id").set_index("player_id")
    out = {}
    for pid, row in top.iterrows():
        tid = int(str(row.team_ids).split("|")[0]) if pd.notna(row.team_ids) else None
        out[pid] = (tm.get(tid, {}).get("org"), tm.get(tid, {}).get("name"))
    return out


def pitchers_block():
    j = lambda f: json.loads((DATA / f).read_text())  # noqa: E731
    bt, m22 = j("pitch_backtest.json"), j("b22_metrics.json")
    return {"c15": j("b20_c15.json"), "c17": j("b21_c17.json"), "psp": j("b20_psp.json"), "cv": m22["cv_stat"], "c18": m22["c18"],
            "spread": {k: {"chosen": v["chosen"], "c11_pass": v["c11_pass"]} for k, v in m22["spread"].items()},
            "holdout_2013_17": {k: {x: bt["P_MLB_2013_17"]["all"][x] for x in ("n", "logloss", "auc", "war_q10_q90_coverage")} for k in ("stat",)},
            "c3": bt["C3"]["primary_excl_censored"], "c4_pass": bt["C4"]["all_pass"], "c2": bt["C2"]["primary_excl_censored"]["pooled"],
            "c2_n": bt["C2"]["primary_excl_censored"]["n"], "c12": bt["C12"]["ev_vs_war_thru_2026"]["all"],
            "c12_lists": bt["C12"]["lists_2019_2020_vs_war_thru_2026"]["pooled"], "c12_lists_n": bt["C12"]["lists_2019_2020_vs_war_thru_2026"]["n"],
            "combined": bt["combined_board_2013_17"], "c19": j("b24_c19.json"), "sensitivity": j("b24_sensitivity.json"),
            "war_profile": pd.read_parquet(DATA / "pitch_war_profile.parquet")[["control_year", "share"]].to_dict("records")}


def main():
    np.seterr(all="ignore")
    b = pd.read_parquet(DATA / "board_2026.parquet").set_index("player_id")
    lbj = json.loads((SITE / "leaderboard.json").read_text())
    lbj["rows"] = [x for x in lbj["rows"] if x.get("role") != "P"]  # rerunnable without b9
    n = len(b)
    for row in lbj["rows"]:
        row["rank"], row["role"] = int(b.loc[row["id"], "rank"]), b.loc[row["id"], "role"]
    for f in (SITE / "players").glob("*.json"):  # b9 wrote hitter cards with hitter-only ranks
        c = json.loads(f.read_text())
        c.update(kind="hitter", rank=int(b.loc[c["id"], "rank"]), n_ranked=n)
        dump(f, c)

    v = pd.read_parquet(DATA / "pitch_valuations.parquet").query("fit == 'final' and season == @SEASON")
    v = v[v.player_id.isin(b.index[b.role == "P"])].set_index("player_id")
    pp = pd.read_parquet(DATA / "pitch_predictions.parquet").query("fit == 'final' and season == @SEASON").set_index("player_id")
    ft, _ = b22.contact_adjust(pd.read_parquet(DATA / "pitch_features.parquet"))
    ft = ft[ft.season == SEASON].set_index("player_id")
    ms = pd.read_parquet(DATA / "milb_pitching_seasons.parquet")
    ms = ms[ms.league_id != MEXICAN_LEAGUE]
    mle = pd.read_parquet(DATA / "pitch_mle.parquet").query("season == @SEASON")
    mera = pd.read_parquet(DATA / "pitch_mera.parquet").query("season == @SEASON")
    ms_ = pd.read_parquet(DATA / "pitch_mera_player_season.parquet").query("season == @SEASON").set_index("player_id")
    ars = pd.read_parquet(DATA / "pitch_arsenal.parquet").query("season >= @SEASON - 1")
    con = pd.read_parquet(DATA / "pitch_contact.parquet").query("season == @SEASON").set_index("player_id")
    dg = pd.read_parquet(DATA / "pitch_drivers_grouped.parquet").query("fit == 'final' and season == @SEASON")
    ply = pd.read_parquet(DATA / "pitch_players.parquet").set_index("player_id")
    org = org_lookup(ms, set(v.index), teams())
    by = lambda d: {k: g for k, g in d.groupby("player_id")}  # noqa: E731
    ms_by, mle_by, mera_by, ars_by, dg_by = by(ms[ms.season >= SEASON - 2]), by(mle), by(mera), by(ars), by(dg)
    pd_cols = [c for c in v.columns if c.startswith("p_debut_")]
    drv = lambda g, t: [dict(family=y.family, c=r(y.contribution, 3), phrase=y.phrase, sup=int(bool(y.suppressed)))  # noqa: E731
                        for y in g[g.target == t].sort_values("rank").itertuples()]

    for pid, x in v.iterrows():
        f, p = ft.loc[pid], pp.loc[pid]
        stat = x.group == "stat"
        sp = "SP" if stat and f.p_sp >= .5 else ("RP" if stat else None)
        org_, team = org.get(pid, (None, None))
        lbj["rows"].append(dict(id=int(pid), name=f["name"], org=org_, team=team, level=f.highest_level, age=r(f.age, 1),
                                pos=(f.throws + "HP") if pd.notna(f.throws) else "P", mlb_pos=sp, group=x.group, low_conf=bool(x.low_confidence),
                                p_mlb=r(x.p_mlb, 4), war=r(x.war_mean, 2), eta=None if x.debuted else r(x.eta_mean, 2), ev=m(x.ev_surplus),
                                q10=m(x.surplus_q10), q90=m(x.surplus_q90), rank=int(b.loc[pid, "rank"]), in_mlb=bool(x.debuted), role="P"))
        hist = []
        h = ms_by.get(pid)
        if h is not None:
            h = h.assign(lv=h.level.map(LV)).sort_values(["season", "lv"], ascending=[False, True])
            rr = raw_rates(h)
            for i, y in enumerate(h.itertuples()):
                hist.append(dict(season=int(y.season), level=y.level, G=int(y.G), GS=int(y.GS), IP=r(y.outs / 3, 1), BF=int(y.BF),
                                 K=r(rr["K"].iloc[i]), BB=r(rr["BB"].iloc[i]), HR=r(rr["HR"].iloc[i]), GB=r(rr["GB"].iloc[i]),
                                 BABIP=r(y.BABIP), RA9=r(y.RA9, 2)))
        chain = []
        c = mle_by.get(pid)
        if c is not None:
            raw = ms[(ms.player_id == pid) & (ms.season == SEASON)].set_index(["level", "league_id"])
            rr = raw_rates(raw)
            for y in c.assign(lv=c.level.map(LV)).sort_values("lv").itertuples():
                key = (y.level, y.league_id)
                row = dict(level=y.level, BF=int(y.BF))
                for k in COMPS:
                    row[k] = [r(rr[k].get(key)), r(getattr(y, "neutral_" + k)), r(getattr(y, "mle_" + k)), r(getattr(y, "reg_" + k))]
                chain.append(row)
        me = mera_by.get(pid)
        ladder = None
        if me is not None and stat:
            w = me.BF / me.BF.sum()
            ladder = {lv: r((me["mera_" + lv] * w).sum(min_count=1), 2) for lv in ("a", "a+", "aa", "aaa")}
        a = ars_by.get(pid)
        arsenal = [] if a is None else [
            dict(season=int(y.season), type=y.pitch_type, family=y.family, n=int(y.pitches), usage=r(y.usage), velo=r(y.velocity, 1),
                 spin=r(y.spin_rate, 0), ivb=r(y.ivb, 1), hb=r(y.hb, 1), ext=r(y.release_extension, 1), whiff=r(y.whiff))
            for y in a.sort_values(["season", "pitches"], ascending=[False, False]).itertuples()]
        g = dg_by.get(pid)
        pl = ply.loc[pid] if pid in ply.index else None
        card = dict(
            kind="pitcher", id=int(pid), name=f["name"], season=SEASON, run_date=lbj["run_date"], people_pulled_on=lbj["people_pulled_on"],
            data_through=lbj["data_through"], rank=int(b.loc[pid, "rank"]), n_ranked=n, org=org_, team=team, level=f.highest_level,
            age=r(f.age, 1), group=x.group, low_conf=bool(x.low_confidence),
            bio=dict(throws=f.throws if pd.notna(f.throws) else None, height_in=r(f.height_in, 0), weight_lb=r(f.weight_lb, 0),
                     age_vs_level=r(f.age_vs_level, 1), international=bool(f.international),
                     draft=None if f.international or pd.isna(f.pick_overall) else dict(year=r(f.draft_year, 0), round=r(f.round_num, 0),
                                                                                       pick=r(f.pick_overall, 0), bonus=r(f.signing_bonus, 0))),
            role=dict(gs_share=r(f.GS_share), ip_per_g=r(f.outs_per_G / 3, 1), pitches_per_g=r(f.pitches_per_G, 0),
                      p_sp=r(f.p_sp) if stat else None, proj=sp),
            hist=hist, chain=chain,
            blend=None if not stat else {k: r(f["blend_reg_" + k]) for k in ("K", "BB", "HBP", "HR", "GB", "XB")} | {"XB_box": r(f.blend_reg_XB_raw)},
            contact=dict(xwoba=r(con.loc[pid, "xwoba"]), xb_adj=r(con.loc[pid, "xb_contact_adj"]), bip=int(con.loc[pid, "bip"]))
            if pid in con.index else None,
            mera=None if ladder is None else dict(mera=r(ms_.loc[pid, "mera"], 2) if pid in ms_.index else None, ladder=ladder),
            arsenal=arsenal,
            il=dict(count=int(f.il_count), max_days=r(f.il_max_days, 0)) if f.il_count > 0 else None,
            in_mlb=None if not x.debuted else dict(debut=str(pl.mlb_debut_date.date()), control_years_left=int(max(0, 6 - (SEASON - int(f.debut_year) + 1)))),
            p_mlb=r(x.p_mlb, 4), war=dict(mean=r(x.war_mean, 2), q10=r(x.war_q10, 2), q50=r(x.war_q50, 2), q90=r(x.war_q90, 2)),
            eta=None if x.debuted else dict(mean=r(x.eta_mean, 2), q10=r(p.eta_q10, 2), q90=r(p.eta_q90, 2), debut={k[-4:]: r(x[k], 4) for k in pd_cols}),
            surplus=dict(if_mlb=m(x.surplus_if_mlb), q10=m(x.surplus_q10), q50=m(x.surplus_q50), q90=m(x.surplus_q90), ev=m(x.ev_surplus)),
            drivers=dict(p_mlb=[] if g is None else drv(g, "p_mlb"), war=[] if g is None else drv(g, "war")),
        )
        dump(SITE / "players" / f"{pid}.json", card)

    lbj["rows"].sort(key=lambda z: z["rank"])
    dump(SITE / "leaderboard.json", lbj)
    meth = json.loads((SITE / "method.json").read_text())
    meth["pitchers"] = pitchers_block()
    meth["coverage"]["pitchers_2026"] = int(len(v))
    meth["coverage"]["pitchers_prior"] = int((v.group == "prior").sum())
    dump(SITE / "method.json", meth)


if __name__ == "__main__":
    main()
