"""B17 pitcher WAR (S17, S19, D16, Q19, Q20, C13, C14). MLB pitcher-seasons 2005-2026, unregressed.

Runs allowed above average = K, uBB + HBP, and HR at the A14 BaseRuns run values (b2 linear_weights), non-HR balls in play
at the league-season BIP value, plus a contact term: observed 2B and 3B allowed, centered on the league rate per BIP, at
their run value above a single. IBB excluded (FIP convention). Park adjusted per team stint with B3 half-park factors
(pf_SO, pf_BB, pf_HR, pf_2B3B); events a park removes are returned as balls in play so BF is unchanged.
Replacement per out: starter innings sit SP_RP_GAP wins per 9 above relief innings (Q20); the overall level is solved per
season so pitcher WAR sums to 410 x games / 2430. Relief value is scaled by (1 + gmLI) / 2, gmLI = bWAR
GR_leverage_index_avg (Q19), weighted by relief outs. Starter/relief outs split from bWAR IPouts_start/IPouts_relief
(GS / G where bWAR has no row).

Outputs (data/): mlb_pitch_war.parquet (player x season), pitch_war_target.parquet (player, 6-year window as b2).
"""
import pandas as pd
import requests

from pipeline.b2_war import UA, target
from pipeline.common import DATA, RAW

PITCH_WAR_PER_2430 = 410  # S17: pitcher WAR per 2,430 MLB games (Baseball-Reference split)
SP_RP_GAP = 0.09  # Q20: wins per 9 IP, FanGraphs SP .380 vs RP .470 replacement (0.12 vs 0.03 below average)
BWAR_PITCH_URL = "https://www.baseball-reference.com/data/war_daily_pitch.txt"


def fetch_bwar_pitch():
    f = RAW / "bwar_pitch.csv"
    if not f.exists():
        r = requests.get(BWAR_PITCH_URL, headers={"User-Agent": UA}, timeout=300)
        r.raise_for_status()
        f.write_bytes(r.content)
    return f


def bwar_pitch():
    """player-season bWAR pitching: outs split, relief-weighted gmLI, WAR (validation only)."""
    b = pd.read_csv(fetch_bwar_pitch(), usecols=["mlb_ID", "year_ID", "IPouts", "IPouts_start", "IPouts_relief",
                                                 "GR_leverage_index_avg", "WAR"], low_memory=False).apply(pd.to_numeric, errors="coerce")
    b = b[b.year_ID.between(2005, 2026) & b.mlb_ID.notna()]
    b["li_x"] = b.GR_leverage_index_avg * b.IPouts_relief
    g = b.groupby(["mlb_ID", "year_ID"]).agg(b_outs=("IPouts", "sum"), b_start=("IPouts_start", "sum"),
                                             b_relief=("IPouts_relief", "sum"), li_x=("li_x", "sum"),
                                             bWAR=("WAR", lambda s: s.sum(min_count=1))).reset_index()
    g["gmLI"] = g.li_x / g.b_relief.where(g.b_relief > 0)
    return (g.rename(columns={"mlb_ID": "player_id", "year_ID": "season"}).astype({"player_id": "int64", "season": "int64"})
            [["player_id", "season", "b_outs", "b_start", "gmLI", "bWAR"]])


def war():
    lw = pd.read_parquet(DATA / "linear_weights.parquet").set_index("season")
    mp = pd.read_parquet(DATA / "mlb_pitching.parquet")
    pf = pd.read_parquet(DATA / "park_factors.parquet").query("sport == 'mlb'")[["season", "team_id", "pf_SO", "pf_BB", "pf_HR", "pf_2B3B"]]
    mp = mp.merge(pf, on=["season", "team_id"], how="left")
    half = lambda c: (1 + mp[c].fillna(1)) / 2  # noqa: E731  home half of the schedule
    mp["uBB_HBP"] = mp.BB - mp.IBB + mp.HBP
    mp["BIP"] = mp.BF - mp.SO - mp.BB - mp.HBP - mp.HR

    lg = mp.groupby("season")[["H", "2B", "3B", "HR", "BIP"]].sum().join(lw)
    lg["1B"] = lg.H - lg["2B"] - lg["3B"] - lg.HR
    lg["v_BIP"] = (lg.rv_1B * lg["1B"] + lg.rv_2B * lg["2B"] + lg.rv_3B * lg["3B"]
                   + lg.rv_out * (lg.BIP - lg["1B"] - lg["2B"] - lg["3B"])) / lg.BIP
    lg["r2B"], lg["r3B"] = lg["2B"] / lg.BIP, lg["3B"] / lg.BIP
    L = lg.loc[mp.season].reset_index(drop=True)

    so, bbh, hr = mp.SO / half("pf_SO"), mp.uBB_HBP / half("pf_BB"), mp.HR / half("pf_HR")
    bip = mp.BIP + (mp.SO - so) + (mp.uBB_HBP - bbh) + (mp.HR - hr)
    d2, d3 = mp["2B"] / half("pf_2B3B"), mp["3B"] / half("pf_2B3B")
    mp["fip_runs"] = L.rv_out * so + L.rv_uBB_HBP * bbh + L.rv_HR * hr + L.v_BIP * bip
    mp["contact_runs"] = (L.rv_2B - L.rv_1B) * (d2 - L.r2B * mp.BIP) + (L.rv_3B - L.rv_1B) * (d3 - L.r3B * mp.BIP)

    p = mp.groupby(["player_id", "season"], as_index=False)[["G", "GS", "outs", "BF", "fip_runs", "contact_runs"]].sum()
    p = p.merge(bwar_pitch(), on=["player_id", "season"], how="left")
    p = p.join(lw[["RPW", "games"]], on="season")
    start_frac = (p.b_start / p.b_outs.where(p.b_outs > 0)).fillna(p.GS / p.G.where(p.G > 0)).fillna(0)
    p["outs_start"], p["outs_relief"] = p.outs * start_frac, p.outs * (1 - start_frac)
    p["gmLI"] = p.gmLI.fillna(1.0)
    p["lev"] = (1 + p.gmLI) / 2
    rf = (p.outs_relief / p.outs.where(p.outs > 0)).fillna(0)
    p["raa_runs"] = -(p.fip_runs + p.contact_runs)  # runs saved vs average; positive is good
    wins_aa = p.raa_runs / p.RPW * (1 - rf + p.lev * rf)
    # pwar = wins_aa + gap x start innings + a x (start + leveraged relief innings), a solved per season
    fixed = wins_aa + SP_RP_GAP * p.outs_start / 27
    per_a = (p.outs_start + p.lev * p.outs_relief) / 27
    s = pd.DataFrame({"fixed": fixed, "per_a": per_a, "season": p.season}).groupby("season").sum()
    a = (PITCH_WAR_PER_2430 * lw.games / 2430 - s.fixed) / s.per_a
    p["repl_rp_per9"] = p.season.map(a)
    p["repl_wins"] = (p.repl_rp_per9 + SP_RP_GAP) * p.outs_start / 27 + p.lev * p.repl_rp_per9 * p.outs_relief / 27
    p["pwar"] = fixed + p.repl_rp_per9 * per_a
    out = p[["player_id", "season", "G", "GS", "outs", "BF", "outs_start", "outs_relief", "fip_runs", "contact_runs", "raa_runs",
             "gmLI", "lev", "RPW", "repl_rp_per9", "repl_wins", "pwar", "bWAR"]]
    out.to_parquet(DATA / "mlb_pitch_war.parquet", index=False)
    return out


def main():
    w = war()
    t = target(w, col="pwar", players_file="pitch_players.parquet", out_file="pitch_war_target.parquet")
    tot = w.groupby("season").pwar.sum()
    a = w.groupby("season").repl_rp_per9.first()
    v = w[w.outs >= 300].dropna(subset=["bWAR"])
    rp = w[(w.outs >= 120) & (w.GS < 5)].dropna(subset=["bWAR"])
    print(f"mlb_pitch_war {len(w)} rows, pitch_war_target {len(t)}; season sums {tot.min():.1f}-{tot.max():.1f} "
          f"(2020 {tot[2020]:.1f}); RP replacement {a.min():.3f}-{a.max():.3f} wins/9")
    print(f"C14 r vs bWAR: 100+ IP {v.pwar.corr(v.bWAR):.4f} (n={len(v)}); RP 40+ IP, <5 GS {rp.pwar.corr(rp.bWAR):.4f} (n={len(rp)})")


if __name__ == "__main__":
    main()
