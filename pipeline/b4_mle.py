"""B4: MiLB -> MLB-equivalent K%, BB%, ISO, BABIP (S5 translation part, S6, A5).

Method (see docs/handoff.md B4 for the full write-up):
 1. Park-neutralize every A..AAA (affiliated, non-pitcher) rate by its player park factor; MLB by half-home team pf.
 2. Same-season matched pairs (>=50 PA at both adjacent levels), pair weight = harmonic mean of PAs,
    raw factor = sum(w*upper_rate)/sum(w*lower_rate) per league-season and component.
 3. Shrink league-season -> level-season -> level-all with k from adjacent-season reliability.
 4. Chain league factor x level-season factors of every higher level through aaa->mlb.
 5. Regress by sample size toward the level-season PA-weighted MLE mean (S6).
 6. Roll up to player-season.
Pooled rows: league_id = -1 (level-season, all leagues); season = 0 and league_id = -1 (level-all, all years).
"""
import json

import numpy as np
import pandas as pd

from .common import DATA

LEVELS = ["a", "a+", "aa", "aaa", "mlb"]
NEXT = dict(zip(LEVELS[:-1], LEVELS[1:]))
COMPS = ["K", "BB", "ISO", "BABIP"]
MEXICAN_LEAGUE = 125  # unaffiliated; appears under AAA through 2019
MIN_PA = 50
# FanGraphs stabilization points (denominator unit: PA for K/BB, AB for ISO, BIP for BABIP)
K_STAB = {"K": 60, "BB": 120, "ISO": 160, "BABIP": 820}
DEN = {"K": "PA", "BB": "PA", "ISO": "AB", "BABIP": "BIP"}
K_FIXED = 20000.0  # pair-weight fallback when reliability is unusable (r <= 0.05 or < 15 adjacent pairs)


def rates(d):
    """Raw component rates from counts; zero denominators -> NaN."""
    z = lambda s: s.where(s > 0)  # noqa: E731
    d["BIP"] = d["AB"] - d["SO"] - d["HR"] + d["SF"]
    d["K"] = d["SO"] / z(d["PA"])
    d["BB"] = (d["BB"] - d["IBB"] + d["HBP"]) / z(d["PA"])
    d["ISO"] = (d["TBx"] - d["H"]) / z(d["AB"])
    d["BABIP"] = (d["H"] - d["HR"]) / z(d["BIP"])
    return d


def prep_milb():
    s = pd.read_parquet(DATA / "milb_player_seasons.parquet")
    s = s[s.level.isin(LEVELS[:4]) & (s.league_id != MEXICAN_LEAGUE) & (s.primary_pos_milb != "P")]
    s = s.merge(pd.read_parquet(DATA / "milb_player_park.parquet"),
                on=["player_id", "season", "level", "league_id"], validate="1:1")
    s["TBx"] = s.H + s["2B"] + 2 * s["3B"] + 3 * s.HR
    # ISO park factor: blend 2B3B and HR by each league-season's share of ISO bases
    g = s.assign(b2=s["2B"] + 2 * s["3B"], b3=3 * s.HR).groupby(["league_id", "season"])[["b2", "b3"]].transform("sum")
    wHR = g.b3 / (g.b2 + g.b3)
    s["ppf_ISO"] = (1 - wHR) * s.ppf_2B3B + wHR * s.ppf_HR
    cols = ["player_id", "season", "level", "league_id", "PA", "AB", "H", "HR", "BB", "IBB", "HBP", "SO", "SF", "TBx"]
    out = rates(s[cols].copy())
    for c in COMPS:
        out["neutral_" + c] = out[c] / s["ppf_" + {"K": "SO", "BB": "BB", "ISO": "ISO", "BABIP": "BABIP"}[c]]
    return out


def prep_mlb():
    m = pd.read_parquet(DATA / "mlb_seasons.parquet")
    pl = pd.read_parquet(DATA / "players.parquet")[["player_id", "primary_pos"]]
    m = m.merge(pl, on="player_id", how="left")
    m = m[m.primary_pos != "P"]
    pf = pd.read_parquet(DATA / "park_factors.parquet").query("sport == 'mlb'")
    m = m.merge(pf, on=["season", "team_id"], how="left", validate="m:1")
    m["TBx"] = m.H + m["2B"] + 2 * m["3B"] + 3 * m.HR
    g = m.assign(b2=m["2B"] + 2 * m["3B"], b3=3 * m.HR).groupby("season")[["b2", "b3"]].transform("sum")
    wHR = g.b3 / (g.b2 + g.b3)
    half = lambda c: ((1 + m["pf_" + c]) / 2).fillna(1.0)  # noqa: E731 half-home exposure
    ppf = {"K": half("SO"), "BB": half("BB"), "BABIP": half("BABIP"),
           "ISO": (1 - wHR) * half("2B3B") + wHR * half("HR")}
    # neutralize team-stint rates, then PA/AB/BIP-weighted average per player-season
    t = rates(m[["player_id", "season", "PA", "AB", "H", "HR", "BB", "IBB", "HBP", "SO", "SF", "TBx"]].copy())
    for c in COMPS:
        t["neutral_" + c] = t[c] / ppf[c]
    return rollup(t, ["player_id", "season"]).assign(level="mlb", league_id=0)


def wmean(d, col, wcol):
    ok = d[col].notna() & (d[wcol] > 0)
    return (d[col].where(ok) * d[wcol].where(ok)).sum() / d[wcol].where(ok).sum() if ok.any() else np.nan


def rollup(d, keys, cols=None):
    """Sum counts and denominator-weighted-average the given rate columns per group (vectorized)."""
    cols = cols or ["neutral_" + c for c in COMPS]
    sums = d.groupby(keys)[["PA", "AB", "BIP"]].sum()
    out = sums.copy()
    for c, col in zip(COMPS * (len(cols) // 4), cols):
        w = d[DEN[c]].where(d[col].notna(), 0.0)
        num = (d[col].fillna(0) * w).groupby([d[k] for k in keys]).sum()
        den = w.groupby([d[k] for k in keys]).sum()
        out[col] = (num / den.where(den > 0))
    return out.reset_index()


def build_pairs(milb, mlb):
    """One row per (lower row, same-season upper aggregate) with both >= MIN_PA."""
    nc = ["neutral_" + c for c in COMPS]
    up_minor = rollup(milb, ["player_id", "season", "level"]).rename(columns={"PA": "PA_up"})
    up_mlb = mlb.rename(columns={"PA": "PA_up"})
    ups = pd.concat([up_minor, up_mlb[["player_id", "season", "level", "PA_up"] + nc]], ignore_index=True)
    ups = ups[ups.PA_up >= MIN_PA]
    lo = milb[milb.PA >= MIN_PA][["player_id", "season", "level", "league_id", "PA"] + nc]
    lo = lo.assign(up_level=lo.level.map(NEXT))
    p = lo.merge(ups.rename(columns={"level": "up_level"}), on=["player_id", "season", "up_level"],
                 suffixes=("_lo", "_up"))
    p["w"] = 2 * p.PA * p.PA_up / (p.PA + p.PA_up)
    return p


def raw_factors(p, keys):
    """Ratio of weighted means per component for each group in `keys`."""
    rows = []
    for c in COMPS:
        q = p.dropna(subset=[f"neutral_{c}_lo", f"neutral_{c}_up"])
        q = q.assign(nu=q.w * q[f"neutral_{c}_up"], nl=q.w * q[f"neutral_{c}_lo"])
        g = q.groupby(keys).agg(n_pairs=("w", "size"), pair_weight=("w", "sum"), nu=("nu", "sum"), nl=("nl", "sum"))
        g["raw_factor"] = g.nu / g.nl
        rows.append(g.drop(columns=["nu", "nl"]).reset_index().assign(component=c))
    return pd.concat(rows, ignore_index=True)


def estimate_k(child, parent_cols, keys_child):
    """k = mean(pair_weight)*(1-r)/r, r = corr of adjacent-season deviations from the parent raw factor.
    Adjacent = consecutive seasons (2019 and 2021 count as adjacent). Falls back to K_FIXED."""
    out = {}
    for c in COMPS:
        d = child[(child.component == c) & (child.pair_weight > 0)].copy()
        d["dev"] = d.raw_factor - d.parent_raw
        seasons = sorted(d.season.unique())
        nxt = {a: b for a, b in zip(seasons[:-1], seasons[1:])}
        d["season_next"] = d.season.map(nxt)
        m = d.merge(d[keys_child + ["season", "dev"]].rename(columns={"season": "season_next", "dev": "dev_next"}),
                    on=keys_child + ["season_next"])
        r = m.dev.corr(m.dev_next) if len(m) >= 15 else np.nan
        if r is None or np.isnan(r) or r <= 0.05:
            out[c] = {"k": K_FIXED, "r": None if r is None or np.isnan(r) else round(float(r), 3), "fixed": True, "n": len(m)}
        else:
            r = min(r, 0.95)
            out[c] = {"k": float(d.pair_weight.mean() * (1 - r) / r), "r": round(float(r), 3), "fixed": False, "n": len(m)}
    return out


def shrink(raw, parent, k):
    w = raw.n_pairs * 0 + raw.pair_weight
    f = (w * raw.raw_factor.fillna(0) + k * parent) / (w + k)
    return f.where(w.notna())


def translation_factors(p, milb):
    lg = raw_factors(p, ["level", "league_id", "season"])
    ls = raw_factors(p, ["level", "season"]).assign(league_id=-1)
    la = raw_factors(p, ["level"]).assign(league_id=-1, season=0)
    # full grid so every league-season / level-season exists (zero pairs fall back to the parent)
    grid = milb[["level", "league_id", "season"]].drop_duplicates()
    seasons = sorted(set(grid.season) | {2026})
    grid_ls = pd.MultiIndex.from_product([LEVELS[:4], seasons], names=["level", "season"]).to_frame(index=False)
    comps = pd.DataFrame({"component": COMPS})
    lg = grid.merge(comps, how="cross").merge(lg, how="left", on=["level", "league_id", "season", "component"])
    ls = grid_ls.merge(comps, how="cross").assign(league_id=-1).merge(
        ls, how="left", on=["level", "league_id", "season", "component"])
    for d in (lg, ls):
        d[["n_pairs", "pair_weight"]] = d[["n_pairs", "pair_weight"]].fillna(0)
    la_f = la.set_index(["level", "component"]).raw_factor
    # shrinkage k values
    ls["parent_raw"] = [la_f[(a, b)] for a, b in zip(ls.level, ls.component)]
    ls["factor_all"] = ls.parent_raw
    k_ls = estimate_k(ls, ["parent_raw"], ["level"])
    lsr = ls.set_index(["level", "season", "component"]).raw_factor
    lg["parent_raw"] = [lsr.get((a, b, c), np.nan) for a, b, c in zip(lg.level, lg.season, lg.component)]
    k_lg = estimate_k(lg.dropna(subset=["parent_raw"]), ["parent_raw"], ["level", "league_id"])
    ls["factor"] = shrink(ls, ls.parent_raw, ls.component.map(lambda c: k_ls[c]["k"]))
    lsf = ls.set_index(["level", "season", "component"]).factor
    lg["parent_f"] = [lsf[(a, b, c)] for a, b, c in zip(lg.level, lg.season, lg.component)]
    lg["factor"] = shrink(lg, lg.parent_f, lg.component.map(lambda c: k_lg[c]["k"]))
    la["factor"] = la.raw_factor
    cols = ["level", "league_id", "season", "component", "n_pairs", "pair_weight", "raw_factor", "factor"]
    out = pd.concat([lg[cols], ls[cols], la[cols]], ignore_index=True).rename(columns={"level": "from_level"})
    return out, {"league_season_to_level_season": k_lg, "level_season_to_level_all": k_ls}


def apply_mle(milb, fac):
    ls = fac[(fac.league_id == -1) & (fac.season > 0)].set_index(["from_level", "season", "component"]).factor
    lgf = fac[fac.league_id != -1].set_index(["from_level", "league_id", "season", "component"]).factor
    m = milb.copy()
    for c in COMPS:
        own = pd.Series([lgf[(a, b, s, c)] for a, b, s in zip(m.level, m.league_id, m.season)], index=m.index)
        chain = own.copy()
        for lv in ["a", "a+", "aa", "aaa"]:  # multiply by level-season factors of every higher level
            above = m.level.map({"a": 1, "a+": 2, "aa": 3, "aaa": 4}) < LEVELS.index(lv) + 1
            above &= m.level != lv
            chain = chain * np.where(above, [ls[(lv, s, c)] for s in m.season], 1.0)
        m["factor_" + c] = chain
        m["mle_" + c] = m["neutral_" + c] * chain
    return m


def regress(m):
    for c in COMPS:
        n = m[DEN[c]]
        ok = m["mle_" + c].notna() & (n > 0)
        key = [m.level, m.season]
        prior = (m["mle_" + c].where(ok) * n.where(ok)).groupby(key).transform("sum") / n.where(ok).groupby(key).transform("sum")
        m["prior_" + c] = prior
        m["reg_" + c] = (n * m["mle_" + c] + K_STAB[c] * prior) / (n + K_STAB[c])
    return m


def player_season(m):
    cols = [f"{p}_{c}" for p in ("mle", "reg") for c in COMPS]
    # weights: PA for K/BB, AB for ISO, BIP for BABIP (same denominators as the stabilization points)
    out = rollup(m, ["player_id", "season"], cols).rename(columns={"PA": "PA"})[["player_id", "season", "PA"] + cols]
    top = m.assign(r=m.level.map(LEVELS.index)).sort_values("r").groupby(["player_id", "season"])["level"].last()
    return out.merge(top.rename("highest_level").reset_index(), on=["player_id", "season"])


def main():
    milb, mlb = prep_milb(), prep_mlb()
    pairs = build_pairs(milb, mlb)
    fac, ks = translation_factors(pairs, milb)
    fac.to_parquet(DATA / "translation_factors.parquet", index=False)
    (DATA / "b4_k.json").write_text(json.dumps({"k": ks, "k_stab": K_STAB, "k_fixed": K_FIXED}, indent=1))
    m = regress(apply_mle(milb, fac))
    keep = (["player_id", "season", "level", "league_id", "PA", "AB", "BIP"] + ["neutral_" + c for c in COMPS]
            + ["mle_" + c for c in COMPS] + ["reg_" + c for c in COMPS])
    m[keep].to_parquet(DATA / "mle.parquet", index=False)
    player_season(m).to_parquet(DATA / "mle_player_season.parquet", index=False)
    print(json.dumps(ks, indent=1))
    print(f"factors {len(fac)}, mle rows {len(m)}")


if __name__ == "__main__":
    main()
