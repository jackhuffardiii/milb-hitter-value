"""B18: pitcher MiLB -> MLB-equivalent K%, BB%, HBP%, HR%, GB%, XB/BIP (S20, Q25, C16). Same method as B4 (reuses its
functions with pitcher components): park-neutralize, matched same-season (>=50 BF) and cross-season (>=300 BF, aging
drift from same-level repeaters) pairs, league-season -> level-season -> level-all shrinkage, chain to MLB, regress toward
the source league-season mean, roll up to player-season, level-step test.
Components: K=SO/BF, BB=(BB-IBB)/BF, HBP=HBP/BF, HR=HR/BF, GB=GO/(GO+AO) (outs-based), XB=(2B+2*3B)/BIP.
R=R/BF (runs allowed) is translated too: it is the B19 mERA target and the S22 ladder scale, never a model input.
"""
import json

import numpy as np
import pandas as pd

from .b3_park import player_park
from .b4_mle import LEVELS, MEXICAN_LEAGUE, aging_drift, apply_mle, build_pairs, level_step, player_season, regress, rollup, translation_factors
from . import config
from .common import DATA

COMPS = ["K", "BB", "HBP", "HR", "GB", "XB", "R"]
DEN = {"K": "BF", "BB": "BF", "HBP": "BF", "HR": "BF", "GB": "GOAO", "XB": "BIP", "R": "BF"}
# Carleton (2012) pitcher reliability / stabilization points, in each component's own denominator
K_STAB = config.K_STAB_PITCH  # R has no Carleton point; reg_R is never read (B19 uses mle_R as the target)
PARK = {"K": "SO", "BB": "BB", "HBP": "BB", "HR": "HR", "XB": "2B3B", "R": "R"}  # GB has no park factor


def rates(d):
    """Raw component rates from counts; zero denominators -> NaN."""
    z = lambda s: s.where(s > 0)  # noqa: E731
    d["GOAO"] = d.GO + d.AO
    d["BIP"] = d.BF - d.SO - d.BB - d.HBP - d.HR
    d["K"] = d.SO / z(d.BF)
    d["BB"] = (d.BB - d.IBB) / z(d.BF)
    d["HBP"] = d.HBP / z(d.BF)
    d["HR"] = d.HR / z(d.BF)
    d["GB"] = d.GO / z(d.GOAO)
    d["XB"] = (d["2B"] + 2 * d["3B"]) / z(d.BIP)
    d["R"] = d.R / z(d.BF)
    return d


COUNTS = ["BF", "SO", "BB", "IBB", "HBP", "HR", "GO", "AO", "2B", "3B", "R"]


def _neutral(d, ppf):
    t = rates(d[["player_id", "season"] + COUNTS + [c for c in ("level", "league_id", "age") if c in d]].copy())
    for c in COMPS:
        t["neutral_" + c] = t[c] / ppf[c] if c in ppf else t[c]
    return t


def prep_milb():
    s = pd.read_parquet(DATA / "milb_pitching_seasons.parquet")
    s = s[s.level.isin(LEVELS[:4]) & (s.league_id != MEXICAN_LEAGUE) & (s.BF > 0)]
    pf = pd.read_parquet(DATA / "park_factors.parquet")
    pp = player_park(pf, "milb_pitch_stints.parquet", "BF")
    s = s.merge(pp, on=["player_id", "season", "level", "league_id"], validate="1:1")
    return _neutral(s, {c: s["ppf_" + p] for c, p in PARK.items()})


def prep_mlb():
    m = pd.read_parquet(DATA / "mlb_pitching.parquet")
    m = m[m.BF > 0]
    pf = pd.read_parquet(DATA / "park_factors.parquet").query("sport == 'mlb'")
    m = m.merge(pf, on=["season", "team_id"], how="left", validate="m:1")
    half = lambda c: ((1 + m["pf_" + c]) / 2).fillna(1.0)  # noqa: E731 half-home exposure
    t = _neutral(m, {c: half(p) for c, p in PARK.items()})
    return rollup(t, ["player_id", "season"], None, COMPS, DEN, "BF").assign(level="mlb", league_id=0)


def main():
    milb, mlb = prep_milb(), prep_mlb()
    drift = aging_drift(milb, COMPS, "BF")
    pairs = build_pairs(milb, mlb, drift, COMPS, DEN, "BF")
    fac, ks = translation_factors(pairs, milb, COMPS)
    fac.to_parquet(DATA / "pitch_translation_factors.parquet", index=False)
    m = regress(apply_mle(milb, fac, COMPS), COMPS, DEN, K_STAB)
    c16 = level_step(m, COMPS, "BF")
    (DATA / "b18_k.json").write_text(json.dumps({"k": ks, "k_stab": K_STAB, "aging_drift": drift,
                                                 "pairs": pairs.kind.value_counts().to_dict(), "C16": c16}, indent=1, default=float))
    for step, v in c16.items():
        print("C16", step, {c: (round(v[c]["diff"], 4), round(v[c]["se"], 4), v[c]["pass"]) for c in COMPS})
    keep = (["player_id", "season", "level", "league_id", "BF", "GOAO", "BIP"] + ["neutral_" + c for c in COMPS]
            + ["mle_" + c for c in COMPS] + ["reg_" + c for c in COMPS])
    m[keep].to_parquet(DATA / "pitch_mle.parquet", index=False)
    ps = player_season(m, COMPS, DEN, "BF")
    ps.to_parquet(DATA / "pitch_mle_player_season.parquet", index=False)
    print(json.dumps(ks, indent=1))
    print("pairs", pairs.kind.value_counts().to_dict())
    print(f"factors {len(fac)}, mle rows {len(m)}, player-seasons {len(ps)}")


if __name__ == "__main__":
    main()
