"""B21: Savant pitch tracking for pitchers (D17, S27, S28, C17).

Savant minors CSVs mix every tracked level (AAA 2023+, Florida State League 2021+), so these are "tracked games" only.
Arsenal (D17, S27) is display only, never a model feature -> data/pitch_arsenal.parquet.
Contact adjustment (S28): xwOBA on contact allowed (xwOBAcon) blended into the AAA XB/BIP contact term -> data/pitch_contact.parquet.
C17 asks whether the blend predicts next-season AAA ISO on contact better than observed XB alone, with a no-tracking shrinkage
control (C) so a gain from shrinking toward the league mean is not credited to tracking -> data/b21_c17.json.
xb_contact_adj = f(xwOBAcon) on the XB/BIP scale (xwOBA only when tracked, Jack's call after C17); B22 rescales reg_XB with it.
"""
import json
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from .b5_features import MEXICAN_LEAGUE
from .b9_site import PITCH_FAMILY, SAVANT_SPLITS, savant_family
from .b11_batted import BBT
from . import config
from .common import DATA, _get

ARSENAL_SEASONS = range(2021, 2027)
CONTACT_SEASONS = range(2022, 2027)
K_GRID = [50, 100, 200, 400, 800]
AAA_SHARE, MIN_BIP = 0.8, 100


def arsenal():
    """One row per pitcher x season x pitch code (FF, SI, SL, ...), so a four-seam and a sinker keep their own shapes."""
    codes = {c: fam for fam, cs in PITCH_FAMILY.items() for c in cs.split("|")}
    d = pd.concat([savant_family(y, c, "pitcher").assign(pitch_type=c, family=fam)
                   for y in ARSENAL_SEASONS for c, fam in codes.items()], ignore_index=True)
    d["usage"] = d.pitches / d.total_pitches
    d["whiff"] = d.whiffs / d.swings.where(d.swings > 0)
    # Savant movement is in feet; cards show inches. HB is arm-side positive (api_break_x_arm), IVB is gravity-removed
    d["ivb"] = pd.to_numeric(d.api_break_z_induced, errors="coerce") * 12
    d["hb"] = pd.to_numeric(d.api_break_x_arm, errors="coerce") * 12
    cols = ["player_id", "season", "pitch_type", "family", "pitches", "usage", "velocity", "spin_rate", "release_extension", "ivb", "hb", "whiff"]
    return d.loc[d.pitches > 0, cols].reset_index(drop=True)


def savant_contact(season):
    """Tracked pitcher rows on balls in play only (all pitch types), grouped by pitcher; cached CSV."""
    f = SAVANT_SPLITS / f"p_{season}_contact.csv"
    if not f.exists():
        url = (f"https://baseballsavant.mlb.com/statcast-search-minors/csv?all=true&hfGT=R%7C&hfSea={season}%7C&player_type=pitcher"
               f"&group_by=name&minors=true&min_pitches=0&min_results=0&min_pas=0&sort_col=pitches&sort_order=desc&hfBBT={BBT}")
        SAVANT_SPLITS.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_get(url).content)
        time.sleep(0.2)
    d = pd.read_csv(f, encoding="utf-8-sig")
    assert len(d) < 25000, f"Savant row cap hit on {f.name}"
    return d[["player_id", "xwoba", "bip"]].assign(season=season)


def aaa_contact():
    """Per pitcher-season, AAA only: XB/BIP (the B18 definition), BIP, and ISO on contact; plus AAA's share of affiliated BF."""
    s = pd.read_parquet(DATA / "milb_pitching_seasons.parquet")
    s = s[s.league_id != MEXICAN_LEAGUE].copy()
    s["is_aaa"] = s.level == "aaa"
    s["BF_aaa"] = s.BF.where(s.is_aaa, 0)
    a = s[s.is_aaa].copy()
    a["BIP"] = a.BF - a.SO - a.BB - a.HBP - a.HR
    a["xb_n"], a["iso_n"], a["iso_d"] = a["2B"] + 2 * a["3B"], a["2B"] + 2 * a["3B"] + 3 * a.HR, a.AB - a.SO + a.SF
    g = a.groupby(["player_id", "season"])[["BIP", "xb_n", "iso_n", "iso_d"]].sum()
    g["XB"], g["iso_con"] = g.xb_n / g.BIP.where(g.BIP > 0), g.iso_n / g.iso_d.where(g.iso_d > 0)
    share = s.groupby(["player_id", "season"]).BF_aaa.sum() / s.groupby(["player_id", "season"]).BF.sum()
    return g.join(share.rename("aaa_share")).reset_index()


def wfit(x, y, w):
    """Weighted least squares y ~ a + b x -> (a, b)."""
    b, a = np.polyfit(x, y, 1, w=np.sqrt(w))
    return a, b


def wrmse(y, p, w):
    return float(np.sqrt(np.average((y - p) ** 2, weights=w)))


def blend(xb, bip, x, f, k, prior=None):
    """w * observed XB + (1 - w) * prior; prior is f(xwOBAcon) unless a constant is passed (control C)."""
    w = bip / (bip + k)
    return w * xb + (1 - w) * (f[0] + f[1] * x if prior is None else prior)


def fit_blend(d, kind):
    """Pick k from the grid by in-sample weighted RMSE after a linear calibration (1 parameter + 2 calibration terms);
    returns (k, f, calibration) for predictor 'B' (tracking blend) or 'C' (league-mean shrinkage control)."""
    f = wfit(d.xwoba, d.XB, d.BIP)
    mean = np.average(d.XB, weights=d.BIP)
    best = None
    for k in K_GRID:
        p = blend(d.XB, d.BIP, d.xwoba, f, k, None if kind == "B" else mean)
        cal = wfit(p, d.target, d.target_w)
        e = wrmse(d.target, cal[0] + cal[1] * p, d.target_w)
        if best is None or e < best[0]:
            best = (e, k, cal)
    return best[1], f, best[2], mean


def predict(d, kind, k, f, cal, mean):
    p = blend(d.XB, d.BIP, d.xwoba, f, k, None if kind == "B" else mean)
    return cal[0] + cal[1] * p


def c17(contact):
    a = aaa_contact()
    a = a[(a.aaa_share >= AAA_SHARE) & (a.BIP >= MIN_BIP)]
    nxt = a.assign(season=a.season - 1)[["player_id", "season", "iso_con", "iso_d"]].rename(columns={"iso_con": "target", "iso_d": "target_w"})
    d = a.merge(nxt, on=["player_id", "season"]).merge(contact[["player_id", "season", "xwoba"]], on=["player_id", "season"])
    d = d[d.season.isin([2023, 2024])].reset_index(drop=True)
    oof = {k: np.full(len(d), np.nan) for k in "ABCD"}
    for tr, te in GroupKFold(5).split(d, groups=d.player_id):
        t, v = d.iloc[tr], d.iloc[te]
        cal = wfit(t.XB, t.target, t.target_w)  # A: observed XB alone
        oof["A"][te] = cal[0] + cal[1] * v.XB
        for kind in "BC":
            oof[kind][te] = predict(v, kind, *fit_blend(t, kind))
        cal = wfit(t.xwoba, t.target, t.target_w)  # D: xwOBAcon alone (no box-score XB)
        oof["D"][te] = cal[0] + cal[1] * v.xwoba
    r = {k: wrmse(d.target, oof[k], d.target_w) for k in "ABCD"}
    k, f, cal, mean = fit_blend(d, "B")
    out = dict(n=len(d), n_players=int(d.player_id.nunique()), rmse_observed=r["A"], rmse_blended=r["B"], rmse_shrunk_control=r["C"], rmse_xwoba_only=r["D"],
               k_blend=k, f_intercept=f[0], f_slope=f[1], k_control=fit_blend(d, "C")[0],
               **{"pass": bool(r["B"] < r["A"])}, blend_beats_control=bool(r["B"] < r["C"]))
    return out, (k, f)


def main():
    ar = arsenal()
    ar.to_parquet(DATA / "pitch_arsenal.parquet", index=False)
    contact = pd.concat([savant_contact(y) for y in CONTACT_SEASONS], ignore_index=True)
    contact = contact[contact.xwoba.notna()].reset_index(drop=True)
    res, (k, f) = c17(contact)
    a = aaa_contact()
    contact = contact.merge(a[["player_id", "season", "XB", "BIP"]], on=["player_id", "season"], how="left")
    # Jack, 2026-10-10: with tracking, use xwOBAcon alone (D ties the blend B on C17; box-score XB adds nothing once xwOBAcon is known)
    contact["xb_contact_adj"] = (f[0] + f[1] * contact.xwoba if config.CONTACT_XWOBA_ONLY
                                 else blend(contact.XB.fillna(0), contact.BIP.fillna(0), contact.xwoba, f, k))  # no AAA BIP -> pure f(xwOBAcon)
    contact[["player_id", "season", "xwoba", "bip", "xb_contact_adj"]].to_parquet(DATA / "pitch_contact.parquet", index=False)
    (DATA / "b21_c17.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
