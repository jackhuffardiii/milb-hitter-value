"""B8 surplus value model and grouped drivers (S10, A6, A7, A1, D9, Q10, Q2).

Surplus (S10): for each prediction row, debut year = snapshot+1+J, J ~ Poisson(eta_mean) truncated at 8 and renormalised
(eta 0 = debut in snapshot+1). WAR in control years 1..6 = war * share_y (share profile from historical reached hitters).
value = war * $/WAR(year), pre-arb (y 1-3) salary = league minimum, arb (y 4-6) salary = share * max(value, minimum).
Cash flows are discounted to the snapshot year at 8%/yr (cash flow in calendar year Y: 1.08^-(Y-snapshot)).
Expected surplus = p_mlb * surplus_if_mlb; a player who never reaches costs nothing in this model. WAR is raw (no floor),
so q10 surplus can be negative. Backtest rows use the same function with $/WAR and minimum salary deflated back from
2026 at the inflation rate (APPROXIMATE era parameters).

Grouped drivers (A6): full per-feature contributions (B6 `drivers`, top=all) summed within feature families.
Outputs: data/valuations.parquet, data/war_profile.parquet, data/drivers_grouped.parquet.
"""
import joblib
import numpy as np
import pandas as pd
from scipy.stats import poisson

from .b6_models import MODELS, _X, drivers, prior_X
from .common import DATA, MANUAL

J_MAX, BASE_YEAR = 8, 2026
DEBUT_YEARS = [BASE_YEAR + 1 + j for j in range(J_MAX + 1)]


def load_params():
    p = pd.read_csv(MANUAL / "dollar_params.csv").set_index("param").value.astype(float)
    return {"dpw": p.dollars_per_war_2026, "infl": p.dollars_per_war_inflation, "min": p.mlb_min_salary_2026,
            "min_g": p.mlb_min_salary_growth_2027plus, "arb": [p.arb_share_year1, p.arb_share_year2, p.arb_share_year3],
            "disc": p.discount_rate}


def arrival_probs(eta_mean):
    """(n, J_MAX+1) P(debut = snapshot+1+j), Poisson(eta_mean) truncated at J_MAX and renormalised."""
    pm = poisson.pmf(np.arange(J_MAX + 1)[None, :], np.asarray(eta_mean, float)[:, None])
    return pm / pm.sum(axis=1, keepdims=True)


def war_profile():
    """Share of war_6yr realised in control year 1..6: mean owar in year k / mean war_6yr, over reached non-censored
    debuts 2005-2017 (missing seasons count 0), normalised to sum 1."""
    wt = pd.read_parquet(DATA / "war_target.parquet")
    wt = wt[(~wt.censored) & (~wt.pre2005) & wt.debut_season.between(2005, 2017)]
    m = pd.read_parquet(DATA / "mlb_war.parquet")[["player_id", "season", "owar"]].merge(wt[["player_id", "debut_season"]])
    m["y"] = m.season - m.debut_season + 1
    m = m[m.y.between(1, 6)]
    mean_y = m.groupby("y").owar.sum().reindex(range(1, 7), fill_value=0) / len(wt)
    return pd.DataFrame({"control_year": range(1, 7), "mean_owar": mean_y.to_numpy(), "share": (mean_y / mean_y.sum()).to_numpy(),
                         "n_players": len(wt)})


def surplus_if_mlb(war, eta_mean, snapshot, prof, prm):
    """Expected discounted surplus ($) given the player reaches MLB, per row. Increasing in war; later eta lowers it."""
    war, snap = np.asarray(war, float), np.asarray(snapshot, int)
    pj, share = arrival_probs(eta_mean), np.asarray(prof.share)
    out = np.zeros(len(war))
    for j in range(J_MAX + 1):
        tot = np.zeros(len(war))
        for y in range(1, 7):
            yr = snap + 1 + j + y - 1  # calendar year of control year y
            dpw = prm["dpw"] * (1 + prm["infl"]) ** (yr - BASE_YEAR)
            mn = prm["min"] * (1 + prm["min_g"]) ** (yr - BASE_YEAR)
            value = war * share[y - 1] * dpw
            sal = mn if y <= 3 else prm["arb"][y - 4] * np.maximum(value, mn)
            tot += (value - sal) / (1 + prm["disc"]) ** (yr - snap)
        out += pj[:, j] * tot
    return out


def value(pred, prof, prm):
    v = pred[["player_id", "season", "fit", "group", "low_confidence", "p_mlb", "war_mean", "war_q10", "war_q50", "war_q90", "eta_mean"]].copy()
    pj = arrival_probs(v.eta_mean)
    # debut-year columns are calendar years relative to the 2026 snapshot (2026 rows); backtest rows use snapshot+1+j
    for j in range(J_MAX + 1):
        v[f"p_debut_{BASE_YEAR + 1 + j}"] = pj[:, j]
    for k, c in [("mean", "war_mean"), ("q10", "war_q10"), ("q50", "war_q50"), ("q90", "war_q90")]:
        s = surplus_if_mlb(v[c], v.eta_mean, v.season, prof, prm)
        v["surplus_if_mlb" if k == "mean" else f"surplus_{k}"] = s
    v["ev_surplus"] = v.p_mlb * v.surplus_if_mlb
    return v


# ---------- grouped drivers ----------
FAMILIES = ["Age", "Strikeouts", "Walks", "Power", "Contact quality", "Position", "Speed", "Development pace", "Body", "Draft pedigree", "Other"]
_DEV = {"games_at_current_level", "ascent_pace", "levels_climbed_s", "repeated_level", "pro_years", "highest_level", "career_milb_pa",
        "PA_s", "PA_highest", "level_num", "log_PA", "years_since_draft"}


EXPECT = {"Strikeouts": -1, "Walks": 1, "Power": 1, "Contact quality": 1, "Speed": 1}  # sign of contribution when the lead input is above the training mean
NOTE = "; net effect also reflects trend/regressed values"


def family(feat):
    if feat.startswith("missingindicator_delta_"):  # "no prior-season delta" flags describe career stage, not the rate they are named after
        return "Development pace"
    f = feat.removeprefix("missingindicator_").split("=")[0]
    if f in ("age", "age_vs_level"):
        return "Age"
    if f.endswith("_K"):
        return "Strikeouts"
    if f.endswith("_BB"):
        return "Walks"
    if f.endswith("_ISO"):
        return "Power"
    if f.endswith("_BABIP"):
        return "Contact quality"
    if f == "exp_pos_runs" or f.startswith(("p_", "pos_share_")):
        return "Position"
    if f in ("sb_att_rate", "sb_success", "triple_rate"):
        return "Speed"
    if f in _DEV:
        return "Development pace"
    if f in ("height_in", "bats"):
        return "Body"
    if f in ("round_num", "pick_overall", "log_bonus", "international"):
        return "Draft pedigree"
    return "Other"


def _prior_contrib(mod, df):
    X = prior_X(df)[mod["cols"]]
    rows = []
    for t in ("p_mlb", "war"):
        imp, sc, lin = mod[t].steps[0][1], mod[t].steps[1][1], mod[t].steps[2][1]
        c = sc.transform(imp.transform(X)) * np.ravel(lin.coef_)
        names = list(imp.get_feature_names_out(mod["cols"]))
        rows.append(pd.DataFrame({"player_id": np.repeat(df.player_id.to_numpy(), len(names)), "season": np.repeat(df.season.to_numpy(), len(names)),
                                  "target": t, "feature": np.tile(names, len(df)), "contribution": c.ravel()}))
    return pd.concat(rows, ignore_index=True)


def full_contrib(fit, group, rows):
    mod = joblib.load(MODELS / f"{group}_{fit}.joblib")
    if group == "prior":
        return _prior_contrib(mod, rows)
    return pd.concat([drivers(mod, rows, t, top=999) for t in ("p_mlb", "war")], ignore_index=True)


DIR_FEATS = {"Strikeouts": ("blend_K", "K%", True), "Walks": ("blend_BB", "BB%", True), "Power": ("blend_ISO", "ISO", False),
             "Contact quality": ("blend_BABIP", "BABIP", False), "Speed": ("sb_att_rate", "SB attempts per time on base", True)}


def _phrases(r, ref):
    """Plain-English phrase per family. Directional families compare the family's lead model input with `ref`, the pooled
    training-row mean of that input (the same reference the model contribution is measured against). Returns {family: (phrase, dir)},
    dir = +1 above / -1 below the reference, 0 for neutral (multi-input) families."""
    lv = str(r.highest_level).upper() if pd.notna(r.get("highest_level")) else "?"
    ag = r.age_vs_level
    out = {"Age": (f"Age {r.age:.1f}; {abs(ag):.1f} yrs {'younger' if ag < 0 else 'older'} than {lv} avg", 0)}
    for fam, (col, lab, pct) in DIR_FEATS.items():
        v = r.get(col)
        if pd.notna(v):
            f = (lambda x: f"{x:.1%}") if pct else (lambda x: f"{x:.3f}")
            pre = "" if fam in ("Strikeouts", "Walks", "Speed") else "MLB-equivalent "
            out[fam] = (f"{pre}{lab} {f(v)} vs {f(ref[col])} prospect avg", 1 if v > ref[col] else -1)
    out["Position"] = ((f"Catcher profile ({r.p_C:.0%} C, pos adj {r.exp_pos_runs:+.1f} runs)" if pd.notna(r.get("p_C")) and r.p_C >= .5
                        else f"Position adjustment {r.exp_pos_runs:+.1f} runs") if pd.notna(r.get("exp_pos_runs")) else "Position", 0)
    if "Speed" not in out:
        out["Speed"] = ("Speed: little base-stealing data", 0)
    g = r.get("games_at_current_level")
    out["Development pace"] = ((f"{r.pro_years:.0f} pro years, {g:.0f} games at {lv}" if pd.notna(g) else f"{r.pro_years:.0f} pro years at {lv}")
                               if pd.notna(r.get("pro_years")) else "Development pace", 0)
    out["Body"] = (f"Height {r.height_in:.0f} in" if pd.notna(r.get("height_in")) else "Body: no height listed", 0)
    out["Draft pedigree"] = ("Draft: " + (f"round {r.round_num:.0f}, pick {r.pick_overall:.0f}" if pd.notna(r.get("round_num")) else "international/undrafted"), 0)
    return out


def grouped_drivers(pred, feats):
    out = []
    for (fit, group), pr in pred.groupby(["fit", "group"]):
        rows = feats[feats.group == group].merge(pr[["player_id", "season"]], on=["player_id", "season"]).reset_index(drop=True)
        c = full_contrib(fit, group, rows)
        c["family"] = c.feature.map(family)
        if group == "stat":
            assert (c.family != "Other").all(), c[c.family == "Other"].feature.unique()
        total = c.groupby(["player_id", "season", "target"]).contribution.sum()
        g = c.groupby(["player_id", "season", "target", "family"], as_index=False).contribution.sum()
        assert np.allclose(g.groupby(["player_id", "season", "target"]).contribution.sum().reindex(total.index), total, atol=1e-6)
        tr = feats[(feats.group == group) & (feats.split == "train_era")]
        if fit == "backtest":
            tr = tr[tr.season <= 2012]
        ref = tr[[c for c, _, _ in DIR_FEATS.values()]].mean()
        ph = {(r.player_id, r.season): _phrases(r, ref) for _, r in rows.iterrows()}
        pd_ = [ph[(p, s)].get(f, (f, 0)) for p, s, f in zip(g.player_id, g.season, g.family)]
        g["phrase"], g["input_dir"] = [x[0] for x in pd_], np.array([x[1] for x in pd_])
        # keep a direction only where it agrees with the family's net contribution; otherwise say so and imply none
        exp = g.family.map(EXPECT).fillna(0).to_numpy()
        bad = (g.input_dir.to_numpy() * exp * g.contribution.to_numpy()) < 0
        g["suppressed"] = bad
        g.loc[bad, "phrase"] = g.loc[bad, "phrase"] + NOTE
        g.loc[bad, "input_dir"] = 0
        g["fit"], g["group"] = fit, group
        g["rank"] = g.assign(a=g.contribution.abs()).groupby(["player_id", "season", "target"]).a.rank(ascending=False, method="first").astype(int)
        out.append(g)
    return pd.concat(out, ignore_index=True)[["player_id", "season", "fit", "group", "target", "family", "contribution", "phrase", "input_dir", "suppressed", "rank"]]


def main():
    prm, prof = load_params(), war_profile()
    prof.to_parquet(DATA / "war_profile.parquet", index=False)
    print(prof.to_string(index=False))
    fin = pd.read_parquet(DATA / "predictions_final.parquet")
    fin = fin[fin.season == 2026]
    bt = pd.read_parquet(DATA / "predictions.parquet")
    bt = bt[bt.fit == "backtest"]
    pred = pd.concat([fin, bt], ignore_index=True)
    v = value(pred, prof, prm)
    v["s14_applied"] = pred.s14_applied.fillna(False).astype(bool).to_numpy()
    v.to_parquet(DATA / "valuations.parquet", index=False)
    f = pd.read_parquet(DATA / "features.parquet")
    gd = grouped_drivers(pred, f)
    gd.to_parquet(DATA / "drivers_grouped.parquet", index=False)
    print(v[v.fit == "final"].groupby("group").ev_surplus.describe().to_string())
    print(len(v), "valuations;", len(gd), "grouped driver rows")


if __name__ == "__main__":
    main()
