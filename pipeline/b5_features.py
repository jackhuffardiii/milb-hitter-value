"""B5: model-ready snapshot table (A10, S7 features part, S8 prior population, Q5, Q7, A2, A3).

One row per non-pitcher x offseason season s (2005-2026) who played affiliated MiLB in s (not Mexican League) and is
rookie-eligible at end of s (career MLB AB through s < 130). group 'stat' (>=150 PA at A..AAA over s and s-1, Q7, and
complete reg_ MLE for s) else 'prior' (S8). Labels: reached_mlb, eta_years, war_6yr (B6 uses split == 'train_era' only).
Outputs: data/position_transition.parquet, data/features.parquet.
"""
import numpy as np
import pandas as pd

from .b2_war import POS_RUNS
from .common import DATA

LVL = {"rk": 0, "a-": 0.5, "a": 1, "a+": 2, "aa": 3, "aaa": 4}
POS9 = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
RATES = ["K", "BB", "ISO", "BABIP"]
MEXICAN_LEAGUE = 125
YEARS = range(2005, 2027)


def build_transition(snap, fld, players):
    """P(MLB primary pos | MiLB primary pos, level_group) from s<=2017 snapshots of players who reached MLB."""
    deb = players.set_index("player_id").mlb_debut_date.dt.year
    f = fld[fld.position != "P"].merge(deb.rename("dy"), left_on="player_id", right_index=True)
    f = f[(f.season >= f.dy) & (f.season <= f.dy + 2)]
    mlb_pos = f.groupby(["player_id", "position"]).games.sum().reset_index().sort_values(["player_id", "games"])
    mlb_pos = mlb_pos.groupby("player_id").position.last().rename("mlb_pos")  # no fielding rows -> absent -> DH
    t = snap[(snap.season <= 2017) & snap.level_group.notna() & snap.reached_mlb & (snap.debut_year >= 2005)].copy()
    t = t.merge(mlb_pos, left_on="player_id", right_index=True, how="left")
    t["mlb_pos"] = t.mlb_pos.where(t.mlb_pos.isin(POS9), "DH")
    cnt = t.groupby(["level_group", "milb_pos", "mlb_pos"]).size().rename("n").reset_index()
    tot = t.groupby(["level_group", "mlb_pos"]).size().rename("n").reset_index().assign(milb_pos="_ALL")
    cnt = pd.concat([cnt, tot])
    grid = pd.MultiIndex.from_product([cnt[["level_group", "milb_pos"]].drop_duplicates().apply(tuple, axis=1), POS9])
    grid = pd.DataFrame([(a, b, c) for (a, b), c in grid], columns=["level_group", "milb_pos", "mlb_pos"])
    out = grid.merge(cnt, how="left").fillna({"n": 0})
    out["n"] = out.n.astype(int)
    out["p"] = (out.n + 1) / out.groupby(["level_group", "milb_pos"]).n.transform(lambda x: x.sum() + len(POS9))
    return out


def main():
    S = pd.read_parquet(DATA / "milb_player_seasons.parquet")
    pl = pd.read_parquet(DATA / "players.parquet")
    S = S[(S.league_id != MEXICAN_LEAGUE) & (S.primary_pos_milb != "P")]
    S = S[~S.player_id.isin(pl.loc[pl.primary_pos == "P", "player_id"])]
    S = S.assign(lv=S.level.map(LVL))
    # mlb career AB through season s
    mb = pd.read_parquet(DATA / "mlb_seasons.parquet").groupby(["player_id", "season"]).AB.sum().reset_index()

    # one row per player-season: highest level, PA there, position and team there
    S = S.sort_values(["player_id", "season", "lv", "PA"])
    g = S.groupby(["player_id", "season"])
    top = g.tail(1).set_index(["player_id", "season"])
    snap = pd.DataFrame({"highest_level": top.level, "level_num": top.lv, "milb_pos": top.primary_pos_milb,
                         "team": top.teams, "age": g.age.last()})
    snap["bats"] = top.bats
    snap["PA_s"] = g.PA.sum()
    snap = snap.reset_index()
    hl = S.merge(snap[["player_id", "season", "highest_level"]], on=["player_id", "season"])
    hl = hl[hl.level == hl.highest_level].groupby(["player_id", "season"]).PA.sum().rename("PA_highest")
    snap = snap.merge(hl.reset_index(), on=["player_id", "season"])
    # career MiLB PA through s, first MiLB season
    ps = S.groupby(["player_id", "season"]).PA.sum().reset_index().sort_values(["player_id", "season"])
    ps["career_milb_pa"] = ps.groupby("player_id").PA.cumsum()
    ps["pro_years"] = ps.season - ps.groupby("player_id").season.transform("min") + 1
    snap = snap.merge(ps[["player_id", "season", "career_milb_pa", "pro_years"]], on=["player_id", "season"])
    # age vs level: PA-weighted league-level mean age (all affiliated hitters, A-ball and up and below)
    a = S.dropna(subset=["age"]).assign(wa=lambda d: d.age * d.PA).groupby(["season", "level"])[["wa", "PA"]].sum()
    snap = snap.merge((a.wa / a.PA).rename("lvl_age").reset_index(), left_on=["season", "highest_level"],
                      right_on=["season", "level"], how="left").drop(columns="level")
    snap["age_vs_level"] = snap.age - snap.lvl_age
    snap = snap.drop(columns="lvl_age")

    # rookie eligibility
    mb = mb.sort_values(["player_id", "season"])
    mb["cum_ab"] = mb.groupby("player_id").AB.cumsum()
    c = snap[["player_id", "season"]].merge(mb, on="player_id", suffixes=("", "_m"))
    c = c[c.season_m <= c.season].groupby(["player_id", "season"]).AB.sum().rename("mlb_ab_thru")
    snap = snap.merge(c.reset_index(), on=["player_id", "season"], how="left")
    snap = snap[snap.mlb_ab_thru.fillna(0) < 130].drop(columns="mlb_ab_thru")
    snap = snap[snap.season.isin(YEARS)]

    # stat group (Q7): A..AAA PA over s and s-1 >= 150 and complete reg_ for s
    aaa = S[S.lv >= 1].groupby(["player_id", "season"]).PA.sum()
    prev = aaa.rename("pa_prev").reset_index().assign(season=lambda d: d.season + 1)
    snap = snap.merge(aaa.rename("pa_cur").reset_index(), on=["player_id", "season"], how="left")
    snap = snap.merge(prev, on=["player_id", "season"], how="left")
    snap["pa_two"] = snap.pa_cur.fillna(0) + snap.pa_prev.fillna(0)
    mle = pd.read_parquet(DATA / "mle_player_season.parquet")
    regc = [f"reg_{c}" for c in RATES]
    mc = mle[["player_id", "season", "PA"] + regc].rename(columns={"PA": "mle_PA"})
    snap = snap.merge(mc, on=["player_id", "season"], how="left")
    snap["group"] = np.where((snap.pa_two >= 150) & snap[regc].notna().all(axis=1), "stat", "prior")
    stat = snap.group == "stat"
    snap.loc[~stat, regc] = np.nan
    # Marcel blend s (w=3) + s-1 (w=2), weighted by PA*w, and trajectory
    p = mc.assign(season=mc.season + 1).rename(columns={c: "p_" + c for c in regc + ["mle_PA"]})
    snap = snap.merge(p, on=["player_id", "season"], how="left")
    for r in RATES:
        x0, x1, w0, w1 = snap[f"reg_{r}"], snap[f"p_reg_{r}"], 3 * snap.mle_PA, 2 * snap.p_mle_PA
        w1 = w1.where(x1.notna(), 0)
        snap[f"blend_{r}"] = (x0 * w0 + x1.fillna(0) * w1) / (w0 + w1)
        snap[f"delta_{r}"] = x0 - x1
    snap = snap.drop(columns=["pa_cur", "pa_prev", "pa_two", "mle_PA", "p_mle_PA"] + ["p_" + c for c in regc])
    snap["level_group"] = np.where(stat, np.where(snap.level_num <= 2, "low", "high"), None)

    # labels
    snap = snap.merge(pl[["player_id", "full_name", "mlb_debut_date"]].rename(columns={"full_name": "name"}),
                      on="player_id", how="left")
    snap["debut_year"] = snap.mlb_debut_date.dt.year
    snap["reached_mlb"] = snap.debut_year.notna()
    snap["eta_years"] = (snap.debut_year - snap.season).clip(lower=0).where(snap.reached_mlb)
    snap = snap.merge(pd.read_parquet(DATA / "war_target.parquet")[["player_id", "war_6yr"]], on="player_id", how="left")
    snap.loc[~snap.reached_mlb, "war_6yr"] = np.nan

    # transition matrix (A10) and positional features
    tm = build_transition(snap, pd.read_parquet(DATA / "mlb_fielding_games.parquet"), pl)
    tm.to_parquet(DATA / "position_transition.parquet", index=False)
    wide = tm.pivot(index=["level_group", "milb_pos"], columns="mlb_pos", values="p")[POS9]
    fall = wide.xs("_ALL", level="milb_pos")  # milb positions never seen in train snapshots
    pm = snap[["level_group", "milb_pos"]].drop_duplicates().dropna()
    rows = [wide.loc[(lg, mp)] if (lg, mp) in wide.index else fall.loc[lg] for lg, mp in zip(pm.level_group, pm.milb_pos)]
    P = pd.DataFrame(rows, index=pd.MultiIndex.from_frame(pm))
    P["exp_pos_runs"] = P[POS9] @ pd.Series({k: POS_RUNS[k] for k in POS9})
    P = P.rename(columns={"C": "p_C", "SS": "p_SS", "CF": "p_CF"})[["p_C", "p_SS", "p_CF", "exp_pos_runs"]].reset_index()
    snap = snap.merge(P, on=["level_group", "milb_pos"], how="left")

    # draft features (latest record on or before s; international = none)
    d = pd.read_parquet(DATA / "draft.parquet").dropna(subset=["player_id"])
    d = d.assign(player_id=d.player_id.astype(int), round_num=pd.to_numeric(d["round"], errors="coerce"))
    d = d.sort_values(["player_id", "draft_year"])[["player_id", "draft_year", "round_num", "pick_overall",
                                                    "signing_bonus"]]
    snap = snap.merge(d.groupby("player_id").tail(1).rename(columns={"draft_year": "dy"}), on="player_id", how="left")
    ok = snap.dy.notna() & (snap.dy <= snap.season)
    snap["international"] = ~ok
    snap["draft_year"] = snap.dy.where(ok)
    snap["years_since_draft"] = snap.season - snap.draft_year
    for c in ["round_num", "pick_overall", "signing_bonus"]:
        snap[c] = snap[c].where(ok)
    snap = snap.drop(columns=["dy", "mlb_debut_date"])
    snap["split"] = np.select([snap.season <= 2017, snap.season <= 2025], ["train_era", "censored"], "score")
    snap = snap.sort_values(["season", "player_id"]).reset_index(drop=True)
    snap.to_parquet(DATA / "features.parquet", index=False)

    print(snap.groupby(["split", "group"]).size().unstack())
    te = snap[(snap.split == "train_era") & (snap.group == "stat")]
    print(te.groupby("highest_level").reached_mlb.agg(["mean", "size"]))
    print(tm[(tm.level_group == "high") & tm.milb_pos.isin(["SS", "C", "CF"])]
          .pivot(index="milb_pos", columns="mlb_pos", values="p")[POS9].round(3))
    r = snap[snap.reached_mlb & (snap.split == "train_era")]
    print("train_era reached rows lacking war_6yr:", r.war_6yr.isna().sum(), "of", len(r),
          "| unique players:", r[r.war_6yr.isna()].player_id.nunique())


if __name__ == "__main__":
    main()
