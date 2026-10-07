"""B6 models (S7, S8, A6, A7, A3). P(MLB), E[WAR | reached], ETA | reached, plus S8 draft-slot prior.

Stat models (group 'stat'): logistic/ridge/Poisson GLM vs LightGBM, chosen per target by GroupKFold(5) (by player_id)
on train_era snapshots s<=2012. Two fits per target: 'backtest' (train s<=2012, predict 2013-2017) and 'final'
(train s<=2017, predict censored 2018-2025 + score 2026). Quantile LightGBM gives WAR/ETA 10/50/90 (A7).
Prior models (group 'prior', low confidence): logistic/ridge/Poisson on draft + age/level features, residual quantiles.
Drivers (A6): SHAP (LightGBM) or coef*standardized value (linear), top 5 per row for P(MLB) and WAR.

Reusable API for B11: fit_stat(train, cfg) / predict_stat(models, df), fit_prior / predict_prior (DataFrames in/out).
Outputs: data/predictions.parquet, data/drivers.parquet, data/b6_metrics.json, data/models/*.joblib.
"""
import json
import warnings

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor, early_stopping
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, PoissonRegressor, RidgeCV
from sklearn.metrics import brier_score_loss, log_loss, mean_poisson_deviance, roc_auc_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pipeline.b5_features import S15_KEPT
from pipeline.common import DATA

warnings.filterwarnings("ignore", message="Skipping features without any observed values")  # log_bonus is all-NaN pre-2017
MODELS = DATA / "models"
QS = [0.1, 0.5, 0.9]
LOG_COLS = ["PA_s", "PA_highest", "career_milb_pa"]
STAT_NUM = (["level_num", "age", "age_vs_level", "pro_years", "p_C", "p_SS", "p_CF", "exp_pos_runs"] + LOG_COLS
            + [f"{k}_{c}" for k in ("reg", "blend", "delta") for c in ("K", "BB", "ISO")])  # BABIP out of the model (S7 v1.1)
POS_COLS = ["p_C", "p_SS", "p_CF", "exp_pos_runs"]


def for_fit(df, fit):
    """Backtest rows use the position transition fit on s<=2012 (columns *_bt), so the holdout never leaks in (v1.1)."""
    if fit != "backtest":
        return df
    return df.assign(**{c: df[c + "_bt"] for c in POS_COLS})
STAT_CATS = {"bats": ["L", "R", "S"], "highest_level": ["a", "a+", "aa", "aaa"]}  # raw MiLB position dummies removed (A6): position enters via exp_pos_runs, p_C, p_SS, p_CF
PRIOR_NUM = ["round_num", "pick_overall", "log_bonus", "international", "age", "level_num", "log_PA", "years_since_draft"]
LGB = dict(num_leaves=15, learning_rate=0.03, min_child_samples=50, random_state=0, verbose=-1)


# ---------- design matrices ----------
LOG_EXTRA = ["games_at_current_level", "ascent_pace"]  # skewed S15 counts, log1p like LOG_COLS (also used by B12)


def stat_X(df, extra=()):
    """Baseline stat features + `extra` S15 columns (B12 evaluates groups; models use `_X` = S15_KEPT)."""
    X = df[STAT_NUM].astype(float).copy()
    for c in LOG_COLS:
        X[c] = np.log1p(X[c])
    for c in extra:
        X[c] = np.log1p(df[c].to_numpy(float)) if c in LOG_EXTRA else df[c].astype(float).to_numpy()
    for col, cats in STAT_CATS.items():
        for v in cats:
            X[f"{col}={v}"] = (df[col] == v).astype(float)
    return X.reset_index(drop=True)


def _X(df):
    return stat_X(df, S15_KEPT)


def prior_X(df):
    X = pd.DataFrame({"round_num": df.round_num, "pick_overall": df.pick_overall,
                      "log_bonus": np.log1p(df.signing_bonus), "international": df.international.astype(float),
                      "age": df.age, "level_num": df.level_num, "log_PA": np.log1p(df.PA_s),
                      "years_since_draft": df.years_since_draft}).astype(float)
    return X.reset_index(drop=True)


# ---------- candidates ----------
def _lin(est):
    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), est)


def _lgb_params(target):
    return {"p_mlb": dict(), "war": dict(), "eta": dict(objective="poisson")}[target]


def _linear(target):
    return {"p_mlb": lambda: _lin(LogisticRegression(C=0.1, max_iter=2000)),
            "war": lambda: _lin(RidgeCV(alphas=np.logspace(0, 3, 13))),
            "eta": lambda: _lin(PoissonRegressor(alpha=0.01, max_iter=1000))}[target]()


def _lgb(target, n, **kw):
    cls = LGBMClassifier if target == "p_mlb" else LGBMRegressor
    return cls(n_estimators=n, **{**LGB, **_lgb_params(target), **kw})


def _predict(est, X, target):
    if target == "p_mlb":
        return est.predict_proba(X)[:, 1]
    p = est.predict(X)
    return np.clip(p, 1e-6, None) if target == "eta" else p


def _metric(target, y, p):
    if target == "p_mlb":
        return log_loss(y, p)
    if target == "war":
        return float(np.sqrt(np.mean((y - p) ** 2)))
    return mean_poisson_deviance(y, np.clip(p, 1e-6, None))


def _lgb_cv(target, X, y, groups, **kw):
    """Outer GroupKFold(5); early stopping on a 20% group holdout inside each training fold. Returns (OOF pred, mean best iter)."""
    oof, iters = np.zeros(len(y)), []
    for tr, te in GroupKFold(5).split(X, y, groups):
        a, b = next(GroupShuffleSplit(1, test_size=0.2, random_state=0).split(X.iloc[tr], groups=groups[tr]))
        a, b = tr[a], tr[b]
        m = _lgb(target, 2000, **kw)
        m.fit(X.iloc[a], y[a], eval_set=[(X.iloc[b], y[b])], callbacks=[early_stopping(50, verbose=False)])
        iters.append(m.best_iteration_ or 50)
        oof[te] = _predict(m, X.iloc[te], target) if not kw.get("objective") == "quantile" else m.predict(X.iloc[te])
    return oof, int(np.mean(iters) * 1.1) + 1


def _lin_cv(target, X, y, groups):
    oof = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, groups):
        m = _linear(target).fit(X.iloc[tr], y[tr])
        oof[te] = _predict(m, X.iloc[te], target)
    return oof


# ---------- binned residual intervals for WAR (A7) ----------
NBINS = 5


def binned_resid(make, X, y, groups):
    """GroupKFold(5) OOF predictions of `make()` on (X, y); residual 10/50/90 quantiles per quintile of the OOF prediction.
    Returns {'edges': 4 interior quintile cut points, 'q': (5, 3) residual quantiles}."""
    oof = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, groups):
        oof[te] = _predict(make().fit(X.iloc[tr], y[tr]), X.iloc[te], "war")
    edges = np.quantile(oof, np.arange(1, NBINS) / NBINS)
    b = np.searchsorted(edges, oof)
    return {"edges": edges, "q": np.array([np.quantile((y - oof)[b == k], QS) for k in range(NBINS)])}


def war_interval(resid, pred):
    return pred[:, None] + resid["q"][np.searchsorted(resid["edges"], pred)]


# ---------- target frames ----------
def _targets(df):
    """Per-target (mask, y) on a features frame joined with war_target flags."""
    wt = pd.read_parquet(DATA / "war_target.parquet")[["player_id", "censored", "pre2005"]]
    d = df[["player_id"]].merge(wt, on="player_id", how="left")
    reached = df.reached_mlb.to_numpy(bool)
    fresh = ~df.debuted.to_numpy(bool)  # S16: players already in MLB at s are never training rows
    ok_war = fresh & reached & (d.censored == False).to_numpy() & (d.pre2005 == False).to_numpy()  # noqa: E712
    return {"p_mlb": (fresh, df.reached_mlb.astype(int).to_numpy()),
            "war": (ok_war, df.war_6yr.to_numpy()),
            "eta": (fresh & reached & df.eta_years.notna().to_numpy(), df.eta_years.to_numpy())}


def select_stat(train):
    """CV candidate comparison on `train`; returns cfg with chosen model name and LightGBM n_estimators per target."""
    X, tg, g = _X(train), _targets(train), train.player_id.to_numpy()
    cfg, cv = {}, {}
    for t in ("p_mlb", "war", "eta"):
        m, y = tg[t]
        Xm, ym, gm = X[m].reset_index(drop=True), y[m], g[m]
        lo = _lin_cv(t, Xm, ym, gm)
        oof, n = _lgb_cv(t, Xm, ym, gm)
        lin, gbm = _metric(t, ym, lo), _metric(t, ym, oof)
        cv[t] = {"linear": lin, "lightgbm": gbm, "n_rows": int(m.sum()), "lgb_n_estimators": n}
        better = gbm < lin
        if t == "war":  # A12: rank quality of E[WAR | reached] (Spearman OOF), not RMSE
            sl, sg = float(spearmanr(lo, ym)[0]), float(spearmanr(oof, ym)[0])
            cv[t].update(spearman_linear=sl, spearman_lightgbm=sg)
            better = sg > sl
        cfg[t] = {"chosen": "lightgbm" if better else "linear", "n": n}
    for t in ("eta",):  # quantile iteration counts (WAR intervals are binned OOF residuals, A7)
        m, y = tg[t]
        Xm, ym, gm = X[m].reset_index(drop=True), y[m], g[m]
        cfg[t]["qn"] = {q: _lgb_cv(t, Xm, ym, gm, objective="quantile", alpha=q)[1] for q in QS}
    return cfg, cv


# ---------- recency recalibration of P(MLB) (C4) ----------
class Recal:
    """Monotone map of raw P(MLB). kind 'isotonic' or 'platt' (logistic on logit p)."""

    def __init__(self, kind):
        self.kind = kind

    def fit(self, p, y):
        if self.kind == "isotonic":
            self.m = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(p, y)
        else:
            self.m = LogisticRegression(C=1e6).fit(_logit(p)[:, None], y)
        return self

    def predict(self, p):
        return self.m.predict(p) if self.kind == "isotonic" else self.m.predict_proba(_logit(p)[:, None])[:, 1]


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_recal(train, cfg, recent=3):
    """OOF P(MLB) (GroupKFold by player) on all train rows; recalibrate on the last `recent` training seasons only.
    Isotonic vs Platt chosen by group-CV log loss on those recent OOF rows (holdout-free)."""
    X, y, g = _X(train), train.reached_mlb.astype(int).to_numpy(), train.player_id.to_numpy()
    oof = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, g):
        m = _lgb("p_mlb", cfg["p_mlb"]["n"]) if cfg["p_mlb"]["chosen"] == "lightgbm" else _linear("p_mlb")
        oof[te] = _predict(m.fit(X.iloc[tr], y[tr]), X.iloc[te], "p_mlb")
    r = (train.season >= train.season.max() - recent + 1).to_numpy()
    po, yo, go = oof[r], y[r], g[r]
    ll = {}
    for kind in ("isotonic", "platt"):
        cv = np.zeros(len(yo))
        for tr, te in GroupKFold(5).split(po, yo, go):
            cv[te] = Recal(kind).fit(po[tr], yo[tr]).predict(po[te])
        ll[kind] = log_loss(yo, np.clip(cv, 1e-4, 1 - 1e-4))
    kind = min(ll, key=ll.get)
    return Recal(kind).fit(po, yo), {"kind": kind, "cv_logloss": ll, "n_rows": int(r.sum())}


# ---------- stat fit / predict ----------
def fit_stat(train, cfg):
    X, tg = _X(train), _targets(train)
    mod = {"cfg": cfg, "cols": list(X.columns)}
    mod["recal"], mod["recal_info"] = fit_recal(train, cfg)
    for t in ("p_mlb", "war", "eta"):
        m, y = tg[t]
        Xm, ym = X[m], y[m]
        c = cfg[t]
        mod[t] = (_lgb(t, c["n"]) if c["chosen"] == "lightgbm" else _linear(t)).fit(Xm, ym)
        if t == "war":
            gm = train.player_id.to_numpy()[m]
            mk = (lambda: _lgb(t, c["n"])) if c["chosen"] == "lightgbm" else (lambda: _linear(t))
            mod["war_resid"] = binned_resid(mk, Xm.reset_index(drop=True), ym, gm)
        elif t == "eta":
            mod[t + "_q"] = {q: _lgb(t, c["qn"][q], objective="quantile", alpha=q).fit(Xm, ym) for q in QS}
    return mod


def _sorted_q(mod, key, X, lo=None):
    q = np.sort(np.column_stack([mod[key][a].predict(X) for a in QS]), axis=1)
    return np.clip(q, lo, None) if lo is not None else q


def predict_stat(mod, df, calibrate=True):
    X = _X(df)[mod["cols"]]
    out = pd.DataFrame(index=df.index)
    out["p_mlb"] = _predict(mod["p_mlb"], X, "p_mlb")
    if calibrate:
        out["p_mlb"] = np.clip(mod["recal"].predict(out.p_mlb.to_numpy()), 0, 1)
    out["war_mean"] = _predict(mod["war"], X, "war")
    out[["war_q10", "war_q50", "war_q90"]] = war_interval(mod["war_resid"], out.war_mean.to_numpy())
    out["eta_mean"] = _predict(mod["eta"], X, "eta")
    out[["eta_q10", "eta_q50", "eta_q90"]] = _sorted_q(mod, "eta_q", X, 0)
    out["ev_war"] = out.p_mlb * out.war_mean
    out["low_confidence"] = False
    return out.drop(columns="eta_q50")


# ---------- prior fit / predict (S8) ----------
def fit_prior(train):
    X, tg = prior_X(train), _targets(train)
    mod = {"cols": list(X.columns)}
    for t in ("p_mlb", "war", "eta"):
        m, y = tg[t]
        mod[t] = _linear(t).fit(X[m], y[m])
        if t == "war":  # binned OOF residual quantiles (A7)
            mod["war_resid"] = binned_resid(lambda: _linear("war"), X[m].reset_index(drop=True), y[m], train.player_id.to_numpy()[m])
        elif t == "eta":
            r = y[m] - _predict(mod[t], X[m], t)
            mod["eta_resid"] = np.quantile(r, QS)
    return mod


def predict_prior(mod, df):
    X = prior_X(df)[mod["cols"]]
    out = pd.DataFrame(index=df.index)
    out["p_mlb"] = _predict(mod["p_mlb"], X, "p_mlb")
    out["war_mean"] = _predict(mod["war"], X, "war")
    out[["war_q10", "war_q50", "war_q90"]] = war_interval(mod["war_resid"], out.war_mean.to_numpy())
    out["eta_mean"] = _predict(mod["eta"], X, "eta")
    out[["eta_q10", "eta_q50", "eta_q90"]] = np.clip(out.eta_mean.to_numpy()[:, None] + mod["eta_resid"], 0, None)
    out["ev_war"] = out.p_mlb * out.war_mean
    out["low_confidence"] = True
    return out.drop(columns="eta_q50")


# ---------- drivers (A6) ----------
def drivers(mod, df, target, top=5):
    """Long-format top-`top` contributions per row for target 'p_mlb' (log-odds) or 'war' (wins)."""
    import shap
    X = _X(df)[mod["cols"]]
    est = mod[target if target == "p_mlb" else "war"]
    if hasattr(est, "steps"):
        imp, sc, lin = est.steps[0][1], est.steps[1][1], est.steps[2][1]
        raw = imp.transform(X)
        names = list(imp.get_feature_names_out(mod["cols"]))
        contrib = sc.transform(raw) * np.ravel(lin.coef_)
    else:
        sv = shap.TreeExplainer(est).shap_values(X)
        contrib = sv[1] if isinstance(sv, list) else sv
        names, raw = mod["cols"], X.to_numpy()
    top = min(top, contrib.shape[1])  # top=999 gives every feature (B8 grouped drivers)
    top_i = np.argsort(-np.abs(contrib), axis=1)[:, :top]
    rows = np.repeat(np.arange(len(df)), top)
    cols = top_i.ravel()
    return pd.DataFrame({"player_id": df.player_id.to_numpy()[rows], "season": df.season.to_numpy()[rows],
                         "target": target, "feature": np.array(names)[cols], "feature_value": raw[rows, cols],
                         "contribution": contrib[rows, cols], "rank": np.tile(np.arange(1, top + 1), len(df))})


# ---------- metrics ----------
def _calibration(y, p):
    d = pd.DataFrame({"y": y, "p": p})
    d["decile"] = pd.qcut(d.p.rank(method="first"), 10, labels=False) + 1
    g = d.groupby("decile").agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"))
    g["gap"] = g.predicted - g.observed
    return g.reset_index().to_dict("records")


def holdout_metrics(df, pred):
    d = pd.concat([df.reset_index(drop=True), pred.reset_index(drop=True)], axis=1)
    tg = _targets(d)
    y, p = tg["p_mlb"][1], d.p_mlb.to_numpy()
    out = {"n": len(d), "logloss": log_loss(y, p), "brier": brier_score_loss(y, p), "auc": roc_auc_score(y, p),
           "calibration": _calibration(y, p)}
    mw, yw = tg["war"]
    out["war_rmse"] = float(np.sqrt(np.mean((yw[mw] - d.war_mean.to_numpy()[mw]) ** 2)))
    me, ye = tg["eta"]
    out["eta_rmse"] = float(np.sqrt(np.mean((ye[me] - d.eta_mean.to_numpy()[me]) ** 2)))
    wt = pd.read_parquet(DATA / "war_target.parquet")[["player_id", "censored", "pre2005"]]
    dd = d.merge(wt, on="player_id", how="left")
    keep = ~(dd.reached_mlb & ((dd.censored == True) | (dd.pre2005 == True)))  # noqa: E712
    real = np.where(dd.reached_mlb, dd.war_6yr, 0.0)
    out["spearman_ev_vs_realized"] = float(spearmanr(dd.ev_war[keep], real[keep]).statistic)
    out["spearman_war_reached_only"] = float(spearmanr(d.war_mean[mw], yw[mw]).statistic)
    out["war_q10_q90_coverage"] = float(((yw[mw] >= d.war_q10.to_numpy()[mw]) & (yw[mw] <= d.war_q90.to_numpy()[mw])).mean())
    return out


# ---------- main ----------
def main():
    MODELS.mkdir(exist_ok=True)
    f = pd.read_parquet(DATA / "features.parquet")
    te = f[f.split == "train_era"]
    st, pr = f[f.group == "stat"], f[f.group == "prior"]
    bt_tr, fin_tr = st[(st.split == "train_era") & (st.season <= 2012)], st[st.split == "train_era"]
    hold = st[st.season.between(2013, 2017)]
    pen = st[st.split != "train_era"]
    score_stat = st[st.split == "score"]

    cfg, cv = select_stat(bt_tr)
    print("stat CV:", json.dumps(cv, indent=1, default=float))
    preds, drv = [], []
    fits = {"backtest": (bt_tr, hold, hold), "final": (fin_tr, pen, score_stat)}
    metrics = {"cv_stat": cv, "chosen_stat": {t: cfg[t]["chosen"] for t in cfg}, "holdout_stat": None}
    for name, (tr, tgt, drv_rows) in fits.items():
        mod = fit_stat(tr, cfg)
        joblib.dump(mod, MODELS / f"stat_{name}.joblib")
        p = predict_stat(mod, tgt)
        preds.append(pd.concat([tgt[["player_id", "season", "group"]], p], axis=1).assign(fit=name))
        for t in ("p_mlb", "war"):
            drv.append(drivers(mod, drv_rows, t).assign(fit=name))
        metrics.setdefault("recal", {})[name] = mod["recal_info"]
        if name == "backtest":
            metrics["holdout_stat"] = holdout_metrics(tgt, p)
            metrics["holdout_stat_uncalibrated"] = holdout_metrics(tgt, predict_stat(mod, tgt, calibrate=False))

    # S8 prior: CV (linear only, logistic/ridge/Poisson) on s<=2012 for reference, then the same two fits
    ptr = pr[(pr.split == "train_era") & (pr.season <= 2012)]
    X, tg, g = prior_X(ptr), _targets(ptr), ptr.player_id.to_numpy()
    metrics["cv_prior"] = {t: _metric(t, tg[t][1][tg[t][0]], _lin_cv(t, X[tg[t][0]].reset_index(drop=True), tg[t][1][tg[t][0]], g[tg[t][0]]))
                           for t in ("p_mlb", "war", "eta")}
    for name, (tr, tgt) in {"backtest": (ptr, pr[pr.season.between(2013, 2017)]),
                            "final": (pr[pr.split == "train_era"], pr[pr.split != "train_era"])}.items():
        mod = fit_prior(tr)
        joblib.dump(mod, MODELS / f"prior_{name}.joblib")
        p = predict_prior(mod, tgt)
        preds.append(pd.concat([tgt[["player_id", "season", "group"]], p], axis=1).assign(fit=name))
        if name == "backtest":
            metrics["holdout_prior"] = holdout_metrics(tgt, p)

    out = pd.concat(preds, ignore_index=True)
    chosen = {f"chosen_{t}": cfg[t]["chosen"] for t in cfg}
    for k, v in chosen.items():
        out[k] = np.where(out.group == "stat", v, "linear")
    out.to_parquet(DATA / "predictions.parquet", index=False)
    pd.concat(drv, ignore_index=True).to_parquet(DATA / "drivers.parquet", index=False)
    json.dump(metrics, open(DATA / "b6_metrics.json", "w"), indent=1, default=float)
    h = metrics["holdout_stat"]
    print(f"predictions {len(out)} rows; chosen {metrics['chosen_stat']}")
    print({k: v for k, v in h.items() if k != "calibration"})


if __name__ == "__main__":
    main()
