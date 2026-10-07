"""B7 (S9, S16, C2, C3, C4, C12, D8, Q3, Q6, Q12, Q18): backtests of the model vs MLB Pipeline top-100 ranks and a
naive baseline. v1.1.

2013-17 holdout ('backtest' fit, trained s<=2012): C2 (lists 2014-18), C3, C4. Fresh 2018-19 holdout ('fit2017' fit,
trained s<=2017): C12 (P(MLB) log loss and calibration, EV Spearman vs WAR accumulated through 2026 per snapshot year,
2018 six-year WAR on complete windows only = fast risers; lists 2019-20 vs WAR through 2026). Every block also reports
a player-disjoint subset (players with no training-era row), because a time split shares players across train and test.
Players already in MLB at s (S16) are out of P(MLB) metrics; on ranked lists they enter with P(MLB) = 1.
Reads data/manual/top100.csv, features, predictions, war_target, mlb_war, b6_metrics.
Writes data/backtest.json and data/backtest_players.parquet.
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pipeline.common import DATA, MANUAL

LEVELS = ["a-", "a", "a+", "aa", "aaa", "rk"]
SEED = 7
HOLDOUTS = {"backtest": (2013, 2017, 2012), "fit2017": (2018, 2019, 2017)}  # fit: (first, last snapshot, train cutoff)


def sp(a, b):
    r = spearmanr(a, b).statistic
    return None if np.isnan(r) else float(r)


def population(fit):
    lo, hi, cut = HOLDOUTS[fit]
    f = pd.read_parquet(DATA / "features.parquet")
    train_ids = set(f[f.season <= cut].player_id)
    f = f[f.season.between(lo, hi)]
    p = pd.read_parquet(DATA / "predictions.parquet")
    p = p[p.fit == fit].drop(columns=["group", "fit", "debuted"])
    t = pd.read_parquet(DATA / "war_target.parquet")[["player_id", "censored", "pre2005"]]
    d = f.merge(p, on=["player_id", "season"], how="inner", validate="1:1").merge(t, on="player_id", how="left")
    d["censored"] = d.censored.fillna(False).astype(bool)
    d["pre2005"] = d.pre2005.fillna(False).astype(bool)
    d["realized"] = np.where(d.reached_mlb, d.war_6yr, 0.0)
    d["reached"] = d.reached_mlb.astype(bool)
    w = pd.read_parquet(DATA / "mlb_war.parquet").groupby("player_id").owar.sum()
    d["war_thru_2026"] = d.player_id.map(w).fillna(0.0)  # rookie-eligible rows: (nearly) all MLB WAR comes after s
    d["disjoint"] = ~d.player_id.isin(train_ids)
    return d


def baseline_features(f):
    """age_vs_level, raw OPS at highest level in s (from counting stats), highest_level one-hot."""
    m = pd.read_parquet(DATA / "milb_player_seasons.parquet")
    k = f[["player_id", "season", "highest_level"]].merge(
        m.rename(columns={"level": "highest_level"}), on=["player_id", "season", "highest_level"], how="left")
    g = k.groupby(["player_id", "season"])[["AB", "H", "2B", "3B", "HR", "BB", "HBP", "SF"]].sum()
    tb = g.H + g["2B"] + 2 * g["3B"] + 3 * g.HR
    ops = (g.H + g.BB + g.HBP) / (g.AB + g.BB + g.HBP + g.SF) + tb / g.AB
    ops = ops.rename("ops").replace([np.inf, -np.inf], np.nan).reset_index()
    x = f[["player_id", "season", "age_vs_level", "highest_level"]].merge(ops, on=["player_id", "season"], how="left")
    for lv in LEVELS:
        x[f"lvl_{lv}"] = (x.highest_level == lv).astype(float)
    cols = ["age_vs_level", "ops"] + [f"lvl_{lv}" for lv in LEVELS]
    return x[["player_id", "season"] + cols], cols


def baseline(hold, cut, war_cut):
    """Naive age-vs-level + OPS logistic / ridge on stat rows s<=cut (not yet in MLB); returns hold with b_p, b_ev."""
    f = pd.read_parquet(DATA / "features.parquet")
    t = pd.read_parquet(DATA / "war_target.parquet")[["player_id", "censored", "pre2005"]]
    tr = f[(f.group == "stat") & (f.season <= cut) & ~f.debuted].merge(t, on="player_id", how="left")
    k = ["player_id", "season", "age_vs_level", "highest_level"]
    xb, cols = baseline_features(pd.concat([tr[k], hold[k]], ignore_index=True).drop_duplicates(["player_id", "season"]))
    trx = tr[["player_id", "season", "reached_mlb", "war_6yr", "censored", "pre2005"]].merge(xb, on=["player_id", "season"])
    clf = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=1000))
    clf.fit(trx[cols], trx.reached_mlb.astype(int))
    wr = trx[trx.reached_mlb & ~trx.censored.fillna(False).astype(bool) & ~trx.pre2005.fillna(False).astype(bool)
             & (trx.season <= war_cut)]
    reg = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0)).fit(wr[cols], wr.war_6yr)
    h = hold.merge(xb, on=["player_id", "season"], how="left", suffixes=("", "_b"))
    h["b_p"] = clf.predict_proba(h[cols])[:, 1]
    h["b_ev"] = h.b_p * reg.predict(h[cols])
    return h, {"n_train_p": int(len(trx)), "n_train_war": int(len(wr)), "baseline_features": cols}


def _c3_block(d, target):
    return {"n": int(len(d)),
            "logloss_model": float(log_loss(d.reached, np.clip(d.p_mlb, 1e-6, 1 - 1e-6))),
            "logloss_baseline": float(log_loss(d.reached, d.b_p)),
            "spearman_model": sp(d.ev_war, d[target]), "spearman_baseline": sp(d.b_ev, d[target])}


def c3(hold):
    h, out = baseline(hold[(hold.group == "stat") & ~hold.debuted], 2012, 2012)
    v1 = hold[(hold.group == "stat") & ~hold.censored & ~hold.pre2005]  # v1 population (already-in-MLB rows included, p = 1)
    out["v1_population_spearman_model"] = sp(v1.ev_war, v1.realized)
    for name, d in (("primary_excl_censored", h[~h.censored & ~h.pre2005]), ("sensitivity_incl_censored", h[~h.pre2005]),
                    ("player_disjoint", h[~h.censored & ~h.pre2005 & h.disjoint])):
        o = out[name] = _c3_block(d, "realized")
        o["model_beats_baseline_logloss"] = o["logloss_model"] < o["logloss_baseline"]
        o["model_beats_baseline_spearman"] = o["spearman_model"] > o["spearman_baseline"]
    return out


def boot_diff(d, target="realized", n=2000):
    rng = np.random.default_rng(SEED)
    groups = {k: g[["ev_war", "neg_rank", target]].to_numpy() for k, g in d.groupby("player_id")}
    ids = list(groups)
    diffs = []
    for _ in range(n):
        a = np.vstack([groups[i] for i in rng.choice(ids, len(ids))])
        diffs.append(sp(a[:, 0], a[:, 2]) - sp(a[:, 1], a[:, 2]))
    return [float(np.nanpercentile(diffs, 5)), float(np.nanpercentile(diffs, 95))]


def c2(d, target="realized"):
    d = d.copy()
    d["neg_rank"] = -d["rank"]
    res = {"n": int(len(d)), "target": target, "per_year": {}, "top_n": {}}
    for y, g in d.groupby("list_year"):
        res["per_year"][int(y)] = {"n": int(len(g)), "spearman_model": sp(g.ev_war, g[target]),
                                   "spearman_list": sp(g.neg_rank, g[target])}
        for N in (10, 25):
            m, b = g.nlargest(N, "ev_war"), g.nsmallest(N, "rank")
            res["top_n"].setdefault(str(N), {})[int(y)] = {
                "model_reached_share": float(m.reached.mean()), "list_reached_share": float(b.reached.mean()),
                "model_mean_realized": float(m[target].mean()), "list_mean_realized": float(b[target].mean()),
                "overlap": int(len(set(m.player_id) & set(b.player_id)))}
    pm, pb = sp(d.ev_war, d[target]), sp(d.neg_rank, d[target])
    res["pooled"] = {"spearman_model": pm, "spearman_list": pb, "diff": pm - pb, "diff_ci90_boot2000": boot_diff(d, target)}
    return res


def ranked(top, hold):
    top = top[(top.match_status == "matched")].astype({"player_id": int}).assign(season=lambda d: d.list_year - 1)
    r = top.merge(hold, on=["player_id", "season"], how="inner", suffixes=("_list", ""))
    r["name"] = r.name_list
    r["model_rank_within_list"] = r.groupby("list_year").ev_war.rank(ascending=False, method="first").astype(int)
    r["list_rank_within_matched"] = r.groupby("list_year")["rank"].rank(method="first").astype(int)  # same set both sides
    r["gap"] = r.list_rank_within_matched - r.model_rank_within_list  # >0: model likes more than the list
    return r


def c12(hold, top, b6m):
    """Fresh 2018-19 holdout (C12): one look, reported as it comes out."""
    out = {"p_mlb": {k: {kk: v[kk] for kk in ("n", "logloss", "brier", "auc", "calibration")}
                     for k, v in b6m["holdout"]["stat_fit2017"].items()}}
    st = hold[(hold.group == "stat") & ~hold.debuted]
    h, info = baseline(st, 2017, 2015)
    out["baseline"] = info
    for name, d in (("all", h), ("player_disjoint", h[h.disjoint])):
        o = out.setdefault("ev_vs_war_thru_2026", {})[name] = {}
        for y, g in d.groupby("season"):
            o[int(y)] = {"n": int(len(g)), "spearman_model": sp(g.ev_war, g.war_thru_2026),
                         "spearman_baseline": sp(g.b_ev, g.war_thru_2026),
                         "logloss_model": float(log_loss(g.reached, np.clip(g.p_mlb, 1e-6, 1 - 1e-6), labels=[0, 1])),
                         "logloss_baseline": float(log_loss(g.reached, g.b_p, labels=[0, 1]))}
    fr = h[(h.season == 2018) & h.reached & ~h.censored & ~h.pre2005]
    out["war6_2018_complete_windows_fast_risers"] = {"n": int(len(fr)), "spearman_war_mean": sp(fr.war_mean, fr.war_6yr),
                                                    "spearman_baseline": sp(fr.b_ev / fr.b_p, fr.war_6yr),
                                                    "note": "debut by 2021 only (complete 6-year window): fast risers"}
    r = ranked(top[top.list_year.isin([2019, 2020])], hold)
    out["lists_2019_2020_vs_war_thru_2026"] = c2(r, "war_thru_2026") if len(r) else None
    return out, r


def main():
    top = pd.read_csv(MANUAL / "top100.csv")
    b6m = json.load(open(DATA / "b6_metrics.json"))
    hold = population("backtest")
    r = ranked(top[top.list_year.between(2014, 2018)], hold)
    ncens = int((r.censored | r.pre2005).sum())
    prim, sens = r[~r.censored & ~r.pre2005], r[~r.pre2005]
    cal = b6m["holdout"]["stat_backtest"]["all"]["calibration"]
    cols = ["list_year", "rank", "player_id", "name", "model_rank_within_list", "list_rank_within_matched", "gap",
            "ev_war", "p_mlb", "war_mean", "realized", "war_thru_2026", "reached", "debuted", "censored", "pre2005"]

    def dis(df):
        return [{k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()}
                for row in df[["list_year", "rank", "name", "model_rank_within_list", "gap", "ev_war", "p_mlb",
                               "realized", "reached", "debuted", "censored"]].to_dict("records")]
    dp = prim.sort_values("gap")
    fresh, r2 = c12(population("fit2017"), top, b6m)
    out = {
        "sources": {int(y): {"source": g.source.iloc[0], "url": g.source_url.iloc[0]}
                    for y, g in top.groupby("list_year")},
        "note": "BA lists are paywalled; all years use MLB Pipeline preseason Top 100 (source='pipeline') per Q6.",
        "holdout_looks": "2013-17: 5th look (v1.1, Q18; A12 was chosen after a holdout result). 2018-19: first look (C12).",
        "C2": {"primary_excl_censored": c2(prim), "sensitivity_incl_censored": c2(sens),
               "player_disjoint": c2(prim[prim.disjoint]) if prim.disjoint.sum() > 10 else None,
               "ranked_matched_rows": int(len(r)), "rows_censored_or_pre2005": ncens,
               "rows_already_in_mlb": int(r.debuted.sum())},
        "C3": c3(hold),
        "C4": {"deciles": [{**c, "pass": abs(c["gap"]) <= 0.05} for c in cal],
               "all_pass": all(abs(c["gap"]) <= 0.05 for c in cal)},
        "C12": fresh,
        "disagreements": {"model_higher_than_list": dis(dp.sort_values("gap", ascending=False).head(10)),
                          "model_lower_than_list": dis(dp.head(10))},
        "realized_definition": "war_6yr if reached_mlb else 0; primary excludes censored (debut_season+5>2026) and pre2005 rows. "
                               "C12 uses WAR accumulated through 2026.",
    }
    json.dump(out, open(DATA / "backtest.json", "w"), indent=1, default=float)
    pd.concat([r.assign(holdout="2013-17"), r2.assign(holdout="2018-19")])[cols + ["holdout"]].sort_values(
        ["list_year", "rank"]).to_parquet(DATA / "backtest_players.parquet", index=False)
    print("backtest.json written (holdout results are read once, at R9)")


if __name__ == "__main__":
    main()
