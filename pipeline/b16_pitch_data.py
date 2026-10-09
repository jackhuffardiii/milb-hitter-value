"""B16 pitcher data layer (spec S18, D13, D14, D15, D18, Q4, Q17).

Outputs (data/): milb_pitching_seasons, milb_pitch_history, mlb_pitching, pitch_players, il_2026 (.parquet),
b16_api_validation_2024.json. Mirrors b1_data for pitching: repo files cover MiLB 2005-2024 (D13), the Stats API
covers MiLB 2025-2026 (D14) and MLB 2005-2026 (D15, with the S3 missing-stint repair). Rates are recomputed
from counting stats (Q4); GB% is left to B18.
"""
import json
import re
import time

import numpy as np
import pandas as pd
import requests

from pipeline.b1_data import (API_MILB_YEARS, HISTORY_SPORTS, HISTORY_YEARS, LEVELS, MLB_YEARS, REPO_YEARS,
                              SPORT_LEVEL, _teams, _team_stats, players, pull_date)
from pipeline.common import DATA, RAW, api_get, download, pmap

REPO_URL = "https://github.com/armstjc/milb-data-repository/releases/download/season_player_pitching/{y}_{lv}_season_pitching_stats.csv"
SWING_YEAR = 2026  # repo 2026 files carry swings/whiffs; the API has none
PCOLS = ["G", "GS", "GF", "outs", "BF", "AB", "H", "2B", "3B", "HR", "TB", "BB", "IBB", "SO", "HBP", "SF", "GiDP",
         "GO", "AO", "FO", "PO", "LO", "FH", "PH", "LH", "pitches", "swings", "whiffs", "R", "ER"]
REPO_COLS = {"team_id": "team_id", "team_abv": "team_abv", "team_league_id": "league_id", "team_league": "league_name",
             "player_id": "player_id", "season": "season", "pitching_G": "G", "pitching_GS": "GS", "pitching_GF": "GF",
             "pitching_BF": "BF", "pitching_AB": "AB", "pitching_H": "H", "pitching_2B": "2B", "pitching_3B": "3B",
             "pitching_HR": "HR", "pitching_TB": "TB", "pitching_BB": "BB", "pitching_IBB": "IBB",
             "pitching_SO": "SO", "pitching_HBP": "HBP", "pitching_SF": "SF", "pitching_GiDP": "GiDP",
             "pitching_GO": "GO", "pitching_AO": "AO", "pitching_FO": "FO", "pitching_pop_outs": "PO",
             "pitching_line_outs": "LO", "pitching_FH": "FH", "pitching_PH": "PH", "pitching_LH": "LH",
             "pitching_PI": "pitches", "pitching_total_swings": "swings", "pitching_swing_and_misses": "whiffs",
             "batting_R": "R", "pitching_ER": "ER"}  # repo runs allowed sit in batting_R (pitching_R is runs scored)
API_STATS = {"gamesPitched": "G", "gamesStarted": "GS", "gamesFinished": "GF", "outs": "outs", "battersFaced": "BF",
             "atBats": "AB", "hits": "H", "doubles": "2B", "triples": "3B", "homeRuns": "HR", "totalBases": "TB",
             "baseOnBalls": "BB", "intentionalWalks": "IBB", "strikeOuts": "SO", "hitBatsmen": "HBP",
             "sacFlies": "SF", "groundIntoDoublePlay": "GiDP", "groundOuts": "GO", "airOuts": "AO",
             "numberOfPitches": "pitches", "runs": "R", "earnedRuns": "ER"}  # no swings/whiffs/FO/PO/LO/FH/PH/LH -> NaN
IL_SPORTS = [1, 11, 12, 13, 14, 16]


# ---------- MiLB stints ----------
def _repo_file(args):
    y, lv = args
    try:
        p = download(REPO_URL.format(y=y, lv=lv), RAW / "milb_pitching" / f"{y}_{lv}.csv")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None
        raise
    raw = pd.read_csv(p)
    d = raw[list(REPO_COLS)].rename(columns=REPO_COLS)
    ip10 = (raw["pitching_IP_str"] * 10).round()  # "123.1" = 123 and 1/3 innings
    d["outs"] = (ip10 // 10) * 3 + ip10 % 10
    d[["season", "team_id", "league_id", "player_id"]] = d[["season", "team_id", "league_id", "player_id"]].astype(int)
    d["level"] = lv
    return d[d.player_id > 0]  # one 2006 DSL row has player_id 0


def repo_swings(season=SWING_YEAR):
    parts = [p for p in pmap(_repo_file, [(season, lv) for lv in LEVELS]) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    return d.groupby(["player_id", "team_id", "level"], as_index=False)[["swings", "whiffs"]].sum(min_count=1)


def repo_stints():
    parts = pmap(_repo_file, [(y, lv) for y in REPO_YEARS for lv in LEVELS])
    d = pd.concat([p for p in parts if p is not None], ignore_index=True)
    d["source"] = "repo"
    return d


def _api_split_rows(splits, level):
    rows = []
    for s in splits:
        r = {v: s["stat"].get(k) for k, v in API_STATS.items()}
        r.update({c: None for c in ["FO", "PO", "LO", "FH", "PH", "LH", "swings", "whiffs"]})
        r.update(season=int(s["season"]), player_id=s["player"]["id"], team_id=s["team"]["id"],
                 league_id=s.get("league", {}).get("id"), league_name=s.get("league", {}).get("name"), level=level)
        rows.append(r)
    return rows


def api_stints(season):
    jobs, abv = [], {}
    for sport in SPORT_LEVEL:
        teams = _teams(sport, season)
        abv.update(teams)
        jobs += [(sport, season, t, "pitching") for t in teams]
    rows = []
    for (sport, *_), splits in zip(jobs, pmap(_team_stats, jobs)):
        rows += _api_split_rows(splits, SPORT_LEVEL[sport])
    d = pd.DataFrame(rows)
    d["team_abv"] = d["team_id"].map(abv)
    d["source"] = "statsapi"
    if season == SWING_YEAR:
        sw = repo_swings().rename(columns={"swings": "sw_repo", "whiffs": "wh_repo"})
        d = d.merge(sw, on=["player_id", "team_id", "level"], how="left")
        d["swings"], d["whiffs"] = d.pop("sw_repo"), d.pop("wh_repo")
    return d


def compare_2024(repo):
    """Pull 2024 via the API and compare counting stats to repo rows (validates IP parsing and the API mapping)."""
    api = api_stints(2024)
    key = ["player_id", "team_id", "level"]
    cols = ["G", "GS", "outs", "BF", "H", "2B", "3B", "HR", "BB", "SO", "HBP", "ER"]
    r = repo[repo.season == 2024].set_index(key)[cols]
    a = api.set_index(key)[cols]
    both = r.index.intersection(a.index)
    out = {"repo_rows": len(r), "api_rows": len(a), "joined_rows": len(both),
           "per_stat_equal": {c: float((r.loc[both, c] == a.loc[both, c]).mean()) for c in cols},
           "repo_rows_found_in_api": len(both) / len(r), "api_rows_found_in_repo": len(both) / len(a),
           "BF_total_repo": int(r.BF.sum()), "BF_total_api": int(a.BF.sum()),
           "outs_total_repo": int(r.outs.sum()), "outs_total_api": int(a.outs.sum())}
    (DATA / "b16_api_validation_2024.json").write_text(json.dumps(out, indent=1))
    print("2024 repo-vs-API:", json.dumps(out))


def aggregate_stints(d):
    """Sum stints at different teams in the same league -> grain player x season x level x league."""
    keys = ["player_id", "season", "level", "league_id"]
    g = d.groupby(keys)
    out = g[PCOLS].sum(min_count=1)
    out["league_name"] = g["league_name"].first()
    out["teams"] = g["team_abv"].agg(lambda s: "|".join(sorted(set(s.dropna()))))
    out["team_ids"] = g["team_id"].agg(lambda s: "|".join(str(x) for x in sorted(set(s))))
    out["source"] = g["source"].first()
    out = out.reset_index()
    for c in ["IBB", "HBP", "SF"]:
        out[c] = out[c].fillna(0)
    return out


def history():
    """Q17: MiLB 2000-2004 G, GS, BF, outs per player x season x level x league (Stats API, per team)."""
    jobs = [(sp, y, t, "pitching") for y in HISTORY_YEARS for sp in HISTORY_SPORTS for t in _teams(sp, y)]
    rows = []
    for (sp, *_), splits in zip(jobs, pmap(_team_stats, jobs)):
        rows += _api_split_rows(splits, HISTORY_SPORTS[sp])
    d = pd.DataFrame(rows)
    return d.groupby(["player_id", "season", "level", "league_id"], as_index=False)[["G", "GS", "BF", "outs"]].sum()


# ---------- MLB ----------
def _league_totals(season):
    d = api_get("stats", stats="season", group="pitching", sportId=1, season=season, playerPool="All", limit=5000)
    return {s["player"]["id"]: s["stat"]["battersFaced"] for s in d["stats"][0]["splits"]}


def _person_splits(args):
    pid, season = args
    d = api_get(f"people/{pid}/stats", stats="season", group="pitching", season=season, sportId=1)
    return [s for s in d["stats"][0]["splits"] if s.get("team")] if d["stats"] else []


def _fill_missing_stints(rows, season, teams):
    """S3: where a pitcher's team rows sum to fewer BF than the league-wide row, replace his rows with his own
    per-team splits."""
    have = {}
    for r in rows:
        have[r["player_id"]] = have.get(r["player_id"], 0) + (r["BF"] or 0)
    bad = {p for p, bf in _league_totals(season).items() if have.get(p, 0) != bf}
    fixed = [r for r in rows if r["player_id"] not in bad]
    for splits in pmap(_person_splits, [(p, season) for p in sorted(bad)]):
        for r in _api_split_rows(splits, "mlb"):
            r["team_abv"] = teams.get(r["team_id"])
            fixed.append(r)
    print(f"MLB {season}: {len(bad)} pitchers re-pulled for missing stints")
    return fixed


def mlb_pitching():
    rows = []
    for y in MLB_YEARS:
        teams = _teams(1, y)
        yr = []
        jobs = [(1, y, t, "pitching") for t in teams]
        for (_, _, t, _), splits in zip(jobs, pmap(_team_stats, jobs)):
            for r in _api_split_rows(splits, "mlb"):
                r["team_abv"] = teams[t]
                yr.append(r)
        rows += _fill_missing_stints(yr, y, teams)
    d = pd.DataFrame(rows).drop(columns=["level"])
    return d.groupby(["player_id", "season", "team_id"], as_index=False).agg(
        {**{c: (lambda s: s.sum(min_count=1)) for c in PCOLS}, "league_id": "first", "league_name": "first",
         "team_abv": "first"})


def add_pitch_rates(df):
    """Q4: rates from counts; zero denominators give NaN, never inf."""
    d = lambda s: s.where(s != 0)  # noqa: E731
    df["IP"] = df["outs"] / 3
    df["K_pct"], df["BB_pct"] = df["SO"] / d(df["BF"]), df["BB"] / d(df["BF"])
    df["HBP_pct"], df["HR_pct"] = df["HBP"] / d(df["BF"]), df["HR"] / d(df["BF"])
    df["K_BB_pct"] = df["K_pct"] - df["BB_pct"]
    df["BIP"] = df["BF"] - df["SO"] - df["BB"] - df["HBP"] - df["HR"]
    df["BABIP"] = (df["H"] - df["HR"]) / d(df["BIP"])
    df["XB_per_BIP"] = (df["2B"] + 2 * df["3B"]) / d(df["BIP"])  # extra bases per non-HR ball in play
    df["GS_share"] = df["GS"] / d(df["G"])
    df["outs_per_G"] = df["outs"] / d(df["G"])
    df["RA9"] = 27 * df["R"] / d(df["outs"])
    return df


def _age(df, pl):
    df = df.merge(pl[["player_id", "birth_date", "throws"]], on="player_id", how="left")
    df["age"] = (pd.to_datetime(df.season.astype(str) + "-07-01") - df.pop("birth_date")).dt.days / 365.25
    return df


# ---------- injured list ----------
def il_2026():
    """D18: injured-list placements, snapshot season 2026 (card display). sportId filters; one call per sport."""
    rows = {}
    for sp in IL_SPORTS:
        for t in api_get("transactions", startDate="2026-01-01", endDate="2026-12-31", sportId=sp)["transactions"]:
            desc = t.get("description") or ""
            if "placed" in desc and "injured list" in desc and t.get("person"):
                m = re.search(r"(\d+)-day injured list", desc)
                rows[t["id"]] = {"player_id": t["person"]["id"], "date": t.get("date"),
                                 "team_id": (t.get("toTeam") or {}).get("id"), "description": desc,
                                 "il_days": int(m[1]) if m else np.nan}
    d = pd.DataFrame(rows.values()).drop_duplicates(["player_id", "date", "team_id", "description"])  # API repeats ids
    d["date"] = pd.to_datetime(d["date"])
    return d


def main():
    t0 = time.time()
    DATA.mkdir(exist_ok=True)
    repo = repo_stints()
    compare_2024(repo)
    stints = pd.concat([repo] + [api_stints(y) for y in API_MILB_YEARS], ignore_index=True)
    milb = aggregate_stints(stints)
    hist = history()
    mlb = mlb_pitching()
    il = il_2026()
    ids = set(milb.player_id) | set(hist.player_id) | set(mlb.player_id)
    pl = players(ids)
    pl["pulled_on"] = pull_date(ids)

    milb = add_pitch_rates(_age(milb, pl))
    mlb = add_pitch_rates(_age(mlb, pl))
    milb.to_parquet(DATA / "milb_pitching_seasons.parquet", index=False)
    hist.to_parquet(DATA / "milb_pitch_history.parquet", index=False)
    mlb.to_parquet(DATA / "mlb_pitching.parquet", index=False)
    pl.to_parquet(DATA / "pitch_players.parquet", index=False)
    il.to_parquet(DATA / "il_2026.parquet", index=False)
    print(f"milb {len(milb)} rows, history {len(hist)}, mlb {len(mlb)}, players {len(pl)}, il {len(il)}; "
          f"{time.time() - t0:.0f}s")
