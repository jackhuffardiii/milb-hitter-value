"""B2 simplified WAR (S4, A2, A3, A4, A14, C1, D7, Q2, X2). Run values from BaseRuns partial derivatives (A14). MLB hitter-seasons 2005-2026, WAR = batting (park-adjusted)
+ baserunning (wSB + GIDP) + fielding (bWAR runs_field) + positional + replacement runs, over runs-per-win.
Column `owar` holds this full WAR (name kept from the offense-only version; `fld_runs` is the fielding part).
Also the 6-year WAR target per player.

Outputs (data/): linear_weights.parquet (season), mlb_war.parquet (player x season), war_target.parquet (player).
bWAR (D7, data/raw/bwar.csv) supplies fielding runs only; its total WAR is validation (tests/test_b2.py, docs/handoff.md).
"""
import numpy as np
import pandas as pd
import requests

from pipeline.common import DATA, RAW, api_get, pmap

YEARS = range(2005, 2027)
EVENTS = ["1B", "2B", "3B", "HR", "uBB_HBP", "out"]
POS_RUNS = {"C": 12.5, "SS": 7.5, "2B": 2.5, "3B": 2.5, "CF": 2.5, "LF": -7.5, "RF": -7.5, "1B": -12.5,
            "DH": -17.5, "OF": -2.5}  # OF (generic) never occurs in the data; kept for safety
BWAR_URL = "https://www.baseball-reference.com/data/war_daily_bat.txt"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _team_totals(season, group):
    d = api_get("teams/stats", stats="season", group=group, season=season, sportId=1, gameType="R", limit=100)
    return [s["stat"] | {"team_id": s["team"]["id"], "season": season} for s in d["stats"][0]["splits"]]


def _ip(s):  # "1432.1" -> 1432 + 1/3
    w, _, f = str(s).partition(".")
    return int(w) + int(f or 0) / 3


def _events(d):
    return pd.DataFrame({"1B": d.H - d["2B"] - d["3B"] - d.HR, "2B": d["2B"], "3B": d["3B"], "HR": d.HR,
                         "uBB_HBP": d.BB - d.IBB + d.HBP, "out": d.AB - d.H + d.SF + d.SH})


# A14: d(A, B, C, D)/d(event) for BaseRuns, A = H + uBB + HBP - HR + .5 IBB, B = 1.02 (1.4 TB - .6 H - 3 HR + .1 (uBB + HBP)),
# C = outs, D = HR. BsR = A B / (B + C) + D.
BSR_D = {"1B": (1, 1.02 * 0.8, 0, 0), "2B": (1, 1.02 * 2.2, 0, 0), "3B": (1, 1.02 * 3.6, 0, 0), "HR": (0, 1.02 * 2.0, 0, 1),
         "uBB_HBP": (1, 1.02 * 0.1, 0, 0), "out": (0, 0, 1, 0)}


def baseruns_values(r):
    """A14: marginal run value of each event = partial derivative of BaseRuns at league totals `r` (a Series of event sums)."""
    tb = r["1B"] + 2 * r["2B"] + 3 * r["3B"] + 4 * r.HR
    h = r["1B"] + r["2B"] + r["3B"] + r.HR
    A = r["1B"] + r["2B"] + r["3B"] + r.uBB_HBP + 0.5 * r.IBB
    B = 1.02 * (1.4 * tb - 0.6 * h - 3 * r.HR + 0.1 * r.uBB_HBP)
    C = r.out
    return np.array([dA * B / (B + C) + A * (dB * C - B * dC) / (B + C) ** 2 + dD for dA, dB, dC, dD in (BSR_D[e] for e in EVENTS)])


def linear_weights():
    hit = pd.DataFrame([r for rs in pmap(lambda y: _team_totals(y, "hitting"), YEARS) for r in rs])
    pit = pd.DataFrame([r for rs in pmap(lambda y: _team_totals(y, "pitching"), YEARS) for r in rs])
    num = ["atBats", "hits", "doubles", "triples", "homeRuns", "baseOnBalls", "intentionalWalks", "hitByPitch",
           "sacFlies", "sacBunts", "runs", "plateAppearances", "stolenBases", "caughtStealing", "groundIntoDoublePlay"]
    hit = hit[["season", "team_id"] + num].astype({c: float for c in num})
    hit.columns = ["season", "team_id", "AB", "H", "2B", "3B", "HR", "BB", "IBB", "HBP", "SF", "SH", "R", "PA", "SB", "CS", "GIDP"]
    pit["IP"] = pit["inningsPitched"].map(_ip)
    ev = _events(hit)
    hit = hit.join(ev[["1B", "uBB_HBP", "out"]])
    lg = hit.groupby("season")[["AB", "H", "BB", "IBB", "HBP", "SF", "SH", "R", "PA", "SB", "CS", "GIDP"] + EVENTS].sum()
    lg["IP"] = pit.groupby("season").IP.sum()
    rows = []
    for s, r in lg.iterrows():
        beta = baseruns_values(r)
        rv = beta * r.R / (r[EVENTS].to_numpy() @ beta)  # scale so predicted league runs == actual (absolute values)
        rv[5] -= r.R / r.out  # above-average out value (absolute out minus runs per out): league LW sum to 0, RE24 convention
        w = rv[:5] - rv[5]
        denom = r.AB + r.BB - r.IBB + r.SF + r.HBP
        obp = (r.H + r.BB + r.HBP) / (r.AB + r.BB + r.HBP + r.SF)
        raw = (w * r[EVENTS[:5]].to_numpy()).sum() / denom
        scale = obp / raw  # wOBA = scale * sum(w n)/denom
        # S4 baserunning, FanGraphs wSB form: runSB .2, runCS = -(2 runs/out + .075); lg_wSB per opportunity
        run_cs = -(2 * r.R / (r.AB - r.H + r.SF + r.SH) + 0.075)
        opp = r["1B"] + r.BB + r.HBP - r.IBB
        rows.append({"season": s, "runCS": run_cs, "lg_wSB": (r.SB * 0.2 + r.CS * run_cs) / opp,
                     "lg_GIDP_per_PA": r.GIDP / r.PA, **{f"rv_{e}": v for e, v in zip(EVENTS, rv)},
                     **{f"w_{e}": scale * v for e, v in zip(EVENTS[:5], w)},
                     "wOBA_scale": scale, "lg_wOBA": obp, "lg_R_per_PA": r.R / r.PA,
                     "RPW": 9 * (r.R / r.IP) * 1.5 + 3})
    return pd.DataFrame(rows)


def _gidp():
    """player-season GIDP: b1 carries it on mlb_seasons (includes the S3 re-pulled stints)."""
    m = pd.read_parquet(DATA / "mlb_seasons.parquet")
    return m.groupby(["player_id", "season"], as_index=False).GiDP.sum().rename(columns={"GiDP": "GIDP"})


def _fielding():
    """player-season fielding runs (X2 reversed 2026-10-06): Baseball-Reference runs_field (DRS-based), summed over stints."""
    b = pd.read_csv(fetch_bwar(), usecols=["mlb_ID", "year_ID", "runs_field"], low_memory=False)
    b["runs_field"] = pd.to_numeric(b.runs_field, errors="coerce")
    b = b[b.year_ID.between(2005, 2026) & b.mlb_ID.notna()]
    return (b.groupby(["mlb_ID", "year_ID"], as_index=False).runs_field.sum()
            .rename(columns={"mlb_ID": "player_id", "year_ID": "season", "runs_field": "fld_runs"})
            .astype({"player_id": "int64", "season": "int64"}))


def war():
    lw = linear_weights()
    lw.to_parquet(DATA / "linear_weights.parquet")
    ms = pd.read_parquet(DATA / "mlb_seasons.parquet").merge(lw, on="season")
    pf = pd.read_parquet(DATA / "park_factors.parquet").query("sport == 'mlb'")[["season", "team_id", "pf_R"]]
    ms = ms.merge(pf, on=["season", "team_id"], how="left")
    ms["ppf"] = (1 + ms.pf_R.fillna(0)) / 2  # pf_R missing -> neutral
    ms["ppf_pa"] = ms.ppf * ms.PA
    ms["uBB_HBP"] = ms.BB - ms.IBB + ms.HBP
    ms["1B"] = ms.H - ms["2B"] - ms["3B"] - ms.HR
    ms["w_sum"] = sum(ms[f"w_{e}"] * ms[e] for e in EVENTS[:5]) / ms.wOBA_scale  # un-scaled run-weighted sum
    ms["den"] = ms.AB + ms.BB - ms.IBB + ms.SF + ms.HBP
    g = ms.groupby(["player_id", "season"])
    p = g[["G", "PA", "den", "w_sum", "ppf_pa"]].sum()
    p = p.join(g[["wOBA_scale", "lg_wOBA", "lg_R_per_PA", "RPW"]].first()).reset_index()
    p = p[p.PA > 0]
    p["wOBA"] = p.w_sum * p.wOBA_scale / p.den
    p["bat_runs"] = (p.wOBA - p.lg_wOBA) / p.wOBA_scale * p.PA
    p["park_runs"] = -(p.ppf_pa / p.PA - 1) * p.lg_R_per_PA * p.PA
    p["repl_runs"] = 20 * p.PA / 600
    sb = ms.groupby(["player_id", "season"])[["SB", "CS", "1B", "BB", "HBP", "IBB"]].sum()
    p = p.join(sb, on=["player_id", "season"]).merge(_gidp(), on=["player_id", "season"], how="left")
    p = p.merge(lw[["season", "runCS", "lg_wSB", "lg_GIDP_per_PA"]], on="season")
    p["GIDP"] = p.GIDP.fillna(0)
    p["wSB"] = (p.SB * 0.2 + p.CS * p.runCS - p.lg_wSB * (p["1B"] + p.BB + p.HBP - p.IBB)).fillna(0)
    # ponytail: GIDP runs approximated as -0.37 runs per GIDP above league rate per PA. True double-play opportunities
    # (runner on 1st, <2 outs) need MLB play-by-play, which we do not pull.
    p["gidp_runs"] = -0.37 * (p.GIDP - p.lg_GIDP_per_PA * p.PA)
    p["bsr_runs"] = p.wSB + p.gidp_runs
    p = p.merge(_fielding(), on=["player_id", "season"], how="left")
    p["fld_runs"] = p.fld_runs.fillna(0)  # not in bWAR (rare cup-of-coffee rows) -> average fielder

    fg = pd.read_parquet(DATA / "mlb_fielding_games.parquet")
    tot = fg.groupby(["player_id", "season"]).games.sum().rename("f_all")
    pg = fg[fg.position == "P"].set_index(["player_id", "season"]).games.rename("f_p")
    nonp = fg[~fg.position.isin(["P", "DH"])]
    pos = (nonp.assign(r=nonp.position.map(POS_RUNS) * nonp.games / 162)
           .groupby(["player_id", "season"]).agg(pos_f=("r", "sum"), f_np=("games", "sum")))
    top = nonp.sort_values("games").groupby(["player_id", "season"]).position.last().rename("primary_pos")
    p = p.join(tot, on=["player_id", "season"]).join(pg, on=["player_id", "season"]).join(
        pos, on=["player_id", "season"]).join(top, on=["player_id", "season"])
    p[["f_all", "f_p", "pos_f", "f_np"]] = p[["f_all", "f_p", "pos_f", "f_np"]].fillna(0)
    p = p[~(p.f_p > 0.5 * p.f_all)]  # drop pitchers
    dh = (p.G - p.f_np).clip(lower=0)
    p["pos_runs"] = p.pos_f + POS_RUNS["DH"] * dh / 162
    p["primary_pos"] = p.primary_pos.fillna("DH")
    p["owar"] = (p.bat_runs + p.park_runs + p.bsr_runs + p.fld_runs + p.pos_runs + p.repl_runs) / p.RPW
    out = p[["player_id", "season", "PA", "wOBA", "lg_wOBA", "wOBA_scale", "bat_runs", "park_runs", "wSB", "gidp_runs", "bsr_runs",
             "fld_runs", "pos_runs", "repl_runs", "RPW", "owar", "primary_pos"]]
    out.to_parquet(DATA / "mlb_war.parquet")
    return out


def target(w):
    pl = pd.read_parquet(DATA / "players.parquet")
    pl = pl[pl.mlb_debut_date.notna()][["player_id", "mlb_debut_date"]]
    pl["debut_season"] = pl.mlb_debut_date.dt.year
    m = w.merge(pl, on="player_id")
    m = m[(m.season >= m.debut_season) & (m.season <= m.debut_season + 5)]
    a = m.groupby("player_id").agg(war_6yr=("owar", "sum"), n_seasons_observed=("season", "nunique"))
    t = pl.drop(columns="mlb_debut_date").merge(a, on="player_id", how="left")
    # debut with no hitting PA in the window (pinch-runner/defensive sub, pitcher, or a pre-2005 debut whose window
    # predates the data; the latter are flagged pre2005 and excluded from training) produced zero hitting value
    t["war_6yr"] = t.war_6yr.fillna(0.0)
    t["n_seasons_observed"] = t.n_seasons_observed.fillna(0).astype(int)
    t["censored"] = t.debut_season + 5 > 2026
    t["pre2005"] = t.debut_season < 2005
    t.to_parquet(DATA / "war_target.parquet")
    return t


def fetch_bwar():
    f = RAW / "bwar.csv"
    if not f.exists():
        r = requests.get(BWAR_URL, headers={"User-Agent": UA}, timeout=300)
        r.raise_for_status()  # blocked -> raises; validation test is then skipped, no workarounds
        f.write_bytes(r.content)
    return f


def validate(w):
    b = pd.read_csv(fetch_bwar(), low_memory=False)
    b = b[(b.pitcher == "N") & b.year_ID.between(2005, 2026)]
    for c in ["WAR", "runs_bat", "runs_br", "runs_dp", "runs_position", "runs_replacement"]:
        b[c] = pd.to_numeric(b[c], errors="coerce")
    b = b.groupby(["mlb_ID", "year_ID"]).agg(WAR=("WAR", "sum"), rb=("runs_bat", "sum"), rbr=("runs_br", "sum"),
                                             rdp=("runs_dp", "sum"), rp=("runs_position", "sum"),
                                             rr=("runs_replacement", "sum")).reset_index()
    j = w.merge(b, left_on=["player_id", "season"], right_on=["mlb_ID", "year_ID"])
    j = j[j.PA >= 300]
    j["b_off"] = (j.rb + j.rbr + j.rdp + j.rp + j.rr) / j.RPW  # bWAR offense incl. baserunning + DP
    j["off"] = j.owar - j.fld_runs / j.RPW  # our WAR without the borrowed fielding: tests our own components
    j["b_bsr"] = j.rbr + j.rdp
    return j


def main():
    w = war()
    t = target(w)
    print(f"mlb_war {len(w)} rows, war_target {len(t)} rows")
    try:
        j = validate(w)
    except Exception as e:  # validation is optional (C1); report and continue
        print("bWAR validation skipped:", e)
        return
    print(f"C1 (n={len(j)}): r vs bWAR WAR = {j.owar.corr(j.WAR):.4f}; "
          f"r offense-only vs bWAR (bat+br+dp+pos+repl)/RPW = {j.off.corr(j.b_off):.4f}; "
          f"r bsr_runs vs bWAR (runs_br+runs_dp) = {j.bsr_runs.corr(j.b_bsr):.4f}")


if __name__ == "__main__":
    main()
