"""B22 pitcher models (S23, S25, C18), the pitcher twin of B6: same hazard (A13), WAR mean selection (A12), spread (A16),
Platt rule (C4) and drivers (A6), on data/pitch_features.parquet.

Stat design = B20's pitch_X (no mERA: C15 failed). S28 contact adjustment (C17 passed): for stat rows whose season has
>= 100 AAA BIP and an xb_contact_adj, reg_XB and blend_reg_XB are scaled by xb_contact_adj / observed AAA XB/BIP
(unadjusted values kept in *_raw). Prior design = the pitcher analog of B6 prior_X.
Selection uses stat s<=2012 GroupKFold CV only. WAR trains s<=2012 (backtest) or s<=2014 (fit2017, final): A12's "under 2%
censored" rule gives 2014 for pitchers. No metric of any kind is computed on 2013-19 predictions (B23 is the single holdout
look); b22_metrics.json holds only s<=2012 CV numbers, so calibration_check is the backtest fits' (fit2017/final Platt
info stays inside their model files).
C18: GroupKFold OOF vs forward-chained (train s<=2009, test 2010-12) on stat s<=2012, report only.

Pitcher kinds are registered in B6's XFN / SPREAD as 'pitch_stat' / 'pitch_prior', so B6's predict / drivers work on the
saved models once this module is imported.
Outputs: data/pitch_predictions.parquet, data/pitch_drivers.parquet, data/b22_metrics.json, data/models/pitch_*.joblib.
"""
import json

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import log_loss
from sklearn.model_selection import GroupKFold

from .b6_models import (MODELS, PRIOR_CFG, SPREAD, XFN, _make, _predict, _reach9, _war_mask, curve, drivers, fit,
                        person_period, predict, select_stat)
from .b20_pitch_features import pitch_X
from .b21_pitch_tracking import aaa_contact
from .common import DATA

K = ["player_id", "season"]
WT = "pitch_war_target.parquet"
MIN_AAA_BIP = 100
PITCH_SPREAD = ["age", "age_vs_level", "level_num", "pro_years", "blend_GS_share"]  # variance-model inputs (stat)


def pitch_prior_X(df):
    X = pd.DataFrame({"round_num": df.round_num, "pick_overall": df.pick_overall,
                      "log_bonus": np.log1p(df.signing_bonus), "international": df.international.astype(float),
                      "age": df.age, "level_num": df.level_num, "log_BF": np.log1p(df.BF_s),
                      "years_since_draft": df.years_since_draft, "hs_draftee": df.hs_draftee}).astype(float)
    return X.reset_index(drop=True)


XFN.update(pitch_stat=pitch_X, pitch_prior=pitch_prior_X)
SPREAD["pitch_stat"] = PITCH_SPREAD


def contact_adjust(f):
    """S28: scale reg_XB / blend_reg_XB of stat rows by xb_contact_adj / AAA XB_obs. Returns (f, rows changed by season).
    XB_obs = 0 (no extra-base hits on 100+ BIP) has no defined ratio; those rows stay unadjusted."""
    a = aaa_contact()[K + ["XB", "BIP"]]
    c = pd.read_parquet(DATA / "pitch_contact.parquet")[K + ["xb_contact_adj"]]
    d = f[K].merge(a, on=K, how="left").merge(c, on=K, how="left")
    ratio = (d.xb_contact_adj / d.XB).where((d.BIP >= MIN_AAA_BIP) & (d.XB > 0)).to_numpy()
    hit = (f.group == "stat").to_numpy() & ~np.isnan(ratio)
    for col in ("reg_XB", "blend_reg_XB"):
        f[col + "_raw"] = f[col]
        f.loc[hit, col] = f.loc[hit, col] * ratio[hit]
    return f, f[hit].groupby("season").size()


def c18(st, cfg):
    """P(MLB) log loss (9-year reach, not-debuted rows, as hazard_cv_check) and WAR Spearman (WAR-mask reached rows) on
    stat s<=2012 with the chosen model types, under GroupKFold(5) OOF and forward chaining (train s<=2009, test 2010-12)."""
    d = st[st.season <= 2012].reset_index(drop=True)
    X, war = XFN["pitch_stat"](d), d.war_6yr.to_numpy()
    mk_h = _make("p_mlb", cfg["hazard"]["chosen"], cfg["hazard"]["n"])
    mk_w = _make("war", cfg["war"]["chosen"], cfg["war"]["n"])
    nd, wm, early = ~d.debuted.to_numpy(bool), _war_mask(d, 2012, WT), d.season.to_numpy() <= 2009
    schemes = {"group_kfold": list(GroupKFold(5).split(X, groups=d.player_id)),
               "forward_2009_to_2010_12": [(np.flatnonzero(early), np.flatnonzero(~early))]}
    out = {}
    for name, folds in schemes.items():
        p, w = np.full(len(d), np.nan), np.full(len(d), np.nan)
        for tr, te in folds:
            H, yh, _, _ = person_period(d.iloc[tr], X.iloc[tr].reset_index(drop=True))
            p[te] = curve(mk_h().fit(H, yh), X.iloc[te].reset_index(drop=True))[1]
            tw = tr[wm[tr]]
            w[te] = _predict(mk_w().fit(X.iloc[tw], war[tw]), X.iloc[te], "war")
        sp, sw = nd & ~np.isnan(p), wm & ~np.isnan(w)
        out[name] = {"p_mlb_logloss": log_loss(_reach9(d)[sp], np.clip(p[sp], 1e-6, 1 - 1e-6)), "p_mlb_n": int(sp.sum()),
                     "war_spearman": float(spearmanr(w[sw], war[sw])[0]), "war_n": int(sw.sum())}
    return out


def reach_vs_hitters(st):
    """Train-era (s<=2017) stat, not-debuted reach rate, pitchers vs hitters, by highest level x age-vs-level tercile
    (cut on the pooled rows)."""
    cols = ["season", "highest_level", "age_vs_level", "reached_mlb", "debuted"]
    h = pd.read_parquet(DATA / "features.parquet")
    d = pd.concat([st[cols].assign(pos="pitcher"), h.loc[h.group == "stat", cols].assign(pos="hitter")], ignore_index=True)
    d = d[(d.season <= 2017) & ~d.debuted.astype(bool)]
    d["tercile"], cuts = pd.qcut(d.age_vs_level, 3, labels=["young", "mid", "old"], retbins=True)
    t = d.groupby(["highest_level", "tercile", "pos"], observed=True).reached_mlb.agg(rate="mean", n="size").unstack("pos")
    t.columns = [f"{pos}_{m}" for m, pos in t.columns]
    return {"tercile_cuts": list(cuts), "table": t.reset_index().to_dict("records")}


def main():
    MODELS.mkdir(exist_ok=True)
    f, adjusted = contact_adjust(pd.read_parquet(DATA / "pitch_features.parquet"))
    st, pr = f[f.group == "stat"], f[f.group == "prior"]
    cfg, cv = select_stat(st[st.season <= 2012], "pitch_stat", WT)
    print("selection (s<=2012 CV):", json.dumps(cv, default=float))
    fits = {  # name: (train rows, war cutoff, predict rows, driver rows)
        "backtest": (lambda d: d[d.season <= 2012], 2012, lambda d: d[d.season.between(2013, 2017)], True),
        "fit2017": (lambda d: d[d.season <= 2017], 2014, lambda d: d[d.season.between(2018, 2019)], False),
        "final": (lambda d: d[d.season <= 2025], 2014, lambda d: d[d.season >= 2018], True),
    }
    preds, drv = [], []
    metrics = {"cv_stat": cv, "chosen_stat": {k: v["chosen"] for k, v in cfg.items()}}
    for kind, data, c in (("stat", st, cfg), ("prior", pr, PRIOR_CFG)):
        spread_kind = None
        for name, (trf, wcut, prf, do_drv) in fits.items():
            tr, tg = trf(data), prf(data)
            mod = fit(tr, c, f"pitch_{kind}", wcut, spread_kind, WT)
            if name == "backtest":  # spread model and the s<=2012 CV calibration check (the only one reported)
                spread_kind = mod["spread_kind"]
                metrics.setdefault("spread", {})[kind] = mod["spread_info"]
                metrics.setdefault("calibration_check", {})[f"{kind}_{name}"] = mod["recal_info"]
            joblib.dump(mod, MODELS / f"pitch_{kind}_{name}.joblib")
            p = predict(mod, tg)
            preds.append(pd.concat([tg[["player_id", "season", "group"]], p], axis=1).assign(fit=name))
            if do_drv and kind == "stat":
                rows = tg if name == "backtest" else tg[tg.split == "score"]
                for t in ("p_mlb", "war"):
                    drv.append(drivers(mod, rows, t).assign(fit=name))
            print(f"{kind} {name}: trained {len(tr)} rows, predicted {len(tg)}", flush=True)
    metrics["c18"] = c18(st, cfg)
    metrics["reach_vs_hitters"] = reach_vs_hitters(st)
    metrics["contact_adjusted_rows"] = {int(k): int(v) for k, v in adjusted.items()}
    out = pd.concat(preds, ignore_index=True)
    for k, v in metrics["chosen_stat"].items():
        out[f"chosen_{k}"] = np.where(out.group == "stat", v, "linear")
    out.to_parquet(DATA / "pitch_predictions.parquet", index=False)
    pd.concat(drv, ignore_index=True).to_parquet(DATA / "pitch_drivers.parquet", index=False)
    json.dump(metrics, open(DATA / "b22_metrics.json", "w"), indent=1, default=float)
    print("chosen", metrics["chosen_stat"], "| spread", {k: v["chosen"] for k, v in metrics["spread"].items()},
          "| C11", {k: v["c11_pass"] for k, v in metrics["spread"].items()}, "| C18", json.dumps(metrics["c18"]))


if __name__ == "__main__":
    main()
