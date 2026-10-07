"""B8 surplus value model and grouped drivers (S10, S16, A15, A16, A6, A7, A1, D9, Q10, Q2). v1.1.

Surplus (S10, A15): debut year = snapshot + t with B6 hazard probabilities P(debut = s + t), t = 1..9 (A13). WAR draws =
war_mean + war_scale x z over the 199 stored standardized-residual quantiles of the row's B6 model (A16), each draw spread
over control years 1..6 by the historical share profile. Per control year: value = WAR x $/WAR(year); salary = league
minimum (years 1-3) or arb share x max(value, minimum) (years 4-6); surplus = max(value - salary, 0) (demote/release or
non-tender). Discounted to the snapshot at 8%/yr. ev_surplus = sum_t P(debut = s + t) x E_draws[surplus | debut s + t];
surplus_if_mlb = ev_surplus / p_mlb. Players already in MLB (S16): p = 1, control year 1 = their debut season, years up to
the snapshot are sunk. Backtest rows use $/WAR and minimum deflated from 2026 at the inflation rate (APPROXIMATE).

Grouped drivers (A6): full per-feature contributions (B6 `drivers`, top=all) summed within feature families.
Outputs: data/valuations.parquet, data/war_profile.parquet, data/drivers_grouped.parquet.
"""
import joblib
import numpy as np
import pandas as pd

from .b6_models import MODELS, T_MAX, drivers
from .common import DATA, MANUAL

BASE_YEAR = 2026
DEBUT_YEARS = [BASE_YEAR + t for t in range(1, T_MAX + 1)]


def load_params():
    p = pd.read_csv(MANUAL / "dollar_params.csv").set_index("param").value.astype(float)
    return {"dpw": p.dollars_per_war_2026, "infl": p.dollars_per_war_inflation, "min": p.mlb_min_salary_2026,
            "min_g": p.mlb_min_salary_growth_2027plus, "arb": [p.arb_share_year1, p.arb_share_year2, p.arb_share_year3],
            "disc": p.discount_rate}


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


def contract_surplus(war, debut_year, snapshot, share, prm):
    """Floored, discounted surplus ($) of each WAR draw. war: (n, k) draws; debut_year, snapshot: (n,). Control years
    with calendar year <= snapshot are sunk (already-debuted players)."""
    out = np.zeros(war.shape)
    for y in range(1, 7):
        yr = debut_year + y - 1
        live = (yr > snapshot)[:, None]
        dpw = (prm["dpw"] * (1 + prm["infl"]) ** (yr - BASE_YEAR))[:, None]
        mn = (prm["min"] * (1 + prm["min_g"]) ** (yr - BASE_YEAR))[:, None]
        value = war * share[y - 1] * dpw
        sal = mn if y <= 3 else prm["arb"][y - 4] * np.maximum(value, mn)
        out += np.where(live, np.maximum(value - sal, 0) / ((1 + prm["disc"]) ** (yr - snapshot))[:, None], 0)
    return out


def _z(pred):
    """(n, 199) standardized residual quantiles of each row's B6 model (A16)."""
    z = np.zeros((len(pred), 199))
    for (fit, group), idx in pred.groupby(["fit", "group"]).groups.items():
        z[pred.index.get_indexer(idx)] = joblib.load(MODELS / f"{group}_{fit}.joblib")["z"]
    return z


def value(pred, prof, prm, war_col="war_mean"):
    pred = pred.reset_index(drop=True)
    v = pred[["player_id", "season", "fit", "group", "low_confidence", "debuted", "p_mlb", "war_mean", "war_q10", "war_q50",
              "war_q90", "eta_mean"]].copy()
    share, snap = np.asarray(prof.share), v.season.to_numpy()
    draws = pred[war_col].to_numpy()[:, None] + pred.war_scale.to_numpy()[:, None] * _z(pred)
    pdeb = pred[[f"p_debut_t{t}" for t in range(1, T_MAX + 1)]].to_numpy()
    deb = v.debuted.to_numpy(bool)
    per_draw = np.zeros(draws.shape)  # E over arrival, per draw, unconditional (sums P(debut) x surplus)
    for t in range(1, T_MAX + 1):
        per_draw += pdeb[:, t - 1:t] * contract_surplus(draws, snap + t, snap, share, prm)
    debut_year = pd.to_numeric(pred.get("debut_year"), errors="coerce").to_numpy() if "debut_year" in pred else np.full(len(v), np.nan)
    if deb.any():
        per_draw[deb] = contract_surplus(draws[deb], debut_year[deb].astype(int), snap[deb], share, prm)
    p = v.p_mlb.to_numpy()
    cond = per_draw / np.clip(p, 1e-9, None)[:, None]  # conditional on reaching
    v["surplus_if_mlb"] = cond.mean(axis=1)
    for a in (0.1, 0.5, 0.9):
        v[f"surplus_q{int(a * 100)}"] = np.quantile(cond, a, axis=1)
    v["ev_surplus"] = per_draw.mean(axis=1)
    for t in range(1, T_MAX + 1):  # 2026 rows: calendar years; backtest rows: snapshot + t
        v[f"p_debut_{BASE_YEAR + t}"] = pdeb[:, t - 1]
    return v


# ---------- grouped drivers ----------
FAMILIES = ["Age", "Strikeouts", "Walks", "Power", "Swing and miss", "Position", "Speed", "Development pace", "Body", "Draft pedigree", "Other"]
_DEV = {"games_at_current_level", "ascent_pace", "levels_climbed_s", "repeated_level", "pro_years", "highest_level", "career_milb_pa",
        "PA_s", "PA_highest", "level_num", "log_PA", "years_since_draft"}


EXPECT = {"Strikeouts": -1, "Walks": 1, "Power": 1, "Swing and miss": 1, "Speed": 1}  # sign of contribution when the lead input is above the training mean
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
    if f.endswith(("contact_rate", "swing_rate")):  # S15 contact group (BABIP left the model in v1.1)
        return "Swing and miss"
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


def full_contrib(fit, group, rows):
    mod = joblib.load(MODELS / f"{group}_{fit}.joblib")
    return pd.concat([drivers(mod, rows, t, top=999) for t in ("p_mlb", "war")], ignore_index=True)


DIR_FEATS = {"Strikeouts": ("blend_K", "K%", True), "Walks": ("blend_BB", "BB%", True), "Power": ("blend_ISO", "ISO", False),
             "Swing and miss": ("blend_contact_rate", "Contact rate (1 - whiffs/swings)", True), "Speed": ("sb_att_rate", "SB attempts per time on base", True)}


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
            pre = "" if fam in ("Strikeouts", "Walks", "Speed", "Swing and miss") else "MLB-equivalent "
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
    f = pd.read_parquet(DATA / "features.parquet")
    pred = pd.concat([fin, bt], ignore_index=True).merge(f[["player_id", "season", "debut_year"]], on=["player_id", "season"], how="left")
    v = value(pred, prof, prm)
    v["s14_applied"] = pred.s14_applied.fillna(False).astype(bool).to_numpy()
    v.to_parquet(DATA / "valuations.parquet", index=False)
    gd = grouped_drivers(pred, f)
    gd.to_parquet(DATA / "drivers_grouped.parquet", index=False)
    print(v[v.fit == "final"].groupby("group").ev_surplus.describe().to_string())
    print(len(v), "valuations;", len(gd), "grouped driver rows")


if __name__ == "__main__":
    main()
