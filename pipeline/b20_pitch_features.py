"""B20: pitcher snapshot table (S21, S23, S24, S25, S26, C15), mirroring B5 for hitters.

One row per pitcher x season s (2005-2026) with affiliated MiLB pitching in s (not Mexican League), who is a pitcher
(bio primary_pos P/TWP) or threw >= 150 BF in s (S29), and is rookie-eligible at end of s (career MLB outs through s < 150).
group 'stat' (A..AAA BF over s and s-1 >= 150, or over s, s-1, s-2 when under 60 A..AAA outs in s; and complete reg_K/BB/GB/XB
for s) else 'prior'. Non-stat rows carry NaN MLE / mERA features. Labels: reached_mlb, eta_years, war_6yr.
Also writes p_sp (S24, logistic P(starter) display column, never a model feature -> data/b20_psp.json) and runs the C15 gate
for mERA as a feature (-> data/b20_c15.json), mirroring B12's evaluator on s <= 2012 stat, not-debuted rows (GroupKFold(5)).
Only mera_cv columns enter the gate (never the final mera). Caveat, reported not hidden: mera_cv's own coefficients were fit
on target seasons <= 2012, the same window as this CV, so the gate carries mild cross-fold leakage in mERA's favor (about
12 coefficients over ~11.6k rows).
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .b5_features import LVL, MEXICAN_LEAGUE, YEARS, _blend, draft_features
from .b6_models import _lgb_cv, _linear, _predict
from .common import DATA

RATES = ["K", "BB", "HBP", "HR", "GB", "XB"]
STAT_REG = ["reg_K", "reg_BB", "reg_GB", "reg_XB"]
PSP_FEATS = ["blend_GS_share", "blend_outs_per_G", "blend_pitches_per_G", "reg_K", "reg_BB", "reg_GB", "age", "level_num"]
K = ["player_id", "season"]
PITCH_NUM = (["level_num", "age", "age_vs_level", "pro_years"]
             + [f"blend_reg_{r}" for r in ("K", "BB", "HBP", "HR", "GB", "XB")] + ["delta_reg_K", "delta_reg_BB"]
             + ["blend_GS_share", "blend_outs_per_G", "blend_pitches_per_G", "levels_climbed_s", "height_in"])
PITCH_LOG = ["BF_s", "BF_highest", "career_milb_bf"]
PITCH_CATS = {"throws": ["L", "R"], "highest_level": ["a", "a+", "aa", "aaa"]}


def pitch_X(df, extra=()):
    """Pitcher design matrix (B22 reuses it): baseline features + `extra` columns (raw)."""
    X = df[PITCH_NUM].astype(float).copy()
    for c in PITCH_LOG:
        X[c] = np.log1p(df[c].astype(float))
    for c in extra:
        X[c] = df[c].astype(float).to_numpy()
    for col, cats in PITCH_CATS.items():
        for v in cats:
            X[f"{col}={v}"] = (df[col] == v).astype(float)
    return X.reset_index(drop=True)


def _role(S):
    """GS share, outs/G, pitches/G over all affiliated rows of each pitcher-season, plus BF weight (blend adds s-1)."""
    g = S.groupby(K)
    r = pd.DataFrame({"G": g.G.sum(), "GS": g.GS.sum(), "outs": g.outs.sum(), "BF_s": g.BF.sum(),
                      "pitches": g.pitches.agg(lambda x: x.sum(skipna=False))}).reset_index()
    r["GS_share"], r["outs_per_G"] = r.GS / r.G.where(r.G > 0), r.outs / r.G.where(r.G > 0)
    r["pitches_per_G"] = r.pitches / r.G.where(r.G > 0)  # NaN when any stint lacks pitch counts
    cols = ["GS_share", "outs_per_G", "pitches_per_G"]
    return r[K + cols + ["BF_s"]].merge(_blend(r, cols, "BF_s"), on=K, how="left")


def _lag_blend(snap, T, rates, w, prefix):
    """B5's Marcel pattern: s weight 3, s-1 weight 2 (by BF), plus delta = s minus s-1. T: player-season table."""
    p = T[K + [w] + [f"{prefix}{r}" for r in rates]].assign(season=lambda d: d.season + 1)
    p.columns = K + ["p_" + c for c in p.columns[2:]]
    snap = snap.merge(p, on=K, how="left")
    for r in rates:
        x0, x1 = snap[f"{prefix}{r}"], snap[f"p_{prefix}{r}"]
        w0, w1 = 3 * snap[w], (2 * snap["p_" + w]).where(x1.notna(), 0)
        snap[f"blend_{prefix}{r}"] = (x0 * w0 + x1.fillna(0) * w1) / (w0 + w1)
        snap[f"delta_{prefix}{r}"] = x0 - x1
    return snap.drop(columns=["p_" + w] + [f"p_{prefix}{r}" for r in rates])


def build():
    S = pd.read_parquet(DATA / "milb_pitching_seasons.parquet")
    S = S[S.league_id != MEXICAN_LEAGUE].assign(lv=lambda d: d.level.map(LVL))
    for c in ("G", "GS", "outs", "BF"):
        S[c] = S[c].fillna(0)
    pl = pd.read_parquet(DATA / "pitch_players.parquet")
    mp = pd.read_parquet(DATA / "mlb_pitching.parquet")

    S = S.sort_values(["player_id", "season", "lv", "BF"])
    g = S.groupby(K)
    top = g.tail(1).set_index(K)
    snap = pd.DataFrame({"highest_level": top.level, "level_num": top.lv, "age": g.age.last(), "throws": top.throws,
                         "BF_s": g.BF.sum()}).reset_index()
    hl = S.merge(snap[K + ["highest_level"]], on=K)
    hl = hl[hl.level == hl.highest_level].groupby(K).BF.sum().rename("BF_highest")
    snap = snap.merge(hl.reset_index(), on=K)
    # career MiLB BF through s (incl. 2000-04 history, Q17) and pro years
    hist = pd.read_parquet(DATA / "milb_pitch_history.parquet")
    hist = hist[hist.league_id != MEXICAN_LEAGUE]
    ps = pd.concat([S[K + ["BF"]], hist[K + ["BF"]]]).groupby(K).BF.sum().reset_index().sort_values(K)
    ps["career_milb_bf"] = ps.groupby("player_id").BF.cumsum()
    ps["pro_years"] = ps.season - ps.groupby("player_id").season.transform("min") + 1
    snap = snap.merge(ps[K + ["career_milb_bf", "pro_years"]], on=K)
    # age vs level: BF-weighted mean age of all affiliated pitchers at the season-level
    a = S.dropna(subset=["age"]).assign(wa=lambda d: d.age * d.BF).groupby(["season", "level"])[["wa", "BF"]].sum()
    snap = snap.merge((a.wa / a.BF).rename("lvl_age").reset_index(), left_on=["season", "highest_level"],
                      right_on=["season", "level"], how="left").drop(columns="level")
    snap["age_vs_level"] = snap.age - snap.lvl_age
    snap = snap.drop(columns="lvl_age")
    # pace: level change vs last season's highest level
    prev = snap[K + ["level_num", "highest_level"]].assign(season=lambda d: d.season + 1)
    snap = snap.merge(prev.rename(columns={"level_num": "p_lv", "highest_level": "p_hl"}), on=K, how="left")
    snap["levels_climbed_s"] = snap.level_num - snap.p_lv
    snap["repeated_level"] = (snap.highest_level == snap.p_hl).astype(float).where(snap.p_hl.notna())
    snap = snap.drop(columns=["p_lv", "p_hl"])
    # role (S23)
    role = _role(S)
    snap = snap.merge(role.drop(columns="BF_s"), on=K, how="left")

    # population: pitcher by bio or >= 150 BF; rookie eligible (S25); 2005-2026
    snap = snap.merge(pl[["player_id", "primary_pos", "height_in", "weight_lb", "mlb_debut_date", "full_name", "throws"]]
                      .rename(columns={"throws": "bio_throws", "full_name": "name"}), on="player_id", how="left")
    snap["throws"] = snap.throws.fillna(snap.bio_throws)
    snap = snap.drop(columns="bio_throws")
    snap = snap[snap.primary_pos.isin(["P", "TWP"]) | (snap.BF_s >= 150)].drop(columns="primary_pos")
    mo = mp.groupby(K).outs.sum().reset_index().sort_values(K)
    c = snap[K].merge(mo, on="player_id", suffixes=("", "_m"))
    c = c[c.season_m <= c.season].groupby(K).outs.sum().rename("mlb_outs_thru")
    snap = snap.merge(c.reset_index(), on=K, how="left")
    snap = snap[(snap.mlb_outs_thru.fillna(0) < 150) & snap.season.isin(YEARS)].drop(columns="mlb_outs_thru")

    # stat group (S25): A..AAA BF over s, s-1 (and s-2 if under 60 outs in s) and complete reg_ for s
    H = S[S.lv >= 1].groupby(K)[["BF", "outs"]].sum().reset_index()
    def lag(n):
        return H.assign(season=H.season + n)[K + ["BF"]].rename(columns={"BF": f"bf{n}"})
    snap = snap.merge(H.rename(columns={"BF": "bf0", "outs": "outs0"}), on=K, how="left")
    for n in (1, 2):
        snap = snap.merge(lag(n), on=K, how="left")
    bf0, outs0 = snap.bf0.fillna(0), snap.outs0.fillna(0)
    snap["bf_win"] = bf0 + snap.bf1.fillna(0) + snap.bf2.fillna(0).where(outs0 < 60, 0)
    snap = snap.drop(columns=["bf0", "outs0", "bf1", "bf2"])
    mle = pd.read_parquet(DATA / "pitch_mle_player_season.parquet")
    regc = [f"reg_{r}" for r in RATES]
    mc = mle[K + ["BF"] + regc].rename(columns={"BF": "mle_BF"})
    snap = snap.merge(mc, on=K, how="left")
    snap["group"] = np.where((snap.bf_win >= 150) & snap[STAT_REG].notna().all(axis=1), "stat", "prior")
    stat = (snap.group == "stat").to_numpy()
    snap.loc[~stat, regc + ["mle_BF"]] = np.nan
    snap = _lag_blend(snap, mc, RATES, "mle_BF", "reg_").drop(columns=["bf_win", "mle_BF"])
    # mERA (S21): mera_cv (out-of-sample fit) and mera (final) with 3:2 blends
    me = pd.read_parquet(DATA / "pitch_mera_player_season.parquet")
    mb = me[K + ["BF", "mera_cv", "mera"]].merge(_blend(me, ["mera_cv", "mera"], "BF"), on=K, how="left")
    mb = mb.rename(columns={"blend_mera_cv": "mera_cv_blend", "blend_mera": "mera_blend"}).drop(columns="BF")
    snap = snap.merge(mb, on=K, how="left")
    snap.loc[~stat, ["mera_cv", "mera", "mera_cv_blend", "mera_blend"]] = np.nan

    # draft (+ HS vs college for the P(SP) prior)
    snap = draft_features(snap, hs=True)
    # IL 2026 (S26, display only)
    il = pd.read_parquet(DATA / "il_2026.parquet").groupby("player_id").il_days.agg(il_count="size", il_max_days="max")
    snap = snap.merge(il, left_on="player_id", right_index=True, how="left")
    is26 = snap.season == 2026
    snap["il_count"] = snap.il_count.fillna(0).where(is26)
    snap.loc[~is26, "il_max_days"] = np.nan
    # labels
    snap["debut_year"] = snap.mlb_debut_date.dt.year
    snap["reached_mlb"] = snap.debut_year.notna()
    snap["debuted"] = snap.debut_year <= snap.season
    snap["eta_years"] = (snap.debut_year - snap.season).where(snap.reached_mlb & ~snap.debuted)
    snap = snap.merge(pd.read_parquet(DATA / "pitch_war_target.parquet")[["player_id", "war_6yr"]], on="player_id", how="left")
    snap.loc[~snap.reached_mlb, "war_6yr"] = np.nan
    snap["split"] = np.select([snap.season <= 2017, snap.season <= 2025], ["train_era", "censored"], "score")
    snap = snap.drop(columns="mlb_debut_date").sort_values(K).reset_index(drop=True)
    return snap, mp


def p_sp(snap, mp):
    """S24: P(starter) from the last pre-debut stat snapshot of 2016-2025 debutants. Starter = GS/G > 0.5 over MLB seasons D, D+1."""
    deb = snap.groupby("player_id").debut_year.first()
    deb = deb[deb.between(2016, 2025)]
    m = mp.merge(deb.rename("D"), left_on="player_id", right_index=True)
    m = m[(m.season == m.D) | (m.season == m.D + 1)]
    y = m.groupby("player_id").apply(lambda d: d.GS.sum() / d.G.sum() > 0.5, include_groups=False).rename("is_starter")
    st = snap[snap.group == "stat"]
    t = st.merge(y, left_on="player_id", right_index=True)
    t = t[t.season < t.debut_year].sort_values(K).groupby("player_id").tail(1)
    X, yy, gp = t[PSP_FEATS], t.is_starter.astype(int).to_numpy(), t.player_id.to_numpy()
    mk = lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
    oof = np.zeros(len(t))
    for tr, te in GroupKFold(5).split(X, yy, gp):
        oof[te] = mk().fit(X.iloc[tr], yy[tr]).predict_proba(X.iloc[te])[:, 1]
    metrics = {"n": len(t), "base_rate": float(yy.mean()), "oof_logloss": float(log_loss(yy, oof)),
               "oof_auc": float(roc_auc_score(yy, oof)),
               "baseline_logloss": float(log_loss(yy, np.full(len(yy), yy.mean())))}
    model = mk().fit(X, yy)
    snap["p_sp"] = np.nan
    snap.loc[st.index, "p_sp"] = model.predict_proba(st[PSP_FEATS])[:, 1]
    (DATA / "b20_psp.json").write_text(json.dumps(metrics, indent=1))
    return metrics


def evaluate(df, extra, wt):
    X, y, g = pitch_X(df, extra), df.reached_mlb.astype(int).to_numpy(), df.player_id.to_numpy()
    p, _ = _lgb_cv("p_mlb", X, y, g)
    ok = (~df.player_id.map(wt.censored).fillna(False).astype(bool) & ~df.player_id.map(wt.pre2005).fillna(False).astype(bool)).to_numpy()
    war = df.war_6yr.to_numpy()
    train_w = ok & df.reached_mlb.to_numpy(bool) & ~np.isnan(war)
    w = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, g):
        tr = tr[train_w[tr]]
        w[te] = _predict(_linear("war").fit(X.iloc[tr], war[tr]), X.iloc[te], "war")
    real = np.where(y == 1, np.nan_to_num(war), 0.0)
    return {"logloss": float(log_loss(y, p)), "ev_spearman": float(spearmanr((p * w)[ok], real[ok])[0])}


def c15(snap):
    df = snap[(snap.group == "stat") & (snap.season <= 2012) & ~snap.debuted].reset_index(drop=True)
    wt = pd.read_parquet(DATA / "pitch_war_target.parquet").set_index("player_id")
    b = evaluate(df, [], wt)
    res = {"baseline": b}
    for name, extra in (("mera_cv_blend", ["mera_cv_blend"]), ("mera_cv", ["mera_cv"])):
        r = evaluate(df, extra, wt)
        dl, ds = b["logloss"] - r["logloss"], r["ev_spearman"] - b["ev_spearman"]
        r.update(d_logloss_gain=dl, d_spearman_gain=ds, keep=bool((dl > 0 or ds > 0) and dl >= 0 and ds >= 0))  # C15 as written: no tolerance (Jack, 2026-10-10)
        res[name] = r
    kept = [n for n in ("mera_cv_blend", "mera_cv") if res[n]["keep"]]
    res["kept_feature"] = max(kept, key=lambda n: res[n]["d_logloss_gain"] + res[n]["d_spearman_gain"]) if kept else None
    out = {"n_rows": len(df), "rule": "improve one metric, worsen neither (strict C15)", **res}
    (DATA / "b20_c15.json").write_text(json.dumps(out, indent=1))
    return out


def main():
    snap, mp = build()
    print("p_sp", p_sp(snap, mp), flush=True)
    snap.to_parquet(DATA / "pitch_features.parquet", index=False)
    print(snap.groupby(["split", "group"]).size().unstack())
    te = snap[(snap.split == "train_era") & (snap.group == "stat")]
    print(te.groupby("highest_level").reached_mlb.agg(["mean", "size"]))
    print(json.dumps(c15(snap), indent=1))


if __name__ == "__main__":
    main()
