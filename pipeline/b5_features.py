"""B5: model-ready snapshot table (A10, S7 features part, S8 prior population, S15, Q5, Q7, Q15, Q16, A2, A3).

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
ORD = {"rk": 0, "a-": 1, "a": 2, "a+": 3, "aa": 4, "aaa": 5}  # ladder ordinals for progression pace
S15_GROUPS = {
    "contact": ["contact_rate", "swing_rate", "blend_contact_rate", "blend_swing_rate"],
    "batted": ["gb_rate", "fb_rate", "ld_rate", "pu_rate", "gofb", "blend_gb_rate", "blend_fb_rate",
               "blend_ld_rate", "blend_pu_rate", "blend_gofb"],
    "speed": ["sb_att_rate", "sb_success", "triple_rate"],
    "posmix": ["pos_share_SS", "pos_share_CF", "pos_share_C"],
    "pace": ["games_at_current_level", "ascent_pace", "levels_climbed_s", "repeated_level"],
    "body": ["height_in"],  # weight_lb/bmi stay in features.parquet for display only (Q15 look-ahead: listed weights are updated post-snapshot)
}
S15_KEPT = ["contact_rate", "swing_rate", "blend_contact_rate", "blend_swing_rate", "sb_att_rate", "sb_success",
            "triple_rate", "pos_share_SS", "pos_share_CF", "pos_share_C",
            "height_in"]  # v1.1 C9 rerun (data/b12_c9.json): contact, speed, posmix, body kept; pace dropped


def _blend(A, cols, w):
    """3:2 weighted blend of season s with s-1 (weights 3*w, 2*w_prev); a missing side gets weight 0."""
    P = A[["player_id", "season", w] + cols].assign(season=A.season + 1)
    M = A.merge(P, on=["player_id", "season"], how="left", suffixes=("", "_p"))
    for c in cols:
        w0, w1 = 3 * M[w].where(M[c].notna(), 0), 2 * M[w + "_p"].where(M[c + "_p"].notna(), 0)
        M["blend_" + c] = (M[c].fillna(0) * w0 + M[c + "_p"].fillna(0) * w1) / (w0 + w1).where(lambda x: x > 0)
    return M[["player_id", "season"] + ["blend_" + c for c in cols]]


def s15_features(S, snap, pl, hist):
    """S15 features for every snapshot row (caller blanks non-stat rows). S: filtered milb seasons with `lv`.
    Contact/batted/speed use A..AAA rows of season s only (blend adds s-1); detail rows with no data are skipped.
    Batted-ball mix is not park-adjusted. Contact is NaN for 2025 (no swings data, Q16): 2026 uses 2026 alone."""
    k = ["player_id", "season"]
    H = S[S.lv >= 1]
    # contact (swings > 0 marks real repo data; repo holds 0 where untracked)
    c = H[H.swings > 0].groupby(k).agg(sw=("swings", "sum"), wh=("whiffs", "sum"), pf=("pitches_faced", "sum"), w_c=("PA", "sum"))
    c["contact_rate"], c["swing_rate"] = 1 - c.wh / c.sw, c.sw / c.pf.where(c.pf > 0)
    c = c.reset_index()
    # batted-ball mix: detailed types where present (repo through 2024), GO/AO ratio where only that exists
    d = H.assign(gb=H.GO + H.ground_hits, fb=H.FO + H.fly_hits, ld=H.LO + H.line_hits, pu=H.PO + H.pop_hits)
    d["bip"] = d[["gb", "fb", "ld", "pu"]].sum(axis=1, min_count=4)
    b = d[d.bip > 0].groupby(k)[["gb", "fb", "ld", "pu", "bip", "PA"]].sum()
    for x in ("gb", "fb", "ld", "pu"):
        b[x + "_rate"] = b[x] / b.bip
    b = b.reset_index().rename(columns={"PA": "w_b"})[k + ["gb_rate", "fb_rate", "ld_rate", "pu_rate", "w_b"]]
    g = H[(H.AO > 0) | (H.GO > 0)].groupby(k)[["GO", "AO", "PA"]].sum().reset_index()
    g["gofb"], g["w_g"] = g.GO / g.AO.where(g.AO > 0), g.PA
    # speed
    H = H.assign(b1=H.H - H["2B"] - H["3B"] - H.HR)
    sp = H.groupby(k)[["SB", "CS", "b1", "BB", "HBP", "IBB", "2B", "3B"]].sum()
    sp["sb_att_rate"] = ((sp.SB + sp.CS) / (sp.b1 + sp.BB + sp.HBP - sp.IBB).where(lambda x: x > 0)).clip(upper=1)
    sp["sb_success"] = sp.SB / (sp.SB + sp.CS).where(lambda x: x > 0)
    sp["triple_rate"] = sp["3B"] / (sp["2B"] + sp["3B"]).where(lambda x: x > 0)
    sp = sp.reset_index()[k + ["sb_att_rate", "sb_success", "triple_rate"]]
    out = snap[k].copy()
    for A, cols, w in [(c, ["contact_rate", "swing_rate"], "w_c"),
                       (b, ["gb_rate", "fb_rate", "ld_rate", "pu_rate"], "w_b"), (g, ["gofb"], "w_g")]:
        out = out.merge(A[k + cols + [w]], on=k, how="left").merge(_blend(A, cols, w), on=k, how="left").drop(columns=w)
    out = out.merge(sp, on=k, how="left")
    # position mix at the highest level in s: games listing the position / games (strings lack per-position games, so a
    # player listed "SS/2B" counts all stint games for both; shares of different positions can sum above 1)
    hl = snap[k + ["highest_level"]].merge(S, left_on=k + ["highest_level"], right_on=k + ["level"])
    pm = hl.groupby(k)[["G", "pos_g_SS", "pos_g_CF", "pos_g_C"]].sum()
    for t in ("SS", "CF", "C"):
        pm[f"pos_share_{t}"] = (pm[f"pos_g_{t}"] / pm.G.where(pm.G > 0)).clip(upper=1)
    out = out.merge(pm.reset_index()[k + [f"pos_share_{t}" for t in ("SS", "CF", "C")]], on=k, how="left")
    # progression pace in games, through s (all levels incl. rookie ball)
    L = pd.concat([S[["player_id", "season", "level", "G", "PA"]], hist], ignore_index=True)  # Q17: 2000-04 history
    L = L.assign(o=L.level.map(ORD), G=L.G.fillna(0))
    cum = snap[k].merge(L[["player_id", "season", "o", "G", "PA"]], on="player_id", suffixes=("", "_l"))
    cum = cum[cum.season_l <= cum.season]
    top = cum.groupby(k).o.max().rename("top")
    first = cum[cum.season_l == cum.groupby(k).season_l.transform("min")].groupby(k).o.min().rename("first")
    cum = cum.join(top, on=k).join(first, on=k)
    pace = pd.DataFrame({"games_at_current_level": cum[cum.o == cum.top].groupby(k).G.sum(),
                         "below": cum[cum.o < cum.top].groupby(k).G.sum()})
    pace["below"] = pace.below.fillna(0)
    pace = pace.join(top).join(first)
    pace["ascent_pace"] = pace.below / (pace.top - pace["first"]).clip(lower=1)
    cur = cum[cum.season_l == cum.season]
    pace["levels_climbed_s"] = cur[cur.o > cur["first"]].groupby(k).o.nunique()
    pace["levels_climbed_s"] = pace.levels_climbed_s.fillna(0)
    prev = cum[cum.season_l == cum.season - 1].copy()
    ptop = prev.groupby(k).o.max().rename("ptop")
    prev = prev.join(ptop, on=k)
    ppa = prev[prev.o == prev.ptop].groupby(k).PA.sum().rename("ppa")
    pace = pace.join(ptop).join(ppa)
    pace["repeated_level"] = ((pace.top == pace.ptop) & (pace.ppa >= 200)).astype(float)
    out = out.merge(pace.reset_index()[k + ["games_at_current_level", "ascent_pace", "levels_climbed_s", "repeated_level"]],
                    on=k, how="left")
    # body: current values (Q15 look-ahead)
    out = out.merge(pl[["player_id", "height_in", "weight_lb"]], on="player_id", how="left")
    out["bmi"] = 703 * out.weight_lb / out.height_in ** 2
    return out


def build_transition(snap, fld, players, cutoff=2017):
    """P(MLB primary pos | MiLB primary pos, level_group) from stat-group s<=cutoff snapshots of players who reached MLB.
    Fit per model cutoff (backtest 2012, final 2017) so the backtest never sees holdout players' positions (v1.1)."""
    deb = players.set_index("player_id").mlb_debut_date.dt.year
    f = fld[fld.position != "P"].merge(deb.rename("dy"), left_on="player_id", right_index=True)
    f = f[(f.season >= f.dy) & (f.season <= f.dy + 2)]
    mlb_pos = f.groupby(["player_id", "position"]).games.sum().reset_index().sort_values(["player_id", "games"])
    mlb_pos = mlb_pos.groupby("player_id").position.last().rename("mlb_pos")  # no fielding rows -> absent -> DH
    t = snap[(snap.season <= cutoff) & snap.level_group.notna() & snap.reached_mlb & (snap.debut_year >= 2005)].copy()
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
    hist = pd.read_parquet(DATA / "milb_history.parquet")  # Q17: 2000-04 career history (not snapshots)
    hist = hist[hist.league_id != MEXICAN_LEAGUE][["player_id", "season", "level", "G", "PA"]]
    ps = pd.concat([S[["player_id", "season", "PA"]], hist[["player_id", "season", "PA"]]])
    ps = ps.groupby(["player_id", "season"]).PA.sum().reset_index().sort_values(["player_id", "season"])
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
    f15 = s15_features(S, snap, pl, hist).drop(columns=["player_id", "season"])
    f15[~stat.to_numpy()] = np.nan  # S15 features exist for the stat group only
    snap = pd.concat([snap, f15], axis=1)


    # labels
    snap = snap.merge(pl[["player_id", "full_name", "mlb_debut_date"]].rename(columns={"full_name": "name"}),
                      on="player_id", how="left")
    snap["debut_year"] = snap.mlb_debut_date.dt.year
    snap["reached_mlb"] = snap.debut_year.notna()
    # S16: already in MLB by the end of s (still rookie-eligible). Never a training row; scored with P(MLB) = 1.
    snap["debuted"] = snap.debut_year <= snap.season
    snap["eta_years"] = (snap.debut_year - snap.season).where(snap.reached_mlb & ~snap.debuted)  # >= 1 (A13)
    snap = snap.merge(pd.read_parquet(DATA / "war_target.parquet")[["player_id", "war_6yr"]], on="player_id", how="left")
    snap.loc[~snap.reached_mlb, "war_6yr"] = np.nan

    # transition matrix (A10) and positional features
    fld = pd.read_parquet(DATA / "mlb_fielding_games.parquet")
    tms = []
    for cutoff, suffix in ((2017, ""), (2012, "_bt")):  # final columns p_C...; backtest columns p_C_bt... (B6 swaps them)
        tm = build_transition(snap, fld, pl, cutoff).assign(cutoff=cutoff)
        tms.append(tm)
        wide = tm.pivot(index=["level_group", "milb_pos"], columns="mlb_pos", values="p")[POS9]
        fall = wide.xs("_ALL", level="milb_pos")  # milb positions never seen in train snapshots
        pm = snap[["level_group", "milb_pos"]].drop_duplicates().dropna()
        rows = [wide.loc[(lg, mp)] if (lg, mp) in wide.index else fall.loc[lg] for lg, mp in zip(pm.level_group, pm.milb_pos)]
        P = pd.DataFrame(rows, index=pd.MultiIndex.from_frame(pm))
        P["exp_pos_runs"] = P[POS9] @ pd.Series({k: POS_RUNS[k] for k in POS9})
        P = P.rename(columns={"C": "p_C", "SS": "p_SS", "CF": "p_CF"})[["p_C", "p_SS", "p_CF", "exp_pos_runs"]]
        P = P.add_suffix(suffix).reset_index()
        snap = snap.merge(P, on=["level_group", "milb_pos"], how="left")
    tm = pd.concat(tms, ignore_index=True)
    tm.to_parquet(DATA / "position_transition.parquet", index=False)

    # draft features (latest record on or before s; international = none)
    d = pd.read_parquet(DATA / "draft.parquet").dropna(subset=["player_id"])
    d = d.assign(player_id=d.player_id.astype(int), round_num=pd.to_numeric(d["round"], errors="coerce"))
    d = d.sort_values(["player_id", "draft_year"])[["player_id", "draft_year", "round_num", "pick_overall",
                                                    "signing_bonus"]]
    # latest draft record with draft_year <= s (a player drafted again later keeps his earlier record before then)
    dd = snap[["player_id", "season"]].merge(d.rename(columns={"draft_year": "dy"}), on="player_id")
    dd = dd[dd.dy <= dd.season].sort_values("dy").groupby(["player_id", "season"]).tail(1)
    snap = snap.merge(dd, on=["player_id", "season"], how="left")
    ok = snap.dy.notna()
    snap["international"] = ~ok  # means "no draft record (1990+) on or before s": international or undrafted (Q17)
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
    print(tm[(tm.cutoff == 2017) & (tm.level_group == "high") & tm.milb_pos.isin(["SS", "C", "CF"])]
          .pivot(index="milb_pos", columns="mlb_pos", values="p")[POS9].round(3))
    r = snap[snap.reached_mlb & (snap.split == "train_era")]
    print("train_era reached rows lacking war_6yr:", r.war_6yr.isna().sum(), "of", len(r),
          "| unique players:", r[r.war_6yr.isna()].player_id.nunique())


if __name__ == "__main__":
    main()
