"""B11: batted-ball layer (S13, S14, C8, D2, D11, Q11, Q13, Q14).

 1. data/bip.parquet: one row per tracked ball in play (launch_speed and launch_angle present), AAA and Low-A (FSL).
    All from Baseball Savant minors Statcast CSV, one cached parquet per day (D11, Q13); repo PBP not used (too slow).
 2. data/batted_ball.parquet (S13): player x season x level display metrics.
 3. Expected-outcome LightGBM per level group (aaa, a): P(out,1B,2B,3B,HR | EV, LA, spray), out-of-fold by batter.
 4. S14 blend of expected ISO/BABIP with park-neutral observed (B4 neutral_*), k fit on AAA 2022/2023 -> next season.
 5. C8 gate -> data/b11_c8.json. If it passes, rescore B6 final-fit predictions/drivers with adjusted inputs.
"""
import io
import json
import time

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from concurrent.futures import ThreadPoolExecutor

from sklearn.model_selection import GroupKFold

from . import b4_mle as b4
from . import b6_models as b6
from .common import DATA, RAW, _get, api_get

SAVANT = RAW / "savant"
SAVANT_URL = "https://baseballsavant.mlb.com/statcast-search-minors/csv"
SAVANT_START, SAVANT_END = "2021-04-01", "2026-09-30"
SPORT_LEVEL = {11: "aaa", 14: "a"}
CLASSES = ["out", "1B", "2B", "3B", "HR"]
BIP_COLS = ["batter", "season", "level", "game_pk", "home_team", "launch_speed", "launch_angle", "spray_angle", "stand",
            "outcome", "source"]
KEEP = ["batter", "game_pk", "game_date", "home_team", "stand", "launch_speed", "launch_angle", "hc_x", "hc_y", "des"]
MIN_TRACKED_EVAL = 50  # C8 samples need >= this many tracked BIP in the evaluated AAA season
K_GRID = [10, 25, 50, 100, 200, 400, 800, 1600, 3200, 6400, 12800, 1e5, 1e7]
TRAIN_SEASONS = (2022, 2023)  # k selection pairs (s -> s+1); 2024 -> 2025 is held out
BYTES = {"savant": 0}  # download volume


# ---------- outcome / spray ----------
EVENT = {"single": "1B", "double": "2B", "triple": "3B", "home_run": "HR"}


def spray(x, y, stand):
    """Degrees from the center-field line; pull side negative for both hands (LHB sign flipped). Standard Statcast
    centre (125.42, 198.27): atan((hc_x - 125.42) / (198.27 - hc_y))."""
    a = np.degrees(np.arctan2(x - 125.42, 198.27 - y))
    return np.where(stand == "L", -a, a)


def finish(d):
    d = d[d.launch_speed.notna() & d.launch_angle.notna()].copy()
    d = d[~d.des.fillna("").str.contains(r"\bbunt", regex=True) & ~d.bb_type.fillna("").str.contains("bunt")]
    d["outcome"] = d.events.map(EVENT).fillna("out")  # errors, FC, DP, SF all 'out'
    d["spray_angle"] = spray(d.hc_x, d.hc_y, d.stand)
    d["source"] = "savant"
    d["season"] = pd.to_datetime(d.game_date).dt.year
    return d


# ---------- Savant (D11, Q13) ----------
BBT = "fly%5C.%5C.ball%7Cground%5C.%5C.ball%7Cline%5C.%5C.drive%7Cpopup%7C"  # server-side balls-in-play filter


def pmap(fn, items):
    with ThreadPoolExecutor(4) as ex:  # architect: at most 4 concurrent requests
        return list(ex.map(fn, items))


def savant_day(day):
    f = SAVANT / f"{day}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    url = (f"{SAVANT_URL}?all=true&hfGT=R%7C&hfSea={day[:4]}%7C&player_type=batter&game_date_gt={day}&game_date_lt={day}"
           f"&type=details&minors=true&hfBBT={BBT}")
    r = _get(url)
    BYTES["savant"] += len(r.content)
    SAVANT.mkdir(parents=True, exist_ok=True)
    txt = r.content.decode("utf-8-sig")
    cols = KEEP + ["events", "bb_type", "type"]
    if not txt.strip():
        d = pd.DataFrame(columns=cols)
    else:
        d = pd.read_csv(io.StringIO(txt), low_memory=False)
        assert len(d) < 24000, f"Savant row cap hit on {day}"
        d = d[d.type == "X"][cols]
    d.to_parquet(f, index=False)
    time.sleep(0.2)
    return d


def game_levels(days):
    """game_pk -> level (aaa/a) from the Stats API schedule, monthly ranges, cached."""
    m = {}
    for ym in sorted({d[:7] for d in days}):
        start = f"{ym}-01"
        end = (pd.Timestamp(start) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        for sid, lv in SPORT_LEVEL.items():
            for dt in api_get("schedule", sportId=sid, startDate=start, endDate=end)["dates"]:
                for g in dt["games"]:
                    m[g["gamePk"]] = lv
    return m


def build_bip():
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(SAVANT_START, SAVANT_END) if 4 <= d.month <= 9]
    d = pd.concat([x for x in pmap(savant_day, days) if len(x)], ignore_index=True)
    d["level"] = d.game_pk.map(game_levels(days))
    print(f"savant BIP rows {len(d)}; dropped (game not AAA/Low-A in schedule) {d.level.isna().sum()}")
    bip = finish(d[d.level.notna()])
    bip["batter"] = bip.batter.astype(int)
    bip = bip.drop_duplicates(["game_pk", "batter", "game_date", "launch_speed", "launch_angle", "hc_x", "hc_y", "des"])
    bip = bip[BIP_COLS].sort_values(["season", "level", "batter"]).reset_index(drop=True)
    return bip, None


# ---------- S13: display metrics ----------
def barrel(ev, la):
    """Statcast barrel (MLB glossary): EV >= 98 and LA inside a window that is 26-30 degrees at 98 mph and widens
    ~1 degree low / ~1.1 degrees high per mph, to 8-50 at 116 mph and above (piecewise-linear fit of the published table)."""
    lo = np.maximum(26 - (ev - 98), 8)
    hi = np.minimum(30 + (20 / 18) * (ev - 98), 50)
    return (ev >= 98) & (la >= lo) & (la <= hi)


def batted_ball_table(bip):
    S = pd.read_parquet(DATA / "milb_player_seasons.parquet")
    S = S[S.level.isin(["aaa", "a"])].assign(inplay=lambda d: d.AB - d.SO + d.SF)  # in play incl. HR
    tot = S.groupby(["player_id", "season", "level"]).inplay.sum().rename("inplay_total").reset_index()
    b = bip.assign(hard=bip.launch_speed >= 95, sweet=bip.launch_angle.between(8, 32),
                   barrel=barrel(bip.launch_speed, bip.launch_angle))
    g = b.groupby(["batter", "season", "level"])
    out = pd.DataFrame({"n_bip_tracked": g.size(), "avg_ev": g.launch_speed.mean(), "ev90": g.launch_speed.quantile(0.9),
                        "hard_hit_pct": g.hard.mean(), "avg_la": g.launch_angle.mean(), "la_sd": g.launch_angle.std(),
                        "sweet_spot_pct": g.sweet.mean(), "barrel_pct": g.barrel.mean()}).reset_index()
    out = out.rename(columns={"batter": "player_id"}).merge(tot, on=["player_id", "season", "level"], how="left")
    out["share_bip_tracked"] = out.n_bip_tracked / out.inplay_total.where(out.inplay_total > 0)
    return out.drop(columns="inplay_total")


# ---------- expected outcomes ----------
def add_expected(bip):
    """Per-level multiclass LightGBM P(class | EV, LA, spray), out-of-fold by batter (every row scored by a model that
    never saw that batter, so player xStats are not in-sample)."""
    for c in CLASSES:
        bip["p_" + c] = np.nan
    y = bip.outcome.map({c: i for i, c in enumerate(CLASSES)}).to_numpy()
    X = bip[["launch_speed", "launch_angle", "spray_angle"]]
    for lv in ("aaa", "a"):
        idx = np.flatnonzero((bip.level == lv).to_numpy())
        P = np.zeros((len(idx), len(CLASSES)))
        for tr, te in GroupKFold(5).split(idx, groups=bip.batter.to_numpy()[idx]):
            m = LGBMClassifier(objective="multiclass", n_estimators=150, learning_rate=0.05, num_leaves=15,
                               min_child_samples=100, random_state=0, verbose=-1)
            m.fit(X.iloc[idx[tr]], y[idx[tr]])
            P[te] = m.predict_proba(X.iloc[idx[te]])
        bip.loc[bip.index[idx], ["p_" + c for c in CLASSES]] = P
    return bip


def player_expected(bip, obs):
    """x-stats per (player, season, level) and per-row tracked n. Formulas (all park-neutral by construction):
      xBABIP = sum(P1B+P2B+P3B) / sum(1-PHR)              (BABIP = (H-HR)/(BIP excl. HR), expected conditional on non-HR)
      xISO   = sum(P2B+2*P3B+3*PHR) / n_tracked * inplay / AB   (extra bases per tracked BIP, scaled by the player's actual
               balls in play incl. HR (= AB-SO+SF) over AB, i.e. his tracked-BIP share; ISO=(TB-H)/AB)"""
    g = bip.assign(hits_nonHR=bip.p_1B + bip.p_2B + bip.p_3B, nonHR=1 - bip.p_HR,
                   xb=bip.p_2B + 2 * bip.p_3B + 3 * bip.p_HR).groupby(["batter", "season", "level"])
    x = pd.DataFrame({"n_t": g.size(), "h": g.hits_nonHR.sum(), "nonHR": g.nonHR.sum(), "xb": g.xb.sum()}).reset_index()
    x = x.rename(columns={"batter": "player_id"})
    lv = obs[obs.level.isin(["aaa", "a"])].copy()
    lv["inplay"] = lv.BIP + lv.HR
    t = lv.groupby(["player_id", "season", "level"])[["inplay", "AB"]].sum().rename(columns=lambda c: c + "_lv").reset_index()
    x = x.merge(t, on=["player_id", "season", "level"])
    x["x_BABIP"] = x.h / x.nonHR
    x["x_ISO"] = x.xb / x.n_t * x.inplay_lv / x.AB_lv.where(x.AB_lv > 0)
    rows = lv.merge(x[["player_id", "season", "level", "n_t", "x_BABIP", "x_ISO", "inplay_lv"]],
                    on=["player_id", "season", "level"], how="left")
    rows["n_row"] = (rows.n_t * rows.inplay / rows.inplay_lv.where(rows.inplay_lv > 0)).fillna(0.0)
    return x, rows


COMP = {"ISO": ("neutral_ISO", "AB"), "BABIP": ("neutral_BABIP", "BIP")}


def adjust(rows, k):
    """S14: adj = w*x + (1-w)*observed_neutral, w = n/(n+k) on tracked BIP; untracked rows (n=0) unchanged."""
    out = rows.copy()
    for c, (col, _) in COMP.items():
        w = rows.n_row / (rows.n_row + k[c])
        out["adj_" + c] = np.where((rows.n_row > 0) & rows["x_" + c].notna() & rows[col].notna(),
                                   w * rows["x_" + c] + (1 - w) * rows[col], rows[col])
    return out


def wavg(d, keys, val, w):
    ok = d[val].notna() & (d[w] > 0)
    num = (d[val].where(ok, 0) * d[w].where(ok, 0)).groupby([d[k] for k in keys]).sum()
    den = d[w].where(ok, 0).groupby([d[k] for k in keys]).sum()
    return (num / den.where(den > 0)).rename(val)


def aaa_players(rows, k, valcols=None):
    """AAA player-season table: PA, tracked n, observed neutral ISO/BABIP and adjusted (AB / BIP weighted)."""
    a = adjust(rows[rows.level == "aaa"], k)
    keys = ["player_id", "season"]
    t = a.groupby(keys)[["PA", "n_row"]].sum()
    for c, (col, w) in COMP.items():
        t["obs_" + c] = wavg(a, keys, col, w)
        t["adj_" + c] = wavg(a, keys, "adj_" + c, w)
    return t.reset_index()


def year_ahead(rows, k, s):
    cur = aaa_players(rows, k)
    cur = cur[(cur.season == s) & (cur.PA >= 200) & (cur.n_row >= MIN_TRACKED_EVAL)]
    nxt = aaa_players(rows, k)
    nxt = nxt[(nxt.season == s + 1) & (nxt.PA >= 200)][["player_id", "obs_ISO", "obs_BABIP"]].rename(
        columns={"obs_ISO": "y_ISO", "obs_BABIP": "y_BABIP"})
    return cur.merge(nxt, on="player_id")


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def choose_k(rows):
    res, best = {}, {}
    for c in COMP:
        res[c] = {}
        for kk in K_GRID:
            r = []
            for s in TRAIN_SEASONS:
                d = year_ahead(rows, {"ISO": kk, "BABIP": kk}, s)
                d = d.dropna(subset=[f"adj_{c}", f"y_{c}"])
                r.append(((d[f"adj_{c}"] - d[f"y_{c}"]) ** 2))
            res[c][kk] = float(np.sqrt(pd.concat(r).mean()))
        best[c] = min(res[c], key=res[c].get)
    return best, res


def eval_year_ahead(rows, k, s):
    d = year_ahead(rows, k, s)
    out = {"n": int(len(d))}
    for c in COMP:
        e = d.dropna(subset=[f"adj_{c}", f"y_{c}"])
        out[c] = {"rmse_observed": rmse(e[f"obs_{c}"], e[f"y_{c}"]), "rmse_adjusted": rmse(e[f"adj_{c}"], e[f"y_{c}"])}
    return out


# ---------- MLE recompute (reuses B4) ----------
def adjusted_mle(obs, rows, k, base):
    """Replace neutral_ISO/BABIP of tracked rows by the S14-adjusted values and rerun B4 factors (not refit) ->
    mle_/reg_. Only tracked rows take the recomputed values; all other rows keep B4's originals."""
    fac = pd.read_parquet(DATA / "translation_factors.parquet")
    a = adjust(rows, k)
    key = ["player_id", "season", "level", "league_id"]
    m = obs.merge(a[key + ["adj_ISO", "adj_BABIP", "n_row"]], on=key, how="left")
    trk = m.n_row.fillna(0) > 0
    m.loc[trk, "neutral_ISO"] = m.loc[trk, "adj_ISO"]
    m.loc[trk, "neutral_BABIP"] = m.loc[trk, "adj_BABIP"]
    new = b4.regress(b4.apply_mle(m.drop(columns=["adj_ISO", "adj_BABIP", "n_row"]), fac))
    assert new.shape[0] == len(obs)
    return new, trk


def eval_translation(base, adj_rows, mlb):
    """C8(b): AAA s (>=200 PA, >= MIN_TRACKED_EVAL tracked BIP) -> MLB s+1 (>=150 PA) neutral ISO/BABIP vs reg_ MLE."""
    keys = ["player_id", "season"]
    out = {}
    pa = base[base.level == "aaa"].groupby(keys).PA.sum().rename("PA").reset_index()
    ntr = adj_rows[adj_rows.level == "aaa"].groupby(keys).n_row.sum().reset_index()
    t = pa.merge(ntr, on=keys)
    for c, (_, w) in COMP.items():
        for nm, d in (("base", base), ("adj", adj_rows)):
            d = d[d.level == "aaa"]
            t = t.merge(wavg(d, keys, f"reg_{c}", w).rename(f"{nm}_{c}").reset_index(), on=keys, how="left")
    t = t[(t.PA >= 200) & (t.n_row >= MIN_TRACKED_EVAL) & t.season.between(2022, 2025)]
    y = mlb[(mlb.PA >= 150)][keys + ["neutral_ISO", "neutral_BABIP"]].assign(season=lambda d: d.season - 1)
    t = t.merge(y, on=keys)
    out["n"] = int(len(t))
    for c in COMP:
        e = t.dropna(subset=[f"base_{c}", f"adj_{c}", f"neutral_{c}"])
        out[c] = {"rmse_baseline": rmse(e[f"base_{c}"], e[f"neutral_{c}"]), "rmse_adjusted": rmse(e[f"adj_{c}"], e[f"neutral_{c}"])}
    return out


# ---------- rescoring ----------
def blend_delta(ps, keys):
    """B5's Marcel blend (weights 3*PA_s, 2*PA_{s-1}, s-1 dropped when absent) and delta for ISO/BABIP from a
    player-season frame (PA, reg_*) -- identical formulas to pipeline/b5_features.py."""
    rc = [f"reg_{c}" for c in ("K", "BB", "ISO", "BABIP")]
    mc = ps[["player_id", "season", "PA"] + rc]
    p = mc.assign(season=mc.season + 1).rename(columns={c: "p_" + c for c in rc + ["PA"]})
    d = keys.merge(mc, on=["player_id", "season"], how="left").merge(p, on=["player_id", "season"], how="left")
    out = d[["player_id", "season"]].copy()
    for r in ("ISO", "BABIP"):
        x0, x1, w0, w1 = d[f"reg_{r}"], d[f"p_reg_{r}"], 3 * d.PA, 2 * d.p_PA
        w1 = w1.where(x1.notna(), 0)
        out[f"reg_{r}"] = x0
        out[f"blend_{r}"] = (x0 * w0 + x1.fillna(0) * w1) / (w0 + w1)
        out[f"delta_{r}"] = x0 - x1
    return out


FEAT = [f"{p}_{r}" for p in ("reg", "blend", "delta") for r in ("ISO", "BABIP")]
PRED_COLS = ["p_mlb", "war_mean", "war_q10", "war_q50", "war_q90", "eta_mean", "eta_q10", "eta_q90", "ev_war"]
BASE_COLS = ["p_mlb", "war_mean", "war_q10", "war_q50", "war_q90", "eta_mean", "ev_war"]


def rescore(m_adj_rows, passed):
    """Rebuild reg/blend/delta ISO+BABIP for stat rows from adjusted player-season MLEs, re-predict with the B6 final
    models (no refit), write predictions_final / drivers_final (Q14: s14_applied)."""
    f = pd.read_parquet(DATA / "features.parquet")
    st = f[(f.group == "stat") & (f.split != "train_era")].reset_index(drop=True)
    pred = pd.read_parquet(DATA / "predictions.parquet").query("fit == 'final'").reset_index(drop=True)
    drv = pd.read_parquet(DATA / "drivers.parquet").query("fit == 'final'").reset_index(drop=True)
    mod = joblib.load(b6.MODELS / "stat_final.joblib")
    keys = st[["player_id", "season"]]
    # sanity: B4 roll-up + blend formula reproduces features exactly on unadjusted data
    base_ps = pd.read_parquet(DATA / "mle_player_season.parquet")
    chk = blend_delta(base_ps, keys)
    for c in FEAT:
        assert np.allclose(chk[c], st[c], atol=1e-9, equal_nan=True), f"feature rebuild mismatch {c}"
    new = st.copy()
    if passed:
        ps = b4.player_season(m_adj_rows)
        adj = blend_delta(ps, keys)
        for c in FEAT:
            new[c] = adj[c].to_numpy()
    changed = np.zeros(len(st), bool)
    for c in FEAT:
        changed |= ~np.isclose(new[c], st[c], atol=1e-9, equal_nan=True)
    st_applied = pd.Series(changed, index=pd.MultiIndex.from_frame(keys))
    # predictions
    p0 = predict_cols(mod, st)
    p1 = predict_cols(mod, new) if changed.any() else p0
    cmp = pred.merge(p0.assign(player_id=st.player_id, season=st.season), on=["player_id", "season"], suffixes=("", "_re"))
    assert len(cmp) == (pred.group == "stat").sum() and np.allclose(cmp.p_mlb, cmp.p_mlb_re, atol=1e-9) and \
        np.allclose(cmp.ev_war, cmp.ev_war_re, atol=1e-9), "re-prediction does not reproduce predictions.parquet"
    p1 = p1.assign(player_id=st.player_id.to_numpy(), season=st.season.to_numpy(), s14_applied=changed)[
        ["player_id", "season", "s14_applied"] + PRED_COLS]
    out = pred.merge(p1, on=["player_id", "season"], how="left", suffixes=("", "_new"))
    app = out.s14_applied.fillna(False).astype(bool)
    for c in BASE_COLS:
        out[c + "_base"] = np.where(app, out[c], np.nan)
    for c in PRED_COLS:
        out[c] = np.where(app, out[c + "_new"], out[c])
    out = out.drop(columns=[c + "_new" for c in PRED_COLS]).assign(s14_applied=app)
    out["fit"] = "final"
    # drivers (2026 score rows)
    dsel = st.merge(drv[["player_id", "season"]].drop_duplicates(), on=["player_id", "season"])
    dnew = new.merge(dsel[["player_id", "season"]], on=["player_id", "season"])
    dn = pd.concat([b6.drivers(mod, dnew, t) for t in ("p_mlb", "war")], ignore_index=True).assign(fit="final")
    dn = dn.merge(drv[["player_id", "season", "target", "rank", "feature", "feature_value", "contribution"]]
                  .rename(columns={"feature": "feature_base", "feature_value": "feature_value_base", "contribution": "contribution_base"}),
                  on=["player_id", "season", "target", "rank"], how="left")
    da = st_applied.reindex(pd.MultiIndex.from_frame(dn[["player_id", "season"]])).to_numpy()
    dn["s14_applied"] = da.astype(bool)
    for c in ("feature_base", "feature_value_base", "contribution_base"):
        dn.loc[~dn.s14_applied, c] = np.nan
    return out, dn


def predict_cols(mod, df):
    return b6.predict_stat(mod, df).reset_index(drop=True)


def main():
    bip, agree = build_bip()
    print(bip.groupby(["level", "season"]).size().unstack("level"))
    print("download bytes", BYTES)
    bip = add_expected(bip)
    bip.to_parquet(DATA / "bip.parquet", index=False)
    batted_ball_table(bip).to_parquet(DATA / "batted_ball.parquet", index=False)

    obs = b4.prep_milb()
    obs = obs.merge(pd.read_parquet(DATA / "mle.parquet")[["player_id", "season", "level", "league_id", "reg_ISO", "reg_BABIP",
                                                           "reg_K", "reg_BB", "mle_ISO", "mle_BABIP", "mle_K", "mle_BB"]],
                    on=["player_id", "season", "level", "league_id"], validate="1:1")
    x, rows = player_expected(bip, obs)
    k, grid = choose_k(rows)
    print("chosen k", k)
    kd = {c: float(v) for c, v in k.items()}
    res = {"k": kd, "k_grid_rmse": {c: {str(a): b for a, b in g.items()} for c, g in grid.items()},
           "k_train_pairs": [f"{s}->{s + 1}" for s in TRAIN_SEASONS], "min_tracked_bip": MIN_TRACKED_EVAL,
           "sources": {"savant": [SAVANT_START, SAVANT_END], "download_bytes": BYTES}}
    res["a"] = {f"{s}->{s + 1}": eval_year_ahead(rows, kd, s) for s in (2023, 2024, 2025)}
    res["a_heldout"] = "2024->2025"
    held = res["a"]["2024->2025"]
    res["a_pass"] = all(held[c]["rmse_adjusted"] < held[c]["rmse_observed"] for c in COMP)

    new, trk = adjusted_mle(obs.drop(columns=["reg_ISO", "reg_BABIP", "reg_K", "reg_BB", "mle_ISO", "mle_BABIP", "mle_K", "mle_BB"]),
                            rows, kd, obs)
    key = ["player_id", "season", "level", "league_id"]
    # rows frame carrying baseline and adjusted reg_ (adjusted only where tracked)
    mle0 = pd.read_parquet(DATA / "mle.parquet")
    for c in ("reg_ISO", "reg_BABIP", "mle_ISO", "mle_BABIP"):
        new[c + "_adj"] = new[c]
    ma = mle0.merge(new[key + [c + "_adj" for c in ("reg_ISO", "reg_BABIP", "mle_ISO", "mle_BABIP")]], on=key, how="left")
    tr = rows[key + ["n_row"]]
    ma = ma.merge(tr, on=key, how="left").assign(n_row=lambda d: d.n_row.fillna(0))
    for c in ("reg_ISO", "reg_BABIP", "mle_ISO", "mle_BABIP"):
        ma["b_" + c] = ma[c]
        ma[c] = np.where(ma.n_row > 0, ma[c + "_adj"], ma[c])
    adj_rows, base_rows = ma, mle0.merge(tr, on=key, how="left")
    mlb = b4.prep_mlb()
    bt = adj_rows.assign(**{c: adj_rows["b_" + c] for c in ("reg_ISO", "reg_BABIP")})
    res["b"] = eval_translation(bt, adj_rows, mlb)
    res["b_pass"] = all(res["b"][c]["rmse_adjusted"] <= res["b"][c]["rmse_baseline"] for c in COMP)
    res["s14_pass"] = bool(res["a_pass"] and res["b_pass"])
    (DATA / "b11_c8.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k_: v for k_, v in res.items() if k_ not in ("k_grid_rmse",)}, indent=1))

    ma_ps = ma.drop(columns=[c for c in ma.columns if c.endswith("_adj") or c.startswith("b_")])
    pf, dfinal = rescore(ma_ps, res["s14_pass"])
    pf.to_parquet(DATA / "predictions_final.parquet", index=False)
    dfinal.to_parquet(DATA / "drivers_final.parquet", index=False)
    ch = pf[pf.s14_applied].assign(d_ev_war=lambda d: d.ev_war - d.ev_war_base)
    print(f"s14_applied rows {int(pf.s14_applied.sum())} of {len(pf)}")
    print(ch.reindex(ch.d_ev_war.abs().sort_values(ascending=False).index)[
        ["player_id", "season", "ev_war_base", "ev_war", "d_ev_war"]].head(10).to_string())


if __name__ == "__main__":
    main()
