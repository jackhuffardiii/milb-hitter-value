"""B23 (C20): the single pitcher holdout evaluation, run once by the main session after B22 was reviewed.

2013-17 ('backtest' fit, trained s<=2012): C2 vs MLB Pipeline top-100 pitchers (lists 2014-18), C3 vs a naive
age-vs-level + K-BB% + level baseline, C4 decile calibration. 2018-19 ('fit2017' fit, trained s<=2017): C12 analog (P(MLB)
on the observed horizon, EV Spearman vs pitcher WAR through 2026, lists 2019-20). Combined board: one 2013-17 Spearman of
EV WAR vs realized across hitters and pitchers (same 590/410 scale). Reported whichever way it goes.
List pitchers had no player_id in v1 (top100.csv match_status 'pitcher'); they are matched here with b7_top100's name keys
against pitcher snapshots in list_year-1 (else -2), throwing hand breaking ties, ambiguity rejected (Q12).
Writes data/pitch_backtest.json and data/pitch_backtest_players.parquet.
"""
import json

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pipeline import b7_backtest as b7
from pipeline.b5_features import MEXICAN_LEAGUE
from pipeline.b6_models import _calibration, _reach9, horizon, p_within
from pipeline.b7_backtest import _c3_block, c2, ranked, sp
from pipeline.b7_top100 import keys
from pipeline.common import DATA, MANUAL

K = ["player_id", "season"]
HOLDOUTS = {"backtest": (2013, 2017, 2012, 2012), "fit2017": (2018, 2019, 2017, 2014)}  # first, last, train cut, WAR cut
LEVELS = ["a", "a+", "aa", "aaa"]


def match_pitchers(top):
    pl = pd.read_parquet(DATA / "pitch_players.parquet")
    pl = pl.assign(ks=pl.full_name.fillna("").map(keys))
    f = pd.read_parquet(DATA / "pitch_features.parquet", columns=K + ["throws"])
    t = top[top.match_status == "pitcher"].copy()
    ids, status = [], []
    for r in t.itertuples():
        kk = keys(r.name)
        cand = pl[pl.ks.map(lambda s: bool(s & kk))].player_id
        pid, res = pd.NA, "unmatched"
        for s in (r.list_year - 1, r.list_year - 2):
            c = f[(f.season == s) & f.player_id.isin(cand)].drop_duplicates("player_id")
            same_hand = c.throws == {"RHP": "R", "LHP": "L"}.get(r.pos)
            if len(c) > 1 and same_hand.any():
                c = c[same_hand]
            if len(c) == 1:
                pid, res = int(c.player_id.iloc[0]), "matched"
                break
            if len(c) > 1:
                res = "ambiguous"
                break
        ids.append(pid)
        status.append(res)
    return t.assign(player_id=pd.array(ids, dtype="Int64"), match_status=status)


def population(fit):
    lo, hi, cut, _ = HOLDOUTS[fit]
    f = pd.read_parquet(DATA / "pitch_features.parquet")
    train_ids = set(f[f.season <= cut].player_id)
    f = f[f.season.between(lo, hi)]
    p = pd.read_parquet(DATA / "pitch_predictions.parquet")
    p = p[p.fit == fit].drop(columns=["group", "fit", "debuted"])
    t = pd.read_parquet(DATA / "pitch_war_target.parquet")[["player_id", "censored", "pre2005"]]
    d = f.merge(p, on=K, how="inner", validate="1:1").merge(t, on="player_id", how="left")
    d["censored"] = d.censored.fillna(False).astype(bool)
    d["pre2005"] = d.pre2005.fillna(False).astype(bool)
    d["realized"] = np.where(d.reached_mlb, d.war_6yr, 0.0)
    d["reached"] = d.reached_mlb.astype(bool)
    w = pd.read_parquet(DATA / "mlb_pitch_war.parquet").groupby("player_id").pwar.sum()
    d["war_thru_2026"] = d.player_id.map(w).fillna(0.0)
    d["disjoint"] = ~d.player_id.isin(train_ids)
    return d


def pmlb_block(x):
    """b6 holdout_metrics analog on not-debuted rows, scored on the horizon each row has observed."""
    x = x[~x.debuted]
    h = horizon(x)
    y, p = _reach9(x, h), p_within(x, h)
    o = {"n": int(len(x)), "logloss": float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))), "brier": float(brier_score_loss(y, p)),
         "auc": float(roc_auc_score(y, p)), "calibration": _calibration(y, p)}
    m = (x.reached & ~x.censored & ~x.pre2005).to_numpy()
    o["war_n"] = int(m.sum())
    o["spearman_war_reached_only"] = sp(x.war_mean[m], x.war_6yr[m])
    o["war_q10_q90_coverage"] = float(((x.war_6yr[m] >= x.war_q10[m]) & (x.war_6yr[m] <= x.war_q90[m])).mean())
    r = (x.reached & (x.debut_year - x.season <= 9)).to_numpy()
    o["eta_rmse"] = float(np.sqrt(np.mean((x.eta_years[r] - x.eta_mean[r]) ** 2)))
    keep = ~(x.reached & (x.censored | x.pre2005))
    o["spearman_ev_vs_realized"] = sp(x.ev_war[keep], x.realized[keep])
    return o


def baseline_features(f):
    """age_vs_level, raw K-BB% at the highest level in s, highest_level one-hot."""
    m = pd.read_parquet(DATA / "milb_pitching_seasons.parquet")
    m = m[m.league_id != MEXICAN_LEAGUE].rename(columns={"level": "highest_level"})
    k = f[K + ["highest_level"]].merge(m, on=K + ["highest_level"], how="left")
    g = k.groupby(K)[["SO", "BB", "BF"]].sum()
    kbb = ((g.SO - g.BB) / g.BF.where(g.BF > 0)).rename("k_bb").reset_index()
    x = f[K + ["age_vs_level", "highest_level"]].merge(kbb, on=K, how="left")
    for lv in LEVELS:
        x[f"lvl_{lv}"] = (x.highest_level == lv).astype(float)
    cols = ["age_vs_level", "k_bb"] + [f"lvl_{lv}" for lv in LEVELS]
    return x[K + cols], cols


def baseline(hold, cut, war_cut):
    f = pd.read_parquet(DATA / "pitch_features.parquet")
    t = pd.read_parquet(DATA / "pitch_war_target.parquet")[["player_id", "censored", "pre2005"]]
    tr = f[(f.group == "stat") & (f.season <= cut) & ~f.debuted].merge(t, on="player_id", how="left")
    k = K + ["age_vs_level", "highest_level"]
    xb, cols = baseline_features(pd.concat([tr[k], hold[k]], ignore_index=True).drop_duplicates(K))
    trx = tr[K + ["reached_mlb", "war_6yr", "censored", "pre2005"]].merge(xb, on=K)
    clf = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=1000))
    clf.fit(trx[cols], trx.reached_mlb.astype(int))
    wr = trx[trx.reached_mlb & ~trx.censored.fillna(False).astype(bool) & ~trx.pre2005.fillna(False).astype(bool)
             & (trx.season <= war_cut)]
    reg = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0)).fit(wr[cols], wr.war_6yr)
    h = hold.merge(xb, on=K, how="left", suffixes=("", "_b"))
    h["b_p"] = clf.predict_proba(h[cols])[:, 1]
    h["b_ev"] = h.b_p * reg.predict(h[cols])
    return h, {"n_train_p": int(len(trx)), "n_train_war": int(len(wr)), "baseline_features": cols}


def c3(hold):
    h, out = baseline(hold[(hold.group == "stat") & ~hold.debuted], 2012, 2012)
    for name, d in (("primary_excl_censored", h[~h.censored & ~h.pre2005]), ("sensitivity_incl_censored", h[~h.pre2005]),
                    ("player_disjoint", h[~h.censored & ~h.pre2005 & h.disjoint])):
        o = out[name] = _c3_block(d, "realized")
        o["model_beats_baseline_logloss"] = o["logloss_model"] < o["logloss_baseline"]
        o["model_beats_baseline_spearman"] = o["spearman_model"] > o["spearman_baseline"]
    return out


def c12(hold, top):
    st = hold[hold.group == "stat"]
    out = {"p_mlb": {"all": pmlb_block(st), "player_disjoint": pmlb_block(st[st.disjoint])}}
    h, out["baseline"] = baseline(st[~st.debuted], 2017, 2014)
    for name, d in (("all", h), ("player_disjoint", h[h.disjoint])):
        o = out.setdefault("ev_vs_war_thru_2026", {})[name] = {}
        for y, g in d.groupby("season"):
            o[int(y)] = {"n": int(len(g)), "spearman_model": sp(g.ev_war, g.war_thru_2026),
                         "spearman_baseline": sp(g.b_ev, g.war_thru_2026),
                         "logloss_model": float(log_loss(g.reached, np.clip(p_within(g, horizon(g)), 1e-6, 1 - 1e-6), labels=[0, 1])),
                         "logloss_baseline": float(log_loss(g.reached, g.b_p, labels=[0, 1]))}
    r = ranked(top[top.list_year.isin([2019, 2020])], hold)
    out["lists_2019_2020_vs_war_thru_2026"] = c2(r, "war_thru_2026") if len(r) else None
    return out, r


def combined_board():
    """C20: one 2013-17 Spearman of EV WAR vs realized across hitters and pitchers (stat rows, not censored/pre2005).
    A two-way player-season appears once per pipeline, as on the board before S29's sum."""
    rows = []
    for kind, d in (("hitter", b7.population("backtest")), ("pitcher", population("backtest"))):
        d = d[(d.group == "stat") & ~d.censored & ~d.pre2005]
        rows.append(d[["ev_war", "realized"]].assign(kind=kind))
    a = pd.concat(rows, ignore_index=True)
    return {"n": int(len(a)), "spearman_pooled": sp(a.ev_war, a.realized),
            "by_kind": {k: {"n": int(len(g)), "spearman": sp(g.ev_war, g.realized)} for k, g in a.groupby("kind")}}


def main():
    top = match_pitchers(pd.read_csv(MANUAL / "top100.csv", dtype={"player_id": "Int64"}))
    hold = population("backtest")
    r = ranked(top[top.list_year.between(2014, 2018)], hold)
    prim, sens = r[~r.censored & ~r.pre2005], r[~r.pre2005]
    st = hold[hold.group == "stat"]
    p13 = {"all": pmlb_block(st), "player_disjoint": pmlb_block(st[st.disjoint]), "prior": pmlb_block(hold[hold.group == "prior"])}
    cal = p13["all"]["calibration"]
    fresh, r2 = c12(population("fit2017"), top)
    out = {
        "holdout_looks": "pitchers: first and only look (C20), run once after B22 review",
        "list_matching": top.groupby(["list_year", "match_status"]).size().unstack(fill_value=0).to_dict("index"),
        "unmatched": top[top.match_status != "matched"][["list_year", "rank", "name", "pos", "org", "match_status"]].to_dict("records"),
        "P_MLB_2013_17": p13,
        "C2": {"primary_excl_censored": c2(prim), "sensitivity_incl_censored": c2(sens),
               "player_disjoint": c2(prim[prim.disjoint]) if prim.disjoint.sum() > 10 else None,
               "ranked_matched_rows": int(len(r)), "rows_already_in_mlb": int(r.debuted.sum())},
        "C3": c3(hold),
        "C4": {"deciles": [{**c, "pass": abs(c["gap"]) <= 0.05} for c in cal], "all_pass": all(abs(c["gap"]) <= 0.05 for c in cal)},
        "C12": fresh,
        "combined_board_2013_17": combined_board(),
        "realized_definition": "war_6yr (pitcher WAR, 410 per 2,430 games) if reached else 0; primary excludes censored and pre2005. "
                               "C12 uses pitcher WAR accumulated through 2026.",
    }
    json.dump(out, open(DATA / "pitch_backtest.json", "w"), indent=1, default=float)
    cols = ["list_year", "rank", "player_id", "name", "model_rank_within_list", "list_rank_within_matched", "gap", "ev_war",
            "p_mlb", "war_mean", "realized", "war_thru_2026", "reached", "debuted", "censored", "pre2005"]
    pd.concat([r.assign(holdout="2013-17"), r2.assign(holdout="2018-19")])[cols + ["holdout"]].sort_values(
        ["list_year", "rank"]).to_parquet(DATA / "pitch_backtest_players.parquet", index=False)


if __name__ == "__main__":
    main()
