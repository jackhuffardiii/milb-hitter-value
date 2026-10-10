"""B30 (v3 DRAFT, S35, C24): arbitration salary model.

Rows: matched player-seasons 2011-2026 entering season s with 3 <= service years < 6 (or Super Two, 2y120d+), listed with a
position (blank-position rows are a former club's deferred money, B27), salary > 1.05 x the league minimum (drops pre-arb
renewals and minor-league deals), and salary different from last season's (proxy for multi-year deals). Arb year = floor(service) - 2.
Target = log(salary / league minimum of s). Ridge vs LightGBM chosen by GroupKFold(5) by player on s < config.ARB_HOLDOUT_FIRST;
the v2 rule (arb share x max(prior WAR x $/WAR of s, minimum)) is the baseline. One holdout look on s >= ARB_HOLDOUT_FIRST,
then the chosen model is refit on every season. predict_arb(df) is the API for B31.
Outputs: data/models/arb.joblib, data/b30_c24.json.
"""
import json

import joblib
import numpy as np
import pandas as pd

from . import config
from .b6_models import MODELS, _lgb, _lgb_cv, _lin_cv, _linear
from .b8_value import load_params
from .common import DATA

LEAGUE_MIN = {2010: 400e3, 2011: 414e3, 2012: 480e3, 2013: 490e3, 2014: 500e3, 2015: 507.5e3, 2016: 507.5e3, 2017: 535e3,
              2018: 545e3, 2019: 555e3, 2020: 563.5e3, 2021: 570.5e3, 2022: 700e3, 2023: 720e3, 2024: 740e3, 2025: 760e3}
SUPER_TWO = 2 + 120 / 172  # 2.120 in years.days
FEATS = ["prev_war", "war_3yr", "career_war", "arb_year", "is_pitcher", "is_starter", "prev_log_salary_rel", "prev_pt"]
OUT = DATA / "b30_c24.json"
PRM = load_params()
LEAGUE_MIN[2026] = PRM["min"]


def league_min(season):
    """League minimum in dollars: a float for a scalar season, an array otherwise. After 2026 grows at dollar_params min_g."""
    season = np.asarray(season)
    out = np.array([LEAGUE_MIN.get(s, PRM["min"] * (1 + PRM["min_g"]) ** (s - 2026)) for s in season.ravel()]).reshape(season.shape)
    return float(out) if out.ndim == 0 else out


def design(df, onehot=False):
    """Model matrix from the public feature columns. Missing prior salary -> 0 plus an indicator (ridge); NaN for LightGBM."""
    X = df[FEATS].astype(float).copy()
    X["prev_pt"] = np.log1p(X.prev_pt)
    if onehot:
        X["no_prev_salary"] = X.prev_log_salary_rel.isna().astype(float)
        X["prev_log_salary_rel"] = X.prev_log_salary_rel.fillna(0)
        for k in (2, 3):
            X[f"arb{k}"] = (X.arb_year == k).astype(float)
        X = X.drop(columns="arb_year")
    return X


def build():
    """One row per training player-season with the public feature columns, target and flags."""
    sal = pd.read_parquet(DATA / "mlb_salaries.parquet")
    sal = sal[(sal.match_status == "matched") & (sal.pos != "") & sal.salary.notna()]
    sal = sal.drop_duplicates(["season", "player_id"]).assign(player_id=lambda d: d.player_id.astype(int))
    sal["rel"] = sal.salary / league_min(sal.season)
    prev = sal.assign(season=sal.season + 1)[["season", "player_id", "salary", "rel", "service_years"]]
    prev.columns = ["season", "player_id", "prev_salary", "prev_rel", "prev_service"]
    d = sal.merge(prev, on=["season", "player_id"], how="left")

    h = pd.read_parquet(DATA / "mlb_war.parquet")[["player_id", "season", "owar", "PA"]]
    p = pd.read_parquet(DATA / "mlb_pitch_war.parquet")[["player_id", "season", "pwar", "G", "GS", "BF"]]
    w = h.merge(p, on=["player_id", "season"], how="outer").fillna(0)
    w["war"], w["pt"] = w.owar + w.pwar, w.PA + w.BF
    w["pitcher"], w["starter"] = (w.BF > w.PA).astype(float), ((w.GS / w.G.where(w.G > 0)) > 0.5).astype(float)
    w = w.sort_values(["player_id", "season"])
    w["career_war"] = w.groupby("player_id").war.cumsum()
    w["war_3yr"] = sum(w.groupby("player_id").war.shift(k).fillna(0) for k in (0, 1, 2))
    last = w[["player_id", "season", "war", "pt", "pitcher", "starter", "career_war", "war_3yr"]].assign(season=lambda x: x.season + 1)
    last.columns = ["player_id", "season", "prev_war", "prev_pt", "is_pitcher", "is_starter", "career_war", "war_3yr"]
    d = d.merge(last, on=["player_id", "season"], how="left").fillna({c: 0 for c in last.columns[2:]})

    ok = ((d.service_years >= 3) & (d.service_years < 6)) | ((d.service_years >= SUPER_TWO) & (d.service_years < 3))
    d = d[ok & (d.season >= 2011) & (d.rel > 1.05) & (d.salary != d.prev_salary)].copy()
    d["super_two"] = d.service_years < 3
    d["arb_year"] = np.maximum(np.floor(d.service_years) - 2, 1).astype(int)
    arb_prev = (d.prev_service >= SUPER_TWO) & (d.prev_rel > 1.05)
    d["prev_log_salary_rel"] = np.log(d.prev_rel.where(arb_prev))
    d["y"] = np.log(d.rel)
    return d.reset_index(drop=True)


def baseline(df):
    """v2 rule in dollars: arb share x max(prior WAR x $/WAR of the season, minimum)."""
    mn = league_min(df.season)
    dpw = PRM["dpw"] * (1 + PRM["infl"]) ** (df.season - 2026)
    share = df.arb_year.map(dict(enumerate(PRM["arb"], 1)))
    return share * np.maximum(df.prev_war * dpw, mn)


def metrics(y, pred_log):
    return dict(rmse_log=float(np.sqrt(np.mean((y - pred_log) ** 2))),
                median_abs_pct_err=float(np.median(np.abs(np.exp(pred_log - y) - 1))))


def main():
    d = build()
    tr, ho = d[d.season < config.ARB_HOLDOUT_FIRST], d[d.season >= config.ARB_HOLDOUT_FIRST]
    y, groups = tr.y.to_numpy(), tr.player_id.to_numpy()
    mono = [1 if f in ("prev_war", "war_3yr", "career_war", "arb_year") else 0 for f in FEATS]
    oof_lin = _lin_cv("war", design(tr, True), y, groups)
    oof_lgb, n_iter = _lgb_cv("war", design(tr), y, groups, monotone_constraints=mono)
    rmse = lambda o: float(np.sqrt(np.mean((y - o) ** 2)))
    cv = {"ridge": rmse(oof_lin), "lightgbm": rmse(oof_lgb)}
    base_log = lambda x: np.log(np.maximum(baseline(x), league_min(x.season)) / league_min(x.season))
    chosen = min(cv, key=cv.get)

    def fit(x):
        if chosen == "ridge":
            return _linear("war").fit(design(x, True), x.y)
        return _lgb("war", n_iter, monotone_constraints=mono).fit(design(x), x.y)

    m = fit(tr)
    pred = m.predict(design(ho, chosen == "ridge"))
    out = dict(n_rows=dict(train=len(tr), holdout=len(ho), super_two=int(d.super_two.sum())), cv_rmse_log=cv,
               baseline_cv_rmse_log=float(np.sqrt(np.mean((y - base_log(tr)) ** 2))), chosen=chosen,
               holdout=dict(model=metrics(ho.y.to_numpy(), pred), baseline=metrics(ho.y.to_numpy(), base_log(ho).to_numpy())))
    final = fit(d)
    MODELS.mkdir(exist_ok=True)
    joblib.dump(dict(model=final, kind=chosen), MODELS / "arb.joblib")
    OUT.write_text(json.dumps(out, indent=1))


def predict_arb(df):
    """Arbitration-year salary in dollars (never below the season's league minimum)."""
    art = joblib.load(MODELS / "arb.joblib")
    mn = league_min(df.season.to_numpy())
    return mn * np.exp(np.maximum(art["model"].predict(design(df, art["kind"] == "ridge")), 0))


if __name__ == "__main__":
    main()
