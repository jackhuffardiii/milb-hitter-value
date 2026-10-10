"""B31 (v3 S36, DRAFT defaults): surplus $ for every 2026 40-man player, and the trade-asset table that joins them to the
v2 prospect board.

Per control year 2027-2032 (resolved from the B-Ref contract cells, B28, and service time):
- a dollar amount is guaranteed salary: surplus = value - salary, NOT floored (the club owes it);
- "Arb" (or a blank cell with 3-6 years of service entering the year) is arbitration: salary from the B30 model, fed the
  projected WAR path; surplus floored at 0 (non-tender);
- "Pre-Arb" / blank with under 3 years: league minimum, floored at 0 (option or release);
- "FA" (or 6+ years entering a blank year) ends control.
Options (B28 option_years): a team option is exercised when projected value beats its price, a player option when the
price beats his value; a declined option ends control. Mutual options are treated as declined, vesting options as
guaranteed. Value = projected WAR (B29) x $/WAR of the year; discounted to 2026 at the dollar_params rate (b8's economics).
Uncertainty: one talent draw per row (WAR + sd x z, the same z every year), sd = B29's next-season residual SD for the
player's projected-playing-time tercile, 199 normal quantiles; floors apply per draw.
Rookie-eligible players already on the v2 board keep their v2 value (their MLB sample is too small); the asset table marks
40-man membership for both. Writes data/mlb_values.parquet and data/trade_assets.parquet.
"""
import json
import re

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import config
from .b8_value import load_params
from .b30_arb import league_min, predict_arb
from .common import DATA

TEAM_NAMES = {"ARI": "Arizona Diamondbacks", "OAK": "Athletics", "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
              "BOS": "Boston Red Sox", "CHC": "Chicago Cubs", "CHW": "Chicago White Sox", "CIN": "Cincinnati Reds",
              "CLE": "Cleveland Guardians", "COL": "Colorado Rockies", "DET": "Detroit Tigers", "HOU": "Houston Astros",
              "KCR": "Kansas City Royals", "ANA": "Los Angeles Angels", "LAD": "Los Angeles Dodgers", "MIA": "Miami Marlins",
              "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins", "NYM": "New York Mets", "NYY": "New York Yankees",
              "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates", "SDP": "San Diego Padres", "SEA": "Seattle Mariners",
              "SFG": "San Francisco Giants", "STL": "St. Louis Cardinals", "TBR": "Tampa Bay Rays", "TEX": "Texas Rangers",
              "TOR": "Toronto Blue Jays", "WSN": "Washington Nationals"}
YEARS = list(range(config.PROJ_FIRST, config.PROJ_FIRST + config.PROJ_YEARS))
Z = norm.ppf(np.linspace(0.005, 0.995, 199))


def option_years(s):
    """'28' -> {2028}; '27-28' -> {2027, 2028}."""
    if not isinstance(s, str):
        return set()
    a = [2000 + int(x) for x in re.findall(r"\d+", s)]
    return set(range(a[0], a[-1] + 1)) if a else set()


def history():
    """Actual WAR by player-season (hitting + pitching), PT, starter flag, and last known salary."""
    h = pd.read_parquet(DATA / "mlb_war.parquet").groupby(["player_id", "season"]).agg(war_h=("owar", "sum"), pa=("PA", "sum"))
    p = pd.read_parquet(DATA / "mlb_pitch_war.parquet").groupby(["player_id", "season"]).agg(war_p=("pwar", "sum"), outs=("outs", "sum"), G=("G", "sum"), GS=("GS", "sum"))
    w = h.join(p, how="outer").fillna(0)
    w["war"] = w.war_h + w.war_p
    return w.reset_index()


def contract_years(c, prm, war):
    """Per row and year: status ('g' guaranteed, 'a' arb, 'p' pre-arb, None no control), listed salary. war: (n, years)."""
    n = len(c)
    status = np.full((n, len(YEARS)), None, dtype=object)
    price = np.full((n, len(YEARS)), np.nan)
    for i, r in enumerate(c.itertuples()):
        opts, done = option_years(r.option_years), False
        for j, y in enumerate(YEARS):
            if done:
                continue
            cell = getattr(r, f"raw_{y}", "") or ""
            sal = getattr(r, f"sal_{y}", np.nan) if f"sal_{y}" in c else np.nan
            svc = (r.service_years if pd.notna(r.service_years) else 0) + (y - config.PROJ_FIRST)  # service entering y
            value = war[i, j] * prm["dpw"] * (1 + prm["infl"]) ** (y - 2026)
            if y in opts and pd.notna(sal):
                keep = (value > sal) if r.team_option else (sal > value) if r.player_option else bool(r.vesting_option)
                if not keep:  # declined (mutual options count as declined): control ends
                    done = True
                    continue
            if pd.notna(sal):
                status[i, j], price[i, j] = "g", sal
            elif cell.startswith("FA") or (cell == "" and svc >= 6):
                done = True
            elif cell.startswith("Arb") or (cell == "" and svc >= 3):
                status[i, j] = "a"
            else:
                status[i, j] = "p"
    return status, price


def arb_salaries(c, status, war, hist):
    """Arbitration salary for each 'a' year, walking forward so each year sees the projected WAR and salary before it."""
    sal = np.full(status.shape, np.nan)
    last = hist[hist.season <= 2026].sort_values("season").groupby("player_id")
    career = last.war.sum()
    w3 = hist[hist.season.between(2024, 2026)].groupby("player_id").war.sum()
    s26 = hist[hist.season == 2026].set_index("player_id")
    paid = pd.read_parquet(DATA / "mlb_salaries.parquet").query("season == 2026 and pos != ''").dropna(subset=["player_id"])
    paid = paid.groupby("player_id").salary.sum()
    for i, r in enumerate(c.itertuples()):
        pid = r.player_id
        prev_war = float(s26.war.get(pid, 0.0)) if pid in s26.index else 0.0
        cw, hist3 = float(career.get(pid, 0.0)), [float(w3.get(pid, 0.0))]
        prev_rel = np.log(paid[pid] / league_min(2026)) if pid in paid.index and paid[pid] > 1.05 * league_min(2026) else np.nan
        starter = bool(pid in s26.index and s26.G.get(pid, 0) > 0 and s26.GS.get(pid, 0) / max(s26.G.get(pid, 1), 1) > .5)
        is_p = bool(pid in s26.index and s26.outs.get(pid, 0) > 3 * s26.pa.get(pid, 0))
        prev_pt = float(s26.outs.get(pid, 0) if is_p else s26.pa.get(pid, 0)) if pid in s26.index else 0.0
        recent = [prev_war]
        for j, y in enumerate(YEARS):
            if status[i, j] == "a":
                svc = (r.service_years if pd.notna(r.service_years) else 3) + (y - config.PROJ_FIRST)
                row = pd.DataFrame([dict(season=y, prev_war=prev_war, war_3yr=sum(recent[-3:]), career_war=cw,
                                         arb_year=int(min(3, max(1, np.floor(svc) - 2))), is_pitcher=is_p, is_starter=starter,
                                         prev_log_salary_rel=prev_rel, prev_pt=prev_pt)])
                sal[i, j] = float(predict_arb(row)[0])
                prev_rel = np.log(sal[i, j] / league_min(min(y, 2026)))
            prev_war = war[i, j]
            recent.append(war[i, j])
            cw += war[i, j]
    return sal


def mlb_values():
    prm = load_params()
    c = pd.read_parquet(DATA / "mlb_contracts_2026.parquet").dropna(subset=["player_id"]).drop_duplicates("player_id")
    proj = pd.read_parquet(DATA / "mlb_projections.parquet").set_index("player_id")
    c = c[c.player_id.isin(proj.index)].reset_index(drop=True)
    war = proj.loc[c.player_id, [f"war_{y}" for y in YEARS]].to_numpy()
    sd_tab = json.loads((DATA / "b29_c23.json").read_text())["residual_sd_by_pt_tercile"]
    pt = proj.loc[c.player_id, f"pt_{YEARS[0]}"].to_numpy()
    kind = proj.loc[c.player_id, "kind"].to_numpy()
    sd = np.array([sd_tab["pitcher" if k == "pitcher" else "hitter"][min(2, int(np.searchsorted(sd_tab["cuts_" + ("pitcher" if k == "pitcher" else "hitter")], p)))]
                   for k, p in zip(kind, pt)])
    status, price = contract_years(c, prm, war)
    hist = history()
    arb = arb_salaries(c, status, war, hist)
    yrs = np.array(YEARS)
    dpw = prm["dpw"] * (1 + prm["infl"]) ** (yrs - 2026)
    mn = prm["min"] * (1 + prm["min_g"]) ** (yrs - 2026)
    salary = np.where(status == "g", price, np.where(status == "a", arb, np.where(status == "p", mn[None, :], 0.0)))
    disc = (1 + prm["disc"]) ** (yrs - 2026)
    draws = war[:, None, :] + sd[:, None, None] * Z[None, :, None]  # (n, 199, years)
    value = draws * dpw
    sur = value - salary[:, None, :]
    floored = np.isin(status, ["a", "p"])[:, None, :]
    sur = np.where(floored, np.maximum(sur, 0), sur)
    sur = np.where((status == None)[:, None, :], 0, sur) / disc  # noqa: E711
    tot = sur.sum(axis=2)
    out = c[["player_id", "team", "name", "age", "service_years", "contract_summary"]].copy()
    out["kind"] = kind
    for j, y in enumerate(YEARS):
        out[f"war_{y}"], out[f"status_{y}"], out[f"salary_{y}"] = war[:, j], status[:, j], np.where(status[:, j] == None, np.nan, salary[:, j])  # noqa: E711
    out["control_years"] = (status != None).sum(axis=1)  # noqa: E711
    out["surplus"] = tot.mean(axis=1)
    for a in (0.1, 0.5, 0.9):
        out[f"surplus_q{int(a * 100)}"] = np.quantile(tot, a, axis=1)
    return out


def assets(mv):
    """MLB players (B31) and prospects (v2 board) in one table, by organization. v2 value wins for rookie-eligible players."""
    lb = pd.DataFrame(json.loads((DATA.parent / "site" / "data" / "leaderboard.json").read_text())["rows"])
    code = {v: k for k, v in TEAM_NAMES.items()}
    on40 = set(mv.player_id)
    pros = pd.DataFrame({"player_id": lb.id, "name": lb.name, "team": lb.org.map(code), "kind": np.where(lb.role == "H", "prospect_h", "prospect_p"),
                         "pos": lb.pos, "level": lb.level, "age": lb.age, "value": lb.ev * 1e6, "q10": lb.q10 * 1e6, "q90": lb.q90 * 1e6,
                         "war_next": np.nan, "salary_next": np.nan, "control_years": 6, "rank": lb["rank"]})
    pros = pros[pros.team.notna()]
    mlb = mv[~mv.player_id.isin(pros.player_id)]
    m = pd.DataFrame({"player_id": mlb.player_id, "name": mlb.name, "team": mlb.team, "kind": "mlb", "pos": mlb.kind, "level": "mlb",
                      "age": mlb.age, "value": mlb.surplus, "q10": mlb.surplus_q10, "q90": mlb.surplus_q90,
                      "war_next": mlb[f"war_{YEARS[0]}"], "salary_next": mlb[f"salary_{YEARS[0]}"], "control_years": mlb.control_years, "rank": np.nan})
    a = pd.concat([m, pros], ignore_index=True)
    a["on_40"] = a.player_id.isin(on40)
    sal = mv.set_index("player_id")[f"salary_{YEARS[0]}"]
    a.loc[a.on_40 & a.salary_next.isna(), "salary_next"] = a.player_id.map(sal)
    return a


def main():
    mv = mlb_values()
    mv.to_parquet(DATA / "mlb_values.parquet", index=False)
    a = assets(mv)
    a.to_parquet(DATA / "trade_assets.parquet", index=False)
    print(f"{len(mv)} MLB players valued (median surplus ${mv.surplus.median() / 1e6:.1f}M); {len(a)} trade assets")


if __name__ == "__main__":
    main()
