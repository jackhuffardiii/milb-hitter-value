"""B7 (S9, C2, C3, C4, D8, Q3, Q6, Q12): backtest of model vs top-100 ranks and a naive baseline.

Reads data/manual/top100.csv (built by pipeline.b7_top100), features, predictions (fit=='backtest'),
war_target, b6_metrics. Writes data/backtest.json and data/backtest_players.parquet.
"""
import json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from pipeline.common import DATA, MANUAL

LEVELS = ["a-", "a", "a+", "aa", "aaa", "rk"]
SEED = 7


def sp(a, b):
    r = spearmanr(a, b).statistic
    return None if np.isnan(r) else float(r)


def population():
    f = pd.read_parquet(DATA / "features.parquet")
    f = f[(f.split == "train_era") & f.season.between(2013, 2017)]
    p = pd.read_parquet(DATA / "predictions.parquet")
    p = p[p.fit == "backtest"].drop(columns=["group", "fit"])
    t = pd.read_parquet(DATA / "war_target.parquet")[["player_id", "censored", "pre2005"]]
    d = f.merge(p, on=["player_id", "season"], how="inner", validate="1:1").merge(t, on="player_id", how="left")
    d["censored"] = d.censored.fillna(False).astype(bool)
    d["pre2005"] = d.pre2005.fillna(False).astype(bool)
    d["realized"] = np.where(d.reached_mlb, d.war_6yr, 0.0)
    d["reached"] = d.reached_mlb.astype(bool)
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
    for l in LEVELS: x[f"lvl_{l}"] = (x.highest_level == l).astype(float)
    cols = ["age_vs_level", "ops"] + [f"lvl_{l}" for l in LEVELS]
    return x[["player_id", "season"] + cols], cols


def c3(hold):
    f = pd.read_parquet(DATA / "features.parquet")
    t = pd.read_parquet(DATA / "war_target.parquet")[["player_id", "censored", "pre2005"]]
    tr = f[(f.split == "train_era") & (f.group == "stat") & (f.season <= 2012)].merge(t, on="player_id", how="left")
    k = ["player_id", "season", "age_vs_level", "highest_level"]
    xb, cols = baseline_features(pd.concat([tr[k], hold[k]], ignore_index=True).drop_duplicates(["player_id", "season"]))
    trx = tr[["player_id", "season", "reached_mlb", "war_6yr", "censored", "pre2005"]].merge(xb, on=["player_id", "season"])
    clf = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=1000))
    clf.fit(trx[cols], trx.reached_mlb.astype(int))
    wr = trx[trx.reached_mlb & ~trx.censored.fillna(False).astype(bool) & ~trx.pre2005.fillna(False).astype(bool)]
    reg = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0))
    reg.fit(wr[cols], wr.war_6yr)
    h = hold[hold.group == "stat"].merge(xb, on=["player_id", "season"], how="left", suffixes=("", "_b"))
    h["b_p"] = clf.predict_proba(h[cols])[:, 1]
    h["b_ev"] = h.b_p * reg.predict(h[cols])
    out = {"n_train_p": int(len(trx)), "n_train_war": int(len(wr)), "baseline_features": cols}
    for name, d in (("primary_excl_censored", h[~h.censored & ~h.pre2005]), ("sensitivity_incl_censored", h[~h.pre2005])):
        out[name] = {
            "n": int(len(d)),
            "logloss_model": float(log_loss(d.reached, d.p_mlb)), "logloss_baseline": float(log_loss(d.reached, d.b_p)),
            "spearman_model": sp(d.ev_war, d.realized), "spearman_baseline": sp(d.b_ev, d.realized)}
        o = out[name]
        o["model_beats_baseline_logloss"] = o["logloss_model"] < o["logloss_baseline"]
        o["model_beats_baseline_spearman"] = o["spearman_model"] > o["spearman_baseline"]
    return out


def boot_diff(d, n=2000):
    rng = np.random.default_rng(SEED)
    groups = {k: g[["ev_war", "neg_rank", "realized"]].to_numpy() for k, g in d.groupby("player_id")}
    ids = list(groups)
    diffs = []
    for _ in range(n):
        a = np.vstack([groups[i] for i in rng.choice(ids, len(ids))])
        diffs.append(sp(a[:, 0], a[:, 2]) - sp(a[:, 1], a[:, 2]))
    return [float(np.nanpercentile(diffs, 5)), float(np.nanpercentile(diffs, 95))]


def c2(d):
    d = d.copy(); d["neg_rank"] = -d["rank"]
    res = {"n": int(len(d)), "per_year": {}, "top_n": {}}
    for y, g in d.groupby("list_year"):
        res["per_year"][int(y)] = {"n": int(len(g)), "spearman_model": sp(g.ev_war, g.realized),
                                   "spearman_ba": sp(g.neg_rank, g.realized)}
        for N in (10, 25):
            m, b = g.nlargest(N, "ev_war"), g.nsmallest(N, "rank")
            res["top_n"].setdefault(str(N), {})[int(y)] = {
                "model_reached_share": float(m.reached.mean()), "list_reached_share": float(b.reached.mean()),
                "model_mean_realized": float(m.realized.mean()), "list_mean_realized": float(b.realized.mean()),
                "overlap": int(len(set(m.player_id) & set(b.player_id)))}
    pm, pb = sp(d.ev_war, d.realized), sp(d.neg_rank, d.realized)
    res["pooled"] = {"spearman_model": pm, "spearman_ba": pb, "diff": pm - pb, "diff_ci90_boot2000": boot_diff(d)}
    return res


def main():
    top = pd.read_csv(MANUAL / "top100.csv")
    hold = population()
    top = top[(top.match_status == "matched")].astype({"player_id": int})
    top["season"] = top.list_year - 1
    r = top.merge(hold, on=["player_id", "season"], how="inner", suffixes=("_list", ""))
    r["name"] = r.name_list
    r["model_rank_within_list"] = r.groupby("list_year").ev_war.rank(ascending=False, method="first").astype(int)
    # ranks among matched hitters only, so both sides rank the same set
    r["list_rank_within_matched"] = r.groupby("list_year")["rank"].rank(method="first").astype(int)
    r["gap"] = r.list_rank_within_matched - r.model_rank_within_list  # >0: model likes more than the list
    ncens = int((r.censored | r.pre2005).sum())
    prim, sens = r[~r.censored & ~r.pre2005], r[~r.pre2005]
    cal = json.load(open(DATA / "b6_metrics.json"))["holdout_stat"]["calibration"]
    cols = ["list_year", "rank", "player_id", "name", "model_rank_within_list", "list_rank_within_matched", "gap",
            "ev_war", "p_mlb", "war_mean", "realized", "reached", "censored", "pre2005"]

    def dis(df):
        return [{k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()}
                for row in df[["list_year", "rank", "name", "model_rank_within_list", "gap", "ev_war", "p_mlb",
                               "realized", "reached", "censored"]].to_dict("records")]
    dp = prim.sort_values("gap")
    out = {
        "sources": {int(y): {"source": g.source.iloc[0], "url": g.source_url.iloc[0]}
                    for y, g in pd.read_csv(MANUAL / "top100.csv").groupby("list_year")},
        "note": "BA lists are paywalled; all years use MLB Pipeline preseason Top 100 (source='pipeline') per Q6.",
        "C2": {"primary_excl_censored": c2(prim), "sensitivity_incl_censored": c2(sens),
               "ranked_matched_rows": int(len(r)), "rows_censored_or_pre2005": ncens},
        "C3": c3(hold),
        "C4": {"deciles": [{**c, "pass": abs(c["gap"]) <= 0.05} for c in cal],
               "all_pass": all(abs(c["gap"]) <= 0.05 for c in cal)},
        "disagreements": {"model_higher_than_list": dis(dp.sort_values("gap", ascending=False).head(10)),
                          "model_lower_than_list": dis(dp.head(10))},
        "realized_definition": "war_6yr if reached_mlb else 0; primary excludes censored (debut_season+5>2026) and pre2005 rows.",
    }
    json.dump(out, open(DATA / "backtest.json", "w"), indent=1, default=float)
    r[cols].sort_values(["list_year", "rank"]).to_parquet(DATA / "backtest_players.parquet", index=False)
    print(json.dumps({k: out[k] for k in ("C2", "C3")}, indent=1, default=float)[:6000])
    print("C4 fails:", [c["decile"] for c in out["C4"]["deciles"] if not c["pass"]])


if __name__ == "__main__":
    main()
