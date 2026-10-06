"""B3 park factors (spec S5 park part, Q8, D2). Deviation: source is MLB Stats API team home/road splits
(statSplits sitCodes h/a, team hitting + pitching-allowed), not PBP, because repo PBP ends May 2025 (see handoff).

Outputs (data/): park_factors.parquet (sport x season x team), milb_player_park.parquet (player x season x level x league).
Factor per component = rate in team's home games / rate in road games (hitting + pitching-allowed pooled),
normalised to PA-weighted mean 1 within league-season, pooled over season-1..+1 at same league+venue,
shrunk to 1 by n/(n+k).
"""
import numpy as np
import pandas as pd

from pipeline.common import DATA, api_get, pmap

SPORTS = {11: "aaa", 12: "aa", 13: "a+", 14: "a", 15: "a-", 16: "rk", 1: "mlb"}
YEARS = range(2005, 2027)
SUMS = ["PA", "AB", "H", "2B", "3B", "HR", "BB", "IBB", "HBP", "SO", "SF", "R"]
KEY = {"plateAppearances": "PA", "battersFaced": "PA", "atBats": "AB", "hits": "H", "doubles": "2B",
       "triples": "3B", "homeRuns": "HR", "baseOnBalls": "BB", "intentionalWalks": "IBB",
       "hitByPitch": "HBP", "strikeOuts": "SO", "sacFlies": "SF", "runs": "R"}
# component -> (numerator, denominator) on a frame of event sums
COMPS = {
    "1B": (lambda d: d.H - d["2B"] - d["3B"] - d.HR, lambda d: d.PA),
    "2B3B": (lambda d: d["2B"] + d["3B"], lambda d: d.PA),
    "HR": (lambda d: d.HR, lambda d: d.PA),
    "BB": (lambda d: d.BB - d.IBB + d.HBP, lambda d: d.PA),  # uBB + HBP
    "SO": (lambda d: d.SO, lambda d: d.PA),
    "BABIP": (lambda d: d.H - d.HR, lambda d: d.AB - d.SO - d.HR + d.SF),
    "R": (lambda d: d.R, lambda d: d.PA),
}


def _fetch(args):
    sport, season, group, sit = args
    d = api_get("teams/stats", stats="statSplits", sitCodes=sit, group=group, season=season,
                sportId=sport, gameType="R", limit=500)
    rows = []
    for s in (d["stats"][0]["splits"] if d["stats"] else []):
        r = {"sport_id": sport, "season": season, "team_id": s["team"]["id"], "side": sit}
        r.update({v: s["stat"].get(k) for k, v in KEY.items() if k in s["stat"]})
        rows.append(r)
    return rows


def _exists(sp, y):
    """No MiLB in 2020; short-season A (sportId 15) ends 2019."""
    return not (sp != 1 and y == 2020) and not (sp == 15 and y > 2019)


def team_splits():
    """One row per sport x season x team with home (_h) and road (_r) event sums, hitting + pitching-allowed."""
    jobs = [(sp, y, g, s) for sp in SPORTS for y in YEARS for g in ("hitting", "pitching") for s in ("h", "a")
            if _exists(sp, y)]
    rows = [r for rs in pmap(_fetch, jobs) for r in rs]
    d = pd.DataFrame(rows).fillna(0)
    g = d.groupby(["sport_id", "season", "team_id", "side"])[SUMS].sum().unstack("side")
    g.columns = [f"{c}_{'h' if s == 'h' else 'r'}" for c, s in g.columns]
    return g.reset_index()


def team_info():
    def one(a):
        sp, y = a
        return [{"sport_id": sp, "season": y, "team_id": t["id"], "venue_id": (t.get("venue") or {}).get("id"),
                 "league_id": (t.get("league") or {}).get("id")} for t in api_get("teams", sportId=sp, season=y)["teams"]]
    rows = [r for rs in pmap(one, [(sp, y) for sp in SPORTS for y in YEARS if _exists(sp, y)]) for r in rs]
    return pd.DataFrame(rows).drop_duplicates(["sport_id", "season", "team_id"])


def raw_factors(d):
    """Add num/den per side and raw_<comp> (home rate / road rate), normalised in league-season."""
    for c, (num, den) in COMPS.items():
        h = d[[f"{s}_h" for s in SUMS]].set_axis(SUMS, axis=1)
        r = d[[f"{s}_r" for s in SUMS]].set_axis(SUMS, axis=1)
        dh, dr = den(h), den(r)
        d[f"dh_{c}"], d[f"dr_{c}"] = dh, dr
        rate_h, rate_r = num(h) / dh.where(dh > 0), num(r) / dr.where(dr > 0)
        raw = rate_h / rate_r.where(rate_r > 0)
        w = (dh + dr).where(raw.notna(), 0)
        key = [d.sport_id, d.season, d.league_id]
        mean = (raw * w).groupby(key).transform("sum") / w.groupby(key).transform("sum")
        d[f"raw_{c}"] = raw / mean
        d[f"n_{c}"] = dh * dr / (dh + dr).where(dh + dr > 0)  # effective sample of a home-minus-road difference
    return d


def neighbors(d):
    """Pairs of the same team within one season of each other (MiLB 2019 and 2021 count as adjacent),
    same league and venue; a venue or league change breaks the window."""
    a = d[["sport_id", "team_id", "season", "league_id", "venue_id"]].copy()
    a["idx"] = a.season - ((a.sport_id != 1) & (a.season >= 2021))
    m = a.merge(a, on=["sport_id", "team_id", "league_id", "venue_id"], suffixes=("", "_o"))
    return m[(m.idx - m.idx_o).abs() <= 1]


def choose_k(d):
    """k per component so n/(n+k) equals the year-to-year correlation of raw factors (MiLB A-AAA, adjacent seasons)."""
    d = d[d.sport_id.isin([11, 12, 13, 14])]
    x = d.set_index(["team_id", "season"])
    p = neighbors(d)
    p = p[p.idx_o == p.idx + 1]
    ks = {}
    for c in COMPS:
        a = x[f"raw_{c}"].reindex(pd.MultiIndex.from_arrays([p.team_id, p.season])).to_numpy()
        b = x[f"raw_{c}"].reindex(pd.MultiIndex.from_arrays([p.team_id, p.season_o])).to_numpy()
        ok = ~(np.isnan(a) | np.isnan(b))
        r_raw = float(np.corrcoef(a[ok], b[ok])[0, 1])
        r = min(max(r_raw, 0.05), 0.95)  # floor: components with ~no signal get heavy shrinkage
        n1 = x[f"n_{c}"].mean()
        ks[c] = dict(k=float(n1 * (1 - r) / r), r_yy=r_raw, n_mean=float(n1))
    return ks


def regress(d, ks):
    cols = [f"{t}_{c}" for c in COMPS for t in ("raw", "n")]
    p = neighbors(d).merge(d[["sport_id", "team_id", "season"] + cols].rename(columns={"season": "season_o"}),
                           on=["sport_id", "team_id", "season_o"])
    keys = ["sport_id", "team_id", "season"]
    out = d.set_index(keys)
    for c in COMPS:
        raw, n = p[f"raw_{c}"], p[f"n_{c}"].where(p[f"raw_{c}"].notna(), 0)
        s = pd.DataFrame({"w": n, "wr": n * raw.fillna(0)}).groupby([p[k] for k in keys]).sum()
        comb = (s.wr / s.w.where(s.w > 0)).fillna(1.0)
        pf = (1 + (comb - 1) * s.w / (s.w + ks[c]["k"])).reindex(out.index)
        # pooling across seasons drifts the league mean; renormalise to PA-weighted mean 1 per league-season
        wt = (out.PA_home + out.PA_road).where(pf.notna(), 0)
        g = [out.league_id, out.index.get_level_values("season"), out.index.get_level_values("sport_id")]
        out[f"pf_{c}"] = pf / ((pf * wt).groupby(g).transform("sum") / wt.groupby(g).transform("sum"))
    return out.reset_index()


def build():
    d = team_splits().merge(team_info(), on=["sport_id", "season", "team_id"], how="left")
    d = d[d.league_id.notna()].reset_index(drop=True)
    d["sport"] = np.where(d.sport_id == 1, "mlb", "milb")
    d["level"] = d.sport_id.map(SPORTS)
    d["PA_home"], d["PA_road"] = d.PA_h, d.PA_r
    d["method"] = "api"
    d = raw_factors(d)
    ks = choose_k(d)
    d = regress(d, ks)
    return d, ks


def player_park(pf):
    """Per-stint factor (1+pf)/2 (about half of games at home), PA-weighted to player x season x level x league."""
    st = pd.read_parquet(DATA / "milb_stints.parquet")
    st = st.merge(pf[pf.sport == "milb"][["season", "team_id"] + [f"pf_{c}" for c in COMPS]], on=["season", "team_id"], how="left")
    has = st.pf_HR.notna()
    st["pa"] = st.PA.fillna(0)
    st["w"] = (st.pa + 1e-6).where(has, 0)  # tiny floor so zero-PA stints still get a factor
    st["pa_has"] = st.pa.where(has, 0)
    for c in COMPS:
        st[f"ppf_{c}"] = (1 + st[f"pf_{c}"].fillna(1)) / 2 * st.w
    g = st.groupby(["player_id", "season", "level", "league_id"])
    s = g[[f"ppf_{c}" for c in COMPS] + ["w", "pa", "pa_has"]].sum()
    out = s[[f"ppf_{c}" for c in COMPS]].div(s.w.where(s.w > 0), axis=0)
    out["share_PA_with_factor"] = (s.pa_has / s.pa.where(s.pa > 0)).fillna((s.w > 0).astype(float))
    return out.reset_index()


def main():
    pf, ks = build()
    cols = (["sport", "season", "team_id", "level", "league_id", "venue_id", "method", "PA_home", "PA_road"]
            + [f"raw_{c}" for c in COMPS] + [f"pf_{c}" for c in COMPS])
    pf[cols].to_parquet(DATA / "park_factors.parquet", index=False)
    for c, v in ks.items():
        print(f"k {c}: {v}")
    pp = player_park(pf)
    pp.to_parquet(DATA / "milb_player_park.parquet", index=False)
    (DATA / "b3_k.json").write_text(__import__("json").dumps(ks, indent=1))
    print(f"park_factors {len(pf)} rows, milb_player_park {len(pp)} rows")
