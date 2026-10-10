"""B29: MLB WAR projections 2027-2032 for the 2026 40-man population (v3 S33, C23).

Marcel rate (3 seasons, config.MARCEL_WEIGHTS, regressed to the league WAR rate) x flat playing time (config.PT_HIT / PT_PITCH),
with our own delta-method aging curves in place of Marcel's textbook ones. Two sides: hitters (PT = PA, owar) and pitchers
(PT = outs, pwar); a two-way player (>= config.TWO_WAY_MIN_PA PA and >= config.TWO_WAY_MIN_BF BF in the window) gets both, summed.
`project(hist, base_season)` only sees seasons <= base_season (curves included), so the C23 backtest has no leakage.
C23 (-> data/b29_c23.json): base seasons 2014-2024, project base+1, ours vs plain Marcel vs last-season WAR; no tuning on it.
"""
import json

import numpy as np
import pandas as pd

from . import config
from .common import DATA

BASE = 2026  # last complete season in the data
UNIT = {"hitter": 600, "pitcher": 450}  # aging deltas are WAR per 600 PA / 450 outs
GROUPS = ["hitter", "starter", "reliever"]
CURVE_FIRST, CURVE_LAST_AGE = 2006, 38  # curve pairs start at season 2006; ages bucket at <=23 and >=38
AGES = list(range(23, CURVE_LAST_AGE + 1))
C23_BASES = [b for b in range(2014, 2025) if b not in (2019, 2020)]
YEARS = [config.PROJ_FIRST + i for i in range(config.PROJ_YEARS)]


def load_hist():
    """Long table: player_id, season, kind (hitter/pitcher), war, pt, G, GS."""
    h = pd.read_parquet(DATA / "mlb_war.parquet").rename(columns={"owar": "war", "PA": "pt"})
    h = h.assign(kind="hitter", G=0, GS=0, BF=0)
    p = pd.read_parquet(DATA / "mlb_pitch_war.parquet").rename(columns={"pwar": "war", "outs": "pt"}).assign(kind="pitcher")
    c = ["player_id", "season", "kind", "war", "pt", "G", "GS", "BF"]
    return pd.concat([h[c], p[c]], ignore_index=True).dropna(subset=["war"])  # drops one 1-PA row (2018) with no owar


def load_birth():
    b = pd.concat([pd.read_parquet(DATA / f, columns=["player_id", "birth_date"]) for f in ("players.parquet", "pitch_players.parquet")])
    return b.dropna().drop_duplicates("player_id").set_index("player_id").birth_date


def age_on_july1(birth, ids, season):
    """Age (years, continuous) on July 1 of `season`, same convention as b4/b16."""
    july1 = pd.to_datetime(pd.Series(np.broadcast_to(season, len(ids))).astype(str) + "-07-01")
    return ((july1 - pd.Series(birth.reindex(ids).to_numpy())).dt.days / 365.25).to_numpy()


def _smooth(s):
    return s.rolling(3, center=True, min_periods=1).mean()


def fit_curves(hist, birth, last_season):
    """Delta-method aging curves {group: {age: change in WAR per UNIT PT from age to age+1}} from pairs (s, s+1) <= last_season."""
    out = {}
    for kind in ("hitter", "pitcher"):
        d = hist[(hist.kind == kind) & (hist.pt > 0)]
        a = d.assign(next=d.season + 1)
        pairs = a.merge(d, left_on=["player_id", "next"], right_on=["player_id", "season"], suffixes=("", "_n"))
        pairs = pairs[(pairs.season >= CURVE_FIRST) & (pairs.next <= last_season) & (pairs.season != 2020) & (pairs.next != 2020)]
        pairs = pairs.assign(age=age_on_july1(birth, pairs.player_id, pairs.season)).dropna(subset=["age"])
        pairs["delta"] = (pairs.war_n / pairs.pt_n - pairs.war / pairs.pt) * UNIT[kind]
        pairs["w"] = 2 / (1 / pairs.pt + 1 / pairs.pt_n)  # harmonic mean of the two PT
        pairs["bucket"] = np.floor(pairs.age).clip(AGES[0], AGES[-1]).astype(int)
        pairs["group"] = "hitter" if kind == "hitter" else np.where(pairs.GS / pairs.G > .5, "starter", "reliever")
        for g, x in pairs.groupby("group"):
            m = x.assign(dw=x.delta * x.w).groupby("bucket")[["dw", "w"]].sum()
            out[g] = _smooth((m.dw / m.w).reindex(AGES).interpolate(limit_direction="both")).to_dict()
    return out


def _cum_delta(curve, age, h):
    """Sum of the curve over ages floor(age) .. floor(age)+h-1 (age -> age+h)."""
    a = np.floor(age).astype(int)
    return sum(np.array([curve[min(max(x + i, AGES[0]), AGES[-1])] for x in a]) for i in range(h))


def project(hist, base_season, birth, n_years=config.PROJ_YEARS, curves=None):
    """One row per (player_id, kind) with PT > 0-or-any history <= base_season: age, starter, rate, pt_1..n, war_1..n (h = years ahead)."""
    hist = hist[hist.season <= base_season]
    curves = curves or fit_curves(hist, birth, base_season)
    seasons = [base_season - i for i in range(len(config.MARCEL_WEIGHTS))]
    w = dict(zip(seasons, config.MARCEL_WEIGHTS))
    rows = []
    for kind, reg, (pa, pb, *pc) in (("hitter", config.REGRESS_PA, config.PT_HIT), ("pitcher", config.REGRESS_OUTS, config.PT_PITCH)):
        d = hist[hist.kind == kind]
        win = d[d.season.isin(seasons)]
        m = win[win.pt > 0].war.sum() / win[win.pt > 0].pt.sum()  # league WAR per PT over the window
        win = win.assign(w=win.season.map(w))
        g = win.groupby("player_id")
        rate = (g.apply(lambda x: (x.w * x.war).sum(), include_groups=False) + reg * m) / \
               (g.apply(lambda x: (x.w * x.pt).sum(), include_groups=False) + reg)
        x = pd.DataFrame({"rate": rate, "G": g.G.sum(), "GS": g.GS.sum()})
        x["starter"] = (x.GS / x.G.replace(0, np.nan) > .5).fillna(False)
        last = d[d.season == base_season].set_index("player_id").pt.reindex(x.index).fillna(0)
        prev = d[d.season == base_season - 1].set_index("player_id").pt.reindex(x.index).fillna(0)
        base = pa * last + pb * prev + (np.where(x.starter, pc[1], pc[0]) if kind == "pitcher" else pc[0])
        x["pt_1"] = base
        x["age"] = age_on_july1(birth, x.index, base_season)
        x = x.dropna(subset=["age"])
        grp = np.where(x.starter, "starter", "reliever") if kind == "pitcher" else np.full(len(x), "hitter")
        for h in range(1, n_years + 1):
            cum = np.zeros(len(x))
            for gname in set(grp):
                s = grp == gname
                cum[s] = _cum_delta(curves[gname], x.age.to_numpy()[s], h)
            x[f"pt_{h}"] = base
            x[f"war_{h}"] = (x.rate + cum / UNIT[kind]) * base
        rows.append(x.reset_index().assign(kind=kind))
    return pd.concat(rows, ignore_index=True)


def marcel_war(p, h=1):
    """Plain Marcel, same rate and PT: textbook age factor on the rate, +.6%/yr per year under 29, -.3%/yr per year over."""
    age = np.floor(p.age) + h
    return p.rate * (1 + np.where(age < 29, .006, .003) * (29 - age)) * p[f"pt_{h}"]


def c23(hist, birth):
    """Backtest: next-season WAR for every player with base-season PT > 0, pooled over C23_BASES."""
    rows = []
    for b in C23_BASES:
        p = project(hist, b, birth, n_years=1)
        cur = hist[(hist.season == b) & (hist.pt > 0)][["player_id", "kind", "war"]].rename(columns={"war": "naive"})
        nxt = hist[hist.season == b + 1][["player_id", "kind", "war"]].rename(columns={"war": "actual"})
        p = p.merge(cur, on=["player_id", "kind"]).merge(nxt, on=["player_id", "kind"], how="left")
        p["actual"] = p.actual.fillna(0)
        p["marcel"] = marcel_war(p)
        rows.append(p.assign(base=b))
    d = pd.concat(rows).rename(columns={"war_1": "ours"})
    res = {"residual_sd_by_pt_tercile": {}}
    for kind, x in d.groupby("kind"):
        r = {m: {"r": float(np.corrcoef(x[m], x.actual)[0, 1]), "rmse": float(np.sqrt(((x[m] - x.actual) ** 2).mean()))}
             for m in ("ours", "marcel", "naive")}
        cuts = x.pt_1.quantile([1 / 3, 2 / 3]).tolist()
        t = np.searchsorted(cuts, x.pt_1)  # same rule B31 uses: 0 low, 1 mid, 2 high
        res["residual_sd_by_pt_tercile"][kind] = [float((v.actual - v.ours).std()) for _, v in x.groupby(t)]
        res["residual_sd_by_pt_tercile"][f"cuts_{kind}"] = cuts
        r["n"] = len(x)
        r["pass"] = bool(r["ours"]["r"] >= r["marcel"]["r"] and r["ours"]["rmse"] <= r["marcel"]["rmse"])
        res[kind] = r
    res["bases"] = C23_BASES
    return res


def main():
    hist, birth = load_hist(), load_birth()
    curves = fit_curves(hist, birth, BASE)
    json.dump({g: {str(a): round(v, 4) for a, v in c.items()} for g, c in curves.items()}, open(DATA / "b29_aging.json", "w"), indent=1)

    p = project(hist, BASE, birth, curves=curves)
    ids = pd.read_parquet(DATA / "mlb_contracts_2026.parquet").player_id.dropna().astype(int).unique()
    p = p[p.player_id.isin(ids)]
    # side(s) per player: both if past the two-way thresholds over the window, else the side with more PA / BF
    win = hist[hist.season > BASE - len(config.MARCEL_WEIGHTS)].groupby(["player_id", "kind"])[["pt", "BF"]].sum().unstack(fill_value=0)
    pa, bf = win[("pt", "hitter")], win[("BF", "pitcher")]
    two = (pa >= config.TWO_WAY_MIN_PA) & (bf >= config.TWO_WAY_MIN_BF)
    side = pd.Series(np.where(bf > pa, "pitcher", "hitter"), index=win.index)
    ever = hist.groupby(["player_id", "kind"]).pt.sum().unstack(fill_value=0)  # no MLB window at all: use career side
    side = side.reindex(ids).fillna(pd.Series(np.where(ever.pitcher / 3 > ever.hitter, "pitcher", "hitter"), index=ever.index).reindex(ids))
    two = two.reindex(ids, fill_value=False)
    keep = np.where(two.to_numpy(), "both", side.to_numpy())
    want = pd.Series(keep, index=ids)
    p = p[(want.reindex(p.player_id).to_numpy() == "both") | (want.reindex(p.player_id).to_numpy() == p.kind.to_numpy())]

    out = pd.DataFrame({"player_id": ids}).set_index("player_id")
    hit, pit = p[p.kind == "hitter"].set_index("player_id"), p[p.kind == "pitcher"].set_index("player_id")
    out["kind"] = np.where(two.reindex(out.index), "two_way", want.reindex(out.index))
    out["age_2026"] = age_on_july1(birth, out.index, BASE)
    out["starter"] = pit.starter.reindex(out.index).fillna(False).astype(bool)
    for h, y in enumerate(YEARS, 1):
        out[f"war_{y}"] = hit[f"war_{h}"].reindex(out.index).fillna(0) + pit[f"war_{h}"].reindex(out.index).fillna(0)
        out[f"pa_{y}"] = hit[f"pt_{h}"].reindex(out.index).fillna(0)  # extra: both sides' PT, so a two-way player keeps PA and outs
        out[f"outs_{y}"] = pit[f"pt_{h}"].reindex(out.index).fillna(0)
        out[f"pt_{y}"] = np.where(out.kind == "pitcher", out[f"outs_{y}"], out[f"pa_{y}"])
    out.reset_index().to_parquet(DATA / "mlb_projections.parquet", index=False)

    res = c23(hist, birth)
    json.dump(res, open(DATA / "b29_c23.json", "w"), indent=1)
    print(f"{len(out)} players ({out.kind.value_counts().to_dict()}); C23 pass: hitter {res['hitter']['pass']}, pitcher {res['pitcher']['pass']}")


if __name__ == "__main__":
    main()
