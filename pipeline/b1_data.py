"""B1 data layer (spec S1, S2, S3, D1, D3, D4, D5, D6, Q4).

Outputs (data/): milb_player_seasons, players, draft, mlb_seasons, mlb_fielding_games (.parquet).
Repo files cover MiLB 2005-2024 (D1); the MLB Stats API covers MiLB 2025-2026 (D3), per team so
stints keep team and league. Rates are always recomputed from counting stats (Q4).
"""
import json
import time

import numpy as np
import pandas as pd
import requests

from pipeline.common import API, COUNTS, DATA, RAW, add_rates, api_get, download, pmap

REPO_URL = "https://github.com/armstjc/milb-data-repository/releases/download/season_player_batting/{y}_{lv}_season_batting_stats.csv"
LEVELS = ["aaa", "aa", "a+", "a", "a-", "rk"]
REPO_YEARS = range(2005, 2025)
API_MILB_YEARS = [2025, 2026]
MLB_YEARS = range(2005, 2027)
DRAFT_YEARS = range(2005, 2027)
SPORT_LEVEL = {11: "aaa", 12: "aa", 13: "a+", 14: "a", 16: "rk"}  # a+ = High-A, a = Low-A (repo codes)

REPO_COLS = {"team_id": "team_id", "team_abv": "team_abv", "team_league_id": "league_id",
             "team_league": "league_name", "player_id": "player_id", "player_position": "position",
             "G": "G", "batting_PA": "PA", "batting_AB": "AB", "batting_H": "H", "batting_2B": "2B",
             "batting_3B": "3B", "batting_HR": "HR", "batting_BB": "BB", "batting_IBB": "IBB",
             "batting_HBP": "HBP", "batting_SO": "SO", "batting_SF": "SF", "batting_SH": "SH",
             "batting_SB": "SB", "batting_CS": "CS", "batting_GO": "GO", "batting_AO": "AO",
             "batting_pitches_faced": "pitches_faced", "batting_swings": "swings",
             "batting_whiffs": "whiffs", "season": "season"}
API_STATS = {"gamesPlayed": "G", "plateAppearances": "PA", "atBats": "AB", "hits": "H",
             "doubles": "2B", "triples": "3B", "homeRuns": "HR", "baseOnBalls": "BB",
             "intentionalWalks": "IBB", "hitByPitch": "HBP", "strikeOuts": "SO", "sacFlies": "SF",
             "sacBunts": "SH", "stolenBases": "SB", "caughtStealing": "CS", "groundOuts": "GO",
             "airOuts": "AO", "numberOfPitches": "pitches_faced"}  # API has no swings/whiffs -> NaN


# ---------- MiLB stints ----------
def _repo_file(args):
    y, lv = args
    try:
        p = download(REPO_URL.format(y=y, lv=lv), RAW / "milb_batting" / f"{y}_{lv}.csv")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None
        raise
    d = pd.read_csv(p)
    d = d[list(REPO_COLS)].rename(columns=REPO_COLS)
    d["level"] = lv
    return d


def repo_stints():
    parts = pmap(_repo_file, [(y, lv) for y in REPO_YEARS for lv in LEVELS])
    d = pd.concat([p for p in parts if p is not None], ignore_index=True)
    d["source"] = "repo"
    return d


def _api_split_rows(splits, level):
    rows = []
    for s in splits:
        st = s["stat"]
        r = {v: st.get(k) for k, v in API_STATS.items()}
        r.update(swings=None, whiffs=None)
        r.update(season=int(s["season"]), player_id=s["player"]["id"], team_id=s["team"]["id"],
                 league_id=s.get("league", {}).get("id"), league_name=s.get("league", {}).get("name"),
                 position=s.get("position", {}).get("abbreviation"), level=level)
        rows.append(r)
    return rows


def _team_stats(args):
    sport, season, team, group = args
    d = api_get("stats", stats="season", group=group, sportId=sport, season=season, teamId=team,
                playerPool="All", limit=5000)
    return d["stats"][0]["splits"] if d["stats"] else []


def _teams(sport, season):
    return {t["id"]: t.get("abbreviation") for t in api_get("teams", sportId=sport, season=season)["teams"]}


def api_stints(season):
    jobs, abv = [], {}
    for sport in SPORT_LEVEL:
        teams = _teams(sport, season)
        abv.update(teams)
        jobs += [(sport, season, t, "hitting") for t in teams]
    rows = []
    for (sport, *_), splits in zip(jobs, pmap(_team_stats, jobs)):
        rows += _api_split_rows(splits, SPORT_LEVEL[sport])
    d = pd.DataFrame(rows)
    d["team_abv"] = d["team_id"].map(abv)
    d["source"] = "statsapi"
    return d


def compare_2024(repo):
    """Verify the API approach: pull 2024 via API, compare counting stats to repo rows."""
    api = api_stints(2024)
    key = ["player_id", "team_id", "level"]
    cols = ["G", "PA", "AB", "H", "2B", "3B", "HR", "BB", "SO", "SB"]
    r = repo[repo.season == 2024].set_index(key)[cols]
    a = api.set_index(key)[cols]
    both = r.index.intersection(a.index)
    eq_all = (r.loc[both].fillna(-1).astype(int) == a.loc[both].fillna(-1).astype(int)).all(axis=1)
    out = {"repo_rows": len(r), "api_rows": len(a), "joined_rows": len(both),
           "joined_all_counting_stats_equal": float(eq_all.mean()),
           "per_stat_equal": {c: float((r.loc[both, c] == a.loc[both, c]).mean()) for c in cols},
           "repo_rows_found_in_api": len(both) / len(r), "api_rows_found_in_repo": len(both) / len(a),
           "PA_total_repo": int(r.PA.sum()), "PA_total_api": int(a.PA.sum())}
    (DATA / "b1_api_validation_2024.json").write_text(json.dumps(out, indent=1))
    print("2024 repo-vs-API:", json.dumps(out))
    return out


def _primary_pos(df, keys):
    t = df[keys + ["position", "G"]].dropna(subset=["position"]).copy()
    t["tok"] = t["position"].str.split("/")
    t = t.explode("tok")
    t["w"] = t["G"].fillna(0) + 0.001
    w = t.groupby(keys + ["tok"])["w"].sum().reset_index().sort_values(keys + ["w", "tok"], ascending=[True] * len(keys) + [False, True])
    return w.drop_duplicates(keys).set_index(keys)["tok"].rename("primary_pos_milb")


def aggregate_stints(d):
    """Sum stints at different teams in the same league -> grain player x season x league."""
    keys = ["player_id", "season", "level", "league_id"]
    g = d.groupby(keys)
    out = g[COUNTS].sum(min_count=1)
    out["league_name"] = g["league_name"].first()
    out["teams"] = g["team_abv"].agg(lambda s: "|".join(sorted(set(s.dropna()))))
    out["team_ids"] = g["team_id"].agg(lambda s: "|".join(str(x) for x in sorted(set(s))))
    out["source"] = g["source"].first()
    out = out.join(_primary_pos(d, keys)).reset_index()
    for c in ["IBB", "HBP", "SF", "SH"]:  # missing in a source means none recorded, needed for OBP
        out[c] = out[c].fillna(0)
    return out


# ---------- MLB ----------
def mlb_hitting_fielding():
    hit, fld = [], []
    for y in MLB_YEARS:
        teams = _teams(1, y)
        jobs = [(1, y, t, g) for t in teams for g in ("hitting", "fielding")]
        for (_, _, t, g), splits in zip(jobs, pmap(_team_stats, jobs)):
            if g == "hitting":
                for r in _api_split_rows(splits, "mlb"):
                    r["team_abv"] = teams[t]
                    hit.append(r)
            else:
                for s in splits:
                    st = s["stat"]
                    fld.append({"player_id": s["player"]["id"], "season": y, "team_id": t,
                                "position": s["position"]["abbreviation"], "games": st.get("games"),
                                "games_started": st.get("gamesStarted"),
                                "innings": float(str(st.get("innings", 0) or 0).replace(",", ""))})
    h = pd.DataFrame(hit).drop(columns=["level"])
    h = h.groupby(["player_id", "season", "team_id"], as_index=False).agg(
        {**{c: (lambda s: s.sum(min_count=1)) for c in COUNTS}, "league_id": "first", "league_name": "first",
         "team_abv": "first", "position": "first"})
    f = pd.DataFrame(fld).groupby(["player_id", "season", "position"], as_index=False)[
        ["games", "games_started", "innings"]].sum()
    return h, f


# ---------- draft ----------
def draft():
    rows = []
    for y in DRAFT_YEARS:
        for rd in api_get(f"draft/{y}")["drafts"]["rounds"]:
            for p in rd["picks"]:
                person = p.get("person") or {}
                sch = p.get("school") or {}
                rows.append({"draft_year": y, "round": p.get("pickRound"), "pick_overall": p.get("pickNumber"),
                             "pick_in_round": p.get("roundPickNumber"), "player_id": person.get("id"),
                             "full_name": person.get("fullName"), "team_id": (p.get("team") or {}).get("id"),
                             "signing_bonus": p.get("signingBonus"), "pick_value": p.get("pickValue"),
                             "school": sch.get("name"), "school_class": sch.get("schoolClass"),
                             "school_state": sch.get("state"), "school_country": sch.get("country"),
                             "draft_type": (p.get("draftType") or {}).get("code"),
                             "position": (person.get("primaryPosition") or {}).get("abbreviation")})
    d = pd.DataFrame(rows).drop_duplicates()  # API repeats 2008 pick 127 once
    for c in ["signing_bonus", "pick_value"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["player_id"] = d["player_id"].astype("Int64")
    return d


# ---------- players ----------
def _people(chunk):
    return api_get("people", personIds=",".join(map(str, chunk)))["people"]


def players(ids):
    ids = sorted(ids)
    res = pmap(_people, [ids[i:i + 100] for i in range(0, len(ids), 100)])
    rows = [{"player_id": p["id"], "full_name": p.get("fullName"), "birth_date": p.get("birthDate"),
             "bats": (p.get("batSide") or {}).get("code"), "throws": (p.get("pitchHand") or {}).get("code"),
             "primary_pos": (p.get("primaryPosition") or {}).get("abbreviation"),
             "mlb_debut_date": p.get("mlbDebutDate"), "draft_year": p.get("draftYear")}
            for chunk in res for p in chunk]
    d = pd.DataFrame(rows).drop_duplicates("player_id").set_index("player_id").reindex(ids).reset_index()
    for c in ["birth_date", "mlb_debut_date"]:
        d[c] = pd.to_datetime(d[c], errors="coerce")
    d["draft_year"] = d["draft_year"].astype("Int64")
    return d


def main():
    t0 = time.time()
    DATA.mkdir(exist_ok=True)
    repo = repo_stints()
    compare_2024(repo)
    stints = pd.concat([repo] + [api_stints(y) for y in API_MILB_YEARS], ignore_index=True)
    milb = aggregate_stints(stints)

    mlb, fld = mlb_hitting_fielding()
    dr = draft()
    ids = set(milb.player_id) | set(mlb.player_id) | set(fld.player_id) | set(dr.player_id.dropna())
    pl = players(ids)

    milb = milb.merge(pl[["player_id", "birth_date", "bats"]], on="player_id", how="left")
    milb["age"] = (pd.to_datetime(milb.season.astype(str) + "-07-01") - milb.pop("birth_date")).dt.days / 365.25
    milb = add_rates(milb)
    mlb = add_rates(mlb.merge(pl[["player_id", "birth_date"]], on="player_id", how="left")
                    .assign(age=lambda x: (pd.to_datetime(x.season.astype(str) + "-07-01") - x.pop("birth_date")).dt.days / 365.25))
    milb.to_parquet(DATA / "milb_player_seasons.parquet", index=False)
    pl.to_parquet(DATA / "players.parquet", index=False)
    dr.to_parquet(DATA / "draft.parquet", index=False)
    mlb.to_parquet(DATA / "mlb_seasons.parquet", index=False)
    fld.to_parquet(DATA / "mlb_fielding_games.parquet", index=False)
    print(f"milb {len(milb)} rows, players {len(pl)} ({int(pl.birth_date.isna().sum())} without birth_date), "
          f"draft {len(dr)}, mlb {len(mlb)}, fielding {len(fld)}; {time.time() - t0:.0f}s")
