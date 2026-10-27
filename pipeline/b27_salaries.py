"""B27 (v3 DRAFT, D19, C27): MLB salaries 2000-2026 and service time 2010-2026 from Cot's workbook, joined to MLBAM ids.

Source: data/raw/cots/mlb_salaries_2000_2026.xlsx (hand-downloaded, gitignored; one sheet per season, "Last, First", position,
MLS as years.days from 2010, that season's salary). Read with the standard library (no openpyxl in .venv).
Join (Q12 rule, never guesses): b7_top100 name keys against MLB players who appeared in s-2..s+1 (salaried players can miss a full
season injured; MLB data starts 2005, so 2000-04 rows stay unmatched); pitcher vs position player breaks ties; anything still ambiguous is rejected.
Writes data/mlb_salaries.parquet and data/b27_c27.json. Rows without a salary (40-man players listed with MLS only) are kept,
salary NaN. A blank-position row is a former club's deferred money or buyout for that player.
"""
import json
import re
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from .b7_top100 import keys
from .common import DATA, RAW

SRC = RAW / "cots" / "mlb_salaries_2000_2026.xlsx"
_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def read_xlsx(path):
    """Sheet name -> rows (lists of str or None); shared strings resolved."""
    z = zipfile.ZipFile(path)
    ss = ["".join(t.text or "" for t in si.iter(_M + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_M + "si")]
    rels = {r.get("Id"): r.get("Target").lstrip("/") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find(_M + "sheets"):
        tgt = rels[sh.get(_RID)]
        rows = []
        for row in ET.fromstring(z.read(tgt if tgt.startswith("xl/") else "xl/" + tgt)).iter(_M + "row"):
            vals = {}
            for c in row.findall(_M + "c"):
                v = c.find(_M + "v")
                i = sum((ord(ch) - 64) * 26 ** k for k, ch in enumerate(reversed(re.match(r"[A-Z]+", c.get("r")).group()))) - 1
                if c.get("t") == "s" and v is not None:
                    vals[i] = ss[int(v.text)]
                elif c.get("t") == "inlineStr":
                    vals[i] = "".join(x.text or "" for x in c.iter(_M + "t"))
                elif v is not None:
                    vals[i] = v.text
            rows.append([vals.get(i) for i in range(max(vals) + 1)] if vals else [])
        out[sh.get("name")] = rows
    return out


def parse():
    rows = []
    for name, sheet in read_xlsx(SRC).items():
        season = int(name[:4])
        hdr_i = next(i for i, r in enumerate(sheet) if r and r[0] == "Player")
        has_mls = "MLS" in sheet[hdr_i]
        for r in sheet[hdr_i + 1:]:
            if not r or not r[0] or "," not in r[0]:  # totals/average rows and blanks
                continue
            r = r + [None] * 4
            last, first = [x.strip() for x in r[0].split(",", 1)]
            mls = r[2] if has_mls else None
            sal = r[3] if has_mls else r[2]
            rows.append(dict(season=season, name=f"{first} {last}", pos=(r[1] or "").lower(), mls=mls, salary=sal))
    d = pd.DataFrame(rows)
    d["mls"], d["salary"] = pd.to_numeric(d.mls, errors="coerce"), pd.to_numeric(d.salary, errors="coerce")  # e.g. "forfeited"
    # MLS years.days: 172 days = one service year
    d["service_years"] = np.floor(d.mls) + (d.mls - np.floor(d.mls)) * 1000 / 172
    return d.drop_duplicates(["season", "name", "pos", "salary"])


def candidates():
    """MLBAM player-seasons in MLB (any PA or BF) with names and pitcher flag."""
    pl = pd.concat([pd.read_parquet(DATA / f)[["player_id", "full_name"]] for f in ("players.parquet", "pitch_players.parquet")]).drop_duplicates("player_id")
    h = pd.read_parquet(DATA / "mlb_war.parquet")[["player_id", "season"]].assign(p=False)
    p = pd.read_parquet(DATA / "mlb_pitch_war.parquet")[["player_id", "season"]].assign(p=True)
    a = pd.concat([h, p]).groupby(["player_id", "season"]).p.max().reset_index().merge(pl, on="player_id")
    return a.assign(ks=a.full_name.fillna("").map(keys))


def match(d, cand):
    idx = {}  # (season, name key) -> {(player_id, is_pitcher)}
    for r in cand.itertuples():
        for k in r.ks:
            idx.setdefault((r.season, k), set()).add((r.player_id, r.p))
    ids, status = [], []
    for r in d.itertuples():
        hits = set().union(*[idx.get((s, k), set()) for s in range(r.season - 2, r.season + 2) for k in keys(r.name)])
        pid = {h[0] for h in hits}
        if len(pid) > 1:  # tie-break: pitcher listing vs pitcher record
            is_p = "hp" in r.pos or r.pos in ("p", "sp", "rp")
            pid = {h[0] for h in hits if h[1] == is_p}
        ids.append(int(next(iter(pid))) if len(pid) == 1 else pd.NA)
        status.append("matched" if len(pid) == 1 else ("ambiguous" if len(pid) > 1 else "unmatched"))
    d = d.assign(player_id=pd.array(ids, dtype="Int64"), match_status=status)
    # two listed players (both with a position) on one id in a season are two people sharing a name: reject both.
    # A blank-position row is money owed by a former club (deferred salary, buyout), so it stays with its player.
    listed = (d.match_status == "matched") & (d.pos != "")
    clash = listed & d[listed].duplicated(["season", "player_id"], keep=False).reindex(d.index, fill_value=False)
    d.loc[clash, ["player_id", "match_status"]] = [pd.NA, "ambiguous"]
    return d


def main():
    d = match(parse(), candidates())
    d.to_parquet(DATA / "mlb_salaries.parquet", index=False)
    paid = d[d.salary.notna() & (d.season >= 2010)]
    out = {"rows": len(d), "paid_2010_2026": len(paid), "matched_share_paid_2010_2026": float((paid.match_status == "matched").mean()),
           "by_status": paid.match_status.value_counts().to_dict(),
           "c27_pass": bool((paid.match_status == "matched").mean() >= 0.95),
           "unmatched_examples": paid[paid.match_status != "matched"][["season", "name", "pos", "match_status"]].head(25).to_dict("records")}
    (DATA / "b27_c27.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: v for k, v in out.items() if k != "unmatched_examples"}))


if __name__ == "__main__":
    main()
