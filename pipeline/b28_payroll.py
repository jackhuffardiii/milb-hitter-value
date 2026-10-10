"""B28 (v3 DRAFT, D21): 2026 MLB contracts from Baseball-Reference team payroll pages.

One cached page per team (data/raw/bref_payroll/{TEAM}.html; the year-specific URL 301-redirects to the current-season page,
so this is a 2026 snapshot only). Table `payroll`, parsed with regex on data-stat attributes (no lxml in .venv): bbref id, age,
service time (years.days, 172 days a year), contract summary, salary cells 2026-2032. A cell is a dollar amount (guaranteed),
"Arb", "FA", or blank (pre-arbitration or not yet decided); negative amounts are cash flowing to the club, kept as-is.
Options (team, player, mutual, vesting) are parsed from the summary text; opt-outs are not shown there. bbref ids map to MLBAM ids through bWAR's player_ID -> mlb_ID.
Writes data/mlb_contracts_2026.parquet.
"""
import html
import re
import time

import pandas as pd
import requests

from .b2_war import UA
from .common import DATA, RAW

TEAMS = ["ARI", "OAK", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET", "HOU", "KCR", "ANA", "LAD", "MIA", "MIL",
         "MIN", "NYM", "NYY", "PHI", "PIT", "SDP", "SEA", "SFG", "STL", "TBR", "TEX", "TOR", "WSN"]
YEARS = range(2026, 2033)  # TEAMS are B-Ref franchise codes (Athletics: OAK, Angels: ANA)
DIRECT = {"ANA": "ANA/los-angeles-angels-salaries-and-contracts.shtml",  # their year URLs redirect to dead pages
          "WSN": "WSN/washington-nationals-salaries-and-contracts.shtml"}
CACHE = RAW / "bref_payroll"


def page(team):
    f = CACHE / f"{team}.html"
    if not f.exists():
        r = requests.get("https://www.baseball-reference.com/teams/" + DIRECT.get(team, f"{team}/2026-payroll-salaries.shtml"), headers={"User-Agent": UA}, timeout=120)
        r.raise_for_status()
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(r.text)
        time.sleep(4)  # Baseball-Reference allows about 20 requests a minute
    return f.read_text()


def money(x):
    m = re.fullmatch(r"(-?)\$([\d.]+)([MK]?)", x.replace(",", ""))
    if not m:
        return None
    v = float(m.group(2)) * {"M": 1e6, "K": 1e3, "": 1}[m.group(3)]
    return -v if m.group(1) else v


def parse(team, text):
    t = text[text.index('id="payroll"'):]
    t = t[:t.index("</table>")]
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        cells = dict(re.findall(r'data-stat="([a-z_0-9]+)"[^>]*>(.*?)</t[dh]>', tr, re.S))
        bid = re.search(r'/players/\w/(\w+)\.shtml', cells.get("player", ""))
        if not bid:
            continue  # header and total rows
        txt = {k: html.unescape(re.sub(r"<[^>]+>", "", v)).strip() for k, v in cells.items()}
        summ = txt.get("contract_summary", "")
        st = txt.get("service_time", "")
        row = dict(team=team, bbref_id=bid.group(1), name=txt["player"], age=pd.to_numeric(txt.get("age"), errors="coerce"),
                   service_time=pd.to_numeric(st, errors="coerce"), how_acquired=txt.get("how_acquired"), contract_summary=summ)
        opt = re.search(r"&\s*([\d-]+)\s+([a-z/]+) option", summ.lower())  # "& 28 team option", "& 27-28 player/mutual option"
        kinds = set(opt.group(2).split("/")) if opt else set()
        row.update({f"{k}_option": k in kinds for k in ("team", "player", "mutual", "vesting")}, option_years=opt.group(1) if opt else None)
        for i, y in enumerate(YEARS):
            cell = txt.get(f"contract_y{i}", "")
            row[f"raw_{y}"] = cell
            row[f"sal_{y}"] = money(cell)
        rows.append(row)
    return rows


def main():
    d = pd.DataFrame([r for t in TEAMS for r in parse(t, page(t))])
    d["service_years"] = d.service_time.floordiv(1) + (d.service_time % 1) * 1000 / 172
    ids = pd.concat([pd.read_csv(RAW / f, usecols=["player_ID", "mlb_ID"]) for f in ("bwar.csv", "bwar_pitch.csv")]).dropna().drop_duplicates("player_ID")
    d = d.merge(ids.rename(columns={"player_ID": "bbref_id", "mlb_ID": "player_id"}), on="bbref_id", how="left")
    d["player_id"] = d.player_id.astype("Int64")
    d.to_parquet(DATA / "mlb_contracts_2026.parquet", index=False)
    print(f"{len(d)} rows, {d.team.nunique()} teams, mlbam id for {d.player_id.notna().mean():.1%}; "
          f"options: " + ", ".join(f"{k} {int(d[k + '_option'].sum())}" for k in ("team", "player", "mutual", "vesting")))


if __name__ == "__main__":
    main()
