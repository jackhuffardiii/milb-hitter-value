"""B9: export site JSON (S11, S13, S16, C5, C7, U1, U2; v1.1 adds C10-C12, Q17, Q18). Reads parquet/json outputs, writes site/data/*.json.

Players: 2026 'final' rows of valuations.parquet. Rerunnable after any upstream rerun (python run.py b9).
Dollar values are exported in millions of USD (rounded) so JSON stays small.
"""
import datetime
import io
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from pipeline.b11_batted import BBT
from pipeline.common import DATA, MANUAL, RAW, ROOT, _get, api_get

SITE = ROOT / "site" / "data"
SEASON = 2026
LEVEL_ORDER = ["aaa", "aa", "a+", "a", "a-", "rk"]
SPORT_LEVEL = {11: "aaa", 12: "aa", 13: "a+", 14: "a", 16: "rk"}


def r(x, n=3):
    """Round to n places; NaN/None -> None."""
    if x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x)):
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    return round(float(x), n)


def m(x):
    """USD -> millions, 3 places."""
    return r(x / 1e6, 3) if pd.notna(x) else None


# v1.1 audit (2026-10-06, v1 features, s<=2012 GroupKFold CV; holdout untouched): dropping reg_/blend_/delta_BABIP
BABIP_ABLATION = dict(logloss_with=0.4142, logloss_without=0.4151, ev_spearman_with=0.1416, ev_spearman_without=0.1401,
                      r_yoy_mle=0.435, r_next_mlb=0.108, n_next_mlb=1065, driver_share_p_mlb_v1=0.126)
RUN_DATE = datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def data_through():
    """Last game date in the 2026 Savant cache (tracked AAA/FSL games; the other 2026 sources carry season totals only)."""
    last = ""
    for f in sorted((DATA / "raw" / "savant").glob(f"{SEASON}-*.parquet")):
        d = pd.read_parquet(f, columns=["game_date"])
        if len(d):
            last = max(last, str(d.game_date.max())[:10])
    return last


HAND = {"vl": "LHP", "vr": "RHP"}
# Savant pitch_type codes by family; Savant minors only covers tracked parks (AAA, Low-A FSL)
PITCH_FAMILY = {"Fastball": "FF|SI|FC|FA", "Breaking": "SL|ST|SV|CU|KC|CS", "Offspeed": "CH|FS|FO|SC|KN|EP"}
SAVANT_SPLITS = RAW / "savant_splits"


def hand_splits(seasons):
    """(player_id, season, level) -> [vs LHP, vs RHP] lines, Stats API statSplits vl/vr, one league-wide call per sport-season."""
    rows = []
    for y in seasons:
        for sid, lv in SPORT_LEVEL.items():
            for x in api_get("stats", stats="statSplits", group="hitting", sitCodes="vl,vr", sportId=sid, season=y,
                             playerPool="all", limit=10000)["stats"][0]["splits"]:
                t = x["stat"]
                rows.append(dict(player_id=x["player"]["id"], season=y, level=lv, hand=HAND[x["split"]["code"]], PA=t["plateAppearances"],
                                 AB=t["atBats"], H=t["hits"], TB=t["totalBases"], BB=t["baseOnBalls"], HBP=t["hitByPitch"],
                                 SF=t["sacFlies"], SO=t["strikeOuts"], HR=t["homeRuns"]))
    d = pd.DataFrame(rows).groupby(["player_id", "season", "level", "hand"], as_index=False).sum()
    d["AVG"], d["SLG"] = d.H / d.AB, d.TB / d.AB
    d["OBP"] = (d.H + d.BB + d.HBP) / (d.AB + d.BB + d.HBP + d.SF)
    d["ISO"], d["K"], d["BBp"] = d.SLG - d.AVG, d.SO / d.PA, d.BB / d.PA  # same K%/BB% definitions as milb_player_seasons
    return d


def savant_family(season, fam):
    """Savant minors batter rows for one pitch family and season, grouped by player; cached CSV."""
    f = SAVANT_SPLITS / f"{season}_{fam}.csv"
    if not f.exists():
        url = (f"https://baseballsavant.mlb.com/statcast-search-minors/csv?all=true&hfPT={PITCH_FAMILY[fam].replace('|', '%7C')}%7C"
               f"&hfGT=R%7C&hfSea={season}%7C&player_type=batter&group_by=name&minors=true&min_pitches=0&min_results=0&min_pas=0"
               f"&sort_col=pitches&sort_order=desc")
        SAVANT_SPLITS.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_get(url).content)
    d = pd.read_csv(f, encoding="utf-8-sig")
    assert len(d) < 25000, f"Savant row cap hit on {f.name}"
    return d.assign(season=season, family=fam)


def savant_family_bip(season, fam, month):
    """Tracked balls in play (batter, EV) for one pitch family and month; one month keeps each query under Savant's row cap."""
    f = SAVANT_SPLITS / f"bip_{season}_{month:02d}_{fam}.parquet"
    if not f.exists():
        start = f"{season}-{month:02d}-01"
        end = (pd.Timestamp(start) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        url = (f"https://baseballsavant.mlb.com/statcast-search-minors/csv?all=true&hfPT={PITCH_FAMILY[fam].replace('|', '%7C')}%7C"
               f"&hfGT=R%7C&hfSea={season}%7C&player_type=batter&game_date_gt={start}&game_date_lt={end}&type=details&minors=true&hfBBT={BBT}")
        txt = _get(url).content.decode("utf-8-sig")
        d = pd.read_csv(io.StringIO(txt), low_memory=False) if txt.strip() else pd.DataFrame(columns=["batter", "launch_speed", "launch_angle", "des", "bb_type", "type"])
        assert len(d) < 24000, f"Savant row cap hit on {f.name}"
        d = d[(d.type == "X") & d.launch_speed.notna() & d.launch_angle.notna()]
        d = d[~d.des.fillna("").str.contains(r"\bbunt", regex=True) & ~d.bb_type.fillna("").str.contains("bunt")]  # same BIP filter as B11
        SAVANT_SPLITS.mkdir(parents=True, exist_ok=True)
        d[["batter", "launch_speed"]].to_parquet(f, index=False)
        time.sleep(0.2)
    return pd.read_parquet(f).astype({"batter": "Int64", "launch_speed": float}).assign(season=season, family=fam)


def pitch_splits(seasons):
    """(player_id, season) -> one row per pitch family: pitches seen, share of all pitches, AVG, SLG, wOBA, whiff%, avg EV, EV90."""
    d = pd.concat([savant_family(y, fam) for y in seasons for fam in PITCH_FAMILY], ignore_index=True)
    d["whiff"] = d.whiffs / d.swings.where(d.swings > 0)
    jobs = [(y, fam, mo) for y in seasons for fam in PITCH_FAMILY for mo in range(3, 11)]
    with ThreadPoolExecutor(4) as ex:  # same concurrency cap as B11
        bip = pd.concat(list(ex.map(lambda j: savant_family_bip(*j), jobs)), ignore_index=True)
    ev90 = bip.groupby(["batter", "season", "family"]).launch_speed.quantile(0.9).rename("ev90").reset_index()
    return d.merge(ev90, left_on=["player_id", "season", "family"], right_on=["batter", "season", "family"], how="left")


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False))


def teams():
    """team_id -> (name, parent org name, level, venue) for MiLB 2026, via cached Stats API."""
    out = {}
    for sid in SPORT_LEVEL:
        for t in api_get("teams", sportId=sid, season=SEASON)["teams"]:
            out[t["id"]] = dict(name=t["name"], org=t.get("parentOrgName"), venue=t.get("venue", {}).get("name"))
    return out


def ply_names():
    return pd.read_parquet(DATA / "players.parquet").set_index("player_id").full_name.to_dict()


def c1():
    from pipeline.b2_war import validate
    w = pd.read_parquet(DATA / "mlb_war.parquet")
    j = validate(w)
    names = pd.read_parquet(DATA / "players.parquet").set_index("player_id").full_name
    j["resid"] = j.owar - j.WAR
    j["name"] = j.player_id.map(names)
    row = lambda x: dict(name=x["name"], season=int(x.season), owar=r(x.owar, 1), bwar=r(x.WAR, 1))  # noqa: E731
    return dict(n=len(j), r_owar_bwar=r(j.owar.corr(j.WAR), 4), r_owar_vs_bwar_offense=r(j.off.corr(j.b_off), 4),
                r_bsr_vs_bwar_br_dp=r(j.bsr_runs.corr(j.b_bsr), 4), threshold=0.85, min_pa=300,
                glove_first=[row(x) for _, x in j.nsmallest(5, "resid").iterrows()],
                bat_first=[row(x) for _, x in j.nlargest(5, "resid").iterrows()])


def park_examples(tm):
    pf = pd.read_parquet(DATA / "park_factors.parquet")
    a = pf[(pf.sport == "milb") & (pf.season == SEASON) & (pf.level == "aaa")].copy()
    a["name"] = a.team_id.map(lambda t: tm.get(t, {}).get("name"))
    a["venue"] = a.team_id.map(lambda t: tm.get(t, {}).get("venue"))
    a = a.dropna(subset=["name"]).sort_values("pf_HR")
    pick = lambda d: [dict(team=x["name"], venue=x["venue"], pf_HR=r(x.pf_HR), pf_SO=r(x.pf_SO), pf_BABIP=r(x.pf_BABIP), pf_R=r(x.pf_R))  # noqa: E731
                      for _, x in d.iterrows()]
    return dict(season=SEASON, level="aaa", lowest_hr=pick(a.head(3)), highest_hr=pick(a.tail(3)[::-1]),
                note="pf = regressed factor, 1.0 neutral; a player's park adjustment uses half the factor (home games only).")


def translation_table():
    t = pd.read_parquet(DATA / "translation_factors.parquet")
    t = t[(t.season == 0) & (t.league_id == -1)]
    return [dict(from_level=x.from_level, component=x.component, factor=r(x.factor), n_pairs=int(x.n_pairs)) for _, x in t.iterrows()]


def sensitivity(names):
    """Top-10 ev_surplus (2026 final) at $/WAR growth 0.58% (base), 3% and 7%, via b8_value.value (read-only reuse)."""
    from pipeline.b8_value import load_params, value, war_profile
    prm, prof = load_params(), war_profile()
    pr = pd.read_parquet(DATA / "predictions_final.parquet")
    pr = pr[(pr.fit == "final") & (pr.season == SEASON)]
    ft = pd.read_parquet(DATA / "features.parquet", columns=["player_id", "season", "debut_year"])
    pr = pr.merge(ft, on=["player_id", "season"], how="left")
    out = []
    for g in (prm["infl"], 0.03, 0.07):
        v = value(pr, prof, {**prm, "infl": g, "min_g": g}).sort_values("ev_surplus", ascending=False).head(10)
        out.append(dict(growth=r(g, 4), top=[dict(name=names.get(i), ev=m(e)) for i, e in zip(v.player_id, v.ev_surplus)]))
    return out


def method(tm, n_players, grp_counts):
    bt = json.loads((DATA / "backtest.json").read_text())
    b6 = json.loads((DATA / "b6_metrics.json").read_text())
    c8 = json.loads((DATA / "b11_c8.json").read_text())
    c9 = json.loads((DATA / "b12_c9.json").read_text())
    c8.pop("k_grid_rmse", None)
    dis = lambda L: [dict(name=x["name"], list_year=x["list_year"], list_rank=x["rank"], model_rank=x["model_rank_within_list"],  # noqa: E731
                          p_mlb=r(x["p_mlb"]), realized_war=r(x["realized"], 1), reached=x["reached"]) for x in L]
    dp = pd.read_csv(MANUAL / "dollar_params.csv")
    prof = pd.read_parquet(DATA / "war_profile.parquet")
    names = ply_names()
    ho = lambda d: {k: v for k, v in d.items() if k != "calibration"}  # noqa: E731
    bb = pd.read_parquet(DATA / "batted_ball.parquet")
    ms = pd.read_parquet(DATA / "milb_player_seasons.parquet")
    return dict(
        run_date=RUN_DATE, data_through=data_through(), season=SEASON,
        C1=c1(), park_examples=park_examples(tm), translation_factors=translation_table(),
        model_choice=dict(chosen=b6["chosen_stat"], cv=b6["cv_stat"], spread=b6["spread"],
                          calibration_check={k: {kk: v[kk] for kk in ("max_abs_gap", "platt_applied", "n_rows", "tail")}
                                             for k, v in b6["calibration_check"].items()}),
        holdout={k: {kk: ho(vv) for kk, vv in v.items()} for k, v in b6["holdout"].items()},
        C2=bt["C2"], C3=bt["C3"], C4=bt["C4"], C12=bt["C12"], holdout_looks=bt["holdout_looks"], sources=bt["sources"],
        backtest_note=bt["note"], C10=json.loads((DATA / "b4_k.json").read_text())["C10"],
        babip=BABIP_ABLATION, people_pulled_on=str(pd.read_parquet(DATA / "players.parquet").pulled_on.iloc[0].date()),
        disagreements=dict(model_higher=dis(bt["disagreements"]["model_higher_than_list"]),
                           model_lower=dis(bt["disagreements"]["model_lower_than_list"])),
        realized_definition=bt["realized_definition"],
        C8=c8, C9=c9, sensitivity=sensitivity(names),
        dollar_params=[dict(param=x.param, value=r(x.value, 4), unit=x.unit, source_url=None if pd.isna(x.source_url) else x.source_url,
                            note=x.source_note) for _, x in dp.iterrows()],
        war_profile=[dict(control_year=int(x.control_year), mean_owar=r(x.mean_owar), share=r(x.share), n=int(x.n_players)) for _, x in prof.iterrows()],
        coverage=dict(players_2026=n_players, stat=grp_counts.get("stat", 0), prior=grp_counts.get("prior", 0),
                      milb_player_season_rows=len(ms), milb_seasons=f"{ms.season.min()}-{ms.season.max()} (no 2020)",
                      tracked_bip_rows=int(bb.n_bip_tracked.sum()), tracked_player_seasons=len(bb)),
    )


def main():
    np.seterr(all="ignore")  # PA == 0 rows give NaN rates, exported as null
    v = pd.read_parquet(DATA / "valuations.parquet")
    v = v[(v.fit == "final") & (v.season == SEASON)].copy()
    pf = pd.read_parquet(DATA / "predictions_final.parquet")
    pf = pf[(pf.fit == "final") & (pf.season == SEASON)].set_index("player_id")
    ft = pd.read_parquet(DATA / "features.parquet")
    ft = ft[(ft.season == SEASON) & (ft.split == "score")].set_index("player_id")
    ply = pd.read_parquet(DATA / "players.parquet").set_index("player_id")
    ms = pd.read_parquet(DATA / "milb_player_seasons.parquet")
    mle = pd.read_parquet(DATA / "mle.parquet")
    ppk = pd.read_parquet(DATA / "milb_player_park.parquet")
    bb = pd.read_parquet(DATA / "batted_ball.parquet")
    dg = pd.read_parquet(DATA / "drivers_grouped.parquet")
    dg = dg[(dg.fit == "final") & (dg.season == SEASON)]
    pt = pd.read_parquet(DATA / "position_transition.parquet").query("cutoff == 2017")
    tm = teams()
    seasons = range(SEASON - 2, SEASON + 1)
    hs, ps = hand_splits(seasons), pitch_splits(seasons)
    THROUGH = data_through()

    # sort for rank and org
    v = v.sort_values("ev_surplus", ascending=False).reset_index(drop=True)
    v["rank"] = np.arange(1, len(v) + 1)
    ids = set(v.player_id)

    cur = ms[(ms.season == SEASON) & ms.player_id.isin(ids)].copy()
    cur["lv"] = cur.level.map({l: i for i, l in enumerate(LEVEL_ORDER)})
    top = cur.sort_values(["player_id", "lv", "PA"], ascending=[True, True, False]).drop_duplicates("player_id").set_index("player_id")
    org_of = {}
    for pid, row in top.iterrows():
        tid = int(str(row.team_ids).split("|")[0]) if pd.notna(row.team_ids) else None
        org_of[pid] = (tm.get(tid, {}).get("org"), tm.get(tid, {}).get("name"))

    def pos_probs(pid):
        f = ft.loc[pid]
        pos = f.milb_pos if pd.notna(f.milb_pos) else "_ALL"
        lg = "high" if f.highest_level in ("aa", "aaa") else "low"
        d = pt[(pt.level_group == lg) & (pt.milb_pos == pos)]
        if d.empty:
            d = pt[(pt.level_group == lg) & (pt.milb_pos == "_ALL")]
        d = d.sort_values("p", ascending=False)
        return [[x.mlb_pos, r(x.p)] for _, x in d.iterrows() if x.p >= 0.02][:6]

    pos_cache = {}
    lb = []
    for x in v.itertuples():
        pid = x.player_id
        f = ft.loc[pid]
        pp = pos_probs(pid)
        pos_cache[pid] = pp
        org, tname = org_of.get(pid, (None, None))
        lb.append(dict(id=int(pid), name=f["name"], org=org, team=tname, level=f.highest_level, age=r(f.age, 1),
                       pos=f.milb_pos if pd.notna(f.milb_pos) else None, mlb_pos=pp[0][0] if pp else None,
                       group=x.group, low_conf=bool(x.low_confidence), p_mlb=r(x.p_mlb, 4), war=r(x.war_mean, 2),
                       eta=None if x.debuted else r(x.eta_mean, 2), ev=m(x.ev_surplus), q10=m(x.surplus_q10), q90=m(x.surplus_q90),
                       rank=int(x.rank), in_mlb=bool(x.debuted)))
    pulled = str(ply.pulled_on.iloc[0].date())
    dump(SITE / "leaderboard.json", dict(season=SEASON, run_date=RUN_DATE, data_through=data_through(), people_pulled_on=pulled, rows=lb))

    # player cards
    pdir = SITE / "players"
    if pdir.exists():
        shutil.rmtree(pdir)
    ms_by = {k: g for k, g in ms[ms.season >= SEASON - 2].groupby("player_id")}
    mle_by = {k: g for k, g in mle[mle.season == SEASON].groupby("player_id")}
    ppk_by = {k: g for k, g in ppk[ppk.season == SEASON].groupby("player_id")}
    bb_by = {k: g for k, g in bb[bb.season >= SEASON - 1].groupby("player_id")}
    hs_by = {k: g for k, g in hs.groupby("player_id")}
    ps_by = {k: g for k, g in ps.groupby("player_id")}
    lv_rank = {l: i for i, l in enumerate(LEVEL_ORDER)}
    fam_rank = {f: i for i, f in enumerate(PITCH_FAMILY)}
    dg_by = {k: g for k, g in dg.groupby("player_id")}
    drivers_target = lambda g, tgt: [dict(family=y.family, c=r(y.contribution, 3), phrase=y.phrase, sup=int(bool(y.suppressed)))  # noqa: E731
                                     for y in g[g.target == tgt].sort_values("rank").itertuples()]
    pd_cols = [c for c in v.columns if c.startswith("p_debut_")]
    for x in v.itertuples():
        pid = x.player_id
        f = ft.loc[pid]
        p = pf.loc[pid]
        hist = []
        h = ms_by.get(pid)
        if h is not None:
            h = h.assign(lv=h.level.map({l: i for i, l in enumerate(LEVEL_ORDER)})).sort_values(["season", "lv"], ascending=[False, True])
            for y in h.itertuples():
                hist.append(dict(season=int(y.season), level=y.level, G=int(y.G), PA=int(y.PA), AVG=r(y.AVG), OBP=r(y.OBP), SLG=r(y.SLG),
                                 K=r(y.K_pct), BB=r(y.BB_pct), ISO=r(y.ISO), BABIP=r(y.BABIP)))
        chain = []
        c = mle_by.get(pid)
        if c is not None:
            raw = ms_by[pid]
            raw = raw[raw.season == SEASON].set_index(["level", "league_id"])
            pk = ppk_by.get(pid)
            pk = pk.set_index(["level", "league_id"]) if pk is not None else None
            for y in c.assign(lv=c.level.map({l: i for i, l in enumerate(LEVEL_ORDER)})).sort_values("lv").itertuples():
                key = (y.level, y.league_id)
                s = raw.loc[key]
                ppf = pk.loc[key] if pk is not None and key in pk.index else None
                bip = y.BIP
                row = dict(level=y.level, PA=int(y.PA), AB=int(y.AB), BIP=int(bip))
                row["K"] = [r(s.SO / s.PA), r(y.neutral_K), r(y.mle_K), r(y.reg_K)]
                row["BB"] = [r((s.BB - s.IBB + s.HBP) / s.PA), r(y.neutral_BB), r(y.mle_BB), r(y.reg_BB)]
                row["ISO"] = [r(s.ISO), r(y.neutral_ISO), r(y.mle_ISO), r(y.reg_ISO)]
                row["BABIP"] = [r(s.BABIP), r(y.neutral_BABIP), r(y.mle_BABIP), r(y.reg_BABIP)]
                row["park"] = None if ppf is None else dict(SO=r(ppf.ppf_SO), BB=r(ppf.ppf_BB), B2B3B=r(ppf.ppf_2B3B), HR=r(ppf.ppf_HR), BABIP=r(ppf.ppf_BABIP))
                chain.append(row)
        bbl = []
        g = bb_by.get(pid)
        if g is not None:
            for y in g.sort_values("season", ascending=False).itertuples():
                bbl.append(dict(season=int(y.season), level=y.level, n=int(y.n_bip_tracked), ev=r(y.avg_ev, 1), ev90=r(y.ev90, 1), hh=r(y.hard_hit_pct, 3),
                                la=r(y.avg_la, 1), sweet=r(y.sweet_spot_pct, 3), barrel=r(y.barrel_pct, 3), share=r(y.share_bip_tracked, 2)))
        g = hs_by.get(pid)
        hand = [] if g is None else [
            dict(season=int(y.season), level=y.level, hand=y.hand, PA=int(y.PA), AVG=r(y.AVG), OBP=r(y.OBP), SLG=r(y.SLG), ISO=r(y.ISO), K=r(y.K), BB=r(y.BBp))
            for y in g.assign(lv=g.level.map(lv_rank)).sort_values(["season", "lv", "hand"], ascending=[False, True, True]).itertuples()]
        g = ps_by.get(pid)
        pitch = [] if g is None else [
            dict(season=int(y.season), family=y.family, n=int(y.pitches), share=r(y.pitch_percent / 100), PA=r(y.pa, 0), AVG=r(y.ba), SLG=r(y.slg),
                 wOBA=r(y.woba), whiff=r(y.whiff), ev=r(y.launch_speed, 1), ev90=r(y.ev90, 1))
            for y in g.assign(fr=g.family.map(fam_rank)).sort_values(["season", "fr"], ascending=[False, True]).itertuples()]
        dd = dg_by.get(pid)
        pl = ply.loc[pid] if pid in ply.index else None
        card = dict(
            id=int(pid), name=f["name"], season=SEASON, run_date=RUN_DATE, people_pulled_on=pulled, data_through=THROUGH, rank=int(x.rank), n_ranked=len(v),
            org=org_of.get(pid, (None, None))[0], team=org_of.get(pid, (None, None))[1], level=f.highest_level, age=r(f.age, 1),
            group=x.group, low_conf=bool(x.low_confidence), s14_applied=bool(x.s14_applied),
            bio=dict(bats=f.bats if pd.notna(f.bats) else None, height_in=r(f.height_in, 0), weight_lb=r(f.weight_lb, 0),
                     pos=f.milb_pos if pd.notna(f.milb_pos) else None, age_vs_level=r(f.age_vs_level, 1),
                     draft=None if f.international or pd.isna(f.pick_overall) else dict(year=r(f.draft_year, 0), round=r(f.round_num, 0), pick=r(f.pick_overall, 0),
                                                                                       bonus=r(f.signing_bonus, 0)),
                     international=bool(f.international)),
            hist=hist, hand=hand, pitch=pitch, chain=chain,
            blend=None if x.group != "stat" else dict(K=r(f.blend_K), BB=r(f.blend_BB), ISO=r(f.blend_ISO),
                                                      reg_K=r(f.reg_K), reg_BB=r(f.reg_BB), reg_ISO=r(f.reg_ISO),
                                                      contact=r(f.blend_contact_rate)),  # BABIP is display only (S7 v1.1)
            in_mlb=None if not x.debuted else dict(debut=str(ply.loc[pid].mlb_debut_date.date()),
                                                   control_years_left=int(max(0, 6 - (SEASON - int(f.debut_year) + 1)))),
            p_mlb=r(x.p_mlb, 4), war=dict(mean=r(x.war_mean, 2), q10=r(x.war_q10, 2), q50=r(x.war_q50, 2), q90=r(x.war_q90, 2)),
            eta=None if x.debuted else dict(mean=r(x.eta_mean, 2), q10=r(p.eta_q10, 2), q90=r(p.eta_q90, 2),
                                            debut={c[-4:]: r(x._asdict()[c], 4) for c in pd_cols}),
            surplus=dict(if_mlb=m(x.surplus_if_mlb), q10=m(x.surplus_q10), q50=m(x.surplus_q50), q90=m(x.surplus_q90), ev=m(x.ev_surplus)),
            drivers=dict(p_mlb=[] if dd is None else drivers_target(dd, "p_mlb"), war=[] if dd is None else drivers_target(dd, "war")),
            batted=bbl, pos_probs=pos_cache[pid],
        )
        dump(pdir / f"{pid}.json", card)

    grp = v.group.value_counts().to_dict()
    dump(SITE / "method.json", method(tm, len(v), grp))
    size = sum(f.stat().st_size for f in (ROOT / "site").rglob("*") if f.is_file())
    print(f"leaderboard rows {len(lb)}, player JSONs {len(list(pdir.glob('*.json')))}, site size {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
