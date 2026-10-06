"""B12 C9 selection (S15, C9, A12): which S15 feature groups earn a place, on train-era s <= 2012 stat rows only.

GroupKFold(5) by player_id. P(MLB): B6's LightGBM (early-stopped). EV = P(MLB) * WAR-hat, WAR-hat = ridge (A12 candidate)
fit on reached, non-censored, non-pre2005 rows of the training folds. Realized = war_6yr if reached else 0, scored on
non-censored, non-pre2005 rows. Keep a group if it beats baseline on log loss or ev Spearman without losing more than
0.002 log loss / 0.005 Spearman on the other. The 2013-2017 holdout is never touched. Writes data/b12_c9.json.
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import log_loss
from sklearn.model_selection import GroupKFold

from .b5_features import S15_GROUPS
from .b6_models import _lgb_cv, _linear, _predict, stat_X
from .common import DATA

LL_TOL, SP_TOL = 0.002, 0.005


def _X(df, cols):
    return stat_X(df, cols)


def evaluate(df, cols, wt):
    X, y, g = _X(df, cols), df.reached_mlb.astype(int).to_numpy(), df.player_id.to_numpy()
    p, _ = _lgb_cv("p_mlb", X, y, g)
    ok = (~df.player_id.map(wt.censored).fillna(False).astype(bool) & ~df.player_id.map(wt.pre2005).fillna(False).astype(bool)).to_numpy()
    train_w = ok & df.reached_mlb.to_numpy(bool)
    w, war = np.zeros(len(y)), df.war_6yr.to_numpy()
    for tr, te in GroupKFold(5).split(X, y, g):
        tr = tr[train_w[tr]]
        w[te] = _predict(_linear("war").fit(X.iloc[tr], war[tr]), X.iloc[te], "war")
    real = np.where(y == 1, np.nan_to_num(war), 0.0)
    return {"logloss": float(log_loss(y, p)), "ev_spearman": float(spearmanr((p * w)[ok], real[ok])[0])}


def main():
    f = pd.read_parquet(DATA / "features.parquet")
    df = f[(f.group == "stat") & (f.season <= 2012)].reset_index(drop=True)
    wt = pd.read_parquet(DATA / "war_target.parquet").set_index("player_id")
    res = {"baseline": evaluate(df, [], wt)}
    b = res["baseline"]
    print("baseline", b, flush=True)

    def verdict(r):
        dl, ds = b["logloss"] - r["logloss"], r["ev_spearman"] - b["ev_spearman"]  # positive = better
        r.update(d_logloss_gain=dl, d_spearman_gain=ds,
                 keep=bool((dl > 0 or ds > 0) and dl > -LL_TOL and ds > -SP_TOL))
        return r

    for name, cols in S15_GROUPS.items():
        res[name] = verdict({**evaluate(df, cols, wt), "features": cols})
        print(name, res[name], flush=True)
    kept_groups = [n for n in S15_GROUPS if res[n]["keep"]]
    kept = [c for n in kept_groups for c in S15_GROUPS[n]]
    if kept:
        res["all_kept"] = verdict({**evaluate(df, kept, wt), "features": kept})
        print("all_kept", res["all_kept"], flush=True)
    out = {"n_rows": len(df), "tolerances": {"logloss": LL_TOL, "spearman": SP_TOL}, "table": res,
           "kept_groups": kept_groups, "kept_features": kept}
    (DATA / "b12_c9.json").write_text(json.dumps(out, indent=1))
    print("kept groups:", kept_groups)


if __name__ == "__main__":
    main()
