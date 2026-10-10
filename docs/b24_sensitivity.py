"""B24 sensitivity (not part of the pipeline): does season-centering the pitcher rate/role features (B22 audit) or an OOF
linear WAR recalibration put pitchers on the combined 2026 board? Run: PYTHONPATH=. .venv/bin/python docs/b24_sensitivity.py
"""
import json, numpy as np, pandas as pd
import pipeline.b22_pitch_models as b22
from pipeline import b6_models as b6
from pipeline.b8_value import load_params, value, war_profile
from pipeline.b24_pitch_value import board
from pipeline.common import DATA
CENTER = [c for c in b22.pitch_X(pd.read_parquet(DATA/"pitch_features.parquet").head(2)).columns
          if c.startswith(("blend_reg_", "delta_reg_", "blend_GS", "blend_outs", "blend_pitches"))]
f = pd.read_parquet(DATA/"pitch_features.parquet")
f, _ = b22.contact_adjust(f)
def center(f):
    st = f.group == "stat"
    base = f[st & (f.season <= 2012)][CENTER].mean()
    f = f.copy(); f.loc[st, CENTER] = f.loc[st, CENTER] - f[st].groupby("season")[CENTER].transform("mean") + base
    return f
cfg = {"hazard": {"chosen": "linear", "n": 0}, "war": {"chosen": "linear", "n": 0}}
WT = "pitch_war_target.parquet"
def run(ff, recal):
    st = ff[ff.group == "stat"]
    mod = b6.fit(st[st.season <= 2025], cfg, "pitch_stat", 2014, "lightgbm", WT)
    tg = st[st.season == 2026]
    p = b6.predict(mod, tg)
    if recal:  # OOF linear recalibration of WAR level on s<=2012 reached rows (CV only)
        d = st[st.season <= 2012].reset_index(drop=True); m = b6._war_mask(d, 2012, WT)
        X = b6.XFN["pitch_stat"](d)[m].reset_index(drop=True); y = d.war_6yr.to_numpy()[m]
        oof = b6._oof(lambda: b6._linear("war"), X, y, d.player_id.to_numpy()[m], "war")
        b, a = np.polyfit(oof, y, 1); print("recal slope", round(b, 2), "intercept", round(a, 2))
        p["war_mean"] = a + b * p.war_mean; p["war_scale"] = p.war_scale * b
    p = pd.concat([tg[["player_id", "season", "group", "debut_year"]].reset_index(drop=True), p.reset_index(drop=True)], axis=1).assign(fit="final")
    return p
pv_ship = pd.read_parquet(DATA/"pitch_valuations.parquet").query("fit=='final' and season==2026")
hv = pd.read_parquet(DATA/"valuations.parquet").query("fit=='final' and season==2026")
prior = pv_ship[pv_ship.group == "prior"]
prm, prof = load_params(), war_profile("pitch_war_target.parquet", "mlb_pitch_war.parquet", "pwar")
out = {}
for name, ff, rc in (("center", center(f), False), ("center+recal", center(f), True), ("recal_only", f, True)):
    p = run(ff, rc); v = value(p.reset_index(drop=True), prof, prm, prefix="pitch_")
    b = board(hv, pd.concat([v, prior], ignore_index=True))
    out[name] = {"top50_P": int((b.head(50).role == "P").sum()), "top100_P": int((b.head(100).role == "P").sum()),
                 "top_pitcher_war_mean": round(float(p.war_mean.max()), 2), "median_stat_war_mean": round(float(p.war_mean.median()), 2)}
    print(name, out[name], flush=True)
json.dump(out, open(DATA/"b24_sensitivity.json", "w"), indent=1)
