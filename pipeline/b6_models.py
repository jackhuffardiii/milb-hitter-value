"""B6 models (S7, S8, S16, A6, A7, A12, A13, A16, A3). v1.1.

P(MLB) and ETA (A13): one discrete-time hazard model of debut. Person-period rows = snapshot x year t = 1..9 after s
while not yet debuted and observed (s + t <= 2026). P(MLB) = 1 - prod(1 - h_t); P(debut = s + t) = S_{t-1} h_t.
Censored snapshots enter a fit for the years they have observed. Platt recalibration of P(MLB) only if group-CV deciles
on fully observed training rows miss by more than 5 points (C4).
E[WAR | reached] (A12): ridge vs LightGBM by OOF Spearman among reached rows. Spread (A16): a variance model of the OOF
residual scale; WAR distribution = mean + scale x pooled centered standardized residual quantiles (`z`).
Players already in MLB at s (S16) are never training rows; they are scored with P(MLB) = 1.

Fits: 'backtest' (train s<=2012, predicts 2013-17), 'fit2017' (train s<=2017, predicts the fresh 2018-19 holdout, C12),
'final' (hazard trains s<=2025 with censoring; predicts 2018-2025 and the 2026 score rows). WAR trains s<=2012 (backtest)
or s<=2015 (fit2017, final; A12 v1.1: under 2% censored). Selection uses s<=2012 GroupKFold CV only.
Prior group (S8): same hazard / WAR / spread machinery on draft + age/level features, linear only.

Reusable API (B8, B11): predict_stat(mod, df), drivers(mod, df, target, top), prior_X, _X.
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
from sklearn.linear_model import LogisticRegression, Ridge, RidgeCV
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pipeline.b5_features import S15_KEPT
from pipeline.common import DATA

warnings.filterwarnings("ignore", message="Skipping features without any observed values")  # log_bonus is all-NaN pre-2017
warnings.filterwarnings("ignore", message=".*eval_set.*")
MODELS = DATA / "models"
QS = [0.1, 0.5, 0.9]
T_MAX, LAST_OBS = 9, 2026
LOG_COLS = ["PA_s", "PA_highest", "career_milb_pa"]
STAT_NUM = (["level_num", "age", "age_vs_level", "pro_years", "p_C", "p_SS", "p_CF", "exp_pos_runs"] + LOG_COLS
            + [f"{k}_{c}" for k in ("reg", "blend", "delta") for c in ("K", "BB", "ISO")])  # BABIP out of the model (S7 v1.1)
POS_COLS = ["p_C", "p_SS", "p_CF", "exp_pos_runs"]
STAT_CATS = {"bats": ["L", "R", "S"], "highest_level": ["a", "a+", "aa", "aaa"]}  # position enters via exp_pos_runs, p_C, p_SS, p_CF
LGB = dict(num_leaves=15, learning_rate=0.03, min_child_samples=50, random_state=0, verbose=-1)
LOG_EXTRA = ["games_at_current_level", "ascent_pace"]  # skewed S15 counts, log1p like LOG_COLS (also used by B12)
Z_GRID = np.linspace(0.005, 0.995, 199)  # stored standardized-residual quantiles (A16), sampled by B8
SPREAD_FEATS = ["age", "age_vs_level", "level_num", "exp_pos_runs", "p_C", "pro_years"]  # variance-model inputs (stat)


def for_fit(df, fit):
    """Backtest rows use the position transition fit on s<=2012 (columns *_bt), so the holdout never leaks in (v1.1)."""
    if fit != "backtest":
        return df
    return df.assign(**{c: df[c + "_bt"] for c in POS_COLS})


# ---------- design matrices ----------
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


XFN = {"stat": _X, "prior": prior_X}


def _hx(X, t):
    """Hazard design: player features + period t (numeric, dummies, and t x age/level interactions)."""
    H = X.copy()
    t = np.asarray(t, float)
    H["t"] = t
    for k in range(1, T_MAX + 1):
        H[f"t={k}"] = (t == k).astype(float)
    H["age_vs_level_x_t"] = X["age_vs_level"].to_numpy() * t if "age_vs_level" in X else X["age"].to_numpy() * t
    H["level_num_x_t"] = X["level_num"].to_numpy() * t
    return H


def person_period(df, X):
    """(design, y, row index, groups) of hazard rows for not-yet-debuted rows of df; observed while s + t <= LAST_OBS."""
    s = df.season.to_numpy()
    lag = (df.debut_year - df.season).to_numpy(float)  # NaN if never reached
    ok = ~df.debuted.to_numpy(bool)
    T = np.minimum(T_MAX, LAST_OBS - s)
    T = np.where(np.isnan(lag) | (lag > T), T, lag).astype(int)
    T = np.where(ok, T, 0)
    idx = np.repeat(np.arange(len(df)), T)
    t = np.concatenate([np.arange(1, n + 1) for n in T]) if T.sum() else np.array([], int)
    y = (t == lag[idx]).astype(int)
    return _hx(X.iloc[idx].reset_index(drop=True), t), y, idx, df.player_id.to_numpy()[idx]


# ---------- candidates ----------
def _lin(est):
    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), est)


def _linear(target):
    return {"p_mlb": lambda: _lin(LogisticRegression(C=0.1, max_iter=3000)),
            "war": lambda: _lin(RidgeCV(alphas=np.logspace(0, 3, 13)))}[target]()


def _lgb(target, n, **kw):
    cls = LGBMClassifier if target == "p_mlb" else LGBMRegressor
    return cls(n_estimators=n, **{**LGB, **kw})


def _predict(est, X, target):
    return est.predict_proba(X)[:, 1] if target == "p_mlb" else est.predict(X)


def _make(target, chosen, n):
    return (lambda: _lgb(target, n)) if chosen == "lightgbm" else (lambda: _linear(target))


def _lgb_cv(target, X, y, groups, **kw):
    """Outer GroupKFold(5); early stopping on a 20% group holdout inside each training fold. Returns (OOF pred, mean best iter)."""
    oof, iters = np.zeros(len(y)), []
    for tr, te in GroupKFold(5).split(X, y, groups):
        a, b = next(GroupShuffleSplit(1, test_size=0.2, random_state=0).split(X.iloc[tr], groups=groups[tr]))
        a, b = tr[a], tr[b]
        m = _lgb(target, 2000, **kw)
        m.fit(X.iloc[a], y[a], eval_set=[(X.iloc[b], y[b])], callbacks=[early_stopping(50, verbose=False)])
        iters.append(m.best_iteration_ or 50)
        oof[te] = _predict(m, X.iloc[te], target)
    return oof, int(np.mean(iters) * 1.1) + 1


def _lin_cv(target, X, y, groups):
    oof = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, groups):
        oof[te] = _predict(_linear(target).fit(X.iloc[tr], y[tr]), X.iloc[te], target)
    return oof


def _oof(make, X, y, groups, target):
    oof = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, groups):
        oof[te] = _predict(make().fit(X.iloc[tr], y[tr]), X.iloc[te], target)
    return oof


# ---------- hazard curve ----------
def curve(est, X):
    """(n, T_MAX) P(debut = s + t), and P(MLB within T_MAX years), for every row of X."""
    n = len(X)
    H = _hx(X.iloc[np.repeat(np.arange(n), T_MAX)].reset_index(drop=True), np.tile(np.arange(1, T_MAX + 1), n))
    h = _predict(est, H, "p_mlb").reshape(n, T_MAX)
    S = np.cumprod(1 - h, axis=1)
    prev = np.column_stack([np.ones(n), S[:, :-1]])
    return prev * h, 1 - S[:, -1]


def _reach9(df):
    lag = (df.debut_year - df.season).to_numpy(float)
    return (~np.isnan(lag) & (lag <= T_MAX)).astype(int)


def _calibration(y, p):
    d = pd.DataFrame({"y": y, "p": p})
    d["decile"] = pd.qcut(d.p.rank(method="first"), 10, labels=False) + 1
    g = d.groupby("decile").agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"))
    g["gap"] = g.predicted - g.observed
    return g.reset_index().to_dict("records")


class Platt:
    def fit(self, p, y):
        self.m = LogisticRegression(C=1e6).fit(_logit(p)[:, None], y)
        return self

    def predict(self, p):
        return self.m.predict_proba(_logit(p)[:, None])[:, 1]


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def hazard_cv_check(make, df, X):
    """C4 on CV: OOF row-level P(MLB) for fully observed (s + 9 <= 2026) not-debuted rows, grouped by player.
    Returns (Platt or None, info)."""
    full = (~df.debuted.to_numpy(bool)) & (df.season.to_numpy() + T_MAX <= LAST_OBS)
    d, Xf = df[full].reset_index(drop=True), X[full].reset_index(drop=True)
    y, g, p = _reach9(d), d.player_id.to_numpy(), np.zeros(len(d))
    for tr, te in GroupKFold(5).split(Xf, y, g):
        H, yh, _, _ = person_period(d.iloc[tr], Xf.iloc[tr].reset_index(drop=True))
        p[te] = curve(make().fit(H, yh), Xf.iloc[te].reset_index(drop=True))[1]
    cal = _calibration(y, p)
    worst = max(abs(c["gap"]) for c in cal)
    rec = Platt().fit(p, y) if worst > 0.05 else None
    tail = [{"lo": lo, "hi": hi, "n": int(((p >= lo) & (p < hi)).sum()), "predicted": float(p[(p >= lo) & (p < hi)].mean()),
             "observed": float(y[(p >= lo) & (p < hi)].mean())}
            for lo, hi in ((0.9, 0.95), (0.95, 0.98), (0.98, 0.99), (0.99, 1.01)) if ((p >= lo) & (p < hi)).sum()]
    return rec, {"cv_deciles": cal, "max_abs_gap": worst, "platt_applied": rec is not None, "n_rows": int(len(d)),
                 "tail": tail}  # deciles hide the top tail; reported, not used for recalibration (C4 rule is decile-based)


# ---------- WAR spread (A16) ----------
def _pinball(y, q, a):
    d = y - q
    return float(np.mean(np.maximum(a * d, (a - 1) * d)))


def _scale_model(kind):
    if kind == "ridge":
        return _lin(Ridge(alpha=10.0))
    return _lgb("war", 200, num_leaves=7, min_child_samples=100)


def _zq(z):
    return np.quantile(z - z.mean(), Z_GRID)


def _spread_fit(kind, F, r):
    """Fit log|r| on F. Returns (model or constant, z quantile table)."""
    target = np.log(np.abs(r) + 0.05)
    if kind == "const":
        m, ls = float(target.mean()), np.full(len(r), target.mean())
    else:
        m = _scale_model(kind).fit(F, target)
        ls = m.predict(F)
    return m, _zq(r / np.exp(ls))


def _spread_scale(m, F):
    return np.exp(np.full(len(F), m) if isinstance(m, float) else m.predict(F))


def _zval(zq, a):
    return np.interp(a, Z_GRID, zq)


def select_spread(F, r, groups, info_df):
    """CV pinball loss (q10/q50/q90) of const / ridge / lightgbm scale models on OOF residuals; C11 coverage of the
    chosen one by age-vs-level tercile, level group and predicted-WAR quintile."""
    res, oofq = {}, {}
    for kind in ("const", "ridge", "lightgbm"):
        q = np.zeros((len(r), 3))
        for tr, te in GroupKFold(5).split(F, r, groups):
            m, zq = _spread_fit(kind, F.iloc[tr], r[tr])
            q[te] = _spread_scale(m, F.iloc[te])[:, None] * np.array([_zval(zq, a) for a in QS])[None, :]
        res[kind] = float(np.mean([_pinball(r, q[:, i], a) for i, a in enumerate(QS)]))
        oofq[kind] = q
    best = min(res, key=res.get)
    q = oofq[best]
    cov = (r >= q[:, 0]) & (r <= q[:, 2])
    d = info_df.assign(covered=cov)
    sub = {"age_vs_level_tercile": d.groupby(pd.qcut(d.age_vs_level, 3, labels=False)).covered.mean().to_dict(),
           "level_group": d.groupby(np.where(d.level_num <= 2, "low", "high")).covered.mean().to_dict(),
           "pred_war_quintile": d.groupby(pd.qcut(d.pred, 5, labels=False)).covered.mean().to_dict()}
    allc = [v for s in sub.values() for v in s.values()]
    return best, {"cv_pinball": res, "chosen": best, "coverage_overall": float(cov.mean()), "coverage_by": sub,
                  "c11_pass": bool(all(0.75 <= v <= 0.85 for v in allc))}


def _spread_F(df, kind, pred):
    """Variance-model inputs: player features plus the WAR mean prediction (OOF in training), since residual spread grows
    with the predicted level (right-skewed WAR)."""
    F = df[SPREAD_FEATS].astype(float).reset_index(drop=True) if kind == "stat" else prior_X(df)
    return F.assign(pred=np.asarray(pred, float))


# ---------- training masks ----------
def _war_mask(df, cutoff):
    wt = pd.read_parquet(DATA / "war_target.parquet")[["player_id", "censored", "pre2005"]]
    d = df[["player_id"]].merge(wt, on="player_id", how="left")
    return ((~df.debuted.to_numpy(bool)) & df.reached_mlb.to_numpy(bool) & (d.censored == False).to_numpy()  # noqa: E712
            & (d.pre2005 == False).to_numpy() & (df.season.to_numpy() <= cutoff))  # noqa: E712


# ---------- selection (s<=2012 CV only) ----------
def select_stat(train):
    X, g = _X(train), train.player_id.to_numpy()
    H, yh, _, gh = person_period(train, X)
    lin = log_loss(yh, np.clip(_lin_cv("p_mlb", H, yh, gh), 1e-6, 1 - 1e-6))
    oof, n = _lgb_cv("p_mlb", H, yh, gh)
    gbm = log_loss(yh, np.clip(oof, 1e-6, 1 - 1e-6))
    cfg = {"hazard": {"chosen": "lightgbm" if gbm < lin else "linear", "n": n}}
    cv = {"hazard": {"linear": lin, "lightgbm": gbm, "n_person_periods": int(len(yh)), "lgb_n_estimators": n}}
    m = _war_mask(train, 2012)
    Xm, ym, gm = X[m].reset_index(drop=True), train.war_6yr.to_numpy()[m], g[m]
    lo = _lin_cv("war", Xm, ym, gm)
    go, nw = _lgb_cv("war", Xm, ym, gm)
    sl, sg = float(spearmanr(lo, ym)[0]), float(spearmanr(go, ym)[0])
    cfg["war"] = {"chosen": "lightgbm" if sg > sl else "linear", "n": nw}
    cv["war"] = {"spearman_linear": sl, "spearman_lightgbm": sg, "n_rows": int(m.sum()), "lgb_n_estimators": nw}
    return cfg, cv


PRIOR_CFG = {"hazard": {"chosen": "linear", "n": 0}, "war": {"chosen": "linear", "n": 0}}


# ---------- fit / predict ----------
def fit(train, cfg, kind, war_cutoff, spread_kind=None):
    """Hazard on all not-debuted rows of `train` (observed periods), WAR on s<=war_cutoff, spread model (A16)."""
    X = XFN[kind](train)
    mod = {"kind": kind, "cfg": cfg, "cols": list(X.columns)}
    mk_h = _make("p_mlb", cfg["hazard"]["chosen"], cfg["hazard"]["n"])
    H, yh, _, _ = person_period(train, X)
    mod["hazard"] = mk_h().fit(H, yh)
    mod["recal"], mod["recal_info"] = hazard_cv_check(mk_h, train, X)
    m = _war_mask(train, war_cutoff)
    Xm, ym, gm = X[m].reset_index(drop=True), train.war_6yr.to_numpy()[m], train.player_id.to_numpy()[m]
    mk_w = _make("war", cfg["war"]["chosen"], cfg["war"]["n"])
    mod["war"] = mk_w().fit(Xm, ym)
    oof = _oof(mk_w, Xm, ym, gm, "war")
    r = ym - oof
    F = _spread_F(train[m], kind, oof)
    if spread_kind is None:
        info_df = train[m][["age_vs_level", "level_num"]].reset_index(drop=True).assign(pred=oof)
        spread_kind, mod["spread_info"] = select_spread(F, r, gm, info_df)
    mod["spread"], mod["z"] = _spread_fit(spread_kind, F, r)
    mod["spread_kind"] = spread_kind
    return mod


def predict(mod, df, calibrate=True):
    X = XFN[mod["kind"]](df)[mod["cols"]]
    pdeb, p = curve(mod["hazard"], X)
    if calibrate and mod["recal"] is not None:
        adj = np.clip(mod["recal"].predict(p), 0, 1)
        pdeb, p = pdeb * (adj / np.clip(p, 1e-9, None))[:, None], adj
    deb = df.debuted.to_numpy(bool)
    p, pdeb = np.where(deb, 1.0, p), np.where(deb[:, None], 0.0, pdeb)  # S16: already in MLB
    out = pd.DataFrame(index=df.index)
    out["p_mlb"] = p
    for t in range(1, T_MAX + 1):
        out[f"p_debut_t{t}"] = pdeb[:, t - 1]
    cond = pdeb / np.clip(pdeb.sum(axis=1, keepdims=True), 1e-12, None)
    out["eta_mean"] = np.where(deb, 0.0, cond @ np.arange(1, T_MAX + 1))
    cdf = np.cumsum(cond, axis=1)
    for q in (0.1, 0.9):
        out[f"eta_q{int(q * 100)}"] = np.where(deb, 0.0, 1 + (cdf < q).sum(axis=1))
    out["war_mean"] = _predict(mod["war"], X, "war")
    out["war_scale"] = _spread_scale(mod["spread"], _spread_F(df, mod["kind"], out.war_mean))
    for a in QS:
        out[f"war_q{int(a * 100)}"] = out.war_mean + out.war_scale * _zval(mod["z"], a)
    out["ev_war"] = out.p_mlb * out.war_mean
    out["debuted"] = deb
    out["low_confidence"] = mod["kind"] == "prior"
    return out


def predict_stat(mod, df, calibrate=True):
    return predict(mod, df, calibrate)


# ---------- drivers (A6) ----------
T_FEATS = {"t"} | {f"t={k}" for k in range(1, T_MAX + 1)}


def _contrib(est, X):
    if hasattr(est, "steps"):
        imp, sc, lin = est.steps[0][1], est.steps[1][1], est.steps[2][1]
        raw = imp.transform(X)
        return sc.transform(raw) * np.ravel(lin.coef_), list(imp.get_feature_names_out(list(X.columns))), raw
    import shap
    sv = shap.TreeExplainer(est).shap_values(X)
    return (sv[1] if isinstance(sv, list) else sv), list(X.columns), X.to_numpy()


def drivers(mod, df, target, top=5):
    """Long-format top-`top` contributions per row: 'p_mlb' = hazard log-odds averaged over t = 1..9 (period terms
    dropped; interactions renamed to their base feature), 'war' = wins."""
    X = XFN[mod["kind"]](df)[mod["cols"]]
    n = len(df)
    if target == "p_mlb":
        H = _hx(X.iloc[np.repeat(np.arange(n), T_MAX)].reset_index(drop=True), np.tile(np.arange(1, T_MAX + 1), n))
        c, names, raw = _contrib(mod["hazard"], H)
        c = c.reshape(n, T_MAX, -1).mean(axis=1)
        raw = raw.reshape(n, T_MAX, -1)[:, 0, :]
        keep = [i for i, nm in enumerate(names) if nm.removeprefix("missingindicator_") not in T_FEATS]
        c, raw, names = c[:, keep], raw[:, keep], [names[i].replace("_x_t", "") for i in keep]
        # interaction terms share a name with their base feature: sum them into it
        cf = pd.DataFrame(c, columns=names).T.groupby(level=0, sort=False).sum().T
        rf = pd.DataFrame(raw, columns=names).T.groupby(level=0, sort=False).first().T
        c, names, raw = cf.to_numpy(), list(cf.columns), rf[cf.columns].to_numpy()
    else:
        c, names, raw = _contrib(mod["war"], X)
    top = min(top, c.shape[1])
    top_i = np.argsort(-np.abs(c), axis=1)[:, :top]
    rows, cols = np.repeat(np.arange(n), top), top_i.ravel()
    return pd.DataFrame({"player_id": df.player_id.to_numpy()[rows], "season": df.season.to_numpy()[rows],
                         "target": target, "feature": np.array(names)[cols], "feature_value": raw[rows, cols],
                         "contribution": c[rows, cols], "rank": np.tile(np.arange(1, top + 1), n)})


# ---------- metrics (written to b6_metrics.json; read only at R9) ----------
def holdout_metrics(df, pred, train_ids):
    d = pd.concat([df.reset_index(drop=True), pred.reset_index(drop=True).drop(columns=["debuted"])], axis=1)
    out = {}
    for name, sel in (("all", np.ones(len(d), bool)), ("player_disjoint", ~d.player_id.isin(train_ids).to_numpy())):
        x = d[sel & ~d.debuted.to_numpy(bool)]
        y, p = _reach9(x), x.p_mlb.to_numpy()
        o = {"n": int(len(x)), "logloss": log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)), "brier": brier_score_loss(y, p),
             "auc": roc_auc_score(y, p), "calibration": _calibration(y, p)}
        m = _war_mask(x, 9999)
        yw, pw = x.war_6yr.to_numpy()[m], x.war_mean.to_numpy()[m]
        o["war_n"] = int(m.sum())
        o["spearman_war_reached_only"] = float(spearmanr(pw, yw).statistic)
        o["war_q10_q90_coverage"] = float(((yw >= x.war_q10.to_numpy()[m]) & (yw <= x.war_q90.to_numpy()[m])).mean())
        r = x.reached_mlb.to_numpy(bool) & (x.debut_year - x.season <= T_MAX).to_numpy()
        o["eta_rmse"] = float(np.sqrt(np.mean((x.eta_years.to_numpy()[r] - x.eta_mean.to_numpy()[r]) ** 2)))
        wt = pd.read_parquet(DATA / "war_target.parquet")[["player_id", "censored", "pre2005"]]
        xx = x.merge(wt, on="player_id", how="left")
        keep = ~(xx.reached_mlb & ((xx.censored == True) | (xx.pre2005 == True)))  # noqa: E712
        real = np.where(xx.reached_mlb, xx.war_6yr, 0.0)
        o["spearman_ev_vs_realized"] = float(spearmanr(xx.ev_war[keep], real[keep]).statistic)
        out[name] = o
    return out


# ---------- main ----------
def main():
    MODELS.mkdir(exist_ok=True)
    f = pd.read_parquet(DATA / "features.parquet")
    st, pr = f[f.group == "stat"], f[f.group == "prior"]
    cfg, cv = select_stat(for_fit(st[st.season <= 2012], "backtest"))
    print("selection (s<=2012 CV):", json.dumps(cv, default=float))
    fits = {  # name: (train rows, war cutoff, predict rows, driver rows)
        "backtest": (lambda d: for_fit(d[d.season <= 2012], "backtest"), 2012,
                     lambda d: for_fit(d[d.season.between(2013, 2017)], "backtest"), True),
        "fit2017": (lambda d: d[d.season <= 2017], 2015, lambda d: d[d.season.between(2018, 2019)], False),
        "final": (lambda d: d[d.season <= 2025], 2015, lambda d: d[d.season >= 2018], True),
    }
    preds, drv = [], []
    metrics = {"cv_stat": cv, "chosen_stat": {k: v["chosen"] for k, v in cfg.items()}}
    for kind, data, c in (("stat", st, cfg), ("prior", pr, PRIOR_CFG)):
        spread_kind = None
        for name, (trf, wcut, prf, do_drv) in fits.items():
            tr, tg = trf(data), prf(data)
            mod = fit(tr, c, kind, wcut, spread_kind)
            if name == "backtest":  # spread model chosen on s<=2012 CV, reused by the later fits
                spread_kind = mod["spread_kind"]
                metrics.setdefault("spread", {})[kind] = mod["spread_info"]
            metrics.setdefault("calibration_check", {})[f"{kind}_{name}"] = mod["recal_info"]
            joblib.dump(mod, MODELS / f"{kind}_{name}.joblib")
            p = predict(mod, tg)
            preds.append(pd.concat([tg[["player_id", "season", "group"]], p], axis=1).assign(fit=name))
            if name in ("backtest", "fit2017"):
                metrics.setdefault("holdout", {})[f"{kind}_{name}"] = holdout_metrics(tg, p, set(tr.player_id))
            if do_drv and kind == "stat":
                rows = tg if name == "backtest" else tg[tg.split == "score"]
                for t in ("p_mlb", "war"):
                    drv.append(drivers(mod, rows, t).assign(fit=name))
            print(f"{kind} {name}: trained {len(tr)} rows, predicted {len(tg)}", flush=True)
    out = pd.concat(preds, ignore_index=True)
    for k, v in metrics["chosen_stat"].items():
        out[f"chosen_{k}"] = np.where(out.group == "stat", v, "linear")
    out.to_parquet(DATA / "predictions.parquet", index=False)
    pd.concat(drv, ignore_index=True).to_parquet(DATA / "drivers.parquet", index=False)
    json.dump(metrics, open(DATA / "b6_metrics.json", "w"), indent=1, default=float)
    print("chosen", metrics["chosen_stat"], "| spread", {k: v["chosen"] for k, v in metrics["spread"].items()},
          "| C11", {k: v["c11_pass"] for k, v in metrics["spread"].items()})


if __name__ == "__main__":
    main()
