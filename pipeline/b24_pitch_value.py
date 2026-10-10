"""B24 (S29, C19, Q23): pitcher surplus $, two-way sum, combined 2026 board.

Pitcher surplus uses B8's machinery unchanged (value(), contract_surplus, grouped_drivers) with the pitcher WAR-by-control-year
profile (pitch_war_target / mlb_pitch_war.pwar) and the B22 models (prefix "pitch_").
Combined board (S30): every 2026 hitter and pitcher row ranked by ev_surplus, role H / P / 2W. Two-way (S29): a player in both
2026 populations with 150+ PA and 150+ BF gets value = hitter + pitcher, labelled "if both paths stick" (Q23); quantiles are
summed as an approximation (not a convolution). A player in both populations without both thresholds keeps the side with more
volume (PA vs BF).
C19: hitter/pitcher WAR split sensitivity. WAR draws are rescaled by the share ratio (57/43: hitters x 570/590, pitchers x
430/410; 61/39 likewise), an approximation to re-anchoring replacement level; top-50 overlap and rank moves vs 59/41.
Outputs: data/pitch_valuations.parquet, data/pitch_war_profile.parquet, data/pitch_drivers_grouped.parquet,
data/board_2026.parquet, data/b24_c19.json.
"""
import json

import numpy as np
import pandas as pd

from . import b22_pitch_models  # noqa: F401  registers the pitch_* kinds in b6.XFN for drivers()
from .b8_value import grouped_drivers, load_params, value, war_profile
from .common import DATA

PREFIX = "pitch_"
SPLITS = {"57/43": (570 / 590, 430 / 410), "61/39": (610 / 590, 390 / 410)}
BOARD_COLS = ["player_id", "p_mlb", "war_mean", "eta_mean", "ev_surplus", "surplus_if_mlb", "surplus_q10", "surplus_q50",
              "surplus_q90", "group", "low_confidence", "debuted"]

FAMILIES = ["Age", "Strikeouts", "Walks", "Ground balls", "Contact allowed", "Role", "Development pace", "Body", "Draft pedigree"]
EXPECT = {"Strikeouts": 1, "Walks": -1, "Ground balls": 1, "Contact allowed": -1}
DIR_FEATS = {"Strikeouts": ("blend_reg_K", "K%", True), "Walks": ("blend_reg_BB", "BB%", True),
             "Ground balls": ("blend_reg_GB", "GB%", True), "Contact allowed": ("blend_reg_XB", "XB/BIP", False)}


def family(feat):
    f = feat.removeprefix("missingindicator_").split("=")[0]
    if feat.startswith("missingindicator_delta_"):
        return "Development pace"
    if f in ("age", "age_vs_level"):
        return "Age"
    if f.endswith("_K"):
        return "Strikeouts"
    if f.endswith(("_BB", "_HBP")):
        return "Walks"
    if f.endswith("_GB"):
        return "Ground balls"
    if f.endswith(("_HR", "_XB")):
        return "Contact allowed"
    if f in ("blend_GS_share", "blend_outs_per_G", "blend_pitches_per_G"):
        return "Role"
    if f in ("height_in", "throws"):
        return "Body"
    if f in ("round_num", "pick_overall", "log_bonus", "international", "hs_draftee"):
        return "Draft pedigree"
    return "Development pace"  # level, pro years, BF volume, levels climbed, years since draft


def phrases(r, ref):
    lv = str(r.highest_level).upper() if pd.notna(r.get("highest_level")) else "?"
    ag = r.age_vs_level
    out = {"Age": (f"Age {r.age:.1f}; {abs(ag):.1f} yrs {'younger' if ag < 0 else 'older'} than {lv} avg", 0)}
    for fam, (col, lab, pct) in DIR_FEATS.items():
        v = r.get(col)
        if pd.notna(v):
            f = (lambda x: f"{x:.1%}") if pct else (lambda x: f"{x:.3f}")
            out[fam] = (f"MLB-equivalent {lab} {f(v)} vs {f(ref[col])} prospect avg", 1 if v > ref[col] else -1)
    gs, ipg = r.get("blend_GS_share"), r.get("blend_outs_per_G")
    out["Role"] = (f"{gs:.0%} starts, {ipg / 3:.1f} IP per game" if pd.notna(gs) and pd.notna(ipg) else "Role", 0)
    out["Development pace"] = (f"{r.pro_years:.0f} pro year{'' if r.pro_years == 1 else 's'}, {r.BF_s:.0f} BF at {lv} and below this season"
                               if pd.notna(r.get("pro_years")) else "Development pace", 0)
    body = [f"Height {r.height_in:.0f} in"] if pd.notna(r.get("height_in")) else []
    out["Body"] = (", ".join(body + [f"throws {r.throws}"]) if pd.notna(r.get("throws")) else (body[0] if body else "Body"), 0)
    out["Draft pedigree"] = ("Draft: " + (f"round {r.round_num:.0f}, pick {r.pick_overall:.0f}" if pd.notna(r.get("round_num"))
                                          else "international/undrafted"), 0)
    return out


def pitcher_values():
    prm = load_params()
    prof = war_profile("pitch_war_target.parquet", "mlb_pitch_war.parquet", "pwar")
    prof.to_parquet(DATA / "pitch_war_profile.parquet", index=False)
    p = pd.read_parquet(DATA / "pitch_predictions.parquet")
    p = p[((p.fit == "final") & (p.season == 2026)) | (p.fit == "backtest")]
    f = pd.read_parquet(DATA / "pitch_features.parquet")
    pred = p.merge(f[["player_id", "season", "debut_year"]], on=["player_id", "season"], how="left").reset_index(drop=True)
    v = value(pred, prof, prm, prefix=PREFIX)
    v.to_parquet(DATA / "pitch_valuations.parquet", index=False)
    grouped_drivers(pred, f, PREFIX, family, phrases, DIR_FEATS, EXPECT).to_parquet(DATA / "pitch_drivers_grouped.parquet", index=False)
    return v, pred, prof, prm


def board(hv, pv):
    """Combined 2026 board from hitter and pitcher final valuations (one row per player)."""
    h = hv[["player_id"] + BOARD_COLS[1:]].assign(role="H")
    p = pv[["player_id"] + BOARD_COLS[1:]].assign(role="P")
    vol = pd.concat([pd.read_parquet(DATA / "features.parquet").query("season == 2026")[["player_id", "PA_s"]].set_index("player_id").PA_s,
                     pd.read_parquet(DATA / "pitch_features.parquet").query("season == 2026")[["player_id", "BF_s"]].set_index("player_id").BF_s],
                    axis=1)
    both = set(h.player_id) & set(p.player_id)
    two = {i for i in both if vol.PA_s.get(i, 0) >= 150 and vol.BF_s.get(i, 0) >= 150}
    keep_h = {i for i in both - two if vol.PA_s.get(i, 0) >= vol.BF_s.get(i, 0)}
    rows = [h[~h.player_id.isin(both) | h.player_id.isin(keep_h)], p[~p.player_id.isin(both) | p.player_id.isin(both - two - keep_h)]]
    if two:
        hh, pp = h[h.player_id.isin(two)].set_index("player_id"), p[p.player_id.isin(two)].set_index("player_id")
        add = ["ev_surplus", "surplus_if_mlb", "surplus_q10", "surplus_q50", "surplus_q90", "war_mean"]
        tw = hh.copy()
        tw[add] = hh[add] + pp[add]
        tw["p_mlb"] = np.maximum(hh.p_mlb, pp.p_mlb)
        rows.append(tw.reset_index().assign(role="2W"))
    b = pd.concat(rows, ignore_index=True).sort_values("ev_surplus", ascending=False).reset_index(drop=True)
    b["rank"] = np.arange(1, len(b) + 1)
    return b


def c19(hpred, hprof, ppred, pprof, prm, base):
    """Rescale WAR draws (mean and scale) by the split ratio, revalue, compare the top 50 with the 59/41 board."""
    top = base.head(50)
    out = {"approximation": "WAR rescaled by share ratio, not re-anchored replacement level"}
    for name, (fh, fp) in SPLITS.items():
        hv = value(hpred.assign(war_mean=hpred.war_mean * fh, war_scale=hpred.war_scale * fh), hprof, prm)
        pv = value(ppred.assign(war_mean=ppred.war_mean * fp, war_scale=ppred.war_scale * fp), pprof, prm, prefix=PREFIX)
        b = board(hv[hv.fit == "final"], pv[pv.fit == "final"])
        t = b.head(50)
        r = top[["player_id", "rank", "role"]].merge(b[["player_id", "rank"]], on="player_id", suffixes=("", "_alt"))
        out[name] = {"top50_overlap": int(len(set(t.player_id) & set(top.player_id))),
                     "top50_pitchers": int((t.role != "H").sum()), "base_top50_pitchers": int((top.role != "H").sum()),
                     "mean_abs_rank_change_base_top50": float((r["rank"] - r.rank_alt).abs().mean()),
                     "max_abs_rank_change_base_top50": int((r["rank"] - r.rank_alt).abs().max())}
    return out


def main():
    pv, ppred, pprof, prm = pitcher_values()
    hv = pd.read_parquet(DATA / "valuations.parquet")
    b = board(hv[(hv.fit == "final") & (hv.season == 2026)], pv[(pv.fit == "final") & (pv.season == 2026)])
    b.to_parquet(DATA / "board_2026.parquet", index=False)
    hfin = pd.read_parquet(DATA / "predictions_final.parquet").query("season == 2026")
    f = pd.read_parquet(DATA / "features.parquet")
    hpred = hfin.merge(f[["player_id", "season", "debut_year"]], on=["player_id", "season"], how="left").reset_index(drop=True)
    pfin = ppred[(ppred.fit == "final") & (ppred.season == 2026)].reset_index(drop=True)
    res = c19(hpred, war_profile(), pfin, pprof, prm, b)
    res["board"] = {"n": int(len(b)), "roles": b.role.value_counts().to_dict(), "top50_roles": b.head(50).role.value_counts().to_dict(),
                    "top100_roles": b.head(100).role.value_counts().to_dict()}
    json.dump(res, open(DATA / "b24_c19.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
