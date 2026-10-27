"""B32 (v3 S39, C26, DRAFT defaults): trade simulator data and the real-trade replay.

site/data/trade.json feeds the browser simulator (site/trade.html, app.js initTrade): every organization's assets (B31: MLB
players on the 40-man with contract surplus, v2 prospects with expected surplus), team-neutral values in $M (S40 contender
adjustment not applied; NBA precedent), each team's projected 2027 payroll and 40-man count. The browser does the rest:
value in minus value out per side, 40-man limit (config.ROSTER_MAX), payroll vs config.CBT_THRESHOLD_2027.
C26 replay -> data/b32_c26.json: trades in ~/Projects/mlb-trade-web trades.json made after the v3 declaration date (the
pre-registered test; empty until trades happen), plus an informational replay of 2026 trades from July 1. That one has
look-ahead (values use the full 2026 season) and only counts assets we value; it is reported, never tuned on.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .b31_mlb_value import TEAM_NAMES
from .b9_site import RUN_DATE, SITE, dump, r
from .common import DATA

TRADES = Path.home() / "Projects" / "mlb-trade-web" / "public" / "data" / "trades.json"
DECLARED = "2026-10-10"  # v3 declaration date: trades after it are the pre-registered replay set
FAIR = 10e6  # a trade is "even" when the two sides' value gains are within this many dollars


def site_json(a):
    teams = []
    for code, name in sorted(TEAM_NAMES.items(), key=lambda x: x[1]):
        t = a[a.team == code]
        teams.append(dict(code=code, name=name, payroll=r(t.loc[t.on_40, "salary_next"].sum() / 1e6, 1), n40=int(t.on_40.sum())))
    rows = [dict(id=int(x.player_id), name=x.name, team=x.team, kind=x.kind, pos=x.pos if isinstance(x.pos, str) else None,
                 level=x.level, age=r(x.age, 1), v=r(x.value / 1e6, 2), q10=r(x.q10 / 1e6, 1), q90=r(x.q90 / 1e6, 1),
                 war=r(x.war_next, 1), sal=r(x.salary_next / 1e6, 2), ctrl=int(x.control_years), on40=bool(x.on_40),
                 rank=None if pd.isna(x.rank) else int(x.rank))
            for x in a.sort_values("value", ascending=False).itertuples()]
    dump(SITE / "trade.json", dict(run_date=RUN_DATE, season=2027, cbt=config.CBT_THRESHOLD_2027 / 1e6, roster_max=config.ROSTER_MAX,
                                   fair=FAIR / 1e6, teams=teams, assets=rows))


def replay(a):
    if not TRADES.exists():
        return {"available": False}
    t = json.loads(TRADES.read_text())
    tid = {x["id"]: next((c for c, n in TEAM_NAMES.items() if n == x["name"]), None) for x in t["teams"]}
    val = a.set_index("player_id").value
    out = {"declared": DECLARED, "trades_file_generated": t["generated"]}
    for name, sel in (("after_declaration", lambda d: d > DECLARED), ("informational_2026_from_jul1", lambda d: d >= "2026-07-01")):
        gaps, cover = [], []
        for tr in (x for x in t["trades"] if sel(x["date"])):
            gain = {}
            players = [s for s in tr["assets"] if s.get("kind") == "player"]
            if len({tid.get(s["toTeamId"]) for s in players}) != 2:
                continue  # two-team player trades only
            known = [s for s in players if s["personId"] in val.index]
            cover.append(len(known) / len(players))
            for s in known:
                gain[tid[s["toTeamId"]]] = gain.get(tid[s["toTeamId"]], 0) + val[s["personId"]]
                gain[tid[s["fromTeamId"]]] = gain.get(tid[s["fromTeamId"]], 0) - val[s["personId"]]
            if len(known) == len(players) and len(gain) == 2:
                gaps.append(abs(list(gain.values())[0]))
        g = np.array(gaps)
        out[name] = {"two_team_trades": len(cover), "fully_valued": int(len(g)),
                     "mean_asset_coverage": float(np.mean(cover)) if cover else None,
                     "median_gap_m": float(np.median(g) / 1e6) if len(g) else None,
                     "share_within_fair": float((g <= FAIR).mean()) if len(g) else None}
    return out


def main():
    a = pd.read_parquet(DATA / "trade_assets.parquet")
    site_json(a)
    res = replay(a)
    (DATA / "b32_c26.json").write_text(json.dumps(res, indent=1))
    meth = json.loads((SITE / "method.json").read_text())  # methodology page reads the v3 numbers from here
    meth["v3"] = {"c23": json.loads((DATA / "b29_c23.json").read_text()), "c24": json.loads((DATA / "b30_c24.json").read_text()),
                  "c26": res, "n_mlb": int((a.kind == "mlb").sum()), "n_assets": len(a), "fair": FAIR / 1e6}
    dump(SITE / "method.json", meth)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
