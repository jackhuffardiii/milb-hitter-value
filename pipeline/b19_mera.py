"""B19 mERA, Majors-Equivalent Run Average (S21, S22, A18, Q21, Q22, C15 slope test). PyMC hierarchical regression.

Rows: MiLB pitcher rows (A..AAA, player x season x level x league, >= 50 BF) from B18. Inputs: regressed MLEs reg_K, reg_BB,
reg_GB, reg_XB, standardized. Target: next-season MLB-equivalent RA9 over all of the player's next-season rows (MiLB mle_R
and MLB park-neutral R per BF, BF-weighted), scaled to RA9 with that season's MLB batters per 27 outs; needs >= 100 next-season
BF (Q21). Next-season BF is the precision weight: Normal sd = sigma / sqrt(w), Gamma shape = alpha x w (w = BF / mean BF).
Model: intercept + level and level-league intercepts (partially pooled) + slopes per component, either fixed or varying by
level around a pooled slope. Normal uses an identity link, Gamma a log link.
Spec choice (Gamma vs Normal, varying vs fixed slopes) by 5-fold GroupKFold (player) CV on rows whose target season <= 2012,
scored by BF-weighted MSE. The chosen spec is refit twice: `cv` on target seasons <= 2012 (feature for CV and holdouts) and
`final` on all seasons (2026 board). Unseen leagues get a 0 league offset.
S22 ladder: mERA (MLB scale) divided by the B18 level-season runs chain factor of each level from the pitcher's own up to AAA.

Outputs (data/): pitch_mera.parquet (row grain), pitch_mera_player_season.parquet, b19_mera.json.
"""
import json
import os

os.environ.setdefault("PYTENSOR_FLAGS", f"base_compiledir={os.path.abspath('data/raw/pytensor')}")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pymc as pm  # noqa: E402
from sklearn.model_selection import GroupKFold  # noqa: E402

from pipeline.b18_pitch_mle import prep_mlb  # noqa: E402
from pipeline.common import DATA  # noqa: E402

X_COLS = ["reg_K", "reg_BB", "reg_GB", "reg_XB"]
LEVELS = ["a", "a+", "aa", "aaa"]
MIN_BF, MIN_BF_NEXT, CV_LAST = 50, 100, 2012
SPECS = [(lik, slopes) for lik in ("normal", "gamma") for slopes in ("varying", "fixed")]


def rows():
    m = pd.read_parquet(DATA / "pitch_mle.parquet")
    m = m[m.level.isin(LEVELS)]
    mlb = prep_mlb()[["player_id", "season", "BF", "neutral_R"]].rename(columns={"neutral_R": "R"})
    nxt = pd.concat([m[["player_id", "season", "BF", "mle_R"]].rename(columns={"mle_R": "R"}), mlb]).dropna(subset=["R"])
    nxt = nxt.assign(rbf=nxt.R * nxt.BF).groupby(["player_id", "season"])[["rbf", "BF"]].sum()
    mp = pd.read_parquet(DATA / "mlb_pitching.parquet").groupby("season")[["BF", "outs"]].sum()
    bf27 = 27 * mp.BF / mp.outs  # MLB batters per 27 outs: runs per BF -> RA9
    nxt = nxt.reset_index().assign(y=lambda d: d.rbf / d.BF * d.season.map(bf27), season=lambda d: d.season - 1)
    m = m.merge(nxt[["player_id", "season", "y", "BF"]].rename(columns={"BF": "BF_next"}), on=["player_id", "season"], how="left")
    m["lvl"] = m.level.map(LEVELS.index)
    m["lg"] = m.level + "|" + m.league_id.astype(str)
    return m


def train_set(m, last_target):
    t = m[(m.BF >= MIN_BF) & (m.BF_next >= MIN_BF_NEXT) & (m.season + 1 <= last_target)].dropna(subset=X_COLS + ["y"])
    return t.assign(y=t.y.clip(lower=0.05))  # a clean 100+ BF season can be 0 runs; Gamma needs y > 0


def fit(t, lik, slopes, std, draws=500, chains=2, seed=19):
    X = ((t[X_COLS] - std["mean"]) / std["sd"]).to_numpy()
    w = (t.BF_next / t.BF_next.mean()).to_numpy()
    lgs = sorted(t.lg.unique())
    gi = t.lg.map({g: i for i, g in enumerate(lgs)}).to_numpy()
    li = t.lvl.to_numpy()
    y = t.y.to_numpy()
    log = lik == "gamma"
    with pm.Model():
        # level intercepts unpooled (4 levels, thousands of rows each; an extra global intercept is redundant and mixes badly)
        a_l = pm.Normal("a_l", np.log(y.mean()) if log else y.mean(), 1.0 if log else 3.0, shape=len(LEVELS))
        s_g = pm.HalfNormal("s_g", 0.3 if log else 1.0)
        a_g = pm.Normal("a_g", 0, s_g, shape=len(lgs))  # centered: every league has hundreds of rows
        b = pm.Normal("b", 0, 0.5 if log else 2.0, shape=len(X_COLS))
        if slopes == "varying":
            tau = pm.HalfNormal("tau", 0.1 if log else 0.5, shape=len(X_COLS))
            d = pm.Normal("d", 0, tau, shape=(len(LEVELS), len(X_COLS)))
            eta = a_l[li] + a_g[gi] + ((b + d[li]) * X).sum(axis=1)
        else:
            eta = a_l[li] + a_g[gi] + (b * X).sum(axis=1)
        if log:
            alpha = pm.HalfNormal("alpha", 20.0)
            mu = pm.math.exp(eta)
            pm.Gamma("y", alpha=alpha * w, beta=alpha * w / mu, observed=y)
        else:
            sigma = pm.HalfNormal("sigma", 5.0)
            pm.Normal("y", eta, sigma / np.sqrt(w), observed=y)
        tr = pm.sample(draws, tune=draws, chains=chains, cores=chains, progressbar=False, random_seed=seed,
                       target_accept=0.9)
    post = {k: tr.posterior[k].mean(("chain", "draw")).to_numpy() for k in ("a_l", "a_g", "b") + (("d",) if slopes == "varying" else ())}
    rhat = float(max(_rhat(tr.posterior[k]) for k in tr.posterior.data_vars))
    return {"lik": lik, "slopes": slopes, "lgs": lgs, "post": post, "std": std, "rhat_max": rhat}


def _rhat(v):
    """Split-free Gelman-Rubin R-hat, max over the variable's elements (chains x draws x ...)."""
    x = v.to_numpy()
    n = x.shape[1]
    cm, cv = x.mean(1), x.var(1, ddof=1)
    wv, bv = cv.mean(0), n * cm.var(0, ddof=1)
    return float(np.nanmax(np.sqrt(((n - 1) / n * wv + bv / n) / wv)))


def predict(f, d):
    p = f["post"]
    X = ((d[X_COLS] - f["std"]["mean"]) / f["std"]["sd"]).to_numpy()
    li = d.lvl.to_numpy()
    gmap = {g: i for i, g in enumerate(f["lgs"])}
    ag = np.array([p["a_g"][gmap[g]] if g in gmap else 0.0 for g in d.lg])
    slope = p["b"] + p["d"][li] if f["slopes"] == "varying" else p["b"]
    eta = p["a_l"][li] + ag + (slope * X).sum(axis=1)
    return np.exp(eta) if f["lik"] == "gamma" else eta


def wmse(y, yhat, w):
    return float(np.sum(w * (y - yhat) ** 2) / np.sum(w))


def cv(t, std):
    out = {}
    folds = list(GroupKFold(5).split(t, groups=t.player_id))
    for lik, slopes in SPECS:
        oof = np.full(len(t), np.nan)
        for tr_i, te_i in folds:
            oof[te_i] = predict(fit(t.iloc[tr_i], lik, slopes, std), t.iloc[te_i])
        out[f"{lik}/{slopes}"] = wmse(t.y.to_numpy(), oof, t.BF_next.to_numpy())
    base = wmse(t.y.to_numpy(), np.average(t.y, weights=t.BF_next), t.BF_next.to_numpy())
    return out, base


def ladder(m, col):
    """S22: mERA at each level from the pitcher's own up to AAA = MLB-scale mERA / runs chain (that level -> MLB)."""
    fac = pd.read_parquet(DATA / "pitch_translation_factors.parquet")
    ls = fac[(fac.component == "R") & (fac.league_id == -1) & (fac.season > 0)].set_index(["from_level", "season"]).factor
    chain = {}
    for i, lv in enumerate(LEVELS):  # chain from lv to MLB = product of level-season factors lv..aaa
        chain[lv] = np.prod([[ls.get((u, s), np.nan) for s in m.season] for u in LEVELS[i:]], axis=0)
    for i, lv in enumerate(LEVELS):
        m[f"mera_{lv}"] = np.where(m.lvl <= i, m[col] / chain[lv], np.nan)
    return m


def main():
    m = rows()
    t_cv = train_set(m, CV_LAST)
    std = {"mean": t_cv[X_COLS].mean().to_numpy(), "sd": t_cv[X_COLS].std().to_numpy()}
    scores, base = cv(t_cv, std)
    best = min(scores, key=scores.get)
    lik, slopes = best.split("/")
    other = f"{lik}/{'fixed' if slopes == 'varying' else 'varying'}"
    f_cv = fit(t_cv, lik, slopes, std, draws=1000, chains=4)
    t_all = train_set(m, 2026)
    f_all = fit(t_all, lik, slopes, std, draws=1000, chains=4)
    ok = m[X_COLS].notna().all(axis=1)
    m["mera_cv"] = np.where(ok, predict(f_cv, m.fillna({c: 0 for c in X_COLS})), np.nan)
    m["mera"] = np.where(ok, predict(f_all, m.fillna({c: 0 for c in X_COLS})), np.nan)
    m = ladder(m, "mera")
    keep = ["player_id", "season", "level", "league_id", "BF", "y", "BF_next", "mera_cv", "mera"] + [f"mera_{lv}" for lv in LEVELS]
    m[keep].rename(columns={"y": "next_ra9_mle"}).to_parquet(DATA / "pitch_mera.parquet", index=False)
    g = m[ok].assign(c=m.mera_cv * m.BF, f=m.mera * m.BF).groupby(["player_id", "season"])
    ps = (g[["c", "f", "BF"]].sum().assign(mera_cv=lambda d: d.c / d.BF, mera=lambda d: d.f / d.BF)
          [["BF", "mera_cv", "mera"]].reset_index())
    ps.to_parquet(DATA / "pitch_mera_player_season.parquet", index=False)

    def coefs(f):
        p = f["post"]
        out = {"b_pooled": dict(zip(X_COLS, p["b"].round(4).tolist())), "a_level": dict(zip(LEVELS, p["a_l"].round(4).tolist()))}
        if f["slopes"] == "varying":
            out["b_by_level"] = {lv: dict(zip(X_COLS, (p["b"] + p["d"][i]).round(4).tolist())) for i, lv in enumerate(LEVELS)}
        return out | {"rhat_max": round(f["rhat_max"], 4), "n_rows": int(len(t_cv) if f is f_cv else len(t_all)),
                      "link": "log" if f["lik"] == "gamma" else "identity"}
    res = {"cv_weighted_mse": scores, "cv_baseline_weighted_mean": base, "chosen": best, "n_cv_rows": int(len(t_cv)),
           "C15_varying_vs_fixed": {"chosen_lik": lik, "varying": scores[f"{lik}/varying"], "fixed": scores[f"{lik}/fixed"],
                                    "varying_kept": slopes == "varying"},
           "fit_cv": coefs(f_cv), "fit_final": coefs(f_all), "std": {k: v.tolist() for k, v in std.items()}}
    (DATA / "b19_mera.json").write_text(json.dumps(res, indent=1))
    print("CV weighted MSE:", {k: round(v, 4) for k, v in scores.items()}, "baseline", round(base, 4), "chosen", best,
          "| other slopes", other)
    print(f"rows {len(m)}, mera non-null {m.mera.notna().mean():.3f}; rhat cv {f_cv['rhat_max']:.3f} final {f_all['rhat_max']:.3f}")


if __name__ == "__main__":
    main()
