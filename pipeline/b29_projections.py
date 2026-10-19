"""B29: MLB WAR projections 2027-2032 for the 2026 40-man population (v3 S33, C23).

Marcel rate (3 seasons, config.MARCEL_WEIGHTS, regressed to the league WAR rate) x flat playing time (config.PT_HIT / PT_PITCH),
plus our own age adjustment in place of Marcel's textbook one. Two sides: hitters (PT = PA, owar) and pitchers
(PT = outs, pwar); a two-way player (>= config.TWO_WAY_MIN_PA PA and >= config.TWO_WAY_MIN_BF BF in the window) gets both, summed.
Age adjustment (audit 2026-10-19): per horizon h and base-season age, the PT-weighted mean of actual WAR rate in b+h minus
the Marcel rate at b, over past bases b. Measured against the already-regressed Marcel rate, so regression to the mean is
not counted twice (the old season-to-season delta curve was, and its sum went to -2.8 WAR/600 PA from 26 to 32), and fit
per h, so nothing is summed. It is a rate given the player plays in b+h; playing-time attrition is not modeled (flat PT).
`project(hist, base_season)` only sees seasons <= base_season (adjustments included), so the C23 backtest has no leakage.
C23 (-> data/b29_c23.json): base seasons 2014-2025, every horizon h = 1..6 observed by 2026; ours vs plain Marcel vs
last-season WAR at h = 1; rate bias at every h is gated (config.C23_MAX_RATE_BIAS); no tuning on it.
"""
import json

import numpy as np
import pandas as pd

from . import config
from .common import DATA

BASE = 2026  # last complete season in the data
UNIT = {"hitter": 600, "pitcher": 450}  # age adjustments are WAR per 600 PA / 450 outs
GROUPS = ["hitter", "starter", "reliever"]
CURVE_FIRST, CURVE_LAST_AGE = 2007, 38  # first base season with a full 3-season window (data start 2005); ages bucket at <=23 and >=38
AGES = list(range(23, CURVE_LAST_AGE + 1))
C23_BASES = [b for b in range(2014, 2025) if b not in (2019, 2020)]  # h = 1 comparison (unchanged)
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


def marcel(hist, base_season, birth):
    """Marcel rate per (player_id, kind) from the window ending at base_season: rate, starter, group, age, pt_1 (projected PT)."""
    seasons = [base_season - i for i in range(len(config.MARCEL_WEIGHTS))]
    w = dict(zip(seasons, config.MARCEL_WEIGHTS))
    rows = []
    for kind, reg, (pa, pb, *pc) in (("hitter", config.REGRESS_PA, config.PT_HIT), ("pitcher", config.REGRESS_OUTS, config.PT_PITCH)):
        d = hist[(hist.kind == kind) & (hist.season <= base_season)]
        win = d[d.season.isin(seasons)]
        m = win[win.pt > 0].war.sum() / win[win.pt > 0].pt.sum()  # league WAR per PT over the window
        win = win.assign(ww=win.season.map(w) * win.war, wp=win.season.map(w) * win.pt)
        x = win.groupby("player_id")[["ww", "wp", "G", "GS"]].sum()
        x["rate"] = (x.ww + reg * m) / (x.wp + reg)
        x["starter"] = (x.GS / x.G.replace(0, np.nan) > .5).fillna(False)
        last = d[d.season == base_season].set_index("player_id").pt.reindex(x.index).fillna(0)
        prev = d[d.season == base_season - 1].set_index("player_id").pt.reindex(x.index).fillna(0)
        x["pt_1"] = pa * last + pb * prev + (np.where(x.starter, pc[1], pc[0]) if kind == "pitcher" else pc[0])
        x["age"] = age_on_july1(birth, x.index, base_season)
        x["group"] = np.where(x.starter, "starter", "reliever") if kind == "pitcher" else "hitter"
        rows.append(x.drop(columns=["ww", "wp"]).dropna(subset=["age"]).reset_index().assign(kind=kind))
    return pd.concat(rows, ignore_index=True)


def fit_curves(hist, birth, last_season, n_years=config.PROJ_YEARS, mt=None):
    """Age adjustments {group: {h: {age: WAR per UNIT PT}}}: PT-weighted mean of (actual rate in b+h - Marcel rate at b) by
    floor(age at b), over bases b >= CURVE_FIRST with b + h <= last_season (2020 skipped as base or target).
    `mt`: optional {base: marcel(...)} cache (each table only sees seasons <= its base)."""
    mt = mt if mt is not None else {}
    act = hist[hist.pt > 0][["player_id", "kind", "season", "war", "pt"]]
    pairs = []
    for b in range(CURVE_FIRST, last_season):
        if b == 2020:
            continue
        if b not in mt:
            mt[b] = marcel(hist, b, birth)
        played = act[act.season == b][["player_id", "kind"]]
        base = mt[b].merge(played, on=["player_id", "kind"])
        for h in range(1, n_years + 1):
            if b + h > last_season or b + h == 2020:
                continue
            a = act[act.season == b + h]
            x = base.merge(a, on=["player_id", "kind"])
            pairs.append(pd.DataFrame({"group": x.group, "h": h, "w": x.pt, "age": x.age,
                                       "resid": (x.war / x.pt - x.rate) * x.kind.map(UNIT)}))
    p = pd.concat(pairs, ignore_index=True)
    p["bucket"] = np.floor(p.age).clip(AGES[0], AGES[-1]).astype(int)
    p["rw"] = p.resid * p.w
    s = p.groupby(["group", "h", "bucket"])[["rw", "w"]].sum()
    out = {}
    for (g, h), x in (s.rw / s.w).groupby(level=[0, 1]):
        out.setdefault(g, {})[h] = _smooth(x.droplevel([0, 1]).reindex(AGES).interpolate(limit_direction="both")).to_dict()
    return out


def _adj(curve, age):
    return np.array([curve[min(max(int(a), AGES[0]), AGES[-1])] for a in np.floor(age)])


def project(hist, base_season, birth, n_years=config.PROJ_YEARS, curves=None, mt=None):
    """One row per (player_id, kind) with history in the Marcel window: age, starter, rate, pt_1..n, war_1..n (h = years ahead)."""
    hist = hist[hist.season <= base_season]
    curves = curves or fit_curves(hist, birth, base_season, n_years, mt)
    x = marcel(hist, base_season, birth)
    for h in range(1, n_years + 1):
        adj = np.zeros(len(x))
        for g in x.group.unique():
            s = (x.group == g).to_numpy()
            adj[s] = _adj(curves[g][h], x.age.to_numpy()[s])
        x[f"pt_{h}"] = x.pt_1
        x[f"war_{h}"] = (x.rate + adj / x.kind.map(UNIT)) * x.pt_1
    return x


def marcel_war(p, h=1):
    """Plain Marcel, same rate and PT: textbook age factor on the rate, +.6%/yr per year under 29, -.3%/yr per year over."""
    age = np.floor(p.age) + h
    return p.rate * (1 + np.where(age < 29, .006, .003) * (29 - age)) * p[f"pt_{h}"]


def c23(hist, birth):
    """Backtest, every base b in 2014-2025 (not 2020) and horizon h with b + h <= 2026 (target 2020 skipped), for players with
    base-season PT > 0. h = 1 (C23_BASES): r / RMSE of ours vs plain Marcel vs last-season WAR. Every h: rate bias among
    players who play in b + h (PT-weighted mean of projected minus actual rate, WAR per 600 PA / 450 outs; the gate) and
    total-WAR bias per player (0 if absent; reported, not gated: flat PT has no attrition)."""
    n = config.PROJ_YEARS
    mt, rows = {}, []
    for b in [b for b in range(2014, BASE) if b != 2020]:
        p = project(hist, b, birth, n_years=n, mt=mt)
        cur = hist[(hist.season == b) & (hist.pt > 0)][["player_id", "kind", "war"]].rename(columns={"war": "naive"})
        p = p.merge(cur, on=["player_id", "kind"])
        for h in range(1, n + 1):
            if b + h > BASE or b + h == 2020:
                continue
            a = hist[hist.season == b + h][["player_id", "kind", "war", "pt"]].rename(columns={"war": "actual", "pt": "actual_pt"})
            x = p.merge(a, on=["player_id", "kind"], how="left").fillna({"actual": 0, "actual_pt": 0})
            rows.append(pd.DataFrame({"base": b, "h": h, "kind": x.kind, "pt_1": x.pt_1, "naive": x.naive, "actual": x.actual,
                                      "actual_pt": x.actual_pt, "ours": x[f"war_{h}"], "marcel": marcel_war(x, h)}))
    d = pd.concat(rows, ignore_index=True)
    res = {"residual_sd_by_pt_tercile": {}, "bias_by_h": {}}
    for kind, x in d[(d.h == 1) & d.base.isin(C23_BASES)].groupby("kind"):
        r = {m: {"r": float(np.corrcoef(x[m], x.actual)[0, 1]), "rmse": float(np.sqrt(((x[m] - x.actual) ** 2).mean()))}
             for m in ("ours", "marcel", "naive")}
        cuts = x.pt_1.quantile([1 / 3, 2 / 3]).tolist()
        t = np.searchsorted(cuts, x.pt_1)  # same rule B31 uses: 0 low, 1 mid, 2 high
        res["residual_sd_by_pt_tercile"][kind] = [float((v.actual - v.ours).std()) for _, v in x.groupby(t)]
        res["residual_sd_by_pt_tercile"][f"cuts_{kind}"] = cuts
        r["n"] = len(x)
        r["h1_pass"] = bool(r["ours"]["r"] >= r["marcel"]["r"] and r["ours"]["rmse"] <= r["marcel"]["rmse"])
        res[kind] = r
    for kind, x in d.groupby("kind"):
        u, bias = UNIT[kind], {}
        for h, v in x.groupby("h"):
            pl = v[v.actual_pt > 0]
            rate_bias = lambda m: float(((pl[m] / pl.pt_1 * pl.actual_pt).sum() - pl.actual.sum()) / pl.actual_pt.sum() * u)  # noqa: E731
            bias[int(h)] = {"n": len(v), "n_played": len(pl), "bases": sorted(int(b) for b in v.base.unique()),
                            "rate_bias": {m: rate_bias(m) for m in ("ours", "marcel")},
                            "mean_war": {m: float(v[m].mean()) for m in ("ours", "marcel", "actual")}}
        res["bias_by_h"][kind] = bias
        res[kind]["bias_pass"] = bool(all(abs(b["rate_bias"]["ours"]) <= config.C23_MAX_RATE_BIAS for b in bias.values()))
        res[kind]["pass"] = res[kind]["h1_pass"] and res[kind]["bias_pass"]
    res["bases"] = C23_BASES
    res["max_rate_bias"] = config.C23_MAX_RATE_BIAS
    return res


def main():
    hist, birth = load_hist(), load_birth()
    curves = fit_curves(hist, birth, BASE)
    json.dump({g: {str(h): {str(a): round(v, 4) for a, v in c.items()} for h, c in hc.items()} for g, hc in curves.items()},
              open(DATA / "b29_aging.json", "w"), indent=1)

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
